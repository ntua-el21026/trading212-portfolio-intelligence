"""Fixed projection delivery, async leases and durable child checkpoint acknowledgements."""

from __future__ import annotations

import asyncio
import secrets
import threading
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from celery import Celery, Task  # type: ignore[import-untyped]
from trading212_application import projection_jobs as jobs
from trading212_domain.errors import DomainError
from trading212_persistence import create_database_engine, create_session_factory

from .projection_process import ProjectionProcessResult, calculate_private_projection


class ProjectionPublisher(Protocol):
    async def publish_projection(self, message: jobs.ProjectionTaskMessage) -> None: ...


class CeleryProjectionPublisher:
    def __init__(self, application: Celery) -> None:
        self._application = application

    async def publish_projection(self, message: jobs.ProjectionTaskMessage) -> None:
        await asyncio.to_thread(
            self._application.send_task,
            jobs.PROJECTION_TASK_NAME,
            kwargs=message.to_wire(),
            task_id=message.job_id,
            retry=False,
            ignore_result=True,
        )


@dataclass(frozen=True, slots=True)
class ProjectionDispatchResult:
    claimed: int
    published: int
    deferred: int
    fenced: int


async def dispatch_projections_once(
    store: jobs.ProjectionJobStore,
    publisher: ProjectionPublisher,
    *,
    dispatcher_id: str,
    limit: int = jobs.PROJECTION_DISPATCH_BATCH_SIZE,
) -> ProjectionDispatchResult:
    claims = await store.claim_projection_dispatches(dispatcher_id=dispatcher_id, limit=limit)
    published = deferred = fenced = 0
    for claim in claims:
        try:
            await publisher.publish_projection(claim.message)
        except Exception:
            if await store.defer_projection_dispatch(
                claim, failure_code=jobs.ProjectionJobFailureCode.PUBLICATION_UNAVAILABLE
            ):
                deferred += 1
            else:
                fenced += 1
        else:
            if await store.acknowledge_projection_dispatch(claim):
                published += 1
            else:
                fenced += 1
    return ProjectionDispatchResult(len(claims), published, deferred, fenced)


class ProjectionExecutionState(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    FENCED = "fenced"
    RECOVERY_PENDING = "recovery_pending"


def _bridge[T](
    operation: Callable[[], Coroutine[Any, Any, T]],
    *,
    loop: asyncio.AbstractEventLoop,
    cancelled: threading.Event,
    deadline: float,
) -> T:
    if cancelled.is_set():
        raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
    future = asyncio.run_coroutine_threadsafe(operation(), loop)
    try:
        while True:
            if cancelled.is_set():
                raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED)
            try:
                return future.result(timeout=min(0.1, remaining))
            except FutureTimeout:
                if future.done():
                    raise jobs.ProjectionJobInputError(
                        jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
                    ) from None
    except jobs.ProjectionJobInputError:
        raise
    except Exception:
        raise jobs.ProjectionJobInputError(
            jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
        ) from None
    finally:
        if not future.done():
            future.cancel()


async def execute_projection_message(
    store: jobs.ProjectionJobStore,
    message: jobs.ProjectionTaskMessage,
    *,
    consumer_id: str,
    clock: Callable[[], datetime] | None = None,
) -> ProjectionExecutionState:
    now = clock or (lambda: datetime.now(UTC))
    claim = await store.claim_projection_job(message, consumer_id=consumer_id)
    if claim is None:
        return ProjectionExecutionState.FENCED
    stopped = asyncio.Event()
    cancelled = threading.Event()
    # One immutable monotonic budget includes input loading, resume, callbacks and publication.
    deadline = time.monotonic() + min(240, (claim.deadline_at - now()).total_seconds())

    def remaining() -> float:
        seconds = min(deadline - time.monotonic(), (claim.deadline_at - now()).total_seconds())
        if cancelled.is_set():
            raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
        if seconds <= 0:
            raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED)
        return seconds

    async def heartbeat() -> None:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=jobs.PROJECTION_HEARTBEAT_SECONDS)
                return
            except TimeoutError:
                pass
            try:
                accepted = await asyncio.wait_for(
                    store.heartbeat_projection_job(claim),
                    timeout=jobs.PROJECTION_HEARTBEAT_SECONDS,
                )
                if not accepted:
                    cancelled.set()
                    return
            except Exception:
                cancelled.set()
                return

    heartbeats = asyncio.create_task(heartbeat())
    computation: asyncio.Task[ProjectionProcessResult] | None = None
    try:
        input_timeout = remaining()
        plan = await asyncio.wait_for(store.load_projection_job_input(claim), timeout=input_timeout)
        loop = asyncio.get_running_loop()
        computation = asyncio.create_task(
            asyncio.to_thread(
                calculate_private_projection,
                plan,
                input_digest=message.input_digest,
                load_chunks=lambda after: _bridge(
                    lambda: store.load_projection_job_chunks(claim, after=after, limit=32),
                    loop=loop,
                    cancelled=cancelled,
                    deadline=deadline,
                ),
                save_chunk=lambda chunk: _bridge(
                    lambda: store.save_projection_job_chunk(claim, chunk),
                    loop=loop,
                    cancelled=cancelled,
                    deadline=deadline,
                ),
                cancelled=cancelled,
                maximum_seconds=remaining(),
            )
        )
        computed = await asyncio.shield(computation)
        completion_timeout = remaining()
        accepted = await asyncio.wait_for(
            store.complete_projection_job(claim, computed.calculation), timeout=completion_timeout
        )
        return ProjectionExecutionState.SUCCEEDED if accepted else ProjectionExecutionState.FENCED
    except asyncio.CancelledError:
        cancelled.set()
        if computation is not None:
            with suppress(Exception):
                await asyncio.shield(computation)
        raise
    except Exception as error:
        if cancelled.is_set():
            return ProjectionExecutionState.FENCED
        failure = (
            error
            if isinstance(error, jobs.ProjectionJobInputError)
            else jobs.ProjectionJobInputError(
                jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED
                if isinstance(error, TimeoutError)
                else jobs.ProjectionJobFailureCode.CALCULATION_FAILED
            )
        )
        if await store.fail_projection_job(
            claim, failure_code=failure.code, retryable=failure.retryable
        ):
            return (
                ProjectionExecutionState.RECOVERY_PENDING
                if failure.retryable
                else ProjectionExecutionState.FAILED
            )
        return ProjectionExecutionState.FENCED
    finally:
        cancelled.set()
        stopped.set()
        heartbeats.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeats


def _run(database_url: str, message: jobs.ProjectionTaskMessage) -> ProjectionExecutionState:
    from trading212_persistence.projection_job_store import PostgresProjectionJobStore

    engine = create_database_engine(database_url)
    try:
        store = PostgresProjectionJobStore(
            create_session_factory(engine), cursor_signing_key=secrets.token_bytes(32)
        )
        return asyncio.run(
            execute_projection_message(
                store, message, consumer_id="projection-worker:" + secrets.token_hex(8)
            )
        )
    finally:
        engine.dispose()


def register_projection_tasks(application: Celery, *, database_url: str) -> None:
    application.tasks.pop(jobs.PROJECTION_TASK_NAME, None)

    @application.task(bind=True, name=jobs.PROJECTION_TASK_NAME, ignore_result=True, max_retries=0)  # type: ignore[untyped-decorator]
    def calculate_projection(task: Task, *args: object, **payload: object) -> dict[str, str]:
        try:
            if args:
                return {"state": "rejected"}
            message = jobs.ProjectionTaskMessage.from_wire(payload)
            if task.request.id != message.job_id:
                return {"state": "rejected"}
        except (DomainError, ValueError, TypeError):
            return {"state": "rejected"}
        try:
            return {"state": _run(database_url, message).value}
        except Exception:
            return {"state": ProjectionExecutionState.RECOVERY_PENDING.value}
