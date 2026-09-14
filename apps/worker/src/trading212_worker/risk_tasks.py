"""Fixed risk delivery and bounded computation under PostgreSQL leases."""

from __future__ import annotations

import asyncio
import secrets
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from celery import Celery, Task  # type: ignore[import-untyped]
from trading212_application import risk_jobs as jobs
from trading212_domain.errors import DomainError
from trading212_persistence import create_database_engine, create_session_factory

from .risk_process import calculate_private_risk


class RiskPublisher(Protocol):
    async def publish_risk(self, message: jobs.RiskTaskMessage) -> None: ...


class CeleryRiskPublisher:
    def __init__(self, application: Celery) -> None:
        self._application = application

    async def publish_risk(self, message: jobs.RiskTaskMessage) -> None:
        await asyncio.to_thread(
            self._application.send_task,
            jobs.RISK_TASK_NAME,
            kwargs=message.to_wire(),
            task_id=message.job_id,
            retry=False,
            ignore_result=True,
        )


@dataclass(frozen=True, slots=True)
class RiskDispatchResult:
    claimed: int
    published: int
    deferred: int
    fenced: int


async def dispatch_risks_once(
    store: jobs.RiskJobStore, publisher: RiskPublisher, *, dispatcher_id: str, limit: int = 1
) -> RiskDispatchResult:
    claims = await store.claim_risk_dispatches(dispatcher_id=dispatcher_id, limit=limit)
    published = deferred = fenced = 0
    for claim in claims:
        try:
            await publisher.publish_risk(claim.message)
        except Exception:
            if await store.defer_risk_dispatch(
                claim, failure_code=jobs.RiskJobFailureCode.PUBLICATION_UNAVAILABLE
            ):
                deferred += 1
            else:
                fenced += 1
        else:
            if await store.acknowledge_risk_dispatch(claim):
                published += 1
            else:
                fenced += 1
    return RiskDispatchResult(len(claims), published, deferred, fenced)


class RiskExecutionState(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    FENCED = "fenced"
    RECOVERY_PENDING = "recovery_pending"


async def execute_risk_message(
    store: jobs.RiskJobStore,
    message: jobs.RiskTaskMessage,
    *,
    consumer_id: str,
    clock: Callable[[], datetime] | None = None,
) -> RiskExecutionState:
    now = clock or (lambda: datetime.now(UTC))
    claim = await store.claim_risk_job(message, consumer_id=consumer_id)
    if claim is None:
        return RiskExecutionState.FENCED
    stopped = asyncio.Event()
    cancelled = threading.Event()

    async def heartbeat() -> None:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=15)
                return
            except TimeoutError:
                pass
            try:
                if not await store.heartbeat_risk_job(claim):
                    cancelled.set()
                    return
            except Exception:
                cancelled.set()
                return

    heartbeats = asyncio.create_task(heartbeat())
    try:
        inputs = await store.load_risk_job_input(claim)
        remaining = min(240, (claim.deadline_at - now()).total_seconds())
        result = await asyncio.to_thread(
            calculate_private_risk, inputs, cancelled=cancelled, maximum_seconds=remaining
        )
        if cancelled.is_set():
            return RiskExecutionState.FENCED
        return (
            RiskExecutionState.SUCCEEDED
            if await store.complete_risk_job(claim, result)
            else RiskExecutionState.FENCED
        )
    except jobs.RiskJobInputError as failure:
        if await store.fail_risk_job(claim, failure_code=failure.code, retryable=failure.retryable):
            return (
                RiskExecutionState.RECOVERY_PENDING
                if failure.retryable
                else RiskExecutionState.FAILED
            )
        return RiskExecutionState.FENCED
    except asyncio.CancelledError:
        cancelled.set()
        raise
    except Exception:
        if await store.fail_risk_job(
            claim, failure_code=jobs.RiskJobFailureCode.CALCULATION_FAILED, retryable=False
        ):
            return RiskExecutionState.FAILED
        return RiskExecutionState.FENCED
    finally:
        cancelled.set()
        stopped.set()
        heartbeats.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeats


def _run(database_url: str, message: jobs.RiskTaskMessage) -> RiskExecutionState:
    from trading212_analytics.risk_history import validate_risk_capacity
    from trading212_persistence.risk_job_store import PostgresRiskJobStore

    engine = create_database_engine(database_url)
    try:
        store = PostgresRiskJobStore(
            create_session_factory(engine),
            cursor_signing_key=secrets.token_bytes(32),
            preflight=validate_risk_capacity,
        )
        return asyncio.run(
            execute_risk_message(store, message, consumer_id="risk-worker:" + secrets.token_hex(8))
        )
    finally:
        engine.dispose()


def register_risk_tasks(application: Celery, *, database_url: str) -> None:
    application.tasks.pop(jobs.RISK_TASK_NAME, None)

    @application.task(bind=True, name=jobs.RISK_TASK_NAME, ignore_result=True, max_retries=0)  # type: ignore[untyped-decorator]
    def calculate_risk(task: Task, *args: object, **payload: object) -> dict[str, str]:
        try:
            if args:
                return {"state": "rejected"}
            message = jobs.RiskTaskMessage.from_wire(payload)
            if task.request.id != message.job_id:
                return {"state": "rejected"}
        except (DomainError, ValueError, TypeError):
            return {"state": "rejected"}
        try:
            return {"state": _run(database_url, message).value}
        except Exception:
            return {"state": RiskExecutionState.RECOVERY_PENDING.value}
