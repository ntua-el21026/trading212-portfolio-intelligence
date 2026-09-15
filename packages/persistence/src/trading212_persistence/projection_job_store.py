"""Fixed projection dispatch, shared premium execution and resumable fenced chunks."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from trading212_application import projection as app
from trading212_application import projection_jobs as jobs
from trading212_application import sources as source_app
from trading212_application.projection_capture import ProjectionCapturePlan
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.projection import PROJECTION_MAX_BYTES, ProjectionVariant
from trading212_domain.projection_result import ProjectionCalculation, ProjectionChunk
from trading212_security.principals import AuthorizationError, Scope

from .premium_attempts import premium_attempt
from .premium_models import (
    PremiumAttemptModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from .projection_capture_codec import ProjectionCodecError
from .projection_definition_store import READ_SCOPES, ProjectionStorageError, projection_owner_lock
from .projection_input_store import CapturedProjectionInputs
from .projection_job_lifecycle import finish_projection_job
from .projection_models import ProjectionRunModel
from .projection_run_authorization import require_projection_run_sources
from .projection_service_base import ProjectionServiceBase
from .report_authorization import ReportAuthorization, authorize_report_job

_ACTOR = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_EXECUTION_SECONDS = 240
_WRITE_SCOPES = READ_SCOPES | {Scope.PROJECTIONS_WRITE}
_VARIANTS: tuple[ProjectionVariant, ...] = ("baseline", "contribution_delta", "mean_log_delta")


def _input_failure(
    failure: app.ProjectionServiceError | ProjectionStorageError | ProjectionCodecError,
) -> jobs.ProjectionJobInputError:
    mapping = {
        "ACCESS_DENIED": jobs.ProjectionJobFailureCode.ACCESS_DENIED,
        "NOT_FOUND": jobs.ProjectionJobFailureCode.INPUT_UNAVAILABLE,
        "RUN_EXPIRED": jobs.ProjectionJobFailureCode.INPUT_UNAVAILABLE,
        "SOURCE_UNAVAILABLE": jobs.ProjectionJobFailureCode.SOURCE_RESTRICTED,
        "INPUT_BOUND_EXCEEDED": jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED,
        "RATE_LIMITED": jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED,
    }
    return jobs.ProjectionJobInputError(
        mapping.get(failure.code.value, jobs.ProjectionJobFailureCode.INPUT_CHANGED)
    )


def _job_claim(claim: jobs.ProjectionJobClaim) -> None:
    if type(claim) is not jobs.ProjectionJobClaim:
        raise ValueError("Invalid projection worker claim.")


class PostgresProjectionJobStore(ProjectionServiceBase):
    async def _worker_run[T](self, action: Callable[[Session], T]) -> T:
        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    # Every worker transaction takes the common slot before owner
                    # locks, including heartbeat and terminal failure transitions.
                    self._global_slot(session)
                    return action(session)
            except SQLAlchemyError:
                raise jobs.ProjectionJobInputError(
                    jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
                ) from None
            except source_app.SourceServiceError:
                raise jobs.ProjectionJobInputError(
                    jobs.ProjectionJobFailureCode.SOURCE_RESTRICTED
                ) from None
            except AuthorizationError:
                raise jobs.ProjectionJobInputError(
                    jobs.ProjectionJobFailureCode.ACCESS_DENIED
                ) from None
            except (
                app.ProjectionServiceError,
                ProjectionStorageError,
                ProjectionCodecError,
            ) as failure:
                raise _input_failure(failure) from None
            except DomainError as failure:
                code = (
                    jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED
                    if failure.code is ErrorCode.INPUT_BOUND_EXCEEDED
                    else jobs.ProjectionJobFailureCode.INPUT_CHANGED
                )
                raise jobs.ProjectionJobInputError(code) from None

        return await asyncio.to_thread(execute)

    def _global_slot(self, session: Session) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "premium:single-execution-slot"},
        )

    def _message(self, root: PremiumRunModel, job: PremiumJobModel) -> jobs.ProjectionTaskMessage:
        return jobs.ProjectionTaskMessage(
            str(job.id), str(root.id), str(root.owner_id), str(root.account_id), root.input_digest
        )

    def _metadata(
        self, session: Session, message: jobs.ProjectionTaskMessage
    ) -> tuple[PremiumRunModel, PremiumJobModel] | None:
        if type(message) is not jobs.ProjectionTaskMessage:
            raise ValueError("Invalid projection task message.")
        projection_owner_lock(session, UUID(message.owner_id))
        row = session.execute(
            select(PremiumRunModel, PremiumJobModel)
            .join(ProjectionRunModel, ProjectionRunModel.id == PremiumRunModel.id)
            .join(PremiumJobModel, PremiumJobModel.run_id == PremiumRunModel.id)
            .where(
                PremiumRunModel.id == UUID(message.run_id),
                PremiumRunModel.owner_id == UUID(message.owner_id),
                PremiumRunModel.account_id == UUID(message.account_id),
                PremiumRunModel.kind == "projection",
                PremiumRunModel.input_digest == message.input_digest,
                ProjectionRunModel.owner_id == PremiumRunModel.owner_id,
                ProjectionRunModel.account_id == PremiumRunModel.account_id,
                ProjectionRunModel.sealed.is_(True),
                ProjectionRunModel.capture_digest == PremiumRunModel.input_digest,
                PremiumJobModel.id == UUID(message.job_id),
                PremiumJobModel.owner_id == PremiumRunModel.owner_id,
                PremiumJobModel.account_id == PremiumRunModel.account_id,
            )
            .with_for_update(of=(PremiumRunModel, PremiumJobModel))
            .execution_options(populate_existing=True)
        ).first()
        if row is None:
            return None
        root, job = row
        if self._message(root, job) != message:
            return None
        return root, job

    def _auth(self, session: Session, root: PremiumRunModel) -> ReportAuthorization:
        auth = authorize_report_job(
            session,
            principal_id=root.actor_principal_id,
            owner_id=root.owner_id,
            account_id=root.account_id,
            required_scopes=_WRITE_SCOPES,
            expires_at=root.expires_at,
            now=self._now(),
        )
        run = session.scalar(
            select(ProjectionRunModel)
            .where(
                ProjectionRunModel.id == root.id,
                ProjectionRunModel.owner_id == root.owner_id,
                ProjectionRunModel.account_id == root.account_id,
                ProjectionRunModel.sealed.is_(True),
                ProjectionRunModel.capture_digest == root.input_digest,
            )
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise ProjectionStorageError(app.ProjectionErrorCode.PROJECTION_UNAVAILABLE)
        # This metadata-only traversal checks original and current recursive source
        # rights. A retention prefilter alone cannot confer authority to decode.
        deadline = require_projection_run_sources(self, session, auth, root, run)
        if root.expires_at > deadline or deadline <= self._now():
            raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)
        auth.check(session, now=self._now())
        return auth

    def _handoff_authority(
        self,
        session: Session,
        root: PremiumRunModel,
        job: PremiumJobModel,
    ) -> bool:
        try:
            self._auth(session, root)
        except AuthorizationError:
            self._terminal(session, root, job, jobs.ProjectionJobFailureCode.ACCESS_DENIED)
            return False
        except ProjectionStorageError as failure:
            self._terminal(session, root, job, _input_failure(failure).code)
            return False
        except source_app.SourceServiceError:
            self._terminal(session, root, job, jobs.ProjectionJobFailureCode.SOURCE_RESTRICTED)
            return False
        return True

    def _terminal(
        self,
        session: Session,
        root: PremiumRunModel,
        job: PremiumJobModel,
        code: jobs.ProjectionJobFailureCode,
        *,
        expired: bool = False,
    ) -> None:
        finish_projection_job(
            self, session, root, job, "expired" if expired else "failed", code.value
        )

    def _outbox(
        self, session: Session, root: PremiumRunModel, job: PremiumJobModel
    ) -> PremiumOutboxModel:
        outbox = session.scalar(
            select(PremiumOutboxModel)
            .where(
                PremiumOutboxModel.job_id == job.id,
                PremiumOutboxModel.owner_id == root.owner_id,
                PremiumOutboxModel.account_id == root.account_id,
                PremiumOutboxModel.task_name == jobs.PROJECTION_TASK_NAME,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if outbox is None:
            raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.INPUT_CHANGED)
        return outbox

    def _deadline(
        self,
        session: Session,
        root: PremiumRunModel,
        job: PremiumJobModel,
        *,
        initial_at: datetime | None = None,
    ) -> datetime:
        first_claim = session.scalar(
            select(func.min(PremiumAttemptModel.created_at)).where(
                PremiumAttemptModel.owner_id == root.owner_id,
                PremiumAttemptModel.account_id == root.account_id,
                PremiumAttemptModel.job_id == job.id,
                PremiumAttemptModel.kind == "consumer",
                PremiumAttemptModel.event == "claimed",
            )
        )
        if job.consumer_attempts > 0 and first_claim is None:
            raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.INPUT_CHANGED)
        return min(
            root.expires_at,
            (first_claim or initial_at or self._now()) + timedelta(seconds=_EXECUTION_SECONDS),
        )

    def _requeue(
        self,
        session: Session,
        root: PremiumRunModel,
        job: PremiumJobModel,
        code: jobs.ProjectionJobFailureCode,
    ) -> None:
        outbox = self._outbox(session, root, job)
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
        outbox.state = "pending"
        outbox.claim_token = outbox.claim_expires_at = outbox.dispatcher_id = None
        outbox.available_at = self._now()
        # Existing sealed chunks and their original attempts/proofs remain untouched.
        session.flush()

    def _recover(self, session: Session) -> None:
        rows = session.execute(
            select(PremiumRunModel, PremiumJobModel)
            .join(PremiumJobModel, PremiumJobModel.run_id == PremiumRunModel.id)
            .where(
                PremiumRunModel.kind == "projection",
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
            .limit(jobs.PROJECTION_DISPATCH_MAX_BATCH_SIZE)
        ).all()
        for candidate, candidate_job in rows:
            found = self._metadata(session, self._message(candidate, candidate_job))
            if found is None:
                continue
            root, job = found
            if job.state not in ("queued", "running"):
                continue
            if root.expires_at <= self._now():
                self._terminal(
                    session,
                    root,
                    job,
                    jobs.ProjectionJobFailureCode.INPUT_UNAVAILABLE,
                    expired=True,
                )
            elif (
                job.consumer_attempts >= jobs.PROJECTION_CONSUMER_ATTEMPTS
                or self._deadline(session, root, job) <= self._now()
            ):
                self._terminal(session, root, job, jobs.ProjectionJobFailureCode.ATTEMPTS_EXHAUSTED)
            elif (
                job.state == "running"
                and job.lease_expires_at is not None
                and job.lease_expires_at <= self._now()
            ) and self._handoff_authority(session, root, job):
                self._requeue(session, root, job, jobs.ProjectionJobFailureCode.LEASE_EXPIRED)

    async def claim_projection_dispatches(
        self,
        *,
        dispatcher_id: str,
        limit: int = jobs.PROJECTION_DISPATCH_BATCH_SIZE,
    ) -> tuple[jobs.ProjectionDispatchClaim, ...]:
        if (
            not isinstance(dispatcher_id, str)
            or _ACTOR.fullmatch(dispatcher_id) is None
            or type(limit) is not int
            or not 1 <= limit <= jobs.PROJECTION_DISPATCH_MAX_BATCH_SIZE
        ):
            raise ValueError("Invalid bounded projection dispatcher request.")

        def action(session: Session) -> tuple[jobs.ProjectionDispatchClaim, ...]:
            self._recover(session)
            if session.scalar(
                select(PremiumJobModel.id).where(PremiumJobModel.state == "running").limit(1)
            ):
                return ()
            candidates = session.execute(
                select(PremiumRunModel, PremiumJobModel)
                .join(PremiumJobModel, PremiumJobModel.run_id == PremiumRunModel.id)
                .join(PremiumOutboxModel, PremiumOutboxModel.job_id == PremiumJobModel.id)
                .where(
                    PremiumRunModel.kind == "projection",
                    PremiumJobModel.state == "queued",
                    PremiumOutboxModel.task_name == jobs.PROJECTION_TASK_NAME,
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
                            PremiumOutboxModel.published_at
                            <= self._now()
                            - timedelta(seconds=jobs.PROJECTION_WORKER_LEASE_SECONDS),
                        ),
                    ),
                )
                .order_by(PremiumRunModel.created_at, PremiumRunModel.id)
                .limit(limit)
            ).all()
            claims = []
            for candidate, candidate_job in candidates:
                found = self._metadata(session, self._message(candidate, candidate_job))
                if found is None:
                    continue
                root, job = found
                if job.state != "queued":
                    continue
                if self._deadline(session, root, job) <= self._now():
                    self._terminal(
                        session, root, job, jobs.ProjectionJobFailureCode.ATTEMPTS_EXHAUSTED
                    )
                    continue
                if not self._handoff_authority(session, root, job):
                    continue
                outbox = self._outbox(session, root, job)
                if outbox.publication_attempts >= jobs.PROJECTION_PUBLICATION_ATTEMPTS:
                    self._terminal(
                        session, root, job, jobs.ProjectionJobFailureCode.ATTEMPTS_EXHAUSTED
                    )
                    continue
                outbox.state = "claimed"
                outbox.publication_attempts += 1
                outbox.claim_token = uuid4()
                outbox.claim_expires_at = min(
                    root.expires_at,
                    self._now() + timedelta(seconds=jobs.PROJECTION_DISPATCH_CLAIM_SECONDS),
                )
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
                if not self._handoff_authority(session, root, job):
                    continue
                if outbox.claim_expires_at is None or outbox.claim_expires_at <= self._now():
                    raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
                claims.append(
                    jobs.ProjectionDispatchClaim(
                        self._message(root, job),
                        str(outbox.claim_token),
                        outbox.claim_expires_at,
                        outbox.publication_attempts,
                    )
                )
            return tuple(claims)

        return await self._worker_run(action)

    async def _dispatch_transition(
        self,
        claim: jobs.ProjectionDispatchClaim,
        failure: jobs.ProjectionJobFailureCode | None,
    ) -> bool:
        if type(claim) is not jobs.ProjectionDispatchClaim:
            raise ValueError("Invalid projection dispatch claim.")

        def action(session: Session) -> bool:
            found = self._metadata(session, claim.message)
            if found is None:
                return False
            root, job = found
            outbox = self._outbox(session, root, job)
            if (
                outbox.state != "claimed"
                or outbox.claim_token != UUID(claim.claim_token)
                or outbox.publication_attempts != claim.publication_attempt
                or outbox.claim_expires_at is None
                or outbox.claim_expires_at != claim.expires_at
                or outbox.claim_expires_at <= self._now()
                or job.state not in ("queued", "running")
            ):
                return False
            if not self._handoff_authority(session, root, job):
                return False
            if claim.expires_at <= self._now():
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
            if not self._handoff_authority(session, root, job):
                return False
            if claim.expires_at <= self._now():
                raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
            return True

        return await self._worker_run(action)

    async def acknowledge_projection_dispatch(self, claim: jobs.ProjectionDispatchClaim) -> bool:
        return await self._dispatch_transition(claim, None)

    async def defer_projection_dispatch(
        self,
        claim: jobs.ProjectionDispatchClaim,
        *,
        failure_code: jobs.ProjectionJobFailureCode,
    ) -> bool:
        if not isinstance(failure_code, jobs.ProjectionJobFailureCode):
            raise ValueError("Invalid projection failure category.")
        return await self._dispatch_transition(claim, failure_code)

    async def claim_projection_job(
        self,
        message: jobs.ProjectionTaskMessage,
        *,
        consumer_id: str,
    ) -> jobs.ProjectionJobClaim | None:
        if (
            type(message) is not jobs.ProjectionTaskMessage
            or not isinstance(consumer_id, str)
            or _ACTOR.fullmatch(consumer_id) is None
        ):
            raise ValueError("Invalid projection consumer request.")

        def action(session: Session) -> jobs.ProjectionJobClaim | None:
            self._recover(session)
            found = self._metadata(session, message)
            if found is None:
                return None
            root, job = found
            if job.state != "queued" or session.scalar(
                select(PremiumJobModel.id).where(PremiumJobModel.state == "running").limit(1)
            ):
                return None
            if not self._handoff_authority(session, root, job):
                return None
            claimed_at = self._now()
            deadline = self._deadline(session, root, job, initial_at=claimed_at)
            if (
                job.consumer_attempts >= jobs.PROJECTION_CONSUMER_ATTEMPTS
                or deadline <= self._now()
            ):
                self._terminal(session, root, job, jobs.ProjectionJobFailureCode.ATTEMPTS_EXHAUSTED)
                return None
            if root.reserved_bytes != PROJECTION_MAX_BYTES or root.retained_bytes != 0:
                raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.INPUT_CHANGED)
            job.state = "running"
            job.consumer_attempts += 1
            job.lease_token = uuid4()
            job.deadline_at = deadline
            job.lease_expires_at = min(
                deadline, self._now() + timedelta(seconds=jobs.PROJECTION_WORKER_LEASE_SECONDS)
            )
            job.heartbeat_at = claimed_at
            job.consumer_id = consumer_id
            premium_attempt(
                session,
                job,
                kind="consumer",
                event="claimed",
                number=job.consumer_attempts,
                token=job.lease_token,
                at=claimed_at,
            )
            if not self._handoff_authority(session, root, job):
                return None
            if (
                job.lease_expires_at is None
                or job.lease_expires_at <= self._now()
                or deadline <= self._now()
            ):
                return None
            return jobs.ProjectionJobClaim(
                message, str(job.lease_token), job.lease_expires_at, job.consumer_attempts, deadline
            )

        return await self._worker_run(action)

    def _fenced(
        self,
        session: Session,
        claim: jobs.ProjectionJobClaim,
    ) -> tuple[PremiumRunModel, PremiumJobModel] | None:
        rows = self._metadata(session, claim.message)
        if rows is None:
            return None
        root, job = rows
        if (
            job.state != "running"
            or job.lease_token != UUID(claim.claim_token)
            or job.consumer_attempts != claim.consumer_attempt
            or job.lease_expires_at is None
            or job.lease_expires_at <= self._now()
            or job.deadline_at is None
            or job.deadline_at != claim.deadline_at
            or job.deadline_at <= self._now()
            or root.expires_at <= self._now()
            or root.reserved_bytes != PROJECTION_MAX_BYTES
            or root.retained_bytes != 0
        ):
            return None
        return rows

    def _current_inputs(
        self,
        session: Session,
        auth: ReportAuthorization,
        root: PremiumRunModel,
    ) -> CapturedProjectionInputs:
        captured = self.read_retained_input(session, auth, root.id)
        if (
            captured.input_digest != root.input_digest
            or captured.plan.selection.account_id != root.account_id
        ):
            raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.INPUT_CHANGED)
        return captured

    def _final_boundary(self, session: Session, claim: jobs.ProjectionJobClaim) -> None:
        rows = self._fenced(session, claim)
        if rows is None:
            raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
        self._auth(session, rows[0])
        if self._fenced(session, claim) is None:
            raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)

    async def heartbeat_projection_job(self, claim: jobs.ProjectionJobClaim) -> bool:
        _job_claim(claim)

        def action(session: Session) -> bool:
            rows = self._fenced(session, claim)
            if rows is None:
                return False
            root, job = rows
            if not self._handoff_authority(session, root, job):
                return False
            if self._fenced(session, claim) is None:
                return False
            job.heartbeat_at = self._now()
            job.lease_expires_at = min(
                claim.deadline_at,
                self._now() + timedelta(seconds=jobs.PROJECTION_WORKER_LEASE_SECONDS),
            )
            session.flush()
            self._final_boundary(session, claim)
            return True

        return await self._worker_run(action)

    async def load_projection_job_input(
        self, claim: jobs.ProjectionJobClaim
    ) -> ProjectionCapturePlan:
        _job_claim(claim)

        def action(session: Session) -> ProjectionCapturePlan:
            rows = self._fenced(session, claim)
            if rows is None:
                raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
            root, _ = rows
            auth = self._auth(session, root)
            captured = self._current_inputs(session, auth, root)
            self._final_boundary(session, claim)
            return captured.plan

        return await self._worker_run(action)

    async def load_projection_job_chunks(
        self,
        claim: jobs.ProjectionJobClaim,
        *,
        after: tuple[ProjectionVariant, int] | None = None,
        limit: int = 32,
    ) -> tuple[ProjectionChunk, ...]:
        _job_claim(claim)
        if (
            type(limit) is not int
            or not 1 <= limit <= 32
            or (
                after is not None
                and (
                    type(after) is not tuple
                    or len(after) != 2
                    or after[0] not in _VARIANTS
                    or type(after[1]) is not int
                    or not 0 <= after[1] < 4096
                )
            )
        ):
            raise ValueError("Invalid bounded projection chunk page.")

        def action(session: Session) -> tuple[ProjectionChunk, ...]:
            rows = self._fenced(session, claim)
            if rows is None:
                raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
            root, _ = rows
            auth = self._auth(session, root)
            captured = self._current_inputs(session, auth, root)
            stored = self.read_chunks(session, auth, root, captured, after=after, limit=limit)
            self._final_boundary(session, claim)
            # A nonempty short page can reflect the aggregate byte budget. The
            # worker continues after the last absolute key until an empty page.
            return tuple(item.chunk for item in stored)

        return await self._worker_run(action)

    async def save_projection_job_chunk(
        self, claim: jobs.ProjectionJobClaim, chunk: ProjectionChunk
    ) -> bool:
        _job_claim(claim)
        if type(chunk) is not ProjectionChunk:
            raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.INPUT_CHANGED)

        def action(session: Session) -> bool:
            rows = self._fenced(session, claim)
            if rows is None:
                return False
            root, job = rows
            auth = self._auth(session, root)
            captured = self._current_inputs(session, auth, root)
            self.publish_chunk(
                session,
                auth,
                root,
                captured,
                chunk,
                job_id=job.id,
                lease_token=UUID(claim.claim_token),
                consumer_attempt=claim.consumer_attempt,
            )
            self._final_boundary(session, claim)
            return True

        return await self._worker_run(action)

    async def complete_projection_job(
        self, claim: jobs.ProjectionJobClaim, result: ProjectionCalculation
    ) -> bool:
        _job_claim(claim)
        if type(result) is not ProjectionCalculation:
            raise jobs.ProjectionJobInputError(jobs.ProjectionJobFailureCode.INPUT_CHANGED)

        def action(session: Session) -> bool:
            rows = self._fenced(session, claim)
            if rows is None:
                return False
            root, job = rows
            auth = self._auth(session, root)
            captured = self._current_inputs(session, auth, root)
            self.publish_result(
                session,
                auth,
                root,
                captured,
                result,
                job_id=job.id,
                lease_token=UUID(claim.claim_token),
                consumer_attempt=claim.consumer_attempt,
            )
            size = self._result_bytes(session, root)
            self._final_boundary(session, claim)
            finish_projection_job(self, session, root, job, "succeeded", None, retained_bytes=size)
            # Job-state-independent authority is checked again after accounting;
            # a failure rolls back the seal, job and capacity together.
            self._auth(session, root)
            return True

        return await self._worker_run(action)

    async def fail_projection_job(
        self,
        claim: jobs.ProjectionJobClaim,
        *,
        failure_code: jobs.ProjectionJobFailureCode,
        retryable: bool,
    ) -> bool:
        _job_claim(claim)
        if (
            not isinstance(failure_code, jobs.ProjectionJobFailureCode)
            or type(retryable) is not bool
        ):
            raise ValueError("Invalid projection failure category.")

        def action(session: Session) -> bool:
            rows = self._fenced(session, claim)
            if rows is None:
                return False
            root, job = rows
            if (
                retryable
                and job.consumer_attempts < jobs.PROJECTION_CONSUMER_ATTEMPTS
                and claim.deadline_at > self._now()
            ):
                if self._handoff_authority(session, root, job):
                    if self._fenced(session, claim) is None:
                        return False
                    self._requeue(session, root, job, failure_code)
            else:
                # Operational cleanup must remain possible after a grant/source is
                # revoked. No private payload read is needed to charge physical bytes.
                self._terminal(session, root, job, failure_code)
            return True

        return await self._worker_run(action)
