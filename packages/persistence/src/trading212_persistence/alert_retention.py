"""Licensed alert copies share the existing source-purge accounting and barriers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, select, update
from sqlalchemy.orm import Session

from .alert_base import alert_owner_lock
from .alert_models import (
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertEvaluationOutboxModel,
    AlertEventModel,
    AlertInputDependencyModel,
    AlertInputSnapshotModel,
    AlertRetentionWorkModel,
    NotificationDeliveryJobModel,
    NotificationDeliveryOutboxModel,
)
from .models import AuditEventModel
from .report_retention import _clear_payloads
from .source_retention import SourcePurgeBudget


def purge_alert_input(
    session: Session,
    *,
    owner: UUID,
    input_id: UUID,
    reason: Literal["ttl", "source", "owner"],
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    if not budget.enter_capture("alert", input_id) or not budget.metadata_limit:
        return False
    row = session.scalar(
        select(AlertInputSnapshotModel)
        .where(AlertInputSnapshotModel.id == input_id, AlertInputSnapshotModel.owner_id == owner)
        .with_for_update()
    )
    if not budget.inspect(rows=1) or row is None:
        return False
    work = session.scalar(
        select(AlertRetentionWorkModel).where(
            AlertRetentionWorkModel.input_id == input_id, AlertRetentionWorkModel.owner_id == owner
        )
    )
    if not budget.inspect(rows=1):
        return False
    if work is None:
        work = AlertRetentionWorkModel(
            id=uuid4(),
            owner_id=owner,
            input_id=input_id,
            reason=reason,
            created_at=at,
            completed_at=None,
        )
        session.add(work)
        session.flush()
    elif work.completed_at is not None:
        return True
    evaluation_ids = select(AlertEvaluationModel.id).where(
        AlertEvaluationModel.owner_id == owner, AlertEvaluationModel.input_id == input_id
    )
    event_ids = select(AlertEventModel.id).where(
        AlertEventModel.owner_id == owner, AlertEventModel.evaluation_id.in_(evaluation_ids)
    )
    # Expiry immediately fences delivery, including the IDs-only external projection.
    for model, outbox, parent in (
        (
            AlertEvaluationJobModel,
            AlertEvaluationOutboxModel,
            AlertEvaluationJobModel.input_id == input_id,
        ),
        (
            NotificationDeliveryJobModel,
            NotificationDeliveryOutboxModel,
            NotificationDeliveryJobModel.event_id.in_(event_ids),
        ),
    ):
        jobs = tuple(
            session.scalars(
                select(model)
                .where(model.owner_id == owner, parent, model.state.in_(("queued", "running")))
                .order_by(model.id)
                .limit(budget.metadata_limit)
            )
        )
        if not budget.inspect(rows=len(jobs)):
            return False
        for job in jobs:
            if not budget.enter_run("alert", job.id):
                return False
            job.state = "expired"
            job.completed_at = at
            job.failure_code = "source_expired"
            job.lease_id = None
            job.lease_expires_at = None
            job.consumer_id = None
            session.execute(
                update(outbox)
                .where(outbox.job_id == job.id)
                .values(
                    state="failed",
                    claim_token=None,
                    claim_expires_at=None,
                    dispatcher_id=None,
                    failure_code="source_expired",
                )
            )
            session.add(
                AuditEventModel(
                    id=uuid4(),
                    owner_id=owner,
                    principal_id=job.principal_id,
                    broker_account_id=job.account_id,
                    action="alert.job.expired",
                    resource_type="alert_job",
                    resource_id=str(job.id),
                    outcome="succeeded",
                    occurred_at=at,
                    safe_metadata={"reason": reason},
                )
            )
        if not budget.metadata_limit:
            return False
        if (
            session.scalar(
                select(model.id)
                .where(model.owner_id == owner, parent, model.state.in_(("queued", "running")))
                .limit(1)
            )
            is not None
        ):
            budget.inspect(rows=1)
            return False
    for payload_model, predicate in (
        (AlertEventModel, (AlertEventModel.owner_id == owner) & AlertEventModel.id.in_(event_ids)),
        (
            AlertEvaluationModel,
            (AlertEvaluationModel.owner_id == owner) & (AlertEvaluationModel.input_id == input_id),
        ),
        (
            AlertInputSnapshotModel,
            (AlertInputSnapshotModel.owner_id == owner) & (AlertInputSnapshotModel.id == input_id),
        ),
    ):
        if not _clear_payloads(
            session,
            cast(Table, payload_model.__table__),
            predicate,
            columns=("payload",),
            at=at,
            budget=budget,
        ):
            return False
    work.completed_at = at
    session.add(
        AuditEventModel(
            id=uuid4(),
            owner_id=owner,
            principal_id=None,
            broker_account_id=row.account_id,
            action="alert.input.purged",
            resource_type="alert_input",
            resource_id=str(input_id),
            outcome="succeeded",
            occurred_at=at,
            safe_metadata={"reason": reason},
        )
    )
    session.flush()
    return True


def purge_alert_source_copies(
    session: Session,
    *,
    owner: UUID,
    kind: str,
    source_id: UUID,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    while budget.metadata_limit >= 2:
        identifier = session.scalar(
            select(AlertInputSnapshotModel.id)
            .join(
                AlertInputDependencyModel,
                AlertInputDependencyModel.input_id == AlertInputSnapshotModel.id,
            )
            .where(
                AlertInputSnapshotModel.owner_id == owner,
                AlertInputDependencyModel.owner_id == owner,
                AlertInputDependencyModel.kind == kind,
                AlertInputDependencyModel.source_id == source_id,
                AlertInputSnapshotModel.purged_at.is_(None),
            )
            .order_by(AlertInputSnapshotModel.id)
            .limit(1)
        )
        if identifier is None:
            return True
        if not budget.inspect(rows=2) or not purge_alert_input(
            session, owner=owner, input_id=identifier, reason="source", at=at, budget=budget
        ):
            return False
    return False


def expire_alert_payloads(
    session: Session, *, at: datetime, limit: int = 100, budget: SourcePurgeBudget | None = None
) -> int:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Alert expiry is bounded to 100 captures.")
    budget = budget or SourcePurgeBudget(captures=limit)
    completed = 0
    while completed < limit and budget.metadata_limit >= 2:
        row = session.execute(
            select(AlertInputSnapshotModel.id, AlertInputSnapshotModel.owner_id)
            .where(
                AlertInputSnapshotModel.expires_at <= at,
                AlertInputSnapshotModel.purged_at.is_(None),
            )
            .order_by(AlertInputSnapshotModel.expires_at, AlertInputSnapshotModel.id)
            .limit(1)
        ).first()
        if row is None:
            break
        if not budget.inspect(rows=1) or not alert_owner_lock(session, row.owner_id, wait=False):
            break
        if not purge_alert_input(
            session, owner=row.owner_id, input_id=row.id, reason="ttl", at=at, budget=budget
        ):
            break
        completed += 1
    return completed
