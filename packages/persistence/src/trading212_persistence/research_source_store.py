"""Private typed source publication; authority and original clocks precede payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from trading212_application import research as app
from trading212_domain.research import ResearchEventKind
from trading212_domain.research_serialization import (
    research_record_bytes,
    research_record_digest,
    research_source_version_from_json,
)
from trading212_domain.research_sources import (
    ResearchCitation,
    ResearchCitationPin,
    ResearchCompanyOverviewFacts,
    ResearchNewsFacts,
    ResearchSourceFacts,
    ResearchSourceVersion,
)
from trading212_domain.sources import SourceUse

from .report_authorization import ReportAuthorization
from .research_capacity import admit_research
from .research_models import (
    ResearchCitationModel,
    ResearchOwnerErasureModel,
    ResearchRetentionModel,
    ResearchSourceModel,
    ResearchSourceOriginModel,
    ResearchSourcePayloadModel,
    ResearchSourceVersionModel,
)
from .research_permissions import ResearchCapabilityAuthority, require_research_capability
from .source_models import MarketDataProviderModel
from .source_store import SourceStore


def research_error(
    code: app.ResearchErrorCode = app.ResearchErrorCode.SOURCE_UNAVAILABLE,
) -> app.ResearchServiceError:
    return app.ResearchServiceError(code)


def research_owner_lock(session: Session, owner: UUID) -> None:
    for namespace in ("sources", "xray", "historical", "premium", "research"):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{owner}"},
        )


@dataclass(frozen=True, slots=True)
class ResearchAuthorizedSource:
    header: ResearchSourceVersionModel
    deadline: datetime


class ResearchSourceStore(SourceStore):
    """The runtime service supplies the session, current principal and closed provider grant."""

    _research_capabilities: ResearchCapabilityAuthority | None = None

    def research_authority(
        self, session: Session, auth: ReportAuthorization, *, write: bool = False
    ) -> None:
        scopes = app.RESEARCH_WRITE_SCOPES if write else app.RESEARCH_READ_SCOPES
        if not scopes <= auth.required_scopes:
            raise research_error(app.ResearchErrorCode.ACCESS_DENIED)
        auth.check(session, now=self._now())
        if (
            session.scalar(
                select(ResearchOwnerErasureModel.owner_id).where(
                    ResearchOwnerErasureModel.owner_id == auth.owner_id
                )
            )
            is not None
        ):
            raise research_error(app.ResearchErrorCode.NOT_FOUND)

    def authorize_source(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> ResearchAuthorizedSource:
        """Only metadata/normalized license fields are selected before source authority."""
        self.research_authority(session, auth)
        row = session.scalar(
            select(ResearchSourceVersionModel)
            .where(
                ResearchSourceVersionModel.owner_id == auth.owner_id,
                ResearchSourceVersionModel.id == identifier,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if row is None or not row.sealed:
            raise research_error()
        original = session.scalar(
            select(ResearchSourceOriginModel).where(
                ResearchSourceOriginModel.owner_id == auth.owner_id,
                ResearchSourceOriginModel.id == row.origin_id,
            )
        )
        provider = session.scalar(
            select(MarketDataProviderModel)
            .where(
                MarketDataProviderModel.owner_id == auth.owner_id,
                MarketDataProviderModel.id == row.provider_id,
            )
            .execution_options(populate_existing=True)
        )
        if (
            original is None
            or provider is None
            or provider.configuration_state != "configured"
            or (original.entity_id, original.capability, original.facts_digest)
            != (row.entity_id, row.capability, row.facts_digest)
            or original.original_retained_at > row.retained_at
            or session.scalar(
                select(ResearchRetentionModel.id).where(
                    ResearchRetentionModel.owner_id == auth.owner_id,
                    ResearchRetentionModel.source_version_id == row.id,
                )
            )
            is not None
        ):
            raise research_error()
        pinned = self._permit(session, auth.owner_id, row.license_version_id, SourceUse.STORE)
        self._permit(session, auth.owner_id, row.license_version_id, SourceUse.DISPLAY)
        current = self._current_license(session, auth.owner_id, row.provider_id)
        grant = require_research_capability(
            self._research_capabilities,
            session,
            owner_id=auth.owner_id,
            provider_id=row.provider_id,
            entity_id=row.entity_id,
            capability=ResearchEventKind(row.capability),
            license_version_id=row.license_version_id,
            grant_id=row.capability_grant_id,
            grant_digest=row.capability_grant_digest,
            now=self._now(),
        )
        if current is None or current.retention_days is None or pinned.retention_days is None:
            raise research_error()
        deadline = min(
            row.expires_at,
            original.expires_at,
            grant.expires_at,
            original.original_retained_at
            + timedelta(days=min(30, pinned.retention_days, current.retention_days)),
        )
        # A newly shortened right cannot leave an overlong immutable retained copy authorized.
        if (
            row.effective_expires_at > deadline
            or self._now() >= row.effective_expires_at
            or grant.effective_at > row.retained_at
        ):
            raise research_error()
        return ResearchAuthorizedSource(row, deadline)

    @staticmethod
    def source_facts(row: ResearchSourcePayloadModel) -> ResearchSourceFacts:
        if row.kind == "news":
            if (
                row.title is None
                or row.summary is None
                or row.published_at is None
                or row.company_name is not None
                or row.description is not None
                or row.publication_reason is not None
            ):
                raise research_error()
            return ResearchNewsFacts(
                publisher=row.publisher,
                title=row.title,
                summary=row.summary,
                published_at=row.published_at,
            )
        if row.kind == "company_overview":
            if (
                row.company_name is None
                or row.description is None
                or row.published_at is not None
                or row.title is not None
                or row.summary is not None
                or row.publication_reason != "provider_publication_unavailable"
            ):
                raise research_error()
            return ResearchCompanyOverviewFacts(
                publisher=row.publisher, company_name=row.company_name, description=row.description
            )
        raise research_error()

    def read_source(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> tuple[ResearchSourceVersion, ResearchSourceFacts]:
        allowed = self.authorize_source(session, auth, identifier)
        row = allowed.header
        payload = session.scalar(
            select(ResearchSourcePayloadModel).where(
                ResearchSourcePayloadModel.owner_id == auth.owner_id,
                ResearchSourcePayloadModel.version_id == row.id,
            )
        )
        if payload is None:
            raise research_error()
        value = research_source_version_from_json(
            payload.canonical_source, expected_digest=row.content_digest
        )
        facts = self.source_facts(payload)
        if (
            research_record_bytes(facts) != payload.canonical_facts
            or research_record_digest(facts) != row.facts_digest
            or (
                value.version_id,
                value.owner_id,
                value.source_id,
                value.provider_id,
                value.entity_id,
                value.license_version_id,
                value.capability.value,
                value.adapter_version,
                value.request_digest,
                value.facts_digest,
                value.observed_at,
                value.first_known_at,
                value.source_cutoff_at,
                value.retained_at,
                value.expires_at,
                value.synthetic,
            )
            != (
                row.id,
                row.owner_id,
                row.source_id,
                row.provider_id,
                row.entity_id,
                row.license_version_id,
                row.capability,
                row.adapter_version,
                row.request_digest,
                row.facts_digest,
                row.observed_at,
                row.first_known_at,
                row.source_cutoff_at,
                row.retained_at,
                row.expires_at,
                row.synthetic,
            )
            or value.license != self._license(session, auth.owner_id, row.license_version_id)
            or facts.kind != row.capability
        ):
            raise research_error()
        self.authorize_source(session, auth, identifier)
        return value, facts

    def read_citation(
        self,
        session: Session,
        auth: ReportAuthorization,
        identifier: UUID,
        *,
        expected: ResearchCitationPin | None = None,
    ) -> tuple[ResearchCitation, ResearchSourceFacts]:
        self.research_authority(session, auth)
        row = session.scalar(
            select(ResearchCitationModel).where(
                ResearchCitationModel.owner_id == auth.owner_id,
                ResearchCitationModel.id == identifier,
            )
        )
        if row is None:
            raise research_error()
        # Authorize the source before selecting payload; citation identity is metadata only.
        source, facts = self.read_source(session, auth, row.source_version_id)
        citation = ResearchCitation(
            citation_id=row.id,
            source=source,
            provider_event_key=row.provider_event_key,
            entity_id=row.entity_id,
            facts_digest=row.facts_digest,
            published_at=row.published_at,
        )
        if (
            citation.content_digest != row.content_digest
            or source.content_digest != row.source_version_digest
            or (expected is not None and ResearchCitationPin.from_citation(citation) != expected)
        ):
            raise research_error()
        return citation, facts

    def publish_source(
        self,
        session: Session,
        auth: ReportAuthorization,
        value: ResearchSourceVersion,
        facts: ResearchSourceFacts,
    ) -> ResearchSourceVersionModel:
        """Internal capability-gated publication, never a public source-registration API."""
        research_owner_lock(session, auth.owner_id)
        self.research_authority(session, auth, write=True)
        if type(value) is not ResearchSourceVersion or type(facts) not in (
            ResearchNewsFacts,
            ResearchCompanyOverviewFacts,
        ):
            raise research_error(app.ResearchErrorCode.VALIDATION_FAILED)
        if (
            value.owner_id != auth.owner_id
            or value.facts_digest != research_record_digest(facts)
            or value.capability.value != facts.kind
            or value.retained_at > self._now()
            or value.expires_at <= self._now()
        ):
            raise research_error(app.ResearchErrorCode.VALIDATION_FAILED)
        if max(len(research_record_bytes(value)), len(research_record_bytes(facts))) > 16384:
            raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
        prior = session.scalar(
            select(ResearchSourceVersionModel).where(
                ResearchSourceVersionModel.id == value.version_id
            )
        )
        if prior is not None:
            if prior.owner_id != auth.owner_id or self.read_source(session, auth, prior.id) != (
                value,
                facts,
            ):
                raise research_error(app.ResearchErrorCode.CONFLICT)
            return prior
        provider = self._owned(session, auth.owner_id, MarketDataProviderModel, value.provider_id)
        if provider.configuration_state != "configured" or provider.synthetic != value.synthetic:
            raise research_error()
        pinned = self._permit(session, auth.owner_id, value.license_version_id, SourceUse.STORE)
        self._permit(session, auth.owner_id, value.license_version_id, SourceUse.DISPLAY)
        current = self._current_license(session, auth.owner_id, value.provider_id)
        grant = require_research_capability(
            self._research_capabilities,
            session,
            owner_id=auth.owner_id,
            provider_id=value.provider_id,
            entity_id=value.entity_id,
            capability=value.capability,
            license_version_id=value.license_version_id,
            now=self._now(),
        )
        if (
            pinned != value.license
            or current is None
            or current.retention_days is None
            or pinned.retention_days is None
            or grant.effective_at > value.retained_at
        ):
            raise research_error()
        origin = session.scalar(
            select(ResearchSourceOriginModel)
            .where(
                ResearchSourceOriginModel.owner_id == auth.owner_id,
                ResearchSourceOriginModel.entity_id == value.entity_id,
                ResearchSourceOriginModel.capability == value.capability.value,
                ResearchSourceOriginModel.facts_digest == value.facts_digest,
            )
            .with_for_update()
        )
        if origin is None:
            origin = ResearchSourceOriginModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                entity_id=value.entity_id,
                capability=value.capability.value,
                facts_digest=value.facts_digest,
                original_retained_at=value.retained_at,
                expires_at=value.expires_at,
                created_at=self._now(),
            )
            session.add(origin)
            session.flush()
        if origin.original_retained_at > value.retained_at:
            raise research_error(app.ResearchErrorCode.CONFLICT)
        effective = min(
            value.expires_at,
            origin.expires_at,
            grant.expires_at,
            origin.original_retained_at
            + timedelta(days=min(30, pinned.retention_days, current.retention_days)),
        )
        if effective <= self._now():
            raise research_error()
        source = session.scalar(
            select(ResearchSourceModel).where(ResearchSourceModel.id == value.source_id)
        )
        if source is None:
            source = ResearchSourceModel(
                id=value.source_id,
                owner_id=auth.owner_id,
                provider_id=value.provider_id,
                entity_id=value.entity_id,
                capability=value.capability.value,
                provider=value.provider,
                created_at=value.retained_at,
            )
            session.add(source)
            session.flush()
        elif (
            source.owner_id,
            source.provider_id,
            source.entity_id,
            source.capability,
            source.provider,
        ) != (
            value.owner_id,
            value.provider_id,
            value.entity_id,
            value.capability.value,
            value.provider,
        ):
            raise research_error(app.ResearchErrorCode.CONFLICT)
        fact_text = (
            (facts.publisher, facts.title, facts.summary)
            if isinstance(facts, ResearchNewsFacts)
            else (facts.publisher, facts.company_name, facts.description, facts.publication_reason)
        )
        cost = (
            len(research_record_bytes(value))
            + len(research_record_bytes(facts))
            + sum(len(v.encode()) for v in fact_text)
            + len(facts.kind.encode())
            + (8 if facts.published_at is not None else 0)
        )
        admit_research(session, auth, "source", payload_bytes=cost)
        row = ResearchSourceVersionModel(
            id=value.version_id,
            owner_id=value.owner_id,
            source_id=value.source_id,
            origin_id=origin.id,
            provider_id=value.provider_id,
            entity_id=value.entity_id,
            license_version_id=value.license_version_id,
            capability=value.capability.value,
            adapter_version=value.adapter_version,
            request_digest=value.request_digest,
            facts_digest=value.facts_digest,
            content_digest=value.content_digest,
            capability_grant_id=grant.grant_id,
            capability_grant_digest=grant.grant_digest,
            observed_at=value.observed_at,
            first_known_at=value.first_known_at,
            source_cutoff_at=value.source_cutoff_at,
            retained_at=value.retained_at,
            expires_at=value.expires_at,
            effective_expires_at=effective,
            synthetic=value.synthetic,
            sealed=False,
            created_at=value.retained_at,
        )
        session.add(row)
        session.flush()
        session.add(
            ResearchSourcePayloadModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                version_id=row.id,
                canonical_source=research_record_bytes(value),
                canonical_facts=research_record_bytes(facts),
                kind=facts.kind,
                publisher=facts.publisher,
                title=facts.title if isinstance(facts, ResearchNewsFacts) else None,
                summary=facts.summary if isinstance(facts, ResearchNewsFacts) else None,
                company_name=facts.company_name
                if isinstance(facts, ResearchCompanyOverviewFacts)
                else None,
                description=facts.description
                if isinstance(facts, ResearchCompanyOverviewFacts)
                else None,
                published_at=facts.published_at,
                publication_reason=None
                if isinstance(facts, ResearchNewsFacts)
                else facts.publication_reason,
                created_at=self._now(),
            )
        )
        session.flush()
        row.sealed = True
        session.flush()
        self.read_source(session, auth, row.id)
        return row

    def publish_citation(
        self,
        session: Session,
        auth: ReportAuthorization,
        value: ResearchCitation,
        facts: ResearchSourceFacts,
    ) -> ResearchCitationModel:
        self.publish_source(session, auth, value.source, facts)
        prior = session.scalar(
            select(ResearchCitationModel).where(ResearchCitationModel.id == value.citation_id)
        )
        if prior is not None:
            if (
                prior.owner_id != auth.owner_id
                or self.read_citation(session, auth, prior.id)[0] != value
            ):
                raise research_error(app.ResearchErrorCode.CONFLICT)
            return prior
        # Reusing a source version/key with a different row identity is a conflicting receipt.
        if (
            session.scalar(
                select(ResearchCitationModel.id).where(
                    ResearchCitationModel.source_version_id == value.source.version_id,
                    ResearchCitationModel.provider_event_key == value.provider_event_key,
                )
            )
            is not None
        ):
            raise research_error(app.ResearchErrorCode.CONFLICT)
        row = ResearchCitationModel(
            id=value.citation_id,
            owner_id=auth.owner_id,
            source_version_id=value.source.version_id,
            source_version_digest=value.source.content_digest,
            entity_id=value.entity_id,
            provider_event_key=value.provider_event_key,
            facts_digest=value.facts_digest,
            published_at=value.published_at,
            content_digest=value.content_digest,
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        self.read_citation(session, auth, row.id)
        return row
