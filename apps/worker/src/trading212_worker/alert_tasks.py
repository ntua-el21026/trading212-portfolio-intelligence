"""Fixed, opaque alert task delivery and bounded fenced consumers."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from celery import Celery, Task  # type: ignore[import-untyped]
from trading212_analytics.alerts import evaluate_alert
from trading212_application import alert_jobs as jobs
from trading212_domain.alerts import AlertReason
from trading212_domain.errors import DomainError, ErrorCode
from trading212_persistence import create_database_engine, create_session_factory

_LOGGER = logging.getLogger("trading212_worker.alerts")


class CeleryAlertPublisher:
    def __init__(self, application: Celery) -> None:
        self._application = application

    async def publish_evaluation(self, message: jobs.AlertEvaluationTaskMessage) -> None:
        await asyncio.to_thread(
            self._application.send_task,
            jobs.ALERT_EVALUATION_TASK_NAME,
            kwargs=message.to_wire(),
            task_id=str(message.job_id),
            retry=False,
            ignore_result=True,
        )

    async def publish_notification(self, message: jobs.AlertNotificationTaskMessage) -> None:
        await asyncio.to_thread(
            self._application.send_task,
            jobs.ALERT_NOTIFICATION_TASK_NAME,
            kwargs=message.to_wire(),
            task_id=str(message.delivery_id),
            retry=False,
            ignore_result=True,
        )


@dataclass(frozen=True, slots=True)
class AlertDispatchResult:
    claimed: int
    published: int
    deferred: int
    fenced: int


async def dispatch_alerts_once(
    store: jobs.AlertJobStore,
    publisher: jobs.AlertTaskPublisher,
    *,
    dispatcher_id: str,
    limit: int = 20,
) -> AlertDispatchResult:
    claims = await store.claim_evaluation_dispatches(dispatcher_id=dispatcher_id, limit=limit)
    published = deferred = fenced = 0
    for claim in claims:
        try:
            await publisher.publish_evaluation(claim.message)
        except Exception:
            retained = await store.defer_evaluation_dispatch(
                claim, failure=AlertReason.PUBLICATION_UNAVAILABLE
            )
            deferred += int(retained)
        else:
            retained = await store.acknowledge_evaluation_dispatch(claim)
            published += int(retained)
        fenced += int(not retained)
    return AlertDispatchResult(len(claims), published, deferred, fenced)


async def dispatch_notifications_once(
    store: jobs.AlertNotificationStore,
    publisher: jobs.AlertTaskPublisher,
    *,
    dispatcher_id: str,
    limit: int = 20,
) -> AlertDispatchResult:
    claims = await store.claim_notification_dispatches(dispatcher_id=dispatcher_id, limit=limit)
    published = deferred = fenced = 0
    for claim in claims:
        try:
            await publisher.publish_notification(claim.message)
        except Exception:
            retained = await store.defer_notification_dispatch(
                claim, failure=AlertReason.PUBLICATION_UNAVAILABLE
            )
            deferred += int(retained)
        else:
            retained = await store.acknowledge_notification_dispatch(claim)
            published += int(retained)
        fenced += int(not retained)
    return AlertDispatchResult(len(claims), published, deferred, fenced)


class AlertExecutionState(StrEnum):
    COMPLETED = "completed"
    NOT_CLAIMED = "not_claimed"
    FENCED = "fenced"
    FAILED = "failed"
    DEFERRED = "deferred"
    RECOVERY_PENDING = "recovery_pending"


type Store = jobs.AlertJobStore | jobs.AlertNotificationStore
type Message = jobs.AlertEvaluationTaskMessage | jobs.AlertNotificationTaskMessage
type Claim = jobs.AlertEvaluationJobClaim | jobs.AlertNotificationJobClaim


async def _execute(
    store: Store,
    message: Message,
    *,
    consumer_id: str,
    notification_port: jobs.AlertNotificationPort | None,
) -> AlertExecutionState:
    if isinstance(message, jobs.AlertEvaluationTaskMessage):
        claim: Claim | None = await cast(jobs.AlertJobStore, store).claim_evaluation_job(
            message, consumer_id=consumer_id
        )
    else:
        claim = await cast(jobs.AlertNotificationStore, store).claim_notification_job(
            message, consumer_id=consumer_id
        )
    if claim is None:
        return AlertExecutionState.NOT_CLAIMED
    stopped = asyncio.Event()
    fenced = asyncio.Event()

    async def heartbeat() -> None:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=jobs.ALERT_HEARTBEAT_SECONDS)
            except TimeoutError:
                try:
                    retained = (
                        await cast(jobs.AlertJobStore, store).heartbeat_evaluation_job(claim)
                        if isinstance(claim, jobs.AlertEvaluationJobClaim)
                        else await cast(
                            jobs.AlertNotificationStore, store
                        ).heartbeat_notification_job(claim)
                    )
                except Exception:
                    retained = False
                if not retained:
                    fenced.set()
                    return

    async def fail(reason: AlertReason, retryable: bool) -> AlertExecutionState:
        if fenced.is_set():
            return AlertExecutionState.FENCED
        try:
            retained = (
                await cast(jobs.AlertJobStore, store).fail_evaluation_job(
                    claim, failure=reason, retryable=retryable
                )
                if isinstance(claim, jobs.AlertEvaluationJobClaim)
                else await cast(jobs.AlertNotificationStore, store).fail_notification_job(
                    claim, failure=reason, retryable=retryable
                )
            )
        except Exception:
            return AlertExecutionState.RECOVERY_PENDING
        if not retained:
            return AlertExecutionState.FENCED
        will_retry = (
            retryable
            and reason not in jobs.ALERT_PERMANENT_FAILURES
            and claim.consumer_attempt < jobs.ALERT_CONSUMER_ATTEMPTS
        )
        return AlertExecutionState.DEFERRED if will_retry else AlertExecutionState.FAILED

    async def work() -> AlertExecutionState:
        if isinstance(claim, jobs.AlertEvaluationJobClaim):
            typed = cast(jobs.AlertJobStore, store)
            value = await typed.load_evaluation_input(claim)
            result = await asyncio.to_thread(evaluate_alert, value)
            if fenced.is_set():
                return AlertExecutionState.FENCED
            retained = await typed.complete_evaluation_job(claim, result=result)
            return AlertExecutionState.COMPLETED if retained else AlertExecutionState.FENCED
        typed_notification = cast(jobs.AlertNotificationStore, store)
        payload = await typed_notification.load_notification_payload(claim)
        if fenced.is_set():
            return AlertExecutionState.FENCED
        if notification_port is None:
            receipt = jobs.AlertDeliveryReceipt(
                delivery_id=payload.delivery_id,
                outcome=jobs.AlertDeliveryOutcome.UNAVAILABLE,
                observed_at=datetime.now(UTC),
                reason=AlertReason.NOT_CONFIGURED,
            )
        else:
            # Destination transports must enforce their own fixed URL/address policy.
            # A timeout is ambiguous: deterministic delivery_id remains the retry identity.
            try:
                receipt = await asyncio.wait_for(
                    notification_port.deliver(claim.message.destination_version_id, payload),
                    timeout=30,
                )
            except TimeoutError:
                raise jobs.AlertJobInputError(
                    AlertReason.PUBLICATION_UNAVAILABLE, retryable=True
                ) from None
        if fenced.is_set():
            return AlertExecutionState.FENCED
        if receipt.outcome is not jobs.AlertDeliveryOutcome.ACCEPTED:
            state = await fail(
                receipt.reason or AlertReason.NOT_CONFIGURED,
                receipt.outcome is jobs.AlertDeliveryOutcome.RETRYABLE_FAILURE,
            )
            return state
        retained = await typed_notification.complete_notification_job(claim, receipt=receipt)
        return AlertExecutionState.COMPLETED if retained else AlertExecutionState.FENCED

    pulse = asyncio.create_task(heartbeat())
    operation = asyncio.create_task(work())
    try:
        try:
            outcome = await asyncio.shield(operation)
        except jobs.AlertJobInputError as error:
            return await fail(error.code, error.retryable)
        except DomainError as error:
            reason = (
                AlertReason.INPUT_BOUND_EXCEEDED
                if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
                else AlertReason.COMPUTATION_FAILED
            )
            return await fail(reason, False)
        except Exception:
            return await fail(AlertReason.STORAGE_UNAVAILABLE, True)
        return outcome
    finally:
        fenced.set()
        stopped.set()
        await pulse
        if not operation.done():
            with suppress(Exception):
                await asyncio.shield(operation)


async def execute_alert_message(
    store: jobs.AlertJobStore, message: jobs.AlertEvaluationTaskMessage, *, consumer_id: str
) -> AlertExecutionState:
    return await _execute(store, message, consumer_id=consumer_id, notification_port=None)


async def execute_notification_message(
    store: jobs.AlertNotificationStore,
    message: jobs.AlertNotificationTaskMessage,
    *,
    consumer_id: str,
    notification_port: jobs.AlertNotificationPort | None = None,
) -> AlertExecutionState:
    return await _execute(
        store, message, consumer_id=consumer_id, notification_port=notification_port
    )


def register_alert_tasks(
    application: Celery,
    *,
    database_url: str,
    cursor_signing_key: bytes,
    notification_port: jobs.AlertNotificationPort | None = None,
) -> None:
    application.tasks.pop(jobs.ALERT_EVALUATION_TASK_NAME, None)
    application.tasks.pop(jobs.ALERT_NOTIFICATION_TASK_NAME, None)

    def invoke(
        task: Task, args: tuple[object, ...], payload: dict[str, object], *, notification: bool
    ) -> dict[str, str]:
        try:
            if args:
                return {"state": "rejected"}
            message: Message = (
                jobs.AlertNotificationTaskMessage.from_wire(payload)
                if notification
                else jobs.AlertEvaluationTaskMessage.from_wire(payload)
            )
            identifier = (
                message.delivery_id
                if isinstance(message, jobs.AlertNotificationTaskMessage)
                else message.job_id
            )
            if task.request.id != str(identifier):
                return {"state": "rejected"}
        except (DomainError, ValueError, TypeError):
            return {"state": "rejected"}
        engine = create_database_engine(database_url)
        try:
            from trading212_persistence.alert_job_store import PostgresAlertJobStore
            from trading212_persistence.notification_store import PostgresAlertNotificationStore

            sessions = create_session_factory(engine)
            consumer = "alert-worker:" + secrets.token_hex(12)
            if isinstance(message, jobs.AlertEvaluationTaskMessage):
                outcome = asyncio.run(
                    execute_alert_message(
                        PostgresAlertJobStore(sessions, cursor_signing_key=cursor_signing_key),
                        message,
                        consumer_id=consumer,
                    )
                )
            else:
                outcome = asyncio.run(
                    execute_notification_message(
                        PostgresAlertNotificationStore(
                            sessions, cursor_signing_key=cursor_signing_key
                        ),
                        message,
                        consumer_id=consumer,
                        notification_port=notification_port,
                    )
                )
        except Exception:
            _LOGGER.error("alert_consumer_recovery_pending")
            return {"state": AlertExecutionState.RECOVERY_PENDING.value}
        finally:
            engine.dispose()
        _LOGGER.info("alert_consumer_finished", extra={"outcome": outcome.value})
        return {"state": outcome.value}

    @application.task(
        bind=True, name=jobs.ALERT_EVALUATION_TASK_NAME, ignore_result=True, max_retries=0
    )  # type: ignore[untyped-decorator]
    def evaluate(task: Task, *args: object, **payload: object) -> dict[str, str]:
        return invoke(task, args, payload, notification=False)

    @application.task(
        bind=True, name=jobs.ALERT_NOTIFICATION_TASK_NAME, ignore_result=True, max_retries=0
    )  # type: ignore[untyped-decorator]
    def notify(task: Task, *args: object, **payload: object) -> dict[str, str]:
        return invoke(task, args, payload, notification=True)
