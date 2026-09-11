"""Atomic fanout bounds and exact-slot backfill reuse with real durable transactions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_analytics.alerts import evaluate_alert
from trading212_application import alerts as app
from trading212_domain import alerts as d
from trading212_domain.alert_serialization import encode_alert_input, encode_alert_result
from trading212_persistence.alert_job_store import PostgresAlertJobStore
from trading212_persistence.alert_models import (
    AlertCommandModel,
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertEventModel,
    NotificationDeliveryJobModel,
)
from trading212_persistence.notification_store import provision_notification_destination
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message

from tests.integration.test_alert_postgres import KEY, AlertCase
from tests.integration.test_alert_postgres import alert_case as alert_case
from tests.integration.test_alert_postgres import alert_database as alert_database
from tests.unit.analytics.alert_factories import capture, predicate

pytestmark = pytest.mark.integration


class FanoutCapture:
    def capture_evaluation(
        self,
        version: d.AlertRuleVersion,
        scheduled_for: datetime,
        execution_intent: d.AlertExecutionIntent,
    ) -> d.AlertEvaluationInput:
        original = capture(d.AlertMetric.REPORT_TERMINAL)
        assert isinstance(original.payload, d.AlertEventBatchInput)
        item = original.payload.events[0]
        events = tuple(
            replace(
                item,
                identity=UUID(int=100000 + number),
                revision_id=UUID(int=200000 + number),
                economic_at=scheduled_for - timedelta(seconds=2),
                first_eligible_at=scheduled_for - timedelta(seconds=1),
            )
            for number in range(1001)
        )
        return replace(
            original,
            version=version,
            scheduled_for=scheduled_for,
            source_cutoff_at=scheduled_for,
            execution_intent=execution_intent,
            observation_window=replace(
                original.observation_window,
                start_at=scheduled_for - timedelta(seconds=300),
                end_at=scheduled_for,
            ),
            contexts=tuple(
                replace(
                    context,
                    account_id=version.account_id,
                    source_cutoff_at=scheduled_for,
                    valuation_at=scheduled_for,
                )
                for context in original.contexts
            ),
            payload=d.AlertEventBatchInput(events=events, complete=True),
        )


def test_delivery_fanout_overflow_rolls_back_every_event_and_delivery(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        with case.sessions() as session, session.begin():
            destinations = tuple(
                provision_notification_destination(
                    session,
                    owner_id=UUID(case.principal.owner_id),
                    account_id=case.account_id,
                    configuration_key=f"fanout-{uuid4()}-{number}",
                    channel=app.NotificationChannel.WEBHOOK,
                    label="Synthetic destination",
                    secret_reference="synthetic-config-reference",
                    state=app.NotificationDestinationState.CONFIGURED,
                    now=case.clock[0],
                )
                for number in range(10)
            )
        definition = replace(
            case.definition(destinations=tuple(destinations)),
            predicate=predicate(d.AlertMetric.REPORT_TERMINAL),
            cooldown_seconds=0,
        )
        rule = await case.service.create_rule(
            case.principal,
            app.CreateAlertRuleCommand(account_id=case.account_id, definition=definition),
            idempotency_key=uuid4().hex,
            correlation_id="fanout",
        )
        rule = await case.service.activate_rule(
            case.principal,
            rule.id,
            rule.latest_version.id,
            idempotency_key=uuid4().hex,
            expected_revision=rule.revision,
            correlation_id="fanout",
        )
        control = FanoutCapture()
        case.store = PostgresAlertJobStore(
            case.sessions,
            cursor_signing_key=KEY,
            clock=lambda: case.clock[0],
            capture_factory=lambda _s, _a: control,
        )
        message = await case.admit(rule.id)
        assert rule.active_version is not None
        value = control.capture_evaluation(
            rule.active_version, message.scheduled_for, message.execution_intent
        )
        result = evaluate_alert(value)
        assert len(encode_alert_input(value)) < d.MAX_ALERT_INPUT_BYTES
        assert len(encode_alert_result(result)) < d.MAX_ALERT_RESULT_BYTES
        assert len(result.event_decisions) == 1001 and all(
            event.decision is True for event in result.event_decisions
        )
        assert (
            await execute_alert_message(case.store, message, consumer_id="fanout-bound")
            is AlertExecutionState.FAILED
        )
        with case.sessions() as session:
            job = session.get(AlertEvaluationJobModel, message.job_id)
            assert (
                job is not None
                and job.state == "failed"
                and job.failure_code == "input_bound_exceeded"
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertEvaluationModel)
                    .where(AlertEvaluationModel.job_id == message.job_id)
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertEventModel)
                    .where(AlertEventModel.rule_id == rule.id)
                )
                == 0
            )
            assert (
                session.scalar(select(func.count()).select_from(NotificationDeliveryJobModel)) == 0
            )

    asyncio.run(run())


def test_backfill_reuses_exact_occupied_slot_and_binds_idempotency_without_stealing_due_work(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        message = await case.admit(rule.id)
        request = app.AlertBackfillRequest(
            rule_version_id=message.rule_version_id, scheduled_for=message.scheduled_for
        )
        key = uuid4().hex
        for _ in range(2):
            assert (
                await case.store.backfill_evaluation(
                    case.principal,
                    request,
                    idempotency_key=key,
                    correlation_id="reuse",
                )
                == message
            )
        with pytest.raises(app.AlertServiceError) as reused:
            await case.store.backfill_evaluation(
                case.principal,
                replace(request, scheduled_for=request.scheduled_for + timedelta(seconds=300)),
                idempotency_key=key,
                correlation_id="different",
            )
        assert reused.value.code is app.AlertServiceErrorCode.IDEMPOTENCY_KEY_REUSED
        with pytest.raises(app.AlertServiceError) as frontier:
            await case.store.backfill_evaluation(
                case.principal,
                replace(request, scheduled_for=request.scheduled_for + timedelta(seconds=300)),
                idempotency_key=uuid4().hex,
                correlation_id="frontier",
            )
        assert frontier.value.code is app.AlertServiceErrorCode.INVALID_STATE_TRANSITION
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertEvaluationJobModel)
                    .where(AlertEvaluationJobModel.rule_id == rule.id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AlertCommandModel)
                    .where(
                        AlertCommandModel.command == "backfill",
                        AlertCommandModel.idempotency_key == key,
                    )
                )
                == 1
            )
        assert (
            await execute_alert_message(case.store, message, consumer_id="live-after-reuse")
            is AlertExecutionState.COMPLETED
        )

    asyncio.run(run())
