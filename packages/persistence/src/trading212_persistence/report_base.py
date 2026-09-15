"""Shared report authorization and bounded metadata projections."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import reports as app
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.reports import (
    ExportDataset,
    ExportFieldSet,
    ExportFormat,
    ExportSelection,
    ReportFailureCode,
    ReportFormat,
    ReportJobState,
    ReportManifest,
    ReportMimeType,
    ReportSelection,
    ReportSourceUse,
    ReportType,
    report_schema_version,
)
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Scope

from .report_authorization import ReportAuthorization, authorize_report_job
from .report_models import (
    ExportArtifactModel,
    ExportJobModel,
    ReportArtifactBase,
    ReportArtifactModel,
    ReportDefinitionModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportRetentionWorkModel,
)

type StoredJob = ReportJobModel | ExportJobModel
type StoredArtifact = ReportArtifactBase


def report_error(code: app.ReportServiceErrorCode) -> app.ReportServiceError:
    return app.ReportServiceError(
        code,
        {
            app.ReportServiceErrorCode.NOT_FOUND: "The private report resource was not found.",
            app.ReportServiceErrorCode.ACCESS_DENIED: "Access to the private report is denied.",
            app.ReportServiceErrorCode.VALIDATION_FAILED: "The report request is invalid.",
            app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED: "The report exceeds its bound.",
            app.ReportServiceErrorCode.CONFLICT: (
                "The report command conflicts with an earlier request."
            ),
            app.ReportServiceErrorCode.ARTIFACT_EXPIRED: "The private artifact has expired.",
            app.ReportServiceErrorCode.REPORT_UNAVAILABLE: "The private report is unavailable.",
            app.ReportServiceErrorCode.INVALID_STATE_TRANSITION: (
                "The private report is not ready for this operation."
            ),
            app.ReportServiceErrorCode.RATE_LIMITED: (
                "The private artifact grant limit was reached."
            ),
        }[code],
        retryable=code
        in {app.ReportServiceErrorCode.REPORT_UNAVAILABLE, app.ReportServiceErrorCode.RATE_LIMITED},
    )


def report_scopes(
    *,
    sections: tuple[str, ...] = (),
    dataset: str | None = None,
    create: bool = False,
    detail: bool = False,
) -> frozenset[Scope]:
    """Derive the fixed capability union from sealed selections, never worker input."""
    result = {Scope.PORTFOLIO_READ, Scope.REPORTS_WRITE if create else Scope.REPORTS_READ}
    if create or detail:
        result.add(Scope.ANALYTICS_READ)
        if dataset == "alerts":
            result.add(Scope.ALERTS_READ)
        if set(sections) & {"income", "cash_flows", "activity", "risk"} or dataset in {
            "activity",
            "dividends",
        }:
            result.add(Scope.ACTIVITY_READ)
        if set(sections) & {"targets", "drift", "contribution_plan"} or dataset in {
            "targets",
            "plans",
        }:
            result.add(Scope.TARGETS_READ)
    return frozenset(result)


def selection_scopes(selection: ReportSelection | ExportSelection) -> frozenset[Scope]:
    if isinstance(selection, ReportSelection):
        return report_scopes(sections=tuple(s.value for s in selection.sections), create=True)
    return report_scopes(dataset=selection.dataset.value, create=True)


def job_scopes(
    session: Session, job: StoredJob, *, create: bool = False, detail: bool = False
) -> frozenset[Scope]:
    if isinstance(job, ExportJobModel):
        return report_scopes(dataset=job.dataset, create=create, detail=detail)
    definition = session.scalar(
        select(ReportDefinitionModel).where(
            ReportDefinitionModel.id == job.definition_id,
            ReportDefinitionModel.owner_id == job.owner_id,
            ReportDefinitionModel.account_id == job.account_id,
        )
    )
    if definition is None:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    return report_scopes(sections=tuple(definition.sections), create=create, detail=detail)


def report_owner_lock(session: Session, owner_id: UUID, *, wait: bool = True) -> bool:
    """Source serialization precedes family work, report rows and collection capacity."""
    function = "pg_advisory_xact_lock" if wait else "pg_try_advisory_xact_lock"
    result = session.scalar(
        text(f"SELECT {function}(hashtextextended(:key,0))"), {"key": f"sources:{owner_id}"}
    )
    return wait or bool(result)


def artifact_metadata(row: StoredArtifact) -> app.ReportArtifactMetadata:
    return app.ReportArtifactMetadata(
        artifact_id=row.id,
        format=ReportFormat(row.format),
        mime_type=ReportMimeType(row.mime_type),
        byte_length=row.byte_length,
        content_digest=row.content_digest,
        expires_at=row.expires_at,
    )


class ReportStore:
    def __init__(
        self, sessions: sessionmaker[Session], *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return require_utc(self._clock())

    async def _run[T](self, operation: Callable[[], T]) -> T:
        def execute() -> T:
            try:
                return operation()
            except AuthorizationError:
                raise report_error(app.ReportServiceErrorCode.ACCESS_DENIED) from None
            except DomainError as exc:
                if exc.code is ErrorCode.INPUT_BOUND_EXCEEDED:
                    raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED) from None
                raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED) from None
            except SQLAlchemyError:
                raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE) from None

        return await asyncio.to_thread(execute)

    def _input(
        self, session: Session, job: StoredJob, *, allow_expired: bool = False
    ) -> ReportInputSnapshotModel:
        row = session.scalar(
            select(ReportInputSnapshotModel)
            .where(
                ReportInputSnapshotModel.owner_id == job.owner_id,
                ReportInputSnapshotModel.account_id == job.account_id,
                ReportInputSnapshotModel.id == job.input_id,
            )
            .execution_options(populate_existing=True)
        )
        version = job.contract_version if isinstance(job, ReportJobModel) else 1
        if (
            row is None
            or row.sealed_at is None
            or row.input_digest != job.input_digest
            or row.contract_version != version
            or version not in (1, 2)
        ):
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        if not allow_expired and (
            row.purged_at is not None
            or row.expires_at <= self._now()
            or job.expires_at <= self._now()
            or session.scalar(
                select(ReportRetentionWorkModel.id)
                .where(
                    ReportRetentionWorkModel.owner_id == job.owner_id,
                    ReportRetentionWorkModel.input_id == row.id,
                )
                .limit(1)
            )
            is not None
        ):
            raise report_error(app.ReportServiceErrorCode.ARTIFACT_EXPIRED)
        return row

    def _manifest_contract(self, job: StoredJob, manifest: ReportManifest) -> None:
        version = job.contract_version if isinstance(job, ReportJobModel) else 1
        if (
            manifest.document.document_schema_version != f"{version}.0.0"
            or report_schema_version(manifest.document.selection) != f"{version}.0.0"
        ):
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)

    def _sources(
        self, session: Session, authorization: ReportAuthorization, job: StoredJob
    ) -> None:
        from .report_sources import authorize_report_sources

        authorization.check(session, now=self._now())
        self._input(session, job)
        authorize_report_sources(
            session,
            authorization,
            input_id=job.input_id,
            source_use=ReportSourceUse.REPORT
            if isinstance(job, ReportJobModel)
            else ReportSourceUse.EXPORT,
            now=self._now(),
        )

    def _job_authorization(self, session: Session, job: StoredJob) -> ReportAuthorization:
        authorization = authorize_report_job(
            session,
            principal_id=job.principal_id,
            owner_id=job.owner_id,
            account_id=job.account_id,
            required_scopes=job_scopes(session, job, create=True),
            expires_at=job.expires_at,
            now=self._now(),
        )
        self._sources(session, authorization, job)
        return authorization

    def _status(
        self, session: Session, authorization: ReportAuthorization, job: StoredJob
    ) -> app.ReportJobStatus | app.ExportJobStatus:
        row = self._input(session, job, allow_expired=True)
        expired = (
            row.purged_at is not None
            or row.expires_at <= self._now()
            or job.expires_at <= self._now()
        )
        pending = (
            session.scalar(
                select(ReportRetentionWorkModel.id)
                .where(
                    ReportRetentionWorkModel.owner_id == job.owner_id,
                    ReportRetentionWorkModel.input_id == row.id,
                )
                .limit(1)
            )
            is not None
        )
        state = ReportJobState.EXPIRED if expired or pending else ReportJobState(job.state)
        context = None
        if state not in {ReportJobState.EXPIRED, ReportJobState.CANCELLED}:
            from trading212_application.reports import decode_report_pinned_context

            self._sources(session, authorization, job)
            payload = session.scalar(
                select(ReportInputSnapshotModel.canonical_context).where(
                    ReportInputSnapshotModel.id == row.id,
                    ReportInputSnapshotModel.owner_id == row.owner_id,
                )
            )
            if payload is None:
                raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
            context = decode_report_pinned_context(payload)
            if (
                context.input_digest != job.input_digest
                or context.document_digest != row.document_digest
                or context.schema_version != f"{row.contract_version}.0.0"
                or context.profile_version != f"report_sections_v{row.contract_version}"
            ):
                raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        artifacts: tuple[app.ReportArtifactMetadata, ...] = ()
        if job.manifest_digest is not None:
            model: type[ReportArtifactModel] | type[ExportArtifactModel] = (
                ReportArtifactModel if isinstance(job, ReportJobModel) else ExportArtifactModel
            )
            rows = tuple(
                session.scalars(
                    select(model)
                    .where(model.owner_id == job.owner_id, model.job_id == job.id)
                    .order_by(model.format)
                    .limit(5)
                )
            )
            if len(rows) > 4:
                raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
            artifacts = tuple(artifact_metadata(artifact) for artifact in rows)
        authorization.check(session, now=self._now())
        if isinstance(job, ReportJobModel):
            return app.ReportJobStatus(
                account_id=job.account_id,
                context=context,
                job_id=job.id,
                report_id=job.id if job.manifest_digest else None,
                state=state,
                requested_at=job.requested_at,
                completed_at=job.completed_at,
                expires_at=job.expires_at,
                failure_code=ReportFailureCode(job.failure_code) if job.failure_code else None,
                report_type=ReportType(job.report_type),
                formats=tuple(ReportFormat(x) for x in job.formats),
                manifest_digest=job.manifest_digest,
                artifacts=artifacts,
            )
        return app.ExportJobStatus(
            account_id=job.account_id,
            context=context,
            export_id=job.id,
            state=state,
            requested_at=job.requested_at,
            completed_at=job.completed_at,
            expires_at=job.expires_at,
            failure_code=ReportFailureCode(job.failure_code) if job.failure_code else None,
            dataset=ExportDataset(job.dataset),
            field_set=ExportFieldSet(job.field_set),
            format=ExportFormat(job.format),
            manifest_digest=job.manifest_digest,
            artifacts=artifacts,
        )
