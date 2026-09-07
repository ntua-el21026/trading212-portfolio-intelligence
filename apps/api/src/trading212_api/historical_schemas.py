"""Typed historical selectors and full authorized response ETags; no financial calculations."""

from __future__ import annotations

import hashlib

from fastapi import Request, Response
from trading212_api_contracts import historical as wire
from trading212_application import historical as app
from trading212_domain import historical as domain
from trading212_domain import historical_results as result
from trading212_domain.errors import DomainError
from trading212_domain.planning import CoveragePolicy
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode

from .target_routes import RESPONSE_BYTE_LIMIT, _error


def historical_window(value: wire.HistoricalWindowQuery) -> domain.HistoricalWindow:
    return domain.HistoricalWindow(
        start_date=value.start_date,
        end_date=value.end_date,
        source_cutoff_at=value.source_cutoff_at,
        reporting_currency=CurrencyCode(value.reporting_currency),
        coverage_policy=CoveragePolicy(value.coverage_policy),
        knowledge_policy=domain.KnowledgePolicy(value.knowledge_policy),
    )


def performance_options(value: wire.HistoricalPerformanceSummaryQuery) -> result.PerformanceOptions:
    return result.PerformanceOptions(
        method=domain.ReturnMethod(value.method),
        frequency=domain.HistoricalFrequency(value.frequency),
        rolling_window=domain.RollingWindow(value.rolling_window),
        calendar_period=domain.CalendarPeriod(value.calendar_period),
    )


def performance_series_query(
    value: wire.HistoricalPerformanceSeriesQuery,
) -> app.PerformanceSeriesQuery:
    return app.PerformanceSeriesQuery(
        window=historical_window(value),
        options=performance_options(value),
        input_snapshot_id=value.input_snapshot_id,
        cursor=value.cursor,
        limit=value.limit,
    )


def performance_summary_query(
    value: wire.HistoricalPerformanceSummaryQuery,
) -> app.PerformanceSummaryQuery:
    return app.PerformanceSummaryQuery(
        window=historical_window(value),
        options=performance_options(value),
        input_snapshot_id=value.input_snapshot_id,
    )


def benchmark_comparison_query(
    value: wire.HistoricalBenchmarkComparisonQuery,
) -> app.BenchmarkComparisonQuery:
    return app.BenchmarkComparisonQuery(
        window=historical_window(value),
        benchmark_version_id=value.benchmark_version_id,
        options=result.ComparisonOptions(
            frequency=domain.HistoricalFrequency(value.frequency),
            rolling_window=domain.RollingWindow(value.rolling_window),
            calendar_period=domain.CalendarPeriod(value.calendar_period),
        ),
        input_snapshot_id=value.input_snapshot_id,
    )


def attribution_query(value: wire.HistoricalAttributionQuery) -> app.AttributionQuery:
    return app.AttributionQuery(
        window=historical_window(value),
        options=result.AttributionOptions(
            grouping=domain.HistoricalGrouping(value.grouping),
            method=domain.AttributionMethod(value.method),
        ),
        target_version_id=value.target_version_id,
        benchmark_version_id=value.benchmark_version_id,
        grouping_policy=value.grouping_policy,
        top_n=value.top_n,
        input_snapshot_id=value.input_snapshot_id,
    )


def dividend_intelligence_query(
    value: wire.HistoricalDividendIntelligenceQuery,
) -> app.DividendIntelligenceQuery:
    return app.DividendIntelligenceQuery(
        window=historical_window(value),
        options=result.IncomeOptions(
            grouping=domain.HistoricalGrouping(value.grouping),
        ),
        target_version_id=value.target_version_id,
        grouping_policy=value.grouping_policy,
        top_n=value.top_n,
        input_snapshot_id=value.input_snapshot_id,
    )


def cash_flow_intelligence_query(
    value: wire.HistoricalCashFlowIntelligenceQuery,
) -> app.CashFlowIntelligenceQuery:
    return app.CashFlowIntelligenceQuery(
        window=historical_window(value),
        options=result.CashFlowOptions(
            frequency=domain.HistoricalFrequency(value.frequency),
            kind=domain.HistoricalCashFlowKind(value.kind) if value.kind is not None else None,
        ),
        input_snapshot_id=value.input_snapshot_id,
        cursor=value.cursor,
        limit=value.limit,
    )


def historical_response[T: wire.HistoricalSchema](
    request: Request, value: object, schema: type[T]
) -> Response:
    try:
        payload = schema.model_validate(to_primitive(value)).model_dump_json().encode("utf-8")
    except (KeyError, TypeError, ValueError, DomainError):
        return _error(
            request, 500, "INTERNAL_ERROR", "The historical operation could not complete."
        )
    if len(payload) > RESPONSE_BYTE_LIMIT:
        return _error(request, 422, "RESULT_TOO_LARGE", "The requested result is too large.")
    # The service has reauthorized owner/account and every current source license.
    # Hash the complete closed page, separately from its immutable financial digest.
    etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
    headers = {"Cache-Control": "private, no-store", "ETag": etag}
    tags = {
        item.strip().removeprefix("W/")
        for item in request.headers.get("if-none-match", "").split(",")
    }
    if etag in tags or "*" in tags:
        return Response(status_code=304, headers=headers)
    return Response(payload, media_type="application/json", headers=headers)
