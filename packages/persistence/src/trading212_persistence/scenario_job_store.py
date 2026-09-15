"""Fixed scenario outbox delivery, one global execution slot and fenced atomic completion."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from trading212_application import scenario as app
from trading212_application import scenario_jobs as jobs
from trading212_domain.errors import DomainError
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_security.principals import AuthorizationError

from .premium_attempts import premium_attempt
from .premium_models import (
    PremiumAttemptModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from .report_authorization import ReportAuthorization, authorize_report_job
from .scenario_definition_store import WRITE_SCOPES, scenario_owner_lock
from .scenario_models import ScenarioRunModel
from .scenario_service import PostgresScenarioService
from .scenario_store_types import ScenarioStorageError

_ACTOR = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


def _input_failure(
    failure: app.ScenarioServiceError | ScenarioStorageError,
) -> jobs.ScenarioJobInputError:
    mapping = {
        "ACCESS_DENIED": jobs.ScenarioJobFailureCode.ACCESS_DENIED,
        "NOT_FOUND": jobs.ScenarioJobFailureCode.INPUT_UNAVAILABLE,
        "RUN_EXPIRED": jobs.ScenarioJobFailureCode.INPUT_UNAVAILABLE,
        "SOURCE_UNAVAILABLE": jobs.ScenarioJobFailureCode.SOURCE_RESTRICTED,
        "INPUT_BOUND_EXCEEDED": jobs.ScenarioJobFailureCode.LIMIT_EXCEEDED,
        "RATE_LIMITED": jobs.ScenarioJobFailureCode.LIMIT_EXCEEDED,
    }
    return jobs.ScenarioJobInputError(
        mapping.get(failure.code.value, jobs.ScenarioJobFailureCode.INPUT_CHANGED)
    )


class PostgresScenarioJobStore(PostgresScenarioService):
    async def _worker_run[T](self, action: Callable[[Session], T]) -> T:
        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    return action(session)
            except SQLAlchemyError:
                raise jobs.ScenarioJobInputError(
                    jobs.ScenarioJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
                ) from None

        return await asyncio.to_thread(execute)

    def _global_slot(self, session: Session) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "premium:single-execution-slot"},
        )

    def _message(self, root: PremiumRunModel, job: PremiumJobModel) -> jobs.ScenarioTaskMessage:
        return jobs.ScenarioTaskMessage(
            str(job.id), str(root.id), str(root.owner_id), str(root.account_id), root.input_digest
        )

    def _metadata(
        self, session: Session, message: jobs.ScenarioTaskMessage
    ) -> tuple[PremiumRunModel, ScenarioRunModel, PremiumJobModel] | None:
        scenario_owner_lock(session, UUID(message.owner_id))
        row = session.execute(
            select(PremiumRunModel, ScenarioRunModel, PremiumJobModel)
            .join(ScenarioRunModel, ScenarioRunModel.id == PremiumRunModel.id)
            .join(PremiumJobModel, PremiumJobModel.run_id == PremiumRunModel.id)
            .where(
                PremiumRunModel.id == UUID(message.run_id),
                PremiumRunModel.owner_id == UUID(message.owner_id),
                PremiumRunModel.account_id == UUID(message.account_id),
                PremiumRunModel.kind == "scenario",
                PremiumJobModel.id == UUID(message.job_id),
                PremiumRunModel.input_digest == message.input_digest,
            )
            .with_for_update(of=(PremiumRunModel, PremiumJobModel))
            .execution_options(populate_existing=True)
        ).first()
        if row is None:
            return None
        root, run, job = row
        if not run.sealed or self._message(root, job) != message:
            return None
        return root, run, job

    def _auth(self, session: Session, root: PremiumRunModel) -> ReportAuthorization:
        return authorize_report_job(
            session,
            principal_id=root.actor_principal_id,
            owner_id=root.owner_id,
            account_id=root.account_id,
            required_scopes=WRITE_SCOPES,
            expires_at=root.expires_at,
            now=self._now(),
        )

    def _terminal(
        self,
        session: Session,
        root: PremiumRunModel,
        job: PremiumJobModel,
        code: jobs.ScenarioJobFailureCode,
        *,
        expired: bool = False,
    ) -> None:
        self._finish_job(session, root, job, "expired" if expired else "failed", code.value)

    def _requeue(
        self,
        session: Session,
        root: PremiumRunModel,
        job: PremiumJobModel,
        code: jobs.ScenarioJobFailureCode,
    ) -> None:
        premium_attempt(
            session,
            job,
            kind="consumer",
            event="expired",
            number=job.consumer_attempts,
            token=job.lease_token,
            at=self._now(),
            failure=code.value,
        )
        job.state = "queued"
        job.lease_token = job.lease_expires_at = job.deadline_at = job.heartbeat_at = (
            job.consumer_id
        ) = None
        job.failure_code = code.value
        outbox = session.scalar(
            select(PremiumOutboxModel).where(
                PremiumOutboxModel.job_id == job.id, PremiumOutboxModel.owner_id == root.owner_id
            )
        )
        if outbox is None:
            raise jobs.ScenarioJobInputError(jobs.ScenarioJobFailureCode.INPUT_CHANGED)
        outbox.state = "pending"
        outbox.claim_token = outbox.claim_expires_at = outbox.dispatcher_id = None
        outbox.available_at = self._now()
        session.flush()

    def _recover(self, session: Session) -> None:
        # The execution slot lock precedes each owner lock; only one running row exists.
        rows = session.execute(
            select(PremiumRunModel, PremiumJobModel)
            .join(PremiumJobModel, PremiumJobModel.run_id == PremiumRunModel.id)
            .where(
                PremiumRunModel.kind == "scenario",
                PremiumJobModel.state.in_(("queued", "running")),
                or_(
                    PremiumRunModel.expires_at <= self._now(),
                    and_(
                        PremiumJobModel.state == "running",
                        or_(
                            PremiumJobModel.lease_expires_at <= self._now(),
                            PremiumJobModel.deadline_at <= self._now(),
                        ),
                    ),
                ),
            )
            .order_by(PremiumRunModel.created_at, PremiumRunModel.id)
            .limit(20)
        ).all()
        for candidate, candidate_job in rows:
            found = self._metadata(session, self._message(candidate, candidate_job))
            if found is None:
                continue
            root, _, job = found
            if job.state not in ("queued", "running"):
                continue
            if root.expires_at <= self._now():
                self._terminal(
                    session, root, job, jobs.ScenarioJobFailureCode.INPUT_UNAVAILABLE, expired=True
                )
            elif job.consumer_attempts >= 4 or (
                job.deadline_at is not None and job.deadline_at <= self._now()
            ):
                self._terminal(session, root, job, jobs.ScenarioJobFailureCode.ATTEMPTS_EXHAUSTED)
            elif (
                job.state == "running"
                and job.lease_expires_at is not None
                and job.lease_expires_at <= self._now()
            ):
                self._requeue(session, root, job, jobs.ScenarioJobFailureCode.LEASE_EXPIRED)

    async def claim_scenario_dispatches(
        self, *, dispatcher_id: str, limit: int = 1
    ) -> tuple[jobs.ScenarioDispatchClaim, ...]:
        if (
            not isinstance(dispatcher_id, str)
            or _ACTOR.fullmatch(dispatcher_id) is None
            or type(limit) is not int
            or not 1 <= limit <= 20
        ):
            raise ValueError("Invalid bounded scenario dispatcher request.")

        def action(session: Session) -> tuple[jobs.ScenarioDispatchClaim, ...]:
            self._global_slot(session)
            self._recover(session)
            if session.scalar(
                select(PremiumJobModel.id).where(PremiumJobModel.state == "running").limit(1)
            ):
                return ()
            candidates = session.execute(
                select(PremiumRunModel, PremiumJobModel, PremiumOutboxModel)
                .join(PremiumJobModel, PremiumJobModel.run_id == PremiumRunModel.id)
                .join(PremiumOutboxModel, PremiumOutboxModel.job_id == PremiumJobModel.id)
                .where(
                    PremiumRunModel.kind == "scenario",
                    PremiumJobModel.state == "queued",
                    or_(
                        and_(
                            PremiumOutboxModel.state == "pending",
                            PremiumOutboxModel.available_at <= self._now(),
                        ),
                        and_(
                            PremiumOutboxModel.state == "claimed",
                            PremiumOutboxModel.claim_expires_at <= self._now(),
                        ),
                        and_(
                            PremiumOutboxModel.state == "published",
                            PremiumOutboxModel.published_at <= self._now() - timedelta(seconds=60),
                        ),
                    ),
                )
                .order_by(PremiumRunModel.created_at, PremiumRunModel.id)
                .limit(limit)
            ).all()
            claims = []
            for candidate, candidate_job, outbox in candidates:
                found = self._metadata(session, self._message(candidate, candidate_job))
                if found is None:
                    continue
                root, _, job = found
                if job.state != "queued":
                    continue
                try:
                    self._auth(session, root)
                except AuthorizationError:
                    self._terminal(session, root, job, jobs.ScenarioJobFailureCode.ACCESS_DENIED)
                    continue
                if outbox.publication_attempts >= 8:
                    self._terminal(
                        session, root, job, jobs.ScenarioJobFailureCode.ATTEMPTS_EXHAUSTED
                    )
                    continue
                outbox.state = "claimed"
                outbox.publication_attempts += 1
                outbox.claim_token = uuid4()
                outbox.claim_expires_at = self._now() + timedelta(seconds=30)
                outbox.dispatcher_id = dispatcher_id
                premium_attempt(
                    session,
                    job,
                    kind="publication",
                    event="claimed",
                    number=outbox.publication_attempts,
                    token=outbox.claim_token,
                    at=self._now(),
                )
                claims.append(
                    jobs.ScenarioDispatchClaim(
                        self._message(root, job),
                        str(outbox.claim_token),
                        outbox.claim_expires_at,
                        outbox.publication_attempts,
                    )
                )
            return tuple(claims)

        return await self._worker_run(action)

    async def _dispatch_transition(
        self, claim: jobs.ScenarioDispatchClaim, failure: jobs.ScenarioJobFailureCode | None
    ) -> bool:
        def action(session: Session) -> bool:
            found = self._metadata(session, claim.message)
            if found is None:
                return False
            root, _, job = found
            outbox = session.scalar(
                select(PremiumOutboxModel).where(PremiumOutboxModel.job_id == job.id)
            )
            if (
                outbox is None
                or outbox.state != "claimed"
                or outbox.claim_token != UUID(claim.claim_token)
                or outbox.claim_expires_at is None
                or outbox.claim_expires_at <= self._now()
                or job.state not in ("queued", "running")
            ):
                return False
            try:
                self._auth(session, root)
            except AuthorizationError:
                self._terminal(session, root, job, jobs.ScenarioJobFailureCode.ACCESS_DENIED)
                return False
            premium_attempt(
                session,
                job,
                kind="publication",
                event="published" if failure is None else "failed",
                number=outbox.publication_attempts,
                token=outbox.claim_token,
                at=self._now(),
                failure=None if failure is None else failure.value,
            )
            outbox.claim_token = outbox.claim_expires_at = outbox.dispatcher_id = None
            outbox.failure_code = None if failure is None else failure.value
            outbox.state = "published" if failure is None else "pending"
            if failure is None:
                outbox.published_at = self._now()
            else:
                outbox.available_at = self._now() + timedelta(
                    seconds=min(60, 2**outbox.publication_attempts)
                )
            session.flush()
            return True

        return await self._worker_run(action)

    async def acknowledge_scenario_dispatch(self, claim: jobs.ScenarioDispatchClaim) -> bool:
        return await self._dispatch_transition(claim, None)

    async def defer_scenario_dispatch(
        self, claim: jobs.ScenarioDispatchClaim, *, failure_code: jobs.ScenarioJobFailureCode
    ) -> bool:
        if not isinstance(failure_code, jobs.ScenarioJobFailureCode):
            raise ValueError("Invalid scenario failure category.")
        return await self._dispatch_transition(claim, failure_code)

    async def claim_scenario_job(
        self, message: jobs.ScenarioTaskMessage, *, consumer_id: str
    ) -> jobs.ScenarioJobClaim | None:
        if not isinstance(consumer_id, str) or _ACTOR.fullmatch(consumer_id) is None:
            raise ValueError("Invalid scenario consumer identity.")

        def action(session: Session) -> jobs.ScenarioJobClaim | None:
            self._global_slot(session)
            self._recover(session)
            found = self._metadata(session, message)
            if found is None:
                return None
            root, _, job = found
            if job.state != "queued" or session.scalar(
                select(PremiumJobModel.id).where(PremiumJobModel.state == "running").limit(1)
            ):
                return None
            try:
                self._auth(session, root)
            except AuthorizationError:
                self._terminal(session, root, job, jobs.ScenarioJobFailureCode.ACCESS_DENIED)
                return None
            first_claim = session.scalar(
                select(func.min(PremiumAttemptModel.created_at)).where(
                    PremiumAttemptModel.owner_id == root.owner_id,
                    PremiumAttemptModel.job_id == job.id,
                    PremiumAttemptModel.kind == "consumer",
                    PremiumAttemptModel.event == "claimed",
                )
            )
            deadline = min(root.expires_at, (first_claim or self._now()) + timedelta(seconds=240))
            if job.consumer_attempts >= 4 or deadline <= self._now():
                self._terminal(session, root, job, jobs.ScenarioJobFailureCode.ATTEMPTS_EXHAUSTED)
                return None
            job.state = "running"
            job.consumer_attempts += 1
            job.lease_token = uuid4()
            job.deadline_at = deadline
            job.lease_expires_at = min(deadline, self._now() + timedelta(seconds=60))
            job.heartbeat_at = self._now()
            job.consumer_id = consumer_id
            premium_attempt(
                session,
                job,
                kind="consumer",
                event="claimed",
                number=job.consumer_attempts,
                token=job.lease_token,
                at=self._now(),
            )
            return jobs.ScenarioJobClaim(
                message, str(job.lease_token), job.lease_expires_at, job.consumer_attempts, deadline
            )

        return await self._worker_run(action)

    def _fenced(
        self, session: Session, claim: jobs.ScenarioJobClaim
    ) -> tuple[PremiumRunModel, ScenarioRunModel, PremiumJobModel] | None:
        rows = self._metadata(session, claim.message)
        if rows is None:
            return None
        _, _, job = rows
        if (
            job.state != "running"
            or job.lease_token != UUID(claim.claim_token)
            or job.lease_expires_at is None
            or job.lease_expires_at <= self._now()
            or job.deadline_at != claim.deadline_at
            or job.deadline_at <= self._now()
        ):
            return None
        return rows

    async def heartbeat_scenario_job(self, claim: jobs.ScenarioJobClaim) -> bool:
        def action(session: Session) -> bool:
            rows = self._fenced(session, claim)
            if rows is None:
                return False
            root, _, job = rows
            try:
                self._auth(session, root)
            except AuthorizationError:
                self._terminal(session, root, job, jobs.ScenarioJobFailureCode.ACCESS_DENIED)
                return False
            job.heartbeat_at = self._now()
            job.lease_expires_at = min(claim.deadline_at, self._now() + timedelta(seconds=60))
            return True

        return await self._worker_run(action)

    async def load_scenario_job_input(
        self, claim: jobs.ScenarioJobClaim
    ) -> jobs.ScenarioExecutionInput:
        def action(session: Session) -> jobs.ScenarioExecutionInput:
            rows = self._fenced(session, claim)
            if rows is None:
                raise jobs.ScenarioJobInputError(jobs.ScenarioJobFailureCode.LEASE_EXPIRED)
            root, run, _ = rows
            try:
                auth = self._auth(session, root)
                return self._current_inputs(session, auth, root, run)
            except AuthorizationError:
                raise jobs.ScenarioJobInputError(
                    jobs.ScenarioJobFailureCode.ACCESS_DENIED
                ) from None
            except (app.ScenarioServiceError, ScenarioStorageError) as failure:
                raise _input_failure(failure) from None

        return await self._worker_run(action)

    async def complete_scenario_job(
        self, claim: jobs.ScenarioJobClaim, result: ScenarioCalculation
    ) -> bool:
        def action(session: Session) -> bool:
            rows = self._fenced(session, claim)
            if rows is None:
                return False
            root, run, job = rows
            try:
                auth = self._auth(session, root)
                inputs = self._current_inputs(session, auth, root, run)
                self.publish_result(session, auth, root, inputs, result)
                size = self._result_bytes(session, root)
                if self._fenced(session, claim) is None:
                    raise jobs.ScenarioJobInputError(jobs.ScenarioJobFailureCode.LEASE_EXPIRED)
                auth.check(session, now=self._now())
                self._finish_job(session, root, job, "succeeded", None, retained_bytes=size)
                return True
            except AuthorizationError:
                raise jobs.ScenarioJobInputError(
                    jobs.ScenarioJobFailureCode.ACCESS_DENIED
                ) from None
            except DomainError:
                raise jobs.ScenarioJobInputError(
                    jobs.ScenarioJobFailureCode.INPUT_CHANGED
                ) from None
            except (app.ScenarioServiceError, ScenarioStorageError) as failure:
                raise _input_failure(failure) from None

        return await self._worker_run(action)

    async def fail_scenario_job(
        self,
        claim: jobs.ScenarioJobClaim,
        *,
        failure_code: jobs.ScenarioJobFailureCode,
        retryable: bool,
    ) -> bool:
        if not isinstance(failure_code, jobs.ScenarioJobFailureCode) or type(retryable) is not bool:
            raise ValueError("Invalid scenario failure category.")

        def action(session: Session) -> bool:
            rows = self._fenced(session, claim)
            if rows is None:
                return False
            root, _, job = rows
            if retryable and job.consumer_attempts < 4 and claim.deadline_at > self._now():
                self._requeue(session, root, job, failure_code)
            else:
                self._terminal(session, root, job, failure_code)
            return True

        return await self._worker_run(action)
