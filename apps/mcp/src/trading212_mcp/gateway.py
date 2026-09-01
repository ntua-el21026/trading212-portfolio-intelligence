"""Authorized, bounded MCP composition over canonical application services."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Iterable
from datetime import date
from typing import Any, TypeVar, cast

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel
from trading212_application.queries import (
    ActivityQuery,
    CollectionSnapshotCapacityError,
    CursorValidationError,
    DirectAllocationQuery,
    DividendSummaryQuery,
    PageQuery,
    PositionQuery,
)
from trading212_application.queries import (
    ActivityTypeFilter as ApplicationActivityTypeFilter,
)
from trading212_application.queries import (
    PositionSort as ApplicationPositionSort,
)
from trading212_application.services import PortfolioService
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
    CheckpointQuality,
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
    RefreshRunQuality,
    RefreshStepQuality,
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
                    discrepancy_count=reconciliation.discrepancy_count,
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
            if snapshot_id is not None:
                detail, account = await asyncio.gather(
                    self._service.get_snapshot_detail(principal, account_id, snapshot_id),
                    self._service.get_account(principal, account_id),
                )
            else:
                snapshots, account = await asyncio.gather(
                    self._service.list_snapshots(principal, account_id, query=PageQuery(limit=1)),
                    self._service.get_account(principal, account_id),
                )
                if not snapshots.items:
                    raise LookupError("snapshot not found")
                detail = await self._service.get_snapshot_detail(
                    principal,
                    account_id,
                    snapshots.items[0].id,
                )
            selected = detail.snapshot
            synthetic = account.provider == "synthetic" or account.environment == "synthetic"
            snapshot_quality = quality(selected.quality)
            data = SnapshotData(
                id=safe_text(selected.id, maximum=255),
                valuation_at=selected.valuation_at,
                source_cutoff_at=selected.source_cutoff_at,
                reporting_currency=selected.reporting_currency,
                total_value=metric(selected.total_value),
                cash_value=metric(selected.cash_value),
                invested_value=metric(selected.invested_value),
                net_contributions=metric(selected.net_contributions),
                dividends_received=metric(detail.dividends_received),
                realized_profit_loss=metric(detail.realized_profit_loss),
                unrealized_profit_loss=metric(detail.unrealized_profit_loss),
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
            selected, summary = await asyncio.gather(
                self._service.list_positions(
                    principal,
                    account_id,
                    query=PositionQuery(
                        cursor=cursor,
                        limit=limit,
                        sort=ApplicationPositionSort(sort.value),
                        search=normalized_search,
                    ),
                ),
                self._service.get_summary(principal, account_id),
            )
            result = PositionsResult(
                data=PositionsData(
                    positions=[position(item) for item in selected.items],
                    sort=sort,
                    search=normalized_search,
                ),
                as_of=summary.quality.as_of,
                reporting_currency=summary.account.reporting_currency,
                data_quality=quality(summary.quality),
                calculation=_calculation(
                    "canonical_positions",
                    summary.total_value.calculation_version,
                    summary.quality.as_of,
                ),
                pagination=Pagination(
                    next_cursor=selected.next_cursor,
                    limit=selected.limit,
                    total=selected.total,
                    truncated=selected.next_cursor is not None,
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
            selected, summary = await asyncio.gather(
                self._service.list_activity(
                    principal,
                    account_id,
                    query=ActivityQuery(
                        cursor=cursor,
                        limit=limit,
                        start_date=start_date,
                        end_date=end_date,
                        activity_type=ApplicationActivityTypeFilter(type_filter.value),
                    ),
                ),
                self._service.get_summary(principal, account_id),
            )
            base_quality = selected.items[0].quality if selected.items else summary.quality
            result = TransactionsResult(
                data=TransactionsData(
                    transactions=[activity(item) for item in selected.items],
                    period_start=start_date,
                    period_end=end_date,
                    type_filter=type_filter,
                ),
                as_of=base_quality.as_of,
                reporting_currency=summary.account.reporting_currency,
                data_quality=quality(base_quality),
                calculation=_calculation(
                    "normalized_activity",
                    "phase1-ledger/1.0.0",
                    base_quality.as_of,
                ),
                pagination=Pagination(
                    next_cursor=selected.next_cursor,
                    limit=selected.limit,
                    total=selected.total,
                    truncated=selected.next_cursor is not None,
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
            summary, account_value = await asyncio.gather(
                self._service.get_dividend_summary(
                    principal,
                    account_id,
                    query=DividendSummaryQuery(
                        start_date=start_date,
                        end_date=end_date,
                        recent_limit=recent_limit,
                    ),
                ),
                self._service.get_account(principal, account_id),
            )
            result = DividendSummaryResult(
                data=DividendSummaryData(
                    period_start=start_date,
                    period_end=end_date,
                    totals_by_currency=[
                        DividendCurrencyTotal(
                            currency=item.currency,
                            net_amount=decimal_string(item.net_amount),
                            gross_amount=(
                                decimal_string(item.gross_amount)
                                if item.gross_amount is not None
                                else None
                            ),
                            withholding_tax=(
                                decimal_string(item.withholding_tax)
                                if item.withholding_tax is not None
                                else None
                            ),
                        )
                        for item in summary.totals
                    ],
                    recent_dividends=[dividend(item) for item in summary.recent],
                    covered_record_count=summary.covered_record_count,
                    totals_truncated=summary.totals_truncated,
                    omitted_currency_count=summary.omitted_currency_count,
                ),
                as_of=summary.quality.as_of,
                reporting_currency=account_value.reporting_currency,
                data_quality=quality(summary.quality),
                calculation=_calculation(
                    "dividend_summary",
                    "phase1-ledger/1.0.0",
                    summary.quality.as_of,
                    assumptions=(
                        "Totals are grouped by currency; no unsourced FX conversion is performed.",
                    ),
                ),
                pagination=Pagination(
                    next_cursor=None,
                    limit=recent_limit,
                    total=summary.covered_record_count,
                    truncated=summary.covered_record_count > recent_limit,
                ),
                error=None,
            )
            return (
                result,
                f"Summarized {summary.covered_record_count} covered dividend observations.",
                {},
            )

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
            allocation_view, summary = await asyncio.gather(
                self._service.get_direct_allocation(
                    principal, account_id, query=DirectAllocationQuery(top_n=top_n)
                ),
                self._service.get_summary(principal, account_id),
            )
            selected = allocation_view.items
            includes_cash = any(item.asset_type.casefold() == "cash" for item in selected)
            result = DirectAllocationResult(
                data=DirectAllocationData(
                    allocations=[allocation(item) for item in selected],
                    returned_count=len(selected),
                    includes_cash=includes_cash,
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
                    total=allocation_view.total,
                    truncated=allocation_view.truncated,
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
            reconciliation, issue_page, account_value = await asyncio.gather(
                self._service.get_reconciliation(principal, account_id),
                self._service.list_reconciliation_discrepancies(
                    principal, account_id, query=PageQuery(limit=issue_limit)
                ),
                self._service.get_account(principal, account_id),
            )
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
                    discrepancy_count=reconciliation.discrepancy_count,
                    issues=[reconciliation_issue(item) for item in issue_page.items],
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
                    total=issue_page.total,
                    truncated=issue_page.next_cursor is not None,
                ),
                error=None,
            )
            return (
                result,
                f"Reconciliation state is {reconciliation.status} "
                f"with {reconciliation.discrepancy_count} discrepancies.",
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
            summary = await self._service.get_data_quality_summary(principal, account_id)

            def run_quality(value: Any) -> RefreshRunQuality:
                return RefreshRunQuality(
                    id=value.id,
                    status=safe_text(value.status, maximum=40),
                    started_at=value.started_at,
                    completed_at=value.completed_at,
                    steps=[
                        RefreshStepQuality(
                            capability=safe_text(step.capability, maximum=100),
                            status=safe_text(step.status, maximum=40),
                            warnings=[safe_text(item, maximum=500) for item in step.warnings],
                        )
                        for step in value.steps
                    ],
                )

            data = DataQualitySummaryData(
                capabilities=[
                    CapabilityQuality(
                        capability=cast(Any, item.capability),
                        data_quality=quality(item.quality),
                    )
                    for item in summary.capabilities
                ],
                failed_or_partial_runs=list(summary.failed_or_partial_runs),
                latest_refresh_run=(
                    None
                    if summary.latest_refresh_run is None
                    else run_quality(summary.latest_refresh_run)
                ),
                latest_runs_by_status=[run_quality(item) for item in summary.latest_runs_by_status],
                checkpoints=[
                    CheckpointQuality(
                        capability=safe_text(item.capability, maximum=100),
                        version=item.version,
                        coverage_start_at=item.coverage_start_at,
                        coverage_end_at=item.coverage_end_at,
                        coverage_complete=item.coverage_complete,
                    )
                    for item in summary.checkpoints
                ],
                latest_snapshot_id=summary.latest_snapshot_id,
                latest_snapshot_source_cutoff_at=summary.latest_snapshot_source_cutoff_at,
                materialization_state=cast(Any, summary.materialization_state),
                reconciliation_status=safe_text(summary.reconciliation_status, maximum=40),
                missing_fx_record_count=summary.missing_fx_record_count,
                unknown_mapping_record_count=summary.unknown_mapping_record_count,
            )
            result = DataQualitySummaryResult(
                data=data,
                as_of=summary.as_of,
                reporting_currency=summary.reporting_currency,
                data_quality=quality(summary.quality),
                calculation=_calculation(
                    "data_quality_summary",
                    "phase1-data-quality/1.0.0",
                    summary.as_of,
                ),
                pagination=None,
                error=None,
            )
            return (
                result,
                f"Retrieved quality states for {len(summary.capabilities)} bounded capabilities.",
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


def _validate_date_range(start_date: date, end_date: date, *, maximum_days: int) -> None:
    if end_date < start_date or (end_date - start_date).days > maximum_days:
        raise ValueError("date range is outside the bounded window")


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
    if isinstance(exc, CursorValidationError):
        return ErrorDetail(
            code="CURSOR_INVALID",
            message="The pagination cursor is invalid.",
            correlation_id=correlation_id,
            retryable=False,
            remediation="Restart pagination from the first page with the same filters.",
        )
    if isinstance(exc, CollectionSnapshotCapacityError):
        return ErrorDetail(
            code="COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
            message="Active pagination capacity is temporarily exhausted.",
            correlation_id=correlation_id,
            retryable=True,
            remediation="Resume an existing cursor or retry after active cursors expire.",
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
