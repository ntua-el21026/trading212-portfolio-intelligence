"""Seven canonical export producers use actual jobs, workers and private downloads."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from uuid import UUID, uuid4
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.planning import calculate_contribution_plan
from trading212_application import report_jobs as jobs
from trading212_application import reports as app
from trading212_application import xray
from trading212_application.planning_jobs import PlanTaskMessage
from trading212_domain import CurrencyCode, build_synthetic_identity
from trading212_domain import historical_results as h
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import (
    canonical_report_cell_value,
    decode_report_chunk,
    decode_report_manifest,
    decode_report_row,
    encode_report_manifest,
    report_table_digest,
)
from trading212_domain.report_schema import report_tables, table_schema
from trading212_persistence import PostgresPlanningService
from trading212_persistence.models import SnapshotPositionModel
from trading212_persistence.planning_models import ContributionPlanResultModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import (
    ExportJobModel,
    ReportInputChunkModel,
    ReportInputSnapshotModel,
)
from trading212_persistence.report_service import PostgresReportService
from trading212_persistence.target_service import PostgresTargetService
from trading212_security.principals import Principal, Scope
from trading212_worker.historical_seed import CURSOR_KEY, history_principal
from trading212_worker.report_tasks import ReportExecutionState, execute_export_message

from tests.integration.report_history_cases import HISTORY_CUTOFF, history_report_case
from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.integration.test_planning_postgres import command_input
from tests.integration.test_planning_postgres import planning_database as planning_database
from tests.integration.test_report_postgres import ReportCase
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_report_type_matrix_postgres import (
    DownloadedReport,
    _retained_calculation,
    _snapshot_parity,
    _tabular_values,
)
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def _tabular_artifact(report: DownloadedReport, format: r.ExportFormat, content: bytes) -> None:
    if format is r.ExportFormat.CSV:
        parsed = list(csv.DictReader(StringIO(content.decode(), newline="")))
        fragments = [row["value"][5:] for row in parsed if row["section"] == "manifest"]
        records = [row for row in parsed if row["section"] != "manifest"]
        # Decode only the documented CSV text prefix; preserve the original text.
        expected = {
            (table.value, row.key, column.key): canonical_report_cell_value(cell)
            for table, rows in report.tables.items()
            for row in rows
            for column, cell in zip(table_schema(table).columns, row.cells, strict=True)
        }
        for record in records:
            if record["section"] == "proof":
                continue
            value = expected[(record["table"], record["row_key"], record["column_key"])]
            assert record["value"] in {value, "'" + value}
            if record["cell_kind"] in {"decimal", "integer", "boolean"}:
                assert record["value"] == value
            record["value"] = value
    else:
        assert format is r.ExportFormat.XLSX
        namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        fragments, records = [], []
        with ZipFile(BytesIO(content)) as archive:
            assert not any(
                "externalLink" in name or "vbaProject" in name for name in archive.namelist()
            )
            for name in archive.namelist():
                if not name.startswith("xl/worksheets/sheet"):
                    continue
                sheet = ElementTree.fromstring(archive.read(name))  # noqa: S314 - actual synthetic generated artifact
                assert not sheet.findall(".//s:f", namespace) and not sheet.findall(
                    ".//s:hyperlink", namespace
                )
                values = [
                    [node.text or "" for node in row.findall("s:c/s:is/s:t", namespace)]
                    for row in sheet.findall("s:sheetData/s:row", namespace)
                ]
                assert values
                if values[0][0] == "Fragment ordinal":
                    assert all(row[1].startswith("json:") for row in values[1:])
                    fragments.extend(row[1][5:] for row in values[1:])
                else:
                    records.extend(dict(zip(values[0], row, strict=True)) for row in values[1:])
    assert fragments and "".join(fragments).encode() == encode_report_manifest(report.manifest)
    _tabular_values(report, records)


async def _export(
    sessions: sessionmaker[Session],
    service: PostgresReportService,
    store: PostgresReportJobStore,
    principal: Principal,
    selection: r.ExportSelection,
) -> DownloadedReport:
    pending = await service.create_export(
        principal, app.CreateExportCommand(selection=selection, idempotency_key=uuid4().hex)
    )
    assert pending.state is r.ReportJobState.QUEUED and pending.context is not None
    with sessions() as session:
        job = session.get(ExportJobModel, pending.export_id)
        assert job is not None
        message = jobs.ExportTaskMessage(
            job_id=job.id,
            owner_id=job.owner_id,
            account_id=job.account_id,
            capture_id=job.input_id,
            input_digest=job.input_digest,
        )
    outcome = await execute_export_message(store, message, consumer_id="export-producer-matrix")
    status = await service.get_export_status(principal, selection.account_id, pending.export_id)
    assert outcome is ReportExecutionState.COMPLETED, (outcome, status.failure_code)
    assert status.state is r.ReportJobState.SUCCEEDED and len(status.artifacts) == 1
    assert (status.dataset, status.field_set, status.format) == (
        selection.dataset,
        selection.field_set,
        selection.format,
    )
    artifact = status.artifacts[0]
    grant = await service.create_export_download_grant(
        principal, selection.account_id, status.export_id, artifact.artifact_id
    )
    downloaded = await service.download_export_artifact(
        principal,
        selection.account_id,
        status.export_id,
        artifact.artifact_id,
        grant_token=grant.token,
    )
    assert downloaded.metadata == artifact
    assert artifact.format.value == selection.format.value
    assert artifact.mime_type is r.report_mime_type(selection.format)
    assert 0 < len(downloaded.content) == artifact.byte_length <= r.MAX_REPORT_ARTIFACT_BYTES
    assert hashlib.sha256(downloaded.content).hexdigest() == artifact.content_digest
    assert grant.token.encode() not in downloaded.content
    with sessions() as session:
        capture = session.get(ReportInputSnapshotModel, message.capture_id)
        assert capture is not None and capture.canonical_manifest is not None
        payload = capture.canonical_manifest
        assert hashlib.sha256(payload).hexdigest() == status.manifest_digest
        manifest = decode_report_manifest(payload)
        tables: dict[r.ReportTableKey, list[r.ReportRow]] = defaultdict(list)
        for saved in session.scalars(
            select(ReportInputChunkModel)
            .where(ReportInputChunkModel.input_id == message.capture_id)
            .order_by(ReportInputChunkModel.table_key, ReportInputChunkModel.ordinal)
        ):
            assert saved.payload is not None
            chunk = decode_report_chunk(saved.payload)
            tables[chunk.table].extend(chunk.rows)
    rows = {
        descriptor.table: tuple(tables.pop(descriptor.table, []))
        for descriptor in manifest.document.tables
    }
    assert not tables and manifest.document.selection == selection
    assert set(report_tables(selection)) <= set(rows)
    for descriptor in manifest.document.tables:
        assert len(rows[descriptor.table]) == descriptor.row_count
        assert (
            report_table_digest(descriptor.table, rows[descriptor.table])
            == descriptor.content_digest
        )
    report = DownloadedReport(
        manifest, rows, {r.ReportFormat(selection.format.value): downloaded.content}
    )
    assert manifest.bindings and manifest.contexts and manifest.source_references
    if selection.format is r.ExportFormat.JSON:
        decoded = json.loads(downloaded.content)
        assert decoded["schema"] == "report_document_json_v1"
        assert decode_report_manifest(_json_bytes(decoded["manifest"])) == manifest
        assert decoded["header"] == decoded["manifest"]["document"]
        actual = {
            r.ReportTableKey(table["table"]): tuple(
                decode_report_row(_json_bytes(row)) for row in table["rows"]
            )
            for table in decoded["tables"]
        }
        assert len(actual) == len(decoded["tables"]) and actual == rows
    else:
        _tabular_artifact(report, selection.format, downloaded.content)
    return report


def test_positions_and_xray_exports_include_real_values_and_all_three_formats(
    report_case: ReportCase,
) -> None:
    async def run() -> None:
        case = report_case
        request = case.selection()
        selection = r.ExportSelection(
            account_id=request.account_id,
            snapshot_id=request.snapshot_id,
            start_date=request.start_date,
            end_date=request.end_date,
            source_cutoff_at=request.source_cutoff_at,
            reporting_currency=request.reporting_currency,
            dataset=r.ExportDataset.POSITIONS,
            field_set=r.ExportFieldSet.STANDARD,
            format=r.ExportFormat.JSON,
        )
        for format, field_set in (
            (r.ExportFormat.JSON, r.ExportFieldSet.STANDARD),
            (r.ExportFormat.XLSX, r.ExportFieldSet.STANDARD),
            (r.ExportFormat.CSV, r.ExportFieldSet.AUDIT),
        ):
            report = await _export(
                case.base.sessions,
                case.service,
                case.jobs,
                case.principal,
                replace(selection, format=format, field_set=field_set),
            )
            await _snapshot_parity(case.base.sessions, case.principal, report)
            positions = report.rows(r.ReportTableKey.POSITIONS)
            with case.base.sessions() as session:
                original = {
                    str(item.id): item
                    for item in session.scalars(
                        select(SnapshotPositionModel).where(
                            SnapshotPositionModel.snapshot_id == selection.snapshot_id
                        )
                    )
                }
                assert positions and {row["position_id"].value for row in positions} == set(
                    original
                )
                for row in positions:
                    saved = original[str(row["position_id"].value)]
                    assert row["quantity"].value == saved.quantity
                    assert row["market_value"].value == saved.market_value
                    assert row["market_value"].currency == CurrencyCode(saved.currency)
        report = await _export(
            case.base.sessions,
            case.service,
            case.jobs,
            case.principal,
            replace(selection, dataset=r.ExportDataset.XRAY, field_set=r.ExportFieldSet.AUDIT),
        )
        run_id = next(
            pin.subject_id
            for pin in report.manifest.bindings
            if pin.family is r.ReportFamily.XRAY and pin.role is r.ReportInputRole.RESULT
        )
        canonical = await case.base.service.get_effective_exposure(
            case.principal,
            str(case.account_id),
            query=xray.EffectiveExposureQuery(request=case.base.request(str(run_id))),
        )
        assert isinstance(canonical, xray.ExposuresView)
        summary = report.rows(r.ReportTableKey.XRAY_SUMMARY)[0]
        assert canonical.summary.total.value is not None
        assert summary["total"].value == canonical.summary.total.value.amount == Decimal("1000")
        assert (
            summary["duplicated_exposure"].value
            == canonical.summary.duplicated_exposure.value
            == Decimal("0.41")
        )
        assert (
            report.tables[r.ReportTableKey.XRAY_PATHS]
            and report.tables[r.ReportTableKey.XRAY_OVERLAP_PAIRS]
        )
        assert report.manifest.license_references
        with pytest.raises(DomainError):
            replace(selection, dataset=r.ExportDataset.ALERTS, constituent_snapshot_id=uuid4())

    asyncio.run(run())


def test_activity_dividends_performance_and_targets_exports_match_canonical_producers(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
) -> None:
    async def run() -> None:
        case = history_report_case(*seeded_history)
        for dataset, field_set in (
            (r.ExportDataset.ACTIVITY, r.ExportFieldSet.AUDIT),
            (r.ExportDataset.DIVIDENDS, r.ExportFieldSet.STANDARD),
            (r.ExportDataset.PERFORMANCE, r.ExportFieldSet.STANDARD),
            (r.ExportDataset.TARGETS, r.ExportFieldSet.AUDIT),
        ):
            selection = r.ExportSelection(
                account_id=case.account_id,
                snapshot_id=case.snapshot_id,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                source_cutoff_at=HISTORY_CUTOFF,
                reporting_currency=CurrencyCode("EUR"),
                dataset=dataset,
                field_set=field_set,
                format=r.ExportFormat.JSON,
                target_version_id=case.target_version_id
                if dataset is r.ExportDataset.TARGETS
                else None,
            )
            report = await _export(
                case.sessions, case.service, case.jobs, case.principal, selection
            )
            if dataset is r.ExportDataset.TARGETS:
                target = await PostgresTargetService(
                    sessions=case.sessions, cursor_signing_key=CURSOR_KEY
                ).get_target_version(case.principal, str(case.target_version_id))
                nodes = report.rows(r.ReportTableKey.TARGET_NODES)
                assert len(nodes) == len(target.content.nodes)
                assert {row["node_key"].value: row["target_weight"].value for row in nodes} == {
                    node.key: node.weight for node in target.content.nodes
                }
                assert any(
                    pin.subject_id == case.target_version_id
                    and pin.content_digest == target.content_digest
                    for pin in report.manifest.bindings
                )
                continue
            assert (
                report.manifest.license_references
                and report.tables[r.ReportTableKey.HISTORICAL_SOURCE_DETAILS]
            )
            if dataset is r.ExportDataset.ACTIVITY:
                canonical = _retained_calculation(case, report, r.ReportFamily.CASH_FLOWS)
                assert isinstance(canonical, h.CashFlowCalculation)
                rows = report.rows(r.ReportTableKey.ACTIVITY)
                assert rows and {row["revision_id"].value for row in rows} == {
                    event.event_revision_id for event in canonical.events
                }
                assert len(rows) == len(canonical.events)
                events = {event.event_revision_id: event for event in canonical.events}
                for row in rows:
                    event = events[str(row["revision_id"].value)]
                    assert row["occurred_at"].value == event.economic_at
                    assert row["correction_of"].value == event.correction_of
                    assert row["amount"].value == (
                        event.native_amount.value.amount
                        if event.native_amount.value is not None
                        else None
                    )
                    assert row["amount"].state.value == event.native_amount.availability.value
            elif dataset is r.ExportDataset.DIVIDENDS:
                canonical = _retained_calculation(case, report, r.ReportFamily.INCOME)
                assert isinstance(canonical, h.IncomeCalculation)
                rows = report.rows(r.ReportTableKey.DIVIDENDS)
                assert rows and {row["revision_id"].value for row in rows} == {
                    event.event_revision_id for event in canonical.events
                }
                assert len(rows) == len(canonical.events)
                events = {event.event_revision_id: event for event in canonical.events}
                for row in rows:
                    event = events[str(row["revision_id"].value)]
                    assert row["paid_on"].value == event.economic_at.date()
                    assert event.native_amount.value is not None
                    assert row["net"].value == event.native_amount.value.amount
                    assert row["net"].currency == event.native_amount.value.currency
            else:
                canonical = _retained_calculation(case, report, r.ReportFamily.PERFORMANCE)
                assert isinstance(canonical, h.PerformanceCalculation)
                points = report.rows(r.ReportTableKey.PERFORMANCE_POINTS)
                assert len(points) == len(canonical.points) == 12
                assert [row["portfolio_value"].value for row in points] == [
                    point.portfolio_value.value.amount
                    if point.portfolio_value.value is not None
                    else None
                    for point in canonical.points
                ]
                assert report.rows(r.ReportTableKey.PERFORMANCE_SUMMARY)[0][
                    "ending_value"
                ].value == Decimal("2191.280575")

    asyncio.run(run())


def test_plan_export_uses_a_real_finalized_revision_and_complete_audit_operands(
    planning_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    async def run() -> None:
        _, sessions = planning_database
        principal = history_principal(datetime.now(UTC))
        with sessions() as session, session.begin():
            provision_principal_scopes(
                session,
                principal_id=UUID(principal.principal_id),
                scopes=frozenset(Scope),
                now=datetime.now(UTC) - timedelta(seconds=1),
            )
        planner = PostgresPlanningService(sessions=sessions, cursor_signing_key=CURSOR_KEY)
        command = command_input(sessions)
        job = await planner.create_contribution_plan(
            principal, command, idempotency_key=uuid4().hex, correlation_id="export-plan-producer"
        )
        claim = await planner.claim_plan_job(
            PlanTaskMessage(
                job.job_id, job.request_id, principal.owner_id, job.account_id, job.input_digest
            ),
            consumer_id="export-plan-producer",
        )
        assert claim is not None
        canonical = calculate_contribution_plan(await planner.load_plan_job_input(claim))
        assert await planner.complete_plan_job(claim, canonical)
        with sessions() as session:
            revision = session.scalar(
                select(ContributionPlanResultModel).where(
                    ContributionPlanResultModel.request_id == UUID(job.request_id)
                )
            )
            assert revision is not None
            revision_id = revision.id
        cutoff = datetime.now(UTC)
        selection = r.ExportSelection(
            account_id=build_synthetic_identity().account.id,
            snapshot_id=UUID(command.snapshot_id),
            start_date=cutoff.date(),
            end_date=cutoff.date(),
            source_cutoff_at=cutoff,
            reporting_currency=CurrencyCode("EUR"),
            dataset=r.ExportDataset.PLANS,
            field_set=r.ExportFieldSet.AUDIT,
            format=r.ExportFormat.JSON,
            target_version_id=UUID(command.target_version_id),
            plan_revision_id=revision_id,
        )
        report = await _export(
            sessions,
            PostgresReportService(sessions, cursor_signing_key=CURSOR_KEY),
            PostgresReportJobStore(sessions),
            principal,
            selection,
        )
        summary = report.rows(r.ReportTableKey.PLAN_SUMMARY)[0]
        assert summary["plan_revision_id"].value == str(revision_id)
        assert summary["execution_allowed"].value is False
        assert summary["contribution"].value == Decimal("20")
        lines = report.rows(r.ReportTableKey.PLAN_LINES)
        assert len(lines) == len(canonical.lines)
        assert {row["node_key"].value: row["recommended_amount"].value for row in lines} == {
            line.node_key: line.recommended_amount.amount for line in canonical.lines
        }
        assert report.tables[r.ReportTableKey.PLAN_INPUT_HEADER]
        assert report.tables[r.ReportTableKey.PLAN_VALUATION_POSITIONS]
        assert r.ReportTableKey.DRIFT_TOTALS in report.tables

    asyncio.run(run())
