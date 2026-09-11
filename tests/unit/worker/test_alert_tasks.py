"""Opaque task boundaries, durable failures and lease-safe alert publication."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from trading212_analytics.alerts import evaluate_alert
from trading212_application import alert_jobs as jobs
from trading212_domain.alert_serialization import alert_input_digest, alert_record_digest
from trading212_domain.alerts import AlertReason
from trading212_worker.alert_tasks import (
    AlertExecutionState,
    dispatch_alerts_once,
    execute_alert_message,
    execute_notification_message,
)

from tests.unit.analytics.alert_factories import AT, capture, uid

pytestmark = pytest.mark.unit


def evaluation_store() -> tuple[Mock, jobs.AlertEvaluationTaskMessage]:
    value = capture()
    message = jobs.AlertEvaluationTaskMessage(
        job_id=uid(801),
        owner_id=value.version.owner_id,
        account_id=value.version.account_id,
        rule_version_id=value.version.id,
        capture_id=uid(802),
        input_digest=alert_input_digest(value),
        scheduled_for=value.scheduled_for,
        execution_intent=value.execution_intent,
    )
    claim = jobs.AlertEvaluationJobClaim(
        message=message,
        lease_id=uid(803),
        fence=1,
        lease_expires_at=AT + timedelta(seconds=60),
        consumer_attempt=1,
        lifecycle_sequence=1,
    )
    retained = Mock()
    retained.claim_evaluation_job = AsyncMock(return_value=claim)
    retained.heartbeat_evaluation_job = AsyncMock(return_value=True)
    retained.load_evaluation_input = AsyncMock(return_value=value)
    retained.complete_evaluation_job = AsyncMock(return_value=True)
    retained.fail_evaluation_job = AsyncMock(return_value=True)
    return retained, message


def test_actual_pure_evaluation_is_passed_to_one_fenced_publication() -> None:
    retained, message = evaluation_store()
    assert (
        asyncio.run(
            execute_alert_message(
                cast(jobs.AlertJobStore, retained), message, consumer_id="unit-evaluation"
            )
        )
        is AlertExecutionState.COMPLETED
    )
    retained.complete_evaluation_job.assert_awaited_once_with(
        retained.claim_evaluation_job.return_value,
        result=evaluate_alert(retained.load_evaluation_input.return_value),
    )
    retained.fail_evaluation_job.assert_not_awaited()


def test_unclaimed_job_never_loads_or_computes() -> None:
    retained, message = evaluation_store()
    retained.claim_evaluation_job.return_value = None
    assert (
        asyncio.run(execute_alert_message(retained, message, consumer_id="unit-evaluation"))
        is AlertExecutionState.NOT_CLAIMED
    )
    retained.load_evaluation_input.assert_not_awaited()
    retained.complete_evaluation_job.assert_not_awaited()


@pytest.mark.parametrize("reason", [AlertReason.ACCESS_DENIED, AlertReason.INPUT_BOUND_EXCEEDED])
def test_input_or_fanout_failure_stays_typed_and_never_completes(reason: AlertReason) -> None:
    retained, message = evaluation_store()
    retained.load_evaluation_input.side_effect = jobs.AlertJobInputError(reason)
    assert (
        asyncio.run(execute_alert_message(retained, message, consumer_id="unit-evaluation"))
        is AlertExecutionState.FAILED
    )
    retained.complete_evaluation_job.assert_not_awaited()
    retained.fail_evaluation_job.assert_awaited_once_with(
        retained.claim_evaluation_job.return_value, failure=reason, retryable=False
    )


def test_lost_publication_fence_cannot_turn_into_success_or_retry() -> None:
    retained, message = evaluation_store()
    retained.complete_evaluation_job.return_value = False
    assert (
        asyncio.run(execute_alert_message(retained, message, consumer_id="unit-evaluation"))
        is AlertExecutionState.FENCED
    )
    retained.fail_evaluation_job.assert_not_awaited()


def test_ambiguous_dispatch_uses_only_persisted_retry_and_safe_reason() -> None:
    retained, message = evaluation_store()
    dispatch = jobs.AlertEvaluationDispatchClaim(
        message=message,
        claim_token=uid(804),
        claim_expires_at=AT + timedelta(seconds=30),
        publication_attempt=1,
    )
    retained.claim_evaluation_dispatches = AsyncMock(return_value=(dispatch,))
    retained.defer_evaluation_dispatch = AsyncMock(return_value=True)
    retained.acknowledge_evaluation_dispatch = AsyncMock()
    publisher = Mock()
    publisher.publish_evaluation = AsyncMock(side_effect=OSError("synthetic private detail"))
    result = asyncio.run(dispatch_alerts_once(retained, publisher, dispatcher_id="unit-dispatch"))
    assert (result.claimed, result.published, result.deferred, result.fenced) == (1, 0, 1, 0)
    retained.defer_evaluation_dispatch.assert_awaited_once_with(
        dispatch, failure=AlertReason.PUBLICATION_UNAVAILABLE
    )
    retained.acknowledge_evaluation_dispatch.assert_not_awaited()


def notification_store() -> tuple[Mock, jobs.AlertNotificationTaskMessage]:
    payload = jobs.AlertNotificationPayload(
        delivery_id=uid(810), event_id=uid(811), rule_id=uid(812), rule_version_id=uid(813)
    )
    message = jobs.AlertNotificationTaskMessage(
        delivery_id=payload.delivery_id,
        owner_id=uid(1),
        account_id=uid(2),
        event_id=payload.event_id,
        destination_version_id=uid(814),
        payload_digest=alert_record_digest(payload),
    )
    claim = jobs.AlertNotificationJobClaim(
        message=message,
        lease_id=uid(815),
        fence=1,
        lease_expires_at=AT + timedelta(seconds=60),
        consumer_attempt=1,
    )
    retained = Mock()
    retained.claim_notification_job = AsyncMock(return_value=claim)
    retained.heartbeat_notification_job = AsyncMock(return_value=True)
    retained.load_notification_payload = AsyncMock(return_value=payload)
    retained.complete_notification_job = AsyncMock(return_value=True)
    retained.fail_notification_job = AsyncMock(return_value=True)
    return retained, message


def test_absent_transport_records_unavailable_without_success() -> None:
    retained, message = notification_store()
    assert (
        asyncio.run(
            execute_notification_message(retained, message, consumer_id="unit-notification")
        )
        is AlertExecutionState.FAILED
    )
    retained.fail_notification_job.assert_awaited_once_with(
        retained.claim_notification_job.return_value,
        failure=AlertReason.NOT_CONFIGURED,
        retryable=False,
    )
    retained.complete_notification_job.assert_not_awaited()


@pytest.mark.parametrize(
    ("reason", "attempt", "expected"),
    [
        (AlertReason.PUBLICATION_UNAVAILABLE, 1, AlertExecutionState.DEFERRED),
        (
            AlertReason.PUBLICATION_UNAVAILABLE,
            jobs.ALERT_CONSUMER_ATTEMPTS,
            AlertExecutionState.FAILED,
        ),
        (AlertReason.COMPUTATION_FAILED, 1, AlertExecutionState.FAILED),
    ],
)
def test_notification_failure_summary_matches_durable_retry_policy(
    reason: AlertReason, attempt: int, expected: AlertExecutionState
) -> None:
    retained, message = notification_store()
    retained.claim_notification_job.return_value = replace(
        retained.claim_notification_job.return_value, consumer_attempt=attempt
    )
    port = Mock()
    port.deliver = AsyncMock(
        return_value=jobs.AlertDeliveryReceipt(
            delivery_id=message.delivery_id,
            outcome=jobs.AlertDeliveryOutcome.RETRYABLE_FAILURE,
            observed_at=AT,
            reason=reason,
        )
    )
    assert (
        asyncio.run(
            execute_notification_message(
                retained, message, consumer_id="unit-failure-summary", notification_port=port
            )
        )
        is expected
    )
    retained.complete_notification_job.assert_not_awaited()


def test_notification_transport_gets_only_pinned_destination_and_fixed_ids() -> None:
    retained, message = notification_store()
    receipt = jobs.AlertDeliveryReceipt(
        delivery_id=message.delivery_id, outcome=jobs.AlertDeliveryOutcome.ACCEPTED, observed_at=AT
    )
    port = Mock()
    port.deliver = AsyncMock(return_value=receipt)
    assert (
        asyncio.run(
            execute_notification_message(
                retained, message, consumer_id="unit-notification", notification_port=port
            )
        )
        is AlertExecutionState.COMPLETED
    )
    port.deliver.assert_awaited_once_with(
        message.destination_version_id, retained.load_notification_payload.return_value
    )
    retained.complete_notification_job.assert_awaited_once_with(
        retained.claim_notification_job.return_value, receipt=receipt
    )
    retained.fail_notification_job.assert_not_awaited()
