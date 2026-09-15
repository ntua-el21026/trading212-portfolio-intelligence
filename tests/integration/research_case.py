"""Real storage/X-ray fixture with an explicitly synthetic private grant authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from trading212_application import research as app
from trading212_domain.research import ResearchEventKind
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.research_sources import (
    ResearchCitation,
    ResearchEventRevision,
    ResearchNewsFacts,
    ResearchSourceVersion,
)
from trading212_domain.sources import SourceUse
from trading212_persistence.report_authorization import (
    ReportAuthorization,
    authorize_report_request,
)
from trading212_persistence.research_permissions import ResearchCapabilityGrant
from trading212_persistence.research_service import PostgresResearchService
from trading212_persistence.source_models import (
    MarketDataProviderModel,
    ProviderLicenseVersionModel,
)
from trading212_persistence.source_store import license_view
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_scenario_runs_postgres import grant_scenario_identity
from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.unit.persistence.research_authority import SyntheticResearchAuthority


@dataclass
class ResearchCase:
    xray: XrayReadCase
    service: PostgresResearchService
    authority: SyntheticResearchAuthority
    license: ProviderLicenseVersionModel
    run_id: UUID
    entity_id: UUID

    @property
    def account_id(self) -> UUID:
        return UUID(XRAY_ACCOUNT_ID)

    def auth(self, session: Session) -> ReportAuthorization:
        return authorize_report_request(
            session,
            self.xray.principal,
            account_id=self.account_id,
            required_scopes=app.RESEARCH_WRITE_SCOPES,
            now=self.xray.now[0],
        )

    def incoming(
        self,
        key: str,
        *,
        summary: str = "Actual synthetic issuer update.",
        revision: int = 1,
        previous_revision_id: UUID | None = None,
        entity_id: UUID | None = None,
    ) -> ResearchEventRevision:
        at = self.xray.now[0]
        entity = self.entity_id if entity_id is None else entity_id
        facts = ResearchNewsFacts(
            publisher="Synthetic licensed publisher",
            title="Retained issuer update",
            summary=summary,
            published_at=at - timedelta(hours=2),
        )
        source = ResearchSourceVersion(
            source_id=uuid4(),
            version_id=uuid4(),
            owner_id=UUID(self.xray.principal.owner_id),
            provider_id=self.license.provider_id,
            entity_id=entity,
            facts_digest=research_record_digest(facts),
            license_version_id=self.license.id,
            license=license_view(self.license),
            capability=ResearchEventKind.NEWS,
            adapter_version="research-fixture-1",
            request_digest="a" * 64,
            observed_at=at - timedelta(hours=1),
            first_known_at=at - timedelta(hours=1),
            source_cutoff_at=at,
            retained_at=at,
            expires_at=at + timedelta(days=30),
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
        return ResearchEventRevision(
            event_id=uuid4(),
            revision_id=uuid4(),
            revision=revision,
            previous_revision_id=previous_revision_id,
            owner_id=source.owner_id,
            entity_id=entity,
            provider_id=source.provider_id,
            provider_event_key=key,
            facts=facts,
            citations=(citation,),
            created_at=at,
        )

    def publish(self, value: ResearchEventRevision) -> ResearchEventRevision:
        with self.xray.sessions() as session, session.begin():
            return self.service.publish_event(session, self.auth(session), value)

    def query(self, *, limit: int = 25, cursor: str | None = None) -> app.ResearchSummaryQuery:
        return app.ResearchSummaryQuery(
            account_id=self.account_id,
            xray_run_id=self.run_id,
            source_cutoff_at=self.xray.now[0],
            limit=limit,
            cursor=cursor,
        )


@pytest.fixture
async def research_case(xray_read_case: XrayReadCase) -> ResearchCase:
    case = xray_read_case
    case.now[0] = max(case.now[0], datetime.now(UTC))
    grant_scenario_identity(case.sessions, case.principal, case.now[0])
    saved = await company(case)
    owner = UUID(case.principal.owner_id)
    entity = UUID(xray_id("entity/alpha"))
    at = case.now[0]
    with case.sessions() as session, session.begin():
        provider = MarketDataProviderModel(
            id=uuid4(),
            owner_id=owner,
            key=uuid4().hex,
            name="Synthetic research fixture",
            adapter_version="research-fixture-1",
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
            owner_id=owner,
            provider_id=provider.id,
            version_number=1,
            version="1",
            effective_at=at - timedelta(days=1),
            store_permission="allowed",
            display_permission="allowed",
            report_permission="allowed",
            export_permission="allowed",
            retention_days=30,
            attribution="Synthetic research fixture",
            evidence_key="fixture",
            created_at=at,
        )
        session.add(license)
        session.flush()
        session.expunge(license)
    authority = SyntheticResearchAuthority(
        ResearchCapabilityGrant(
            grant_id=uuid4(),
            grant_digest="b" * 64,
            owner_id=owner,
            provider_id=license.provider_id,
            entity_id=entity,
            capability=ResearchEventKind.NEWS,
            license_version_id=license.id,
            effective_at=at - timedelta(days=1),
            expires_at=at + timedelta(days=365),
            uses=(SourceUse.STORE, SourceUse.DISPLAY),
        )
    )
    service = PostgresResearchService(
        case.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: case.now[0],
        capability_authority=authority,
    )
    return ResearchCase(case, service, authority, license, UUID(saved.context.run_id), entity)
