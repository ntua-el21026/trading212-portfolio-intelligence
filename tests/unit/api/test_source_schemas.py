"""Exact source bounds, raw-level distinctions and private benchmark input shapes."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError
from trading212_api.source_schemas import benchmark_content, source_status_query
from trading212_api_contracts import sources as wire
from trading212_domain.errors import DomainError
from trading212_domain.sources import normalize_benchmark_content

SOURCE = "19751815-c671-47c4-a42c-1e619a037234"
BODY: dict[str, Any] = {
    "name": "Synthetic benchmark",
    "content": {
        "reporting_currency": "EUR",
        "effective_at": "2026-09-07T12:00:00Z",
        "return_basis": "raw_close",
        "calendar_id": "weekday",
        "calendar_version": "v1",
        "rebalance_rule": "buy_and_hold",
        "components": [{"source_id": SOURCE, "weight": "1"}],
    },
}


@pytest.mark.parametrize(
    "weight",
    [1, 1.0, True, None, "1e0", "01", "NaN", "Infinity", "-0.1", "1.1", "0." + "1" * 19, "1" * 21],
)
def test_source_weights_are_exact_bounded_financial_strings(weight: object) -> None:
    body = copy.deepcopy(BODY)
    body["content"]["components"][0]["weight"] = weight
    with pytest.raises(ValidationError):
        wire.CreateBenchmarkDefinitionRequest.model_validate(body)


@pytest.mark.parametrize("location", ["root", "content", "component"])
def test_unknown_nested_source_fields_are_not_reflected(location: str) -> None:
    body = copy.deepcopy(BODY)
    node = {
        "root": body,
        "content": body["content"],
        "component": body["content"]["components"][0],
    }[location]
    node["source-canary-unknown-field"] = "source-canary-private-value"
    with pytest.raises(ValidationError) as error:
        wire.CreateBenchmarkDefinitionRequest.model_validate(body)
    assert "source-canary" not in str(error.value)


def test_source_period_is_inclusive_bounded_and_preserves_explicit_cutoff() -> None:
    value = wire.SourceStatusQuery.model_validate(
        {
            "start": "2020-01-01",
            "end": "2030-01-08",
            "source_cutoff_at": "2026-09-07T15:00:00+03:00",
        }
    )
    query = source_status_query(value)
    assert query.period is not None and (query.period.end - query.period.start).days == 3660
    assert query.source_cutoff_at is not None and query.source_cutoff_at.hour == 12
    default = source_status_query(wire.SourceStatusQuery())
    assert default.period is None and default.source_cutoff_at is None
    assert default.limit == 25 and default.sort == "source_key_asc"
    for fields in (
        {"start": "2020-01-01"},
        {"end": "2020-01-01"},
        {"start": "2020-01-01", "end": "2030-01-09"},
        {"start": "2026-09-08", "end": "2026-09-07"},
        {"start": 1, "end": 2},
    ):
        with pytest.raises(ValidationError):
            wire.SourceStatusQuery.model_validate(fields)


def test_benchmark_normalization_is_an_explicit_command_and_never_a_wire_coercion() -> None:
    body = copy.deepcopy(BODY)
    body["content"]["components"][0]["weight"] = "0.9999999999995"
    value = wire.CreateBenchmarkDefinitionRequest.model_validate(body)
    content = benchmark_content(value.content)
    assert str(content.components[0].weight) == "0.9999999999995"
    with pytest.raises(DomainError, match="weights must sum"):
        normalize_benchmark_content(content)
    result = normalize_benchmark_content(content, normalize=True)
    assert str(result.content.components[0].weight) == "1.000000000000000000"
    assert len(result.adjustments) == 1
    body["normalize"] = "true"
    with pytest.raises(ValidationError):
        wire.CreateBenchmarkDefinitionRequest.model_validate(body)


@pytest.mark.parametrize(
    "fields",
    [
        {"base": "EUR"},
        {"quote": "USD"},
        {"provider_id": "https://untrusted.invalid"},
        {"limit": 101},
        {"sort": "rate_desc"},
    ],
)
def test_fx_status_filters_are_paired_and_closed(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        wire.FxSourceStatusQuery.model_validate(fields)


def test_available_observation_is_not_missing_or_fabricated_zero() -> None:
    item = {
        "session_date": "2026-09-07",
        "effective_at": "2026-09-07T12:00:00Z",
        "level": "0.000000000000000001",
    }
    assert wire.BenchmarkObservation.model_validate(item).level == item["level"]
    for changes in ({"level": None}, {"level": "0"}, {"state": "missing"}):
        with pytest.raises(ValidationError):
            wire.BenchmarkObservation.model_validate({**item, **changes})
    missing = wire.BenchmarkObservation.model_validate({**item, "level": None, "state": "missing"})
    assert missing.level is None


def test_source_page_and_benchmark_components_cannot_truncate_or_repeat() -> None:
    with pytest.raises(ValidationError):
        wire.SourcePage[wire.BenchmarkObservation].model_validate(
            {"items": [], "next_cursor": None, "total": 0, "limit": 101}
        )
    body = copy.deepcopy(BODY)
    body["content"]["components"] *= 2
    with pytest.raises(ValidationError):
        wire.CreateBenchmarkDefinitionRequest.model_validate(body)


@pytest.mark.parametrize("value", [2**63 - 1, "9223372036854775808", "01", "-1", "1.5"])
def test_wire_revision_order_is_an_exact_nonnegative_integer_string(value: object) -> None:
    from pydantic import TypeAdapter

    with pytest.raises(ValidationError):
        TypeAdapter(wire.SourceRevisionOrder).validate_python(value)


@pytest.mark.parametrize("state", ["fresh", "stale"])
def test_known_freshness_cannot_fabricate_missing_policy_or_source_time(state: str) -> None:
    with pytest.raises(ValidationError):
        wire.SourceFreshness.model_validate(
            {"state": state, "policy_version": None, "reference_at": None, "max_age_seconds": None}
        )


def test_gap_preview_never_claims_more_observations_than_the_retained_coverage() -> None:
    with pytest.raises(ValidationError):
        wire.SourceCoverage.model_validate(
            {
                "expected_count": 1,
                "available_count": 1,
                "gaps": [{"session_date": "2026-09-07", "reason": "missing_session"}],
                "gap_count": 1,
                "gaps_truncated": False,
                "quality": "partial",
            }
        )
