"""Finite intelligence quality projections from canonical results."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from typing import TypedDict, get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError
from trading212_analytics import historical as calculate
from trading212_analytics.planning import calculate_drift
from trading212_analytics.xray import calculate_xray
from trading212_api_contracts import intelligence_quality as wire
from trading212_application import intelligence_quality as q
from trading212_application.sources import SourceFreshnessState
from trading212_application.views import Availability, ViewQuality
from trading212_domain import historical_results as hr
from trading212_domain.serialization import canonical_json
from trading212_domain.xray_codec import encode_xray_component
from trading212_persistence.intelligence_quality_codec import _Reader, status_document
from trading212_persistence.intelligence_quality_projection import (
    empty_metrics,
    metric_row,
    overlay_sources,
)
from trading212_persistence.intelligence_quality_sources import source_freshness

from tests.unit.analytics.historical_factories import fixture as historical_input
from tests.unit.analytics.planning_factories import planning_input
from tests.unit.analytics.xray_factories import fixture as xray_input

HISTORY: tuple[tuple[q.IntelligenceKind, Callable[[], hr.HistoricalCalculation]], ...] = (
    (
        q.IntelligenceKind.PERFORMANCE,
        lambda: calculate.calculate_performance(
            historical_input(), options=hr.PerformanceOptions()
        ),
    ),
    (
        q.IntelligenceKind.BENCHMARK,
        lambda: calculate.calculate_benchmark_comparison(
            historical_input(), options=hr.ComparisonOptions()
        ),
    ),
    (
        q.IntelligenceKind.INCOME,
        lambda: calculate.calculate_income(historical_input(), options=hr.IncomeOptions()),
    ),
    (
        q.IntelligenceKind.ATTRIBUTION,
        lambda: calculate.calculate_attribution(
            historical_input(), options=hr.AttributionOptions()
        ),
    ),
    (
        q.IntelligenceKind.CASH_FLOW,
        lambda: calculate.calculate_cash_flows(historical_input(), options=hr.CashFlowOptions()),
    ),
)


class QueryOptions(TypedDict, total=False):
    analytics_kind: q.IntelligenceKind
    cursor: str | None
    limit: int


@pytest.mark.parametrize(("kind", "calculator"), HISTORY)
def test_status_parser_uses_real_native_result_and_keeps_every_metric(
    kind: q.IntelligenceKind, calculator: Callable[[], hr.HistoricalCalculation]
) -> None:
    result = calculator()
    actual = status_document(canonical_json(result).encode(), kind)
    assert actual.account_id == result.context.account_id
    assert actual.input_digest == result.context.input_digest
    assert tuple(row.key for row in actual.metrics) == tuple(
        field.name for field in fields(result.summary)
    )
    for row in actual.metrics:
        native = getattr(result.summary, row.key)
        basis = native if hasattr(native, "availability") else result.context
        assert row.quality.value == basis.quality.value
        assert row.availability.value == (
            "unavailable" if basis.availability.value == "failed" else basis.availability.value
        )
        assert "value" not in {field.name for field in fields(row)}


@pytest.mark.parametrize("kind", (q.IntelligenceKind.ACTUAL_VS_TARGET, q.IntelligenceKind.DRIFT))
def test_planning_status_inherits_real_context_without_expanding_rows(
    kind: q.IntelligenceKind,
) -> None:
    result = calculate_drift(planning_input())
    actual = status_document(canonical_json(result).encode(), kind)
    assert tuple(row.key for row in actual.metrics) == tuple(
        field.name for field in fields(result.totals)
    )
    assert all(row.basis == "result_context" for row in actual.metrics)


def test_xray_normalized_component_preserves_metric_and_inherited_status() -> None:
    summary = calculate_xray(xray_input()).portfolio_summary
    actual = status_document(encode_xray_component(summary), q.IntelligenceKind.XRAY)
    assert tuple(row.key for row in actual.metrics) == tuple(
        field.name for field in fields(summary)
    )
    assert (
        next(row for row in actual.metrics if row.key == "total").quality.value
        == summary.total.quality.value
    )
    assert next(row for row in actual.metrics if row.key == "thresholds").basis == "result_context"


def test_protected_activity_and_source_values_are_never_decoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = calculate.calculate_performance(historical_input(), options=hr.PerformanceOptions())
    payload = json.loads(canonical_json(result))
    canary = "protected-source-or-activity-id"
    payload["context"]["sources"] = [{"id": canary} for _ in range(200)]
    seen: list[str] = []
    original = _Reader._string

    def string(self: _Reader, *, decode: bool) -> str:
        value = original(self, decode=decode)
        if decode:
            seen.append(value)
        return value

    monkeypatch.setattr(_Reader, "_string", string)
    actual = status_document(json.dumps(payload).encode(), q.IntelligenceKind.PERFORMANCE)
    assert canary not in seen and canary not in repr(actual)
    assert "200" not in repr(actual)


@pytest.mark.parametrize(
    "mutation",
    (
        "duplicate",
        "unknown",
        "quality",
        "availability",
        "missing",
        "null_value",
        "family",
        "trailing",
    ),
)
def test_status_parser_rejects_malformed_named_fields(mutation: str) -> None:
    result = calculate.calculate_performance(historical_input(), options=hr.PerformanceOptions())
    payload = json.loads(canonical_json(result))
    metric = payload["summary"]["ending_value"]
    if mutation == "unknown":
        metric["provider_url"] = "https://invalid.example/private"
    elif mutation == "quality":
        metric["quality"] = "invented_quality"
    elif mutation == "availability":
        metric["availability"] = "invented_availability"
    elif mutation == "missing":
        del metric["quality"]
    elif mutation == "null_value":
        metric["value"] = None
        metric["availability"] = "available"
    elif mutation == "family":
        payload["family"] = "income"
    encoded = json.dumps(payload)
    if mutation == "duplicate":
        encoded = encoded.replace('"ending_value":', '"ending_value": null, "ending_value":', 1)
    elif mutation == "trailing":
        encoded += "{}"
    with pytest.raises(ValueError):
        status_document(encoded.encode(), q.IntelligenceKind.PERFORMANCE)


def test_lexical_skipping_enforces_size_depth_escapes_and_duplicate_keys() -> None:
    for payload in (b"[" * 34 + b"0" + b"]" * 34, b'{"x":0,"x":1}', b'"\\uZZZZ"', b"[0,]", b"NaN"):
        reader = _Reader(payload)
        with pytest.raises(ValueError):
            reader.skip()
            reader.finish()
    with pytest.raises(ValueError):
        _Reader(b" " * (33_554_432 + 1))


def test_zero_missing_failed_and_unknown_policy_remain_distinct() -> None:
    available = metric_row("ending_value", Availability.AVAILABLE, ViewQuality.ESTIMATED)
    absent = metric_row("ending_value", Availability.UNAVAILABLE, ViewQuality.PARTIAL)
    failed = metric_row("ending_value", Availability.UNAVAILABLE, ViewQuality.FAILED)
    assert available.current_usability == "usable"
    assert absent.recorded_quality is ViewQuality.PARTIAL and absent.missing_input == "unknown"
    assert failed.reasons == (q.QualityReason.COMPUTATION_FAILED,)
    assert (
        empty_metrics(q.IntelligenceKind.VALUATION, q.QualityReason.NOT_CALCULATED)[
            0
        ].recorded_quality
        is None
    )
    assert overlay_sources((available,), ())[0].freshness is SourceFreshnessState.UNAVAILABLE


def test_actual_900_second_boundary_preserves_intrinsic_quality() -> None:
    now = datetime(2026, 9, 11, tzinfo=UTC)
    at_boundary = source_freshness(
        now=now,
        reference_at=now - timedelta(seconds=900),
        policy_version="fixture",
        max_age_seconds=900,
    )
    stale = source_freshness(
        now=now + timedelta(microseconds=1),
        reference_at=now - timedelta(seconds=900),
        policy_version="fixture",
        max_age_seconds=900,
    )
    assert (
        at_boundary.state is SourceFreshnessState.FRESH
        and stale.state is SourceFreshnessState.STALE
    )
    assert (
        source_freshness(
            now=now,
            reference_at=now - timedelta(seconds=900),
            policy_version="provider-policy",
            max_age_seconds=900,
            inclusive_boundary=True,
        ).state
        is SourceFreshnessState.STALE
    )
    source = q.QualitySource(
        identity=q.QualitySourceIdentity(kind=q.QualitySourceKind.PRICE, id=uuid4()),
        freshness=stale,
    )
    row = metric_row("ending_value", Availability.AVAILABLE, ViewQuality.ESTIMATED)
    assert overlay_sources((row,), (source,))[0].recorded_quality is ViewQuality.ESTIMATED


@pytest.mark.parametrize("kind", tuple(q.IntelligenceKind))
def test_wire_catalogue_matches_application_and_rejects_arbitrary_metric_keys(
    kind: q.IntelligenceKind,
) -> None:
    assert tuple(wire.METRIC_KEYS[kind.value]) == q.METRIC_KEYS[kind]
    assert set(get_args(wire.IntelligenceMetricKey)) == {
        key for keys in q.METRIC_KEYS.values() for key in keys
    }
    for row in empty_metrics(kind, q.QualityReason.NOT_CALCULATED):
        payload = json.loads(canonical_json(row))
        wire.IntelligenceMetricQuality.model_validate(payload)
    payload["key"] = "arbitrary_json_path"
    with pytest.raises(ValidationError):
        wire.IntelligenceMetricQuality.model_validate(payload)


@pytest.mark.parametrize(
    "options",
    (
        {"analytics_kind": "all"},
        {"limit": 0},
        {"limit": True},
        {"limit": 101},
        {"cursor": "x" * 2049},
    ),
)
def test_query_contract_rejects_unbounded_or_noncanonical_options(options: QueryOptions) -> None:
    with pytest.raises(ValueError):
        q.IntelligenceDataQualityQuery(**options)
