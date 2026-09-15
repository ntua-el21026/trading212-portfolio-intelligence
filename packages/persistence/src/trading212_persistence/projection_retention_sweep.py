"""Persist a small keyset cursor; inspect every root, including clean roots.

An owner-scoped sweep restarts after an owner epoch change (including a new
projection publication). A global expiry pass is an incremental maintenance pass,
not a snapshot-wide authorization claim; earlier owners are revisited next pass.
Private reads and source-parent deletion retain their independent exact guards.
"""

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Table, select, text
from sqlalchemy.orm import Session

from .projection_retention_models import ProjectionRetentionEpochModel as Epoch
from .projection_retention_models import ProjectionRetentionSweepModel as Sweep
from .projection_retention_scan import SourceKind
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows


def begin_sweep(
    session: Session,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    owner: UUID | None,
    target: tuple[SourceKind, UUID] | None,
    erasure: bool,
    report: bool = False,
) -> Sweep | None:
    if type(report) is not bool or (report and (erasure or target is not None)):
        raise ValueError("Report expiry requires its own untargeted root sweep.")
    purpose = (
        "report_expiry"
        if report
        else "owner_erasure"
        if erasure
        else "source_match"
        if target is not None
        else "expiry"
    )
    key = f"{purpose}:{owner or 'global'}" + (f":{target[0]}:{target[1]}" if target else "")
    if budget.metadata_limit < 4:
        return None
    if (
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "projection-sweep:" + key},
        )
        is not True
    ):
        return None
    budget.inspect(rows=1)
    sweep = session.scalar(select(Sweep).where(Sweep.key == key).with_for_update())
    epoch = 0
    if owner is not None:
        budget.inspect(rows=1)
        # Source-match/erasure membership changes only when a new root is published.
        # Unrelated source marker progress cannot reset a long root prefix.
        selected_epoch = Epoch.roots_epoch if target is not None or erasure else Epoch.epoch
        epoch = session.scalar(select(selected_epoch).where(Epoch.owner_id == owner)) or 0
    if sweep is None:
        if (
            session.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"projection-sweep-quota:{owner or 'global'}"},
            )
            is not True
        ):
            return None
        # A fixed ceiling bounds active cursors without evicting pending work.
        # Query at most the remaining allowance and charge every returned identity.
        limit = min(101, budget.metadata_limit)
        rows = list(
            session.scalars(
                select(Sweep.id).where(Sweep.owner_id == owner).order_by(Sweep.key).limit(limit)
            )
        )
        budget.inspect(rows=max(1, len(rows)))
        if len(rows) >= 100 or len(rows) == limit or budget.metadata_limit == 0:
            return None
        budget.inspect(rows=1)
        sweep = Sweep(
            id=uuid4(),
            key=key,
            owner_id=owner,
            purpose=purpose,
            target_kind=target[0] if target else None,
            target_id=target[1] if target else None,
            after_id=None,
            deferred=False,
            policy_epoch=epoch,
            evaluated_at=at,
        )
        session.add(sweep)
    elif sweep.policy_epoch != epoch or at < sweep.evaluated_at:
        budget.inspect(rows=1)
        sweep.after_id, sweep.deferred, sweep.policy_epoch, sweep.evaluated_at = (
            None,
            False,
            epoch,
            at,
        )
    session.flush()
    return sweep


def end_sweep(session: Session, sweep: Sweep, budget: SourcePurgeBudget) -> bool:
    table = cast(Table, Sweep.__table__)
    complete = purge_payload_rows(
        session,
        table,
        table.c.id == sweep.id,
        payload_columns=(
            "key",
            "owner_id",
            "purpose",
            "target_kind",
            "target_id",
            "after_id",
            "deferred",
            "policy_epoch",
            "evaluated_at",
        ),
        delete_rows=True,
        budget=budget,
    ).complete
    return complete and not sweep.deferred
