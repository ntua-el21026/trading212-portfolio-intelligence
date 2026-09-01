from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from trading212_application.ingestion import CURRENT_REFRESH_ORDER, HISTORY_REFRESH_ORDER, RunMode
from trading212_application.queries import (
    ActivityQuery,
    ActivityTypeFilter,
    DirectAllocationQuery,
    DividendQuery,
    InstrumentQuery,
    PageQuery,
    PositionQuery,
)
from trading212_application.refresh_semantics import RefreshIdempotencyConflictError
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
    first = await service.list_positions(
        _principal(), service.ACCOUNT_ID, query=PositionQuery(limit=2)
    )
    second = await service.list_positions(
        _principal(), service.ACCOUNT_ID, query=PositionQuery(cursor=first.next_cursor, limit=100)
    )
    assert len(first.items) == 2
    assert len(second.items) == 3
    assert second.next_cursor is None
    allocation = await service.get_direct_allocation(
        _principal(),
        service.ACCOUNT_ID,
        query=DirectAllocationQuery(top_n=50),
    )
    assert sum(row.weight or Decimal(0) for row in allocation.items) == Decimal("1.000000000000")
    assert allocation.total == len(allocation.items)
    assert allocation.truncated is False


@pytest.mark.asyncio
async def test_accounts_and_order_observations_are_authorized_typed_reads() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    accounts = await service.list_accounts(_principal())
    orders = await service.list_orders(_principal(), service.ACCOUNT_ID, query=PageQuery(limit=20))
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
            query=ActivityQuery(limit=20),
        )
    with pytest.raises(AuthorizationError, match="access denied"):
        await service.get_summary(_principal(owner_id="other-owner"), service.ACCOUNT_ID)
    with pytest.raises(AuthorizationError, match="access denied"):
        await service.get_summary(_principal(), "unknown-account")


@pytest.mark.asyncio
async def test_activity_filter_maps_public_tax_and_unknown_to_canonical_types() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    base = service._activity[0]
    service._activity = (
        replace(base, id="activity-tax", activity_type="tax_withholding"),
        replace(
            base,
            id="activity-unknown",
            activity_type="unknown_provider_activity",
        ),
        replace(base, id="activity-adjustment", activity_type="adjustment"),
        replace(base, id="activity-transfer", activity_type="transfer"),
    )

    tax = await service.list_activity(
        _principal(),
        service.ACCOUNT_ID,
        query=ActivityQuery(activity_type=ActivityTypeFilter.TAX),
    )
    unknown = await service.list_activity(
        _principal(),
        service.ACCOUNT_ID,
        query=ActivityQuery(activity_type=ActivityTypeFilter.UNKNOWN),
    )
    fx = await service.list_activity(
        _principal(),
        service.ACCOUNT_ID,
        query=ActivityQuery(activity_type=ActivityTypeFilter.FX_CONVERSION),
    )

    assert [item.id for item in tax.items] == ["activity-tax"]
    assert [item.id for item in unknown.items] == ["activity-unknown"]
    assert fx.items == ()
    assert fx.total == 0


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
        mode=RunMode.INCREMENTAL,
        capabilities=HISTORY_REFRESH_ORDER,
        idempotency_key="manual-refresh-1",
        correlation_id="different-correlation",
    )
    assert first == second
    assert first.status == "succeeded"
    assert first.capabilities == tuple(capability.value for capability in HISTORY_REFRESH_ORDER)
    with pytest.raises(RefreshIdempotencyConflictError):
        await service.refresh(
            principal,
            service.ACCOUNT_ID,
            mode=RunMode.FULL,
            capabilities=HISTORY_REFRESH_ORDER,
            idempotency_key="manual-refresh-1",
            correlation_id="correlation-3",
        )
    with pytest.raises(RefreshIdempotencyConflictError):
        await service.refresh(
            principal,
            service.ACCOUNT_ID,
            mode=RunMode.INCREMENTAL,
            capabilities=CURRENT_REFRESH_ORDER,
            idempotency_key="manual-refresh-1",
            correlation_id="correlation-4",
        )


@pytest.mark.asyncio
async def test_refresh_concurrently_coalesces_and_preserves_requested_promotion_identity() -> None:
    service = SyntheticPortfolioService(
        clock=lambda: NOW,
        refresh_initial_sync_required=True,
    )
    principal = _principal()

    runs = await asyncio.gather(
        *(
            service.refresh(
                principal,
                service.ACCOUNT_ID,
                mode=RunMode.INCREMENTAL,
                capabilities=HISTORY_REFRESH_ORDER,
                idempotency_key="concurrent-promoted-refresh",
                correlation_id=f"correlation-{index}",
            )
            for index in range(50)
        )
    )

    assert len({run.id for run in runs}) == 1
    assert all(run == runs[0] for run in runs)
    assert "initial synchronization promoted" in " ".join(runs[0].warnings)
    assert len(service._refresh_runs) == 1
    with pytest.raises(RefreshIdempotencyConflictError):
        await service.refresh(
            principal,
            service.ACCOUNT_ID,
            mode=RunMode.FULL,
            capabilities=HISTORY_REFRESH_ORDER,
            idempotency_key="concurrent-promoted-refresh",
            correlation_id="different-requested-semantics",
        )
    with pytest.raises(ValueError, match="idempotency"):
        await service.refresh(
            principal,
            service.ACCOUNT_ID,
            mode=RunMode.INCREMENTAL,
            capabilities=HISTORY_REFRESH_ORDER,
            idempotency_key="x" * 181,
            correlation_id="oversized-key",
        )


@pytest.mark.asyncio
async def test_concurrent_mismatched_synthetic_refreshes_return_one_conflict() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    principal = _principal()

    results = await asyncio.gather(
        service.refresh(
            principal,
            service.ACCOUNT_ID,
            mode=RunMode.INCREMENTAL,
            capabilities=HISTORY_REFRESH_ORDER,
            idempotency_key="concurrent-mismatched-refresh",
            correlation_id="incremental-request",
        ),
        service.refresh(
            principal,
            service.ACCOUNT_ID,
            mode=RunMode.FULL,
            capabilities=HISTORY_REFRESH_ORDER,
            idempotency_key="concurrent-mismatched-refresh",
            correlation_id="full-request",
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(item, RefreshIdempotencyConflictError) for item in results) == 1
    assert sum(not isinstance(item, BaseException) for item in results) == 1
    assert len(service._refresh_runs) == 1


@pytest.mark.asyncio
async def test_invalid_metric_and_pagination_contracts_fail_closed() -> None:
    from trading212_application.views import MetricView

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
        await SyntheticPortfolioService(clock=lambda: NOW).list_positions(
            _principal(),
            SyntheticPortfolioService.ACCOUNT_ID,
            query=PositionQuery(cursor="../../../private", limit=2),
        )


@pytest.mark.asyncio
async def test_synthetic_mutable_collections_keep_immutable_membership_after_page_one() -> None:
    service = SyntheticPortfolioService(clock=lambda: NOW)
    principal = _principal()

    activity_ids = {item.id for item in service._activity}
    first_activity = await service.list_activity(
        principal,
        service.ACCOUNT_ID,
        query=ActivityQuery(limit=1),
    )
    assert first_activity.next_cursor is not None
    service._activity = tuple(
        replace(
            item,
            occurred_at=(
                datetime(2026, 1, 1, tzinfo=UTC)
                if item.id == first_activity.items[0].id
                else datetime(2026, 12, 1, tzinfo=UTC)
            ),
        )
        if item.id in {first_activity.items[0].id, service._activity[1].id}
        else item
        for item in service._activity
    )
    seen_activity = {item.id for item in first_activity.items}
    cursor: str | None = first_activity.next_cursor
    while cursor is not None:
        activity_page = await service.list_activity(
            principal,
            service.ACCOUNT_ID,
            query=ActivityQuery(cursor=cursor, limit=1),
        )
        assert seen_activity.isdisjoint(item.id for item in activity_page.items)
        seen_activity.update(item.id for item in activity_page.items)
        cursor = activity_page.next_cursor
    assert seen_activity == activity_ids
    with pytest.raises(ValueError, match="cursor"):
        await service.list_activity(
            principal,
            service.ACCOUNT_ID,
            query=ActivityQuery(
                cursor=first_activity.next_cursor,
                limit=1,
                activity_type=ActivityTypeFilter.DEPOSIT,
            ),
        )

    base_dividend = service._dividends[0]
    service._dividends = (
        base_dividend,
        replace(base_dividend, id="dividend-synthetic-2", paid_on=date(2026, 8, 20)),
        replace(base_dividend, id="dividend-synthetic-3", paid_on=date(2026, 8, 10)),
        replace(base_dividend, id="dividend-synthetic-4", paid_on=date(2026, 8, 1)),
    )
    dividend_ids = {item.id for item in service._dividends}
    first_dividends = await service.list_dividends(
        principal,
        service.ACCOUNT_ID,
        query=DividendQuery(limit=2),
    )
    assert first_dividends.next_cursor is not None
    service._dividends = tuple(
        replace(item, paid_on=date(2025, 1, 1)) if item.id == first_dividends.items[0].id else item
        for item in service._dividends
    )
    second_dividends = await service.list_dividends(
        principal,
        service.ACCOUNT_ID,
        query=DividendQuery(cursor=first_dividends.next_cursor, limit=100),
    )
    assert {
        *(item.id for item in first_dividends.items),
        *(item.id for item in second_dividends.items),
    } == dividend_ids

    listing_ids = {item.listing_id for item in service._instruments}
    first_instruments = await service.search_instruments(
        principal,
        query=InstrumentQuery(limit=2),
    )
    assert first_instruments.next_cursor is not None
    service._instruments = tuple(
        replace(item, ticker="ZZZZ", canonical_name="Renamed after page one")
        if item.listing_id == first_instruments.items[0].listing_id
        else item
        for item in service._instruments
    )
    seen_listings = {item.listing_id for item in first_instruments.items}
    cursor = first_instruments.next_cursor
    while cursor is not None:
        instrument_page = await service.search_instruments(
            principal,
            query=InstrumentQuery(cursor=cursor, limit=2),
        )
        assert seen_listings.isdisjoint(item.listing_id for item in instrument_page.items)
        seen_listings.update(item.listing_id for item in instrument_page.items)
        cursor = instrument_page.next_cursor
    assert seen_listings == listing_ids
