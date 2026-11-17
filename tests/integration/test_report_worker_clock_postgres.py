"""Real publication guards remain independent of an injected worker clock."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from trading212_application import report_jobs as jobs
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import (
    ReportArtifactModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportManifestModel,
)

from tests.integration.test_report_postgres import ReportCase, generate
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def test_frozen_worker_view_cannot_override_database_publication_time(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        cutoff_before = case.selection().source_cutoff_at
        fixture_clock_before = case.base.now[0]
        live = PostgresReportJobStore(case.base.sessions, clock=lambda: datetime.now(UTC))
        pending = await generate(case)
        with case.base.sessions() as session:
            row = session.get_one(ReportJobModel, pending.job_id)
            message = jobs.ReportTaskMessage(
                job_id=row.id,
                owner_id=row.owner_id,
                account_id=row.account_id,
                capture_id=row.input_id,
                input_digest=row.input_digest,
            )
        claim = await live.claim_report_job(message, consumer_id="worker-clock-regression")
        assert claim is not None
        with case.base.sessions() as session, session.begin():
            database_now = session.scalar(text("SELECT CURRENT_TIMESTAMP"))
            assert isinstance(database_now, datetime)
            frozen_at = database_now - timedelta(seconds=jobs.REPORT_WORKER_LEASE_SECONDS + 5)
            # Construct a lagging heartbeat without changing its fence or identity.
            session.execute(
                update(ReportJobModel)
                .where(ReportJobModel.id == pending.job_id)
                .values(
                    heartbeat_at=frozen_at,
                    lease_expires_at=frozen_at
                    + timedelta(seconds=jobs.REPORT_WORKER_LEASE_SECONDS),
                )
            )
        frozen = PostgresReportJobStore(case.base.sessions, clock=lambda: frozen_at)
        with case.base.sessions() as session:
            frozen_sees_live = frozen._live(session, claim) is not None
            real_clock_sees_live = live._live(session, claim) is not None
        assert frozen_sees_live
        assert not real_clock_sees_live

        rejection = "not_rejected"
        try:
            with case.base.sessions() as session, session.begin():
                capture = session.get_one(ReportInputSnapshotModel, message.capture_id)
                payload = capture.canonical_manifest
                assert payload is not None
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
        except DBAPIError as error:
            primary = getattr(getattr(error.orig, "diag", None), "message_primary", None)
            rejection = (
                "publication_fence_stale"
                if primary == "Report publication fence is stale"
                else "unexpected_storage_error"
            )
        # Never expose SQL parameters or the canonical report payload on failure.
        assert rejection == "publication_fence_stale"
        with case.base.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ReportManifestModel)) == 0
            assert session.scalar(select(func.count()).select_from(ReportArtifactModel)) == 0

        recovered = await live.claim_report_job(message, consumer_id="live-clock-recovery")
        assert recovered is not None and recovered.fence == claim.fence + 1
        assert recovered.lease_id != claim.lease_id
        assert not await live.heartbeat_report_job(claim)
        assert await live.heartbeat_report_job(recovered)
        with case.base.sessions() as session:
            row = session.get_one(ReportJobModel, pending.job_id)
            database_now = session.scalar(text("SELECT CURRENT_TIMESTAMP"))
            assert row.lease_expires_at is not None and row.lease_expires_at > database_now
        assert case.base.now[0] == fixture_clock_before
        assert case.selection().source_cutoff_at == cutoff_before

    asyncio.run(run())
