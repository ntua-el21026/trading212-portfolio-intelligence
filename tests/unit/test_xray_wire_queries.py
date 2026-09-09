"""Closed X-ray selectors reject cross-view inputs and preserve the MCP surface."""

from typing import Any

import pytest
from pydantic import ValidationError
from trading212_api_contracts import xray as wire

from tests.unit.analytics.source_factories import uid

pytestmark = pytest.mark.unit


def request() -> dict[str, Any]:
    return {
        "snapshot_id": uid(1),
        "source_cutoff_at": "2026-09-01T12:00:00Z",
        "reporting_currency": "EUR",
    }


@pytest.mark.parametrize("selector", [True, False, 0, 1.0, "01", "1.0", "-1", "101", "1000"])
def test_page_rejects_noncanonical_or_out_of_bounds_integer_selector(selector: Any) -> None:
    with pytest.raises(ValidationError):
        wire.XrayEffectiveExposureQuery.model_validate({**request(), "limit": selector})


@pytest.mark.parametrize("selector", [0, 1, "0", "1", "yes", "False"])
def test_normalization_does_not_coerce_ambiguous_boolean_selector(selector: Any) -> None:
    with pytest.raises(ValidationError):
        wire.XrayEffectiveExposureQuery.model_validate(
            {**request(), "normalized_known_only": selector}
        )


@pytest.mark.parametrize(
    "selectors",
    [
        {"view": "held_funds", "dimension": "company"},
        {"view": "held_funds", "normalized_known_only": False},
        {"view": "held_funds", "exposure_id": uid(8)},
        {"view": "exposures", "exposure_id": uid(8)},
        {"view": "paths"},
        {"view": "mcp_top_pair"},
    ],
)
def test_exposure_views_reject_wrong_branch_fields_or_missing_run_pin(
    selectors: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        wire.XrayEffectiveExposureQuery.model_validate({**request(), **selectors})


def test_valid_path_and_held_fund_queries_preserve_distinct_selectors() -> None:
    value = wire.XrayEffectiveExposureQuery.model_validate(
        {
            **request(),
            "view": "paths",
            "run_id": uid(2),
            "normalized_known_only": "false",
            "limit": "1",
        }
    )
    assert value.normalized_known_only is False and value.limit == 1
    assert value.run_id == uid(2)
    continued = wire.XrayEffectiveExposureQuery.model_validate(
        {**request(), "view": "paths", "cursor": "opaque_cursor"}
    )
    assert continued.cursor == "opaque_cursor"
    discovery = wire.XrayEffectiveExposureQuery.model_validate({**request(), "view": "held_funds"})
    assert discovery.dimension is None and discovery.normalized_known_only is None


@pytest.mark.parametrize(
    "selectors",
    [
        {"fund_ids": [uid(1), uid(1)]},
        {"fund_ids": [uid(1)]},
        {"fund_ids": [uid(i) for i in range(1, 34)]},
        {"fund_ids": uid(1) + "," + uid(2)},
        {"fund_ids": [uid(1), uid(2)], "left_fund_id": uid(1)},
        {
            "fund_ids": [uid(1), uid(2)],
            "view": "common_entities",
            "left_fund_id": uid(1),
            "right_fund_id": uid(2),
        },
        {
            "fund_ids": [uid(1), uid(2)],
            "view": "common_entities",
            "left_fund_id": uid(1),
            "right_fund_id": uid(3),
            "run_id": uid(5),
        },
    ],
)
def test_overlap_requires_a_bounded_unique_set_and_one_pinned_member_pair(
    selectors: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        wire.XrayEtfOverlapQuery.model_validate({**request(), **selectors})


@pytest.mark.parametrize("selector", [{"account_id": uid(1)}, {"run_id": uid(2)}])
def test_dependent_source_reads_require_both_account_and_run(selector: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        wire.XrayConstituentSnapshotQuery.model_validate(selector)
    assert wire.XrayConstituentSnapshotQuery.model_validate({}).account_id is None


@pytest.mark.parametrize(
    "extra", ["reporting_currency", "run_id", "view", "cursor", "limit", "provider"]
)
def test_mcp_overlap_has_no_currency_replay_page_or_provider_capability(extra: str) -> None:
    data = request()
    data.pop("reporting_currency")
    data.update(left_fund_id=uid(2), right_fund_id=uid(3), top_n="50")
    assert wire.XrayMcpOverlapQuery.model_validate(data).top_n == 50
    with pytest.raises(ValidationError):
        wire.XrayMcpOverlapQuery.model_validate({**data, extra: "rejected"})
