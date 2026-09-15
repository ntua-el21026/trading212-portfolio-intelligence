"""Real capture flags and fixed source witnesses cannot authorize forged purges."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from trading212_application import reports as app
from trading212_domain.sources import LicensePermission
from trading212_persistence.projection_report_retention import expire_projection_report_payloads
from trading212_persistence.report_models import (
    ReportInputPremiumDependencyModel,
    ReportJobModel,
    ReportRetentionWorkModel,
)
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.projection_report_runtime import (
    execute_saved,
    report_selection,
    report_service,
    saved_projection,
)
from tests.integration.test_projection_report_sources_postgres import (
    pin_calibration,
    publish_calibration,
)
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


async def test_live_copy_flag_and_exact_witness_are_independent_of_mutable_scan_state(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    calibration = await publish_calibration(case, report=LicensePermission.ALLOWED)
    await pin_calibration(case, calibration)
    original = await execute_saved(case)
    reports = report_service(case)
    queued = await reports.generate_report(
        case.principal,
        app.GenerateReportCommand(
            selection=report_selection(case),
            idempotency_key=uuid4().hex,
            ttl_days=30,
        ),
    )
    owner = UUID(case.principal.owner_id)
    physical = UUID(calibration.snapshot.id)
    with case.sessions() as session:
        input_id = session.get_one(ReportJobModel, queued.job_id).input_id
        dependency = session.scalar(
            select(ReportInputPremiumDependencyModel).where(
                ReportInputPremiumDependencyModel.input_id == input_id,
            )
        )
        assert dependency is not None and dependency.copy_pending is True
        for kind, identifier in (("price", physical), ("price", uuid4()), ("license", uuid4())):
            assert (
                session.scalar(
                    select(
                        func.report_projection_witness_restricted(
                            owner,
                            input_id,
                            kind,
                            identifier,
                            case.now,
                        )
                    )
                )
                is False
            )
    # A caller cannot clear a real live-copy flag or manufacture an expired
    # source marker by supplying the identity of a currently allowed source.
    with (
        pytest.raises(IntegrityError, match="immutable"),
        case.sessions() as session,
        session.begin(),
    ):
        session.execute(
            update(ReportInputPremiumDependencyModel)
            .where(
                ReportInputPremiumDependencyModel.input_id == input_id,
            )
            .values(copy_pending=False)
        )
    with (
        pytest.raises(IntegrityError, match="No current projection report source restriction"),
        case.sessions() as session,
        session.begin(),
    ):
        session.add(
            ReportRetentionWorkModel(
                id=uuid4(),
                owner_id=owner,
                input_id=input_id,
                created_at=case.now,
                started_at=case.now,
                reason="source",
                completed_at=None,
                projection_source_kind="price",
                projection_source_id=physical,
            )
        )
        session.flush()
    await calibration.service.register_source_license(
        case.principal,
        replace(
            calibration.license,
            id=str(uuid4()),
            version="copy-witness-denied",
            effective_at=case.now,
            report=LicensePermission.DENIED,
        ),
        idempotency_key=uuid4().hex,
        correlation_id="projection-copy-witness",
    )
    with case.sessions() as session:
        assert (
            session.scalar(
                select(
                    func.report_projection_witness_restricted(
                        owner,
                        input_id,
                        "price",
                        physical,
                        case.now,
                    )
                )
            )
            is True
        )
        assert (
            session.scalar(
                select(
                    func.report_projection_witness_restricted(
                        uuid4(),
                        input_id,
                        "price",
                        physical,
                        case.now,
                    )
                )
            )
            is False
        )
        assert (
            session.scalar(
                select(
                    func.report_projection_witness_restricted(
                        owner,
                        input_id,
                        "price",
                        uuid4(),
                        case.now,
                    )
                )
            )
            is False
        )
    outcomes = []
    for _ in range(100):
        budget = SourcePurgeBudget(rows_inspected=96, rows_removed=10)
        with case.sessions() as session, session.begin():
            complete = expire_projection_report_payloads(
                session, at=case.now, owner=owner, budget=budget
            )
        assert 0 <= budget.rows_inspected <= 96
        outcomes.append(complete)
        if complete:
            break
    else:
        pytest.fail("report-copy flag did not complete its bounded cleanup")
    assert False in outcomes
    with case.sessions() as session:
        dependency = session.scalar(
            select(ReportInputPremiumDependencyModel).where(
                ReportInputPremiumDependencyModel.input_id == input_id,
            )
        )
        work = session.scalar(
            select(ReportRetentionWorkModel).where(
                ReportRetentionWorkModel.owner_id == owner,
                ReportRetentionWorkModel.input_id == input_id,
            )
        )
        assert dependency is not None and dependency.copy_pending is False
        assert work is not None and work.completed_at is not None
        assert (work.projection_source_kind, work.projection_source_id) == ("price", physical)
        assert session.scalar(select(func.report_capture_pending(owner, input_id))) is False
    assert saved_projection(case) == original
