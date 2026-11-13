"""Original physical copy deadlines remain independent of longer stored-source TTLs."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.scenario import ScenarioVersionContent
from trading212_domain.sources import LicensePermission
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    ReportDefinitionModel,
    ReportDispatchOutboxModel,
    ReportInputChunkModel,
    ReportInputDependencyModel,
    ReportInputLicenseModel,
    ReportInputPinModel,
    ReportInputPremiumDependencyModel,
    ReportInputSnapshotModel,
    ReportJobModel,
)
from trading212_persistence.report_sources import original_report_copy_deadline
from trading212_persistence.source_models import PriceSnapshotModel
from trading212_security.principals import AuthorizationError, Scope

from tests.integration.report_runtime_sources import fresh_report_xray
from tests.integration.test_premium_report_v3_sources_postgres import (
    publish_replay_history,
    select_run,
    sources,
)
from tests.integration.test_premium_reports_v3_postgres import selection, service
from tests.integration.test_report_v3_retention_postgres import capture
from tests.integration.test_scenario_retention_postgres import published
from tests.integration.test_scenario_runs_postgres import ScenarioCase, cancel_scenario
from tests.integration.test_scenario_runs_postgres import scenario_case as scenario_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def report_counts(case: ScenarioCase) -> tuple[int, ...]:
    with case.sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in (
                ReportInputSnapshotModel,
                ReportInputChunkModel,
                ReportInputPinModel,
                ReportInputDependencyModel,
                ReportInputPremiumDependencyModel,
                ReportInputLicenseModel,
                ReportDefinitionModel,
                ReportJobModel,
                ReportDispatchOutboxModel,
                ApplicationCommandIdentityModel,
            )
        )


@pytest.mark.parametrize("current_days,expected_days", [(7, 7), (3650, 30)])
async def test_current_and_original_license_metadata_bound_copy_without_changing_source(
    scenario_case: ScenarioCase, current_days: int, expected_days: int
) -> None:
    case = scenario_case
    source = await publish_replay_history(case)
    await sources(case).register_source_license(
        case.principal,
        replace(
            source.license,
            id=str(uuid4()),
            version="current-copy-bound",
            effective_at=case.now,
            retention_days=current_days,
        ),
        idempotency_key=uuid4().hex,
        correlation_id="original-copy-bound",
    )
    with case.sessions() as session, session.begin():
        physical = session.get_one(PriceSnapshotModel, UUID(source.price_snapshot_id))
        original_expiry = physical.expires_at
        authorization = authorize_report_request(
            session,
            case.principal,
            account_id=case.command.account_id,
            required_scopes=frozenset({Scope.PORTFOLIO_READ, Scope.REPORTS_WRITE}),
            now=case.now,
        )
        dependency = ReportInputDependencyModel(
            id=uuid4(),
            owner_id=physical.owner_id,
            created_at=case.now,
            input_id=uuid4(),
            source_key="original-price",
            kind="price",
            source_id=physical.id,
            parent_id=None,
            content_digest=physical.content_digest,
            provider_id=physical.provider_id,
            license_version_id=physical.license_version_id,
            expires_at=physical.expires_at,
            price_snapshot_id=physical.id,
        )
        expected = physical.created_at + timedelta(days=expected_days)
        assert expected < original_expiry == physical.created_at + timedelta(days=365)
        assert (
            original_report_copy_deadline(
                session, authorization, dependencies=(dependency,), now=case.now
            )
            == expected
        )
        dependency.expires_at = original_expiry - timedelta(microseconds=1)
        with pytest.raises(AuthorizationError):
            original_report_copy_deadline(
                session, authorization, dependencies=(dependency,), now=case.now
            )
        assert session.get_one(PriceSnapshotModel, physical.id).expires_at == original_expiry


async def test_sql_accepts_original_boundary_and_rejects_one_microsecond_overlong_open_capture(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    await cancel_scenario(case, case.run.id)
    fresh = await fresh_report_xray(case.xray)
    # Distinct normal creation clocks make the root deadline later than its source.
    case.now = max(datetime.now(UTC), case.now + timedelta(seconds=2))
    case.command = replace(
        case.command,
        xray_run_id=UUID(fresh.context.run_id),
        source_cutoff_at=fresh.context.source_cutoff_at,
        idempotency_key=uuid4().hex,
    )
    case.run = await case.service.create_run(case.principal, case.command)
    await published(case)
    expected = fresh.context.source_cutoff_at + timedelta(days=30)
    assert expected + timedelta(microseconds=1) < case.run.expires_at - timedelta(seconds=1)
    before = report_counts(case)
    for extra in (timedelta(0), timedelta(microseconds=1)):
        if extra:
            with (
                case.sessions() as session,
                pytest.raises(DBAPIError, match="Premium report source is unavailable") as failure,
                session.begin(),
            ):
                identifier = capture(session, case, copy_deadline=expected + extra)
                assert (
                    session.scalar(
                        text(
                            "SELECT report_premium_v3_basis_valid(d,i) "
                            "FROM report_input_snapshots i "
                            "JOIN report_input_premium_dependencies d "
                            "ON d.input_id=i.id WHERE i.id=:id"
                        ),
                        {"id": identifier},
                    )
                    is True
                )
                session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            assert getattr(failure.value.orig, "sqlstate", None) == "23514"
        else:
            with case.sessions() as session:
                identifier = capture(session, case, copy_deadline=expected)
                assert session.get_one(ReportInputSnapshotModel, identifier).expires_at == expected
                session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                assert (
                    session.scalar(
                        func.report_premium_restricted(
                            UUID(case.principal.owner_id), identifier, case.now
                        )
                    )
                    is False
                )
            # The successful guard control is deliberately rolled back with this session.
        assert report_counts(case) == before


@pytest.mark.parametrize("restriction", ["expired_original", "report_denied"])
async def test_original_expiry_and_permission_denial_roll_back_new_report_capture(
    scenario_case: ScenarioCase, restriction: str
) -> None:
    case = scenario_case
    source = await publish_replay_history(case)
    original = await select_run(
        case,
        ScenarioVersionContent(
            name="Original copy deadline", description="Synthetic rollback", mode="compounded"
        ),
        source.selected,
    )
    if restriction == "expired_original":
        with case.sessions() as session:
            physical = session.get_one(PriceSnapshotModel, UUID(source.price_snapshot_id))
            case.now = physical.created_at + timedelta(days=30, microseconds=1)
            assert case.now < original.expires_at < physical.expires_at
    else:
        await sources(case).register_source_license(
            case.principal,
            replace(
                source.license,
                id=str(uuid4()),
                version="copy-report-denied",
                effective_at=case.now,
                report=LicensePermission.DENIED,
            ),
            idempotency_key=uuid4().hex,
            correlation_id="copy-permission-rollback",
        )
    before = report_counts(case)
    selected = replace(
        selection(case, formats=(r.ReportFormat.JSON,)),
        start_date=source.selected.start_date,
        end_date=source.selected.end_date,
    )
    with pytest.raises(app.ReportServiceError) as failure:
        await service(case).generate_report(
            case.principal,
            app.GenerateReportCommand(selection=selected, idempotency_key=uuid4().hex),
        )
    assert failure.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
    assert report_counts(case) == before
