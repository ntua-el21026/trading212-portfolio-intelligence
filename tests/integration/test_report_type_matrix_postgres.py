"""All ten report types use real captures, workers and private artifact downloads."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from uuid import UUID, uuid4
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from pypdf import PdfReader
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.planning import calculate_contribution_plan
from trading212_application import historical as history
from trading212_application import planning, report_jobs, xray
from trading212_application import reports as app
from trading212_application.planning_jobs import PlanTaskMessage
from trading212_domain import CurrencyCode, build_synthetic_identity
from trading212_domain import historical as h
from trading212_domain import reports as r
from trading212_domain import xray as xd
from trading212_domain.historical_results import (
    HistoricalCalculation,
    HistoricalObservationUse,
    IncomeCalculation,
    PerformanceCalculation,
)
from trading212_domain.historical_serialization import historical_result_from_json
from trading212_domain.report_manifest import (
    canonical_report_cell_value,
    decode_report_manifest,
    decode_report_row,
    encode_report_manifest,
    encode_report_schema,
    report_table_digest,
)
from trading212_domain.report_schema import report_tables, table_schema
from trading212_persistence import PostgresPlanningService, PostgresPortfolioService
from trading212_persistence.historical_models import HistoricalRunModel
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_persistence.planning_models import AnalyticsRunModel, ContributionPlanResultModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import ReportJobModel
from trading212_persistence.report_service import PostgresReportService
from trading212_persistence.target_models import TargetVersionModel
from trading212_security.principals import Principal, Scope
from trading212_worker.historical_seed import CURSOR_KEY, history_principal
from trading212_worker.report_tasks import ReportExecutionState, execute_report_message

from tests.integration.report_history_cases import HistoryReportCase, history_report_case
from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.integration.test_planning_postgres import command_input
from tests.integration.test_planning_postgres import planning_database as planning_database
from tests.integration.test_report_postgres import ReportCase, finish, generate
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration

_CALENDAR_SECTIONS = (
    r.ReportSection.OVERVIEW,
    r.ReportSection.ALLOCATION,
    r.ReportSection.PERFORMANCE,
    r.ReportSection.INCOME,
    r.ReportSection.CASH_FLOWS,
    r.ReportSection.QUALITY,
)
_HISTORY_CASES = (
    (r.ReportType.MONTHLY, _CALENDAR_SECTIONS, date(2025, 12, 1), date(2025, 12, 31)),
    (r.ReportType.QUARTERLY, _CALENDAR_SECTIONS, date(2025, 10, 1), date(2025, 12, 31)),
    (r.ReportType.ANNUAL, _CALENDAR_SECTIONS, date(2025, 1, 1), date(2025, 12, 31)),
    (
        r.ReportType.PERFORMANCE_BENCHMARK,
        (
            r.ReportSection.OVERVIEW,
            r.ReportSection.PERFORMANCE,
            r.ReportSection.BENCHMARK,
            r.ReportSection.QUALITY,
        ),
        date(2025, 1, 1),
        date(2025, 12, 31),
    ),
    (
        r.ReportType.DIVIDEND_INCOME,
        (
            r.ReportSection.OVERVIEW,
            r.ReportSection.INCOME,
            r.ReportSection.CASH_FLOWS,
            r.ReportSection.QUALITY,
        ),
        date(2025, 1, 1),
        date(2025, 12, 31),
    ),
    (
        r.ReportType.TARGET_DRIFT,
        (
            r.ReportSection.OVERVIEW,
            r.ReportSection.TARGETS,
            r.ReportSection.DRIFT,
            r.ReportSection.QUALITY,
        ),
        date(2025, 1, 1),
        date(2025, 12, 31),
    ),
    (
        r.ReportType.QUALITY_RECONCILIATION,
        (r.ReportSection.OVERVIEW, r.ReportSection.QUALITY, r.ReportSection.ACTIVITY),
        date(2025, 1, 1),
        date(2025, 12, 31),
    ),
)


@dataclass(frozen=True)
class DownloadedReport:
    manifest: r.ReportManifest
    tables: dict[r.ReportTableKey, tuple[r.ReportRow, ...]]
    artifacts: dict[r.ReportFormat, bytes]
    csv_records: tuple[dict[str, str], ...] = ()
    pdf_text: str = ""
    pdf_first_page: str = ""

    def rows(self, key: r.ReportTableKey) -> tuple[dict[str, r.ReportCell], ...]:
        return tuple(
            dict(
                zip(
                    (column.key for column in table_schema(key).columns),
                    (
                        replace(cell, context_key=cell.context_key or row.context_key)
                        for cell in row.cells
                    ),
                    strict=True,
                )
            )
            for row in self.tables[key]
        )


def _canonical(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


async def _download(
    service: PostgresReportService,
    principal: Principal,
    account_id: UUID,
    status: app.ReportJobStatus,
) -> DownloadedReport:
    assert status.state is r.ReportJobState.SUCCEEDED
    assert status.context is not None and status.artifacts
    assert len(status.artifacts) == len(r.ReportFormat)
    manifest = await service.get_report_manifest(principal, account_id, status.job_id)
    assert hashlib.sha256(encode_report_manifest(manifest)).hexdigest() == status.manifest_digest
    artifacts: dict[r.ReportFormat, bytes] = {}
    for metadata in status.artifacts:
        grant = await service.create_report_download_grant(
            principal, account_id, status.job_id, metadata.artifact_id
        )
        artifact = await service.download_report_artifact(
            principal, account_id, status.job_id, metadata.artifact_id, grant_token=grant.token
        )
        assert artifact.metadata == metadata
        assert metadata.mime_type is r.report_mime_type(metadata.format)
        assert 0 < len(artifact.content) == metadata.byte_length <= 10 * 1024 * 1024
        assert hashlib.sha256(artifact.content).hexdigest() == metadata.content_digest
        assert grant.token.encode() not in artifact.content
        artifacts[metadata.format] = artifact.content
    assert sum(map(len, artifacts.values())) <= 25 * 1024 * 1024
    decoded = json.loads(artifacts[r.ReportFormat.JSON])
    assert decoded["schema"] == "report_document_json_v1"
    assert decode_report_manifest(_canonical(decoded["manifest"])) == manifest
    assert decoded["header"] == decoded["manifest"]["document"]
    tables = {
        r.ReportTableKey(item["table"]): tuple(
            decode_report_row(_canonical(row)) for row in item["rows"]
        )
        for item in decoded["tables"]
    }
    assert len(tables) == len(decoded["tables"]) == len(manifest.document.tables)
    assert set(report_tables(manifest.document.selection)) <= set(tables)
    for descriptor in manifest.document.tables:
        rows = tables[descriptor.table]
        assert len(rows) == descriptor.row_count
        assert report_table_digest(descriptor.table, rows) == descriptor.content_digest
    assert manifest.bindings and manifest.contexts and manifest.source_references
    reference_keys = {reference.key for reference in manifest.source_references}
    assert manifest.source_memberships
    assert all(member.source_key in reference_keys for member in manifest.source_memberships)
    return _checked_formats(DownloadedReport(manifest, tables, artifacts))


async def _snapshot_parity(
    sessions: sessionmaker[Session], principal: Principal, report: DownloadedReport
) -> None:
    selection = report.manifest.document.selection
    canonical = await PostgresPortfolioService(
        sessions=sessions, cursor_signing_key=CURSOR_KEY
    ).get_snapshot_detail(principal, str(selection.account_id), str(selection.snapshot_id))
    row = report.rows(r.ReportTableKey.SNAPSHOT_TOTALS)[0]
    assert row["snapshot_id"].value == str(selection.snapshot_id)
    assert row["valuation_at"].value == canonical.snapshot.valuation_at
    assert report.manifest.document.valuation_at == canonical.snapshot.valuation_at
    for name, metric in (
        ("total", canonical.snapshot.total_value),
        ("cash", canonical.snapshot.cash_value),
        ("invested", canonical.snapshot.invested_value),
        ("net_contributions", canonical.snapshot.net_contributions),
        ("dividends_received", canonical.dividends_received),
        ("realized_profit_loss", canonical.realized_profit_loss),
        ("unrealized_profit_loss", canonical.unrealized_profit_loss),
    ):
        assert row[name].value == metric.value
        assert row[name].currency == CurrencyCode(metric.currency)
        assert (row[name].value is None) == (row[name].state is r.CellState.UNAVAILABLE)


async def _xray_path_parity(case: ReportCase, report: DownloadedReport, run_id: UUID) -> None:
    paths = await case.base.service.get_effective_exposure(
        case.principal,
        str(case.account_id),
        query=xray.EffectiveExposureQuery(
            request=case.base.request(str(run_id)), options=xray.Paths(), limit=100
        ),
    )
    assert isinstance(paths, xray.PathsView)
    assert paths.context.run_id == str(run_id)
    assert paths.paths.next_cursor is None
    rows = report.rows(r.ReportTableKey.XRAY_PATHS)
    assert len(rows) == paths.paths.total == len(paths.paths.items) > 0
    expected_by_key = {path.key: path for path in paths.paths.items}
    assert len(expected_by_key) == len(rows)
    assert {row["key"].value for row in rows} == set(expected_by_key)
    relations = report.rows(r.ReportTableKey.XRAY_PATH_RELATIONS)
    compact_pdf = "".join(report.pdf_text.split())
    for retained, row in zip(report.tables[r.ReportTableKey.XRAY_PATHS], rows, strict=True):
        expected = expected_by_key[str(row["key"].value)]
        position = expected.root if isinstance(expected.root, xd.PositionRoot) else None
        for key, value in (
            ("root_key", expected.root_key),
            ("root_kind", "position" if position is not None else "cash"),
            ("position_id", str(position.position_id) if position is not None else None),
            ("instrument_id", expected.instrument_id),
            ("entity_id", expected.entity_id),
            ("explicit_cash", expected.explicit_cash),
            (
                "unresolved_reason",
                expected.unresolved_reason.value if expected.unresolved_reason else None,
            ),
            ("quality", expected.quality.value),
            ("confidence", expected.confidence),
        ):
            assert row[key].value == value
        for kind, identifiers in (
            ("identity_decision", expected.identity_decision_ids),
            ("source", expected.source_reference_ids),
        ):
            actual = {
                (item["ordinal"].value, item["referenced_key"].value)
                for item in relations
                if item["path_key"].value == expected.key and item["relation_kind"].value == kind
            }
            assert actual == set(enumerate(identifiers))
        # Bind each PDF assertion to its own captured path record, including wrapped IDs.
        marker = f"Record:{retained.key}Key:"
        assert compact_pdf.count(marker) == 1
        pdf_record = compact_pdf.split(marker, 1)[1].split("Record:", 1)[0]
        assert pdf_record.startswith(expected.key)
        for key, metric in (
            ("reporting_value", expected.reporting_value),
            ("absolute_weight", expected.absolute_weight),
            ("relative_weight", expected.relative_weight),
        ):
            cell = row[key]
            if isinstance(metric, xd.XrayMoneyMetric):
                assert cell.value == (None if metric.value is None else metric.value.amount)
                assert cell.currency == (
                    report.manifest.document.selection.reporting_currency
                    if metric.value is None
                    else metric.value.currency
                )
            else:
                assert cell.value == metric.value and cell.currency is None
            assert cell.state.value == metric.availability.value
            context = next(
                item for item in report.manifest.contexts if item.key == cell.context_key
            )
            assert (cell.quality if cell.quality is not None else context.quality) == metric.quality
            assert cell.confidence == metric.confidence
            assert cell.reason_key == (
                f"xray.reason.{metric.reason.value}" if metric.reason else None
            )
            label = key.replace("_", " ").capitalize()
            if cell.value is None:
                display = f"{cell.state.value.capitalize()} ({cell.reason_key})"
            else:
                display = canonical_report_cell_value(cell)
                if cell.currency is not None:
                    display += f" {cell.currency.value}"
                if cell.state is not r.CellState.AVAILABLE:
                    display += f" [{cell.state.value}]"
                assert cell.bound_key is not None
                display += f" [bound: {cell.bound_key}]"
            assert "".join(f"{label}: {display}".split()) in pdf_record


def _metric(
    report: DownloadedReport,
    cell: r.ReportCell,
    value: h.HistoricalMoneyMetric | h.HistoricalRatioMetric,
) -> None:
    context = next(item for item in report.manifest.contexts if item.key == cell.context_key)
    assert cell.state.value == value.availability.value
    assert (cell.quality if cell.quality is not None else context.quality) == value.quality
    assert cell.origin is not None and cell.origin.value == value.origin.value
    assert (cell.coverage_key or context.coverage_set_key) == value.coverage_key.value
    assert cell.provenance_set_key or context.provenance_set_key
    assert cell.method_key or context.method_key
    assert cell.method_version or context.method_version
    if isinstance(value, h.HistoricalMoneyMetric):
        assert cell.value == (None if value.value is None else value.value.amount)
        if value.value is not None:
            assert cell.currency == value.value.currency
    else:
        assert cell.value == value.value and cell.currency is None


def _input(report: DownloadedReport, family: r.ReportFamily) -> str:
    return str(
        next(
            binding.subject_id
            for binding in report.manifest.bindings
            if binding.family is family and binding.role is r.ReportInputRole.INPUT
        )
    )


def _retained_calculation(
    case: HistoryReportCase, report: DownloadedReport, family: r.ReportFamily
) -> HistoricalCalculation:
    binding = next(
        item
        for item in report.manifest.bindings
        if item.family is family and item.role is r.ReportInputRole.RESULT
    )
    with case.sessions() as session:
        run = session.get(HistoricalRunModel, binding.subject_id)
        assert run is not None and str(run.input_id) == _input(report, family)
        retained = session.get(AnalyticsRunModel, run.analytics_run_id)
        assert retained is not None and retained.owner_id == UUID(case.principal.owner_id)
        assert retained.broker_account_id == case.account_id and retained.kind == run.kind
        assert (
            hashlib.sha256(retained.canonical_result).hexdigest()
            == retained.content_digest
            == binding.content_digest
        )
        return historical_result_from_json(retained.canonical_result)


async def _historical_parity(case: HistoryReportCase, report: DownloadedReport) -> None:
    selection = report.manifest.document.selection
    service = PostgresHistoricalService(case.sessions, cursor_signing_key=CURSOR_KEY)
    window = h.HistoricalWindow(
        start_date=selection.start_date,
        end_date=selection.end_date,
        source_cutoff_at=selection.source_cutoff_at,
        reporting_currency=selection.reporting_currency,
    )
    account = str(case.account_id)
    if r.ReportTableKey.PERFORMANCE_SUMMARY in report.tables:
        performance = await service.get_performance_summary(
            case.principal,
            account,
            query=history.PerformanceSummaryQuery(
                window=window, input_snapshot_id=_input(report, r.ReportFamily.PERFORMANCE)
            ),
        )
        row = report.rows(r.ReportTableKey.PERFORMANCE_SUMMARY)[0]
        for key, metric in (
            ("beginning_value", performance.summary.beginning_value),
            ("ending_value", performance.summary.ending_value),
            ("investment_gain", performance.summary.investment_gain),
            ("time_weighted_return", performance.summary.time_weighted_return),
        ):
            _metric(report, row[key], metric)
        points = report.rows(r.ReportTableKey.PERFORMANCE_POINTS)
        assert len(points) == len(performance.series)
        for actual, expected in zip(points, performance.series, strict=True):
            assert actual["date"].value == expected.date
            _metric(report, actual["portfolio_value"], expected.portfolio_value)
            _metric(report, actual["cumulative_return"], expected.cumulative_return)
        if selection.start_date == date(2025, 1, 1) and selection.end_date == date(2025, 12, 31):
            assert row["beginning_value"].value == Decimal("1872.4697")
            assert row["ending_value"].value == Decimal("2191.280575")
            assert row["investment_gain"].value == Decimal("218.810875")
            references = {str(ref.subject_id) for ref in report.manifest.source_references}
            complete_performance = _retained_calculation(case, report, r.ReportFamily.PERFORMANCE)
            assert isinstance(complete_performance, PerformanceCalculation)
            context_keys = {
                context.key
                for context in report.manifest.contexts
                if context.family is r.ReportFamily.PERFORMANCE
            }
            uses = {
                use["use_key"].value: use
                for use in report.rows(r.ReportTableKey.HISTORICAL_OBSERVATION_USES)
                if use["use_key"].context_key in context_keys
            }
            # Valuation instants differ from the observed price/session date;
            # the inclusive Dec31 window ends at Jan1 midnight UTC.
            for boundary in (
                complete_performance.context.window.start_at,
                complete_performance.context.window.end_at,
            ):
                matching = [
                    use
                    for use in complete_performance.source_uses
                    if isinstance(use, HistoricalObservationUse)
                    and use.use_at == boundary
                    and use.source_kind in {"price", "fx"}
                ]
                assert matching
                for expected_use in matching:
                    actual_use = uses[expected_use.use_key]
                    for key in (
                        "role",
                        "use_at",
                        "knowledge_cutoff_at",
                        "source_kind",
                        "snapshot_id",
                        "observation_index",
                    ):
                        assert actual_use[key].value == getattr(expected_use, key)
                    assert expected_use.snapshot_id in references
    if r.ReportTableKey.BENCHMARK_SUMMARY in report.tables:
        benchmark = await service.get_benchmark_comparison(
            case.principal,
            account,
            query=history.BenchmarkComparisonQuery(
                window=window,
                benchmark_version_id=str(case.benchmark_version_id),
                input_snapshot_id=_input(report, r.ReportFamily.BENCHMARK),
            ),
        )
        row = report.rows(r.ReportTableKey.BENCHMARK_SUMMARY)[0]
        _metric(report, row["benchmark_return"], benchmark.summary.benchmark_return)
        _metric(report, row["excess_return"], benchmark.summary.excess_return)
        assert len(report.tables[r.ReportTableKey.BENCHMARK_POINTS]) == len(benchmark.series)
        assert benchmark.composite_snapshot is not None
        composite_pins = [
            binding
            for binding in report.manifest.bindings
            if binding.family is r.ReportFamily.BENCHMARK
            and binding.role is r.ReportInputRole.SNAPSHOT
        ]
        assert len(composite_pins) == 1
        composite_pin = composite_pins[0]
        assert str(composite_pin.subject_id) == benchmark.composite_snapshot.id
        assert composite_pin.content_digest == benchmark.composite_snapshot.content_digest
        assert composite_pin.method_key == benchmark.composite_snapshot.method.name
        assert composite_pin.method_version == benchmark.composite_snapshot.method.version
        result_pins = [
            binding
            for binding in report.manifest.bindings
            if binding.family is r.ReportFamily.BENCHMARK
            and binding.role is r.ReportInputRole.RESULT
        ]
        assert len(result_pins) == 1 and composite_pin.parent_id == result_pins[0].subject_id
        composite = report.rows(r.ReportTableKey.BENCHMARK_COMPOSITE)[0]
        assert (
            composite["observation_count"].value == benchmark.composite_snapshot.observation_count
        )
        assert r.ReportTableKey.BENCHMARK_OBSERVATIONS not in report.tables
        for actual, benchmark_point in zip(
            report.rows(r.ReportTableKey.BENCHMARK_POINTS), benchmark.series, strict=True
        ):
            assert actual["ordinal"].value == benchmark_point.ordinal
            assert actual["date"].value == benchmark_point.date
            assert actual["valuation_at"].value == benchmark_point.valuation_at
            for key in (
                "portfolio_return",
                "benchmark_return",
                "excess_return",
                "portfolio_wealth",
                "benchmark_wealth",
                "relative_wealth",
            ):
                _metric(report, actual[key], getattr(benchmark_point, key))
    if r.ReportTableKey.INCOME_SUMMARY in report.tables:
        income = await service.get_dividend_intelligence(
            case.principal,
            account,
            query=history.DividendIntelligenceQuery(
                window=window, input_snapshot_id=_input(report, r.ReportFamily.INCOME)
            ),
        )
        row = report.rows(r.ReportTableKey.INCOME_SUMMARY)[0]
        _metric(report, row["net_income"], income.summary.net_income)
        _metric(report, row["income_yield"], income.summary.income_yield)
        components = report.rows(r.ReportTableKey.INCOME_COMPONENTS)
        instruments = [item for item in components if item["grouping"].value == "instrument"]
        assert len(instruments) == income.eligible_count == len(income.rows)
        for actual, instrument_income in zip(instruments, income.rows, strict=True):
            assert actual["key"].value == instrument_income.key
            _metric(report, actual["net"], instrument_income.net)
        # Supplemental groups belong to this exact retained calculation. Asking
        # the public GROUP view would require a target pin and change the input.
        complete_income = _retained_calculation(case, report, r.ReportFamily.INCOME)
        assert isinstance(complete_income, IncomeCalculation)
        groups = [item for item in components if item["grouping"].value == "group"]
        assert len(groups) == len(complete_income.group_rows)
        assert len(components) == len(instruments) + len(groups)
        for actual, group_income in zip(groups, complete_income.group_rows, strict=True):
            assert actual["key"].value == group_income.key
            _metric(report, actual["net"], group_income.net)
    if (
        r.ReportTableKey.CASH_FLOW_SUMMARY in report.tables
        or r.ReportTableKey.ACTIVITY in report.tables
    ):
        cash = await service.get_cash_flow_intelligence(
            case.principal,
            account,
            query=history.CashFlowIntelligenceQuery(
                window=window,
                input_snapshot_id=_input(report, r.ReportFamily.CASH_FLOWS),
                limit=100,
            ),
        )
        table = (
            r.ReportTableKey.CASH_FLOW_EVENTS
            if r.ReportTableKey.CASH_FLOW_EVENTS in report.tables
            else r.ReportTableKey.ACTIVITY
        )
        assert len(report.tables[table]) == cash.events.total == len(cash.events.items)
        if r.ReportTableKey.CASH_FLOW_SUMMARY in report.tables:
            row = report.rows(r.ReportTableKey.CASH_FLOW_SUMMARY)[0]
            assert row["event_count"].value == cash.summary.event_count
            assert row["unresolved_count"].value == cash.summary.unresolved_count
    if any(
        binding.family
        in {
            r.ReportFamily.PERFORMANCE,
            r.ReportFamily.BENCHMARK,
            r.ReportFamily.INCOME,
            r.ReportFamily.CASH_FLOWS,
        }
        for binding in report.manifest.bindings
    ):
        assert report.manifest.license_references
        assert report.tables[r.ReportTableKey.HISTORICAL_SOURCE_DETAILS]
        assert report.tables[r.ReportTableKey.HISTORICAL_OPTIONS]
        assert any(ref.license_version_id is not None for ref in report.manifest.source_references)


def _tabular_values(report: DownloadedReport, records: list[dict[str, str]]) -> None:
    by_table: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in records:
        by_table[record["table"]].append(record)
    for descriptor in report.manifest.document.tables:
        actual = by_table.pop(descriptor.table.value, [])
        rows = report.tables[descriptor.table]
        schema = table_schema(descriptor.table)
        if descriptor.section is not None or descriptor.dataset is not None:
            expected = [
                (row, column, cell)
                for row in rows
                for column, cell in zip(schema.columns, row.cells, strict=True)
            ]
            assert len(actual) == len(expected)
            for item, (row, column, cell) in zip(actual, expected, strict=True):
                assert item["row_key"] == row.key and item["column_key"] == column.key
                assert item["value"] == canonical_report_cell_value(cell)
                assert item["cell_kind"] == cell.kind.value and item["state"] == cell.state.value
                assert item["currency"] == (cell.currency.value if cell.currency else "")
                assert item["context_key"] == (cell.context_key or row.context_key)
            continue
        fragments: dict[str, list[dict[str, str]]] = defaultdict(list)
        for item in actual:
            assert item["section"] == "proof" and item["value"].startswith("json:")
            assert len(item["value"]) <= 4005
            key = item["column_key"]
            family, *ordinals = key.split(".")
            assert family in {"schema", "row"}
            assert len(ordinals) == (1 if family == "schema" else 2)
            group = "schema" if family == "schema" else f"row.{ordinals[0]}"
            assert key == f"{group}.{len(fragments[group]):06d}"
            fragments[group].append(item)
        if not actual:
            assert not rows
            continue
        schema_bytes = "".join(item["value"][5:] for item in fragments.pop("schema")).encode()
        assert schema_bytes == encode_report_schema(schema)
        reconstructed = []
        for ordinal, row in enumerate(rows):
            pieces = fragments.pop(f"row.{ordinal:06d}")
            assert all(
                item["row_key"] == row.key and item["context_key"] == row.context_key
                for item in pieces
            )
            encoded = "".join(item["value"][5:] for item in pieces).encode()
            reconstructed.append(decode_report_row(encoded))
        assert not fragments and tuple(reconstructed) == rows
        assert report_table_digest(descriptor.table, reconstructed) == descriptor.content_digest
    assert not by_table


def _checked_formats(report: DownloadedReport) -> DownloadedReport:
    assert set(report.artifacts) == set(r.ReportFormat)
    manifest_bytes = encode_report_manifest(report.manifest)
    csv_rows = list(
        csv.DictReader(StringIO(report.artifacts[r.ReportFormat.CSV].decode(), newline=""))
    )
    fragments = [row["value"] for row in csv_rows if row["table"] == "canonical_manifest"]
    assert fragments and all(value.startswith("json:") for value in fragments)
    assert "".join(value[5:] for value in fragments).encode() == manifest_bytes
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    spreadsheet_records: list[dict[str, str]] = []
    with ZipFile(BytesIO(report.artifacts[r.ReportFormat.XLSX])) as archive:
        root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))  # noqa: S314 - actual generated synthetic artifact
        fragments = []
        for row in root.findall("s:sheetData/s:row", ns)[1:]:
            value = row[1].find("s:is/s:t", ns)
            assert value is not None and value.text is not None and value.text.startswith("json:")
            fragments.append(value.text[5:])
        assert "".join(fragments).encode() == manifest_bytes
        assert not any(
            "externalLink" in name or "vbaProject" in name for name in archive.namelist()
        )
        for name in archive.namelist():
            if not name.startswith("xl/worksheets/sheet"):
                continue
            sheet = ElementTree.fromstring(archive.read(name))  # noqa: S314 - actual generated synthetic artifact
            assert not sheet.findall(".//s:f", ns) and not sheet.findall(".//s:hyperlink", ns)
            values = [
                [node.text or "" for node in row.findall("s:c/s:is/s:t", ns)]
                for row in sheet.findall("s:sheetData/s:row", ns)
            ]
            if values and values[0][0] == "section":
                spreadsheet_records.extend(
                    dict(zip(values[0], row, strict=True)) for row in values[1:]
                )
    table_csv = [item for item in csv_rows if item["section"] != "manifest"]
    assert len(table_csv) == len(spreadsheet_records)
    for csv_record, xlsx_record in zip(table_csv, spreadsheet_records, strict=True):
        assert csv_record.keys() == xlsx_record.keys()
        for key, xlsx_value in xlsx_record.items():
            csv_value = csv_record[key]
            if key == "value" and csv_record["cell_kind"] not in {"decimal", "integer", "boolean"}:
                assert csv_value in {xlsx_value, "'" + xlsx_value}
            else:
                assert csv_value == xlsx_value
    _tabular_values(report, spreadsheet_records)
    pdf = PdfReader(BytesIO(report.artifacts[r.ReportFormat.PDF]))
    assert 0 < len(pdf.pages) <= r.MAX_REPORT_PDF_PAGES
    assert dict(pdf.attachments) == {"report-manifest.json": [manifest_bytes]}
    first = pdf.pages[0].extract_text()
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert text.strip()
    assert report.manifest.document.document_digest in " ".join(text.split())
    return replace(report, csv_records=tuple(csv_rows), pdf_text=text, pdf_first_page=first)


def _annual_formats(report: DownloadedReport) -> None:
    assert any(
        row["table"] == "performance_summary"
        and row["column_key"] == "ending_value"
        and row["value"] == "2191.280575"
        and row["currency"] == "EUR"
        for row in report.csv_records
    )
    note = next(note for note in report.manifest.notes if note.code == "snapshot_outside_period")
    assert "2025" in report.pdf_first_page and "2026" in report.pdf_first_page
    assert " ".join(note.text.split()) in " ".join(report.pdf_first_page.split())
    assert "1872.4697" in report.pdf_text and "2191.280575" in report.pdf_text


@pytest.mark.parametrize(
    "report_type,sections,start,end", _HISTORY_CASES, ids=[case[0].value for case in _HISTORY_CASES]
)
def test_historical_report_type_matrix(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
    report_type: r.ReportType,
    sections: tuple[r.ReportSection, ...],
    start: date,
    end: date,
) -> None:
    async def run() -> None:
        assert {item[0] for item in _HISTORY_CASES} | {
            r.ReportType.PORTFOLIO_SUMMARY,
            r.ReportType.PORTFOLIO_XRAY,
            r.ReportType.CONTRIBUTION_PLAN,
        } == set(r.ReportType)
        case = history_report_case(*seeded_history)
        selection = case.selection(report_type, sections, start_date=start, end_date=end)
        selection = replace(selection, formats=tuple(r.ReportFormat))
        status = await case.complete(selection)
        report = await _download(case.service, case.principal, case.account_id, status)
        assert report.manifest.document.selection == selection
        await _snapshot_parity(case.sessions, case.principal, report)
        assert report.manifest.document.valuation_at.year == 2026
        assert any(note.code == "snapshot_outside_period" for note in report.manifest.notes)
        await _historical_parity(case, report)
        if report_type is r.ReportType.TARGET_DRIFT:
            with case.sessions() as session:
                target = session.get(TargetVersionModel, case.target_version_id)
                assert target is not None
                portfolio_id = str(target.virtual_portfolio_id)
            drift = await PostgresPlanningService(
                sessions=case.sessions, cursor_signing_key=CURSOR_KEY
            ).get_drift_analysis(
                case.principal,
                str(case.account_id),
                query=planning.DriftAnalysisQuery(
                    snapshot_id=str(case.snapshot_id),
                    virtual_portfolio_id=portfolio_id,
                    target_version_id=str(case.target_version_id),
                    reporting_currency=CurrencyCode("EUR"),
                ),
            )
            totals = report.rows(r.ReportTableKey.DRIFT_TOTALS)[0]
            assert totals["value"].value == (
                None if drift.totals.value is None else drift.totals.value.amount
            )
            assert totals["l1_drift"].value == drift.totals.l1_drift
            assert len(report.tables[r.ReportTableKey.DRIFT_ROWS]) == drift.eligible_rows
            assert report.tables[r.ReportTableKey.TARGET_NODES]
        if report_type is r.ReportType.ANNUAL:
            cash_run_id = next(
                binding.subject_id
                for binding in report.manifest.bindings
                if binding.family is r.ReportFamily.CASH_FLOWS
                and binding.role is r.ReportInputRole.RESULT
            )
            with case.sessions() as session:
                cash_run = session.get(HistoricalRunModel, cash_run_id)
                assert cash_run is not None and cash_run.kind == "cash_flow"
                analytics_run = session.get(AnalyticsRunModel, cash_run.analytics_run_id)
                assert analytics_run is not None and analytics_run.kind == "cash_flow"
            _annual_formats(report)

    asyncio.run(run())


@pytest.mark.parametrize(
    "report_type",
    [r.ReportType.PORTFOLIO_SUMMARY, r.ReportType.PORTFOLIO_XRAY],
    ids=lambda value: value.value,
)
def test_snapshot_and_xray_report_types(report_case: ReportCase, report_type: r.ReportType) -> None:
    async def run() -> None:
        case = report_case
        status = await finish(
            case,
            await generate(
                case, xray=report_type is r.ReportType.PORTFOLIO_XRAY, formats=tuple(r.ReportFormat)
            ),
        )
        report = await _download(case.service, case.principal, case.account_id, status)
        assert isinstance(report.manifest.document.selection, r.ReportSelection)
        assert report.manifest.document.selection.report_type is report_type
        await _snapshot_parity(case.base.sessions, case.principal, report)
        assert report.rows(r.ReportTableKey.SNAPSHOT_TOTALS)[0]["total"].value == Decimal("1000")
        if report_type is r.ReportType.PORTFOLIO_XRAY:
            run_id = next(
                binding.subject_id
                for binding in report.manifest.bindings
                if binding.family is r.ReportFamily.XRAY
                and binding.role is r.ReportInputRole.RESULT
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
                summary["company_known_weight"].value
                == canonical.summary.company_known_weight.value
                == Decimal("0.95")
            )
            assert (
                summary["unresolved_weight"].value
                == canonical.summary.unresolved_weight.value
                == Decimal("0.05")
            )
            assert (
                summary["duplicated_exposure"].value
                == canonical.summary.duplicated_exposure.value
                == Decimal("0.41")
            )
            assert summary["hhi"].value == canonical.summary.hhi.value == Decimal("0.4657")
            await _xray_path_parity(case, report, run_id)
            assert report.manifest.license_references
            for table in (
                r.ReportTableKey.XRAY_PATHS,
                r.ReportTableKey.XRAY_SOURCE_USES,
                r.ReportTableKey.XRAY_SELECTION_EVIDENCE,
                r.ReportTableKey.XRAY_DEPENDENCY_IDENTITIES,
            ):
                assert report.tables[table]

    asyncio.run(run())


def test_contribution_plan_report_uses_a_real_finalized_revision(
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
            principal, command, idempotency_key=uuid4().hex, correlation_id="report-matrix"
        )
        claim = await planner.claim_plan_job(
            PlanTaskMessage(
                job.job_id, job.request_id, principal.owner_id, job.account_id, job.input_digest
            ),
            consumer_id="report-matrix",
        )
        assert claim is not None
        pinned = await planner.load_plan_job_input(claim)
        canonical = calculate_contribution_plan(pinned)
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
        selection = r.ReportSelection(
            account_id=build_synthetic_identity().account.id,
            snapshot_id=UUID(command.snapshot_id),
            start_date=cutoff.date(),
            end_date=cutoff.date(),
            source_cutoff_at=cutoff,
            reporting_currency=CurrencyCode("EUR"),
            report_type=r.ReportType.CONTRIBUTION_PLAN,
            sections=(
                r.ReportSection.OVERVIEW,
                r.ReportSection.TARGETS,
                r.ReportSection.CONTRIBUTION_PLAN,
                r.ReportSection.QUALITY,
            ),
            formats=tuple(r.ReportFormat),
            target_version_id=UUID(command.target_version_id),
            plan_revision_id=revision_id,
        )
        service = PostgresReportService(sessions, cursor_signing_key=CURSOR_KEY)
        status = await service.generate_report(
            principal, app.GenerateReportCommand(selection=selection, idempotency_key=uuid4().hex)
        )
        with sessions() as session:
            saved = session.get(ReportJobModel, status.job_id)
            assert saved is not None
            message = report_jobs.ReportTaskMessage(
                job_id=saved.id,
                owner_id=saved.owner_id,
                account_id=saved.account_id,
                capture_id=saved.input_id,
                input_digest=saved.input_digest,
            )
        assert (
            await execute_report_message(
                PostgresReportJobStore(sessions), message, consumer_id="report-plan-matrix"
            )
            is ReportExecutionState.COMPLETED
        )
        status = await service.get_report_status(principal, selection.account_id, status.job_id)
        report = await _download(service, principal, selection.account_id, status)
        await _snapshot_parity(sessions, principal, report)
        summary = report.rows(r.ReportTableKey.PLAN_SUMMARY)[0]
        assert summary["plan_revision_id"].value == str(revision_id)
        assert summary["execution_allowed"].value is False
        assert summary["contribution"].value == command.options.contribution.amount == Decimal("20")
        assert canonical.summary.residual_cash is not None
        assert summary["residual_cash"].value == canonical.summary.residual_cash.amount
        input_header = report.rows(r.ReportTableKey.PLAN_INPUT_HEADER)[0]
        assert input_header["input_digest"].value == job.input_digest
        options = report.rows(r.ReportTableKey.PLAN_OPTIONS)[0]
        assert options["eligibility_explicit"].value is (
            pinned.options.eligible_holding_ids is not None
        )
        expected_members = {
            (kind, ordinal): member
            for kind, members in (
                ("eligible", pinned.options.eligible_holding_ids or ()),
                ("excluded", pinned.options.excluded_holding_ids),
                ("restricted_group", pinned.options.restricted_group_ids),
                ("missing_input", pinned.valuation.missing_inputs),
            )
            for ordinal, member in enumerate(members)
        }
        member_rows = (
            report.rows(r.ReportTableKey.PLAN_INPUT_MEMBERS)
            if r.ReportTableKey.PLAN_INPUT_MEMBERS in report.tables
            else ()
        )
        assert len(member_rows) == len(expected_members)
        assert {
            (row["relation_kind"].value, row["ordinal"].value): row["member_key"].value
            for row in member_rows
        } == expected_members
        lines = report.rows(r.ReportTableKey.PLAN_LINES)
        assert len(lines) == len(canonical.lines)
        for actual, expected in zip(lines, canonical.lines, strict=True):
            assert actual["node_key"].value == expected.node_key
            assert actual["recommended_amount"].value == expected.recommended_amount.amount
            assert actual["post_value"].value == expected.post_value.amount
        for table in (
            r.ReportTableKey.PLAN_INPUT_HEADER,
            r.ReportTableKey.PLAN_VALUATION,
            r.ReportTableKey.PLAN_OPTIONS,
            r.ReportTableKey.PLAN_NODE_IDENTITIES,
            r.ReportTableKey.PLAN_SOURCE_DETAILS,
        ):
            assert report.tables[table]

    asyncio.run(run())
