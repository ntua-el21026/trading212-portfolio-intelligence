"""Incremental V2/V3 report expiry without recursive candidate predicates."""

from datetime import datetime
from typing import Literal, cast

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .legacy_report_retention_models import LegacyReportRetentionSweepModel as Sweep
from .legacy_report_retention_scan import LegacyReportScanInput, scan_legacy_report
from .projection_retention import _lock_owner
from .report_models import ReportInputPremiumDependencyModel as Dependency
from .report_models import ReportInputSnapshotModel, ReportRetentionWorkModel
from .report_retention import purge_report_input
from .source_retention import SourcePurgeBudget


def resume_report_retention_work(
    session: Session, *, at: datetime, budget: SourcePurgeBudget
) -> int:
    """A permanent marker resumes without proving source restriction again.

    The pending-only index also covers reports whose header was already cleared
    but whose physical source flags or final completion need another batch.
    """
    if budget.metadata_limit < 3:
        return 0
    if (
        session.scalar(
            text(
                "SELECT pg_try_advisory_xact_lock(hashtextextended('legacy-report-retenti"
                "on:sweep',0))"
            )
        )
        is not True
    ):
        return 0
    budget.inspect(rows=1)
    sweep = session.scalar(select(Sweep).where(Sweep.id == 1).with_for_update())
    if sweep is None:
        budget.inspect(rows=1)
        sweep = Sweep(id=1, after_id=None, pending_after_id=None, deferred=False)
        session.add(sweep)
        session.flush()
    completed = 0
    while budget.metadata_limit >= 3:
        budget.inspect(rows=1)
        query = select(
            ReportRetentionWorkModel.id,
            ReportRetentionWorkModel.owner_id,
            ReportRetentionWorkModel.input_id,
            ReportRetentionWorkModel.reason,
        ).where(ReportRetentionWorkModel.completed_at.is_(None))
        if sweep.pending_after_id is not None:
            query = query.where(ReportRetentionWorkModel.id > sweep.pending_after_id)
        candidate = session.execute(query.order_by(ReportRetentionWorkModel.id).limit(1)).first()
        budget.inspect(rows=1)  # Reserve the eventual checkpoint before draining.
        if candidate is None:
            sweep.pending_after_id = None
            session.flush()
            return completed
        if not _lock_owner(session, candidate.owner_id):
            sweep.pending_after_id = candidate.id
            session.flush()
            continue
        if candidate.reason not in ("ttl", "source", "owner"):
            raise RuntimeError("Invalid pending report retention reason.")
        if not purge_report_input(
            session,
            owner=candidate.owner_id,
            input_id=candidate.input_id,
            reason=cast(Literal["ttl", "source", "owner"], candidate.reason),
            at=at,
            budget=budget,
        ):
            return completed
        completed += 1
        sweep.pending_after_id = candidate.id
        session.flush()
    return completed


def expire_legacy_report_payloads(
    session: Session, *, at: datetime, budget: SourcePurgeBudget
) -> int:
    if budget.metadata_limit < 3:
        return 0
    if (
        session.scalar(
            text(
                "SELECT pg_try_advisory_xact_lock(hashtextextended('legacy-report-retenti"
                "on:sweep',0))"
            )
        )
        is not True
    ):
        return 0
    budget.inspect(rows=1)
    sweep = session.scalar(select(Sweep).where(Sweep.id == 1).with_for_update())
    if sweep is None:
        budget.inspect(rows=1)
        sweep = Sweep(id=1, after_id=None, pending_after_id=None, deferred=False)
        session.add(sweep)
        session.flush()
    completed = 0
    while budget.metadata_limit >= 6:
        budget.inspect(rows=1)
        query = select(
            Dependency.id,
            Dependency.owner_id,
            Dependency.account_id,
            Dependency.input_id,
            Dependency.run_id,
            Dependency.kind,
        ).where(Dependency.kind.in_(("risk", "scenario")), Dependency.copy_pending.is_(True))
        if sweep.after_id is not None:
            query = query.where(Dependency.id > sweep.after_id)
        candidate = session.execute(query.order_by(Dependency.id).limit(1)).first()
        # A single metadata mutation was reserved before descendant work; absent
        # and busy candidates are charged too. No clean filter precedes LIMIT.
        budget.inspect(rows=1)
        if candidate is None:
            sweep.after_id, sweep.deferred = None, False
            session.flush()
            return completed
        if not _lock_owner(session, candidate.owner_id):
            sweep.after_id, sweep.deferred = candidate.id, True
            session.flush()
            continue
        budget.inspect(rows=1)
        capture = session.execute(
            select(
                ReportInputSnapshotModel.id,
                ReportInputSnapshotModel.contract_version,
                ReportInputSnapshotModel.created_at,
                ReportInputSnapshotModel.expires_at,
            )
            .where(
                ReportInputSnapshotModel.owner_id == candidate.owner_id,
                ReportInputSnapshotModel.account_id == candidate.account_id,
                ReportInputSnapshotModel.id == candidate.input_id,
            )
            .with_for_update(skip_locked=True)
        ).first()
        if capture is None:
            sweep.after_id, sweep.deferred = candidate.id, True
            session.flush()
            continue
        # A sweep timestamp can precede a concurrent capture. Its original clock
        # is then in the future only relative to this sweep, not a current licence
        # restriction. Revisit it in a later sweep without authorizing erasure.
        if capture.created_at > at:
            sweep.after_id, sweep.deferred = candidate.id, True
            session.flush()
            continue
        if capture.contract_version not in (2, 3) or candidate.kind not in ("risk", "scenario"):
            raise RuntimeError("Invalid legacy report maintenance binding.")
        if not budget.enter_capture("report", candidate.input_id) or not budget.enter_run(
            cast(Literal["risk", "scenario"], candidate.kind), candidate.run_id
        ):
            return completed
        budget.inspect(rows=1)
        pending = session.scalar(
            select(ReportRetentionWorkModel.id).where(
                ReportRetentionWorkModel.owner_id == candidate.owner_id,
                ReportRetentionWorkModel.input_id == candidate.input_id,
                ReportRetentionWorkModel.completed_at.is_(None),
            )
        )
        witness = None
        if capture.expires_at > at and pending is None:
            value = LegacyReportScanInput(
                candidate.owner_id,
                candidate.account_id,
                candidate.input_id,
                candidate.run_id,
                cast(Literal[2, 3], capture.contract_version),
                cast(Literal["risk", "scenario"], candidate.kind),
            )
            outcome = scan_legacy_report(session, value, at=at, budget=budget)
            if outcome == "pending":
                return completed
            if outcome == "deferred":
                sweep.after_id, sweep.deferred = candidate.id, True
                session.flush()
                continue
            if outcome == "clean":
                sweep.after_id = candidate.id
                session.flush()
                continue
            witness = outcome
        if not purge_report_input(
            session,
            owner=candidate.owner_id,
            input_id=candidate.input_id,
            reason="ttl" if capture.expires_at <= at else "source",
            at=at,
            budget=budget,
            legacy_witness=witness,
        ):
            return completed
        completed += 1
        sweep.after_id = candidate.id
        session.flush()
    return completed
