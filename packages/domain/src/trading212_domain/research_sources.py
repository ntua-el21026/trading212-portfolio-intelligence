"""Minimized licensed facts, retained citations and immutable event revisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from .errors import fail_validation
from .research import (
    MAX_RESEARCH_CITATIONS,
    MAX_RESEARCH_SOURCE_BYTES,
    MAX_RESEARCH_VERSIONS,
    ResearchEventKind,
    ResearchRecord,
    inert_research_text,
    opaque_research_key,
    research_bound,
    research_unique,
)
from .sources import SourceLicense, SourceUse


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchSourceVersion(ResearchRecord):
    source_id: UUID
    version_id: UUID
    owner_id: UUID
    provider_id: UUID
    entity_id: UUID
    facts_digest: str
    license_version_id: UUID
    license: SourceLicense
    capability: ResearchEventKind
    adapter_version: str
    request_digest: str
    observed_at: datetime
    first_known_at: datetime
    source_cutoff_at: datetime
    retained_at: datetime
    expires_at: datetime
    provider: Literal["alpha_vantage"] = "alpha_vantage"
    synthetic: bool = False
    schema_version: Literal["1.0.0"] = "1.0.0"

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        opaque_research_key(self.adapter_version)
        if (str(self.provider_id), str(self.license_version_id)) != (
            self.license.provider_id,
            self.license.id,
        ):
            fail_validation("Research license identity differs.", field="license")
        if (
            not self.license.permits(SourceUse.STORE)
            or not self.license.permits(SourceUse.DISPLAY)
            or self.license.effective_at > self.first_known_at
        ):
            fail_validation("Research retained source permission is unavailable.", field="license")
        if (
            not self.observed_at
            <= self.first_known_at
            <= self.source_cutoff_at
            <= self.retained_at
            < self.expires_at
        ):
            fail_validation("Research source times are inconsistent.", field="source_cutoff_at")
        days = self.license.retention_days
        if days is None or self.expires_at > self.retained_at + timedelta(days=min(30, days)):
            fail_validation(
                "Research source retention exceeds its pinned bound.", field="expires_at"
            )

    @property
    def content_digest(self) -> str:
        from .research_serialization import research_record_digest

        return research_record_digest(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchNewsFacts(ResearchRecord):
    publisher: str
    title: str
    summary: str
    published_at: datetime
    kind: Literal["news"] = "news"
    content_type: Literal["source_facts"] = "source_facts"

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        inert_research_text(self.publisher)
        inert_research_text(self.title)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchCompanyOverviewFacts(ResearchRecord):
    publisher: str
    company_name: str
    description: str
    published_at: None = None
    publication_reason: Literal["provider_publication_unavailable"] = (
        "provider_publication_unavailable"
    )
    kind: Literal["company_overview"] = "company_overview"
    content_type: Literal["source_facts"] = "source_facts"

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        inert_research_text(self.publisher)
        inert_research_text(self.company_name)


type ResearchSourceFacts = ResearchNewsFacts | ResearchCompanyOverviewFacts


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchCitation(ResearchRecord):
    citation_id: UUID
    source: ResearchSourceVersion
    provider_event_key: str
    entity_id: UUID
    facts_digest: str
    published_at: datetime | None

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        opaque_research_key(self.provider_event_key)
        if (self.entity_id, self.facts_digest) != (self.source.entity_id, self.source.facts_digest):
            fail_validation(
                "Research citation differs from its immutable source facts.", field="citation"
            )
        if self.published_at is not None and self.published_at > self.source.observed_at:
            fail_validation("Research publication follows retrieval.", field="published_at")

    @property
    def content_digest(self) -> str:
        from .research_serialization import research_record_digest

        return research_record_digest(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchCitationPin(ResearchRecord):
    citation_id: UUID
    source_version_id: UUID
    source_version_digest: str
    citation_digest: str

    @classmethod
    def from_citation(cls, value: ResearchCitation) -> ResearchCitationPin:
        return cls(
            citation_id=value.citation_id,
            source_version_id=value.source.version_id,
            source_version_digest=value.source.content_digest,
            citation_digest=value.content_digest,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchEventRevision(ResearchRecord):
    event_id: UUID
    revision_id: UUID
    revision: int
    previous_revision_id: UUID | None
    owner_id: UUID
    entity_id: UUID
    provider_id: UUID
    provider_event_key: str
    facts: ResearchSourceFacts
    citations: tuple[ResearchCitation, ...]
    created_at: datetime
    schema_version: Literal["1.0.0"] = "1.0.0"

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        opaque_research_key(self.provider_event_key)
        research_bound(1 <= self.revision <= MAX_RESEARCH_VERSIONS, "revision")
        research_bound(1 <= len(self.citations) <= MAX_RESEARCH_CITATIONS, "citations")
        research_unique(tuple(item.citation_id for item in self.citations), "citations")
        if (self.revision == 1) != (
            self.previous_revision_id is None
        ) or self.previous_revision_id == self.revision_id:
            fail_validation("Research revision ancestry is invalid.", field="previous_revision_id")
        object.__setattr__(
            self, "citations", tuple(sorted(self.citations, key=lambda item: item.citation_id))
        )
        from .research_serialization import research_record_bytes, research_record_digest

        facts_digest = research_record_digest(self.facts)
        if not any(
            item.source.provider_id == self.provider_id
            and item.provider_event_key == self.provider_event_key
            for item in self.citations
        ):
            fail_validation("Research primary source citation is absent.", field="citations")
        for item in self.citations:
            if item.source.capability.value != self.facts.kind:
                fail_validation(
                    "Research source capability differs from its facts.", field="citations"
                )
            if (item.source.owner_id, item.entity_id, item.facts_digest, item.published_at) != (
                self.owner_id,
                self.entity_id,
                facts_digest,
                self.facts.published_at,
            ) or not item.source.retained_at <= self.created_at < item.source.expires_at:
                fail_validation("Research citation scope or facts differ.", field="citations")
        research_bound(
            len(research_record_bytes(self)) <= MAX_RESEARCH_SOURCE_BYTES, "source_bytes"
        )

    @property
    def content_digest(self) -> str:
        from .research_serialization import research_record_digest

        return research_record_digest(self)

    @property
    def expires_at(self) -> datetime:
        return min(item.source.expires_at for item in self.citations)
