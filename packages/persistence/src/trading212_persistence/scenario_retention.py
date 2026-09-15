"""Indexed, resumable scenario cleanup under the shared physical allowance."""

from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import Table, select
from sqlalchemy.orm import Session

from .premium_models import PremiumRunModel
from .premium_retention_runtime import (
    begin_run,
    charge,
    drain_parent,
    expire_runs,
    finish_run,
    lock_owner,
)
from .scenario_models import (
    ScenarioAppliedSensitivityModel,
    ScenarioComponentModel,
    ScenarioResultModel,
    ScenarioRunPayloadModel,
)
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows

SCENARIO_PAYLOADS = (
    (
        ScenarioAppliedSensitivityModel,
        (
            "component_id",
            "rule_key",
            "version_id",
            "driver_id",
            "driver_definition_version_id",
            "candidate_observation_ids",
            "observation_id",
            "coefficient",
            "shock_size",
            "effect_ratio",
            "effect_reason",
            "effect_quality",
            "reason",
        ),
    ),
    (
        ScenarioComponentModel,
        (
            "path_key",
            "root_key",
            "root_kind",
            "position_id",
            "snapshot_cash_id",
            "root_instrument_id",
            "partition",
            "money_basis",
            "currency",
            "pre_value",
            "post_value",
            "impact",
            "rounding_residual",
            "quality",
            "reason",
            "applied_use_count",
            "canonical_component",
        ),
    ),
)


def _charge(budget: SourcePurgeBudget, rows: int) -> None:
    charge(budget, rows)


def _lock_owner(session: Session, owner: UUID) -> bool:
    return lock_owner(session, owner)


def _purge_run(
    session: Session,
    root: PremiumRunModel,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    reason: Literal["run_expired", "source_restricted", "owner_erasure"] | None = None,
) -> bool:
    marker = begin_run(session, root, at, budget, reason=reason)
    if marker is None:
        return False
    if marker.completed_at is not None:
        return True
    if not budget.inspect(rows=1):
        return False
    result_id = session.scalar(
        select(ScenarioResultModel.id).where(
            ScenarioResultModel.owner_id == root.owner_id,
            ScenarioResultModel.run_id == root.id,
        )
    )
    if result_id is not None:
        for model, columns in SCENARIO_PAYLOADS:
            table = cast(Table, model.__table__)
            if not purge_payload_rows(
                session,
                table,
                (table.c.owner_id == root.owner_id) & (table.c.result_id == result_id),
                payload_columns=columns,
                delete_rows=True,
                budget=budget,
            ).complete:
                return False
    if result_id is not None:
        result = cast(Table, ScenarioResultModel.__table__)
        if not purge_payload_rows(
            session,
            result,
            (result.c.owner_id == root.owner_id) & (result.c.id == result_id),
            payload_columns=("canonical_result",),
            delete_rows=False,
            budget=budget,
        ).complete:
            return False
    payload = cast(Table, ScenarioRunPayloadModel.__table__)
    if not purge_payload_rows(
        session,
        payload,
        (payload.c.owner_id == root.owner_id) & (payload.c.run_id == root.id),
        payload_columns=("canonical_input",),
        delete_rows=True,
        budget=budget,
    ).complete:
        return False
    return finish_run(session, root, marker, at, budget)


def expire_scenario_payloads(
    session: Session, *, at: datetime, budget: SourcePurgeBudget, owner: UUID | None = None
) -> bool:
    return expire_runs(
        session,
        "scenario",
        lambda session, root, at, budget: _purge_run(session, root, at=at, budget=budget),
        at=at,
        budget=budget,
        owner=owner,
    )


def purge_scenario_xray_copies(
    session: Session, owner: UUID, input_id: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    return drain_parent(session, owner, "xray_input", input_id, at=at, budget=budget)


def purge_scenario_historical_copies(
    session: Session, owner: UUID, input_id: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    return drain_parent(session, owner, "historical", input_id, at=at, budget=budget)


def purge_scenario_sensitivity_copies(
    session: Session, owner: UUID, version_id: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    return drain_parent(session, owner, "sensitivity", version_id, at=at, budget=budget)


def purge_owner_scenario_payloads(
    session: Session, owner: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    from .projection_retention import purge_owner_projection_payloads
    from .research_retention import purge_owner_research_payloads
    from .scenario_source_retention import expire_scenario_sensitivity_payloads

    if not purge_owner_research_payloads(
        session, owner, at=at, budget=budget
    ) or not purge_owner_projection_payloads(session, owner, at=at, budget=budget):
        return False
    if not expire_runs(
        session,
        "scenario",
        lambda session, root, at, budget: _purge_run(
            session, root, at=at, budget=budget, reason="owner_erasure"
        ),
        at=at,
        budget=budget,
        owner=owner,
        erase=True,
    ):
        return False
    return expire_scenario_sensitivity_payloads(
        session, at=at, budget=budget, owner=owner, erase=True
    )
