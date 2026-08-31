"""Authorized Phase 1 portfolio use cases and deterministic synthetic implementation."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

from trading212_domain.fixtures import fixture_uuid
from trading212_security.principals import Authorizer, Principal, Scope
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from .ingestion import IngestionCapability, RunMode, validate_refresh_capabilities
from .views import (
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
    ReconciliationView,
    RefreshRunView,
    SnapshotComparisonView,
    SnapshotView,
    ViewQuality,
    paginate,
)


class PortfolioService(Protocol):
    async def list_accounts(self, principal: Principal) -> tuple[AccountView, ...]: ...

    async def get_account(self, principal: Principal, account_id: str) -> AccountView: ...

    async def get_summary(self, principal: Principal, account_id: str) -> AccountSummaryView: ...

    async def list_positions(
        self, principal: Principal, account_id: str, *, cursor: str | None, limit: int
    ) -> Page[PositionView]: ...

    async def get_position(
        self, principal: Principal, account_id: str, position_id: str
    ) -> PositionView: ...

    async def list_activity(
        self, principal: Principal, account_id: str, *, cursor: str | None, limit: int
    ) -> Page[ActivityView]: ...

    async def list_dividends(
        self, principal: Principal, account_id: str, *, cursor: str | None, limit: int
    ) -> Page[DividendView]: ...

    async def list_orders(
        self, principal: Principal, account_id: str, *, cursor: str | None, limit: int
    ) -> Page[OrderView]: ...

    async def get_allocation(
        self, principal: Principal, account_id: str
    ) -> tuple[AllocationView, ...]: ...

    async def list_snapshots(
        self, principal: Principal, account_id: str, *, cursor: str | None, limit: int
    ) -> Page[SnapshotView]: ...

    async def compare_snapshots(
        self, principal: Principal, account_id: str, start_id: str, end_id: str
    ) -> SnapshotComparisonView: ...

    async def get_reconciliation(
        self, principal: Principal, account_id: str
    ) -> ReconciliationView: ...

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
    ) -> None:
        self._authorizer = Authorizer()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._refresh_runs: dict[str, RefreshRunView] = {}
        self._refresh_idempotency: dict[str, str] = {}
        self._refresh_queue = refresh_queue
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

    async def owner_for_account(self, account_id: str) -> str | None:
        return self.OWNER_ID if account_id == self.ACCOUNT_ID else None

    async def _read_access(self, principal: Principal, account_id: str, scope: Scope) -> None:
        self._authorizer.require_scope(principal, scope, now=self._clock())
        await self._authorizer.require_account(principal, account_id, self)

    async def get_account(self, principal: Principal, account_id: str) -> AccountView:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        return self._account

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
        cursor: str | None,
        limit: int,
    ) -> Page[PositionView]:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        return paginate(self._positions, cursor=cursor, limit=limit)

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
        cursor: str | None,
        limit: int,
    ) -> Page[ActivityView]:
        await self._read_access(principal, account_id, Scope.ACTIVITY_READ)
        return paginate(self._activity, cursor=cursor, limit=limit)

    async def list_dividends(
        self,
        principal: Principal,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[DividendView]:
        await self._read_access(principal, account_id, Scope.ACTIVITY_READ)
        return paginate(self._dividends, cursor=cursor, limit=limit)

    async def list_orders(
        self,
        principal: Principal,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[OrderView]:
        await self._read_access(principal, account_id, Scope.ACTIVITY_READ)
        return paginate(self._orders, cursor=cursor, limit=limit)

    async def get_allocation(
        self, principal: Principal, account_id: str
    ) -> tuple[AllocationView, ...]:
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
        return tuple(rows)

    async def list_snapshots(
        self,
        principal: Principal,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[SnapshotView]:
        await self._read_access(principal, account_id, Scope.PORTFOLIO_READ)
        return paginate(self._snapshots, cursor=cursor, limit=limit)

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
            quality=self._quality,
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
        if not idempotency_key or len(idempotency_key) > 255:
            raise ValueError("invalid idempotency key")
        existing_id = self._refresh_idempotency.get(idempotency_key)
        if existing_id is not None:
            return self._refresh_runs[existing_id]
        requested_at = self._clock().astimezone(UTC)
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-refresh/{idempotency_key}"))
        result = RefreshRunView(
            id=run_id,
            account_id=account_id,
            status="succeeded",
            requested_at=requested_at,
            completed_at=requested_at,
            correlation_id=correlation_id,
            capabilities=tuple(capability.value for capability in selected),
            warnings=("synthetic local provider; no external broker request was made",),
        )
        self._refresh_runs[run_id] = result
        self._refresh_idempotency[idempotency_key] = run_id
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
