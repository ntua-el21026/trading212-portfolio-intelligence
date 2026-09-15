"""Small indexed scheduling and terminal transitions for the closed premium families."""

from collections.abc import Callable
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .premium_attempts import premium_attempt
from .premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRetentionModel,
    PremiumRunModel,
)
from .premium_retention_costs import (
    PREMIUM_COMPLETE_ROWS,
    PREMIUM_JOB_ROWS,
    PREMIUM_MARKER_ROWS,
    PREMIUM_PARENT_ROWS,
)
from .premium_retention_models import (
    PremiumRetainedParentModel as Parent,
)
from .premium_retention_models import (
    PremiumRetentionStateModel as State,
)
from .premium_retention_models import (
    PremiumRetentionSweepModel as Sweep,
)
from .premium_retention_scan import PremiumScanInput, scan_premium_restriction
from .report_retention import purge_report_premium_copies
from .source_retention import PayloadCopyCost, SourcePurgeBudget

RunFamily = Literal["risk", "scenario"]
PurgeRun = Callable[[Session, PremiumRunModel, datetime, SourcePurgeBudget], bool]


def lock_owner(session: Session, owner: UUID) -> bool:
    return all(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{owner}"},
        )
        is True
        for namespace in ("sources", "xray", "historical", "premium")
    )


def charge(budget: SourcePurgeBudget, rows: int) -> None:
    if not budget.inspect(rows=rows):
        raise RuntimeError("Premium cleanup exceeded its reserved physical work.")


def open_sweep(
    session: Session, family: str, owner: UUID | None, at: datetime, budget: SourcePurgeBudget
) -> Sweep | None:
    if budget.metadata_limit < 8:
        return None
    scope = owner or UUID(int=0)
    if (
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"premium-sweep:{family}:{scope}"},
        )
        is not True
    ):
        return None
    charge(budget, 1)
    sweep = session.get(Sweep, (scope, family), with_for_update=True)
    epoch = 0
    if owner is not None:
        charge(budget, 1)
        present = session.scalar(text("SELECT id FROM owners WHERE id=:owner"), {"owner": owner})
        if present is None:
            # Empty foreign/missing scopes do not create operational metadata.
            return Sweep(
                scope_id=scope, family=family, deferred=False, policy_epoch=0, evaluated_at=at
            )
        charge(budget, 1)
        epoch = (
            session.scalar(
                text("SELECT epoch FROM projection_retention_epochs WHERE owner_id=:owner"),
                {"owner": owner},
            )
            or 0
        )
    reset = (
        sweep is None
        or sweep.evaluated_at is None
        or (
            owner is not None
            and (
                sweep.policy_epoch != epoch
                or at < sweep.evaluated_at
                or (sweep.earliest_deadline is not None and sweep.earliest_deadline <= at)
                or (sweep.next_policy_at is not None and sweep.next_policy_at <= at)
            )
        )
    )
    if reset:
        next_policy = None
        if owner is not None:
            charge(budget, 1)
            next_policy = session.scalar(
                text(
                    "SELECT effective_at FROM provider_license_versions WHERE "
                    "owner_id=:owner AND effective_at>:at ORDER BY effective_at "
                    "LIMIT 1"
                ),
                {"owner": owner, "at": at},
            )
        charge(budget, 1)
        if sweep is None:
            sweep = Sweep(scope_id=scope, family=family)
            session.add(sweep)
        sweep.after_id, sweep.deferred = None, False
        sweep.policy_epoch, sweep.evaluated_at = epoch, at
        sweep.earliest_deadline, sweep.next_policy_at = None, next_policy
        session.flush()
    return sweep


def checkpoint(
    session: Session,
    sweep: Sweep,
    budget: SourcePurgeBudget,
    identifier: UUID | None,
    *,
    deferred: bool = False,
    deadline: datetime | None = None,
) -> None:
    charge(budget, 1)
    sweep.after_id = identifier
    sweep.deferred = sweep.deferred or deferred
    if deadline is not None:
        sweep.earliest_deadline = (
            deadline if sweep.earliest_deadline is None else min(deadline, sweep.earliest_deadline)
        )
    session.flush()


def finish_sweep(session: Session, sweep: Sweep, budget: SourcePurgeBudget) -> bool:
    clean = not sweep.deferred
    charge(budget, 1)
    sweep.after_id, sweep.deferred, sweep.evaluated_at = None, False, None
    session.flush()
    return clean


def begin_run(
    session: Session,
    root: PremiumRunModel,
    at: datetime,
    budget: SourcePurgeBudget,
    *,
    reason: str | None = None,
) -> PremiumRetentionModel | None:
    if root.kind not in ("risk", "scenario"):
        raise RuntimeError("Unexpected premium cleanup family.")
    family: RunFamily = "risk" if root.kind == "risk" else "scenario"
    if (
        not budget.enter_run(family, root.id)
        or (root.kind == "scenario" and not budget.enter_capture("scenario", root.id))
        or budget.metadata_limit < 2
    ):
        return None
    charge(budget, 1)
    marker = session.scalar(
        select(PremiumRetentionModel).where(
            PremiumRetentionModel.owner_id == root.owner_id, PremiumRetentionModel.run_id == root.id
        )
    )
    if marker is not None and marker.completed_at is not None:
        return marker
    if marker is None:
        if not budget.inspect(rows=PREMIUM_MARKER_ROWS):
            return None
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
        return None
    if budget.metadata_limit < 2:
        return None
    charge(budget, 1)
    job = session.scalar(
        select(PremiumJobModel)
        .where(PremiumJobModel.owner_id == root.owner_id, PremiumJobModel.run_id == root.id)
        .with_for_update()
    )
    if job is None:
        raise RuntimeError("Premium cleanup job identity is absent.")
    if job.state in ("queued", "running"):
        if not budget.inspect(rows=PREMIUM_JOB_ROWS):
            return None
        capacity = session.get(PremiumCapacityModel, root.owner_id, with_for_update=True)
        outbox = session.scalar(
            select(PremiumOutboxModel)
            .where(
                PremiumOutboxModel.owner_id == root.owner_id, PremiumOutboxModel.job_id == job.id
            )
            .with_for_update()
        )
        if capacity is None or outbox is None or capacity.active_jobs < 1:
            raise RuntimeError("Premium cleanup capacity/dispatch identity is absent.")
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
        job.state, job.failure_code, job.completed_at = "expired", "source_restricted", at
        job.lease_token = job.lease_expires_at = job.heartbeat_at = job.deadline_at = (
            job.consumer_id
        ) = None
        capacity.active_jobs -= 1
        capacity.updated_at = at
        outbox.state, outbox.failure_code = "dead_letter", "source_restricted"
        outbox.claim_token = outbox.claim_expires_at = outbox.dispatcher_id = None
        session.flush()
    return marker


def finish_run(
    session: Session,
    root: PremiumRunModel,
    marker: PremiumRetentionModel,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    # The counter has already been updated by each physical row mutation. It is
    # read once; no aggregate payload scan participates in maintenance.
    if budget.metadata_limit < 2:
        return False
    charge(budget, 1)
    state = session.get(State, root.id, populate_existing=True)
    if state is None or state.financial_rows != 0:
        return False
    while budget.metadata_limit >= 1 + PREMIUM_PARENT_ROWS:
        count = min(512 // PREMIUM_PARENT_ROWS, budget.metadata_limit // (1 + PREMIUM_PARENT_ROWS))
        rows = tuple(
            session.scalars(
                select(Parent.id)
                .where(Parent.owner_id == root.owner_id, Parent.run_id == root.id)
                .order_by(Parent.id)
                .limit(count)
            )
        )
        charge(budget, max(1, len(rows)))
        if not rows:
            break
        selected = budget.reserve_clear_batch(
            tuple(
                PayloadCopyCost(row_id=row, payload_bytes=0, inspection_rows=PREMIUM_PARENT_ROWS)
                for row in rows
            )
        )
        if not selected:
            return False
        session.execute(
            delete(Parent).where(
                Parent.owner_id == root.owner_id, Parent.run_id == root.id, Parent.id.in_(selected)
            )
        )
        session.flush()
        if len(selected) != len(rows):
            return False
    else:
        return False
    if not budget.inspect(rows=PREMIUM_COMPLETE_ROWS):
        return False
    capacity = session.get(PremiumCapacityModel, root.owner_id, with_for_update=True)
    if (
        capacity is None
        or capacity.reserved_bytes < root.reserved_bytes
        or capacity.retained_bytes < root.retained_bytes
    ):
        raise RuntimeError("Premium retained capacity is inconsistent.")
    capacity.reserved_bytes -= root.reserved_bytes
    capacity.retained_bytes -= root.retained_bytes
    capacity.updated_at = at
    root.reserved_bytes = root.retained_bytes = 0
    marker.completed_at = at
    session.flush()
    return True


def expire_runs(
    session: Session,
    family: RunFamily,
    purge: PurgeRun,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    owner: UUID | None = None,
    erase: bool = False,
) -> bool:
    sweep = open_sweep(session, family, owner, at, budget)
    if sweep is None:
        return False
    while budget.metadata_limit >= 8:
        query = select(State.run_id, State.owner_id).where(
            State.kind == family, State.closed.is_(False)
        )
        if owner is not None:
            query = query.where(State.owner_id == owner)
        if sweep.after_id is not None:
            query = query.where(State.run_id > sweep.after_id)
        charge(budget, 1)
        candidate = session.execute(query.order_by(State.run_id).limit(1)).first()
        if candidate is None:
            return finish_sweep(session, sweep, budget)
        # Reserve the progress write before potentially consuming the remainder.
        charge(budget, 1)
        deferred = True
        deadline = None
        if lock_owner(session, candidate.owner_id):
            charge(budget, 1)
            root = session.scalar(
                select(PremiumRunModel)
                .where(
                    PremiumRunModel.id == candidate.run_id,
                    PremiumRunModel.owner_id == candidate.owner_id,
                    PremiumRunModel.kind == family,
                )
                .with_for_update(skip_locked=True)
            )
            if root is not None:
                charge(budget, 1)  # Reserve final source-deadline metadata before traversal.
                outcome = (
                    "restricted"
                    if erase
                    else scan_premium_restriction(
                        session,
                        PremiumScanInput(
                            root.owner_id, root.id, family, root.created_at, root.expires_at
                        ),
                        at=at,
                        budget=budget,
                    )
                )
                deadline = root.expires_at
                if outcome == "clean":
                    # The scan's earliest original/pinned/current boundary must
                    # also invalidate a resumed owner sweep's earlier prefix.
                    from .premium_retention_models import PremiumRetentionScanModel

                    slot = session.get(PremiumRetentionScanModel, (root.owner_id, family))
                    if slot is not None and slot.earliest_deadline is not None:
                        deadline = min(deadline, slot.earliest_deadline)
                    deferred = False
                elif outcome == "pending":
                    # Keep this absolute root next; advancing a never-started
                    # proof can otherwise starve the same budget-boundary root.
                    session.flush()
                    return False
                elif outcome == "restricted":
                    if not purge(session, root, at, budget):
                        session.flush()
                        return False
                    deferred = False
        sweep.after_id = candidate.run_id
        sweep.deferred = sweep.deferred or deferred
        if deadline is not None:
            sweep.earliest_deadline = (
                deadline
                if sweep.earliest_deadline is None
                else min(sweep.earliest_deadline, deadline)
            )
        session.flush()
    return False


def drain_parent(
    session: Session,
    owner: UUID,
    parent_kind: str,
    parent_id: UUID,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    if not lock_owner(session, owner):
        return False
    while budget.metadata_limit >= 3:
        charge(budget, 1)
        identifier = session.scalar(
            select(Parent.run_id)
            .where(
                Parent.owner_id == owner,
                Parent.parent_kind == parent_kind,
                Parent.parent_id == parent_id,
            )
            .order_by(Parent.run_id)
            .limit(1)
        )
        if identifier is None:
            return True
        charge(budget, 1)
        root = session.scalar(
            select(PremiumRunModel)
            .where(PremiumRunModel.owner_id == owner, PremiumRunModel.id == identifier)
            .with_for_update(skip_locked=True)
        )
        if root is None:
            return False
        if root.kind == "risk":
            from .risk_retention import _purge_run as purge_risk

            complete = purge_risk(session, root, at=at, budget=budget)
        elif root.kind == "scenario":
            from .scenario_retention import _purge_run as purge_scenario

            complete = purge_scenario(session, root, at=at, budget=budget)
        else:
            raise RuntimeError("Unexpected retained premium parent family.")
        if not complete:
            return False
    return False
