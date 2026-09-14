"""Risk admission, source authority and normalized publication using real seeded history."""

from dataclasses import dataclass, replace
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.risk import calculate_risk
from trading212_analytics.risk_history import validate_risk_capacity
from trading212_application import historical as historical_app
from trading212_application import risk as app
from trading212_domain import historical as d
from trading212_domain import historical_results as results
from trading212_domain.risk import RiskDefinitionContent
from trading212_persistence.historical_capture import HistoricalCaptureStore
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_persistence.models import PortfolioSnapshotModel, PrincipalModel
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
)
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_persistence.risk_definitions import RISK_WRITE_SCOPES
from trading212_persistence.risk_service import PostgresRiskService
from trading212_persistence.risk_storage import persist_risk_result
from trading212_security.principals import Principal
from trading212_worker.historical_seed import CURSOR_KEY, history_principal

from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import NOW, window
from tests.integration.test_historical_seed import seeded_history as seeded_history

pytestmark = pytest.mark.integration


@dataclass
class RunCase:
    sessions: sessionmaker[Session]
    service: PostgresRiskService
    principal: Principal
    command: app.CreateRiskRun


@pytest.fixture
async def run_case(seeded_history: tuple[sessionmaker[Session], dict[str, str]]) -> RunCase:
    sessions, ids = seeded_history
    original = history_principal(NOW)
    principal = replace(original, scopes=original.scopes | RISK_WRITE_SCOPES)
    account = UUID(ids["annual_account_id"])
    with sessions() as session, session.begin():
        identity = session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.issuer == principal.issuer,
                PrincipalModel.subject == principal.subject,
            )
        )
        if identity is None:
            identity = PrincipalModel(
                id=uuid4(),
                owner_id=UUID(principal.owner_id),
                issuer=principal.issuer,
                subject=principal.subject,
                status="active",
            )
            session.add(identity)
            session.flush()
        identity.status = "active"
        for scope in RISK_WRITE_SCOPES:
            grant = session.get(PrincipalScopeGrantModel, (identity.id, scope.value))
            if grant is None:
                session.add(
                    PrincipalScopeGrantModel(
                        principal_id=identity.id,
                        scope=scope.value,
                        granted_at=NOW - timedelta(days=1),
                        expires_at=None,
                        revoked_at=None,
                    )
                )
            else:
                grant.revoked_at = None
                grant.expires_at = None
        snapshot = session.scalar(
            select(PortfolioSnapshotModel)
            .where(PortfolioSnapshotModel.broker_account_id == account)
            .order_by(PortfolioSnapshotModel.valuation_at.desc())
            .limit(1)
        )
        assert snapshot is not None
        snapshot_id = snapshot.id
    history = PostgresHistoricalService(sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW)
    summary = await history.get_performance_summary(
        principal,
        str(account),
        query=historical_app.PerformanceSummaryQuery(
            window=window("annual"),
            options=results.PerformanceOptions(frequency=d.HistoricalFrequency.DAILY),
        ),
    )
    capture = await HistoricalCaptureStore(
        sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW
    ).load(principal, summary.context.input_snapshot_id)
    ref = capture.input.selection.reporting_calendar_ref
    assert ref is not None
    service = PostgresRiskService(
        sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW, preflight=validate_risk_capacity
    )
    definition = await service.create_definition(
        principal,
        app.CreateRiskDefinition(
            account_id=account,
            content=RiskDefinitionContent(
                name="Historical risk",
                description="Synthetic canonical history",
                calendar_id=ref.id,
                calendar_version=ref.version,
            ),
            idempotency_key=str(uuid4()),
            correlation_id="risk-run-fixture",
        ),
    )
    command = app.CreateRiskRun(
        account_id=account,
        definition_version_id=definition.current_version_id,
        portfolio_snapshot_id=snapshot_id,
        historical_input_snapshot_id=UUID(capture.id),
        window=window("annual"),
        idempotency_key=str(uuid4()),
        correlation_id="risk-run-fixture",
    )
    return RunCase(sessions, service, principal, command)


async def _cancel(case: RunCase, identifier: UUID) -> app.RiskRunView:
    return await case.service.cancel_run(
        case.principal,
        app.CancelRiskRun(
            run_id=identifier, idempotency_key=str(uuid4()), correlation_id="risk-test-cleanup"
        ),
    )


async def test_admission_is_atomic_opaque_and_semantically_idempotent(run_case: RunCase) -> None:
    case = run_case
    first = await case.service.create_run(case.principal, case.command)
    again = await case.service.create_run(
        case.principal, replace(case.command, correlation_id="new-trace")
    )
    assert first == again and first.state is app.PremiumJobState.QUEUED and first.result is None
    with case.sessions() as session:
        outbox = session.scalar(
            select(PremiumOutboxModel).where(PremiumOutboxModel.job_id == first.job_id)
        )
        assert (
            outbox is not None
            and outbox.task_name == "risk.calculate.v1"
            and outbox.state == "pending"
        )
        capacity = session.get(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert (
            capacity is not None
            and capacity.active_jobs == 1
            and capacity.reserved_bytes == 33554432
        )
    changed = replace(
        case.command,
        window=replace(case.command.window, end_date=case.command.window.end_date.replace(day=30)),
    )
    with pytest.raises(app.RiskServiceError) as failure:
        await case.service.create_run(case.principal, changed)
    assert failure.value.code is app.RiskErrorCode.CONFLICT
    cancelled = await _cancel(case, first.id)
    assert cancelled.state is app.PremiumJobState.CANCELLED and cancelled.result is None
    with case.sessions() as session:
        capacity = session.get(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert capacity is not None and capacity.active_jobs == capacity.reserved_bytes == 0


async def test_two_active_jobs_limit_is_released_by_cancellation(run_case: RunCase) -> None:
    case = run_case
    first = await case.service.create_run(case.principal, case.command)
    second = await case.service.create_run(
        case.principal, replace(case.command, idempotency_key=str(uuid4()))
    )
    with pytest.raises(app.RiskServiceError) as failure:
        await case.service.create_run(
            case.principal, replace(case.command, idempotency_key=str(uuid4()))
        )
    assert failure.value.code is app.RiskErrorCode.RATE_LIMITED
    await _cancel(case, first.id)
    third = await case.service.create_run(
        case.principal, replace(case.command, idempotency_key=str(uuid4()))
    )
    await _cancel(case, second.id)
    await _cancel(case, third.id)


async def test_canonical_result_and_every_normalized_projection_round_trip(
    run_case: RunCase,
) -> None:
    case = run_case
    first = await case.service.create_run(case.principal, case.command)

    async def publish() -> None:
        def operation(session: Session, auth: object) -> None:
            from trading212_persistence.report_authorization import ReportAuthorization

            assert isinstance(auth, ReportAuthorization)
            root, run, job = case.service._run_rows(session, auth, first.id)
            inputs = case.service._current_inputs(session, auth, root, run)
            result = calculate_risk(
                inputs.historical, inputs.definition, assets=inputs.assets, xray=inputs.xray
            )
            row = persist_risk_result(session, run, result, at=NOW)
            case.service._finish_job(
                session,
                root,
                job,
                "succeeded",
                None,
                retained_bytes=len(row.canonical_result),
            )

        await case.service._execute(case.principal, case.command.account_id, operation, write=True)

    await publish()
    view = await case.service.get_run(case.principal, first.id)
    assert view.result is not None and view.result_availability == "available"
    assert view.result.observed.requested_observations > 200
    assert view.result.observed.volatility_annualized.value is not None
    assert len(view.result.historical_context.sources) <= 64
    matrix = await case.service.get_matrix(case.principal, first.id)
    assert matrix.matrix == view.result.matrix
    assert matrix.content_digest == view.result.content_digest
    assert matrix.historical_context == view.result.historical_context
    assert matrix.definition == view.result.definition
    # This proves the persisted path does not silently substitute a recalculated result.
    with patch(
        "trading212_analytics.risk.calculate_risk",
        side_effect=AssertionError("unexpected calculation"),
    ):
        assert await case.service.get_run(case.principal, first.id) == view
    with case.sessions() as session:
        job = session.get(PremiumJobModel, first.job_id)
        assert job is not None and job.state == "succeeded"
