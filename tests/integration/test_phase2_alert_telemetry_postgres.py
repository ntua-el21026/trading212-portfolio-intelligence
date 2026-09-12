"""Committed alert observations distinguish creation, latching and delivery receipts."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from trading212_application import alert_jobs as jobs
from trading212_application import alerts as app
from trading212_domain.alerts import AlertReason
from trading212_persistence.alert_job_store import PostgresAlertJobStore
from trading212_persistence.alert_models import AlertEventModel, NotificationDeliveryJobModel
from trading212_persistence.notification_store import (
    PostgresAlertNotificationStore,
    provision_notification_destination,
)
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message

from tests.integration.test_alert_postgres import KEY, AlertCase
from tests.integration.test_alert_postgres import alert_case as alert_case
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


def observed(caplog: pytest.LogCaptureFixture, operation: str) -> list[str]:
    return [
        str(record.__dict__["outcome"])
        for record in caplog.records
        if record.getMessage() == "phase2_operation"
        and record.__dict__.get("operation") == operation
    ]


def operational_store(case: AlertCase) -> PostgresAlertJobStore:
    """Keep admission pinned while worker leases follow current time."""
    return PostgresAlertJobStore(
        case.sessions,
        cursor_signing_key=KEY,
        clock=lambda: max(case.clock[0], datetime.now(UTC)),
        capture_factory=lambda _session, _authorization: case.control,
    )


def test_replay_does_not_repeat_committed_evaluation_or_event_counts(
    alert_case: AlertCase, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="trading212.phase2.telemetry")

    async def run() -> None:
        case = alert_case
        consumer = operational_store(case)
        rule = await case.active()
        first = await case.admit(rule.id)
        assert first.scheduled_for == case.clock[0]
        assert (
            await execute_alert_message(consumer, first, consumer_id="telemetry-first")
            is AlertExecutionState.COMPLETED
        )
        assert observed(caplog, "alert_evaluation_committed") == ["matched"]
        assert observed(caplog, "alert_event_publication_committed") == ["created"]
        caplog.clear()
        assert (
            await execute_alert_message(consumer, first, consumer_id="telemetry-replay")
            is AlertExecutionState.NOT_CLAIMED
        )
        assert not observed(caplog, "alert_evaluation_committed")
        assert not observed(caplog, "alert_event_publication_committed")
        case.clock[0] += timedelta(seconds=300)
        second = await case.admit(rule.id)
        assert second.scheduled_for == first.scheduled_for + timedelta(seconds=300)
        assert (
            await execute_alert_message(consumer, second, consumer_id="telemetry-latched")
            is AlertExecutionState.COMPLETED
        )
        assert observed(caplog, "alert_evaluation_committed") == ["matched"]
        assert observed(caplog, "alert_event_publication_committed") == ["latched"]
        entries = [
            record.__dict__
            for record in caplog.records
            if record.getMessage() == "phase2_operation"
        ]
        rendered = repr(entries)
        assert str(rule.id) not in rendered
        assert str(case.account_id) not in rendered
        assert case.principal.owner_id not in rendered

    asyncio.run(run())


@pytest.mark.parametrize(
    "channel", [app.NotificationChannel.EMAIL, app.NotificationChannel.WEBHOOK]
)
@pytest.mark.parametrize("configured", [True, False])
def test_destination_category_follows_real_retry_and_receipt_transactions(
    alert_case: AlertCase,
    caplog: pytest.LogCaptureFixture,
    channel: app.NotificationChannel,
    configured: bool,
) -> None:
    caplog.set_level(logging.INFO, logger="trading212.phase2.telemetry")

    async def run() -> None:
        case = alert_case
        consumer = operational_store(case)
        with case.sessions.begin() as session:
            destination = provision_notification_destination(
                session,
                owner_id=UUID(case.principal.owner_id),
                account_id=case.account_id,
                configuration_key="telemetry-" + uuid4().hex,
                channel=channel,
                label="PRIVATE-DESTINATION-CANARY",
                secret_reference="PRIVATE-SECRET-REFERENCE" if configured else None,
                state=(
                    app.NotificationDestinationState.CONFIGURED
                    if configured
                    else app.NotificationDestinationState.UNAVAILABLE
                ),
                now=case.clock[0],
            )
        rule = await case.active(destinations=(destination,))
        message = await case.admit(rule.id)
        assert message.scheduled_for == case.clock[0]
        assert (
            await execute_alert_message(consumer, message, consumer_id="telemetry-destination")
            is AlertExecutionState.COMPLETED
        )
        # Retry progression is operational; it must not move the selected slot.
        delivery_floor = case.clock[0]

        def delivery_now() -> datetime:
            return max(delivery_floor, datetime.now(UTC))

        store = PostgresAlertNotificationStore(
            case.sessions, cursor_signing_key=KEY, clock=delivery_now
        )
        with case.sessions() as session:
            row = session.scalar(
                select(NotificationDeliveryJobModel)
                .join(AlertEventModel, AlertEventModel.id == NotificationDeliveryJobModel.event_id)
                .where(AlertEventModel.rule_id == rule.id)
            )
            assert row is not None
            task = store._message(row)
            assert isinstance(task, jobs.AlertNotificationTaskMessage)
        operation = f"{channel.value}_delivery_transition_recorded"
        if not configured:
            assert (
                await store.claim_notification_job(task, consumer_id="telemetry-unavailable")
                is None
            )
            assert observed(caplog, operation) == ["not_configured"]
            return
        claim = await store.claim_notification_job(task, consumer_id="telemetry-retry")
        assert claim is not None
        assert await store.fail_notification_job(
            claim, failure=AlertReason.PUBLICATION_UNAVAILABLE, retryable=True
        )
        delivery_floor = delivery_now() + timedelta(seconds=4)
        again = await store.claim_notification_job(task, consumer_id="telemetry-receipt")
        assert again is not None
        receipt = jobs.AlertDeliveryReceipt(
            delivery_id=task.delivery_id,
            outcome=jobs.AlertDeliveryOutcome.ACCEPTED,
            observed_at=delivery_now(),
        )
        assert await store.complete_notification_job(again, receipt=receipt)
        assert not await store.complete_notification_job(again, receipt=receipt)
        assert observed(caplog, operation) == ["retry", "accepted"]
        rendered = repr(
            [
                record.__dict__
                for record in caplog.records
                if record.getMessage() == "phase2_operation"
            ]
        )
        for private in (
            "PRIVATE-DESTINATION-CANARY",
            "PRIVATE-SECRET-REFERENCE",
            str(task.delivery_id),
        ):
            assert private not in rendered

    asyncio.run(run())
