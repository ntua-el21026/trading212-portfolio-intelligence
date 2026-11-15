"""Dense real checkpoint publication must preserve the unchanged heartbeat fence."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from trading212_application.projection_capture import ProjectionDatedSchedule
from trading212_domain.projection import ProjectionAllocation
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.premium_models import PremiumJobModel
from trading212_persistence.projection_models import (
    ProjectionChunkModel,
    ProjectionPathModel,
    ProjectionPointAssetModel,
    ProjectionPointModel,
)
from trading212_worker.projection_tasks import ProjectionExecutionState, execute_projection_message

from tests.integration.phase3_operational_fixture import evidence
from tests.integration.projection_heartbeat_diagnostics import (
    ObservedProjectionStore,
    ProjectionTrace,
    observe_waits,
)
from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.projection_report_runtime import saved_projection
from tests.integration.test_projection_jobs_postgres import admitted, charged
from tests.integration.test_research_report_actual_size_boundary_postgres import _definition
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


async def test_dense_checkpoint_publication_does_not_cancel_valid_heartbeat(
    projection_job_case: ProjectionJobCase,
) -> None:
    """Use the exact original 42 x 112 x 10 x 120 geometry and production budgets."""
    case, started = projection_job_case, perf_counter()
    trace = ProjectionTrace()
    stopped = asyncio.Event()
    outcome: ProjectionExecutionState | None = None
    job_metadata: dict[str, object] = {}
    publication: dict[str, int] = {}
    failure: str | None = None
    sampler: asyncio.Task[None] | None = None
    try:
        definition = await _definition(case)
        case.now = datetime.now(UTC)
        original = case.command.selection
        currency = CurrencyCode("EUR")
        command = replace(
            case.command,
            selection=replace(
                original,
                assumption_version_id=definition,
                initial=replace(original.initial, modeled_value=Money(Decimal("100"), currency)),
                allocation=tuple(
                    ProjectionAllocation(key=f"document-asset-{index:02d}", weight=Decimal("0.1"))
                    for index in range(10)
                ),
                schedule=ProjectionDatedSchedule(base_monthly=Money(Decimal(0), currency)),
                months=120,
                paths=42,
                retained_months=(*range(111), 120),
            ),
            idempotency_key=str(uuid4()),
            correlation_id="dense-projection-heartbeat-regression",
        )
        queued = await case.service.create_run(case.principal, command)
        actual = replace(case, command=command, run=queued)
        worker = ObservedProjectionStore(actual, trace)
        dispatch = await admitted(actual, worker)
        assert await worker.acknowledge_projection_dispatch(dispatch)
        sampler = asyncio.create_task(observe_waits(actual, trace, stopped))
        try:
            outcome = await execute_projection_message(
                worker, dispatch.message, consumer_id="dense-projection-heartbeat"
            )
        finally:
            stopped.set()
            await sampler
            with actual.sessions() as session:
                job = session.execute(
                    select(
                        PremiumJobModel.state,
                        PremiumJobModel.failure_code,
                        PremiumJobModel.consumer_attempts,
                        PremiumJobModel.heartbeat_at,
                        PremiumJobModel.lease_expires_at,
                        PremiumJobModel.deadline_at,
                    ).where(PremiumJobModel.id == actual.run.job_id)
                ).one()
            job_metadata = {
                "state": job[0],
                "failure_code": job[1],
                "consumer_attempts": job[2],
                "heartbeat_at": None if job[3] is None else job[3].isoformat(),
                "lease_expires_at": None if job[4] is None else job[4].isoformat(),
                "deadline_at": None if job[5] is None else job[5].isoformat(),
            }
        assert outcome is ProjectionExecutionState.SUCCEEDED
        saved = saved_projection(actual)
        publication["retained_storage_bytes"] = charged(actual)
        with actual.sessions() as session:
            for name, model, expected in (
                ("chunks", ProjectionChunkModel, 42),
                ("paths", ProjectionPathModel, 42),
                ("points", ProjectionPointModel, 42 * 112),
                ("asset_rows", ProjectionPointAssetModel, 42 * 112 * 10),
            ):
                count = session.scalar(
                    select(func.count()).select_from(model).where(model.run_id == actual.run.id)
                )
                assert count == expected
                publication[name] = expected
        assert len(saved.value.variants) == 1
        assert len(saved.value.variants[0].paths) == 42
        for path in saved.value.variants[0].paths:
            assert len(path.points) == 112
            for point in path.points:
                assert point.nominal == point.real == Decimal("100")
                assert len(point.assets) == 10
                assert all(asset.value == Decimal("10") for asset in point.assets)
    except Exception as error:
        failure = type(error).__name__
        raise
    finally:
        stopped.set()
        if sampler is not None and not sampler.done():
            await sampler
        evidence(
            "projection-dense-heartbeat-diagnosis",
            {
                "geometry": {"paths": 42, "instants": 112, "assets": 10, "months": 120},
                "work_units": 50_400,
                "elapsed_seconds": perf_counter() - started,
                "outcome": None if outcome is None else outcome.value,
                "failure_type": failure,
                "job": job_metadata,
                "publication": publication,
                "events": trace.records(),
                "dropped_events": trace.dropped,
                "instrumentation": "metadata_only_observer_delegates_unchanged_production_calls",
                "application_limits_or_lease_parameters_modified": False,
                "source_payloads_tokens_sql_text_or_parameters_retained": False,
            },
        )
