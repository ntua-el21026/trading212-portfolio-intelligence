"""Real fenced projection jobs, immutable replay and exact retained capacity charges."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from trading212_analytics.projection import calculate_projection, calculate_projection_chunk
from trading212_application import projection as app
from trading212_application import projection_jobs as jobs
from trading212_application.projection_views import ProjectionRunView
from trading212_application.risk import PremiumJobState
from trading212_persistence.models import PrincipalModel
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from trading212_persistence.projection_job_store import PostgresProjectionJobStore
from trading212_persistence.projection_models import ProjectionChunkModel, ProjectionResultModel
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_security.principals import Scope
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def store(
    case: ProjectionJobCase, clock: Callable[[], datetime] | None = None
) -> PostgresProjectionJobStore:
    return PostgresProjectionJobStore(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=clock or (lambda: case.now)
    )


async def admitted(
    case: ProjectionJobCase, worker: PostgresProjectionJobStore
) -> jobs.ProjectionDispatchClaim:
    claims = await worker.claim_projection_dispatches(dispatcher_id="projection-dispatcher")
    assert len(claims) == 1 and claims[0].message.run_id == str(case.run.id)
    return claims[0]


async def cancel(case: ProjectionJobCase, identifier: UUID) -> ProjectionRunView:
    return await case.service.cancel_run(
        case.principal,
        app.CancelProjectionRun(
            run_id=identifier,
            idempotency_key=str(uuid4()),
            correlation_id="projection-job-cancel",
        ),
    )


def charged(case: ProjectionJobCase, *, active: int = 0) -> int:
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        size = session.scalar(select(func.projection_storage_bytes(root.id)))
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert isinstance(size, int) and size > 0
        assert root.retained_bytes == size and root.reserved_bytes == 0
        assert capacity.active_jobs == active and capacity.reserved_bytes == active * 33_554_432
        assert capacity.retained_bytes >= size
        return size


async def test_dispatch_chunks_complete_and_saved_read_are_atomic(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    worker = store(case)
    dispatch = await admitted(case, worker)
    assert set(dispatch.message.to_wire()) == {
        "job_id",
        "run_id",
        "owner_id",
        "account_id",
        "input_digest",
    }
    assert await worker.acknowledge_projection_dispatch(dispatch)
    claim = await worker.claim_projection_job(dispatch.message, consumer_id="projection-consumer")
    assert claim is not None and claim.consumer_attempt == 1
    assert await worker.claim_projection_job(dispatch.message, consumer_id="duplicate") is None
    captured = await worker.load_projection_job_input(claim)
    assert captured.numerical_input_digest != dispatch.message.input_digest
    assert await worker.load_projection_job_chunks(claim) == ()
    chunks = tuple(
        calculate_projection_chunk(captured.inputs, start, min(2, captured.inputs.paths - start))
        for start in range(0, captured.inputs.paths, 2)
    )
    for chunk in chunks:
        assert await worker.save_projection_job_chunk(claim, chunk)
    first = await worker.load_projection_job_chunks(claim, limit=2)
    second = await worker.load_projection_job_chunks(
        claim, after=(first[-1].variant, first[-1].paths[0].index), limit=2
    )
    assert first + second == chunks
    assert (
        await worker.load_projection_job_chunks(
            claim, after=(second[-1].variant, second[-1].paths[0].index), limit=2
        )
        == ()
    )
    result = calculate_projection(captured.inputs)
    assert await worker.heartbeat_projection_job(claim)
    assert await worker.complete_projection_job(claim, result)
    assert not await worker.complete_projection_job(claim, result)
    assert not await worker.heartbeat_projection_job(claim)
    with patch(
        "trading212_analytics.projection.calculate_projection_chunk",
        side_effect=AssertionError("saved read must not resample"),
    ):
        saved = await case.service.get_run(
            case.principal, case.run.id, app.ProjectionPointPageQuery(point_limit=1)
        )
    assert saved.state is PremiumJobState.SUCCEEDED and saved.result is not None
    with case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProjectionResultModel)
                .where(ProjectionResultModel.run_id == case.run.id)
            )
            == 1
        )
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert capacity.retained_bytes == charged(case)


async def test_restart_reuses_original_chunks_and_rejects_old_fence(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    now = [case.now]
    worker = store(case, lambda: now[0])
    dispatch = await admitted(case, worker)
    old = await worker.claim_projection_job(dispatch.message, consumer_id="before-crash")
    assert old is not None
    captured = await worker.load_projection_job_input(old)
    chunk = calculate_projection_chunk(captured.inputs, 0, 2)
    assert await worker.save_projection_job_chunk(old, chunk)
    with case.sessions() as session:
        row = session.scalar(
            select(ProjectionChunkModel).where(ProjectionChunkModel.run_id == case.run.id)
        )
        assert row is not None
        before = (row.id, row.created_at, row.lease_token, row.consumer_attempt, row.content_digest)
    now[0] += timedelta(seconds=61)
    resumed = store(case, lambda: now[0])
    new = await resumed.claim_projection_job(dispatch.message, consumer_id="after-crash")
    assert new is not None and new.consumer_attempt == 2 and new.claim_token != old.claim_token
    assert new.deadline_at == old.deadline_at
    assert not await resumed.save_projection_job_chunk(old, chunk)
    assert not await resumed.save_projection_job_chunk(replace(new, consumer_attempt=1), chunk)
    assert await resumed.load_projection_job_chunks(new) == (chunk,)
    assert await resumed.save_projection_job_chunk(new, chunk)
    with case.sessions() as session:
        row = session.scalar(
            select(ProjectionChunkModel).where(ProjectionChunkModel.run_id == case.run.id)
        )
        assert row is not None
        assert before == (
            row.id,
            row.created_at,
            row.lease_token,
            row.consumer_attempt,
            row.content_digest,
        )
    remaining = calculate_projection_chunk(captured.inputs, 2, captured.inputs.paths - 2)
    assert await resumed.save_projection_job_chunk(new, remaining)
    assert await resumed.complete_projection_job(new, calculate_projection(captured.inputs))
    charged(case)


async def test_overlapping_chunk_and_incomplete_result_cannot_seal(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    worker = store(case)
    dispatch = await admitted(case, worker)
    claim = await worker.claim_projection_job(dispatch.message, consumer_id="complete-partition")
    assert claim is not None
    captured = await worker.load_projection_job_input(claim)
    assert await worker.save_projection_job_chunk(
        claim, calculate_projection_chunk(captured.inputs, 0, 2)
    )
    with pytest.raises(jobs.ProjectionJobInputError):
        await worker.save_projection_job_chunk(
            claim, calculate_projection_chunk(captured.inputs, 1, 2)
        )
    with pytest.raises(jobs.ProjectionJobInputError):
        await worker.complete_projection_job(claim, calculate_projection(captured.inputs))
    with case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProjectionChunkModel)
                .where(ProjectionChunkModel.run_id == case.run.id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProjectionResultModel)
                .where(ProjectionResultModel.run_id == case.run.id)
            )
            == 0
        )
        root = session.get_one(PremiumRunModel, case.run.id)
        assert (root.reserved_bytes, root.retained_bytes) == (33_554_432, 0)
    assert await worker.fail_projection_job(
        claim, failure_code=jobs.ProjectionJobFailureCode.INPUT_CHANGED, retryable=False
    )
    charged(case)


async def test_ambiguous_publish_old_ack_and_redis_loss_redelivery(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    now = [case.now]
    worker = store(case, lambda: now[0])
    old = await admitted(case, worker)
    now[0] += timedelta(seconds=31)
    claims = await worker.claim_projection_dispatches(dispatcher_id="after-dispatch-crash")
    assert (
        len(claims) == 1 and claims[0].message == old.message and claims[0].publication_attempt == 2
    )
    assert not await worker.acknowledge_projection_dispatch(old)
    assert not await worker.acknowledge_projection_dispatch(
        replace(claims[0], publication_attempt=1)
    )
    assert await worker.acknowledge_projection_dispatch(claims[0])
    now[0] += timedelta(seconds=61)
    replay = await worker.claim_projection_dispatches(dispatcher_id="after-redis-loss")
    assert (
        len(replay) == 1 and replay[0].message == old.message and replay[0].publication_attempt == 3
    )
    await cancel(case, case.run.id)
    assert not await worker.acknowledge_projection_dispatch(replay[0])
    charged(case)


async def test_two_owner_jobs_share_one_global_slot_and_cancel_preserves_copies(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    worker = store(case)
    first = await admitted(case, worker)
    second = await case.service.create_run(
        case.principal, replace(case.command, idempotency_key=str(uuid4()))
    )
    with pytest.raises(app.ProjectionServiceError) as maximum:
        await case.service.create_run(
            case.principal, replace(case.command, idempotency_key=str(uuid4()))
        )
    assert maximum.value.code is app.ProjectionErrorCode.RATE_LIMITED
    second_message = jobs.ProjectionTaskMessage(
        str(second.job_id),
        str(second.id),
        first.message.owner_id,
        first.message.account_id,
        second.capture_digest,
    )
    claims = await asyncio.gather(
        worker.claim_projection_job(first.message, consumer_id="slot-one"),
        store(case).claim_projection_job(second_message, consumer_id="slot-two"),
    )
    assert sum(value is not None for value in claims) == 1
    winner = next(value for value in claims if value is not None)
    captured = await worker.load_projection_job_input(winner)
    chunk = calculate_projection_chunk(captured.inputs, 0, 2)
    assert await worker.save_projection_job_chunk(winner, chunk)
    await cancel(case, UUID(winner.message.run_id))
    assert not await worker.save_projection_job_chunk(winner, chunk)
    other = second_message if winner.message == first.message else first.message
    next_claim = await worker.claim_projection_job(other, consumer_id="released-slot")
    assert next_claim is not None
    assert await worker.fail_projection_job(
        next_claim, failure_code=jobs.ProjectionJobFailureCode.CALCULATION_FAILED, retryable=False
    )
    with case.sessions() as session:
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        sizes = tuple(
            session.scalars(
                select(func.projection_storage_bytes(PremiumRunModel.id)).where(
                    PremiumRunModel.id.in_((case.run.id, second.id))
                )
            )
        )
        assert len(sizes) == 2 and all(size > 0 for size in sizes)
        assert capacity.active_jobs == capacity.reserved_bytes == 0
        assert capacity.retained_bytes == sum(sizes)


@pytest.mark.parametrize("operation", ("load", "chunks", "save", "complete"))
async def test_revoked_grant_prevents_private_decode_and_publication(
    projection_job_case: ProjectionJobCase, operation: str
) -> None:
    case = projection_job_case
    worker = store(case)
    dispatch = await admitted(case, worker)
    claim = await worker.claim_projection_job(dispatch.message, consumer_id="revocation")
    assert claim is not None
    captured = await worker.load_projection_job_input(claim)
    chunk = calculate_projection_chunk(captured.inputs, 0, 2)
    result = calculate_projection(captured.inputs)
    with case.sessions() as session, session.begin():
        identity = session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.issuer == case.principal.issuer,
                PrincipalModel.subject == case.principal.subject,
            )
        )
        assert identity is not None
        grant = session.get_one(
            PrincipalScopeGrantModel, (identity.id, Scope.PROJECTIONS_WRITE.value)
        )
        grant.revoked_at = case.now
    seen: list[str] = []

    def observe(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        seen.append(statement.lower())

    event.listen(case.engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(jobs.ProjectionJobInputError) as denied:
            if operation == "load":
                await worker.load_projection_job_input(claim)
            elif operation == "chunks":
                await worker.load_projection_job_chunks(claim)
            elif operation == "save":
                await worker.save_projection_job_chunk(claim, chunk)
            else:
                await worker.complete_projection_job(claim, result)
    finally:
        event.remove(case.engine, "before_cursor_execute", observe)
    assert denied.value.code is jobs.ProjectionJobFailureCode.ACCESS_DENIED
    assert not any(
        table in query
        for query in seen
        for table in (
            "projection_inputs",
            "projection_points",
            "canonical_chunk",
            "canonical_result",
            "canonical_proof",
        )
    )
    assert await worker.fail_projection_job(
        claim, failure_code=jobs.ProjectionJobFailureCode.ACCESS_DENIED, retryable=False
    )
    charged(case)


async def test_absolute_deadline_cannot_restart_after_requeue(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    now = [case.now]
    worker = store(case, lambda: now[0])
    dispatch = await admitted(case, worker)
    first = await worker.claim_projection_job(dispatch.message, consumer_id="deadline-first")
    assert first is not None and first.deadline_at == now[0] + timedelta(seconds=240)
    assert await worker.fail_projection_job(
        first, failure_code=jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
    )
    now[0] += timedelta(seconds=100)
    second = await worker.claim_projection_job(dispatch.message, consumer_id="deadline-second")
    assert second is not None and second.deadline_at == first.deadline_at
    assert await worker.fail_projection_job(
        second, failure_code=jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
    )
    now[0] = first.deadline_at + timedelta(seconds=1)
    assert (
        await worker.claim_projection_dispatches(dispatcher_id="cannot-republish-expired-budget")
        == ()
    )
    assert (
        await worker.claim_projection_job(dispatch.message, consumer_id="cannot-reset-budget")
        is None
    )
    with case.sessions() as session:
        job = session.get_one(PremiumJobModel, case.run.job_id)
        assert job.state == "failed" and job.failure_code == "attempts_exhausted"
    charged(case)


async def test_four_consumer_attempts_are_global_across_service_restarts(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    worker = store(case)
    dispatch = await admitted(case, worker)
    for number in range(1, 5):
        worker = store(case)
        claim = await worker.claim_projection_job(
            dispatch.message, consumer_id=f"consumer-{number}"
        )
        assert claim is not None and claim.consumer_attempt == number
        assert await worker.fail_projection_job(
            claim, failure_code=jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
        )
    assert await store(case).claim_projection_job(dispatch.message, consumer_id="fifth") is None
    charged(case)


async def test_eight_publication_attempts_end_with_retained_input_charge(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    now = [case.now]
    worker = store(case, lambda: now[0])
    for number in range(1, 9):
        claims = await worker.claim_projection_dispatches(dispatcher_id="publisher")
        assert len(claims) == 1 and claims[0].publication_attempt == number
        assert await worker.defer_projection_dispatch(
            claims[0], failure_code=jobs.ProjectionJobFailureCode.PUBLICATION_UNAVAILABLE
        )
        now[0] += timedelta(seconds=61)
    assert await worker.claim_projection_dispatches(dispatcher_id="ninth") == ()
    with case.sessions() as session:
        job = session.get_one(PremiumJobModel, case.run.job_id)
        outbox = session.scalar(
            select(PremiumOutboxModel).where(PremiumOutboxModel.job_id == job.id)
        )
        assert (
            outbox is not None
            and outbox.publication_attempts == 8
            and outbox.state == "dead_letter"
        )
        assert job.state == "failed" and job.failure_code == "attempts_exhausted"
    charged(case)


async def test_foreign_full_capture_digest_cannot_claim_or_read(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    worker = store(case)
    dispatch = await admitted(case, worker)
    assert (
        await worker.claim_projection_job(
            replace(dispatch.message, input_digest="0" * 64), consumer_id="wrong-capture"
        )
        is None
    )
    assert (
        await worker.claim_projection_job(
            replace(dispatch.message, account_id=str(uuid4())), consumer_id="foreign-account"
        )
        is None
    )
    assert (
        await worker.claim_projection_job(
            replace(dispatch.message, owner_id=str(uuid4())), consumer_id="foreign-owner"
        )
        is None
    )
    with case.sessions() as session:
        job = session.get_one(PremiumJobModel, case.run.job_id)
        assert job.state == "queued" and job.consumer_attempts == 0
