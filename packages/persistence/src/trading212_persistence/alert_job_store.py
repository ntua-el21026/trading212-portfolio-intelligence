"""One-slot admission and atomic fenced publication of actual immutable evaluations."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import alert_jobs as jobs
from trading212_application import alerts as app
from trading212_application.operational_telemetry import (
    AlertPublicationCounts,
    Operation,
    record_operation,
)
from trading212_domain.alert_serialization import decode_alert_input, encode_alert_result
from trading212_domain.alerts import (
    MAX_ALERT_RESULT_BYTES,
    AlertEvaluationInput,
    AlertEvaluationResult,
    AlertExecutionIntent,
    AlertReason,
)
from trading212_security.principals import AuthorizationError, Principal

from .alert_authorization import authorize_alert_job, authorize_alert_request
from .alert_base import alert_owner_lock, fail, rule_version
from .alert_events import apply_alert_result
from .alert_input_store import seal_alert_input
from .alert_job_transitions import AlertJobTransitions
from .alert_lifecycle import (
    aligned_slot,
    command_digest,
    eligible_interval,
    next_eligible_slot,
    next_slot,
)
from .alert_models import (
    ALERT_ADMISSION_SEQUENCE,
    AlertConditionModel,
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertInputSnapshotModel,
    AlertRuleModel,
    AlertRuleVersionModel,
)
from .alert_sources import authorize_alert_sources


class PostgresAlertJobStore(AlertJobTransitions):
    async def admit_due_evaluations(self, *, limit: int = 100) -> jobs.AlertAdmissionSummary:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Due admission is bounded to 100 slots.")

        def execute() -> jobs.AlertAdmissionSummary:
            at = self._now()
            # Reserve only operational ordering, then release every rule lock before
            # requesting the established owner/source locks. Failed or busy owners
            # retain their due slot but cannot monopolize a bounded candidate prefix.
            with self._sessions() as session, session.begin():
                rules = tuple(
                    session.scalars(
                        select(AlertRuleModel)
                        .where(
                            AlertRuleModel.lifecycle == "active",
                            AlertRuleModel.next_scheduled_for <= at,
                        )
                        .order_by(
                            AlertRuleModel.last_admission_sequence.asc().nulls_first(),
                            AlertRuleModel.next_scheduled_for,
                            AlertRuleModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                candidates = tuple((rule.id, rule.owner_id) for rule in rules)
                for reserved in rules:
                    sequence = session.scalar(ALERT_ADMISSION_SEQUENCE.next_value())
                    assert sequence is not None
                    reserved.last_admission_sequence = sequence
            admitted = 0
            for identifier, owner in candidates:
                with self._sessions() as session, session.begin():
                    if not alert_owner_lock(session, owner, wait=False):
                        continue
                    rule = session.scalar(
                        select(AlertRuleModel)
                        .where(AlertRuleModel.id == identifier, AlertRuleModel.owner_id == owner)
                        .with_for_update(skip_locked=True)
                    )
                    if (
                        rule is None
                        or rule.lifecycle != "active"
                        or rule.next_scheduled_for is None
                        or rule.next_scheduled_for > at
                    ):
                        continue
                    version = self._version(session, rule, rule.active_version_id)
                    slot = next_eligible_slot(session, version, rule.next_scheduled_for, through=at)
                    if slot is None:
                        rule.next_scheduled_for = aligned_slot(
                            version, at + timedelta(microseconds=1)
                        )
                        continue
                    existing = session.scalar(
                        select(AlertEvaluationJobModel.id).where(
                            AlertEvaluationJobModel.rule_version_id == version.id,
                            AlertEvaluationJobModel.scheduled_for == slot,
                        )
                    )
                    if existing is not None:
                        rule.next_scheduled_for = next_slot(version, slot)
                        continue
                    try:
                        with session.begin_nested():
                            authorization = authorize_alert_job(
                                session,
                                principal_id=rule.principal_id,
                                owner_id=rule.owner_id,
                                account_id=rule.account_id,
                                definition=rule_version(version).definition,
                                expires_at=self._now() + timedelta(days=90),
                                now=self._now(),
                            )
                            self._references(
                                session, authorization, rule_version(version).definition
                            )
                            value = self._capture(session, authorization).capture_evaluation(
                                rule_version(version), slot, AlertExecutionIntent.LIVE
                            )
                            if (
                                value.scheduled_for != slot
                                or value.execution_intent is not AlertExecutionIntent.LIVE
                            ):
                                fail(app.AlertServiceErrorCode.VALIDATION_FAILED)
                            job = seal_alert_input(
                                session, authorization, rule, value, now=self._now()
                            )
                            self._references(session, authorization, value.version.definition)
                            authorize_alert_sources(
                                session, authorization, input_id=job.input_id, now=self._now()
                            )
                            rule.next_scheduled_for = next_slot(version, slot)
                            self._audit_job(session, job, "created")
                            admitted += 1
                    except (AuthorizationError, app.AlertServiceError):
                        # Preserve the eligible slot; revoked access is not a false evaluation.
                        continue
            with self._sessions() as session:
                deferred = (
                    session.scalar(
                        select(AlertRuleModel.id)
                        .where(
                            AlertRuleModel.lifecycle == "active",
                            AlertRuleModel.next_scheduled_for <= self._now(),
                        )
                        .limit(1)
                    )
                    is not None
                )
            return jobs.AlertAdmissionSummary(
                admitted=admitted, deferred=deferred, observed_at=self._now()
            )

        return await self._worker_run(execute)

    async def backfill_evaluation(
        self,
        principal: Principal,
        request: app.AlertBackfillRequest,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> jobs.AlertEvaluationTaskMessage:
        def execute() -> jobs.AlertEvaluationTaskMessage:
            with self._sessions() as session, session.begin():
                owner = UUID(principal.owner_id)
                alert_owner_lock(session, owner)
                version = session.scalar(
                    select(AlertRuleVersionModel).where(
                        AlertRuleVersionModel.id == request.rule_version_id,
                        AlertRuleVersionModel.owner_id == owner,
                    )
                )
                if version is None:
                    fail(app.AlertServiceErrorCode.NOT_FOUND)
                assert version is not None
                rule = session.scalar(
                    select(AlertRuleModel)
                    .where(AlertRuleModel.id == version.rule_id)
                    .with_for_update()
                )
                assert rule is not None
                authorization = authorize_alert_request(
                    session,
                    principal,
                    account_id=rule.account_id,
                    definition=rule_version(version).definition,
                    write=True,
                    now=self._now(),
                )
                digest = command_digest(
                    "backfill", rule.account_id, str(version.id), request.scheduled_for.isoformat()
                )
                previous = self._command(
                    session,
                    authorization,
                    command="backfill",
                    idempotency_key=idempotency_key,
                    digest=digest,
                )
                existing = session.scalar(
                    select(AlertEvaluationJobModel).where(
                        AlertEvaluationJobModel.rule_version_id == version.id,
                        AlertEvaluationJobModel.scheduled_for == request.scheduled_for,
                    )
                )
                if previous is not None or existing is not None:
                    job = existing
                    if job is None:
                        assert previous is not None
                        job = session.get(AlertEvaluationJobModel, previous.result_id)
                    assert isinstance(job, AlertEvaluationJobModel)
                    if previous is None:
                        self._record_command(
                            session,
                            authorization,
                            command="backfill",
                            key=idempotency_key,
                            digest=digest,
                            result_id=job.id,
                            revision=rule.revision,
                            rule_id=rule.id,
                        )
                    authorization.check(session, now=self._now())
                    return self._evaluation_message(job)
                condition = session.scalar(
                    select(AlertConditionModel)
                    .where(AlertConditionModel.rule_version_id == version.id)
                    .with_for_update()
                )
                if (
                    condition is None
                    or condition.last_applied_scheduled_for is None
                    or request.scheduled_for >= condition.last_applied_scheduled_for
                    or aligned_slot(version, request.scheduled_for) != request.scheduled_for
                    or eligible_interval(session, version, request.scheduled_for) is None
                ):
                    fail(app.AlertServiceErrorCode.INVALID_STATE_TRANSITION)
                self._references(session, authorization, rule_version(version).definition)
                value = self._capture(session, authorization).capture_evaluation(
                    rule_version(version), request.scheduled_for, AlertExecutionIntent.OBSERVE_ONLY
                )
                if (
                    value.execution_intent is not AlertExecutionIntent.OBSERVE_ONLY
                    or value.scheduled_for != request.scheduled_for
                ):
                    fail(app.AlertServiceErrorCode.VALIDATION_FAILED)
                job = seal_alert_input(session, authorization, rule, value, now=self._now())
                self._record_command(
                    session,
                    authorization,
                    command="backfill",
                    key=idempotency_key,
                    digest=digest,
                    result_id=job.id,
                    revision=rule.revision,
                    rule_id=rule.id,
                )
                self._audit_job(session, job, "created")
                authorization.check(session, now=self._now())
                return self._evaluation_message(job)

        return await self._run(execute)

    def _evaluation_message(self, job: AlertEvaluationJobModel) -> jobs.AlertEvaluationTaskMessage:
        message = self._message(job)
        assert isinstance(message, jobs.AlertEvaluationTaskMessage)
        return message

    def _input(self, session: Session, job: AlertEvaluationJobModel) -> AlertEvaluationInput:
        self._job_authorization(session, job)
        row = session.get(AlertInputSnapshotModel, job.input_id)
        if (
            row is None
            or row.sealed_at is None
            or row.purged_at is not None
            or row.expires_at <= self._now()
        ):
            raise jobs.AlertJobInputError(AlertReason.SOURCE_EXPIRED)
        payload = row.payload
        if (
            payload is None
            or hashlib.sha256(payload).hexdigest() != job.input_digest
            or len(payload) != row.byte_length
        ):
            raise jobs.AlertJobInputError(AlertReason.AMBIGUOUS_SOURCE)
        value = decode_alert_input(payload)
        if (
            value.version.id,
            value.version.rule_id,
            value.version.owner_id,
            value.version.account_id,
            value.scheduled_for,
            value.execution_intent.value,
        ) != (
            job.rule_version_id,
            job.rule_id,
            job.owner_id,
            job.account_id,
            job.scheduled_for,
            job.execution_intent,
        ):
            raise jobs.AlertJobInputError(AlertReason.AMBIGUOUS_SOURCE)
        return value

    async def load_evaluation_input(
        self, claim: jobs.AlertEvaluationJobClaim
    ) -> AlertEvaluationInput:
        def execute() -> AlertEvaluationInput:
            with self._sessions() as session, session.begin():
                alert_owner_lock(session, claim.message.owner_id)
                job = self._live(session, claim)
                if not isinstance(job, AlertEvaluationJobModel):
                    raise jobs.AlertJobInputError(AlertReason.LEASE_EXPIRED)
                return self._input(session, job)

        return await self._worker_run(execute)

    async def complete_evaluation_job(
        self, claim: jobs.AlertEvaluationJobClaim, *, result: AlertEvaluationResult
    ) -> bool:
        payload = encode_alert_result(result)
        if len(payload) > MAX_ALERT_RESULT_BYTES:
            raise jobs.AlertJobInputError(AlertReason.INPUT_BOUND_EXCEEDED)

        def execute() -> tuple[bool, AlertPublicationCounts | None]:
            with self._sessions() as session, session.begin():
                alert_owner_lock(session, claim.message.owner_id)
                job = self._live(session, claim)
                if not isinstance(job, AlertEvaluationJobModel):
                    return False, None
                value = self._input(session, job)
                if (
                    result.rule_version_id,
                    result.input_digest,
                    result.scheduled_for,
                    result.execution_intent,
                    result.contexts,
                ) != (
                    value.version.id,
                    job.input_digest,
                    value.scheduled_for,
                    value.execution_intent,
                    value.contexts,
                ):
                    raise jobs.AlertJobInputError(AlertReason.AMBIGUOUS_SOURCE)
                with session.begin_nested() as savepoint:
                    row = AlertEvaluationModel(
                        id=uuid4(),
                        owner_id=job.owner_id,
                        account_id=job.account_id,
                        job_id=job.id,
                        input_id=job.input_id,
                        rule_version_id=job.rule_version_id,
                        publication_fence=job.fence,
                        created_at=self._now(),
                        input_digest=job.input_digest,
                        method_name=result.method_key,
                        method_version=result.method_version,
                        outcome=result.outcome.value,
                        decision=result.decision,
                        scheduled_for=job.scheduled_for,
                        evaluated_at=self._now(),
                        content_digest=hashlib.sha256(payload).hexdigest(),
                        byte_length=len(payload),
                        payload=payload,
                        expires_at=job.expires_at,
                        purged_at=None,
                    )
                    session.add(row)
                    session.flush()
                    observations = apply_alert_result(
                        session, value, result, row, principal_id=job.principal_id, now=self._now()
                    )
                    session.flush()
                    if self._live(session, claim) is None:
                        savepoint.rollback()
                        return False, None
                    self._job_authorization(session, job)
                    job.state = "succeeded"
                    job.completed_at = self._now()
                    job.failure_code = None
                    job.lease_id = None
                    job.lease_expires_at = None
                    job.consumer_id = None
                    self._attempt(
                        session,
                        job,
                        phase="consumer",
                        attempt=job.consumer_attempts,
                        outcome="succeeded",
                    )
                    self._audit_job(session, job, "completed")
                return True, observations

        retained, observations = await self._worker_run(execute)
        if retained:
            record_operation(Operation.ALERT_EVALUATION, result.outcome.value)
            assert observations is not None
            observations.record()
        return retained
