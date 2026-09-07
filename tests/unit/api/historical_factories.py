"""Synthetic wire fixtures for adapter boundaries, not financial algorithm evidence."""

from __future__ import annotations

from typing import Any

from trading212_api_contracts import historical as wire

ACCOUNT = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee"
CAPTURE = "2f34c23a-3798-4d4a-9133-9cd47639dd37"
RUN = "7cd43322-221c-4003-9bd3-ebd5bc97f99a"
VERSION = "1f0d0a41-8395-48b7-b6ca-0ee93eebecfe"
QUERY = {
    "start_date": "2026-01-01",
    "end_date": "2026-01-02",
    "source_cutoff_at": "2026-02-01T00:00:00Z",
    "reporting_currency": "EUR",
}


def metric(*, money: bool = False, amount: str = "0") -> dict[str, Any]:
    return {
        "value": {"amount": amount, "currency": "EUR"} if money else amount,
        "availability": "available",
        "reason_code": None,
        "quality": "fresh",
        "coverage_key": "valuation_cells",
        "origin": "derived",
    }


def metrics(schema: type[wire.HistoricalSchema]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        if field.annotation is wire.HistoricalMoneyMetric:
            values[name] = metric(money=True)
        elif field.annotation is wire.HistoricalRatioMetric:
            values[name] = metric()
        elif name == "currency":
            values[name] = "EUR"
        elif name == "comparable_total_return_basis":
            values[name] = False
        else:
            values[name] = 0
    return values


def context(method: str = "performance_v2") -> dict[str, Any]:
    return {
        "account_id": ACCOUNT,
        "window": {
            **QUERY,
            "coverage_policy": "require_complete",
            "knowledge_policy": "as_of_cutoff",
        },
        "method": {"name": method, "version": "1.0.0"},
        "primitive_methods": [],
        "input_digest": "a" * 64,
        "source_policy_version": None,
        "accounting_policy_version": "v1",
        "coverage": {"measures": []},
        "quality": "fresh",
        "availability": "available",
        "reconstruction": "restated",
        "sources": [],
        "warnings": [],
        "assumptions": [],
        "schema_version": "1.0.0",
        "run_id": RUN,
        "input_snapshot_id": CAPTURE,
        "content_digest": "b" * 64,
        "calculated_at": "2026-02-01T00:00:00Z",
        "source_count": 0,
        "source_omitted_count": 0,
        "warning_count": 0,
        "warning_omitted_count": 0,
        "access": {"reproducibility": "reproducible", "status_reference_at": None},
    }


def point() -> dict[str, Any]:
    return {
        **{
            name: metric(money=True)
            for name in (
                "portfolio_value",
                "invested_value",
                "cash_value",
                "external_flow",
                "deposits",
                "withdrawals",
                "net_contributions",
                "income",
                "fees",
                "withholding_taxes",
            )
        },
        **{
            name: metric()
            for name in ("interval_return", "cumulative_return", "twr_wealth", "drawdown")
        },
        "ordinal": 0,
        "date": "2026-01-01",
        "valuation_at": "2026-01-01T00:00:00Z",
        "flow_count": 0,
        "flow_revision_ids": [],
        "flow_revision_omitted_count": 0,
    }


def payload(name: str) -> dict[str, Any]:
    methods = {
        "get_performance_series": "performance_v2",
        "get_performance_summary": "performance_v2",
        "get_benchmark_comparison": "benchmark_comparison_v1",
        "get_attribution_summary": "attribution_bridge_v1",
        "get_dividend_intelligence": "income_v1",
        "get_cash_flow_intelligence": "cash_flow_intelligence_v1",
    }
    common = {"context": context(methods[name])}
    if name == "get_performance_summary":
        return {
            **common,
            "summary": metrics(wire.PerformanceMetrics),
            "series": [point()],
            "rolling_returns": [],
            "calendar_returns": [],
        }
    if name == "get_performance_series":
        return {
            **common,
            "summary": metrics(wire.PerformanceMetrics),
            "points": {"items": [point()], "limit": 25, "next_cursor": None, "total": 1},
        }
    if name == "get_benchmark_comparison":
        return {
            **common,
            "summary": metrics(wire.BenchmarkComparisonMetrics),
            "series": [],
            "composite_snapshot": None,
            "rolling_returns": [],
            "calendar_returns": [],
        }
    if name == "get_attribution_summary":
        return {
            **common,
            "summary": metrics(wire.AttributionMetrics),
            "rows": [],
            "eligible_count": 0,
            "omitted_count": 0,
            "effects": [],
        }
    if name == "get_dividend_intelligence":
        return {
            **common,
            "summary": metrics(wire.IncomeMetrics),
            "native_currency_totals": [],
            "reporting_totals": metrics(wire.CurrencyIncomeTotals),
            "rows": [],
            "eligible_count": 0,
            "omitted_count": 0,
            "period_rows": [],
            "event_preview": {"items": [], "total_count": 0, "omitted_count": 0},
        }
    if name == "get_cash_flow_intelligence":
        return {
            **common,
            "summary": metrics(wire.CashFlowMetrics),
            "native_currency_totals": [],
            "reporting_totals": metrics(wire.CurrencyCashFlowTotals),
            "period_rows": [],
            "events": {"items": [], "next_cursor": None, "limit": 25, "total": 0},
            "filtered_count": 0,
        }
    raise AssertionError("Unknown fixed test operation")
