"""Atomic private report/export creation and authorized durable reads."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import reports as app
from trading212_application.queries import (
    CollectionSnapshotCapacityError,
    CursorCodec,
    CursorValidationError,
)
from trading212_application.views import Page
from trading212_domain.report_manifest import encode_report_selection
from trading212_domain.report_v3 import ReportManifestContract, is_report_selection
from trading212_domain.reports import (
    ReportSourceUse,
    report_schema_version,
)
from trading212_security.principals import Principal

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
)
from .report_audit import audit_report_job
from .report_authorization import ReportAuthorization, authorize_report_request
from .report_base import (
    ReportStore,
    StoredJob,
    job_scopes,
    report_error,
    report_owner_lock,
    report_scopes,
    selection_scopes,
)
from .report_input_store import ReportInputSink
from .report_models import (
    ApplicationCommandIdentityModel,
    ExportDispatchOutboxModel,
    ExportJobModel,
    ReportDefinitionModel,
    ReportDispatchOutboxModel,
    ReportInputSnapshotModel,
    ReportJobModel,
)
from .risk_inputs import RiskPreflight

type CaptureFactory = Callable[
    [Session, ReportAuthorization, ReportSourceUse], app.ReportCapturePort
]


def _command_digest(command: app.GenerateReportCommand | app.CreateExportCommand) -> str:
    return app.report_request_digest(command)


class PostgresReportService(ReportStore):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        capture_factory: CaptureFactory | None = None,
        contract_version: int = 1,
        risk_preflight: RiskPreflight | None = None,
        cursor_ttl_seconds: int = 3600,
        max_active_collection_snapshots_per_owner: int = 64,
        max_active_collection_members_per_owner: int = 250_000,
    ) -> None:
        super().__init__(sessions, clock=clock)
        if type(contract_version) is not int or contract_version not in (1, 2, 3, 4):
            raise ValueError("Report contract version is unsupported.")
        self._contract_version = contract_version
        self._cursor_key = cursor_signing_key
        self._cursors = CursorCodec(
            cursor_signing_key, ttl_seconds=cursor_ttl_seconds, clock=self._clock
        )
        self._capture_factory = capture_factory
        self._risk_preflight = risk_preflight
        self._cursor_ttl = cursor_ttl_seconds
        self._max_collections = max_active_collection_snapshots_per_owner
        self._max_members = max_active_collection_members_per_owner

    def _capture_port(
        self, session: Session, authorization: ReportAuthorization, use: ReportSourceUse
    ) -> app.ReportCapturePort:
        if self._capture_factory is not None:
            return self._capture_factory(session, authorization, use)
        from .report_capture import PostgresReportCapture

        return PostgresReportCapture(
            session,
            authorization,
            source_use=use,
            risk_preflight=self._risk_preflight,
            sessions=self._sessions,
            clock=self._clock,
            cursor_signing_key=self._cursor_key,
        )

    async def generate_report(
        self, principal: Principal, command: app.GenerateReportCommand
    ) -> app.ReportJobStatus:
        return cast(app.ReportJobStatus, await self._generate(principal, command))

    async def create_export(
        self, principal: Principal, command: app.CreateExportCommand
    ) -> app.ExportJobStatus:
        return cast(app.ExportJobStatus, await self._generate(principal, command))

    async def _generate(
        self, principal: Principal, command: app.GenerateReportCommand | app.CreateExportCommand
    ) -> app.ReportJobStatus | app.ExportJobStatus:
        selection = command.selection
        use = (
            ReportSourceUse.REPORT
            if isinstance(command, app.GenerateReportCommand)
            else ReportSourceUse.EXPORT
        )
        task = "reports.generate.v1" if use is ReportSourceUse.REPORT else "exports.generate.v1"
        command_name = (
            "reports.generate.v2"
            if use is ReportSourceUse.REPORT and self._contract_version in (2, 3, 4)
            else task
        )
        digest = _command_digest(command)

        def execute() -> app.ReportJobStatus | app.ExportJobStatus:
            with self._sessions() as session, session.begin():
                authorization = authorize_report_request(
                    session,
                    principal,
                    account_id=selection.account_id,
                    required_scopes=selection_scopes(selection),
                    now=self._now(),
                )
                selected_version = {"1.0.0": 1, "2.0.0": 2, "3.0.0": 3, "4.0.0": 4}[
                    report_schema_version(selection)
                ]
                if selected_version != self._contract_version:
                    raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
                report_owner_lock(session, authorization.owner_id)
                prior = session.scalar(
                    select(ApplicationCommandIdentityModel).where(
                        ApplicationCommandIdentityModel.owner_id == authorization.owner_id,
                        ApplicationCommandIdentityModel.command == command_name,
                        ApplicationCommandIdentityModel.idempotency_key == command.idempotency_key,
                    )
                )
                if prior is not None:
                    if prior.command_digest != digest or prior.account_id != selection.account_id:
                        raise report_error(app.ReportServiceErrorCode.CONFLICT)
                    model: type[ReportJobModel] | type[ExportJobModel] = (
                        ReportJobModel if use is ReportSourceUse.REPORT else ExportJobModel
                    )
                    identifier = (
                        prior.report_job_id
                        if use is ReportSourceUse.REPORT
                        else prior.export_job_id
                    )
                    job = session.scalar(
                        select(model).where(
                            model.owner_id == authorization.owner_id, model.id == identifier
                        )
                    )
                    if job is None:
                        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
                    return self._status(session, authorization, cast(StoredJob, job))
                at = self._now()
                sink = ReportInputSink(
                    session,
                    authorization,
                    selection=selection,
                    expires_at=at + timedelta(days=command.ttl_days),
                    clock=self._clock,
                )
                capture = self._capture_port(session, authorization, use)
                summary = (
                    capture.capture_report(selection, sink=sink)
                    if is_report_selection(selection)
                    else capture.capture_export(selection, sink=sink)
                )
                authorization.check(session, now=self._now())
                sink.finish(summary)
                common = dict(
                    id=uuid4(),
                    owner_id=authorization.owner_id,
                    account_id=authorization.account_id,
                    principal_id=authorization.principal_id,
                    input_id=sink.row.id,
                    created_at=at,
                    command_digest=digest,
                    input_digest=sink.row.input_digest,
                    authorization_policy="report_delegation_v1",
                    state="queued",
                    requested_at=at,
                    expires_at=sink.row.expires_at,
                    completed_at=None,
                    failure_code=None,
                    consumer_attempts=0,
                    fence=0,
                    lease_id=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                    consumer_id=None,
                    available_at=at,
                    manifest_digest=None,
                )
                outbox_model: type[ReportDispatchOutboxModel] | type[ExportDispatchOutboxModel]
                if is_report_selection(selection):
                    definition_digest = hashlib.sha256(
                        encode_report_selection(selection)
                    ).hexdigest()
                    definition = session.scalar(
                        select(ReportDefinitionModel).where(
                            ReportDefinitionModel.owner_id == authorization.owner_id,
                            ReportDefinitionModel.content_digest == definition_digest,
                        )
                    )
                    if definition is None:
                        definition = ReportDefinitionModel(
                            id=uuid4(),
                            owner_id=authorization.owner_id,
                            account_id=authorization.account_id,
                            created_at=at,
                            report_type=selection.report_type.value,
                            period_rule=selection.report_type.value
                            if selection.report_type.value in {"monthly", "quarterly", "annual"}
                            else "explicit",
                            sections=[x.value for x in selection.sections],
                            template_version=selection.template_version,
                            reporting_currency=selection.reporting_currency.value,
                            revision=1,
                            content_digest=definition_digest,
                        )
                        session.add(definition)
                        session.flush()
                    job = ReportJobModel(
                        **common,
                        contract_version=self._contract_version,
                        definition_id=definition.id,
                        report_type=selection.report_type.value,
                        formats=[x.value for x in selection.formats],
                    )
                    outbox_model = ReportDispatchOutboxModel
                else:
                    job = ExportJobModel(
                        **common,
                        dataset=selection.dataset.value,
                        field_set=selection.field_set.value,
                        format=selection.format.value,
                    )
                    outbox_model = ExportDispatchOutboxModel
                session.add(job)
                session.flush()
                session.add(
                    ApplicationCommandIdentityModel(
                        id=uuid4(),
                        owner_id=authorization.owner_id,
                        account_id=authorization.account_id,
                        created_at=at,
                        command=command_name,
                        idempotency_key=command.idempotency_key,
                        command_digest=digest,
                        report_job_id=job.id if isinstance(job, ReportJobModel) else None,
                        export_job_id=job.id if isinstance(job, ExportJobModel) else None,
                    )
                )
                session.add(
                    outbox_model(
                        id=uuid4(),
                        owner_id=authorization.owner_id,
                        created_at=at,
                        job_id=job.id,
                        task_name=task,
                        schema_version="1.0.0",
                        state="pending",
                        publication_attempts=0,
                        available_at=at,
                        claim_token=None,
                        claim_expires_at=None,
                        dispatcher_id=None,
                        failure_code=None,
                        published_at=None,
                    )
                )
                session.flush()
                self._sources(session, authorization, job)
                audit_report_job(session, job, event="created", at=at)
                return self._status(session, authorization, job)

        return await self._run(execute)

    def _find(
        self,
        session: Session,
        authorization: ReportAuthorization,
        kind: Literal["report", "export"],
        identifier: UUID,
    ) -> StoredJob:
        model: type[ReportJobModel] | type[ExportJobModel] = (
            ReportJobModel if kind == "report" else ExportJobModel
        )
        row = session.scalar(
            select(model)
            .where(
                model.owner_id == authorization.owner_id,
                model.account_id == authorization.account_id,
                model.id == identifier,
            )
            .execution_options(populate_existing=True)
        )
        if (
            row is None
            or (isinstance(row, ReportJobModel) and row.contract_version != self._contract_version)
            or (kind == "export" and self._contract_version != 1)
        ):
            raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
        return cast(StoredJob, row)

    async def _with_job[T](
        self,
        principal: Principal,
        account_id: UUID,
        kind: Literal["report", "export"],
        identifier: UUID,
        operation: Callable[[Session, ReportAuthorization, StoredJob], T],
        *,
        detail: bool = False,
    ) -> T:
        def execute() -> T:
            with self._sessions() as session, session.begin():
                authorization = authorize_report_request(
                    session,
                    principal,
                    account_id=account_id,
                    required_scopes=report_scopes(),
                    now=self._now(),
                )
                report_owner_lock(session, authorization.owner_id)
                job = self._find(session, authorization, kind, identifier)
                if detail:
                    authorization = authorize_report_request(
                        session,
                        principal,
                        account_id=account_id,
                        required_scopes=job_scopes(session, job, detail=True),
                        now=self._now(),
                    )
                result = operation(session, authorization, job)
                authorization.check(session, now=self._now())
                return result

        return await self._run(execute)

    async def get_report_status(
        self, principal: Principal, account_id: UUID, job_id: UUID
    ) -> app.ReportJobStatus:
        return cast(
            app.ReportJobStatus,
            await self._with_job(principal, account_id, "report", job_id, self._status),
        )

    async def get_export_status(
        self, principal: Principal, account_id: UUID, export_id: UUID
    ) -> app.ExportJobStatus:
        return cast(
            app.ExportJobStatus,
            await self._with_job(principal, account_id, "export", export_id, self._status),
        )

    async def get_report_manifest(
        self, principal: Principal, account_id: UUID, report_id: UUID
    ) -> ReportManifestContract:
        def read(
            session: Session, authorization: ReportAuthorization, job: StoredJob
        ) -> ReportManifestContract:
            self._sources(session, authorization, job)
            if job.state != "succeeded":
                raise report_error(app.ReportServiceErrorCode.INVALID_STATE_TRANSITION)
            payload = session.scalar(
                select(ReportInputSnapshotModel.canonical_manifest).where(
                    ReportInputSnapshotModel.id == job.input_id,
                    ReportInputSnapshotModel.owner_id == job.owner_id,
                )
            )
            if payload is None or hashlib.sha256(payload).hexdigest() != job.manifest_digest:
                raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
            result = self._decode_manifest(job, payload)
            self._manifest_contract(job, result)
            self._sources(session, authorization, job)
            return result

        return await self._with_job(principal, account_id, "report", report_id, read, detail=True)

    async def list_reports(
        self, principal: Principal, account_id: UUID, *, query: app.ReportListQuery
    ) -> Page[app.ReportJobStatus]:
        return cast(Page[app.ReportJobStatus], await self._list(principal, account_id, query))

    async def list_exports(
        self, principal: Principal, account_id: UUID, *, query: app.ExportListQuery
    ) -> Page[app.ExportJobStatus]:
        return cast(Page[app.ExportJobStatus], await self._list(principal, account_id, query))

    async def _list(
        self,
        principal: Principal,
        account_id: UUID,
        query: app.ReportListQuery | app.ExportListQuery,
    ) -> Page[app.ReportJobStatus | app.ExportJobStatus]:
        def execute() -> Page[app.ReportJobStatus | app.ExportJobStatus]:
            with self._sessions() as session, session.begin():
                authorization = authorize_report_request(
                    session,
                    principal,
                    account_id=account_id,
                    required_scopes=report_scopes(),
                    now=self._now(),
                )
                report_owner_lock(session, authorization.owner_id)
                is_report = isinstance(query, app.ReportListQuery)
                model: type[ReportJobModel] | type[ExportJobModel] = (
                    ReportJobModel if is_report else ExportJobModel
                )
                fingerprint = collection_filter_fingerprint(
                    query.state.value if query.state else None,
                    query.report_type.value
                    if isinstance(query, app.ReportListQuery) and query.report_type
                    else None,
                    query.start_date.isoformat()
                    if isinstance(query, app.ReportListQuery) and query.start_date
                    else None,
                    query.end_date.isoformat()
                    if isinstance(query, app.ReportListQuery) and query.end_date
                    else None,
                    query.dataset.value
                    if isinstance(query, app.ExportListQuery) and query.dataset
                    else None,
                )
                if is_report and self._contract_version in (2, 3, 4):
                    fingerprint = collection_filter_fingerprint(
                        f"premium_reports_v{self._contract_version}", fingerprint
                    )
                if not is_report and self._contract_version != 1:
                    raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
                definition = CollectionSnapshotDefinition(
                    resource=(
                        CollectionSnapshotResource.PREMIUM_REPORTS
                        if self._contract_version in (2, 3, 4)
                        else CollectionSnapshotResource.REPORTS
                    )
                    if is_report
                    else CollectionSnapshotResource.EXPORTS,
                    owner_id=authorization.owner_id,
                    broker_account_id=account_id,
                    filter_fingerprint=fingerprint,
                )
                collections = CollectionSnapshotStore(
                    session,
                    cursor_codec=self._cursors,
                    ttl_seconds=self._cursor_ttl,
                    max_active_snapshots_per_owner=self._max_collections,
                    max_active_members_per_owner=self._max_members,
                )
                if query.cursor is not None:
                    page = collections.resume(definition, query.cursor, limit=query.limit)
                else:
                    statement = select(model.id).where(
                        model.owner_id == authorization.owner_id, model.account_id == account_id
                    )
                    if is_report:
                        statement = statement.where(
                            ReportJobModel.contract_version == self._contract_version
                        )
                    if query.state is not None:
                        if query.state.value == "expired":
                            statement = statement.where(
                                (model.state == "expired") | (model.expires_at <= self._now())
                            )
                        else:
                            statement = statement.where(
                                model.state == query.state.value, model.expires_at > self._now()
                            )
                    if isinstance(query, app.ReportListQuery):
                        if query.report_type is not None:
                            statement = statement.where(
                                ReportJobModel.report_type == query.report_type.value
                            )
                        if query.start_date is not None:
                            statement = statement.join(
                                ReportInputSnapshotModel,
                                ReportInputSnapshotModel.id == model.input_id,
                            ).where(
                                ReportInputSnapshotModel.start_date >= query.start_date,
                                ReportInputSnapshotModel.end_date <= query.end_date,
                            )
                    elif query.dataset is not None:
                        statement = statement.where(ExportJobModel.dataset == query.dataset.value)
                    statement = statement.order_by(
                        model.requested_at.desc(), model.id.desc()
                    ).limit(self._max_members + 1)
                    page = collections.materialize(
                        definition, lambda: session.scalars(statement), limit=query.limit
                    )
                row_statement = select(model).where(
                    model.owner_id == authorization.owner_id,
                    model.account_id == account_id,
                    model.id.in_(page.record_ids),
                )
                if is_report:
                    row_statement = row_statement.where(
                        ReportJobModel.contract_version == self._contract_version
                    )
                rows = tuple(session.scalars(row_statement))
                by_id = {row.id: cast(StoredJob, row) for row in rows}
                if len(by_id) != len(page.record_ids):
                    raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
                items = tuple(
                    self._status(session, authorization, by_id[identifier])
                    for identifier in page.record_ids
                )
                return Page(
                    items=items,
                    next_cursor=page.next_cursor,
                    limit=page.limit,
                    total=page.exact_total,
                )

        try:
            return await self._run(execute)
        except CursorValidationError:
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED) from None
        except CollectionSnapshotCapacityError:
            raise report_error(app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED) from None

    async def create_report_download_grant(
        self, principal: Principal, account_id: UUID, report_id: UUID, artifact_id: UUID
    ) -> app.ArtifactGrant:
        from .report_downloads import create_grant

        return await self._with_job(
            principal,
            account_id,
            "report",
            report_id,
            lambda session, authorization, job: create_grant(
                self, session, authorization, job, artifact_id
            ),
            detail=True,
        )

    async def create_export_download_grant(
        self, principal: Principal, account_id: UUID, export_id: UUID, artifact_id: UUID
    ) -> app.ArtifactGrant:
        from .report_downloads import create_grant

        return await self._with_job(
            principal,
            account_id,
            "export",
            export_id,
            lambda session, authorization, job: create_grant(
                self, session, authorization, job, artifact_id
            ),
            detail=True,
        )

    async def download_report_artifact(
        self,
        principal: Principal,
        account_id: UUID,
        report_id: UUID,
        artifact_id: UUID,
        *,
        grant_token: str,
    ) -> app.ReportArtifactDownload:
        from .report_downloads import download_artifact

        return await self._with_job(
            principal,
            account_id,
            "report",
            report_id,
            lambda session, authorization, job: download_artifact(
                self, session, authorization, job, artifact_id, grant_token
            ),
            detail=True,
        )

    async def download_export_artifact(
        self,
        principal: Principal,
        account_id: UUID,
        export_id: UUID,
        artifact_id: UUID,
        *,
        grant_token: str,
    ) -> app.ReportArtifactDownload:
        from .report_downloads import download_artifact

        return await self._with_job(
            principal,
            account_id,
            "export",
            export_id,
            lambda session, authorization, job: download_artifact(
                self, session, authorization, job, artifact_id, grant_token
            ),
            detail=True,
        )
