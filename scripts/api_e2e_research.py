"""Explicit synthetic research publication for the disposable browser fixture only."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement
from trading212_application import research as app
from trading212_application import xray as xray_app
from trading212_domain import CurrencyCode, build_synthetic_identity
from trading212_domain.research import ResearchEventKind
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.research_sources import (
    ResearchCitation,
    ResearchCompanyOverviewFacts,
    ResearchEventRevision,
    ResearchNewsFacts,
    ResearchSourceVersion,
)
from trading212_domain.sources import SourceUse
from trading212_persistence.models import PortfolioSnapshotModel
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.research_permissions import (
    ResearchCapabilityGrant,
    ResearchCapabilityRequest,
    ResearchCapabilityScope,
)
from trading212_persistence.research_service import PostgresResearchService
from trading212_persistence.source_models import (
    MarketDataProviderModel,
    ProviderLicenseVersionModel,
)
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_store import license_view
from trading212_persistence.xray_catalog_models import EconomicEntityModel
from trading212_persistence.xray_service import PostgresXrayService
from trading212_security.principals import Principal
from trading212_worker.synthetic_grants import seed_synthetic_grants
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.unit.persistence.research_authority import SyntheticResearchAuthority

KEY = b"synthetic-browser-research-cursor-key"


@dataclass(frozen=True)
class ResearchBrowserAuthority:
    """Fixed, visibly synthetic grants; no provider I/O or public registration."""

    authorities: tuple[SyntheticResearchAuthority, ...]

    def research_source_eligibility(
        self,
        scope: ResearchCapabilityScope,
        *,
        now: datetime,
    ) -> ColumnElement[bool]:
        return or_(
            *(
                authority.research_source_eligibility(scope, now=now)
                for authority in self.authorities
            )
        )

    def authorize_research_capability(
        self,
        session: Session,
        *,
        owner_id: UUID,
        provider_id: UUID,
        entity_id: UUID,
        capability: ResearchEventKind,
        license_version_id: UUID,
        grant_id: UUID | None,
        now: datetime,
        budget: SourcePurgeBudget | None = None,
    ) -> ResearchCapabilityGrant:
        for authority in self.authorities:
            grant = authority.grant
            if (
                grant.owner_id,
                grant.provider_id,
                grant.entity_id,
                grant.capability,
                grant.license_version_id,
            ) == (owner_id, provider_id, entity_id, capability, license_version_id):
                return authority.authorize_research_capability(
                    session,
                    owner_id=owner_id,
                    provider_id=provider_id,
                    entity_id=entity_id,
                    capability=capability,
                    license_version_id=license_version_id,
                    grant_id=grant_id,
                    now=now,
                    budget=budget,
                )
        raise app.ResearchServiceError(app.ResearchErrorCode.SOURCE_UNAVAILABLE)

    def authorize_research_capabilities(
        self,
        session: Session,
        *,
        requests: tuple[ResearchCapabilityRequest, ...],
        now: datetime,
    ) -> tuple[ResearchCapabilityGrant, ...]:
        # Each delegate is a zero-I/O, exact fixture grant; the normal caller
        # validates every returned identity/digest/use/clock against each request.
        return tuple(
            self.authorize_research_capability(
                session,
                owner_id=request.owner_id,
                provider_id=request.provider_id,
                entity_id=request.entity_id,
                capability=request.capability,
                license_version_id=request.license_version_id,
                grant_id=request.grant_id,
                now=now,
            )
            for request in requests
        )


async def seed_research_browser_scenario(
    sessions: sessionmaker[Session],
) -> ResearchBrowserAuthority:
    identity = build_synthetic_identity()
    at = datetime.now(UTC).replace(microsecond=0)
    scopes = app.RESEARCH_WRITE_SCOPES
    seed_synthetic_grants(sessions, app_environment="test", at=at, scopes=scopes)
    principal = Principal(
        principal_id=str(identity.principal.id),
        owner_id=str(identity.owner.id),
        issuer="local.synthetic",
        subject="synthetic-owner",
        scopes=scopes,
        authenticated_at=at - timedelta(seconds=1),
        expires_at=at + timedelta(hours=2),
    )
    account = UUID(XRAY_ACCOUNT_ID)
    # Pin an actual saved X-ray through its established application service.
    with sessions() as session:
        snapshot = session.scalar(
            select(PortfolioSnapshotModel)
            .where(
                PortfolioSnapshotModel.broker_account_id == account,
            )
            .order_by(PortfolioSnapshotModel.valuation_at.desc(), PortfolioSnapshotModel.id.desc())
            .limit(1)
        )
        if snapshot is None:
            raise RuntimeError("Research browser fixture requires the seeded X-ray account.")
        request = xray_app.XrayRunRequest(
            snapshot_id=str(snapshot.id),
            source_cutoff_at=snapshot.source_cutoff_at,
            currency=xray_app.ExplicitCurrency(
                reporting_currency=CurrencyCode(snapshot.reporting_currency)
            ),
        )
    xray_service = PostgresXrayService(
        sessions=sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: at
    )
    await xray_service.get_effective_exposure(
        principal, XRAY_ACCOUNT_ID, query=xray_app.EffectiveExposureQuery(request=request, limit=1)
    )
    alpha, beta = UUID(xray_id("entity/alpha")), UUID(xray_id("entity/beta"))
    absent = UUID(xray_id("entity/research-not-held"))
    with sessions() as session, session.begin():
        session.add(
            EconomicEntityModel(
                id=absent,
                owner_id=identity.owner.id,
                key="synthetic-research-not-held",
                created_at=at,
            )
        )
        provider = MarketDataProviderModel(
            id=uuid4(),
            owner_id=identity.owner.id,
            key="synthetic-browser-research",
            name="Synthetic browser research",
            adapter_version="browser-research-1",
            configuration_state="configured",
            synthetic=True,
            revision=1,
            capabilities=[],
            supported_price_bases=[],
            freshness_policy_version=None,
            max_age_seconds=None,
            created_at=at,
            updated_at=at,
        )
        session.add(provider)
        session.flush()
        license = ProviderLicenseVersionModel(
            id=uuid4(),
            owner_id=identity.owner.id,
            provider_id=provider.id,
            version_number=1,
            version="synthetic-research-1",
            effective_at=at - timedelta(days=2),
            store_permission="allowed",
            display_permission="allowed",
            report_permission="allowed",
            export_permission="allowed",
            retention_days=30,
            attribution="Synthetic browser research fixture. No live provider connection.",
            evidence_key="browser-research-fixture",
            created_at=at,
        )
        session.add(license)
        session.flush()
        license_value = license_view(license)
    authority = ResearchBrowserAuthority(
        tuple(
            SyntheticResearchAuthority(
                ResearchCapabilityGrant(
                    grant_id=uuid4(),
                    grant_digest=sha256(
                        f"research-browser-grant:{entity}:{kind.value}".encode()
                    ).hexdigest(),
                    owner_id=identity.owner.id,
                    provider_id=UUID(license_value.provider_id),
                    entity_id=entity,
                    capability=kind,
                    license_version_id=UUID(license_value.id),
                    effective_at=at - timedelta(days=2),
                    expires_at=at + timedelta(days=30),
                    uses=(SourceUse.STORE, SourceUse.DISPLAY),
                )
            )
            for entity, kind in (
                (alpha, ResearchEventKind.NEWS),
                (beta, ResearchEventKind.COMPANY_OVERVIEW),
                (absent, ResearchEventKind.NEWS),
            )
        )
    )
    service = PostgresResearchService(
        sessions, cursor_signing_key=KEY, clock=lambda: at, capability_authority=authority
    )
    events: list[tuple[UUID, ResearchNewsFacts | ResearchCompanyOverviewFacts]] = [
        (
            alpha,
            ResearchNewsFacts(
                publisher="Synthetic fixture publisher",
                title=f"Synthetic issuer update {index:02d}",
                summary=(
                    "<script>window.researchInjected = true</script> "
                    "Source statement; this is not portfolio finance."
                ),
                published_at=at - timedelta(hours=2, minutes=index),
            ),
        )
        for index in range(27)
    ]
    events += [
        (
            beta,
            ResearchCompanyOverviewFacts(
                publisher="Synthetic fixture publisher",
                company_name="Synthetic Beta overview",
                description="A source-authored company description.",
            ),
        ),
        (
            absent,
            ResearchNewsFacts(
                publisher="Synthetic fixture publisher",
                title="Synthetic entity absent from capture",
                summary="An event for an entity without captured exposure.",
                published_at=at - timedelta(hours=2),
            ),
        ),
    ]
    for index, (entity, facts) in enumerate(events):
        key = f"synthetic-browser-event-{index}"
        source = ResearchSourceVersion(
            source_id=uuid4(),
            version_id=uuid4(),
            owner_id=identity.owner.id,
            provider_id=UUID(license_value.provider_id),
            entity_id=entity,
            facts_digest=research_record_digest(facts),
            license_version_id=UUID(license_value.id),
            license=license_value,
            capability=ResearchEventKind(facts.kind),
            adapter_version="browser-research-1",
            request_digest=sha256(f"research-browser-request:{key}".encode()).hexdigest(),
            observed_at=at - timedelta(hours=1),
            first_known_at=at - timedelta(hours=1),
            source_cutoff_at=at,
            retained_at=at,
            expires_at=at + timedelta(days=20),
            synthetic=True,
        )
        citation = ResearchCitation(
            citation_id=uuid4(),
            source=source,
            provider_event_key=key,
            entity_id=entity,
            facts_digest=source.facts_digest,
            published_at=facts.published_at,
        )
        incoming = ResearchEventRevision(
            event_id=uuid4(),
            revision_id=uuid4(),
            revision=1,
            previous_revision_id=None,
            owner_id=identity.owner.id,
            entity_id=entity,
            provider_id=source.provider_id,
            provider_event_key=key,
            facts=facts,
            citations=(citation,),
            created_at=at,
        )
        with sessions() as session, session.begin():
            auth = authorize_report_request(
                session, principal, account_id=account, required_scopes=scopes, now=at
            )
            service.publish_event(session, auth, incoming)
    return authority
