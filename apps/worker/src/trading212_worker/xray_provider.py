"""Minimized provider-shaped snapshot ingestion for the declared synthetic X-ray account."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading212_application.ingestion import (
    BrokerAccountDataProvider,
    Checkpoint,
    IngestionCapability,
    SourcePage,
    SourceRecord,
)
from trading212_domain import build_synthetic_identity

from .xray_fixture import XRAY_AT, XRAY_EFFECTIVE, XrayFixture, build_xray_fixture


class SyntheticXrayBrokerProvider(BrokerAccountDataProvider):
    def __init__(self) -> None:
        self.fixture = build_xray_fixture()

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        del correlation_id
        if (
            owner_id != str(build_synthetic_identity().owner.id)
            or account_id != str(self.fixture.account.id)
            or checkpoint is not None
        ):
            raise ValueError("Synthetic X-ray scope does not match its declared account.")
        return SourcePage(
            records=tuple(
                SourceRecord(
                    provider_record_id=key,
                    source_timestamp=at,
                    observed_at=XRAY_AT,
                    payload=payload,
                    schema_version=f"synthetic-xray-v1:{capability.value}",
                )
                for key, at, payload in _payloads(self.fixture, capability)
            ),
            next_checkpoint=None,
            complete=True,
        )


def _payloads(
    fixture: XrayFixture, capability: IngestionCapability
) -> tuple[tuple[str, datetime, dict[str, object]], ...]:
    if capability is IngestionCapability.INSTRUMENTS:
        return tuple(
            (
                row.listing.provider_instrument_id,
                XRAY_EFFECTIVE,
                {
                    "addedOn": XRAY_EFFECTIVE,
                    "currencyCode": str(row.listing.trading_currency),
                    "extendedHours": False,
                    "isin": row.instrument.isin,
                    "maxOpenQuantity": Decimal("1000000"),
                    "name": row.instrument.canonical_name,
                    "shortName": row.listing.ticker,
                    "ticker": row.listing.ticker,
                    "type": row.instrument.instrument_type,
                    "workingScheduleId": 75,
                },
            )
            for row in fixture.listings
        )
    if capability is IngestionCapability.EXCHANGES:
        return (
            ("75", XRAY_AT, {"id": 75, "name": "Synthetic X-ray exchange", "workingSchedules": []}),
        )
    if capability is IngestionCapability.ACCOUNT:
        return (
            (
                fixture.account.provider_account_id,
                XRAY_AT,
                {
                    "id": 2120501,
                    "currency": "EUR",
                    "cash": {
                        "availableToTrade": Decimal("0"),
                        "inPies": Decimal("0"),
                        "reservedForOrders": Decimal("0"),
                    },
                    "investments": {
                        "currentValue": Decimal("1000"),
                        "realizedProfitLoss": Decimal("0"),
                        "totalCost": Decimal("1000"),
                        "unrealizedProfitLoss": Decimal("0"),
                    },
                    "totalValue": Decimal("1000"),
                },
            ),
        )
    if capability is IngestionCapability.POSITIONS:
        rows = []
        for row in fixture.listings:
            if row.held_value is None:
                continue
            wallet: dict[str, object] = {
                "currency": str(row.listing.trading_currency),
                "currentValue": row.held_value,
                "totalCost": row.held_value,
                "unrealizedProfitLoss": Decimal("0"),
                "fxImpact": Decimal("0"),
            }
            if str(row.listing.trading_currency) == "USD":
                wallet["fxRate"] = {
                    "baseCurrency": "USD",
                    "quoteCurrency": "EUR",
                    "rate": Decimal("0.8"),
                    "observedAt": XRAY_AT,
                    "source": "synthetic-xray-fixing-v1",
                }
            rows.append(
                (
                    row.listing.provider_instrument_id,
                    XRAY_AT,
                    {
                        "averagePricePaid": row.held_value,
                        "createdAt": XRAY_EFFECTIVE,
                        "currentPrice": row.held_value,
                        "instrument": {
                            "currency": str(row.listing.trading_currency),
                            "isin": row.instrument.isin,
                            "name": row.instrument.canonical_name,
                            "ticker": row.listing.ticker,
                        },
                        "quantity": Decimal("1"),
                        "quantityAvailableForTrading": Decimal("1"),
                        "quantityInPies": Decimal("0"),
                        "walletImpact": wallet,
                    },
                )
            )
        return tuple(rows)
    if capability in (
        IngestionCapability.PENDING_ORDERS,
        IngestionCapability.HISTORICAL_ORDERS,
        IngestionCapability.TRANSACTIONS,
        IngestionCapability.DIVIDENDS,
        IngestionCapability.EXPORT_METADATA,
    ):
        return ()
    raise ValueError("Unknown synthetic X-ray ingestion capability.")
