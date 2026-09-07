"""Bounded source-expiry cleanup of licensed historical copies and derived financial payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from . import historical_models as hm
from . import source_models as sm
from .planning_models import AnalyticsRunModel

# Closed payload inventory. Identity, methodology hashes and audit are never rewritten.
RESULT_PAYLOADS = (
    (hm.PerformancePointModel, ("portfolio_value", "cash_value", "wealth", "period_return")),
    (hm.PerformancePeriodModel, ("period_return",)),
    (hm.HistoricalIncomeRowModel, ("net", "gross", "withholding")),
    (hm.HistoricalAttributionRowModel, ("gain", "return_contribution")),
    (hm.HistoricalCashFlowRowModel, ("amount",)),
)


@dataclass(slots=True)
class HistoricalPurgeBudget:
    captures: int = 100
    runs: int = 100


def purge_source_copies(
    session: Session,
    snapshot: sm.SourceSnapshotFields,
    *,
    at: datetime,
    budget: HistoricalPurgeBudget,
) -> bool:
    """Return true only after every dependent copied financial payload was removed.

    The shared expiry invocation budget bounds all capture and run documents;
    a remaining dependency keeps the source pending for the next ordinary expiry batch.
    Normalized rows within one run already have the fixed historical calculation bounds.
    """
    column = (
        "price_snapshot_id"
        if isinstance(snapshot, sm.PriceSnapshotModel)
        else "fx_snapshot_id"
        if isinstance(snapshot, sm.FxSnapshotModel)
        else "action_snapshot_id"
        if isinstance(snapshot, sm.CorporateActionSnapshotModel)
        else "benchmark_snapshot_id"
    )
    dependency = getattr(hm.HistoricalDependencyModel, column)
    pending_run = (
        select(hm.HistoricalRunModel.id)
        .join(AnalyticsRunModel, AnalyticsRunModel.id == hm.HistoricalRunModel.analytics_run_id)
        .where(
            hm.HistoricalRunModel.input_id == hm.HistoricalInputModel.id,
            AnalyticsRunModel.canonical_input != b"",
        )
        .exists()
    )
    candidates = session.execute(
        select(hm.HistoricalInputModel, hm.HistoricalDependencyModel)
        .join(
            hm.HistoricalDependencyModel,
            hm.HistoricalDependencyModel.input_id == hm.HistoricalInputModel.id,
        )
        .where(
            dependency == snapshot.id,
            hm.HistoricalInputModel.owner_id == snapshot.owner_id,
            or_(hm.HistoricalInputModel.canonical_input != b"", pending_run),
        )
        .order_by(hm.HistoricalInputModel.id)
        .limit(max(budget.captures, budget.runs))
    ).all()
    for capture, selected_dependency in candidates:
        if capture.canonical_input and budget.captures <= 0:
            continue
        tombstone = session.scalar(
            select(hm.HistoricalRetentionEventModel.id).where(
                hm.HistoricalRetentionEventModel.input_id == capture.id
            )
        )
        if tombstone is None:
            session.add(
                hm.HistoricalRetentionEventModel(
                    owner_id=snapshot.owner_id,
                    input_id=capture.id,
                    dependency_id=selected_dependency.id,
                    removed_at=at,
                    reason="retention_removed",
                    created_at=at,
                )
            )
            session.flush()
        if capture.canonical_input:
            capture.canonical_input = b""
            session.flush()
            budget.captures -= 1
        runs = session.scalars(
            select(hm.HistoricalRunModel)
            .join(AnalyticsRunModel, AnalyticsRunModel.id == hm.HistoricalRunModel.analytics_run_id)
            .where(
                hm.HistoricalRunModel.input_id == capture.id,
                AnalyticsRunModel.canonical_input != b"",
            )
            .order_by(hm.HistoricalRunModel.id)
            .limit(budget.runs)
        ).all()
        for run in runs:
            _purge_run(session, run)
            budget.runs -= 1
        if budget.captures == budget.runs == 0:
            break
    session.flush()
    return not bool(
        session.scalar(
            select(hm.HistoricalInputModel.id)
            .join(
                hm.HistoricalDependencyModel,
                hm.HistoricalDependencyModel.input_id == hm.HistoricalInputModel.id,
            )
            .where(
                dependency == snapshot.id,
                hm.HistoricalInputModel.owner_id == snapshot.owner_id,
                or_(hm.HistoricalInputModel.canonical_input != b"", pending_run),
            )
            .limit(1)
        )
    )


def _purge_run(session: Session, run: hm.HistoricalRunModel) -> None:
    for model, numeric_columns in RESULT_PAYLOADS:
        session.execute(
            update(model)
            .where(model.run_id == run.id)
            .values(canonical_row=b"", **dict.fromkeys(numeric_columns))
        )
    session.execute(
        update(hm.HistoricalConversionModel)
        .where(hm.HistoricalConversionModel.run_id == run.id)
        .values(rate=None)
    )
    composites = tuple(
        session.scalars(
            select(hm.HistoricalCompositeModel.snapshot_id).where(
                hm.HistoricalCompositeModel.run_id == run.id
            )
        )
    )
    for identifier in composites:
        session.execute(
            update(hm.BenchmarkCompositePointModel)
            .where(hm.BenchmarkCompositePointModel.snapshot_id == identifier)
            .values(canonical_point=b"", wealth=None, interval_return=None)
        )
        session.execute(
            update(hm.HistoricalCompositeModel)
            .where(hm.HistoricalCompositeModel.snapshot_id == identifier)
            .values(canonical_composite=b"")
        )
    session.execute(
        update(AnalyticsRunModel)
        .where(AnalyticsRunModel.id == run.analytics_run_id)
        .values(canonical_input=b"", canonical_result=b"")
    )
