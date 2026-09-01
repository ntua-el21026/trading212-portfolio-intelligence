"""Authorized Phase 1 portfolio use cases and deterministic synthetic implementation."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from trading212_domain.fixtures import fixture_uuid
from trading212_security.principals import Authorizer, Principal, Scope
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from .ingestion import (
    FULL_REFRESH_ORDER,
    IngestionCapability,
    RunMode,
    validate_refresh_capabilities,
)
from .performance import (
    CorePerformanceInput,
    PerformanceSnapshotInput,
    calculate_core_performance,
)
from .queries import (
    ActivityQuery,
    ActivityTypeFilter,
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
from .refresh_semantics import (
    RefreshIdempotencyConflictError,
    RefreshRequestSemantics,
)
from .views import (
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
    RefreshRunView,
    SnapshotComparisonView,
    SnapshotDetailView,
    SnapshotView,
    ViewQuality,
)

_SYNTHETIC_CURSOR_SIGNING_KEY = hashlib.sha256(
    b"trading212-portfolio-intelligence/synthetic-cursor-signing-key/v1"
).digest()


@dataclass(frozen=True, slots=True)
class _MemoryCollectionSnapshot:
    id: str
    resource: str
    binding: str
    item_ids: tuple[str, ...]
    created_at: datetime
    expires_at: datetime
    source_identity: str | None = None


class PortfolioService(Protocol):
    async def list_broker_connections(
        self, principal: Principal
    ) -> tuple[BrokerConnectionView, ...]: ...

    async def list_accounts(self, principal: Principal) -> tuple[AccountView, ...]: ...

    async def get_account(self, principal: Principal, account_id: str) -> AccountView: ...

    async def get_summary(self, principal: Principal, account_id: str) -> AccountSummaryView: ...

    async def list_positions(
        self, principal: Principal, account_id: str, *, query: PositionQuery
    ) -> Page[PositionView]: ...

    async def get_position(
        self, principal: Principal, account_id: str, position_id: str
    ) -> PositionView: ...

    async def list_activity(
        self, principal: Principal, account_id: str, *, query: ActivityQuery
    ) -> Page[ActivityView]: ...

    async def list_dividends(
        self, principal: Principal, account_id: str, *, query: DividendQuery
    ) -> Page[DividendView]: ...

    async def get_dividend_summary(
        self, principal: Principal, account_id: str, *, query: DividendSummaryQuery
    ) -> DividendSummaryView: ...

    async def list_orders(
        self, principal: Principal, account_id: str, *, query: PageQuery
    ) -> Page[OrderView]: ...

    async def get_direct_allocation(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: DirectAllocationQuery,
    ) -> DirectAllocationView: ...

    async def list_snapshots(
        self, principal: Principal, account_id: str, *, query: PageQuery
    ) -> Page[SnapshotView]: ...

    async def get_snapshot(
        self, principal: Principal, account_id: str, snapshot_id: str
    ) -> SnapshotView: ...

    async def get_snapshot_detail(
        self, principal: Principal, account_id: str, snapshot_id: str
    ) -> SnapshotDetailView: ...

    async def compare_snapshots(
        self, principal: Principal, account_id: str, start_id: str, end_id: str
    ) -> SnapshotComparisonView: ...

    async def get_reconciliation(
        self, principal: Principal, account_id: str
    ) -> ReconciliationView: ...

    async def list_reconciliation_discrepancies(
        self, principal: Principal, account_id: str, *, query: PageQuery
    ) -> Page[ReconciliationIssueView]: ...

    async def search_instruments(
        self, principal: Principal, *, query: InstrumentQuery
    ) -> Page[InstrumentView]: ...

    async def get_instrument(self, principal: Principal, instrument_id: str) -> InstrumentView: ...

    async def get_core_performance_summary(
        self, principal: Principal, account_id: str
    ) -> PerformanceSummaryView: ...

    async def get_data_quality_summary(
        self, principal: Principal, account_id: str
    ) -> DataQualitySummaryView: ...

    async def refresh(
        self,
        principal: Principal,
        account_id: str,
        *,
        mode: RunMode,
        capabilities: tuple[IngestionCapability, ...],
        idempotency_key: str,
        correlation_id: str,
    ) -> RefreshRunView: ...

    async def get_refresh(self, principal: Principal, run_id: str) -> RefreshRunView: ...


class RefreshQueue(Protocol):
    async def enqueue(
        self,
        *,
        owner_id: str,
        account_id: str,
        mode: RunMode,
        capabilities: tuple[IngestionCapability, ...],
        idempotency_key: str,
        correlation_id: str,
    ) -> RefreshRunView: ...

    async def get(self, *, owner_id: str, run_id: str) -> RefreshRunView: ...


class RefreshUnavailableError(RuntimeError):
    """The durable refresh queue is temporarily unavailable."""


class SyntheticPortfolioService:
    """Deterministic local fixture implementing the same authorization/service boundary."""

    ACCOUNT_ID = str(fixture_uuid("account"))
    OWNER_ID = LOCAL_SYNTHETIC_OWNER_ID
    AS_OF = datetime(2026, 8, 31, 9, 30, tzinfo=UTC)
    SOURCE_AT = datetime(2026, 8, 31, 9, 28, tzinfo=UTC)

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        refresh_queue: RefreshQueue | None = None,
        cursor_signing_key: bytes | None = None,
        cursor_ttl_seconds: int = 3_600,
        refresh_initial_sync_required: bool = False,
    ) -> None:
        self._authorizer = Authorizer()
        self._clock = clock or (lambda: self.AS_OF)
        self._refresh_runs: dict[str, RefreshRunView] = {}
        self._refresh_idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self._refresh_lock = asyncio.Lock()
        self._refresh_initial_sync_required = refresh_initial_sync_required
        self._refresh_queue = refresh_queue
        self._cursor_ttl_seconds = cursor_ttl_seconds
        self._cursors = CursorCodec(
            cursor_signing_key or _SYNTHETIC_CURSOR_SIGNING_KEY,
            clock=self._clock,
            ttl_seconds=cursor_ttl_seconds,
        )
        self._collection_snapshots: dict[str, _MemoryCollectionSnapshot] = {}
        self._collection_snapshot_sequence = 0
        self._quality = QualityView(
            state=ViewQuality.FRESH,
            as_of=self.AS_OF,
            source_timestamp=self.SOURCE_AT,
            freshness_threshold_seconds=900,
        )
        self._account = AccountView(
            id=self.ACCOUNT_ID,
            display_name="Long-term investment account",
            provider="synthetic",
            environment="synthetic",
            account_type="invest",
            reporting_currency="EUR",
            connection_state="connected_read_only",
            last_refresh_at=self.AS_OF,
        )
        self._positions = _positions(self._quality)
        self._activity = _activity(self._quality)
        self._dividends = _dividends(self._quality)
        self._orders = _orders(self._quality)
        self._snapshots = _snapshots(self._quality)
        self._position_snapshot_id = self._snapshots[-1].id
        self._instruments = _instruments(self._positions)

    async def owner_for_account(self, account_id: str) -> str | None:
        return self.OWNER_ID if account_id == self.ACCOUNT_ID else None

    async def _read_access(self, principal: Principal, account_id: str, scope: Scope) -> None:
        self._authorizer.require_scope(principal, scope, now=self._clock())
        await self._authorizer.require_account(principal, account_id, self)

    async def get_account(self, principal: Principal, account_id: str) -> AccountView:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        return self._account

    async def list_broker_connections(
        self, principal: Principal
    ) -> tuple[BrokerConnectionView, ...]:
        await self._read_access(principal, self.ACCOUNT_ID, Scope.CONFIGURATION_READ)
        return (
            BrokerConnectionView(
                id=str(fixture_uuid("connection")),
                provider="synthetic",
                environment="synthetic",
                status="active",
                credential_configured=False,
                last_successful_refresh_at=self.AS_OF,
            ),
        )

    async def list_accounts(self, principal: Principal) -> tuple[AccountView, ...]:
        await self._read_access(principal, self.ACCOUNT_ID, Scope.PORTFOLIO_READ)
        return (self._account,)

    async def get_summary(self, principal: Principal, account_id: str) -> AccountSummaryView:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        return AccountSummaryView(
            account=self._account,
            total_value=_metric("248431.27", "broker account plus canonical components"),
            cash_balance=_metric("12431.27", "canonical cash ledger"),
            invested_value=_metric("236000.00", "sum of direct provider-observed positions"),
            net_contributions=_metric("230000.00", "covered external cash flows only"),
            dividends_received=_metric("1738.20", "covered normalized dividend history"),
            realized_profit_loss=_unavailable(
                "EUR",
                "complete disposal basis is not available in the synthetic fixture",
                "weighted-average acquisition policy",
            ),
            unrealized_profit_loss=_metric(
                "18431.27",
                "provider-reported unrealized profit/loss retained separately",
                provenance=("provider_position_observations",),
            ),
            quality=self._quality,
            position_count=len(self._positions),
        )

    async def list_positions(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: PositionQuery,
    ) -> Page[PositionView]:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        search = query.search.strip().casefold() if query.search is not None else None
        values = [
            item
            for item in self._positions
            if search is None or search in item.ticker.casefold() or search in item.name.casefold()
        ]
        if query.sort is PositionSort.TICKER_ASC:
            values.sort(key=lambda item: (item.ticker.casefold(), item.id))
        elif query.sort is PositionSort.WEIGHT_DESC:
            values.sort(key=lambda item: (item.ticker.casefold(), item.id))
            values.sort(
                key=lambda item: (
                    item.direct_weight if item.direct_weight is not None else Decimal("-1")
                ),
                reverse=True,
            )
        else:
            values.sort(key=lambda item: (item.ticker.casefold(), item.id))
            values.sort(
                key=lambda item: (
                    item.market_value.value
                    if item.market_value.value is not None
                    else Decimal("-1")
                ),
                reverse=True,
            )
        return self._memory_collection_snapshot_page(
            self._positions,
            initial_values=values,
            query=query,
            resource={
                PositionSort.MARKET_VALUE_DESC: "positions_market_value",
                PositionSort.WEIGHT_DESC: "positions_weight",
                PositionSort.TICKER_ASC: "positions_ticker",
            }[query.sort],
            binding=cursor_binding(
                "collection-query-snapshot",
                principal.owner_id,
                account_id,
                "positions",
                query.sort,
                search,
            ),
            item_id=lambda item: item.id,
            source_identity=self._position_snapshot_id,
        )

    async def get_position(
        self, principal: Principal, account_id: str, position_id: str
    ) -> PositionView:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        for position in self._positions:
            if position.id == position_id:
                return position
        raise LookupError("position not found")

    async def list_activity(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: ActivityQuery,
    ) -> Page[ActivityView]:
        await self._read_access(principal, account_id, Scope.ACTIVITY_READ)
        values = [
            item
            for item in self._activity
            if _in_period(item.occurred_at.date(), query.start_date, query.end_date)
            and _activity_matches(item.activity_type, query.activity_type)
        ]
        values.sort(key=lambda item: (item.occurred_at, item.id), reverse=True)
        return self._memory_collection_snapshot_page(
            self._activity,
            initial_values=values,
            query=query,
            resource="activity",
            binding=cursor_binding(
                "collection-query-snapshot",
                principal.owner_id,
                account_id,
                "activity",
                "occurred_at_desc_id_desc",
                query.start_date,
                query.end_date,
                query.activity_type,
            ),
            item_id=lambda item: item.id,
        )

    async def list_dividends(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: DividendQuery,
    ) -> Page[DividendView]:
        await self._read_access(principal, account_id, Scope.ACTIVITY_READ)
        values = [
            item
            for item in self._dividends
            if _in_period(item.paid_on, query.start_date, query.end_date)
        ]
        values.sort(key=lambda item: (item.paid_on, item.id), reverse=True)
        return self._memory_collection_snapshot_page(
            self._dividends,
            initial_values=values,
            query=query,
            resource="dividends",
            binding=cursor_binding(
                "collection-query-snapshot",
                principal.owner_id,
                account_id,
                "dividends",
                "paid_on_desc_id_desc",
                query.start_date,
                query.end_date,
            ),
            item_id=lambda item: item.id,
        )

    async def get_dividend_summary(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: DividendSummaryQuery,
    ) -> DividendSummaryView:
        await self._read_access(principal, account_id, Scope.ACTIVITY_READ)
        values = [
            item for item in self._dividends if query.start_date <= item.paid_on <= query.end_date
        ]
        values.sort(key=lambda item: (item.paid_on, item.id), reverse=True)
        totals = _dividend_totals(values)
        selected_totals = totals[:20]
        omitted = len(totals) - len(selected_totals)
        quality = (
            self._quality
            if omitted == 0
            else QualityView(
                state=ViewQuality.PARTIAL,
                as_of=self._quality.as_of,
                source_timestamp=self._quality.source_timestamp,
                freshness_threshold_seconds=self._quality.freshness_threshold_seconds,
                warnings=("Dividend currency aggregates exceed the bounded output.",),
                missing_inputs=("dividend_currency_groups",),
            )
        )
        return DividendSummaryView(
            start_date=query.start_date,
            end_date=query.end_date,
            totals=selected_totals,
            recent=tuple(values[: query.recent_limit]),
            covered_record_count=len(values),
            totals_truncated=omitted > 0,
            omitted_currency_count=omitted,
            quality=quality,
        )

    async def list_orders(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: PageQuery,
    ) -> Page[OrderView]:
        await self._read_access(principal, account_id, Scope.ACTIVITY_READ)
        values = sorted(self._orders, key=lambda item: (item.created_at, item.id), reverse=True)
        return self._memory_page(
            values,
            query=query,
            resource="orders",
            binding=cursor_binding(account_id),
            key=lambda item: (item.created_at.isoformat(), item.id),
        )

    async def get_direct_allocation(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: DirectAllocationQuery,
    ) -> DirectAllocationView:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        rows = [
            AllocationView(
                id=position.id,
                label=position.name,
                asset_type=position.instrument_type,
                market_value=position.market_value,
                weight=position.direct_weight,
                weight_availability=Availability.AVAILABLE,
            )
            for position in self._positions
        ]
        rows.append(
            AllocationView(
                id="cash",
                label="Cash",
                asset_type="cash",
                market_value=_metric("12431.27", "canonical cash ledger"),
                weight=Decimal("0.050039071168"),
                weight_availability=Availability.AVAILABLE,
            )
        )
        values = tuple(rows)
        cash = tuple(
            item for item in values if item.asset_type.casefold() == "cash" or item.id == "cash"
        )
        positions = tuple(item for item in values if item not in cash)
        ordered = sorted(positions, key=lambda item: item.id)
        ordered.sort(
            key=lambda item: item.weight if item.weight is not None else Decimal("-1"),
            reverse=True,
        )
        selected_cash = cash[:1]
        return DirectAllocationView(
            items=(*ordered[: query.top_n], *selected_cash),
            total=len(positions) + len(cash),
            truncated=len(positions) > query.top_n or len(cash) > len(selected_cash),
        )

    async def list_snapshots(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: PageQuery,
    ) -> Page[SnapshotView]:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        values = sorted(
            self._snapshots, key=lambda item: (item.valuation_at, item.id), reverse=True
        )
        return self._memory_page(
            values,
            query=query,
            resource="snapshots",
            binding=cursor_binding(account_id),
            key=lambda item: (item.valuation_at.isoformat(), item.id),
        )

    async def get_snapshot(
        self, principal: Principal, account_id: str, snapshot_id: str
    ) -> SnapshotView:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        for snapshot in self._snapshots:
            if snapshot.id == snapshot_id:
                return snapshot
        raise LookupError("snapshot not found")

    async def get_snapshot_detail(
        self, principal: Principal, account_id: str, snapshot_id: str
    ) -> SnapshotDetailView:
        snapshot = await self.get_snapshot(principal, account_id, snapshot_id)
        reason = (
            "This metric is not persisted with the immutable portfolio snapshot and "
            "cannot be reconstructed at that historical cutoff."
        )
        return SnapshotDetailView(
            snapshot=snapshot,
            dividends_received=_unavailable(
                snapshot.reporting_currency,
                reason,
                "snapshot-cutoff dividend coverage gate",
            ),
            realized_profit_loss=_unavailable(
                snapshot.reporting_currency,
                reason,
                "snapshot-cutoff realized profit/loss coverage gate",
            ),
            unrealized_profit_loss=_unavailable(
                snapshot.reporting_currency,
                reason,
                "snapshot-cutoff unrealized profit/loss coverage gate",
            ),
        )

    async def compare_snapshots(
        self,
        principal: Principal,
        account_id: str,
        start_id: str,
        end_id: str,
    ) -> SnapshotComparisonView:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        indexed = {snapshot.id: snapshot for snapshot in self._snapshots}
        try:
            start, end = indexed[start_id], indexed[end_id]
        except KeyError as exc:
            raise LookupError("snapshot not found") from exc
        assert end.total_value.value is not None
        assert start.total_value.value is not None
        value_change = end.total_value.value - start.total_value.value
        external = Decimal("0")
        return SnapshotComparisonView(
            start=start,
            end=end,
            value_change=_metric(str(value_change), "ending value minus beginning value"),
            net_external_flows=_metric(str(external), "covered external flows in period"),
            investment_result=_metric(
                str(value_change - external),
                "value change less external flows",
            ),
            reconciliation_residual=_metric("0", "versioned accounting bridge residual"),
            quality=self._quality,
        )

    async def get_reconciliation(self, principal: Principal, account_id: str) -> ReconciliationView:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        return ReconciliationView(
            status="reconciled",
            evaluated_at=self.AS_OF,
            algorithm_version="phase1-reconciliation/1.0.0",
            tolerance_version="phase1-tolerance/1.0.0",
            issues=(),
            discrepancy_count=0,
            quality=self._quality,
        )

    async def list_reconciliation_discrepancies(
        self,
        principal: Principal,
        account_id: str,
        *,
        query: PageQuery,
    ) -> Page[ReconciliationIssueView]:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        return self._memory_page(
            [],
            query=query,
            resource="reconciliation_discrepancies",
            binding=cursor_binding(account_id, "synthetic-reconciliation"),
            key=lambda item: (item.id,),
        )

    async def search_instruments(
        self, principal: Principal, *, query: InstrumentQuery
    ) -> Page[InstrumentView]:
        await self._read_access(principal, self.ACCOUNT_ID, Scope.PORTFOLIO_READ)
        search = query.search.strip().casefold() if query.search is not None else None
        values = [
            item
            for item in self._instruments
            if search is None or search in item.ticker.casefold() or search in item.name.casefold()
        ]
        values.sort(
            key=lambda item: (
                item.provider,
                item.environment,
                item.ticker.casefold(),
                item.canonical_name.casefold(),
                item.listing_id,
            )
        )
        return self._memory_collection_snapshot_page(
            self._instruments,
            initial_values=values,
            query=query,
            resource="instruments",
            binding=cursor_binding(
                "collection-query-snapshot",
                principal.owner_id,
                None,
                "instruments",
                "provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc",
                search,
                "synthetic/synthetic",
            ),
            item_id=lambda item: item.listing_id,
        )

    async def get_instrument(self, principal: Principal, instrument_id: str) -> InstrumentView:
        await self._read_access(principal, self.ACCOUNT_ID, Scope.PORTFOLIO_READ)
        for instrument in self._instruments:
            if instrument.instrument_id == instrument_id:
                return instrument
        raise LookupError("instrument not found")

    async def get_core_performance_summary(
        self, principal: Principal, account_id: str
    ) -> PerformanceSummaryView:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        return calculate_core_performance(
            CorePerformanceInput(
                snapshots=tuple(
                    PerformanceSnapshotInput(
                        snapshot_id=item.id,
                        valuation_at=item.valuation_at,
                        value=item.total_value.value,
                        currency=item.reporting_currency,
                        quality=item.quality.state,
                    )
                    for item in self._snapshots
                ),
                external_flows=(),
                reporting_currency=self._account.reporting_currency,
                evaluated_at=self.AS_OF,
                coverage_start_at=self._snapshots[0].valuation_at,
                coverage_end_at=self._snapshots[-1].valuation_at,
                coverage_complete=True,
            )
        )

    async def get_data_quality_summary(
        self, principal: Principal, account_id: str
    ) -> DataQualitySummaryView:
        authorization_time = self._clock()
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
        return DataQualitySummaryView(
            as_of=summary.quality.as_of,
            reporting_currency=summary.account.reporting_currency,
            quality=summary.quality,
            capabilities=tuple(
                CapabilityQualityView(capability=name, quality=summary.quality)
                for name in (
                    "account_summary",
                    "portfolio_snapshots",
                    "positions",
                    "activity",
                    "dividends",
                    "reconciliation",
                )
            ),
            failed_or_partial_runs=(),
            latest_refresh_run=None,
            latest_runs_by_status=(),
            checkpoints=tuple(
                CheckpointQualityView(
                    capability=name,
                    version=1,
                    coverage_start_at=self._snapshots[0].valuation_at,
                    coverage_end_at=self._snapshots[-1].valuation_at,
                    coverage_complete=True,
                )
                for name in (
                    "portfolio_positions",
                    "historical_transactions",
                    "historical_dividends",
                )
            ),
            latest_snapshot_id=self._snapshots[-1].id,
            latest_snapshot_source_cutoff_at=self._snapshots[-1].source_cutoff_at,
            materialization_state="available",
            reconciliation_status="reconciled",
            missing_fx_record_count=0,
            unknown_mapping_record_count=0,
        )

    def _memory_page[ItemT](
        self,
        values: Sequence[ItemT],
        *,
        query: PageQuery,
        resource: str,
        binding: str,
        key: Callable[[ItemT], tuple[str, ...]],
    ) -> Page[ItemT]:
        cutoff = _utc(self._clock())
        start = 0
        if query.cursor is not None:
            cutoff, cursor_key = self._cursors.decode(
                query.cursor,
                resource=resource,
                binding=binding,
                key_size=len(key(values[0])) if values else 1,
            )
            for index, value in enumerate(values):
                if key(value) == cursor_key:
                    start = index + 1
                    break
            else:
                raise CursorValidationError("invalid cursor")
        selected = tuple(values[start : start + query.limit])
        next_cursor = None
        if start + len(selected) < len(values) and selected:
            next_cursor = self._cursors.encode(
                resource=resource,
                binding=binding,
                read_cutoff=cutoff,
                key=key(selected[-1]),
            )
        return Page(selected, next_cursor, query.limit, len(values))

    def _memory_collection_snapshot_page[ItemT](
        self,
        current_values: Sequence[ItemT],
        *,
        initial_values: Sequence[ItemT],
        query: PageQuery,
        resource: str,
        binding: str,
        item_id: Callable[[ItemT], str],
        source_identity: str | None = None,
    ) -> Page[ItemT]:
        now = _utc(self._clock())
        expired = tuple(
            snapshot_id
            for snapshot_id, snapshot in self._collection_snapshots.items()
            if snapshot.expires_at <= now
        )
        for snapshot_id in expired:
            del self._collection_snapshots[snapshot_id]

        after_ordinal = 0
        if query.cursor is None:
            item_ids = tuple(item_id(item) for item in initial_values)
            if len(item_ids) != len(set(item_ids)):
                raise ValueError("collection snapshot record IDs must be unique")
            snapshot = next(
                (
                    existing
                    for existing in self._collection_snapshots.values()
                    if existing.resource == resource
                    and existing.binding == binding
                    and existing.item_ids == item_ids
                    and existing.source_identity == source_identity
                ),
                None,
            )
            if snapshot is None:
                self._collection_snapshot_sequence += 1
                snapshot_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        "trading212-portfolio-intelligence/synthetic-collection-snapshot/"
                        f"{self._collection_snapshot_sequence}/{resource}/{binding}",
                    )
                )
                snapshot = _MemoryCollectionSnapshot(
                    id=snapshot_id,
                    resource=resource,
                    binding=binding,
                    item_ids=item_ids,
                    created_at=now,
                    expires_at=now + timedelta(seconds=self._cursor_ttl_seconds),
                    source_identity=source_identity,
                )
                self._collection_snapshots[snapshot.id] = snapshot
        else:
            try:
                created_at, key = self._cursors.decode(
                    query.cursor,
                    resource=f"collection_snapshot.{resource}",
                    binding=binding,
                    key_size=2,
                )
                snapshot = self._collection_snapshots[key[0]]
                after_ordinal = int(key[1])
                if (
                    snapshot.resource != resource
                    or snapshot.binding != binding
                    or snapshot.created_at != created_at
                    or snapshot.expires_at <= now
                    or after_ordinal < 1
                    or after_ordinal >= len(snapshot.item_ids)
                ):
                    raise CursorValidationError("invalid cursor")
            except CursorValidationError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise CursorValidationError("invalid cursor") from exc

        selected_ids = snapshot.item_ids[after_ordinal : after_ordinal + query.limit]
        indexed = {item_id(item): item for item in current_values}
        try:
            selected = tuple(indexed[record_id] for record_id in selected_ids)
        except KeyError as exc:
            raise CursorValidationError("invalid cursor") from exc
        next_ordinal = after_ordinal + len(selected)
        next_cursor = None
        if next_ordinal < len(snapshot.item_ids) and selected:
            next_cursor = self._cursors.encode(
                resource=f"collection_snapshot.{resource}",
                binding=binding,
                read_cutoff=snapshot.created_at,
                key=(snapshot.id, str(next_ordinal)),
            )
        return Page(selected, next_cursor, query.limit, len(snapshot.item_ids))

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
        if not isinstance(mode, RunMode):
            raise ValueError("only typed refresh modes are accepted")
        selected = validate_refresh_capabilities(capabilities)
        if self._refresh_queue is not None:
            return await self._refresh_queue.enqueue(
                owner_id=principal.owner_id,
                account_id=account_id,
                mode=mode,
                capabilities=selected,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        if not idempotency_key or len(idempotency_key) > 180:
            raise ValueError("invalid idempotency key")
        fingerprint = RefreshRequestSemantics.create(
            owner_id=principal.owner_id,
            account_id=account_id,
            mode=mode,
            capabilities=selected,
        ).fingerprint
        scoped_key = (account_id, idempotency_key)
        async with self._refresh_lock:
            existing = self._refresh_idempotency.get(scoped_key)
            if existing is not None:
                existing_fingerprint, existing_id = existing
                if existing_fingerprint != fingerprint:
                    raise RefreshIdempotencyConflictError(
                        "idempotency key is already bound to different refresh semantics"
                    )
                return self._refresh_runs[existing_id]
            requested_at = _utc(self._clock())
            run_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"synthetic-refresh/{account_id}/{idempotency_key}",
                )
            )
            effective = FULL_REFRESH_ORDER if self._refresh_initial_sync_required else selected
            promotion = (
                "initial synchronization promoted the request to full/all capability coverage"
                if self._refresh_initial_sync_required
                and (mode is not RunMode.FULL or selected != FULL_REFRESH_ORDER)
                else None
            )
            result = RefreshRunView(
                id=run_id,
                account_id=account_id,
                status="succeeded",
                requested_at=requested_at,
                completed_at=requested_at,
                correlation_id=correlation_id,
                capabilities=tuple(capability.value for capability in effective),
                warnings=tuple(
                    item
                    for item in (
                        promotion,
                        "synthetic local provider; no external broker request was made",
                    )
                    if item is not None
                ),
            )
            self._refresh_runs[run_id] = result
            self._refresh_idempotency[scoped_key] = (fingerprint, run_id)
            return result

    async def get_refresh(self, principal: Principal, run_id: str) -> RefreshRunView:
        self._authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=self._clock())
        if self._refresh_queue is not None:
            return await self._refresh_queue.get(owner_id=principal.owner_id, run_id=run_id)
        result = self._refresh_runs.get(run_id)
        if result is None:
            raise LookupError("refresh run not found")
        await self._read_access(principal, result.account_id, Scope.PORTFOLIO_READ)
        return result


def _metric(
    value: str,
    methodology: str,
    *,
    provenance: Sequence[str] = ("synthetic_canonical_fixture",),
) -> MetricView:
    return MetricView(
        value=Decimal(value),
        currency="EUR",
        availability=Availability.AVAILABLE,
        calculation_version="phase1-core-accounting/1.0.0",
        methodology=methodology,
        provenance=tuple(provenance),
    )


def _unavailable(currency: str, reason: str, methodology: str) -> MetricView:
    return MetricView(
        value=None,
        currency=currency,
        availability=Availability.UNAVAILABLE,
        calculation_version="phase1-core-accounting/1.0.0",
        methodology=methodology,
        provenance=("coverage_gate",),
        unavailable_reason=reason,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _in_period(value: date, start: date | None, end: date | None) -> bool:
    return (start is None or value >= start) and (end is None or value <= end)


def _activity_matches(value: str, requested: ActivityTypeFilter) -> bool:
    membership = canonical_activity_type_membership(requested)
    return membership is None or value.casefold() in membership


def _dividend_totals(values: Sequence[DividendView]) -> tuple[DividendCurrencyTotalView, ...]:
    totals: dict[str, list[Decimal | None]] = {}
    for item in values:
        row = totals.setdefault(item.net_amount.currency, [Decimal(0), Decimal(0), Decimal(0)])
        assert item.net_amount.value is not None
        row[0] = (row[0] or Decimal(0)) + item.net_amount.value
        row[1] = (
            None
            if row[1] is None or item.gross_amount.value is None
            else row[1] + item.gross_amount.value
        )
        row[2] = (
            None
            if row[2] is None or item.withholding_tax.value is None
            else row[2] + item.withholding_tax.value
        )
    return tuple(
        DividendCurrencyTotalView(
            currency=currency,
            net_amount=values[0] or Decimal(0),
            gross_amount=values[1],
            withholding_tax=values[2],
        )
        for currency, values in sorted(totals.items())
    )


def _instruments(positions: Sequence[PositionView]) -> tuple[InstrumentView, ...]:
    held = tuple(
        InstrumentView(
            id=f"instrument-{item.id}",
            instrument_id=f"instrument-{item.id}",
            listing_id=item.id,
            ticker=item.ticker,
            name=item.name,
            canonical_name=item.name,
            instrument_type=item.instrument_type,
            isin=None,
            exchange_mic="XETR",
            exchange_id="synthetic-xetr",
            trading_currency=item.trading_currency,
            provider="synthetic",
            environment="synthetic",
            listing_status="active",
        )
        for item in positions
    )
    return (
        *held,
        InstrumentView(
            id="instrument-sxr8-unheld",
            instrument_id="instrument-sxr8-unheld",
            listing_id="sxr8-unheld",
            ticker="SXR8",
            name="iShares Core S&P 500 UCITS ETF",
            canonical_name="iShares Core S&P 500 UCITS ETF",
            instrument_type="etf",
            isin="IE00B5BMR087",
            exchange_mic="XETR",
            exchange_id="synthetic-xetr",
            trading_currency="EUR",
            provider="synthetic",
            environment="synthetic",
            listing_status="active",
        ),
    )


def _positions(quality: QualityView) -> tuple[PositionView, ...]:
    rows = (
        (
            "vwce",
            "VWCE",
            "Vanguard FTSE All-World UCITS ETF",
            "etf",
            "412.5",
            "252.121212",
            "104000",
            "0.418626849994",
        ),
        (
            "iwda",
            "IWDA",
            "iShares Core MSCI World UCITS ETF",
            "etf",
            "612.75",
            "104.447164",
            "64000",
            "0.257616523073",
        ),
        (
            "asml",
            "ASML",
            "ASML Holding",
            "equity",
            "48",
            "750",
            "36000",
            "0.144909294229",
        ),
        (
            "msft",
            "MSFT",
            "Microsoft",
            "equity",
            "52",
            "423.076923",
            "22000",
            "0.088555679806",
        ),
        (
            "novo",
            "NOVO-B",
            "Novo Nordisk",
            "equity",
            "125",
            "80",
            "10000",
            "0.040252581730",
        ),
    )
    return tuple(
        PositionView(
            id=position_id,
            ticker=ticker,
            name=name,
            instrument_type=instrument_type,
            quantity=Decimal(quantity),
            trading_currency="EUR",
            current_price=Decimal(price),
            market_value=_metric(value, "provider-observed market value"),
            provider_cost_basis=_metric(
                str(Decimal(value) * Decimal("0.93")),
                "provider-reported cost basis",
                provenance=("provider_position_observations",),
            ),
            provider_unrealized_profit_loss=_metric(
                str(Decimal(value) * Decimal("0.07")),
                "provider-reported unrealized profit/loss",
                provenance=("provider_position_observations",),
            ),
            direct_weight=Decimal(weight),
            quality=quality,
        )
        for position_id, ticker, name, instrument_type, quantity, price, value, weight in rows
    )


def _activity(quality: QualityView) -> tuple[ActivityView, ...]:
    return (
        ActivityView(
            id="tx-2026-08-dividend-vwce",
            occurred_at=datetime(2026, 8, 28, 8, 0, tzinfo=UTC),
            activity_type="dividend",
            direction="credit",
            amount=_metric("418.20", "normalized investment income"),
            ticker="VWCE",
            quantity=None,
            description="Dividend received",
            quality=quality,
        ),
        ActivityView(
            id="tx-2026-08-buy-asml",
            occurred_at=datetime(2026, 8, 12, 14, 32, tzinfo=UTC),
            activity_type="buy",
            direction="internal_exchange",
            amount=_metric("-7500.00", "normalized security purchase cash leg"),
            ticker="ASML",
            quantity=Decimal("10"),
            description="Bought 10 ASML shares",
            quality=quality,
        ),
        ActivityView(
            id="tx-2026-07-deposit",
            occurred_at=datetime(2026, 7, 1, 9, 15, tzinfo=UTC),
            activity_type="deposit",
            direction="external_inflow",
            amount=_metric("10000.00", "normalized external contribution"),
            ticker=None,
            quantity=None,
            description="Bank transfer contribution",
            quality=quality,
        ),
    )


def _dividends(quality: QualityView) -> tuple[DividendView, ...]:
    return (
        DividendView(
            id="dividend-vwce-20260828",
            paid_on=date(2026, 8, 28),
            ticker="VWCE",
            net_amount=_metric("418.20", "normalized provider dividend"),
            gross_amount=_metric("492.00", "provider-reported gross dividend"),
            withholding_tax=_metric("-73.80", "provider-reported withholding"),
            quantity=Decimal("412.5"),
            quality=quality,
        ),
    )


def _orders(quality: QualityView) -> tuple[OrderView, ...]:
    return (
        OrderView(
            id="order-asml-20260812",
            created_at=datetime(2026, 8, 12, 14, 31, tzinfo=UTC),
            ticker="ASML",
            side="buy",
            order_type="market",
            status="filled",
            quantity=Decimal("10"),
            filled_quantity=Decimal("10"),
            limit_price=None,
            observed_value=_metric("7500.00", "provider-observed filled order value"),
            quality=quality,
        ),
    )


def _snapshots(quality: QualityView) -> tuple[SnapshotView, ...]:
    return (
        SnapshotView(
            id="snapshot-2026-07-31",
            valuation_at=datetime(2026, 7, 31, 16, 30, tzinfo=UTC),
            source_cutoff_at=datetime(2026, 7, 31, 16, 28, tzinfo=UTC),
            reporting_currency="EUR",
            total_value=_metric("241220.18", "immutable portfolio snapshot"),
            cash_value=_metric("10420.18", "immutable cash snapshot"),
            invested_value=_metric("230800.00", "immutable position snapshots"),
            net_contributions=_metric("230000.00", "covered external cash flows"),
            quality=quality,
        ),
        SnapshotView(
            id="snapshot-2026-08-31",
            valuation_at=SyntheticPortfolioService.AS_OF,
            source_cutoff_at=SyntheticPortfolioService.SOURCE_AT,
            reporting_currency="EUR",
            total_value=_metric("248431.27", "immutable portfolio snapshot"),
            cash_value=_metric("12431.27", "immutable cash snapshot"),
            invested_value=_metric("236000.00", "immutable position snapshots"),
            net_contributions=_metric("230000.00", "covered external cash flows"),
            quality=quality,
        ),
    )
