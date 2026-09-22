"""Bounded source-expiry cleanup of licensed historical copies and derived payloads."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Table, or_, select
from sqlalchemy.orm import Session

from . import historical_models as hm
from . import source_models as sm
from .phase2_retention_costs import PHASE2_MARKER_ROWS
from .phase2_retention_models import (
    HistoricalCompositeErasureModel,
    HistoricalPhysicalRunModel,
    HistoricalRetainedSourceModel,
)
from .phase2_retention_runtime import charge, drain_retained_sources, source_erasure_authorized
from .planning_models import AnalyticsRunModel
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows

# Preserve the existing internal import while sharing the invocation allowance
# with source and X-ray participants. No independent historical counters remain.
HistoricalPurgeBudget = SourcePurgeBudget

# Closed payload inventory. Identity, methodology hashes and audit are retained.
RESULT_PAYLOADS = (
    (hm.PerformancePointModel, ("portfolio_value", "cash_value", "wealth", "period_return")),
    (hm.PerformancePeriodModel, ("period_return",)),
    (hm.HistoricalIncomeRowModel, ("net", "gross", "withholding")),
    (hm.HistoricalAttributionRowModel, ("gain", "return_contribution")),
    (hm.HistoricalCashFlowRowModel, ("amount",)),
)


def _source_column(snapshot: sm.SourceSnapshotFields) -> str:
    for kind, column in (
        (sm.PriceSnapshotModel, "price_snapshot_id"),
        (sm.FxSnapshotModel, "fx_snapshot_id"),
        (sm.CorporateActionSnapshotModel, "action_snapshot_id"),
        (sm.BenchmarkSnapshotModel, "benchmark_snapshot_id"),
    ):
        if isinstance(snapshot, kind):
            return column
    raise ValueError("A registered historical source family is required.")


def purge_source_copies(
    session: Session,
    snapshot: sm.SourceSnapshotFields,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    """Return true only after each indexed historical copy phase is complete.

    The analytics blobs are cleared last, so their retained marker continues to
    discover incomplete normalized/conversion/composite work on the next call.
    Partial progress commits with the existing immutable retention tombstone;
    current source authorization already denies access at expiry.
    """
    kind = _source_column(snapshot).removesuffix("_snapshot_id")
    if kind == "action":
        kind = "corporate_action"
    if not source_erasure_authorized(session, snapshot.owner_id, kind, snapshot.id, at, budget):
        return False
    membership = HistoricalRetainedSourceModel
    while budget.metadata_limit >= 2:
        if not charge(budget, 2):
            return False
        candidate = session.execute(
            select(membership.input_id.label("id"), membership.dependency_id, membership.leaf_id)
            .where(
                membership.owner_id == snapshot.owner_id,
                membership.source_kind == kind,
                membership.source_id == snapshot.id,
            )
            .order_by(membership.input_id, membership.dependency_id, membership.leaf_id)
            .limit(1)
        ).first()
        if candidate is None:
            return True
        if not budget.enter_capture("historical", candidate.id):
            return False
        if not budget.metadata_limit:
            return False
        from .projection_retention import purge_projection_source_copies
        from .scenario_retention import purge_scenario_historical_copies

        if not purge_projection_source_copies(
            session, snapshot.owner_id, "historical", candidate.id, at=at, budget=budget
        ):
            return False

        if not purge_scenario_historical_copies(
            session, snapshot.owner_id, candidate.id, at=at, budget=budget
        ):
            return False
        if not charge(budget):
            return False
        tombstone = session.scalar(
            select(hm.HistoricalRetentionEventModel.id)
            .where(
                hm.HistoricalRetentionEventModel.input_id == candidate.id,
                hm.HistoricalRetentionEventModel.owner_id == snapshot.owner_id,
            )
            .limit(1)
        )
        if tombstone is None:
            if not charge(budget, PHASE2_MARKER_ROWS):
                return False
            session.add(
                hm.HistoricalRetentionEventModel(
                    owner_id=snapshot.owner_id,
                    input_id=candidate.id,
                    dependency_id=candidate.dependency_id,
                    source_dependency_id=candidate.leaf_id
                    if candidate.leaf_id != candidate.dependency_id
                    else None,
                    removed_at=at,
                    reason="retention_removed",
                    created_at=at,
                )
            )
            session.flush()
        table = cast(Table, hm.HistoricalInputModel.__table__)
        if not purge_payload_rows(
            session,
            table,
            (table.c.owner_id == snapshot.owner_id) & (table.c.id == candidate.id),
            payload_columns=("canonical_input",),
            delete_rows=False,
            budget=budget,
        ).complete:
            return False
        if not _purge_capture_runs(session, snapshot.owner_id, candidate.id, budget=budget):
            return False
        if not drain_retained_sources(
            session, snapshot.owner_id, "historical", candidate.id, budget
        ):
            return False
    return False


def _purge_capture_runs(
    session: Session, owner_id: UUID, input_id: UUID, *, budget: SourcePurgeBudget
) -> bool:
    state = HistoricalPhysicalRunModel
    while budget.metadata_limit >= 3:
        if not charge(budget, 3):
            return False
        identifier = session.scalar(
            select(state.run_id)
            .where(
                state.owner_id == owner_id,
                state.input_id == input_id,
                or_(state.child_rows > 0, state.analytics_pending),
            )
            .order_by(state.run_id)
            .limit(1)
        )
        if identifier is None:
            return True
        run = session.get(hm.HistoricalRunModel, identifier)
        if run is None or run.owner_id != owner_id or run.input_id != input_id:
            raise RuntimeError("Historical physical state differs from its immutable run.")
        if not budget.enter_run("historical", run.id):
            return False
        if not _purge_run(session, run, budget=budget):
            return False
    return False


def _purge_run(session: Session, run: hm.HistoricalRunModel, *, budget: SourcePurgeBudget) -> bool:
    for model, numeric_columns in RESULT_PAYLOADS:
        table = cast(Table, model.__table__)
        if not purge_payload_rows(
            session,
            table,
            (table.c.owner_id == run.owner_id) & (table.c.run_id == run.id),
            payload_columns=("canonical_row", *numeric_columns),
            delete_rows=False,
            budget=budget,
        ).complete:
            return False
    table = cast(Table, hm.HistoricalConversionModel.__table__)
    if not purge_payload_rows(
        session,
        table,
        (table.c.owner_id == run.owner_id) & (table.c.run_id == run.id),
        payload_columns=("rate",),
        delete_rows=False,
        budget=budget,
    ).complete:
        return False
    if not charge(budget):
        return False
    composite = session.execute(
        select(hm.HistoricalCompositeModel.id, hm.HistoricalCompositeModel.snapshot_id)
        .where(
            hm.HistoricalCompositeModel.run_id == run.id,
            hm.HistoricalCompositeModel.owner_id == run.owner_id,
        )
        .limit(1)
    ).first()
    if composite is not None:
        if not charge(budget):
            return False
        witness = session.get(HistoricalCompositeErasureModel, composite.snapshot_id)
        if witness is None:
            if not charge(budget, 12):
                return False
            event_id = session.scalar(
                select(hm.HistoricalRetentionEventModel.id).where(
                    hm.HistoricalRetentionEventModel.owner_id == run.owner_id,
                    hm.HistoricalRetentionEventModel.input_id == run.input_id,
                )
            )
            if event_id is None:
                raise RuntimeError("Historical composite marker is unavailable.")
            session.add(
                HistoricalCompositeErasureModel(
                    snapshot_id=composite.snapshot_id,
                    owner_id=run.owner_id,
                    run_id=run.id,
                    event_id=event_id,
                )
            )
            session.flush()
        table = cast(Table, hm.BenchmarkCompositePointModel.__table__)
        if not purge_payload_rows(
            session,
            table,
            (table.c.owner_id == run.owner_id) & (table.c.snapshot_id == composite.snapshot_id),
            payload_columns=("canonical_point", "wealth", "interval_return"),
            delete_rows=False,
            budget=budget,
        ).complete:
            return False
        table = cast(Table, hm.HistoricalCompositeModel.__table__)
        if not purge_payload_rows(
            session,
            table,
            (table.c.owner_id == run.owner_id) & (table.c.id == composite.id),
            payload_columns=("canonical_composite",),
            delete_rows=False,
            budget=budget,
        ).complete:
            return False
    table = cast(Table, AnalyticsRunModel.__table__)
    return purge_payload_rows(
        session,
        table,
        (table.c.owner_id == run.owner_id) & (table.c.id == run.analytics_run_id),
        payload_columns=("canonical_input", "canonical_result"),
        delete_rows=False,
        budget=budget,
    ).complete
