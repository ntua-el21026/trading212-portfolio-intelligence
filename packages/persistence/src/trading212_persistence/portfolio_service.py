"""Owner-scoped PostgreSQL implementation of the canonical portfolio service."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.ingestion import IngestionCapability, RunMode
from trading212_application.services import (
    PortfolioService,
    RefreshQueue,
    RefreshUnavailableError,
)
from trading212_application.views import (
    AccountSummaryView,
    AccountView,
    ActivityView,
    AllocationView,
    Availability,
    DividendView,
    MetricView,
    OrderView,
    Page,
    PositionView,
    QualityView,
    ReconciliationIssueView,
    ReconciliationView,
    RefreshRunView,
    SnapshotComparisonView,
    SnapshotView,
    ViewQuality,
    paginate,
)
from trading212_domain import quantize_boundary
from trading212_security.principals import Authorizer, Principal, Scope

from .models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    DividendModel,
    IngestionCheckpointModel,
    IngestionRunModel,
    InstrumentModel,
    ListingModel,
    OrderObservationModel,
    PortfolioSnapshotModel,
    ReconciliationDiscrepancyModel,
    ReconciliationRunModel,
    SnapshotCashModel,
    SnapshotPositionModel,
    TransactionModel,
)

_ACCOUNTING_VERSION = "phase1-core-accounting/1.0.0"
_COMPARISON_VERSION = "phase1-snapshot-change/1.0.0"
_FRESHNESS_SECONDS = 900
_MAX_COLLECTION_ROWS = 10_000
_RATIO_QUANTUM = Decimal("0.000000000000000001")


class PostgresPortfolioService(PortfolioService):
    """Read normalized facts and immutable snapshots; never provider DTOs."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        clock: Callable[[], datetime] | None = None,
        refresh_queue: RefreshQueue | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._refresh_queue = refresh_queue
        self._authorizer = Authorizer()

    async def owner_for_account(self, account_id: str) -> str | None:
        try:
            account_uuid = UUID(account_id)
        except (TypeError, ValueError, AttributeError):
            return None

        def read() -> str | None:
            with self._sessions() as session:
                value = session.scalar(
                    select(BrokerConnectionModel.owner_id)
                    .join(BrokerAccountModel)
                    .where(BrokerAccountModel.id == account_uuid)
                )
                return None if value is None else str(value)

        return await asyncio.to_thread(read)

    async def _read_access(self, principal: Principal, account_id: str, scope: Scope) -> UUID:
        self._authorizer.require_scope(principal, scope, now=_utc(self._clock()))
        await self._authorizer.require_account(principal, account_id, self)
        return _uuid(account_id, "account_id")

    async def list_accounts(self, principal: Principal) -> tuple[AccountView, ...]:
        self._authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=_utc(self._clock()))
        owner_id = _uuid(principal.owner_id, "owner_id")

        def read() -> tuple[AccountView, ...]:
            with self._sessions() as session:
                rows = session.execute(
                    select(BrokerAccountModel, BrokerConnectionModel)
                    .join(BrokerConnectionModel)
                    .where(BrokerConnectionModel.owner_id == owner_id)
                    .order_by(BrokerAccountModel.id)
                    .limit(100)
                ).all()
                return tuple(_account_view(account, connection) for account, connection in rows)

        return await asyncio.to_thread(read)

    async def get_account(self, principal: Principal, account_id: str) -> AccountView:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)

        def read() -> AccountView:
            with self._sessions() as session:
                row = session.execute(
                    select(BrokerAccountModel, BrokerConnectionModel)
                    .join(BrokerConnectionModel)
                    .where(BrokerAccountModel.id == account_uuid)
                ).one_or_none()
                if row is None:
                    raise LookupError("account not found")
                return _account_view(*row)

        return await asyncio.to_thread(read)

    async def get_summary(self, principal: Principal, account_id: str) -> AccountSummaryView:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)

        def read() -> AccountSummaryView:
            with self._sessions() as session:
                account_row = session.execute(
                    select(BrokerAccountModel, BrokerConnectionModel)
                    .join(BrokerConnectionModel)
                    .where(BrokerAccountModel.id == account_uuid)
                ).one_or_none()
                if account_row is None:
                    raise LookupError("account not found")
                account = _account_view(*account_row)
                snapshot = _latest_snapshot(session, account_uuid)
                if snapshot is None:
                    unavailable = _metric(
                        None,
                        account.reporting_currency,
                        "canonical snapshot not available",
                        provenance=("coverage_gate",),
                        unavailable_reason="A completed canonical snapshot is required.",
                    )
                    return AccountSummaryView(
                        account=account,
                        total_value=unavailable,
                        cash_balance=unavailable,
                        invested_value=unavailable,
                        net_contributions=unavailable,
                        dividends_received=unavailable,
                        realized_profit_loss=unavailable,
                        unrealized_profit_loss=unavailable,
                        quality=_quality(
                            ViewQuality.PARTIAL,
                            as_of=account_row[0].last_seen_at,
                            source_at=account_row[0].last_seen_at,
                            warnings=("No canonical portfolio snapshot is available.",),
                            missing=("portfolio_snapshot",),
                        ),
                        position_count=0,
                    )
                currency = snapshot.reporting_currency
                positions = tuple(
                    session.scalars(
                        select(SnapshotPositionModel).where(
                            SnapshotPositionModel.snapshot_id == snapshot.id
                        )
                    )
                )
                dividends = session.scalar(
                    select(func.sum(DividendModel.net_amount)).where(
                        DividendModel.broker_account_id == account_uuid,
                        DividendModel.currency == currency,
                    )
                )
                foreign_dividends = (
                    session.scalar(
                        select(func.count())
                        .select_from(DividendModel)
                        .where(
                            DividendModel.broker_account_id == account_uuid,
                            DividendModel.currency != currency,
                        )
                    )
                    or 0
                )
                dividend_checkpoint = session.scalar(
                    select(IngestionCheckpointModel).where(
                        IngestionCheckpointModel.broker_account_id == account_uuid,
                        IngestionCheckpointModel.capability == IngestionCapability.DIVIDENDS.value,
                    )
                )
                dividend_coverage_complete = bool(
                    dividend_checkpoint is not None and dividend_checkpoint.coverage_complete
                )
                dividend_value = (
                    (dividends or Decimal(0))
                    if dividend_coverage_complete and foreign_dividends == 0
                    else None
                )
                if not dividend_coverage_complete:
                    dividend_unavailable_reason = (
                        "Complete dividend-history coverage is unavailable."
                    )
                elif foreign_dividends > 0:
                    dividend_unavailable_reason = "Dividend FX coverage is incomplete."
                else:
                    dividend_unavailable_reason = None
                unrealized = (
                    sum(
                        (
                            item.unrealized_pnl
                            for item in positions
                            if item.unrealized_pnl is not None
                        ),
                        Decimal(0),
                    )
                    if positions and all(item.unrealized_pnl is not None for item in positions)
                    else None
                )
                return AccountSummaryView(
                    account=account,
                    total_value=_snapshot_metric(
                        snapshot.portfolio_total,
                        currency,
                        "portfolio total",
                        version=snapshot.calculation_version,
                    ),
                    cash_balance=_snapshot_metric(
                        snapshot.cash_total,
                        currency,
                        "cash total",
                        version=snapshot.calculation_version,
                    ),
                    invested_value=_snapshot_metric(
                        snapshot.invested_total,
                        currency,
                        "invested position total",
                        version=snapshot.calculation_version,
                    ),
                    net_contributions=_snapshot_metric(
                        snapshot.net_contributions,
                        currency,
                        "covered net external contributions",
                        version=snapshot.calculation_version,
                    ),
                    dividends_received=_metric(
                        dividend_value,
                        currency,
                        "sum of normalized dividends in reporting currency",
                        provenance=("canonical_dividends",),
                        unavailable_reason=dividend_unavailable_reason,
                    ),
                    realized_profit_loss=_metric(
                        None,
                        currency,
                        "coverage-gated realized profit/loss",
                        provenance=("canonical_transactions", "coverage_gate"),
                        unavailable_reason=(
                            "Complete deterministic disposal and acquisition history "
                            "is unavailable."
                        ),
                    ),
                    unrealized_profit_loss=_metric(
                        unrealized,
                        currency,
                        "sum of snapshot position unrealized profit/loss",
                        provenance=("snapshot_positions",),
                        unavailable_reason=(
                            None
                            if unrealized is not None
                            else "At least one position lacks unrealized P/L coverage."
                        ),
                    ),
                    quality=_effective_snapshot_quality(
                        session,
                        snapshot,
                        account_uuid,
                        now=_utc(self._clock()),
                    ),
                    position_count=len(positions),
                )

        return await asyncio.to_thread(read)

    async def list_positions(
        self,
        principal: Principal,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[PositionView]:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)

        def read() -> Page[PositionView]:
            with self._sessions() as session:
                snapshot = _require_snapshot(session, account_uuid)
                quality = _effective_snapshot_quality(
                    session,
                    snapshot,
                    account_uuid,
                    now=_utc(self._clock()),
                )
                rows = session.execute(
                    select(SnapshotPositionModel, ListingModel, InstrumentModel)
                    .join(
                        ListingModel,
                        ListingModel.id == SnapshotPositionModel.listing_id,
                    )
                    .join(
                        InstrumentModel,
                        InstrumentModel.id == ListingModel.instrument_id,
                    )
                    .where(SnapshotPositionModel.snapshot_id == snapshot.id)
                    .order_by(ListingModel.ticker, ListingModel.id)
                    .limit(_MAX_COLLECTION_ROWS)
                ).all()
                values = tuple(
                    _position_view(item, listing, instrument, snapshot, quality)
                    for item, listing, instrument in rows
                )
                return paginate(values, cursor=cursor, limit=limit)

        return await asyncio.to_thread(read)

    async def get_position(
        self, principal: Principal, account_id: str, position_id: str
    ) -> PositionView:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        listing_id = _uuid(position_id, "position_id")

        def read() -> PositionView:
            with self._sessions() as session:
                snapshot = _require_snapshot(session, account_uuid)
                row = session.execute(
                    select(SnapshotPositionModel, ListingModel, InstrumentModel)
                    .join(
                        ListingModel,
                        ListingModel.id == SnapshotPositionModel.listing_id,
                    )
                    .join(
                        InstrumentModel,
                        InstrumentModel.id == ListingModel.instrument_id,
                    )
                    .where(
                        SnapshotPositionModel.snapshot_id == snapshot.id,
                        SnapshotPositionModel.listing_id == listing_id,
                    )
                ).one_or_none()
                if row is None:
                    raise LookupError("position not found")
                item, listing, instrument = row
                return _position_view(
                    item,
                    listing,
                    instrument,
                    snapshot,
                    _effective_snapshot_quality(
                        session,
                        snapshot,
                        account_uuid,
                        now=_utc(self._clock()),
                    ),
                )

        return await asyncio.to_thread(read)

    async def list_activity(
        self,
        principal: Principal,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[ActivityView]:
        account_uuid = await self._read_access(principal, account_id, Scope.ACTIVITY_READ)

        def read() -> Page[ActivityView]:
            with self._sessions() as session:
                quality = _fallback_quality(
                    session,
                    account_uuid,
                    _latest_snapshot(session, account_uuid),
                    _latest_run_time(session, account_uuid),
                    now=_utc(self._clock()),
                )
                rows = session.execute(
                    select(TransactionModel, ListingModel)
                    .outerjoin(ListingModel)
                    .where(TransactionModel.broker_account_id == account_uuid)
                    .order_by(TransactionModel.occurred_at.desc(), TransactionModel.id)
                    .limit(_MAX_COLLECTION_ROWS)
                ).all()
                return paginate(
                    tuple(_activity_view(item, listing, quality) for item, listing in rows),
                    cursor=cursor,
                    limit=limit,
                )

        return await asyncio.to_thread(read)

    async def list_dividends(
        self,
        principal: Principal,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[DividendView]:
        account_uuid = await self._read_access(principal, account_id, Scope.ACTIVITY_READ)

        def read() -> Page[DividendView]:
            with self._sessions() as session:
                quality = _fallback_quality(
                    session,
                    account_uuid,
                    _latest_snapshot(session, account_uuid),
                    _latest_run_time(session, account_uuid),
                    now=_utc(self._clock()),
                )
                rows = session.execute(
                    select(DividendModel, ListingModel)
                    .outerjoin(ListingModel)
                    .where(DividendModel.broker_account_id == account_uuid)
                    .order_by(DividendModel.paid_on.desc(), DividendModel.id)
                    .limit(_MAX_COLLECTION_ROWS)
                ).all()
                return paginate(
                    tuple(_dividend_view(item, listing, quality) for item, listing in rows),
                    cursor=cursor,
                    limit=limit,
                )

        return await asyncio.to_thread(read)

    async def list_orders(
        self,
        principal: Principal,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[OrderView]:
        account_uuid = await self._read_access(principal, account_id, Scope.ACTIVITY_READ)

        def read() -> Page[OrderView]:
            with self._sessions() as session:
                quality = _fallback_quality(
                    session,
                    account_uuid,
                    _latest_snapshot(session, account_uuid),
                    _latest_run_time(session, account_uuid),
                    now=_utc(self._clock()),
                )
                rows = session.execute(
                    select(OrderObservationModel, ListingModel)
                    .join(ListingModel)
                    .where(OrderObservationModel.broker_account_id == account_uuid)
                    .distinct(OrderObservationModel.provider_order_id)
                    .order_by(
                        OrderObservationModel.provider_order_id,
                        OrderObservationModel.observed_at.desc(),
                    )
                    .limit(_MAX_COLLECTION_ROWS)
                ).all()
                values = sorted(
                    (_order_view(item, listing, quality) for item, listing in rows),
                    key=lambda item: item.created_at,
                    reverse=True,
                )
                return paginate(values, cursor=cursor, limit=limit)

        return await asyncio.to_thread(read)

    async def get_allocation(
        self, principal: Principal, account_id: str
    ) -> tuple[AllocationView, ...]:
        positions = await self.list_positions(
            principal,
            account_id,
            cursor=None,
            limit=100,
        )
        if positions.next_cursor is not None:
            raise ValueError("direct allocation exceeds the Phase 1 bounded position set")
        account_uuid = _uuid(account_id, "account_id")

        def read_cash() -> tuple[AllocationView, ...]:
            with self._sessions() as session:
                snapshot = _require_snapshot(session, account_uuid)
                rows = tuple(
                    session.scalars(
                        select(SnapshotCashModel)
                        .where(SnapshotCashModel.snapshot_id == snapshot.id)
                        .order_by(SnapshotCashModel.currency)
                    )
                )
                return tuple(
                    AllocationView(
                        id=f"cash:{item.currency}",
                        label=f"Cash ({item.currency})",
                        asset_type="cash",
                        market_value=_snapshot_metric(
                            item.amount,
                            item.currency,
                            "canonical snapshot cash component",
                            version=snapshot.calculation_version,
                            provenance=_stored_provenance(
                                item.provenance, fallback="snapshot_cash"
                            ),
                        ),
                        weight=_weight(item.amount, snapshot.portfolio_total),
                        weight_availability=(
                            Availability.AVAILABLE
                            if _weight(item.amount, snapshot.portfolio_total) is not None
                            else Availability.UNAVAILABLE
                        ),
                    )
                    for item in rows
                )

        cash = await asyncio.to_thread(read_cash)
        position_rows = tuple(
            AllocationView(
                id=item.id,
                label=item.name,
                asset_type=item.instrument_type,
                market_value=item.market_value,
                weight=item.direct_weight,
                weight_availability=(
                    Availability.AVAILABLE
                    if item.direct_weight is not None
                    else Availability.UNAVAILABLE
                ),
            )
            for item in positions.items
        )
        return position_rows + cash

    async def list_snapshots(
        self,
        principal: Principal,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[SnapshotView]:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)

        def read() -> Page[SnapshotView]:
            with self._sessions() as session:
                rows = tuple(
                    session.scalars(
                        select(PortfolioSnapshotModel)
                        .where(PortfolioSnapshotModel.broker_account_id == account_uuid)
                        .order_by(
                            PortfolioSnapshotModel.valuation_at.desc(),
                            PortfolioSnapshotModel.id,
                        )
                        .limit(_MAX_COLLECTION_ROWS)
                    )
                )
                now = _utc(self._clock())
                latest_id = rows[0].id if rows else None
                return paginate(
                    tuple(
                        _snapshot_view(
                            item,
                            now=now,
                            quality=(
                                _effective_snapshot_quality(
                                    session,
                                    item,
                                    account_uuid,
                                    now=now,
                                )
                                if item.id == latest_id
                                else None
                            ),
                        )
                        for item in rows
                    ),
                    cursor=cursor,
                    limit=limit,
                )

        return await asyncio.to_thread(read)

    async def compare_snapshots(
        self,
        principal: Principal,
        account_id: str,
        start_id: str,
        end_id: str,
    ) -> SnapshotComparisonView:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        start_uuid = _uuid(start_id, "start_id")
        end_uuid = _uuid(end_id, "end_id")

        def read() -> SnapshotComparisonView:
            with self._sessions() as session:
                snapshots = {
                    item.id: item
                    for item in session.scalars(
                        select(PortfolioSnapshotModel).where(
                            PortfolioSnapshotModel.broker_account_id == account_uuid,
                            PortfolioSnapshotModel.id.in_((start_uuid, end_uuid)),
                        )
                    )
                }
                if start_uuid not in snapshots or end_uuid not in snapshots:
                    raise LookupError("snapshot not found")
                start = snapshots[start_uuid]
                end = snapshots[end_uuid]
                if end.valuation_at < start.valuation_at:
                    raise ValueError("ending snapshot precedes beginning snapshot")
                currency = start.reporting_currency
                if end.reporting_currency != currency:
                    raise ValueError("snapshot reporting currencies differ")
                total_change = _subtract(end.portfolio_total, start.portfolio_total)
                flows = _subtract(end.net_contributions, start.net_contributions)
                investment = _subtract(total_change, flows)
                residual = (
                    _subtract(total_change, _add(investment, flows))
                    if investment is not None and flows is not None
                    else None
                )
                latest = _latest_snapshot(session, account_uuid)
                start_quality = _snapshot_quality(start, now=_utc(self._clock()))
                end_quality = (
                    _effective_snapshot_quality(
                        session,
                        end,
                        account_uuid,
                        now=_utc(self._clock()),
                    )
                    if latest is not None and latest.id == end.id
                    else _snapshot_quality(end, now=_utc(self._clock()))
                )
                return SnapshotComparisonView(
                    start=_snapshot_view(
                        start,
                        now=_utc(self._clock()),
                        quality=start_quality,
                    ),
                    end=_snapshot_view(
                        end,
                        now=_utc(self._clock()),
                        quality=end_quality,
                    ),
                    value_change=_comparison_metric(
                        total_change, currency, "ending value minus beginning value"
                    ),
                    net_external_flows=_comparison_metric(
                        flows,
                        currency,
                        "change in covered net external contributions",
                    ),
                    investment_result=_comparison_metric(
                        investment,
                        currency,
                        "value change less covered external flows",
                    ),
                    reconciliation_residual=_comparison_metric(
                        residual,
                        currency,
                        "snapshot accounting identity residual",
                    ),
                    quality=_comparison_quality(start_quality, end_quality),
                )

        return await asyncio.to_thread(read)

    async def get_reconciliation(self, principal: Principal, account_id: str) -> ReconciliationView:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)

        def read() -> ReconciliationView:
            with self._sessions() as session:
                run = session.scalar(
                    select(ReconciliationRunModel)
                    .where(ReconciliationRunModel.broker_account_id == account_uuid)
                    .order_by(ReconciliationRunModel.as_of.desc(), ReconciliationRunModel.id)
                    .limit(1)
                )
                if run is None:
                    observed = _latest_run_time(session, account_uuid) or _utc(self._clock())
                    return ReconciliationView(
                        status="not_evaluated",
                        evaluated_at=observed,
                        algorithm_version="phase1-reconciliation/1.0.0",
                        tolerance_version="phase1-tolerance/1.0.0",
                        issues=(),
                        quality=_quality(
                            ViewQuality.PARTIAL,
                            as_of=observed,
                            source_at=observed,
                            warnings=("Reconciliation has not completed.",),
                            missing=("reconciliation_run",),
                        ),
                    )
                issues = tuple(
                    _reconciliation_issue(item)
                    for item in session.scalars(
                        select(ReconciliationDiscrepancyModel)
                        .where(ReconciliationDiscrepancyModel.reconciliation_run_id == run.id)
                        .order_by(
                            ReconciliationDiscrepancyModel.severity.desc(),
                            ReconciliationDiscrepancyModel.id,
                        )
                    )
                )
                return ReconciliationView(
                    status=run.status,
                    evaluated_at=run.as_of,
                    algorithm_version=run.algorithm_version,
                    tolerance_version=run.tolerance_version,
                    issues=issues,
                    quality=_quality(
                        _view_quality(run.quality_state),
                        as_of=run.as_of,
                        source_at=run.coverage_end_at,
                        warnings=_warning_text(run.warnings),
                        missing=tuple(run.coverage_gaps),
                    ),
                )

        return await asyncio.to_thread(read)

    async def refresh(
        self,
        principal: Principal,
        account_id: str,
        *,
        mode: RunMode,
        capabilities: tuple[IngestionCapability, ...],
        idempotency_key: str,
        correlation_id: str,
    ) -> RefreshRunView:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_REFRESH)
        if self._refresh_queue is None:
            raise RefreshUnavailableError("durable refresh queue is not configured")
        return await self._refresh_queue.enqueue(
            owner_id=principal.owner_id,
            account_id=account_id,
            mode=mode,
            capabilities=capabilities,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    async def get_refresh(self, principal: Principal, run_id: str) -> RefreshRunView:
        self._authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=_utc(self._clock()))
        if self._refresh_queue is not None:
            return await self._refresh_queue.get(owner_id=principal.owner_id, run_id=run_id)
        run_uuid = _uuid(run_id, "run_id")
        owner_uuid = _uuid(principal.owner_id, "owner_id")

        def read() -> RefreshRunView:
            with self._sessions() as session:
                run = session.scalar(
                    select(IngestionRunModel)
                    .join(BrokerAccountModel)
                    .join(BrokerConnectionModel)
                    .where(
                        IngestionRunModel.id == run_uuid,
                        BrokerConnectionModel.owner_id == owner_uuid,
                    )
                )
                if run is None:
                    raise LookupError("refresh run not found")
                capabilities = tuple(
                    str(item.get("capability"))
                    for item in (run.warnings or [])
                    if item.get("capability")
                )
                return RefreshRunView(
                    id=str(run.id),
                    account_id=str(run.broker_account_id),
                    status=run.status,
                    requested_at=run.started_at,
                    completed_at=run.completed_at,
                    correlation_id=run.correlation_id,
                    capabilities=capabilities,
                    warnings=_warning_text(run.warnings),
                )

        return await asyncio.to_thread(read)


def _uuid(value: str, name: str) -> UUID:
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _account_view(account: BrokerAccountModel, connection: BrokerConnectionModel) -> AccountView:
    return AccountView(
        id=str(account.id),
        display_name=account.display_name,
        provider=connection.provider,
        environment=connection.environment,
        account_type=account.account_type,
        reporting_currency=account.base_currency,
        connection_state=(
            "connected_read_only" if connection.status == "active" else connection.status
        ),
        last_refresh_at=account.last_seen_at,
    )


def _latest_snapshot(session: Session, account_id: UUID) -> PortfolioSnapshotModel | None:
    return session.scalar(
        select(PortfolioSnapshotModel)
        .where(PortfolioSnapshotModel.broker_account_id == account_id)
        .order_by(PortfolioSnapshotModel.valuation_at.desc(), PortfolioSnapshotModel.id)
        .limit(1)
    )


def _require_snapshot(session: Session, account_id: UUID) -> PortfolioSnapshotModel:
    value = _latest_snapshot(session, account_id)
    if value is None:
        raise LookupError("portfolio snapshot not found")
    return value


def _latest_run_time(session: Session, account_id: UUID) -> datetime | None:
    return session.scalar(
        select(IngestionRunModel.completed_at)
        .where(IngestionRunModel.broker_account_id == account_id)
        .order_by(IngestionRunModel.completed_at.desc().nullslast())
        .limit(1)
    )


def _latest_terminal_run(session: Session, account_id: UUID) -> IngestionRunModel | None:
    return session.scalar(
        select(IngestionRunModel)
        .where(
            IngestionRunModel.broker_account_id == account_id,
            IngestionRunModel.completed_at.is_not(None),
            IngestionRunModel.status.in_(("succeeded", "partial", "failed", "cancelled")),
        )
        .order_by(IngestionRunModel.completed_at.desc(), IngestionRunModel.id.desc())
        .limit(1)
    )


def _view_quality(value: str) -> ViewQuality:
    try:
        return ViewQuality(value)
    except ValueError:
        return ViewQuality.FAILED


def _quality(
    state: ViewQuality,
    *,
    as_of: datetime,
    source_at: datetime,
    warnings: Sequence[str] = (),
    missing: Sequence[str] = (),
) -> QualityView:
    return QualityView(
        state=state,
        as_of=_utc(as_of),
        source_timestamp=_utc(source_at),
        freshness_threshold_seconds=_FRESHNESS_SECONDS,
        warnings=tuple(warnings),
        missing_inputs=tuple(missing),
    )


def _snapshot_quality(snapshot: PortfolioSnapshotModel, *, now: datetime) -> QualityView:
    gaps = snapshot.coverage.get("gaps", []) if snapshot.coverage else []
    state = _view_quality(snapshot.quality_state)
    warnings = list(_warning_text(snapshot.warnings))
    if state is ViewQuality.FRESH and now - snapshot.source_cutoff_at > timedelta(
        seconds=_FRESHNESS_SECONDS
    ):
        state = ViewQuality.STALE
        warnings.append("Canonical source observations exceed the freshness threshold.")
    return _quality(
        state,
        as_of=snapshot.valuation_at,
        source_at=snapshot.source_cutoff_at,
        warnings=warnings,
        missing=tuple(str(value) for value in gaps),
    )


def _effective_snapshot_quality(
    session: Session,
    snapshot: PortfolioSnapshotModel,
    account_id: UUID,
    *,
    now: datetime,
) -> QualityView:
    """Overlay a newer unsuccessful refresh on the retained canonical snapshot.

    Retaining the last valid snapshot is intentional, but presenting that snapshot as
    fresh after a newer partial or failed publication would be misleading. Historical
    snapshots remain immutable; this overlay is applied only to current-facing reads.
    """

    base = _overlay_reconciliation_quality(
        session,
        account_id,
        snapshot,
        _snapshot_quality(snapshot, now=now),
    )
    run = _latest_terminal_run(session, account_id)
    if (
        run is None
        or run.status == "succeeded"
        or run.completed_at is None
        or run.completed_at < snapshot.valuation_at
    ):
        return base

    failed_steps = tuple(
        item
        for item in (run.warnings or ())
        if isinstance(item, dict)
        and isinstance(item.get("capability"), str)
        and item.get("status") != "succeeded"
    )
    missing = tuple(
        dict.fromkeys(
            (
                *(str(item["capability"]) for item in failed_steps),
                *(base.missing_inputs),
            )
        )
    )
    if not missing:
        missing = ("latest_refresh",)
    step_warnings = tuple(
        f"{item['capability']} refresh ended {item.get('status', run.status)}"
        for item in failed_steps
    )
    state = (
        base.state
        if base.state in {ViewQuality.UNRECONCILED, ViewQuality.FAILED}
        else ViewQuality.PARTIAL
    )
    return _quality(
        state,
        as_of=base.as_of,
        source_at=base.source_timestamp,
        warnings=tuple(
            dict.fromkeys(
                (
                    *base.warnings,
                    f"Latest refresh ended {run.status}; retained prior canonical snapshot.",
                    *step_warnings,
                )
            )
        ),
        missing=missing,
    )


def _overlay_reconciliation_quality(
    session: Session,
    account_id: UUID,
    snapshot: PortfolioSnapshotModel,
    base: QualityView,
) -> QualityView:
    """Propagate the latest applicable reconciliation gate to current reads."""

    run = session.scalar(
        select(ReconciliationRunModel)
        .where(ReconciliationRunModel.broker_account_id == account_id)
        .order_by(ReconciliationRunModel.as_of.desc(), ReconciliationRunModel.id.desc())
        .limit(1)
    )
    if run is None or run.as_of < snapshot.valuation_at:
        return base
    severity = {
        ViewQuality.FRESH: 0,
        ViewQuality.STALE: 1,
        ViewQuality.ESTIMATED: 2,
        ViewQuality.PARTIAL: 3,
        ViewQuality.UNRECONCILED: 4,
        ViewQuality.FAILED: 5,
    }
    reconciliation_state = _view_quality(run.quality_state)
    state = max((base.state, reconciliation_state), key=severity.__getitem__)
    warning = (
        f"Latest reconciliation has {run.discrepancy_count} open discrepancy records."
        if run.discrepancy_count
        else None
    )
    return _quality(
        state,
        as_of=max(base.as_of, run.as_of),
        source_at=max(base.source_timestamp, run.coverage_end_at),
        warnings=tuple(
            dict.fromkeys(
                (
                    *base.warnings,
                    *_warning_text(run.warnings),
                    *((warning,) if warning is not None else ()),
                )
            )
        ),
        missing=tuple(dict.fromkeys((*base.missing_inputs, *run.coverage_gaps))),
    )


def _fallback_quality(
    session: Session,
    account_id: UUID,
    snapshot: PortfolioSnapshotModel | None,
    observed_at: datetime | None,
    *,
    now: datetime,
) -> QualityView:
    if snapshot is not None:
        return _effective_snapshot_quality(session, snapshot, account_id, now=now)
    observed = observed_at or datetime(1970, 1, 1, tzinfo=UTC)
    return _quality(
        ViewQuality.PARTIAL,
        as_of=observed,
        source_at=observed,
        warnings=("No canonical snapshot is available.",),
        missing=("portfolio_snapshot",),
    )


def _warning_text(values: Sequence[object]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str):
            result.append(value[:500])
        elif isinstance(value, dict):
            text = value.get("message") or value.get("code")
            if isinstance(text, str):
                result.append(text[:500])
            nested = value.get("warnings")
            if isinstance(nested, list):
                result.extend(str(item)[:500] for item in nested)
    return tuple(dict.fromkeys(result))[:20]


def _stored_provenance(value: object, *, fallback: str) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return (fallback,)
    result: list[str] = []
    mapping_version = value.get("mapping_version")
    origin = value.get("origin")
    source_ids = value.get("source_record_ids")
    if isinstance(mapping_version, str):
        result.append(f"mapping:{mapping_version}")
    if isinstance(origin, str):
        result.append(f"origin:{origin}")
    if isinstance(source_ids, list):
        result.extend(f"source_record:{source_id}" for source_id in source_ids[:20])
    return tuple(result) or (fallback,)


def _metric(
    value: Decimal | None,
    currency: str,
    methodology: str,
    *,
    provenance: Sequence[str],
    unavailable_reason: str | None = None,
    version: str = _ACCOUNTING_VERSION,
) -> MetricView:
    return MetricView(
        value=value,
        currency=currency,
        availability=Availability.AVAILABLE if value is not None else Availability.UNAVAILABLE,
        calculation_version=version,
        methodology=methodology,
        provenance=tuple(provenance),
        unavailable_reason=unavailable_reason if value is None else None,
    )


def _snapshot_metric(
    value: Decimal | None,
    currency: str,
    methodology: str,
    *,
    version: str,
    provenance: Sequence[str] = ("portfolio_snapshots",),
) -> MetricView:
    return _metric(
        value,
        currency,
        methodology,
        provenance=provenance,
        version=version,
        unavailable_reason=(
            None if value is not None else "Required canonical snapshot inputs are incomplete."
        ),
    )


def _comparison_metric(value: Decimal | None, currency: str, methodology: str) -> MetricView:
    return _metric(
        value,
        currency,
        methodology,
        provenance=("portfolio_snapshots",),
        unavailable_reason=(
            None if value is not None else "Required snapshot or flow coverage is incomplete."
        ),
        version=_COMPARISON_VERSION,
    )


def _position_view(
    item: SnapshotPositionModel,
    listing: ListingModel,
    instrument: InstrumentModel,
    snapshot: PortfolioSnapshotModel,
    quality: QualityView,
) -> PositionView:
    return PositionView(
        id=str(listing.id),
        ticker=listing.ticker,
        name=instrument.canonical_name,
        instrument_type=instrument.instrument_type,
        quantity=item.quantity,
        trading_currency=listing.trading_currency,
        current_price=item.current_price,
        market_value=_snapshot_metric(
            item.market_value,
            item.currency,
            "snapshot position value",
            version=snapshot.calculation_version,
            provenance=_stored_provenance(item.provenance, fallback="snapshot_positions"),
        ),
        provider_cost_basis=_metric(
            item.cost_basis,
            item.currency,
            "provider-reported or deterministic position cost basis",
            provenance=("snapshot_positions", item.value_origin),
            unavailable_reason=(
                None
                if item.cost_basis is not None
                else "Position cost-basis coverage is incomplete."
            ),
        ),
        provider_unrealized_profit_loss=_metric(
            item.unrealized_pnl,
            item.currency,
            "provider-reported or deterministic position unrealized profit/loss",
            provenance=("snapshot_positions", item.value_origin),
            unavailable_reason=(
                None
                if item.unrealized_pnl is not None
                else "Position unrealized profit/loss coverage is incomplete."
            ),
        ),
        direct_weight=_weight(item.market_value, snapshot.portfolio_total),
        quality=quality,
    )


def _activity_view(
    item: TransactionModel, listing: ListingModel | None, quality: QualityView
) -> ActivityView:
    activity_type = item.transaction_type.casefold()
    if activity_type == "deposit":
        direction = "external_inflow"
    elif activity_type == "withdrawal":
        direction = "external_outflow"
    elif activity_type in {"buy", "sell"}:
        direction = "internal_exchange"
    else:
        direction = "credit" if item.net_cash_amount >= 0 else "debit"
    return ActivityView(
        id=str(item.id),
        occurred_at=item.occurred_at,
        activity_type=activity_type,
        direction=direction,
        amount=_metric(
            item.net_cash_amount,
            item.currency,
            "normalized canonical transaction cash effect",
            provenance=("transactions", str(item.source_record_id)),
        ),
        ticker=None if listing is None else listing.ticker,
        quantity=item.quantity,
        description=f"{activity_type.replace('_', ' ').title()} activity",
        quality=quality,
    )


def _dividend_view(
    item: DividendModel, listing: ListingModel | None, quality: QualityView
) -> DividendView:
    return DividendView(
        id=str(item.id),
        paid_on=item.paid_on,
        ticker="UNKNOWN" if listing is None else listing.ticker,
        net_amount=_metric(
            item.net_amount,
            item.currency,
            "normalized net dividend",
            provenance=("dividends", str(item.source_record_id)),
        ),
        gross_amount=_metric(
            item.gross_amount,
            item.currency,
            "provider-reported gross dividend",
            provenance=("dividends",),
            unavailable_reason=(
                None if item.gross_amount is not None else "Gross dividend is unavailable."
            ),
        ),
        withholding_tax=_metric(
            item.withholding_tax,
            item.currency,
            "provider-reported withholding tax",
            provenance=("dividends",),
            unavailable_reason=(
                None if item.withholding_tax is not None else "Withholding tax is unavailable."
            ),
        ),
        quantity=item.quantity,
        quality=quality,
    )


def _order_view(
    item: OrderObservationModel, listing: ListingModel, quality: QualityView
) -> OrderView:
    value = item.filled_value if item.filled_value is not None else item.requested_value
    currency = item.currency or listing.trading_currency
    return OrderView(
        id=str(item.id),
        created_at=item.submitted_at or item.observed_at,
        ticker=listing.ticker,
        side=item.side,
        order_type=item.order_type,
        status=item.status,
        quantity=item.requested_quantity,
        filled_quantity=item.filled_quantity,
        limit_price=None,
        observed_value=_metric(
            value,
            currency,
            "read-only provider order observation",
            provenance=("order_observations", str(item.source_record_id)),
            unavailable_reason=None if value is not None else "Order value is unavailable.",
        ),
        quality=quality,
    )


def _snapshot_view(
    snapshot: PortfolioSnapshotModel,
    *,
    now: datetime,
    quality: QualityView | None = None,
) -> SnapshotView:
    return SnapshotView(
        id=str(snapshot.id),
        valuation_at=snapshot.valuation_at,
        source_cutoff_at=snapshot.source_cutoff_at,
        reporting_currency=snapshot.reporting_currency,
        total_value=_snapshot_metric(
            snapshot.portfolio_total,
            snapshot.reporting_currency,
            "portfolio total",
            version=snapshot.calculation_version,
        ),
        cash_value=_snapshot_metric(
            snapshot.cash_total,
            snapshot.reporting_currency,
            "cash total",
            version=snapshot.calculation_version,
        ),
        invested_value=_snapshot_metric(
            snapshot.invested_total,
            snapshot.reporting_currency,
            "invested position total",
            version=snapshot.calculation_version,
        ),
        net_contributions=_snapshot_metric(
            snapshot.net_contributions,
            snapshot.reporting_currency,
            "covered net external contributions",
            version=snapshot.calculation_version,
        ),
        quality=quality or _snapshot_quality(snapshot, now=now),
    )


def _reconciliation_issue(item: ReconciliationDiscrepancyModel) -> ReconciliationIssueView:
    return ReconciliationIssueView(
        id=str(item.id),
        issue_type=item.discrepancy_type,
        severity=item.severity,
        status=item.resolution_state,
        summary=item.downstream_effect,
        expected_value=item.expected_value,
        observed_value=item.observed_value,
        residual=item.residual,
        tolerance=item.tolerance,
        currency=item.currency,
    )


def _comparison_quality(start: QualityView, end: QualityView) -> QualityView:
    severity = {
        ViewQuality.FRESH: 0,
        ViewQuality.STALE: 1,
        ViewQuality.ESTIMATED: 2,
        ViewQuality.PARTIAL: 3,
        ViewQuality.UNRECONCILED: 4,
        ViewQuality.FAILED: 5,
    }
    state = max(
        (
            start.state,
            end.state,
        ),
        key=severity.__getitem__,
    )
    return _quality(
        state,
        as_of=end.as_of,
        source_at=end.source_timestamp,
        warnings=tuple(dict.fromkeys((*start.warnings, *end.warnings))),
        missing=tuple(dict.fromkeys((*start.missing_inputs, *end.missing_inputs))),
    )


def _weight(value: Decimal | None, total: Decimal | None) -> Decimal | None:
    if value is None or total is None or total <= 0:
        return None
    return quantize_boundary(value / total, _RATIO_QUANTUM)


def _subtract(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return None if left is None or right is None else left - right


def _add(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return None if left is None or right is None else left + right
