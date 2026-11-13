"""Real legacy copies resume under a shared budget without recursive cleanup predicates."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from inspect import unwrap
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_application.scenario import ScenarioComponentPageQuery
from trading212_domain import reports as r
from trading212_domain.scenario import (
    ScenarioRateShock,
    ScenarioSensitivityVersionPin,
    ScenarioVersionContent,
)
from trading212_domain.sources import LicensePermission
from trading212_persistence.legacy_report_retention_scan import (
    LegacyReportScanInput,
    scan_legacy_report,
)
from trading212_persistence.premium_models import PremiumRunLicenseModel
from trading212_persistence.report_models import (
    ReportInputDependencyModel,
    ReportInputPremiumDependencyModel,
    ReportInputSnapshotModel,
    ReportJobModel,
    ReportRetentionWorkModel,
)
from trading212_persistence.report_retention import expire_report_payloads
from trading212_persistence.risk_models import RiskResultModel
from trading212_persistence.source_models import ProviderLicenseVersionModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_store import license_view

from tests.integration.test_historical_postgres import historical_database as _historical_database
from tests.integration.test_historical_seed import NOW
from tests.integration.test_historical_seed import seeded_history as _seeded_history
from tests.integration.test_premium_report_retention_postgres import capture, report_policy
from tests.integration.test_premium_report_v3_sources_postgres import (
    publish_sensitivity,
    select_run,
    sources,
)
from tests.integration.test_premium_reports_v3_postgres import (
    no_private_reads,
    saved,
    selection,
    service,
)
from tests.integration.test_risk_retention_postgres import published
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case
from tests.integration.test_scenario_runs_postgres import ScenarioCase
from tests.integration.test_scenario_runs_postgres import scenario_case as scenario_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration
historical_database = pytest.fixture(scope="function")(unwrap(_historical_database))
seeded_history = pytest.fixture(scope="function")(unwrap(_seeded_history))


@contextmanager
def reject_recursive_cleanup(session: Session) -> Iterator[None]:
    """Canaries reject accidental old cleanup calls; all normal guards still run.

    The originals are restored in the same transaction. A failing assertion rolls
    back replacement DDL, so this cannot affect another serial fixture.
    """
    signatures = (
        (
            "report_premium_restricted(uuid,uuid,timestamptz)",
            "report_premium_restricted(p_owner uuid,p_input uuid,p_at timestamptz)",
        ),
        (
            "report_premium_v3_sources_restricted(uuid,uuid,uuid,text,timestamptz)",
            (
                "report_premium_v3_sources_restricted(p_owner uuid,p_input uuid,p_run "
                "uuid,p_kind text,p_at timestamptz)"
            ),
        ),
        ("scenario_capture_complete(uuid)", "scenario_capture_complete(p_run uuid)"),
    )
    originals = []
    for signature, declaration in signatures:
        original = session.scalar(
            text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": signature}
        )
        assert isinstance(original, str)
        originals.append(original)
        session.execute(
            text(
                f"CREATE OR REPLACE FUNCTION {declaration} RETURNS boolean "
                "LANGUAGE plpgsql STABLE AS $$ BEGIN RAISE EXCEPTION "
                "'Recursive maintenance canary reached'; END $$"
            )
        )
    yield
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    for original in originals:
        session.execute(text(original))


async def test_v2_report_only_policy_resumes_and_preserves_saved_risk(run_case: RunCase) -> None:
    case = run_case
    run = await published(case, clock=lambda: datetime.now(UTC))
    owner = UUID(case.principal.owner_id)
    with case.sessions() as session, session.begin():
        identifier = capture(session, case, run, at=datetime.now(UTC))
        original = session.scalar(
            select(RiskResultModel.canonical_result).where(RiskResultModel.run_id == run.id)
        )
        assert original
        assert (
            session.scalar(func.report_premium_restricted(owner, identifier, datetime.now(UTC)))
            is False
        )
    report_policy(case, run, "denied", at=datetime.now(UTC))
    at = datetime.now(UTC)
    assert at < run.expires_at - timedelta(seconds=1)
    with case.sessions() as session, session.begin(), reject_recursive_cleanup(session):
        expire_report_payloads(session, at=at, budget=SourcePurgeBudget(bytes_removed=0))
        initial = session.scalar(
            select(ReportRetentionWorkModel).where(ReportRetentionWorkModel.input_id == identifier)
        )
        assert initial is not None and initial.completed_at is None
    for _ in range(30):
        budget = SourcePurgeBudget(rows_inspected=192)
        with case.sessions() as session, session.begin(), reject_recursive_cleanup(session):
            expire_report_payloads(session, at=at, budget=budget)
            work = session.scalar(
                select(ReportRetentionWorkModel).where(
                    ReportRetentionWorkModel.input_id == identifier
                )
            )
            if work is not None:
                assert work.reason == "source"
                assert work.legacy_source_kind == "premium_license"
                if work.completed_at is not None:
                    break
        assert 0 <= budget.rows_inspected <= 192
    else:
        pytest.fail("V2 bounded cleanup did not finish")
    with case.sessions() as session:
        assert (
            session.scalar(
                select(RiskResultModel.canonical_result).where(RiskResultModel.run_id == run.id)
            )
            == original
        )
        assert session.get_one(ReportInputSnapshotModel, identifier).purged_at is not None
        assert (
            session.scalar(
                select(ReportInputPremiumDependencyModel.copy_pending).where(
                    ReportInputPremiumDependencyModel.input_id == identifier
                )
            )
            is False
        )
        assert session.scalar(func.report_capture_pending(owner, identifier)) is False


async def test_v2_original_clock_is_not_replaced_by_v3_copy_deadline_rule(
    run_case: RunCase,
) -> None:
    case = run_case
    run = await published(case)
    with case.sessions() as session:
        lineage = session.scalars(
            select(PremiumRunLicenseModel).where(PremiumRunLicenseModel.run_id == run.id)
        ).first()
        assert lineage is not None
        pinned = session.get_one(ProviderLicenseVersionModel, lineage.license_version_id)
        current = session.scalar(
            select(ProviderLicenseVersionModel)
            .where(
                ProviderLicenseVersionModel.provider_id == pinned.provider_id,
                ProviderLicenseVersionModel.effective_at <= NOW,
            )
            .order_by(
                ProviderLicenseVersionModel.effective_at.desc(),
                ProviderLicenseVersionModel.version_number.desc(),
                ProviderLicenseVersionModel.id.desc(),
            )
            .limit(1)
        )
        assert current is not None and pinned.retention_days and current.retention_days
        days = min(pinned.retention_days, current.retention_days)
        origin = NOW - timedelta(days=days) + timedelta(hours=1)
        parameters = {
            "owner": pinned.owner_id,
            "provider": pinned.provider_id,
            "license": pinned.id,
            "origin": origin,
            "until": NOW + timedelta(hours=2),
            "at": NOW,
        }
        query = text(
            "SELECT restricted,next_deadline FROM legacy_report_license_probe(:owner,:pro"
            "vider,:license,:origin,:until,:at,:mode)"
        )
        v2 = session.execute(query, {**parameters, "mode": "v2"}).one()
        v3 = session.execute(query, {**parameters, "mode": "v3"}).one()
        assert v2.restricted is False and v2.next_deadline == NOW + timedelta(hours=1)
        assert v3.restricted is True
        expired = session.execute(
            query, {**parameters, "at": NOW + timedelta(hours=1), "mode": "v2"}
        ).one()
        assert expired.restricted is True


async def test_v3_exact_witness_and_physical_flags_survive_incremental_cleanup(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    sensitivity = await publish_sensitivity(case)
    version = sensitivity.versions[0]
    shock = ScenarioRateShock(
        source=ScenarioSensitivityVersionPin(
            version_id=version.version_id,
            content_digest=version.content_digest,
            driver_id=version.driver.driver_id,
            driver_definition_version_id=version.driver.definition_version_id,
        ),
        size=Decimal("0.01"),
    )
    original = await select_run(
        case,
        ScenarioVersionContent(
            name="Bounded legacy report",
            description="Synthetic source retention regression",
            mode="compounded",
            shocks=(shock,),
        ),
    )
    case.now = max(case.now, datetime.now(UTC))
    reports = service(case)
    selected = replace(
        selection(case, formats=(r.ReportFormat.JSON,)),
        start_date=original.value.valuation_at.date(),
        end_date=original.value.valuation_at.date(),
    )
    pending = await reports.generate_report(
        case.principal,
        app.GenerateReportCommand(selection=selected, idempotency_key=uuid4().hex, ttl_days=30),
    )
    owner = UUID(case.principal.owner_id)
    with case.sessions() as session:
        job = session.get_one(ReportJobModel, pending.job_id)
        identifier = job.input_id
        created_at = session.get_one(ReportInputSnapshotModel, identifier).created_at
        physical = tuple(
            session.scalars(
                select(ReportInputDependencyModel.id).where(
                    ReportInputDependencyModel.input_id == identifier
                )
            )
        )
        assert physical
        value = LegacyReportScanInput(
            owner, case.command.account_id, identifier, case.run.id, 3, "scenario"
        )
    # A capture committed after a maintenance timestamp is deferred, never
    # interpreted as a current source restriction by its later original clock.
    with case.sessions() as session, session.begin(), reject_recursive_cleanup(session):
        expire_report_payloads(
            session,
            at=created_at - timedelta(microseconds=1),
            budget=SourcePurgeBudget(rows_inspected=192),
        )
        assert (
            session.scalar(
                select(ReportRetentionWorkModel.id).where(
                    ReportRetentionWorkModel.input_id == identifier
                )
            )
            is None
        )
        assert session.scalar(func.report_capture_pending(owner, identifier)) is True
    case.now = max(case.now, datetime.now(UTC))
    assert created_at <= case.now
    # The real saved source remains permitted. A made-up witness or foreign
    # dependency must not authorize destruction, and flags cannot clear early.
    for witness in (uuid4(), physical[0]):
        with (
            case.sessions() as session,
            pytest.raises(DBAPIError, match="No current legacy report source restriction"),
            session.begin(),
        ):
            session.add(
                ReportRetentionWorkModel(
                    id=uuid4(),
                    owner_id=owner,
                    input_id=identifier,
                    reason="source",
                    legacy_source_kind="physical",
                    legacy_source_id=witness,
                    created_at=case.now,
                    started_at=case.now,
                    completed_at=None,
                )
            )
            session.flush()
    with case.sessions() as session, pytest.raises(DBAPIError), session.begin():
        session.execute(
            update(ReportInputDependencyModel)
            .where(ReportInputDependencyModel.id == physical[0])
            .values(copy_pending=False)
        )
    # Start a partial proof, then change policy. This advances the protected epoch
    # and must invalidate the saved prefix before a later clean conclusion.
    with case.sessions() as session, session.begin(), no_private_reads(case):
        assert (
            scan_legacy_report(
                session, value, at=case.now, budget=SourcePurgeBudget(rows_inspected=40)
            )
            == "pending"
        )
    with case.sessions() as session:
        license = license_view(
            session.get_one(ProviderLicenseVersionModel, version.license_version_id)
        )
    await sources(case).register_source_license(
        case.principal,
        replace(
            license,
            id=str(uuid4()),
            version="2-retention-report-denied",
            effective_at=case.now,
            report=LicensePermission.DENIED,
        ),
        idempotency_key=uuid4().hex,
        correlation_id="bounded-report-retention",
    )
    remaining = len(physical)
    for _ in range(100):
        budget = SourcePurgeBudget(rows_inspected=192)
        with case.sessions() as session, session.begin(), reject_recursive_cleanup(session):
            expire_report_payloads(session, at=case.now, budget=budget)
            flags = session.scalar(
                select(func.count())
                .select_from(ReportInputDependencyModel)
                .where(
                    ReportInputDependencyModel.input_id == identifier,
                    ReportInputDependencyModel.copy_pending.is_(True),
                )
            )
            assert flags is not None and flags <= remaining
            remaining = flags
            work = session.scalar(
                select(ReportRetentionWorkModel).where(
                    ReportRetentionWorkModel.input_id == identifier
                )
            )
            if work is not None and work.completed_at is not None:
                assert remaining == 0
                assert (
                    session.scalar(
                        select(ReportInputPremiumDependencyModel.copy_pending).where(
                            ReportInputPremiumDependencyModel.input_id == identifier
                        )
                    )
                    is False
                )
                break
        assert 0 <= budget.rows_inspected <= 192
    else:
        pytest.fail("V3 bounded report cleanup did not finish")
    assert saved(case).input_payload == original.input_payload
    assert saved(case).result_payload == original.result_payload
    assert (
        await case.service.get_run(case.principal, case.run.id, ScenarioComponentPageQuery())
    ).result is not None
