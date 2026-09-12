"""Fixed planning delivery with PostgreSQL fencing and bounded pure calculation."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from celery import Celery, Task  # type: ignore[import-untyped]
from trading212_application.operational_telemetry import Operation, record_operation
from trading212_application.planning_jobs import (
    PLAN_DISPATCH_BATCH_SIZE,
    PLAN_HEARTBEAT_SECONDS,
    PLAN_TASK_NAME,
    PlanJobFailureCode,
    PlanJobInputError,
    PlanJobStore,
    PlanTaskMessage,
)
from trading212_persistence import create_database_engine, create_session_factory

if TYPE_CHECKING:
    from trading212_domain.planning import ContributionPlanResult, PlanningInput

_LOGGER = logging.getLogger("trading212_worker.planning")


class PlanPublisher(Protocol):
    def publish(self, message: PlanTaskMessage) -> None: ...


class CeleryPlanPublisher:
    def __init__(self, application: Celery) -> None:
        self._application = application

    def publish(self, message: PlanTaskMessage) -> None:
        # The durable outbox owns retries. The existing worker consumes this
        # default queue; no financial inputs or user-selected task names travel.
        self._application.send_task(
            PLAN_TASK_NAME,
            kwargs=message.to_wire(),
            task_id=message.job_id,
            retry=False,
            ignore_result=True,
        )


@dataclass(frozen=True, slots=True)
class PlanDispatchResult:
    claimed: int
    published: int
    deferred: int
    fenced: int


async def dispatch_plans_once(
    store: PlanJobStore,
    publisher: PlanPublisher,
    *,
    dispatcher_id: str,
    limit: int = PLAN_DISPATCH_BATCH_SIZE,
) -> PlanDispatchResult:
    claims = await store.claim_plan_dispatches(dispatcher_id=dispatcher_id, limit=limit)
    published = deferred = fenced = 0
    for claim in claims:
        try:
            await asyncio.to_thread(publisher.publish, claim.message)
        except Exception:
            retained = await store.defer_plan_dispatch(
                claim, failure_code=PlanJobFailureCode.PUBLICATION_UNAVAILABLE
            )
            deferred += int(retained)
            fenced += int(not retained)
        else:
            retained = await store.acknowledge_plan_dispatch(claim)
            published += int(retained)
            fenced += int(not retained)
    return PlanDispatchResult(len(claims), published, deferred, fenced)


class PlanExecutionState(StrEnum):
    COMPLETED = "completed"
    NOT_CLAIMED = "not_claimed"
    FENCED = "fenced"
    FAILED = "failed"
    DEFERRED = "deferred"
    RECOVERY_PENDING = "recovery_pending"


async def execute_plan_message(
    store: PlanJobStore,
    message: PlanTaskMessage,
    *,
    consumer_id: str,
    calculate: Callable[[PlanningInput], ContributionPlanResult],
) -> PlanExecutionState:
    claim = await store.claim_plan_job(message, consumer_id=consumer_id)
    if claim is None:
        return PlanExecutionState.NOT_CLAIMED
    stopped = asyncio.Event()
    lease_lost = asyncio.Event()

    async def heartbeat() -> None:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=PLAN_HEARTBEAT_SECONDS)
            except TimeoutError:
                try:
                    retained = await store.heartbeat_plan_job(claim)
                except Exception:
                    retained = False
                if not retained:
                    lease_lost.set()
                    return

    async def fail(code: PlanJobFailureCode, *, retryable: bool) -> PlanExecutionState:
        if lease_lost.is_set():
            return PlanExecutionState.FENCED
        try:
            retained = await store.fail_plan_job(claim, failure_code=code, retryable=retryable)
        except Exception:
            # Keep the original lease/job identity for the dispatcher to recover.
            return PlanExecutionState.RECOVERY_PENDING
        if not retained:
            return PlanExecutionState.FENCED
        return PlanExecutionState.DEFERRED if retryable else PlanExecutionState.FAILED

    pulse = asyncio.create_task(heartbeat())
    started = time.perf_counter()
    try:
        try:
            pinned = await store.load_plan_job_input(claim)
        except PlanJobInputError as error:
            return await fail(error.code, retryable=error.retryable)
        except Exception:
            return await fail(PlanJobFailureCode.STORAGE_UNAVAILABLE, retryable=True)
        if lease_lost.is_set():
            return PlanExecutionState.FENCED
        calculation_started = time.perf_counter()
        try:
            result = await asyncio.to_thread(calculate, pinned)
        except Exception:
            record_operation(
                Operation.OPTIMIZER_CALCULATION,
                "failed",
                duration_seconds=time.perf_counter() - calculation_started,
            )
            return await fail(PlanJobFailureCode.CALCULATION_FAILED, retryable=False)
        record_operation(
            Operation.OPTIMIZER_CALCULATION,
            result.summary.outcome.value,
            duration_seconds=time.perf_counter() - calculation_started,
        )
        if lease_lost.is_set():
            return PlanExecutionState.FENCED
        try:
            retained = await store.complete_plan_job(claim, result)
        except Exception:
            return await fail(PlanJobFailureCode.STORAGE_UNAVAILABLE, retryable=True)
        return PlanExecutionState.COMPLETED if retained else PlanExecutionState.FENCED
    finally:
        stopped.set()
        await pulse
        _LOGGER.info(
            "plan_calculation_finished",
            extra={"duration_seconds": time.perf_counter() - started},
        )


def _run_durable_plan(database_url: str, message: PlanTaskMessage) -> PlanExecutionState:
    from trading212_analytics.planning import calculate_contribution_plan
    from trading212_persistence.planning_service import PostgresPlanningService

    engine = create_database_engine(database_url)
    try:
        store = PostgresPlanningService(
            sessions=create_session_factory(engine), cursor_signing_key=secrets.token_bytes(32)
        )
        return asyncio.run(
            execute_plan_message(
                store,
                message,
                consumer_id="celery-plan-worker",
                calculate=calculate_contribution_plan,
            )
        )
    finally:
        engine.dispose()


def register_planning_task(application: Celery, *, database_url: str) -> None:
    application.tasks.pop(PLAN_TASK_NAME, None)

    @application.task(  # type: ignore[untyped-decorator]
        bind=True,
        name=PLAN_TASK_NAME,
        ignore_result=True,
        max_retries=0,
    )
    def calculate_plan(task: Task, *args: object, **payload: object) -> dict[str, str]:
        # Parse before any logging, persistence or callback. Celery's ordinary
        # Python argument errors can echo arbitrary unexpected keys and values.
        try:
            if args:
                raise ValueError("planning task accepts named fields only")
            message = PlanTaskMessage.from_wire(payload)
            if task.request.id != message.job_id:
                raise ValueError("planning delivery identity does not match")
        except ValueError:
            return {"state": "rejected"}
        try:
            outcome = _run_durable_plan(database_url, message)
        except Exception:
            # PostgreSQL retains the claim and owns bounded redelivery. Do not
            # leak raw exception context into Celery's result backend or logs.
            _LOGGER.error("plan_consumer_recovery_pending")
            return {"state": PlanExecutionState.RECOVERY_PENDING.value}
        _LOGGER.info("plan_consumer_finished", extra={"outcome": outcome.value})
        return {"state": outcome.value}
