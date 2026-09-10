"""Delayed publication callbacks cannot change an already completed private job."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import Table, select
from trading212_application import report_jobs as jobs
from trading212_application import reports as app
from trading212_domain.reports import (
    ExportDataset,
    ExportFieldSet,
    ExportFormat,
    ExportSelection,
    ReportFailureCode,
)
from trading212_persistence.models import AuditEventModel
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import (
    ExportArtifactModel,
    ExportDispatchOutboxModel,
    ExportJobModel,
    ExportManifestModel,
    ReportArtifactModel,
    ReportAttemptModel,
    ReportDispatchOutboxModel,
    ReportJobModel,
    ReportManifestModel,
)
from trading212_worker.report_tasks import (
    ReportExecutionState,
    execute_export_message,
    execute_report_message,
)

from tests.integration.test_report_postgres import ReportCase, generate
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def retained_rows(
    case: ReportCase, job_id: UUID, *, export: bool
) -> dict[str, tuple[tuple[object, ...], ...]]:
    """Compare complete durable rows, including all content, digests and audit metadata."""
    job = (ExportJobModel if export else ReportJobModel).__table__
    outbox = (ExportDispatchOutboxModel if export else ReportDispatchOutboxModel).__table__
    manifest = (ExportManifestModel if export else ReportManifestModel).__table__
    artifact = (ExportArtifactModel if export else ReportArtifactModel).__table__
    attempt = ReportAttemptModel.__table__
    audit = AuditEventModel.__table__
    with case.base.sessions() as session:
        return {
            cast(Table, table).name: tuple(
                tuple(row)
                for row in session.execute(select(table).where(predicate).order_by(table.c.id))
            )
            for table, predicate in (
                (job, job.c.id == job_id),
                (outbox, outbox.c.job_id == job_id),
                (manifest, manifest.c.job_id == job_id),
                (artifact, artifact.c.job_id == job_id),
                (
                    attempt,
                    (attempt.c.export_job_id if export else attempt.c.report_job_id) == job_id,
                ),
                (audit, audit.c.resource_id == str(job_id)),
            )
        }


@pytest.mark.parametrize("export", (False, True), ids=("report", "export"))
def test_completed_job_ignores_late_final_publication_failure_and_acknowledgment(
    report_case: ReportCase, *, export: bool
) -> None:
    async def run() -> None:
        case = report_case
        at = datetime.now(UTC)
        store = PostgresReportJobStore(case.base.sessions, clock=lambda: at)
        if export:
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
                format=ExportFormat.JSON,
            )
            pending = await case.service.create_export(
                case.principal,
                app.CreateExportCommand(selection=selection, idempotency_key="late-publisher"),
            )
            job_id = pending.export_id
        else:
            job_id = (await generate(case, key="late-publisher")).job_id
        # Each retry is an actual transition. Only the injected clock moves to the
        # persisted retry deadline; retained timestamps and SQL guards stay intact.
        at = datetime.now(UTC)
        claim: jobs.ReportDispatchClaim | jobs.ExportDispatchClaim | None = None
        for publication_attempt in range(1, 9):
            claims = (
                await store.claim_export_dispatches(dispatcher_id="late-publisher", limit=1)
                if export
                else await store.claim_report_dispatches(dispatcher_id="late-publisher", limit=1)
            )
            assert len(claims) == 1
            claim = claims[0]
            assert claim.message.job_id == job_id
            assert claim.publication_attempt == publication_attempt
            if publication_attempt < 8:
                assert (
                    await store.defer_export_dispatch(
                        claim, failure=ReportFailureCode.PUBLICATION_UNAVAILABLE
                    )
                    if isinstance(claim, jobs.ExportDispatchClaim)
                    else await store.defer_report_dispatch(
                        claim, failure=ReportFailureCode.PUBLICATION_UNAVAILABLE
                    )
                )
                with case.base.sessions() as session:
                    model = ExportDispatchOutboxModel if export else ReportDispatchOutboxModel
                    row = session.scalar(select(model).where(model.job_id == job_id))
                    assert row is not None and row.state == "pending"
                    at = row.available_at
        assert claim is not None
        completed = (
            await execute_export_message(store, claim.message, consumer_id="delivered-first")
            if isinstance(claim, jobs.ExportDispatchClaim)
            else await execute_report_message(store, claim.message, consumer_id="delivered-first")
        )
        assert completed is ReportExecutionState.COMPLETED
        with case.base.sessions() as session:
            job_model = ExportJobModel if export else ReportJobModel
            job = session.get(job_model, job_id)
            assert job is not None and job.state == "succeeded"
            assert job.completed_at is not None and job.manifest_digest is not None
            model = ExportDispatchOutboxModel if export else ReportDispatchOutboxModel
            row = session.scalar(select(model).where(model.job_id == job_id))
            assert row is not None and row.state == "claimed"
            assert row.claim_token == claim.claim_token and row.publication_attempts == 8
        before = retained_rows(case, job_id, export=export)
        assert len(before["export_manifests" if export else "report_manifests"]) == 1
        assert len(before["export_artifacts" if export else "report_artifacts"]) == 1
        assert len(before["report_job_attempts"]) == 17
        assert len(before["audit_events"]) == 2
        # The consumer has sealed success before the publisher returns either an
        # ambiguous final failure or a late acknowledgment for the same live claim.
        if isinstance(claim, jobs.ExportDispatchClaim):
            assert not await store.defer_export_dispatch(
                claim, failure=ReportFailureCode.PUBLICATION_UNAVAILABLE
            )
            assert not await store.acknowledge_export_dispatch(claim)
        else:
            assert not await store.defer_report_dispatch(
                claim, failure=ReportFailureCode.PUBLICATION_UNAVAILABLE
            )
            assert not await store.acknowledge_report_dispatch(claim)
        assert retained_rows(case, job_id, export=export) == before
        # An expired historical claim on a terminal job is never redispatched.
        at = claim.claim_expires_at + timedelta(seconds=1)
        assert not (
            await store.claim_export_dispatches(dispatcher_id="later-publisher", limit=1)
            if export
            else await store.claim_report_dispatches(dispatcher_id="later-publisher", limit=1)
        )
        assert retained_rows(case, job_id, export=export) == before

    asyncio.run(run())
