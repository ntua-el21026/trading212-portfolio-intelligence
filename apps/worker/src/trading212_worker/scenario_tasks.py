"""Fixed scenario delivery and bounded computation under PostgreSQL leases."""

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
from trading212_application import scenario_jobs as jobs
from trading212_domain.errors import DomainError
from trading212_persistence import create_database_engine, create_session_factory

from .scenario_process import calculate_private_scenario


class ScenarioPublisher(Protocol):
    async def publish_scenario(self, message: jobs.ScenarioTaskMessage) -> None: ...


class CeleryScenarioPublisher:
    def __init__(self, application: Celery) -> None:
        self._application = application

    async def publish_scenario(self, message: jobs.ScenarioTaskMessage) -> None:
        await asyncio.to_thread(
            self._application.send_task,
            jobs.SCENARIO_TASK_NAME,
            kwargs=message.to_wire(),
            task_id=message.job_id,
            retry=False,
            ignore_result=True,
        )


@dataclass(frozen=True, slots=True)
class ScenarioDispatchResult:
    claimed: int
    published: int
    deferred: int
    fenced: int


async def dispatch_scenarios_once(
    store: jobs.ScenarioJobStore,
    publisher: ScenarioPublisher,
    *,
    dispatcher_id: str,
    limit: int = 1,
) -> ScenarioDispatchResult:
    claims = await store.claim_scenario_dispatches(dispatcher_id=dispatcher_id, limit=limit)
    published = deferred = fenced = 0
    for claim in claims:
        try:
            await publisher.publish_scenario(claim.message)
        except Exception:
            if await store.defer_scenario_dispatch(
                claim, failure_code=jobs.ScenarioJobFailureCode.PUBLICATION_UNAVAILABLE
            ):
                deferred += 1
            else:
                fenced += 1
        else:
            if await store.acknowledge_scenario_dispatch(claim):
                published += 1
            else:
                fenced += 1
    return ScenarioDispatchResult(len(claims), published, deferred, fenced)


class ScenarioExecutionState(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    FENCED = "fenced"
    RECOVERY_PENDING = "recovery_pending"


async def execute_scenario_message(
    store: jobs.ScenarioJobStore,
    message: jobs.ScenarioTaskMessage,
    *,
    consumer_id: str,
    clock: Callable[[], datetime] | None = None,
) -> ScenarioExecutionState:
    now = clock or (lambda: datetime.now(UTC))
    claim = await store.claim_scenario_job(message, consumer_id=consumer_id)
    if claim is None:
        return ScenarioExecutionState.FENCED
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
                if not await store.heartbeat_scenario_job(claim):
                    cancelled.set()
                    return
            except Exception:
                cancelled.set()
                return

    heartbeats = asyncio.create_task(heartbeat())
    try:
        inputs = await store.load_scenario_job_input(claim)
        remaining = min(240, (claim.deadline_at - now()).total_seconds())
        result = await asyncio.to_thread(
            calculate_private_scenario, inputs, cancelled=cancelled, maximum_seconds=remaining
        )
        if cancelled.is_set():
            return ScenarioExecutionState.FENCED
        return (
            ScenarioExecutionState.SUCCEEDED
            if await store.complete_scenario_job(claim, result)
            else ScenarioExecutionState.FENCED
        )
    except jobs.ScenarioJobInputError as failure:
        if await store.fail_scenario_job(
            claim, failure_code=failure.code, retryable=failure.retryable
        ):
            return (
                ScenarioExecutionState.RECOVERY_PENDING
                if failure.retryable
                else ScenarioExecutionState.FAILED
            )
        return ScenarioExecutionState.FENCED
    except asyncio.CancelledError:
        cancelled.set()
        raise
    except Exception:
        if await store.fail_scenario_job(
            claim, failure_code=jobs.ScenarioJobFailureCode.CALCULATION_FAILED, retryable=False
        ):
            return ScenarioExecutionState.FAILED
        return ScenarioExecutionState.FENCED
    finally:
        cancelled.set()
        stopped.set()
        heartbeats.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeats


def _run(database_url: str, message: jobs.ScenarioTaskMessage) -> ScenarioExecutionState:
    from trading212_analytics.scenario_replay import resolve_scenario_replay
    from trading212_persistence.scenario_job_store import PostgresScenarioJobStore

    engine = create_database_engine(database_url)
    try:
        store = PostgresScenarioJobStore(
            create_session_factory(engine),
            cursor_signing_key=secrets.token_bytes(32),
            replay_resolver=resolve_scenario_replay,
        )
        return asyncio.run(
            execute_scenario_message(
                store, message, consumer_id="scenario-worker:" + secrets.token_hex(8)
            )
        )
    finally:
        engine.dispose()


def register_scenario_tasks(application: Celery, *, database_url: str) -> None:
    application.tasks.pop(jobs.SCENARIO_TASK_NAME, None)

    @application.task(bind=True, name=jobs.SCENARIO_TASK_NAME, ignore_result=True, max_retries=0)  # type: ignore[untyped-decorator]
    def calculate_scenario(task: Task, *args: object, **payload: object) -> dict[str, str]:
        try:
            if args:
                return {"state": "rejected"}
            message = jobs.ScenarioTaskMessage.from_wire(payload)
            if task.request.id != message.job_id:
                return {"state": "rejected"}
        except (DomainError, ValueError, TypeError):
            return {"state": "rejected"}
        try:
            return {"state": _run(database_url, message).value}
        except Exception:
            return {"state": ScenarioExecutionState.RECOVERY_PENDING.value}
