"""Actual synthetic dump/restore, original canonical state and durable job recovery."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from trading212_application import projection as projection_app
from trading212_application.risk import PremiumJobState
from trading212_domain import reports as reports
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.projection_job_store import PostgresProjectionJobStore
from trading212_persistence.projection_models import ProjectionResultModel
from trading212_persistence.projection_service import PostgresProjectionService
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import ReportArtifactModel
from trading212_persistence.report_research_models import ReportInputResearchDependencyModel
from trading212_persistence.report_service import PostgresReportService
from trading212_worker.projection_tasks import ProjectionExecutionState, execute_projection_message
from trading212_worker.report_tasks import ReportExecutionState, execute_report_message
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.phase3_operational_fixture import (
    drop_restored,
    evidence,
    inventory,
    restore_empty,
)
from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.research_case import research_case as research_case
from tests.integration.research_report_case import ResearchReportCase, generate, message, selection
from tests.integration.research_report_case import research_report_case as research_report_case
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def test_failed_restore_has_no_unaccounted_task_database(
    xray_read_case: XrayReadCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = xray_read_case
    root = Path(os.environ["T212PI_PHASE3_EVIDENCE_DIR"]) / "operations-backups"
    root.mkdir(mode=0o700, exist_ok=True)
    corrupt = root / f"invalid-pgdump-{uuid4().hex}.bin"
    corrupt.write_bytes(b"explicit synthetic invalid pg_dump header\n")
    original_run = subprocess.run

    def broken_stream(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if "pg_restore" in arguments:
            with corrupt.open("rb") as invalid:
                return original_run(arguments, **{**kwargs, "stdin": invalid})
        return original_run(arguments, **kwargs)

    def targets() -> set[str]:
        admin = case.engine.url.set(drivername="postgresql", database="postgres")
        with psycopg.connect(admin.render_as_string(hide_password=False)) as connection:
            return {
                row[0]
                for row in connection.execute(
                    "SELECT datname FROM pg_database WHERE datname LIKE 't212pi_phase3_ops_%'"
                )
            }

    before = targets()
    source_before = inventory(case.sessions)
    try:
        with monkeypatch.context() as context:
            context.setattr(subprocess, "run", broken_stream)
            with pytest.raises(subprocess.CalledProcessError):
                restore_empty(case.engine, directory=root)
        after = targets()
        evidence(
            "restore-fault",
            {
                "targets_before": sorted(before),
                "targets_after": sorted(after),
                "fault": "real pg_restore consumed an invalid synthetic header",
            },
        )
        assert inventory(case.sessions) == source_before
        assert after == before
    finally:
        # The injected invalid header cannot create schema/data. Retain that exact
        # observed empty state before cleaning a target leaked by the RED helper.
        for name in targets() - before:
            url = case.engine.url.set(drivername="postgresql", database=name)
            with psycopg.connect(url.render_as_string(hide_password=False)) as connection:
                tables = tuple(
                    connection.execute(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname='public' ORDER BY tablename"
                    )
                )
                evidence("failed-target-empty", {"target": name, "public_tables": tables})
                assert not tables
            drop_restored(case.engine, name)


async def test_empty_database_restore_preserves_canonical_state_and_recovers_both_jobs(
    projection_job_case: ProjectionJobCase,
    research_report_case: ResearchReportCase,
) -> None:
    projection, research = projection_job_case, research_report_case
    assert projection.engine is research.research.xray.engine
    pending = await generate(
        research, selected=selection(research, formats=(reports.ReportFormat.JSON,))
    )
    report_message = message(research, pending)
    worker = PostgresProjectionJobStore(
        projection.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: datetime.now(UTC)
    )
    dispatches = await worker.claim_projection_dispatches(dispatcher_id="before-backup")
    assert len(dispatches) == 1
    projection_message = dispatches[0].message
    assert await worker.acknowledge_projection_dispatch(dispatches[0])
    before = inventory(projection.sessions)
    recovery_started = perf_counter()
    backup_directory = Path(os.environ["T212PI_PHASE3_EVIDENCE_DIR"]) / "operations-backups"
    backup_directory.mkdir(mode=0o700, exist_ok=True)
    restored_name, observation = restore_empty(projection.engine, directory=backup_directory)
    restored_engine = create_database_engine(
        projection.engine.url.set(database=restored_name).render_as_string(hide_password=False)
    )
    sessions = create_session_factory(restored_engine)
    try:
        after = inventory(sessions)
        evidence("restore-inventories", {"before": before, "after": after})
        assert {k: v for k, v in after.items() if k != "raw_schema_sha256"} == {
            k: v for k, v in before.items() if k != "raw_schema_sha256"
        }
        with sessions() as session, pytest.raises(IntegrityError), session.begin():
            session.execute(
                update(ReportInputResearchDependencyModel)
                .where(ReportInputResearchDependencyModel.input_id == report_message.capture_id)
                .values(item_selection_digest="f" * 64)
            )
        assert inventory(sessions) == after
        assert observation["backup_and_restore_seconds"] <= 600
        resumed = PostgresProjectionJobStore(
            sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: datetime.now(UTC)
        )
        assert (
            await execute_projection_message(
                resumed,
                projection_message,
                consumer_id="after-clean-restore",
                clock=lambda: datetime.now(UTC),
            )
            is ProjectionExecutionState.SUCCEEDED
        )
        assert (
            await execute_projection_message(
                resumed,
                projection_message,
                consumer_id="duplicate-after-restore",
                clock=lambda: datetime.now(UTC),
            )
            is ProjectionExecutionState.FENCED
        )
        reader = PostgresProjectionService(
            sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: datetime.now(UTC)
        )
        view = await reader.get_run(
            projection.principal,
            projection.run.id,
            projection_app.ProjectionPointPageQuery(point_limit=1),
        )
        assert view.state is PremiumJobState.SUCCEEDED and view.result is not None
        report_store = PostgresReportJobStore(sessions, clock=lambda: datetime.now(UTC))
        assert (
            await execute_report_message(
                report_store, report_message, consumer_id="restored-research-report"
            )
            is ReportExecutionState.COMPLETED
        )
        report_reader = PostgresReportService(
            sessions=sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: datetime.now(UTC),
            contract_version=3,
        )
        completed = await report_reader.get_report_status(
            research.research.xray.principal, research.research.account_id, pending.job_id
        )
        assert completed.state is reports.ReportJobState.SUCCEEDED
        with sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ProjectionResultModel)
                    .where(ProjectionResultModel.run_id == projection.run.id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportArtifactModel)
                    .where(ReportArtifactModel.job_id == pending.job_id)
                )
                == 1
            )
        assert inventory(projection.sessions) == before
        recovery_seconds = perf_counter() - recovery_started
        assert recovery_seconds <= 600
        evidence(
            "clean-restore",
            {
                **observation,
                "table_count": len(before["tables"]),
                "source_inventory": before,
                "restored_inventory": after,
                "pending_projection_recovered": True,
                "pending_research_report_recovered": True,
                "duplicate_fenced": True,
                "source_database_unchanged": True,
                "recovery_through_validated_job_reads_seconds": recovery_seconds,
            },
        )
    finally:
        restored_engine.dispose()
        drop_restored(projection.engine, restored_name)
