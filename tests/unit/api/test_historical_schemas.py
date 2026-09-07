"""Historical queries retain exact replay scope and reject unbounded selectors."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from trading212_api_contracts import historical as wire

_WINDOW = {
    "start_date": "2025-01-01",
    "end_date": "2025-12-31",
    "source_cutoff_at": "2026-01-03T12:00:00Z",
    "reporting_currency": "EUR",
}


def test_historical_scope_and_reconstruction_are_explicit() -> None:
    query = wire.HistoricalPerformanceSummaryQuery.model_validate(_WINDOW)
    assert query.knowledge_policy == "as_of_cutoff"
    assert query.coverage_policy == "require_complete"
    assert query.method == "twr"
    assert query.frequency == "monthly"
    assert query.source_cutoff_at.year == 2026
    pinned = wire.HistoricalPerformanceSummaryQuery.model_validate(
        {
            **_WINDOW,
            "input_snapshot_id": "2bd3d1a8-7491-4bcb-ab71-5d487510f941",
            "knowledge_policy": "point_in_time",
            "rolling_window": "calendar_days_365",
            "calendar_period": "year",
        }
    )
    assert pinned.input_snapshot_id is not None
    assert pinned.knowledge_policy == "point_in_time"
    assert pinned.rolling_window == "calendar_days_365"


@pytest.mark.parametrize("days", [0, 3660])
def test_inclusive_historical_window_retains_exact_boundaries(days: int) -> None:
    start = date(2000, 1, 1)
    query = wire.HistoricalPerformanceSeriesQuery.model_validate(
        {
            **_WINDOW,
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=days)).isoformat(),
        }
    )
    assert (query.end_date - query.start_date).days == days


@pytest.mark.parametrize(
    "changes",
    [
        {"end_date": "2024-12-31"},
        {"start_date": "2000-01-01", "end_date": "2011-01-01"},
        {"source_cutoff_at": "2026-01-03T12:00:00"},
        {"source_cutoff_at": 1735732800},
        {"knowledge_policy": "latest"},
        {"method": "best_return"},
        {"frequency": "hourly"},
        {"rolling_window": 365},
        {"calendar_period": "fiscal_year"},
        {"input_snapshot_id": "unowned-or-opaque-query"},
        {"reporting_currency": "eur"},
        {"limit": 101},
        {"cursor": "https://invalid.example/provider"},
    ],
)
def test_historical_query_rejects_unsupported_scope(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        wire.HistoricalPerformanceSeriesQuery.model_validate({**_WINDOW, **changes})


def test_unknown_historical_input_key_never_becomes_error_location() -> None:
    unknown = "private-historical-query-canary"
    with pytest.raises(ValidationError) as captured:
        wire.HistoricalPerformanceSummaryQuery.model_validate({**_WINDOW, unknown: "unused"})
    assert unknown not in str(captured.value)
    assert all(unknown not in str(error["loc"]) for error in captured.value.errors())


@pytest.mark.parametrize(
    "schema", [wire.HistoricalAttributionQuery, wire.HistoricalDividendIntelligenceQuery]
)
def test_grouping_requires_a_pinned_target_and_top_remains_bounded(
    schema: type[wire.HistoricalSchema],
) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate({**_WINDOW, "grouping": "group"})
    with pytest.raises(ValidationError):
        schema.model_validate({**_WINDOW, "top_n": 51})
    valid = schema.model_validate(
        {
            **_WINDOW,
            "grouping": "group",
            "target_version_id": "2bd3d1a8-7491-4bcb-ab71-5d487510f941",
        }
    )
    assert valid.model_dump()["target_version_id"] == "2bd3d1a8-7491-4bcb-ab71-5d487510f941"


def test_cash_flow_filter_cannot_be_a_generic_expression() -> None:
    query = wire.HistoricalCashFlowIntelligenceQuery.model_validate(
        {**_WINDOW, "kind": "withdrawal"}
    )
    assert query.kind == "withdrawal"
    with pytest.raises(ValidationError):
        wire.HistoricalCashFlowIntelligenceQuery.model_validate({**_WINDOW, "kind": "amount > 0"})


@pytest.mark.parametrize("limit", [True, 1.0, "1.0", "1e1", " 1", "01", "1" * 1000])
def test_historical_integer_selectors_reject_coercion(limit: object) -> None:
    with pytest.raises(ValidationError):
        wire.HistoricalPerformanceSeriesQuery.model_validate({**_WINDOW, "limit": limit})


def test_http_integer_selector_has_same_value_as_typed_mcp_integer() -> None:
    textual = wire.HistoricalPerformanceSeriesQuery.model_validate({**_WINDOW, "limit": "100"})
    typed = wire.HistoricalPerformanceSeriesQuery.model_validate({**_WINDOW, "limit": 100})
    assert textual == typed


def test_zero_historical_money_is_distinct_from_unavailable_and_partial() -> None:
    base = {
        "availability": "available",
        "reason_code": None,
        "quality": "fresh",
        "coverage_key": "cash",
        "origin": "derived",
    }
    zero = wire.HistoricalMoneyMetric.model_validate(
        {**base, "value": {"amount": "0", "currency": "EUR"}}
    )
    assert zero.value is not None and zero.value.amount == "0"
    missing = wire.HistoricalMoneyMetric.model_validate(
        {
            **base,
            "value": None,
            "availability": "unavailable",
            "reason_code": "unavailable_valuation",
            "quality": "partial",
        }
    )
    assert missing.value is None
    with pytest.raises(ValidationError):
        wire.HistoricalMoneyMetric.model_validate({**base, "value": None})
    with pytest.raises(ValidationError):
        wire.HistoricalMoneyMetric.model_validate(
            {**base, "value": {"amount": "0", "currency": "EUR"}, "availability": "partial"}
        )


@pytest.mark.parametrize(
    "amount",
    [0, 0.1, True, "NaN", "Infinity", "1e-18", "100000000000000000000", "0.0000000000000000001"],
)
def test_historical_money_rejects_inexact_or_out_of_range_values(amount: object) -> None:
    with pytest.raises(ValidationError):
        wire.HistoricalMoney.model_validate({"amount": amount, "currency": "EUR"})


def test_historical_money_preserves_all_eighteen_fraction_digits() -> None:
    value = wire.HistoricalMoney.model_validate(
        {"amount": "99999999999999999999.999999999999999999", "currency": "EUR"}
    )
    assert value.amount == "99999999999999999999.999999999999999999"


def test_historical_coverage_cannot_hide_a_missing_cell_or_repeat_a_denominator() -> None:
    complete = {
        "key": "valuation_cells",
        "expected_count": 10,
        "available_count": 10,
        "complete": True,
    }
    with pytest.raises(ValidationError):
        wire.HistoricalCoverageMeasure.model_validate({**complete, "available_count": 9})
    with pytest.raises(ValidationError):
        wire.HistoricalCoverageMeasure.model_validate({**complete, "available_count": 11})
    with pytest.raises(ValidationError):
        wire.HistoricalCoverage.model_validate({"measures": [complete, complete]})


@pytest.mark.parametrize(
    "schema", [wire.HistoricalAttributionQuery, wire.HistoricalDividendIntelligenceQuery]
)
def test_grouping_policy_requires_an_explicit_authorizable_target(
    schema: type[wire.HistoricalSchema],
) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate({**_WINDOW, "grouping_policy": "historical_assignment"})
    selected = schema.model_validate(
        {
            **_WINDOW,
            "target_version_id": "2bd3d1a8-7491-4bcb-ab71-5d487510f941",
            "grouping_policy": "historical_assignment",
        }
    )
    assert selected.model_dump()["grouping_policy"] == "historical_assignment"
