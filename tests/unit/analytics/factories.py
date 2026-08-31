"""Deterministic analytics test factories."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from trading212_domain import (
    BrokerAccountId,
    Instant,
    ListingId,
    Money,
    ProvenanceReference,
    Quantity,
    SourceRecordId,
    Transaction,
    TransactionId,
    TransactionStatus,
    TransactionType,
    ValueOrigin,
)

ACCOUNT_ID = BrokerAccountId(UUID(int=1))
OTHER_ACCOUNT_ID = BrokerAccountId(UUID(int=2))
LISTING_ID = ListingId(UUID(int=101))
SECOND_LISTING_ID = ListingId(UUID(int=102))
START = Instant.parse("2026-01-01T00:00:00Z")
MID = Instant.parse("2026-07-02T12:00:00Z")
END = Instant.parse("2027-01-01T00:00:00Z")


def transaction(
    sequence: int,
    provider_id: str,
    transaction_type: TransactionType,
    amount: str,
    *,
    status: TransactionStatus = TransactionStatus.POSTED,
    account_id: BrokerAccountId = ACCOUNT_ID,
    occurred_at: Instant = START,
    listing_id: ListingId | None = None,
    quantity: str | None = None,
) -> Transaction:
    return Transaction(
        id=TransactionId(UUID(int=1000 + sequence)),
        broker_account_id=account_id,
        provider_transaction_id=provider_id,
        transaction_type=transaction_type,
        status=status,
        net_cash_amount=Money(Decimal(amount), Money.parse(0, "EUR").currency),
        occurred_at=occurred_at,
        provenance=ProvenanceReference(
            (SourceRecordId(UUID(int=2000 + sequence)),),
            "analytics-fixture-v1",
            ValueOrigin.NORMALIZED_PROVIDER,
        ),
        instrument_listing_id=listing_id,
        quantity=Quantity.parse(quantity) if quantity is not None else None,
    )
