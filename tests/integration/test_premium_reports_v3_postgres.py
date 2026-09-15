"""Actual saved scenario reports, complete four-format proof and private profile isolation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from functools import partial
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import Connection, ExecutionContext
from trading212_application import report_jobs
from trading212_application import reports as app
from trading212_application import xray as xray_app
from trading212_domain import reports as r
from trading212_domain.report_scenario_schema import SCENARIO_PROOF_TABLES, SCENARIO_REPORT_TABLES
from trading212_domain.report_v3 import (
    ReportScenarioRunBinding,
    ReportScenarioRunSelection,
    ReportSelectionV3,
)
from trading212_domain.scenario import ScenarioEntitySelector, ScenarioPriceShock, scenario_rule_key
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import (
    ScenarioCalculation,
    ScenarioMoneyMetric,
    ScenarioRatioMetric,
)
from trading212_domain.scenario_serialization import scenario_result_from_json
from trading212_domain.values import CurrencyCode, Instant
from trading212_persistence.premium_models import PremiumRunLicenseModel, PremiumRunModel
from trading212_persistence.report_input_store import ReportInputSink
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    ReportInputPremiumDependencyModel,
    ReportInputSnapshotModel,
    ReportJobModel,
)
from trading212_persistence.report_service import PostgresReportService
from trading212_persistence.scenario_input_codec import unpack_scenario_input
from trading212_persistence.scenario_models import ScenarioResultModel, ScenarioRunPayloadModel
from trading212_persistence.source_models import ProviderLicenseVersionModel
from trading212_worker.report_tasks import ReportExecutionState, execute_report_message
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.premium_report_v3_artifacts import DownloadedReportV3, download_v3
from tests.integration.test_scenario_retention_postgres import published
from tests.integration.test_scenario_runs_postgres import ScenarioCase, cancel_scenario
from tests.integration.test_scenario_runs_postgres import scenario_case as scenario_case
from tests.integration.test_xray_fx_postgres import _fx_setup, _ingest_fx
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class SavedScenario:
    execution: ScenarioExecutionInput
    value: ScenarioCalculation
    result_id: UUID
    result_digest: str
    input_payload: bytes
    result_payload: bytes
    expires_at: datetime


def saved(case: ScenarioCase) -> SavedScenario:
    """Read the independently retained originals once, before report generation or revocation."""
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        assert root.owner_id == UUID(case.principal.owner_id)
        assert root.account_id == case.command.account_id
        result = session.execute(
            select(
                ScenarioResultModel.id,
                ScenarioResultModel.content_digest,
                ScenarioResultModel.canonical_result,
            ).where(ScenarioResultModel.run_id == root.id)
        ).one()
        payload = session.scalar(
            select(ScenarioRunPayloadModel.canonical_input).where(
                ScenarioRunPayloadModel.run_id == root.id
            )
        )
        assert payload is not None
        return SavedScenario(
            unpack_scenario_input(payload, expected_digest=root.input_digest),
            scenario_result_from_json(
                result.canonical_result, expected_digest=result.content_digest
            ),
            result.id,
            result.content_digest,
            payload,
            result.canonical_result,
            root.expires_at,
        )


def service(case: ScenarioCase, version: int = 3) -> PostgresReportService:
    return PostgresReportService(
        case.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: max(case.now, datetime.now(UTC)),
        contract_version=version,
    )


def selection(
    case: ScenarioCase, *, formats: tuple[r.ReportFormat, ...] = tuple(r.ReportFormat)
) -> ReportSelectionV3:
    return ReportSelectionV3(
        account_id=case.command.account_id,
        snapshot_id=case.command.portfolio_snapshot_id,
        reporting_currency=case.command.reporting_currency,
        start_date=case.command.source_cutoff_at.date(),
        end_date=case.command.source_cutoff_at.date(),
        source_cutoff_at=case.command.source_cutoff_at,
        report_type=r.ReportType.PORTFOLIO_SUMMARY,
        sections=(
            r.ReportSection.OVERVIEW,
            r.ReportSection.ALLOCATION,
            r.ReportSection.QUALITY,
            r.ReportSection.SCENARIO,
        ),
        formats=formats,
        premium_run=ReportScenarioRunSelection(run_id=case.run.id),
    )


def message(case: ScenarioCase, status: app.ReportJobStatus) -> report_jobs.ReportTaskMessage:
    with case.sessions() as session:
        job = session.get_one(ReportJobModel, status.job_id)
        return report_jobs.ReportTaskMessage(
            job_id=job.id,
            owner_id=job.owner_id,
            account_id=job.account_id,
            capture_id=job.input_id,
            input_digest=job.input_digest,
        )


async def complete(
    case: ScenarioCase, reports: PostgresReportService, pending: app.ReportJobStatus
) -> app.ReportJobStatus:
    state = await execute_report_message(
        PostgresReportJobStore(case.sessions, clock=lambda: max(case.now, datetime.now(UTC))),
        message(case, pending),
        consumer_id="premium-report-v3-test",
    )
    result = await reports.get_report_status(
        case.principal, case.command.account_id, pending.job_id
    )
    assert state is ReportExecutionState.COMPLETED, result.failure_code
    assert result.state is r.ReportJobState.SUCCEEDED
    return result


def metric(
    report: DownloadedReportV3,
    actual: r.ReportCell,
    expected: ScenarioMoneyMetric | ScenarioRatioMetric,
) -> None:
    assert actual.context_key is not None
    context = next(item for item in report.manifest.contexts if item.key == actual.context_key)
    assert actual.state is (
        r.CellState.UNAVAILABLE if expected.value is None else r.CellState.AVAILABLE
    )
    assert (actual.quality or context.quality) == expected.quality
    assert actual.bound_key is not None
    bound = next(item for item in report.manifest.bounds if item.key == actual.bound_key)
    assert bound.kind is (
        r.ReportBoundKind.UNAVAILABLE if expected.value is None else r.ReportBoundKind.EXACT
    )
    if expected.reason is None:
        assert actual.reason_key is None
    else:
        assert actual.reason_key is not None
        assert (
            next(item for item in report.manifest.notes if item.key == actual.reason_key).code
            == expected.reason.value
        )
    if isinstance(expected, ScenarioMoneyMetric):
        assert actual.value == (None if expected.value is None else expected.value.amount)
        assert actual.currency == report.manifest.document.selection.reporting_currency
        assert actual.confidence == expected.confidence
        provenance = actual.provenance_set_key or context.provenance_set_key
        assert {
            item.source_key
            for item in report.manifest.source_memberships
            if item.provenance_set_key == provenance
        } == {f"xray.source.{identifier}" for identifier in expected.source_reference_ids}
    else:
        assert actual.value == expected.value and actual.currency is None


def parity(report: DownloadedReportV3, source: SavedScenario) -> None:
    value, execution = source.value, source.execution
    manifest = report.manifest
    binding = manifest.document.premium_binding
    assert isinstance(binding, ReportScenarioRunBinding)
    assert binding.result_id == source.result_id and binding.result_digest == source.result_digest
    assert binding.input_digest == value.input_digest == execution.input_digest
    assert binding.snapshot_digest == value.pins.portfolio_snapshot_digest
    assert binding.scenario_version_id == value.pins.scenario_version_id
    assert binding.scenario_version_digest == value.pins.scenario_version_digest
    assert binding.xray.run_id == value.pins.xray_run_id
    assert binding.xray.input_digest == value.pins.xray_input_digest
    assert binding.xray.result_digest == value.pins.xray_result_digest
    assert binding.historical is None and execution.replay is None
    assert set((*SCENARIO_REPORT_TABLES, *SCENARIO_PROOF_TABLES)) <= set(report.tables)
    assert all(item.schema_version == "3.0.0" for item in manifest.contexts)
    basis = report.rows(r.ReportTableKey.SCENARIO_BASIS_V1)[0]
    assert basis["run_id"].value == str(binding.run_id)
    assert basis["result_id"].value == str(source.result_id)
    assert basis["result_digest"].value == source.result_digest
    assert basis["portfolio_snapshot_digest"].value == value.pins.portfolio_snapshot_digest
    definition = report.rows(r.ReportTableKey.SCENARIO_DEFINITION_V1)[0]
    for name in ("name", "description", "mode", "method_version"):
        assert definition[name].value == getattr(value.definition, name)
    shocks = report.rows(r.ReportTableKey.SCENARIO_SHOCKS_V1)
    assert len(shocks) == len(value.definition.shocks) == 1
    shock = value.definition.shocks[0]
    assert isinstance(shock, ScenarioPriceShock)
    assert isinstance(shock.selector, ScenarioEntitySelector)
    assert shocks[0]["rule_key"].value == scenario_rule_key(shock)
    assert shocks[0]["size"].value == shock.size == Decimal("-0.1")
    assert shocks[0]["entity_id"].value == str(shock.selector.entity_id)
    assert shocks[0]["sensitivity_version_id"].state is r.CellState.NOT_APPLICABLE
    assert value.definition.exclusions == ()
    assert report.tables[r.ReportTableKey.SCENARIO_EXCLUSIONS_V1] == ()
    summary = report.rows(r.ReportTableKey.SCENARIO_SUMMARY_V1)[0]
    for field in fields(value.summary):
        expected = getattr(value.summary, field.name)
        if isinstance(expected, ScenarioMoneyMetric):
            metric(report, summary[field.name], expected)
        elif isinstance(expected, int):
            assert summary[field.name].value == expected
    metric(report, summary["upstream_portfolio_value"], value.upstream_portfolio_value)
    metric(report, summary["upstream_partition_difference"], value.upstream_partition_difference)
    components = report.rows(r.ReportTableKey.SCENARIO_COMPONENTS_V1)
    assert len(components) == len(value.components) > 1
    by_path = {str(item["path_key"].value): item for item in components}
    assert set(by_path) == {item.exposure.path_key for item in value.components}
    for item in value.components:
        actual = by_path[item.exposure.path_key]
        assert actual["root_key"].value == item.exposure.root_key
        assert actual["root_kind"].value == item.exposure.root_kind
        assert actual["partition"].value == item.partition
        assert actual["money_basis"].value == item.money_basis
        assert actual["winning_price_rule_key"].value == item.winning_price_rule_key
        for name, expected in (
            ("pre_value", item.exposure.pre_value),
            ("post_value", item.post_value),
            ("impact", item.impact),
            ("rounding_residual", item.rounding_residual),
        ):
            metric(report, actual[name], expected)
    channels = report.rows(r.ReportTableKey.SCENARIO_CHANNELS_V1)
    assert len(channels) == 4 * (1 + len(value.components))
    effects = {item.exposure.path_key: item.effects for item in value.components}
    for actual in channels:
        effect = (
            value.summary.effects
            if actual["scope"].value == "summary"
            else effects[str(actual["path_key"].value)]
        )
        channel = str(actual["channel"].value)
        money = getattr(effect, channel)
        assert isinstance(money, ScenarioMoneyMetric)
        metric(report, actual["effect"], money)
        if channel == "interaction":
            assert actual["ratio"].state is r.CellState.NOT_APPLICABLE
        else:
            ratio = getattr(effect, f"{channel}_ratio")
            assert isinstance(ratio, ScenarioRatioMetric)
            metric(report, actual["ratio"], ratio)
    paths = report.rows(r.ReportTableKey.SCENARIO_XRAY_PATHS_V1)
    originals = {item.key: item for item in execution.xray_result.terminal_paths}
    assert len(paths) == len(originals)
    assert {item["key"].value for item in paths} == set(originals)
    for actual in paths:
        path = originals[str(actual["key"].value)]
        assert actual["root_key"].value == path.root_key
        assert actual["explicit_cash"].value == path.explicit_cash
        assert actual["reporting_value"].value == (
            None if path.reporting_value.value is None else path.reporting_value.value.amount
        )
        assert actual["reporting_value"].state.value == path.reporting_value.availability.value
        assert actual["absolute_weight"].value == path.absolute_weight.value
        assert actual["absolute_weight"].state.value == path.absolute_weight.availability.value
    references = {item.key for item in manifest.source_references}
    assert {
        f"xray.source.{item.id}" for item in execution.xray_input.source_dependencies
    } <= references
    assert report.tables[r.ReportTableKey.SCENARIO_SUBJECTS_V1]
    assert report.tables[r.ReportTableKey.SCENARIO_MEMBERS_V1]
    assert report.tables[r.ReportTableKey.XRAY_DEPENDENCY_IDENTITIES]
    original_fx = {
        (attempt.consumer_key, ordinal): leg
        for attempt in execution.xray_input.licensed_fx
        for ordinal, leg in enumerate(attempt.legs)
    }
    if original_fx:
        fx = report.rows(r.ReportTableKey.XRAY_FX_LEGS)
    else:
        assert r.ReportTableKey.XRAY_FX_LEGS not in report.tables
        fx = ()
    assert len(fx) == len(original_fx)
    for actual in fx:
        ordinal = actual["ordinal"].value
        assert isinstance(ordinal, int)
        key = (str(actual["consumer_key"].value), ordinal)
        assert key in original_fx
        leg = original_fx[key]
        for field in fields(leg):
            expected = getattr(leg, field.name)
            scalar = (
                str(expected)
                if isinstance(expected, UUID)
                else expected.value
                if isinstance(expected, (Enum, CurrencyCode, Instant))
                else expected
            )
            assert actual[field.name].value == scalar
    if execution.pins.reporting_currency == CurrencyCode("GBP"):
        assert fx
        assert all(leg.rate == Decimal("0.8") for leg in original_fx.values())
    # This fixture has an explicit price shock only; no coefficient/evidence is fabricated.
    assert execution.sensitivities.versions == ()
    assert report.tables[r.ReportTableKey.SCENARIO_APPLIED_SENSITIVITIES_V1] == ()
    assert report.tables[r.ReportTableKey.SCENARIO_SOURCE_HEADERS_V1] == ()
    assert report.tables[r.ReportTableKey.SCENARIO_REPLAY_BASIS_V1] == ()
    text = " ".join(report.pdf_body_text.split())
    assert "Scenario summary v1" in text and "Scenario components v1" in text
    for row, actual in zip(
        report.tables[r.ReportTableKey.SCENARIO_COMPONENTS_V1], components, strict=True
    ):
        compact = "".join(report.pdf_body_text.split())
        marker = f"Record:{row.key}"
        assert compact.count(marker) == 1
        record = compact.split(marker, 1)[1].split("Record:", 1)[0]
        assert str(actual["path_key"].value) in record


@contextmanager
def no_private_reads(case: ScenarioCase) -> Iterator[None]:
    """Fail on the payload SELECT itself; a later decoder check cannot hide a private read."""
    columns = (
        "scenario_run_payloads.canonical_input",
        "scenario_results.canonical_result",
        "scenario_components.canonical_component",
        "scenario_applied_sensitivities.coefficient",
        "scenario_sensitivity_version_payloads.canonical_payload",
        "scenario_sensitivity_observation_payloads.canonical_payload",
        "scenario_sensitivity_evidence_payloads.canonical_payload",
        "xray_input_snapshots.canonical_input",
        "xray_runs.canonical_summary",
        "historical_input_snapshots.canonical_input",
        "risk_results.canonical_result",
        "report_input_snapshots.canonical_context",
        "report_input_snapshots.canonical_manifest",
        "report_input_chunks.payload",
        "report_manifests.payload",
        "report_artifacts.contents",
    )

    def before_read(
        _connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: ExecutionContext,
        _executemany: bool,
    ) -> None:
        sql = statement.replace('"', "").lower().lstrip()
        if sql.startswith("select"):
            assert not any(column in sql for column in columns), (
                "Private payload read before authorization"
            )

    event.listen(case.engine, "before_cursor_execute", before_read)
    try:
        yield
    finally:
        event.remove(case.engine, "before_cursor_execute", before_read)


def revoke_report(case: ScenarioCase) -> None:
    case.now = max(case.now, datetime.now(UTC))
    with case.sessions() as session, session.begin():
        lineage = session.scalar(
            select(PremiumRunLicenseModel)
            .where(PremiumRunLicenseModel.run_id == case.run.id)
            .order_by(PremiumRunLicenseModel.id)
            .limit(1)
        )
        assert lineage is not None
        pinned = session.get_one(ProviderLicenseVersionModel, lineage.license_version_id)
        number = session.scalar(
            select(func.max(ProviderLicenseVersionModel.version_number)).where(
                ProviderLicenseVersionModel.provider_id == pinned.provider_id
            )
        )
        assert number is not None
        session.add(
            ProviderLicenseVersionModel(
                id=uuid4(),
                owner_id=pinned.owner_id,
                provider_id=pinned.provider_id,
                version_number=number + 1,
                version=f"v3-report-denied-{number + 1}",
                effective_at=case.now,
                store_permission="allowed",
                display_permission="allowed",
                report_permission="denied",
                export_permission="allowed",
                retention_days=30,
                attribution="Synthetic REPORT-only revocation",
                evidence_key="synthetic-v3",
                created_at=case.now,
            )
        )


@pytest.mark.parametrize("currency", ["EUR", "GBP"])
async def test_saved_scenario_four_formats_original_proof_and_ttl_clamping(
    scenario_case: ScenarioCase, currency: str
) -> None:
    case = scenario_case
    if currency == "GBP":
        calendar = await _fx_setup(case.xray)
        await _ingest_fx(case.xray, calendar, (("EUR", "GBP", "0.8"),))
        converted = await case.xray.service.get_effective_exposure(
            case.principal,
            XRAY_ACCOUNT_ID,
            query=xray_app.EffectiveExposureQuery(
                request=replace(
                    case.xray.request(),
                    currency=xray_app.ExplicitCurrency(reporting_currency=CurrencyCode("GBP")),
                )
            ),
        )
        assert isinstance(converted, xray_app.ExposuresView)
        assert converted.summary.total.value is not None
        assert converted.summary.total.value.amount == Decimal("800")
        case.command = replace(
            case.command,
            xray_run_id=UUID(converted.context.run_id),
            reporting_currency=CurrencyCode("GBP"),
            idempotency_key=uuid4().hex,
        )
        case.run = await case.service.create_run(case.principal, case.command)
    await published(case)
    original = saved(case)
    # The request is newer than its retained source. Thirty days must clamp to
    # original source/run deadlines before V3 authorization and sealing.
    case.now = max(case.now + timedelta(days=2), datetime.now(UTC))
    reports = service(case)
    chosen = selection(case)
    command = app.GenerateReportCommand(selection=chosen, idempotency_key=uuid4().hex, ttl_days=30)
    with patch(
        "trading212_analytics.scenario.calculate_scenario",
        side_effect=AssertionError("report recalculated scenario"),
    ):
        queued = await reports.generate_report(case.principal, command)
    assert queued.context is not None and queued.context.profile_version == "report_sections_v3"
    assert queued.expires_at <= original.expires_at < case.now + timedelta(days=30)
    with patch.object(
        ReportInputSink, "__init__", side_effect=AssertionError("idempotent retry recaptured input")
    ):
        assert await reports.generate_report(case.principal, command) == queued
        with pytest.raises(app.ReportServiceError) as error:
            await reports.generate_report(case.principal, replace(command, ttl_days=7))
        assert error.value.code is app.ReportServiceErrorCode.CONFLICT
    with case.sessions() as session:
        job = session.get_one(ReportJobModel, queued.job_id)
        dependency = session.scalar(
            select(ReportInputPremiumDependencyModel).where(
                ReportInputPremiumDependencyModel.input_id == job.input_id
            )
        )
        assert dependency is not None and dependency.kind == "scenario"
        assert dependency.run_id == case.run.id and dependency.result_id == original.result_id
        assert dependency.input_digest == original.execution.input_digest
        assert dependency.result_digest == original.result_digest
        assert dependency.snapshot_digest == original.value.pins.portfolio_snapshot_digest
        assert job.contract_version == 3
        assert (
            session.get_one(ReportInputSnapshotModel, job.input_id).expires_at == queued.expires_at
        )
        identity = session.scalar(
            select(ApplicationCommandIdentityModel).where(
                ApplicationCommandIdentityModel.report_job_id == job.id
            )
        )
        assert identity is not None and identity.command == "reports.generate.v2"
    completed = await complete(case, reports, queued)
    report = await download_v3(reports, case.principal, case.command.account_id, completed)
    assert report.manifest.document.selection == chosen
    parity(report, original)
    total = report.rows(r.ReportTableKey.SNAPSHOT_TOTALS)[0]["total"]
    assert total.value == Decimal("1000") and total.currency == CurrencyCode("EUR")
    upstream = report.rows(r.ReportTableKey.SCENARIO_SUMMARY_V1)[0]["upstream_portfolio_value"]
    assert upstream.value == Decimal("800" if currency == "GBP" else "1000")
    assert upstream.currency == CurrencyCode(currency)
    if currency == "GBP":
        assert any(
            note.kind is r.ReportNoteKind.WARNING and "EUR" in note.text and "GBP" in note.text
            for note in report.manifest.notes
        )
        assert "1000 EUR" in report.pdf_body_text and "800 GBP" in report.pdf_body_text
    after = saved(case)
    assert (
        after.input_payload == original.input_payload
        and after.result_payload == original.result_payload
    )
    await isolation_and_revocation(case, reports, command, completed)


async def isolation_and_revocation(
    case: ScenarioCase,
    reports: PostgresReportService,
    command: app.GenerateReportCommand,
    completed: app.ReportJobStatus,
) -> None:
    account = case.command.account_id
    artifact = completed.artifacts[0]
    grant = await reports.create_report_download_grant(
        case.principal, account, completed.job_id, artifact.artifact_id
    )
    for wrong in (service(case, 1), service(case, 2)):
        with no_private_reads(case):
            for unavailable_operation in (
                partial(wrong.get_report_status, case.principal, account, completed.job_id),
                partial(wrong.get_report_manifest, case.principal, account, completed.job_id),
                partial(
                    wrong.create_report_download_grant,
                    case.principal,
                    account,
                    completed.job_id,
                    artifact.artifact_id,
                ),
                partial(
                    wrong.download_report_artifact,
                    case.principal,
                    account,
                    completed.job_id,
                    artifact.artifact_id,
                    grant_token=grant.token,
                ),
            ):
                with pytest.raises(app.ReportServiceError) as error:
                    await unavailable_operation()
                assert error.value.code is app.ReportServiceErrorCode.NOT_FOUND
        page = await wrong.list_reports(case.principal, account, query=app.ReportListQuery(limit=1))
        assert page.items == () and page.total == 0
    second = await reports.generate_report(
        case.principal,
        app.GenerateReportCommand(
            selection=selection(case, formats=(r.ReportFormat.JSON,)), idempotency_key=uuid4().hex
        ),
    )
    page = await reports.list_reports(case.principal, account, query=app.ReportListQuery(limit=1))
    assert page.total == 2 and page.next_cursor is not None
    tail = await reports.list_reports(
        case.principal, account, query=app.ReportListQuery(limit=1, cursor=page.next_cursor)
    )
    assert {item.job_id for item in (*page.items, *tail.items)} == {second.job_id, completed.job_id}
    assert tail.next_cursor is None
    with pytest.raises(app.ReportServiceError) as error:
        await service(case, 2).list_reports(
            case.principal, account, query=app.ReportListQuery(limit=1, cursor=page.next_cursor)
        )
    assert error.value.code is app.ReportServiceErrorCode.VALIDATION_FAILED
    revoke_report(case)
    with no_private_reads(case):
        for operation in (
            lambda: reports.get_report_status(case.principal, account, completed.job_id),
            lambda: reports.get_report_manifest(case.principal, account, completed.job_id),
            lambda: reports.create_report_download_grant(
                case.principal, account, completed.job_id, artifact.artifact_id
            ),
            lambda: reports.download_report_artifact(
                case.principal,
                account,
                completed.job_id,
                artifact.artifact_id,
                grant_token=grant.token,
            ),
            lambda: reports.generate_report(case.principal, command),
            lambda: reports.generate_report(
                case.principal, replace(command, idempotency_key=uuid4().hex)
            ),
        ):
            with pytest.raises(app.ReportServiceError) as error:
                await operation()
            assert error.value.code is app.ReportServiceErrorCode.ACCESS_DENIED


@pytest.mark.parametrize("cancelled", [False, True], ids=["queued", "cancelled"])
async def test_only_succeeded_owned_scenario_can_be_captured(
    scenario_case: ScenarioCase, cancelled: bool
) -> None:
    case = scenario_case
    if cancelled:
        status = await cancel_scenario(case, case.run.id)
        assert status.state.value == "cancelled"
    with no_private_reads(case), pytest.raises(app.ReportServiceError) as error:
        await service(case).generate_report(
            case.principal,
            app.GenerateReportCommand(
                selection=selection(case, formats=(r.ReportFormat.JSON,)),
                idempotency_key=uuid4().hex,
            ),
        )
    assert error.value.code is app.ReportServiceErrorCode.REPORT_UNAVAILABLE
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ReportJobModel)) == 0
