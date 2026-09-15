"""Resumable closed source metadata checks; no saved financial payload is selected."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .premium_retention_models import PremiumRetentionScanModel as Scan
from .source_retention import SourcePurgeBudget

ScanFamily = Literal["risk", "scenario", "sensitivity"]
ScanOutcome = Literal["clean", "pending", "deferred", "restricted"]


@dataclass(frozen=True)
class PremiumScanInput:
    owner_id: UUID
    subject_id: UUID
    family: ScanFamily
    created_at: datetime
    expires_at: datetime


def _one(session: Session, sql: str, parameters: dict[str, Any], budget: SourcePurgeBudget) -> Any:
    if not budget.inspect(rows=1):
        raise RuntimeError("Premium source probe exceeded its preflight allowance.")
    return session.execute(text(sql), parameters).first()


def _remember(slot: Scan, deadline: datetime | None) -> None:
    if deadline is not None:
        slot.earliest_deadline = (
            deadline if slot.earliest_deadline is None else min(slot.earliest_deadline, deadline)
        )


def _license(
    session: Session,
    slot: Scan,
    provider: UUID,
    identifier: UUID,
    origin: datetime,
    at: datetime,
    budget: SourcePurgeBudget,
) -> bool:
    values = {"owner": slot.owner_id, "provider": provider, "license": identifier, "at": at}
    pinned = _one(
        session,
        "SELECT id,effective_at,store_permission,display_permission,retention_days "
        "FROM provider_license_versions WHERE owner_id=:owner AND "
        "provider_id=:provider AND id=:license",
        values,
        budget,
    )
    current = _one(
        session,
        "SELECT id,effective_at,store_permission,display_permission,retention_days "
        "FROM provider_license_versions WHERE owner_id=:owner AND "
        "provider_id=:provider AND effective_at<=:at ORDER BY "
        "effective_at DESC,version_number DESC,id DESC LIMIT 1",
        values,
        budget,
    )
    for policy in (pinned, current):
        if (
            policy is None
            or policy.effective_at > at
            or policy.store_permission != "allowed"
            or policy.display_permission != "allowed"
            or policy.retention_days is None
        ):
            return True
        deadline = origin + timedelta(days=policy.retention_days)
        _remember(slot, deadline)
        if deadline <= at:
            return True
    return False


def _slot(
    session: Session, value: PremiumScanInput, at: datetime, budget: SourcePurgeBudget
) -> Scan | Literal["deferred"] | None:
    if budget.metadata_limit < 8:
        return None
    budget.inspect(rows=1)
    slot = session.scalar(
        select(Scan)
        .where(Scan.owner_id == value.owner_id, Scan.family == value.family)
        .with_for_update()
    )
    marker_table = (
        "scenario_sensitivity_retention"
        if value.family == "sensitivity"
        else "premium_retention_events"
    )
    marker_parent = "version_id" if value.family == "sensitivity" else "run_id"
    if slot is not None and slot.subject_id != value.subject_id and slot.phase != 9:
        prior = _one(
            session,
            f"SELECT id FROM {marker_table} WHERE owner_id=:owner AND {marker_parent}=:subject",  # noqa: S608 - closed internal identifiers; caller values stay bound.
            {"owner": value.owner_id, "subject": slot.subject_id},
            budget,
        )
        if prior is None:
            return "deferred"
    epoch_row = _one(
        session,
        "SELECT epoch FROM projection_retention_epochs WHERE owner_id=:owner",
        {"owner": value.owner_id},
        budget,
    )
    epoch = 0 if epoch_row is None else epoch_row.epoch
    reset = (
        slot is None
        or slot.subject_id != value.subject_id
        or slot.phase == 9
        or slot.policy_epoch != epoch
        or at < slot.evaluated_at
        or (slot.earliest_deadline is not None and slot.earliest_deadline <= at)
        or (slot.next_policy_at is not None and slot.next_policy_at <= at)
    )
    if not reset:
        return slot
    next_policy = _one(
        session,
        "SELECT effective_at FROM provider_license_versions WHERE "
        "owner_id=:owner AND effective_at>:at ORDER BY effective_at "
        "LIMIT 1",
        {"owner": value.owner_id, "at": at},
        budget,
    )
    if not budget.inspect(rows=3):
        return None
    if slot is None:
        slot = Scan(owner_id=value.owner_id, family=value.family)
        session.add(slot)
    slot.subject_id, slot.phase = value.subject_id, 3 if value.family == "sensitivity" else 1
    slot.cursor, slot.child_cursor = None, None
    slot.version_id = value.subject_id if value.family == "sensitivity" else None
    slot.policy_epoch, slot.evaluated_at = epoch, at
    slot.earliest_deadline = value.expires_at
    slot.next_policy_at = None if next_policy is None else next_policy.effective_at
    session.flush()
    return slot


def scan_premium_restriction(
    session: Session, value: PremiumScanInput, *, at: datetime, budget: SourcePurgeBudget
) -> ScanOutcome:
    # A permanent marker is authoritative for resumption. It never authorizes a
    # sibling root, and every unmarked source is checked from original metadata.
    if value.expires_at <= at:
        return "restricted"
    if budget.metadata_limit < 6:
        return "pending"
    parameters = {"owner": value.owner_id, "subject": value.subject_id, "at": at}
    marker_table = (
        "scenario_sensitivity_retention"
        if value.family == "sensitivity"
        else "premium_retention_events"
    )
    marker_parent = "version_id" if value.family == "sensitivity" else "run_id"
    if (
        _one(
            session,
            f"SELECT id FROM {marker_table} WHERE owner_id=:owner AND {marker_parent}=:subject",  # noqa: S608 - closed internal identifiers; caller values stay bound.
            parameters,
            budget,
        )
        is not None
    ):
        return "restricted"
    if value.family != "sensitivity":
        table = "risk_runs" if value.family == "risk" else "scenario_runs"
        parent = _one(
            session,
            f"SELECT historical_input_id,xray_run_id FROM {table} "  # noqa: S608 - closed internal table.
            "WHERE owner_id=:owner AND id=:subject",
            parameters,
            budget,
        )
        if parent is None:
            raise RuntimeError("Premium retained input metadata is absent.")
        if parent.historical_input_id is not None:
            historical = _one(
                session,
                "SELECT id FROM historical_retention_events WHERE "
                "owner_id=:owner AND input_id=:parent",
                {**parameters, "parent": parent.historical_input_id},
                budget,
            )
            if historical is not None:
                return "restricted"
        if parent.xray_run_id is not None:
            xray = _one(
                session,
                "SELECT input_id FROM xray_runs WHERE owner_id=:owner AND id=:parent",
                {**parameters, "parent": parent.xray_run_id},
                budget,
            )
            if xray is None:
                raise RuntimeError("Premium retained X-ray metadata is absent.")
            if (
                _one(
                    session,
                    "SELECT id FROM xray_retention_events WHERE owner_id=:owner "
                    "AND input_id=:parent",
                    {**parameters, "parent": xray.input_id},
                    budget,
                )
                is not None
            ):
                return "restricted"
    slot = _slot(session, value, at, budget)
    if slot is None:
        return "pending"
    if slot == "deferred":
        return "deferred"
    while budget.rows_inspected >= 8:
        # Reserve a checkpoint and the largest fixed phase before its metadata.
        if not budget.inspect(rows=1):
            return "pending"
        params = {"owner": value.owner_id, "subject": value.subject_id, "version": slot.version_id}
        restricted = False
        if slot.phase in (3, 4, 5):
            # Operational continuation cannot invent authority: bind the active
            # source to this exact original root before any restriction witness.
            if value.family == "sensitivity":
                if slot.version_id != value.subject_id:
                    raise RuntimeError("Sensitivity scan source binding is invalid.")
            elif value.family == "scenario":
                selected = _one(
                    session,
                    "SELECT id FROM scenario_run_sensitivity_versions WHERE "
                    "owner_id=:owner AND run_id=:subject AND "
                    "version_id=:version",
                    params,
                    budget,
                )
                if selected is None:
                    raise RuntimeError("Scenario scan source is not an original retained version.")
            else:
                raise RuntimeError("Risk scan cannot acquire a sensitivity source.")
        if slot.phase == 1:
            query = (
                "SELECT id,provider_id,license_version_id FROM "
                "premium_run_licenses WHERE owner_id=:owner AND "
                "run_id=:subject "
            )
            if slot.cursor is not None:
                query += "AND id>:cursor "
                params["cursor"] = slot.cursor
            row = _one(session, query + "ORDER BY id LIMIT 1", params, budget)
            if row is None:
                slot.phase, slot.cursor = (9 if value.family == "risk" else 2), None
            else:
                restricted = _license(
                    session,
                    slot,
                    row.provider_id,
                    row.license_version_id,
                    value.created_at,
                    at,
                    budget,
                )
                slot.cursor = row.id
        elif slot.phase == 2:
            query = (
                "SELECT id,version_id FROM "
                "scenario_run_sensitivity_versions WHERE owner_id=:owner "
                "AND run_id=:subject "
            )
            if slot.cursor is not None:
                query += "AND id>:cursor "
                params["cursor"] = slot.cursor
            row = _one(session, query + "ORDER BY id LIMIT 1", params, budget)
            if row is None:
                slot.phase = 9
            else:
                slot.cursor, slot.version_id, slot.child_cursor, slot.phase = (
                    row.id,
                    row.version_id,
                    None,
                    3,
                )
        elif slot.phase == 3:
            row = _one(
                session,
                "SELECT "
                "id,provider_id,license_version_id,created_at,expires_at "
                "FROM scenario_sensitivity_versions WHERE owner_id=:owner "
                "AND id=:version",
                params,
                budget,
            )
            if row is None:
                raise RuntimeError("Premium sensitivity metadata is absent.")
            _remember(slot, row.expires_at)
            marked = _one(
                session,
                "SELECT id FROM scenario_sensitivity_retention WHERE "
                "owner_id=:owner AND version_id=:version",
                params,
                budget,
            )
            restricted = (
                row.expires_at <= at
                or marked is not None
                or _license(
                    session,
                    slot,
                    row.provider_id,
                    row.license_version_id,
                    row.created_at,
                    at,
                    budget,
                )
            )
            slot.phase, slot.child_cursor = 4, None
        elif slot.phase in (4, 5):
            is_observation = slot.phase == 4
            table = (
                "scenario_sensitivity_observations"
                if is_observation
                else "scenario_sensitivity_evidence_links"
            )
            columns = (
                "id,provider_id,license_version_id,created_at"
                if is_observation
                else "id,evidence_id"
            )
            query = f"SELECT {columns} FROM {table} WHERE owner_id=:owner AND version_id=:version "  # noqa: S608 - closed internal identifiers; caller values stay bound.
            if slot.child_cursor is not None:
                query += "AND id>:cursor "
                params["cursor"] = slot.child_cursor
            row = _one(session, query + "ORDER BY id LIMIT 1", params, budget)
            if row is None:
                slot.phase = 5 if is_observation else 9 if value.family == "sensitivity" else 2
                slot.child_cursor = None
            else:
                source = (
                    row
                    if is_observation
                    else _one(
                        session,
                        "SELECT provider_id,license_version_id,created_at FROM "
                        "scenario_sensitivity_evidence WHERE owner_id=:owner AND "
                        "id=:evidence",
                        {**params, "evidence": row.evidence_id},
                        budget,
                    )
                )
                if source is None:
                    raise RuntimeError("Premium evidence source metadata is absent.")
                restricted = _license(
                    session,
                    slot,
                    source.provider_id,
                    source.license_version_id,
                    source.created_at,
                    at,
                    budget,
                )
                slot.child_cursor = row.id
        elif slot.phase == 9:
            return "clean"
        else:
            raise RuntimeError("Invalid premium source scan phase.")
        if restricted:
            slot.phase = 9
        session.flush()
        if restricted:
            return "restricted"
        if slot.phase == 9:
            return "clean"
    return "pending"
