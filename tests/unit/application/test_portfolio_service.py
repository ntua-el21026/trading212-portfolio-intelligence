from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from trading212_application.ingestion import HISTORY_REFRESH_ORDER, RunMode
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import Availability, ViewQuality
from trading212_security.principals import AuthorizationError, Principal, Scope
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

NOW = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)


def _principal(
    *,
    owner_id: str = LOCAL_SYNTHETIC_OWNER_ID,
    scopes: frozenset[Scope] | None = None,
) -> Principal:
    return Principal(
        principal_id="synthetic-principal",
        owner_id=owner_id,
        issuer="local.synthetic",
        subject="synthetic-owner",
        scopes=scopes
        or frozenset(
            {
                Scope.PORTFOLIO_READ,
                Scope.ACTIVITY_READ,
                Scope.PORTFOLIO_REFRESH,
            }
        ),
        authenticated_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_summary_uses_exact_values_and_explicit_unavailable_metrics() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    summary = await service.get_summary(_principal(), service.ACCOUNT_ID)
    assert summary.total_value.value == Decimal("248431.27")
    assert summary.cash_balance.value is not None
    assert summary.invested_value.value is not None
    assert summary.total_value.value is not None
    assert summary.cash_balance.value + summary.invested_value.value == summary.total_value.value
    assert summary.realized_profit_loss.value is None
    assert summary.realized_profit_loss.availability is Availability.UNAVAILABLE
    assert summary.realized_profit_loss.unavailable_reason
    assert summary.quality.state is ViewQuality.FRESH


@pytest.mark.asyncio
async def test_positions_are_cursor_paginated_and_weights_include_cash_residual() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    first = await service.list_positions(_principal(), service.ACCOUNT_ID, cursor=None, limit=2)
    second = await service.list_positions(
        _principal(), service.ACCOUNT_ID, cursor=first.next_cursor, limit=100
    )
    assert len(first.items) == 2
    assert len(second.items) == 3
    assert second.next_cursor is None
    allocation = await service.get_allocation(_principal(), service.ACCOUNT_ID)
    assert sum(row.weight or Decimal(0) for row in allocation) == Decimal("1.000000000000")


@pytest.mark.asyncio
async def test_accounts_and_order_observations_are_authorized_typed_reads() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    accounts = await service.list_accounts(_principal())
    orders = await service.list_orders(_principal(), service.ACCOUNT_ID, cursor=None, limit=20)
    assert [account.id for account in accounts] == [service.ACCOUNT_ID]
    assert len(orders.items) == 1
    assert orders.items[0].status == "filled"
    assert orders.items[0].observed_value.value == Decimal("7500.00")


@pytest.mark.asyncio
async def test_activity_scope_and_cross_owner_access_are_enforced() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    with pytest.raises(AuthorizationError, match="access denied"):
        await service.list_activity(
            _principal(scopes=frozenset({Scope.PORTFOLIO_READ})),
            service.ACCOUNT_ID,
            cursor=None,
            limit=20,
        )
    with pytest.raises(AuthorizationError, match="access denied"):
        await service.get_summary(_principal(owner_id="other-owner"), service.ACCOUNT_ID)
    with pytest.raises(AuthorizationError, match="access denied"):
        await service.get_summary(_principal(), "unknown-account")


@pytest.mark.asyncio
async def test_snapshot_comparison_preserves_accounting_identity() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    comparison = await service.compare_snapshots(
        _principal(),
        service.ACCOUNT_ID,
        "snapshot-2026-07-31",
        "snapshot-2026-08-31",
    )
    assert comparison.value_change.value == Decimal("7211.09")
    assert comparison.net_external_flows.value == Decimal("0")
    assert comparison.investment_result.value == Decimal("7211.09")
    assert comparison.reconciliation_residual.value == Decimal("0")


@pytest.mark.asyncio
async def test_refresh_is_high_level_scope_checked_and_idempotent() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    principal = _principal()
    first = await service.refresh(
        principal,
        service.ACCOUNT_ID,
        mode=RunMode.INCREMENTAL,
        capabilities=HISTORY_REFRESH_ORDER,
        idempotency_key="manual-refresh-1",
        correlation_id="correlation-1",
    )
    second = await service.refresh(
        principal,
        service.ACCOUNT_ID,
        mode=RunMode.FULL,
        capabilities=HISTORY_REFRESH_ORDER,
        idempotency_key="manual-refresh-1",
        correlation_id="different-correlation",
    )
    assert first == second
    assert first.status == "succeeded"
    assert first.capabilities == tuple(capability.value for capability in HISTORY_REFRESH_ORDER)


def test_invalid_metric_and_pagination_contracts_fail_closed() -> None:
    from trading212_application.views import MetricView, paginate

    with pytest.raises(ValueError, match="availability"):
        MetricView(
            value=None,
            currency="EUR",
            availability=Availability.AVAILABLE,
            calculation_version="test/1",
            methodology="test",
            provenance=("test",),
        )
    with pytest.raises(ValueError, match="cursor"):
        paginate((1, 2, 3), cursor="../../../private", limit=2)
