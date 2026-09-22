"""Bounded exact metadata operations shared by Phase2 retention participants."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Table, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .phase2_retention_costs import PHASE2_MEMBERSHIP_MUTATION_ROWS
from .phase2_retention_models import (
    HistoricalRetainedSourceModel,
    Phase2RetentionSweepModel,
    SourceRetentionDispatchModel,
    XrayRetainedSourceModel,
)
from .source_retention import PayloadCopyCost, SourcePurgeBudget


def charge(budget: SourcePurgeBudget, rows: int = 1) -> bool:
    return budget.inspect(rows=rows)


def source_erasure_authorized(
    session: Session, owner: UUID, kind: str, source: UUID, at: datetime, budget: SourcePurgeBudget
) -> bool:
    # Exact header plus its original validated permanent work marker.
    if not charge(budget, 2):
        return False
    return (
        session.scalar(
            text("SELECT phase2_source_erasure_authorized(:owner,:kind,:source,:at)"),
            {"owner": owner, "kind": kind, "source": source, "at": at},
        )
        is True
    )


def drain_retained_sources(
    session: Session,
    owner: UUID,
    family: Literal["xray", "historical"],
    input_id: UUID,
    budget: SourcePurgeBudget,
) -> bool:
    """An exact marker and zero physical counters independently guard every DELETE."""
    model = XrayRetainedSourceModel if family == "xray" else HistoricalRetainedSourceModel
    while budget.rows_inspected >= PHASE2_MEMBERSHIP_MUTATION_ROWS + 2 and budget.rows_removed:
        if not charge(budget):
            return False
        columns = (
            (model.dependency_id,)
            if family == "xray"
            else (
                HistoricalRetainedSourceModel.dependency_id,
                HistoricalRetainedSourceModel.leaf_id,
            )
        )
        selected = session.execute(
            select(
                *columns,
                (func.octet_length(model.source_kind) + (64 if family == "xray" else 80)).label(
                    "payload_bytes"
                ),
            )
            .where(model.owner_id == owner, model.input_id == input_id)
            .order_by(*columns)
            .limit(
                min(
                    budget.rows_removed,
                    512 // PHASE2_MEMBERSHIP_MUTATION_ROWS,
                    budget.rows_inspected // (PHASE2_MEMBERSHIP_MUTATION_ROWS + 1),
                )
            )
        ).all()
        if not charge(budget, len(selected)):
            raise RuntimeError("Retained source selection exceeded its allowance.")
        if not selected:
            return True
        for row in selected:
            identifier = row.dependency_id if family == "xray" else row.leaf_id
            if budget.reserve_clear_batch(
                (
                    PayloadCopyCost(
                        row_id=identifier,
                        payload_bytes=row.payload_bytes,
                        inspection_rows=PHASE2_MEMBERSHIP_MUTATION_ROWS,
                    ),
                )
            ) != (identifier,):
                return False
            predicate = (
                (model.owner_id == owner)
                & (model.input_id == input_id)
                & (model.dependency_id == row.dependency_id)
            )
            if family == "historical":
                predicate &= HistoricalRetainedSourceModel.leaf_id == row.leaf_id
            session.execute(delete(model).where(predicate))
    return False


def rotation(
    session: Session,
    family: Literal["dispatch", "source", "enrichment"],
    count: int,
    budget: SourcePurgeBudget,
) -> tuple[int, ...]:
    expected = {"dispatch": 7, "source": 5, "enrichment": 4}[family]
    if type(count) is not int or count != expected:
        raise ValueError("A fixed retention family inventory is required.")
    if not charge(budget, 4):
        return ()
    if (
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "retention-order:" + family},
        )
        is not True
    ):
        return ()
    session.execute(
        insert(SourceRetentionDispatchModel)
        .values(family=family, next_family=0)
        .on_conflict_do_nothing()
    )
    row = session.scalar(
        select(SourceRetentionDispatchModel)
        .where(SourceRetentionDispatchModel.family == family)
        .with_for_update()
    )
    if row is None:
        raise RuntimeError("Retention scheduling state is unavailable.")
    first = row.next_family
    row.next_family = (first + 1) % count
    session.flush()
    return tuple((first + index) % count for index in range(count))


@dataclass(frozen=True, slots=True)
class PhysicalSourceCandidate:
    id: UUID
    owner_id: UUID
    expires_at: datetime | None
    pending: bool


def physical_source_candidates(
    session: Session,
    source: Table,
    work: Table,
    reference: str,
    family: str,
    at: datetime,
    budget: SourcePurgeBudget,
) -> Iterator[PhysicalSourceCandidate]:
    """One pending-work turn, then charged physical rows without rejected-prefix SQL.

    The work keyset resumes a different pending source next time, even if an
    earlier source must wait for another source family. The source keyset is
    independent; work updates never turn maintenance state into read authority.
    Both keysets wrap only on an actual indexed end probe.
    """
    fixed = {
        "price": ("price_snapshots", "price_snapshot_id"),
        "fx": ("fx_snapshots", "fx_snapshot_id"),
        "benchmark": ("benchmark_snapshots", "benchmark_snapshot_id"),
        "corporate_action": ("corporate_action_snapshots", "corporate_action_snapshot_id"),
        "constituent": ("constituent_snapshots", "constituent_snapshot_id"),
        "entity_evidence": ("entity_evidence_versions", "entity_evidence_version_id"),
        "classification": ("classification_snapshots", "classification_snapshot_id"),
        "fund_definition": ("fund_definitions", "fund_definition_id"),
        "fund_mapping": ("fund_source_mappings", "fund_mapping_id"),
    }
    if fixed.get(family) != (source.name, reference) or work.name not in (
        "source_retention_work",
        "enrichment_retention_work",
    ):
        raise ValueError("A fixed physical source family is required.")
    if not charge(budget, 3):
        return
    scope = UUID(int=0)
    session.execute(
        insert(Phase2RetentionSweepModel)
        .values(family=family, scope_id=scope)
        .on_conflict_do_nothing()
    )
    sweep = session.get(Phase2RetentionSweepModel, (family, scope), with_for_update=True)
    if sweep is None:
        raise RuntimeError("Source retention scheduling state is unavailable.")
    attempted: UUID | None = None
    for wrap in range(2):
        if not charge(budget, 2):
            return
        query = select(work.c.id, work.c.owner_id, work.c[reference].label("source_id")).where(
            work.c[reference].is_not(None), work.c.completed_at.is_(None)
        )
        if sweep.pending_id is not None:
            query = query.where(work.c.id > sweep.pending_id)
        pending = session.execute(query.order_by(work.c.id).limit(1)).first()
        if pending is None:
            if sweep.pending_id is None or wrap:
                break
            if not charge(budget):
                return
            sweep.pending_id = None
            session.flush()
            continue
        if not charge(budget):
            return
        attempted = pending.source_id
        yield PhysicalSourceCandidate(pending.source_id, pending.owner_id, None, True)
        # Advance only after the caller actually received an opportunity to work.
        # A budget return inside the caller closes this yield without checkpoint.
        sweep.pending_id = pending.id
        session.flush()
        break
    while budget.rows_inspected >= 4:
        if not charge(budget, 2):
            return
        query = select(source.c.id, source.c.owner_id, source.c.expires_at)
        if sweep.after_id is not None:
            query = query.where(source.c.id > sweep.after_id)
        row = session.execute(query.order_by(source.c.id).limit(1)).first()
        if row is None:
            if not charge(budget):
                return
            sweep.after_id = None
            sweep.evaluated_at = at
            session.flush()
            break
        if not charge(budget):
            return
        if row.id != attempted:
            yield PhysicalSourceCandidate(row.id, row.owner_id, row.expires_at, False)
        sweep.after_id = row.id
        session.flush()
