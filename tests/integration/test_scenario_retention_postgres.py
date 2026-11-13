"""Actual scenario admission, retained calculations, worker fences and parent cleanup."""

from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from trading212_analytics.scenario import calculate_scenario
from trading212_analytics.scenario_replay import resolve_scenario_replay
from trading212_application import scenario as app
from trading212_application import scenario_jobs as jobs
from trading212_domain import historical as history
from trading212_domain.scenario_execution import ScenarioReplaySelection
from trading212_persistence.aggregation_models import AggregateOwnerErasureModel
from trading212_persistence.historical_capture import HistoricalCaptureStore
from trading212_persistence.historical_models import HistoricalInputModel
from trading212_persistence.models import BrokerConnectionModel, PrincipalModel
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRetentionModel,
    PremiumRunLicenseModel,
    PremiumRunModel,
)
from trading212_persistence.premium_retention_models import PremiumRetentionStateModel
from trading212_persistence.scenario_input_store import ScenarioInputStore
from trading212_persistence.scenario_job_store import PostgresScenarioJobStore
from trading212_persistence.scenario_models import (
    ScenarioResultModel,
    ScenarioRunModel,
    ScenarioRunPayloadModel,
)
from trading212_persistence.scenario_retention import (
    SCENARIO_PAYLOADS,
    expire_scenario_payloads,
    purge_owner_scenario_payloads,
    purge_scenario_historical_copies,
)
from trading212_persistence.source_models import (
    ProviderLicenseVersionModel,
)
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.xray_catalog_models import ConstituentSnapshotModel
from trading212_persistence.xray_retention import purge_xray_source_copies
from trading212_persistence.xray_run_models import (
    XrayInputDependencyModel,
    XrayInputSnapshotModel,
    XrayRetentionEventModel,
)
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_scenario_runs_postgres import ScenarioCase
from tests.integration.test_scenario_runs_postgres import scenario_case as scenario_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def store(case: ScenarioCase) -> PostgresScenarioJobStore:
    return PostgresScenarioJobStore(
        case.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: case.now,
        replay_resolver=resolve_scenario_replay,
    )


def message(case: ScenarioCase) -> jobs.ScenarioTaskMessage:
    return jobs.ScenarioTaskMessage(
        str(case.run.job_id),
        str(case.run.id),
        case.principal.owner_id,
        str(case.command.account_id),
        case.run.input_digest,
    )


async def published(case: ScenarioCase) -> UUID:
    worker = store(case)
    claim = await worker.claim_scenario_job(message(case), consumer_id="retention-fixture")
    assert claim is not None
    inputs = await worker.load_scenario_job_input(claim)
    result = calculate_scenario(inputs)
    assert len(result.components) > 1
    assert await worker.complete_scenario_job(claim, result)
    with case.sessions() as session:
        result_id = session.scalar(
            select(ScenarioResultModel.id).where(
                ScenarioResultModel.run_id == case.run.id,
            )
        )
        assert result_id is not None
        return result_id


def restrict(case: ScenarioCase, *, permission: str = "denied", days: int = 30) -> None:
    with case.sessions() as session, session.begin():
        license_id = session.scalar(
            select(PremiumRunLicenseModel.license_version_id)
            .where(
                PremiumRunLicenseModel.run_id == case.run.id,
            )
            .order_by(PremiumRunLicenseModel.id)
            .limit(1)
        )
        assert license_id is not None
        original = session.get_one(ProviderLicenseVersionModel, license_id)
        revision = session.scalar(
            select(func.max(ProviderLicenseVersionModel.version_number)).where(
                ProviderLicenseVersionModel.provider_id == original.provider_id,
            )
        )
        assert revision is not None
        session.add(
            ProviderLicenseVersionModel(
                id=uuid4(),
                owner_id=original.owner_id,
                provider_id=original.provider_id,
                version_number=revision + 1,
                version=f"retention-{revision + 1}",
                effective_at=case.now,
                store_permission=permission,
                display_permission="allowed",
                report_permission="allowed",
                export_permission="allowed",
                retention_days=days,
                attribution="Synthetic scenario license restriction",
                evidence_key="synthetic",
                created_at=case.now,
            )
        )


def cleanup(
    case: ScenarioCase,
    *,
    at: datetime | None = None,
    budget: SourcePurgeBudget | None = None,
    owner: UUID | None = None,
) -> bool:
    with case.sessions() as session, session.begin():
        return expire_scenario_payloads(
            session,
            at=at or case.now,
            owner=owner,
            budget=budget or SourcePurgeBudget(),
        )


def assert_empty(case: ScenarioCase, result_id: UUID | None = None) -> None:
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        marker = session.scalar(
            select(PremiumRetentionModel).where(
                PremiumRetentionModel.run_id == root.id,
            )
        )
        assert marker is not None and marker.completed_at is not None
        assert root.reserved_bytes == root.retained_bytes == 0
        assert capacity.reserved_bytes == capacity.retained_bytes == capacity.active_jobs == 0
        assert (
            session.scalar(
                select(ScenarioRunPayloadModel.id).where(
                    ScenarioRunPayloadModel.run_id == root.id,
                )
            )
            is None
        )
        license_count = session.scalar(
            select(func.count())
            .select_from(PremiumRunLicenseModel)
            .where(
                PremiumRunLicenseModel.run_id == root.id,
            )
        )
        assert license_count is not None and license_count > 0
        assert session.get(ScenarioRunModel, root.id) is not None
        if result_id is not None:
            result = session.get_one(ScenarioResultModel, result_id)
            assert result.canonical_result == b"" and result.content_digest
            for model, _ in SCENARIO_PAYLOADS:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(
                            model.result_id == result_id,
                        )
                    )
                    == 0
                )


@pytest.mark.parametrize("permission,days,later", [("denied", 30, 0), ("allowed", 1, 2)])
async def test_current_license_physically_removes_full_saved_scenario_without_decode(
    scenario_case: ScenarioCase,
    permission: str,
    days: int,
    later: int,
) -> None:
    case = scenario_case
    result_id = await published(case)
    restrict(case, permission=permission, days=days)
    case.now += timedelta(days=later)
    with patch.object(
        ScenarioInputStore, "read_retained_input", side_effect=AssertionError("decode")
    ):
        assert cleanup(case)
    assert_empty(case, result_id)
    assert cleanup(case)
    assert_empty(case, result_id)
    view = await case.service.get_run(case.principal, case.run.id, app.ScenarioComponentPageQuery())
    assert view.result is None and view.result_availability == "expired"


async def test_bounded_cleanup_resumes_and_releases_capacity_only_after_last_copy(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    result_id = await published(case)
    later = case.run.expires_at + timedelta(seconds=1)
    with case.sessions() as session:
        original = session.get_one(PremiumRunModel, case.run.id).retained_bytes
        assert original > 0
    assert not cleanup(case, at=later, budget=SourcePurgeBudget(bytes_removed=0))
    incomplete = 0
    metadata_only = False
    for _ in range(100):
        budget = SourcePurgeBudget(rows_inspected=128, rows_removed=1)
        done = cleanup(case, at=later, budget=budget)
        assert 0 <= budget.rows_inspected <= 128 and 0 <= budget.rows_removed <= 1
        if done:
            break
        incomplete += 1
        with case.sessions() as session:
            root = session.get_one(PremiumRunModel, case.run.id)
            assert root.retained_bytes == original
            payload = session.scalar(
                select(ScenarioRunPayloadModel.id).where(
                    ScenarioRunPayloadModel.run_id == root.id,
                )
            )
            if payload is None:
                # Removing the last financial copy can consume this pass's
                # allowance. Indexed parent removal and final capacity release
                # then resume separately, without retaining private input bytes.
                metadata_only = True
                state = session.get_one(PremiumRetentionStateModel, root.id)
                assert state.financial_rows == 0 and not state.closed
                assert session.get_one(ScenarioResultModel, result_id).canonical_result == b""
                for model, _ in SCENARIO_PAYLOADS:
                    assert (
                        session.scalar(
                            select(func.count())
                            .select_from(model)
                            .where(model.result_id == result_id)
                        )
                        == 0
                    )
    else:
        pytest.fail("Shared bounded scenario cleanup did not converge")
    assert incomplete > 1 and metadata_only
    assert_empty(case, result_id)


async def test_retention_fences_real_running_worker_and_preserves_foreign_owner(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    worker = store(case)
    claim = await worker.claim_scenario_job(message(case), consumer_id="retention-race")
    assert claim is not None
    result = calculate_scenario(await worker.load_scenario_job_input(claim))
    restrict(case)
    assert cleanup(case, owner=uuid4())
    with case.sessions() as session:
        assert session.get_one(PremiumJobModel, case.run.job_id).state == "running"
    assert cleanup(case)
    assert not await worker.complete_scenario_job(claim, result)
    assert not await worker.heartbeat_scenario_job(claim)
    assert await worker.claim_scenario_job(message(case), consumer_id="stale-redelivery") is None
    with case.sessions() as session:
        job = session.get_one(PremiumJobModel, case.run.job_id)
        outbox = session.scalar(
            select(PremiumOutboxModel).where(PremiumOutboxModel.job_id == job.id)
        )
        assert job.state == "expired" and job.lease_token is None and job.consumer_id is None
        assert outbox is not None and outbox.state == "dead_letter"
    assert_empty(case)


async def test_direct_xray_source_cleanup_drains_scenario_before_parent_payload(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    result_id = await published(case)
    with case.sessions() as session:
        input_id = session.get_one(ScenarioRunModel, case.run.id).xray_input_id
        source_id = session.scalar(
            select(XrayInputDependencyModel.constituent_snapshot_id)
            .where(
                XrayInputDependencyModel.input_id == input_id,
                XrayInputDependencyModel.constituent_snapshot_id.is_not(None),
            )
            .limit(1)
        )
        assert source_id is not None
        at = session.get_one(ConstituentSnapshotModel, source_id).expires_at
    for _ in range(30):
        with case.sessions() as session, session.begin():
            source = session.get_one(ConstituentSnapshotModel, source_id)
            # The ordinary upstream source lock precedes the parent/drain helper.
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"sources:{case.principal.owner_id}"},
            )
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"xray:{case.principal.owner_id}"},
            )
            if purge_xray_source_copies(session, source, at=at, budget=SourcePurgeBudget()):
                break
    else:
        pytest.fail("Direct X-ray source cleanup did not converge")
    assert_empty(case, result_id)
    with case.sessions() as session:
        assert session.get_one(XrayInputSnapshotModel, input_id).canonical_input == b""
        assert (
            session.scalar(
                select(XrayRetentionEventModel.id).where(
                    XrayRetentionEventModel.input_id == input_id,
                )
            )
            is not None
        )


async def test_exact_historical_parent_drain_preserves_unselected_scenario(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    start = case.now.date() - timedelta(days=3)
    end = case.now.date() - timedelta(days=1)
    captured = await HistoricalCaptureStore(
        case.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: case.now,
    ).capture(
        case.principal,
        str(case.command.account_id),
        request=history.HistoricalSelectionRequest(
            window=history.HistoricalWindow(
                start_date=start,
                end_date=end,
                source_cutoff_at=case.now,
                reporting_currency=case.command.reporting_currency,
                knowledge_policy=history.KnowledgePolicy.POINT_IN_TIME,
            ),
            accounting_policy=history.HistoricalAccountingPolicy(),
            source_policy=None,
            reporting_calendar_ref=None,
        ),
    )
    original = await case.service.get_version(case.principal, case.command.scenario_version_id)
    replay_version = await case.service.create_version(
        case.principal,
        app.CreateScenarioVersion(
            scenario_id=original.definition_id,
            expected_revision=1,
            content=replace(original.content, shocks=()),
            idempotency_key=str(uuid4()),
            correlation_id="retention-replay",
        ),
    )
    selected = await case.service.create_run(
        case.principal,
        replace(
            case.command,
            scenario_version_id=replay_version.id,
            idempotency_key=str(uuid4()),
            replay=ScenarioReplaySelection(
                historical_input_snapshot_id=UUID(captured.id),
                start_date=start,
                end_date=end,
                market_knowledge_cutoff_at=case.now,
                holdings_basis="current_holdings",
                knowledge_basis="point_in_time",
            ),
        ),
    )
    with case.sessions() as session, session.begin():
        assert purge_scenario_historical_copies(
            session,
            UUID(case.principal.owner_id),
            UUID(captured.id),
            at=selected.expires_at,
            budget=SourcePurgeBudget(),
        )
        assert (
            session.scalar(
                select(ScenarioRunPayloadModel.id).where(
                    ScenarioRunPayloadModel.run_id == selected.id,
                )
            )
            is None
        )
        assert (
            session.scalar(
                select(ScenarioRunPayloadModel.id).where(
                    ScenarioRunPayloadModel.run_id == case.run.id,
                )
            )
            is not None
        )
        assert session.get_one(HistoricalInputModel, UUID(captured.id)).canonical_input
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert capacity.active_jobs == 1 and capacity.reserved_bytes == 33554432


async def test_owner_erasure_clears_unexpired_queued_input_without_losing_audit(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    owner = UUID(case.principal.owner_id)
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        capacity = session.get_one(PremiumCapacityModel, owner)
        job = session.get_one(PremiumJobModel, case.run.job_id)
        state = session.get_one(PremiumRetentionStateModel, root.id)
        before = (
            root.reserved_bytes,
            root.retained_bytes,
            capacity.reserved_bytes,
            capacity.retained_bytes,
            capacity.active_jobs,
            job.state,
            state.financial_rows,
            state.closed,
        )
        assert root.expires_at > case.now and job.state == "queued"
        assert (
            session.scalar(
                select(PrincipalModel.id)
                .where(PrincipalModel.owner_id == owner, PrincipalModel.status == "active")
                .limit(1)
            )
            is not None
        )
        assert (
            session.scalar(
                select(BrokerConnectionModel.id)
                .where(
                    BrokerConnectionModel.owner_id == owner,
                    BrokerConnectionModel.status == "active",
                )
                .limit(1)
            )
            is not None
        )
    with (
        pytest.raises(IntegrityError, match="aggregate owner remains active"),
        case.sessions() as session,
        session.begin(),
    ):
        purge_owner_scenario_payloads(session, owner, at=case.now, budget=SourcePurgeBudget())
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        capacity = session.get_one(PremiumCapacityModel, owner)
        job = session.get_one(PremiumJobModel, case.run.job_id)
        state = session.get_one(PremiumRetentionStateModel, root.id)
        assert (
            root.reserved_bytes,
            root.retained_bytes,
            capacity.reserved_bytes,
            capacity.retained_bytes,
            capacity.active_jobs,
            job.state,
            state.financial_rows,
            state.closed,
        ) == before
        assert session.get(AggregateOwnerErasureModel, owner) is None
    # This is fixture lifecycle state in a disposable synthetic database, not a
    # broker operation or a public owner-erasure command.
    with case.sessions() as session, session.begin():
        session.execute(
            update(PrincipalModel).where(PrincipalModel.owner_id == owner).values(status="disabled")
        )
        session.execute(
            update(BrokerConnectionModel)
            .where(BrokerConnectionModel.owner_id == owner)
            .values(status="disabled")
        )
    with case.sessions() as session, session.begin():
        assert purge_owner_scenario_payloads(
            session,
            owner,
            at=case.now,
            budget=SourcePurgeBudget(),
        )
    assert_empty(case)
    with case.sessions() as session:
        marker = session.scalar(
            select(PremiumRetentionModel).where(
                PremiumRetentionModel.run_id == case.run.id,
            )
        )
        assert marker is not None and marker.reason == "owner_erasure"
