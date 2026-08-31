"""Deterministic local/test provider implementing the production ingestion port."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

from trading212_application.ingestion import (
    BrokerAccountDataProvider,
    Checkpoint,
    IngestionCapability,
    SourcePage,
    SourceRecord,
)


class SyntheticIngestionProvider(BrokerAccountDataProvider):
    """Provider-shaped local data that traverses the production normalizer."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        current_price: Decimal = Decimal("590.00"),
        include_position: bool = True,
        reported_total_offset: Decimal = Decimal("0"),
    ) -> None:
        if not current_price.is_finite() or current_price < 0:
            raise ValueError("synthetic current price must be a non-negative finite decimal")
        if not reported_total_offset.is_finite():
            raise ValueError("synthetic reported total offset must be finite")
        self._clock = clock or (lambda: datetime.now(UTC))
        self._current_price = current_price
        self._include_position = include_position
        self._reported_total_offset = reported_total_offset

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
        observed_at = self._clock().astimezone(UTC)
        records = tuple(
            SourceRecord(
                provider_record_id=provider_id,
                source_timestamp=source_timestamp,
                observed_at=observed_at,
                payload=payload,
                schema_version=f"synthetic-phase1:{capability.value}",
            )
            for provider_id, source_timestamp, payload in self._payloads(
                account_id=account_id,
                capability=capability,
                observed_at=observed_at,
            )
        )
        return SourcePage(records=records, next_checkpoint=None, complete=True)

    def _payloads(
        self,
        *,
        account_id: str,
        capability: IngestionCapability,
        observed_at: datetime,
    ) -> tuple[tuple[str, datetime, dict[str, object]], ...]:
        instrument = {
            "currency": "EUR",
            "isin": "XS0000000001",
            "name": "Synthetic Global Equity",
            "ticker": "SYNEQ",
        }
        added_on = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        invested = self._current_price * Decimal("400") if self._include_position else Decimal("0")
        acquisition_cost = Decimal("217568.73")
        provider_cost = acquisition_cost if self._include_position else Decimal("0")
        cash = Decimal("12431.27")
        if capability is IngestionCapability.INSTRUMENTS:
            return (
                (
                    "SYNTHETIC_EQ_1",
                    added_on,
                    {
                        "addedOn": added_on,
                        "currencyCode": "EUR",
                        "extendedHours": False,
                        "isin": "XS0000000001",
                        "maxOpenQuantity": Decimal("1000000"),
                        "name": "Synthetic Global Equity",
                        "shortName": "Synthetic Equity",
                        "ticker": "SYNEQ",
                        "type": "equity",
                        "workingScheduleId": 1,
                    },
                ),
            )
        if capability is IngestionCapability.EXCHANGES:
            return (
                (
                    "1",
                    observed_at,
                    {"id": 1, "name": "Synthetic Exchange", "workingSchedules": []},
                ),
            )
        if capability is IngestionCapability.ACCOUNT:
            return (
                (
                    "synthetic-account",
                    observed_at,
                    {
                        "id": account_id,
                        "currency": "EUR",
                        "cash": {
                            "availableToTrade": cash,
                            "inPies": Decimal("0"),
                            "reservedForOrders": Decimal("0"),
                        },
                        "investments": {
                            "currentValue": invested,
                            "realizedProfitLoss": Decimal("0"),
                            "totalCost": provider_cost,
                            "unrealizedProfitLoss": invested - provider_cost,
                        },
                        "totalValue": invested + cash + self._reported_total_offset,
                    },
                ),
            )
        if capability is IngestionCapability.POSITIONS:
            if not self._include_position:
                return ()
            return (
                (
                    "SYNTHETIC_EQ_1",
                    observed_at,
                    {
                        "averagePricePaid": acquisition_cost / Decimal("400"),
                        "createdAt": added_on,
                        "currentPrice": self._current_price,
                        "instrument": instrument,
                        "quantity": Decimal("400"),
                        "quantityAvailableForTrading": Decimal("400"),
                        "quantityInPies": Decimal("0"),
                        "walletImpact": {
                            "currency": "EUR",
                            "currentValue": invested,
                            "fxImpact": Decimal("0"),
                            "totalCost": acquisition_cost,
                            "unrealizedProfitLoss": invested - acquisition_cost,
                        },
                    },
                ),
            )
        order = {
            "createdAt": datetime(2026, 8, 28, 9, 0, tzinfo=UTC),
            "currency": "EUR",
            "extendedHours": False,
            "filledQuantity": Decimal("0"),
            "filledValue": Decimal("0"),
            "id": 9001,
            "initiatedFrom": "API",
            "instrument": instrument,
            "limitPrice": Decimal("550"),
            "quantity": Decimal("1"),
            "side": "BUY",
            "status": "NEW",
            "stopPrice": None,
            "strategy": "QUANTITY",
            "ticker": "SYNEQ",
            "timeInForce": "DAY",
            "type": "LIMIT",
            "value": Decimal("550"),
        }
        if capability is IngestionCapability.PENDING_ORDERS:
            return (("9001", observed_at, order),)
        if capability is IngestionCapability.HISTORICAL_ORDERS:
            historical_order = dict(order)
            historical_order["id"] = 9000
            historical_order["status"] = "FILLED"
            historical_order["filledQuantity"] = Decimal("1")
            historical_order["filledValue"] = Decimal("550")
            return (("9000", observed_at, {"fill": None, "order": historical_order}),)
        if capability is IngestionCapability.TRANSACTIONS:
            deposit_at = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
            buy_at = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)
            return (
                (
                    "synthetic-deposit-1",
                    deposit_at,
                    {
                        "amount": Decimal("230000"),
                        "currency": "EUR",
                        "dateTime": deposit_at,
                        "reference": "synthetic-deposit-1",
                        "type": "DEPOSIT",
                    },
                ),
                (
                    "synthetic-buy-1",
                    buy_at,
                    {
                        "amount": -acquisition_cost,
                        "currency": "EUR",
                        "dateTime": buy_at,
                        "reference": "synthetic-buy-1",
                        "type": "BUY",
                    },
                ),
            )
        if capability is IngestionCapability.DIVIDENDS:
            paid_on = date(2026, 6, 30)
            return (
                (
                    "synthetic-dividend-1",
                    datetime.combine(paid_on, datetime.min.time(), tzinfo=UTC),
                    {
                        "amount": Decimal("1738.20"),
                        "amountInEuro": Decimal("1738.20"),
                        "currency": "EUR",
                        "grossAmountPerShare": Decimal("4.3455"),
                        "instrument": instrument,
                        "paidOn": paid_on,
                        "quantity": Decimal("400"),
                        "reference": "synthetic-dividend-1",
                        "ticker": "SYNEQ",
                        "tickerCurrency": "EUR",
                        "type": "ORDINARY",
                    },
                ),
            )
        if capability is IngestionCapability.EXPORT_METADATA:
            return (
                (
                    "synthetic-export-1",
                    observed_at,
                    {
                        "dataIncluded": {"includeDividends": True, "includeTransactions": True},
                        "downloadLink": None,
                        "reportId": 1,
                        "status": "Finished",
                        "timeFrom": added_on,
                        "timeTo": observed_at,
                    },
                ),
            )
        raise ValueError(f"unsupported synthetic capability: {capability.value}")
