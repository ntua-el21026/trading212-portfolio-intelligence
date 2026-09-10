"""Real historical account pins shared by report integration journeys."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import report_jobs as jobs
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.values import CurrencyCode
from trading212_persistence.models import PortfolioSnapshotModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import ReportInputSnapshotModel, ReportJobModel
from trading212_persistence.report_service import PostgresReportService
from trading212_security.principals import Principal, Scope
from trading212_worker.historical_seed import CURSOR_KEY, history_principal
from trading212_worker.report_tasks import ReportExecutionState, execute_report_message

HISTORY_CUTOFF = datetime(2026, 9, 8, tzinfo=UTC)


@dataclass(frozen=True)
class HistoryReportCase:
    sessions: sessionmaker[Session]
    principal: Principal
    account_id: UUID
    snapshot_id: UUID
    benchmark_version_id: UUID
    target_version_id: UUID
    service: PostgresReportService
    jobs: PostgresReportJobStore

    def selection(
        self,
        report_type: r.ReportType,
        sections: tuple[r.ReportSection, ...],
        *,
        start_date: date = date(2025, 1, 1),
        end_date: date = date(2025, 12, 31),
        plan_revision_id: UUID | None = None,
    ) -> r.ReportSelection:
        return r.ReportSelection(
            account_id=self.account_id,
            snapshot_id=self.snapshot_id,
            start_date=start_date,
            end_date=end_date,
            source_cutoff_at=HISTORY_CUTOFF,
            reporting_currency=CurrencyCode("EUR"),
            report_type=report_type,
            sections=sections,
            formats=(r.ReportFormat.JSON,),
            benchmark_version_id=self.benchmark_version_id
            if r.ReportSection.BENCHMARK in sections
            else None,
            target_version_id=self.target_version_id
            if set(sections)
            & {r.ReportSection.TARGETS, r.ReportSection.DRIFT, r.ReportSection.CONTRIBUTION_PLAN}
            else None,
            plan_revision_id=plan_revision_id,
        )

    async def complete(self, selection: r.ReportSelection) -> app.ReportJobStatus:
        pending = await self.service.generate_report(
            self.principal,
            app.GenerateReportCommand(selection=selection, idempotency_key=str(uuid4())),
        )
        with self.sessions() as session:
            row = session.get(ReportJobModel, pending.job_id)
            assert row is not None
            message = jobs.ReportTaskMessage(
                job_id=row.id,
                owner_id=row.owner_id,
                account_id=row.account_id,
                capture_id=row.input_id,
                input_digest=row.input_digest,
            )
        outcome = await execute_report_message(
            self.jobs, message, consumer_id="report-history-test"
        )
        with self.sessions() as session:
            finished = session.get(ReportJobModel, pending.job_id)
            assert finished is not None
            captured = session.get(ReportInputSnapshotModel, finished.input_id)
            assert captured is not None
            assert outcome is ReportExecutionState.COMPLETED, (
                outcome,
                finished.failure_code,
                captured.canonical_byte_length,
                captured.chunk_count,
            )
        return await self.service.get_report_status(self.principal, self.account_id, pending.job_id)


def history_report_case(
    sessions: sessionmaker[Session], identifiers: dict[str, str]
) -> HistoryReportCase:
    now = datetime.now(UTC)
    principal = history_principal(now)
    account_id = UUID(identifiers["annual_account_id"])
    with sessions() as session, session.begin():
        provision_principal_scopes(
            session,
            principal_id=UUID(principal.principal_id),
            scopes=frozenset(Scope),
            now=now - timedelta(seconds=1),
        )
        snapshot = session.scalar(
            select(PortfolioSnapshotModel)
            .where(
                PortfolioSnapshotModel.broker_account_id == account_id,
                PortfolioSnapshotModel.source_cutoff_at <= HISTORY_CUTOFF,
            )
            .order_by(PortfolioSnapshotModel.valuation_at.desc(), PortfolioSnapshotModel.id)
            .limit(1)
        )
        assert snapshot is not None
        snapshot_id = snapshot.id
    return HistoryReportCase(
        sessions,
        principal,
        account_id,
        snapshot_id,
        UUID(identifiers["annual_benchmark_version_id"]),
        UUID(identifiers["annual_target_version_id"]),
        PostgresReportService(sessions, cursor_signing_key=CURSOR_KEY),
        PostgresReportJobStore(sessions),
    )
