"""Small real saved-projection/report helpers; no direct financial publication."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.engine import Connection, ExecutionContext
from trading212_application import report_jobs
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.projection_result import ProjectionCalculation
from trading212_domain.projection_serialization import decode_projection_result
from trading212_domain.report_v4 import ReportProjectionRunSelection, ReportSelectionV4
from trading212_persistence.models import PortfolioSnapshotModel
from trading212_persistence.premium_models import PremiumRunModel
from trading212_persistence.projection_models import (
    ProjectionInputModel,
    ProjectionResultModel,
    ProjectionSourceProofModel,
)
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import ReportJobModel
from trading212_persistence.report_service import PostgresReportService
from trading212_worker.projection_tasks import ProjectionExecutionState, execute_projection_message
from trading212_worker.report_tasks import ReportExecutionState, execute_report_message
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.test_projection_jobs_postgres import admitted, store


@dataclass(frozen=True)
class SavedProjection:
    value: ProjectionCalculation
    input_id: UUID
    result_id: UUID
    capture_digest: str
    numerical_digest: str
    result_digest: str
    capture_bytes: bytes
    input_bytes: bytes
    result_bytes: bytes
    sources: tuple[bytes, ...]
    expires_at: datetime


async def execute_saved(case: ProjectionJobCase) -> SavedProjection:
    worker = store(case)
    dispatch = await admitted(case, worker)
    assert await worker.acknowledge_projection_dispatch(dispatch)
    assert (
        await execute_projection_message(
            worker, dispatch.message, consumer_id="projection-report-source", clock=lambda: case.now
        )
        is ProjectionExecutionState.SUCCEEDED
    )
    return saved_projection(case)


def saved_projection(case: ProjectionJobCase) -> SavedProjection:
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        original = session.scalar(
            select(ProjectionInputModel).where(ProjectionInputModel.run_id == root.id)
        )
        result = session.scalar(
            select(ProjectionResultModel).where(ProjectionResultModel.run_id == root.id)
        )
        assert original is not None and result is not None
        assert sha256(result.canonical_result).hexdigest() == result.content_digest
        value = decode_projection_result(result.canonical_result)
        copies = tuple(
            session.scalars(
                select(ProjectionSourceProofModel.canonical_proof)
                .where(ProjectionSourceProofModel.run_id == root.id)
                .order_by(ProjectionSourceProofModel.id)
            )
        )
        return SavedProjection(
            value,
            original.id,
            result.id,
            root.input_digest,
            value.input_digest,
            result.content_digest,
            original.canonical_capture,
            original.canonical_input,
            result.canonical_result,
            copies,
            root.expires_at,
        )


def report_service(case: ProjectionJobCase, version: int = 4) -> PostgresReportService:
    return PostgresReportService(
        case.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: max(case.now, datetime.now(UTC)),
        contract_version=version,
    )


def report_selection(case: ProjectionJobCase) -> ReportSelectionV4:
    # The fixture supplies the exact ordinary snapshot; no latest-run/source resolver is used.
    with case.sessions() as session:
        snapshot = session.get_one(PortfolioSnapshotModel, UUID(case.xray.seed["snapshot_id"]))
        assert snapshot.broker_account_id == case.command.selection.account_id
        money = case.command.selection.initial.modeled_value
        assert money is not None
        return ReportSelectionV4(
            account_id=case.command.selection.account_id,
            snapshot_id=snapshot.id,
            start_date=snapshot.valuation_at.date(),
            end_date=snapshot.valuation_at.date(),
            source_cutoff_at=snapshot.source_cutoff_at,
            reporting_currency=money.currency,
            report_type=r.ReportType.PORTFOLIO_SUMMARY,
            sections=(
                r.ReportSection.OVERVIEW,
                r.ReportSection.ALLOCATION,
                r.ReportSection.QUALITY,
                r.ReportSection.PROJECTION,
            ),
            formats=tuple(r.ReportFormat),
            premium_run=ReportProjectionRunSelection(run_id=case.run.id),
        )


async def complete_report(
    case: ProjectionJobCase, service: PostgresReportService, pending: app.ReportJobStatus
) -> app.ReportJobStatus:
    with case.sessions() as session:
        job = session.get_one(ReportJobModel, pending.job_id)
        message = report_jobs.ReportTaskMessage(
            job_id=job.id,
            owner_id=job.owner_id,
            account_id=job.account_id,
            capture_id=job.input_id,
            input_digest=job.input_digest,
        )
    outcome = await execute_report_message(
        PostgresReportJobStore(case.sessions, clock=lambda: max(case.now, datetime.now(UTC))),
        message,
        consumer_id="projection-report4",
    )
    status = await service.get_report_status(
        case.principal, case.command.selection.account_id, pending.job_id
    )
    assert outcome is ReportExecutionState.COMPLETED, status.failure_code
    assert status.state is r.ReportJobState.SUCCEEDED
    return status


@contextmanager
def no_resampling() -> Iterator[None]:
    with (
        patch(
            "trading212_analytics.projection.calculate_projection",
            side_effect=AssertionError("report resampled"),
        ),
        patch(
            "trading212_analytics.projection.calculate_projection_chunk",
            side_effect=AssertionError("report resampled chunk"),
        ),
    ):
        yield


@contextmanager
def no_private_reads(case: ProjectionJobCase) -> Iterator[None]:
    columns = (
        "projection_inputs.canonical_capture",
        "projection_inputs.canonical_input",
        "projection_results.canonical_result",
        "projection_chunks.canonical_chunk",
        "projection_source_proofs.canonical_proof",
        "projection_assumption_assets.annual_mean_log_return",
        "projection_points.nominal",
        "price_observations.value",
        "historical_input_snapshots.canonical_input",
        "report_input_snapshots.canonical_context",
        "report_input_snapshots.canonical_manifest",
        "report_input_chunks.payload",
        "report_manifests.payload",
        "report_artifacts.contents",
    )

    def observe(
        _connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: ExecutionContext,
        _many: bool,
    ) -> None:
        sql = statement.replace('"', "").lower().lstrip()
        if sql.startswith("select"):
            assert not any(column in sql for column in columns), (
                "Private financial SELECT preceded authorization"
            )

    event.listen(case.engine, "before_cursor_execute", observe)
    try:
        yield
    finally:
        event.remove(case.engine, "before_cursor_execute", observe)
