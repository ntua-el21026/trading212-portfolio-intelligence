"""Read-only native custody adapter through the unchanged canonical ingestion port."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from trading212_application.ingestion import (
    BrokerAccountDataProvider,
    Checkpoint,
    IngestionCapability,
    SourcePage,
    SourceRecord,
)
from trading212_domain.values import require_utc

from .synthetic_custody_types import CustodyAccountSnapshot, CustodyAsset

_KIND = {
    "cash_in": "DEPOSIT",
    "cash_out": "WITHDRAWAL",
    "asset_purchase": "BUY",
    "asset_sale": "SELL",
    "custody_transfer": "TRANSFER",
    "custody_fee": "FEE",
    "unknown": "UNKNOWN",
}


def custody_record_key(kind: str, native: str) -> str:
    if kind not in ("asset", "position", "activity") or not native or len(native) > 96:
        raise ValueError("Invalid fixed custody record identity")
    return f"custody:{kind}:{native}"


def _asset(asset: CustodyAsset) -> dict[str, object]:
    return {
        "currency": str(asset.quote_currency),
        "isin": asset.isin,
        "name": asset.name,
        "ticker": asset.listing_code,
    }


class SyntheticCustodyIngestionProvider(BrokerAccountDataProvider):
    """Explicit synthetic fixture only; performs no HTTP or broker action."""

    def __init__(
        self, snapshot: CustodyAccountSnapshot, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        if type(snapshot) is not CustodyAccountSnapshot:
            raise ValueError("A complete native custody fixture is required")
        self._snapshot = snapshot
        self._clock = clock or (lambda: datetime.now(UTC))

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        del owner_id, correlation_id
        if UUID(account_id) != self._snapshot.account_id or not isinstance(
            capability, IngestionCapability
        ):
            raise ValueError("Custody fixture account/capability differs")
        if checkpoint is not None:
            raise ValueError("This bounded native fixture has no continuation")
        observed = require_utc(self._clock())
        if observed < self._snapshot.valuation_at:
            raise ValueError("Custody fixture is not yet observed")
        records = tuple(
            SourceRecord(
                provider_record_id=key,
                source_timestamp=at,
                observed_at=observed,
                payload=payload,
                schema_version=f"synthetic-custody-v1:{capability.value}",
            )
            for key, at, payload in self._rows(capability)
        )
        return SourcePage(records=records, next_checkpoint=None, complete=True)

    def _rows(
        self, capability: IngestionCapability
    ) -> tuple[tuple[str, datetime, dict[str, object]], ...]:
        s = self._snapshot
        if capability is IngestionCapability.INSTRUMENTS:
            return tuple(
                (
                    custody_record_key("asset", a.native_asset_key),
                    s.valuation_at,
                    {
                        "addedOn": s.valuation_at,
                        "currencyCode": str(a.quote_currency),
                        "extendedHours": False,
                        "isin": a.isin,
                        "maxOpenQuantity": Decimal("1000000"),
                        "name": a.name,
                        "shortName": a.name,
                        "ticker": a.listing_code,
                        "type": "equity",
                        "workingScheduleId": 73001,
                    },
                )
                for a in s.assets
            )
        if capability is IngestionCapability.EXCHANGES:
            return (
                (
                    "custody:exchange:73001",
                    s.valuation_at,
                    {"id": 73001, "name": "Synthetic Custody Venue", "workingSchedules": []},
                ),
            )
        if capability is IngestionCapability.ACCOUNT:
            return (
                (
                    "custody:account:" + str(s.account_id),
                    s.valuation_at,
                    {
                        "id": str(s.account_id),
                        "currency": str(s.currency),
                        "cash": {
                            "availableToTrade": s.cash_available,
                            "inPies": Decimal(0),
                            "reservedForOrders": Decimal(0),
                        },
                        "investments": {
                            "currentValue": s.investments_value,
                            "realizedProfitLoss": Decimal(0),
                            "totalCost": s.investments_cost,
                            "unrealizedProfitLoss": s.unrealized_pnl,
                        },
                        "totalValue": s.net_asset_value,
                    },
                ),
            )
        if capability is IngestionCapability.POSITIONS:
            # Native values remain native. Do not invent an account-currency wallet impact.
            return tuple(
                (
                    custody_record_key("position", p.asset.native_asset_key),
                    p.valuation_at,
                    {
                        "averagePricePaid": p.mean_acquisition_quote,
                        "createdAt": p.opened_at,
                        "currentPrice": p.last_quote,
                        "instrument": _asset(p.asset),
                        "quantity": p.units,
                        "quantityAvailableForTrading": p.units,
                        "quantityInPies": Decimal(0),
                        "walletImpact": {
                            "currency": str(p.asset.quote_currency),
                            "currentValue": p.native_market_value,
                            "fxImpact": Decimal(0),
                            "totalCost": p.native_cost_basis,
                            "unrealizedProfitLoss": p.native_unrealized_pnl,
                        },
                    },
                )
                for p in s.positions
            )
        if capability is IngestionCapability.TRANSACTIONS:
            rows: list[tuple[str, datetime, dict[str, object]]] = []
            for activity in s.activity:
                key = custody_record_key("activity", activity.native_record_key)
                payload: dict[str, object] = {
                    "reference": key,
                    "type": _KIND[activity.kind],
                    "amount": activity.signed_cash,
                    "currency": str(activity.currency),
                    "dateTime": activity.booked_at,
                }
                if activity.transfer is not None:
                    proof = activity.transfer
                    payload["custodyTransfer"] = {
                        "counterpartyAccountId": str(proof.counterparty_account_id),
                        "transferReference": proof.transfer_reference,
                        "principal": proof.principal,
                        "currency": str(proof.currency),
                        "fxRate": proof.fx_rate,
                        "fxBaseCurrency": None
                        if proof.fx_base_currency is None
                        else str(proof.fx_base_currency),
                        "fxQuoteCurrency": None
                        if proof.fx_quote_currency is None
                        else str(proof.fx_quote_currency),
                        "feeRecordKey": None
                        if proof.fee_native_record_key is None
                        else custody_record_key("activity", proof.fee_native_record_key),
                        "feeAmount": proof.fee_amount,
                        "feeCurrency": None
                        if proof.fee_currency is None
                        else str(proof.fee_currency),
                    }
                rows.append((key, activity.published_at, payload))
            return tuple(rows)
        if capability in (
            IngestionCapability.PENDING_ORDERS,
            IngestionCapability.HISTORICAL_ORDERS,
            IngestionCapability.DIVIDENDS,
            IngestionCapability.EXPORT_METADATA,
        ):
            # These explicit native fixture collections are empty; unsupported enums never fall
            # through.
            return ()
        raise ValueError("Unsupported fixed custody capability")
