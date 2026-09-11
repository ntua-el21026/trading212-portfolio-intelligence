"""Fixed evaluation/delivery lease transitions, preserving late callback and retry semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import cast
from uuid import uuid4

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased
from trading212_application import alert_jobs as jobs
from trading212_application import alerts as app
from trading212_domain.alerts import AlertExecutionIntent, AlertReason
from trading212_security.principals import AuthorizationError

from .alert_authorization import AlertAuthorization, authorize_alert_job
from .alert_base import ACTOR as _ACTOR
from .alert_base import AlertStore, alert_owner_lock, rule_version
from .alert_models import (
    AlertEvaluationAttemptModel,
    AlertEvaluationJobModel,
    AlertEvaluationOutboxModel,
    AlertEventModel,
    AlertRuleEventModel,
    AlertRuleModel,
    AlertRuleVersionModel,
    NotificationDeliveryAttemptModel,
    NotificationDeliveryJobModel,
    NotificationDeliveryOutboxModel,
    NotificationDestinationModel,
    NotificationDestinationVersionModel,
)
from .alert_sources import authorize_alert_sources
from .models import AuditEventModel

type StoredAlertJob = AlertEvaluationJobModel | NotificationDeliveryJobModel
type TaskMessage = jobs.AlertEvaluationTaskMessage | jobs.AlertNotificationTaskMessage
type JobClaim = jobs.AlertEvaluationJobClaim | jobs.AlertNotificationJobClaim
type DispatchClaim = jobs.AlertEvaluationDispatchClaim | jobs.AlertNotificationDispatchClaim
type Outbox = AlertEvaluationOutboxModel | NotificationDeliveryOutboxModel


class AlertJobTransitions(AlertStore):
    async def _worker_run[T](self, operation: Callable[[], T]) -> T:
        def execute() -> T:
            try:
                return operation()
            except AuthorizationError:
                raise jobs.AlertJobInputError(AlertReason.ACCESS_DENIED) from None
            except app.AlertServiceError as error:
                if error.code is app.AlertServiceErrorCode.ACCESS_DENIED:
                    code = AlertReason.ACCESS_DENIED
                elif error.code in {
                    app.AlertServiceErrorCode.INPUT_BOUND_EXCEEDED,
                    app.AlertServiceErrorCode.RESULT_TOO_LARGE,
                }:
                    code = AlertReason.INPUT_BOUND_EXCEEDED
                else:
                    code = AlertReason.MISSING_INPUT
                raise jobs.AlertJobInputError(code) from None
            except SQLAlchemyError:
                raise jobs.AlertJobInputError(
                    AlertReason.STORAGE_UNAVAILABLE, retryable=True
                ) from None

        return await asyncio.to_thread(execute)

    def _message(self, job: StoredAlertJob) -> TaskMessage:
        if isinstance(job, AlertEvaluationJobModel):
            return jobs.AlertEvaluationTaskMessage(
                job_id=job.id,
                owner_id=job.owner_id,
                account_id=job.account_id,
                rule_version_id=job.rule_version_id,
                capture_id=job.input_id,
                input_digest=job.input_digest,
                scheduled_for=job.scheduled_for,
                execution_intent=AlertExecutionIntent(job.execution_intent),
            )
        return jobs.AlertNotificationTaskMessage(
            delivery_id=job.id,
            owner_id=job.owner_id,
            account_id=job.account_id,
            event_id=job.event_id,
            destination_version_id=job.destination_version_id,
            payload_digest=job.payload_digest,
        )

    def _lookup(self, session: Session, message: TaskMessage) -> StoredAlertJob | None:
        model = (
            AlertEvaluationJobModel
            if isinstance(message, jobs.AlertEvaluationTaskMessage)
            else NotificationDeliveryJobModel
        )
        identifier = (
            message.job_id
            if isinstance(message, jobs.AlertEvaluationTaskMessage)
            else message.delivery_id
        )
        # Rule lock always precedes evaluation lease/event locks under the owner/source lock.
        if isinstance(message, jobs.AlertEvaluationTaskMessage):
            rule_id = session.scalar(
                select(AlertEvaluationJobModel.rule_id).where(
                    AlertEvaluationJobModel.id == identifier,
                    AlertEvaluationJobModel.owner_id == message.owner_id,
                )
            )
            if rule_id is not None:
                session.execute(
                    select(AlertRuleModel.id).where(AlertRuleModel.id == rule_id).with_for_update()
                )
        row = session.scalar(
            select(model)
            .where(
                model.id == identifier,
                model.owner_id == message.owner_id,
                model.account_id == message.account_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (
            cast(StoredAlertJob, row)
            if row is not None and self._message(cast(StoredAlertJob, row)) == message
            else None
        )

    def _outbox(self, session: Session, job: StoredAlertJob) -> Outbox:
        model: type[AlertEvaluationOutboxModel] | type[NotificationDeliveryOutboxModel] = (
            AlertEvaluationOutboxModel
            if isinstance(job, AlertEvaluationJobModel)
            else NotificationDeliveryOutboxModel
        )
        row = session.scalar(
            select(model)
            .where(model.owner_id == job.owner_id, model.job_id == job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise jobs.AlertJobInputError(AlertReason.AMBIGUOUS_SOURCE)
        return cast(Outbox, row)

    def _attempt(
        self,
        session: Session,
        job: StoredAlertJob,
        *,
        phase: str,
        attempt: int,
        outcome: str,
        failure: AlertReason | None = None,
    ) -> None:
        model = (
            AlertEvaluationAttemptModel
            if isinstance(job, AlertEvaluationJobModel)
            else NotificationDeliveryAttemptModel
        )
        session.add(
            model(
                id=uuid4(),
                owner_id=job.owner_id,
                job_id=job.id,
                created_at=self._now(),
                phase=phase,
                attempt=attempt,
                fence=job.fence,
                outcome=outcome,
                failure_code=failure.value if failure else None,
            )
        )

    def _terminal(
        self, session: Session, job: StoredAlertJob, failure: AlertReason, *, expired: bool = False
    ) -> None:
        job.state = "expired" if expired else "failed"
        job.failure_code = failure.value
        job.completed_at = self._now()
        job.lease_id = None
        job.lease_expires_at = None
        job.consumer_id = None
        outbox = self._outbox(session, job)
        outbox.state = "failed"
        outbox.claim_token = None
        outbox.claim_expires_at = None
        outbox.dispatcher_id = None
        outbox.failure_code = failure.value
        self._audit_job(session, job, "expired" if expired else "failed", failure)

    async def _claim_dispatches(
        self, *, notification: bool, dispatcher_id: str, limit: int
    ) -> tuple[DispatchClaim, ...]:
        if not _ACTOR.fullmatch(dispatcher_id) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("A bounded dispatcher identity and batch are required.")
        model: type[AlertEvaluationOutboxModel] | type[NotificationDeliveryOutboxModel] = (
            NotificationDeliveryOutboxModel if notification else AlertEvaluationOutboxModel
        )
        job_model: type[AlertEvaluationJobModel] | type[NotificationDeliveryJobModel] = (
            NotificationDeliveryJobModel if notification else AlertEvaluationJobModel
        )

        def execute() -> tuple[DispatchClaim, ...]:
            at = self._now()
            with self._sessions() as session:
                statement = (
                    select(model.id, model.owner_id, model.job_id)
                    .join(job_model, job_model.id == model.job_id)
                    .where(
                        job_model.state.in_(("queued", "running")),
                        or_(job_model.state == "queued", job_model.lease_expires_at <= at),
                        or_(
                            and_(
                                model.state.in_(("pending", "published")), model.available_at <= at
                            ),
                            and_(model.state == "claimed", model.claim_expires_at <= at),
                        ),
                    )
                )
                if not notification:
                    # Inhibited later/paused slots must not occupy a bounded candidate prefix.
                    # Archived/superseded work remains eligible for its audited cancellation.
                    earlier = aliased(AlertEvaluationJobModel)
                    predecessor = exists(
                        select(earlier.id).where(
                            earlier.owner_id == AlertEvaluationJobModel.owner_id,
                            earlier.rule_version_id == AlertEvaluationJobModel.rule_version_id,
                            earlier.execution_intent == "live",
                            earlier.scheduled_for < AlertEvaluationJobModel.scheduled_for,
                            earlier.state.in_(("queued", "running")),
                        )
                    ).correlate(AlertEvaluationJobModel)
                    lifecycle = exists(
                        select(AlertRuleModel.id).where(
                            AlertRuleModel.id == AlertEvaluationJobModel.rule_id,
                            AlertRuleModel.owner_id == AlertEvaluationJobModel.owner_id,
                            or_(
                                AlertRuleModel.lifecycle == "archived",
                                AlertRuleModel.active_version_id
                                != AlertEvaluationJobModel.rule_version_id,
                                and_(
                                    AlertRuleModel.lifecycle == "active",
                                    or_(
                                        AlertRuleModel.next_scheduled_for.is_(None),
                                        AlertRuleModel.next_scheduled_for
                                        >= AlertEvaluationJobModel.scheduled_for,
                                    ),
                                    ~predecessor,
                                ),
                            ),
                        )
                    ).correlate(AlertEvaluationJobModel)
                    statement = statement.where(
                        or_(AlertEvaluationJobModel.execution_intent == "observe_only", lifecycle)
                    )
                candidates = tuple(
                    session.execute(statement.order_by(model.available_at, model.id).limit(limit))
                )
            claims: list[DispatchClaim] = []
            for identifier, owner, job_id in candidates:
                with self._sessions() as session, session.begin():
                    if not alert_owner_lock(session, owner, wait=False):
                        continue
                    row = session.scalar(
                        select(model)
                        .where(model.id == identifier, model.owner_id == owner)
                        .with_for_update(skip_locked=True)
                        .execution_options(populate_existing=True)
                    )
                    job = session.scalar(
                        select(job_model)
                        .where(job_model.id == job_id, job_model.owner_id == owner)
                        .with_for_update(skip_locked=True)
                        .execution_options(populate_existing=True)
                    )
                    at = self._now()
                    if row is None or job is None or job.state not in {"queued", "running"}:
                        continue
                    job = cast(StoredAlertJob, job)
                    if (
                        job.state == "running"
                        and job.lease_expires_at is not None
                        and job.lease_expires_at > at
                    ):
                        continue
                    if (
                        row.state == "failed"
                        or (
                            row.state == "claimed"
                            and row.claim_expires_at is not None
                            and row.claim_expires_at > at
                        )
                        or row.available_at > at
                    ):
                        continue
                    if not self._eligible(session, job):
                        continue
                    if job.expires_at <= at:
                        self._terminal(session, job, AlertReason.MISSING_INPUT, expired=True)
                        continue
                    if row.publication_attempts >= 8 or job.consumer_attempts >= 4:
                        self._terminal(session, job, AlertReason.ATTEMPTS_EXHAUSTED)
                        continue
                    try:
                        self._job_authorization(session, job)
                    except (AuthorizationError, app.AlertServiceError):
                        self._terminal(session, job, AlertReason.ACCESS_DENIED)
                        continue
                    row.state = "claimed"
                    row.claim_token = uuid4()
                    row.claim_expires_at = at + timedelta(seconds=30)
                    row.dispatcher_id = dispatcher_id
                    row.publication_attempts += 1
                    row.failure_code = None
                    self._attempt(
                        session,
                        job,
                        phase="dispatch",
                        attempt=row.publication_attempts,
                        outcome="claimed",
                    )
                    message = self._message(job)
                    if isinstance(message, jobs.AlertEvaluationTaskMessage):
                        claims.append(
                            jobs.AlertEvaluationDispatchClaim(
                                message=message,
                                claim_token=row.claim_token,
                                claim_expires_at=row.claim_expires_at,
                                publication_attempt=row.publication_attempts,
                            )
                        )
                    else:
                        claims.append(
                            jobs.AlertNotificationDispatchClaim(
                                message=message,
                                claim_token=row.claim_token,
                                claim_expires_at=row.claim_expires_at,
                                publication_attempt=row.publication_attempts,
                            )
                        )
            return tuple(claims)

        return await self._worker_run(execute)

    async def claim_evaluation_dispatches(
        self, *, dispatcher_id: str, limit: int = 20
    ) -> tuple[jobs.AlertEvaluationDispatchClaim, ...]:
        return cast(
            tuple[jobs.AlertEvaluationDispatchClaim, ...],
            await self._claim_dispatches(
                notification=False, dispatcher_id=dispatcher_id, limit=limit
            ),
        )

    async def claim_notification_dispatches(
        self, *, dispatcher_id: str, limit: int = 20
    ) -> tuple[jobs.AlertNotificationDispatchClaim, ...]:
        return cast(
            tuple[jobs.AlertNotificationDispatchClaim, ...],
            await self._claim_dispatches(
                notification=True, dispatcher_id=dispatcher_id, limit=limit
            ),
        )

    async def _dispatch_transition(self, claim: DispatchClaim, failure: AlertReason | None) -> bool:
        def execute() -> bool:
            with self._sessions() as session, session.begin():
                alert_owner_lock(session, claim.message.owner_id)
                job = self._lookup(session, claim.message)
                # Delivery can complete before its publisher returns. Preserve the
                # terminal result and historical claim without inventing an ack.
                if job is None or job.state not in {"queued", "running"}:
                    return False
                row = self._outbox(session, job)
                if (
                    row.state != "claimed"
                    or row.claim_token != claim.claim_token
                    or row.publication_attempts != claim.publication_attempt
                    or row.claim_expires_at is None
                    or row.claim_expires_at <= self._now()
                ):
                    return False
                self._attempt(
                    session,
                    job,
                    phase="dispatch",
                    attempt=row.publication_attempts,
                    outcome="published" if failure is None else "retry",
                    failure=failure,
                )
                row.claim_token = None
                row.claim_expires_at = None
                row.dispatcher_id = None
                if failure is None:
                    row.state = "published"
                    row.published_at = self._now()
                    row.available_at = self._now() + timedelta(seconds=60)
                    row.failure_code = None
                elif (
                    job.state == "running"
                    and job.lease_expires_at is not None
                    and job.lease_expires_at > self._now()
                ):
                    row.state = "published"
                    row.available_at = job.lease_expires_at
                    row.failure_code = failure.value
                elif row.publication_attempts >= 8:
                    self._terminal(session, job, AlertReason.ATTEMPTS_EXHAUSTED)
                else:
                    row.state = "pending"
                    row.failure_code = failure.value
                    row.available_at = self._now() + timedelta(
                        seconds=min(2 ** (row.publication_attempts - 1), 60)
                    )
                return True

        return await self._worker_run(execute)

    async def acknowledge_evaluation_dispatch(
        self, claim: jobs.AlertEvaluationDispatchClaim
    ) -> bool:
        return await self._dispatch_transition(claim, None)

    async def acknowledge_notification_dispatch(
        self, claim: jobs.AlertNotificationDispatchClaim
    ) -> bool:
        return await self._dispatch_transition(claim, None)

    async def defer_evaluation_dispatch(
        self, claim: jobs.AlertEvaluationDispatchClaim, *, failure: AlertReason
    ) -> bool:
        return await self._dispatch_transition(claim, failure)

    async def defer_notification_dispatch(
        self, claim: jobs.AlertNotificationDispatchClaim, *, failure: AlertReason
    ) -> bool:
        return await self._dispatch_transition(claim, failure)

    async def _claim_job(self, message: TaskMessage, consumer_id: str) -> JobClaim | None:
        if not _ACTOR.fullmatch(consumer_id):
            raise ValueError("A bounded consumer identity is required.")

        def execute() -> JobClaim | None:
            with self._sessions() as session, session.begin():
                alert_owner_lock(session, message.owner_id)
                job = self._lookup(session, message)
                at = self._now()
                if job is None or job.state not in {"queued", "running"} or job.available_at > at:
                    return None
                if (
                    job.state == "running"
                    and job.lease_expires_at is not None
                    and job.lease_expires_at > at
                ):
                    return None
                if not self._eligible(session, job):
                    return None
                if job.expires_at <= at:
                    self._terminal(session, job, AlertReason.MISSING_INPUT, expired=True)
                    return None
                if job.consumer_attempts >= 4:
                    self._terminal(session, job, AlertReason.ATTEMPTS_EXHAUSTED)
                    return None
                try:
                    self._job_authorization(session, job)
                except (AuthorizationError, app.AlertServiceError):
                    self._terminal(session, job, AlertReason.ACCESS_DENIED)
                    return None
                if isinstance(job, AlertEvaluationJobModel):
                    rule = session.get(AlertRuleModel, job.rule_id)
                    assert rule is not None
                    job.lifecycle_sequence = rule.lifecycle_sequence
                job.state = "running"
                job.consumer_attempts += 1
                job.fence += 1
                job.lease_id = uuid4()
                job.lease_expires_at = at + timedelta(seconds=60)
                job.heartbeat_at = at
                job.consumer_id = consumer_id
                job.failure_code = None
                self._attempt(
                    session, job, phase="consumer", attempt=job.consumer_attempts, outcome="claimed"
                )
                if isinstance(message, jobs.AlertEvaluationTaskMessage):
                    return jobs.AlertEvaluationJobClaim(
                        message=message,
                        lease_id=job.lease_id,
                        fence=job.fence,
                        lease_expires_at=job.lease_expires_at,
                        consumer_attempt=job.consumer_attempts,
                        lifecycle_sequence=cast(AlertEvaluationJobModel, job).lifecycle_sequence,
                    )
                return jobs.AlertNotificationJobClaim(
                    message=message,
                    lease_id=job.lease_id,
                    fence=job.fence,
                    lease_expires_at=job.lease_expires_at,
                    consumer_attempt=job.consumer_attempts,
                )

        return await self._worker_run(execute)

    async def claim_evaluation_job(
        self, message: jobs.AlertEvaluationTaskMessage, *, consumer_id: str
    ) -> jobs.AlertEvaluationJobClaim | None:
        return cast(
            jobs.AlertEvaluationJobClaim | None, await self._claim_job(message, consumer_id)
        )

    async def claim_notification_job(
        self, message: jobs.AlertNotificationTaskMessage, *, consumer_id: str
    ) -> jobs.AlertNotificationJobClaim | None:
        return cast(
            jobs.AlertNotificationJobClaim | None, await self._claim_job(message, consumer_id)
        )

    def _live(self, session: Session, claim: JobClaim) -> StoredAlertJob | None:
        job = self._lookup(session, claim.message)
        if (
            job is None
            or job.state != "running"
            or job.lease_id != claim.lease_id
            or job.fence != claim.fence
            or job.consumer_attempts != claim.consumer_attempt
            or job.lease_expires_at is None
            or job.lease_expires_at <= self._now()
            or job.expires_at <= self._now()
        ):
            return None
        if not self._eligible(session, job):
            return None
        if isinstance(job, AlertEvaluationJobModel):
            rule = session.get(AlertRuleModel, job.rule_id)
            if (
                rule is None
                or not isinstance(claim, jobs.AlertEvaluationJobClaim)
                or rule.lifecycle_sequence != claim.lifecycle_sequence
            ):
                return None
        return job

    async def _heartbeat(self, claim: JobClaim) -> bool:
        def execute() -> bool:
            with self._sessions() as session, session.begin():
                alert_owner_lock(session, claim.message.owner_id)
                job = self._live(session, claim)
                if job is None:
                    return False
                try:
                    self._job_authorization(session, job)
                except (AuthorizationError, app.AlertServiceError):
                    self._terminal(session, job, AlertReason.ACCESS_DENIED)
                    return False
                job.heartbeat_at = self._now()
                job.lease_expires_at = min(job.expires_at, self._now() + timedelta(seconds=60))
                return True

        return await self._worker_run(execute)

    async def heartbeat_evaluation_job(self, claim: jobs.AlertEvaluationJobClaim) -> bool:
        return await self._heartbeat(claim)

    async def heartbeat_notification_job(self, claim: jobs.AlertNotificationJobClaim) -> bool:
        return await self._heartbeat(claim)

    async def _fail(self, claim: JobClaim, failure: AlertReason, retryable: bool) -> bool:
        if not isinstance(failure, AlertReason) or type(retryable) is not bool:
            raise ValueError("A typed report failure is required.")
        permanent = failure in jobs.ALERT_PERMANENT_FAILURES

        def execute() -> bool:
            with self._sessions() as session, session.begin():
                alert_owner_lock(session, claim.message.owner_id)
                job = self._live(session, claim)
                if job is None:
                    return False
                if (
                    retryable
                    and not permanent
                    and job.consumer_attempts < jobs.ALERT_CONSUMER_ATTEMPTS
                ):
                    job.state = "queued"
                    job.lease_id = None
                    job.lease_expires_at = None
                    job.consumer_id = None
                    job.failure_code = failure.value
                    job.available_at = self._now() + timedelta(
                        seconds=(1, 2, 4)[job.consumer_attempts - 1]
                    )
                    row = self._outbox(session, job)
                    row.state = "pending"
                    row.available_at = job.available_at
                    row.claim_token = None
                    row.claim_expires_at = None
                    row.dispatcher_id = None
                    self._attempt(
                        session,
                        job,
                        phase="consumer",
                        attempt=job.consumer_attempts,
                        outcome="retry",
                        failure=failure,
                    )
                else:
                    self._terminal(
                        session,
                        job,
                        AlertReason.ATTEMPTS_EXHAUSTED if retryable and not permanent else failure,
                    )
                    self._attempt(
                        session,
                        job,
                        phase="consumer",
                        attempt=job.consumer_attempts,
                        outcome="failed",
                        failure=failure,
                    )
                return True

        return await self._worker_run(execute)

    async def fail_evaluation_job(
        self, claim: jobs.AlertEvaluationJobClaim, *, failure: AlertReason, retryable: bool
    ) -> bool:
        return await self._fail(claim, failure, retryable)

    async def fail_notification_job(
        self, claim: jobs.AlertNotificationJobClaim, *, failure: AlertReason, retryable: bool
    ) -> bool:
        return await self._fail(claim, failure, retryable)

    def _audit_job(
        self, session: Session, job: StoredAlertJob, event: str, failure: AlertReason | None = None
    ) -> None:
        family = (
            "alert.evaluation" if isinstance(job, AlertEvaluationJobModel) else "alert.notification"
        )
        session.add(
            AuditEventModel(
                id=uuid4(),
                owner_id=job.owner_id,
                principal_id=job.principal_id,
                broker_account_id=job.account_id,
                action=f"{family}.{event}",
                resource_type="alert_job",
                resource_id=str(job.id),
                outcome="failed" if event == "failed" else "succeeded",
                occurred_at=self._now(),
                safe_metadata={"reason": failure.value} if failure else None,
            )
        )

    def _eligible(self, session: Session, job: StoredAlertJob) -> bool:
        if not isinstance(job, AlertEvaluationJobModel):
            event = session.get(AlertEventModel, job.event_id)
            assert event is not None
            rule = session.get(AlertRuleModel, event.rule_id)
            destination = session.get(
                NotificationDestinationVersionModel, job.destination_version_id
            )
            assert destination is not None
            current = session.get(NotificationDestinationModel, destination.destination_id)
            if (
                rule is None
                or current is None
                or rule.lifecycle != "active"
                or rule.active_version_id != event.rule_version_id
                or current.state != "configured"
            ):
                self._terminal(session, job, AlertReason.NOT_CONFIGURED)
                return False
            return True
        from .alert_lifecycle import eligible_interval

        rule = session.get(AlertRuleModel, job.rule_id)
        version = session.get(AlertRuleVersionModel, job.rule_version_id)
        assert rule is not None and version is not None
        if job.execution_intent == "observe_only":
            return eligible_interval(session, version, job.scheduled_for) is not None
        if rule.lifecycle == "archived" or rule.active_version_id != job.rule_version_id:
            reason = (
                AlertReason.RULE_ARCHIVED
                if rule.lifecycle == "archived"
                else AlertReason.RULE_SUPERSEDED
            )
            terminal = session.scalar(
                select(AlertRuleEventModel)
                .where(
                    AlertRuleEventModel.rule_id == rule.id,
                    AlertRuleEventModel.kind.in_(("archived", "activated")),
                )
                .order_by(AlertRuleEventModel.sequence.desc())
                .limit(1)
            )
            job.state = "cancelled"
            job.failure_code = reason.value
            job.completed_at = self._now()
            job.cancelled_by_event_id = terminal.id if terminal else None
            job.lease_id = None
            job.lease_expires_at = None
            job.consumer_id = None
            outbox = self._outbox(session, job)
            outbox.state = "failed"
            outbox.failure_code = reason.value
            outbox.claim_token = None
            outbox.claim_expires_at = None
            outbox.dispatcher_id = None
            self._audit_job(session, job, "cancelled", reason)
            return False
        if rule.lifecycle != "active":
            return False
        if eligible_interval(session, version, job.scheduled_for) is None:
            return False
        if rule.next_scheduled_for is not None and rule.next_scheduled_for < job.scheduled_for:
            return False
        predecessor = session.scalar(
            select(AlertEvaluationJobModel.id)
            .where(
                AlertEvaluationJobModel.rule_version_id == job.rule_version_id,
                AlertEvaluationJobModel.execution_intent == "live",
                AlertEvaluationJobModel.scheduled_for < job.scheduled_for,
                AlertEvaluationJobModel.state.in_(("queued", "running")),
            )
            .limit(1)
        )
        return predecessor is None

    def _job_authorization(self, session: Session, job: StoredAlertJob) -> AlertAuthorization:
        if isinstance(job, AlertEvaluationJobModel):
            version_id, input_id = job.rule_version_id, job.input_id
        else:
            event = session.get(AlertEventModel, job.event_id)
            assert event is not None
            from .alert_models import AlertEvaluationModel

            evaluation = session.get(AlertEvaluationModel, event.evaluation_id)
            assert evaluation is not None
            version_id, input_id = event.rule_version_id, evaluation.input_id
        row = session.get(AlertRuleVersionModel, version_id)
        assert row is not None
        authorization = authorize_alert_job(
            session,
            principal_id=job.principal_id,
            owner_id=job.owner_id,
            account_id=job.account_id,
            definition=rule_version(row).definition,
            expires_at=job.expires_at,
            now=self._now(),
        )
        authorize_alert_sources(session, authorization, input_id=input_id, now=self._now())
        return authorization
