"""Resumable physical scenario expiry under the existing shared source purge budget.

Only fixed ORM participants are used. License lineage contains identities, not
licensed values; cleanup neither decodes a result nor fetches an external source.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, and_, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .premium_attempts import premium_attempt
from .premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRetentionModel,
    PremiumRunModel,
)
from .report_retention import purge_report_premium_copies
from .scenario_models import (
    ScenarioAppliedSensitivityModel,
    ScenarioComponentModel,
    ScenarioResultModel,
    ScenarioRunModel,
    ScenarioRunPayloadModel,
    ScenarioRunSensitivityVersionModel,
)
from .scenario_retention_policy import scenario_run_restricted
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows

# Financial children precede their canonical result and the complete captured envelope.
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
    if not budget.inspect(rows=rows):
        raise RuntimeError("Scenario retention exceeded its metadata allowance.")


def _complete() -> ColumnElement[bool]:
    return (
        select(PremiumRetentionModel.id)
        .where(
            PremiumRetentionModel.owner_id == PremiumRunModel.owner_id,
            PremiumRetentionModel.run_id == PremiumRunModel.id,
            PremiumRetentionModel.completed_at.is_not(None),
        )
        .exists()
    )


def _eligible(at: datetime) -> ColumnElement[bool]:
    return and_(PremiumRunModel.kind == "scenario", ~_complete(), scenario_run_restricted(at))


def _lock_owner(session: Session, owner: UUID) -> bool:
    # No execution-slot lock: a worker holds that lock before these owner locks.
    return all(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{owner}"},
        )
        is True
        for namespace in ("sources", "xray", "historical", "premium")
    )


def _purge_run(
    session: Session,
    root: PremiumRunModel,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    reason: Literal["run_expired", "source_restricted", "owner_erasure"] | None = None,
) -> bool:
    if (
        not budget.enter_run("scenario", root.id)
        or not budget.enter_capture("scenario", root.id)
        or budget.metadata_limit < 7
    ):
        return False
    marker = session.scalar(
        select(PremiumRetentionModel).where(
            PremiumRetentionModel.owner_id == root.owner_id,
            PremiumRetentionModel.run_id == root.id,
        )
    )
    if marker is not None:
        _charge(budget, 1)
        if marker.completed_at is not None:
            return True
    else:
        marker = PremiumRetentionModel(
            id=uuid4(),
            owner_id=root.owner_id,
            account_id=root.account_id,
            run_id=root.id,
            reason=reason or ("run_expired" if root.expires_at <= at else "source_restricted"),
            created_at=at,
        )
        session.add(marker)
        session.flush()
    if not purge_report_premium_copies(session, root.owner_id, root.id, at=at, budget=budget):
        return False
    # Report copies share this allowance. Keep source payload and capacity until
    # a later invocation can inspect and clear the remaining run participants.
    if budget.metadata_limit < 6:
        return False
    job = session.scalar(
        select(PremiumJobModel)
        .where(
            PremiumJobModel.owner_id == root.owner_id,
            PremiumJobModel.run_id == root.id,
        )
        .with_for_update()
    )
    capacity = session.scalar(
        select(PremiumCapacityModel)
        .where(
            PremiumCapacityModel.owner_id == root.owner_id,
        )
        .with_for_update()
    )
    if job is None or capacity is None:
        raise RuntimeError("Scenario retention authority is incomplete.")
    _charge(budget, 2)
    if job.state in ("queued", "running"):
        # Fence publication immediately. Byte reservations remain charged until
        # every payload row is physically gone, even across cleanup invocations.
        _charge(budget, 1)
        premium_attempt(
            session,
            job,
            kind="consumer",
            event="expired",
            number=job.consumer_attempts,
            token=job.lease_token,
            at=at,
            failure="source_restricted",
        )
        job.state = "expired"
        job.failure_code = "source_restricted"
        job.completed_at = at
        job.lease_token = job.lease_expires_at = job.heartbeat_at = job.deadline_at = (
            job.consumer_id
        ) = None
        capacity.active_jobs -= 1
        capacity.updated_at = at
        outbox = session.scalar(
            select(PremiumOutboxModel)
            .where(
                PremiumOutboxModel.owner_id == root.owner_id,
                PremiumOutboxModel.job_id == job.id,
            )
            .with_for_update()
        )
        if outbox is None:
            raise RuntimeError("Scenario retention dispatch identity is missing.")
        _charge(budget, 1)
        outbox.state = "dead_letter"
        outbox.failure_code = "source_restricted"
        outbox.claim_token = outbox.claim_expires_at = outbox.dispatcher_id = None
        session.flush()
    result_id = session.scalar(
        select(ScenarioResultModel.id).where(
            ScenarioResultModel.owner_id == root.owner_id,
            ScenarioResultModel.run_id == root.id,
        )
    )
    if result_id is not None:
        _charge(budget, 1)
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
    capacity.reserved_bytes -= root.reserved_bytes
    capacity.retained_bytes -= root.retained_bytes
    capacity.updated_at = at
    root.reserved_bytes = root.retained_bytes = 0
    marker.completed_at = at
    session.flush()
    return True


def expire_scenario_payloads(
    session: Session, *, at: datetime, budget: SourcePurgeBudget, owner: UUID | None = None
) -> bool:
    """True only if no eligible scenario run remains in the requested scope.

    Sources call this before dropping their copies. Independent dispatch also
    calls it for current license revocation/tightening and ordinary run expiry.
    Busy owners are skipped with nonblocking locks; incomplete work stays indexed.
    """
    busy: set[UUID] = set()
    after: UUID | None = None
    while budget.metadata_limit >= 2:
        query = select(PremiumRunModel.id, PremiumRunModel.owner_id).where(_eligible(at))
        if owner is not None:
            query = query.where(PremiumRunModel.owner_id == owner)
        if busy:
            query = query.where(PremiumRunModel.owner_id.not_in(busy))
        if after is not None:
            query = query.where(PremiumRunModel.id > after)
        candidate = session.execute(query.order_by(PremiumRunModel.id).limit(1)).first()
        if candidate is None:
            return not busy
        _charge(budget, 1)
        after = candidate.id
        if not _lock_owner(session, candidate.owner_id):
            busy.add(candidate.owner_id)
            continue
        root = session.scalar(
            select(PremiumRunModel)
            .where(
                PremiumRunModel.id == candidate.id,
                PremiumRunModel.owner_id == candidate.owner_id,
                _eligible(at),
            )
            .with_for_update(skip_locked=True)
        )
        if root is None:
            busy.add(candidate.owner_id)
            continue
        _charge(budget, 1)
        if not _purge_run(session, root, at=at, budget=budget):
            return False
    return False


def _drain_copies(
    session: Session,
    owner: UUID,
    predicate: ColumnElement[bool],
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    reason: Literal["source_restricted", "owner_erasure"] = "source_restricted",
) -> bool:
    """Caller establishes an exact upstream expiry or explicit owner erasure authority."""
    if not _lock_owner(session, owner):
        return False
    while budget.metadata_limit >= 2:
        identifier = session.scalar(
            select(PremiumRunModel.id)
            .where(
                PremiumRunModel.owner_id == owner,
                PremiumRunModel.kind == "scenario",
                ~_complete(),
                predicate,
            )
            .order_by(PremiumRunModel.id)
            .limit(1)
        )
        if identifier is None:
            return True
        _charge(budget, 1)
        root = session.scalar(
            select(PremiumRunModel)
            .where(
                PremiumRunModel.id == identifier,
                PremiumRunModel.owner_id == owner,
                PremiumRunModel.kind == "scenario",
                ~_complete(),
                predicate,
            )
            .with_for_update(skip_locked=True)
        )
        if root is None:
            return False
        _charge(budget, 1)
        if not _purge_run(session, root, at=at, budget=budget, reason=reason):
            return False
    return False


def purge_scenario_xray_copies(
    session: Session, owner: UUID, input_id: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    selected = (
        select(ScenarioRunModel.id)
        .where(
            ScenarioRunModel.owner_id == owner,
            ScenarioRunModel.id == PremiumRunModel.id,
            ScenarioRunModel.xray_input_id == input_id,
        )
        .exists()
    )
    return _drain_copies(session, owner, selected, at=at, budget=budget)


def purge_scenario_historical_copies(
    session: Session, owner: UUID, input_id: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    selected = (
        select(ScenarioRunModel.id)
        .where(
            ScenarioRunModel.owner_id == owner,
            ScenarioRunModel.id == PremiumRunModel.id,
            ScenarioRunModel.historical_input_id == input_id,
        )
        .exists()
    )
    return _drain_copies(session, owner, selected, at=at, budget=budget)


def purge_scenario_sensitivity_copies(
    session: Session, owner: UUID, version_id: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    selected = (
        select(ScenarioRunSensitivityVersionModel.id)
        .where(
            ScenarioRunSensitivityVersionModel.owner_id == owner,
            ScenarioRunSensitivityVersionModel.run_id == PremiumRunModel.id,
            ScenarioRunSensitivityVersionModel.version_id == version_id,
        )
        .exists()
    )
    return _drain_copies(session, owner, selected, at=at, budget=budget)


def purge_owner_scenario_payloads(
    session: Session, owner: UUID, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    """Explicit owner-erasure participant; permanent identities/audit are retained."""
    from sqlalchemy import true

    from .scenario_source_retention import expire_scenario_sensitivity_payloads

    if not _drain_copies(session, owner, true(), at=at, budget=budget, reason="owner_erasure"):
        return False
    return expire_scenario_sensitivity_payloads(
        session, at=at, budget=budget, owner=owner, erase=True
    )
