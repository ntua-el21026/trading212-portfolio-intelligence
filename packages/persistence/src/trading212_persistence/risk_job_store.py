"""Fixed risk outbox delivery, one global execution slot and fenced atomic completion."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Table, and_, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from trading212_application import risk as app
from trading212_application import risk_jobs as jobs
from trading212_domain.errors import DomainError
from trading212_domain.risk_result import RiskCalculation
from trading212_security.principals import AuthorizationError

from .premium_attempts import premium_attempt
from .premium_models import (
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from .report_authorization import ReportAuthorization, authorize_report_job
from .risk_definitions import RISK_WRITE_SCOPES, premium_owner_lock
from .risk_models import RiskRunModel
from .risk_service import MAX_RISK_RUN_BYTES, PostgresRiskService, verify_risk_execution
from .risk_storage import RiskIntegrityError, persist_risk_result

_ACTOR = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


class PostgresRiskJobStore(PostgresRiskService):
    async def _worker_run[T](self, action: Callable[[Session], T]) -> T:
        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    return action(session)
            except SQLAlchemyError:
                raise jobs.RiskJobInputError(
                    jobs.RiskJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
                ) from None

        return await asyncio.to_thread(execute)

    def _global_slot(self, session: Session) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "premium:single-execution-slot"},
        )

    def _message(self, root: PremiumRunModel, job: PremiumJobModel) -> jobs.RiskTaskMessage:
        return jobs.RiskTaskMessage(
            str(job.id), str(root.id), str(root.owner_id), str(root.account_id), root.input_digest
        )

    def _metadata(
        self, session: Session, message: jobs.RiskTaskMessage
    ) -> tuple[PremiumRunModel, RiskRunModel, PremiumJobModel] | None:
        premium_owner_lock(session, UUID(message.owner_id))
        row = session.execute(
            select(PremiumRunModel, RiskRunModel, PremiumJobModel)
            .join(RiskRunModel, RiskRunModel.id == PremiumRunModel.id)
            .join(PremiumJobModel, PremiumJobModel.run_id == PremiumRunModel.id)
            .where(
                PremiumRunModel.id == UUID(message.run_id),
                PremiumRunModel.owner_id == UUID(message.owner_id),
                PremiumRunModel.account_id == UUID(message.account_id),
                PremiumRunModel.kind == "risk",
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
            required_scopes=RISK_WRITE_SCOPES,
            expires_at=root.expires_at,
            now=self._now(),
        )

    def _terminal(
        self,
        session: Session,
        root: PremiumRunModel,
        job: PremiumJobModel,
        code: jobs.RiskJobFailureCode,
        *,
        expired: bool = False,
    ) -> None:
        self._finish_job(session, root, job, "expired" if expired else "failed", code.value)

    def _requeue(
        self,
        session: Session,
        root: PremiumRunModel,
        job: PremiumJobModel,
        code: jobs.RiskJobFailureCode,
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
            raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.INPUT_CHANGED)
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
                PremiumRunModel.kind == "risk",
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
                    session, root, job, jobs.RiskJobFailureCode.INPUT_UNAVAILABLE, expired=True
                )
            elif job.consumer_attempts >= 4 or (
                job.deadline_at is not None and job.deadline_at <= self._now()
            ):
                self._terminal(session, root, job, jobs.RiskJobFailureCode.ATTEMPTS_EXHAUSTED)
            elif (
                job.state == "running"
                and job.lease_expires_at is not None
                and job.lease_expires_at <= self._now()
            ):
                self._requeue(session, root, job, jobs.RiskJobFailureCode.LEASE_EXPIRED)

    async def claim_risk_dispatches(
        self, *, dispatcher_id: str, limit: int = 1
    ) -> tuple[jobs.RiskDispatchClaim, ...]:
        if (
            not isinstance(dispatcher_id, str)
            or _ACTOR.fullmatch(dispatcher_id) is None
            or type(limit) is not int
            or not 1 <= limit <= 20
        ):
            raise ValueError("Invalid bounded risk dispatcher request.")

        def action(session: Session) -> tuple[jobs.RiskDispatchClaim, ...]:
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
                    PremiumRunModel.kind == "risk",
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
                    self._terminal(session, root, job, jobs.RiskJobFailureCode.ACCESS_DENIED)
                    continue
                if outbox.publication_attempts >= 8:
                    self._terminal(session, root, job, jobs.RiskJobFailureCode.ATTEMPTS_EXHAUSTED)
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
                    jobs.RiskDispatchClaim(
                        self._message(root, job),
                        str(outbox.claim_token),
                        outbox.claim_expires_at,
                        outbox.publication_attempts,
                    )
                )
            return tuple(claims)

        return await self._worker_run(action)

    async def _dispatch_transition(
        self, claim: jobs.RiskDispatchClaim, failure: jobs.RiskJobFailureCode | None
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
                self._terminal(session, root, job, jobs.RiskJobFailureCode.ACCESS_DENIED)
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

    async def acknowledge_risk_dispatch(self, claim: jobs.RiskDispatchClaim) -> bool:
        return await self._dispatch_transition(claim, None)

    async def defer_risk_dispatch(
        self, claim: jobs.RiskDispatchClaim, *, failure_code: jobs.RiskJobFailureCode
    ) -> bool:
        if not isinstance(failure_code, jobs.RiskJobFailureCode):
            raise ValueError("Invalid risk failure category.")
        return await self._dispatch_transition(claim, failure_code)

    async def claim_risk_job(
        self, message: jobs.RiskTaskMessage, *, consumer_id: str
    ) -> jobs.RiskJobClaim | None:
        if not isinstance(consumer_id, str) or _ACTOR.fullmatch(consumer_id) is None:
            raise ValueError("Invalid risk consumer identity.")

        def action(session: Session) -> jobs.RiskJobClaim | None:
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
                self._terminal(session, root, job, jobs.RiskJobFailureCode.ACCESS_DENIED)
                return None
            deadline = min(root.expires_at, self._now() + timedelta(seconds=240))
            if job.consumer_attempts >= 4 or deadline <= self._now():
                self._terminal(session, root, job, jobs.RiskJobFailureCode.ATTEMPTS_EXHAUSTED)
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
            return jobs.RiskJobClaim(
                message, str(job.lease_token), job.lease_expires_at, job.consumer_attempts, deadline
            )

        return await self._worker_run(action)

    def _fenced(
        self, session: Session, claim: jobs.RiskJobClaim
    ) -> tuple[PremiumRunModel, RiskRunModel, PremiumJobModel] | None:
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

    async def heartbeat_risk_job(self, claim: jobs.RiskJobClaim) -> bool:
        def action(session: Session) -> bool:
            rows = self._fenced(session, claim)
            if rows is None:
                return False
            root, _, job = rows
            try:
                self._auth(session, root)
            except AuthorizationError:
                self._terminal(session, root, job, jobs.RiskJobFailureCode.ACCESS_DENIED)
                return False
            job.heartbeat_at = self._now()
            job.lease_expires_at = min(claim.deadline_at, self._now() + timedelta(seconds=60))
            return True

        return await self._worker_run(action)

    async def load_risk_job_input(self, claim: jobs.RiskJobClaim) -> jobs.RiskExecutionInput:
        def action(session: Session) -> jobs.RiskExecutionInput:
            rows = self._fenced(session, claim)
            if rows is None:
                raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.LEASE_EXPIRED)
            root, run, _ = rows
            try:
                auth = self._auth(session, root)
                return self._current_inputs(session, auth, root, run)
            except AuthorizationError:
                raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.ACCESS_DENIED) from None
            except app.RiskServiceError:
                raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.SOURCE_RESTRICTED) from None

        return await self._worker_run(action)

    async def complete_risk_job(self, claim: jobs.RiskJobClaim, result: RiskCalculation) -> bool:
        def action(session: Session) -> bool:
            rows = self._fenced(session, claim)
            if rows is None:
                return False
            root, run, job = rows
            try:
                auth = self._auth(session, root)
                inputs = self._current_inputs(session, auth, root, run)
                verify_risk_execution(result, inputs)
                row = persist_risk_result(session, run, result, at=self._now())
                # Storage capacity includes canonical and normalized physical row sizes.
                from .risk_storage import _RESULT_MODELS

                size = len(row.canonical_result)
                for model in _RESULT_MODELS:
                    size += (
                        session.scalar(
                            select(
                                func.coalesce(
                                    func.sum(
                                        func.pg_column_size(
                                            cast(Table, model.__table__).table_valued()
                                        )
                                    ),
                                    0,
                                )
                            ).where(model.__table__.c.result_id == row.id)
                        )
                        or 0
                    )
                if size > MAX_RISK_RUN_BYTES:
                    raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.LIMIT_EXCEEDED)
                if self._fenced(session, claim) is None:
                    raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.LEASE_EXPIRED)
                auth.check(session, now=self._now())
                self._finish_job(session, root, job, "succeeded", None, retained_bytes=size)
                return True
            except AuthorizationError:
                raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.ACCESS_DENIED) from None
            except (RiskIntegrityError, DomainError):
                raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.INPUT_CHANGED) from None
            except app.RiskServiceError:
                raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.SOURCE_RESTRICTED) from None

        return await self._worker_run(action)

    async def fail_risk_job(
        self, claim: jobs.RiskJobClaim, *, failure_code: jobs.RiskJobFailureCode, retryable: bool
    ) -> bool:
        if not isinstance(failure_code, jobs.RiskJobFailureCode) or type(retryable) is not bool:
            raise ValueError("Invalid risk failure category.")

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
