"""Owner-authored revisions and exact acknowledgments; never copied provider facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from .errors import fail_validation
from .research import (
    MAX_RESEARCH_CITATIONS,
    MAX_RESEARCH_COMMAND_BYTES,
    MAX_RESEARCH_VERSIONS,
    ResearchRecord,
    inert_research_text,
    research_bound,
    research_unique,
)
from .research_sources import ResearchCitationPin


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchNoteContent(ResearchRecord):
    title: str
    note: str = ""
    thesis: str = ""
    risks: str = ""
    catalysts: str = ""
    break_conditions: str = ""
    citations: tuple[ResearchCitationPin, ...] = ()
    content_type: Literal["owner_revision"] = "owner_revision"

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        inert_research_text(self.title)
        if not any(
            value.strip()
            for value in (self.note, self.thesis, self.risks, self.catalysts, self.break_conditions)
        ):
            fail_validation("Research note content is empty.", field="note")
        research_bound(len(self.citations) <= MAX_RESEARCH_CITATIONS, "citations")
        research_unique(tuple(item.citation_id for item in self.citations), "citations")
        object.__setattr__(
            self, "citations", tuple(sorted(self.citations, key=lambda item: item.citation_id))
        )
        from .research_serialization import research_record_bytes

        research_bound(len(research_record_bytes(self)) <= MAX_RESEARCH_COMMAND_BYTES, "note_bytes")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchNoteRevision(ResearchRecord):
    note_id: UUID
    revision_id: UUID
    revision: int
    previous_revision_id: UUID | None
    owner_id: UUID
    account_id: UUID
    entity_id: UUID
    actor_id: UUID
    created_at: datetime
    content: ResearchNoteContent
    schema_version: Literal["1.0.0"] = "1.0.0"

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        research_bound(1 <= self.revision <= MAX_RESEARCH_VERSIONS, "revision")
        if (self.revision == 1) != (
            self.previous_revision_id is None
        ) or self.previous_revision_id == self.revision_id:
            fail_validation("Research note ancestry is invalid.", field="previous_revision_id")

    @property
    def content_digest(self) -> str:
        from .research_serialization import research_record_digest

        return research_record_digest(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchReviewAcknowledgment(ResearchRecord):
    acknowledgment_id: UUID
    owner_id: UUID
    account_id: UUID
    event_id: UUID
    revision_id: UUID
    revision_digest: str
    actor_id: UUID
    reviewed_at: datetime
