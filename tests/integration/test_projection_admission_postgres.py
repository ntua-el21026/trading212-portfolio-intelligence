"""Real admission rejection preserves commands, financial copies and owner capacity."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, func, select, text
from trading212_analytics.projection import calculate_projection_chunk
from trading212_application import projection as app
from trading212_application import projection_jobs as jobs
from trading212_application.projection_capture import ProjectionDatedSchedule
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
)
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.premium_models import (
    PremiumAuditModel,
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from trading212_persistence.projection_models import (
    ProjectionCalendarBoundaryModel,
    ProjectionChunkModel,
    ProjectionInputModel,
    ProjectionPathModel,
    ProjectionPointAssetModel,
    ProjectionPointModel,
    ProjectionResultModel,
    ProjectionRunAllocationModel,
    ProjectionRunModel,
)
from trading212_persistence.report_models import ApplicationCommandIdentityModel

from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.test_projection_jobs_postgres import admitted, cancel, store
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration

RESERVATION = 33_554_432
OWNER_LIMIT = 268_435_456
RETAINED_BOUNDARY = 234_881_024
TARGET_RUN_BYTES = 24 * 1024 * 1024
MAX_SEED_RUNS = 10
MAX_CHUNKS_PER_RUN = 16


def _database_clock(case: ProjectionJobCase) -> None:
    """Use the real database clock without extending any lease or attempt budget."""
    with case.sessions() as session:
        at = session.scalar(select(func.clock_timestamp()))
    assert isinstance(at, datetime)
    case.now = max(case.now, at)


def _snapshot(case: ProjectionJobCase) -> dict[str, object]:
    owner = UUID(case.principal.owner_id)
    state: dict[str, object] = {}
    with case.sessions() as session:
        for model in (
            ApplicationCommandIdentityModel,
            PremiumAuditModel,
            PremiumRunModel,
            PremiumJobModel,
            PremiumOutboxModel,
            PremiumCapacityModel,
            ProjectionRunModel,
            ProjectionInputModel,
        ):
            table = cast(Table, model.__table__)
            state[model.__tablename__] = tuple(
                tuple(row)
                for row in session.execute(
                    select(*table.columns)
                    .where(model.owner_id == owner)
                    .order_by(*table.primary_key.columns)
                )
            )
        # Count the potentially large checkpoint families without reading their
        # financial bytes into the snapshot. Inputs above are complete and bounded.
        for checkpoint_model in (
            ProjectionRunAllocationModel,
            ProjectionCalendarBoundaryModel,
            ProjectionChunkModel,
            ProjectionPathModel,
            ProjectionPointModel,
            ProjectionPointAssetModel,
            ProjectionResultModel,
        ):
            state[checkpoint_model.__tablename__] = session.scalar(
                select(func.count())
                .select_from(checkpoint_model)
                .where(checkpoint_model.owner_id == owner)
            )
    return state


def _stored_bytes(case: ProjectionJobCase, run_id: UUID) -> int:
    with case.sessions() as session:
        size = session.scalar(
            select(ProjectionRunModel.stored_bytes).where(ProjectionRunModel.id == run_id)
        )
    assert isinstance(size, int) and 0 < size <= RESERVATION
    return size


def _fixture_copy_bytes(case: ProjectionJobCase, run_id: UUID) -> int:
    """Measure this fixture's copied bytes/rows without the production aggregate.

    This is the logical retained-copy charge, not compressed on-disk relation
    size. BYTEA octet lengths count full original canonical bytes; scalar-row
    sizes independently include the actual normalized PostgreSQL values.
    """
    with case.sessions() as session:
        # The fixture has no calibration, schedule entries or published result.
        # Assert that closed scope before summing its seven actual participants.
        extra = session.scalar(
            text(
                """
                SELECT count(*) FROM (
                  SELECT run_id FROM projection_run_pauses WHERE run_id=:run
                  UNION ALL SELECT run_id FROM projection_run_schedule_entries WHERE run_id=:run
                  UNION ALL SELECT run_id FROM projection_run_sources WHERE run_id=:run
                  UNION ALL SELECT run_id FROM projection_source_proofs WHERE run_id=:run
                  UNION ALL SELECT run_id FROM projection_source_licenses WHERE run_id=:run
                  UNION ALL SELECT run_id FROM projection_retained_source_memberships
                    WHERE run_id=:run
                  UNION ALL SELECT run_id FROM projection_results WHERE run_id=:run
                ) extra
                """
            ),
            {"run": run_id},
        )
        assert extra == 0
        measured = session.scalar(
            text(
                """
                SELECT coalesce(sum(bytes),0)::bigint FROM (
                  SELECT pg_column_size(ROW(
                    t.run_id,t.initial_value,t.base_monthly,t.annual_growth,
                    t.contribution_delta,t.annual_mean_log_delta,t.pause_count,t.entry_count,
                    t.capture_bytes,t.input_bytes,t.id,t.owner_id,t.account_id,t.created_at
                  ))::bigint + octet_length(t.canonical_capture)
                    + octet_length(t.canonical_input) AS bytes
                    FROM projection_inputs t WHERE t.run_id=:run
                  UNION ALL SELECT pg_column_size(t)::bigint
                    FROM projection_run_allocations t WHERE t.run_id=:run
                  UNION ALL SELECT pg_column_size(t)::bigint
                    FROM projection_calendar_boundaries t WHERE t.run_id=:run
                  UNION ALL SELECT pg_column_size(ROW(
                    t.run_id,t.job_id,t.lease_token,t.consumer_attempt,t.variant,t.first_path,
                    t.path_count,t.input_digest,t.content_digest,t.byte_length,t.sealed,
                    t.id,t.owner_id,t.account_id,t.created_at
                  ))::bigint + octet_length(t.canonical_chunk)
                    FROM projection_chunks t WHERE t.run_id=:run
                  UNION ALL SELECT pg_column_size(t)::bigint
                    FROM projection_paths t WHERE t.run_id=:run
                  UNION ALL SELECT pg_column_size(t)::bigint
                    FROM projection_points t WHERE t.run_id=:run
                  UNION ALL SELECT pg_column_size(t)::bigint
                    FROM projection_point_assets t WHERE t.run_id=:run
                ) copies
                """
            ),
            {"run": run_id},
        )
    assert isinstance(measured, int) and 0 < measured <= RESERVATION
    return measured


def _assert_terminal_physical_charge(case: ProjectionJobCase, run_id: UUID) -> int:
    measured_size = _fixture_copy_bytes(case, run_id)
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, run_id)
        run = session.get_one(ProjectionRunModel, run_id)
        job = session.scalar(select(PremiumJobModel).where(PremiumJobModel.run_id == run_id))
        accounted_size = session.scalar(select(func.projection_storage_bytes(run_id)))
        assert job is not None and job.state in ("cancelled", "failed")
        assert root.reserved_bytes == 0
        assert root.retained_bytes == run.stored_bytes == accounted_size == measured_size
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProjectionResultModel)
                .where(ProjectionResultModel.run_id == run_id)
            )
            == 0
        )
        return measured_size


def _assert_owner_charge(case: ProjectionJobCase) -> int:
    with case.sessions() as session:
        owner = UUID(case.principal.owner_id)
        capacity = session.get_one(PremiumCapacityModel, owner)
        roots = tuple(
            session.execute(
                select(PremiumRunModel.retained_bytes, PremiumRunModel.reserved_bytes).where(
                    PremiumRunModel.owner_id == owner
                )
            )
        )
        assert capacity.active_jobs == capacity.reserved_bytes == 0
        assert all(reserved == 0 for _, reserved in roots)
        assert capacity.retained_bytes == sum(retained for retained, _ in roots)
        assert 0 < capacity.retained_bytes <= OWNER_LIMIT
        return capacity.retained_bytes


async def test_active_quota_rejection_preserves_all_persistent_admission_state(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    await case.service.create_run(
        case.principal, replace(case.command, idempotency_key=uuid4().hex)
    )
    before = _snapshot(case)
    rejected_key = uuid4().hex
    with pytest.raises(app.ProjectionServiceError) as rejected:
        await case.service.create_run(
            case.principal, replace(case.command, idempotency_key=rejected_key)
        )
    assert rejected.value.code is app.ProjectionErrorCode.RATE_LIMITED
    assert _snapshot(case) == before
    with case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ApplicationCommandIdentityModel)
                .where(ApplicationCommandIdentityModel.idempotency_key == rejected_key)
            )
            == 0
        )


async def test_physical_retained_copies_cross_reservation_boundary_without_rejected_inserts(
    projection_job_case: ProjectionJobCase,
) -> None:
    """Real copied bytes cross 224 MiB; the next 32 MiB cannot exceed 256 MiB.

    Exact equality/+1 arithmetic has independent unit vectors. This integration
    fixture deliberately keeps genuine failed checkpoints rather than padding
    private documents or fabricating counters to land on one byte exactly.
    """
    case = projection_job_case
    _database_clock(case)
    initial_id = case.run.id
    await cancel(case, initial_id)
    _assert_terminal_physical_charge(case, initial_id)
    currency = CurrencyCode("EUR")
    key = "synthetic-cash-" + "x" * 105
    assumptions = ProjectionAssumptions(
        assets=(
            ProjectionAsset(
                key=key,
                annual_mean_log_return=Decimal(0),
                annual_volatility=Decimal(0),
                weight=Decimal(1),
            ),
        ),
        correlation=((Decimal(1),),),
        reporting_currency=currency,
    )
    definition = await case.service.create_assumption_set(
        case.principal,
        app.CreateAssumptionSet(
            account_id=case.command.selection.account_id,
            metadata=ProjectionVersionMetadata(name="Synthetic retained-capacity reference"),
            content=assumptions,
            idempotency_key=uuid4().hex,
            correlation_id="projection-capacity-reference",
        ),
    )
    selection = replace(
        case.command.selection,
        assumption_version_id=definition.current_version_id,
        initial=replace(case.command.selection.initial, modeled_value=Money(Decimal(0), currency)),
        schedule=ProjectionDatedSchedule(base_monthly=Money(Decimal(0), currency)),
        allocation=(ProjectionAllocation(key=key, weight=Decimal(1)),),
        months=120,
        paths=4096,
        retained_months=tuple(range(121)),
    )
    seeded: list[UUID] = []
    total = _assert_owner_charge(case)
    for ordinal in range(MAX_SEED_RUNS):
        if total > RETAINED_BOUNDARY:
            break
        assert total + RESERVATION <= OWNER_LIMIT
        _database_clock(case)
        command = replace(
            case.command,
            selection=replace(selection, seed=ordinal),
            idempotency_key=uuid4().hex,
        )
        case.run = await case.service.create_run(case.principal, command)
        worker = store(case)
        dispatch = await admitted(case, worker)
        assert await worker.acknowledge_projection_dispatch(dispatch)
        claim = await worker.claim_projection_job(dispatch.message, consumer_id="capacity-fixture")
        assert claim is not None
        captured = await worker.load_projection_job_input(claim)
        assert captured.inputs.work_units == 491_520
        for chunk_index in range(MAX_CHUNKS_PER_RUN):
            before_chunk = _stored_bytes(case, case.run.id)
            if before_chunk >= TARGET_RUN_BYTES:
                break
            _database_clock(case)
            assert await worker.heartbeat_projection_job(claim)
            chunk = calculate_projection_chunk(captured.inputs, chunk_index * 32, 32)
            assert await worker.save_projection_job_chunk(claim, chunk)
            after_chunk = _stored_bytes(case, case.run.id)
            # All canonical zero-value points/asset rows are real. This bound
            # ensures the final chunk cannot exceed the unchanged 32 MiB cap.
            assert 0 < after_chunk - before_chunk <= 8 * 1024 * 1024
        assert TARGET_RUN_BYTES <= _stored_bytes(case, case.run.id) <= RESERVATION
        _database_clock(case)
        assert await worker.heartbeat_projection_job(claim)
        assert await worker.fail_projection_job(
            claim, failure_code=jobs.ProjectionJobFailureCode.CALCULATION_FAILED, retryable=False
        )
        seeded.append(case.run.id)
        _assert_terminal_physical_charge(case, case.run.id)
        total = _assert_owner_charge(case)
    assert 1 <= len(seeded) <= MAX_SEED_RUNS
    assert RETAINED_BOUNDARY < total <= OWNER_LIMIT
    assert total + RESERVATION > OWNER_LIMIT
    before = _snapshot(case)
    rejected_key = uuid4().hex
    with pytest.raises(app.ProjectionServiceError) as rejected:
        await case.service.create_run(
            case.principal,
            replace(case.command, selection=selection, idempotency_key=rejected_key),
        )
    assert rejected.value.code is app.ProjectionErrorCode.RATE_LIMITED
    assert _snapshot(case) == before
    assert _assert_owner_charge(case) == total
    for run_id in (initial_id, *seeded):
        _assert_terminal_physical_charge(case, run_id)
    with case.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ApplicationCommandIdentityModel)
                .where(ApplicationCommandIdentityModel.idempotency_key == rejected_key)
            )
            == 0
        )
