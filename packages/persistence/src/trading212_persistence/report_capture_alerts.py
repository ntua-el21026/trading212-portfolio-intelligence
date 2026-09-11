"""As-known alert exports from actual retained evaluations and lifecycle records."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_domain import alerts as a
from trading212_domain import reports as r
from trading212_domain.alert_serialization import decode_alert_input, decode_alert_result
from trading212_domain.enums import QualityState
from trading212_domain.report_schema import ALERT_EXPORT_TABLES

from .alert_base import rule_version
from .alert_models import (
    AlertAcknowledgmentModel,
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertEventModel,
    AlertEventTransitionModel,
    AlertInputSnapshotModel,
    AlertRuleVersionModel,
    InAppNotificationModel,
)
from .alert_sources import authorize_alert_sources
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_builder import ReportBuilder
from .report_capture_alert_values import emit, project_evaluation, project_version


def _unavailable() -> None:
    raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)


def _metadata(builder: ReportBuilder) -> r.ReportContext:
    context = r.ReportContext(
        key="context.alerts",
        family=r.ReportFamily.ALERTS,
        method_key=a.ALERT_METHOD,
        method_version=a.ALERT_METHOD_VERSION,
        valuation_at=builder.valuation_at,
        source_cutoff_at=builder.selection.source_cutoff_at,
        quality=QualityState.FRESH,
        provenance_set_key="sources.alerts",
        coverage_set_key="coverage.alerts",
        note_set_key="notes.alerts",
    )
    builder.add_context(context)
    return context


def _read_evaluation(
    session: Session,
    authorization: ReportAuthorization,
    row: AlertEvaluationModel,
    version: a.AlertRuleVersion,
    *,
    now: datetime,
) -> tuple[a.AlertEvaluationInput, a.AlertEvaluationResult, datetime] | None:
    # Safe scalar tombstones remain inspectable. Licensed payloads are never read
    # before both the normalized source/EXPORT check and the retained expiry check.
    if row.purged_at is not None or row.expires_at <= now:
        return None
    authorize_alert_sources(session, authorization, input_id=row.input_id, now=now, export=True)
    snapshot = session.get(AlertInputSnapshotModel, row.input_id)
    if snapshot is None or snapshot.purged_at is not None or snapshot.expires_at <= now:
        _unavailable()
    assert snapshot is not None
    if (
        snapshot.owner_id != authorization.owner_id
        or snapshot.account_id != authorization.account_id
        or snapshot.rule_version_id != version.id
        or snapshot.input_digest != row.input_digest
        or snapshot.scheduled_for != row.scheduled_for
        or snapshot.sealed_at is None
    ):
        _unavailable()
    input_bytes, result_bytes = snapshot.payload, row.payload
    if (
        input_bytes is None
        or result_bytes is None
        or len(input_bytes) != snapshot.byte_length
        or len(result_bytes) != row.byte_length
        or sha256(input_bytes).hexdigest() != row.input_digest
        or sha256(result_bytes).hexdigest() != row.content_digest
    ):
        _unavailable()
    assert input_bytes is not None and result_bytes is not None
    captured, result = decode_alert_input(input_bytes), decode_alert_result(result_bytes)
    if (
        captured.version != version
        or result.rule_version_id != version.id
        or result.input_digest != row.input_digest
        or result.scheduled_for != row.scheduled_for
        or captured.scheduled_for != row.scheduled_for
        or captured.contexts != result.contexts
        or result.outcome.value != row.outcome
        or result.decision is not row.decision
        or result.method_key != row.method_name
        or result.method_version != row.method_version
    ):
        _unavailable()
    return captured, result, min(snapshot.expires_at, row.expires_at)


def _evaluation(
    builder: ReportBuilder,
    session: Session,
    authorization: ReportAuthorization,
    context: r.ReportContext,
    row: AlertEvaluationModel,
    *,
    now: datetime,
    versions: set[UUID],
) -> None:
    stored_version = session.get(AlertRuleVersionModel, row.rule_version_id)
    job = session.get(AlertEvaluationJobModel, row.job_id)
    if (
        stored_version is None
        or job is None
        or row.owner_id != authorization.owner_id
        or row.account_id != authorization.account_id
        or stored_version.owner_id != authorization.owner_id
        or stored_version.account_id != authorization.account_id
        or job.owner_id != authorization.owner_id
        or job.account_id != authorization.account_id
        or job.rule_version_id != row.rule_version_id
        or job.input_id != row.input_id
        or job.input_digest != row.input_digest
        or job.state != "succeeded"
    ):
        _unavailable()
    assert stored_version is not None and job is not None
    version = rule_version(stored_version)
    loaded = _read_evaluation(session, authorization, row, version, now=now)
    captured, result, deadline = loaded if loaded else (None, None, None)
    emit(
        builder,
        context,
        r.ReportTableKey.ALERT_EVALUATIONS,
        f"alert.evaluation.{row.id}",
        {
            "evaluation_id": row.id,
            "job_id": row.job_id,
            "input_id": row.input_id,
            "rule_id": version.rule_id,
            "rule_version_id": version.id,
            "input_digest": row.input_digest,
            "result_digest": row.content_digest,
            "rule_content_digest": version.content_digest,
            "scheduled_for": row.scheduled_for,
            "source_cutoff_at": row.scheduled_for,
            "evaluated_at": row.evaluated_at,
            "recorded_at": row.created_at,
            "execution_intent": job.execution_intent,
            "outcome": row.outcome,
            "decision": result.decision if result else None,
            "reason": result.reason if result else None,
            "reproducibility": "retained" if loaded else "expired",
            "expires_at": row.expires_at,
            "method_key": row.method_name,
            "method_version": row.method_version,
            "schema_version": result.schema_version if result else None,
            "window_start_at": captured.observation_window.start_at if captured else None,
            "window_end_at": captured.observation_window.end_at if captured else None,
            "newly_known_revisions": captured.observation_window.newly_known_revisions
            if captured
            else None,
            "active_interval_id": captured.observation_window.active_interval_id
            if captured
            else None,
        },
    )
    if loaded is None:
        return
    assert captured is not None and result is not None
    assert deadline is not None
    builder.limit_copy_expiry(deadline)
    if version.id not in versions:
        project_version(builder, context, version)
        versions.add(version.id)
    for role, identity, digest in (
        (r.ReportInputRole.INPUT, row.input_id, row.input_digest),
        (r.ReportInputRole.RESULT, row.id, row.content_digest),
    ):
        builder.add_binding(
            r.ReportBinding(
                family=r.ReportFamily.ALERTS,
                role=role,
                subject_id=identity,
                content_digest=digest,
                parent_id=version.id,
                method_key=result.method_key,
                method_version=result.method_version,
            )
        )
    project_evaluation(builder, context, evaluation_id=row.id, captured=captured, result=result)


def _event(
    builder: ReportBuilder,
    session: Session,
    context: r.ReportContext,
    row: AlertEventModel,
    *,
    cutoff: datetime,
) -> None:
    # Project only immutable facts and transitions actually recorded by the cutoff.
    # Current row.state/revision and current external delivery attempts are not historical evidence.
    transitions = session.scalars(
        select(AlertEventTransitionModel)
        .where(
            AlertEventTransitionModel.event_id == row.id,
            AlertEventTransitionModel.owner_id == row.owner_id,
            AlertEventTransitionModel.account_id == row.account_id,
            AlertEventTransitionModel.occurred_at <= cutoff,
            AlertEventTransitionModel.created_at <= cutoff,
        )
        .order_by(AlertEventTransitionModel.sequence)
        .limit(r.MAX_REPORT_DATASET_ROWS + 1)
    )
    resolution: AlertEventTransitionModel | None = None
    for count, transition in enumerate(transitions, start=1):
        r.report_limit(count <= r.MAX_REPORT_DATASET_ROWS, "rows")
        if transition.kind == "resolved":
            resolution = transition
        emit(
            builder,
            context,
            r.ReportTableKey.ALERT_TRANSITIONS,
            f"alert.transition.{transition.id}",
            {
                "transition_id": transition.id,
                "event_id": row.id,
                "evaluation_id": transition.evaluation_id,
                "principal_id": transition.principal_id,
                "sequence": transition.sequence,
                "kind": transition.kind,
                "reason": transition.reason,
                "occurred_at": transition.occurred_at,
                "note": transition.note,
            },
        )
    emit(
        builder,
        context,
        r.ReportTableKey.ALERT_EVENTS,
        f"alert.event.{row.id}",
        {
            "event_id": row.id,
            "evaluation_id": row.evaluation_id,
            "rule_id": row.rule_id,
            "rule_version_id": row.rule_version_id,
            "family": row.family,
            "severity": row.severity,
            "occurred_at": row.occurred_at,
            "recorded_at": row.created_at,
            "episode_state": "resolved" if resolution else "open",
            "resolved_at": resolution.occurred_at if resolution else None,
            "resolution_reason": resolution.reason if resolution else None,
            "correction_of": row.correction_of_id,
            "episode_ordinal": row.episode_ordinal,
            "event_identity": row.event_identity,
            "event_revision_id": row.event_revision_id,
            "deduplication_digest": row.dedup_digest,
            "notification_state": row.notification_state,
        },
    )
    for count, ack in enumerate(
        session.scalars(
            select(AlertAcknowledgmentModel)
            .where(
                AlertAcknowledgmentModel.event_id == row.id,
                AlertAcknowledgmentModel.owner_id == row.owner_id,
                AlertAcknowledgmentModel.account_id == row.account_id,
                AlertAcknowledgmentModel.acknowledged_at <= cutoff,
                AlertAcknowledgmentModel.created_at <= cutoff,
            )
            .order_by(AlertAcknowledgmentModel.acknowledged_at, AlertAcknowledgmentModel.id)
            .limit(r.MAX_REPORT_DATASET_ROWS + 1)
        ),
        start=1,
    ):
        r.report_limit(count <= r.MAX_REPORT_DATASET_ROWS, "rows")
        emit(
            builder,
            context,
            r.ReportTableKey.ALERT_ACKNOWLEDGMENTS,
            f"alert.ack.{ack.id}",
            {
                "acknowledgment_id": ack.id,
                "event_id": row.id,
                "principal_id": ack.principal_id,
                "acknowledged_at": ack.acknowledged_at,
                "note": ack.note,
            },
        )
    notification = session.scalar(
        select(InAppNotificationModel).where(
            InAppNotificationModel.event_id == row.id,
            InAppNotificationModel.owner_id == row.owner_id,
            InAppNotificationModel.account_id == row.account_id,
            InAppNotificationModel.created_at <= cutoff,
        )
    )
    if notification:
        emit(
            builder,
            context,
            r.ReportTableKey.ALERT_NOTIFICATIONS,
            f"alert.notification.{notification.id}",
            {
                "notification_id": notification.id,
                "event_id": row.id,
                "created_at": notification.created_at,
                "eligibility": notification.eligibility,
            },
        )


def capture_alerts(
    builder: ReportBuilder,
    session: Session,
    authorization: ReportAuthorization,
    *,
    clock: Callable[[], datetime],
) -> None:
    selection = builder.selection
    if (
        not isinstance(selection, r.ExportSelection)
        or selection.dataset is not r.ExportDataset.ALERTS
    ):
        return
    authorization.check(session, now=clock())
    context = _metadata(builder)
    for table in ALERT_EXPORT_TABLES:
        builder.append_dataset_row(table, None)
    start = datetime.combine(selection.start_date, time.min, UTC)
    end = datetime.combine(selection.end_date + timedelta(days=1), time.min, UTC)
    cutoff = selection.source_cutoff_at
    event_filters = (
        AlertEventModel.owner_id == authorization.owner_id,
        AlertEventModel.account_id == authorization.account_id,
        AlertEventModel.created_at <= cutoff,
        AlertEventModel.occurred_at >= start,
        AlertEventModel.occurred_at < end,
    )
    # Suppressions/no-match evaluations are independently inspectable. An event's
    # economic date can precede its evaluation slot, so include its complete evaluation too.
    selected_event = exists(
        select(AlertEventModel.id).where(
            *event_filters,
            AlertEventModel.evaluation_id == AlertEvaluationModel.id,
        )
    )
    rows = session.scalars(
        select(AlertEvaluationModel)
        .where(
            AlertEvaluationModel.owner_id == authorization.owner_id,
            AlertEvaluationModel.account_id == authorization.account_id,
            AlertEvaluationModel.created_at <= cutoff,
            or_(
                (AlertEvaluationModel.scheduled_for >= start)
                & (AlertEvaluationModel.scheduled_for < end),
                selected_event,
            ),
        )
        .order_by(AlertEvaluationModel.created_at, AlertEvaluationModel.id)
        .limit(r.MAX_REPORT_DATASET_ROWS + 1)
        .execution_options(yield_per=32)
    )
    versions: set[UUID] = set()
    evaluations: set[UUID] = set()
    for count, row in enumerate(rows, start=1):
        r.report_limit(count <= r.MAX_REPORT_DATASET_ROWS, "rows")
        _evaluation(builder, session, authorization, context, row, now=clock(), versions=versions)
        evaluations.add(row.id)
    events = session.scalars(
        select(AlertEventModel)
        .where(*event_filters)
        .order_by(AlertEventModel.created_at, AlertEventModel.id)
        .limit(r.MAX_REPORT_DATASET_ROWS + 1)
        .execution_options(yield_per=32)
    )
    for count, event in enumerate(events, start=1):
        r.report_limit(count <= r.MAX_REPORT_DATASET_ROWS, "rows")
        if event.evaluation_id not in evaluations:
            _unavailable()
        _event(builder, session, context, event, cutoff=cutoff)
    authorization.check(session, now=clock())
