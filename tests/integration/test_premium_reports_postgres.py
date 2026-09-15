"""Real selected risk captures, version isolation and complete private artifacts."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from inspect import unwrap
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from trading212_analytics.risk_history import validate_risk_capacity
from trading212_application import historical as historical_app
from trading212_application import report_jobs
from trading212_application import reports as app
from trading212_application import xray as xray_app
from trading212_application.xray_ingestion import XrayPolicyRegistration, XrayTaxonomyRegistration
from trading212_domain import reports as r
from trading212_domain.historical import HistoricalFrequency
from trading212_domain.historical_results import PerformanceOptions
from trading212_domain.report_v3 import ReportRiskRunSelection, ReportSelectionV3
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_persistence.models import PrincipalModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import ReportInputPremiumDependencyModel, ReportJobModel
from trading212_persistence.report_service import PostgresReportService
from trading212_persistence.xray_service import PostgresXrayService
from trading212_security.principals import Scope
from trading212_worker.historical_seed import CURSOR_KEY
from trading212_worker.report_tasks import ReportExecutionState, execute_report_message
from trading212_worker.xray_fixture import synthetic_xray_policy

from tests.integration.premium_report_v3_artifacts import download_v3
from tests.integration.test_historical_postgres import historical_database as _historical_database
from tests.integration.test_historical_seed import NOW
from tests.integration.test_historical_seed import seeded_history as _seeded_history
from tests.integration.test_report_type_matrix_postgres import _download
from tests.integration.test_risk_retention_postgres import published
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case

pytestmark = pytest.mark.integration
historical_database = pytest.fixture(scope="function")(unwrap(_historical_database))
seeded_history = pytest.fixture(scope="function")(unwrap(_seeded_history))


async def selected_xray(case: RunCase) -> xray_app.PathsView:
    service = PostgresXrayService(
        sessions=case.sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW
    )
    policy = replace(synthetic_xray_policy(), id=uuid4())
    await service.register_xray_policy(
        case.principal,
        str(case.command.account_id),
        XrayPolicyRegistration(
            key="premium-report-xray",
            effective_at=case.command.window.source_cutoff_at.replace(year=2024),
            policy=policy,
            taxonomies=tuple(
                XrayTaxonomyRegistration(
                    id=str(item.taxonomy_id),
                    dimension=item.dimension,
                    key=item.key,
                    version=item.version,
                )
                for item in policy.taxonomy_versions
            ),
        ),
        idempotency_key=uuid4().hex,
        correlation_id="premium-report-test",
    )
    request = xray_app.XrayRunRequest(
        snapshot_id=str(case.command.portfolio_snapshot_id),
        source_cutoff_at=case.command.window.source_cutoff_at,
        currency=xray_app.ExplicitCurrency(
            reporting_currency=case.command.window.reporting_currency
        ),
    )
    exposure = await service.get_effective_exposure(
        case.principal,
        str(case.command.account_id),
        query=xray_app.EffectiveExposureQuery(request=request, limit=1),
    )
    paths = await service.get_effective_exposure(
        case.principal,
        str(case.command.account_id),
        query=xray_app.EffectiveExposureQuery(
            request=replace(request, run_id=exposure.context.run_id),
            options=xray_app.Paths(),
            limit=100,
        ),
    )
    assert isinstance(paths, xray_app.PathsView)
    assert paths.paths.next_cursor is None and paths.paths.total > 0
    case.command = replace(case.command, xray_run_id=UUID(paths.context.run_id))
    return paths


@pytest.mark.parametrize("profile", [2, 3])
@pytest.mark.parametrize("with_xray", [False, True])
async def test_selected_risk_all_formats_and_sql_version_collections(
    run_case: RunCase, with_xray: bool, profile: int
) -> None:
    case = run_case
    with case.sessions() as session, session.begin():
        identity = session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.issuer == case.principal.issuer,
                PrincipalModel.subject == case.principal.subject,
            )
        )
        assert identity is not None
        principal_id = str(identity.id)
        provision_principal_scopes(
            session,
            principal_id=identity.id,
            scopes=frozenset(Scope),
            now=datetime.now(UTC) - timedelta(days=30),
        )
    case.principal = replace(case.principal, principal_id=principal_id, scopes=frozenset(Scope))
    # A complete month exercises the twenty-observation rolling method within
    # the unchanged PDF/page/artifact bounds; no source trace is truncated.
    window = replace(
        case.command.window, end_date=case.command.window.start_date + timedelta(days=30)
    )
    history = await PostgresHistoricalService(
        case.sessions,
        cursor_signing_key=CURSOR_KEY,
        clock=lambda: NOW,
    ).get_performance_summary(
        case.principal,
        str(case.command.account_id),
        query=historical_app.PerformanceSummaryQuery(
            window=window,
            options=PerformanceOptions(frequency=HistoricalFrequency.DAILY),
        ),
    )
    case.command = replace(
        case.command,
        window=window,
        historical_input_snapshot_id=UUID(history.context.input_snapshot_id),
    )
    paths = await selected_xray(case) if with_xray else None
    run = await published(case)
    assert run.result is not None
    auth_now = datetime.now(UTC)
    case.principal = replace(
        case.principal,
        authenticated_at=auth_now - timedelta(minutes=1),
        expires_at=auth_now + timedelta(hours=2),
    )
    v1 = PostgresReportService(case.sessions, cursor_signing_key=CURSOR_KEY)
    premium = PostgresReportService(
        case.sessions,
        cursor_signing_key=CURSOR_KEY,
        contract_version=profile,
        risk_preflight=validate_risk_capacity,
    )
    selection = r.ReportSelection(
        account_id=case.command.account_id,
        snapshot_id=case.command.portfolio_snapshot_id,
        reporting_currency=case.command.window.reporting_currency,
        start_date=case.command.window.start_date,
        end_date=case.command.window.end_date,
        source_cutoff_at=case.command.window.source_cutoff_at,
        report_type=r.ReportType.PORTFOLIO_SUMMARY,
        sections=(
            r.ReportSection.OVERVIEW,
            r.ReportSection.ALLOCATION,
            r.ReportSection.QUALITY,
            r.ReportSection.RISK,
        ),
        formats=tuple(r.ReportFormat),
        risk_run_id=run.id,
    )
    key = uuid4().hex
    selected = (
        ReportSelectionV3(
            **{
                field.name: getattr(selection, field.name)
                for field in fields(selection)
                if field.name != "risk_run_id"
            },
            premium_run=ReportRiskRunSelection(run_id=run.id),
        )
        if profile == 3
        else selection
    )
    command = app.GenerateReportCommand(selection=selected, idempotency_key=key)
    queued = await premium.generate_report(case.principal, command)
    assert (
        queued.context is not None
        and queued.context.profile_version == f"report_sections_v{profile}"
    )
    assert await premium.generate_report(case.principal, command) == queued
    legacy_selection = replace(
        selection,
        risk_run_id=None,
        sections=tuple(
            section for section in selection.sections if section is not r.ReportSection.RISK
        ),
        formats=(r.ReportFormat.JSON,),
    )
    # Separate semantic command namespaces permit the same owner's key in each version.
    legacy = await v1.generate_report(
        case.principal,
        app.GenerateReportCommand(
            selection=legacy_selection,
            idempotency_key=key,
        ),
    )
    assert legacy.job_id != queued.job_id
    for service, foreign in ((v1, queued), (premium, legacy)):
        with pytest.raises(app.ReportServiceError) as error:
            await service.get_report_status(case.principal, selection.account_id, foreign.job_id)
        assert error.value.code is app.ReportServiceErrorCode.NOT_FOUND
    for service, expected in ((v1, legacy), (premium, queued)):
        page = await service.list_reports(
            case.principal, selection.account_id, query=app.ReportListQuery(limit=1)
        )
        assert page.total == 1 and page.next_cursor is None
        assert tuple(item.job_id for item in page.items) == (expected.job_id,)
    with case.sessions() as session:
        job = session.get_one(ReportJobModel, queued.job_id)
        dependency = session.scalar(
            select(ReportInputPremiumDependencyModel).where(
                ReportInputPremiumDependencyModel.input_id == job.input_id,
            )
        )
        assert dependency is not None and dependency.run_id == run.id
        assert dependency.input_digest == run.input_digest
        message = report_jobs.ReportTaskMessage(
            job_id=job.id,
            owner_id=job.owner_id,
            account_id=job.account_id,
            capture_id=job.input_id,
            input_digest=job.input_digest,
        )
    state = await execute_report_message(
        PostgresReportJobStore(case.sessions),
        message,
        consumer_id="premium-report-test",
    )
    completed = await premium.get_report_status(case.principal, selection.account_id, queued.job_id)
    assert state is ReportExecutionState.COMPLETED, completed.failure_code
    report = (
        await download_v3(premium, case.principal, selection.account_id, completed)
        if profile == 3
        else await _download(premium, case.principal, selection.account_id, completed)
    )
    assert report.manifest.document.document_schema_version == f"{profile}.0.0"
    assert all(context.schema_version == f"{profile}.0.0" for context in report.manifest.contexts)
    observed = report.rows(r.ReportTableKey.RISK_OBSERVED_V1)[0]
    assert (
        observed["volatility_annualized"].value == run.result.observed.volatility_annualized.value
    )
    assert observed["downside_annualized"].value == run.result.observed.downside_annualized.value
    proof_paths = report.rows(r.ReportTableKey.RISK_XRAY_PATHS_V1)
    if paths is None:
        assert proof_paths == ()
    else:
        assert len(proof_paths) == paths.paths.total
        expected_paths = {item.key: item for item in paths.paths.items}
        assert {item["key"].value for item in proof_paths} == set(expected_paths)
        for item in proof_paths:
            path = expected_paths[str(item["key"].value)]
            assert item["root_key"].value == path.root_key
            assert item["entity_id"].value == path.entity_id
            assert item["explicit_cash"].value == path.explicit_cash
            assert item["absolute_weight"].value == path.absolute_weight.value
            amount = path.reporting_value.value
            assert item["reporting_value"].value == (None if amount is None else amount.amount)
            assert item["reporting_value"].state.value == path.reporting_value.availability.value
        concentration = report.rows(r.ReportTableKey.RISK_CONCENTRATION_V1)[0]
        assert concentration["basis"].value == run.result.concentration.basis
        assert (
            concentration["effective_holdings"].value
            == run.result.concentration.effective_holdings.value
        )
    assert "Risk" in report.pdf_body_text or "risk" in report.pdf_body_text
    artifact = completed.artifacts[0]
    with pytest.raises(app.ReportServiceError) as error:
        await v1.create_report_download_grant(
            case.principal,
            selection.account_id,
            queued.job_id,
            artifact.artifact_id,
        )
    assert error.value.code is app.ReportServiceErrorCode.NOT_FOUND
