"""Resumable owned source inspection under the shared physical cleanup budget.

A completed clean sweep is maintenance state, never read authorization. Original
source/retention SQL triggers remain independent integrity backstops. Every
explicit read here reserves a row before I/O; absent lookups are conservatively
charged too. No financial columns or private codec are used.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from . import historical_models as hm
from . import source_models as sm
from .premium_models import PremiumRunModel
from .projection_models import ProjectionRunModel, ProjectionRunSourceModel
from .projection_retention_models import (
    ProjectionRetentionEpochModel as Epoch,
)
from .projection_retention_models import (
    ProjectionRetentionFrontierModel as Frontier,
)
from .projection_retention_models import (
    ProjectionRetentionScanModel as Scan,
)
from .projection_retention_models import (
    ProjectionRetentionTargetModel as Target,
)
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows

SourceKind = Literal["price", "fx", "corporate_action", "benchmark", "historical"]
ScanResult = Literal["restricted", "clean", "match", "no_match", "pending"]
_PHYSICAL: dict[str, Any] = {
    "price": sm.PriceSnapshotModel,
    "fx": sm.FxSnapshotModel,
    "corporate_action": sm.CorporateActionSnapshotModel,
    "benchmark": sm.BenchmarkSnapshotModel,
}
_FRONTIER_COLUMNS = ("scan_id", "subject_id", "is_evidence", "dependency_cursor", "complete")
_TARGET_COLUMNS = ("run_id", "target_kind", "target_id", "matched")
_SCAN_COLUMNS = (
    "run_id",
    "restriction_kind",
    "restriction_id",
    "purpose",
    "target_kind",
    "target_id",
    "phase",
    "policy_epoch",
    "evaluated_at",
    "next_policy_at",
    "earliest_deadline",
    "source_cursor",
    "current_source_id",
    "history_input_id",
    "history_created_at",
    "source_count",
    "dependencies_seen",
    "node_count",
)


class _Yield(Exception):
    pass


def _charge(budget: SourcePurgeBudget) -> None:
    if not budget.inspect(rows=1):
        raise _Yield


def _row(session: Session, query: Select[Any], budget: SourcePurgeBudget) -> Any:
    _charge(budget)
    return session.execute(query).mappings().one_or_none()


def _scalar(session: Session, query: Select[Any], budget: SourcePurgeBudget) -> Any:
    _charge(budget)
    return session.scalar(query)


def _epoch(session: Session, owner: UUID, budget: SourcePurgeBudget) -> int:
    value = _scalar(session, select(Epoch.epoch).where(Epoch.owner_id == owner), budget)
    if value is None:
        return 0
    if type(value) is not int or value < 0:
        raise RuntimeError("Invalid projection retention policy epoch.")
    return value


def _until(scan: Scan, value: datetime) -> None:
    scan.earliest_deadline = min(scan.earliest_deadline or value, value)


def _license_until(
    session: Session,
    scan: Scan,
    identifier: UUID,
    original: datetime,
    at: datetime,
    budget: SourcePurgeBudget,
) -> datetime | None:
    model = sm.ProviderLicenseVersionModel
    columns = (
        model.id,
        model.provider_id,
        model.effective_at,
        model.store_permission,
        model.display_permission,
        model.report_permission,
        model.retention_days,
    )
    pinned = _row(
        session,
        select(*columns).where(model.owner_id == scan.owner_id, model.id == identifier),
        budget,
    )
    if (
        pinned is None
        or pinned.effective_at > at
        or pinned.store_permission != "allowed"
        or pinned.display_permission != "allowed"
        or (scan.purpose == "report_expiry" and pinned.report_permission != "allowed")
        or pinned.retention_days is None
        or original > at
    ):
        return None
    current = _row(
        session,
        select(*columns)
        .where(
            model.owner_id == scan.owner_id,
            model.provider_id == pinned.provider_id,
            model.effective_at <= at,
        )
        .order_by(model.effective_at.desc(), model.version_number.desc(), model.id.desc())
        .limit(1),
        budget,
    )
    if (
        current is None
        or current.store_permission != "allowed"
        or current.display_permission != "allowed"
        or (scan.purpose == "report_expiry" and current.report_permission != "allowed")
        or current.retention_days is None
    ):
        return None
    value = original + timedelta(days=min(30, pinned.retention_days, current.retention_days))
    _until(scan, value)
    return value


def _restrict(scan: Scan, kind: str, identifier: UUID) -> bool:
    if scan.purpose == "report_expiry":
        scan.restriction_kind, scan.restriction_id = kind, identifier
    return True


def _physical(
    session: Session,
    scan: Scan,
    kind: str,
    identifier: UUID,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    """True means a current concrete restriction, never an incomplete proof."""
    model = _PHYSICAL[kind]
    row = _row(
        session,
        select(
            model.id,
            model.created_at,
            model.expires_at,
            model.license_version_id,
            model.provider_id,
        ).where(model.owner_id == scan.owner_id, model.id == identifier),
        budget,
    )
    if row is None or row.created_at > at:
        return _restrict(scan, kind, identifier)
    for marker in (sm.SourceRetentionWorkModel, sm.SourceExpiryEventModel):
        reference = getattr(marker, f"{kind}_snapshot_id")
        if (
            _scalar(
                session,
                select(marker.id)
                .where(marker.owner_id == scan.owner_id, reference == identifier)
                .limit(1),
                budget,
            )
            is not None
        ):
            return _restrict(scan, kind, identifier)
    _until(scan, row.expires_at)
    until = _license_until(session, scan, row.license_version_id, row.created_at, at, budget)
    return (until is None or min(until, row.expires_at) <= at) and _restrict(scan, kind, identifier)


def _add_node(
    session: Session, scan: Scan, subject: UUID, evidence: bool, budget: SourcePurgeBudget
) -> None:
    _charge(budget)
    inserted = session.scalar(
        insert(Frontier)
        .values(
            id=uuid4(),
            owner_id=scan.owner_id,
            account_id=scan.account_id,
            scan_id=scan.id,
            subject_id=subject,
            is_evidence=evidence,
            dependency_cursor=None,
            complete=False,
            created_at=scan.evaluated_at,
        )
        .on_conflict_do_nothing(index_elements=["scan_id", "subject_id", "is_evidence"])
        .returning(Frontier.id)
    )
    if inserted is not None:
        scan.node_count += 1
        if scan.node_count > 100001:
            raise RuntimeError("Projection retention frontier exceeds the admitted graph bound.")


def _clear_frontier(session: Session, scan: Scan, budget: SourcePurgeBudget) -> bool:
    table = cast(Table, Frontier.__table__)
    return purge_payload_rows(
        session,
        table,
        (table.c.owner_id == scan.owner_id)
        & (table.c.account_id == scan.account_id)
        & (table.c.scan_id == scan.id),
        payload_columns=_FRONTIER_COLUMNS,
        delete_rows=True,
        budget=budget,
    ).complete


def clear_projection_scans(
    session: Session, root: PremiumRunModel, budget: SourcePurgeBudget
) -> bool:
    """Remove no-longer-needed continuation metadata with the same allowance."""
    while budget.metadata_limit:
        scan = _scalar(
            session,
            select(Scan)
            .where(
                Scan.owner_id == root.owner_id,
                Scan.account_id == root.account_id,
                Scan.run_id == root.id,
            )
            .order_by(Scan.id)
            .limit(1),
            budget,
        )
        if scan is None:
            table = cast(Table, Target.__table__)
            return purge_payload_rows(
                session,
                table,
                (table.c.owner_id == root.owner_id)
                & (table.c.account_id == root.account_id)
                & (table.c.run_id == root.id),
                payload_columns=_TARGET_COLUMNS,
                delete_rows=True,
                budget=budget,
            ).complete
        if not _clear_frontier(session, scan, budget):
            return False
        table = cast(Table, Scan.__table__)
        if not purge_payload_rows(
            session,
            table,
            (table.c.owner_id == root.owner_id)
            & (table.c.account_id == root.account_id)
            & (table.c.id == scan.id),
            payload_columns=_SCAN_COLUMNS,
            delete_rows=True,
            budget=budget,
        ).complete:
            return False
    return False


def _reset(
    session: Session, scan: Scan, epoch: int, at: datetime, budget: SourcePurgeBudget
) -> bool:
    _charge(budget)  # reserve restart checkpoint before bounded frontier deletion
    _charge(budget)  # reserve final reset checkpoint
    scan.phase = "restart"
    if not _clear_frontier(session, scan, budget):
        return False
    next_policy = _scalar(
        session,
        select(sm.ProviderLicenseVersionModel.effective_at)
        .where(
            sm.ProviderLicenseVersionModel.owner_id == scan.owner_id,
            sm.ProviderLicenseVersionModel.effective_at > at,
        )
        .order_by(sm.ProviderLicenseVersionModel.effective_at)
        .limit(1),
        budget,
    )
    scan.phase = "source"
    scan.policy_epoch, scan.evaluated_at, scan.next_policy_at = epoch, at, next_policy
    scan.earliest_deadline = None
    scan.restriction_kind = scan.restriction_id = None
    scan.source_cursor = scan.current_source_id = scan.history_input_id = None
    scan.history_created_at = None
    scan.source_count = scan.dependencies_seen = scan.node_count = 0
    return True


def _source(
    session: Session,
    root: PremiumRunModel,
    scan: Scan,
    at: datetime,
    budget: SourcePurgeBudget,
) -> ScanResult | None:
    model = ProjectionRunSourceModel
    query = select(model).where(
        model.owner_id == root.owner_id,
        model.account_id == root.account_id,
        model.run_id == root.id,
    )
    if scan.source_cursor is not None:
        query = query.where(model.id > scan.source_cursor)
    source = _scalar(session, query.order_by(model.id).limit(1), budget)
    if source is None:
        count = _scalar(
            session,
            select(ProjectionRunModel.source_count).where(
                ProjectionRunModel.owner_id == root.owner_id,
                ProjectionRunModel.account_id == root.account_id,
                ProjectionRunModel.id == root.id,
            ),
            budget,
        )
        if count != scan.source_count:
            return "restricted" if scan.purpose in ("expiry", "report_expiry") else "pending"
        scan.phase = "clean"
        return "clean" if scan.purpose in ("expiry", "report_expiry") else "no_match"
    scan.current_source_id = source.id
    # Advance only after fully inspecting the source; a yield repeats no partial conclusion.
    if scan.purpose in ("expiry", "report_expiry"):
        _until(scan, source.source_expires_at)
        if source.source_expires_at <= at or source.original_created_at > at:
            return "restricted"
    if source.kind == "initial_snapshot":
        scan.source_count += 1
        scan.source_cursor = source.id
        return None
    if source.kind != "calibration":
        return "restricted" if scan.purpose in ("expiry", "report_expiry") else "pending"
    historical = _row(
        session,
        select(
            hm.HistoricalInputModel.id,
            hm.HistoricalInputModel.created_at,
            hm.HistoricalInputModel.input_digest,
            hm.HistoricalInputModel.sealed,
            hm.HistoricalInputModel.broker_account_id,
        ).where(
            hm.HistoricalInputModel.owner_id == root.owner_id,
            hm.HistoricalInputModel.id == source.subject_id,
        ),
        budget,
    )
    price = _row(
        session,
        select(
            sm.PriceSnapshotModel.id,
            sm.PriceSnapshotModel.created_at,
            sm.PriceSnapshotModel.content_digest,
        ).where(
            sm.PriceSnapshotModel.owner_id == root.owner_id,
            sm.PriceSnapshotModel.id == source.subject_id,
        ),
        budget,
    )
    benchmark = _row(
        session,
        select(
            sm.BenchmarkSnapshotModel.id,
            sm.BenchmarkSnapshotModel.created_at,
            sm.BenchmarkSnapshotModel.content_digest,
        ).where(
            sm.BenchmarkSnapshotModel.owner_id == root.owner_id,
            sm.BenchmarkSnapshotModel.id == source.subject_id,
        ),
        budget,
    )
    if sum(item is not None for item in (historical, price, benchmark)) != 1:
        return "restricted" if scan.purpose in ("expiry", "report_expiry") else "pending"
    kind = "historical" if historical is not None else "price" if price is not None else "benchmark"
    header = historical if historical is not None else price if price is not None else benchmark
    actual_digest = header.input_digest if historical is not None else header.content_digest
    if header.created_at != source.original_created_at or actual_digest != source.content_digest:
        return "restricted" if scan.purpose in ("expiry", "report_expiry") else "pending"
    if scan.purpose == "source_match" and (scan.target_kind, scan.target_id) == (
        kind,
        source.subject_id,
    ):
        return "match"
    if historical is not None:
        if historical.broker_account_id != root.account_id or not historical.sealed:
            return "restricted" if scan.purpose in ("expiry", "report_expiry") else "pending"
        if (
            scan.purpose in ("expiry", "report_expiry")
            and _scalar(
                session,
                select(hm.HistoricalRetentionEventModel.id)
                .where(
                    hm.HistoricalRetentionEventModel.owner_id == root.owner_id,
                    hm.HistoricalRetentionEventModel.input_id == source.subject_id,
                )
                .limit(1),
                budget,
            )
            is not None
        ):
            _restrict(scan, "historical", source.subject_id)
            return "restricted"
        scan.history_input_id, scan.history_created_at = source.subject_id, historical.created_at
        _add_node(session, scan, source.subject_id, False, budget)
        scan.phase = "walk"
    else:
        if scan.purpose in ("expiry", "report_expiry") and _physical(
            session, scan, kind, source.subject_id, at, budget
        ):
            return "restricted"
        scan.source_count += 1
        scan.source_cursor = source.id
    return None


def _walk(
    session: Session,
    root: PremiumRunModel,
    scan: Scan,
    at: datetime,
    budget: SourcePurgeBudget,
) -> ScanResult | None:
    node = _scalar(
        session,
        select(Frontier)
        .where(
            Frontier.owner_id == root.owner_id,
            Frontier.account_id == root.account_id,
            Frontier.scan_id == scan.id,
            Frontier.complete.is_(False),
        )
        .order_by(Frontier.id)
        .limit(1),
        budget,
    )
    if node is None:
        scan.phase = "clear"
        return None
    dependency = hm.HistoricalDependencyModel
    parent = (
        dependency.evidence_id == node.subject_id
        if node.is_evidence
        else dependency.input_id == node.subject_id
    )
    query = select(dependency).where(dependency.owner_id == root.owner_id, parent)
    if node.dependency_cursor is not None:
        query = query.where(dependency.id > node.dependency_cursor)
    link = _scalar(session, query.order_by(dependency.id).limit(1), budget)
    if link is None:
        node.complete = True
        return None
    if scan.dependencies_seen >= 100000:
        return "restricted" if scan.purpose in ("expiry", "report_expiry") else "pending"
    physical = next(
        (
            (kind, identifier)
            for kind, identifier in (
                ("price", link.price_snapshot_id),
                ("fx", link.fx_snapshot_id),
                ("corporate_action", link.action_snapshot_id),
                ("benchmark", link.benchmark_snapshot_id),
            )
            if identifier is not None
        ),
        None,
    )
    if physical is not None:
        kind, identifier = physical
        if scan.purpose == "source_match" and (kind, identifier) == (
            scan.target_kind,
            scan.target_id,
        ):
            return "match"
        if scan.purpose in ("expiry", "report_expiry") and _physical(
            session, scan, kind, identifier, at, budget
        ):
            return "restricted"
    elif link.registered_evidence_id is not None:
        evidence = _row(
            session,
            select(hm.HistoricalEvidenceModel.id, hm.HistoricalEvidenceModel.sealed).where(
                hm.HistoricalEvidenceModel.owner_id == root.owner_id,
                hm.HistoricalEvidenceModel.id == link.registered_evidence_id,
            ),
            budget,
        )
        if evidence is None or not evidence.sealed:
            return "restricted" if scan.purpose in ("expiry", "report_expiry") else "pending"
        _add_node(session, scan, link.registered_evidence_id, True, budget)
    elif scan.purpose in ("expiry", "report_expiry") and (
        link.license_version_id is not None or link.classification_id is not None
    ):
        original = scan.history_created_at
        license_id = link.license_version_id
        if link.classification_id is not None:
            classification = _row(
                session,
                select(
                    hm.HistoricalClassificationModel.license_version_id,
                    hm.HistoricalClassificationModel.created_at,
                ).where(
                    hm.HistoricalClassificationModel.owner_id == root.owner_id,
                    hm.HistoricalClassificationModel.id == link.classification_id,
                ),
                budget,
            )
            if classification is None or classification.license_version_id is None:
                _restrict(scan, "classification", link.classification_id)
                return "restricted"
            original = (
                min(original, classification.created_at)
                if original is not None
                else classification.created_at
            )
            license_id = classification.license_version_id
        if original is None or license_id is None:
            return "restricted"
        until = _license_until(session, scan, license_id, original, at, budget)
        if until is None or until <= at:
            _restrict(
                scan,
                "classification" if link.classification_id is not None else "license",
                link.classification_id or license_id,
            )
            return "restricted"
    # Other admitted dependencies are immutable unlicensed identities. The original
    # recursive source reader and SQL guards own their full integrity validation.
    node.dependency_cursor = link.id
    scan.dependencies_seen += 1
    return None


def _remember_target(
    session: Session, scan: Scan, matched: bool, budget: SourcePurgeBudget
) -> bool:
    requested = min(33, budget.metadata_limit)
    query = (
        select(Target)
        .where(
            Target.owner_id == scan.owner_id,
            Target.account_id == scan.account_id,
            Target.run_id == scan.run_id,
        )
        .order_by(Target.id)
        .limit(requested)
    )
    if budget.metadata_limit < 3:
        return False
    rows = list(session.scalars(query))
    if not budget.inspect(rows=max(1, len(rows))):
        raise _Yield
    for row in rows:
        if (row.target_kind, row.target_id) == (scan.target_kind, scan.target_id):
            if row.matched != matched:
                raise RuntimeError("Immutable projection source membership changed.")
            return True
    if len(rows) == requested and requested < 33:
        # A short allowance cannot establish that the bounded cache is complete.
        return False
    if len(rows) > 32:
        raise RuntimeError("Projection target cache exceeds its bound.")
    if len(rows) == 32:
        table = cast(Table, Target.__table__)
        if not purge_payload_rows(
            session,
            table,
            (table.c.owner_id == scan.owner_id)
            & (table.c.account_id == scan.account_id)
            & (table.c.id == rows[0].id),
            payload_columns=_TARGET_COLUMNS,
            delete_rows=True,
            budget=budget,
        ).complete:
            return False
    _charge(budget)
    session.add(
        Target(
            id=uuid4(),
            owner_id=scan.owner_id,
            account_id=scan.account_id,
            run_id=scan.run_id,
            target_kind=scan.target_kind,
            target_id=scan.target_id,
            matched=matched,
            created_at=scan.evaluated_at,
        )
    )
    session.flush()
    return True


def _scan_projection_sources(
    session: Session,
    root: PremiumRunModel,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    target: tuple[SourceKind, UUID] | None = None,
    report: bool = False,
) -> ScanResult:
    """Caller holds the exact owner/root locks for the transaction.

    An epoch change, backwards clock or future policy activation restarts the
    normalized frontier. A reached cached deadline is restrictive only while the
    policy epoch/activation remain unchanged. Clean cache reuse therefore cannot
    hide a shorter newly published retention policy or a pending source marker.
    """
    if target is not None and target[0] not in (*_PHYSICAL, "historical"):
        raise ValueError("An exact supported projection parent kind is required.")
    if type(report) is not bool or (report and target is not None):
        raise ValueError("Report expiry requires its own untargeted source traversal.")
    purpose = "report_expiry" if report else "expiry" if target is None else "source_match"
    try:
        if budget.metadata_limit < 6:
            return "pending"
        if target is not None:
            cached = _scalar(
                session,
                select(Target).where(
                    Target.owner_id == root.owner_id,
                    Target.account_id == root.account_id,
                    Target.run_id == root.id,
                    Target.target_kind == target[0],
                    Target.target_id == target[1],
                ),
                budget,
            )
            if cached is not None:
                return "match" if cached.matched else "no_match"
        epoch = _epoch(session, root.owner_id, budget)
        scan = _scalar(
            session,
            select(Scan).where(
                Scan.owner_id == root.owner_id,
                Scan.account_id == root.account_id,
                Scan.run_id == root.id,
                Scan.purpose == purpose,
            ),
            budget,
        )
        target_kind, target_id = target if target is not None else (None, None)
        if scan is None:
            scan = Scan(
                id=uuid4(),
                owner_id=root.owner_id,
                account_id=root.account_id,
                run_id=root.id,
                purpose=purpose,
                target_kind=target_kind,
                target_id=target_id,
                phase="restart",
                policy_epoch=epoch,
                evaluated_at=at,
                next_policy_at=None,
                earliest_deadline=None,
                source_cursor=None,
                current_source_id=None,
                history_input_id=None,
                history_created_at=None,
                source_count=0,
                dependencies_seen=0,
                node_count=0,
                created_at=at,
            )
            _charge(budget)
            session.add(scan)
            session.flush()
        if purpose == "source_match" and scan.phase in ("clean", "matched"):
            if not _remember_target(session, scan, scan.phase == "matched", budget):
                return "pending"
            if (scan.target_kind, scan.target_id) == (target_kind, target_id):
                return "match" if scan.phase == "matched" else "no_match"
        requested_target = (target_kind, target_id)
        if purpose == "source_match" and scan.phase not in ("clean", "matched", "restart"):
            # A different caller helps finish the existing graph; it never discards
            # another target's partial frontier or accepts that target's answer.
            target_kind, target_id = scan.target_kind, scan.target_id
        invalidate = (
            scan.phase == "restart"
            or (scan.target_kind, scan.target_id) != (target_kind, target_id)
            or (
                purpose in ("expiry", "report_expiry")
                and (
                    scan.policy_epoch != epoch
                    or at < scan.evaluated_at
                    or (scan.next_policy_at is not None and scan.next_policy_at <= at)
                )
            )
        )
        if invalidate:
            scan.target_kind, scan.target_id = target_kind, target_id
            if not _reset(session, scan, epoch, at, budget):
                session.flush()
                return "pending"
        if (
            purpose in ("expiry", "report_expiry")
            and scan.earliest_deadline is not None
            and scan.earliest_deadline <= at
        ):
            if not report:
                return "restricted"
            # A reached aggregate deadline does not identify a concrete source.
            # Resume a fresh bounded traversal to obtain a verifiable witness.
            if not _reset(session, scan, epoch, at, budget):
                session.flush()
                return "pending"
        if scan.phase == "clean":
            return "clean" if purpose in ("expiry", "report_expiry") else "no_match"
        # Each closed source/dependency step performs <=12 one-row lookups. Reserve
        # enough headroom so a very small allowance yields without partial decisions.
        while budget.metadata_limit >= 20:
            _charge(budget)  # reserve continuation update before any bounded deletion
            _charge(budget)  # reserve current-node checkpoint/update
            if scan.phase == "source":
                result = _source(session, root, scan, at, budget)
            elif scan.phase == "walk":
                result = _walk(session, root, scan, at, budget)
            elif scan.phase == "clear":
                if not _clear_frontier(session, scan, budget):
                    session.flush()
                    return "pending"
                scan.source_cursor = scan.current_source_id
                scan.source_count += 1
                scan.current_source_id = scan.history_input_id = None
                scan.history_created_at = None
                scan.dependencies_seen = scan.node_count = 0
                scan.phase = "source"
                result = None
            else:
                raise RuntimeError("Unknown projection retention scan phase.")
            session.flush()
            if result is not None:
                if result == "pending":
                    return "pending"
                if purpose == "source_match":
                    scan.phase = "matched" if result == "match" else "clean"
                    session.flush()
                    if not _remember_target(session, scan, result == "match", budget):
                        return "pending"
                    if (scan.target_kind, scan.target_id) != requested_target:
                        return "pending"
                return result
        session.flush()
        return "pending"
    except _Yield:
        session.flush()
        return "pending"


def scan_projection_sources(
    session: Session,
    root: PremiumRunModel,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    target: tuple[SourceKind, UUID] | None = None,
    report: bool = False,
) -> ScanResult:
    # Only explicit, precharged checkpoints flush. Intermediate metadata lookups
    # must not repeatedly flush a dirty scan header behind the allowance.
    with session.no_autoflush:
        return _scan_projection_sources(
            session, root, at=at, budget=budget, target=target, report=report
        )
