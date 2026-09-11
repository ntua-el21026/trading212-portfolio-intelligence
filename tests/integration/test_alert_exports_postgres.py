"""Actual canonical alert jobs feed private exports with cutoff-stable lifecycle proof."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from trading212_application import alerts as app
from trading212_application import reports as reports_app
from trading212_domain import alerts as a
from trading212_domain import reports as r
from trading212_domain.report_schema import ALERT_EXPORT_TABLES, table_schema
from trading212_domain.sources import LicensePermission
from trading212_domain.values import CurrencyCode
from trading212_persistence.alert_job_store import PostgresAlertJobStore
from trading212_persistence.alert_models import AlertEvaluationJobModel
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.models import PortfolioSnapshotModel, SnapshotCashModel
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import (
    ExportArtifactModel,
    ExportJobModel,
    ReportInputSnapshotModel,
)
from trading212_persistence.report_service import PostgresReportService
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import Scope
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message
from trading212_worker.xray_source_fixture import xray_license

from tests.integration.test_alert_postgres import KEY, AlertCase
from tests.integration.test_alert_postgres import alert_case as alert_case
from tests.integration.test_alert_postgres import alert_database as alert_database
from tests.integration.test_report_exports_postgres import _export
from tests.integration.test_report_postgres import ReportCase
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_report_type_matrix_postgres import DownloadedReport
from tests.integration.test_xray_reads_postgres import company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _rows(report: DownloadedReport, table: r.ReportTableKey) -> list[dict[str, r.ReportCell]]:
    return [
        dict(zip((column.key for column in table_schema(table).columns), row.cells, strict=True))
        for row in report.tables[table]
    ]


def test_real_canonical_alert_exports_all_formats_keep_past_acknowledgment_and_resolution_out(
    alert_case: AlertCase,
) -> None:
    async def run() -> None:
        case = alert_case
        # Deliberately omit the persistence-test CaptureControl: this is the real
        # canonical source adapter over the existing immutable broker snapshot.
        service = PostgresAlertService(
            case.sessions, cursor_signing_key=KEY, clock=lambda: case.clock[0]
        )
        jobs = PostgresAlertJobStore(
            case.sessions, cursor_signing_key=KEY, clock=lambda: case.clock[0]
        )
        report_service = PostgresReportService(
            case.sessions, cursor_signing_key=KEY, clock=lambda: case.clock[0]
        )
        report_jobs = PostgresReportJobStore(case.sessions, clock=lambda: case.clock[0])
        definition = a.AlertRuleDefinition(
            name="Canonical export cash",
            quality_policy=a.AlertQualityPolicy.ALLOW_DEGRADED,
            predicate=a.AlertPredicate(
                family=a.AlertFamily.CASH_THRESHOLD,
                metric=a.AlertMetric.CASH_AMOUNT,
                comparison=a.AlertComparison.GT,
                threshold=Decimal("0"),
                currency=CurrencyCode("EUR"),
            ),
            schedule=a.AlertIntervalSchedule(anchor_at=case.clock[0]),
            remediation="Review the actual cash balance manually.",
        )
        rule = await service.create_rule(
            case.principal,
            app.CreateAlertRuleCommand(account_id=case.account_id, definition=definition),
            idempotency_key=uuid4().hex,
            correlation_id="alert-export-create",
        )
        await service.activate_rule(
            case.principal,
            rule.id,
            rule.latest_version.id,
            expected_revision=rule.revision,
            idempotency_key=uuid4().hex,
            correlation_id="alert-export-activate",
        )
        assert (await jobs.admit_due_evaluations()).admitted >= 1
        with case.sessions() as session:
            row = session.scalar(
                select(AlertEvaluationJobModel).where(AlertEvaluationJobModel.rule_id == rule.id)
            )
            assert row is not None
            message = jobs._evaluation_message(row)
        assert (
            await execute_alert_message(jobs, message, consumer_id="alert-export-canonical")
            is AlertExecutionState.COMPLETED
        )
        detail = await service.get_rule(case.principal, rule.id, query=app.AlertRuleDetailQuery())
        evaluation = detail.latest_evaluation
        assert evaluation is not None and evaluation.result is not None
        assert evaluation.outcome is a.AlertEvaluationOutcome.MATCHED
        observed = evaluation.result.observation
        assert observed is not None and observed.currency == CurrencyCode("EUR")
        snapshot_pin = next(
            pin
            for pin in evaluation.canonical_bindings
            if pin.family is a.AlertCanonicalFamily.VALUATION
            and pin.role is a.AlertInputRole.SNAPSHOT
        )
        with case.sessions() as session:
            snapshot = session.get(PortfolioSnapshotModel, snapshot_pin.subject_id)
            assert snapshot is not None
            cash = tuple(
                session.scalars(
                    select(SnapshotCashModel).where(SnapshotCashModel.snapshot_id == snapshot.id)
                )
            )
            assert cash and {value.currency for value in cash} == {"EUR"}
            assert observed.value == sum((value.amount for value in cash), Decimal("0"))
            snapshot_id, currency = snapshot.id, CurrencyCode(snapshot.reporting_currency)
        cutoff = case.clock[0]
        selection = r.ExportSelection(
            account_id=case.account_id,
            snapshot_id=snapshot_id,
            start_date=cutoff.date(),
            end_date=cutoff.date(),
            source_cutoff_at=cutoff,
            reporting_currency=currency,
            dataset=r.ExportDataset.ALERTS,
            field_set=r.ExportFieldSet.STANDARD,
            format=r.ExportFormat.JSON,
        )
        first = None
        for format in r.ExportFormat:
            selected = replace(
                selection,
                format=format,
                field_set=r.ExportFieldSet.AUDIT
                if format is r.ExportFormat.CSV
                else r.ExportFieldSet.STANDARD,
            )
            report = await _export(
                case.sessions, report_service, report_jobs, case.principal, selected
            )
            assert set(ALERT_EXPORT_TABLES) <= report.tables.keys()
            metric = next(
                row
                for row in _rows(report, r.ReportTableKey.ALERT_OBSERVATIONS)
                if row["evaluation_id"].value == str(evaluation.id)
            )
            assert metric["observed"].value == observed.value
            assert metric["observed"].currency == observed.currency
            assert metric["observed"].origin is r.ReportMetricOrigin(observed.origin.value)
            assert any(
                binding.family is r.ReportFamily.ALERTS
                and binding.subject_id == evaluation.id
                and binding.content_digest == evaluation.result_digest
                for binding in report.manifest.bindings
            )
            assert any(
                source.subject_id == snapshot_id for source in report.manifest.source_references
            )
            if format is r.ExportFormat.JSON:
                first = report
        assert first is not None
        events = await service.list_events(
            case.principal,
            query=app.AlertEventListQuery(account_id=case.account_id, rule_id=rule.id),
        )
        assert len(events.items) == 1
        event = events.items[0]
        assert _rows(first, r.ReportTableKey.ALERT_ACKNOWLEDGMENTS) == []
        case.clock[0] += timedelta(seconds=10)
        await service.acknowledge_event(
            case.principal,
            event.id,
            note="Reviewed after export cutoff",
            expected_revision=event.revision,
            idempotency_key=uuid4().hex,
            correlation_id="alert-export-ack",
        )
        acknowledged = await service.get_event(case.principal, event.id)
        await service.resolve_event(
            case.principal,
            event.id,
            note="Resolved after export cutoff",
            expected_revision=acknowledged.revision,
            idempotency_key=uuid4().hex,
            correlation_id="alert-export-resolve",
        )
        past = await _export(case.sessions, report_service, report_jobs, case.principal, selection)
        assert past.tables == first.tables
        assert past.manifest.document.document_digest == first.manifest.document.document_digest
        current = await _export(
            case.sessions,
            report_service,
            report_jobs,
            case.principal,
            replace(selection, source_cutoff_at=case.clock[0]),
        )
        projected = next(
            row
            for row in _rows(current, r.ReportTableKey.ALERT_EVENTS)
            if row["event_id"].value == str(event.id)
        )
        assert projected["episode_state"].value == "resolved"
        assert (
            _rows(current, r.ReportTableKey.ALERT_ACKNOWLEDGMENTS)[0]["note"].value
            == "Reviewed after export cutoff"
        )
        assert "revision" not in projected
        denied = replace(case.principal, scopes=case.principal.scopes - {Scope.ALERTS_READ})
        with pytest.raises(reports_app.ReportServiceError) as failure:
            await report_service.create_export(
                denied,
                reports_app.CreateExportCommand(selection=selection, idempotency_key=uuid4().hex),
            )
        assert failure.value.code is reports_app.ReportServiceErrorCode.ACCESS_DENIED
        # Advance only the injected clock. The original alert rows remain immutable;
        # a new seven-day report may retain their copied payload for only this last hour.
        case.clock[0] = evaluation.expires_at - timedelta(hours=1)
        await _export(case.sessions, report_service, report_jobs, case.principal, selection)
        with case.sessions() as session:
            late = session.scalar(
                select(ExportJobModel)
                .where(ExportJobModel.account_id == case.account_id)
                .order_by(ExportJobModel.created_at.desc())
                .limit(1)
            )
            assert late is not None
            copied = session.get(ReportInputSnapshotModel, late.input_id)
            artifact = session.scalar(
                select(ExportArtifactModel).where(ExportArtifactModel.job_id == late.id)
            )
            assert copied is not None and artifact is not None
            assert (
                copied.expires_at == late.expires_at == artifact.expires_at == evaluation.expires_at
            )

    asyncio.run(run())


def test_actual_licensed_xray_alert_export_denies_current_export_permission_before_decode(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        canonical = await company(case.base)
        at = datetime.now(UTC)
        clock = [at]
        service = PostgresAlertService(
            case.base.sessions, cursor_signing_key=KEY, clock=lambda: clock[0]
        )
        jobs = PostgresAlertJobStore(
            case.base.sessions, cursor_signing_key=KEY, clock=lambda: clock[0]
        )
        definition = a.AlertRuleDefinition(
            name="Licensed exact HHI export",
            quality_policy=a.AlertQualityPolicy.ALLOW_DEGRADED,
            predicate=a.AlertPredicate(
                family=a.AlertFamily.EFFECTIVE_COMPANY_CONCENTRATION,
                metric=a.AlertMetric.EFFECTIVE_HHI,
                comparison=a.AlertComparison.GT,
                threshold=Decimal("0"),
            ),
            schedule=a.AlertIntervalSchedule(anchor_at=at),
        )
        rule = await service.create_rule(
            case.principal,
            app.CreateAlertRuleCommand(account_id=case.account_id, definition=definition),
            idempotency_key=uuid4().hex,
            correlation_id="licensed-export-create",
        )
        await service.activate_rule(
            case.principal,
            rule.id,
            rule.latest_version.id,
            expected_revision=rule.revision,
            idempotency_key=uuid4().hex,
            correlation_id="licensed-export-activate",
        )
        assert (await jobs.admit_due_evaluations()).admitted == 1
        with case.base.sessions() as session:
            row = session.scalar(
                select(AlertEvaluationJobModel).where(AlertEvaluationJobModel.rule_id == rule.id)
            )
            assert row is not None
            message = jobs._evaluation_message(row)
        assert (
            await execute_alert_message(jobs, message, consumer_id="licensed-export")
            is AlertExecutionState.COMPLETED
        )
        detail = await service.get_rule(case.principal, rule.id, query=app.AlertRuleDetailQuery())
        evaluation = detail.latest_evaluation
        assert evaluation is not None and evaluation.result is not None and evaluation.licenses
        observed = evaluation.result.observation
        assert observed is not None and observed.value == canonical.summary.hhi.value == Decimal(
            "0.4657"
        )
        request = case.selection()
        selection = r.ExportSelection(
            account_id=case.account_id,
            snapshot_id=request.snapshot_id,
            start_date=at.date(),
            end_date=at.date(),
            source_cutoff_at=at,
            reporting_currency=request.reporting_currency,
            dataset=r.ExportDataset.ALERTS,
            field_set=r.ExportFieldSet.AUDIT,
            format=r.ExportFormat.JSON,
        )
        report = await _export(
            case.base.sessions, case.service, case.jobs, case.principal, selection
        )
        assert report.manifest.license_references
        assert any(
            source.kind is r.ReportSourceKind.CONSTITUENT_SNAPSHOT
            for source in report.manifest.source_references
        )
        metric = _rows(report, r.ReportTableKey.ALERT_OBSERVATIONS)[0]["observed"]
        assert metric.value == observed.value
        sources = PostgresSourceService(sessions=case.base.sessions, cursor_signing_key=KEY)
        key = str(uuid4())
        await sources.register_source_license(
            case.principal,
            replace(
                xray_license(),
                id=key,
                version=key,
                effective_at=datetime.now(UTC),
                export=LicensePermission.DENIED,
            ),
            idempotency_key=key,
            correlation_id="deny-alert-export",
        )
        statements: list[str] = []

        def observe(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _many: object,
        ) -> None:
            statements.append(statement)

        event.listen(case.base.engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(reports_app.ReportServiceError) as denied:
                await case.service.create_export(
                    case.principal,
                    reports_app.CreateExportCommand(
                        selection=selection, idempotency_key=uuid4().hex
                    ),
                )
            assert denied.value.code is reports_app.ReportServiceErrorCode.ACCESS_DENIED
            assert not any(
                "SELECT alert_input_snapshots.payload" in statement
                or "SELECT alert_evaluations.payload" in statement
                for statement in statements
            )
        finally:
            event.remove(case.base.engine, "before_cursor_execute", observe)

    asyncio.run(run())
