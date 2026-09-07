"""Synthetic history replay through the same minimized broker ingestion contract."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, localcontext

from trading212_application.ingestion import (
    BrokerAccountDataProvider,
    Checkpoint,
    IngestionCapability,
    SourcePage,
    SourceRecord,
)

from .historical_fixture import (
    HISTORY_CONTEXT,
    SyntheticHistoryActivity,
    SyntheticHistoryInstrument,
    SyntheticHistoryScenario,
    close_at,
)


def instrument_reference(item: SyntheticHistoryInstrument) -> dict[str, object]:
    return {
        "currency": str(item.listing.trading_currency),
        "isin": item.instrument.isin,
        "name": item.instrument.canonical_name,
        "ticker": item.listing.ticker,
    }


class SyntheticHistoricalProvider(BrokerAccountDataProvider):
    def __init__(
        self,
        scenario: SyntheticHistoryScenario,
        *,
        economic_at: datetime,
        clock: Callable[[], datetime],
        include_equal: bool = True,
    ) -> None:
        if economic_at.tzinfo is None or not scenario.opening_at <= economic_at <= datetime.combine(
            scenario.end + timedelta(days=1), time.min, tzinfo=UTC
        ):
            raise ValueError("A covered UTC synthetic economic instant is required")
        self.scenario = scenario
        self.economic_at = economic_at
        self.clock = clock
        self.include_equal = include_equal

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        del owner_id, checkpoint, correlation_id
        if account_id != str(self.scenario.account.id):
            raise ValueError("Synthetic historical account differs from the replay scope")
        observed_at = self.clock()
        if observed_at.tzinfo is None or observed_at < self.economic_at:
            raise ValueError("Synthetic receipt cannot precede economic evidence")
        with localcontext(HISTORY_CONTEXT):
            payloads = self._payloads(capability)
        return SourcePage(
            records=tuple(
                SourceRecord(
                    provider_record_id=key,
                    source_timestamp=at,
                    observed_at=observed_at,
                    payload=payload,
                    schema_version=f"history-v1:{capability.value}",
                )
                for key, at, payload in payloads
            ),
            next_checkpoint=None,
            complete=True,
        )

    def _payloads(
        self, capability: IngestionCapability
    ) -> tuple[tuple[str, datetime, dict[str, object]], ...]:
        scenario = self.scenario
        at = self.economic_at
        # UTC accounting boundaries use the last completed daily close. Exact
        # boundary activity receipts do not invent a new midnight market price.
        valuation_day = at.date() if at.time() >= time(16) else at.date() - timedelta(days=1)
        state = scenario.state(at, include_equal=self.include_equal)
        quantities = dict(state.quantities)
        cash = dict(state.cash)
        costs = dict(state.acquisition_costs)
        fx = scenario.fx(valuation_day)
        if capability is IngestionCapability.INSTRUMENTS:
            return tuple(
                (
                    item.listing.provider_instrument_id,
                    scenario.opening_at,
                    {
                        "addedOn": scenario.opening_at,
                        "currencyCode": str(item.listing.trading_currency),
                        "extendedHours": False,
                        "isin": item.instrument.isin,
                        "maxOpenQuantity": Decimal("1000000"),
                        "name": item.instrument.canonical_name,
                        "shortName": item.listing.ticker,
                        "ticker": item.listing.ticker,
                        "type": "equity",
                        "workingScheduleId": 71,
                    },
                )
                for item in scenario.instruments
            )
        if capability is IngestionCapability.EXCHANGES:
            return (
                ("71", at, {"id": 71, "name": "Synthetic daily history", "workingSchedules": []}),
            )
        if capability is IngestionCapability.ACCOUNT:
            invested = sum(
                (
                    quantities[currency]
                    * scenario.price(currency, valuation_day)
                    * (fx if currency == "USD" else Decimal(1))
                    for currency in ("EUR", "USD")
                ),
                Decimal(0),
            )
            cash_reporting = cash["EUR"] + cash["USD"] * fx
            cost = costs["EUR"] + costs["USD"] * fx
            return (
                (
                    scenario.account.provider_account_id,
                    at,
                    {
                        "id": 2120401 if scenario.variant == "annual" else 2120402,
                        "currency": "EUR",
                        "cash": {
                            "availableToTrade": cash_reporting,
                            "inPies": Decimal(0),
                            "reservedForOrders": Decimal(0),
                        },
                        "investments": {
                            "currentValue": invested,
                            "realizedProfitLoss": sum(
                                (
                                    value * (fx if currency == "USD" else Decimal(1))
                                    for currency, value in state.realized_profit
                                ),
                                Decimal(0),
                            ),
                            "totalCost": cost,
                            "unrealizedProfitLoss": invested - cost,
                        },
                        "totalValue": invested + cash_reporting,
                    },
                ),
            )
        if capability is IngestionCapability.POSITIONS:
            positions = []
            for item in scenario.instruments:
                currency = str(item.listing.trading_currency)
                quantity = quantities[currency]
                price = scenario.price(currency, valuation_day)
                value = quantity * price
                wallet: dict[str, object] = {
                    "currency": currency,
                    "currentValue": value,
                    "totalCost": costs[currency],
                    "unrealizedProfitLoss": value - costs[currency],
                    "fxImpact": Decimal(0),
                }
                if currency == "USD":
                    # The synthetic provider explicitly supplies this quote; it
                    # is not calculated by dividing wallet monetary values.
                    wallet["fxRate"] = {
                        "baseCurrency": "USD",
                        "quoteCurrency": "EUR",
                        "rate": fx,
                        "observedAt": close_at(valuation_day),
                        "source": "synthetic-history-fixing-v1",
                    }
                positions.append(
                    (
                        item.listing.provider_instrument_id,
                        at,
                        {
                            "averagePricePaid": (costs[currency] / quantity).quantize(
                                Decimal("0.000000000000000001")
                            ),
                            "createdAt": scenario.opening_at,
                            "currentPrice": price,
                            "instrument": instrument_reference(item),
                            "quantity": quantity,
                            "quantityAvailableForTrading": quantity,
                            "quantityInPies": Decimal(0),
                            "walletImpact": wallet,
                        },
                    )
                )
            return tuple(positions)
        eligible = tuple(
            event
            for event in scenario.activities
            if event.at < at or (self.include_equal and event.at == at)
        )
        if capability is IngestionCapability.HISTORICAL_ORDERS:
            return tuple(
                self._execution(event) for event in eligible if event.kind in ("buy", "sell")
            )
        if capability is IngestionCapability.DIVIDENDS:
            return tuple(self._dividend(event) for event in eligible if event.kind == "dividend")
        if capability is IngestionCapability.TRANSACTIONS:
            return tuple(
                (
                    f"history-{scenario.variant}-{event.key}",
                    event.at,
                    {
                        "amount": event.amount,
                        "currency": event.currency,
                        "dateTime": event.at,
                        "reference": f"history-{scenario.variant}-{event.key}",
                        "type": event.kind.upper(),
                    },
                )
                for event in eligible
                if event.kind not in ("buy", "sell", "dividend")
            )
        if capability in (IngestionCapability.PENDING_ORDERS, IngestionCapability.EXPORT_METADATA):
            return ()
        raise ValueError("Unknown synthetic history capability")

    def _execution(
        self, event: SyntheticHistoryActivity
    ) -> tuple[str, datetime, dict[str, object]]:
        item = next(
            row
            for row in self.scenario.instruments
            if str(row.listing.trading_currency) == event.currency
        )
        if event.order_id is None or event.fill_id is None:
            raise ValueError("Synthetic execution requires actual order and fill identities")
        price = self.scenario.price(event.currency, event.at.date())
        gross = abs(event.amount)
        return (
            str(event.order_id),
            event.at,
            {
                "order": {
                    "id": event.order_id,
                    "createdAt": event.at,
                    "currency": event.currency,
                    "extendedHours": False,
                    "filledQuantity": event.quantity,
                    "filledValue": gross,
                    "initiatedFrom": "API",
                    "instrument": instrument_reference(item),
                    "limitPrice": None,
                    "quantity": event.quantity,
                    "side": event.kind.upper(),
                    "status": "FILLED",
                    "stopPrice": None,
                    "strategy": "QUANTITY",
                    "ticker": item.listing.ticker,
                    "timeInForce": "DAY",
                    "type": "MARKET",
                    "value": gross,
                },
                "fill": {
                    "id": event.fill_id,
                    "price": price,
                    "quantity": event.quantity,
                    "timestamp": event.at,
                    "tradingMethod": "EXCHANGE",
                    "type": "TRADE",
                    "walletImpact": {
                        "currency": event.currency,
                        "fxImpact": Decimal(0),
                        "netValue": event.amount,
                        "taxes": Decimal(0),
                    },
                },
            },
        )

    def _dividend(self, event: SyntheticHistoryActivity) -> tuple[str, datetime, dict[str, object]]:
        item = next(
            row
            for row in self.scenario.instruments
            if str(row.listing.trading_currency) == event.currency
        )
        if event.gross is None:
            raise ValueError("This synthetic provider fixture requires its stated gross evidence")
        key = f"history-{self.scenario.variant}-{event.key}"
        return (
            key,
            event.at,
            {
                "amount": event.amount,
                "currency": event.currency,
                "grossAmountPerShare": event.gross / event.quantity,
                "instrument": instrument_reference(item),
                "paidOn": event.at.date(),
                "quantity": event.quantity,
                "reference": key,
                "ticker": item.listing.ticker,
                "tickerCurrency": event.currency,
                "type": "DIVIDEND",
            },
        )
