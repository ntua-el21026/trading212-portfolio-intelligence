"""Bind projection report copies to actual immutable owned normalized records."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import case, select
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_domain.report_v4 import (
    ReportCaptureSummaryV4,
    ReportProjectionObservedBinding,
    ReportSelectionV4,
)

from . import projection_models as m
from .historical_models import HistoricalInputModel
from .models import CalculationRunModel, PortfolioSnapshotModel
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_capture_projection_store import _version, authorize_projection_report_metadata
from .report_models import ReportInputPremiumDependencyModel, ReportInputSnapshotModel
from .source_store import digest


def bind_projection_report_dependency(
    session: Session,
    authorization: ReportAuthorization,
    capture: ReportInputSnapshotModel,
    selection: ReportSelectionV4,
    summary: ReportCaptureSummaryV4,
    *,
    now: datetime,
) -> datetime:
    """Compare every saved immutable binding before admitting the normalized copy."""
    if (
        capture.contract_version != 4
        or capture.kind != "report"
        or summary.header.selection != selection
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    root, run, job, result = authorize_projection_report_metadata(
        session, authorization, selection.premium_run.run_id, now=now
    )
    pin = summary.header.premium_binding
    cutoffs = tuple(
        session.scalars(
            select(
                case(
                    (
                        m.ProjectionRunSourceModel.kind == "initial_snapshot",
                        PortfolioSnapshotModel.source_cutoff_at,
                    ),
                    else_=HistoricalInputModel.source_cutoff_at,
                )
            )
            .select_from(m.ProjectionRunSourceModel)
            .outerjoin(
                PortfolioSnapshotModel,
                (PortfolioSnapshotModel.id == m.ProjectionRunSourceModel.subject_id)
                & (PortfolioSnapshotModel.broker_account_id == authorization.account_id)
                & (m.ProjectionRunSourceModel.kind == "initial_snapshot"),
            )
            .outerjoin(
                HistoricalInputModel,
                (HistoricalInputModel.id == m.ProjectionRunSourceModel.subject_id)
                & (HistoricalInputModel.owner_id == authorization.owner_id)
                & (HistoricalInputModel.broker_account_id == authorization.account_id)
                & (m.ProjectionRunSourceModel.kind == "calibration"),
            )
            .where(
                m.ProjectionRunSourceModel.run_id == root.id,
                m.ProjectionRunSourceModel.owner_id == authorization.owner_id,
                m.ProjectionRunSourceModel.account_id == authorization.account_id,
            )
            .limit(258)
        )
    )
    if len(cutoffs) != run.source_count:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    original_cutoff = (
        max(item for item in cutoffs if item is not None)
        if cutoffs and all(item is not None for item in cutoffs)
        else None
    )
    input_id = session.scalar(
        select(m.ProjectionInputModel.id).where(
            m.ProjectionInputModel.run_id == root.id,
            m.ProjectionInputModel.owner_id == authorization.owner_id,
            m.ProjectionInputModel.account_id == authorization.account_id,
        )
    )
    terminal = session.scalar(
        select(m.ProjectionCalendarBoundaryModel.on).where(
            m.ProjectionCalendarBoundaryModel.run_id == root.id,
            m.ProjectionCalendarBoundaryModel.owner_id == authorization.owner_id,
            m.ProjectionCalendarBoundaryModel.account_id == authorization.account_id,
            m.ProjectionCalendarBoundaryModel.month == run.months,
        )
    )
    snapshot = session.execute(
        select(
            PortfolioSnapshotModel.id,
            PortfolioSnapshotModel.valuation_at,
            PortfolioSnapshotModel.source_cutoff_at,
            CalculationRunModel.output_fingerprint,
        )
        .join(
            CalculationRunModel, CalculationRunModel.id == PortfolioSnapshotModel.calculation_run_id
        )
        .where(
            PortfolioSnapshotModel.id == selection.snapshot_id,
            PortfolioSnapshotModel.broker_account_id == authorization.account_id,
            CalculationRunModel.broker_account_id == authorization.account_id,
        )
    ).one_or_none()
    observed = None
    if run.initial_kind == "observed_snapshot":
        if (
            run.snapshot_id is None
            or run.snapshot_digest is None
            or run.snapshot_valuation_at is None
        ):
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        observed = ReportProjectionObservedBinding(
            snapshot_id=run.snapshot_id,
            snapshot_digest=run.snapshot_digest,
            valuation_at=run.snapshot_valuation_at,
        )
    assumption = _version(session, authorization, run.assumption_version_id)
    goal = (
        None
        if run.goal_version_id is None
        else _version(session, authorization, run.goal_version_id, goal=True)
    )
    if (
        snapshot is None
        or input_id is None
        or terminal is None
        or (
            pin.source_cutoff_at != original_cutoff
            or pin.root_id != root.id
            or pin.run_id != root.id
            or pin.input_id != input_id
            or pin.result_id != result.id
            or pin.capture_digest != root.input_digest
            or pin.capture_digest != run.capture_digest
            or pin.numerical_input_digest != run.numerical_input_digest
            or pin.numerical_input_digest != result.input_digest
            or pin.result_digest != result.content_digest
            or pin.owner_id != authorization.owner_id
            or pin.account_id != authorization.account_id
            or pin.assumption != assumption
            or pin.goal != goal
            or pin.assumption.content_digest != run.assumption_digest
            or (None if pin.goal is None else pin.goal.content_digest) != run.goal_digest
            or pin.initial_kind != run.initial_kind
            or pin.observed != observed
            or pin.anchor_date != run.anchor_date
            or pin.terminal_date != terminal
            or pin.months != run.months
            or pin.path_count != run.path_count
            or pin.retained_point_count != run.retained_point_count
            or pin.variant_count != run.variant_count
            or pin.asset_count != run.asset_count
            or pin.source_count != run.source_count
            or pin.created_at != root.created_at
            or pin.calculated_at != result.created_at
            or pin.completed_at != job.completed_at
            or pin.expires_at != root.expires_at
            or pin.reporting_currency != selection.reporting_currency
            or pin.reporting_currency.value != run.reporting_currency
            or pin.reporting_currency.value != capture.reporting_currency
            or pin.report_context.snapshot_id != capture.snapshot_id
            or pin.report_context.snapshot_id != snapshot.id
            or pin.report_context.snapshot_digest
            != digest((str(snapshot.id), snapshot.output_fingerprint))
            or pin.report_context.valuation_at != snapshot.valuation_at
            or pin.report_context.valuation_at != capture.valuation_at
            or pin.report_context.source_cutoff_at != selection.source_cutoff_at
            or pin.report_context.source_cutoff_at != capture.source_cutoff_at
            or snapshot.source_cutoff_at > selection.source_cutoff_at
            or snapshot.valuation_at > selection.source_cutoff_at
            or selection.source_cutoff_at > now
        )
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    deadline = min(root.expires_at, summary.copy_expires_at or root.expires_at)
    if deadline <= now:
        raise report_error(app.ReportServiceErrorCode.ARTIFACT_EXPIRED)
    session.add(
        ReportInputPremiumDependencyModel(
            id=uuid4(),
            owner_id=authorization.owner_id,
            account_id=authorization.account_id,
            input_id=capture.id,
            run_id=root.id,
            kind="projection",
            input_digest=root.input_digest,
            result_id=result.id,
            result_digest=result.content_digest,
            definition_version_id=run.assumption_version_id,
            definition_digest=run.assumption_digest,
            snapshot_id=pin.report_context.snapshot_id,
            snapshot_digest=pin.report_context.snapshot_digest,
            reporting_currency=run.reporting_currency,
            source_cutoff_at=pin.report_context.source_cutoff_at,
            valuation_at=pin.report_context.valuation_at,
            expires_at=deadline,
            created_at=now,
        )
    )
    session.flush()
    # The sink flushes the complete copied license set and clamps every deadline before sealing.
    return deadline
