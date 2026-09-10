"""Phased physical expiry of the fixed licensed source snapshot families."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Table, select, text, tuple_
from sqlalchemy.orm import Session

from . import source_models as sm
from .historical_retention import purge_source_copies
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
    if not budget.metadata_limit:
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
        if not budget.inspect(rows=1):
            raise RuntimeError("Source expiry work selection exceeded its row allowance.")
        if work.phase == "complete":
            return False
    if work.phase == "copies":
        kind = str(row.__tablename__).removesuffix("_snapshots")
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
        work.phase = "observations"
        session.flush()
    if work.phase == "observations":
        removed = purge_payload_rows(
            session,
            child,
            (child.c.owner_id == row.owner_id) & (child.c.snapshot_id == row.id),
            payload_columns=payload_columns,
            delete_rows=True,
            budget=budget,
        )
        work.removed_observation_count += removed.removed_rows
        if not removed.complete:
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
                session.flush()
                return False
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
    """Resume exact-source work; count only newly completed expiry records.

    A local keyset visits a pending source at most once in this invocation. Its
    durable work row retains phase/count across calls; no completion marker is
    written until dependent copies and source payloads are physically gone.
    """
    completed = 0
    for model, child_model, columns in SOURCE_PAYLOADS:
        reference = str(model.__tablename__).removesuffix("s") + "_id"
        after: tuple[datetime, UUID] | None = None
        while completed < limit and budget.metadata_limit >= 2:
            query = select(model.id, model.owner_id, model.expires_at).where(
                model.expires_at <= at,
                ~select(sm.SourceExpiryEventModel.id)
                .where(
                    getattr(sm.SourceExpiryEventModel, reference) == model.id,
                    sm.SourceExpiryEventModel.owner_id == model.owner_id,
                )
                .exists(),
            )
            if after is not None:
                query = query.where(tuple_(model.expires_at, model.id) > after)
            selected = session.execute(query.order_by(model.expires_at, model.id).limit(1)).first()
            if selected is None:
                break
            if not budget.inspect(rows=1):
                raise RuntimeError("Source expiry discovery exceeded its row allowance.")
            after = (selected.expires_at, selected.id)
            # Keep the existing source owner lock before taking the row lock.
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"sources:{selected.owner_id}"},
            )
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"xray:{selected.owner_id}"},
            )
            row = session.scalar(
                select(model)
                .where(model.id == selected.id, model.owner_id == selected.owner_id)
                .with_for_update()
            )
            if row is None:
                continue
            if not budget.inspect(rows=1):
                raise RuntimeError("Source expiry header exceeded its row allowance.")
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
