"""Real durable risk jobs: redelivery, revoked grants, global capacity and stale workers."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_analytics.risk import calculate_risk
from trading212_analytics.risk_history import validate_risk_capacity
from trading212_application import risk as app
from trading212_application import risk_jobs as jobs
from trading212_persistence.models import PrincipalModel
from trading212_persistence.premium_models import PremiumCapacityModel, PremiumJobModel
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_persistence.risk_job_store import PostgresRiskJobStore
from trading212_persistence.risk_models import RiskResultModel
from trading212_security.principals import Scope
from trading212_worker.historical_seed import CURSOR_KEY

from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import NOW
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case

pytestmark = pytest.mark.integration


def store(case: RunCase, clock: Callable[[], datetime] | None = None) -> PostgresRiskJobStore:
    return PostgresRiskJobStore(
        case.sessions,
        cursor_signing_key=CURSOR_KEY,
        preflight=validate_risk_capacity,
        clock=clock or (lambda: NOW),
    )


async def admitted(
    case: RunCase, worker: PostgresRiskJobStore
) -> tuple[app.RiskRunView, jobs.RiskDispatchClaim]:
    run = await case.service.create_run(case.principal, case.command)
    claims = await worker.claim_risk_dispatches(dispatcher_id="risk-dispatcher")
    assert len(claims) == 1
    assert claims[0].message.run_id == str(run.id)
    return run, claims[0]


async def test_dispatch_claim_execute_and_atomic_result(run_case: RunCase) -> None:
    worker = store(run_case)
    run, dispatch = await admitted(run_case, worker)
    assert set(dispatch.message.to_wire()) == {
        "job_id",
        "run_id",
        "owner_id",
        "account_id",
        "input_digest",
    }
    assert await worker.acknowledge_risk_dispatch(dispatch)
    claim = await worker.claim_risk_job(dispatch.message, consumer_id="risk-consumer")
    assert claim is not None and claim.consumer_attempt == 1
    assert await worker.claim_risk_job(dispatch.message, consumer_id="duplicate") is None
    inputs = await worker.load_risk_job_input(claim)
    result = calculate_risk(
        inputs.historical, inputs.definition, assets=inputs.assets, xray=inputs.xray
    )
    assert await worker.heartbeat_risk_job(claim)
    assert await worker.complete_risk_job(claim, result)
    assert not await worker.complete_risk_job(claim, result)
    assert not await worker.heartbeat_risk_job(claim)
    assert (await run_case.service.get_run(run_case.principal, run.id)).result is not None
    with run_case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RiskResultModel)
                .where(RiskResultModel.run_id == run.id)
            )
            == 1
        )
        capacity = session.get(PremiumCapacityModel, UUID(run_case.principal.owner_id))
        assert capacity is not None and capacity.active_jobs == capacity.reserved_bytes == 0
        assert capacity.retained_bytes > 0


async def test_ambiguous_publish_old_ack_and_redis_loss_redelivery(run_case: RunCase) -> None:
    now = [NOW]
    worker = store(run_case, lambda: now[0])
    run, old = await admitted(run_case, worker)
    now[0] += timedelta(seconds=31)
    claims = await worker.claim_risk_dispatches(dispatcher_id="after-dispatch-crash")
    assert len(claims) == 1 and claims[0].message == old.message
    assert claims[0].publication_attempt == 2
    assert not await worker.acknowledge_risk_dispatch(old)
    assert await worker.acknowledge_risk_dispatch(claims[0])
    now[0] += timedelta(seconds=61)
    replay = await store(run_case, lambda: now[0]).claim_risk_dispatches(
        dispatcher_id="after-redis-loss"
    )
    assert (
        len(replay) == 1 and replay[0].message == old.message and replay[0].publication_attempt == 3
    )
    await run_case.service.cancel_run(
        run_case.principal,
        app.CancelRiskRun(
            run_id=run.id, idempotency_key=str(uuid4()), correlation_id="cancel-redelivery"
        ),
    )
    assert not await worker.acknowledge_risk_dispatch(replay[0])


async def test_restart_reclaims_expired_lease_and_fences_old_worker(run_case: RunCase) -> None:
    now = [NOW]
    worker = store(run_case, lambda: now[0])
    run, dispatch = await admitted(run_case, worker)
    old = await worker.claim_risk_job(dispatch.message, consumer_id="before-crash")
    assert old is not None
    inputs = await worker.load_risk_job_input(old)
    result = calculate_risk(
        inputs.historical, inputs.definition, assets=inputs.assets, xray=inputs.xray
    )
    now[0] += timedelta(seconds=61)
    resumed = store(run_case, lambda: now[0])
    new = await resumed.claim_risk_job(dispatch.message, consumer_id="after-crash")
    assert new is not None and new.claim_token != old.claim_token and new.consumer_attempt == 2
    assert not await worker.complete_risk_job(old, result)
    assert await resumed.complete_risk_job(new, result)
    assert (
        await run_case.service.get_run(run_case.principal, run.id)
    ).state is app.PremiumJobState.SUCCEEDED


async def test_cancellation_fences_inflight_result_and_releases_single_slot(
    run_case: RunCase,
) -> None:
    worker = store(run_case)
    first, dispatch = await admitted(run_case, worker)
    claim = await worker.claim_risk_job(dispatch.message, consumer_id="one-global-slot")
    assert claim is not None
    second = await run_case.service.create_run(
        run_case.principal, replace(run_case.command, idempotency_key=str(uuid4()))
    )
    second_message = jobs.RiskTaskMessage(
        str(second.job_id),
        str(second.id),
        dispatch.message.owner_id,
        dispatch.message.account_id,
        second.input_digest,
    )
    assert await worker.claim_risk_job(second_message, consumer_id="must-wait") is None
    await run_case.service.cancel_run(
        run_case.principal,
        app.CancelRiskRun(
            run_id=first.id, idempotency_key=str(uuid4()), correlation_id="cancel-inflight"
        ),
    )
    assert not await worker.heartbeat_risk_job(claim)
    assert not await worker.fail_risk_job(
        claim, failure_code=jobs.RiskJobFailureCode.CALCULATION_FAILED, retryable=True
    )
    second_claim = await worker.claim_risk_job(second_message, consumer_id="released-slot")
    assert second_claim is not None
    assert await worker.fail_risk_job(
        second_claim, failure_code=jobs.RiskJobFailureCode.CALCULATION_FAILED, retryable=False
    )


async def test_revocation_after_load_blocks_publication_without_private_payload(
    run_case: RunCase,
) -> None:
    worker = store(run_case)
    run, dispatch = await admitted(run_case, worker)
    claim = await worker.claim_risk_job(dispatch.message, consumer_id="revocation-case")
    assert claim is not None
    inputs = await worker.load_risk_job_input(claim)
    result = calculate_risk(
        inputs.historical, inputs.definition, assets=inputs.assets, xray=inputs.xray
    )
    with run_case.sessions() as session, session.begin():
        identity = session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.issuer == run_case.principal.issuer,
                PrincipalModel.subject == run_case.principal.subject,
            )
        )
        assert identity is not None
        grant = session.get(PrincipalScopeGrantModel, (identity.id, Scope.RISK_WRITE.value))
        assert grant is not None
        grant.revoked_at = NOW
    with pytest.raises(jobs.RiskJobInputError) as failure:
        await worker.complete_risk_job(claim, result)
    assert failure.value.code is jobs.RiskJobFailureCode.ACCESS_DENIED
    assert await worker.fail_risk_job(claim, failure_code=failure.value.code, retryable=False)
    with run_case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RiskResultModel)
                .where(RiskResultModel.run_id == run.id)
            )
            == 0
        )
        job = session.get(PremiumJobModel, run.job_id)
        assert job is not None and job.failure_code == "access_denied"


async def test_expired_execution_and_tampered_delivery_never_load_input(run_case: RunCase) -> None:
    now = [NOW]
    worker = store(run_case, lambda: now[0])
    run, dispatch = await admitted(run_case, worker)
    assert (
        await worker.claim_risk_job(
            replace(dispatch.message, input_digest="0" * 64), consumer_id="tampered"
        )
        is None
    )
    assert (
        await worker.claim_risk_job(
            replace(dispatch.message, owner_id=str(uuid4())), consumer_id="foreign"
        )
        is None
    )
    claim = await worker.claim_risk_job(dispatch.message, consumer_id="deadline-case")
    assert claim is not None and claim.deadline_at == NOW + timedelta(seconds=240)
    now[0] += timedelta(seconds=241)
    assert not await worker.heartbeat_risk_job(claim)
    assert await worker.claim_risk_job(dispatch.message, consumer_id="expired") is None
    assert (
        await run_case.service.get_run(run_case.principal, run.id)
    ).state is app.PremiumJobState.FAILED


async def test_actual_worker_process_publishes_through_same_fenced_store(run_case: RunCase) -> None:
    from trading212_worker.risk_tasks import RiskExecutionState, execute_risk_message

    worker = store(run_case)
    run, dispatch = await admitted(run_case, worker)
    assert await worker.acknowledge_risk_dispatch(dispatch)
    state = await execute_risk_message(
        worker, dispatch.message, consumer_id="actual-risk-process", clock=lambda: NOW
    )
    assert state is RiskExecutionState.SUCCEEDED
    result = await run_case.service.get_run(run_case.principal, run.id)
    assert (
        result.result is not None and result.result.observed.volatility_annualized.value is not None
    )
