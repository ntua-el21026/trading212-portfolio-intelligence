"""Bounded dispatch candidates retain progress around paused and ordered live slots."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from trading212_domain.alerts import AlertReason
from trading212_persistence.alert_models import (
    AlertEvaluationJobModel,
    AlertEvaluationOutboxModel,
)
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message

from tests.integration.test_alert_postgres import AlertCase
from tests.integration.test_alert_postgres import alert_case as alert_case
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


def test_paused_candidate_cannot_starve_another_rule_at_dispatch_limit_one(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        paused_rule = await case.active()
        paused = await case.admit(paused_rule.id)
        case.clock[0] += timedelta(seconds=1)
        await case.service.pause_rule(
            case.principal,
            paused_rule.id,
            idempotency_key=uuid4().hex,
            expected_revision=paused_rule.revision,
            correlation_id="paused-dispatch-prefix",
        )
        active_rule = await case.active()
        active = await case.admit(active_rule.id)
        with case.sessions() as session:
            original_prefix = session.scalar(
                select(AlertEvaluationOutboxModel.job_id)
                .where(AlertEvaluationOutboxModel.job_id.in_((paused.job_id, active.job_id)))
                .order_by(AlertEvaluationOutboxModel.available_at)
                .limit(1)
            )
            assert original_prefix == paused.job_id
        claims = await case.store.claim_evaluation_dispatches(
            dispatcher_id="paused-prefix", limit=1
        )
        assert len(claims) == 1 and claims[0].message == active
        assert await case.store.acknowledge_evaluation_dispatch(claims[0])
        assert (
            await execute_alert_message(case.store, active, consumer_id="other-rule")
            is AlertExecutionState.COMPLETED
        )
        with case.sessions() as session:
            job = session.get(AlertEvaluationJobModel, paused.job_id)
            outbox = session.scalar(
                select(AlertEvaluationOutboxModel).where(
                    AlertEvaluationOutboxModel.job_id == paused.job_id
                )
            )
            assert job is not None and job.state == "queued" and job.consumer_attempts == 0
            assert outbox is not None and outbox.state == "pending"
            assert outbox.publication_attempts == 0

    asyncio.run(run())


def test_later_slot_cannot_starve_its_earlier_retry_at_dispatch_limit_one(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        rule = await case.active()
        first = await case.admit(rule.id)
        case.clock[0] += timedelta(seconds=300)
        later = await case.admit(rule.id)
        initial = await case.store.claim_evaluation_dispatches(
            dispatcher_id="first-publication", limit=1
        )
        assert len(initial) == 1 and initial[0].message == first
        assert await case.store.defer_evaluation_dispatch(
            initial[0], failure=AlertReason.PUBLICATION_UNAVAILABLE
        )
        case.clock[0] += timedelta(seconds=1)
        with case.sessions() as session:
            original_prefix = session.scalar(
                select(AlertEvaluationOutboxModel.job_id)
                .where(AlertEvaluationOutboxModel.job_id.in_((first.job_id, later.job_id)))
                .order_by(AlertEvaluationOutboxModel.available_at)
                .limit(1)
            )
            assert original_prefix == later.job_id
        retry = await case.store.claim_evaluation_dispatches(dispatcher_id="ordered-retry", limit=1)
        assert len(retry) == 1 and retry[0].message == first
        assert retry[0].publication_attempt == 2
        with case.sessions() as session:
            later_job = session.get(AlertEvaluationJobModel, later.job_id)
            later_outbox = session.scalar(
                select(AlertEvaluationOutboxModel).where(
                    AlertEvaluationOutboxModel.job_id == later.job_id
                )
            )
            assert later_job is not None and later_job.consumer_attempts == 0
            assert later_outbox is not None and later_outbox.publication_attempts == 0
        assert await case.store.acknowledge_evaluation_dispatch(retry[0])
        assert (
            await execute_alert_message(case.store, first, consumer_id="predecessor")
            is AlertExecutionState.COMPLETED
        )
        next_claim = await case.store.claim_evaluation_dispatches(
            dispatcher_id="successor", limit=1
        )
        assert len(next_claim) == 1 and next_claim[0].message == later
        assert await case.store.acknowledge_evaluation_dispatch(next_claim[0])
        assert (
            await execute_alert_message(case.store, later, consumer_id="successor")
            is AlertExecutionState.COMPLETED
        )

    asyncio.run(run())
