"""Independent accounting assertions for every terminal outcome and damaged capacity."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from trading212_application.projection import ProjectionErrorCode
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_job_lifecycle import (
    ProjectionTerminalState,
    finish_projection_job,
)

AT = datetime(2026, 9, 15, tzinfo=UTC)
RESERVATION = 33_554_432


def rows(
    *, running: bool = True
) -> tuple[PremiumRunModel, PremiumJobModel, PremiumCapacityModel, PremiumOutboxModel]:
    owner, account, run_id, job_id = (UUID(int=value) for value in (1, 2, 3, 4))
    root = PremiumRunModel(
        expires_at=AT + timedelta(days=30),
        id=run_id,
        owner_id=owner,
        account_id=account,
        kind="projection",
        reserved_bytes=RESERVATION,
        retained_bytes=0,
    )
    job = PremiumJobModel(
        id=job_id,
        owner_id=owner,
        account_id=account,
        run_id=run_id,
        state="running" if running else "queued",
        consumer_attempts=2 if running else 0,
        lease_token=UUID(int=5) if running else None,
        lease_expires_at=AT + timedelta(seconds=60) if running else None,
        deadline_at=AT + timedelta(seconds=240) if running else None,
        heartbeat_at=AT if running else None,
        consumer_id="worker" if running else None,
        completed_at=None,
    )
    capacity = PremiumCapacityModel(
        owner_id=owner,
        reserved_bytes=2 * RESERVATION,
        retained_bytes=211,
        active_jobs=2,
        definition_versions=7,
        updated_at=AT,
    )
    outbox = PremiumOutboxModel(
        id=UUID(int=6),
        owner_id=owner,
        account_id=account,
        job_id=job_id,
        task_name="projections.calculate.v1",
        state="claimed",
        publication_attempts=3,
        claim_token=UUID(int=7),
        claim_expires_at=AT + timedelta(seconds=30),
        dispatcher_id="dispatcher",
    )
    return root, job, capacity, outbox


@pytest.mark.parametrize(
    ("state", "code", "running"),
    [
        ("succeeded", None, True),
        ("failed", "calculation_failed", True),
        ("expired", "input_unavailable", True),
        ("cancelled", None, True),
        ("cancelled", None, False),
    ],
)
def test_terminal_charges_all_actual_copies_once_preserving_other_job(
    state: ProjectionTerminalState, code: str | None, running: bool
) -> None:
    root, job, capacity, outbox = rows(running=running)
    session = Mock()
    session.scalar.side_effect = [capacity, outbox]
    service = Mock()
    service._now.return_value = AT
    # Inputs, checkpoints and result are all physical bytes, independent of state.
    service._result_bytes.return_value = 18_901
    with patch("trading212_persistence.projection_job_lifecycle.premium_attempt") as audit:
        finish_projection_job(
            service,
            session,
            root,
            job,
            state,
            code,
            retained_bytes=18_901 if state == "succeeded" else None,
        )
        assert audit.call_args.kwargs["event"] == state
        assert audit.call_args.kwargs["number"] == (2 if running else 0)
        assert audit.call_args.kwargs["token"] == (UUID(int=5) if running else None)
    assert (root.reserved_bytes, root.retained_bytes) == (0, 18_901)
    assert (
        capacity.active_jobs,
        capacity.reserved_bytes,
        capacity.retained_bytes,
        capacity.definition_versions,
    ) == (1, RESERVATION, 19_112, 7)
    assert capacity.reserved_bytes + capacity.retained_bytes == RESERVATION + 211 + 18_901
    assert (job.state, job.completed_at, job.failure_code) == (state, AT, code)
    assert all(
        getattr(job, field) is None
        for field in (
            "lease_token",
            "lease_expires_at",
            "heartbeat_at",
            "deadline_at",
            "consumer_id",
        )
    )
    assert outbox.state == ("completed" if state in ("succeeded", "cancelled") else "dead_letter")
    assert (outbox.claim_token, outbox.claim_expires_at, outbox.dispatcher_id) == (None, None, None)
    with pytest.raises(ProjectionStorageError) as duplicate:
        finish_projection_job(service, session, root, job, state, code)
    assert duplicate.value.code is ProjectionErrorCode.INVALID_STATE_TRANSITION
    assert capacity.retained_bytes == 19_112


@pytest.mark.parametrize(
    "damage",
    (
        "active",
        "reserved",
        "double_charge",
        "wrong_size",
        "boolean_size",
        "missing_outbox",
        "scope",
        "raw_failure",
    ),
)
def test_invalid_terminal_accounting_fails_before_mutation(damage: str) -> None:
    root, job, capacity, outbox = rows()
    service, session = Mock(), Mock()
    service._now.return_value = AT
    service._result_bytes.return_value = 900
    code = "calculation_failed"
    size = None
    if damage == "active":
        capacity.active_jobs = 0
    elif damage == "reserved":
        capacity.reserved_bytes = RESERVATION - 1
    elif damage == "double_charge":
        root.retained_bytes = 1
    elif damage == "wrong_size":
        size = 899
    elif damage == "boolean_size":
        service._result_bytes.return_value = True
    elif damage == "scope":
        job.account_id = UUID(int=99)
    elif damage == "raw_failure":
        code = "postgresql://secret-canary"
    session.scalar.side_effect = [capacity, None if damage == "missing_outbox" else outbox]
    before = (capacity.active_jobs, capacity.reserved_bytes, capacity.retained_bytes)
    with patch("trading212_persistence.projection_job_lifecycle.premium_attempt") as audit:
        with pytest.raises(ProjectionStorageError) as failure:
            finish_projection_job(service, session, root, job, "failed", code, retained_bytes=size)
        assert "secret-canary" not in str(failure.value)
        audit.assert_not_called()
    assert before == (capacity.active_jobs, capacity.reserved_bytes, capacity.retained_bytes)
    assert root.reserved_bytes == RESERVATION and job.state == "running"
    session.flush.assert_not_called()


def test_success_requires_verified_physical_size_and_running_job() -> None:
    root, job, _, _ = rows()
    service, session = Mock(), Mock()
    service._result_bytes.return_value = 900
    with pytest.raises(ProjectionStorageError):
        finish_projection_job(service, session, root, job, "succeeded", None)
    job.state = "queued"
    with pytest.raises(ProjectionStorageError):
        finish_projection_job(service, session, root, job, "succeeded", None, retained_bytes=900)
    session.scalar.assert_not_called()


def test_success_cannot_outlive_lease_during_final_accounting() -> None:
    root, job, capacity, outbox = rows()
    session, service = Mock(), Mock()
    session.scalar.side_effect = [capacity, outbox]
    service._result_bytes.return_value = 900
    service._now.return_value = job.lease_expires_at
    with (
        patch("trading212_persistence.projection_job_lifecycle.premium_attempt") as audit,
        pytest.raises(ProjectionStorageError) as expired,
    ):
        finish_projection_job(service, session, root, job, "succeeded", None, retained_bytes=900)
    assert expired.value.code is ProjectionErrorCode.INVALID_STATE_TRANSITION
    assert (root.reserved_bytes, root.retained_bytes) == (RESERVATION, 0)
    assert capacity.active_jobs == 2
    audit.assert_not_called()
