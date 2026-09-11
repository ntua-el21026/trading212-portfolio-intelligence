"""Real report/export copy, current permission, reuse and expiry."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Never
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_application import report_jobs as jobs
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.sources import LicensePermission
from trading212_persistence import xray_run_store
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import (
    ExportArtifactModel,
    ExportJobModel,
    ReportInputChunkModel,
    ReportInputDependencyModel,
    ReportInputSnapshotModel,
)
from trading212_persistence.report_service import PostgresReportService
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_retention_service import expire_source_payloads
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_run_models import XrayRunModel
from trading212_security.principals import Scope
from trading212_worker.report_tasks import ReportExecutionState, execute_export_message
from trading212_worker.xray_fixture import XRAY_AT, xray_id
from trading212_worker.xray_seed import XRAY_CURSOR_KEY
from trading212_worker.xray_source_fixture import xray_license

from tests.integration.test_planning_company_postgres import request
from tests.integration.test_report_exports_postgres import _export
from tests.integration.test_report_postgres import ReportCase, finish
from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def report_case(base: XrayReadCase) -> ReportCase:
    # Report retention is enforced by the actual PostgreSQL wall clock. Keep the
    # financial snapshot cutoff fixed while capturing and sealing at current time.
    base.now[0] = max(base.now[0], datetime.now(UTC))
    with base.sessions() as session, session.begin():
        provision_principal_scopes(
            session,
            principal_id=UUID(base.principal.principal_id),
            scopes=frozenset(Scope),
            now=base.now[0] - timedelta(seconds=1),
            expires_at=base.principal.expires_at,
        )

    def now() -> datetime:
        # Worker leases also expire against PostgreSQL time during slow renders.
        # Preserve deliberate future test times without freezing lease renewal.
        return max(base.now[0], datetime.now(UTC))

    return ReportCase(
        base,
        PostgresReportService(base.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=now),
        PostgresReportJobStore(base.sessions, clock=now),
    )


async def selected(case: ReportCase) -> r.ReportSelection:
    full = await company(case.base)
    query = await request(case.base, full.context.run_id)
    return replace(
        case.selection(),
        report_type=r.ReportType.TARGET_DRIFT,
        sections=(
            r.ReportSection.OVERVIEW,
            r.ReportSection.TARGETS,
            r.ReportSection.DRIFT,
            r.ReportSection.QUALITY,
        ),
        target_version_id=UUID(query.target_version_id),
        xray_run_id=UUID(full.context.run_id),
        source_cutoff_at=case.base.now[0],
    )


def export_selection(
    selection: r.ReportSelection, format: r.ExportFormat = r.ExportFormat.JSON
) -> r.ExportSelection:
    return r.ExportSelection(
        account_id=selection.account_id,
        start_date=selection.start_date,
        end_date=selection.end_date,
        source_cutoff_at=selection.source_cutoff_at,
        snapshot_id=selection.snapshot_id,
        reporting_currency=selection.reporting_currency,
        dataset=r.ExportDataset.TARGETS,
        field_set=r.ExportFieldSet.AUDIT,
        format=format,
        target_version_id=selection.target_version_id,
        xray_run_id=selection.xray_run_id,
    )


async def license_change(case: ReportCase, field: str, permission: LicensePermission) -> None:
    case.base.now[0] += timedelta(seconds=1)
    identifier = str(uuid4())
    source = PostgresSourceService(
        sessions=case.base.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: case.base.now[0],
    )
    license = replace(
        xray_license(),
        id=identifier,
        version=identifier,
        effective_at=case.base.now[0],
    )
    if field == "display":
        license = replace(license, display=permission)
    elif field == "store":
        license = replace(license, store=permission)
    elif field == "report":
        license = replace(license, report=permission)
    else:
        assert field == "export"
        license = replace(license, export=permission)
    await source.register_source_license(
        case.principal,
        license,
        idempotency_key=identifier,
        correlation_id="company-copy-license",
    )


def forbidden_decode(*args: object, **kwargs: object) -> Never:
    raise AssertionError("A denied company copy reached canonical X-ray decode")


def test_real_company_report_and_all_export_formats_keep_full_metric_and_complete_proof(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = report_case(xray_read_case)
        selection = await selected(case)
        pending = await case.service.generate_report(
            case.principal,
            app.GenerateReportCommand(selection=selection, idempotency_key="company-report"),
        )
        completed = await finish(case, pending)
        manifest = await case.service.get_report_manifest(
            case.principal, case.account_id, completed.job_id
        )
        assert manifest.document.selection.xray_run_id == selection.xray_run_id
        assert any(
            pin.family is r.ReportFamily.XRAY and pin.subject_id == selection.xray_run_id
            for pin in manifest.bindings
        )
        assert {
            r.ReportTableKey.PLANNING_COMPANY_ACTUALS_V1,
            r.ReportTableKey.PLANNING_COMPANY_BASIS_V1,
            r.ReportTableKey.XRAY_PATHS,
        } <= {item.table for item in manifest.document.tables}
        previous = None
        for format in r.ExportFormat:
            artifact = await _export(
                case.base.sessions,
                case.service,
                case.jobs,
                case.principal,
                export_selection(selection, format),
            )
            rows = artifact.rows(r.ReportTableKey.PLANNING_COMPANY_ACTUALS_V1)
            alpha = [row for row in rows if row["entity_id"].value == xray_id("entity/alpha")]
            assert len(alpha) == 4
            assert all(row["actual_weight"].value == Decimal("0.56") for row in alpha)
            assert all(
                row["semantics"].value == "full_portfolio_company_non_additive"
                and row["drift_reason"].value == "effective_exposure_target_unavailable"
                for row in rows
            )
            assert all(
                row["effective_weight"].value is None
                for row in artifact.rows(r.ReportTableKey.DRIFT_ROWS)
            )
            assert all(row["actual_weight"].context_key == "xray" for row in alpha)
            basis = artifact.rows(r.ReportTableKey.PLANNING_COMPANY_BASIS_V1)[0]
            assert basis["xray_run_id"].value == str(selection.xray_run_id)
            signature = tuple(
                (
                    row["row_key"].value,
                    row["entity_id"].value,
                    row["actual_weight"].value,
                    row["projection_digest"].value,
                )
                for row in rows
            )
            assert previous is None or signature == previous
            previous = signature
            relations = artifact.rows(r.ReportTableKey.PLAN_RELATIONS)
            assert any(row["relation_kind"].value == "company_path" for row in relations)
            for row in alpha:
                parent = "company.actual." + str(row["row_key"].value)
                assert (
                    sum(
                        item["parent_key"].value == parent
                        and item["relation_kind"].value == "company_path"
                        for item in relations
                    )
                    == row["path_count"].value
                )

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,permission",
    [
        ("display", LicensePermission.DENIED),
        ("store", LicensePermission.UNKNOWN),
        ("report", LicensePermission.DENIED),
        ("export", LicensePermission.UNKNOWN),
    ],
)
def test_current_copy_license_denial_precedes_canonical_decode(
    xray_read_case: XrayReadCase,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    permission: LicensePermission,
) -> None:
    async def run() -> None:
        case = report_case(xray_read_case)
        selection = await selected(case)
        await license_change(case, field, permission)
        for name in ("decode_xray_component", "decode_xray_input", "decode_xray_result"):
            monkeypatch.setattr(xray_run_store, name, forbidden_decode)
        with pytest.raises(app.ReportServiceError) as denied:
            if field == "report":
                await case.service.generate_report(
                    case.principal,
                    app.GenerateReportCommand(selection=selection, idempotency_key="denied-report"),
                )
            else:
                await case.service.create_export(
                    case.principal,
                    app.CreateExportCommand(
                        selection=export_selection(selection), idempotency_key="denied-export"
                    ),
                )
        assert denied.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
        with case.base.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ReportInputSnapshotModel)) == 0

    asyncio.run(run())


def test_real_later_created_run_is_not_available_at_earlier_report_cutoff(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = report_case(xray_read_case)
        query = await request(case.base, None)
        case.base.now[0] += timedelta(seconds=1)
        full = await company(case.base)
        assert full.context.calculated_at > XRAY_AT
        selection = replace(
            case.selection(),
            report_type=r.ReportType.TARGET_DRIFT,
            sections=(
                r.ReportSection.OVERVIEW,
                r.ReportSection.TARGETS,
                r.ReportSection.DRIFT,
                r.ReportSection.QUALITY,
            ),
            target_version_id=UUID(query.target_version_id),
            xray_run_id=UUID(full.context.run_id),
        )
        assert selection.source_cutoff_at == XRAY_AT
        with pytest.raises(app.ReportServiceError):
            await case.service.generate_report(
                case.principal,
                app.GenerateReportCommand(selection=selection, idempotency_key="too-early"),
            )
        later = await case.service.generate_report(
            case.principal,
            app.GenerateReportCommand(
                selection=replace(selection, source_cutoff_at=case.base.now[0]),
                idempotency_key="available-later",
            ),
        )
        assert later.state is r.ReportJobState.QUEUED

    asyncio.run(run())


async def complete_export(
    case: ReportCase, command: app.CreateExportCommand
) -> tuple[app.ExportJobStatus, jobs.ExportTaskMessage]:
    pending = await case.service.create_export(case.principal, command)
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
        await execute_export_message(case.jobs, message, consumer_id="company-export")
        is ReportExecutionState.COMPLETED
    )
    status = await case.service.get_export_status(
        case.principal, case.account_id, pending.export_id
    )
    return status, message


def test_export_reuse_and_existing_grant_require_current_export_permission(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = report_case(xray_read_case)
        command = app.CreateExportCommand(
            selection=export_selection(await selected(case)), idempotency_key="repeat-company"
        )
        status, _ = await complete_export(case, command)
        artifact = status.artifacts[0]
        grant = await case.service.create_export_download_grant(
            case.principal, case.account_id, status.export_id, artifact.artifact_id
        )
        await license_change(case, "export", LicensePermission.DENIED)
        with pytest.raises(app.ReportServiceError) as reuse:
            await case.service.create_export(case.principal, command)
        assert reuse.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
        with pytest.raises(app.ReportServiceError) as denied:
            await case.service.download_export_artifact(
                case.principal,
                case.account_id,
                status.export_id,
                artifact.artifact_id,
                grant_token=grant.token,
            )
        assert denied.value.code is app.ReportServiceErrorCode.ACCESS_DENIED

    asyncio.run(run())


def test_actual_dependency_ttl_purges_company_copy_and_denies_download(
    xray_read_case: XrayReadCase,
) -> None:
    async def run() -> None:
        case = report_case(xray_read_case)
        report_selection = await selected(case)
        with case.base.sessions() as session:
            selected_run = session.get(XrayRunModel, report_selection.xray_run_id)
            assert selected_run is not None
            deadline = case.base.service._xray_storage_expires_at(
                session, UUID(case.principal.owner_id), selected_run.input_id
            )
            assert deadline is not None
        # Move the test clock near the actual retained dependency deadline;
        # do not mutate source expiry or invent a short-lived parent.
        case.base.now[0] = deadline - timedelta(days=1)
        selection = export_selection(replace(report_selection, source_cutoff_at=case.base.now[0]))
        status, message = await complete_export(
            case,
            app.CreateExportCommand(
                selection=selection, idempotency_key="expiring-company", ttl_days=30
            ),
        )
        grant = await case.service.create_export_download_grant(
            case.principal, case.account_id, status.export_id, status.artifacts[0].artifact_id
        )
        with case.base.sessions() as session:
            capture = session.get(ReportInputSnapshotModel, message.capture_id)
            assert capture is not None
            dependencies = session.scalars(
                select(ReportInputDependencyModel).where(
                    ReportInputDependencyModel.input_id == capture.id
                )
            ).all()
            assert {"constituent", "entity_evidence", "fund_definition", "fund_mapping"} <= {
                row.kind for row in dependencies
            }
            expiries = [row.expires_at for row in dependencies if row.expires_at is not None]
            assert expiries
            assert capture.expires_at == min(case.base.now[0] + timedelta(days=30), min(expiries))
            assert capture.expires_at == deadline < case.base.now[0] + timedelta(days=30)
            # Advance to an actual constituent physical deadline and invoke the
            # real bounded source-retention path, not direct report-row purging.
            constituents = [row for row in dependencies if row.kind == "constituent"]
            assert constituents
            constituent_expiries = []
            for dependency in constituents:
                expiry = dependency.expires_at
                assert expiry is not None
                constituent_expiries.append(expiry)
            at = max(constituent_expiries) + timedelta(seconds=1)
        case.base.now[0] = at
        with pytest.raises(app.ReportServiceError):
            await case.service.download_export_artifact(
                case.principal,
                case.account_id,
                status.export_id,
                status.artifacts[0].artifact_id,
                grant_token=grant.token,
            )
        purged = None
        for _ in range(256):
            with case.base.sessions() as session, session.begin():
                expire_source_payloads(
                    session,
                    at=at,
                    limit=1,
                    budget=SourcePurgeBudget(rows_inspected=256, rows_removed=256),
                )
                purged = session.scalar(
                    select(ReportInputSnapshotModel.purged_at).where(
                        ReportInputSnapshotModel.id == message.capture_id
                    )
                )
            if purged is not None:
                break
        assert purged is not None
        with case.base.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportInputChunkModel)
                    .where(
                        ReportInputChunkModel.input_id == message.capture_id,
                        ReportInputChunkModel.payload.is_not(None),
                    )
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ExportArtifactModel)
                    .where(
                        ExportArtifactModel.job_id == status.export_id,
                        ExportArtifactModel.contents.is_not(None),
                    )
                )
                == 0
            )

    asyncio.run(run())


def test_queued_export_rechecks_copy_permission_before_render(xray_read_case: XrayReadCase) -> None:
    async def run() -> None:
        case = report_case(xray_read_case)
        command = app.CreateExportCommand(
            selection=export_selection(await selected(case)), idempotency_key="queued-company"
        )
        pending = await case.service.create_export(case.principal, command)
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
        await license_change(case, "export", LicensePermission.DENIED)
        assert (
            await case.jobs.claim_export_job(message, consumer_id="queued-company-denied") is None
        )
        with case.base.sessions() as session:
            job = session.get(ExportJobModel, pending.export_id)
            assert job is not None and job.state == "failed" and job.failure_code == "access_denied"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ExportArtifactModel)
                    .where(ExportArtifactModel.job_id == pending.export_id)
                )
                == 0
            )

    asyncio.run(run())
