"""Fixed-query immutable note pages with whole-record byte-bound packing."""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, literal, select, tuple_
from sqlalchemy.orm import InstrumentedAttribute, Session
from trading212_application import research as app
from trading212_application.queries import CursorCodec, CursorValidationError, cursor_binding
from trading212_application.views import Page
from trading212_domain.research import MAX_RESEARCH_RESPONSE_BYTES
from trading212_domain.research_notes import ResearchNoteRevision
from trading212_domain.serialization import canonical_json

from .research_models import (
    ResearchNoteCitationModel,
    ResearchNoteModel,
    ResearchNotePayloadModel,
    ResearchNoteRevisionModel,
)
from .research_note_record import research_note_record
from .research_page_authorization import ResearchPageAuthority
from .research_source_store import research_error


def research_note_page(
    session: Session,
    authority: ResearchPageAuthority,
    query: app.ResearchPageQuery,
    *,
    now: datetime,
    cursors: CursorCodec,
    note_id: UUID | None = None,
) -> Page[ResearchNoteRevision]:
    auth = authority.auth
    resource = (
        "research_notes.bounded.v1" if note_id is None else "research_note_versions.bounded.v1"
    )
    binding = cursor_binding(
        auth.owner_id,
        auth.account_id,
        auth.issuer,
        auth.subject,
        authority.epoch,
        note_id,
        query.limit,
    )
    cutoff = now
    key: tuple[str, ...] | None = None
    if query.cursor is not None:
        cutoff, key = cursors.decode(query.cursor, resource=resource, binding=binding, key_size=2)
    row, head, payload, member = (
        ResearchNoteRevisionModel,
        ResearchNoteModel,
        ResearchNotePayloadModel,
        ResearchNoteCitationModel,
    )
    eligible = select(row.id).where(
        row.owner_id == auth.owner_id,
        row.account_id == auth.account_id,
        row.sealed.is_(True),
        row.created_at <= cutoff,
    )
    order_value: InstrumentedAttribute[datetime] | InstrumentedAttribute[int]
    if note_id is None:
        eligible = eligible.join(head, (head.id == row.note_id) & (head.revision == row.revision))
        order_value = head.created_at
    else:
        eligible = eligible.where(row.note_id == note_id)
        order_value = row.revision
    total = select(func.count()).select_from(eligible.subquery()).scalar_subquery()
    if key is not None:
        try:
            last_id = UUID(key[1])
            last_order: datetime | int
            if note_id is None:
                last_order = datetime.fromisoformat(key[0])
                if (
                    last_order.tzinfo is None
                    or last_order.utcoffset() != UTC.utcoffset(last_order)
                    or last_order.isoformat() != key[0]
                ):
                    raise ValueError("invalid note cursor key")
            else:
                last_order = int(key[0])
                if str(last_order) != key[0] or not 1 <= last_order <= 512:
                    raise ValueError("invalid note cursor key")
            if str(last_id) != key[1]:
                raise ValueError("invalid note cursor key")
        except ValueError:
            raise CursorValidationError("invalid cursor") from None
        eligible = eligible.where(
            tuple_(order_value, row.id) < tuple_(literal(last_order), literal(last_id))
        )
    chosen = (
        eligible.add_columns(order_value.label("page_order"))
        .order_by(order_value.desc(), row.id.desc())
        .limit(query.limit + 1)
        .cte("research_note_page")
    )
    records = session.execute(
        select(row, payload, chosen.c.page_order, total)
        .join(
            chosen,
            chosen.c.id == row.id,
        )
        .outerjoin(
            payload,
            (payload.revision_id == row.id)
            & (payload.owner_id == auth.owner_id)
            & (payload.account_id == auth.account_id),
        )
        .order_by(chosen.c.page_order.desc(), row.id.desc())
    ).all()
    if not records:
        # The empty result needs one metadata count, but skips the citation query;
        # the complete authorized request keeps the same statement bound.
        exact_total = session.scalar(select(total)) or 0
        return Page(items=(), next_cursor=None, limit=query.limit, total=exact_total)
    identifiers = tuple(record[0].id for record in records)
    members = tuple(
        session.scalars(
            select(member)
            .where(
                member.owner_id == auth.owner_id,
                member.account_id == auth.account_id,
                member.revision_id.in_(identifiers),
            )
            .order_by(member.revision_id, member.ordinal)
            .limit(64 * (query.limit + 1) + 1)
        )
    )
    if len(members) > 64 * len(identifiers):
        raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
    grouped: dict[UUID, list[ResearchNoteCitationModel]] = defaultdict(list)
    for citation in members:
        grouped[citation.revision_id].append(citation)
    items: list[ResearchNoteRevision] = []
    next_cursor = None
    exact_total = records[0][3]
    for ordinal, (header, copied, page_order, _) in enumerate(records[: query.limit]):
        if copied is None:
            raise research_error(app.ResearchErrorCode.NOT_FOUND)
        item = research_note_record(header, copied, tuple(grouped[header.id]))
        more = ordinal + 1 < len(records)
        candidate_cursor = (
            cursors.encode(
                resource=resource,
                binding=binding,
                read_cutoff=cutoff,
                key=(
                    page_order.isoformat() if note_id is None else str(page_order),
                    str(header.id),
                ),
            )
            if more
            else None
        )
        candidate = Page(
            items=(*items, item), next_cursor=candidate_cursor, limit=query.limit, total=exact_total
        )
        if len(canonical_json(candidate).encode()) > MAX_RESEARCH_RESPONSE_BYTES:
            if not items:
                raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
            break
        items.append(item)
        next_cursor = candidate_cursor
    return Page(items=tuple(items), next_cursor=next_cursor, limit=query.limit, total=exact_total)
