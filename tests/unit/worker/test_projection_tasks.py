"""Async checkpoint bridge, heartbeat fences and closed Celery message delivery."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from celery import Celery  # type: ignore[import-untyped]
from trading212_analytics import projection as kernel
from trading212_application import projection_jobs as jobs
from trading212_application.projection_capture import (
    ProjectionCapturePlan,
    projection_capture_digest,
)
from trading212_worker import projection_tasks as tasks
from trading212_worker.projection_process import ProjectionProcessResult

from tests.unit.persistence.projection_codec_factories import capture

pytestmark = pytest.mark.unit
NOW = datetime(2026, 9, 15, tzinfo=UTC)


def _message(plan: ProjectionCapturePlan) -> jobs.ProjectionTaskMessage:
    return jobs.ProjectionTaskMessage(
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        str(plan.selection.account_id),
        projection_capture_digest(plan),
    )


def _store(plan: ProjectionCapturePlan, message: jobs.ProjectionTaskMessage) -> Mock:
    claim = jobs.ProjectionJobClaim(
        message, str(uuid4()), NOW + timedelta(seconds=60), 1, NOW + timedelta(seconds=240)
    )
    store = Mock(spec=jobs.ProjectionJobStore)
    store.claim_projection_job = AsyncMock(return_value=claim)
    store.load_projection_job_input = AsyncMock(return_value=plan)
    store.load_projection_job_chunks = AsyncMock(return_value=())
    store.save_projection_job_chunk = AsyncMock(return_value=True)
    store.complete_projection_job = AsyncMock(return_value=True)
    store.fail_projection_job = AsyncMock(return_value=True)
    store.heartbeat_projection_job = AsyncMock(return_value=True)
    return store


async def test_duplicate_consumer_never_reads_private_input() -> None:
    plan = capture(observed=False)
    message = _message(plan)
    store = _store(plan, message)
    store.claim_projection_job.return_value = None
    with patch("trading212_worker.projection_tasks.calculate_private_projection") as compute:
        actual = await tasks.execute_projection_message(
            cast(jobs.ProjectionJobStore, store), message, consumer_id="worker", clock=lambda: NOW
        )
    assert actual is tasks.ProjectionExecutionState.FENCED
    store.load_projection_job_input.assert_not_awaited()
    compute.assert_not_called()


async def test_callbacks_run_on_owner_loop_and_ack_precedes_completion() -> None:
    plan = capture(observed=False)
    message = _message(plan)
    store = _store(plan, message)
    result = kernel.calculate_projection(plan.inputs)
    chunk = kernel.calculate_projection_chunk(plan.inputs, 0, plan.inputs.paths)
    loop = asyncio.get_running_loop()
    events: list[str] = []

    async def load(*args: Any, **kwargs: Any) -> tuple[()]:
        assert asyncio.get_running_loop() is loop
        events.append("load")
        return ()

    async def save(*args: Any, **kwargs: Any) -> bool:
        assert asyncio.get_running_loop() is loop
        events.append("durable")
        return True

    async def complete(*args: Any, **kwargs: Any) -> bool:
        events.append("complete")
        return True

    def compute(*args: Any, **kwargs: Any) -> ProjectionProcessResult:
        assert kwargs["input_digest"] == projection_capture_digest(plan)
        assert kwargs["input_digest"] != plan.numerical_input_digest
        assert kwargs["load_chunks"](None) == ()
        assert kwargs["save_chunk"](chunk) is True
        events.append("ack")
        return ProjectionProcessResult(result, 12345)

    store.load_projection_job_chunks.side_effect = load
    store.save_projection_job_chunk.side_effect = save
    store.complete_projection_job.side_effect = complete
    with patch(
        "trading212_worker.projection_tasks.calculate_private_projection", side_effect=compute
    ):
        actual = await tasks.execute_projection_message(
            cast(jobs.ProjectionJobStore, store), message, consumer_id="worker", clock=lambda: NOW
        )
    assert actual is tasks.ProjectionExecutionState.SUCCEEDED
    assert events == ["load", "durable", "ack", "complete"]
    store.load_projection_job_chunks.assert_awaited_once_with(
        store.claim_projection_job.return_value, after=None, limit=32
    )
    store.complete_projection_job.assert_awaited_once_with(
        store.claim_projection_job.return_value, result
    )


@pytest.mark.parametrize("retryable", [False, True])
async def test_source_denial_uses_closed_failure_without_child(retryable: bool) -> None:
    plan = capture(observed=False)
    message = _message(plan)
    store = _store(plan, message)
    store.load_projection_job_input.side_effect = jobs.ProjectionJobInputError(
        jobs.ProjectionJobFailureCode.SOURCE_RESTRICTED, retryable=retryable
    )
    with patch("trading212_worker.projection_tasks.calculate_private_projection") as compute:
        actual = await tasks.execute_projection_message(
            cast(jobs.ProjectionJobStore, store), message, consumer_id="worker", clock=lambda: NOW
        )
    assert actual is (
        tasks.ProjectionExecutionState.RECOVERY_PENDING
        if retryable
        else tasks.ProjectionExecutionState.FAILED
    )
    compute.assert_not_called()
    store.complete_projection_job.assert_not_awaited()


async def test_storage_failure_in_checkpoint_bridge_keeps_recovery_pending() -> None:
    plan = capture(observed=False)
    message = _message(plan)
    store = _store(plan, message)
    store.load_projection_job_chunks.side_effect = OSError("private-storage-canary")

    def compute(*args: Any, **kwargs: Any) -> ProjectionProcessResult:
        kwargs["load_chunks"](None)
        raise AssertionError("Failed storage operation continued.")

    with patch(
        "trading212_worker.projection_tasks.calculate_private_projection", side_effect=compute
    ):
        actual = await tasks.execute_projection_message(
            cast(jobs.ProjectionJobStore, store), message, consumer_id="worker", clock=lambda: NOW
        )
    assert actual is tasks.ProjectionExecutionState.RECOVERY_PENDING
    store.complete_projection_job.assert_not_awaited()
    store.fail_projection_job.assert_awaited_once_with(
        store.claim_projection_job.return_value,
        failure_code=jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE,
        retryable=True,
    )
    assert "private-storage-canary" not in str(store.fail_projection_job.call_args)


async def test_heartbeat_fences_blocked_callback_without_blocking_owner_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = capture(observed=False)
    message = _message(plan)
    store = _store(plan, message)
    callback_cancelled = asyncio.Event()
    store.heartbeat_projection_job.return_value = False
    monkeypatch.setattr(jobs, "PROJECTION_HEARTBEAT_SECONDS", 0.01)

    async def load(*args: Any, **kwargs: Any) -> tuple[()]:
        try:
            await asyncio.Event().wait()
        finally:
            callback_cancelled.set()
        return ()

    def compute(*args: Any, **kwargs: Any) -> ProjectionProcessResult:
        kwargs["load_chunks"](None)
        raise AssertionError("Fenced checkpoint load continued.")

    store.load_projection_job_chunks.side_effect = load
    with patch(
        "trading212_worker.projection_tasks.calculate_private_projection", side_effect=compute
    ):
        actual = await asyncio.wait_for(
            tasks.execute_projection_message(
                cast(jobs.ProjectionJobStore, store),
                message,
                consumer_id="worker",
                clock=lambda: NOW,
            ),
            timeout=5,
        )
    assert actual is tasks.ProjectionExecutionState.FENCED
    await asyncio.wait_for(callback_cancelled.wait(), timeout=1)
    store.complete_projection_job.assert_not_awaited()
    store.fail_projection_job.assert_not_awaited()


async def test_cancellation_waits_for_process_thread_cleanup() -> None:
    plan = capture(observed=False)
    message = _message(plan)
    store = _store(plan, message)
    started = asyncio.Event()
    finished = threading.Event()
    loop = asyncio.get_running_loop()

    def compute(*args: Any, **kwargs: Any) -> ProjectionProcessResult:
        loop.call_soon_threadsafe(started.set)
        assert kwargs["cancelled"].wait(timeout=3)
        finished.set()
        raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)

    with patch(
        "trading212_worker.projection_tasks.calculate_private_projection", side_effect=compute
    ):
        running = asyncio.create_task(
            tasks.execute_projection_message(
                cast(jobs.ProjectionJobStore, store),
                message,
                consumer_id="worker",
                clock=lambda: NOW,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    assert finished.is_set()
    store.complete_projection_job.assert_not_awaited()


async def test_original_deadline_exhausted_before_load_never_starts_child() -> None:
    plan = capture(observed=False)
    message = _message(plan)
    store = _store(plan, message)
    with patch("trading212_worker.projection_tasks.calculate_private_projection") as compute:
        actual = await tasks.execute_projection_message(
            cast(jobs.ProjectionJobStore, store),
            message,
            consumer_id="worker",
            clock=lambda: NOW + timedelta(seconds=241),
        )
    assert actual is tasks.ProjectionExecutionState.FAILED
    store.fail_projection_job.assert_awaited_once_with(
        store.claim_projection_job.return_value,
        failure_code=jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED,
        retryable=False,
    )
    store.load_projection_job_input.assert_not_awaited()
    compute.assert_not_called()


async def test_completion_fence_never_reports_success() -> None:
    plan = capture(observed=False)
    message = _message(plan)
    store = _store(plan, message)
    store.complete_projection_job.return_value = False
    result = ProjectionProcessResult(kernel.calculate_projection(plan.inputs), None)
    with patch(
        "trading212_worker.projection_tasks.calculate_private_projection", return_value=result
    ):
        actual = await tasks.execute_projection_message(
            cast(jobs.ProjectionJobStore, store), message, consumer_id="worker", clock=lambda: NOW
        )
    assert actual is tasks.ProjectionExecutionState.FENCED


async def test_resume_callback_cannot_renew_original_attempt_deadline() -> None:
    plan = capture(observed=False)
    message = _message(plan)
    store = _store(plan, message)
    store.claim_projection_job.return_value = jobs.ProjectionJobClaim(
        message, str(uuid4()), NOW + timedelta(seconds=240), 2, NOW + timedelta(seconds=240)
    )
    cancelled = asyncio.Event()

    async def load(*args: Any, **kwargs: Any) -> tuple[()]:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return ()

    def compute(*args: Any, **kwargs: Any) -> ProjectionProcessResult:
        assert 0 < kwargs["maximum_seconds"] <= 0.1
        kwargs["load_chunks"](None)
        raise AssertionError("Expired resume continued.")

    store.load_projection_job_chunks.side_effect = load
    with patch(
        "trading212_worker.projection_tasks.calculate_private_projection", side_effect=compute
    ):
        result = await asyncio.wait_for(
            tasks.execute_projection_message(
                cast(jobs.ProjectionJobStore, store),
                message,
                consumer_id="worker",
                clock=lambda: NOW + timedelta(seconds=239.9),
            ),
            timeout=5,
        )
    assert result is tasks.ProjectionExecutionState.FAILED
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    store.complete_projection_job.assert_not_awaited()
    store.fail_projection_job.assert_awaited_once_with(
        store.claim_projection_job.return_value,
        failure_code=jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED,
        retryable=False,
    )


def test_registered_task_rejects_extra_fields_wrong_delivery_and_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = Celery("projection-test", broker="memory://", backend="cache+memory://")
    plan = capture(observed=False)
    incoming = _message(plan)
    try:
        tasks.register_projection_tasks(application, database_url="unused")
        task = application.tasks[jobs.PROJECTION_TASK_NAME]
        caplog.set_level(logging.INFO)
        with patch(
            "trading212_worker.projection_tasks._run",
            return_value=tasks.ProjectionExecutionState.SUCCEEDED,
        ) as run:
            assert task.apply(
                kwargs={**incoming.to_wire(), "private-canary": "secret-canary"},
                task_id=incoming.job_id,
            ).get() == {"state": "rejected"}
            assert task.apply(kwargs=incoming.to_wire(), task_id=str(uuid4())).get() == {
                "state": "rejected"
            }
            assert task.apply(args=("secret-canary",), task_id=incoming.job_id).get() == {
                "state": "rejected"
            }
            run.assert_not_called()
            assert task.apply(kwargs=incoming.to_wire(), task_id=incoming.job_id).get() == {
                "state": "succeeded"
            }
        assert all(marker not in caplog.text for marker in ("private-canary", "secret-canary"))
        assert task.ignore_result and task.max_retries == 0
    finally:
        application.close()


@pytest.mark.parametrize("acknowledged", [False, True])
async def test_dispatch_reuses_opaque_message_and_respects_publication_fence(
    acknowledged: bool,
) -> None:
    plan = capture(observed=False)
    incoming = _message(plan)
    claim = jobs.ProjectionDispatchClaim(incoming, str(uuid4()), NOW + timedelta(seconds=30), 1)
    store = Mock(spec=jobs.ProjectionJobStore)
    store.claim_projection_dispatches = AsyncMock(return_value=(claim,))
    store.defer_projection_dispatch = AsyncMock(return_value=acknowledged)
    publisher = Mock(spec=tasks.ProjectionPublisher)
    publisher.publish_projection = AsyncMock(side_effect=OSError("private-canary"))
    result = await tasks.dispatch_projections_once(
        cast(jobs.ProjectionJobStore, store),
        cast(tasks.ProjectionPublisher, publisher),
        dispatcher_id="dispatcher",
    )
    assert result.claimed == 1 and result.published == 0
    assert (result.deferred, result.fenced) == ((1, 0) if acknowledged else (0, 1))
    publisher.publish_projection.assert_awaited_once_with(incoming)
