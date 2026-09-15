"""Bounded sensitivity cleanup with independent logical and physical evidence flags.

A marked version releases its ownership before shared evidence is considered.
Physical absence is then confirmed for each link separately. A permitted sibling
keeps the payload and leaves the marked version truthfully pending.
"""

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Table, select, update
from sqlalchemy.orm import Session

from .premium_retention_costs import (
    SCENARIO_LINK_ROWS,
    SCENARIO_SOURCE_COMPLETE_ROWS,
    SCENARIO_SOURCE_MARKER_ROWS,
)
from .premium_retention_runtime import charge, finish_sweep, lock_owner, open_sweep
from .premium_retention_scan import PremiumScanInput, scan_premium_restriction
from .scenario_retention import purge_scenario_sensitivity_copies
from .scenario_source_models import (
    ScenarioSensitivityEvidenceLinkModel as Link,
)
from .scenario_source_models import (
    ScenarioSensitivityEvidenceModel as Evidence,
)
from .scenario_source_models import (
    ScenarioSensitivityEvidencePayloadModel as EvidencePayload,
)
from .scenario_source_models import (
    ScenarioSensitivityObservationModel as Observation,
)
from .scenario_source_models import (
    ScenarioSensitivityObservationPayloadModel as ObservationPayload,
)
from .scenario_source_models import (
    ScenarioSensitivityRetentionModel as Marker,
)
from .scenario_source_models import (
    ScenarioSensitivityVersionModel as Version,
)
from .scenario_source_models import (
    ScenarioSensitivityVersionPayloadModel as VersionPayload,
)
from .source_retention import SourcePurgeBudget
from .source_retention_sql import purge_payload_rows

VERSION_PAYLOAD_COLUMNS = (
    "driver_kind",
    "shock_unit",
    "equivalence_kind",
    "equivalence_rate_id",
    "equivalence_factor_id",
    "equivalence_currency",
    "equivalence_selector_kind",
    "equivalence_instrument_id",
    "equivalence_entity_id",
    "equivalence_taxonomy_id",
    "equivalence_taxonomy_version",
    "equivalence_bucket_key",
    "equivalence_reason",
    "effective_at",
    "first_known_at",
    "valid_from",
    "valid_until",
    "revision",
    "adapter_id",
    "adapter_version",
    "availability",
    "quality",
    "canonical_payload",
)
OBSERVATION_PAYLOAD_COLUMNS = (
    "subject_kind",
    "instrument_id",
    "entity_id",
    "coefficient",
    "shock_unit",
    "response_unit",
    "response_basis",
    "response_currency",
    "effective_at",
    "first_known_at",
    "valid_from",
    "valid_until",
    "revision",
    "state",
    "quality",
    "confidence",
    "reason",
    "canonical_payload",
)
EVIDENCE_PAYLOAD_COLUMNS = (
    "effective_at",
    "first_known_at",
    "adapter_id",
    "adapter_version",
    "transformation",
    "canonical_payload",
)


def _release_links(
    session: Session, owner: UUID, version_id: UUID, budget: SourcePurgeBudget
) -> bool:
    while budget.metadata_limit >= 1 + SCENARIO_LINK_ROWS:
        count = min(512 // SCENARIO_LINK_ROWS, budget.metadata_limit // (1 + SCENARIO_LINK_ROWS))
        identifiers = tuple(
            session.scalars(
                select(Link.id)
                .where(
                    Link.owner_id == owner,
                    Link.version_id == version_id,
                    Link.copy_pending.is_(True),
                )
                .order_by(Link.id)
                .limit(count)
            )
        )
        charge(budget, max(1, len(identifiers)))
        if not identifiers:
            return True
        charge(budget, len(identifiers) * SCENARIO_LINK_ROWS)
        session.execute(
            update(Link)
            .where(
                Link.owner_id == owner,
                Link.version_id == version_id,
                Link.id.in_(identifiers),
                Link.copy_pending.is_(True),
            )
            .values(copy_pending=False)
        )
        session.flush()
    return False


def _purge_observations(
    session: Session, owner: UUID, version_id: UUID, budget: SourcePurgeBudget
) -> bool:
    payload = cast(Table, ObservationPayload.__table__)
    while budget.metadata_limit >= 27:
        charge(budget, 1)
        identifier = session.scalar(
            select(Observation.id)
            .where(
                Observation.owner_id == owner,
                Observation.version_id == version_id,
                Observation.payload_present.is_(True),
            )
            .order_by(Observation.id)
            .limit(1)
        )
        if identifier is None:
            return True
        if not purge_payload_rows(
            session,
            payload,
            (payload.c.owner_id == owner) & (payload.c.observation_id == identifier),
            payload_columns=OBSERVATION_PAYLOAD_COLUMNS,
            delete_rows=True,
            budget=budget,
        ).complete:
            return False
    return False


def _purge_evidence(
    session: Session, owner: UUID, version_id: UUID, marker: Marker, budget: SourcePurgeBudget
) -> bool:
    payload = cast(Table, EvidencePayload.__table__)
    while budget.metadata_limit >= 5 + SCENARIO_LINK_ROWS + 24:
        query = select(Link.id, Link.evidence_id).where(
            Link.owner_id == owner, Link.version_id == version_id, Link.payload_pending.is_(True)
        )
        if marker.evidence_after_id is not None:
            query = query.where(Link.id > marker.evidence_after_id)
        charge(budget, 1)
        link = session.execute(query.order_by(Link.id).limit(1)).first()
        if link is None:
            # A blocked earlier sibling remains in the indexed pending set. The
            # next invocation starts another charged pass; it never skips proof.
            charge(budget, 3)
            marker.evidence_after_id = None
            session.flush()
            charge(budget, 1)
            return (
                session.scalar(
                    select(Link.id)
                    .where(
                        Link.owner_id == owner,
                        Link.version_id == version_id,
                        Link.payload_pending.is_(True),
                    )
                    .limit(1)
                )
                is None
            )
        charge(budget, 3)  # Cursor write + original version/marker point guards.
        charge(budget, 1)
        header = session.scalar(
            select(Evidence.id)
            .where(Evidence.owner_id == owner, Evidence.id == link.evidence_id)
            .with_for_update(skip_locked=True)
        )
        if header is None:
            marker.evidence_after_id = link.id
            session.flush()
            continue
        charge(budget, 1)
        blocked = (
            session.scalar(
                select(Link.id)
                .where(
                    Link.owner_id == owner,
                    Link.evidence_id == link.evidence_id,
                    Link.copy_pending.is_(True),
                )
                .limit(1)
            )
            is not None
        )
        if not blocked:
            cleared = purge_payload_rows(
                session,
                payload,
                (payload.c.owner_id == owner) & (payload.c.evidence_id == link.evidence_id),
                payload_columns=EVIDENCE_PAYLOAD_COLUMNS,
                delete_rows=True,
                budget=budget,
            )
            if not cleared.complete:
                return False
            if not budget.inspect(rows=SCENARIO_LINK_ROWS):
                return False
            # SQL independently verifies exact payload absence before this flag.
            session.execute(
                update(Link)
                .where(Link.owner_id == owner, Link.id == link.id)
                .values(payload_pending=False)
            )
        marker.evidence_after_id = link.id
        session.flush()
    return False


def _purge_version(
    session: Session, version: Version, *, at: datetime, budget: SourcePurgeBudget, erase: bool
) -> bool:
    if not budget.enter_capture("scenario", version.id) or budget.metadata_limit < 2:
        return False
    charge(budget, 1)
    marker = session.scalar(
        select(Marker).where(Marker.owner_id == version.owner_id, Marker.version_id == version.id)
    )
    if marker is not None and marker.completed_at is not None:
        return True
    if marker is None:
        if not budget.inspect(rows=SCENARIO_SOURCE_MARKER_ROWS):
            return False
        marker = Marker(
            id=uuid4(),
            owner_id=version.owner_id,
            version_id=version.id,
            created_at=at,
            completed_at=None,
            reason="owner_erasure"
            if erase
            else "source_expired"
            if version.expires_at <= at
            else "source_restricted",
        )
        session.add(marker)
        session.flush()
    if not purge_scenario_sensitivity_copies(
        session, version.owner_id, version.id, at=at, budget=budget
    ):
        return False
    if not _release_links(session, version.owner_id, version.id, budget):
        return False
    if not _purge_observations(session, version.owner_id, version.id, budget):
        return False
    table = cast(Table, VersionPayload.__table__)
    if not purge_payload_rows(
        session,
        table,
        (table.c.owner_id == version.owner_id) & (table.c.version_id == version.id),
        payload_columns=VERSION_PAYLOAD_COLUMNS,
        delete_rows=True,
        budget=budget,
    ).complete:
        return False
    if not _purge_evidence(session, version.owner_id, version.id, marker, budget):
        return False
    if not budget.inspect(rows=SCENARIO_SOURCE_COMPLETE_ROWS):
        return False
    # SQL tests indexed physical flags, original body, exact retained-run parents,
    # then sets the trigger-owned closed bit. No all-observation/link scan.
    marker.completed_at = at
    session.flush()
    return True


def expire_scenario_sensitivity_payloads(
    session: Session,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    owner: UUID | None = None,
    erase: bool = False,
) -> bool:
    if erase and owner is None:
        raise ValueError("Scenario source erasure requires one explicit owner.")
    sweep = open_sweep(session, "sensitivity", owner, at, budget)
    if sweep is None:
        return False
    while budget.metadata_limit >= 8:
        query = select(Version.id, Version.owner_id).where(
            Version.sealed.is_(True), Version.retention_closed.is_(False)
        )
        if owner is not None:
            query = query.where(Version.owner_id == owner)
        if sweep.after_id is not None:
            query = query.where(Version.id > sweep.after_id)
        charge(budget, 1)
        candidate = session.execute(query.order_by(Version.id).limit(1)).first()
        if candidate is None:
            return finish_sweep(session, sweep, budget)
        charge(budget, 1)  # Progress checkpoint, reserved before source traversal.
        deferred = True
        if lock_owner(session, candidate.owner_id):
            charge(budget, 1)
            version = session.scalar(
                select(Version)
                .where(Version.id == candidate.id, Version.owner_id == candidate.owner_id)
                .with_for_update(skip_locked=True)
            )
            if version is not None:
                charge(budget, 1)  # Reserve deadline metadata before proof.
                outcome = (
                    "restricted"
                    if erase
                    else scan_premium_restriction(
                        session,
                        PremiumScanInput(
                            version.owner_id,
                            version.id,
                            "sensitivity",
                            version.created_at,
                            version.expires_at,
                        ),
                        at=at,
                        budget=budget,
                    )
                )
                if outcome == "restricted":
                    deferred = not _purge_version(
                        session, version, at=at, budget=budget, erase=erase
                    )
                elif outcome == "pending":
                    session.flush()
                    return False
                elif outcome == "clean":
                    from .premium_retention_models import PremiumRetentionScanModel

                    slot = session.get(PremiumRetentionScanModel, (version.owner_id, "sensitivity"))
                    deadline = (
                        version.expires_at
                        if slot is None or slot.earliest_deadline is None
                        else min(version.expires_at, slot.earliest_deadline)
                    )
                    sweep.earliest_deadline = (
                        deadline
                        if sweep.earliest_deadline is None
                        else min(deadline, sweep.earliest_deadline)
                    )
                    deferred = False
        sweep.after_id, sweep.deferred = candidate.id, sweep.deferred or deferred
        session.flush()
    return False
