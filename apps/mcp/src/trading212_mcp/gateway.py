"""Authorized, bounded MCP composition over canonical application services."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, date
from decimal import Decimal
from typing import Any, TypeVar

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel
from trading212_application.services import PortfolioService
from trading212_application.views import Page, QualityView, paginate
from trading212_domain.values import decimal_string
from trading212_security.principals import (
    AuthenticationError,
    AuthorizationError,
    Principal,
)
from trading212_security.redaction import RedactingLogFilter, Redactor

from .auth import PrincipalResolver
from .schemas import (
    AccountSummaryData,
    AccountSummaryResult,
    ActivityTypeFilter,
    Calculation,
    CapabilityQuality,
    DataQualitySummaryData,
    DataQualitySummaryResult,
    DirectAllocationData,
    DirectAllocationResult,
    DividendCurrencyTotal,
    DividendSummaryData,
    DividendSummaryResult,
    ErrorDetail,
    Pagination,
    PortfolioSnapshotResult,
    PositionsData,
    PositionSort,
    PositionsResult,
    ReconciliationData,
    ReconciliationResult,
    ReconciliationSummary,
    SnapshotComparisonResult,
    SnapshotData,
    TransactionsData,
    TransactionsResult,
)
from .serialization import (
    account,
    activity,
    allocation,
    dividend,
    metric,
    position,
    quality,
    reconciliation_issue,
    safe_text,
    snapshot_comparison,
)

_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_COLLECTION_PAGE_SIZE = 100
_COLLECTION_PAGE_COUNT = 5
_COLLECTION_CAP = _COLLECTION_PAGE_SIZE * _COLLECTION_PAGE_COUNT
_KNOWN_ACTIVITY_TYPES = frozenset(
    {"buy", "sell", "dividend", "deposit", "withdrawal", "interest", "fee", "tax", "transfer"}
)

ResultT = TypeVar("ResultT", bound=BaseModel)


class PortfolioMcpGateway:
    """MCP-facing use cases; no SQL, provider transport, or calculation internals."""

    def __init__(
        self,
        *,
        service: PortfolioService,
        principals: PrincipalResolver,
        logger: logging.Logger | None = None,
    ) -> None:
        self._service = service
        self._principals = principals
        self._logger = logger or logging.getLogger("trading212_mcp.audit")
        self._logger.addFilter(RedactingLogFilter(Redactor()))

    async def get_account_summary(
        self, account_id: str, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal,
        ) -> tuple[AccountSummaryResult, str, dict[str, Any]]:
            summary, reconciliation = await asyncio.gather(
                self._service.get_summary(principal, account_id),
                self._service.get_reconciliation(principal, account_id),
            )
            data = AccountSummaryData(
                account=account(summary.account),
                total_value=metric(summary.total_value),
                cash_balance=metric(summary.cash_balance),
                invested_value=metric(summary.invested_value),
                net_contributions=metric(summary.net_contributions),
                dividends_received=metric(summary.dividends_received),
                realized_profit_loss=metric(summary.realized_profit_loss),
                unrealized_profit_loss=metric(summary.unrealized_profit_loss),
                position_count=summary.position_count,
                reconciliation=ReconciliationSummary(
                    status=safe_text(reconciliation.status, maximum=40),
                    evaluated_at=reconciliation.evaluated_at,
                    discrepancy_count=len(reconciliation.issues),
                ),
            )
            result = AccountSummaryResult(
                data=data,
                as_of=summary.quality.as_of,
                reporting_currency=summary.account.reporting_currency,
                data_quality=quality(summary.quality),
                calculation=_calculation(
                    "account_summary",
                    summary.total_value.calculation_version,
                    summary.quality.as_of,
                ),
                pagination=None,
                error=None,
            )
            return (
                result,
                "Retrieved the read-only account summary; "
                f"quality is {summary.quality.state.value}.",
                {},
            )

        return await self._execute(
            tool_name="get_account_summary",
            account_id=account_id,
            context=context,
            result_type=AccountSummaryResult,
            operation=operation,
        )

    async def get_portfolio_snapshot(
        self,
        account_id: str,
        snapshot_id: str | None,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal,
        ) -> tuple[PortfolioSnapshotResult, str, dict[str, Any]]:
            async def fetch(cursor: str | None, limit: int) -> Page[Any]:
                return await self._service.list_snapshots(
                    principal, account_id, cursor=cursor, limit=limit
                )

            (snapshots, collection_truncated), summary = await asyncio.gather(
                _collect_pages(fetch),
                self._service.get_summary(principal, account_id),
            )
            if not snapshots:
                raise LookupError("snapshot not found")
            selected = (
                next((item for item in snapshots if item.id == snapshot_id), None)
                if snapshot_id is not None
                else max(snapshots, key=lambda item: item.valuation_at)
            )
            if selected is None:
                raise LookupError("snapshot not found")
            synthetic = (
                summary.account.provider == "synthetic"
                or summary.account.environment == "synthetic"
            )
            extra = (
                [f"Snapshot search was capped at {_COLLECTION_CAP} records."]
                if collection_truncated
                else []
            )
            snapshot_quality = quality(selected.quality, extra_warnings=extra)
            data = SnapshotData(
                id=safe_text(selected.id, maximum=255),
                valuation_at=selected.valuation_at,
                source_cutoff_at=selected.source_cutoff_at,
                reporting_currency=selected.reporting_currency,
                total_value=metric(selected.total_value),
                cash_value=metric(selected.cash_value),
                invested_value=metric(selected.invested_value),
                net_contributions=metric(selected.net_contributions),
                dividends_received=metric(summary.dividends_received),
                realized_profit_loss=metric(summary.realized_profit_loss),
                unrealized_profit_loss=metric(summary.unrealized_profit_loss),
                synthetic_data=synthetic,
                quality_disclosure=(
                    f"Quality is {selected.quality.state.value}; source cutoff is "
                    f"{selected.source_cutoff_at.isoformat()}."
                ),
            )
            result = PortfolioSnapshotResult(
                data=data,
                as_of=selected.valuation_at,
                reporting_currency=selected.reporting_currency,
                data_quality=snapshot_quality,
                calculation=_calculation(
                    "portfolio_snapshot",
                    selected.total_value.calculation_version,
                    selected.valuation_at,
                    assumptions=(
                        "Realized fields remain unavailable when coverage is incomplete.",
                    ),
                ),
                pagination=None,
                error=None,
            )
            return (
                result,
                f"Retrieved read-only snapshot {selected.id}; "
                f"quality is {selected.quality.state.value}.",
                {
                    "portfolioSnapshot": {
                        "readOnly": True,
                        "syntheticData": synthetic,
                        "qualityState": selected.quality.state.value,
                    }
                },
            )

        return await self._execute(
            tool_name="get_portfolio_snapshot",
            account_id=account_id,
            context=context,
            result_type=PortfolioSnapshotResult,
            operation=operation,
        )

    async def list_positions(
        self,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
        sort: PositionSort,
        search: str | None,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(principal: Principal) -> tuple[PositionsResult, str, dict[str, Any]]:
            normalized_search = search.strip() if search is not None else None
            if normalized_search == "":
                raise ValueError("search must contain visible characters")

            async def fetch(page_cursor: str | None, page_limit: int) -> Page[Any]:
                return await self._service.list_positions(
                    principal, account_id, cursor=page_cursor, limit=page_limit
                )

            (values, collection_truncated), summary = await asyncio.gather(
                _collect_pages(fetch),
                self._service.get_summary(principal, account_id),
            )
            if normalized_search is not None:
                needle = normalized_search.casefold()
                values = [
                    item
                    for item in values
                    if needle in item.ticker.casefold() or needle in item.name.casefold()
                ]
            _sort_positions(values, sort)
            selected = paginate(values, cursor=cursor, limit=limit)
            extra = (
                [f"Position collection was capped at {_COLLECTION_CAP} records."]
                if collection_truncated
                else []
            )
            result = PositionsResult(
                data=PositionsData(
                    positions=[position(item) for item in selected.items],
                    sort=sort,
                    search=normalized_search,
                ),
                as_of=summary.quality.as_of,
                reporting_currency=summary.account.reporting_currency,
                data_quality=quality(summary.quality, extra_warnings=extra),
                calculation=_calculation(
                    "canonical_positions",
                    summary.total_value.calculation_version,
                    summary.quality.as_of,
                ),
                pagination=Pagination(
                    next_cursor=selected.next_cursor,
                    limit=selected.limit,
                    total=selected.total,
                    truncated=collection_truncated,
                ),
                error=None,
            )
            return result, f"Retrieved {len(selected.items)} read-only position observations.", {}

        return await self._execute(
            tool_name="list_positions",
            account_id=account_id,
            context=context,
            result_type=PositionsResult,
            operation=operation,
        )

    async def list_recent_transactions(
        self,
        account_id: str,
        *,
        start_date: date,
        end_date: date,
        type_filter: ActivityTypeFilter,
        cursor: str | None,
        limit: int,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(principal: Principal) -> tuple[TransactionsResult, str, dict[str, Any]]:
            _validate_date_range(start_date, end_date, maximum_days=366)

            async def fetch(page_cursor: str | None, page_limit: int) -> Page[Any]:
                return await self._service.list_activity(
                    principal, account_id, cursor=page_cursor, limit=page_limit
                )

            (values, collection_truncated), account_value = await asyncio.gather(
                _collect_pages(fetch),
                self._service.get_account(principal, account_id),
            )
            values = [
                item
                for item in values
                if start_date <= item.occurred_at.astimezone(UTC).date() <= end_date
                and _activity_matches(item.activity_type, type_filter)
            ]
            values.sort(key=lambda item: (item.occurred_at, item.id), reverse=True)
            selected = paginate(values, cursor=cursor, limit=limit)
            base_quality = _first_quality(values)
            if base_quality is None:
                summary = await self._service.get_summary(principal, account_id)
                base_quality = summary.quality
            extra = (
                [f"Activity collection was capped at {_COLLECTION_CAP} records."]
                if collection_truncated
                else []
            )
            result = TransactionsResult(
                data=TransactionsData(
                    transactions=[activity(item) for item in selected.items],
                    period_start=start_date,
                    period_end=end_date,
                    type_filter=type_filter,
                ),
                as_of=base_quality.as_of,
                reporting_currency=account_value.reporting_currency,
                data_quality=quality(base_quality, extra_warnings=extra),
                calculation=_calculation(
                    "normalized_activity",
                    "phase1-ledger/1.0.0",
                    base_quality.as_of,
                ),
                pagination=Pagination(
                    next_cursor=selected.next_cursor,
                    limit=selected.limit,
                    total=selected.total,
                    truncated=collection_truncated,
                ),
                error=None,
            )
            return (
                result,
                f"Retrieved {len(selected.items)} read-only transaction observations.",
                {},
            )

        return await self._execute(
            tool_name="list_recent_transactions",
            account_id=account_id,
            context=context,
            result_type=TransactionsResult,
            operation=operation,
        )

    async def get_dividend_summary(
        self,
        account_id: str,
        *,
        start_date: date,
        end_date: date,
        recent_limit: int,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal,
        ) -> tuple[DividendSummaryResult, str, dict[str, Any]]:
            _validate_date_range(start_date, end_date, maximum_days=3_660)

            async def fetch(page_cursor: str | None, page_limit: int) -> Page[Any]:
                return await self._service.list_dividends(
                    principal, account_id, cursor=page_cursor, limit=page_limit
                )

            (values, collection_truncated), account_value = await asyncio.gather(
                _collect_pages(fetch),
                self._service.get_account(principal, account_id),
            )
            values = [item for item in values if start_date <= item.paid_on <= end_date]
            values.sort(key=lambda item: (item.paid_on, item.id), reverse=True)
            base_quality = _first_quality(values)
            if base_quality is None:
                summary = await self._service.get_summary(principal, account_id)
                base_quality = summary.quality
            totals = _dividend_totals(values)
            extra = (
                [f"Dividend collection was capped at {_COLLECTION_CAP} records."]
                if collection_truncated
                else []
            )
            result = DividendSummaryResult(
                data=DividendSummaryData(
                    period_start=start_date,
                    period_end=end_date,
                    totals_by_currency=totals,
                    recent_dividends=[dividend(item) for item in values[:recent_limit]],
                    covered_record_count=len(values),
                ),
                as_of=base_quality.as_of,
                reporting_currency=account_value.reporting_currency,
                data_quality=quality(base_quality, extra_warnings=extra),
                calculation=_calculation(
                    "dividend_summary",
                    "phase1-ledger/1.0.0",
                    base_quality.as_of,
                    assumptions=(
                        "Totals are grouped by currency; no unsourced FX conversion is performed.",
                    ),
                ),
                pagination=Pagination(
                    next_cursor=None,
                    limit=recent_limit,
                    total=len(values),
                    truncated=collection_truncated or len(values) > recent_limit,
                ),
                error=None,
            )
            return result, f"Summarized {len(values)} covered dividend observations.", {}

        return await self._execute(
            tool_name="get_dividend_summary",
            account_id=account_id,
            context=context,
            result_type=DividendSummaryResult,
            operation=operation,
        )

    async def get_direct_allocation(
        self,
        account_id: str,
        *,
        top_n: int,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal,
        ) -> tuple[DirectAllocationResult, str, dict[str, Any]]:
            values, summary = await asyncio.gather(
                self._service.get_allocation(principal, account_id),
                self._service.get_summary(principal, account_id),
            )
            cash = [
                item for item in values if item.asset_type.casefold() == "cash" or item.id == "cash"
            ]
            positions = [item for item in values if item not in cash]
            positions.sort(
                key=lambda item: (
                    item.weight if item.weight is not None else Decimal("-1"),
                    item.id,
                ),
                reverse=True,
            )
            selected = [*positions[:top_n], *cash[:1]]
            truncated = len(positions) > top_n or len(cash) > 1
            result = DirectAllocationResult(
                data=DirectAllocationData(
                    allocations=[allocation(item) for item in selected],
                    includes_cash=bool(cash),
                    methodology="direct_provider_observed_positions_and_cash",
                ),
                as_of=summary.quality.as_of,
                reporting_currency=summary.account.reporting_currency,
                data_quality=quality(summary.quality),
                calculation=_calculation(
                    "direct_allocation",
                    summary.total_value.calculation_version,
                    summary.quality.as_of,
                    assumptions=("No ETF look-through is performed in Phase 1.",),
                ),
                pagination=Pagination(
                    next_cursor=None,
                    limit=top_n,
                    total=len(values),
                    truncated=truncated,
                ),
                error=None,
            )
            return (
                result,
                f"Retrieved {len(selected)} direct allocation rows, including cash when available.",
                {},
            )

        return await self._execute(
            tool_name="get_direct_allocation",
            account_id=account_id,
            context=context,
            result_type=DirectAllocationResult,
            operation=operation,
        )

    async def compare_portfolio_snapshots(
        self,
        account_id: str,
        *,
        start_snapshot_id: str,
        end_snapshot_id: str,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal,
        ) -> tuple[SnapshotComparisonResult, str, dict[str, Any]]:
            comparison = await self._service.compare_snapshots(
                principal, account_id, start_snapshot_id, end_snapshot_id
            )
            result = SnapshotComparisonResult(
                data=snapshot_comparison(comparison),
                as_of=comparison.end.valuation_at,
                reporting_currency=comparison.end.reporting_currency,
                data_quality=quality(comparison.quality),
                calculation=_calculation(
                    "portfolio_snapshot_comparison",
                    comparison.value_change.calculation_version,
                    comparison.quality.as_of,
                    assumptions=("No attribution is fabricated beyond covered Phase 1 effects.",),
                ),
                pagination=None,
                error=None,
            )
            return result, "Compared two immutable read-only portfolio snapshots.", {}

        return await self._execute(
            tool_name="compare_portfolio_snapshots",
            account_id=account_id,
            context=context,
            result_type=SnapshotComparisonResult,
            operation=operation,
        )

    async def get_reconciliation_status(
        self,
        account_id: str,
        *,
        issue_limit: int,
        context: Context[Any, Any],
    ) -> CallToolResult:
        async def operation(
            principal: Principal,
        ) -> tuple[ReconciliationResult, str, dict[str, Any]]:
            reconciliation, account_value = await asyncio.gather(
                self._service.get_reconciliation(principal, account_id),
                self._service.get_account(principal, account_id),
            )
            issues = list(reconciliation.issues)
            remediation = (
                "No remediation is required for the current reconciled observation."
                if reconciliation.status == "reconciled"
                else (
                    "Review the listed discrepancies and refresh source data before relying "
                    "on affected metrics."
                )
            )
            result = ReconciliationResult(
                data=ReconciliationData(
                    status=safe_text(reconciliation.status, maximum=40),
                    evaluated_at=reconciliation.evaluated_at,
                    algorithm_version=safe_text(reconciliation.algorithm_version, maximum=120),
                    tolerance_version=safe_text(reconciliation.tolerance_version, maximum=120),
                    discrepancy_count=len(issues),
                    issues=[reconciliation_issue(item) for item in issues[:issue_limit]],
                    remediation_guidance=remediation,
                ),
                as_of=reconciliation.quality.as_of,
                reporting_currency=account_value.reporting_currency,
                data_quality=quality(reconciliation.quality),
                calculation=_calculation(
                    "portfolio_reconciliation",
                    reconciliation.algorithm_version,
                    reconciliation.evaluated_at,
                    assumptions=(f"Tolerance policy: {reconciliation.tolerance_version}.",),
                ),
                pagination=Pagination(
                    next_cursor=None,
                    limit=issue_limit,
                    total=len(issues),
                    truncated=len(issues) > issue_limit,
                ),
                error=None,
            )
            return (
                result,
                f"Reconciliation state is {reconciliation.status} "
                f"with {len(issues)} discrepancies.",
                {},
            )

        return await self._execute(
            tool_name="get_reconciliation_status",
            account_id=account_id,
            context=context,
            result_type=ReconciliationResult,
            operation=operation,
        )

    async def get_data_quality_summary(
        self, account_id: str, context: Context[Any, Any]
    ) -> CallToolResult:
        async def operation(
            principal: Principal,
        ) -> tuple[DataQualitySummaryResult, str, dict[str, Any]]:
            (
                summary,
                snapshots,
                positions,
                activity_page,
                dividends,
                reconciliation,
            ) = await asyncio.gather(
                self._service.get_summary(principal, account_id),
                self._service.list_snapshots(principal, account_id, cursor=None, limit=1),
                self._service.list_positions(principal, account_id, cursor=None, limit=1),
                self._service.list_activity(principal, account_id, cursor=None, limit=1),
                self._service.list_dividends(principal, account_id, cursor=None, limit=1),
                self._service.get_reconciliation(principal, account_id),
            )
            capability_values = (
                ("account_summary", summary.quality),
                ("portfolio_snapshots", _page_quality(snapshots, summary.quality)),
                ("positions", _page_quality(positions, summary.quality)),
                ("activity", _page_quality(activity_page, summary.quality)),
                ("dividends", _page_quality(dividends, summary.quality)),
                ("reconciliation", reconciliation.quality),
            )
            data = DataQualitySummaryData(
                capabilities=[
                    CapabilityQuality(
                        capability="account_summary", data_quality=quality(capability_values[0][1])
                    ),
                    CapabilityQuality(
                        capability="portfolio_snapshots",
                        data_quality=quality(capability_values[1][1]),
                    ),
                    CapabilityQuality(
                        capability="positions", data_quality=quality(capability_values[2][1])
                    ),
                    CapabilityQuality(
                        capability="activity", data_quality=quality(capability_values[3][1])
                    ),
                    CapabilityQuality(
                        capability="dividends", data_quality=quality(capability_values[4][1])
                    ),
                    CapabilityQuality(
                        capability="reconciliation",
                        data_quality=quality(capability_values[5][1]),
                    ),
                ],
                failed_or_partial_runs=[],
            )
            result = DataQualitySummaryResult(
                data=data,
                as_of=summary.quality.as_of,
                reporting_currency=summary.account.reporting_currency,
                data_quality=quality(
                    summary.quality,
                    extra_warnings=(
                        "Refresh-run history is not exposed by the current Phase 1 "
                        "application service.",
                    ),
                ),
                calculation=_calculation(
                    "data_quality_summary",
                    "phase1-data-quality/1.0.0",
                    summary.quality.as_of,
                ),
                pagination=None,
                error=None,
            )
            return (
                result,
                f"Retrieved quality states for {len(capability_values)} bounded capabilities.",
                {},
            )

        return await self._execute(
            tool_name="get_data_quality_summary",
            account_id=account_id,
            context=context,
            result_type=DataQualitySummaryResult,
            operation=operation,
        )

    async def _execute(
        self,
        *,
        tool_name: str,
        account_id: str,
        context: Context[Any, Any],
        result_type: type[ResultT],
        operation: Callable[[Principal], Awaitable[tuple[ResultT, str, dict[str, Any]]]],
    ) -> CallToolResult:
        correlation_id = _correlation_id(context)
        try:
            principal = await self._principals.resolve()
            result, message, widget_meta = await operation(principal)
            result_type.model_validate(result)
            self._audit(tool_name, account_id, principal.principal_id, correlation_id, "success")
            meta = {"correlationId": correlation_id, **widget_meta}
            return _call_result(result, message, meta=meta)
        except Exception as exc:
            error = _safe_error(exc, correlation_id)
            principal_id = "unresolved"
            self._audit(tool_name, account_id, principal_id, correlation_id, error.code)
            failure = result_type.model_validate(
                {
                    "data": None,
                    "as_of": None,
                    "reporting_currency": None,
                    "data_quality": None,
                    "calculation": None,
                    "pagination": None,
                    "error": error.model_dump(mode="json"),
                }
            )
            return _call_result(
                failure,
                f"{error.code}: {error.message} Correlation ID: {correlation_id}.",
                meta={"correlationId": correlation_id},
                is_error=True,
            )

    def _audit(
        self,
        tool_name: str,
        account_id: str,
        principal_id: str,
        correlation_id: str,
        outcome: str,
    ) -> None:
        self._logger.info(
            "mcp_tool_call tool=%s outcome=%s account_ref=%s principal_ref=%s correlation_ref=%s",
            tool_name,
            safe_text(outcome, maximum=80),
            _opaque_ref(account_id),
            _opaque_ref(principal_id),
            _opaque_ref(correlation_id),
        )


def _calculation(
    name: str,
    version: str,
    calculated_at: Any,
    *,
    assumptions: Iterable[str] = (),
) -> Calculation:
    return Calculation(
        name=name,
        version=safe_text(version, maximum=120),
        calculated_at=calculated_at,
        assumptions=[safe_text(value, maximum=240) for value in list(assumptions)[:20]],
    )


def _call_result(
    result: BaseModel,
    message: str,
    *,
    meta: dict[str, Any],
    is_error: bool = False,
) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=safe_text(message, maximum=360))],
        structured_content=result.model_dump(mode="json", by_alias=True),
        _meta=meta,
        is_error=is_error,
    )


async def _collect_pages[ItemT](
    fetch: Callable[[str | None, int], Awaitable[Page[ItemT]]],
) -> tuple[list[ItemT], bool]:
    items: list[ItemT] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(_COLLECTION_PAGE_COUNT):
        page = await fetch(cursor, _COLLECTION_PAGE_SIZE)
        items.extend(page.items)
        if page.next_cursor is None:
            return items, False
        if page.next_cursor in seen:
            raise ValueError("application pagination cursor did not advance")
        seen.add(page.next_cursor)
        cursor = page.next_cursor
    return items, cursor is not None


def _sort_positions(values: list[Any], sort: PositionSort) -> None:
    if sort is PositionSort.TICKER_ASC:
        values.sort(key=lambda item: (item.ticker.casefold(), item.id))
    elif sort is PositionSort.WEIGHT_DESC:
        values.sort(
            key=lambda item: (
                item.direct_weight if item.direct_weight is not None else Decimal("-1"),
                item.ticker.casefold(),
            ),
            reverse=True,
        )
    else:
        values.sort(
            key=lambda item: (
                item.market_value.value if item.market_value.value is not None else Decimal("-1"),
                item.ticker.casefold(),
            ),
            reverse=True,
        )


def _validate_date_range(start_date: date, end_date: date, *, maximum_days: int) -> None:
    if end_date < start_date or (end_date - start_date).days > maximum_days:
        raise ValueError("date range is outside the bounded window")


def _activity_matches(activity_type: str, requested: ActivityTypeFilter) -> bool:
    normalized = activity_type.casefold()
    if requested is ActivityTypeFilter.ALL:
        return True
    if requested is ActivityTypeFilter.UNKNOWN:
        return normalized not in _KNOWN_ACTIVITY_TYPES
    return normalized == requested.value


def _first_quality(values: list[Any]) -> QualityView | None:
    return values[0].quality if values else None


def _page_quality(page: Page[Any], fallback: QualityView) -> QualityView:
    return page.items[0].quality if page.items else fallback


def _dividend_totals(values: list[Any]) -> list[DividendCurrencyTotal]:
    totals: dict[str, dict[str, Decimal | None]] = {}
    for value in values:
        for field_name, metric_value in (
            ("net_amount", value.net_amount),
            ("gross_amount", value.gross_amount),
            ("withholding_tax", value.withholding_tax),
        ):
            currency_totals = totals.setdefault(
                metric_value.currency,
                {"net_amount": None, "gross_amount": None, "withholding_tax": None},
            )
            if metric_value.value is not None:
                current = currency_totals[field_name]
                currency_totals[field_name] = (current or Decimal("0")) + metric_value.value
    return [
        DividendCurrencyTotal(
            currency=currency,
            net_amount=_optional_decimal(amounts["net_amount"]),
            gross_amount=_optional_decimal(amounts["gross_amount"]),
            withholding_tax=_optional_decimal(amounts["withholding_tax"]),
        )
        for currency, amounts in sorted(totals.items())
    ]


def _optional_decimal(value: Decimal | None) -> str | None:
    return decimal_string(value) if value is not None else None


def _correlation_id(context: Context[Any, Any]) -> str:
    try:
        headers = context.headers
    except ValueError:
        headers = None
    supplied = headers.get("x-correlation-id") if headers is not None else None
    if supplied is not None and _CORRELATION_PATTERN.fullmatch(supplied):
        return supplied
    return str(uuid.uuid4())


def _safe_error(exc: Exception, correlation_id: str) -> ErrorDetail:
    name = type(exc).__name__.casefold()
    if isinstance(exc, AuthenticationError):
        return ErrorDetail(
            code="AUTHENTICATION_REQUIRED",
            message="Authentication is required.",
            correlation_id=correlation_id,
            retryable=False,
            remediation="Authenticate through the configured MCP OAuth connection and retry.",
        )
    if isinstance(exc, AuthorizationError):
        return ErrorDetail(
            code="ACCESS_DENIED",
            message="Access denied.",
            correlation_id=correlation_id,
            retryable=False,
            remediation=(
                "Use an authorized account and token scope; account existence is not disclosed."
            ),
        )
    if isinstance(exc, LookupError):
        return ErrorDetail(
            code="NOT_FOUND",
            message="The requested private resource was not found or is not accessible.",
            correlation_id=correlation_id,
            retryable=False,
            remediation="Check the opaque identifier returned by an earlier authorized tool call.",
        )
    if isinstance(exc, ValueError):
        return ErrorDetail(
            code="VALIDATION_FAILED",
            message="The bounded request is invalid.",
            correlation_id=correlation_id,
            retryable=False,
            remediation="Use the declared enum, identifier, cursor, date, and limit constraints.",
        )
    if "ratelimit" in name or "rate_limit" in name:
        return ErrorDetail(
            code="PROVIDER_RATE_LIMITED",
            message="The upstream read-only provider is temporarily rate limited.",
            correlation_id=correlation_id,
            retryable=True,
            remediation="Retry after the server-managed backoff window.",
        )
    if "refreshpending" in name or "refresh_pending" in name:
        return ErrorDetail(
            code="DATA_REFRESH_PENDING",
            message="A bounded portfolio refresh is still pending.",
            correlation_id=correlation_id,
            retryable=True,
            remediation="Wait for the current refresh to complete, then retry the read.",
        )
    if "coverage" in name or "calculationunavailable" in name:
        return ErrorDetail(
            code="CALCULATION_UNAVAILABLE",
            message="The calculation is unavailable at the current data coverage.",
            correlation_id=correlation_id,
            retryable=False,
            remediation="Review data-quality warnings and source coverage before retrying.",
        )
    if "partial" in name or "incomplete" in name:
        return ErrorDetail(
            code="DATA_INCOMPLETE",
            message="The requested data is partial or incomplete.",
            correlation_id=correlation_id,
            retryable=True,
            remediation="Review quality metadata and retry after a successful read-only refresh.",
        )
    if isinstance(exc, TimeoutError | ConnectionError):
        return ErrorDetail(
            code="PROVIDER_UNAVAILABLE",
            message="The upstream read-only provider is temporarily unavailable.",
            correlation_id=correlation_id,
            retryable=True,
            remediation="Retry later; no broker mutation was attempted.",
        )
    return ErrorDetail(
        code="INTERNAL_ERROR",
        message="The request could not be completed safely.",
        correlation_id=correlation_id,
        retryable=True,
        remediation="Retry once, then use the correlation ID with server-side support logs.",
    )


def _opaque_ref(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]
