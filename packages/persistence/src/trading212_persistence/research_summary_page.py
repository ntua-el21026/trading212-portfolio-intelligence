"""Whole-request bounded research summary over exact retained X-ray and source facts."""

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Table, column, func, select, union_all, values
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from trading212_application import research as app
from trading212_application.queries import cursor_binding
from trading212_domain.research import MAX_RESEARCH_RESPONSE_BYTES
from trading212_domain.research_facts import copy_research_portfolio_facts
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.serialization import canonical_json

from .research_item_store import ResearchItemStore
from .research_models import ResearchItemModel
from .research_page_authorization import ResearchPageAuthority
from .research_permissions import require_research_capabilities
from .research_source_store import research_error
from .research_summary_payloads import research_event_payloads, research_notes_for_entities
from .research_summary_query import ResearchCandidate, research_candidate_page
from .research_xray_read import ResearchXrayRead, finish_research_xray, read_research_xray


def _bind_items(
    session: Session,
    authority: ResearchPageAuthority,
    basis: ResearchXrayRead,
    candidates: tuple[ResearchCandidate, ...],
    *,
    cutoff: datetime,
    now: datetime,
) -> dict[UUID, UUID]:
    if not candidates:
        return {}
    auth, pin = authority.auth, basis.pin
    table = cast(Table, ResearchItemModel.__table__)
    rows: list[dict[str, object]] = []
    for candidate in candidates:
        revision = candidate.revision
        identity = sha256(
            b"t212pi.research.item.v1\0"
            + canonical_json(
                (auth.owner_id, auth.account_id, revision.id, revision.content_digest, pin, cutoff),
            ).encode()
        ).hexdigest()
        expiry = (
            revision.expires_at
            if basis.deadline is None
            else min(revision.expires_at, basis.deadline)
        )
        if expiry <= now:
            raise research_error()
        rows.append(
            dict(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                revision_id=revision.id,
                revision_digest=revision.content_digest,
                entity_id=revision.entity_id,
                xray_run_id=pin.run_id,
                xray_input_id=basis.input_id,
                snapshot_id=pin.snapshot_id,
                xray_input_digest=pin.input_digest,
                xray_result_digest=pin.result_digest,
                xray_pin_digest=research_record_digest(pin),
                source_cutoff_at=cutoff,
                selection_digest=identity,
                expires_at=expiry,
                created_at=now,
            )
        )
    names = tuple(rows[0])
    requested = (
        values(
            *(column(name, table.c[name].type) for name in names), name="research_requested_items"
        )
        .data(
            [tuple(row[name] for name in names) for row in rows],
        )
        .cte("research_requested_items")
    )
    existing = (
        select(table)
        .join(requested, requested.c.selection_digest == table.c.selection_digest)
        .where(
            table.c.owner_id == auth.owner_id,
            table.c.account_id == auth.account_id,
        )
        .cte("research_existing_items")
    )
    missing = (
        select(requested)
        .where(
            ~select(existing.c.id)
            .where(
                existing.c.selection_digest == requested.c.selection_digest,
            )
            .exists()
        )
        .cte("research_missing_items")
    )
    actual = (
        select(func.count())
        .select_from(table)
        .where(table.c.owner_id == auth.owner_id)
        .scalar_subquery()
    )
    needed = select(func.count()).select_from(missing).scalar_subquery()
    inserted = (
        insert(table)
        .from_select(
            names,
            select(*(missing.c[name] for name in names)).where(
                actual + needed <= 10000,
            ),
        )
        .on_conflict_do_nothing(index_elements=["owner_id", "account_id", "selection_digest"])
        .returning(*table.c)
        .cte("research_inserted_items")
    )
    # Immutable existing identities are selected first; no attempted duplicate INSERT
    # reaches admission triggers or consumes an item quota. The owner lock serializes
    # concurrent requests, and the SQL guard independently checks the immutable cap.
    statement = union_all(select(*inserted.c), select(*existing.c))
    stored = tuple(session.scalars(select(ResearchItemModel).from_statement(statement)))
    if len(stored) != len(rows):
        raise research_error(app.ResearchErrorCode.RATE_LIMITED)
    expected = {row["selection_digest"]: row for row in rows}
    result: dict[UUID, UUID] = {}
    for row in stored:
        wanted = expected.get(row.selection_digest)
        if wanted is None or any(
            getattr(row, name) != wanted[name]
            for name in names
            if name not in ("id", "created_at", "expires_at")
        ):
            raise research_error()
        if row.expires_at <= now or row.expires_at > cast(datetime, wanted["expires_at"]):
            raise research_error()
        result[row.revision_id] = row.id
    return result


def research_summary_page(
    store: ResearchItemStore,
    session: Session,
    authority: ResearchPageAuthority,
    query: app.ResearchSummaryQuery,
) -> app.ResearchSummary:
    auth = authority.auth
    if query.source_cutoff_at > store._now():
        raise research_error(app.ResearchErrorCode.VALIDATION_FAILED)
    binding = cursor_binding(
        auth.owner_id,
        auth.account_id,
        auth.issuer,
        auth.subject,
        authority.epoch,
        query.xray_run_id,
        query.source_cutoff_at,
        query.entity_id,
        query.event_kind,
        query.review_state,
        query.limit,
    )
    resource = "research_items.bounded.v1"
    after = None
    expected_fingerprint = None
    if query.cursor is not None:
        cutoff, key = store._cursors.decode(
            query.cursor, resource=resource, binding=binding, key_size=8
        )
        after, expected_fingerprint = key[:7], key[7]
        if cutoff != query.source_cutoff_at:
            raise research_error(app.ResearchErrorCode.CURSOR_INVALID)
    # Scope/filter/epoch cursor validation precedes the first private X-ray decode.
    basis = read_research_xray(session, auth, query.xray_run_id, now=store._now())
    page = research_candidate_page(
        session,
        auth,
        query,
        basis.result,
        authority=store._research_capabilities,
        now=store._now(),
        after=after,
    )
    if expected_fingerprint is not None and expected_fingerprint != page.fingerprint:
        raise research_error(app.ResearchErrorCode.CURSOR_INVALID)
    signature = page.signature()
    requests = tuple(item.request for item in page.sources)
    require_research_capabilities(
        store._research_capabilities, session, requests=requests, now=store._now()
    )
    events = research_event_payloads(session, auth, page)
    notes = research_notes_for_entities(
        session, auth, tuple(dict.fromkeys(item.revision.entity_id for item in page.candidates))
    )
    template = app.ResearchSummary(
        pin=basis.pin,
        source_cutoff_at=query.source_cutoff_at,
        items=(),
        next_cursor=None,
        limit=query.limit,
        total=page.total,
        unknown_exposure_total=page.unknown,
    )
    items: list[app.ResearchItemView] = []
    selected: list[ResearchCandidate] = []
    next_cursor = None
    for ordinal, candidate in enumerate(page.candidates):
        revision = candidate.revision
        preview = app.preview_research_portfolio(
            copy_research_portfolio_facts(basis.pin, basis.result, revision.entity_id)
        )
        while len(canonical_json(preview).encode()) > MAX_RESEARCH_RESPONSE_BYTES // 2:
            if not preview.warnings:
                raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
            preview = replace(
                preview,
                warnings=preview.warnings[:-1],
                warnings_omitted=preview.warnings_omitted + 1,
            )
        owned_notes = notes.get(revision.entity_id, ())
        item = app.ResearchItemView(
            item_id=uuid4(),
            source_cutoff_at=query.source_cutoff_at,
            source=events[revision.id],
            portfolio=preview,
            owner_revisions_omitted=len(owned_notes),
            review=None if candidate.review is None else store._review_view(candidate.review),
        )
        kept = []
        used = len(canonical_json(item).encode())
        for note in owned_notes[:64]:
            cost = len(canonical_json(note).encode()) + 1
            if used + cost + 4096 > MAX_RESEARCH_RESPONSE_BYTES:
                break
            kept.append(note)
            used += cost
        item = replace(
            item, owner_revisions=tuple(kept), owner_revisions_omitted=len(owned_notes) - len(kept)
        )
        more = ordinal + 1 < page.remaining
        cursor = (
            store._cursors.encode(
                resource=resource,
                binding=binding,
                read_cutoff=query.source_cutoff_at,
                key=(*candidate.key, page.fingerprint),
            )
            if more
            else None
        )
        projected = canonical_json(
            dict(
                pin=basis.pin,
                source_cutoff_at=query.source_cutoff_at,
                items=(*items, item),
                next_cursor=cursor,
                limit=query.limit,
                total=page.total,
                unknown_exposure_total=page.unknown,
                method=template.method,
                method_version=template.method_version,
                schema_version=template.schema_version,
            )
        ).encode()
        if len(projected) > MAX_RESEARCH_RESPONSE_BYTES:
            if not items:
                raise research_error(app.ResearchErrorCode.INPUT_BOUND_EXCEEDED)
            break
        items.append(item)
        selected.append(candidate)
        next_cursor = cursor
    identifiers = _bind_items(
        session, authority, basis, tuple(selected), cutoff=query.source_cutoff_at, now=store._now()
    )
    items = [replace(item, item_id=identifiers[item.source.revision_id]) for item in items]
    # Recompute only eligibility/count/rank from current metadata, not financial
    # calculations. A capability or original-right change cannot leak stale counts.
    final_page = research_candidate_page(
        session,
        auth,
        query,
        basis.result,
        authority=store._research_capabilities,
        now=store._now(),
        after=after,
    )
    if final_page.signature() != signature:
        raise research_error()
    require_research_capabilities(
        store._research_capabilities,
        session,
        requests=tuple(item.request for item in final_page.sources),
        now=store._now(),
    )
    finish_research_xray(session, auth, basis, now=store._now())
    return replace(template, items=tuple(items), next_cursor=next_cursor)
