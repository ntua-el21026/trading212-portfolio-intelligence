"""Durable-worker orchestration never publishes after fencing or private-input failure."""

import logging
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from celery import Celery  # type: ignore[import-untyped]
from trading212_analytics.scenario import calculate_scenario
from trading212_application import scenario_jobs as jobs
from trading212_worker import scenario_tasks
from trading212_worker.scenario_tasks import (
    ScenarioExecutionState,
    ScenarioPublisher,
    dispatch_scenarios_once,
    execute_scenario_message,
)

from tests.unit.analytics.scenario_factories import content, input_for, portfolio, price

pytestmark = pytest.mark.unit
NOW = datetime(2026, 9, 15, tzinfo=UTC)


def _message() -> jobs.ScenarioTaskMessage:
    return jobs.ScenarioTaskMessage(
        str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4()), "a" * 64
    )


def _claim(message: jobs.ScenarioTaskMessage) -> jobs.ScenarioJobClaim:
    return jobs.ScenarioJobClaim(
        message, str(uuid4()), NOW + timedelta(seconds=60), 1, NOW + timedelta(seconds=240)
    )


async def test_duplicate_consumer_never_loads_private_input() -> None:
    store = Mock(spec=jobs.ScenarioJobStore)
    store.claim_scenario_job = AsyncMock(return_value=None)
    with patch("trading212_worker.scenario_tasks.calculate_private_scenario") as compute:
        state = await execute_scenario_message(
            cast(jobs.ScenarioJobStore, store),
            _message(),
            consumer_id="consumer",
            clock=lambda: NOW,
        )
    assert state is ScenarioExecutionState.FENCED
    store.load_scenario_job_input.assert_not_called()
    store.complete_scenario_job.assert_not_called()
    compute.assert_not_called()


@pytest.mark.parametrize("retryable", [False, True])
async def test_private_input_denial_never_calculates_or_publishes(retryable: bool) -> None:
    message = _message()
    store = Mock(spec=jobs.ScenarioJobStore)
    store.claim_scenario_job = AsyncMock(return_value=_claim(message))
    store.load_scenario_job_input = AsyncMock(
        side_effect=jobs.ScenarioJobInputError(
            jobs.ScenarioJobFailureCode.SOURCE_RESTRICTED, retryable=retryable
        )
    )
    store.fail_scenario_job = AsyncMock(return_value=True)
    with patch("trading212_worker.scenario_tasks.calculate_private_scenario") as compute:
        state = await execute_scenario_message(
            cast(jobs.ScenarioJobStore, store), message, consumer_id="consumer", clock=lambda: NOW
        )
    assert state is (
        ScenarioExecutionState.RECOVERY_PENDING if retryable else ScenarioExecutionState.FAILED
    )
    store.complete_scenario_job.assert_not_called()
    compute.assert_not_called()
    store.fail_scenario_job.assert_awaited_once_with(
        store.claim_scenario_job.return_value,
        failure_code=jobs.ScenarioJobFailureCode.SOURCE_RESTRICTED,
        retryable=retryable,
    )


async def test_completion_fence_is_not_reported_as_success() -> None:
    message = _message()
    value = input_for(portfolio(("100",)), content(price(10, "-.2")))
    result = calculate_scenario(value)
    store = Mock(spec=jobs.ScenarioJobStore)
    store.claim_scenario_job = AsyncMock(return_value=_claim(message))
    store.load_scenario_job_input = AsyncMock(return_value=value)
    store.complete_scenario_job = AsyncMock(return_value=False)
    with patch("trading212_worker.scenario_tasks.calculate_private_scenario", return_value=result):
        state = await execute_scenario_message(
            cast(jobs.ScenarioJobStore, store), message, consumer_id="consumer", clock=lambda: NOW
        )
    assert state is ScenarioExecutionState.FENCED
    store.complete_scenario_job.assert_awaited_once()
    store.fail_scenario_job.assert_not_called()


async def test_unexpected_private_failure_uses_only_closed_failure_code() -> None:
    message = _message()
    store = Mock(spec=jobs.ScenarioJobStore)
    store.claim_scenario_job = AsyncMock(return_value=_claim(message))
    store.load_scenario_job_input = AsyncMock(side_effect=RuntimeError("private-error-canary"))
    store.fail_scenario_job = AsyncMock(return_value=True)
    state = await execute_scenario_message(
        cast(jobs.ScenarioJobStore, store), message, consumer_id="consumer", clock=lambda: NOW
    )
    assert state is ScenarioExecutionState.FAILED
    store.fail_scenario_job.assert_awaited_once_with(
        store.claim_scenario_job.return_value,
        failure_code=jobs.ScenarioJobFailureCode.CALCULATION_FAILED,
        retryable=False,
    )
    assert "private-error-canary" not in str(store.fail_scenario_job.call_args)


@pytest.mark.parametrize("acknowledged", [True, False])
async def test_delivery_loss_preserves_dispatch_identity_and_fence(acknowledged: bool) -> None:
    message = _message()
    claim = jobs.ScenarioDispatchClaim(message, str(uuid4()), NOW + timedelta(seconds=30), 1)
    store = Mock(spec=jobs.ScenarioJobStore)
    store.claim_scenario_dispatches = AsyncMock(return_value=(claim,))
    store.defer_scenario_dispatch = AsyncMock(return_value=acknowledged)
    publisher = Mock(spec=ScenarioPublisher)
    publisher.publish_scenario = AsyncMock(side_effect=OSError("delivery-private-canary"))
    result = await dispatch_scenarios_once(
        cast(jobs.ScenarioJobStore, store),
        cast(ScenarioPublisher, publisher),
        dispatcher_id="dispatcher",
        limit=1,
    )
    assert result.claimed == 1 and result.published == 0
    assert (result.deferred, result.fenced) == ((1, 0) if acknowledged else (0, 1))
    publisher.publish_scenario.assert_awaited_once_with(message)
    store.acknowledge_scenario_dispatch.assert_not_called()
    store.defer_scenario_dispatch.assert_awaited_once_with(
        claim, failure_code=jobs.ScenarioJobFailureCode.PUBLICATION_UNAVAILABLE
    )


def test_registered_scenario_task_rejects_untrusted_payload_without_echo(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    application = Celery("scenario-test", broker="memory://", backend="cache+memory://")
    calls: list[jobs.ScenarioTaskMessage] = []

    def run(_: str, incoming: jobs.ScenarioTaskMessage) -> ScenarioExecutionState:
        calls.append(incoming)
        return ScenarioExecutionState.SUCCEEDED

    try:
        scenario_tasks.register_scenario_tasks(application, database_url="unused")
        monkeypatch.setattr(scenario_tasks, "_run", run)
        task = application.tasks[jobs.SCENARIO_TASK_NAME]
        incoming = _message()
        caplog.set_level(logging.INFO)
        for payload, task_id in (
            ({**incoming.to_wire(), "unknown-canary": "private-value-canary"}, incoming.job_id),
            (incoming.to_wire(), str(uuid4())),
            ({**incoming.to_wire(), "input_digest": "invalid"}, incoming.job_id),
        ):
            assert task.apply(kwargs=payload, task_id=task_id).get() == {"state": "rejected"}
        assert task.apply(args=("positional-private-canary",), task_id=incoming.job_id).get() == {
            "state": "rejected"
        }
        assert calls == []
        assert all(
            marker not in caplog.text
            for marker in ("unknown-canary", "private-value-canary", "positional-private-canary")
        )
        assert task.apply(kwargs=incoming.to_wire(), task_id=incoming.job_id).get() == {
            "state": "succeeded"
        }
        assert calls == [incoming]
        assert task.ignore_result is True and task.max_retries == 0
    finally:
        application.close()
