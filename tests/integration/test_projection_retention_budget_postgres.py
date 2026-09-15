"""Real publication counters, bounded cleanup and owned continuation persistence."""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from trading212_analytics.projection import calculate_projection, calculate_projection_chunk
from trading212_persistence import projection_retention as retention
from trading212_persistence.premium_models import PremiumRunModel
from trading212_persistence.projection_models import ProjectionResultModel, ProjectionRunModel
from trading212_persistence.projection_retention_models import (
    ProjectionRetentionEpochModel,
    ProjectionRetentionFrontierModel,
    ProjectionRetentionScanModel,
)
from trading212_persistence.projection_retention_scan import scan_projection_sources
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.test_projection_jobs_postgres import admitted, store
from tests.integration.test_projection_retention_postgres import drain, empty
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def assert_counter(case: ProjectionJobCase, *, empty_payload: bool = False) -> int:
    with case.sessions() as session:
        row = session.get_one(ProjectionRunModel, case.run.id)
        aggregate = session.scalar(select(func.projection_storage_bytes(case.run.id)))
        assert row.stored_bytes == aggregate
        assert (row.payload_rows == 0) is empty_payload
        assert (row.stored_bytes == 0) is empty_payload
        return row.stored_bytes


async def test_trigger_counter_matches_independent_aggregate_at_each_publication_and_purge_phase(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    capture_bytes = assert_counter(case)
    worker = store(case)
    dispatch = await admitted(case, worker)
    claim = await worker.claim_projection_job(dispatch.message, consumer_id="counter-proof")
    assert claim is not None
    captured = await worker.load_projection_job_input(claim)
    chunk = calculate_projection_chunk(captured.inputs, 0, captured.inputs.paths)
    assert await worker.save_projection_job_chunk(claim, chunk)
    chunk_bytes = assert_counter(case)
    assert chunk_bytes > capture_bytes
    assert await worker.complete_projection_job(claim, calculate_projection(captured.inputs))
    result_bytes = assert_counter(case)
    assert result_bytes > chunk_bytes
    with (
        pytest.raises(IntegrityError, match="immutable"),
        case.sessions() as session,
        session.begin(),
    ):
        session.execute(
            update(ProjectionRunModel)
            .where(ProjectionRunModel.id == case.run.id)
            .values(stored_bytes=1)
        )
    assert assert_counter(case) == result_bytes
    with case.sessions() as session:
        case.now = session.get_one(PremiumRunModel, case.run.id).expires_at + timedelta(seconds=1)
    statements: list[str] = []

    def observe(*args: object) -> None:
        assert isinstance(args[2], str)
        statements.append(args[2])

    event.listen(case.engine, "before_cursor_execute", observe)
    try:
        assert not drain(case, budget=SourcePurgeBudget(rows_inspected=512, rows_removed=6))
    finally:
        event.remove(case.engine, "before_cursor_execute", observe)
    assert 0 < assert_counter(case) < result_bytes
    assert all("projection_storage_bytes(" not in statement for statement in statements)
    assert all(
        "projection_original_sources_restricted(" not in statement for statement in statements
    )
    assert all("projection_references_source(" not in statement for statement in statements)
    for _ in range(10):
        if drain(case):
            break
        assert_counter(case)
    else:
        pytest.fail("bounded physical cleanup failed to resume")
    assert_counter(case, empty_payload=True)
    empty(case)
    with case.sessions() as session:
        result = session.scalar(
            select(ProjectionResultModel).where(ProjectionResultModel.run_id == case.run.id)
        )
        assert result is not None and result.canonical_result == b""


async def test_owned_maintenance_cache_is_not_financial_and_is_deleted_after_erasure(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    with case.sessions() as session, session.begin():
        root = session.get_one(PremiumRunModel, case.run.id)
        assert retention._lock_owner(session, root.owner_id)
        assert (
            scan_projection_sources(
                session, root, at=case.now, budget=SourcePurgeBudget(rows_inspected=2)
            )
            == "pending"
        )
        assert (
            session.scalar(
                select(ProjectionRetentionScanModel.id).where(
                    ProjectionRetentionScanModel.run_id == root.id
                )
            )
            is None
        )
        assert (
            scan_projection_sources(
                session, root, at=case.now, budget=SourcePurgeBudget(rows_inspected=48)
            )
            == "clean"
        )
        scan = session.scalar(
            select(ProjectionRetentionScanModel).where(
                ProjectionRetentionScanModel.run_id == root.id
            )
        )
        assert scan is not None and scan.source_count == 0 and scan.phase == "clean"
        assert scan.owner_id == root.owner_id and scan.account_id == root.account_id
        budget = SourcePurgeBudget(rows_inspected=6)
        assert scan_projection_sources(session, root, at=case.now, budget=budget) == "clean"
        assert budget.rows_inspected == 4  # only the epoch and the small saved header
        # An explicit owner clear uses the same job/capacity fence and removes
        # scanner/frontier metadata only after every financial participant is gone.
        assert retention.purge_owner_projection_payloads(
            session, UUID(case.principal.owner_id), at=case.now, budget=SourcePurgeBudget()
        )
    with case.sessions() as session:
        assert (
            session.scalar(
                select(ProjectionRetentionScanModel.id).where(
                    ProjectionRetentionScanModel.run_id == case.run.id
                )
            )
            is None
        )
        assert (
            session.scalar(
                select(ProjectionRetentionFrontierModel.id).where(
                    ProjectionRetentionFrontierModel.owner_id == UUID(case.principal.owner_id)
                )
            )
            is None
        )
    assert_counter(case, empty_payload=True)


async def test_policy_epoch_is_trigger_owned_and_cannot_be_forged_by_direct_dml(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    with (
        pytest.raises(IntegrityError, match="trigger-owned"),
        case.sessions() as session,
        session.begin(),
    ):
        session.add(
            ProjectionRetentionEpochModel(owner_id=UUID(case.principal.owner_id), epoch=999999)
        )
        session.flush()


async def test_root_keyset_plan_has_an_index_for_the_complete_owned_predicate(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    with case.sessions() as session, session.begin():
        session.execute(text("SET LOCAL enable_seqscan=off"))
        plan = session.scalar(
            text(
                "EXPLAIN (FORMAT JSON, COSTS OFF) SELECT id,owner_id FROM premium_runs "
                "WHERE owner_id=:owner AND kind='projection' AND id>:after ORDER BY id LIMIT 1"
            ),
            {"owner": UUID(case.principal.owner_id), "after": UUID(int=0)},
        )
        assert isinstance(plan, list) and len(plan) == 1
        node = plan[0]["Plan"]
        assert node["Node Type"] == "Limit"
        indexed = node["Plans"][0]
        assert indexed["Node Type"] in ("Index Scan", "Index Only Scan")
        assert indexed["Index Name"] == "ix_projection_retention_owner_cursor"
        assert "Filter" not in indexed and "Sort Key" not in indexed
        assert all(name in indexed["Index Cond"] for name in ("owner_id", "kind", "id"))
