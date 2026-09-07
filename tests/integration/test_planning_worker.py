"""Real PostgreSQL orchestration across dispatcher/consumer object restarts."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.planning import calculate_contribution_plan
from trading212_application.planning import ContributionPlanDetailQuery, PlanJobState
from trading212_application.planning_jobs import PlanTaskMessage
from trading212_persistence import (
    PostgresPlanningService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.planning_models import ContributionPlanResultModel
from trading212_worker.plan_tasks import (
    PlanExecutionState,
    dispatch_plans_once,
    execute_plan_message,
)

from tests.integration.test_planning_postgres import (
    KEY,
    NOW,
    command_input,
    create,
    service,
    user,
)
from tests.integration.test_planning_postgres import planning_database as planning_database

pytestmark = pytest.mark.integration


class DeliveryQueue:
    """Test transport; the production relay and worker still own state transitions."""

    def __init__(self) -> None:
        self.messages: list[PlanTaskMessage] = []

    def publish(self, message: PlanTaskMessage) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_committed_request_survives_process_objects_and_duplicate_delivery(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    initial = service(planning_database)
    queued = await create(initial, command_input(planning_database[1]))
    # A new engine/service has no in-memory request, outbox or result cache.
    restarted_engine = create_database_engine(
        planning_database[0].url.render_as_string(hide_password=False)
    )
    try:
        restarted = PostgresPlanningService(
            sessions=create_session_factory(restarted_engine),
            cursor_signing_key=KEY,
            clock=lambda: NOW,
        )
        queue = DeliveryQueue()
        dispatched = await dispatch_plans_once(restarted, queue, dispatcher_id="worker-integration")
        matching = [message for message in queue.messages if message.job_id == queued.job_id]
        assert dispatched.published >= 1 and len(matching) == 1
        assert set(matching[0].to_wire()) == {
            "job_id",
            "request_id",
            "owner_id",
            "account_id",
            "input_digest",
        }
        states = await asyncio.gather(
            *(
                execute_plan_message(
                    restarted,
                    matching[0],
                    consumer_id="worker-integration",
                    calculate=calculate_contribution_plan,
                )
                for _ in range(2)
            )
        )
        assert set(states) == {PlanExecutionState.COMPLETED, PlanExecutionState.NOT_CLAIMED}
        detail = await initial.get_contribution_plan(
            user(), queued.plan_id, query=ContributionPlanDetailQuery(limit=100)
        )
        assert detail.job.state is PlanJobState.SUCCEEDED
        assert detail.result is not None and detail.result.residual_cash is not None
        assert detail.job.input_digest == queued.input_digest
        assert sum(
            (line.recommended_amount.amount for line in detail.lines.items), Decimal(0)
        ) + detail.result.residual_cash.amount == Decimal("20")
        with planning_database[1]() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ContributionPlanResultModel)
                    .where(ContributionPlanResultModel.request_id == UUID(queued.request_id))
                )
                == 1
            )
    finally:
        restarted_engine.dispose()


@pytest.mark.asyncio
async def test_expired_consumer_is_recovered_by_actual_relay_and_stale_completion_is_fenced(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    clock = [NOW]
    original = service(planning_database, clock)
    queued = await create(original, command_input(planning_database[1]))
    first_delivery = DeliveryQueue()
    await dispatch_plans_once(original, first_delivery, dispatcher_id="worker-before-restart")
    message = next(item for item in first_delivery.messages if item.job_id == queued.job_id)
    abandoned = await original.claim_plan_job(message, consumer_id="terminated-worker")
    assert abandoned is not None
    pinned = await original.load_plan_job_input(abandoned)
    clock[0] += timedelta(seconds=61)
    recovered = service(planning_database, clock)
    redelivery = DeliveryQueue()
    await dispatch_plans_once(recovered, redelivery, dispatcher_id="worker-after-restart")
    assert next(item for item in redelivery.messages if item.job_id == queued.job_id) == message
    assert (
        await execute_plan_message(
            recovered,
            message,
            consumer_id="replacement-worker",
            calculate=calculate_contribution_plan,
        )
        is PlanExecutionState.COMPLETED
    )
    assert not await original.complete_plan_job(abandoned, calculate_contribution_plan(pinned))
    detail = await recovered.get_contribution_plan(
        user(), queued.plan_id, query=ContributionPlanDetailQuery()
    )
    assert detail.job.job_id == queued.job_id and detail.job.state is PlanJobState.SUCCEEDED
