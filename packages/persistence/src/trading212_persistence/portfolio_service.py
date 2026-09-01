"""Owner-scoped PostgreSQL implementation of the canonical portfolio service."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, literal, or_, select, tuple_
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.ingestion import IngestionCapability, RunMode
from trading212_application.performance import (
    CorePerformanceInput,
    PerformanceFlowInput,
    PerformanceSnapshotInput,
    calculate_core_performance,
)
from trading212_application.queries import (
    ActivityQuery,
    CursorCodec,
    CursorValidationError,
    DirectAllocationQuery,
    DividendQuery,
    DividendSummaryQuery,
    InstrumentQuery,
    PageQuery,
    PositionQuery,
    PositionSort,
    canonical_activity_type_membership,
    cursor_binding,
)
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
    BrokerConnectionView,
    CapabilityQualityView,
    CheckpointQualityView,
    DataQualitySummaryView,
    DirectAllocationView,
    DividendCurrencyTotalView,
    DividendSummaryView,
    DividendView,
    InstrumentView,
    MetricView,
    OrderView,
    Page,
    PerformanceSummaryView,
    PositionView,
    QualityView,
    ReconciliationIssueView,
    ReconciliationView,
    RefreshRunQualityView,
    RefreshRunView,
    RefreshStepQualityView,
    SnapshotComparisonView,
    SnapshotDetailView,
    SnapshotView,
    ViewQuality,
)
from trading212_domain import quantize_boundary
from trading212_security.principals import Authorizer, Principal, Scope

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
)
from .models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CashFlowModel,
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
_RATIO_QUANTUM = Decimal("0.000000000000000001")
_COLLECTION_SNAPSHOT_STREAM_BATCH = 1_000
_PERFORMANCE_SUPPORTED_TRANSACTION_TYPES = (
    "buy",
    "sell",
    "deposit",
    "withdrawal",
    "dividend",
    "fee",
    "tax_withholding",
    "interest",
)


class PostgresPortfolioService(PortfolioService):
    """Read normalized facts and immutable snapshots; never provider DTOs."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        refresh_queue: RefreshQueue | None = None,
        cursor_ttl_seconds: int = 3_600,
        max_active_collection_snapshots_per_owner: int = 64,
        max_active_collection_members_per_owner: int = 250_000,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._refresh_queue = refresh_queue
        self._authorizer = Authorizer()
        self._cursor_ttl_seconds = cursor_ttl_seconds
        self._max_active_collection_snapshots_per_owner = max_active_collection_snapshots_per_owner
        self._max_active_collection_members_per_owner = max_active_collection_members_per_owner
        self._cursors = CursorCodec(
            cursor_signing_key,
            clock=self._clock,
            ttl_seconds=cursor_ttl_seconds,
        )

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
                ).all()
                return tuple(_account_view(account, connection) for account, connection in rows)

        return await asyncio.to_thread(read)

    async def list_broker_connections(
        self, principal: Principal
    ) -> tuple[BrokerConnectionView, ...]:
        self._authorizer.require_scope(
            principal,
            Scope.CONFIGURATION_READ,
            now=_utc(self._clock()),
        )
        owner_id = _uuid(principal.owner_id, "owner_id")

        def read() -> tuple[BrokerConnectionView, ...]:
            with self._sessions() as session:
                rows = session.scalars(
                    select(BrokerConnectionModel)
                    .where(BrokerConnectionModel.owner_id == owner_id)
                    .order_by(BrokerConnectionModel.provider, BrokerConnectionModel.environment)
                )
                return tuple(
                    BrokerConnectionView(
                        id=str(item.id),
                        provider=item.provider,
                        environment=item.environment,
                        status=item.status,
                        credential_configured=bool(item.credential_reference),
                        last_successful_refresh_at=session.scalar(
                            select(func.max(IngestionRunModel.completed_at))
                            .join(
                                BrokerAccountModel,
                                BrokerAccountModel.id == IngestionRunModel.broker_account_id,
                            )
                            .where(
                                BrokerAccountModel.connection_id == item.id,
                                IngestionRunModel.status == "succeeded",
                            )
                        ),
                    )
                    for item in rows
                )

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
        query: PositionQuery,
    ) -> Page[PositionView]:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        owner_uuid = _uuid(principal.owner_id, "owner_id")

        def read() -> Page[PositionView]:
            with self._sessions.begin() as session:
                search = query.search.strip().casefold() if query.search is not None else None
                resource = _position_collection_resource(query.sort)
                definition = CollectionSnapshotDefinition(
                    resource=resource,
                    owner_id=owner_uuid,
                    broker_account_id=account_uuid,
                    filter_fingerprint=collection_filter_fingerprint(search),
                )
                collection_snapshots = CollectionSnapshotStore(
                    session,
                    self._cursors,
                    ttl_seconds=self._cursor_ttl_seconds,
                    max_active_snapshots_per_owner=(
                        self._max_active_collection_snapshots_per_owner
                    ),
                    max_active_members_per_owner=self._max_active_collection_members_per_owner,
                )
                if query.cursor is None:
                    snapshot = _require_snapshot(session, account_uuid)
                    definition = CollectionSnapshotDefinition(
                        resource=resource,
                        owner_id=owner_uuid,
                        broker_account_id=account_uuid,
                        filter_fingerprint=definition.filter_fingerprint,
                        source_snapshot_id=snapshot.id,
                    )
                    identity_statement = (
                        select(SnapshotPositionModel.id)
                        .join(
                            ListingModel,
                            ListingModel.id == SnapshotPositionModel.listing_id,
                        )
                        .join(
                            InstrumentModel,
                            InstrumentModel.id == ListingModel.instrument_id,
                        )
                        .where(SnapshotPositionModel.snapshot_id == snapshot.id)
                    )
                    if query.search is not None:
                        pattern = f"%{_escape_like(query.search.strip())}%"
                        identity_statement = identity_statement.where(
                            or_(
                                ListingModel.ticker.ilike(pattern, escape="\\"),
                                InstrumentModel.canonical_name.ilike(pattern, escape="\\"),
                            )
                        )
                    if query.sort is PositionSort.TICKER_ASC:
                        identity_statement = identity_statement.order_by(
                            func.lower(ListingModel.ticker),
                            ListingModel.id,
                        )
                    else:
                        metric = (
                            func.coalesce(
                                SnapshotPositionModel.market_value,
                                Decimal("-1E30"),
                            )
                            if query.sort is not PositionSort.WEIGHT_DESC
                            or (
                                snapshot.portfolio_total is not None
                                and snapshot.portfolio_total > 0
                            )
                            else literal(Decimal("-1E30"))
                        )
                        identity_statement = identity_statement.order_by(
                            metric.desc(),
                            func.lower(ListingModel.ticker),
                            ListingModel.id,
                        )
                    page = collection_snapshots.materialize(
                        definition,
                        lambda: session.scalars(
                            identity_statement.execution_options(
                                yield_per=_COLLECTION_SNAPSHOT_STREAM_BATCH
                            )
                        ),
                        limit=query.limit,
                    )
                else:
                    page = collection_snapshots.resume(
                        definition,
                        query.cursor,
                        limit=query.limit,
                    )
                    if page.source_snapshot_id is None:
                        raise CursorValidationError("invalid cursor")
                    resumed_snapshot = session.scalar(
                        select(PortfolioSnapshotModel).where(
                            PortfolioSnapshotModel.id == page.source_snapshot_id,
                            PortfolioSnapshotModel.broker_account_id == account_uuid,
                        )
                    )
                    if resumed_snapshot is None:
                        raise CursorValidationError("invalid cursor")
                    snapshot = resumed_snapshot
                quality = _effective_snapshot_quality(
                    session,
                    snapshot,
                    account_uuid,
                    now=_utc(self._clock()),
                )
                rows = session.execute(
                    select(SnapshotPositionModel, ListingModel, InstrumentModel)
                    .join(ListingModel, ListingModel.id == SnapshotPositionModel.listing_id)
                    .join(InstrumentModel, InstrumentModel.id == ListingModel.instrument_id)
                    .where(
                        SnapshotPositionModel.id.in_(page.record_ids),
                        SnapshotPositionModel.snapshot_id == snapshot.id,
                    )
                )
                indexed = {
                    item.id: (item, listing, instrument) for item, listing, instrument in rows
                }
                try:
                    selected = tuple(indexed[record_id] for record_id in page.record_ids)
                except KeyError as exc:
                    raise CursorValidationError("invalid cursor") from exc
                return Page(
                    tuple(
                        _position_view(item, listing, instrument, snapshot, quality)
                        for item, listing, instrument in selected
                    ),
                    page.next_cursor,
                    query.limit,
                    page.exact_total,
                )

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
        query: ActivityQuery,
    ) -> Page[ActivityView]:
        account_uuid = await self._read_access(principal, account_id, Scope.ACTIVITY_READ)
        owner_uuid = _uuid(principal.owner_id, "owner_id")

        def read() -> Page[ActivityView]:
            with self._sessions.begin() as session:
                definition = CollectionSnapshotDefinition(
                    resource=CollectionSnapshotResource.ACTIVITY,
                    owner_id=owner_uuid,
                    broker_account_id=account_uuid,
                    filter_fingerprint=collection_filter_fingerprint(
                        query.start_date,
                        query.end_date,
                        query.activity_type,
                    ),
                )
                snapshots = CollectionSnapshotStore(
                    session,
                    self._cursors,
                    ttl_seconds=self._cursor_ttl_seconds,
                    max_active_snapshots_per_owner=(
                        self._max_active_collection_snapshots_per_owner
                    ),
                    max_active_members_per_owner=self._max_active_collection_members_per_owner,
                )
                if query.cursor is None:
                    identity_statement = _transaction_filters(
                        select(TransactionModel.id).where(
                            TransactionModel.broker_account_id == account_uuid
                        ),
                        query,
                    ).order_by(
                        TransactionModel.occurred_at.desc(),
                        TransactionModel.id.desc(),
                    )
                    page = snapshots.materialize(
                        definition,
                        lambda: session.scalars(
                            identity_statement.execution_options(
                                yield_per=_COLLECTION_SNAPSHOT_STREAM_BATCH
                            )
                        ),
                        limit=query.limit,
                    )
                else:
                    page = snapshots.resume(definition, query.cursor, limit=query.limit)
                quality = _fallback_quality(
                    session,
                    account_uuid,
                    _latest_snapshot(session, account_uuid),
                    _latest_run_time(session, account_uuid),
                    now=_utc(self._clock()),
                )
                statement = (
                    select(TransactionModel, ListingModel)
                    .outerjoin(ListingModel)
                    .where(TransactionModel.id.in_(page.record_ids))
                )
                indexed = {item.id: (item, listing) for item, listing in session.execute(statement)}
                try:
                    selected = tuple(indexed[record_id] for record_id in page.record_ids)
                except KeyError as exc:
                    raise CursorValidationError("invalid cursor") from exc
                return Page(
                    tuple(_activity_view(item, listing, quality) for item, listing in selected),
                    page.next_cursor,
                    query.limit,
                    page.exact_total,
                )

        return await asyncio.to_thread(read)

    async def list_dividends(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: DividendQuery,
    ) -> Page[DividendView]:
        account_uuid = await self._read_access(principal, account_id, Scope.ACTIVITY_READ)
        owner_uuid = _uuid(principal.owner_id, "owner_id")

        def read() -> Page[DividendView]:
            with self._sessions.begin() as session:
                definition = CollectionSnapshotDefinition(
                    resource=CollectionSnapshotResource.DIVIDENDS,
                    owner_id=owner_uuid,
                    broker_account_id=account_uuid,
                    filter_fingerprint=collection_filter_fingerprint(
                        query.start_date,
                        query.end_date,
                    ),
                )
                snapshots = CollectionSnapshotStore(
                    session,
                    self._cursors,
                    ttl_seconds=self._cursor_ttl_seconds,
                    max_active_snapshots_per_owner=(
                        self._max_active_collection_snapshots_per_owner
                    ),
                    max_active_members_per_owner=self._max_active_collection_members_per_owner,
                )
                if query.cursor is None:
                    identity_statement = _dividend_filters(
                        select(DividendModel.id).where(
                            DividendModel.broker_account_id == account_uuid
                        ),
                        query.start_date,
                        query.end_date,
                    ).order_by(
                        DividendModel.paid_on.desc(),
                        DividendModel.id.desc(),
                    )
                    page = snapshots.materialize(
                        definition,
                        lambda: session.scalars(
                            identity_statement.execution_options(
                                yield_per=_COLLECTION_SNAPSHOT_STREAM_BATCH
                            )
                        ),
                        limit=query.limit,
                    )
                else:
                    page = snapshots.resume(definition, query.cursor, limit=query.limit)
                quality = _fallback_quality(
                    session,
                    account_uuid,
                    _latest_snapshot(session, account_uuid),
                    _latest_run_time(session, account_uuid),
                    now=_utc(self._clock()),
                )
                statement = (
                    select(DividendModel, ListingModel)
                    .outerjoin(ListingModel)
                    .where(DividendModel.id.in_(page.record_ids))
                )
                indexed = {item.id: (item, listing) for item, listing in session.execute(statement)}
                try:
                    selected = tuple(indexed[record_id] for record_id in page.record_ids)
                except KeyError as exc:
                    raise CursorValidationError("invalid cursor") from exc
                return Page(
                    tuple(_dividend_view(item, listing, quality) for item, listing in selected),
                    page.next_cursor,
                    query.limit,
                    page.exact_total,
                )

        return await asyncio.to_thread(read)

    async def get_dividend_summary(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: DividendSummaryQuery,
    ) -> DividendSummaryView:
        account_uuid = await self._read_access(principal, account_id, Scope.ACTIVITY_READ)

        def read() -> DividendSummaryView:
            with self._sessions() as session:
                quality = _fallback_quality(
                    session,
                    account_uuid,
                    _latest_snapshot(session, account_uuid),
                    _latest_run_time(session, account_uuid),
                    now=_utc(self._clock()),
                )
                filtered = _dividend_filters(
                    select(DividendModel).where(DividendModel.broker_account_id == account_uuid),
                    query.start_date,
                    query.end_date,
                )
                count = (
                    session.scalar(
                        select(func.count()).select_from(filtered.order_by(None).subquery())
                    )
                    or 0
                )
                currency_count = (
                    session.scalar(
                        select(func.count(func.distinct(DividendModel.currency))).where(
                            DividendModel.broker_account_id == account_uuid,
                            DividendModel.paid_on >= query.start_date,
                            DividendModel.paid_on <= query.end_date,
                        )
                    )
                    or 0
                )
                aggregate_rows = session.execute(
                    select(
                        DividendModel.currency,
                        func.count(),
                        func.sum(DividendModel.net_amount),
                        func.count(DividendModel.gross_amount),
                        func.sum(DividendModel.gross_amount),
                        func.count(DividendModel.withholding_tax),
                        func.sum(DividendModel.withholding_tax),
                    )
                    .where(
                        DividendModel.broker_account_id == account_uuid,
                        DividendModel.paid_on >= query.start_date,
                        DividendModel.paid_on <= query.end_date,
                    )
                    .group_by(DividendModel.currency)
                    .order_by(DividendModel.currency)
                    .limit(20)
                ).all()
                recent_rows = session.execute(
                    select(DividendModel, ListingModel)
                    .outerjoin(ListingModel)
                    .where(
                        DividendModel.broker_account_id == account_uuid,
                        DividendModel.paid_on >= query.start_date,
                        DividendModel.paid_on <= query.end_date,
                    )
                    .order_by(DividendModel.paid_on.desc(), DividendModel.id.desc())
                    .limit(query.recent_limit)
                ).all()
                missing_gross = any(
                    gross_count != row_count
                    for _, row_count, _, gross_count, _, _, _ in aggregate_rows
                )
                missing_withholding = any(
                    withholding_count != row_count
                    for _, row_count, _, _, _, withholding_count, _ in aggregate_rows
                )
                missing_inputs = tuple(
                    name
                    for missing, name in (
                        (missing_gross, "dividend_gross_amount"),
                        (missing_withholding, "dividend_withholding_tax"),
                        (currency_count > len(aggregate_rows), "dividend_currency_groups"),
                    )
                    if missing
                )
                if missing_inputs:
                    quality = _quality(
                        ViewQuality.PARTIAL,
                        as_of=quality.as_of,
                        source_at=quality.source_timestamp,
                        warnings=(
                            *quality.warnings,
                            "Dividend component aggregates are incomplete for the selected period.",
                        ),
                        missing=tuple(dict.fromkeys((*quality.missing_inputs, *missing_inputs))),
                    )
                return DividendSummaryView(
                    start_date=query.start_date,
                    end_date=query.end_date,
                    totals=tuple(
                        DividendCurrencyTotalView(
                            currency=currency,
                            net_amount=net_amount or Decimal(0),
                            gross_amount=(gross_amount if gross_count == row_count else None),
                            withholding_tax=(
                                withholding_tax if withholding_count == row_count else None
                            ),
                        )
                        for (
                            currency,
                            row_count,
                            net_amount,
                            gross_count,
                            gross_amount,
                            withholding_count,
                            withholding_tax,
                        ) in aggregate_rows
                    ),
                    recent=tuple(
                        _dividend_view(item, listing, quality) for item, listing in recent_rows
                    ),
                    covered_record_count=count,
                    totals_truncated=currency_count > len(aggregate_rows),
                    omitted_currency_count=max(currency_count - len(aggregate_rows), 0),
                    quality=quality,
                )

        return await asyncio.to_thread(read)

    async def list_orders(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: PageQuery,
    ) -> Page[OrderView]:
        account_uuid = await self._read_access(principal, account_id, Scope.ACTIVITY_READ)

        def read() -> Page[OrderView]:
            with self._sessions() as session:
                binding = cursor_binding(account_id)
                cutoff = _database_now(session)
                cursor_key: tuple[str, ...] | None = None
                if query.cursor is not None:
                    cutoff, cursor_key = self._cursors.decode(
                        query.cursor,
                        resource="orders",
                        binding=binding,
                        key_size=2,
                    )
                quality = _fallback_quality(
                    session,
                    account_uuid,
                    _latest_snapshot(session, account_uuid),
                    _latest_run_time(session, account_uuid),
                    now=_utc(self._clock()),
                )
                latest_ids = (
                    select(OrderObservationModel.id)
                    .where(
                        OrderObservationModel.broker_account_id == account_uuid,
                        OrderObservationModel.observed_at <= cutoff,
                        OrderObservationModel.created_at <= cutoff,
                    )
                    .distinct(OrderObservationModel.provider_order_id)
                    .order_by(
                        OrderObservationModel.provider_order_id,
                        OrderObservationModel.observed_at.desc(),
                        OrderObservationModel.id.desc(),
                    )
                )
                statement = (
                    select(OrderObservationModel, ListingModel)
                    .join(ListingModel)
                    .where(OrderObservationModel.id.in_(latest_ids))
                )
                total = (
                    session.scalar(
                        select(func.count()).select_from(statement.order_by(None).subquery())
                    )
                    or 0
                )
                created_at = func.coalesce(
                    OrderObservationModel.submitted_at, OrderObservationModel.observed_at
                )
                if cursor_key is not None:
                    last_time = _cursor_datetime(cursor_key[0])
                    last_id = _cursor_uuid(cursor_key[1])
                    statement = statement.where(
                        tuple_(created_at, OrderObservationModel.id) < (last_time, last_id)
                    )
                rows = session.execute(
                    statement.order_by(created_at.desc(), OrderObservationModel.id.desc()).limit(
                        query.limit + 1
                    )
                ).all()
                selected = rows[: query.limit]
                next_cursor = None
                if len(rows) > query.limit and selected:
                    item = selected[-1][0]
                    next_cursor = self._cursors.encode(
                        resource="orders",
                        binding=binding,
                        read_cutoff=cutoff,
                        key=((item.submitted_at or item.observed_at).isoformat(), str(item.id)),
                    )
                return Page(
                    tuple(_order_view(item, listing, quality) for item, listing in selected),
                    next_cursor,
                    query.limit,
                    total,
                )

        return await asyncio.to_thread(read)

    async def get_direct_allocation(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: DirectAllocationQuery,
    ) -> DirectAllocationView:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)

        def read() -> DirectAllocationView:
            with self._sessions() as session:
                snapshot = _require_snapshot(session, account_uuid)
                quality = _effective_snapshot_quality(
                    session, snapshot, account_uuid, now=_utc(self._clock())
                )
                position_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(SnapshotPositionModel)
                        .where(SnapshotPositionModel.snapshot_id == snapshot.id)
                    )
                    or 0
                )
                cash_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(SnapshotCashModel)
                        .where(SnapshotCashModel.snapshot_id == snapshot.id)
                    )
                    or 0
                )
                position_rows = session.execute(
                    select(SnapshotPositionModel, ListingModel, InstrumentModel)
                    .join(ListingModel, ListingModel.id == SnapshotPositionModel.listing_id)
                    .join(InstrumentModel, InstrumentModel.id == ListingModel.instrument_id)
                    .where(SnapshotPositionModel.snapshot_id == snapshot.id)
                    .order_by(
                        SnapshotPositionModel.market_value.desc().nullslast(),
                        func.lower(ListingModel.ticker),
                        ListingModel.id,
                    )
                    .limit(query.top_n)
                ).all()
                cash_row = session.scalar(
                    select(SnapshotCashModel)
                    .where(SnapshotCashModel.snapshot_id == snapshot.id)
                    .order_by(
                        (SnapshotCashModel.currency != snapshot.reporting_currency).asc(),
                        SnapshotCashModel.currency,
                    )
                    .limit(1)
                )
                positions = tuple(
                    AllocationView(
                        id=str(listing.id),
                        label=instrument.canonical_name,
                        asset_type=instrument.instrument_type,
                        market_value=_position_view(
                            item, listing, instrument, snapshot, quality
                        ).market_value,
                        weight=_weight(item.market_value, snapshot.portfolio_total),
                        weight_availability=(
                            Availability.AVAILABLE
                            if _weight(item.market_value, snapshot.portfolio_total) is not None
                            else Availability.UNAVAILABLE
                        ),
                    )
                    for item, listing, instrument in position_rows
                )
                cash = (
                    ()
                    if cash_row is None
                    else (
                        AllocationView(
                            id=f"cash:{cash_row.currency}",
                            label=f"Cash ({cash_row.currency})",
                            asset_type="cash",
                            market_value=_snapshot_metric(
                                cash_row.amount,
                                cash_row.currency,
                                "canonical snapshot cash component",
                                version=snapshot.calculation_version,
                                provenance=_stored_provenance(
                                    cash_row.provenance, fallback="snapshot_cash"
                                ),
                            ),
                            weight=_weight(cash_row.amount, snapshot.portfolio_total),
                            weight_availability=(
                                Availability.AVAILABLE
                                if _weight(cash_row.amount, snapshot.portfolio_total) is not None
                                else Availability.UNAVAILABLE
                            ),
                        ),
                    )
                )
                return DirectAllocationView(
                    items=positions + cash,
                    total=position_count + cash_count,
                    truncated=position_count > query.top_n or cash_count > len(cash),
                )

        return await asyncio.to_thread(read)

    async def list_snapshots(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: PageQuery,
    ) -> Page[SnapshotView]:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)

        def read() -> Page[SnapshotView]:
            with self._sessions() as session:
                binding = cursor_binding(account_id)
                cutoff = _database_now(session)
                cursor_key: tuple[str, ...] | None = None
                if query.cursor is not None:
                    cutoff, cursor_key = self._cursors.decode(
                        query.cursor,
                        resource="snapshots",
                        binding=binding,
                        key_size=2,
                    )
                statement = select(PortfolioSnapshotModel).where(
                    PortfolioSnapshotModel.broker_account_id == account_uuid,
                    PortfolioSnapshotModel.created_at <= cutoff,
                )
                total = (
                    session.scalar(
                        select(func.count()).select_from(statement.order_by(None).subquery())
                    )
                    or 0
                )
                if cursor_key is not None:
                    last_time = _cursor_datetime(cursor_key[0])
                    last_id = _cursor_uuid(cursor_key[1])
                    statement = statement.where(
                        tuple_(
                            PortfolioSnapshotModel.valuation_at,
                            PortfolioSnapshotModel.id,
                        )
                        < (last_time, last_id)
                    )
                rows = tuple(
                    session.scalars(
                        statement.order_by(
                            PortfolioSnapshotModel.valuation_at.desc(),
                            PortfolioSnapshotModel.id.desc(),
                        ).limit(query.limit + 1)
                    )
                )
                selected = rows[: query.limit]
                now = _utc(self._clock())
                latest = _latest_snapshot(session, account_uuid)
                values = tuple(
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
                            if latest is not None and item.id == latest.id
                            else None
                        ),
                    )
                    for item in selected
                )
                next_cursor = None
                if len(rows) > query.limit and selected:
                    item = selected[-1]
                    next_cursor = self._cursors.encode(
                        resource="snapshots",
                        binding=binding,
                        read_cutoff=cutoff,
                        key=(item.valuation_at.isoformat(), str(item.id)),
                    )
                return Page(values, next_cursor, query.limit, total)

        return await asyncio.to_thread(read)

    async def get_snapshot(
        self, principal: Principal, account_id: str, snapshot_id: str
    ) -> SnapshotView:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        snapshot_uuid = _uuid(snapshot_id, "snapshot_id")

        def read() -> SnapshotView:
            with self._sessions() as session:
                snapshot = session.scalar(
                    select(PortfolioSnapshotModel).where(
                        PortfolioSnapshotModel.id == snapshot_uuid,
                        PortfolioSnapshotModel.broker_account_id == account_uuid,
                    )
                )
                if snapshot is None:
                    raise LookupError("snapshot not found")
                latest = _latest_snapshot(session, account_uuid)
                now = _utc(self._clock())
                quality = (
                    _effective_snapshot_quality(session, snapshot, account_uuid, now=now)
                    if latest is not None and latest.id == snapshot.id
                    else _snapshot_quality(snapshot, now=now)
                )
                return _snapshot_view(snapshot, now=now, quality=quality)

        return await asyncio.to_thread(read)

    async def get_snapshot_detail(
        self, principal: Principal, account_id: str, snapshot_id: str
    ) -> SnapshotDetailView:
        snapshot = await self.get_snapshot(principal, account_id, snapshot_id)
        reason = (
            "This metric is not persisted with the immutable portfolio snapshot and "
            "cannot be reconstructed at that historical cutoff."
        )

        def unavailable(methodology: str) -> MetricView:
            return _metric(
                None,
                snapshot.reporting_currency,
                methodology,
                provenance=("portfolio_snapshots", "coverage_gate"),
                unavailable_reason=reason,
            )

        return SnapshotDetailView(
            snapshot=snapshot,
            dividends_received=unavailable("snapshot-cutoff dividend coverage gate"),
            realized_profit_loss=unavailable("snapshot-cutoff realized profit/loss coverage gate"),
            unrealized_profit_loss=unavailable(
                "snapshot-cutoff unrealized profit/loss coverage gate"
            ),
        )

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
                    .order_by(
                        ReconciliationRunModel.as_of.desc(),
                        ReconciliationRunModel.id.desc(),
                    )
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
                        discrepancy_count=0,
                        quality=_quality(
                            ViewQuality.PARTIAL,
                            as_of=observed,
                            source_at=observed,
                            warnings=("Reconciliation has not completed.",),
                            missing=("reconciliation_run",),
                        ),
                    )
                latest_snapshot = _latest_snapshot(session, account_uuid)
                gate_missing = _reconciliation_gate_missing(
                    run,
                    period_start=(
                        None if latest_snapshot is None else latest_snapshot.valuation_at
                    ),
                    period_end=(None if latest_snapshot is None else latest_snapshot.valuation_at),
                )
                stored_state = _view_quality(run.quality_state)
                effective_state = (
                    _worst_quality_state((stored_state, ViewQuality.PARTIAL))
                    if gate_missing
                    else stored_state
                )
                return ReconciliationView(
                    status=(
                        "partial" if run.status == "reconciled" and gate_missing else run.status
                    ),
                    evaluated_at=run.as_of,
                    algorithm_version=run.algorithm_version,
                    tolerance_version=run.tolerance_version,
                    issues=(),
                    discrepancy_count=run.discrepancy_count,
                    quality=_quality(
                        effective_state,
                        as_of=run.as_of,
                        source_at=run.coverage_end_at,
                        warnings=tuple(
                            dict.fromkeys(
                                (
                                    *_warning_text(run.warnings),
                                    *(
                                        (
                                            "Reconciliation does not satisfy the current "
                                            "snapshot gate.",
                                        )
                                        if gate_missing
                                        else ()
                                    ),
                                )
                            )
                        ),
                        missing=tuple(dict.fromkeys((*run.coverage_gaps, *gate_missing))),
                    ),
                )

        return await asyncio.to_thread(read)

    async def list_reconciliation_discrepancies(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: PageQuery,
    ) -> Page[ReconciliationIssueView]:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)

        def read() -> Page[ReconciliationIssueView]:
            with self._sessions() as session:
                binding = cursor_binding(account_id)
                cutoff = _database_now(session)
                cursor_key: tuple[str, ...] | None = None
                if query.cursor is not None:
                    cutoff, cursor_key = self._cursors.decode(
                        query.cursor,
                        resource="reconciliation_discrepancies",
                        binding=binding,
                        key_size=3,
                    )
                    run_id = _cursor_uuid(cursor_key[0])
                    run = session.scalar(
                        select(ReconciliationRunModel).where(
                            ReconciliationRunModel.id == run_id,
                            ReconciliationRunModel.broker_account_id == account_uuid,
                        )
                    )
                else:
                    run = session.scalar(
                        select(ReconciliationRunModel)
                        .where(ReconciliationRunModel.broker_account_id == account_uuid)
                        .order_by(
                            ReconciliationRunModel.as_of.desc(),
                            ReconciliationRunModel.id.desc(),
                        )
                        .limit(1)
                    )
                if run is None:
                    return Page((), None, query.limit, 0)
                statement = select(ReconciliationDiscrepancyModel).where(
                    ReconciliationDiscrepancyModel.reconciliation_run_id == run.id,
                    ReconciliationDiscrepancyModel.created_at <= cutoff,
                )
                total = (
                    session.scalar(
                        select(func.count()).select_from(statement.order_by(None).subquery())
                    )
                    or 0
                )
                if cursor_key is not None:
                    last_seen = _cursor_datetime(cursor_key[1])
                    last_id = _cursor_uuid(cursor_key[2])
                    statement = statement.where(
                        tuple_(
                            ReconciliationDiscrepancyModel.last_seen_at,
                            ReconciliationDiscrepancyModel.id,
                        )
                        < (last_seen, last_id)
                    )
                rows = tuple(
                    session.scalars(
                        statement.order_by(
                            ReconciliationDiscrepancyModel.last_seen_at.desc(),
                            ReconciliationDiscrepancyModel.id.desc(),
                        ).limit(query.limit + 1)
                    )
                )
                selected = rows[: query.limit]
                next_cursor = None
                if len(rows) > query.limit and selected:
                    item = selected[-1]
                    next_cursor = self._cursors.encode(
                        resource="reconciliation_discrepancies",
                        binding=binding,
                        read_cutoff=cutoff,
                        key=(str(run.id), item.last_seen_at.isoformat(), str(item.id)),
                    )
                return Page(
                    tuple(_reconciliation_issue(item) for item in selected),
                    next_cursor,
                    query.limit,
                    total,
                )

        return await asyncio.to_thread(read)

    async def search_instruments(
        self, principal: Principal, *, query: InstrumentQuery
    ) -> Page[InstrumentView]:
        self._authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=_utc(self._clock()))
        owner_uuid = _uuid(principal.owner_id, "owner_id")

        def read() -> Page[InstrumentView]:
            with self._sessions.begin() as session:
                scopes = tuple(
                    session.execute(
                        select(
                            BrokerConnectionModel.provider,
                            BrokerConnectionModel.environment,
                        )
                        .where(BrokerConnectionModel.owner_id == owner_uuid)
                        .distinct()
                        .order_by(
                            BrokerConnectionModel.provider,
                            BrokerConnectionModel.environment,
                        )
                    ).all()
                )
                search = query.search.strip().casefold() if query.search is not None else None
                definition = CollectionSnapshotDefinition(
                    resource=CollectionSnapshotResource.INSTRUMENTS,
                    owner_id=owner_uuid,
                    broker_account_id=None,
                    filter_fingerprint=collection_filter_fingerprint(
                        search,
                        *(f"{provider}/{environment}" for provider, environment in scopes),
                    ),
                )
                snapshots = CollectionSnapshotStore(
                    session,
                    self._cursors,
                    ttl_seconds=self._cursor_ttl_seconds,
                    max_active_snapshots_per_owner=(
                        self._max_active_collection_snapshots_per_owner
                    ),
                    max_active_members_per_owner=self._max_active_collection_members_per_owner,
                )
                if query.cursor is None:
                    record_ids: Iterable[UUID] | Callable[[], Iterable[UUID]]
                    if scopes:
                        scope_filter = or_(
                            *(
                                and_(
                                    ListingModel.provider == provider,
                                    ListingModel.environment == environment,
                                )
                                for provider, environment in scopes
                            )
                        )
                        identity_statement = (
                            select(ListingModel.id)
                            .join(
                                InstrumentModel,
                                InstrumentModel.id == ListingModel.instrument_id,
                            )
                            .where(scope_filter)
                        )
                        if query.search is not None:
                            pattern = f"%{_escape_like(query.search.strip())}%"
                            identity_statement = identity_statement.where(
                                or_(
                                    ListingModel.ticker.ilike(pattern, escape="\\"),
                                    InstrumentModel.canonical_name.ilike(pattern, escape="\\"),
                                )
                            )
                        identity_statement = identity_statement.order_by(
                            ListingModel.provider,
                            ListingModel.environment,
                            func.lower(ListingModel.ticker),
                            func.lower(InstrumentModel.canonical_name),
                            ListingModel.id,
                        )

                        def load_record_ids() -> Iterable[UUID]:
                            return session.scalars(
                                identity_statement.execution_options(
                                    yield_per=_COLLECTION_SNAPSHOT_STREAM_BATCH
                                )
                            )

                        record_ids = load_record_ids
                    else:
                        record_ids = ()
                    page = snapshots.materialize(
                        definition,
                        record_ids,
                        limit=query.limit,
                    )
                else:
                    page = snapshots.resume(definition, query.cursor, limit=query.limit)
                rows = session.execute(
                    select(ListingModel, InstrumentModel)
                    .join(InstrumentModel, InstrumentModel.id == ListingModel.instrument_id)
                    .where(ListingModel.id.in_(page.record_ids))
                )
                indexed = {listing.id: (listing, instrument) for listing, instrument in rows}
                try:
                    selected = tuple(indexed[record_id] for record_id in page.record_ids)
                except KeyError as exc:
                    raise CursorValidationError("invalid cursor") from exc
                return Page(
                    tuple(
                        _instrument_view(listing, instrument) for listing, instrument in selected
                    ),
                    page.next_cursor,
                    query.limit,
                    page.exact_total,
                )

        return await asyncio.to_thread(read)

    async def get_instrument(self, principal: Principal, instrument_id: str) -> InstrumentView:
        self._authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=_utc(self._clock()))
        owner_uuid = _uuid(principal.owner_id, "owner_id")
        instrument_uuid = _uuid(instrument_id, "instrument_id")

        def read() -> InstrumentView:
            with self._sessions() as session:
                row = session.execute(
                    select(ListingModel, InstrumentModel)
                    .join(InstrumentModel, InstrumentModel.id == ListingModel.instrument_id)
                    .where(
                        InstrumentModel.id == instrument_uuid,
                        select(BrokerConnectionModel.id)
                        .where(
                            BrokerConnectionModel.owner_id == owner_uuid,
                            BrokerConnectionModel.provider == ListingModel.provider,
                            BrokerConnectionModel.environment == ListingModel.environment,
                        )
                        .exists(),
                    )
                    .order_by(
                        ListingModel.provider,
                        ListingModel.environment,
                        func.lower(ListingModel.ticker),
                        ListingModel.id,
                    )
                    .limit(1)
                ).one_or_none()
                if row is None:
                    raise LookupError("instrument not found")
                return _instrument_view(*row)

        return await asyncio.to_thread(read)

    async def get_core_performance_summary(
        self, principal: Principal, account_id: str
    ) -> PerformanceSummaryView:
        account_uuid = await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)

        def read() -> PerformanceSummaryView:
            with self._sessions() as session:
                account = session.scalar(
                    select(BrokerAccountModel).where(BrokerAccountModel.id == account_uuid)
                )
                if account is None:
                    raise LookupError("account not found")
                rows = tuple(
                    session.scalars(
                        select(PortfolioSnapshotModel)
                        .where(PortfolioSnapshotModel.broker_account_id == account_uuid)
                        .order_by(
                            PortfolioSnapshotModel.valuation_at,
                            PortfolioSnapshotModel.id,
                        )
                    )
                )
                now = _utc(self._clock())
                start_at = rows[0].valuation_at if rows else None
                end_at = rows[-1].valuation_at if rows else None
                flows = tuple(
                    session.scalars(
                        select(CashFlowModel)
                        .where(
                            CashFlowModel.broker_account_id == account_uuid,
                            CashFlowModel.classification == "external",
                            CashFlowModel.active.is_(True),
                            *(
                                (CashFlowModel.occurred_at >= start_at,)
                                if start_at is not None
                                else ()
                            ),
                            *((CashFlowModel.occurred_at <= end_at,) if end_at is not None else ()),
                        )
                        .order_by(CashFlowModel.occurred_at, CashFlowModel.id)
                    )
                )
                ambiguous_activity_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(TransactionModel)
                        .where(
                            TransactionModel.broker_account_id == account_uuid,
                            func.lower(TransactionModel.status) != "reversed",
                            or_(
                                func.lower(TransactionModel.status) == "unknown",
                                func.lower(TransactionModel.transaction_type).not_in(
                                    _PERFORMANCE_SUPPORTED_TRANSACTION_TYPES
                                ),
                            ),
                            *(
                                (TransactionModel.occurred_at >= start_at,)
                                if start_at is not None
                                else ()
                            ),
                            *(
                                (TransactionModel.occurred_at <= end_at,)
                                if end_at is not None
                                else ()
                            ),
                        )
                    )
                    or 0
                )
                checkpoint = session.scalar(
                    select(IngestionCheckpointModel).where(
                        IngestionCheckpointModel.broker_account_id == account_uuid,
                        IngestionCheckpointModel.capability
                        == IngestionCapability.TRANSACTIONS.value,
                    )
                )
                reconciliation = session.scalar(
                    select(ReconciliationRunModel)
                    .where(ReconciliationRunModel.broker_account_id == account_uuid)
                    .order_by(ReconciliationRunModel.as_of.desc(), ReconciliationRunModel.id.desc())
                    .limit(1)
                )
                gaps: list[str] = []
                if checkpoint is None:
                    gaps.append("historical_transaction_checkpoint")
                if any(item.portfolio_total is None for item in rows):
                    gaps.append("complete_snapshot_values")
                if ambiguous_activity_count:
                    gaps.append("unambiguous_external_flow_classification")
                reconciliation_missing = _reconciliation_gate_missing(
                    reconciliation,
                    period_start=start_at,
                    period_end=end_at,
                )
                return calculate_core_performance(
                    CorePerformanceInput(
                        snapshots=tuple(
                            PerformanceSnapshotInput(
                                snapshot_id=str(item.id),
                                valuation_at=item.valuation_at,
                                value=item.portfolio_total,
                                currency=item.reporting_currency,
                                quality=_snapshot_quality(item, now=now).state,
                            )
                            for item in rows
                        ),
                        external_flows=tuple(
                            PerformanceFlowInput(
                                occurred_at=item.occurred_at,
                                amount=item.amount,
                                currency=item.currency,
                                quality=_view_quality(item.quality),
                            )
                            for item in flows
                        ),
                        reporting_currency=account.base_currency,
                        evaluated_at=now,
                        coverage_start_at=(
                            None if checkpoint is None else checkpoint.coverage_start_at
                        ),
                        coverage_end_at=(
                            None if checkpoint is None else checkpoint.coverage_end_at
                        ),
                        coverage_complete=bool(
                            checkpoint is not None and checkpoint.coverage_complete
                        ),
                        coverage_gaps=tuple(gaps),
                        gate_missing_inputs=tuple((*gaps, *reconciliation_missing)),
                        reconciled=not reconciliation_missing,
                    )
                )

        return await asyncio.to_thread(read)

    async def get_data_quality_summary(
        self, principal: Principal, account_id: str
    ) -> DataQualitySummaryView:
        authorization_time = _utc(self._clock())
        self._authorizer.require_scope(
            principal,
            Scope.PORTFOLIO_READ,
            now=authorization_time,
        )
        self._authorizer.require_scope(
            principal,
            Scope.ACTIVITY_READ,
            now=authorization_time,
        )
        summary = await self.get_summary(principal, account_id)
        reconciliation = await self.get_reconciliation(principal, account_id)
        account_uuid = _uuid(account_id, "account_id")

        def read() -> tuple[
            tuple[str, ...],
            RefreshRunQualityView | None,
            tuple[RefreshRunQualityView, ...],
            tuple[CheckpointQualityView, ...],
            str | None,
            datetime | None,
            int,
            int,
        ]:
            with self._sessions() as session:
                failed = tuple(
                    str(value)
                    for value in session.scalars(
                        select(IngestionRunModel.id)
                        .where(
                            IngestionRunModel.broker_account_id == account_uuid,
                            IngestionRunModel.status.in_(("partial", "failed", "cancelled")),
                        )
                        .order_by(IngestionRunModel.started_at.desc(), IngestionRunModel.id.desc())
                        .limit(20)
                    )
                )
                latest_run = session.scalar(
                    select(IngestionRunModel)
                    .where(IngestionRunModel.broker_account_id == account_uuid)
                    .order_by(IngestionRunModel.started_at.desc(), IngestionRunModel.id.desc())
                    .limit(1)
                )
                run_view = None if latest_run is None else _refresh_run_quality(latest_run)
                latest_by_status = tuple(
                    _refresh_run_quality(item)
                    for status in ("succeeded", "partial", "failed")
                    if (
                        item := session.scalar(
                            select(IngestionRunModel)
                            .where(
                                IngestionRunModel.broker_account_id == account_uuid,
                                IngestionRunModel.status == status,
                            )
                            .order_by(
                                IngestionRunModel.started_at.desc(),
                                IngestionRunModel.id.desc(),
                            )
                            .limit(1)
                        )
                    )
                    is not None
                )
                checkpoints = tuple(
                    CheckpointQualityView(
                        capability=item.capability,
                        version=item.version,
                        coverage_start_at=item.coverage_start_at,
                        coverage_end_at=item.coverage_end_at,
                        coverage_complete=item.coverage_complete,
                    )
                    for item in session.scalars(
                        select(IngestionCheckpointModel)
                        .where(IngestionCheckpointModel.broker_account_id == account_uuid)
                        .order_by(IngestionCheckpointModel.capability)
                    )
                )
                snapshot = _latest_snapshot(session, account_uuid)
                latest_reconciliation = session.scalar(
                    select(ReconciliationRunModel)
                    .where(ReconciliationRunModel.broker_account_id == account_uuid)
                    .order_by(
                        ReconciliationRunModel.as_of.desc(),
                        ReconciliationRunModel.id.desc(),
                    )
                    .limit(1)
                )
                foreign_flow_missing_fx = (
                    session.scalar(
                        select(func.count())
                        .select_from(CashFlowModel)
                        .where(
                            CashFlowModel.broker_account_id == account_uuid,
                            CashFlowModel.classification == "external",
                            CashFlowModel.active.is_(True),
                            CashFlowModel.currency != summary.account.reporting_currency,
                        )
                    )
                    or 0
                )
                # One unresolved latest-run FX gap represents one missing economic
                # component. Repeated discrepancy rows for the same listing are
                # deduplicated; account-level gaps without a listing remain distinct.
                reconciliation_missing_fx = (
                    0
                    if latest_reconciliation is None
                    else session.scalar(
                        select(
                            func.count(
                                func.distinct(
                                    func.coalesce(
                                        ReconciliationDiscrepancyModel.listing_id,
                                        ReconciliationDiscrepancyModel.id,
                                    )
                                )
                            )
                        ).where(
                            ReconciliationDiscrepancyModel.reconciliation_run_id
                            == latest_reconciliation.id,
                            ReconciliationDiscrepancyModel.discrepancy_type == "currency_fx_gap",
                            ReconciliationDiscrepancyModel.resolution_state != "resolved",
                        )
                    )
                    or 0
                )
                missing_fx = foreign_flow_missing_fx + reconciliation_missing_fx
                unknown_mapping = (
                    session.scalar(
                        select(func.count())
                        .select_from(TransactionModel)
                        .where(
                            TransactionModel.broker_account_id == account_uuid,
                            func.lower(TransactionModel.status) != "reversed",
                            or_(
                                func.lower(TransactionModel.status) == "unknown",
                                func.lower(TransactionModel.transaction_type).not_in(
                                    _PERFORMANCE_SUPPORTED_TRANSACTION_TYPES
                                ),
                            ),
                        )
                    )
                    or 0
                )
                return (
                    failed,
                    run_view,
                    latest_by_status,
                    checkpoints,
                    None if snapshot is None else str(snapshot.id),
                    None if snapshot is None else snapshot.source_cutoff_at,
                    missing_fx,
                    unknown_mapping,
                )

        (
            failed_runs,
            latest_run,
            latest_runs_by_status,
            checkpoints,
            snapshot_id,
            snapshot_cutoff,
            missing_fx,
            unknown_mapping,
        ) = await asyncio.to_thread(read)
        checkpoint_index = {item.capability: item for item in checkpoints}

        def capability_quality(name: str, capability: IngestionCapability | None) -> QualityView:
            if name == "reconciliation":
                return reconciliation.quality
            if capability is None:
                return summary.quality
            checkpoint = checkpoint_index.get(capability.value)
            if checkpoint is None or not checkpoint.coverage_complete:
                return _quality(
                    ViewQuality.PARTIAL,
                    as_of=summary.quality.as_of,
                    source_at=checkpoint.coverage_end_at
                    if checkpoint is not None and checkpoint.coverage_end_at is not None
                    else summary.quality.source_timestamp,
                    warnings=(f"{capability.value} coverage is incomplete.",),
                    missing=(capability.value,),
                )
            return summary.quality

        capability_specs = (
            ("account_summary", IngestionCapability.ACCOUNT),
            ("portfolio_snapshots", None),
            ("positions", IngestionCapability.POSITIONS),
            ("activity", IngestionCapability.TRANSACTIONS),
            ("dividends", IngestionCapability.DIVIDENDS),
            ("reconciliation", None),
        )
        capabilities = tuple(
            CapabilityQualityView(capability=name, quality=capability_quality(name, capability))
            for name, capability in capability_specs
        )
        extra_missing = tuple(
            name
            for count, name in (
                (missing_fx, "external_flow_fx_conversion"),
                (unknown_mapping, "unknown_transaction_mapping"),
            )
            if count
        )
        materialization_state = (
            "missing"
            if snapshot_id is None
            else "available"
            if reconciliation.status == "reconciled"
            else "partial"
        )
        run_state = {
            "failed": ViewQuality.FAILED,
            "partial": ViewQuality.PARTIAL,
            "cancelled": ViewQuality.PARTIAL,
            "queued": ViewQuality.PARTIAL,
            "running": ViewQuality.PARTIAL,
        }.get(latest_run.status if latest_run is not None else "", ViewQuality.FRESH)
        overall_state = _worst_quality_state(
            (
                summary.quality.state,
                reconciliation.quality.state,
                run_state,
                ViewQuality.FRESH if materialization_state == "available" else ViewQuality.PARTIAL,
                *(item.quality.state for item in capabilities),
                *(ViewQuality.PARTIAL for _ in extra_missing),
            )
        )
        overall = _quality(
            overall_state,
            as_of=max(summary.quality.as_of, reconciliation.quality.as_of),
            source_at=min(
                summary.quality.source_timestamp,
                reconciliation.quality.source_timestamp,
            ),
            warnings=tuple(
                dict.fromkeys(
                    (
                        *summary.quality.warnings,
                        *reconciliation.quality.warnings,
                        *(warning for item in capabilities for warning in item.quality.warnings),
                        *(
                            (f"Latest refresh ended {latest_run.status}.",)
                            if latest_run is not None and latest_run.status != "succeeded"
                            else ()
                        ),
                        *(
                            ("Canonical materialization is incomplete.",)
                            if materialization_state != "available"
                            else ()
                        ),
                        *(("Material quality gates remain incomplete.",) if extra_missing else ()),
                    )
                )
            ),
            missing=tuple(
                dict.fromkeys(
                    (
                        *summary.quality.missing_inputs,
                        *reconciliation.quality.missing_inputs,
                        *(item for value in capabilities for item in value.quality.missing_inputs),
                        *extra_missing,
                        *(
                            ("canonical_materialization",)
                            if materialization_state == "missing"
                            else ()
                        ),
                    )
                )
            ),
        )
        return DataQualitySummaryView(
            as_of=overall.as_of,
            reporting_currency=summary.account.reporting_currency,
            quality=overall,
            capabilities=capabilities,
            failed_or_partial_runs=failed_runs,
            latest_refresh_run=latest_run,
            latest_runs_by_status=latest_runs_by_status,
            checkpoints=checkpoints,
            latest_snapshot_id=snapshot_id,
            latest_snapshot_source_cutoff_at=snapshot_cutoff,
            materialization_state=materialization_state,
            reconciliation_status=reconciliation.status,
            missing_fx_record_count=missing_fx,
            unknown_mapping_record_count=unknown_mapping,
        )

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


def _database_now(session: Session) -> datetime:
    value = session.scalar(select(func.now()))
    if value is None:
        raise RuntimeError("database clock is unavailable")
    return _utc(value)


def _cursor_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise CursorValidationError("invalid cursor") from exc


def _cursor_datetime(value: str) -> datetime:
    try:
        return _parse_datetime(value)
    except (TypeError, ValueError) as exc:
        raise CursorValidationError("invalid cursor") from exc


def _cursor_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise CursorValidationError("invalid cursor") from exc


def _cursor_text(value: str) -> str:
    if not value or len(value) > 500 or any(ord(character) < 32 for character in value):
        raise CursorValidationError("invalid cursor")
    return value


def _cursor_metric(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CursorValidationError("invalid cursor") from exc
    sentinel = Decimal("-1E30")
    if not parsed.is_finite() or (parsed != sentinel and parsed < 0):
        raise CursorValidationError("invalid cursor")
    return parsed


def _refresh_run_quality(run: IngestionRunModel) -> RefreshRunQualityView:
    steps: list[RefreshStepQualityView] = []
    for item in run.warnings or []:
        if not isinstance(item, dict):
            continue
        capability = item.get("capability")
        if not isinstance(capability, str) or not capability:
            continue
        status = item.get("status")
        raw_warnings = item.get("warnings")
        warnings = (
            tuple(str(value)[:500] for value in raw_warnings[:20])
            if isinstance(raw_warnings, list)
            else ()
        )
        steps.append(
            RefreshStepQualityView(
                capability=capability,
                status=status if isinstance(status, str) and status else run.status,
                warnings=warnings,
            )
        )
    return RefreshRunQualityView(
        id=str(run.id),
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        steps=tuple(steps),
    )


def _parse_datetime(value: str) -> datetime:
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise CursorValidationError("invalid cursor") from exc


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _transaction_filters(statement: Any, query: ActivityQuery) -> Any:
    if query.start_date is not None:
        statement = statement.where(
            TransactionModel.occurred_at >= datetime.combine(query.start_date, time.min, tzinfo=UTC)
        )
    if query.end_date is not None:
        statement = statement.where(
            TransactionModel.occurred_at
            < datetime.combine(query.end_date + timedelta(days=1), time.min, tzinfo=UTC)
        )
    membership = canonical_activity_type_membership(query.activity_type)
    if membership is not None:
        if not membership:
            statement = statement.where(literal(False))
        elif len(membership) == 1:
            statement = statement.where(
                func.lower(TransactionModel.transaction_type) == next(iter(membership))
            )
        else:
            statement = statement.where(
                func.lower(TransactionModel.transaction_type).in_(tuple(sorted(membership)))
            )
    return statement


def _position_collection_resource(sort: PositionSort) -> CollectionSnapshotResource:
    return {
        PositionSort.MARKET_VALUE_DESC: CollectionSnapshotResource.POSITIONS_MARKET_VALUE,
        PositionSort.WEIGHT_DESC: CollectionSnapshotResource.POSITIONS_WEIGHT,
        PositionSort.TICKER_ASC: CollectionSnapshotResource.POSITIONS_TICKER,
    }[sort]


def _dividend_filters(statement: Any, start: date | None, end: date | None) -> Any:
    if start is not None:
        statement = statement.where(DividendModel.paid_on >= start)
    if end is not None:
        statement = statement.where(DividendModel.paid_on <= end)
    return statement


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


def _instrument_view(listing: ListingModel, instrument: InstrumentModel) -> InstrumentView:
    return InstrumentView(
        id=str(instrument.id),
        instrument_id=str(instrument.id),
        listing_id=str(listing.id),
        ticker=listing.ticker,
        name=instrument.canonical_name,
        canonical_name=instrument.canonical_name,
        instrument_type=instrument.instrument_type,
        isin=instrument.isin,
        exchange_mic=listing.exchange_mic,
        exchange_id=listing.exchange_id,
        trading_currency=listing.trading_currency,
        provider=listing.provider,
        environment=listing.environment,
        listing_status=listing.status,
    )


def _latest_snapshot(session: Session, account_id: UUID) -> PortfolioSnapshotModel | None:
    return session.scalar(
        select(PortfolioSnapshotModel)
        .where(PortfolioSnapshotModel.broker_account_id == account_id)
        .order_by(
            PortfolioSnapshotModel.valuation_at.desc(),
            PortfolioSnapshotModel.id.desc(),
        )
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


def _reconciliation_gate_missing(
    run: ReconciliationRunModel | None,
    *,
    period_start: datetime | None,
    period_end: datetime | None,
) -> tuple[str, ...]:
    """Return stable fail-closed reasons for an economic reconciliation gate."""

    if run is None:
        return ("reconciliation_run",)
    missing: list[str] = []
    if run.status != "reconciled":
        missing.append("reconciled_material_inputs")
    if not run.coverage_complete or run.coverage_gaps:
        missing.append("complete_reconciliation_coverage")
    if _view_quality(run.quality_state) is not ViewQuality.FRESH:
        missing.append("fresh_reconciliation_inputs")
    if run.discrepancy_count:
        missing.append("zero_reconciliation_discrepancies")
    if period_start is not None and run.coverage_start_at > period_start:
        missing.append("reconciliation_coverage_at_period_start")
    if period_end is not None:
        if run.coverage_end_at < period_end:
            missing.append("reconciliation_coverage_at_period_end")
        if run.as_of < period_end:
            missing.append("reconciliation_at_period_end")
    return tuple(dict.fromkeys(missing))


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
    gate_missing = _reconciliation_gate_missing(
        run,
        period_start=snapshot.valuation_at,
        period_end=snapshot.valuation_at,
    )
    reconciliation_state = ViewQuality.PARTIAL if run is None else _view_quality(run.quality_state)
    state = _worst_quality_state((base.state, reconciliation_state))
    if gate_missing:
        state = _worst_quality_state((state, ViewQuality.PARTIAL))
    warning = (
        f"Latest reconciliation has {run.discrepancy_count} open discrepancy records."
        if run is not None and run.discrepancy_count
        else None
    )
    gate_warning = (
        "Reconciliation does not satisfy the current snapshot gate." if gate_missing else None
    )
    return _quality(
        state,
        as_of=max(base.as_of, run.as_of) if run is not None else base.as_of,
        source_at=(
            min(base.source_timestamp, run.coverage_end_at)
            if run is not None
            else base.source_timestamp
        ),
        warnings=tuple(
            dict.fromkeys(
                (
                    *base.warnings,
                    *((_warning_text(run.warnings)) if run is not None else ()),
                    *((warning,) if warning is not None else ()),
                    *((gate_warning,) if gate_warning is not None else ()),
                )
            )
        ),
        missing=tuple(
            dict.fromkeys(
                (
                    *base.missing_inputs,
                    *((run.coverage_gaps) if run is not None else ()),
                    *gate_missing,
                )
            )
        ),
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
    state = _worst_quality_state((start.state, end.state))
    return _quality(
        state,
        as_of=end.as_of,
        source_at=end.source_timestamp,
        warnings=tuple(dict.fromkeys((*start.warnings, *end.warnings))),
        missing=tuple(dict.fromkeys((*start.missing_inputs, *end.missing_inputs))),
    )


def _worst_quality_state(values: Sequence[ViewQuality]) -> ViewQuality:
    severity = {
        ViewQuality.FRESH: 0,
        ViewQuality.STALE: 1,
        ViewQuality.ESTIMATED: 2,
        ViewQuality.PARTIAL: 3,
        ViewQuality.UNRECONCILED: 4,
        ViewQuality.FAILED: 5,
    }
    return max(values or (ViewQuality.PARTIAL,), key=severity.__getitem__)


def _weight(value: Decimal | None, total: Decimal | None) -> Decimal | None:
    if value is None or total is None or total <= 0:
        return None
    return quantize_boundary(value / total, _RATIO_QUANTUM)


def _subtract(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return None if left is None or right is None else left - right


def _add(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return None if left is None or right is None else left + right
