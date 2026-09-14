"""Current copy rights and tightened retention deny risk decode before any licensed value."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_analytics.risk_history import validate_risk_capacity
from trading212_application import risk as app
from trading212_application import risk_jobs as jobs
from trading212_persistence.historical_capture import HistoricalCaptureStore
from trading212_persistence.historical_models import HistoricalDependencyModel
from trading212_persistence.risk_job_store import PostgresRiskJobStore
from trading212_persistence.risk_service import PostgresRiskService
from trading212_persistence.source_models import ProviderLicenseVersionModel
from trading212_worker.historical_seed import CURSOR_KEY

from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import NOW
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case

pytestmark = pytest.mark.integration


def restrict(case: RunCase, *, store: str, days: int) -> None:
    with case.sessions() as session, session.begin():
        license_id = session.scalar(
            select(HistoricalDependencyModel.license_version_id)
            .where(
                HistoricalDependencyModel.input_id == case.command.historical_input_snapshot_id,
                HistoricalDependencyModel.owner_id == UUID(case.principal.owner_id),
                HistoricalDependencyModel.license_version_id.is_not(None),
            )
            .limit(1)
        )
        assert license_id is not None
        original = session.get(ProviderLicenseVersionModel, license_id)
        assert original is not None
        version = (
            session.scalar(
                select(func.max(ProviderLicenseVersionModel.version_number)).where(
                    ProviderLicenseVersionModel.provider_id == original.provider_id
                )
            )
            or 0
        )
        session.add(
            ProviderLicenseVersionModel(
                id=uuid4(),
                owner_id=original.owner_id,
                provider_id=original.provider_id,
                version_number=version + 1,
                version=f"risk-restriction-{version + 1}",
                effective_at=NOW,
                store_permission=store,
                display_permission="allowed",
                report_permission="allowed",
                export_permission="allowed",
                retention_days=days,
                attribution="Synthetic license restriction",
                evidence_key="synthetic-risk-license-test",
                created_at=NOW,
            )
        )


async def test_tightened_retention_and_store_revocation_precede_risk_decode(
    run_case: RunCase,
) -> None:
    case = run_case
    run = await case.service.create_run(case.principal, case.command)
    worker = PostgresRiskJobStore(
        case.sessions,
        cursor_signing_key=CURSOR_KEY,
        preflight=validate_risk_capacity,
        clock=lambda: NOW,
    )
    message = jobs.RiskTaskMessage(
        str(run.job_id),
        str(run.id),
        case.principal.owner_id,
        str(case.command.account_id),
        run.input_digest,
    )
    claim = await worker.claim_risk_job(message, consumer_id="source-rights-test")
    assert claim is not None
    restrict(case, store="allowed", days=1)
    later = NOW + timedelta(days=2)
    service = PostgresRiskService(
        case.sessions,
        cursor_signing_key=CURSOR_KEY,
        preflight=validate_risk_capacity,
        clock=lambda: later,
    )
    renewed = replace(case.principal, authenticated_at=later, expires_at=later + timedelta(hours=1))
    with patch.object(
        HistoricalCaptureStore, "_capture_view", side_effect=AssertionError("private decode")
    ) as decode:
        with pytest.raises(app.RiskServiceError) as failure:
            await service.get_run(renewed, run.id)
        assert failure.value.code is app.RiskErrorCode.RUN_EXPIRED
        decode.assert_not_called()
    restrict(case, store="denied", days=1)
    with patch.object(
        HistoricalCaptureStore, "_capture_view", side_effect=AssertionError("private decode")
    ) as decode:
        operations: tuple[Callable[[], Awaitable[app.RiskRunView]], ...] = (
            lambda: case.service.get_run(case.principal, run.id),
            lambda: case.service.create_run(case.principal, case.command),
        )
        for operation in operations:
            with pytest.raises(app.RiskServiceError) as failure:
                await operation()
            assert failure.value.code is app.RiskErrorCode.SOURCE_UNAVAILABLE
        with pytest.raises(jobs.RiskJobInputError) as denied:
            await worker.load_risk_job_input(claim)
        assert denied.value.code is jobs.RiskJobFailureCode.SOURCE_RESTRICTED
        decode.assert_not_called()
    assert await worker.fail_risk_job(
        claim, failure_code=jobs.RiskJobFailureCode.SOURCE_RESTRICTED, retryable=False
    )
