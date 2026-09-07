from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from celery import Celery  # type: ignore[import-untyped]
from trading212_application.planning_jobs import (
    PLAN_TASK_NAME,
    PlanDispatchClaim,
    PlanJobClaim,
    PlanJobFailureCode,
    PlanJobInputError,
    PlanTaskMessage,
)
from trading212_worker import plan_tasks
from trading212_worker.plan_tasks import (
    CeleryPlanPublisher,
    PlanExecutionState,
    dispatch_plans_once,
    execute_plan_message,
    register_planning_task,
)

if TYPE_CHECKING:
    from trading212_domain.planning import ContributionPlanResult, PlanningInput


def message() -> PlanTaskMessage:
    return PlanTaskMessage(
        job_id=str(uuid4()),
        request_id=str(uuid4()),
        owner_id=str(uuid4()),
        account_id=str(uuid4()),
        input_digest="a" * 64,
    )


class Store:
    def __init__(self) -> None:
        self.message = message()
        self.claim = PlanJobClaim(
            self.message, str(uuid4()), datetime.now(UTC) + timedelta(seconds=60), 1
        )
        self.dispatch = PlanDispatchClaim(
            self.message, str(uuid4()), datetime.now(UTC) + timedelta(seconds=30), 1
        )
        self.pinned = cast("PlanningInput", object())
        self.result = cast("ContributionPlanResult", object())
        self.claimed = False
        self.keep_lease = True
        self.pulse_observed = asyncio.Event()
        self.completed: list[ContributionPlanResult] = []
        self.failed: list[tuple[PlanJobFailureCode, bool]] = []
        self.acknowledged: list[PlanDispatchClaim] = []
        self.deferred: list[PlanJobFailureCode] = []
        self.load_error: Exception | None = None
        self.complete_error: Exception | None = None

    async def claim_plan_dispatches(
        self, *, dispatcher_id: str, limit: int = 20
    ) -> tuple[PlanDispatchClaim, ...]:
        assert dispatcher_id == "test-dispatcher" and limit == 20
        return (self.dispatch,)

    async def acknowledge_plan_dispatch(self, claim: PlanDispatchClaim) -> bool:
        self.acknowledged.append(claim)
        return self.keep_lease

    async def defer_plan_dispatch(
        self, claim: PlanDispatchClaim, *, failure_code: PlanJobFailureCode
    ) -> bool:
        assert claim is self.dispatch
        self.deferred.append(failure_code)
        return self.keep_lease

    async def claim_plan_job(
        self, incoming: PlanTaskMessage, *, consumer_id: str
    ) -> PlanJobClaim | None:
        assert incoming == self.message and consumer_id == "test-worker"
        if self.claimed:
            return None
        self.claimed = True
        return self.claim

    async def heartbeat_plan_job(self, claim: PlanJobClaim) -> bool:
        assert claim is self.claim
        self.pulse_observed.set()
        return self.keep_lease

    async def load_plan_job_input(self, claim: PlanJobClaim) -> PlanningInput:
        assert claim is self.claim
        if self.load_error is not None:
            raise self.load_error
        return self.pinned

    async def complete_plan_job(self, claim: PlanJobClaim, result: ContributionPlanResult) -> bool:
        assert claim is self.claim
        if self.complete_error is not None:
            raise self.complete_error
        self.completed.append(result)
        return self.keep_lease

    async def fail_plan_job(
        self, claim: PlanJobClaim, *, failure_code: PlanJobFailureCode, retryable: bool
    ) -> bool:
        assert claim is self.claim
        self.failed.append((failure_code, retryable))
        return self.keep_lease


class Publisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[PlanTaskMessage] = []
        self.fail = fail

    def publish(self, incoming: PlanTaskMessage) -> None:
        self.messages.append(incoming)
        if self.fail:
            raise RuntimeError("private-provider-content-must-not-leak")


@pytest.mark.asyncio
async def test_publication_is_acknowledged_only_after_fixed_message_dispatch() -> None:
    store = Store()
    publisher = Publisher()
    result = await dispatch_plans_once(store, publisher, dispatcher_id="test-dispatcher")
    assert publisher.messages == [store.message]
    assert store.acknowledged == [store.dispatch]
    assert (result.claimed, result.published, result.deferred, result.fenced) == (1, 1, 0, 0)


@pytest.mark.asyncio
async def test_ambiguous_publication_is_durably_deferred_without_raw_exception() -> None:
    store = Store()
    result = await dispatch_plans_once(store, Publisher(fail=True), dispatcher_id="test-dispatcher")
    assert store.deferred == [PlanJobFailureCode.PUBLICATION_UNAVAILABLE]
    assert store.acknowledged == []
    assert (result.published, result.deferred) == (0, 1)


@pytest.mark.asyncio
async def test_expired_publication_claim_cannot_report_acknowledged_success() -> None:
    store = Store()
    store.keep_lease = False
    result = await dispatch_plans_once(store, Publisher(), dispatcher_id="test-dispatcher")
    assert result.published == 0 and result.fenced == 1


@pytest.mark.asyncio
async def test_duplicate_delivery_calculates_once_and_passes_pinned_input_unchanged() -> None:
    store = Store()
    called: list[PlanningInput] = []

    def calculate(pinned: PlanningInput) -> ContributionPlanResult:
        called.append(pinned)
        return store.result

    results = await asyncio.gather(
        *(
            execute_plan_message(
                store, store.message, consumer_id="test-worker", calculate=calculate
            )
            for _ in range(2)
        )
    )
    assert set(results) == {PlanExecutionState.COMPLETED, PlanExecutionState.NOT_CLAIMED}
    assert called == [store.pinned] and store.completed == [store.result]


@pytest.mark.asyncio
async def test_heartbeat_runs_during_cpu_work_and_lost_lease_prevents_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store()
    store.keep_lease = False
    release = Event()
    monkeypatch.setattr(plan_tasks, "PLAN_HEARTBEAT_SECONDS", 0.01)

    def calculate(_: PlanningInput) -> ContributionPlanResult:
        assert release.wait(timeout=2)
        return store.result

    task = asyncio.create_task(
        execute_plan_message(store, store.message, consumer_id="test-worker", calculate=calculate)
    )
    try:
        await asyncio.wait_for(store.pulse_observed.wait(), timeout=1)
    finally:
        release.set()
    assert await task is PlanExecutionState.FENCED
    assert store.completed == [] and store.failed == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code", "retryable", "expected"),
    [
        (
            PlanJobInputError(PlanJobFailureCode.INPUT_CHANGED),
            PlanJobFailureCode.INPUT_CHANGED,
            False,
            PlanExecutionState.FAILED,
        ),
        (
            PlanJobInputError(PlanJobFailureCode.ACCESS_DENIED),
            PlanJobFailureCode.ACCESS_DENIED,
            False,
            PlanExecutionState.FAILED,
        ),
        (
            RuntimeError("secret-storage-message"),
            PlanJobFailureCode.STORAGE_UNAVAILABLE,
            True,
            PlanExecutionState.DEFERRED,
        ),
    ],
)
async def test_input_failures_preserve_typed_failure_and_never_start_calculation(
    error: Exception, code: PlanJobFailureCode, retryable: bool, expected: PlanExecutionState
) -> None:
    store = Store()
    store.load_error = error

    def forbidden(_: PlanningInput) -> ContributionPlanResult:
        pytest.fail("failed input must not reach calculation")

    assert (
        await execute_plan_message(
            store, store.message, consumer_id="test-worker", calculate=forbidden
        )
        is expected
    )
    assert store.failed == [(code, retryable)] and store.completed == []


@pytest.mark.asyncio
async def test_solver_exception_is_terminal_without_exposing_its_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = Store()

    def broken(_: PlanningInput) -> ContributionPlanResult:
        raise ArithmeticError("private-calculation-canary")

    assert (
        await execute_plan_message(
            store, store.message, consumer_id="test-worker", calculate=broken
        )
        is PlanExecutionState.FAILED
    )
    assert store.failed == [(PlanJobFailureCode.CALCULATION_FAILED, False)]
    assert "private-calculation-canary" not in caplog.text


def test_celery_publisher_keeps_job_identity_and_disables_transport_retries() -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    class Application:
        def send_task(self, name: str, **kwargs: object) -> None:
            captured.append((name, kwargs))

    incoming = message()
    CeleryPlanPublisher(Application()).publish(incoming)
    assert captured == [
        (
            PLAN_TASK_NAME,
            {
                "kwargs": incoming.to_wire(),
                "task_id": incoming.job_id,
                "retry": False,
                "ignore_result": True,
            },
        )
    ]


def test_registered_task_rejects_unknown_or_mismatched_payload_without_echo(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    application = Celery("planning-test", broker="memory://", backend="cache+memory://")
    register_planning_task(application, database_url="unused")
    calls: list[PlanTaskMessage] = []

    def run(_: str, incoming: PlanTaskMessage) -> PlanExecutionState:
        calls.append(incoming)
        return PlanExecutionState.COMPLETED

    monkeypatch.setattr(plan_tasks, "_run_durable_plan", run)
    task = application.tasks[PLAN_TASK_NAME]
    incoming = message()
    caplog.set_level(logging.INFO)
    for payload, task_id in [
        (
            {**incoming.to_wire(), "private-unknown-key-canary": "private-value-canary"},
            incoming.job_id,
        ),
        (incoming.to_wire(), str(uuid4())),
    ]:
        assert task.apply(kwargs=payload, task_id=task_id).get() == {"state": "rejected"}
    assert calls == []
    assert "private-unknown-key-canary" not in caplog.text
    assert "private-value-canary" not in caplog.text
    assert task.apply(kwargs=incoming.to_wire(), task_id=incoming.job_id).get() == {
        "state": "completed"
    }
    assert calls == [incoming] and task.ignore_result is True and task.max_retries == 0
    application.close()
