"""Real normalized research entitlements for the disposable report browser journey."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import research as app
from trading212_application import xray as xray_app
from trading212_domain import CurrencyCode, build_synthetic_identity
from trading212_domain.research import ResearchEventKind
from trading212_domain.research_notes import ResearchNoteContent
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.research_sources import (
    ResearchCitation,
    ResearchCitationPin,
    ResearchEventRevision,
    ResearchNewsFacts,
    ResearchSourceVersion,
)
from trading212_persistence.acquisition_authority import grant_digest
from trading212_persistence.acquisition_models import (
    ProviderCapabilityGrantModel,
    ProviderCapabilityScopeModel,
)
from trading212_persistence.acquisition_research_authority import (
    PostgresResearchCapabilityAuthority,
)
from trading212_persistence.models import PortfolioSnapshotModel
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_persistence.research_models import (
    ResearchNotePayloadModel,
    ResearchNoteRevisionModel,
)
from trading212_persistence.research_service import PostgresResearchService
from trading212_persistence.source_models import (
    MarketDataProviderModel,
    ProviderLicenseVersionModel,
)
from trading212_persistence.source_store import license_view
from trading212_persistence.xray_catalog_models import EconomicEntityModel
from trading212_persistence.xray_service import PostgresXrayService
from trading212_security.principals import Principal, Scope
from trading212_worker.synthetic_grants import seed_synthetic_grants
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

Control = Literal["revoke_report", "expire", "revoke_write"]


@dataclass
class ResearchReportBrowserFixture:
    sessions: sessionmaker[Session]
    at: datetime
    owner_id: UUID
    principal_id: UUID
    account_id: UUID
    grant: ProviderCapabilityGrantModel
    item_id: UUID
    absent_item_id: UUID
    note_ids: tuple[UUID, ...]
    missing_note_revision_id: UUID
    foreign_note_id: UUID
    review_id: UUID
    offset: timedelta = timedelta()
    submissions: list[dict[str, str | int]] = field(default_factory=list)
    completed_controls: set[Control] = field(default_factory=set)

    def now(self) -> datetime:
        return datetime.now(UTC) + self.offset

    def metadata(self) -> dict[str, object]:
        return {
            "account_id": str(self.account_id),
            "item_id": str(self.item_id),
            "absent_item_id": str(self.absent_item_id),
            "note_revision_ids": [str(value) for value in self.note_ids],
            "missing_note_revision_id": str(self.missing_note_revision_id),
            "foreign_note_id": str(self.foreign_note_id),
            "review_id": str(self.review_id),
            "submissions": list(self.submissions),
        }

    def observe(self, status: int, key: str | None) -> None:
        if len(self.submissions) >= 128:
            raise RuntimeError("The bounded research report browser command journal is full.")
        self.submissions.append(
            {
                "status": status,
                "key_digest": sha256((key or "").encode()).hexdigest(),
            }
        )

    def control(self, action: Control) -> None:
        if action in self.completed_controls:
            raise RuntimeError("A destructive research browser control cannot be repeated.")
        with self.sessions() as session, session.begin():
            _require_disposable(session)
            if action == "revoke_report":
                original = self.grant
                denied = ProviderCapabilityGrantModel(
                    id=uuid4(),
                    owner_id=original.owner_id,
                    provider_id=original.provider_id,
                    scope_id=original.scope_id,
                    version_number=original.version_number + 1,
                    license_version_id=original.license_version_id,
                    effective_at=self.now(),
                    expires_at=original.expires_at,
                    store_allowed=True,
                    display_allowed=True,
                    report_allowed=False,
                    export_allowed=False,
                    daily_allowance=original.daily_allowance,
                    evidence_key="synthetic-browser-current-report-denial",
                    content_digest="0" * 64,
                    created_at=self.now(),
                )
                denied.content_digest = grant_digest(denied)
                session.add(denied)
            elif action == "expire":
                self.offset = timedelta(minutes=15)
            elif action == "revoke_write":
                grant = session.scalar(
                    select(PrincipalScopeGrantModel).where(
                        PrincipalScopeGrantModel.principal_id == self.principal_id,
                        PrincipalScopeGrantModel.scope == Scope.REPORTS_WRITE.value,
                    )
                )
                if grant is None or grant.revoked_at is not None:
                    raise RuntimeError("The original report-write grant is unavailable.")
                grant.revoked_at = self.now()
            else:
                raise ValueError("The research browser control is unsupported.")
        self.completed_controls.add(action)


def _require_disposable(session: Session) -> None:
    database = session.get_bind().engine.url.database
    if not re.fullmatch(r"t212pi_web_e2e_[0-9a-f]{32}", database or ""):
        raise RuntimeError("Research browser controls require their disposable database.")


async def seed_research_report_browser_scenario(
    sessions: sessionmaker[Session],
) -> ResearchReportBrowserFixture:
    """Publish real retained inputs; provider data and all identities are synthetic."""
    identity, at = build_synthetic_identity(), datetime.now(UTC)
    scopes = app.RESEARCH_WRITE_SCOPES | {Scope.REPORTS_READ, Scope.REPORTS_WRITE}
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
    account, alpha = UUID(XRAY_ACCOUNT_ID), UUID(xray_id("entity/alpha"))
    absent = uuid4()
    with sessions() as session, session.begin():
        _require_disposable(session)
        snapshot = session.scalar(
            select(PortfolioSnapshotModel)
            .where(
                PortfolioSnapshotModel.broker_account_id == account,
            )
            .order_by(PortfolioSnapshotModel.valuation_at.desc(), PortfolioSnapshotModel.id.desc())
            .limit(1)
        )
        if snapshot is None:
            raise RuntimeError("Research report browser fixture requires the saved X-ray account.")
        xray_request = xray_app.XrayRunRequest(
            snapshot_id=str(snapshot.id),
            source_cutoff_at=snapshot.source_cutoff_at,
            currency=xray_app.ExplicitCurrency(reporting_currency=CurrencyCode("EUR")),
        )
        session.add(
            EconomicEntityModel(
                id=absent,
                owner_id=identity.owner.id,
                key="synthetic-report-absent-entity",
                created_at=at,
            )
        )
        provider = MarketDataProviderModel(
            id=uuid4(),
            owner_id=identity.owner.id,
            key="alpha_vantage",
            name="Synthetic browser report entitlement",
            adapter_version="browser-research-report-1",
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
            version="synthetic-browser-report-only-1",
            effective_at=at - timedelta(hours=1),
            store_permission="allowed",
            display_permission="allowed",
            report_permission="allowed",
            export_permission="denied",
            retention_days=30,
            attribution="Synthetic browser research report evidence.",
            evidence_key="synthetic-browser-report-license",
            created_at=at,
        )
        session.add(license)
        session.flush()
        license_value = license_view(license)
        grants = []
        for entity in (alpha, absent):
            scope = ProviderCapabilityScopeModel(
                id=uuid4(),
                owner_id=identity.owner.id,
                provider_id=provider.id,
                capability="news_sentiment",
                subject_kind="entity",
                subject_id=entity,
                created_at=at,
            )
            session.add(scope)
            session.flush()
            grant = ProviderCapabilityGrantModel(
                id=uuid4(),
                owner_id=identity.owner.id,
                provider_id=provider.id,
                scope_id=scope.id,
                version_number=1,
                license_version_id=license.id,
                effective_at=at - timedelta(minutes=30),
                expires_at=at + timedelta(days=30),
                store_allowed=True,
                display_allowed=True,
                report_allowed=True,
                export_allowed=False,
                daily_allowance=25,
                evidence_key="synthetic-browser-report-approval",
                content_digest="0" * 64,
                created_at=at,
            )
            grant.content_digest = grant_digest(grant)
            session.add(grant)
            session.flush()
            session.expunge(grant)
            grants.append(grant)
    xray = PostgresXrayService(
        sessions=sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: at
    )
    financial = await xray.get_effective_exposure(
        principal,
        XRAY_ACCOUNT_ID,
        query=xray_app.EffectiveExposureQuery(request=xray_request, limit=1),
    )
    service = PostgresResearchService(
        sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: datetime.now(UTC),
        capability_authority=PostgresResearchCapabilityAuthority(),
    )
    events = []
    for index, entity in enumerate((alpha, absent)):
        facts = ResearchNewsFacts(
            publisher="Synthetic browser publisher",
            title=f"Browser research report source {index}",
            summary="A2_PRIVATE_SOURCE_PROSE <script>window.researchReportInjected=true</script>",
            published_at=at - timedelta(hours=2),
        )
        key = f"browser-research-report-event-{index}"
        observed = datetime.now(UTC)
        source = ResearchSourceVersion(
            source_id=uuid4(),
            version_id=uuid4(),
            owner_id=identity.owner.id,
            provider_id=UUID(license_value.provider_id),
            entity_id=entity,
            facts_digest=research_record_digest(facts),
            license_version_id=UUID(license_value.id),
            license=license_value,
            capability=ResearchEventKind.NEWS,
            adapter_version="browser-research-report-1",
            request_digest=sha256(key.encode()).hexdigest(),
            observed_at=observed,
            first_known_at=observed,
            source_cutoff_at=observed,
            retained_at=observed,
            expires_at=observed + timedelta(minutes=10),
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
            created_at=observed,
        )
        with sessions() as session, session.begin():
            auth = authorize_report_request(
                session,
                principal,
                account_id=account,
                required_scopes=scopes,
                now=datetime.now(UTC),
            )
            events.append(service.publish_event(session, auth, incoming))
    cutoff = datetime.now(UTC)
    summary = await service.get_research_summary(
        principal,
        app.ResearchSummaryQuery(
            account_id=account,
            xray_run_id=UUID(financial.context.run_id),
            source_cutoff_at=cutoff,
            limit=25,
        ),
    )
    items = {item.source.entity_id: item for item in summary.items}
    first = await service.create_research_note(
        principal,
        app.CreateResearchNote(
            account_id=account,
            entity_id=alpha,
            content=ResearchNoteContent(
                title="Historical owner thesis",
                note="=1+1\nA2_PRIVATE_OWNER_PROSE",
                thesis="Original exact historical thesis.",
                citations=(ResearchCitationPin.from_citation(events[0].citations[0]),),
            ),
            idempotency_key="browser-report-note-1",
            correlation_id="browser-report-fixture",
        ),
    )
    revisions, head = [first.revision_id], first
    for revision in range(2, 65):
        head = await service.create_research_note_version(
            principal,
            app.CreateResearchNoteVersion(
                note_id=first.note_id,
                expected_revision=head.revision,
                content=replace(first.content, thesis=f"Later explicit owner revision {revision}."),
                idempotency_key=f"browser-report-note-{revision}",
                correlation_id="browser-report-fixture",
            ),
        )
        revisions.append(head.revision_id)
    # A nonexistent immutable revision exercises missing-record denial without
    # inventing unsupported partial note erasure while the owner stays active.
    missing_note_revision_id = uuid4()
    with sessions() as session:
        _require_disposable(session)
        header = session.scalar(
            select(ResearchNoteRevisionModel.id).where(
                ResearchNoteRevisionModel.id == missing_note_revision_id
            )
        )
        payload = session.scalar(
            select(ResearchNotePayloadModel.id).where(
                ResearchNotePayloadModel.revision_id == missing_note_revision_id
            )
        )
        if header is not None or payload is not None:
            raise RuntimeError("The dedicated missing note revision unexpectedly exists.")
    foreign = await service.create_research_note(
        principal,
        app.CreateResearchNote(
            account_id=identity.account.id,
            entity_id=alpha,
            content=ResearchNoteContent(
                title="Foreign account owner note", thesis="A2_FOREIGN_ACCOUNT_NOTE_PROSE"
            ),
            idempotency_key="browser-report-foreign-account-note",
            correlation_id="browser-report-fixture",
        ),
    )
    review = await service.review_research_event(
        principal,
        app.ReviewResearchEvent(
            event_id=events[0].event_id,
            revision_id=events[0].revision_id,
            revision_digest=events[0].content_digest,
            idempotency_key="browser-report-review",
            correlation_id="browser-report-fixture",
        ),
    )
    return ResearchReportBrowserFixture(
        sessions,
        at,
        identity.owner.id,
        identity.principal.id,
        account,
        grants[0],
        items[alpha].item_id,
        items[absent].item_id,
        tuple(revisions),
        missing_note_revision_id,
        foreign.revision_id,
        review.acknowledgment_id,
    )
