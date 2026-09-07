"""Independent synthetic-history conservation, provider shapes and knowledge clocks."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal, localcontext

import pytest
from trading212_application.ingestion import IngestionCapability
from trading212_provider.models import (
    AccountSummaryDTO,
    DividendDTO,
    HistoricalOrderDTO,
    PositionDTO,
    TransactionDTO,
)
from trading212_worker.historical_fixture import HISTORY_RECEIPT, build_history_scenario, close_at
from trading212_worker.historical_provider import SyntheticHistoricalProvider
from trading212_worker.historical_seed import seed_historical_scenarios


def test_annual_fixture_conserves_native_cash_quantity_and_weighted_acquisition_cost() -> None:
    scenario = build_history_scenario("annual")
    expected = scenario.state(close_at(scenario.end))
    assert dict(expected.quantities) == {"EUR": Decimal("11"), "USD": Decimal("5")}
    assert dict(expected.cash) == {"EUR": Decimal("532.94"), "USD": Decimal("5")}
    assert dict(expected.acquisition_costs) == {
        "EUR": Decimal("1128.013333333333333333"),
        "USD": Decimal("200"),
    }
    assert dict(expected.realized_profit) == {
        "EUR": Decimal("13.453333333333333333"),
        "USD": Decimal("0"),
    }
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_UP
        assert scenario.state(close_at(scenario.end)) == expected
    assert len(scenario.sessions) == 732
    assert scenario.price("EUR", scenario.end) == Decimal("129.24")
    assert scenario.price("USD", scenario.end) == Decimal("50.965")
    assert scenario.fx(scenario.end) == Decimal("0.911")


def test_timely_fixture_is_separate_with_complete_declared_zero_activity() -> None:
    annual, timely = build_history_scenario("annual"), build_history_scenario("point_in_time")
    assert timely.account.id != annual.account.id
    assert timely.activities == ()
    assert len(timely.sessions) == 22
    assert timely.state(timely.opening_at) == timely.state(close_at(timely.end))
    assert {row.listing.id for row in timely.instruments}.isdisjoint(
        row.listing.id for row in annual.instruments
    )


@pytest.mark.parametrize(
    "capability, model, count",
    [
        (IngestionCapability.ACCOUNT, AccountSummaryDTO, 1),
        (IngestionCapability.POSITIONS, PositionDTO, 2),
        (IngestionCapability.HISTORICAL_ORDERS, HistoricalOrderDTO, 2),
        (IngestionCapability.TRANSACTIONS, TransactionDTO, 4),
        (IngestionCapability.DIVIDENDS, DividendDTO, 4),
    ],
)
def test_history_replay_passes_real_broker_read_dtos(
    capability: IngestionCapability,
    model: type[
        AccountSummaryDTO | PositionDTO | HistoricalOrderDTO | TransactionDTO | DividendDTO
    ],
    count: int,
) -> None:
    scenario = build_history_scenario("annual")
    provider = SyntheticHistoricalProvider(
        scenario, economic_at=close_at(scenario.end), clock=lambda: HISTORY_RECEIPT
    )
    page = asyncio.run(
        provider.read_page(
            owner_id="synthetic-owner",
            account_id=str(scenario.account.id),
            capability=capability,
            checkpoint=None,
            correlation_id="history-test",
        )
    )
    assert page.complete and page.next_checkpoint is None
    assert len(page.records) == count
    for row in page.records:
        model.model_validate(row.payload)
        assert row.observed_at == HISTORY_RECEIPT
        assert row.source_timestamp is not None and row.source_timestamp < row.observed_at


def test_midnight_observation_uses_completed_close_and_actual_receipt() -> None:
    scenario = build_history_scenario("point_in_time")
    boundary = datetime(2026, 8, 2, tzinfo=UTC)
    provider = SyntheticHistoricalProvider(scenario, economic_at=boundary, clock=lambda: boundary)
    page = asyncio.run(
        provider.read_page(
            owner_id="synthetic-owner",
            account_id=str(scenario.account.id),
            capability=IngestionCapability.POSITIONS,
            checkpoint=None,
            correlation_id="history-test",
        )
    )
    values = [PositionDTO.model_validate(row.payload) for row in page.records]
    assert {value.current_price for value in values} == {Decimal("100"), Decimal("40")}
    assert all(row.source_timestamp == boundary == row.observed_at for row in page.records)
    assert scenario.fx(date(2026, 8, 1)) == Decimal("0.9")


def test_replay_rejects_foreign_scope_future_receipt_and_outside_history() -> None:
    scenario = build_history_scenario("annual")
    provider = SyntheticHistoricalProvider(
        scenario,
        economic_at=scenario.opening_at,
        clock=lambda: scenario.opening_at - timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="scope"):
        asyncio.run(
            provider.read_page(
                owner_id="owner",
                account_id="another-account",
                capability=IngestionCapability.ACCOUNT,
                checkpoint=None,
                correlation_id="test",
            )
        )
    with pytest.raises(ValueError, match="receipt"):
        asyncio.run(
            provider.read_page(
                owner_id="owner",
                account_id=str(scenario.account.id),
                capability=IngestionCapability.ACCOUNT,
                checkpoint=None,
                correlation_id="test",
            )
        )
    with pytest.raises(ValueError, match="covered UTC"):
        SyntheticHistoricalProvider(
            scenario, economic_at=datetime(2026, 1, 2, tzinfo=UTC), clock=lambda: HISTORY_RECEIPT
        )


def test_historical_seed_rejects_production_before_any_persistence() -> None:
    class ForbiddenSessions:
        def __call__(self) -> None:
            raise AssertionError("must not access persistence")

    with pytest.raises(RuntimeError, match="local/test"):
        asyncio.run(seed_historical_scenarios(ForbiddenSessions(), app_environment="production"))  # type: ignore[arg-type]
