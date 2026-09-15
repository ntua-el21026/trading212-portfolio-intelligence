"""Fixed typed payload batches; invoked only after complete page source authority."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import Integer, LargeBinary, Text, Uuid, literal, select, union_all
from sqlalchemy.orm import Session
from trading212_domain.research_notes import ResearchNoteRevision
from trading212_domain.research_ranking import (
    research_material_digest,
    research_semantic_fact_digest,
)
from trading212_domain.research_serialization import (
    research_event_from_json,
    research_record_bytes,
    research_record_digest,
    research_source_version_from_json,
)
from trading212_domain.research_sources import (
    ResearchCitation,
    ResearchEventRevision,
    ResearchSourceFacts,
    ResearchSourceVersion,
)

from .report_authorization import ReportAuthorization
from .research_models import (
    ResearchEventPayloadModel,
    ResearchNoteCitationModel,
    ResearchNoteModel,
    ResearchNotePayloadModel,
    ResearchNoteRevisionModel,
    ResearchSourcePayloadModel,
)
from .research_note_record import research_note_record
from .research_source_store import ResearchSourceStore, research_error
from .research_summary_query import ResearchCandidatePage
from .source_store import license_view
from .types import UTCDateTime


def research_event_payloads(
    session: Session,
    auth: ReportAuthorization,
    page: ResearchCandidatePage,
) -> dict[UUID, ResearchEventRevision]:
    if not page.candidates:
        return {}
    source, event = ResearchSourcePayloadModel, ResearchEventPayloadModel
    fields = (
        "publisher",
        "title",
        "summary",
        "company_name",
        "description",
        "kind",
        "publication_reason",
    )
    statement = union_all(
        select(
            literal("source").label("record_kind"),
            source.version_id.label("record_id"),
            source.canonical_source.label("canonical"),
            source.canonical_facts.label("facts"),
            source.published_at.label("published_at"),
            *(getattr(source, key).label(key) for key in fields),
        ).where(
            source.owner_id == auth.owner_id,
            source.version_id.in_(item.source.id for item in page.sources),
        ),
        select(
            literal("event"),
            event.revision_id,
            event.canonical_event,
            literal(None, LargeBinary()),
            literal(None, UTCDateTime()),
            *(literal(None, Text()) for _ in fields),
        ).where(
            event.owner_id == auth.owner_id,
            event.account_id == auth.account_id,
            event.revision_id.in_(item.revision.id for item in page.candidates),
        ),
    )
    rows = session.execute(statement).mappings().all()
    if len(rows) != len(page.sources) + len(page.candidates):
        raise research_error()
    source_metadata = {item.source.id: item for item in page.sources}
    decoded: dict[UUID, tuple[ResearchSourceVersion, ResearchSourceFacts]] = {}
    event_bytes: dict[UUID, bytes] = {}
    for row in rows:
        identifier = row["record_id"]
        if row["record_kind"] == "event":
            if identifier in event_bytes:
                raise research_error()
            event_bytes[identifier] = row["canonical"]
            continue
        if (
            row["record_kind"] != "source"
            or identifier not in source_metadata
            or identifier in decoded
        ):
            raise research_error()
        metadata = source_metadata[identifier]
        header = metadata.source
        payload = ResearchSourcePayloadModel(
            owner_id=auth.owner_id,
            version_id=identifier,
            canonical_source=row["canonical"],
            canonical_facts=row["facts"],
            published_at=row["published_at"],
            **{field: row[field] for field in fields},
        )
        value = research_source_version_from_json(
            payload.canonical_source, expected_digest=header.content_digest
        )
        facts = ResearchSourceStore.source_facts(payload)
        if (
            research_record_bytes(facts) != payload.canonical_facts
            or research_record_digest(facts) != header.facts_digest
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
                header.id,
                header.owner_id,
                header.source_id,
                header.provider_id,
                header.entity_id,
                header.license_version_id,
                header.capability,
                header.adapter_version,
                header.request_digest,
                header.facts_digest,
                header.observed_at,
                header.first_known_at,
                header.source_cutoff_at,
                header.retained_at,
                header.expires_at,
                header.synthetic,
            )
            or value.license != license_view(metadata.pinned)
            or facts.kind != header.capability
        ):
            raise research_error()
        decoded[identifier] = value, facts
    result: dict[UUID, ResearchEventRevision] = {}
    for candidate in page.candidates:
        revision_header, head = candidate.revision, candidate.event
        if revision_header.id not in event_bytes:
            raise research_error()
        event_value = research_event_from_json(
            event_bytes[revision_header.id], expected_digest=revision_header.content_digest
        )
        citations = []
        for _, citation_row in candidate.members:
            source_value, facts = decoded[citation_row.source_version_id]
            citation_value = ResearchCitation(
                citation_id=citation_row.id,
                source=source_value,
                provider_event_key=citation_row.provider_event_key,
                entity_id=citation_row.entity_id,
                facts_digest=citation_row.facts_digest,
                published_at=citation_row.published_at,
            )
            if (
                facts != event_value.facts
                or citation_value.content_digest != citation_row.content_digest
                or source_value.content_digest != citation_row.source_version_digest
            ):
                raise research_error()
            citations.append(citation_value)
        if (
            tuple(citations) != event_value.citations
            or (
                event_value.event_id,
                event_value.revision_id,
                event_value.revision,
                event_value.previous_revision_id,
                event_value.owner_id,
                event_value.entity_id,
                event_value.provider_id,
                event_value.provider_event_key,
                event_value.created_at,
                event_value.facts.kind,
                event_value.facts.published_at,
                research_record_digest(event_value.facts),
                research_semantic_fact_digest(event_value),
                research_material_digest(event_value),
            )
            != (
                revision_header.event_id,
                revision_header.id,
                revision_header.revision,
                revision_header.previous_revision_id,
                revision_header.owner_id,
                revision_header.entity_id,
                head.provider_id,
                head.provider_event_key,
                revision_header.created_at,
                head.kind,
                revision_header.published_at,
                revision_header.facts_digest,
                revision_header.semantic_digest,
                revision_header.material_digest,
            )
            or revision_header.visible_at != max(c.source.first_known_at for c in citations)
        ):
            raise research_error()
        result[revision_header.id] = event_value
    return result


def research_notes_for_entities(
    session: Session,
    auth: ReportAuthorization,
    entities: tuple[UUID, ...],
) -> dict[UUID, tuple[ResearchNoteRevision, ...]]:
    if not entities:
        return {}
    header, head, payload, member = (
        ResearchNoteRevisionModel,
        ResearchNoteModel,
        ResearchNotePayloadModel,
        ResearchNoteCitationModel,
    )
    selected = (
        select(header.id, head.created_at.label("sort_at"), head.id.label("sort_id"))
        .join(
            head,
            (head.id == header.note_id) & (head.revision == header.revision),
        )
        .where(
            header.owner_id == auth.owner_id,
            header.account_id == auth.account_id,
            head.entity_id.in_(entities),
            header.sealed.is_(True),
        )
        .limit(513)
        .cte("research_page_notes")
    )
    names = (
        "record_kind",
        "revision_id",
        "note_id",
        "revision",
        "previous_revision_id",
        "entity_id",
        "actor_id",
        "created_at",
        "content_digest",
        "citation_count",
        "sort_at",
        "sort_id",
        "canonical",
        "title",
        "note",
        "thesis",
        "risks",
        "catalysts",
        "break_conditions",
        "member_id",
        "citation_id",
        "source_version_id",
        "source_version_digest",
        "citation_digest",
        "ordinal",
    )
    note_values = (
        literal("note"),
        header.id,
        header.note_id,
        header.revision,
        header.previous_revision_id,
        header.entity_id,
        header.actor_id,
        header.created_at,
        header.content_digest,
        header.citation_count,
        selected.c.sort_at,
        selected.c.sort_id,
        payload.canonical_note,
        payload.title,
        payload.note,
        payload.thesis,
        payload.risks,
        payload.catalysts,
        payload.break_conditions,
        literal(None, Uuid()),
        literal(None, Uuid()),
        literal(None, Uuid()),
        literal(None, Text()),
        literal(None, Text()),
        literal(None, Integer()),
    )
    member_values = (
        literal("citation"),
        member.revision_id,
        literal(None, Uuid()),
        literal(None, Integer()),
        literal(None, Uuid()),
        literal(None, Uuid()),
        literal(None, Uuid()),
        literal(None, UTCDateTime()),
        literal(None, Text()),
        literal(None, Integer()),
        literal(None, UTCDateTime()),
        literal(None, Uuid()),
        literal(None, LargeBinary()),
        *(literal(None, Text()) for _ in range(6)),
        member.id,
        member.citation_id,
        member.source_version_id,
        member.source_version_digest,
        member.citation_digest,
        member.ordinal,
    )
    statement = union_all(
        select(*(value.label(name) for name, value in zip(names, note_values, strict=True)))
        .join(selected, selected.c.id == header.id)
        .outerjoin(
            payload,
            (payload.revision_id == header.id)
            & (payload.owner_id == auth.owner_id)
            & (payload.account_id == auth.account_id),
        ),
        select(*member_values)
        .join(selected, selected.c.id == member.revision_id)
        .where(member.owner_id == auth.owner_id, member.account_id == auth.account_id),
    )
    rows = session.execute(statement).mappings().all()
    notes = [row for row in rows if row["record_kind"] == "note"]
    if len(notes) > 512 or len(rows) > 512 * 65:
        raise research_error()
    grouped: dict[UUID, list[ResearchNoteCitationModel]] = defaultdict(list)
    for row in rows:
        if row["record_kind"] == "note":
            continue
        if row["record_kind"] != "citation":
            raise research_error()
        grouped[row["revision_id"]].append(
            ResearchNoteCitationModel(
                id=row["member_id"],
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                revision_id=row["revision_id"],
                citation_id=row["citation_id"],
                source_version_id=row["source_version_id"],
                source_version_digest=row["source_version_digest"],
                citation_digest=row["citation_digest"],
                ordinal=row["ordinal"],
            )
        )
    result: dict[UUID, list[ResearchNoteRevision]] = defaultdict(list)
    for row in sorted(notes, key=lambda value: (value["sort_at"], value["sort_id"]), reverse=True):
        if row["canonical"] is None:
            raise research_error()
        revision = ResearchNoteRevisionModel(
            id=row["revision_id"],
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            note_id=row["note_id"],
            revision=row["revision"],
            previous_revision_id=row["previous_revision_id"],
            entity_id=row["entity_id"],
            actor_id=row["actor_id"],
            created_at=row["created_at"],
            content_digest=row["content_digest"],
            citation_count=row["citation_count"],
            sealed=True,
        )
        copied = ResearchNotePayloadModel(
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            revision_id=revision.id,
            canonical_note=row["canonical"],
            **{
                field: row[field]
                for field in ("title", "note", "thesis", "risks", "catalysts", "break_conditions")
            },
        )
        citations = tuple(sorted(grouped[revision.id], key=lambda item: item.ordinal))
        result[revision.entity_id].append(research_note_record(revision, copied, citations))
    return {entity: tuple(values) for entity, values in result.items()}
