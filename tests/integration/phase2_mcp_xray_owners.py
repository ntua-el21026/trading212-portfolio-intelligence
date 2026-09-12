"""Real two-owner X-ray inputs built through the canonical broker and catalogue paths."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from trading212_application.ingestion import (
    BrokerAccountDataProvider,
    Checkpoint,
    IngestionCapability,
    IngestionCoordinator,
    RunMode,
    RunStatus,
    SourcePage,
    SourceRecord,
)
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.source_providers import SourceCapability
from trading212_application.sources import ProviderConfigurationState
from trading212_application.xray_ingestion import (
    FundDefinitionRegistration,
    XrayPolicyRegistration,
    XrayTaxonomyRegistration,
)
from trading212_persistence.mappers import instrument_to_model, listing_to_model
from trading212_persistence.models import PortfolioSnapshotModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_service import PostgresXrayService
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.xray_fixture import (
    XRAY_EFFECTIVE,
    build_xray_fixture,
    synthetic_xray_policy,
    xray_id,
)
from trading212_worker.xray_provider import _payloads
from trading212_worker.xray_source_fixture import xray_license

from tests.integration.phase2_authorization_cases import KEY, AccountPin, OwnerGrid


class OwnerXrayProvider(BrokerAccountDataProvider):
    """Reuse declared provider-shaped facts with a strict per-call owner/account boundary."""

    def __init__(self, owner: str, account: str, observed_at: datetime) -> None:
        self.owner = owner
        self.account = account
        self.at = observed_at

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
        if (owner_id, account_id, checkpoint) != (self.owner, self.account, None):
            raise ValueError("Synthetic owner/account fixture mismatch.")
        fixture = build_xray_fixture()
        return SourcePage(
            records=tuple(
                SourceRecord(
                    provider_record_id=self.account
                    if capability is IngestionCapability.ACCOUNT
                    else key,
                    source_timestamp=effective,
                    observed_at=self.at,
                    payload=payload,
                    schema_version="p210-xray-owners-v1:" + capability.value,
                )
                for key, effective, payload in _payloads(fixture, capability)
            ),
            next_checkpoint=None,
            complete=True,
        )


@dataclass(frozen=True)
class XrayOwners:
    grid: OwnerGrid
    service: PostgresXrayService
    pins: dict[UUID, AccountPin]
    funds: tuple[str, str]


@pytest.fixture(scope="module")
def xray_owners(owner_grid: OwnerGrid) -> XrayOwners:
    grid = owner_grid
    # Catalogue identities are shared; financial snapshots and licenses are never copied.
    fixture = build_xray_fixture()
    with grid.sessions.begin() as session:
        for row in fixture.listings:
            for model in (
                instrument_to_model(row.instrument, observed_at=row.listing.valid_from),
                listing_to_model(row.listing),
            ):
                values = {
                    column.name: getattr(model, column.name)
                    for column in model.__table__.columns
                    if getattr(model, column.name) is not None or column.server_default is None
                }
                session.execute(insert(type(model)).values(**values).on_conflict_do_nothing())
    source = PostgresSourceService(
        sessions=grid.sessions,
        cursor_signing_key=KEY,
        clock=lambda: grid.at,
    )
    service = PostgresXrayService(
        sessions=grid.sessions,
        cursor_signing_key=KEY,
        clock=lambda: grid.at,
    )
    funds = (xray_id("instrument/fund-a"), xray_id("instrument/fund-b"))

    async def prepare() -> XrayOwners:
        pins: dict[UUID, AccountPin] = {}
        for actor in grid.actors:
            provider = str(uuid4())
            await source.configure_source_provider(
                actor.principal,
                SourceProviderRegistration(
                    id=provider,
                    key="synthetic",
                    name="Synthetic private fund definitions",
                    adapter_version="p210-xray-v1",
                    configuration_state=ProviderConfigurationState.CONFIGURED,
                    synthetic=True,
                    capabilities=(SourceCapability.CONSTITUENTS,),
                ),
                idempotency_key=uuid4().hex,
                correlation_id="p210-xray-owners",
            )
            license = replace(xray_license(), id=str(uuid4()), provider_id=provider)
            await source.register_source_license(
                actor.principal,
                license,
                idempotency_key=uuid4().hex,
                correlation_id="p210-xray-owners",
            )
            for fund in funds:
                await service.register_fund_definition(
                    actor.principal,
                    FundDefinitionRegistration(
                        id=str(uuid4()),
                        key="p210-fund-" + fund,
                        instrument_id=fund,
                        fund_type="etf",
                        provider_id=provider,
                        license_version_id=license.id,
                        revision=1,
                        effective_at=XRAY_EFFECTIVE,
                        valid_until=None,
                        evidence_key="synthetic",
                        confidence=Decimal("1"),
                    ),
                    idempotency_key=uuid4().hex,
                    correlation_id="p210-xray-owners",
                )
            base = synthetic_xray_policy()
            owner_policy = replace(
                base,
                taxonomy_versions=tuple(
                    replace(taxonomy, taxonomy_id=uuid4()) for taxonomy in base.taxonomy_versions
                ),
                provider_selection_policy=replace(
                    base.provider_selection_policy,
                    id=uuid4(),
                    provider_order=(provider,),
                ),
            )
            taxonomies = tuple(
                XrayTaxonomyRegistration(
                    id=str(taxonomy.taxonomy_id),
                    dimension=taxonomy.dimension,
                    key=taxonomy.key,
                    version=taxonomy.version,
                )
                for taxonomy in owner_policy.taxonomy_versions
            )
            for pin in actor.accounts:
                run = await IngestionCoordinator(
                    provider=OwnerXrayProvider(
                        actor.principal.owner_id, str(pin.account_id), grid.at
                    ),
                    store=PostgresIngestionStore(
                        grid.sessions,
                        provider="synthetic",
                        materializer=PostgresCanonicalMaterializer(),
                    ),
                    clock=lambda: grid.at,
                ).refresh(
                    owner_id=actor.principal.owner_id,
                    account_id=str(pin.account_id),
                    mode=RunMode.FULL,
                    idempotency_key=uuid4().hex,
                    correlation_id="p210-xray-owners",
                )
                assert run.status is RunStatus.SUCCEEDED
                policy = replace(owner_policy, id=uuid4())
                await service.register_xray_policy(
                    actor.principal,
                    str(pin.account_id),
                    XrayPolicyRegistration(
                        key="synthetic",
                        effective_at=XRAY_EFFECTIVE,
                        policy=policy,
                        taxonomies=taxonomies,
                    ),
                    idempotency_key=uuid4().hex,
                    correlation_id="p210-xray-owners",
                )
                with grid.sessions() as session:
                    snapshot = session.scalar(
                        select(PortfolioSnapshotModel)
                        .where(PortfolioSnapshotModel.broker_account_id == pin.account_id)
                        .order_by(
                            PortfolioSnapshotModel.created_at.desc(),
                            PortfolioSnapshotModel.id.desc(),
                        )
                        .limit(1)
                    )
                    assert snapshot is not None and snapshot.id != pin.snapshot_id
                    assert snapshot.portfolio_total == Decimal("1000")
                    pins[pin.account_id] = AccountPin(pin.account_id, snapshot.id)
        return XrayOwners(grid, service, pins, funds)

    return asyncio.run(prepare())
