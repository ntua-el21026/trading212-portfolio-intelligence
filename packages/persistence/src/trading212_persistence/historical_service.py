"""Six bounded historical reads over immutable captures and canonical stored calculations."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.orm import Session
from trading212_application import historical as app
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_security.principals import Principal, Scope

from .historical_store import PostgresHistoricalStore

Query = (
    app.PerformanceSeriesQuery
    | app.PerformanceSummaryQuery
    | app.BenchmarkComparisonQuery
    | app.AttributionQuery
    | app.DividendIntelligenceQuery
    | app.CashFlowIntelligenceQuery
)


class PostgresHistoricalService(PostgresHistoricalStore):
    def _request(
        self,
        session: Session,
        owner: UUID,
        account: UUID,
        query: Query,
        *,
        pinned: d.HistoricalSelectionRequest | None,
    ) -> d.HistoricalSelectionRequest:
        policy = (
            None
            if pinned is not None
            else self._policy(session, owner, account, query.window.source_cutoff_at)
        )
        registration = None if policy is None else self._policy_view(policy).registration
        support = []
        rolling = getattr(query.options, "rolling_window", d.RollingWindow.NONE)
        days = {
            d.RollingWindow.DAYS_30: 30,
            d.RollingWindow.DAYS_90: 90,
            d.RollingWindow.DAYS_365: 365,
        }.get(rolling)
        if days is not None:
            support.append(
                d.HistoricalSupportWindow(
                    reason=cast(
                        Literal["rolling_30", "rolling_90", "rolling_365"], f"rolling_{days}"
                    ),
                    start_at=query.window.start_at - timedelta(days=days),
                    end_at=query.window.end_at,
                )
            )
        if isinstance(query, app.DividendIntelligenceQuery):
            start, end = d.historical_previous_income_period(query.window)
            support.append(
                d.HistoricalSupportWindow(
                    reason="previous_calendar_income", start_at=start, end_at=end
                )
            )
        return d.HistoricalSelectionRequest(
            window=query.window,
            accounting_policy=pinned.accounting_policy
            if pinned is not None
            else (
                d.HistoricalAccountingPolicy()
                if registration is None
                else registration.accounting_policy
            ),
            source_policy=pinned.source_policy
            if pinned is not None
            else (None if registration is None else registration.source_policy),
            reporting_calendar_ref=pinned.reporting_calendar_ref
            if pinned is not None
            else (None if registration is None else registration.reporting_calendar_ref),
            support_windows=tuple(support),
            benchmark_version_id=getattr(query, "benchmark_version_id", None),
            target_version_id=getattr(query, "target_version_id", None),
            grouping_policy=getattr(query, "grouping_policy", None),
        )

    def _context(
        self,
        result: r.HistoricalCalculation,
        *,
        run_id: str,
        capture_id: str,
        content_digest: str,
        calculated_at: datetime,
        activity: bool,
    ) -> app.HistoricalRunContext:
        context = result.context
        values = {x.name: getattr(context, x.name) for x in fields(context)}
        sources = tuple(
            source
            for source in context.sources
            if activity
            or source.kind
            not in {"broker_source_record", "broker_source_occurrence", "ingestion_run"}
        )
        values["sources"] = sources[:64]
        values["warnings"] = tuple(
            issue if activity else replace(issue, reference_ids=())
            for issue in context.warnings[:64]
        )
        return app.HistoricalRunContext(
            **values,
            run_id=run_id,
            input_snapshot_id=capture_id,
            content_digest=content_digest,
            calculated_at=calculated_at,
            source_count=len(context.sources),
            source_omitted_count=len(context.sources) - len(sources[:64]),
            warning_count=len(context.warnings),
            warning_omitted_count=max(0, len(context.warnings) - 64),
        )

    async def _read(
        self, principal: Principal, account_id: str, query: Query, family: str
    ) -> object:
        from .historical_publication import (
            composite_header,
            historical_page,
            read_historical_result,
        )

        def operation(session: Session, owner: UUID, account: UUID | None) -> object:
            assert account is not None
            capture, run, stored, result = read_historical_result(
                self, session, principal, owner, account, query, family
            )
            activity = Scope.ACTIVITY_READ in principal.scopes
            context = self._context(
                result,
                run_id=str(run.id),
                capture_id=capture.id,
                content_digest=stored.content_digest,
                calculated_at=stored.created_at,
                activity=activity,
            )
            if isinstance(result, r.PerformanceCalculation):
                # Activity identifiers never cross summary-only scopes.
                points = tuple(
                    replace(
                        point,
                        flow_revision_ids=point.flow_revision_ids[:4] if activity else (),
                        flow_revision_omitted_count=point.flow_count
                        - (min(4, len(point.flow_revision_ids)) if activity else 0),
                    )
                    for point in result.points
                )
                if isinstance(query, app.PerformanceSeriesQuery):
                    return app.PerformanceSeriesView(
                        context=context,
                        summary=result.summary,
                        points=historical_page(self, session, owner, account, run, points, query),
                    )
                return app.PerformanceIntelligenceView(
                    context=context,
                    summary=result.summary,
                    series=points,
                    rolling_returns=result.rolling_returns,
                    calendar_returns=result.calendar_returns,
                )
            if isinstance(result, r.BenchmarkCalculation):
                return app.BenchmarkComparisonView(
                    context=context,
                    summary=result.summary,
                    series=result.points,
                    rolling_returns=result.rolling_returns,
                    calendar_returns=result.calendar_returns,
                    composite_snapshot=None
                    if result.composite is None
                    else composite_header(session, owner, run, result),
                )
            if isinstance(result, r.AttributionCalculation):
                assert isinstance(query, app.AttributionQuery)
                rows = result.rows[: query.top_n]
                return app.AttributionSummaryView(
                    context=context,
                    summary=result.summary,
                    rows=rows,
                    eligible_count=len(result.rows),
                    omitted_count=len(result.rows) - len(rows),
                    effects=result.effects,
                )
            if isinstance(result, r.IncomeCalculation):
                assert isinstance(query, app.DividendIntelligenceQuery)
                all_rows = (
                    result.group_rows
                    if query.options.grouping is d.HistoricalGrouping.GROUP
                    else result.instrument_rows
                )
                income_rows = all_rows[: query.top_n]
                return app.DividendIntelligenceView(
                    context=context,
                    summary=result.summary,
                    native_currency_totals=result.native_currency_totals,
                    reporting_totals=result.reporting_totals,
                    rows=income_rows,
                    eligible_count=len(all_rows),
                    omitted_count=len(all_rows) - len(income_rows),
                    period_rows=result.period_rows,
                    event_preview=app.HistoricalEventPreview(
                        items=tuple(_event_preview(x) for x in result.events[:16]),
                        total_count=len(result.events),
                        omitted_count=max(0, len(result.events) - 16),
                    ),
                )
            assert isinstance(result, r.CashFlowCalculation) and isinstance(
                query, app.CashFlowIntelligenceQuery
            )
            return app.CashFlowIntelligenceView(
                context=context,
                summary=result.summary,
                native_currency_totals=result.native_currency_totals,
                reporting_totals=result.reporting_totals,
                period_rows=result.period_rows,
                events=historical_page(
                    self,
                    session,
                    owner,
                    account,
                    run,
                    tuple(_event_preview(x) for x in result.events),
                    query,
                ),
                filtered_count=result.summary.filtered_count,
            )

        return await self._run(
            principal, account_id, operation, activity=family in {"income", "cash_flow"}
        )

    async def get_performance_series(
        self, principal: Principal, account_id: str, *, query: app.PerformanceSeriesQuery
    ) -> app.PerformanceSeriesView:
        return cast(
            app.PerformanceSeriesView, await self._read(principal, account_id, query, "performance")
        )

    async def get_performance_summary(
        self, principal: Principal, account_id: str, *, query: app.PerformanceSummaryQuery
    ) -> app.PerformanceIntelligenceView:
        return cast(
            app.PerformanceIntelligenceView,
            await self._read(principal, account_id, query, "performance"),
        )

    async def get_benchmark_comparison(
        self, principal: Principal, account_id: str, *, query: app.BenchmarkComparisonQuery
    ) -> app.BenchmarkComparisonView:
        return cast(
            app.BenchmarkComparisonView, await self._read(principal, account_id, query, "benchmark")
        )

    async def get_attribution_summary(
        self, principal: Principal, account_id: str, *, query: app.AttributionQuery
    ) -> app.AttributionSummaryView:
        return cast(
            app.AttributionSummaryView,
            await self._read(principal, account_id, query, "attribution"),
        )

    async def get_dividend_intelligence(
        self, principal: Principal, account_id: str, *, query: app.DividendIntelligenceQuery
    ) -> app.DividendIntelligenceView:
        return cast(
            app.DividendIntelligenceView, await self._read(principal, account_id, query, "income")
        )

    async def get_cash_flow_intelligence(
        self, principal: Principal, account_id: str, *, query: app.CashFlowIntelligenceQuery
    ) -> app.CashFlowIntelligenceView:
        return cast(
            app.CashFlowIntelligenceView,
            await self._read(principal, account_id, query, "cash_flow"),
        )


def _event_preview(value: r.HistoricalCashFlowPoint) -> r.HistoricalCashFlowPoint:
    total = len(value.source_ref_ids) + value.source_ref_omitted_count
    return replace(
        value,
        source_ref_ids=value.source_ref_ids[:4],
        source_ref_omitted_count=total - min(4, len(value.source_ref_ids)),
    )
