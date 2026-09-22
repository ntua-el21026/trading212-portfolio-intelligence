"""Phased physical expiry of the fixed licensed source snapshot families."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Table, select, text
from sqlalchemy.orm import Session, load_only

from . import source_models as sm
from .alert_retention import purge_alert_source_copies
from .historical_retention import purge_source_copies
from .phase2_retention_costs import (
    ACQUISITION_SOURCE_PERMISSION_MAX_ROWS,
    SOURCE_COMPLETION_ROWS,
    SOURCE_MARKER_ROWS,
    SOURCE_PROGRESS_ROWS,
)
from .phase2_retention_models import HistoricalCompositePhysicalModel
from .phase2_retention_runtime import charge, physical_source_candidates, rotation
from .report_retention import purge_report_source_copies
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows
from .xray_catalog_models import ConstituentHoldingModel, ConstituentSnapshotModel
from .xray_retention import purge_xray_source_copies

SOURCE_PAYLOADS = (
    (
        ConstituentSnapshotModel,
        ConstituentHoldingModel,
        (
            "ordinal",
            "source_key",
            "instrument_id",
            "entity_id",
            "state",
            "currency",
            "weight",
            "name",
            "confidence",
            "evidence_key",
        ),
    ),
    (
        sm.PriceSnapshotModel,
        sm.PriceObservationModel,
        ("ordinal", "session_date", "effective_at", "state", "value", "corporate_action_revision"),
    ),
    (
        sm.FxSnapshotModel,
        sm.FxObservationModel,
        ("ordinal", "session_date", "effective_at", "state", "base", "quote", "rate", "batch_key"),
    ),
    (
        sm.BenchmarkSnapshotModel,
        sm.BenchmarkObservationModel,
        ("ordinal", "session_date", "effective_at", "state", "level"),
    ),
    (
        sm.CorporateActionSnapshotModel,
        sm.CorporateActionObservationModel,
        (
            "ordinal",
            "session_date",
            "effective_at",
            "state",
            "source_key",
            "source_revision",
            "kind",
            "ratio",
            "amount",
            "currency",
            "target_instrument_id",
            "correction_source_key",
        ),
    ),
)


def _expire_snapshot(
    session: Session,
    row: sm.SourceSnapshotFields | ConstituentSnapshotModel,
    child: Table,
    payload_columns: tuple[str, ...],
    *,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    reference = str(row.__tablename__).removesuffix("s") + "_id"
    if not charge(budget):
        return False
    work = session.scalar(
        select(sm.SourceRetentionWorkModel)
        .where(
            sm.SourceRetentionWorkModel.owner_id == row.owner_id,
            getattr(sm.SourceRetentionWorkModel, reference) == row.id,
        )
        .limit(1)
    )
    if work is None:
        if not charge(budget, SOURCE_MARKER_ROWS):
            return False
        work = sm.SourceRetentionWorkModel(
            owner_id=row.owner_id,
            **{reference: row.id},
            started_at=at,
            content_digest=row.content_digest,
            phase="copies",
            removed_observation_count=0,
            created_at=at,
        )
        session.add(work)
        session.flush()
    else:
        if work.phase == "complete":
            return False
    if work.started_at > at:
        return False
    if work.phase == "copies":
        from .projection_retention import ProjectionParentKind, purge_projection_source_copies

        kind = str(row.__tablename__).removesuffix("_snapshots")
        if isinstance(row, sm.SourceSnapshotFields) and not purge_projection_source_copies(
            session, row.owner_id, cast(ProjectionParentKind, kind), row.id, at=at, budget=budget
        ):
            return False
        if not purge_alert_source_copies(
            session, owner=row.owner_id, kind=kind, source_id=row.id, at=at, budget=budget
        ):
            return False
        if not purge_report_source_copies(
            session, owner=row.owner_id, kind=kind, source_id=row.id, at=at, budget=budget
        ):
            return False
        if isinstance(row, sm.SourceSnapshotFields) and not purge_source_copies(
            session, row, at=at, budget=budget
        ):
            return False
        if not purge_xray_source_copies(session, row, at=at, budget=budget):
            return False
        if isinstance(row, sm.BenchmarkSnapshotModel) and row.snapshot_kind == "composite":
            if not charge(budget):
                return False
            points = session.scalar(
                select(HistoricalCompositePhysicalModel.point_rows).where(
                    HistoricalCompositePhysicalModel.owner_id == row.owner_id,
                    HistoricalCompositePhysicalModel.snapshot_id == row.id,
                )
            )
            if points is None or points:
                # Its expiry is the minimum original input-source expiry. Let the
                # independent work keyset reach that original parent and its run.
                return False
        if not charge(budget, SOURCE_PROGRESS_ROWS):
            return False
        work.phase = "observations"
        session.flush()
    if work.phase == "observations":
        if not charge(budget, SOURCE_PROGRESS_ROWS):
            return False
        removed = purge_payload_rows(
            session,
            child,
            (child.c.owner_id == row.owner_id) & (child.c.snapshot_id == row.id),
            payload_columns=payload_columns,
            delete_rows=True,
            budget=budget,
        )
        next_removed_count = work.removed_observation_count + removed.removed_rows
        if not removed.complete:
            work.removed_observation_count = next_removed_count
            session.flush()
            return False
        if isinstance(row, ConstituentSnapshotModel):
            header = cast(Table, ConstituentSnapshotModel.__table__)
            if not purge_payload_rows(
                session,
                header,
                (header.c.owner_id == row.owner_id) & (header.c.id == row.id),
                payload_columns=("known_weight", "unresolved_weight", "cash_weight", "confidence"),
                delete_rows=False,
                budget=budget,
            ).complete:
                work.removed_observation_count = next_removed_count
                session.flush()
                return False
        # Keep one progress write: the header clear must not autoflush a separate
        # intermediate counter update before the reserved phase transition.
        work.removed_observation_count = next_removed_count
        work.phase = "coverage"
        session.flush()
    gaps = cast(Table, sm.SourceCoverageGapModel.__table__)
    if not purge_payload_rows(
        session,
        gaps,
        (gaps.c.owner_id == row.owner_id) & (gaps.c[reference] == row.id),
        payload_columns=("session_date", "source_key", "reason", "ordinal"),
        delete_rows=True,
        budget=budget,
    ).complete:
        return False
    if not charge(budget, SOURCE_COMPLETION_ROWS):
        return False
    session.add(
        sm.SourceExpiryEventModel(
            owner_id=row.owner_id,
            **{reference: row.id},
            removed_at=at,
            removed_observation_count=work.removed_observation_count,
            content_digest=row.content_digest,
            reason="retention_removed",
            created_at=at,
        )
    )
    session.flush()
    work.phase = "complete"
    work.completed_at = at
    session.flush()
    return True


def expire_source_payloads(
    session: Session, *, at: datetime, limit: int, budget: SourcePurgeBudget
) -> int:
    """Fair physical keysets and original acquisition witnesses, sharing one budget."""
    completed = 0
    busy_owners: set[UUID] = set()
    for index in rotation(session, "source", len(SOURCE_PAYLOADS), budget):
        model, child_model, columns = SOURCE_PAYLOADS[index]
        reference = str(model.__tablename__).removesuffix("s") + "_id"
        kind = str(model.__tablename__).removesuffix("_snapshots")
        for candidate in physical_source_candidates(
            session,
            cast(Table, model.__table__),
            cast(Table, sm.SourceRetentionWorkModel.__table__),
            reference,
            kind,
            at,
            budget,
        ):
            if completed >= limit or budget.rows_removed == 0:
                return completed
            if candidate.owner_id in busy_owners:
                continue
            if not all(
                session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"{lock}:{candidate.owner_id}"},
                )
                is True
                for lock in ("sources", "xray", "historical")
            ):
                busy_owners.add(candidate.owner_id)
                continue
            if not candidate.pending:
                if not charge(budget):
                    return completed
                if (
                    session.scalar(
                        select(sm.SourceExpiryEventModel.id)
                        .where(
                            sm.SourceExpiryEventModel.owner_id == candidate.owner_id,
                            getattr(sm.SourceExpiryEventModel, reference) == candidate.id,
                        )
                        .limit(1)
                    )
                    is not None
                ):
                    continue
                restricted = candidate.expires_at is not None and candidate.expires_at <= at
                if not restricted and kind in ("price", "fx"):
                    if not charge(budget, ACQUISITION_SOURCE_PERMISSION_MAX_ROWS):
                        return completed
                    restricted = (
                        session.scalar(
                            text(
                                "SELECT acquisition_source_restricted(:owner,:kind,:sour"
                                "ce,:at,'store')"
                            ),
                            {
                                "owner": candidate.owner_id,
                                "kind": kind,
                                "source": candidate.id,
                                "at": at,
                            },
                        )
                        is True
                    )
                if not restricted:
                    continue
            if not charge(budget):
                return completed
            fields = [model.id, model.owner_id, model.expires_at, model.content_digest]
            if model is sm.BenchmarkSnapshotModel:
                fields.append(sm.BenchmarkSnapshotModel.snapshot_kind)
            row = session.scalar(
                select(model)
                .options(load_only(*fields, raiseload=True))
                .where(model.id == candidate.id, model.owner_id == candidate.owner_id)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                continue
            if _expire_snapshot(
                session,
                cast(sm.SourceSnapshotFields | ConstituentSnapshotModel, row),
                cast(Table, child_model.__table__),
                columns,
                at=at,
                budget=budget,
            ):
                completed += 1
    return completed
