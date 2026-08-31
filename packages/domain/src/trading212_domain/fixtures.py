"""Deterministic synthetic builders for tests, demos, and local development."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from .entities import BrokerAccount, BrokerConnection, Instrument, Listing, Owner, Principal
from .enums import BrokerEnvironment, PrincipalStatus, Provider, RecordStatus
from .identifiers import (
    BrokerAccountId,
    BrokerConnectionId,
    InstrumentId,
    ListingId,
    OwnerId,
    PrincipalId,
)
from .values import CurrencyCode, Instant

SYNTHETIC_TIME = Instant.parse("2026-01-15T12:00:00Z")


def fixture_uuid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"trading212-portfolio-intelligence/synthetic/{name}")


@dataclass(frozen=True, slots=True)
class SyntheticIdentityFixture:
    owner: Owner
    principal: Principal
    connection: BrokerConnection
    account: BrokerAccount
    instrument: Instrument
    listing: Listing


def build_synthetic_identity() -> SyntheticIdentityFixture:
    owner_id = OwnerId(fixture_uuid("owner"))
    principal_id = PrincipalId(fixture_uuid("principal"))
    connection_id = BrokerConnectionId(fixture_uuid("connection"))
    account_id = BrokerAccountId(fixture_uuid("account"))
    instrument_id = InstrumentId(fixture_uuid("instrument"))
    listing_id = ListingId(fixture_uuid("listing"))
    return SyntheticIdentityFixture(
        owner=Owner(owner_id, SYNTHETIC_TIME, "Synthetic Owner"),
        principal=Principal(
            principal_id,
            owner_id,
            "local.synthetic",
            "synthetic-owner",
            PrincipalStatus.ACTIVE,
            SYNTHETIC_TIME,
        ),
        connection=BrokerConnection(
            connection_id,
            owner_id,
            Provider.SYNTHETIC,
            BrokerEnvironment.SYNTHETIC,
            "synthetic://credential-reference/no-secret",
            RecordStatus.ACTIVE,
            SYNTHETIC_TIME,
            SYNTHETIC_TIME,
        ),
        account=BrokerAccount(
            account_id,
            connection_id,
            "synthetic-account",
            "invest",
            CurrencyCode("EUR"),
            "Synthetic EUR Portfolio",
            RecordStatus.ACTIVE,
            SYNTHETIC_TIME,
            SYNTHETIC_TIME,
        ),
        instrument=Instrument(instrument_id, "Synthetic Global Equity", "equity", "XS0000000001"),
        listing=Listing(
            listing_id,
            instrument_id,
            Provider.SYNTHETIC,
            BrokerEnvironment.SYNTHETIC,
            "SYNTHETIC_EQ_1",
            "SYNEQ",
            CurrencyCode("EUR"),
            RecordStatus.ACTIVE,
            SYNTHETIC_TIME,
            exchange_mic="XOFF",
        ),
    )
