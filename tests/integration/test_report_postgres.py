"""Real canonical capture, private storage and durable report boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from trading212_application import report_jobs as jobs
from trading212_application import reports as app
from trading212_domain import CurrencyCode
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.report_manifest import decode_report_manifest
from trading212_domain.reports import (
    ExportDataset,
    ExportFieldSet,
    ExportFormat,
    ExportSelection,
    ReportFailureCode,
    ReportFormat,
    ReportJobState,
    ReportProof,
    ReportSection,
    ReportSelection,
    ReportSourceKind,
    ReportSourceReference,
    ReportSourceUse,
    ReportType,
)
from trading212_domain.sources import LicensePermission
from trading212_persistence.models import AuditEventModel, PrincipalModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.report_base import report_owner_lock, selection_scopes
from trading212_persistence.report_input_store import ReportInputSink
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    ArtifactDownloadGrantModel,
    ExportJobModel,
    ReportArtifactModel,
    ReportDispatchOutboxModel,
    ReportInputChunkModel,
    ReportInputDependencyModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportManifestModel,
    ReportRetentionWorkModel,
)
from trading212_persistence.report_retention import expire_report_payloads, purge_report_input
from trading212_persistence.report_service import PostgresReportService
from trading212_persistence.report_sources import project_report_dependencies
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_retention_service import expire_source_payloads
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_enrichment_retention import expire_enrichment_payloads
from trading212_security.principals import AuthorizationError, Principal, Scope
from trading212_worker.report_renderers import PrivateReportRenderer
from trading212_worker.report_tasks import (
    ReportExecutionState,
    execute_export_message,
    execute_report_message,
)
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID
from trading212_worker.xray_seed import XRAY_CURSOR_KEY
from trading212_worker.xray_source_fixture import xray_license

from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


@dataclass
class ReportCase:
    base: XrayReadCase
    service: PostgresReportService
    jobs: PostgresReportJobStore

    @property
    def principal(self) -> Principal:
        return self.base.principal

    @property
    def account_id(self) -> UUID:
        return UUID(XRAY_ACCOUNT_ID)

    def selection(
        self, *, xray: bool = False, formats: tuple[ReportFormat, ...] = (ReportFormat.JSON,)
    ) -> ReportSelection:
        cutoff = datetime.fromisoformat(self.base.seed["source_cutoff_at"])
        return ReportSelection(
            account_id=self.account_id,
            start_date=cutoff.date(),
            end_date=cutoff.date(),
            source_cutoff_at=cutoff,
            snapshot_id=UUID(self.base.seed["snapshot_id"]),
            reporting_currency=CurrencyCode("EUR"),
            report_type=ReportType.PORTFOLIO_XRAY if xray else ReportType.PORTFOLIO_SUMMARY,
            sections=(
                ReportSection.OVERVIEW,
                ReportSection.XRAY if xray else ReportSection.ALLOCATION,
                ReportSection.QUALITY,
            ),
            formats=formats,
        )


@pytest.fixture
def report_case(xray_read_case: XrayReadCase) -> ReportCase:
    case = xray_read_case
    with case.sessions() as session, session.begin():
        provision_principal_scopes(
            session,
            principal_id=UUID(case.principal.principal_id),
            scopes=frozenset(Scope),
            now=datetime.now(UTC) - timedelta(seconds=1),
        )
    return ReportCase(
        case,
        PostgresReportService(case.sessions, cursor_signing_key=XRAY_CURSOR_KEY),
        PostgresReportJobStore(case.sessions),
    )


async def generate(
    case: ReportCase,
    *,
    xray: bool = False,
    key: str | None = None,
    formats: tuple[ReportFormat, ...] = (ReportFormat.JSON,),
) -> app.ReportJobStatus:
    return await case.service.generate_report(
        case.principal,
        app.GenerateReportCommand(
            selection=case.selection(xray=xray, formats=formats),
            idempotency_key=key or str(uuid4()),
        ),
    )


async def finish(case: ReportCase, job: app.ReportJobStatus) -> app.ReportJobStatus:
    assert job.context is not None
    with case.base.sessions() as session:
        row = session.get(ReportJobModel, job.job_id)
        assert row is not None
        message = jobs.ReportTaskMessage(
            job_id=row.id,
            owner_id=row.owner_id,
            account_id=row.account_id,
            capture_id=row.input_id,
            input_digest=row.input_digest,
        )
    state = await execute_report_message(case.jobs, message, consumer_id="report-test")
    status = await case.service.get_report_status(case.principal, case.account_id, job.job_id)
    assert state is ReportExecutionState.COMPLETED, (
        f"Report worker returned {state.value}; failure code: {status.failure_code}"
    )
    return status


def test_canonical_report_survives_new_service_and_private_download(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        pending = await generate(case)
        assert pending.state is ReportJobState.QUEUED and pending.context is not None
        status = await finish(case, pending)
        assert status.state is ReportJobState.SUCCEEDED and len(status.artifacts) == 1
        fresh = PostgresReportService(case.base.sessions, cursor_signing_key=XRAY_CURSOR_KEY)
        manifest = await fresh.get_report_manifest(case.principal, case.account_id, status.job_id)
        assert manifest.document.selection.snapshot_id == UUID(case.base.seed["snapshot_id"])
        grant = await fresh.create_report_download_grant(
            case.principal, case.account_id, status.job_id, status.artifacts[0].artifact_id
        )
        result = await fresh.download_report_artifact(
            case.principal,
            case.account_id,
            status.job_id,
            status.artifacts[0].artifact_id,
            grant_token=grant.token,
        )
        assert hashlib.sha256(result.content).hexdigest() == result.metadata.content_digest
        decoded = json.loads(result.content)
        assert decoded and b"1000" in result.content
        assert grant.token.encode() not in result.content and grant.token not in repr(grant)
        repeat = await fresh.download_report_artifact(
            case.principal,
            case.account_id,
            status.job_id,
            status.artifacts[0].artifact_id,
            grant_token=grant.token,
        )
        assert repeat.content == result.content
        with case.base.sessions() as session:
            row = session.get(ReportJobModel, status.job_id)
            assert row is not None
            message = jobs.ReportTaskMessage(
                job_id=row.id,
                owner_id=row.owner_id,
                account_id=row.account_id,
                capture_id=row.input_id,
                input_digest=row.input_digest,
            )
        assert (
            await execute_report_message(case.jobs, message, consumer_id="duplicate-report")
            is ReportExecutionState.NOT_CLAIMED
        )
        with case.base.sessions() as session:
            events = tuple(
                session.scalars(
                    select(AuditEventModel)
                    .where(AuditEventModel.resource_id == str(status.job_id))
                    .order_by(AuditEventModel.occurred_at)
                )
            )
            assert [event.action for event in events] == [
                "report.job.created",
                "report.job.completed",
            ]
            assert all(
                event.outcome == "succeeded"
                and event.principal_id == UUID(case.principal.principal_id)
                and event.broker_account_id == case.account_id
                and event.safe_metadata is None
                for event in events
            )

    asyncio.run(run())


def test_idempotency_preserves_pins_and_rejects_semantic_change(report_case: ReportCase) -> None:
    async def run() -> None:
        case = report_case
        command = app.GenerateReportCommand(selection=case.selection(), idempotency_key="same-pins")
        first = await case.service.generate_report(case.principal, command)
        assert await case.service.generate_report(case.principal, command) == first
        with pytest.raises(app.ReportServiceError) as error:
            await case.service.generate_report(case.principal, replace(command, ttl_days=8))
        assert error.value.code is app.ReportServiceErrorCode.CONFLICT
        with case.base.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ReportInputSnapshotModel)) == 1
            assert session.scalar(select(func.count()).select_from(ReportDispatchOutboxModel)) == 1
            assert (
                session.scalar(select(func.count()).select_from(ApplicationCommandIdentityModel))
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(
                        AuditEventModel.resource_id == str(first.job_id),
                        AuditEventModel.action == "report.job.created",
                    )
                )
                == 1
            )

    asyncio.run(run())


def test_missing_durable_grants_rejects_before_capture(report_case: ReportCase) -> None:
    case = report_case
    with case.base.sessions() as session, session.begin():
        provision_principal_scopes(
            session,
            principal_id=UUID(case.principal.principal_id),
            scopes=frozenset({Scope.PORTFOLIO_READ}),
            now=datetime.now(UTC),
        )
    with pytest.raises(app.ReportServiceError) as error:
        asyncio.run(generate(case))
    assert error.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
    with case.base.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ReportInputSnapshotModel)) == 0


def test_capture_cannot_commit_unsealed(report_case: ReportCase) -> None:
    case = report_case
    selection = case.selection()
    with pytest.raises(DBAPIError), case.base.sessions() as session, session.begin():
        auth = authorize_report_request(
            session,
            case.principal,
            account_id=case.account_id,
            required_scopes=selection_scopes(selection),
            now=datetime.now(UTC),
        )
        report_owner_lock(session, auth.owner_id)
        ReportInputSink(
            session,
            auth,
            selection=selection,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            clock=lambda: datetime.now(UTC),
        )


def test_disabled_initiator_is_rejected_on_worker_claim(report_case: ReportCase) -> None:
    async def run() -> None:
        case = report_case
        job = await generate(case)
        with case.base.sessions() as session, session.begin():
            row = session.get(ReportJobModel, job.job_id)
            assert row is not None
            message = jobs.ReportTaskMessage(
                job_id=row.id,
                owner_id=row.owner_id,
                account_id=row.account_id,
                capture_id=row.input_id,
                input_digest=row.input_digest,
            )
            session.execute(
                update(PrincipalModel)
                .where(PrincipalModel.id == row.principal_id)
                .values(status="disabled")
            )
        assert await case.jobs.claim_report_job(message, consumer_id="report-disabled") is None
        assert (
            await case.jobs.claim_report_job(message, consumer_id="report-disabled-repeat") is None
        )
        with case.base.sessions() as session:
            stored = session.get(ReportJobModel, job.job_id)
            assert (
                stored is not None
                and stored.state == "failed"
                and stored.failure_code == "access_denied"
            )
            events = tuple(
                session.scalars(
                    select(AuditEventModel)
                    .where(AuditEventModel.resource_id == str(job.job_id))
                    .order_by(AuditEventModel.occurred_at)
                )
            )
            assert [event.action for event in events] == ["report.job.created", "report.job.failed"]
            assert events[1].outcome == "failed"
            assert events[1].safe_metadata == {"failure_code": "access_denied"}

    asyncio.run(run())


def test_worker_reclaim_increments_fence_and_old_claim_cannot_publish(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        pending = await generate(case)
        with case.base.sessions() as session:
            row = session.get(ReportJobModel, pending.job_id)
            assert row is not None
            message = jobs.ReportTaskMessage(
                job_id=row.id,
                owner_id=row.owner_id,
                account_id=row.account_id,
                capture_id=row.input_id,
                input_digest=row.input_digest,
            )
        first = await case.jobs.claim_report_job(message, consumer_id="first")
        assert first is not None
        assert await case.jobs.claim_report_job(message, consumer_id="duplicate") is None
        with case.base.sessions() as session, session.begin():
            session.execute(
                update(ReportJobModel)
                .where(ReportJobModel.id == pending.job_id)
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        second = await case.jobs.claim_report_job(message, consumer_id="recovered")
        assert (
            second is not None
            and second.fence == first.fence + 1
            and second.lease_id != first.lease_id
        )
        assert not await case.jobs.heartbeat_report_job(first)
        assert not await case.jobs.fail_report_job(
            first, failure=ReportFailureCode.RENDER_FAILED, retryable=False
        )
        assert await case.jobs.heartbeat_report_job(second)

    asyncio.run(run())


@pytest.mark.parametrize("permission", ["store", "display", "report"])
@pytest.mark.parametrize("decision", [LicensePermission.DENIED, LicensePermission.UNKNOWN])
def test_current_source_permission_denies_before_payload_read(
    report_case: ReportCase, permission: str, decision: LicensePermission
) -> None:
    async def run() -> None:
        case = report_case
        status = await finish(case, await generate(case, xray=True))
        grant = await case.service.create_report_download_grant(
            case.principal, case.account_id, status.job_id, status.artifacts[0].artifact_id
        )
        source = PostgresSourceService(
            sessions=case.base.sessions, cursor_signing_key=XRAY_CURSOR_KEY
        )
        key = str(uuid4())
        await source.register_source_license(
            case.principal,
            replace(
                xray_license(),
                id=key,
                version=key,
                effective_at=datetime.now(UTC),
                store=decision if permission == "store" else LicensePermission.ALLOWED,
                display=decision if permission == "display" else LicensePermission.ALLOWED,
                report=decision if permission == "report" else LicensePermission.ALLOWED,
            ),
            idempotency_key=key,
            correlation_id="report-permission",
        )
        selects: list[str] = []

        def observe(
            _conn: object,
            _cursor: object,
            statement: str,
            _params: object,
            _context: object,
            _many: object,
        ) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(case.base.engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(app.ReportServiceError) as error:
                await case.service.download_report_artifact(
                    case.principal,
                    case.account_id,
                    status.job_id,
                    status.artifacts[0].artifact_id,
                    grant_token=grant.token,
                )
            assert error.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
            assert not any("SELECT report_artifacts.contents" in statement for statement in selects)
        finally:
            event.remove(case.base.engine, "before_cursor_execute", observe)

    asyncio.run(run())


def test_artifact_grants_are_supplemental_bounded_and_immutable(report_case: ReportCase) -> None:
    async def run() -> None:
        case = report_case
        pending = await generate(case)
        with pytest.raises(app.ReportServiceError) as unready_manifest:
            await case.service.get_report_manifest(case.principal, case.account_id, pending.job_id)
        assert unready_manifest.value.code is app.ReportServiceErrorCode.INVALID_STATE_TRANSITION
        assert not unready_manifest.value.retryable
        with pytest.raises(app.ReportServiceError) as unready_artifact:
            await case.service.create_report_download_grant(
                case.principal, case.account_id, pending.job_id, uuid4()
            )
        assert unready_artifact.value.code is app.ReportServiceErrorCode.INVALID_STATE_TRANSITION
        assert not unready_artifact.value.retryable
        status = await finish(case, pending)
        identifier = status.artifacts[0].artifact_id
        grants = [
            await case.service.create_report_download_grant(
                case.principal, case.account_id, status.job_id, identifier
            )
            for _ in range(10)
        ]
        assert len({g.token for g in grants}) == 10
        with pytest.raises(app.ReportServiceError) as rate_limited:
            await case.service.create_report_download_grant(
                case.principal, case.account_id, status.job_id, identifier
            )
        assert rate_limited.value.code is app.ReportServiceErrorCode.RATE_LIMITED
        assert rate_limited.value.retryable
        with pytest.raises(app.ReportServiceError):
            await case.service.download_report_artifact(
                case.principal, case.account_id, status.job_id, identifier, grant_token="x" * 43
            )
        with pytest.raises(DBAPIError), case.base.sessions() as session, session.begin():
            session.execute(
                update(ReportArtifactModel)
                .where(ReportArtifactModel.id == identifier)
                .values(contents=b"changed")
            )
        with pytest.raises(DBAPIError), case.base.sessions() as session, session.begin():
            session.execute(
                update(ReportManifestModel)
                .where(ReportManifestModel.job_id == status.job_id)
                .values(payload=b"changed")
            )

    asyncio.run(run())


def test_expiry_purges_all_copies_with_shared_budget_and_keeps_safe_tombstones(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        status = await finish(case, await generate(case))
        await case.service.create_report_download_grant(
            case.principal, case.account_id, status.job_id, status.artifacts[0].artifact_id
        )
        with case.base.sessions() as session, session.begin():
            job = session.get(ReportJobModel, status.job_id)
            assert job is not None
            # Owner termination is a real retention cause, not an invented app clock.
            session.execute(
                text("UPDATE broker_accounts SET status='inactive' WHERE id=:id"),
                {"id": case.account_id},
            )
            small = SourcePurgeBudget(
                rows_inspected=4, rows_removed=1, bytes_inspected=1024, bytes_removed=1024
            )
            report_owner_lock(session, job.owner_id)
            assert not purge_report_input(
                session,
                owner=job.owner_id,
                input_id=job.input_id,
                reason="owner",
                at=datetime.now(UTC),
                budget=small,
            )
        for _ in range(10):
            with case.base.sessions() as session, session.begin():
                job = session.get(ReportJobModel, status.job_id)
                assert job is not None
                report_owner_lock(session, job.owner_id)
                budget = SourcePurgeBudget()
                complete = purge_report_input(
                    session,
                    owner=job.owner_id,
                    input_id=job.input_id,
                    reason="owner",
                    at=datetime.now(UTC),
                    budget=budget,
                )
            if complete:
                break
        assert complete
        with case.base.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ArtifactDownloadGrantModel)) == 0
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportInputChunkModel)
                    .where(ReportInputChunkModel.payload.is_not(None))
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportArtifactModel)
                    .where(ReportArtifactModel.contents.is_not(None))
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportRetentionWorkModel)
                    .where(ReportRetentionWorkModel.completed_at.is_not(None))
                )
                == 1
            )
            row = session.get(ReportJobModel, status.job_id)
            assert (
                row is not None
                and row.state == "expired"
                and row.manifest_digest == status.manifest_digest
            )

    asyncio.run(run())


def test_standalone_export_is_a_real_durable_job_and_alerts_is_rejected(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        request = case.selection()
        selection = ExportSelection(
            account_id=request.account_id,
            start_date=request.start_date,
            end_date=request.end_date,
            source_cutoff_at=request.source_cutoff_at,
            snapshot_id=request.snapshot_id,
            reporting_currency=request.reporting_currency,
            dataset=ExportDataset.POSITIONS,
            field_set=ExportFieldSet.AUDIT,
            format=ExportFormat.CSV,
        )
        status = await case.service.create_export(
            case.principal,
            app.CreateExportCommand(selection=selection, idempotency_key="export-real"),
        )
        with case.base.sessions() as session:
            row = session.get(ExportJobModel, status.export_id)
            assert row is not None
            message = jobs.ExportTaskMessage(
                job_id=row.id,
                owner_id=row.owner_id,
                account_id=row.account_id,
                capture_id=row.input_id,
                input_digest=row.input_digest,
            )
        assert (
            await execute_export_message(case.jobs, message, consumer_id="export-test")
            is ReportExecutionState.COMPLETED
        )
        result = await case.service.get_export_status(
            case.principal, case.account_id, status.export_id
        )
        assert result.state is ReportJobState.SUCCEEDED and len(result.artifacts) == 1
        with pytest.raises(DomainError) as error:
            replace(selection, dataset=ExportDataset.ALERTS, target_version_id=uuid4())
        assert error.value.code is ErrorCode.VALIDATION_FAILED
        with case.base.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ExportJobModel)) == 1
            assert tuple(
                session.scalars(
                    select(AuditEventModel.action)
                    .where(AuditEventModel.resource_id == str(status.export_id))
                    .order_by(AuditEventModel.occurred_at)
                )
            ) == ("export.job.created", "export.job.completed")

    asyncio.run(run())


def test_partial_manifest_and_heartbeat_fence_changes_cannot_commit(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        pending = await generate(case, formats=(ReportFormat.JSON, ReportFormat.CSV))
        with case.base.sessions() as session:
            job = session.get(ReportJobModel, pending.job_id)
            assert job is not None
            message = jobs.ReportTaskMessage(
                job_id=job.id,
                owner_id=job.owner_id,
                account_id=job.account_id,
                capture_id=job.input_id,
                input_digest=job.input_digest,
            )
        claim = await case.jobs.claim_report_job(message, consumer_id="partial-publication")
        assert claim is not None
        with (
            pytest.raises(DBAPIError, match="successful job"),
            case.base.sessions() as session,
            session.begin(),
        ):
            capture = session.get(ReportInputSnapshotModel, message.capture_id)
            assert capture is not None and capture.canonical_manifest is not None
            payload = capture.canonical_manifest
            session.add(
                ReportManifestModel(
                    id=uuid4(),
                    owner_id=message.owner_id,
                    job_id=message.job_id,
                    input_id=message.capture_id,
                    created_at=datetime.now(UTC),
                    content_digest=hashlib.sha256(payload).hexdigest(),
                    byte_length=len(payload),
                    publication_fence=claim.fence,
                    payload=payload,
                    purged_at=None,
                )
            )
            session.flush()
        with (
            pytest.raises(DBAPIError, match="heartbeat cannot change"),
            case.base.sessions() as session,
            session.begin(),
        ):
            session.execute(
                update(ReportJobModel)
                .where(ReportJobModel.id == message.job_id)
                .values(fence=claim.fence + 1)
            )
        with case.base.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ReportManifestModel)) == 0
            assert session.scalar(select(func.count()).select_from(ReportArtifactModel)) == 0

    asyncio.run(run())


def test_future_effective_license_denial_after_render_prevents_publication(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        at = [datetime.now(UTC)]
        case.service = PostgresReportService(
            case.base.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: at[0]
        )
        case.jobs = PostgresReportJobStore(case.base.sessions, clock=lambda: at[0])
        pending = await generate(case, xray=True)
        boundary = at[0] + timedelta(seconds=5)
        source = PostgresSourceService(
            sessions=case.base.sessions, cursor_signing_key=XRAY_CURSOR_KEY
        )
        identifier = str(uuid4())
        await source.register_source_license(
            case.principal,
            replace(
                xray_license(),
                id=identifier,
                version=identifier,
                effective_at=boundary,
                report=LicensePermission.DENIED,
            ),
            idempotency_key=identifier,
            correlation_id="report-final-seal",
        )
        with case.base.sessions() as session:
            job = session.get(ReportJobModel, pending.job_id)
            assert job is not None
            message = jobs.ReportTaskMessage(
                job_id=job.id,
                owner_id=job.owner_id,
                account_id=job.account_id,
                capture_id=job.input_id,
                input_digest=job.input_digest,
            )
        claim = await case.jobs.claim_report_job(message, consumer_id="future-license")
        assert claim is not None
        import threading

        from trading212_worker.report_tasks import _render

        manifest, artifacts = await asyncio.to_thread(
            _render, case.jobs, claim, threading.Event(), PrivateReportRenderer()
        )
        assert artifacts
        at[0] = boundary + timedelta(microseconds=1)
        with pytest.raises(jobs.ReportJobInputError) as error:
            await case.jobs.complete_report_job(claim, manifest=manifest, artifacts=artifacts)
        assert error.value.code in {
            ReportFailureCode.ACCESS_DENIED,
            ReportFailureCode.SOURCE_RESTRICTED,
        }
        with case.base.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ReportManifestModel)) == 0
            assert session.scalar(select(func.count()).select_from(ReportArtifactModel)) == 0

    asyncio.run(run())


@pytest.mark.parametrize("decision", [LicensePermission.DENIED, LicensePermission.UNKNOWN])
def test_export_permission_is_rechecked_for_the_actual_xray_sources(
    report_case: ReportCase,
    decision: LicensePermission,
) -> None:
    async def run() -> None:
        case = report_case
        request = case.selection()
        selection = ExportSelection(
            account_id=request.account_id,
            start_date=request.start_date,
            end_date=request.end_date,
            source_cutoff_at=request.source_cutoff_at,
            snapshot_id=request.snapshot_id,
            reporting_currency=request.reporting_currency,
            dataset=ExportDataset.XRAY,
            field_set=ExportFieldSet.AUDIT,
            format=ExportFormat.JSON,
        )
        pending = await case.service.create_export(
            case.principal,
            app.CreateExportCommand(selection=selection, idempotency_key="licensed-export"),
        )
        with case.base.sessions() as session:
            job = session.get(ExportJobModel, pending.export_id)
            assert job is not None
            message = jobs.ExportTaskMessage(
                job_id=job.id,
                owner_id=job.owner_id,
                account_id=job.account_id,
                capture_id=job.input_id,
                input_digest=job.input_digest,
            )
        assert (
            await execute_export_message(case.jobs, message, consumer_id="export-permission")
            is ReportExecutionState.COMPLETED
        )
        status = await case.service.get_export_status(
            case.principal, case.account_id, pending.export_id
        )
        grant = await case.service.create_export_download_grant(
            case.principal, case.account_id, status.export_id, status.artifacts[0].artifact_id
        )
        source = PostgresSourceService(
            sessions=case.base.sessions, cursor_signing_key=XRAY_CURSOR_KEY
        )
        identifier = str(uuid4())
        await source.register_source_license(
            case.principal,
            replace(
                xray_license(),
                id=identifier,
                version=identifier,
                effective_at=datetime.now(UTC),
                export=decision,
            ),
            idempotency_key=identifier,
            correlation_id="export-current-license",
        )
        with pytest.raises(app.ReportServiceError) as error:
            await case.service.download_export_artifact(
                case.principal,
                case.account_id,
                status.export_id,
                status.artifacts[0].artifact_id,
                grant_token=grant.token,
            )
        assert error.value.code is app.ReportServiceErrorCode.ACCESS_DENIED

    asyncio.run(run())


def test_current_reader_is_independent_of_the_disabled_job_initiator(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        status = await finish(case, await generate(case))
        now = datetime.now(UTC)
        identifier = uuid4()
        scopes = frozenset({Scope.PORTFOLIO_READ, Scope.REPORTS_READ, Scope.ANALYTICS_READ})
        reader = replace(
            case.principal,
            principal_id=str(identifier),
            subject="independent-report-reader",
            scopes=scopes,
            authenticated_at=now,
            expires_at=now + timedelta(hours=1),
        )
        with case.base.sessions() as session, session.begin():
            session.add(
                PrincipalModel(
                    id=identifier,
                    owner_id=UUID(reader.owner_id),
                    issuer=reader.issuer,
                    subject=reader.subject,
                    status="active",
                    created_at=now,
                    last_authenticated_at=now,
                )
            )
            session.flush()
            provision_principal_scopes(session, principal_id=identifier, scopes=scopes, now=now)
            session.execute(
                update(PrincipalModel)
                .where(PrincipalModel.id == UUID(case.principal.principal_id))
                .values(status="disabled")
            )
        current = await case.service.get_report_status(reader, case.account_id, status.job_id)
        assert (
            current.manifest_digest == status.manifest_digest
            and current.state is ReportJobState.SUCCEEDED
        )
        grant = await case.service.create_report_download_grant(
            reader, case.account_id, status.job_id, status.artifacts[0].artifact_id
        )
        content = await case.service.download_report_artifact(
            reader,
            case.account_id,
            status.job_id,
            status.artifacts[0].artifact_id,
            grant_token=grant.token,
        )
        assert content.metadata.content_digest == status.artifacts[0].content_digest
        with pytest.raises(app.ReportServiceError):
            await case.service.download_report_artifact(
                case.principal,
                case.account_id,
                status.job_id,
                status.artifacts[0].artifact_id,
                grant_token=grant.token,
            )

    asyncio.run(run())


def test_report_history_cursor_keeps_stable_membership_and_rechecks_current_grants(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        first, second = await generate(case), await generate(case)
        page = await case.service.list_reports(
            case.principal, case.account_id, query=app.ReportListQuery(limit=1)
        )
        assert page.total == 2 and page.next_cursor is not None
        third = await generate(case)
        tail = await case.service.list_reports(
            case.principal,
            case.account_id,
            query=app.ReportListQuery(limit=1, cursor=page.next_cursor),
        )
        assert {page.items[0].job_id, tail.items[0].job_id} == {first.job_id, second.job_id}
        assert third.job_id not in {page.items[0].job_id, tail.items[0].job_id}
        with case.base.sessions() as session, session.begin():
            provision_principal_scopes(
                session,
                principal_id=UUID(case.principal.principal_id),
                scopes=frozenset({Scope.PORTFOLIO_READ}),
                now=datetime.now(UTC),
            )
        with pytest.raises(app.ReportServiceError) as error:
            await case.service.list_reports(
                case.principal,
                case.account_id,
                query=app.ReportListQuery(limit=1, cursor=page.next_cursor),
            )
        assert error.value.code is app.ReportServiceErrorCode.ACCESS_DENIED

    asyncio.run(run())


def test_actual_source_proof_rejects_missing_licenses_and_unbound_children(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        pending = await generate(case, xray=True)
        with case.base.sessions() as session:
            job = session.get(ReportJobModel, pending.job_id)
            assert job is not None
            capture = session.get(ReportInputSnapshotModel, job.input_id)
            assert capture is not None and capture.canonical_manifest is not None
            manifest = decode_report_manifest(capture.canonical_manifest)
            proof = ReportProof(
                **{field.name: getattr(manifest, field.name) for field in fields(ReportProof)}
            )
            input_id = capture.id
        child = next(
            ref
            for ref in proof.source_references
            if ref.kind is ReportSourceKind.ENTITY_EVIDENCE_REFERENCE
        )
        parent = next(
            ref
            for ref in proof.source_references
            if ref.subject_id == child.parent_id
            and ref.kind is ReportSourceKind.ENTITY_EVIDENCE_VERSION
        )

        def modified(reference: ReportSourceReference) -> ReportProof:
            return replace(
                proof,
                source_references=tuple(
                    reference if ref.key == reference.key else ref
                    for ref in proof.source_references
                ),
            )

        bad_proofs = (
            modified(replace(parent, provider_id=None, license_version_id=None)),
            modified(replace(child, provider_id=None, license_version_id=None)),
            modified(replace(child, parent_id=None)),
            modified(replace(child, parent_id=uuid4())),
            modified(replace(child, subject_id=uuid4())),
            modified(replace(parent, subject_id=uuid4())),
            replace(
                proof,
                source_references=tuple(
                    ref
                    for ref in proof.source_references
                    if not (ref.subject_id == parent.subject_id and ref.kind is parent.kind)
                ),
            ),
        )
        with case.base.sessions() as session, session.begin():
            authorization = authorize_report_request(
                session,
                case.principal,
                account_id=case.account_id,
                required_scopes=selection_scopes(case.selection(xray=True)),
                now=datetime.now(UTC),
            )
            report_owner_lock(session, authorization.owner_id)
            count_before = session.scalar(
                select(func.count()).select_from(ReportInputDependencyModel)
            )
            actual = project_report_dependencies(
                session,
                authorization,
                input_id=input_id,
                proof=proof,
                source_use=ReportSourceUse.REPORT,
                now=datetime.now(UTC),
            )
            assert any(row.source_id == parent.subject_id for row in actual)
            for bad in bad_proofs:
                with pytest.raises(AuthorizationError):
                    project_report_dependencies(
                        session,
                        authorization,
                        input_id=input_id,
                        proof=bad,
                        source_use=ReportSourceUse.REPORT,
                        now=datetime.now(UTC),
                    )
            assert (
                session.scalar(select(func.count()).select_from(ReportInputDependencyModel))
                == count_before
            )

    asyncio.run(run())


@pytest.mark.parametrize("family", ["source", "enrichment"])
def test_source_retention_removes_report_copies_before_source_completion(
    report_case: ReportCase,
    family: str,
) -> None:
    async def run() -> None:
        case = report_case
        status = await finish(case, await generate(case, xray=True))
        grant = await case.service.create_report_download_grant(
            case.principal, case.account_id, status.job_id, status.artifacts[0].artifact_id
        )
        with case.base.sessions() as session:
            job = session.get(ReportJobModel, status.job_id)
            assert job is not None
            input_id = job.input_id
            expiry = session.scalar(
                select(func.max(ReportInputDependencyModel.expires_at)).where(
                    ReportInputDependencyModel.input_id == input_id
                )
            )
            assert expiry is not None
        at = expiry + timedelta(seconds=1)
        expire = expire_source_payloads if family == "source" else expire_enrichment_payloads

        def report_copy_state() -> tuple[tuple[object, ...], ...]:
            # Independent byte fingerprints preserve missing versus empty copies
            # and avoid decoding or reflecting retained financial documents.
            values: list[tuple[object, ...]] = []
            with case.base.sessions() as session:
                header = session.get_one(ReportInputSnapshotModel, input_id)
                for name in ("canonical_manifest", "canonical_context"):
                    payload = getattr(header, name)
                    values.append(
                        (
                            "header",
                            name,
                            None if payload is None else len(payload),
                            None if payload is None else hashlib.sha256(payload).hexdigest(),
                            header.purged_at,
                        )
                    )
                for model, column, predicate in (
                    (
                        ReportInputChunkModel,
                        ReportInputChunkModel.payload,
                        ReportInputChunkModel.input_id == input_id,
                    ),
                    (
                        ReportArtifactModel,
                        ReportArtifactModel.contents,
                        ReportArtifactModel.job_id == status.job_id,
                    ),
                ):
                    for identifier, payload, purged_at in session.execute(
                        select(model.id, column, model.purged_at)
                        .where(predicate)
                        .order_by(model.id)
                    ):
                        values.append(
                            (
                                model.__tablename__,
                                str(identifier),
                                None if payload is None else len(payload),
                                None if payload is None else hashlib.sha256(payload).hexdigest(),
                                purged_at,
                            )
                        )
                for identifier, revoked_at, last_used_at in session.execute(
                    select(
                        ArtifactDownloadGrantModel.id,
                        ArtifactDownloadGrantModel.revoked_at,
                        ArtifactDownloadGrantModel.last_used_at,
                    )
                    .where(
                        ArtifactDownloadGrantModel.report_artifact_id
                        == status.artifacts[0].artifact_id
                    )
                    .order_by(ArtifactDownloadGrantModel.id)
                ):
                    values.append(("grant", str(identifier), revoked_at, last_used_at))
            return tuple(values)

        initial_copies = report_copy_state()
        retained_bytes = sum(
            value[2]
            for value in initial_copies
            if value[0] != "grant" and isinstance(value[2], int)
        )
        assert retained_bytes > 8192
        # Keep the original small-budget prefix: routing may either reach the
        # target marker or leave it pending before the report participant.
        for _ in range(128):
            with case.base.sessions() as session, session.begin():
                budget = SourcePurgeBudget(
                    rows_inspected=64, rows_removed=64, bytes_inspected=8192, bytes_removed=8192
                )
                expire(session, at=at, limit=1, budget=budget)
                pending = session.scalar(
                    select(ReportRetentionWorkModel.id).where(
                        ReportRetentionWorkModel.input_id == input_id,
                        ReportRetentionWorkModel.completed_at.is_(None),
                    )
                )
                assert 0 <= budget.rows_inspected <= 64 and 0 <= budget.rows_removed <= 64
                assert 0 <= budget.bytes_inspected <= 8192 and 0 <= budget.bytes_removed <= 8192
                assert 0 <= budget.captures <= 100 and 0 <= budget.runs <= 100
                assert 0 <= budget.artifacts <= 100
            if pending is not None:
                break
        if pending is None:
            # An undersized route may advance operational source/sweep metadata,
            # but it must preserve every target report copy and grant.
            assert report_copy_state() == initial_copies
            with case.base.sessions() as session:
                assert (
                    session.scalar(
                        select(ReportRetentionWorkModel.id).where(
                            ReportRetentionWorkModel.input_id == input_id
                        )
                    )
                    is None
                )
            # This is a separate bounded positive, not a reset within a source
            # invocation. Only inspections increase; removal and byte caps stay.
            for _ in range(128):
                with case.base.sessions() as session, session.begin():
                    budget = SourcePurgeBudget(
                        rows_inspected=256,
                        rows_removed=64,
                        bytes_inspected=8192,
                        bytes_removed=8192,
                    )
                    expire(session, at=at, limit=1, budget=budget)
                    pending = session.scalar(
                        select(ReportRetentionWorkModel.id).where(
                            ReportRetentionWorkModel.input_id == input_id,
                            ReportRetentionWorkModel.completed_at.is_(None),
                        )
                    )
                    assert 0 <= budget.rows_inspected <= 256 and 0 <= budget.rows_removed <= 64
                    assert 0 <= budget.bytes_inspected <= 8192 and 0 <= budget.bytes_removed <= 8192
                    assert 0 <= budget.captures <= 100 and 0 <= budget.runs <= 100
                    assert 0 <= budget.artifacts <= 100
                if pending is not None:
                    break
        assert pending is not None
        with pytest.raises(app.ReportServiceError):
            await case.service.download_report_artifact(
                case.principal,
                case.account_id,
                status.job_id,
                status.artifacts[0].artifact_id,
                grant_token=grant.token,
            )
        for _ in range(128):
            with case.base.sessions() as session, session.begin():
                budget = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
                expire(session, at=at, limit=1, budget=budget)
                purged = session.scalar(
                    select(ReportInputSnapshotModel.purged_at).where(
                        ReportInputSnapshotModel.id == input_id
                    )
                )
                completed = session.scalar(
                    select(ReportRetentionWorkModel.completed_at).where(
                        ReportRetentionWorkModel.input_id == input_id
                    )
                )
                if purged is not None and completed is None:
                    # Header erasure precedes the independently resumable source
                    # flags and completion footer. Share this turn's remainder.
                    expire_report_payloads(session, at=at, limit=1, budget=budget)
                    completed = session.scalar(
                        select(ReportRetentionWorkModel.completed_at).where(
                            ReportRetentionWorkModel.input_id == input_id
                        )
                    )
                assert 0 <= budget.rows_inspected <= 256 and 0 <= budget.rows_removed <= 256
                assert 0 <= budget.artifacts <= 100
                assert 0 <= budget.bytes_inspected <= 64 * 1024 * 1024
                assert 0 <= budget.bytes_removed <= 64 * 1024 * 1024
            if purged is not None:
                break
        assert purged is not None
        # The source invocation may spend its remainder on other source work.
        # Pending report maintenance therefore has separate bounded invocations,
        # each with its own transaction and declared budget, as in the worker.
        for _ in range(128):
            if completed is not None:
                break
            with case.base.sessions() as session, session.begin():
                report_budget = SourcePurgeBudget(rows_inspected=256, rows_removed=256)
                expire_report_payloads(session, at=at, limit=1, budget=report_budget)
                assert 0 <= report_budget.rows_inspected <= 256
                assert 0 <= report_budget.rows_removed <= 256
                assert 0 <= report_budget.artifacts <= 100
                assert 0 <= report_budget.bytes_inspected <= 64 * 1024 * 1024
                assert 0 <= report_budget.bytes_removed <= 64 * 1024 * 1024
                completed = session.scalar(
                    select(ReportRetentionWorkModel.completed_at).where(
                        ReportRetentionWorkModel.input_id == input_id
                    )
                )
        assert purged is not None and completed is not None
        with case.base.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ArtifactDownloadGrantModel)) == 0
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportArtifactModel)
                    .where(ReportArtifactModel.contents.is_not(None))
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportInputChunkModel)
                    .where(ReportInputChunkModel.payload.is_not(None))
                )
                == 0
            )
            assert (
                session.scalar(
                    select(ReportRetentionWorkModel.completed_at).where(
                        ReportRetentionWorkModel.input_id == input_id
                    )
                )
                is not None
            )

    asyncio.run(run())
