"""Retained exact-tag decoding and economic identity regressions without active projections."""

from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal, localcontext
from uuid import uuid4

import pytest
from trading212_domain import historical as d
from trading212_persistence.historical_normalization import normalize_record, number
from trading212_persistence.models import SourceRecordModel
from trading212_persistence.source_models import MarketDataInstrumentModel

AT = datetime(2025, 1, 15, 16, tzinfo=UTC)
KNOWN = datetime(2026, 8, 31, 12, tzinfo=UTC)


def execution(
    *,
    fill_id: int = 101,
    side: str = "BUY",
    net: str = "21",
    taxes: str | None = "0",
    wallet_currency: str = "EUR",
) -> d.HistoricalExecution:
    listing, instrument = uuid4(), uuid4()
    mapping = MarketDataInstrumentModel(
        id=uuid4(),
        provider_key="SYNTHETIC",
        instrument_id=instrument,
        listing_id=listing,
        state="resolved",
        created_at=KNOWN,
        valid_from=AT,
    )
    record = SourceRecordModel(
        id=uuid4(),
        capability="historical_orders",
        provider_record_id="same-order",
        source_updated_at=KNOWN,
        observed_at=KNOWN,
        sanitized_payload={
            "order": {
                "id": 7,
                "ticker": "SYNTHETIC",
                "side": side,
                "instrument": {"currency": "EUR"},
            },
            "fill": {
                "id": fill_id,
                "quantity": {"$decimal": "2"},
                "price": {"$decimal": "10"},
                "timestamp": {"$datetime": AT.isoformat()},
                "walletImpact": {
                    "netValue": {"$decimal": net},
                    "currency": wallet_currency,
                    "taxes": None if taxes is None else {"$decimal": taxes},
                },
            },
        },
    )
    result = normalize_record(record, None, (mapping,))
    assert isinstance(result, d.HistoricalExecution)
    return result


@pytest.mark.parametrize("bad", [True, 1.25, {"$decimal": "1", "extra": 1}, {"$decimal": 1.25}])
def test_authoritative_decimal_tags_reject_float_boolean_and_additive_shape(bad: object) -> None:
    assert number(bad) is None


def test_fill_identity_uses_order_and_fill_with_exact_economic_and_knowledge_times() -> None:
    first, second, replay = execution(fill_id=101), execution(fill_id=102), execution(fill_id=101)
    assert first.identity.economic_key != second.identity.economic_key
    assert first.identity.economic_key == replay.identity.economic_key
    assert first.identity.economic_at == AT
    assert first.identity.first_observed_at == KNOWN
    assert first.identity.revision_id != replay.identity.revision_id
    assert first.quantity == Decimal(2) and first.native_price.amount == Decimal(10)


@pytest.mark.parametrize(
    ("side", "net", "tax", "expected"),
    [("BUY", "21.5", "0.5", "1"), ("SELL", "18.5", "0.5", "1"), ("BUY", "20", "0", "0")],
)
def test_same_currency_fees_derive_only_from_complete_exact_cash_reconciliation(
    side: str, net: str, tax: str, expected: str
) -> None:
    with localcontext() as hostile:
        hostile.prec = 2
        hostile.rounding = ROUND_DOWN
        value = execution(side=side, net=net, taxes=tax)
        assert hostile.prec == 2 and hostile.rounding == ROUND_DOWN
    assert value.fees.value is not None and value.fees.value.amount == Decimal(expected)
    assert value.fees.origin is d.HistoricalOrigin.DERIVED


@pytest.mark.parametrize(
    ("tax", "currency", "net"), [(None, "EUR", "21"), ("0", "USD", "21"), ("0", "EUR", "19")]
)
def test_missing_tax_cross_currency_or_negative_residual_does_not_invent_fee(
    tax: str | None, currency: str, net: str
) -> None:
    value = execution(taxes=tax, wallet_currency=currency, net=net)
    assert value.fees.value is None
    assert value.fees.reason_code is d.HistoricalReason.FEE_UNKNOWN
