"""Bounded fixed-task outboxes and integer-fenced private report consumers."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import timedelta
from typing import cast
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from trading212_application import report_jobs as jobs
from trading212_application import reports as app
from trading212_domain.report_manifest import encode_report_manifest
from trading212_domain.report_v3 import ReportManifestContract
from trading212_domain.reports import ReportFailureCode, ReportManifest
from trading212_security.principals import AuthorizationError

from .report_audit import audit_report_job
from .report_base import ReportStore, StoredJob, report_owner_lock
from .report_models import (
    ExportArtifactModel,
    ExportDispatchOutboxModel,
    ExportJobModel,
    ExportManifestModel,
    ReportArtifactModel,
    ReportAttemptModel,
    ReportDispatchOutboxModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportManifestModel,
)

type TaskMessage = jobs.ReportTaskMessage | jobs.ExportTaskMessage
type JobClaim = jobs.ReportJobClaim | jobs.ExportJobClaim
type DispatchClaim = jobs.ReportDispatchClaim | jobs.ExportDispatchClaim
type Outbox = ReportDispatchOutboxModel | ExportDispatchOutboxModel

_ACTOR = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


class PostgresReportJobStore(ReportStore):
    """Separate typed public methods share the same fixed internal transitions."""

    async def _worker_run[T](self, operation: Callable[[], T]) -> T:
        def execute() -> T:
            try:
                return operation()
            except AuthorizationError:
                raise jobs.ReportJobInputError(ReportFailureCode.ACCESS_DENIED) from None
            except app.ReportServiceError as error:
                code = (
                    ReportFailureCode.ACCESS_DENIED
                    if error.code is app.ReportServiceErrorCode.ACCESS_DENIED
                    else ReportFailureCode.INPUT_UNAVAILABLE
                )
                raise jobs.ReportJobInputError(code) from None
            except SQLAlchemyError:
                raise jobs.ReportJobInputError(
                    ReportFailureCode.STORAGE_UNAVAILABLE, retryable=True
                ) from None

        return await asyncio.to_thread(execute)

    def _message(self, job: StoredJob) -> TaskMessage:
        message = (
            jobs.ReportTaskMessage if isinstance(job, ReportJobModel) else jobs.ExportTaskMessage
        )
        return message(
            job_id=job.id,
            owner_id=job.owner_id,
            account_id=job.account_id,
            capture_id=job.input_id,
            input_digest=job.input_digest,
        )

    def _lookup(self, session: Session, message: TaskMessage) -> StoredJob | None:
        model: type[ReportJobModel] | type[ExportJobModel] = (
            ReportJobModel if isinstance(message, jobs.ReportTaskMessage) else ExportJobModel
        )
        row = session.scalar(
            select(model)
            .where(
                model.id == message.job_id,
                model.owner_id == message.owner_id,
                model.account_id == message.account_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        stored = cast(StoredJob | None, row)
        return stored if stored is not None and self._message(stored) == message else None

    def _outbox(self, session: Session, job: StoredJob) -> Outbox:
        model: type[ReportDispatchOutboxModel] | type[ExportDispatchOutboxModel] = (
            ReportDispatchOutboxModel
            if isinstance(job, ReportJobModel)
            else ExportDispatchOutboxModel
        )
        row = session.scalar(
            select(model)
            .where(model.owner_id == job.owner_id, model.job_id == job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise jobs.ReportJobInputError(ReportFailureCode.INPUT_CHANGED)
        return cast(Outbox, row)

    def _attempt(
        self,
        session: Session,
        job: StoredJob,
        *,
        phase: str,
        attempt: int,
        outcome: str,
        failure: ReportFailureCode | None = None,
    ) -> None:
        session.add(
            ReportAttemptModel(
                id=uuid4(),
                owner_id=job.owner_id,
                created_at=self._now(),
                report_job_id=job.id if isinstance(job, ReportJobModel) else None,
                export_job_id=job.id if isinstance(job, ExportJobModel) else None,
                phase=phase,
                attempt=attempt,
                fence=job.fence,
                outcome=outcome,
                failure_code=failure.value if failure else None,
            )
        )

    def _terminal(
        self, session: Session, job: StoredJob, failure: ReportFailureCode, *, expired: bool = False
    ) -> None:
        job.state = "expired" if expired else "failed"
        job.failure_code = failure.value
        job.completed_at = self._now()
        job.lease_id = None
        job.lease_expires_at = None
        job.consumer_id = None
        outbox = self._outbox(session, job)
        outbox.state = "dead_letter"
        outbox.claim_token = None
        outbox.claim_expires_at = None
        outbox.dispatcher_id = None
        outbox.failure_code = failure.value
        audit_report_job(
            session,
            job,
            event="expired" if expired else "failed",
            at=job.completed_at,
            failure=failure,
        )

    async def _claim_dispatches(
        self, *, export: bool, dispatcher_id: str, limit: int
    ) -> tuple[DispatchClaim, ...]:
        if not _ACTOR.fullmatch(dispatcher_id) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("A bounded dispatcher identity and batch are required.")
        model: type[ReportDispatchOutboxModel] | type[ExportDispatchOutboxModel] = (
            ExportDispatchOutboxModel if export else ReportDispatchOutboxModel
        )
        job_model: type[ReportJobModel] | type[ExportJobModel] = (
            ExportJobModel if export else ReportJobModel
        )

        def execute() -> tuple[DispatchClaim, ...]:
            at = self._now()
            with self._sessions() as session:
                candidates = tuple(
                    session.execute(
                        select(model.id, model.owner_id, model.job_id)
                        .join(job_model, job_model.id == model.job_id)
                        .where(
                            job_model.state.in_(("queued", "running")),
                            or_(job_model.state == "queued", job_model.lease_expires_at <= at),
                            or_(
                                and_(
                                    model.state.in_(("pending", "published")),
                                    model.available_at <= at,
                                ),
                                and_(model.state == "claimed", model.claim_expires_at <= at),
                            ),
                        )
                        .order_by(model.available_at, model.id)
                        .limit(limit)
                    )
                )
            claims: list[DispatchClaim] = []
            for identifier, owner, job_id in candidates:
                with self._sessions() as session, session.begin():
                    if not report_owner_lock(session, owner, wait=False):
                        continue
                    row = session.scalar(
                        select(model)
                        .where(model.id == identifier, model.owner_id == owner)
                        .with_for_update(skip_locked=True)
                        .execution_options(populate_existing=True)
                    )
                    job = session.scalar(
                        select(job_model)
                        .where(job_model.id == job_id, job_model.owner_id == owner)
                        .with_for_update(skip_locked=True)
                        .execution_options(populate_existing=True)
                    )
                    at = self._now()
                    if row is None or job is None or job.state not in {"queued", "running"}:
                        continue
                    job = cast(StoredJob, job)
                    if (
                        job.state == "running"
                        and job.lease_expires_at is not None
                        and job.lease_expires_at > at
                    ):
                        continue
                    if (
                        row.state == "dead_letter"
                        or (
                            row.state == "claimed"
                            and row.claim_expires_at is not None
                            and row.claim_expires_at > at
                        )
                        or row.available_at > at
                    ):
                        continue
                    if job.expires_at <= at:
                        self._terminal(
                            session, job, ReportFailureCode.INPUT_UNAVAILABLE, expired=True
                        )
                        continue
                    if row.publication_attempts >= 8 or job.consumer_attempts >= 4:
                        self._terminal(session, job, ReportFailureCode.ATTEMPTS_EXHAUSTED)
                        continue
                    try:
                        self._job_authorization(session, job)
                    except (AuthorizationError, app.ReportServiceError):
                        self._terminal(session, job, ReportFailureCode.ACCESS_DENIED)
                        continue
                    row.state = "claimed"
                    row.claim_token = uuid4()
                    row.claim_expires_at = at + timedelta(seconds=30)
                    row.dispatcher_id = dispatcher_id
                    row.publication_attempts += 1
                    row.failure_code = None
                    self._attempt(
                        session,
                        job,
                        phase="dispatch",
                        attempt=row.publication_attempts,
                        outcome="claimed",
                    )
                    message = self._message(job)
                    if isinstance(message, jobs.ReportTaskMessage):
                        claims.append(
                            jobs.ReportDispatchClaim(
                                message=message,
                                claim_token=row.claim_token,
                                claim_expires_at=row.claim_expires_at,
                                publication_attempt=row.publication_attempts,
                            )
                        )
                    else:
                        claims.append(
                            jobs.ExportDispatchClaim(
                                message=message,
                                claim_token=row.claim_token,
                                claim_expires_at=row.claim_expires_at,
                                publication_attempt=row.publication_attempts,
                            )
                        )
            return tuple(claims)

        return await self._worker_run(execute)

    async def claim_report_dispatches(
        self, *, dispatcher_id: str, limit: int = 20
    ) -> tuple[jobs.ReportDispatchClaim, ...]:
        return cast(
            tuple[jobs.ReportDispatchClaim, ...],
            await self._claim_dispatches(export=False, dispatcher_id=dispatcher_id, limit=limit),
        )

    async def claim_export_dispatches(
        self, *, dispatcher_id: str, limit: int = 20
    ) -> tuple[jobs.ExportDispatchClaim, ...]:
        return cast(
            tuple[jobs.ExportDispatchClaim, ...],
            await self._claim_dispatches(export=True, dispatcher_id=dispatcher_id, limit=limit),
        )

    async def _dispatch_transition(
        self, claim: DispatchClaim, failure: ReportFailureCode | None
    ) -> bool:
        def execute() -> bool:
            with self._sessions() as session, session.begin():
                report_owner_lock(session, claim.message.owner_id)
                job = self._lookup(session, claim.message)
                # Delivery can complete before its publisher returns. Preserve the
                # terminal result and historical claim without inventing an ack.
                if job is None or job.state not in {"queued", "running"}:
                    return False
                row = self._outbox(session, job)
                if (
                    row.state != "claimed"
                    or row.claim_token != claim.claim_token
                    or row.publication_attempts != claim.publication_attempt
                    or row.claim_expires_at is None
                    or row.claim_expires_at <= self._now()
                ):
                    return False
                self._attempt(
                    session,
                    job,
                    phase="dispatch",
                    attempt=row.publication_attempts,
                    outcome="published" if failure is None else "retry",
                    failure=failure,
                )
                row.claim_token = None
                row.claim_expires_at = None
                row.dispatcher_id = None
                if failure is None:
                    row.state = "published"
                    row.published_at = self._now()
                    row.available_at = self._now() + timedelta(seconds=60)
                    row.failure_code = None
                elif (
                    job.state == "running"
                    and job.lease_expires_at is not None
                    and job.lease_expires_at > self._now()
                ):
                    row.state = "published"
                    row.available_at = job.lease_expires_at
                    row.failure_code = failure.value
                elif row.publication_attempts >= 8:
                    self._terminal(session, job, ReportFailureCode.ATTEMPTS_EXHAUSTED)
                else:
                    row.state = "pending"
                    row.failure_code = failure.value
                    row.available_at = self._now() + timedelta(
                        seconds=min(2 ** (row.publication_attempts - 1), 60)
                    )
                return True

        return await self._worker_run(execute)

    async def acknowledge_report_dispatch(self, claim: jobs.ReportDispatchClaim) -> bool:
        return await self._dispatch_transition(claim, None)

    async def acknowledge_export_dispatch(self, claim: jobs.ExportDispatchClaim) -> bool:
        return await self._dispatch_transition(claim, None)

    async def defer_report_dispatch(
        self, claim: jobs.ReportDispatchClaim, *, failure: ReportFailureCode
    ) -> bool:
        return await self._dispatch_transition(claim, failure)

    async def defer_export_dispatch(
        self, claim: jobs.ExportDispatchClaim, *, failure: ReportFailureCode
    ) -> bool:
        return await self._dispatch_transition(claim, failure)

    async def _claim_job(self, message: TaskMessage, consumer_id: str) -> JobClaim | None:
        if not _ACTOR.fullmatch(consumer_id):
            raise ValueError("A bounded consumer identity is required.")

        def execute() -> JobClaim | None:
            with self._sessions() as session, session.begin():
                report_owner_lock(session, message.owner_id)
                job = self._lookup(session, message)
                at = self._now()
                if job is None or job.state not in {"queued", "running"} or job.available_at > at:
                    return None
                if (
                    job.state == "running"
                    and job.lease_expires_at is not None
                    and job.lease_expires_at > at
                ):
                    return None
                if job.expires_at <= at:
                    self._terminal(session, job, ReportFailureCode.INPUT_UNAVAILABLE, expired=True)
                    return None
                if job.consumer_attempts >= 4:
                    self._terminal(session, job, ReportFailureCode.ATTEMPTS_EXHAUSTED)
                    return None
                try:
                    self._job_authorization(session, job)
                except (AuthorizationError, app.ReportServiceError):
                    self._terminal(session, job, ReportFailureCode.ACCESS_DENIED)
                    return None
                job.state = "running"
                job.consumer_attempts += 1
                job.fence += 1
                job.lease_id = uuid4()
                job.lease_expires_at = at + timedelta(seconds=60)
                job.heartbeat_at = at
                job.consumer_id = consumer_id
                job.failure_code = None
                self._attempt(
                    session, job, phase="consumer", attempt=job.consumer_attempts, outcome="claimed"
                )
                if isinstance(message, jobs.ReportTaskMessage):
                    return jobs.ReportJobClaim(
                        message=message,
                        lease_id=job.lease_id,
                        fence=job.fence,
                        lease_expires_at=job.lease_expires_at,
                        consumer_attempt=job.consumer_attempts,
                    )
                return jobs.ExportJobClaim(
                    message=message,
                    lease_id=job.lease_id,
                    fence=job.fence,
                    lease_expires_at=job.lease_expires_at,
                    consumer_attempt=job.consumer_attempts,
                )

        return await self._worker_run(execute)

    async def claim_report_job(
        self, message: jobs.ReportTaskMessage, *, consumer_id: str
    ) -> jobs.ReportJobClaim | None:
        return cast(jobs.ReportJobClaim | None, await self._claim_job(message, consumer_id))

    async def claim_export_job(
        self, message: jobs.ExportTaskMessage, *, consumer_id: str
    ) -> jobs.ExportJobClaim | None:
        return cast(jobs.ExportJobClaim | None, await self._claim_job(message, consumer_id))

    def _live(self, session: Session, claim: JobClaim) -> StoredJob | None:
        job = self._lookup(session, claim.message)
        if (
            job is None
            or job.state != "running"
            or job.lease_id != claim.lease_id
            or job.fence != claim.fence
            or job.consumer_attempts != claim.consumer_attempt
            or job.lease_expires_at is None
            or job.lease_expires_at <= self._now()
            or job.expires_at <= self._now()
        ):
            return None
        return job

    async def _heartbeat(self, claim: JobClaim) -> bool:
        def execute() -> bool:
            with self._sessions() as session, session.begin():
                report_owner_lock(session, claim.message.owner_id)
                job = self._live(session, claim)
                if job is None:
                    return False
                try:
                    self._job_authorization(session, job)
                except (AuthorizationError, app.ReportServiceError):
                    self._terminal(session, job, ReportFailureCode.ACCESS_DENIED)
                    return False
                job.heartbeat_at = self._now()
                job.lease_expires_at = min(job.expires_at, self._now() + timedelta(seconds=60))
                return True

        return await self._worker_run(execute)

    async def heartbeat_report_job(self, claim: jobs.ReportJobClaim) -> bool:
        return await self._heartbeat(claim)

    async def heartbeat_export_job(self, claim: jobs.ExportJobClaim) -> bool:
        return await self._heartbeat(claim)

    @contextmanager
    def _open_document(self, claim: JobClaim) -> Iterator[app.ReportDocumentReader]:
        from .report_document_reader import PostgresReportDocumentReader

        reader = PostgresReportDocumentReader(self, claim)
        try:
            yield reader
        finally:
            reader.close()

    def open_report_document(
        self, claim: jobs.ReportJobClaim
    ) -> AbstractContextManager[app.ReportDocumentReader]:
        return self._open_document(claim)

    def open_export_document(
        self, claim: jobs.ExportJobClaim
    ) -> AbstractContextManager[app.ReportDocumentReader]:
        return self._open_document(claim)

    async def _complete(
        self,
        claim: JobClaim,
        manifest: ReportManifestContract,
        artifacts: tuple[app.RenderedArtifact, ...],
    ) -> bool:
        payload = encode_report_manifest(manifest)
        if (
            not 1 <= len(artifacts) <= 4
            or len({a.format for a in artifacts}) != len(artifacts)
            or sum(a.byte_length for a in artifacts) > 25 * 1024 * 1024
        ):
            raise jobs.ReportJobInputError(ReportFailureCode.LIMIT_EXCEEDED)
        for artifact in artifacts:
            if (
                len(artifact.content) != artifact.byte_length
                or hashlib.sha256(artifact.content).hexdigest() != artifact.content_digest
            ):
                raise jobs.ReportJobInputError(ReportFailureCode.INPUT_CHANGED)

        def execute() -> bool:
            with self._sessions() as session, session.begin():
                report_owner_lock(session, claim.message.owner_id)
                job = self._live(session, claim)
                if job is None:
                    return False
                authorization = self._job_authorization(session, job)
                original = session.scalar(
                    select(ReportInputSnapshotModel.canonical_manifest).where(
                        ReportInputSnapshotModel.id == job.input_id,
                        ReportInputSnapshotModel.owner_id == job.owner_id,
                    )
                )
                expected = set(job.formats) if isinstance(job, ReportJobModel) else {job.format}
                if original != payload or {a.format.value for a in artifacts} != expected:
                    raise jobs.ReportJobInputError(ReportFailureCode.INPUT_CHANGED)
                # Independently re-decode and compare the exact captured semantic manifest.
                if original is None or self._decode_manifest(job, original) != manifest:
                    raise jobs.ReportJobInputError(ReportFailureCode.INPUT_CHANGED)
                manifest_model = (
                    ReportManifestModel if isinstance(job, ReportJobModel) else ExportManifestModel
                )
                artifact_model = (
                    ReportArtifactModel if isinstance(job, ReportJobModel) else ExportArtifactModel
                )
                at = self._now()
                manifest_id = uuid4()
                digest = hashlib.sha256(payload).hexdigest()
                with session.begin_nested():
                    session.add(
                        manifest_model(
                            id=manifest_id,
                            owner_id=job.owner_id,
                            job_id=job.id,
                            input_id=job.input_id,
                            created_at=at,
                            content_digest=digest,
                            byte_length=len(payload),
                            publication_fence=claim.fence,
                            payload=payload,
                            purged_at=None,
                        )
                    )
                    session.flush()
                    prefix = job.report_type if isinstance(job, ReportJobModel) else job.dataset
                    for artifact in artifacts:
                        session.add(
                            artifact_model(
                                id=uuid4(),
                                owner_id=job.owner_id,
                                account_id=job.account_id,
                                job_id=job.id,
                                manifest_id=manifest_id,
                                created_at=at,
                                format=artifact.format.value,
                                mime_type=artifact.mime_type.value,
                                filename=f"{prefix}_{job.id}.{artifact.format.value}",
                                content_digest=artifact.content_digest,
                                byte_length=artifact.byte_length,
                                publication_fence=claim.fence,
                                contents=artifact.content,
                                expires_at=job.expires_at,
                                purged_at=None,
                            )
                        )
                    session.flush()
                    self._sources(session, authorization, job)
                    if self._live(session, claim) is None:
                        raise jobs.ReportJobInputError(ReportFailureCode.LEASE_EXPIRED)
                    job.state = "succeeded"
                    job.completed_at = self._now()
                    job.manifest_digest = digest
                    job.failure_code = None
                    job.lease_id = None
                    job.lease_expires_at = None
                    job.consumer_id = None
                    self._attempt(
                        session,
                        job,
                        phase="consumer",
                        attempt=job.consumer_attempts,
                        outcome="succeeded",
                    )
                    audit_report_job(session, job, event="completed", at=job.completed_at)
                    session.flush()
                    self._sources(session, authorization, job)
                return True

        return await self._worker_run(execute)

    async def complete_report_job(
        self,
        claim: jobs.ReportJobClaim,
        *,
        manifest: ReportManifestContract,
        artifacts: tuple[app.RenderedArtifact, ...],
    ) -> bool:
        return await self._complete(claim, manifest, artifacts)

    async def complete_export_job(
        self,
        claim: jobs.ExportJobClaim,
        *,
        manifest: ReportManifest,
        artifacts: tuple[app.RenderedArtifact, ...],
    ) -> bool:
        return await self._complete(claim, manifest, artifacts)

    async def _fail(self, claim: JobClaim, failure: ReportFailureCode, retryable: bool) -> bool:
        if not isinstance(failure, ReportFailureCode) or type(retryable) is not bool:
            raise ValueError("A typed report failure is required.")
        permanent = failure in {
            ReportFailureCode.INVALID_INPUT,
            ReportFailureCode.INPUT_CHANGED,
            ReportFailureCode.ACCESS_DENIED,
            ReportFailureCode.SOURCE_RESTRICTED,
            ReportFailureCode.LIMIT_EXCEEDED,
        }

        def execute() -> bool:
            with self._sessions() as session, session.begin():
                report_owner_lock(session, claim.message.owner_id)
                job = self._live(session, claim)
                if job is None:
                    return False
                if retryable and not permanent and job.consumer_attempts < 4:
                    job.state = "queued"
                    job.lease_id = None
                    job.lease_expires_at = None
                    job.consumer_id = None
                    job.failure_code = failure.value
                    job.available_at = self._now() + timedelta(
                        seconds=(1, 2, 4)[job.consumer_attempts - 1]
                    )
                    row = self._outbox(session, job)
                    row.state = "pending"
                    row.available_at = job.available_at
                    row.claim_token = None
                    row.claim_expires_at = None
                    row.dispatcher_id = None
                    self._attempt(
                        session,
                        job,
                        phase="consumer",
                        attempt=job.consumer_attempts,
                        outcome="retry",
                        failure=failure,
                    )
                else:
                    self._terminal(
                        session,
                        job,
                        ReportFailureCode.ATTEMPTS_EXHAUSTED
                        if retryable and not permanent
                        else failure,
                    )
                    self._attempt(
                        session,
                        job,
                        phase="consumer",
                        attempt=job.consumer_attempts,
                        outcome="failed",
                        failure=failure,
                    )
                return True

        return await self._worker_run(execute)

    async def fail_report_job(
        self, claim: jobs.ReportJobClaim, *, failure: ReportFailureCode, retryable: bool
    ) -> bool:
        return await self._fail(claim, failure, retryable)

    async def fail_export_job(
        self, claim: jobs.ExportJobClaim, *, failure: ReportFailureCode, retryable: bool
    ) -> bool:
        return await self._fail(claim, failure, retryable)

    async def expire_report_artifacts(self, *, limit: int = 100) -> int:
        from .report_retention import expire_report_payloads

        def execute() -> int:
            with self._sessions() as session, session.begin():
                return expire_report_payloads(session, at=self._now(), limit=limit)

        return await self._worker_run(execute)
