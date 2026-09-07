"""Bounded PostgreSQL delivery/consumer recovery for one fixed planning task."""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.planning_jobs import (
    PLAN_CONSUMER_ATTEMPTS,
    PLAN_DISPATCH_CLAIM_SECONDS,
    PLAN_PUBLICATION_ATTEMPTS,
    PLAN_WORKER_LEASE_SECONDS,
    PlanDispatchClaim,
    PlanJobClaim,
    PlanJobFailureCode,
    PlanJobInputError,
    PlanTaskMessage,
)
from trading212_domain.planning import ContributionPlanResult, PlanningInput

from .models import BrokerAccountModel, BrokerConnectionModel
from .planning_models import (
    ContributionPlanAttemptModel,
    ContributionPlanJobModel,
    ContributionPlanModel,
    ContributionPlanOutboxModel,
    ContributionPlanRequestModel,
    PlanningAuditModel,
)

_ACTOR = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_TERMINAL = frozenset({"succeeded", "failed", "expired", "cancelled"})


class PlanningJobPersistence(ABC):
    _sessions: sessionmaker[Session]

    @abstractmethod
    def _now(self) -> datetime: ...

    @abstractmethod
    def _load_request_input(
        self, session: Session, request: ContributionPlanRequestModel
    ) -> PlanningInput: ...

    @abstractmethod
    def _persist_plan_result(
        self,
        session: Session,
        request: ContributionPlanRequestModel,
        result: ContributionPlanResult,
    ) -> None: ...

    async def _job_run[T](self, action: Callable[[], T]) -> T:
        def execute() -> T:
            try:
                return action()
            except SQLAlchemyError:
                pass
            raise PlanJobInputError(PlanJobFailureCode.STORAGE_UNAVAILABLE, retryable=True)

        return await asyncio.to_thread(execute)

    def _owner_lock(self, session: Session, owner: UUID, *, wait: bool = True) -> bool:
        function = "pg_advisory_xact_lock" if wait else "pg_try_advisory_xact_lock"
        result = session.scalar(
            text(f"SELECT {function}(hashtextextended(:key,0))"), {"key": f"targets:{owner}"}
        )
        return wait or bool(result)

    def _message(
        self, session: Session, job: ContributionPlanJobModel, *, authorize: bool = True
    ) -> PlanTaskMessage:
        request = session.get(ContributionPlanRequestModel, job.request_id)
        if request is None:
            raise PlanJobInputError(PlanJobFailureCode.INPUT_UNAVAILABLE)
        plan = session.get(ContributionPlanModel, request.plan_id)
        if plan is None:
            raise PlanJobInputError(PlanJobFailureCode.INPUT_UNAVAILABLE)
        owner = session.scalar(
            select(BrokerConnectionModel.owner_id)
            .join(BrokerAccountModel)
            .where(BrokerAccountModel.id == plan.broker_account_id)
        )
        if (
            (authorize and owner != job.owner_id)
            or plan.owner_id != job.owner_id
            or request.owner_id != job.owner_id
        ):
            raise PlanJobInputError(PlanJobFailureCode.ACCESS_DENIED)
        return PlanTaskMessage(
            str(job.id),
            str(request.id),
            str(job.owner_id),
            str(plan.broker_account_id),
            request.input_digest,
        )

    def _attempt(
        self,
        session: Session,
        job: ContributionPlanJobModel,
        *,
        kind: str,
        event: str,
        number: int,
        token: UUID,
        failure: PlanJobFailureCode | None = None,
    ) -> None:
        sequence = session.scalar(
            select(func.coalesce(func.max(ContributionPlanAttemptModel.sequence), 0)).where(
                ContributionPlanAttemptModel.job_id == job.id
            )
        )
        session.add(
            ContributionPlanAttemptModel(
                owner_id=job.owner_id,
                job_id=job.id,
                sequence=int(sequence or 0) + 1,
                kind=kind,
                event=event,
                attempt_number=number,
                claim_token=token,
                failure_code=None if failure is None else failure.value,
                created_at=self._now(),
            )
        )
        session.flush()

    def _outbox(
        self, session: Session, job: ContributionPlanJobModel
    ) -> ContributionPlanOutboxModel:
        outbox = session.scalar(
            select(ContributionPlanOutboxModel).where(ContributionPlanOutboxModel.job_id == job.id)
        )
        if outbox is None:
            raise PlanJobInputError(PlanJobFailureCode.INPUT_UNAVAILABLE)
        return outbox

    def _terminal_failure(
        self, session: Session, job: ContributionPlanJobModel, failure: PlanJobFailureCode
    ) -> None:
        if job.state in _TERMINAL:
            return
        job.state = "failed"
        job.failure_code = failure.value
        job.completed_at = self._now()
        job.lease_token = None
        job.lease_expires_at = None
        outbox = self._outbox(session, job)
        outbox.state = "dead_letter"
        outbox.failure_code = failure.value
        outbox.claim_token = None
        outbox.claim_expires_at = None
        session.add(
            PlanningAuditModel(
                owner_id=job.owner_id,
                request_id=job.request_id,
                kind="failed",
                actor_principal_id="system:planning-worker",
                correlation_id="planning-job-failure",
                created_at=self._now(),
            )
        )

    def _expire_consumer(self, session: Session, job: ContributionPlanJobModel) -> None:
        if (
            job.state != "running"
            or job.lease_expires_at is None
            or job.lease_expires_at > self._now()
        ):
            return
        assert job.lease_token is not None
        self._attempt(
            session,
            job,
            kind="consumer",
            event="expired",
            number=job.consumer_attempts,
            token=job.lease_token,
            failure=PlanJobFailureCode.LEASE_EXPIRED,
        )
        if job.consumer_attempts >= PLAN_CONSUMER_ATTEMPTS:
            self._terminal_failure(session, job, PlanJobFailureCode.ATTEMPTS_EXHAUSTED)
        else:
            job.state = "queued"
            job.failure_code = PlanJobFailureCode.LEASE_EXPIRED.value
            job.lease_token = None
            job.lease_expires_at = None

    async def claim_plan_dispatches(
        self, *, dispatcher_id: str, limit: int = 20
    ) -> tuple[PlanDispatchClaim, ...]:
        if not isinstance(dispatcher_id, str) or _ACTOR.fullmatch(dispatcher_id) is None:
            raise ValueError("planning dispatcher identity is invalid")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("planning dispatch batch must be 1..100")

        def action() -> tuple[PlanDispatchClaim, ...]:
            with self._sessions() as session:
                candidates = tuple(
                    session.execute(
                        select(ContributionPlanOutboxModel.id, ContributionPlanOutboxModel.owner_id)
                        .where(
                            ContributionPlanOutboxModel.state.in_(
                                ("pending", "claimed", "published")
                            ),
                            ContributionPlanOutboxModel.available_at <= self._now(),
                        )
                        .order_by(
                            ContributionPlanOutboxModel.available_at, ContributionPlanOutboxModel.id
                        )
                        .limit(limit)
                    )
                )
            claims = []
            for identifier, owner in candidates:
                with self._sessions() as session, session.begin():
                    if not self._owner_lock(session, owner, wait=False):
                        continue
                    row = session.scalar(
                        select(ContributionPlanOutboxModel)
                        .where(ContributionPlanOutboxModel.id == identifier)
                        .with_for_update(skip_locked=True)
                    )
                    if (
                        row is None
                        or row.available_at > self._now()
                        or row.state not in {"pending", "claimed", "published"}
                    ):
                        continue
                    job = session.get(ContributionPlanJobModel, row.job_id)
                    assert job is not None
                    if job.state in _TERMINAL:
                        row.state = "completed" if job.state == "succeeded" else "dead_letter"
                        continue
                    self._expire_consumer(session, job)
                    if job.state in _TERMINAL:
                        continue
                    if job.state == "running":
                        assert job.lease_expires_at is not None
                        row.available_at = job.lease_expires_at
                        continue
                    if (
                        row.state == "claimed"
                        and row.claim_expires_at is not None
                        and row.claim_expires_at > self._now()
                    ):
                        continue
                    if row.state == "claimed" and row.claim_token is not None:
                        self._attempt(
                            session,
                            job,
                            kind="publication",
                            event="expired",
                            number=row.publication_attempts,
                            token=row.claim_token,
                            failure=PlanJobFailureCode.LEASE_EXPIRED,
                        )
                    if row.publication_attempts >= PLAN_PUBLICATION_ATTEMPTS:
                        self._terminal_failure(session, job, PlanJobFailureCode.ATTEMPTS_EXHAUSTED)
                        continue
                    try:
                        message = self._message(session, job)
                    except PlanJobInputError as failure:
                        self._terminal_failure(session, job, failure.code)
                        continue
                    row.publication_attempts += 1
                    row.claim_token = uuid4()
                    row.claim_expires_at = self._now() + timedelta(
                        seconds=PLAN_DISPATCH_CLAIM_SECONDS
                    )
                    row.available_at = row.claim_expires_at
                    row.dispatcher_id = dispatcher_id
                    row.state = "claimed"
                    self._attempt(
                        session,
                        job,
                        kind="publication",
                        event="claimed",
                        number=row.publication_attempts,
                        token=row.claim_token,
                    )
                    claims.append(
                        PlanDispatchClaim(
                            message,
                            str(row.claim_token),
                            row.claim_expires_at,
                            row.publication_attempts,
                        )
                    )
            return tuple(claims)

        return await self._job_run(action)

    async def _publication_transition(
        self, claim: PlanDispatchClaim, failure: PlanJobFailureCode | None
    ) -> bool:
        def action() -> bool:
            with self._sessions() as session, session.begin():
                self._owner_lock(session, UUID(claim.message.owner_id))
                job = session.get(ContributionPlanJobModel, UUID(claim.message.job_id))
                if job is None or self._message(session, job) != claim.message:
                    return False
                row = self._outbox(session, job)
                if (
                    row.state != "claimed"
                    or row.claim_token != UUID(claim.claim_token)
                    or row.claim_expires_at is None
                    or row.claim_expires_at <= self._now()
                ):
                    return False
                self._attempt(
                    session,
                    job,
                    kind="publication",
                    event="published" if failure is None else "failed",
                    number=row.publication_attempts,
                    token=row.claim_token,
                    failure=failure,
                )
                row.claim_token = None
                row.claim_expires_at = None
                if failure is None:
                    row.state = "completed" if job.state == "succeeded" else "published"
                    row.published_at = self._now()
                    row.available_at = self._now() + timedelta(seconds=PLAN_WORKER_LEASE_SECONDS)
                    row.failure_code = None
                elif (
                    job.state == "running"
                    and job.lease_expires_at is not None
                    and job.lease_expires_at > self._now()
                ):
                    # A send timeout can follow successful delivery. Preserve the live
                    # consumer even at the final publication attempt.
                    row.state = "published"
                    row.failure_code = failure.value
                    row.available_at = job.lease_expires_at
                elif row.publication_attempts >= PLAN_PUBLICATION_ATTEMPTS:
                    self._terminal_failure(session, job, PlanJobFailureCode.ATTEMPTS_EXHAUSTED)
                else:
                    row.state = "pending"
                    row.failure_code = failure.value
                    row.available_at = self._now() + timedelta(
                        seconds=min(2 ** (row.publication_attempts - 1), 60)
                    )
                return True

        return await self._job_run(action)

    async def acknowledge_plan_dispatch(self, claim: PlanDispatchClaim) -> bool:
        return await self._publication_transition(claim, None)

    async def defer_plan_dispatch(
        self, claim: PlanDispatchClaim, *, failure_code: PlanJobFailureCode
    ) -> bool:
        if not isinstance(failure_code, PlanJobFailureCode):
            raise ValueError("planning failure category is invalid")
        return await self._publication_transition(claim, failure_code)

    async def claim_plan_job(
        self, message: PlanTaskMessage, *, consumer_id: str
    ) -> PlanJobClaim | None:
        if not isinstance(consumer_id, str) or _ACTOR.fullmatch(consumer_id) is None:
            raise ValueError("planning consumer identity is invalid")

        def action() -> PlanJobClaim | None:
            with self._sessions() as session, session.begin():
                self._owner_lock(session, UUID(message.owner_id))
                job = session.get(ContributionPlanJobModel, UUID(message.job_id))
                if job is None:
                    return None
                try:
                    actual_message = self._message(session, job)
                except PlanJobInputError as failure:
                    if self._message(session, job, authorize=False) == message:
                        self._terminal_failure(session, job, failure.code)
                    return None
                if actual_message != message:
                    return None
                self._expire_consumer(session, job)
                if job.state != "queued":
                    return None
                if job.consumer_attempts >= PLAN_CONSUMER_ATTEMPTS:
                    self._terminal_failure(session, job, PlanJobFailureCode.ATTEMPTS_EXHAUSTED)
                    return None
                job.consumer_attempts += 1
                job.state = "running"
                job.lease_token = uuid4()
                job.heartbeat_at = self._now()
                job.lease_expires_at = self._now() + timedelta(seconds=PLAN_WORKER_LEASE_SECONDS)
                job.consumer_id = consumer_id
                self._attempt(
                    session,
                    job,
                    kind="consumer",
                    event="claimed",
                    number=job.consumer_attempts,
                    token=job.lease_token,
                )
                return PlanJobClaim(
                    message, str(job.lease_token), job.lease_expires_at, job.consumer_attempts
                )

        return await self._job_run(action)

    def _claimed_job(
        self, session: Session, claim: PlanJobClaim, *, authorize: bool = True
    ) -> ContributionPlanJobModel | None:
        job = session.get(ContributionPlanJobModel, UUID(claim.message.job_id))
        if (
            job is None
            or job.state != "running"
            or job.lease_token != UUID(claim.claim_token)
            or job.lease_expires_at is None
            or job.lease_expires_at <= self._now()
        ):
            return None
        if self._message(session, job, authorize=authorize) != claim.message:
            return None
        return job

    async def heartbeat_plan_job(self, claim: PlanJobClaim) -> bool:
        def action() -> bool:
            with self._sessions() as session, session.begin():
                self._owner_lock(session, UUID(claim.message.owner_id))
                job = self._claimed_job(session, claim)
                if job is None:
                    return False
                job.heartbeat_at = self._now()
                job.lease_expires_at = self._now() + timedelta(seconds=PLAN_WORKER_LEASE_SECONDS)
                self._attempt(
                    session,
                    job,
                    kind="consumer",
                    event="heartbeat",
                    number=job.consumer_attempts,
                    token=UUID(claim.claim_token),
                )
                return True

        return await self._job_run(action)

    async def load_plan_job_input(self, claim: PlanJobClaim) -> PlanningInput:
        def action() -> PlanningInput:
            with self._sessions() as session, session.begin():
                self._owner_lock(session, UUID(claim.message.owner_id))
                job = self._claimed_job(session, claim)
                if job is None:
                    raise PlanJobInputError(PlanJobFailureCode.LEASE_EXPIRED)
                request = session.get(ContributionPlanRequestModel, job.request_id)
                assert request is not None
                return self._load_request_input(session, request)

        return await self._job_run(action)

    async def complete_plan_job(self, claim: PlanJobClaim, result: ContributionPlanResult) -> bool:
        def action() -> bool:
            with self._sessions() as session, session.begin():
                self._owner_lock(session, UUID(claim.message.owner_id))
                job = self._claimed_job(session, claim)
                if job is None:
                    return False
                request = session.get(ContributionPlanRequestModel, job.request_id)
                assert request is not None
                self._load_request_input(session, request)
                with session.begin_nested() as publication:
                    self._persist_plan_result(session, request, result)
                    if job.lease_expires_at is None or job.lease_expires_at <= self._now():
                        publication.rollback()
                        return False
                    # Validate persisted identity/authorization again after result verification.
                    if self._message(session, job) != claim.message:
                        publication.rollback()
                        return False
                self._attempt(
                    session,
                    job,
                    kind="consumer",
                    event="succeeded",
                    number=job.consumer_attempts,
                    token=UUID(claim.claim_token),
                )
                job.state = "succeeded"
                job.failure_code = None
                job.completed_at = self._now()
                job.lease_token = None
                job.lease_expires_at = None
                outbox = self._outbox(session, job)
                outbox.state = "completed"
                outbox.claim_token = None
                outbox.claim_expires_at = None
                session.add(
                    PlanningAuditModel(
                        owner_id=job.owner_id,
                        request_id=job.request_id,
                        kind="completed",
                        actor_principal_id="system:planning-worker",
                        correlation_id=request.correlation_id,
                        created_at=self._now(),
                    )
                )
                return True

        return await self._job_run(action)

    async def fail_plan_job(
        self, claim: PlanJobClaim, *, failure_code: PlanJobFailureCode, retryable: bool
    ) -> bool:
        if not isinstance(failure_code, PlanJobFailureCode) or type(retryable) is not bool:
            raise ValueError("planning failure category is invalid")

        def action() -> bool:
            with self._sessions() as session, session.begin():
                self._owner_lock(session, UUID(claim.message.owner_id))
                job = self._claimed_job(session, claim, authorize=False)
                if job is None:
                    return False
                self._attempt(
                    session,
                    job,
                    kind="consumer",
                    event="failed",
                    number=job.consumer_attempts,
                    token=UUID(claim.claim_token),
                    failure=failure_code,
                )
                if not retryable or job.consumer_attempts >= PLAN_CONSUMER_ATTEMPTS:
                    self._terminal_failure(session, job, failure_code)
                else:
                    job.state = "queued"
                    job.failure_code = failure_code.value
                    job.lease_token = None
                    job.lease_expires_at = None
                    outbox = self._outbox(session, job)
                    outbox.state = "pending"
                    outbox.available_at = self._now() + timedelta(
                        seconds=min(2 ** (job.consumer_attempts - 1), 60)
                    )
                    outbox.claim_token = None
                    outbox.claim_expires_at = None
                return True

        return await self._job_run(action)
