"""Atomic terminal projection accounting shared by workers and public cancellation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application.projection import ProjectionErrorCode
from trading212_application.projection_jobs import ProjectionJobFailureCode
from trading212_domain.projection import PROJECTION_MAX_BYTES

from .premium_attempts import premium_attempt
from .premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from .projection_definition_store import ProjectionStorageError

ProjectionTerminalState = Literal["succeeded", "failed", "expired", "cancelled"]


class ProjectionLifecycleStore(Protocol):
    def _now(self) -> datetime: ...

    def _result_bytes(self, session: Session, root: PremiumRunModel) -> int: ...


def finish_projection_job(
    store: ProjectionLifecycleStore,
    session: Session,
    root: PremiumRunModel,
    job: PremiumJobModel,
    state: ProjectionTerminalState,
    failure_code: str | None,
    *,
    retained_bytes: int | None = None,
) -> None:
    """Caller holds the owner/root/job locks and owns the surrounding transaction.

    An active job reserves all 32 MiB and has no retained charge. Every terminal
    outcome converts that reservation to the current physical byte count, including
    saved inputs and successful chunks after failure or cancellation. This helper
    does not authorize private reads, purge copies, commit, or acquire the global
    execution lock after owner locks. Public command audit belongs to its caller.
    """
    if (
        root.kind != "projection"
        or job.run_id != root.id
        or (job.owner_id, job.account_id) != (root.owner_id, root.account_id)
        or job.state not in ("queued", "running")
        or state not in ("succeeded", "failed", "expired", "cancelled")
        or (state == "succeeded" and job.state != "running")
        or (state in ("succeeded", "cancelled") and failure_code is not None)
        or (
            state in ("failed", "expired")
            and failure_code not in {item.value for item in ProjectionJobFailureCode}
        )
    ):
        raise ProjectionStorageError(ProjectionErrorCode.INVALID_STATE_TRANSITION)
    if root.reserved_bytes != PROJECTION_MAX_BYTES or root.retained_bytes != 0:
        raise ProjectionStorageError(ProjectionErrorCode.PROJECTION_UNAVAILABLE)
    actual_bytes = store._result_bytes(session, root)
    if (
        type(actual_bytes) is not int
        or not 0 <= actual_bytes <= PROJECTION_MAX_BYTES
        or (
            retained_bytes is not None
            and (type(retained_bytes) is not int or retained_bytes != actual_bytes)
        )
        or (state == "succeeded" and retained_bytes is None)
    ):
        raise ProjectionStorageError(ProjectionErrorCode.PROJECTION_UNAVAILABLE)
    capacity = session.scalar(
        select(PremiumCapacityModel)
        .where(PremiumCapacityModel.owner_id == root.owner_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    outbox = session.scalar(
        select(PremiumOutboxModel)
        .where(
            PremiumOutboxModel.job_id == job.id,
            PremiumOutboxModel.owner_id == root.owner_id,
            PremiumOutboxModel.account_id == root.account_id,
            PremiumOutboxModel.task_name == "projections.calculate.v1",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        capacity is None
        or capacity.active_jobs < 1
        or capacity.reserved_bytes < root.reserved_bytes
        or capacity.retained_bytes < 0
        or outbox is None
    ):
        raise ProjectionStorageError(ProjectionErrorCode.PROJECTION_UNAVAILABLE)
    at = store._now()
    if state == "succeeded" and (
        job.lease_expires_at is None
        or job.lease_expires_at <= at
        or job.deadline_at is None
        or job.deadline_at <= at
        or root.expires_at <= at
    ):
        raise ProjectionStorageError(ProjectionErrorCode.INVALID_STATE_TRANSITION)
    premium_attempt(
        session,
        job,
        kind="consumer",
        event=state,
        number=job.consumer_attempts,
        token=job.lease_token,
        at=at,
        failure=failure_code,
    )
    capacity.active_jobs -= 1
    capacity.reserved_bytes -= root.reserved_bytes
    capacity.retained_bytes += actual_bytes
    capacity.updated_at = at
    root.reserved_bytes = 0
    root.retained_bytes = actual_bytes
    job.state, job.failure_code, job.completed_at = state, failure_code, at
    job.lease_token = job.lease_expires_at = job.heartbeat_at = job.deadline_at = (
        job.consumer_id
    ) = None
    outbox.state = "completed" if state in ("succeeded", "cancelled") else "dead_letter"
    outbox.failure_code = failure_code
    outbox.claim_token = outbox.claim_expires_at = outbox.dispatcher_id = None
    session.flush()
