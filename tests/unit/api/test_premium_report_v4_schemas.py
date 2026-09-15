"""Only explicit profile four admits projection clocks and the full saved proof."""

import json
from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError
from trading212_api_contracts import premium_reports as v2
from trading212_api_contracts import premium_reports_v3 as v3
from trading212_api_contracts import premium_reports_v4 as wire
from trading212_domain.report_manifest_v4 import (
    encode_report_manifest_v4,
    encode_report_selection_v4,
)
from trading212_domain.report_projection_schema import PROJECTION_TABLE_COLUMNS

from tests.unit.api.projection_report_profile_factories import (
    PROFILE,
    body_v4,
    manifest_v4,
    status_v4,
)

pytestmark = pytest.mark.unit


def test_complete_saved_domain_manifest_has_exact_profile_four_wire_parity() -> None:
    manifest = manifest_v4()
    payload = encode_report_manifest_v4(manifest)
    raw: dict[str, Any] = json.loads(payload)
    parsed = wire.PremiumReportManifestV4.model_validate_json(payload)
    assert parsed.model_dump(mode="json") == raw
    request = wire.GeneratePremiumReportRequestV4.model_validate_json(
        encode_report_selection_v4(manifest.document.selection)
    )
    assert request.profile_version == PROFILE and request.premium_run.family == "projection"
    assert (
        parsed.document.premium_binding.numerical_input_digest
        != parsed.document.premium_binding.capture_digest
    )
    assert parsed.document.premium_binding.observed is None
    contexts = [item for item in parsed.contexts if item.family == "projection"]
    assert contexts and all(
        item.valuation_at is None and item.source_cutoff_at is None for item in contexts
    )
    assert (
        parsed.document.valuation_at is not None
        and parsed.document.selection.source_cutoff_at is not None
    )
    assert {key.value for key in PROJECTION_TABLE_COLUMNS} <= {
        item.table for item in parsed.document.tables
    }
    for old in (v2.PremiumReportManifest, v3.PremiumReportManifestV3):
        with pytest.raises(ValidationError):
            old.model_validate(raw)


@pytest.mark.parametrize(
    "change",
    [
        {"profile_version": "report_sections_v3"},
        {"profile_version": None},
        {"premium_run": {"family": "risk", "run_id": "00000000-0000-4000-8000-000000000001"}},
        {"premium_run": {"family": "projection", "run_id": "latest"}},
        {"risk_run_id": "00000000-0000-4000-8000-000000000001"},
        {"premium_runs": []},
        {"sections": ["overview", "allocation", "quality", "projection", "scenario"]},
        {"sections": ["overview", "allocation", "quality", "goal"]},
        {"sections": ["overview", "allocation", "quality", "projection", "projection"]},
        {"source_cutoff_at": None},
        {"ttl_days": 31},
        {"ttl_days": True},
        {"coefficients": ["0"]},
    ],
)
def test_request_cannot_silently_infer_profile_clock_or_calibration(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        wire.GeneratePremiumReportRequestV4.model_validate({**body_v4(), **change})


@pytest.mark.parametrize(
    "mutation",
    [
        "snapshot",
        "currency",
        "root",
        "clock",
        "table",
        "count",
        "family",
        "binding",
        "variant_bool",
    ],
)
def test_complete_retained_proof_cannot_change_its_declared_identity(mutation: str) -> None:
    value = json.loads(encode_report_manifest_v4(manifest_v4()))
    pin = value["document"]["premium_binding"]
    if mutation == "snapshot":
        pin["report_context"]["snapshot_id"] = "00000000-0000-4000-8000-000000000099"
    elif mutation == "currency":
        pin["reporting_currency"] = "USD"
    elif mutation == "root":
        pin["root_id"] = "00000000-0000-4000-8000-000000000099"
    elif mutation == "clock":
        next(item for item in value["contexts"] if item["family"] == "projection")[
            "valuation_at"
        ] = value["document"]["valuation_at"]
    elif mutation == "table":
        value["document"]["tables"] = [
            item for item in value["document"]["tables"] if item["table"] != "projection_points_v1"
        ]
    elif mutation == "count":
        next(
            item for item in value["document"]["tables"] if item["table"] == "projection_points_v1"
        )["row_count"] -= 1
    elif mutation == "family":
        next(item for item in value["contexts"] if item["family"] == "projection")["family"] = (
            "snapshot"
        )
    elif mutation == "binding":
        value["bindings"] = [item for item in value["bindings"] if item["family"] != "projection"]
    else:
        pin["variant_count"] = True
    with pytest.raises(ValidationError):
        wire.PremiumReportManifestV4.model_validate(value)


def test_empty_and_expired_responses_still_require_the_explicit_four_marker() -> None:
    page: dict[str, Any] = {"items": [], "next_cursor": None, "limit": 25, "total": 0}
    wire.PremiumReportPageV4.model_validate({**page, "profile_version": PROFILE})
    status = status_v4()
    status.update(state="expired", context=None)
    wire.PremiumReportJobStatusV4.model_validate({**status, "profile_version": PROFILE})
    for marker in (None, "report_sections_v2", "report_sections_v3"):
        for cls, value in (
            (wire.PremiumReportPageV4, page),
            (wire.PremiumReportJobStatusV4, status),
        ):
            supplied = deepcopy(value)
            if marker is not None:
                supplied["profile_version"] = marker
            with pytest.raises(ValidationError):
                cls.model_validate(supplied)


def test_query_default_and_profile_body_matching_remain_closed() -> None:
    assert wire.premium_report_profile_from_query([]) == "report_sections_v2"
    request = wire.GeneratePremiumReportRequestV4.model_validate(body_v4())
    wire.validate_premium_request_profile(PROFILE, request)
    for profile in ("report_sections_v2", "report_sections_v3"):
        with pytest.raises(ValueError):
            wire.validate_premium_request_profile(profile, request)
    for selectors in (
        [("profile", PROFILE), ("profile", PROFILE)],
        [("profile", "report_sections_v5")],
    ):
        with pytest.raises(ValueError):
            wire.premium_report_profile_from_query(selectors)
