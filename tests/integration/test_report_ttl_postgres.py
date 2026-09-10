"""Natural report TTL, distinct from owner termination and source expiry."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_application import reports as app
from trading212_domain.reports import ReportFormat, ReportJobState
from trading212_persistence.models import AuditEventModel, PrincipalModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.report_base import report_scopes
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import (
    ArtifactDownloadGrantModel,
    ReportArtifactModel,
    ReportDispatchOutboxModel,
    ReportInputChunkModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportManifestModel,
    ReportRetentionWorkModel,
)
from trading212_persistence.report_retention import expire_report_payloads
from trading212_persistence.report_service import PostgresReportService
from trading212_security.principals import Scope
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_report_postgres import ReportCase, finish
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def test_natural_report_ttl_denies_before_bounded_idempotent_physical_cleanup(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case

        def database_now() -> datetime:
            with case.base.sessions() as session:
                value = session.scalar(select(func.clock_timestamp()))
                assert isinstance(value, datetime)
                return value.astimezone(UTC)

        def lifecycle_events(job_id: UUID, input_id: UUID) -> tuple[tuple[UUID, str, object], ...]:
            with case.base.sessions() as session:
                return tuple(
                    (event.id, event.action, event.safe_metadata)
                    for event in session.scalars(
                        select(AuditEventModel)
                        .where(AuditEventModel.resource_id.in_((str(job_id), str(input_id))))
                        .order_by(AuditEventModel.occurred_at, AuditEventModel.action)
                    )
                )

        # Insert through ordinary capture at an authorized historical clock. A
        # normal one-day TTL then has a short real remaining lifetime. SQL still
        # verifies its own wall clock; no retained timestamp or trigger is edited.
        expiry = database_now() + timedelta(seconds=45)
        created = expiry - timedelta(days=1)
        at = [created]
        identifier = uuid4()
        principal = replace(
            case.principal,
            principal_id=str(identifier),
            subject=f"report-ttl-{identifier}",
            authenticated_at=created - timedelta(seconds=1),
            expires_at=expiry + timedelta(hours=1),
            scopes=frozenset(Scope),
        )
        with case.base.sessions() as session, session.begin():
            session.add(
                PrincipalModel(
                    id=identifier,
                    owner_id=UUID(principal.owner_id),
                    issuer=principal.issuer,
                    subject=principal.subject,
                    status="active",
                    created_at=created - timedelta(seconds=1),
                    last_authenticated_at=created - timedelta(seconds=1),
                )
            )
            session.flush()
            provision_principal_scopes(
                session,
                principal_id=identifier,
                scopes=principal.scopes,
                now=created - timedelta(seconds=1),
            )
        case.base.principal = principal
        case.service = PostgresReportService(
            case.base.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: at[0]
        )
        case.jobs = PostgresReportJobStore(case.base.sessions, clock=lambda: at[0])
        pending = await case.service.generate_report(
            principal,
            app.GenerateReportCommand(
                selection=case.selection(formats=(ReportFormat.JSON, ReportFormat.CSV)),
                idempotency_key=str(uuid4()),
                ttl_days=1,
            ),
        )
        assert pending.requested_at == created and pending.expires_at == expiry
        at[0] = database_now()
        status = await finish(case, pending)
        assert status.state is ReportJobState.SUCCEEDED and len(status.artifacts) == 2
        assert all(artifact.expires_at == expiry for artifact in status.artifacts)
        grants = tuple(
            [
                await case.service.create_report_download_grant(
                    principal, case.account_id, status.job_id, artifact.artifact_id
                )
                for artifact in status.artifacts
            ]
        )
        content = await case.service.download_report_artifact(
            principal,
            case.account_id,
            status.job_id,
            status.artifacts[0].artifact_id,
            grant_token=grants[0].token,
        )
        assert content.metadata.content_digest == status.artifacts[0].content_digest
        assert database_now() < expiry, "Fixture must finish before its genuine TTL deadline."

        with case.base.sessions() as session:
            job = session.get(ReportJobModel, status.job_id)
            assert job is not None
            input_id = job.input_id
            input_row = session.get(ReportInputSnapshotModel, input_id)
            assert input_row is not None and input_row.expires_at == expiry
            assert input_row.canonical_manifest and input_row.canonical_context
            assert session.scalar(select(func.count()).select_from(ReportRetentionWorkModel)) == 0
            chunk_count = session.scalar(select(func.count()).select_from(ReportInputChunkModel))
            assert chunk_count and chunk_count > 0
            audit_before = tuple(
                session.execute(
                    select(
                        AuditEventModel.id, AuditEventModel.action, AuditEventModel.safe_metadata
                    )
                    .where(
                        AuditEventModel.resource_id.in_(
                            str(a.artifact_id) for a in status.artifacts
                        )
                    )
                    .order_by(AuditEventModel.id)
                )
            )
            assert len(audit_before) == 3
        assert [event[1] for event in lifecycle_events(status.job_id, input_id)] == [
            "report.job.created",
            "report.job.completed",
        ]

        # The requesting session remains current. The exact application error
        # therefore proves report expiry, independently of principal/grant TTL.
        at[0] = expiry + timedelta(microseconds=1)
        current = replace(
            principal,
            authenticated_at=at[0] - timedelta(seconds=1),
            expires_at=at[0] + timedelta(hours=1),
        )
        with case.base.sessions() as session, session.begin():
            authorize_report_request(
                session,
                current,
                account_id=case.account_id,
                required_scopes=report_scopes(detail=True),
                now=at[0],
            )
        expired = await case.service.get_report_status(current, case.account_id, status.job_id)
        assert expired.state is ReportJobState.EXPIRED and expired.context is None
        assert expired.manifest_digest == status.manifest_digest
        for operation in (
            lambda: case.service.get_report_manifest(current, case.account_id, status.job_id),
            lambda: case.service.create_report_download_grant(
                current, case.account_id, status.job_id, status.artifacts[0].artifact_id
            ),
            lambda: case.service.download_report_artifact(
                current,
                case.account_id,
                status.job_id,
                status.artifacts[0].artifact_id,
                grant_token=grants[0].token,
            ),
        ):
            with pytest.raises(app.ReportServiceError) as error:
                await operation()
            assert error.value.code is app.ReportServiceErrorCode.ARTIFACT_EXPIRED
        with case.base.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportArtifactModel)
                    .where(ReportArtifactModel.contents.is_not(None))
                )
                == 2
            )
            assert session.scalar(select(func.count()).select_from(ArtifactDownloadGrantModel)) == 2
            assert session.scalar(select(func.count()).select_from(ReportRetentionWorkModel)) == 0

        # PostgreSQL CURRENT_TIMESTAMP is transaction-start time. Observe the
        # genuine deadline, then open a fresh transaction for every bounded pass.
        remaining = max(0, (expiry - database_now()).total_seconds())
        assert remaining <= 45
        await asyncio.sleep(remaining + 0.05)
        cleanup_at = database_now()
        assert cleanup_at >= expiry
        with (
            case.base.sessions() as session,
            session.begin(),
            pytest.raises(ValueError, match="one hundred"),
        ):
            expire_report_payloads(session, at=cleanup_at, limit=101)
        completed = []
        for remaining_artifacts in (1, 0):
            with case.base.sessions() as session, session.begin():
                completed.append(expire_report_payloads(session, at=database_now(), limit=1))
            with case.base.sessions() as session:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(ReportArtifactModel)
                        .where(ReportArtifactModel.contents.is_not(None))
                    )
                    == remaining_artifacts
                )
                assert (
                    session.scalar(select(func.count()).select_from(ArtifactDownloadGrantModel))
                    == remaining_artifacts
                )
                work = session.scalar(select(ReportRetentionWorkModel))
                assert work is not None and work.reason == "ttl"
                assert (work.completed_at is None) is bool(remaining_artifacts)
        assert completed == [0, 1]
        audit_after = lifecycle_events(status.job_id, input_id)
        assert [event[1] for event in audit_after] == [
            "report.job.created",
            "report.job.completed",
            "report.job.expired",
            "report.input.purged",
        ]
        assert [event[2] for event in audit_after] == [None, None, None, {"reason": "ttl"}]
        with case.base.sessions() as session:
            job = session.get(ReportJobModel, status.job_id)
            assert job is not None and job.state == "expired"
            assert job.requested_at == created and job.expires_at == expiry
            assert job.manifest_digest == status.manifest_digest
            assert job.lease_id is None and job.consumer_id is None
            input_row = session.get(ReportInputSnapshotModel, input_id)
            assert input_row is not None and input_row.purged_at is not None
            assert input_row.canonical_manifest is None and input_row.canonical_context is None
            chunks = tuple(session.scalars(select(ReportInputChunkModel)))
            assert len(chunks) == chunk_count
            assert all(row.payload is None and row.purged_at is not None for row in chunks)
            manifest = session.scalar(select(ReportManifestModel))
            assert manifest is not None and manifest.payload is None and manifest.purged_at
            artifacts = tuple(session.scalars(select(ReportArtifactModel)))
            assert all(row.contents is None and row.purged_at is not None for row in artifacts)
            assert {row.content_digest for row in artifacts} == {
                row.content_digest for row in status.artifacts
            }
            outbox = session.scalar(select(ReportDispatchOutboxModel))
            assert outbox is not None and outbox.state == "dead_letter"
            assert outbox.claim_token is None and outbox.dispatcher_id is None
            work = session.scalar(select(ReportRetentionWorkModel))
            assert work is not None
            retained_work = (work.id, work.created_at, work.started_at, work.completed_at)
            assert (
                tuple(
                    session.execute(
                        select(
                            AuditEventModel.id,
                            AuditEventModel.action,
                            AuditEventModel.safe_metadata,
                        )
                        .where(
                            AuditEventModel.resource_id.in_(
                                str(a.artifact_id) for a in status.artifacts
                            )
                        )
                        .order_by(AuditEventModel.id)
                    )
                )
                == audit_before
            )
        for _ in range(2):
            with case.base.sessions() as session, session.begin():
                assert expire_report_payloads(session, at=database_now(), limit=1) == 0
            with case.base.sessions() as session:
                work = session.scalar(select(ReportRetentionWorkModel))
                assert work is not None
                assert (
                    work.id,
                    work.created_at,
                    work.started_at,
                    work.completed_at,
                ) == retained_work
                assert (
                    session.scalar(select(func.count()).select_from(ArtifactDownloadGrantModel))
                    == 0
                )
            assert lifecycle_events(status.job_id, input_id) == audit_after
        tombstone = await case.service.get_report_status(current, case.account_id, status.job_id)
        assert tombstone.state is ReportJobState.EXPIRED and tombstone.context is None
        assert tombstone.manifest_digest == status.manifest_digest
        assert tombstone.artifacts == status.artifacts

    asyncio.run(run())
