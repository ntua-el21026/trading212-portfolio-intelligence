"""Physical risk removal, source revocation, fencing and real populated upgrade."""

from datetime import datetime, timedelta
from inspect import unwrap
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, MetaData, func, select, text, update
from sqlalchemy.exc import IntegrityError
from trading212_analytics.risk import calculate_risk
from trading212_application import risk as app
from trading212_persistence.historical_capture import HistoricalCaptureStore
from trading212_persistence.historical_models import HistoricalDependencyModel
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRetentionModel,
    PremiumRunLicenseModel,
    PremiumRunModel,
)
from trading212_persistence.risk_models import RiskResultModel
from trading212_persistence.risk_retention import RISK_PAYLOADS, expire_risk_payloads
from trading212_persistence.source_models import (
    PriceSnapshotModel,
    ProviderLicenseVersionModel,
    SourceExpiryEventModel,
)
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_retention_service import expire_source_payloads

from tests.integration.test_historical_postgres import historical_database as _historical_database
from tests.integration.test_historical_seed import NOW
from tests.integration.test_historical_seed import seeded_history as _seeded_history
from tests.integration.test_risk_jobs_postgres import admitted, store
from tests.integration.test_risk_migration_upgrade import fingerprints
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case
from tests.integration.test_risk_source_authorization import restrict

pytestmark = pytest.mark.integration
# Each irreversible expiry/license test gets a fresh database in the same PG container.
historical_database = pytest.fixture(scope="function")(unwrap(_historical_database))
seeded_history = pytest.fixture(scope="function")(unwrap(_seeded_history))


async def published(case: RunCase) -> app.RiskRunView:
    worker = store(case)
    run, dispatch = await admitted(case, worker)
    claim = await worker.claim_risk_job(dispatch.message, consumer_id="retention-test")
    assert claim is not None
    inputs = await worker.load_risk_job_input(claim)
    result = calculate_risk(
        inputs.historical, inputs.definition, assets=inputs.assets, xray=inputs.xray
    )
    assert await worker.complete_risk_job(claim, result)
    return await case.service.get_run(case.principal, run.id)


def pass_cleanup(
    case: RunCase,
    *,
    at: datetime = NOW,
    budget: SourcePurgeBudget | None = None,
    owner: UUID | None = None,
) -> bool:
    with case.sessions() as session, session.begin():
        return expire_risk_payloads(
            session, at=at, owner=owner, budget=budget or SourcePurgeBudget()
        )


def drain_cleanup(case: RunCase, *, at: datetime = NOW) -> None:
    # The 365-day fixture now charges each row's SQL guards/counters as well as
    # the payload deletion. Each committed invocation keeps the original 4096
    # ceiling; continuation must finish instead of silently exceeding it.
    for _ in range(64):
        budget = SourcePurgeBudget()
        done = pass_cleanup(case, at=at, budget=budget)
        assert 0 <= budget.rows_inspected <= 4096
        assert 0 <= budget.rows_removed <= 4096
        if done:
            return
    pytest.fail("Default-budget risk cleanup did not converge")


def assert_empty(case: RunCase, run: app.RiskRunView) -> None:
    with case.sessions() as session:
        result = session.scalar(select(RiskResultModel).where(RiskResultModel.run_id == run.id))
        assert result is not None and result.canonical_result == b""
        for model, _ in RISK_PAYLOADS:
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.result_id == result.id)
                )
                == 0
            )
        marker = session.scalar(
            select(PremiumRetentionModel).where(PremiumRetentionModel.run_id == run.id)
        )
        assert marker is not None and marker.completed_at is not None
        root = session.get_one(PremiumRunModel, run.id)
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert root.reserved_bytes == root.retained_bytes == 0
        assert capacity.active_jobs == capacity.reserved_bytes == capacity.retained_bytes == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(PremiumRunLicenseModel)
                .where(PremiumRunLicenseModel.run_id == run.id)
            )
            or 0
        ) > 0


@pytest.mark.parametrize("restriction,days,later", [("denied", 30, 0), ("allowed", 1, 2)])
async def test_current_license_cleanup_without_decode(
    run_case: RunCase, restriction: str, days: int, later: int
) -> None:
    case = run_case
    run = await published(case)
    restrict(case, store=restriction, days=days)
    with patch.object(
        HistoricalCaptureStore, "_capture_view", side_effect=AssertionError("private decode")
    ) as decode:
        drain_cleanup(case, at=NOW + timedelta(days=later))
        decode.assert_not_called()
    assert_empty(case, run)
    page = await case.service.list_runs(
        case.principal, case.command.account_id, app.RiskPageQuery()
    )
    assert page.items[0].result is None and page.items[0].result_availability == "expired"
    with pytest.raises(app.RiskServiceError) as failure:
        await case.service.get_run(case.principal, run.id)
    assert failure.value.code is app.RiskErrorCode.RUN_EXPIRED
    drain_cleanup(case, at=NOW + timedelta(days=later))
    assert_empty(case, run)


async def test_budgeted_resume_canonical_last_and_capacity_retained(run_case: RunCase) -> None:
    case = run_case
    run = await published(case)
    later = NOW + timedelta(days=31)
    with case.sessions() as session:
        original_bytes = session.get_one(PremiumRunModel, run.id).retained_bytes
    zero = SourcePurgeBudget(bytes_removed=0)
    assert not pass_cleanup(case, at=later, budget=zero)
    with case.sessions() as session:
        assert session.get_one(PremiumRunModel, run.id).retained_bytes == original_bytes
        row = session.scalar(select(RiskResultModel).where(RiskResultModel.run_id == run.id))
        assert row is not None and row.canonical_result
    incomplete = 0
    for _ in range(512):
        budget = SourcePurgeBudget(rows_inspected=96, rows_removed=32)
        done = pass_cleanup(case, at=later, budget=budget)
        assert 0 <= budget.rows_inspected <= 96 and 0 <= budget.rows_removed <= 32
        if done:
            break
        incomplete += 1
        with case.sessions() as session:
            root = session.get_one(PremiumRunModel, run.id)
            marker = session.scalar(
                select(PremiumRetentionModel).where(PremiumRetentionModel.run_id == run.id)
            )
            assert (
                root.retained_bytes == original_bytes
                and marker is not None
                and marker.completed_at is None
            )
    else:
        pytest.fail("Bounded risk retention did not converge")
    assert incomplete > 1
    assert_empty(case, run)


async def test_retention_fences_running_worker_and_foreign_owner_is_untouched(
    run_case: RunCase,
) -> None:
    case = run_case
    worker = store(case)
    run, dispatch = await admitted(case, worker)
    claim = await worker.claim_risk_job(dispatch.message, consumer_id="retention-fence")
    assert claim is not None
    inputs = await worker.load_risk_job_input(claim)
    result = calculate_risk(inputs.historical, inputs.definition, assets=inputs.assets)
    restrict(case, store="denied", days=30)
    assert pass_cleanup(case, owner=uuid4())
    with case.sessions() as session:
        assert session.get_one(PremiumJobModel, run.job_id).state == "running"
    assert pass_cleanup(case)
    assert not await worker.complete_risk_job(claim, result)
    assert not await worker.heartbeat_risk_job(claim)
    assert not await worker.acknowledge_risk_dispatch(dispatch)
    with case.sessions() as session:
        job = session.get_one(PremiumJobModel, run.job_id)
        assert job.state == "expired" and job.lease_token is None
        outbox = session.scalar(
            select(PremiumOutboxModel).where(PremiumOutboxModel.job_id == run.job_id)
        )
        assert outbox is not None and outbox.state == "dead_letter" and outbox.claim_token is None
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert capacity.active_jobs == capacity.reserved_bytes == capacity.retained_bytes == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(RiskResultModel)
                .where(RiskResultModel.run_id == run.id)
            )
            == 0
        )


async def test_future_license_and_busy_owner_do_not_authorize_cleanup(run_case: RunCase) -> None:
    case = run_case
    run = await published(case)
    with case.sessions() as session, session.begin():
        lineage = session.scalar(
            select(PremiumRunLicenseModel).where(PremiumRunLicenseModel.run_id == run.id)
        )
        assert lineage is not None
        old = session.get_one(ProviderLicenseVersionModel, lineage.license_version_id)
        version = session.scalar(
            select(func.max(ProviderLicenseVersionModel.version_number)).where(
                ProviderLicenseVersionModel.provider_id == old.provider_id
            )
        )
        assert version is not None
        session.add(
            ProviderLicenseVersionModel(
                id=uuid4(),
                owner_id=old.owner_id,
                provider_id=old.provider_id,
                version_number=version + 1,
                version="future-risk-restriction",
                effective_at=NOW + timedelta(days=1),
                store_permission="denied",
                display_permission="denied",
                report_permission="denied",
                export_permission="denied",
                retention_days=1,
                attribution="Synthetic future policy",
                evidence_key="synthetic-future-license",
                created_at=NOW,
            )
        )
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                update(PremiumRunLicenseModel)
                .where(PremiumRunLicenseModel.id == lineage.id)
                .values(created_at=NOW + timedelta(seconds=1))
            )
    assert pass_cleanup(case)
    assert (await case.service.get_run(case.principal, run.id)).result is not None
    with case.sessions() as busy, busy.begin():
        busy.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"sources:{case.principal.owner_id}"},
        )
        assert not pass_cleanup(case, at=NOW + timedelta(days=2))
    drain_cleanup(case, at=NOW + timedelta(days=2))
    assert_empty(case, run)


async def test_source_cleanup_stays_pending_until_risk_payloads_are_gone(run_case: RunCase) -> None:
    case = run_case
    run = await published(case)
    with case.sessions() as session:
        expiry = session.scalar(
            select(PriceSnapshotModel.expires_at)
            .join(
                HistoricalDependencyModel,
                HistoricalDependencyModel.price_snapshot_id == PriceSnapshotModel.id,
            )
            .where(HistoricalDependencyModel.input_id == case.command.historical_input_snapshot_id)
            .order_by(PriceSnapshotModel.expires_at)
            .limit(1)
        )
        assert expiry is not None
    later = expiry + timedelta(seconds=1)
    with case.sessions() as session, session.begin():
        before = session.scalar(select(func.count()).select_from(SourceExpiryEventModel))
        budget = SourcePurgeBudget(rows_removed=0)
        assert expire_source_payloads(session, at=later, limit=100, budget=budget) == 0
        assert session.scalar(select(func.count()).select_from(SourceExpiryEventModel)) == before
        marker = session.scalar(
            select(PremiumRetentionModel).where(PremiumRetentionModel.run_id == run.id)
        )
        assert marker is not None and marker.completed_at is None
    drain_cleanup(case, at=later)
    assert_empty(case, run)


async def test_populated_0017_upgrade_backfills_lineage_without_financial_change(
    run_case: RunCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = run_case
    run = await published(case)
    with case.sessions() as session:
        expected = set(
            session.scalars(
                select(PremiumRunLicenseModel.license_version_id).where(
                    PremiumRunLicenseModel.run_id == run.id
                )
            )
        )
        engine = session.get_bind()
    assert isinstance(engine, Engine) and expected
    url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "20260914_0017")
    metadata = MetaData()
    metadata.reflect(bind=engine)
    before = fingerprints(engine, metadata)
    assert len(before) == 229
    command.upgrade(config, "head")
    command.check(config)
    assert fingerprints(engine, metadata) == before
    with case.sessions() as session:
        actual = set(
            session.scalars(
                select(PremiumRunLicenseModel.license_version_id).where(
                    PremiumRunLicenseModel.run_id == run.id
                )
            )
        )
    assert actual == expected
    after = await case.service.get_run(case.principal, run.id)
    assert after.result == run.result
