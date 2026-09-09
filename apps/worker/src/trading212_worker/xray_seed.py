"""Idempotent local/test X-ray seed through real broker and licensed source ingestion."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import source_providers as ports
from trading212_application.ingestion import IngestionCoordinator, RunMode, RunStatus
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.sources import ProviderConfigurationState
from trading212_application.xray_ingestion import (
    FundDefinitionRegistration,
    FundSourceMappingRegistration,
    XrayPolicyRegistration,
    XrayTaxonomyRegistration,
)
from trading212_domain import build_synthetic_identity
from trading212_domain.xray import XrayDimension
from trading212_persistence.mappers import account_to_model, instrument_to_model, listing_to_model
from trading212_persistence.models import (
    BrokerAccountModel,
    InstrumentModel,
    ListingModel,
    PortfolioSnapshotModel,
)
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import Principal, Scope

from .materializer import PostgresCanonicalMaterializer
from .postgres_store import PostgresIngestionStore
from .source_seed import collect_source_pages
from .xray_fixture import (
    XRAY_ACCOUNT_ID,
    XRAY_AT,
    XRAY_EFFECTIVE,
    XRAY_LICENSE_ID,
    XRAY_PROVIDER_ID,
    build_xray_fixture,
    synthetic_xray_policy,
    xray_id,
)
from .xray_provider import SyntheticXrayBrokerProvider
from .xray_source_fixture import xray_entities, xray_license, xray_replay

XRAY_CURSOR_KEY = hashlib.sha256(b"synthetic-xray-seed-cursors-v1").digest()


def _identity(sessions: sessionmaker[Session]) -> None:
    fixture = build_xray_fixture()
    models: list[BrokerAccountModel | InstrumentModel | ListingModel] = [
        account_to_model(fixture.account)
    ]
    for item in fixture.listings:
        models.extend(
            (
                instrument_to_model(item.instrument, observed_at=item.listing.valid_from),
                listing_to_model(item.listing),
            )
        )
    with sessions.begin() as session:
        for model in models:
            values = {
                column.name: getattr(model, column.name)
                for column in model.__table__.columns
                if getattr(model, column.name) is not None or column.server_default is None
            }
            session.execute(insert(type(model)).values(**values).on_conflict_do_nothing())


async def seed_xray_scenario(
    sessions: sessionmaker[Session], *, app_environment: str
) -> dict[str, str]:
    if app_environment not in {"local", "test"}:
        raise RuntimeError("Synthetic X-ray seed is restricted to local/test environments.")
    from trading212_persistence.xray_service import PostgresXrayService

    _identity(sessions)
    identity = build_synthetic_identity()
    owner = str(identity.owner.id)
    principal = Principal(
        str(identity.principal.id),
        owner,
        "local.synthetic",
        "synthetic-owner",
        frozenset(Scope),
        XRAY_AT - timedelta(minutes=1),
        XRAY_AT + timedelta(hours=1),
    )
    prefix = "synthetic-xray-seed-v1"
    run = await IngestionCoordinator(
        provider=SyntheticXrayBrokerProvider(),
        store=PostgresIngestionStore(
            sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
        ),
        clock=lambda: XRAY_AT,
    ).refresh(
        owner_id=owner,
        account_id=XRAY_ACCOUNT_ID,
        mode=RunMode.FULL,
        idempotency_key=prefix,
        correlation_id=prefix,
    )
    if run.status is not RunStatus.SUCCEEDED:
        raise RuntimeError("Synthetic X-ray broker ingestion did not complete.")
    source = PostgresSourceService(
        sessions=sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: XRAY_AT
    )
    await source.configure_source_provider(
        principal,
        SourceProviderRegistration(
            id=XRAY_PROVIDER_ID,
            key="synthetic-xray",
            name="Synthetic X-ray reference replay",
            adapter_version="synthetic-xray-replay-v1",
            configuration_state=ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(
                ports.SourceCapability.CLASSIFICATIONS,
                ports.SourceCapability.CONSTITUENTS,
            ),
            freshness_policy_version="synthetic-xray-freshness-1",
            max_age_seconds=7 * 86400,
        ),
        idempotency_key=f"{prefix}:provider",
        correlation_id=prefix,
    )
    await source.register_source_license(
        principal, xray_license(), idempotency_key=f"{prefix}:license", correlation_id=prefix
    )
    service = PostgresXrayService(
        sessions=sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: XRAY_AT
    )
    await service.register_xray_policy(
        principal,
        XRAY_ACCOUNT_ID,
        XrayPolicyRegistration(
            key="synthetic-xray-v1",
            effective_at=XRAY_EFFECTIVE,
            policy=synthetic_xray_policy(),
            taxonomies=tuple(
                XrayTaxonomyRegistration(
                    id=xray_id(f"taxonomy/{dimension.value}"),
                    dimension=dimension,
                    key=f"synthetic-xray-{dimension.value}",
                    version="1",
                )
                for dimension in XrayDimension
                if dimension is not XrayDimension.COMPANY
            ),
        ),
        idempotency_key=f"{prefix}:policy",
        correlation_id=prefix,
    )
    await service.register_entity_evidence(
        principal, xray_entities(), idempotency_key=f"{prefix}:entities", correlation_id=prefix
    )
    provider = xray_replay(owner)
    result = {
        "account_id": XRAY_ACCOUNT_ID,
        "source_cutoff_at": XRAY_AT.isoformat(),
        "provider_id": XRAY_PROVIDER_ID,
    }
    for key in ("fund-a", "fund-b"):
        await service.register_fund_definition(
            principal,
            FundDefinitionRegistration(
                id=xray_id(f"fund-definition/{key}"),
                key=f"synthetic-{key}",
                instrument_id=xray_id(f"instrument/{key}"),
                fund_type="etf",
                provider_id=XRAY_PROVIDER_ID,
                license_version_id=XRAY_LICENSE_ID,
                revision=1,
                effective_at=XRAY_EFFECTIVE,
                valid_until=None,
                evidence_key=f"synthetic-{key}-definition",
                confidence=Decimal("0.99"),
            ),
            idempotency_key=f"{prefix}:definition:{key}",
            correlation_id=prefix,
        )
        await service.register_fund_mapping(
            principal,
            FundSourceMappingRegistration(
                id=xray_id(f"fund-mapping/{key}"),
                fund_definition_id=xray_id(f"fund-definition/{key}"),
                provider_id=XRAY_PROVIDER_ID,
                license_version_id=XRAY_LICENSE_ID,
                provider_fund_key=f"synthetic-{key}",
                revision=1,
                effective_at=XRAY_EFFECTIVE,
                valid_until=None,
                evidence_key=f"synthetic-{key}-mapping",
                confidence=Decimal("0.99"),
            ),
            idempotency_key=f"{prefix}:mapping:{key}",
            correlation_id=prefix,
        )
        request = ports.ConstituentRequest(
            fund_series_id=xray_id(f"fund-mapping/{key}"),
            effective_at=XRAY_AT,
            source_cutoff_at=XRAY_AT,
        )

        async def fetch(
            cursor: str | None, request: ports.ConstituentRequest = request
        ) -> ports.ConstituentPage | ports.SourceFailure:
            from dataclasses import replace

            return await provider.get_constituents(replace(request, continuation=cursor))

        pages = await collect_source_pages(
            fetch,
            page_type=ports.ConstituentPage,
            next_cursor=lambda page: page.continuation,
            row_count=lambda page: len(page.holdings),
        )
        receipt = await service.ingest_constituents(
            principal,
            request,
            pages,
            idempotency_key=f"{prefix}:constituents:{key}",
            correlation_id=prefix,
        )
        result[f"{key}_instrument_id"] = xray_id(f"instrument/{key}")
        result[f"{key}_snapshot_id"] = receipt.id
    for dimension in XrayDimension:
        if dimension is XrayDimension.COMPANY:
            continue
        classification_request = ports.ClassificationRequest(
            instrument_ids=tuple(
                xray_id(f"instrument/{key}") for key in ("alpha-a", "alpha-b", "alpha-adr", "beta")
            ),
            taxonomy=f"synthetic-xray-{dimension.value}",
            taxonomy_version="1",
            source_cutoff_at=XRAY_AT,
        )

        async def fetch_classifications(
            cursor: str | None, request: ports.ClassificationRequest = classification_request
        ) -> ports.ClassificationPage | ports.SourceFailure:
            from dataclasses import replace

            return await provider.get_classifications(replace(request, continuation=cursor))

        pages_classifications = await collect_source_pages(
            fetch_classifications,
            page_type=ports.ClassificationPage,
            next_cursor=lambda page: page.continuation,
            row_count=lambda page: len(page.observations),
        )
        await service.ingest_classifications(
            principal,
            classification_request,
            pages_classifications,
            idempotency_key=f"{prefix}:classification:{dimension.value}",
            correlation_id=prefix,
        )
    with sessions() as session:
        snapshot = session.scalar(
            select(PortfolioSnapshotModel)
            .where(PortfolioSnapshotModel.broker_account_id == UUID(XRAY_ACCOUNT_ID))
            .order_by(PortfolioSnapshotModel.created_at.desc(), PortfolioSnapshotModel.id.desc())
            .limit(1)
        )
        if snapshot is None:
            raise RuntimeError("Synthetic X-ray snapshot is missing after successful ingestion.")
        result["snapshot_id"] = str(snapshot.id)
    return result
