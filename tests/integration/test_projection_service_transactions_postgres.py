"""Real public projection idempotency, rollback and cancellation accounting."""

from dataclasses import replace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from trading212_application import projection as app
from trading212_persistence.premium_models import (
    PremiumAuditModel,
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.report_models import ApplicationCommandIdentityModel

from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def snapshot(case: ProjectionJobCase) -> tuple[tuple[int, ...], tuple[int, int, int, int]]:
    with case.sessions() as session:
        counts = tuple(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in (
                PremiumRunModel,
                PremiumJobModel,
                PremiumOutboxModel,
                ApplicationCommandIdentityModel,
                PremiumAuditModel,
            )
        )
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        return counts, (
            capacity.active_jobs,
            capacity.reserved_bytes,
            capacity.retained_bytes,
            capacity.definition_versions,
        )


async def test_semantic_replay_keeps_original_run_and_reservation(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    before = snapshot(case)
    with patch.object(
        case.service, "capture", side_effect=AssertionError("same command must not recapture")
    ):
        again = await case.service.create_run(
            case.principal, replace(case.command, correlation_id="refreshed-trace")
        )
        with pytest.raises(app.ProjectionServiceError) as changed:
            await case.service.create_run(
                case.principal,
                replace(
                    case.command,
                    selection=replace(case.command.selection, seed=case.command.selection.seed + 1),
                ),
            )
    assert again == case.run
    assert changed.value.code is app.ProjectionErrorCode.CONFLICT
    assert snapshot(case) == before


async def test_final_source_denial_rolls_back_command_input_job_outbox_and_capacity(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    before = snapshot(case)
    with (
        patch(
            "trading212_persistence.projection_service.require_projection_run_sources",
            side_effect=ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE),
        ),
        pytest.raises(app.ProjectionServiceError) as denied,
    ):
        await case.service.create_run(
            case.principal, replace(case.command, idempotency_key=str(uuid4()))
        )
    assert denied.value.code is app.ProjectionErrorCode.SOURCE_UNAVAILABLE
    assert snapshot(case) == before


async def test_cancel_retry_charges_original_input_exactly_once(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    command = app.CancelProjectionRun(
        run_id=case.run.id, idempotency_key=str(uuid4()), correlation_id="cancel-once"
    )
    first = await case.service.cancel_run(case.principal, command)
    cancelled = snapshot(case)
    again = await case.service.cancel_run(
        case.principal, replace(command, correlation_id="refreshed-cancel")
    )
    assert again == first and first.result is None
    assert snapshot(case) == cancelled
    with case.sessions() as session:
        root = session.get_one(PremiumRunModel, case.run.id)
        size = session.scalar(select(func.projection_storage_bytes(root.id)))
        capacity = session.get_one(PremiumCapacityModel, UUID(case.principal.owner_id))
        assert size is not None and size > 0
        assert root.retained_bytes == capacity.retained_bytes == size
        assert root.reserved_bytes == capacity.reserved_bytes == capacity.active_jobs == 0
