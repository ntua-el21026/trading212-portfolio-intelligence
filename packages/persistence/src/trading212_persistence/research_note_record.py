"""Pure strict normalized/canonical note agreement shared by item and batch reads."""

from trading212_domain.research_notes import ResearchNoteRevision
from trading212_domain.research_serialization import research_note_from_json
from trading212_domain.research_sources import ResearchCitationPin

from .research_models import (
    ResearchNoteCitationModel,
    ResearchNotePayloadModel,
    ResearchNoteRevisionModel,
)
from .research_source_store import research_error


def research_note_record(
    row: ResearchNoteRevisionModel,
    payload: ResearchNotePayloadModel,
    citations: tuple[ResearchNoteCitationModel, ...],
) -> ResearchNoteRevision:
    value = research_note_from_json(payload.canonical_note, expected_digest=row.content_digest)
    pins = tuple(
        ResearchCitationPin(
            citation_id=c.citation_id,
            source_version_id=c.source_version_id,
            source_version_digest=c.source_version_digest,
            citation_digest=c.citation_digest,
        )
        for c in citations
    )
    if (
        len(citations) != row.citation_count
        or tuple(c.ordinal for c in citations) != tuple(range(row.citation_count))
        or (
            value.note_id,
            value.revision_id,
            value.revision,
            value.previous_revision_id,
            value.owner_id,
            value.account_id,
            value.entity_id,
            value.actor_id,
            value.created_at,
        )
        != (
            row.note_id,
            row.id,
            row.revision,
            row.previous_revision_id,
            row.owner_id,
            row.account_id,
            row.entity_id,
            row.actor_id,
            row.created_at,
        )
        or (
            value.content.title,
            value.content.note,
            value.content.thesis,
            value.content.risks,
            value.content.catalysts,
            value.content.break_conditions,
            value.content.citations,
        )
        != (
            payload.title,
            payload.note,
            payload.thesis,
            payload.risks,
            payload.catalysts,
            payload.break_conditions,
            pins,
        )
    ):
        raise research_error()
    return value
