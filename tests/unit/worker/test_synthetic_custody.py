"""Native fixture adapter is separate from the sealed Trading212 transport."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from trading212_application.ingestion import FULL_REFRESH_ORDER, IngestionCapability
from trading212_domain.values import CurrencyCode
from trading212_worker.synthetic_custody import SyntheticCustodyIngestionProvider
from trading212_worker.synthetic_custody_types import (
    CustodyAccountSnapshot,
    CustodyActivity,
    CustodyAsset,
    CustodyPosition,
)

AT = datetime(2026, 9, 15, 10, tzinfo=UTC)


def custody_fixture(account: UUID, at: datetime = AT) -> CustodyAccountSnapshot:
    asset = CustodyAsset(
        native_asset_key="native-share-001",
        isin="XS0000000001",
        listing_code="CUSTODY_EQ",
        name="Synthetic Custody Equity",
        quote_currency=CurrencyCode("EUR"),
    )
    opened = datetime(2026, 1, 15, 12, tzinfo=UTC)
    return CustodyAccountSnapshot(
        account_id=account,
        currency=CurrencyCode("EUR"),
        valuation_at=at,
        cash_available=Decimal("12431.27"),
        investments_value=Decimal("236000"),
        investments_cost=Decimal("217568.73"),
        unrealized_pnl=Decimal("18431.27"),
        net_asset_value=Decimal("248431.27"),
        assets=(asset,),
        positions=(
            CustodyPosition(
                asset=asset,
                opened_at=opened,
                units=Decimal("400"),
                last_quote=Decimal("590"),
                mean_acquisition_quote=Decimal("543.921825"),
                native_market_value=Decimal("236000"),
                native_cost_basis=Decimal("217568.73"),
                native_unrealized_pnl=Decimal("18431.27"),
                valuation_at=at,
            ),
        ),
        activity=(
            CustodyActivity(
                native_record_key="deposit-1",
                kind="cash_in",
                booked_at=opened,
                published_at=opened,
                signed_cash=Decimal("230000"),
                currency=CurrencyCode("EUR"),
            ),
            CustodyActivity(
                native_record_key="purchase-1",
                kind="asset_purchase",
                booked_at=opened,
                published_at=opened,
                signed_cash=Decimal("-217568.73"),
                currency=CurrencyCode("EUR"),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_native_adapter_namespaces_every_record_and_maps_exact_original_values() -> None:
    account = UUID(int=200)
    provider = SyntheticCustodyIngestionProvider(custody_fixture(account), clock=lambda: AT)
    for capability in FULL_REFRESH_ORDER:
        page = await provider.read_page(
            owner_id="owner",
            account_id=str(account),
            capability=capability,
            checkpoint=None,
            correlation_id="native-fixture",
        )
        assert page.complete and page.next_checkpoint is None
        assert all(
            x.provider_record_id is not None and x.provider_record_id.startswith("custody:")
            for x in page.records
        )
        assert all(
            x.schema_version == "synthetic-custody-v1:" + capability.value for x in page.records
        )
        if capability is IngestionCapability.POSITIONS:
            assert page.records[0].payload["quantity"] == Decimal("400")
            assert page.records[0].payload["currentPrice"] == Decimal("590")
    with pytest.raises(ValueError):
        await provider.read_page(
            owner_id="owner",
            account_id=str(UUID(int=201)),
            capability=IngestionCapability.ACCOUNT,
            checkpoint=None,
            correlation_id="wrong-account",
        )


def test_original_ten_gets_are_still_exactly_sealed() -> None:
    document = yaml.safe_load(Path("config/contracts/trading212-read-allowlist.yaml").read_text())
    assert [(x["capability"], x["method"], x["path"]) for x in document["capabilities"]] == [
        ("account_summary", "GET", "/equity/account/summary"),
        ("metadata_instruments", "GET", "/equity/metadata/instruments"),
        ("metadata_exchanges", "GET", "/equity/metadata/exchanges"),
        ("portfolio_positions", "GET", "/equity/positions"),
        ("pending_orders", "GET", "/equity/orders"),
        ("order_detail", "GET", "/equity/orders/{order_id}"),
        ("historical_orders", "GET", "/equity/history/orders"),
        ("historical_transactions", "GET", "/equity/history/transactions"),
        ("historical_dividends", "GET", "/equity/history/dividends"),
        ("historical_exports", "GET", "/equity/history/exports"),
    ]
