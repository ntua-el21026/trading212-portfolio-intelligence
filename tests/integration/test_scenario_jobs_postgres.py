"""Real durable scenario jobs: redelivery, revoked grants, global capacity and stale workers."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_analytics.scenario import calculate_scenario
from trading212_analytics.scenario_replay import resolve_scenario_replay
from trading212_application import scenario as app
from trading212_application import scenario_jobs as jobs
from trading212_application.risk import PremiumJobState
from trading212_application.scenario_views import ScenarioRunView
from trading212_persistence.models import PrincipalModel
from trading212_persistence.premium_models import PremiumCapacityModel, PremiumJobModel
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_persistence.scenario_job_store import PostgresScenarioJobStore
from trading212_persistence.scenario_models import ScenarioResultModel
from trading212_security.principals import Scope
from trading212_worker.historical_seed import CURSOR_KEY

from tests.integration.test_scenario_runs_postgres import ScenarioCase
from tests.integration.test_scenario_runs_postgres import scenario_case as scenario_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def store(
    case: ScenarioCase, clock: Callable[[], datetime] | None = None
) -> PostgresScenarioJobStore:
    return PostgresScenarioJobStore(
        case.sessions,
        cursor_signing_key=CURSOR_KEY,
        replay_resolver=resolve_scenario_replay,
        clock=clock or (lambda: case.now),
    )


async def admitted(
    case: ScenarioCase, worker: PostgresScenarioJobStore
) -> tuple[ScenarioRunView, jobs.ScenarioDispatchClaim]:
    run = await case.service.create_run(case.principal, case.command)
    claims = await worker.claim_scenario_dispatches(dispatcher_id="scenario-dispatcher")
    assert len(claims) == 1
    assert claims[0].message.run_id == str(run.id)
    return run, claims[0]


async def test_dispatch_claim_execute_and_atomic_result(scenario_case: ScenarioCase) -> None:
    worker = store(scenario_case)
    run, dispatch = await admitted(scenario_case, worker)
    assert set(dispatch.message.to_wire()) == {
        "job_id",
        "run_id",
        "owner_id",
        "account_id",
        "input_digest",
    }
    assert await worker.acknowledge_scenario_dispatch(dispatch)
    claim = await worker.claim_scenario_job(dispatch.message, consumer_id="scenario-consumer")
    assert claim is not None and claim.consumer_attempt == 1
    assert await worker.claim_scenario_job(dispatch.message, consumer_id="duplicate") is None
    inputs = await worker.load_scenario_job_input(claim)
    result = calculate_scenario(inputs)
    assert await worker.heartbeat_scenario_job(claim)
    assert await worker.complete_scenario_job(claim, result)
    assert not await worker.complete_scenario_job(claim, result)
    assert not await worker.heartbeat_scenario_job(claim)
    assert (
        await scenario_case.service.get_run(
            scenario_case.principal, run.id, app.ScenarioComponentPageQuery()
        )
    ).result is not None
    with scenario_case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ScenarioResultModel)
                .where(ScenarioResultModel.run_id == run.id)
            )
            == 1
        )
        capacity = session.get(PremiumCapacityModel, UUID(scenario_case.principal.owner_id))
        assert capacity is not None and capacity.active_jobs == capacity.reserved_bytes == 0
        assert capacity.retained_bytes > 0


async def test_ambiguous_publish_old_ack_and_redis_loss_redelivery(
    scenario_case: ScenarioCase,
) -> None:
    now = [scenario_case.now]
    worker = store(scenario_case, lambda: now[0])
    run, old = await admitted(scenario_case, worker)
    now[0] += timedelta(seconds=31)
    claims = await worker.claim_scenario_dispatches(dispatcher_id="after-dispatch-crash")
    assert len(claims) == 1 and claims[0].message == old.message
    assert claims[0].publication_attempt == 2
    assert not await worker.acknowledge_scenario_dispatch(old)
    assert await worker.acknowledge_scenario_dispatch(claims[0])
    now[0] += timedelta(seconds=61)
    replay = await store(scenario_case, lambda: now[0]).claim_scenario_dispatches(
        dispatcher_id="after-redis-loss"
    )
    assert (
        len(replay) == 1 and replay[0].message == old.message and replay[0].publication_attempt == 3
    )
    await scenario_case.service.cancel_run(
        scenario_case.principal,
        app.CancelScenarioRun(
            run_id=run.id, idempotency_key=str(uuid4()), correlation_id="cancel-redelivery"
        ),
    )
    assert not await worker.acknowledge_scenario_dispatch(replay[0])


async def test_restart_reclaims_expired_lease_and_fences_old_worker(
    scenario_case: ScenarioCase,
) -> None:
    now = [scenario_case.now]
    worker = store(scenario_case, lambda: now[0])
    run, dispatch = await admitted(scenario_case, worker)
    old = await worker.claim_scenario_job(dispatch.message, consumer_id="before-crash")
    assert old is not None
    inputs = await worker.load_scenario_job_input(old)
    result = calculate_scenario(inputs)
    now[0] += timedelta(seconds=61)
    resumed = store(scenario_case, lambda: now[0])
    new = await resumed.claim_scenario_job(dispatch.message, consumer_id="after-crash")
    assert new is not None and new.claim_token != old.claim_token and new.consumer_attempt == 2
    assert not await worker.complete_scenario_job(old, result)
    assert await resumed.complete_scenario_job(new, result)
    assert (
        await scenario_case.service.get_run(
            scenario_case.principal, run.id, app.ScenarioComponentPageQuery()
        )
    ).state is PremiumJobState.SUCCEEDED


async def test_cancellation_fences_inflight_result_and_releases_single_slot(
    scenario_case: ScenarioCase,
) -> None:
    worker = store(scenario_case)
    first, dispatch = await admitted(scenario_case, worker)
    claim = await worker.claim_scenario_job(dispatch.message, consumer_id="one-global-slot")
    assert claim is not None
    second = await scenario_case.service.create_run(
        scenario_case.principal, replace(scenario_case.command, idempotency_key=str(uuid4()))
    )
    second_message = jobs.ScenarioTaskMessage(
        str(second.job_id),
        str(second.id),
        dispatch.message.owner_id,
        dispatch.message.account_id,
        second.input_digest,
    )
    assert await worker.claim_scenario_job(second_message, consumer_id="must-wait") is None
    await scenario_case.service.cancel_run(
        scenario_case.principal,
        app.CancelScenarioRun(
            run_id=first.id, idempotency_key=str(uuid4()), correlation_id="cancel-inflight"
        ),
    )
    assert not await worker.heartbeat_scenario_job(claim)
    assert not await worker.fail_scenario_job(
        claim, failure_code=jobs.ScenarioJobFailureCode.CALCULATION_FAILED, retryable=True
    )
    second_claim = await worker.claim_scenario_job(second_message, consumer_id="released-slot")
    assert second_claim is not None
    assert await worker.fail_scenario_job(
        second_claim, failure_code=jobs.ScenarioJobFailureCode.CALCULATION_FAILED, retryable=False
    )


async def test_revocation_after_load_blocks_publication_without_private_payload(
    scenario_case: ScenarioCase,
) -> None:
    worker = store(scenario_case)
    run, dispatch = await admitted(scenario_case, worker)
    claim = await worker.claim_scenario_job(dispatch.message, consumer_id="revocation-case")
    assert claim is not None
    inputs = await worker.load_scenario_job_input(claim)
    result = calculate_scenario(inputs)
    with scenario_case.sessions() as session, session.begin():
        identity = session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.issuer == scenario_case.principal.issuer,
                PrincipalModel.subject == scenario_case.principal.subject,
            )
        )
        assert identity is not None
        grant = session.get(PrincipalScopeGrantModel, (identity.id, Scope.SCENARIOS_WRITE.value))
        assert grant is not None
        grant.revoked_at = scenario_case.now
    with pytest.raises(jobs.ScenarioJobInputError) as failure:
        await worker.complete_scenario_job(claim, result)
    assert failure.value.code is jobs.ScenarioJobFailureCode.ACCESS_DENIED
    assert await worker.fail_scenario_job(claim, failure_code=failure.value.code, retryable=False)
    with scenario_case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ScenarioResultModel)
                .where(ScenarioResultModel.run_id == run.id)
            )
            == 0
        )
        job = session.get(PremiumJobModel, run.job_id)
        assert job is not None and job.failure_code == "access_denied"


async def test_expired_execution_and_tampered_delivery_never_load_input(
    scenario_case: ScenarioCase,
) -> None:
    now = [scenario_case.now]
    worker = store(scenario_case, lambda: now[0])
    run, dispatch = await admitted(scenario_case, worker)
    assert (
        await worker.claim_scenario_job(
            replace(dispatch.message, input_digest="0" * 64), consumer_id="tampered"
        )
        is None
    )
    assert (
        await worker.claim_scenario_job(
            replace(dispatch.message, owner_id=str(uuid4())), consumer_id="foreign"
        )
        is None
    )
    claim = await worker.claim_scenario_job(dispatch.message, consumer_id="deadline-case")
    assert claim is not None and claim.deadline_at == scenario_case.now + timedelta(seconds=240)
    now[0] += timedelta(seconds=241)
    assert not await worker.heartbeat_scenario_job(claim)
    assert await worker.claim_scenario_job(dispatch.message, consumer_id="expired") is None
    assert (
        await scenario_case.service.get_run(
            scenario_case.principal, run.id, app.ScenarioComponentPageQuery()
        )
    ).state is PremiumJobState.FAILED


async def test_actual_worker_process_publishes_through_same_fenced_store(
    scenario_case: ScenarioCase,
) -> None:
    from trading212_worker.scenario_tasks import ScenarioExecutionState, execute_scenario_message

    worker = store(scenario_case)
    run, dispatch = await admitted(scenario_case, worker)
    assert await worker.acknowledge_scenario_dispatch(dispatch)
    state = await execute_scenario_message(
        worker,
        dispatch.message,
        consumer_id="actual-scenario-process",
        clock=lambda: scenario_case.now,
    )
    assert state is ScenarioExecutionState.SUCCEEDED
    result = await scenario_case.service.get_run(
        scenario_case.principal, run.id, app.ScenarioComponentPageQuery()
    )
    assert result.result is not None
    assert result.result.context.input_digest == run.input_digest
    assert (
        result.result.context.pins.scenario_version_id == scenario_case.command.scenario_version_id
    )
    assert result.result.components.total > 0


async def test_consumer_retry_preserves_first_absolute_deadline(
    scenario_case: ScenarioCase,
) -> None:
    now = [scenario_case.now]
    worker = store(scenario_case, lambda: now[0])
    run, dispatch = await admitted(scenario_case, worker)
    first = await worker.claim_scenario_job(dispatch.message, consumer_id="initial-attempt")
    assert first is not None
    now[0] += timedelta(seconds=61)
    retry = await worker.claim_scenario_job(dispatch.message, consumer_id="resumed-attempt")
    assert retry is not None and retry.consumer_attempt == 2
    assert retry.deadline_at == first.deadline_at == scenario_case.now + timedelta(seconds=240)
    now[0] = first.deadline_at + timedelta(seconds=1)
    assert (
        await worker.claim_scenario_job(dispatch.message, consumer_id="cannot-reset-budget") is None
    )
    with scenario_case.sessions() as session:
        job = session.get_one(PremiumJobModel, run.job_id)
        assert job.state == "failed"


@pytest.mark.parametrize("cancel", [True, False])
async def test_terminal_failure_keeps_private_input_in_owner_byte_budget(
    scenario_case: ScenarioCase, cancel: bool
) -> None:
    from sqlalchemy import text
    from trading212_persistence.premium_models import PremiumRunModel

    worker = store(scenario_case)
    run, dispatch = await admitted(scenario_case, worker)
    if cancel:
        await scenario_case.service.cancel_run(
            scenario_case.principal,
            app.CancelScenarioRun(
                run_id=run.id, idempotency_key=str(uuid4()), correlation_id="bytes"
            ),
        )
    else:
        claim = await worker.claim_scenario_job(dispatch.message, consumer_id="failed-with-input")
        assert claim is not None
        assert await worker.fail_scenario_job(
            claim, failure_code=jobs.ScenarioJobFailureCode.CALCULATION_FAILED, retryable=False
        )
    with scenario_case.sessions() as session:
        root = session.get_one(PremiumRunModel, run.id)
        actual = session.scalar(text("SELECT scenario_storage_bytes(:run)"), {"run": run.id})
        capacity = session.get_one(PremiumCapacityModel, UUID(scenario_case.principal.owner_id))
        assert actual is not None and actual > 0
        assert root.reserved_bytes == capacity.reserved_bytes == capacity.active_jobs == 0
        assert root.retained_bytes == capacity.retained_bytes == actual
