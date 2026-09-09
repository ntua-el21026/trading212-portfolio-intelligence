"""Declared synthetic X-ray identity and portfolio; no live broker or market data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from trading212_domain import build_synthetic_identity
from trading212_domain import xray as d
from trading212_domain.entities import BrokerAccount, Instrument, Listing
from trading212_domain.enums import BrokerEnvironment, Provider, RecordStatus
from trading212_domain.fixtures import fixture_uuid
from trading212_domain.identifiers import BrokerAccountId, InstrumentId, ListingId
from trading212_domain.values import CurrencyCode, Instant

XRAY_AT = datetime(2026, 8, 31, 12, tzinfo=UTC)
XRAY_EFFECTIVE = datetime(2026, 8, 1, 12, tzinfo=UTC)
XRAY_CURRENT_SOURCE = datetime(2026, 8, 30, 12, tzinfo=UTC)


def xray_id(key: str) -> str:
    return str(fixture_uuid(f"synthetic-xray-v1/{key}"))


XRAY_PROVIDER_ID = xray_id("provider")
XRAY_LICENSE_ID = xray_id("license")
XRAY_ACCOUNT_ID = xray_id("account")


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayFixtureListing:
    key: str
    instrument: Instrument
    listing: Listing
    held_value: Decimal | None


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayFixture:
    account: BrokerAccount
    listings: tuple[XrayFixtureListing, ...]


def build_xray_fixture() -> XrayFixture:
    identity = build_synthetic_identity()
    at = Instant(XRAY_EFFECTIVE)
    account = BrokerAccount(
        id=BrokerAccountId(UUID(XRAY_ACCOUNT_ID)),
        connection_id=identity.connection.id,
        provider_account_id="synthetic-xray-v1",
        account_type="invest",
        base_currency=CurrencyCode("EUR"),
        display_name="Synthetic X-ray Portfolio",
        status=RecordStatus.ACTIVE,
        first_seen_at=at,
        last_seen_at=Instant(XRAY_AT),
    )
    # Four actual held roots consolidate to Alpha: two ordinary listings, a
    # separate share class and a receipt. Its USD62.50 wallet has sourced EUR0.8 FX.
    declarations = (
        (
            "alpha-primary",
            "alpha-a",
            "Synthetic Alpha Ordinary",
            "EUR",
            "50",
            "equity",
            "XS0000000501",
        ),
        (
            "alpha-secondary",
            "alpha-a",
            "Synthetic Alpha Ordinary",
            "EUR",
            "50",
            "equity",
            "XS0000000501",
        ),
        (
            "alpha-class-b",
            "alpha-b",
            "Synthetic Alpha Class B",
            "EUR",
            "50",
            "equity",
            "XS0000000502",
        ),
        ("alpha-adr", "alpha-adr", "Synthetic Alpha ADR", "USD", "62.50", "equity", "XS0000000503"),
        ("beta", "beta", "Synthetic Beta", "EUR", None, "equity", "XS0000000504"),
        ("fund-a", "fund-a", "Synthetic Atlas Fund", "EUR", "500", "etf", "XS0000000505"),
        ("fund-b", "fund-b", "Synthetic Horizon Fund", "EUR", "300", "etf", "XS0000000506"),
    )
    listings = []
    for key, instrument_key, name, currency, value, kind, isin in declarations:
        instrument = Instrument(
            InstrumentId(UUID(xray_id(f"instrument/{instrument_key}"))), name, kind, isin
        )
        listing = Listing(
            id=ListingId(UUID(xray_id(f"listing/{key}"))),
            instrument_id=instrument.id,
            provider=Provider.SYNTHETIC,
            environment=BrokerEnvironment.SYNTHETIC,
            provider_instrument_id=f"XRAY_{key.upper().replace('-', '_')}",
            ticker=f"XRAY_{key.upper().replace('-', '_')}",
            trading_currency=CurrencyCode(currency),
            status=RecordStatus.ACTIVE,
            valid_from=at,
            exchange_mic="XOFF",
        )
        listings.append(
            XrayFixtureListing(
                key=key,
                instrument=instrument,
                listing=listing,
                held_value=Decimal(value) if value is not None else None,
            )
        )
    return XrayFixture(account=account, listings=tuple(listings))


def synthetic_xray_policy() -> d.XrayPolicyVersion:
    def uid(key: str) -> UUID:
        return UUID(xray_id(f"policy/{key}"))

    return d.XrayPolicyVersion(
        id=uid("calculation"),
        version="synthetic-xray-policy-v1",
        provider_selection_policy=d.XrayProviderSelectionPolicy(
            uid("provider"), "1", (XRAY_PROVIDER_ID,)
        ),
        identity_policy=d.XrayIdentityPolicy(uid("identity"), "1"),
        classification_policy=d.XrayClassificationPolicy(uid("classification"), "1"),
        taxonomy_versions=tuple(
            d.XrayTaxonomyVersion(
                dimension=dimension,
                taxonomy_id=UUID(xray_id(f"taxonomy/{dimension.value}")),
                key=f"synthetic-xray-{dimension.value}",
                version="1",
            )
            for dimension in d.XrayDimension
            if dimension is not d.XrayDimension.COMPANY
        ),
        freshness_policy=d.XrayFreshnessPolicy(uid("freshness"), "1", 7 * 86400, "valuation_at"),
        quality_policy=d.XrayQualityPolicy(uid("quality"), "1"),
        traversal_policy=d.XrayTraversalPolicy(uid("traversal"), "1"),
        thresholds=d.XrayUnconfiguredThresholds(),
        limits=d.XrayLimits(),
    )
