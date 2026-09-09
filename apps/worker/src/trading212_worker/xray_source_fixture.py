"""Explicit licensed entity/constituent/classification fixture declarations."""

from __future__ import annotations

from decimal import Decimal

from trading212_application.xray_ingestion import (
    EconomicEntityRegistration,
    EntityEvidenceRegistration,
    EntityMappingRegistration,
    EntityRelationshipRegistration,
    ShareClassRegistration,
)
from trading212_domain.source_details import (
    ClassificationDimension,
    ClassificationObservation,
    ConstituentHolding,
    ConstituentState,
)
from trading212_domain.sources import LicensePermission, SourceLicense
from trading212_domain.values import CurrencyCode
from trading212_reference_data.xray_replay import XrayReplayFund, XrayReplayProvider

from .xray_fixture import (
    XRAY_AT,
    XRAY_CURRENT_SOURCE,
    XRAY_EFFECTIVE,
    XRAY_LICENSE_ID,
    XRAY_PROVIDER_ID,
    build_xray_fixture,
    xray_id,
)


def xray_license() -> SourceLicense:
    return SourceLicense(
        id=XRAY_LICENSE_ID,
        provider_id=XRAY_PROVIDER_ID,
        version="synthetic-xray-license-1",
        effective_at=XRAY_EFFECTIVE,
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.ALLOWED,
        export=LicensePermission.ALLOWED,
        retention_days=365,
        attribution="Synthetic X-ray fixture only. No live fund holdings or market data.",
        evidence_key="synthetic-xray-license-v1",
    )


def xray_entities() -> EntityEvidenceRegistration:
    fixture = build_xray_fixture()
    mappings = []
    relationships = []
    for row in fixture.listings:
        if row.key.startswith("fund-"):
            continue
        entity = xray_id("entity/beta" if row.key == "beta" else "entity/alpha")
        # A depositary receipt resolves through its declared relationship below.
        if row.key != "alpha-adr":
            mappings.append(
                EntityMappingRegistration(
                    id=xray_id(f"entity-mapping/{row.key}"),
                    instrument_id=str(row.instrument.id),
                    entity_id=entity,
                    # Constituents identify Beta's instrument, without selecting
                    # a listing. Its declared company mapping covers that instrument.
                    listing_id=None if row.key == "beta" else str(row.listing.id),
                    effective_at=XRAY_EFFECTIVE,
                    valid_until=None,
                    confidence=Decimal("0.99"),
                )
            )
        relationships.append(
            EntityRelationshipRegistration(
                id=xray_id(f"listing-relationship/{row.key}"),
                kind="listing_of",
                listing_id=str(row.listing.id),
                instrument_id=str(row.instrument.id),
                effective_at=XRAY_EFFECTIVE,
                valid_until=None,
                confidence=Decimal("0.99"),
            )
        )
    classes = tuple(
        ShareClassRegistration(
            id=xray_id(f"share-class/{key}"),
            instrument_id=xray_id(f"instrument/{key}"),
            entity_id=xray_id("entity/alpha"),
            class_key=key,
            effective_at=XRAY_EFFECTIVE,
            valid_until=None,
            confidence=Decimal("0.98"),
        )
        for key in ("alpha-a", "alpha-b")
    )
    relationships.extend(
        EntityRelationshipRegistration(
            id=xray_id(f"share-relationship/{key}"),
            kind="share_class_of",
            instrument_id=xray_id(f"instrument/{key}"),
            share_class_id=xray_id(f"share-class/{key}"),
            entity_id=xray_id("entity/alpha"),
            effective_at=XRAY_EFFECTIVE,
            valid_until=None,
            confidence=Decimal("0.98"),
        )
        for key in ("alpha-a", "alpha-b")
    )
    relationships.append(
        EntityRelationshipRegistration(
            id=xray_id("receipt/alpha-adr"),
            kind="depositary_receipt_of",
            instrument_id=xray_id("instrument/alpha-adr"),
            underlying_instrument_id=xray_id("instrument/alpha-a"),
            entity_id=xray_id("entity/alpha"),
            units_per_receipt=Decimal("2"),
            effective_at=XRAY_EFFECTIVE,
            valid_until=None,
            confidence=Decimal("0.97"),
        )
    )
    return EntityEvidenceRegistration(
        id=xray_id("entity-evidence"),
        key="synthetic-xray-entities",
        provider_id=XRAY_PROVIDER_ID,
        license_version_id=XRAY_LICENSE_ID,
        revision=1,
        effective_at=XRAY_EFFECTIVE,
        valid_until=None,
        entities=(
            EconomicEntityRegistration(
                id=xray_id("entity/alpha"), key="synthetic-alpha", display_name="Synthetic Alpha"
            ),
            EconomicEntityRegistration(
                id=xray_id("entity/beta"), key="synthetic-beta", display_name="Synthetic Beta"
            ),
        ),
        mappings=tuple(mappings),
        share_classes=classes,
        relationships=tuple(relationships),
    )


def xray_replay(owner_id: str) -> XrayReplayProvider:
    def holding(
        key: str, weight: str, instrument: str | None, currency: str = "EUR"
    ) -> ConstituentHolding:
        return ConstituentHolding(
            source_key=key,
            weight=Decimal(weight),
            state=ConstituentState.RESOLVED if instrument else ConstituentState.UNRESOLVED,
            currency=CurrencyCode(currency),
            instrument_id=xray_id(f"instrument/{instrument}") if instrument else None,
            evidence_key=f"synthetic-xray-{key}" if instrument else None,
        )

    funds = (
        XrayReplayFund(
            mapping_id=xray_id("fund-mapping/fund-a"),
            effective_at=XRAY_EFFECTIVE,
            holdings=(
                holding("atlas-alpha", "0.6", "alpha-a", "USD"),
                holding("atlas-beta", "0.3", "beta"),
                holding("atlas-unresolved", "0.1", None),
            ),
            stated_coverage=Decimal("0.9"),
            unresolved_weight=Decimal("0.1"),
            cash_weight=Decimal("0"),
        ),
        XrayReplayFund(
            mapping_id=xray_id("fund-mapping/fund-b"),
            effective_at=XRAY_CURRENT_SOURCE,
            holdings=(
                holding("horizon-alpha", "0.2", "alpha-a", "USD"),
                holding("horizon-beta", "0.8", "beta"),
            ),
            stated_coverage=Decimal("1"),
            unresolved_weight=Decimal("0"),
            cash_weight=Decimal("0"),
        ),
    )
    categories = {
        "sector": ("technology", "industrials"),
        "industry": ("software", "manufacturing"),
        "country": ("US", "NL"),
        "region": ("north-america", "europe"),
        "currency": ("USD", "EUR"),
    }
    rows: list[ClassificationObservation] = []
    for dimension, (alpha, beta) in categories.items():
        rows.extend(
            ClassificationObservation(
                instrument_id=xray_id(f"instrument/{key}"),
                dimension=ClassificationDimension.ECONOMIC_CURRENCY
                if dimension == "currency"
                else ClassificationDimension(dimension),
                taxonomy=f"synthetic-xray-{dimension}",
                taxonomy_version="1",
                category=beta if key == "beta" else alpha,
                evidence_key=f"synthetic-xray-{dimension}-{key}",
                valid_from=XRAY_EFFECTIVE,
                valid_to=None,
                confidence=Decimal("0.98"),
            )
            for key in ("alpha-a", "alpha-b", "alpha-adr", "beta")
        )
    return XrayReplayProvider(
        owner_id=owner_id,
        license=xray_license(),
        known_at=XRAY_AT,
        funds=funds,
        classifications=tuple(rows),
        clock=lambda: XRAY_AT,
    )
