"""Indexed research report closure within the shared physical-copy purge budget."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from .report_base import report_owner_lock
from .report_models import ReportInputDependencyModel
from .report_physical_retention import LegacyReportWitness
from .report_research_models import (
    ReportInputResearchDependencyModel,
    ReportInputResearchNoteModel,
    ReportInputResearchSourceModel,
    ReportResearchRetentionSweepModel,
)
from .source_retention import SourcePurgeBudget

# Each mutation's trigger reads an exact retention marker, <=24 physical report
# participants and fixed FK/scope rows; the root additionally probes two pending
# child indexes. Selection, including an empty seek, is separately charged.
RESEARCH_REPORT_FLAG_ROWS = 48
# One exact source-member predicate: member/header/origin/provider/scope,
# original+current grants/licenses, three marker/physical probes and fixed seeks.
RESEARCH_REPORT_SOURCE_PROBE_ROWS = 32
# Existing closed physical probe: exact dependency/input, one physical header,
# at most two active marker arms and pinned/current license seeks (<=16), plus
# the existing acquired price/FX authority's <=12 point rows and scoped root.
# The kind is closed by its typed FK; research versions use their own authority.
RESEARCH_REPORT_PHYSICAL_PROBE_ROWS = 32


def clear_report_research_flags(
    session: Session, owner: UUID, input_id: UUID, *, budget: SourcePurgeBudget
) -> bool:
    """Prove physical closure, then clear children before their immutable root.

    A source may finish after its own flag is cleared but before unrelated audit
    flags fit a later batch. The physical witness prevents an event/X-ray barrier
    from mistaking that bounded metadata continuation for retained private bytes.
    """
    root_model = ReportInputResearchDependencyModel
    if not budget.inspect(rows=1):
        return False
    root_id = session.scalar(
        select(root_model.id)
        .where(
            root_model.owner_id == owner,
            root_model.input_id == input_id,
            root_model.payload_pending.is_(True),
        )
        .with_for_update()
    )
    if root_id is not None:
        if not budget.inspect(rows=RESEARCH_REPORT_FLAG_ROWS):
            return False
        session.execute(
            update(root_model).where(root_model.id == root_id).values(payload_pending=False)
        )
    for model in (
        ReportInputResearchSourceModel,
        ReportInputResearchNoteModel,
        ReportInputResearchDependencyModel,
    ):
        predicate = (
            (model.owner_id == owner) & (model.input_id == input_id) & model.copy_pending.is_(True)
        )
        while budget.metadata_limit:
            limit = min(512, budget.rows_inspected) // (1 + RESEARCH_REPORT_FLAG_ROWS)
            if limit < 1:
                return False
            identifiers = tuple(
                session.scalars(
                    select(model.id)
                    .where(predicate)
                    .order_by(model.id)
                    .limit(limit)
                    .with_for_update()
                )
            )
            if not budget.inspect(rows=max(1, len(identifiers))):
                return False
            if not identifiers:
                break
            if not budget.inspect(rows=len(identifiers) * RESEARCH_REPORT_FLAG_ROWS):
                return False
            session.execute(
                update(model).where(predicate, model.id.in_(identifiers)).values(copy_pending=False)
            )
        else:
            return False
    return True


def purge_research_report_copies(
    session: Session,
    owner: UUID,
    subject: UUID,
    *,
    kind: Literal["source", "owner", "xray"],
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    """Drain only exact indexed pending membership, preserving immutable lineage."""
    from .report_retention import purge_report_input

    while budget.metadata_limit >= 3:
        if not budget.inspect(rows=1):
            return False
        witness: LegacyReportWitness
        if kind == "source":
            member = ReportInputResearchSourceModel
            candidate = session.execute(
                select(member.input_id, member.id)
                .where(
                    member.owner_id == owner,
                    member.source_version_id == subject,
                    member.copy_pending.is_(True),
                )
                .order_by(member.input_id, member.id)
                .limit(1)
            ).first()
            if candidate is None:
                return True
            input_id, member_id = candidate
            witness = ("research_source", member_id)
        else:
            root = ReportInputResearchDependencyModel
            query = select(root.input_id).where(root.owner_id == owner, root.copy_pending.is_(True))
            if kind == "xray":
                query = query.where(root.xray_input_id == subject)
            elif subject != owner:
                raise ValueError("Research report owner witness differs.")
            input_id = session.scalar(query.order_by(root.input_id).limit(1))
            if input_id is None:
                return True
            witness = ("research_xray", subject) if kind == "xray" else ("research_owner", owner)
        if not purge_report_input(
            session,
            owner=owner,
            input_id=input_id,
            reason="source",
            at=at,
            budget=budget,
            legacy_witness=witness,
        ):
            return False
    return False


def _expire_research_physical(
    session: Session,
    sweep: ReportResearchRetentionSweepModel,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
) -> None:
    from .report_retention import purge_report_input

    member, root = ReportInputDependencyModel, ReportInputResearchDependencyModel
    # Sixteen raw rows per phase let both source inventories advance even when
    # a long healthy prefix fills the ordinary shared metadata allowance.
    for _ in range(16):
        if budget.metadata_limit < RESEARCH_REPORT_PHYSICAL_PROBE_ROWS + 4:
            return
        budget.inspect(rows=1)
        query = select(member.id, member.owner_id, member.input_id, member.created_at).where(
            member.copy_pending.is_(True)
        )
        if sweep.physical_after_id is not None:
            query = query.where(member.id > sweep.physical_after_id)
        candidate = session.execute(query.order_by(member.id).limit(1)).first()
        budget.inspect(rows=1)  # eventual durable cursor mutation, including empty seek
        if candidate is None:
            sweep.physical_after_id = None
            session.flush()
            return
        budget.inspect(rows=1)
        research = session.scalar(
            select(root.id).where(
                root.owner_id == candidate.owner_id,
                root.input_id == candidate.input_id,
                root.copy_pending.is_(True),
            )
        )
        if (
            research is not None
            and candidate.created_at <= at
            and report_owner_lock(session, candidate.owner_id, wait=False)
        ):
            budget.inspect(rows=RESEARCH_REPORT_PHYSICAL_PROBE_ROWS)
            restricted = session.scalar(
                text("SELECT report_research_physical_restricted(:owner,:input,:member,:at)"),
                {
                    "owner": candidate.owner_id,
                    "input": candidate.input_id,
                    "member": candidate.id,
                    "at": at,
                },
            )
            if restricted is not False and not purge_report_input(
                session,
                owner=candidate.owner_id,
                input_id=candidate.input_id,
                reason="source",
                at=at,
                budget=budget,
                legacy_witness=("physical", candidate.id),
            ):
                return
        sweep.physical_after_id = candidate.id
        session.flush()


def expire_research_report_payloads(
    session: Session, *, at: datetime, budget: SourcePurgeBudget
) -> bool:
    """Rotate a durable raw pending-member keyset, including healthy source rows.

    REPORT-only revocation leaves valid original research prose and notes intact.
    A permanent report marker resumes through the existing shared pending queue.
    No payload, recursive eligibility predicate or uncharged healthy prefix is
    selected before the bounded candidate LIMIT.
    """
    from .report_retention import purge_report_input

    if budget.metadata_limit < 4:
        return False
    if (
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended('research-report:sweep',0))")
        )
        is not True
    ):
        return False
    budget.inspect(rows=1)
    sweep = session.get(ReportResearchRetentionSweepModel, 1, with_for_update=True)
    if sweep is None:
        budget.inspect(rows=1)
        sweep = ReportResearchRetentionSweepModel(id=1, after_id=None, physical_after_id=None)
        session.add(sweep)
        session.flush()
    _expire_research_physical(session, sweep, at=at, budget=budget)
    member = ReportInputResearchSourceModel
    # Each probe is charged before it executes, with a durable next-id write
    # reserved before descendants consume the remaining invocation allowance.
    for _ in range(16):
        if budget.metadata_limit < RESEARCH_REPORT_SOURCE_PROBE_ROWS + 3:
            return False
        budget.inspect(rows=1)
        query = select(member.id, member.owner_id, member.input_id).where(
            member.copy_pending.is_(True)
        )
        if sweep.after_id is not None:
            query = query.where(member.id > sweep.after_id)
        candidate = session.execute(query.order_by(member.id).limit(1)).first()
        budget.inspect(rows=1)
        if candidate is None:
            sweep.after_id = None
            session.flush()
            return True
        if not report_owner_lock(session, candidate.owner_id, wait=False):
            sweep.after_id = candidate.id
            session.flush()
            continue
        budget.inspect(rows=RESEARCH_REPORT_SOURCE_PROBE_ROWS)
        restricted = session.scalar(
            text("SELECT report_research_source_restricted(:owner,:member,:at)"),
            {"owner": candidate.owner_id, "member": candidate.id, "at": at},
        )
        if restricted is not False and not purge_report_input(
            session,
            owner=candidate.owner_id,
            input_id=candidate.input_id,
            reason="source",
            at=at,
            budget=budget,
            legacy_witness=("research_source", candidate.id),
        ):
            return False
        sweep.after_id = candidate.id
        session.flush()
    return False
