"""Physical aggregate erasure with permanent markers and charged indexed progress."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Table, delete, func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from . import aggregation_models as m
from .source_retention import PayloadCopyCost, SourcePurgeBudget

# Every mutation includes the target, scoped root/marker probes, its exact indexed
# reverse FK probes, root/capacity updates and fixed trigger work. Financial
# deletion never invokes the complete-publication aggregate validator.
MUTATION_ROWS = 64
MARKER_ROWS = 32
CURSOR_ROWS = 4
_TABLES = (
    m.AggregateTransferModel,
    m.AggregateFlowModel,
    m.AggregateActivityEvidenceModel,
    m.AggregateCoverageModel,
    m.AggregateRevisionModel,
    m.AggregateAccountTotalModel,
    m.AggregateHoldingModel,
    m.AggregateComponentModel,
    m.AggregateFxModel,
    m.AggregateSnapshotModel,
    m.AggregateActivityPayloadModel,
    m.AggregateHoldingsPayloadModel,
    m.AggregateSourceModel,
)


def _owner(session: Session, owner: UUID, budget: SourcePurgeBudget) -> bool:
    if not budget.inspect(rows=5):
        return False
    return all(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{owner}"},
        )
        is True
        for namespace in ("sources", "xray", "historical", "premium", "aggregate")
    )


def _drain(
    session: Session,
    root: m.AggregateRunModel,
    at: datetime,
    budget: SourcePurgeBudget,
    *,
    reason: str,
    source: UUID | None = None,
) -> bool:
    if (
        not budget.enter_run("aggregate", root.id)
        or not budget.enter_capture("aggregate", root.id)
        or not budget.inspect(rows=1)
    ):
        return False
    marker = session.scalar(
        select(m.AggregateRetentionModel).where(
            m.AggregateRetentionModel.owner_id == root.owner_id,
            m.AggregateRetentionModel.run_id == root.id,
        )
    )
    if marker is None:
        if not budget.inspect(rows=MARKER_ROWS):
            return False
        marker = m.AggregateRetentionModel(
            id=uuid4(),
            owner_id=root.owner_id,
            run_id=root.id,
            reason=reason,
            source_fx_snapshot_id=source,
            source_evidence_id=None,
            completed_at=None,
            created_at=at,
        )
        session.add(marker)
        session.flush()
    if marker.completed_at is not None:
        return True
    for model in _TABLES:
        table = cast(Table, model.__table__)
        while budget.rows_inspected >= MUTATION_ROWS + 2 and budget.rows_removed:
            if not budget.inspect(rows=1):
                return False
            limit = min(
                512 // MUTATION_ROWS,
                budget.rows_removed,
                budget.rows_inspected // (MUTATION_ROWS + 2),
            )
            rows = session.execute(
                select(model.id, func.aggregate_row_cost(table.name, model.id))
                .where(model.owner_id == root.owner_id, model.run_id == root.id)
                .order_by(model.id)
                .limit(limit)
            ).all()
            if not budget.inspect(rows=2 * len(rows)):
                raise RuntimeError("Aggregate cleanup selection exceeded its allowance.")
            if not rows:
                break
            allowed = budget.reserve_clear_batch(
                tuple(
                    PayloadCopyCost(
                        row_id=row[0],
                        payload_bytes=row[1],
                        inspection_rows=MUTATION_ROWS,
                        payload_inspections=2,
                    )
                    for row in rows
                )
            )
            if not allowed:
                return False
            session.execute(
                delete(model).where(
                    model.owner_id == root.owner_id, model.run_id == root.id, model.id.in_(allowed)
                )
            )
            if model is m.AggregateSourceModel:
                # The final source-row mutation allowance also includes this
                # fixed completion probe and marker update. Finish atomically
                # with the last physical copy: zero-byte roots leave the indexed
                # expiry set immediately and cannot be rediscovered next call.
                session.refresh(root)
                if not (root.financial_rows or root.retained_bytes or root.reserved_bytes):
                    marker.completed_at = at
                    session.flush()
                    return True
            if len(allowed) != len(rows):
                return False
        else:
            return False
    if not budget.inspect(rows=MARKER_ROWS):
        return False
    session.refresh(root)
    if root.financial_rows or root.retained_bytes or root.reserved_bytes:
        return False
    marker.completed_at = at
    session.flush()
    return True


def purge_aggregate_source_copies(
    session: Session,
    owner: UUID,
    kind: str,
    source_id: UUID,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    if kind != "fx":
        return True
    if not _owner(session, owner, budget):
        return False
    while budget.rows_inspected >= MARKER_ROWS + MUTATION_ROWS + 4 and budget.rows_removed:
        if not budget.inspect(rows=2):
            return False
        root = session.scalar(
            select(m.AggregateRunModel)
            .join(
                m.AggregateSourceModel,
                (m.AggregateSourceModel.owner_id == m.AggregateRunModel.owner_id)
                & (m.AggregateSourceModel.run_id == m.AggregateRunModel.id),
            )
            .where(
                m.AggregateSourceModel.owner_id == owner,
                m.AggregateSourceModel.source_kind == "fx",
                m.AggregateSourceModel.source_id == source_id,
            )
            .order_by(m.AggregateSourceModel.run_id)
            .limit(1)
        )
        if root is None:
            return True
        if not _drain(session, root, at, budget, reason="source", source=source_id):
            return False
    return False


def expire_aggregate_payloads(
    session: Session,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    owner: UUID | None = None,
    erase: bool = False,
) -> bool:
    key = "aggregate" if owner is None else f"aggregate:{owner}"
    if not budget.inspect(rows=CURSOR_ROWS):
        return False
    if (
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "retention:" + key},
        )
        is not True
    ):
        return False
    session.execute(
        insert(m.AggregateRetentionCursorModel)
        .values(
            key=key,
            owner_id=owner,
            last_owner_id=None,
            last_run_id=None,
            last_source_id=None,
            updated_at=at,
        )
        .on_conflict_do_nothing()
    )
    cursor = session.get(m.AggregateRetentionCursorModel, key, with_for_update=True)
    if cursor is None:
        raise RuntimeError("Aggregate retention cursor is absent.")
    while budget.rows_inspected >= MARKER_ROWS + MUTATION_ROWS + CURSOR_ROWS + 10:
        if not budget.inspect(rows=1):
            return False
        query = select(m.AggregateRunModel).where(
            m.AggregateRunModel.sealed, m.AggregateRunModel.retained_bytes > 0
        )
        if owner is not None:
            query = query.where(m.AggregateRunModel.owner_id == owner)
        if cursor.last_run_id is not None:
            position = tuple_(m.AggregateRunModel.owner_id, m.AggregateRunModel.id)
            key_position = (cursor.last_owner_id, cursor.last_run_id)
            query = query.where(
                position >= key_position
                if cursor.last_source_id is not None
                else position > key_position
            )
        root = session.scalar(
            query.order_by(m.AggregateRunModel.owner_id, m.AggregateRunModel.id).limit(1)
        )
        if root is None:
            if not budget.inspect(rows=CURSOR_ROWS):
                return False
            cursor.last_owner_id = cursor.last_run_id = cursor.last_source_id = None
            cursor.updated_at = at
            session.flush()
            return True
        if not _owner(session, root.owner_id, budget):
            if not budget.inspect(rows=CURSOR_ROWS):
                return False
            cursor.last_owner_id, cursor.last_run_id, cursor.last_source_id = (
                root.owner_id,
                root.id,
                None,
            )
            session.flush()
            continue
        if not budget.inspect(rows=1):
            return False
        marker = session.scalar(
            select(m.AggregateRetentionModel).where(
                m.AggregateRetentionModel.owner_id == root.owner_id,
                m.AggregateRetentionModel.run_id == root.id,
            )
        )
        source = None
        reason = "owner_erasure" if erase else "expired"
        restricted = erase or root.expires_at <= at or marker is not None
        if not restricted:
            # A physical source keyset persists across calls. Healthy prefixes
            # therefore cannot starve a later revoked licence, even with a tiny
            # caller allowance; never advance past a source before inspecting it.
            while budget.rows_inspected >= MARKER_ROWS + CURSOR_ROWS + 3:
                if not budget.inspect(rows=1):
                    return False
                query_source = select(
                    m.AggregateSourceModel.id, m.AggregateSourceModel.source_id
                ).where(
                    m.AggregateSourceModel.owner_id == root.owner_id,
                    m.AggregateSourceModel.run_id == root.id,
                    m.AggregateSourceModel.source_kind == "fx",
                )
                if cursor.last_run_id == root.id and cursor.last_source_id is not None:
                    query_source = query_source.where(
                        m.AggregateSourceModel.id > cursor.last_source_id
                    )
                witness = session.execute(
                    query_source.order_by(m.AggregateSourceModel.id).limit(1)
                ).one_or_none()
                if witness is None:
                    break
                if not budget.inspect(rows=MARKER_ROWS):
                    return False
                until = session.scalar(
                    text("SELECT aggregate_fx_until(:owner,:source,:at)"),
                    {"owner": root.owner_id, "source": witness[1], "at": at},
                )
                if until is None:
                    source, reason, restricted = witness[1], "source", True
                    break
                if not budget.inspect(rows=CURSOR_ROWS):
                    return False
                cursor.last_owner_id, cursor.last_run_id, cursor.last_source_id = (
                    root.owner_id,
                    root.id,
                    witness[0],
                )
                cursor.updated_at = at
                session.flush()
            else:
                return False
        if restricted:
            _drain(session, root, at, budget, reason=reason, source=source)
        if not budget.inspect(rows=CURSOR_ROWS):
            return False
        cursor.last_owner_id, cursor.last_run_id, cursor.last_source_id = (
            root.owner_id,
            root.id,
            None,
        )
        cursor.updated_at = at
        session.flush()
    return False


def purge_owner_aggregate_payloads(
    session: Session, owner: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    if not _owner(session, owner, budget) or not budget.inspect(rows=MARKER_ROWS):
        return False
    marker = session.get(m.AggregateOwnerErasureModel, owner)
    if marker is None:
        marker = m.AggregateOwnerErasureModel(owner_id=owner, created_at=at, completed_at=None)
        session.add(marker)
        session.flush()
    if marker.completed_at is not None:
        return True
    expire_aggregate_payloads(session, at=at, budget=budget, owner=owner, erase=True)
    if not budget.inspect(rows=1):
        return False
    if (
        session.scalar(
            select(m.AggregateRunModel.id)
            .where(
                m.AggregateRunModel.owner_id == owner,
                m.AggregateRunModel.retained_bytes + m.AggregateRunModel.reserved_bytes > 0,
            )
            .limit(1)
        )
        is not None
    ):
        return False
    while budget.rows_inspected >= MUTATION_ROWS + 2 and budget.rows_removed:
        if not budget.inspect(rows=1):
            return False
        row = session.execute(
            select(
                m.AggregateSelectionPayloadModel.id,
                func.octet_length(m.AggregateSelectionPayloadModel.payload),
            )
            .where(m.AggregateSelectionPayloadModel.owner_id == owner)
            .order_by(m.AggregateSelectionPayloadModel.id)
            .limit(1)
        ).one_or_none()
        if row is None:
            if not budget.inspect(rows=MARKER_ROWS):
                return False
            marker.completed_at = at
            session.flush()
            return True
        allowed = budget.reserve_clear_batch(
            (
                PayloadCopyCost(
                    row_id=row[0],
                    payload_bytes=row[1],
                    inspection_rows=MUTATION_ROWS,
                    payload_inspections=2,
                ),
            )
        )
        if not allowed:
            return False
        session.execute(
            delete(m.AggregateSelectionPayloadModel).where(
                m.AggregateSelectionPayloadModel.owner_id == owner,
                m.AggregateSelectionPayloadModel.id == row[0],
            )
        )
    return False
