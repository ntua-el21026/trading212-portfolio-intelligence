"""Transport timeouts retry the same durable delivery and stop at the attempt bound."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_application import alert_jobs as jobs
from trading212_application import alerts as app
from trading212_persistence.alert_models import (
    AlertEventModel,
    NotificationDeliveryJobModel,
    NotificationDeliveryOutboxModel,
)
from trading212_persistence.notification_store import (
    PostgresAlertNotificationStore,
    provision_notification_destination,
)
from trading212_worker.alert_tasks import (
    AlertExecutionState,
    execute_alert_message,
    execute_notification_message,
)

from tests.integration.test_alert_postgres import KEY, AlertCase
from tests.integration.test_alert_postgres import alert_case as alert_case
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("timeouts", [2, jobs.ALERT_CONSUMER_ATTEMPTS])
def test_transport_timeout_preserves_delivery_identity_and_bounded_retry(
    alert_case: AlertCase, timeouts: int
) -> None:
    async def run() -> None:
        case = alert_case
        with case.sessions() as session, session.begin():
            destination = provision_notification_destination(
                session,
                owner_id=UUID(case.principal.owner_id),
                account_id=case.account_id,
                configuration_key="timeout-" + uuid4().hex,
                channel=app.NotificationChannel.WEBHOOK,
                label="Synthetic timeout destination",
                secret_reference="synthetic-timeout-reference",
                state=app.NotificationDestinationState.CONFIGURED,
                now=case.clock[0],
            )
        rule = await case.active(destinations=(destination,))
        evaluation = await case.admit(rule.id)
        assert (
            await execute_alert_message(case.store, evaluation, consumer_id="timeout-evaluation")
            is AlertExecutionState.COMPLETED
        )
        store = PostgresAlertNotificationStore(
            case.sessions, cursor_signing_key=KEY, clock=lambda: case.clock[0]
        )
        with case.sessions() as session:
            row = session.scalar(
                select(NotificationDeliveryJobModel)
                .join(AlertEventModel, AlertEventModel.id == NotificationDeliveryJobModel.event_id)
                .where(AlertEventModel.rule_id == rule.id)
            )
            assert row is not None and row.state == "queued"
            message = store._message(row)
            assert isinstance(message, jobs.AlertNotificationTaskMessage)
            original = bytes(row.payload)

        port = Mock()
        port.deliver = AsyncMock(side_effect=TimeoutError("synthetic-private-timeout-detail"))
        for attempt in range(1, timeouts + 1):
            outcome = await execute_notification_message(
                store, message, consumer_id="timeout-consumer", notification_port=port
            )
            terminal = attempt == jobs.ALERT_CONSUMER_ATTEMPTS
            with case.sessions() as session:
                row = session.get(NotificationDeliveryJobModel, message.delivery_id)
                outbox = session.scalar(
                    select(NotificationDeliveryOutboxModel).where(
                        NotificationDeliveryOutboxModel.job_id == message.delivery_id
                    )
                )
                assert row is not None and outbox is not None
                assert row.state == ("failed" if terminal else "queued")
                assert row.failure_code == (
                    "attempts_exhausted" if terminal else "publication_unavailable"
                )
                assert row.consumer_attempts == attempt
                assert row.payload == original and row.payload_digest == message.payload_digest
                assert row.destination_version_id == message.destination_version_id
                assert outbox.state == ("failed" if terminal else "pending")
            assert outcome is (
                AlertExecutionState.FAILED if terminal else AlertExecutionState.DEFERRED
            )
            case.clock[0] += timedelta(seconds=4)

        if timeouts < jobs.ALERT_CONSUMER_ATTEMPTS:
            port.deliver.side_effect = None
            port.deliver.return_value = jobs.AlertDeliveryReceipt(
                delivery_id=message.delivery_id,
                outcome=jobs.AlertDeliveryOutcome.ACCEPTED,
                observed_at=case.clock[0],
            )
            assert (
                await execute_notification_message(
                    store, message, consumer_id="timeout-recovered", notification_port=port
                )
                is AlertExecutionState.COMPLETED
            )
        assert (
            await execute_notification_message(
                store, message, consumer_id="timeout-replayed", notification_port=port
            )
            is AlertExecutionState.NOT_CLAIMED
        )
        assert port.deliver.await_count == timeouts + int(timeouts < jobs.ALERT_CONSUMER_ATTEMPTS)
        assert all(
            call.args[0] == message.destination_version_id
            and call.args[1].delivery_id == message.delivery_id
            for call in port.deliver.await_args_list
        )
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(NotificationDeliveryJobModel)
                    .where(NotificationDeliveryJobModel.event_id == message.event_id)
                )
                == 1
            )

    asyncio.run(run())
