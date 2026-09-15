"""Bounded licensed sensitivity removal, preserving permanent identity and audit.

A shared evidence payload remains while any linked version is still permitted.
Version completion consequently stays pending; it never claims physical erasure
while another version still retains that evidence. All selection is metadata-only.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import SQLColumnExpression, Table, and_, literal, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from .scenario_models import ScenarioRunSensitivityVersionModel
from .scenario_retention import _charge, _lock_owner, purge_scenario_sensitivity_copies
from .scenario_retention_policy import scenario_run_has_payload, sensitivity_version_restricted
from .scenario_source_models import (
    ScenarioSensitivityEvidenceLinkModel,
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityEvidencePayloadModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityObservationPayloadModel,
    ScenarioSensitivityRetentionModel,
    ScenarioSensitivityVersionModel,
    ScenarioSensitivityVersionPayloadModel,
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


def _complete() -> ColumnElement[bool]:
    return (
        select(ScenarioSensitivityRetentionModel.id)
        .where(
            ScenarioSensitivityRetentionModel.owner_id == ScenarioSensitivityVersionModel.owner_id,
            ScenarioSensitivityRetentionModel.version_id == ScenarioSensitivityVersionModel.id,
            ScenarioSensitivityRetentionModel.completed_at.is_not(None),
        )
        .exists()
    )


def _eligible(at: datetime, *, erase: bool) -> ColumnElement[bool]:
    return and_(
        ScenarioSensitivityVersionModel.sealed.is_(True),
        ~_complete(),
        literal(True) if erase else sensitivity_version_restricted(at),
    )


def _copies_pending(
    owner: SQLColumnExpression[UUID],
    version_id: SQLColumnExpression[UUID],
) -> ColumnElement[bool]:
    used = ScenarioRunSensitivityVersionModel
    return (
        select(used.id)
        .where(
            used.owner_id == owner,
            used.version_id == version_id,
            scenario_run_has_payload(used.owner_id, used.run_id),
        )
        .exists()
    )


def _evidence_blocked() -> ColumnElement[bool]:
    """Correlated with an evidence header; require every immutable linked version."""
    linked = aliased(ScenarioSensitivityEvidenceLinkModel)
    marker = ScenarioSensitivityRetentionModel
    evidence = ScenarioSensitivityEvidenceModel
    marked = (
        select(marker.id)
        .where(
            marker.owner_id == linked.owner_id,
            marker.version_id == linked.version_id,
        )
        .exists()
    )
    return (
        select(linked.id)
        .where(
            linked.owner_id == evidence.owner_id,
            linked.evidence_id == evidence.id,
            or_(~marked, _copies_pending(linked.owner_id, linked.version_id)),
        )
        .exists()
    )


def _purge_evidence(
    session: Session,
    owner: UUID,
    version_id: UUID,
    *,
    budget: SourcePurgeBudget,
) -> None:
    evidence = ScenarioSensitivityEvidenceModel
    link = ScenarioSensitivityEvidenceLinkModel
    payload = cast(Table, ScenarioSensitivityEvidencePayloadModel.__table__)
    selected = (
        select(link.id)
        .where(
            link.owner_id == owner,
            link.version_id == version_id,
            link.evidence_id == evidence.id,
        )
        .exists()
    )
    physical = (
        select(payload.c.id)
        .where(
            payload.c.owner_id == owner,
            payload.c.evidence_id == evidence.id,
        )
        .exists()
    )
    after: UUID | None = None
    while budget.metadata_limit:
        query = select(evidence.id).where(
            evidence.owner_id == owner,
            selected,
            physical,
            ~_evidence_blocked(),
        )
        if after is not None:
            query = query.where(evidence.id > after)
        # The trigger locks E then linked V rows. Never wait for E while holding
        # a marker's V lock: a publisher may hold E and be waiting for that V.
        identifier = session.scalar(
            query.order_by(evidence.id).limit(1).with_for_update(skip_locked=True)
        )
        if identifier is None:
            return
        _charge(budget, 1)
        after = identifier
        # Re-evaluate linked markers and remaining copies under the E lock.
        # Every linked version is locked again in UUID order by the DELETE guard.
        allowed = (
            select(evidence.id)
            .where(
                evidence.id == identifier,
                evidence.owner_id == owner,
                ~_evidence_blocked(),
            )
            .exists()
        )
        if not purge_payload_rows(
            session,
            payload,
            (payload.c.owner_id == owner) & (payload.c.evidence_id == identifier) & allowed,
            payload_columns=EVIDENCE_PAYLOAD_COLUMNS,
            delete_rows=True,
            budget=budget,
        ).complete:
            return


def _physical_pending(owner: UUID, version_id: UUID) -> ColumnElement[bool]:
    version = ScenarioSensitivityVersionPayloadModel
    observation = ScenarioSensitivityObservationModel
    observed = ScenarioSensitivityObservationPayloadModel
    evidence = ScenarioSensitivityEvidencePayloadModel
    link = ScenarioSensitivityEvidenceLinkModel
    return or_(
        select(version.id)
        .where(version.owner_id == owner, version.version_id == version_id)
        .exists(),
        select(observed.id)
        .join(
            observation,
            (observation.id == observed.observation_id)
            & (observation.owner_id == observed.owner_id),
        )
        .where(observation.owner_id == owner, observation.version_id == version_id)
        .exists(),
        select(evidence.id)
        .join(
            link,
            (link.evidence_id == evidence.evidence_id) & (link.owner_id == evidence.owner_id),
        )
        .where(link.owner_id == owner, link.version_id == version_id)
        .exists(),
        _copies_pending(literal(owner), literal(version_id)),
    )


def _purge_version(
    session: Session,
    version: ScenarioSensitivityVersionModel,
    *,
    at: datetime,
    budget: SourcePurgeBudget,
    erase: bool,
) -> bool:
    if not budget.enter_capture("scenario", version.id) or budget.metadata_limit < 3:
        return False
    marker = session.scalar(
        select(ScenarioSensitivityRetentionModel).where(
            ScenarioSensitivityRetentionModel.owner_id == version.owner_id,
            ScenarioSensitivityRetentionModel.version_id == version.id,
        )
    )
    if marker is None:
        marker = ScenarioSensitivityRetentionModel(
            id=uuid4(),
            owner_id=version.owner_id,
            version_id=version.id,
            created_at=at,
            completed_at=None,
            reason="owner_erasure"
            if erase
            else ("source_expired" if version.expires_at <= at else "source_restricted"),
        )
        session.add(marker)
        session.flush()
    else:
        _charge(budget, 1)
    if not purge_scenario_sensitivity_copies(
        session,
        version.owner_id,
        version.id,
        at=at,
        budget=budget,
    ):
        return False
    _purge_evidence(session, version.owner_id, version.id, budget=budget)
    observation = ScenarioSensitivityObservationModel
    observed = cast(Table, ScenarioSensitivityObservationPayloadModel.__table__)
    selected = (
        select(observation.id)
        .where(
            observation.owner_id == version.owner_id,
            observation.version_id == version.id,
            observation.id == observed.c.observation_id,
        )
        .exists()
    )
    if not purge_payload_rows(
        session,
        observed,
        (observed.c.owner_id == version.owner_id) & selected,
        payload_columns=OBSERVATION_PAYLOAD_COLUMNS,
        delete_rows=True,
        budget=budget,
    ).complete:
        return False
    payload = cast(Table, ScenarioSensitivityVersionPayloadModel.__table__)
    if not purge_payload_rows(
        session,
        payload,
        (payload.c.owner_id == version.owner_id) & (payload.c.version_id == version.id),
        payload_columns=VERSION_PAYLOAD_COLUMNS,
        delete_rows=True,
        budget=budget,
    ).complete:
        return False
    if not budget.metadata_limit:
        return False
    # A live sibling or busy E header can leave shared proof pending even though
    # this version's exclusive licensed payload has already been removed.
    pending = session.scalar(select(_physical_pending(version.owner_id, version.id)))
    _charge(budget, 1)
    if pending:
        return False
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
    """Remove eligible source payloads without starving an expired shared sibling.

    Explicit erasure must name one already-authorized owner. This internal
    participant grants no authorization and does not erase permanent audit IDs.
    """
    if erase and owner is None:
        raise ValueError("Scenario source erasure requires one explicit owner.")
    busy: set[UUID] = set()
    pending = False
    after: UUID | None = None
    while budget.metadata_limit >= 2:
        query = select(ScenarioSensitivityVersionModel.id, ScenarioSensitivityVersionModel.owner_id)
        query = query.where(_eligible(at, erase=erase))
        if owner is not None:
            query = query.where(ScenarioSensitivityVersionModel.owner_id == owner)
        if after is not None:
            query = query.where(ScenarioSensitivityVersionModel.id > after)
        if busy:
            query = query.where(ScenarioSensitivityVersionModel.owner_id.not_in(busy))
        candidate = session.execute(
            query.order_by(ScenarioSensitivityVersionModel.id).limit(1)
        ).first()
        if candidate is None:
            return not (pending or busy)
        _charge(budget, 1)
        after = candidate.id
        if not _lock_owner(session, candidate.owner_id):
            busy.add(candidate.owner_id)
            continue
        version = session.scalar(
            select(ScenarioSensitivityVersionModel)
            .where(
                ScenarioSensitivityVersionModel.id == candidate.id,
                ScenarioSensitivityVersionModel.owner_id == candidate.owner_id,
                _eligible(at, erase=erase),
            )
            .with_for_update(skip_locked=True)
        )
        if version is None:
            busy.add(candidate.owner_id)
            continue
        _charge(budget, 1)
        if not _purge_version(session, version, at=at, budget=budget, erase=erase):
            pending = True
            # Continue past shared-evidence blockage; an eligible sibling later
            # in the same bounded keyset must still get its retention marker.
    return False
