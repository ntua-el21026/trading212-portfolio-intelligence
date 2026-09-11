"""Canonical health and terminal-job evidence at the scheduled alert cutoff."""

from dataclasses import replace

from sqlalchemy import String, select
from sqlalchemy import cast as sql_cast
from trading212_domain import alerts as d
from trading212_domain.enums import QualityState
from trading212_domain.ingestion import IngestionCapability
from trading212_domain.reports import ReportSourceKind, ReportType

from .alert_capture_common import AlertCaptureState, bounded
from .models import (
    AuditEventModel,
    IngestionRunModel,
    ReconciliationDiscrepancyModel,
    ReconciliationRunModel,
)
from .planning_inputs import digest
from .provider_observation_models import ProviderInvocationObservationModel
from .report_models import ReportJobModel


def capture_provider(state: AlertCaptureState) -> d.AlertThresholdInput | d.AlertEventBatchInput:
    model = ProviderInvocationObservationModel
    rows = bounded(
        list(
            state.session.scalars(
                select(model)
                .where(
                    model.owner_id == state.version.owner_id,
                    model.provider_id == state.predicate.provider_id,
                    model.completed_at > state.window.start_at,
                    model.completed_at <= state.cutoff,
                    model.first_known_at <= state.cutoff,
                    model.created_at <= state.cutoff,
                )
                .order_by(model.completed_at.desc(), model.observed_sequence.desc())
                .limit(10001)
            )
        ),
        10000,
    )
    if not rows:
        return state.unavailable(d.AlertReason.NO_OBSERVATIONS)
    state.context = replace(
        state.context,
        quality=QualityState.FRESH,
        valuation_at=rows[0].completed_at,
        method_key="provider_invocation_observation",
        method_version="1.0.0",
    )
    latest = rows[0]
    count = 0
    for row in rows:
        state.bindings.append(
            d.AlertCanonicalBinding(
                family=d.AlertCanonicalFamily.PROVIDER,
                role=d.AlertInputRole.RESULT,
                subject_id=row.id,
                parent_id=row.provider_id,
                content_digest=digest(
                    (
                        row.id,
                        row.provider_id,
                        row.observed_sequence,
                        row.capability,
                        row.adapter_version,
                        row.started_at,
                        row.completed_at,
                        row.first_known_at,
                        row.outcome,
                        row.failure_code,
                    )
                ),
                method_key="provider_invocation_observation",
                method_version="1.0.0",
            )
        )
        if row is latest and row.outcome == "unavailable":
            reason = {
                "not_configured": d.AlertReason.NOT_CONFIGURED,
                "license_denied": d.AlertReason.SOURCE_RESTRICTED,
                "unsupported": d.AlertReason.UNSUPPORTED,
            }.get(row.failure_code or "", d.AlertReason.NO_OBSERVATIONS)
            return state.unavailable(reason)
        if state.predicate.metric is d.AlertMetric.PROVIDER_FAILED:
            break
        if row.outcome == "succeeded":
            break
        if row.outcome == "unavailable":
            return state.unavailable(d.AlertReason.NO_OBSERVATIONS)
        count += 1
    value = (
        latest.outcome == "failed"
        if state.predicate.metric is d.AlertMetric.PROVIDER_FAILED
        else count
    )
    return d.AlertThresholdInput(observation=state.observation(value))


def capture_reconciliation(
    state: AlertCaptureState,
) -> d.AlertThresholdInput | d.AlertEventBatchInput:
    model = ReconciliationRunModel
    row = state.session.scalar(
        select(model)
        .where(
            model.broker_account_id == state.version.account_id,
            model.as_of <= state.cutoff,
            model.created_at <= state.cutoff,
        )
        .order_by(model.as_of.desc(), model.created_at.desc(), model.id)
        .limit(1)
    )
    if row is None:
        return state.unavailable(d.AlertReason.MISSING_INPUT)
    state.context = replace(
        state.context,
        quality=QualityState(row.quality_state),
        valuation_at=row.as_of,
        method_key="reconciliation",
        method_version=row.algorithm_version,
        reconciliation_id=row.id,
        coverage=(
            d.AlertCoverageFact(
                key="reconciliation",
                expected_count=None,
                available_count=None,
                complete=row.coverage_complete,
            ),
        ),
    )
    state.reference(
        kind=ReportSourceKind.RECONCILIATION,
        identifier=row.id,
        digest=digest(
            (
                row.input_fingerprint,
                row.algorithm_version,
                row.tolerance_version,
                row.status,
                row.discrepancy_count,
                row.coverage_complete,
            )
        ),
        effective_at=row.as_of,
        known_at=row.created_at,
    )
    if state.predicate.metric is d.AlertMetric.RECONCILIATION_FAILED:
        if row.status == "partial":
            return state.unavailable(d.AlertReason.INCOMPLETE_COVERAGE)
        value: int | bool = row.status in {"unreconciled", "failed"}
    else:
        discrepancy = ReconciliationDiscrepancyModel
        items = bounded(
            list(
                state.session.scalars(
                    select(discrepancy)
                    .where(
                        discrepancy.reconciliation_run_id == row.id,
                        discrepancy.broker_account_id == state.version.account_id,
                        discrepancy.created_at <= state.cutoff,
                        discrepancy.first_seen_at <= state.cutoff,
                    )
                    .order_by(discrepancy.id)
                    .limit(10001)
                )
            ),
            10000,
        )
        if len(items) != row.discrepancy_count:
            return state.unavailable(d.AlertReason.INCOMPLETE_COVERAGE)
        for item in items:
            state.reference(
                kind=ReportSourceKind.RECONCILIATION_DISCREPANCY,
                identifier=item.id,
                parent_id=row.id,
                effective_at=item.first_seen_at,
                known_at=item.created_at,
                digest=digest((item.id, item.discrepancy_type, item.severity)),
            )
        value = sum(
            1
            for item in items
            if state.predicate.discrepancy_severity is None
            or item.severity == state.predicate.discrepancy_severity.value
        )
    return d.AlertThresholdInput(observation=state.observation(value))


def capture_refresh(state: AlertCaptureState) -> d.AlertEventBatchInput:
    model = IngestionRunModel
    query = select(model).where(
        model.broker_account_id == state.version.account_id,
        model.status == "failed",
        model.completed_at > state.window.start_at,
        model.completed_at <= state.cutoff,
    )
    if state.predicate.capability_family is not None:
        query = query.where(
            model.effective_capabilities.contains([state.predicate.capability_family.value])
        )
    rows = bounded(
        list(state.session.scalars(query.order_by(model.completed_at, model.id).limit(10001))),
        10000,
    )
    state.context = replace(
        state.context,
        quality=QualityState.FRESH,
        method_key="canonical_refresh_outcome",
        method_version="1.0.0",
    )
    events = []
    for row in rows:
        assert row.completed_at is not None
        state.reference(
            kind=ReportSourceKind.INGESTION_RUN,
            identifier=row.id,
            digest=digest((row.id, row.request_fingerprint, row.status, row.completed_at)),
            effective_at=row.completed_at,
            known_at=row.completed_at,
        )
        capability = state.predicate.capability_family
        if capability is None and row.capability in {item.value for item in IngestionCapability}:
            capability = IngestionCapability(row.capability)
        events.append(
            d.AlertEventObservation(
                identity=row.id,
                economic_at=row.completed_at,
                first_eligible_at=row.completed_at,
                observation=state.observation(True),
                capability_family=capability,
            )
        )
    return d.AlertEventBatchInput(events=tuple(events), complete=True)


def capture_report_outcomes(state: AlertCaptureState) -> d.AlertEventBatchInput:
    # Append-only completion audits survive artifact expiry and mutable job projections.
    audit, job = AuditEventModel, ReportJobModel
    query = (
        select(audit, job)
        .join(job, audit.resource_id == sql_cast(job.id, String))
        .where(
            audit.owner_id == state.version.owner_id,
            audit.broker_account_id == state.version.account_id,
            job.owner_id == state.version.owner_id,
            job.account_id == state.version.account_id,
            audit.resource_type == "report_job",
            audit.action.in_(("report.job.completed", "report.job.failed")),
            audit.occurred_at > state.window.start_at,
            audit.occurred_at <= state.cutoff,
            job.requested_at <= state.cutoff,
        )
    )
    if state.predicate.report_type is not None:
        query = query.where(job.report_type == state.predicate.report_type.value)
    rows = bounded(
        list(state.session.execute(query.order_by(audit.occurred_at, audit.id).limit(10001))), 10000
    )
    state.context = replace(
        state.context,
        quality=QualityState.FRESH,
        method_key="report_terminal_outcome",
        method_version="1.0.0",
    )
    events = []
    for receipt, row in rows:
        outcome = (
            d.AlertReportOutcome.SUCCEEDED
            if receipt.action == "report.job.completed"
            else d.AlertReportOutcome.FAILED
        )
        if state.predicate.outcome not in {d.AlertReportOutcome.EITHER, outcome}:
            continue
        state.bindings.append(
            d.AlertCanonicalBinding(
                family=d.AlertCanonicalFamily.REPORT,
                role=d.AlertInputRole.RESULT,
                subject_id=row.id,
                parent_id=receipt.id,
                content_digest=digest(
                    (row.id, row.report_type, receipt.action, receipt.occurred_at, row.input_digest)
                ),
                method_key="report_terminal_outcome",
                method_version="1.0.0",
            )
        )
        events.append(
            d.AlertEventObservation(
                identity=row.id,
                economic_at=receipt.occurred_at,
                first_eligible_at=receipt.occurred_at,
                observation=state.observation(True),
                report_type=ReportType(row.report_type),
                report_outcome=outcome,
            )
        )
    return d.AlertEventBatchInput(events=tuple(events), complete=True)
