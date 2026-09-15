"""Bounded physical projection cleanup; no financial document is decoded here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from . import projection_models as pm
from .premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumRetentionModel,
    PremiumRunModel,
)
from .projection_job_lifecycle import finish_projection_job
from .projection_retention_costs import PROJECTION_RUN_MUTATION_RESERVE
from .projection_retention_scan import clear_projection_scans, scan_projection_sources
from .projection_retention_sweep import begin_sweep, end_sweep
from .report_retention import purge_report_premium_copies
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows

RetentionReason = Literal["run_expired", "source_restricted", "owner_erasure"]
ProjectionParentKind = Literal["price", "fx", "corporate_action", "benchmark", "historical"]

# Every fixed financial participant is listed explicitly, in foreign-key order.
# Permanent definitions, original source identities and license membership remain.
PROJECTION_PAYLOADS = (
    (pm.ProjectionDistributionQuantileModel, ("distribution_id", "basis", "probability", "value")),
    (
        pm.ProjectionHistogramBinModel,
        ("histogram_id", "bin_index", "lower", "upper", "upper_inclusive", "count"),
    ),
    (pm.ProjectionGoalShortfallQuantileModel, ("analysis_id", "probability", "value")),
    (
        pm.ProjectionDistributionModel,
        ("result_id", "variant", "month", "nominal_mean", "real_mean", "funding_failed_paths"),
    ),
    (
        pm.ProjectionHistogramModel,
        (
            "result_id",
            "variant",
            "basis",
            "observed_minimum",
            "observed_maximum",
            "bin_count",
            "boundary_rule",
        ),
    ),
    (
        pm.ProjectionGoalAnalysisModel,
        (
            "result_id",
            "goal_version_id",
            "variant",
            "basis",
            "target",
            "paths",
            "successes",
            "probability",
            "interval_low",
            "interval_high",
            "probability_objective",
            "mean_shortfall",
            "objective_met",
            "funding_failed_paths",
            "method",
            "interval_method",
        ),
    ),
    (pm.ProjectionZeroPivotModel, ("result_id", "asset_index")),
    (pm.ProjectionPointAssetModel, ("run_id", "point_id", "asset_index", "value")),
    (
        pm.ProjectionPointModel,
        (
            "run_id",
            "path_id",
            "month",
            "point_index",
            "nominal",
            "real",
            "contributions",
            "withdrawals_requested",
            "withdrawals_funded",
            "unpaid_withdrawals",
            "investment_effect",
            "fees",
            "tax_drag",
            "wealth_residual",
            "allocation_residual",
            "withdrawal_residual",
            "funding_failed",
            "unpaid_positive_below_quantum",
        ),
    ),
    (pm.ProjectionPathModel, ("run_id", "chunk_id", "variant", "path_index", "first_unpaid_month")),
    (
        pm.ProjectionChunkModel,
        (
            "run_id",
            "job_id",
            "lease_token",
            "consumer_attempt",
            "variant",
            "first_path",
            "path_count",
            "input_digest",
            "content_digest",
            "byte_length",
            "canonical_chunk",
            "sealed",
        ),
    ),
    (pm.ProjectionRunAllocationModel, ("run_id", "asset_index", "asset_key", "weight")),
    (pm.ProjectionCalendarBoundaryModel, ("run_id", "month", "on", "point_index")),
    (pm.ProjectionRunPauseModel, ("run_id", "on", "month")),
    (pm.ProjectionRunScheduleEntryModel, ("run_id", "entry_key", "on", "month", "kind", "value")),
    (pm.ProjectionSourceProofModel, ("run_id", "source_id", "canonical_proof")),
    (
        pm.ProjectionInputModel,
        (
            "run_id",
            "initial_value",
            "base_monthly",
            "annual_growth",
            "contribution_delta",
            "annual_mean_log_delta",
            "pause_count",
            "entry_count",
            "capture_bytes",
            "input_bytes",
            "canonical_capture",
            "canonical_input",
        ),
    ),
)


def _charge(budget: SourcePurgeBudget, rows: int = 1) -> None:
    if not budget.inspect(rows=rows):
        raise RuntimeError("Projection cleanup exceeded its metadata allowance.")


def _storage_bytes(session: Session, root: PremiumRunModel) -> int:
    value = session.scalar(
        select(pm.ProjectionRunModel.stored_bytes).where(
            pm.ProjectionRunModel.owner_id == root.owner_id,
            pm.ProjectionRunModel.account_id == root.account_id,
            pm.ProjectionRunModel.id == root.id,
        )
    )
    if type(value) is not int or not 0 <= value <= 33554432:
        raise RuntimeError("Projection physical byte accounting is invalid.")
    return value


@dataclass(frozen=True, slots=True)
class _Lifecycle:
    at: datetime
    budget: SourcePurgeBudget

    def _now(self) -> datetime:
        return self.at

    def _result_bytes(self, session: Session, root: PremiumRunModel) -> int:
        _charge(self.budget)
        return _storage_bytes(session, root)


def _lock_owner(session: Session, owner: UUID) -> bool:
    # Workers acquire the execution slot before these locks. Cleanup never needs it.
    return all(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{owner}"},
        )
        is True
        for namespace in ("sources", "xray", "historical", "premium")
    )


def _scope(table: Table, root: PremiumRunModel) -> ColumnElement[bool]:
    result = pm.ProjectionResultModel
    result_ids = select(result.id).where(
        result.owner_id == root.owner_id,
        result.account_id == root.account_id,
        result.run_id == root.id,
    )
    if "run_id" in table.c:
        selected = table.c.run_id == root.id
    elif "result_id" in table.c:
        selected = table.c.result_id.in_(result_ids)
    elif table.name == "projection_distribution_quantiles":
        parent = pm.ProjectionDistributionModel
        selected = table.c.distribution_id.in_(
            select(parent.id).where(
                parent.owner_id == root.owner_id,
                parent.account_id == root.account_id,
                parent.result_id.in_(result_ids),
            )
        )
    elif table.name == "projection_histogram_bins":
        histogram = pm.ProjectionHistogramModel
        selected = table.c.histogram_id.in_(
            select(histogram.id).where(
                histogram.owner_id == root.owner_id,
                histogram.account_id == root.account_id,
                histogram.result_id.in_(result_ids),
            )
        )
    elif table.name == "projection_goal_shortfall_quantiles":
        goal = pm.ProjectionGoalAnalysisModel
        selected = table.c.analysis_id.in_(
            select(goal.id).where(
                goal.owner_id == root.owner_id,
                goal.account_id == root.account_id,
                goal.result_id.in_(result_ids),
            )
        )
    else:
        raise RuntimeError("Unregistered projection cleanup participant.")
    return selected & (table.c.owner_id == root.owner_id) & (table.c.account_id == root.account_id)


# Each indirect collection uses one exact parent at a time. A cross-parent
# ORDER BY child.id can otherwise sort/materialize its entire population before
# applying LIMIT. These bounds are enforced by the existing closed result schema.
_INDIRECT_PARENTS = {
    "projection_distribution_quantiles": (pm.ProjectionDistributionModel, "distribution_id", 363),
    "projection_histogram_bins": (pm.ProjectionHistogramModel, "histogram_id", 6),
    "projection_goal_shortfall_quantiles": (pm.ProjectionGoalAnalysisModel, "analysis_id", 3),
}


def _clear_indirect(
    session: Session,
    root: PremiumRunModel,
    table: Table,
    columns: tuple[str, ...],
    budget: SourcePurgeBudget,
) -> bool:
    parent_model, field, maximum = _INDIRECT_PARENTS[table.name]
    if not budget.inspect(rows=1):
        return False
    result_id = session.scalar(
        select(pm.ProjectionResultModel.id).where(
            pm.ProjectionResultModel.owner_id == root.owner_id,
            pm.ProjectionResultModel.account_id == root.account_id,
            pm.ProjectionResultModel.run_id == root.id,
        )
    )
    if result_id is None:
        return True
    parent = cast(Table, parent_model.__table__)
    after: UUID | None = None
    inspected = 0
    while budget.metadata_limit:
        # No has-children filter hides previously cleared parent headers. Every
        # revisit is charged, and the fixed parent envelope allows resumption.
        if not budget.inspect(rows=1):
            return False
        predicate = (
            (parent.c.owner_id == root.owner_id)
            & (parent.c.account_id == root.account_id)
            & (parent.c.result_id == result_id)
        )
        if after is not None:
            predicate = predicate & (parent.c.id > after)
        identifier = session.scalar(
            select(parent.c.id).where(predicate).order_by(parent.c.id).limit(1)
        )
        if identifier is None:
            return True
        inspected += 1
        if inspected > maximum:
            raise RuntimeError("Projection cleanup parent envelope is invalid.")
        if not purge_payload_rows(
            session,
            table,
            (table.c.owner_id == root.owner_id)
            & (table.c.account_id == root.account_id)
            & (table.c[field] == identifier),
            payload_columns=columns,
            delete_rows=True,
            budget=budget,
        ).complete:
            return False
        after = identifier
    return False


def _clear_payloads(session: Session, root: PremiumRunModel, budget: SourcePurgeBudget) -> bool:
    for model, columns in PROJECTION_PAYLOADS:
        table = cast(Table, model.__table__)
        if table.name in _INDIRECT_PARENTS:
            if not _clear_indirect(session, root, table, columns, budget):
                return False
            continue
        if not purge_payload_rows(
            session,
            table,
            _scope(table, root),
            payload_columns=columns,
            delete_rows=True,
            budget=budget,
        ).complete:
            return False
    # Keep result identity, digest and publication audit after clearing its value.
    result = cast(Table, pm.ProjectionResultModel.__table__)
    if not purge_payload_rows(
        session,
        result,
        _scope(result, root),
        payload_columns=("canonical_result",),
        delete_rows=False,
        budget=budget,
    ).complete:
        return False
    # Source identities remain blockers after the last financial deletion, until
    # this final bounded phase removes their real storage cost too.
    membership = cast(Table, pm.ProjectionRetainedSourceModel.__table__)
    return purge_payload_rows(
        session,
        membership,
        _scope(membership, root),
        payload_columns=(
            "id",
            "owner_id",
            "account_id",
            "created_at",
            "run_id",
            "source_kind",
            "source_id",
            "original_created_at",
        ),
        delete_rows=True,
        budget=budget,
    ).complete


def _purge_run(
    session: Session,
    root: PremiumRunModel,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    reason: RetentionReason | None = None,
) -> bool:
    if root.kind != "projection":
        raise RuntimeError("Projection cleanup requires an exact owned projection root.")
    if (
        not budget.enter_run("projection", root.id)
        or not budget.enter_capture("projection", root.id)
        or budget.rows_inspected < PROJECTION_RUN_MUTATION_RESERVE + 10
    ):
        return False
    # Includes marker/fence/refund/completion writes and their fixed SQL guards,
    # including deferred root-counter capacity checks at COMMIT.
    _charge(budget, PROJECTION_RUN_MUTATION_RESERVE)
    _charge(budget)
    marker = session.scalar(
        select(PremiumRetentionModel).where(
            PremiumRetentionModel.owner_id == root.owner_id,
            PremiumRetentionModel.account_id == root.account_id,
            PremiumRetentionModel.run_id == root.id,
        )
    )
    if marker is not None and marker.completed_at is not None:
        return True
    if marker is None:
        marker = PremiumRetentionModel(
            id=uuid4(),
            owner_id=root.owner_id,
            account_id=root.account_id,
            run_id=root.id,
            reason=reason or ("run_expired" if root.expires_at <= at else "source_restricted"),
            created_at=at,
        )
        session.add(marker)
        session.flush()
    _charge(budget)
    job = session.scalar(
        select(PremiumJobModel)
        .where(
            PremiumJobModel.owner_id == root.owner_id,
            PremiumJobModel.account_id == root.account_id,
            PremiumJobModel.run_id == root.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise RuntimeError("Projection cleanup job identity is absent.")
    if job.state in ("queued", "running"):
        # Fence before report/artifact deletion. The terminal helper converts the
        # reservation to actual bytes; those bytes stay charged throughout purge.
        _charge(budget, 3)  # capacity, outbox, immutable terminal-attempt record
        finish_projection_job(
            _Lifecycle(at, budget), session, root, job, "expired", "source_restricted"
        )
    if not purge_report_premium_copies(session, root.owner_id, root.id, at=at, budget=budget):
        return False
    if budget.metadata_limit < 2:
        return False
    _charge(budget, 2)  # reserve capacity lookup and final physical-size reconciliation
    capacity = session.scalar(
        select(PremiumCapacityModel)
        .where(PremiumCapacityModel.owner_id == root.owner_id)
        .with_for_update()
    )
    if (
        capacity is None
        or root.reserved_bytes != 0
        or root.retained_bytes < 0
        or capacity.retained_bytes < root.retained_bytes
    ):
        raise RuntimeError("Projection cleanup retained charge is inconsistent.")
    complete = _clear_payloads(session, root, budget)
    # This runs even after a bounded partial delete. Logical purge cost is not a
    # storage refund: only the trigger-maintained exact physical counter may release charge.
    remaining = _storage_bytes(session, root)
    if remaining > root.retained_bytes:
        raise RuntimeError("Projection retained payload grew during cleanup.")
    capacity.retained_bytes -= root.retained_bytes - remaining
    capacity.updated_at = at
    root.retained_bytes = remaining
    if complete:
        if remaining != 0:
            raise RuntimeError("Projection cleanup completion still has physical copies.")
        complete = clear_projection_scans(session, root, budget)
        if complete:
            marker.completed_at = at
    session.flush()
    return complete


def _drain(
    session: Session,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    owner: UUID | None = None,
    target: tuple[ProjectionParentKind, UUID] | None = None,
    reason: RetentionReason | None = None,
) -> bool:
    sweep = begin_sweep(
        session, at=at, budget=budget, owner=owner, target=target, erasure=reason == "owner_erasure"
    )
    if sweep is None:
        return False
    while budget.metadata_limit >= 4:
        query = select(PremiumRunModel.id, PremiumRunModel.owner_id).where(
            PremiumRunModel.kind == "projection"
        )
        if owner is not None:
            query = query.where(PremiumRunModel.owner_id == owner)
        if sweep.after_id is not None:
            query = query.where(PremiumRunModel.id > sweep.after_id)
        _charge(budget)  # includes every skipped/clean root, never filtered after a join
        candidate = session.execute(query.order_by(PremiumRunModel.id).limit(1)).first()
        if candidate is None:
            return end_sweep(session, sweep, budget)
        _charge(budget)  # reserve the persisted sweep checkpoint before descendant work
        if not _lock_owner(session, candidate.owner_id):
            sweep.deferred, sweep.after_id = True, candidate.id
            session.flush()
            continue
        _charge(budget)
        root = session.scalar(
            select(PremiumRunModel)
            .where(
                PremiumRunModel.id == candidate.id, PremiumRunModel.owner_id == candidate.owner_id
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if root is None:
            sweep.deferred, sweep.after_id = True, candidate.id
            session.flush()
            continue
        if not budget.enter_run("projection", root.id) or not budget.enter_capture(
            "projection", root.id
        ):
            return False
        _charge(budget)
        marker = session.scalar(
            select(PremiumRetentionModel).where(
                PremiumRetentionModel.owner_id == root.owner_id,
                PremiumRetentionModel.account_id == root.account_id,
                PremiumRetentionModel.run_id == root.id,
            )
        )
        if marker is not None and marker.completed_at is not None:
            sweep.after_id = root.id
            session.flush()
            continue
        if reason != "owner_erasure" and (
            target is not None or (marker is None and root.expires_at > at)
        ):
            if target is not None:
                if not budget.inspect(rows=1):
                    return False
                membership = pm.ProjectionRetainedSourceModel
                match = session.scalar(
                    select(membership.id)
                    .where(
                        membership.owner_id == root.owner_id,
                        membership.run_id == root.id,
                        membership.source_kind == target[0],
                        membership.source_id == target[1],
                    )
                    .limit(1)
                )
                result = "matched" if match is not None else "no_match"
            else:
                result = scan_projection_sources(session, root, at=at, budget=budget)
            if result == "pending":
                return False
            if result in ("clean", "no_match"):
                sweep.after_id = root.id
                session.flush()
                continue
        if not _purge_run(session, root, at=at, budget=budget, reason=reason):
            return False
        sweep.after_id = root.id
        session.flush()
    return False


def expire_projection_payloads(
    session: Session, *, at: datetime, budget: SourcePurgeBudget, owner: UUID | None = None
) -> bool:
    return _drain(session, at=at, budget=budget, owner=owner)


def purge_projection_source_copies(
    session: Session,
    owner: UUID,
    kind: ProjectionParentKind,
    source_id: UUID,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    """Caller holds an actual source restriction/expiry or historical purge authority."""
    if kind not in ("price", "fx", "corporate_action", "benchmark", "historical"):
        raise ValueError("A closed projection source family is required.")
    return _drain(
        session,
        at=at,
        budget=budget,
        owner=owner,
        target=(kind, source_id),
        reason="source_restricted",
    )


def purge_owner_projection_payloads(
    session: Session, owner: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    """Explicit owner erasure; durable definitions and nonfinancial identities remain."""
    return _drain(session, at=at, budget=budget, owner=owner, reason="owner_erasure")
