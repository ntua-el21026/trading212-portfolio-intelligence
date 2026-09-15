"""Worker boundary regressions without SQL, a sampler child or a broker."""

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.projection import calculate_projection_chunk
from trading212_application import projection_jobs as jobs
from trading212_application.projection import ProjectionErrorCode
from trading212_domain.projection import ProjectionVariant
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_job_store import PostgresProjectionJobStore
from trading212_persistence.projection_result_store import StoredProjectionChunk
from trading212_security.principals import AuthorizationError

from tests.unit.persistence.projection_result_store_factories import AT, records


def worker() -> PostgresProjectionJobStore:
    return PostgresProjectionJobStore(
        cast(sessionmaker[Session], MagicMock()),
        cursor_signing_key=b"synthetic-projection-worker-key" * 2,
        clock=lambda: AT,
    )


def claim() -> jobs.ProjectionJobClaim:
    _, _, _, root, _, job = records()
    return jobs.ProjectionJobClaim(
        worker()._message(root, job),
        str(job.lease_token),
        AT + timedelta(seconds=60),
        job.consumer_attempts,
        AT + timedelta(seconds=60),
    )


def inline(session: Session) -> AsyncMock:
    async def run[T](action: Callable[[Session], T]) -> T:
        return action(session)

    return AsyncMock(side_effect=run)


@pytest.mark.parametrize(
    "changed", ("attempt", "token", "deadline", "expired", "terminal", "reservation")
)
def test_worker_fence_requires_exact_current_attempt_and_live_reserved_job(changed: str) -> None:
    value, session = worker(), MagicMock(spec=Session)
    _, _, _, root, _, job = records()
    request = claim()
    if changed == "attempt":
        request = replace(request, consumer_attempt=1)
    elif changed == "token":
        request = replace(request, claim_token=str(UUID(int=999)))
    elif changed == "deadline":
        request = replace(request, deadline_at=AT + timedelta(seconds=61))
    elif changed == "expired":
        job.lease_expires_at = AT
    elif changed == "terminal":
        job.state = "cancelled"
    else:
        root.retained_bytes = 1
    with patch.object(value, "_metadata", return_value=(root, job)):
        assert value._fenced(session, request) is None


def test_heartbeat_extending_lease_does_not_invalidate_original_claim() -> None:
    value, session = worker(), MagicMock(spec=Session)
    _, _, _, root, _, job = records()
    request = claim()
    job.lease_expires_at = AT + timedelta(seconds=45)
    with patch.object(value, "_metadata", return_value=(root, job)):
        assert value._fenced(session, request) == (root, job)


def test_original_consumer_attempt_clock_controls_all_retry_deadlines() -> None:
    value, session = worker(), MagicMock(spec=Session)
    _, _, _, root, _, job = records()
    session.scalar.return_value = AT
    with patch.object(value, "_now", return_value=AT + timedelta(seconds=200)):
        assert value._deadline(session, root, job) == AT + timedelta(seconds=240)
    root.expires_at = AT + timedelta(seconds=230)
    assert value._deadline(session, root, job) == root.expires_at
    session.scalar.return_value = None
    with pytest.raises(jobs.ProjectionJobInputError) as missing:
        value._deadline(session, root, job)
    assert missing.value.code is jobs.ProjectionJobFailureCode.INPUT_CHANGED


def test_durable_authorization_precedes_any_projection_metadata_or_input_query() -> None:
    value, session = worker(), MagicMock(spec=Session)
    _, _, _, root, _, _ = records()
    with (
        patch(
            "trading212_persistence.projection_job_store.authorize_report_job",
            side_effect=AuthorizationError("denied"),
        ),
        pytest.raises(AuthorizationError),
    ):
        value._auth(session, root)
    session.scalar.assert_not_called()
    session.execute.assert_not_called()


async def test_restricted_original_source_blocks_decode_and_chunk_reads() -> None:
    value, session = worker(), MagicMock(spec=Session)
    _, _, _, root, _, job = records()
    with (
        patch.object(value, "_worker_run", inline(session)),
        patch.object(value, "_fenced", return_value=(root, job)),
        patch.object(
            value,
            "_auth",
            side_effect=ProjectionStorageError(ProjectionErrorCode.SOURCE_UNAVAILABLE),
        ),
        patch.object(value, "read_retained_input") as inputs,
        patch.object(value, "read_chunks") as chunks,
        pytest.raises(ProjectionStorageError),
    ):
        await value.load_projection_job_chunks(claim())
    inputs.assert_not_called()
    chunks.assert_not_called()


async def test_short_chunk_page_preserves_absolute_keys_and_current_final_authority() -> None:
    value, session = worker(), MagicMock(spec=Session)
    captured, _, auth, root, _, job = records()
    chunk = calculate_projection_chunk(captured.plan.inputs, 2, 2)
    descriptor = StoredProjectionChunk(
        id=UUID(int=801), run_id=root.id, content_digest="a" * 64, created_at=AT, chunk=chunk
    )
    with (
        patch.object(value, "_worker_run", inline(session)),
        patch.object(value, "_fenced", return_value=(root, job)),
        patch.object(value, "_auth", return_value=auth),
        patch.object(value, "_current_inputs", return_value=captured),
        patch.object(value, "read_chunks", return_value=(descriptor,)) as read,
        patch.object(value, "_final_boundary") as final,
    ):
        page = await value.load_projection_job_chunks(claim(), after=("baseline", 0), limit=32)
    assert page == (chunk,) and page[0].paths[0].index == 2
    assert read.call_args.kwargs == {"after": ("baseline", 0), "limit": 32}
    final.assert_called_once_with(session, claim())


async def test_chunk_write_passes_exact_fence_and_checks_again_before_acknowledging() -> None:
    value, session = worker(), MagicMock(spec=Session)
    captured, _, auth, root, _, job = records()
    chunk = calculate_projection_chunk(captured.plan.inputs, 0, 2)
    with (
        patch.object(value, "_worker_run", inline(session)),
        patch.object(value, "_fenced", return_value=(root, job)),
        patch.object(value, "_auth", return_value=auth),
        patch.object(value, "_current_inputs", return_value=captured),
        patch.object(value, "publish_chunk") as publish,
        patch.object(
            value,
            "_final_boundary",
            side_effect=jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED),
        ),
        pytest.raises(jobs.ProjectionJobInputError) as expired,
    ):
        await value.save_projection_job_chunk(claim(), chunk)
    assert expired.value.code is jobs.ProjectionJobFailureCode.LEASE_EXPIRED
    assert publish.call_args.kwargs == {
        "job_id": job.id,
        "lease_token": job.lease_token,
        "consumer_attempt": 2,
    }


async def test_publication_failure_never_marks_job_succeeded_or_converts_reservation() -> None:
    value, session = worker(), MagicMock(spec=Session)
    captured, result, auth, root, _, job = records()
    with (
        patch.object(value, "_worker_run", inline(session)),
        patch.object(value, "_fenced", return_value=(root, job)),
        patch.object(value, "_auth", return_value=auth),
        patch.object(value, "_current_inputs", return_value=captured),
        patch.object(
            value,
            "publish_result",
            side_effect=ProjectionStorageError(ProjectionErrorCode.PROJECTION_UNAVAILABLE),
        ),
        patch("trading212_persistence.projection_job_store.finish_projection_job") as finish,
        pytest.raises(ProjectionStorageError),
    ):
        await value.complete_projection_job(claim(), result)
    finish.assert_not_called()
    assert root.reserved_bytes == 33_554_432 and root.retained_bytes == 0


async def test_final_failure_after_revocation_uses_metadata_cleanup_only() -> None:
    value, session = worker(), MagicMock(spec=Session)
    _, _, _, root, _, job = records()
    with (
        patch.object(value, "_worker_run", inline(session)),
        patch.object(value, "_fenced", return_value=(root, job)),
        patch.object(
            value, "_auth", side_effect=AssertionError("must not decode on revoked cleanup")
        ),
        patch.object(value, "_terminal") as terminal,
        patch.object(value, "read_retained_input") as inputs,
    ):
        assert await value.fail_projection_job(
            claim(), failure_code=jobs.ProjectionJobFailureCode.ACCESS_DENIED, retryable=False
        )
    terminal.assert_called_once_with(
        session, root, job, jobs.ProjectionJobFailureCode.ACCESS_DENIED
    )
    inputs.assert_not_called()


async def test_retry_after_source_revocation_does_not_enqueue_again() -> None:
    value, session = worker(), MagicMock(spec=Session)
    _, _, _, root, _, job = records()
    with (
        patch.object(value, "_worker_run", inline(session)),
        patch.object(value, "_fenced", return_value=(root, job)),
        patch.object(
            value,
            "_auth",
            side_effect=ProjectionStorageError(ProjectionErrorCode.SOURCE_UNAVAILABLE),
        ),
        patch.object(value, "_terminal") as terminal,
        patch.object(value, "_requeue") as requeue,
    ):
        assert await value.fail_projection_job(
            claim(), failure_code=jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
        )
    terminal.assert_called_once_with(
        session, root, job, jobs.ProjectionJobFailureCode.SOURCE_RESTRICTED
    )
    requeue.assert_not_called()


async def test_database_errors_are_fixed_retryable_categories_without_sql_leak() -> None:
    value = worker()
    session = MagicMock(spec=Session)
    sessions = MagicMock()
    sessions.return_value.__enter__.return_value = session
    value._sessions = sessions
    with (
        patch.object(
            value, "_global_slot", side_effect=SQLAlchemyError("postgresql://secret-canary")
        ),
        pytest.raises(jobs.ProjectionJobInputError) as failure,
    ):
        await value._worker_run(Mock())
    assert failure.value.code is jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE
    assert failure.value.retryable and "secret-canary" not in str(failure.value)
    assert failure.value.__suppress_context__


@pytest.mark.parametrize(
    ("after", "limit"),
    [
        (None, 0),
        (None, 33),
        (None, True),
        (("other", 0), 1),
        (("baseline", True), 1),
        (("baseline", 4096), 1),
    ],
)
async def test_invalid_page_never_enters_transaction(after: object, limit: int) -> None:
    value = worker()
    with patch.object(value, "_worker_run") as execute, pytest.raises(ValueError):
        await value.load_projection_job_chunks(
            claim(), after=cast(tuple[ProjectionVariant, int] | None, after), limit=limit
        )
    execute.assert_not_called()


async def test_heartbeat_does_not_revive_lease_expired_during_source_authorization() -> None:
    value, session = worker(), MagicMock(spec=Session)
    _, _, _, root, _, job = records()
    before = (job.heartbeat_at, job.lease_expires_at)
    with (
        patch.object(value, "_worker_run", inline(session)),
        patch.object(value, "_fenced", side_effect=[(root, job), None]),
        patch.object(value, "_handoff_authority", return_value=True),
    ):
        assert not await value.heartbeat_projection_job(claim())
    assert before == (job.heartbeat_at, job.lease_expires_at)
    session.flush.assert_not_called()


def test_final_boundary_checks_lease_after_recursive_source_authorization() -> None:
    value, session = worker(), MagicMock(spec=Session)
    _, _, _, root, _, job = records()
    with (
        patch.object(value, "_fenced", side_effect=[(root, job), None]),
        patch.object(value, "_auth"),
        pytest.raises(jobs.ProjectionJobInputError) as expired,
    ):
        value._final_boundary(session, claim())
    assert expired.value.code is jobs.ProjectionJobFailureCode.LEASE_EXPIRED
