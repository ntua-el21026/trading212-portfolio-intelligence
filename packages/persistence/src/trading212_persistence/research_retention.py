"""Bounded metadata-only research expiry and owner erasure using the shared budget."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Table, literal, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from trading212_application.research import ResearchServiceError
from trading212_domain.research import ResearchEventKind
from trading212_domain.sources import SourceUse

from .research_models import (
    ResearchEventCitationModel,
    ResearchEventPayloadModel,
    ResearchNotePayloadModel,
    ResearchOwnerErasureModel,
    ResearchRetentionCursorModel,
    ResearchRetentionModel,
    ResearchSourceOriginModel,
    ResearchSourcePayloadModel,
    ResearchSourceVersionModel,
)
from .research_permissions import ResearchCapabilityAuthority, require_research_capability
from .research_retention_costs import (
    RESEARCH_CURSOR_RESERVE,
    RESEARCH_MARKER_RESERVE,
    RESEARCH_OWNER_MARKER_RESERVE,
)
from .source_models import MarketDataProviderModel, ProviderLicenseVersionModel
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows
from .source_store import license_view

SOURCE_COLUMNS = (
    "canonical_source",
    "canonical_facts",
    "publisher",
    "title",
    "summary",
    "company_name",
    "description",
    "kind",
    "published_at",
    "publication_reason",
)
EVENT_COLUMNS = ("canonical_event",)
NOTE_COLUMNS = (
    "canonical_note",
    "title",
    "note",
    "thesis",
    "risks",
    "catalysts",
    "break_conditions",
)


def _charge(budget: SourcePurgeBudget, rows: int) -> None:
    if not budget.inspect(rows=rows):
        raise RuntimeError("Research retention metadata budget differs.")


def _owner(session: Session, owner: UUID) -> bool:
    return all(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{owner}"},
        )
        is True
        for namespace in ("sources", "xray", "historical", "premium", "research")
    )


def _restricted(
    session: Session,
    row: ResearchSourceVersionModel,
    *,
    at: datetime,
    authority: ResearchCapabilityAuthority | None,
    budget: SourcePurgeBudget,
) -> bool:
    """Original header clocks and current/pinned rights; never decode provider text."""
    _charge(budget, 4)
    origin = session.scalar(
        select(ResearchSourceOriginModel).where(
            ResearchSourceOriginModel.owner_id == row.owner_id,
            ResearchSourceOriginModel.id == row.origin_id,
        )
    )
    provider = session.scalar(
        select(MarketDataProviderModel).where(
            MarketDataProviderModel.owner_id == row.owner_id,
            MarketDataProviderModel.id == row.provider_id,
        )
    )
    pinned = session.scalar(
        select(ProviderLicenseVersionModel).where(
            ProviderLicenseVersionModel.owner_id == row.owner_id,
            ProviderLicenseVersionModel.id == row.license_version_id,
        )
    )
    current = session.scalar(
        select(ProviderLicenseVersionModel)
        .where(
            ProviderLicenseVersionModel.owner_id == row.owner_id,
            ProviderLicenseVersionModel.provider_id == row.provider_id,
            ProviderLicenseVersionModel.effective_at <= at,
        )
        .order_by(
            ProviderLicenseVersionModel.effective_at.desc(),
            ProviderLicenseVersionModel.version_number.desc(),
            ProviderLicenseVersionModel.id.desc(),
        )
        .limit(1)
    )
    if origin is None or provider is None or pinned is None or current is None or authority is None:
        return True
    if (
        provider.configuration_state != "configured"
        or row.effective_expires_at <= at
        or pinned.effective_at > at
        or pinned.retention_days is None
        or current.retention_days is None
    ):
        return True
    licenses = (license_view(pinned), license_view(current))
    if any(
        not license.permits(use)
        for license in licenses
        for use in (SourceUse.STORE, SourceUse.DISPLAY)
    ):
        return True
    try:
        grant = require_research_capability(
            authority,
            session,
            owner_id=row.owner_id,
            provider_id=row.provider_id,
            entity_id=row.entity_id,
            capability=ResearchEventKind(row.capability),
            license_version_id=row.license_version_id,
            grant_id=row.capability_grant_id,
            grant_digest=row.capability_grant_digest,
            now=at,
            budget=budget,
        )
    except ResearchServiceError:
        return True
    deadline = min(
        row.expires_at,
        origin.expires_at,
        grant.expires_at,
        origin.original_retained_at
        + timedelta(days=min(30, pinned.retention_days, current.retention_days)),
    )
    return (
        row.effective_expires_at > deadline
        or at >= deadline
        or grant.effective_at > row.retained_at
        or (origin.entity_id, origin.capability, origin.facts_digest)
        != (row.entity_id, row.capability, row.facts_digest)
    )


def _purge_event_copies(
    session: Session, row: ResearchSourceVersionModel, *, budget: SourcePurgeBudget
) -> bool:
    """Walk only indexed pending copies; completed citation audit rows never scan."""
    member = ResearchEventCitationModel
    event = cast(Table, ResearchEventPayloadModel.__table__)
    while budget.metadata_limit:
        _charge(budget, 1)
        revision = session.scalar(
            select(member.revision_id)
            .where(
                member.owner_id == row.owner_id,
                member.source_version_id == row.id,
                member.copy_pending.is_(True),
            )
            .order_by(member.revision_id, member.id)
            .limit(1)
        )
        if revision is None:
            return True
        result = purge_payload_rows(
            session,
            event,
            (event.c.owner_id == row.owner_id) & (event.c.revision_id == revision),
            payload_columns=EVENT_COLUMNS,
            delete_rows=True,
            budget=budget,
        )
        if not result.complete:
            return False
        if result.removed_rows != 1:
            # A pending member without its physical payload violates the closed
            # trigger lifecycle. Never loop forever or silently clear its proof.
            raise RuntimeError("Research pending event copy differs.")
    return False


def _purge_version(
    session: Session,
    row: ResearchSourceVersionModel,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    authority: ResearchCapabilityAuthority | None,
    erase: bool,
) -> bool:
    if budget.metadata_limit < 5 or not budget.enter_capture("research", row.id):
        return False
    _charge(budget, 1)
    marker = session.scalar(
        select(ResearchRetentionModel)
        .where(
            ResearchRetentionModel.owner_id == row.owner_id,
            ResearchRetentionModel.source_version_id == row.id,
        )
        .with_for_update()
    )
    if marker is not None:
        if marker.completed_at is not None:
            return True
    else:
        if not erase and not _restricted(session, row, at=at, authority=authority, budget=budget):
            return True
        if budget.metadata_limit < RESEARCH_MARKER_RESERVE:
            return False
        _charge(budget, RESEARCH_MARKER_RESERVE)
        marker = ResearchRetentionModel(
            id=uuid4(),
            owner_id=row.owner_id,
            source_version_id=row.id,
            reason="owner_erasure"
            if erase
            else ("source_expired" if row.effective_expires_at <= at else "source_restricted"),
            created_at=at,
            completed_at=None,
        )
        session.add(marker)
        session.flush()
    if not _purge_event_copies(session, row, budget=budget):
        return False
    source = cast(Table, ResearchSourcePayloadModel.__table__)
    if not purge_payload_rows(
        session,
        source,
        (source.c.owner_id == row.owner_id) & (source.c.version_id == row.id),
        payload_columns=SOURCE_COLUMNS,
        delete_rows=True,
        budget=budget,
    ).complete:
        return False
    if budget.metadata_limit < RESEARCH_MARKER_RESERVE:
        return False
    _charge(budget, RESEARCH_MARKER_RESERVE)
    marker.completed_at = at
    session.flush()
    # Trigger-owned charges refund only physically removed copied bytes. Immutable
    # item/citation/receipt/lifetime identities remain; completion proves no copies.
    return True


def expire_research_payloads(
    session: Session,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    capability_authority: ResearchCapabilityAuthority | None,
    owner: UUID | None = None,
    erase: bool = False,
) -> bool:
    """Advance a durable raw-header keyset, charging completed and empty prefixes.

    The fixed global or exact-owner watermark covers every visited immutable
    header. No payload/marker EXISTS predicate can hide discarded physical work.
    Owner erasure does not advance past a partially drained source. Global scans
    rotate past busy owners and revisit pending work in the next bounded sweep.
    """
    if erase and owner is None:
        raise ValueError("Research erasure requires an exact owner.")
    if budget.metadata_limit < RESEARCH_CURSOR_RESERVE + 6:
        return False
    _charge(budget, RESEARCH_CURSOR_RESERVE)
    key = "research" if owner is None else f"research:{owner}"
    session.execute(
        insert(ResearchRetentionCursorModel)
        .values(
            key=key,
            scope_owner_id=owner,
            last_owner_id=None,
            last_version_id=None,
            updated_at=at,
        )
        .on_conflict_do_nothing(index_elements=["key"])
    )
    cursor = session.scalar(
        select(ResearchRetentionCursorModel)
        .where(ResearchRetentionCursorModel.key == key)
        .with_for_update(skip_locked=True)
    )
    if cursor is None:
        return False
    if cursor.scope_owner_id != owner:
        raise RuntimeError("Research retention cursor scope differs.")
    source = ResearchSourceVersionModel
    query = select(source.owner_id, source.id)
    if owner is not None:
        query = query.where(source.owner_id == owner)
    if cursor.last_owner_id is not None:
        query = query.where(
            tuple_(source.owner_id, source.id)
            > tuple_(literal(cursor.last_owner_id), literal(cursor.last_version_id))
        )
    limit = min(100, max(1, budget.metadata_limit // 6))
    identifiers = session.execute(query.order_by(source.owner_id, source.id).limit(limit)).all()
    _charge(budget, len(identifiers))
    complete = True
    consumed = 0
    last_owner = cursor.last_owner_id
    last_version = cursor.last_version_id
    for source_owner, identifier in identifiers:
        if budget.metadata_limit < 6:
            complete = False
            break
        drained = False
        if _owner(session, source_owner):
            _charge(budget, 1)
            row = session.scalar(
                select(source)
                .where(source.owner_id == source_owner, source.id == identifier)
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("Research source identity disappeared.")
            drained = not row.sealed or _purge_version(
                session, row, at=at, budget=budget, authority=capability_authority, erase=erase
            )
        if not drained:
            complete = False
            if owner is not None:
                break
        consumed += 1
        last_owner, last_version = source_owner, identifier
    # Keep pending updates out of autoflush during per-source SQL. One precharged
    # final mutation also covers the exact cursor FK probes, including empty seeks.
    reached_end = consumed == len(identifiers) and len(identifiers) < limit
    cursor.last_owner_id = None if reached_end else last_owner
    cursor.last_version_id = None if reached_end else last_version
    cursor.updated_at = at
    session.flush()
    return complete and reached_end


def purge_owner_research_payloads(
    session: Session, owner: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    if budget.metadata_limit < 1 + RESEARCH_OWNER_MARKER_RESERVE or not _owner(session, owner):
        return False
    _charge(budget, 1)
    marker = session.scalar(
        select(ResearchOwnerErasureModel)
        .where(ResearchOwnerErasureModel.owner_id == owner)
        .with_for_update()
    )
    if marker is None:
        _charge(budget, RESEARCH_OWNER_MARKER_RESERVE)
        marker = ResearchOwnerErasureModel(owner_id=owner, created_at=at, completed_at=None)
        session.add(marker)
        session.flush()
    if marker.completed_at is not None:
        return True
    notes = cast(Table, ResearchNotePayloadModel.__table__)
    if not purge_payload_rows(
        session,
        notes,
        notes.c.owner_id == owner,
        payload_columns=NOTE_COLUMNS,
        delete_rows=True,
        budget=budget,
    ).complete:
        return False
    if not expire_research_payloads(
        session, at=at, budget=budget, capability_authority=None, owner=owner, erase=True
    ):
        return False
    if budget.metadata_limit < 3 + RESEARCH_OWNER_MARKER_RESERVE:
        return False
    for model in (ResearchSourcePayloadModel, ResearchEventPayloadModel, ResearchNotePayloadModel):
        _charge(budget, 1)
        exists_id = session.scalar(select(model.id).where(model.owner_id == owner).limit(1))
        if exists_id is not None:
            return False
    _charge(budget, RESEARCH_OWNER_MARKER_RESERVE)
    marker.completed_at = at
    session.flush()
    return True
