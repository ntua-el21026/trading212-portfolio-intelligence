"""Resume finite metadata phases; current fixed SQL witnesses decide restriction."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .legacy_report_retention_models import LegacyReportRetentionScanModel as Scan
from .projection_retention_models import ProjectionRetentionEpochModel as Epoch
from .report_physical_retention import (
    LEGACY_REPORT_PARENT_INSPECTIONS,
    LEGACY_REPORT_POINT_INSPECTIONS,
    LEGACY_REPORT_ROOT_INSPECTIONS,
    LegacyReportWitness,
    LegacyReportWitnessKind,
)
from .source_retention import SourcePurgeBudget

ScanOutcome = Literal["clean", "pending", "deferred"] | LegacyReportWitness


@dataclass(frozen=True)
class LegacyReportScanInput:
    owner_id: UUID
    account_id: UUID
    input_id: UUID
    run_id: UUID
    contract_version: Literal[2, 3]
    kind: Literal["risk", "scenario"]


@dataclass(frozen=True)
class RestrictionProbe:
    restricted: bool
    deadline: datetime | None


def probe(
    session: Session,
    value: LegacyReportScanInput,
    kind: LegacyReportWitnessKind,
    subject: UUID,
    at: datetime,
    budget: SourcePurgeBudget,
) -> RestrictionProbe | None:
    cost = (
        LEGACY_REPORT_ROOT_INSPECTIONS
        if kind == "root"
        else LEGACY_REPORT_PARENT_INSPECTIONS
        if kind == "parents"
        else LEGACY_REPORT_POINT_INSPECTIONS
    )
    if budget.rows_inspected < cost or not budget.inspect(rows=cost):
        return None
    row = session.execute(
        text(
            "SELECT restricted,next_deadline FROM "
            "legacy_report_retention_probe(:owner,:input,:kind,:subject,:at)"
        ),
        {
            "owner": value.owner_id,
            "input": value.input_id,
            "kind": kind,
            "subject": subject,
            "at": at,
        },
    ).one()
    if type(row.restricted) is not bool or (
        row.next_deadline is not None and not isinstance(row.next_deadline, datetime)
    ):
        raise RuntimeError("Invalid legacy report source probe result.")
    return RestrictionProbe(row.restricted, row.next_deadline)


def _slot(
    session: Session,
    value: LegacyReportScanInput,
    at: datetime,
    budget: SourcePurgeBudget,
) -> Scan | Literal["deferred"] | None:
    if budget.metadata_limit < 8:
        return None
    budget.inspect(rows=1)
    slot = session.scalar(select(Scan).where(Scan.owner_id == value.owner_id).with_for_update())
    # Never evict an interrupted report when a busy owner was skipped by the root
    # sweep. Other reports defer until that report is revisited and completed.
    if slot is not None and slot.input_id != value.input_id:
        budget.inspect(rows=1)
        pending = session.scalar(
            text(
                "SELECT id FROM report_input_premium_dependencies WHERE owner_id=:owner "
                "AND input_id=:input AND copy_pending"
            ),
            {"owner": value.owner_id, "input": slot.input_id},
        )
        if slot.phase != 9 and pending is not None:
            return "deferred"
    budget.inspect(rows=1)
    epoch = session.scalar(select(Epoch.epoch).where(Epoch.owner_id == value.owner_id)) or 0
    invalid = (
        slot is None
        or slot.input_id != value.input_id
        or slot.policy_epoch != epoch
        or at < slot.evaluated_at
        or (slot.next_policy_at is not None and slot.next_policy_at <= at)
        or (slot.earliest_deadline is not None and slot.earliest_deadline <= at)
    )
    if not invalid:
        return slot
    budget.inspect(rows=1)
    history = session.scalar(
        text(
            "SELECT historical_input_id FROM risk_runs WHERE :kind='risk' AND "
            "owner_id=:owner AND account_id=:account AND id=:run UNION ALL SELECT "
            "historical_input_id FROM scenario_runs WHERE :kind='scenario' AND "
            "owner_id=:owner AND account_id=:account AND id=:run"
        ),
        {
            "kind": value.kind,
            "owner": value.owner_id,
            "account": value.account_id,
            "run": value.run_id,
        },
    )
    budget.inspect(rows=1)
    activation = session.scalar(
        text(
            "SELECT effective_at FROM provider_license_versions WHERE owner_id=:owner AND"
            " effective_at>:at ORDER BY effective_at LIMIT 1"
        ),
        {"owner": value.owner_id, "at": at},
    )
    budget.inspect(rows=3)
    if slot is None:
        slot = Scan(owner_id=value.owner_id)
        session.add(slot)
    slot.account_id, slot.input_id, slot.run_id = value.account_id, value.input_id, value.run_id
    slot.historical_input_id = history
    slot.phase, slot.cursor, slot.evidence_id, slot.evidence_cursor = 1, None, None, None
    slot.policy_epoch, slot.evaluated_at = epoch, at
    slot.earliest_deadline, slot.next_policy_at = None, activation
    session.flush()
    return slot


# Only these explicit trusted phase definitions can name SQL tables/columns.
_PHASES: dict[int, tuple[LegacyReportWitnessKind, str, str]] = {
    1: ("physical", "report_input_dependencies", "input_id"),
    2: ("report_license", "report_input_licenses", "input_id"),
    3: ("premium_license", "premium_run_licenses", "run_id"),
    6: ("version", "scenario_run_sensitivity_versions", "run_id"),
    7: ("observation", "scenario_run_sensitivity_observations", "run_id"),
    8: ("evidence", "scenario_run_sensitivity_evidence", "run_id"),
}


def _remember(slot: Scan, deadline: datetime | None) -> None:
    if deadline is not None:
        slot.earliest_deadline = (
            deadline if slot.earliest_deadline is None else min(slot.earliest_deadline, deadline)
        )


def scan_legacy_report(
    session: Session,
    value: LegacyReportScanInput,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
) -> ScanOutcome:
    for kind in ("root", "parents") if value.contract_version == 3 else ("root",):
        current = probe(session, value, kind, value.run_id, at, budget)
        if current is None:
            return "pending"
        if current.restricted:
            return (kind, value.run_id)
    slot = _slot(session, value, at, budget)
    if slot is None:
        return "pending"
    if slot == "deferred":
        return "deferred"
    if slot.phase == 9:
        # A completed slot is not a permanent clean authorization cache. Each
        # root sweep revisits it with fresh current metadata and finite phases.
        if not budget.inspect(rows=1):
            return "pending"
        slot.phase, slot.cursor = 1, None
    while budget.rows_inspected >= LEGACY_REPORT_POINT_INSPECTIONS + 2:
        # One checkpoint mutation is reserved before the selected witness query.
        if not budget.inspect(rows=1):
            return "pending"
        if slot.phase == 4:
            slot.phase, slot.cursor = (5 if value.contract_version == 3 else 9), None
            session.flush()
            continue
        if slot.phase in (6, 7, 8) and value.kind != "scenario":
            slot.phase, slot.cursor = 9, None
            session.flush()
            continue
        if slot.phase == 9:
            return "clean"
        budget.inspect(rows=1)
        if slot.phase == 5:
            if slot.historical_input_id is None:
                slot.phase, slot.cursor = 6, None
                session.flush()
                continue
            if slot.evidence_id is not None:
                row = session.execute(
                    text(
                        (  # noqa: S608 - closed internal selectors; external values are bound.
                            "SELECT id,registered_evidence_id FROM historical_dependencies "
                            "WHERE owner_id=:owner AND evidence_id=:parent "
                        )
                        + ("AND id>:cursor " if slot.evidence_cursor is not None else "")
                        + "ORDER BY id LIMIT 1"
                    ),
                    {
                        "owner": value.owner_id,
                        "parent": slot.evidence_id,
                        "cursor": slot.evidence_cursor,
                    },
                ).first()
                if row is None:
                    slot.evidence_id, slot.evidence_cursor = None, None
                    session.flush()
                    continue
                if row.registered_evidence_id is not None:
                    raise RuntimeError("Nested historical evidence cannot enter report cleanup.")
            else:
                row = session.execute(
                    text(
                        (  # noqa: S608 - closed internal selectors; external values are bound.
                            "SELECT id,registered_evidence_id FROM historical_dependencies "
                            "WHERE owner_id=:owner AND input_id=:parent "
                        )
                        + ("AND id>:cursor " if slot.cursor is not None else "")
                        + "ORDER BY id LIMIT 1"
                    ),
                    {
                        "owner": value.owner_id,
                        "parent": slot.historical_input_id,
                        "cursor": slot.cursor,
                    },
                ).first()
                if row is None:
                    slot.phase, slot.cursor = 6, None
                    session.flush()
                    continue
            selected_kind: LegacyReportWitnessKind = "history"
        else:
            selected_kind, table, parent = _PHASES[slot.phase]
            row = session.execute(
                text(
                    f"SELECT id FROM {table} WHERE owner_id=:owner AND {parent}=:parent "  # noqa: S608 - closed internal selectors; external values are bound.
                    + ("AND id>:cursor " if slot.cursor is not None else "")
                    + "ORDER BY id LIMIT 1"
                ),
                {
                    "owner": value.owner_id,
                    "parent": value.input_id if parent == "input_id" else value.run_id,
                    "cursor": slot.cursor,
                },
            ).first()
            if row is None:
                slot.phase, slot.cursor = slot.phase + 1, None
                session.flush()
                continue
        current = probe(session, value, selected_kind, row.id, at, budget)
        if current is None:
            return "pending"
        if current.restricted:
            return (selected_kind, row.id)
        _remember(slot, current.deadline)
        if slot.phase == 5 and slot.evidence_id is not None:
            slot.evidence_cursor = row.id
        else:
            slot.cursor = row.id
            if slot.phase == 5 and row.registered_evidence_id is not None:
                slot.evidence_id, slot.evidence_cursor = row.registered_evidence_id, None
        session.flush()
    return "clean" if slot.phase == 9 else "pending"
