"""Bounded source-expiry cleanup of licensed historical copies and derived payloads."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import SQLColumnExpression, Table, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Exists

from . import historical_models as hm
from . import source_models as sm
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


def _pending_run(input_id: SQLColumnExpression[UUID]) -> Exists:
    return (
        select(hm.HistoricalRunModel.id)
        .join(AnalyticsRunModel, AnalyticsRunModel.id == hm.HistoricalRunModel.analytics_run_id)
        .where(
            hm.HistoricalRunModel.input_id == input_id,
            or_(
                AnalyticsRunModel.canonical_input != b"", AnalyticsRunModel.canonical_result != b""
            ),
        )
        .exists()
    )


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
    dependency = getattr(hm.HistoricalDependencyModel, _source_column(snapshot))
    while budget.metadata_limit >= 2:
        candidate = session.execute(
            select(
                hm.HistoricalInputModel.id, hm.HistoricalDependencyModel.id.label("dependency_id")
            )
            .join(
                hm.HistoricalDependencyModel,
                hm.HistoricalDependencyModel.input_id == hm.HistoricalInputModel.id,
            )
            .where(
                dependency == snapshot.id,
                hm.HistoricalDependencyModel.owner_id == snapshot.owner_id,
                hm.HistoricalInputModel.owner_id == snapshot.owner_id,
                or_(
                    hm.HistoricalInputModel.canonical_input != b"",
                    _pending_run(hm.HistoricalInputModel.id),
                ),
            )
            .order_by(hm.HistoricalInputModel.id, hm.HistoricalDependencyModel.id)
            .limit(1)
        ).first()
        if candidate is None:
            return True
        if not budget.inspect(rows=2):
            raise RuntimeError("Historical expiry selection exceeded its row allowance.")
        if not budget.enter_capture("historical", candidate.id):
            return False
        if not budget.metadata_limit:
            return False
        tombstone = session.scalar(
            select(hm.HistoricalRetentionEventModel.id)
            .where(
                hm.HistoricalRetentionEventModel.input_id == candidate.id,
                hm.HistoricalRetentionEventModel.owner_id == snapshot.owner_id,
            )
            .limit(1)
        )
        if tombstone is not None:
            if not budget.inspect(rows=1):
                raise RuntimeError("Historical expiry tombstone exceeded its row allowance.")
        else:
            session.add(
                hm.HistoricalRetentionEventModel(
                    owner_id=snapshot.owner_id,
                    input_id=candidate.id,
                    dependency_id=candidate.dependency_id,
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
    return False


def _purge_capture_runs(
    session: Session, owner_id: UUID, input_id: UUID, *, budget: SourcePurgeBudget
) -> bool:
    while budget.metadata_limit >= 2:
        run = session.scalars(
            select(hm.HistoricalRunModel)
            .join(AnalyticsRunModel, AnalyticsRunModel.id == hm.HistoricalRunModel.analytics_run_id)
            .where(
                hm.HistoricalRunModel.owner_id == owner_id,
                hm.HistoricalRunModel.input_id == input_id,
                or_(
                    AnalyticsRunModel.canonical_input != b"",
                    AnalyticsRunModel.canonical_result != b"",
                ),
            )
            .order_by(hm.HistoricalRunModel.id)
            .limit(1)
        ).first()
        if run is None:
            return True
        if not budget.inspect(rows=2):
            raise RuntimeError("Historical run selection exceeded its row allowance.")
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
    if not budget.metadata_limit:
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
        if not budget.inspect(rows=1):
            raise RuntimeError("Historical composite selection exceeded its row allowance.")
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
