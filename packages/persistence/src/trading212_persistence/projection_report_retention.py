"""Resume REPORT-only source expiry without destroying valid projection payloads.

Each candidate root is charged before an indexed keyset lookup, including roots
without reports and roots with cached clean proofs. The source frontier and root
cursor persist independently of STORE/DISPLAY expiry. Current source reads never
consult this maintenance state. SQL copy/FK guards remain independent integrity
checks; report mutation reservations charge their bounded internal probes in
addition to the source scanner inspections.
"""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .premium_models import PremiumRetentionModel, PremiumRunModel
from .projection_retention import _charge, _lock_owner
from .projection_retention_models import ProjectionRetentionScanModel
from .projection_retention_scan import scan_projection_sources
from .projection_retention_sweep import begin_sweep, end_sweep
from .report_models import ReportInputPremiumDependencyModel, ReportRetentionWorkModel
from .report_retention import (
    ProjectionReportWitness,
    purge_report_input,
    purge_report_premium_copies,
)
from .source_retention import SourcePurgeBudget


def expire_projection_report_payloads(
    session: Session, *, at: datetime, budget: SourcePurgeBudget, owner: UUID | None = None
) -> bool:
    sweep = begin_sweep(
        session, at=at, budget=budget, owner=owner, target=None, erasure=False, report=True
    )
    if sweep is None:
        return False
    while budget.metadata_limit >= 5:
        query = select(PremiumRunModel.id, PremiumRunModel.owner_id).where(
            PremiumRunModel.kind == "projection"
        )
        if owner is not None:
            query = query.where(PremiumRunModel.owner_id == owner)
        if sweep.after_id is not None:
            query = query.where(PremiumRunModel.id > sweep.after_id)
        _charge(budget)
        candidate = session.execute(query.order_by(PremiumRunModel.id).limit(1)).first()
        if candidate is None:
            return end_sweep(session, sweep, budget)
        _charge(budget)  # reserve the continuation checkpoint before descendant work
        if not _lock_owner(session, candidate.owner_id):
            sweep.deferred, sweep.after_id = True, candidate.id
            session.flush()
            continue
        _charge(budget)
        root = session.scalar(
            select(PremiumRunModel)
            .where(
                PremiumRunModel.id == candidate.id, PremiumRunModel.owner_id == candidate.owner_id
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if root is None:
            sweep.deferred, sweep.after_id = True, candidate.id
            session.flush()
            continue
        if not budget.enter_run("projection", root.id):
            return False
        # An indexed exact-run existence probe is bounded even with a long healthy
        # global root prefix. It never filters roots before the keyset LIMIT.
        _charge(budget)
        dependency = ReportInputPremiumDependencyModel
        input_id = session.scalar(
            select(dependency.input_id)
            .where(
                dependency.owner_id == root.owner_id,
                dependency.account_id == root.account_id,
                dependency.run_id == root.id,
                dependency.copy_pending.is_(True),
            )
            .order_by(dependency.input_id)
            .limit(1)
        )
        if input_id is None:
            sweep.after_id = root.id
            session.flush()
            continue
        _charge(budget)
        pending_copy = session.scalar(
            select(ReportRetentionWorkModel.id).where(
                ReportRetentionWorkModel.owner_id == root.owner_id,
                ReportRetentionWorkModel.input_id == input_id,
                ReportRetentionWorkModel.completed_at.is_(None),
            )
        )
        if pending_copy is not None:
            # The independently authorized permanent marker already denies this
            # exact copy. Re-scanning its sources can starve an atomic artifact
            # and grant deletion when only a small invocation budget remains.
            # Other copies still require their own marker or a current witness.
            if not purge_report_input(
                session,
                owner=root.owner_id,
                input_id=input_id,
                reason="source",
                at=at,
                budget=budget,
            ):
                return False
            continue
        _charge(budget)
        marked = session.scalar(
            select(PremiumRetentionModel.id).where(
                PremiumRetentionModel.owner_id == root.owner_id,
                PremiumRetentionModel.account_id == root.account_id,
                PremiumRetentionModel.run_id == root.id,
            )
        )
        witness: ProjectionReportWitness | None = None
        restricted = root.expires_at <= at or marked is not None
        if not restricted:
            result = scan_projection_sources(session, root, at=at, budget=budget, report=True)
            if result == "pending":
                return False
            if result not in ("restricted", "clean"):
                raise RuntimeError("Unexpected report source expiry result.")
            restricted = result == "restricted"
            if restricted:
                if not budget.inspect(rows=1):
                    return False
                proposal = session.execute(
                    select(
                        ProjectionRetentionScanModel.restriction_kind,
                        ProjectionRetentionScanModel.restriction_id,
                    ).where(
                        ProjectionRetentionScanModel.owner_id == root.owner_id,
                        ProjectionRetentionScanModel.account_id == root.account_id,
                        ProjectionRetentionScanModel.run_id == root.id,
                        ProjectionRetentionScanModel.purpose == "report_expiry",
                    )
                ).one_or_none()
                if (
                    proposal is None
                    or proposal.restriction_kind
                    not in (
                        "price",
                        "fx",
                        "corporate_action",
                        "benchmark",
                        "historical",
                        "license",
                        "classification",
                    )
                    or not isinstance(proposal.restriction_id, UUID)
                ):
                    return False
                witness = cast(
                    ProjectionReportWitness, (proposal.restriction_kind, proposal.restriction_id)
                )
        if restricted and not purge_report_premium_copies(
            session, root.owner_id, root.id, at=at, budget=budget, projection_witness=witness
        ):
            return False
        sweep.after_id = root.id
        session.flush()
    return False
