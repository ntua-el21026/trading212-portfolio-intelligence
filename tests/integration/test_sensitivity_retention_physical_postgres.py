"""Actual source publication, shared evidence flags and durable source keysets."""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from trading212_persistence.premium_retention_models import PremiumRetentionSweepModel
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityEvidenceLinkModel as Link,
)
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityEvidencePayloadModel as Payload,
)
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityRetentionModel as Marker,
)
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityVersionModel as Version,
)
from trading212_persistence.scenario_source_retention import expire_scenario_sensitivity_payloads
from trading212_persistence.source_retention import SourcePurgeBudget

from tests.integration.test_phase3_scenario_schema import NOW, source
from tests.integration.test_phase3_scenario_schema import database_engine as database_engine
from tests.integration.test_phase3_scenario_schema import scope as scope
from tests.integration.test_scenario_source_retention_postgres import publish, shared

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def test_live_sibling_preserves_bytes_and_false_copy_flags_are_rejected(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, _, _ = scope
    first, second, payload = shared(session, owner)
    identifier = session.scalar(select(Link.id).where(Link.version_id == first.id))
    assert identifier is not None
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(update(Link).where(Link.id == identifier).values(copy_pending=False))
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(update(Version).where(Version.id == first.id).values(retention_closed=True))
    early = NOW + timedelta(days=2)
    for _ in range(40):
        budget = SourcePurgeBudget(rows_inspected=100)
        assert not expire_scenario_sensitivity_payloads(
            session, at=early, owner=owner, budget=budget
        )
        assert 0 <= budget.rows_inspected <= 100
        session.expire_all()
        link = session.get_one(Link, identifier)
        if not link.copy_pending:
            break
    else:
        pytest.fail("Restricted version did not release logical evidence ownership")
    assert link.payload_pending and session.get(Payload, payload) is not None
    assert not session.get_one(Version, second.id).retention_closed
    with pytest.raises(IntegrityError, match="physical copy remains"), session.begin_nested():
        session.execute(update(Link).where(Link.id == identifier).values(payload_pending=False))
    for _ in range(100):
        budget = SourcePurgeBudget(rows_inspected=120)
        complete = expire_scenario_sensitivity_payloads(
            session, at=NOW + timedelta(days=8), owner=owner, budget=budget
        )
        assert 0 <= budget.rows_inspected <= 120
        if complete:
            break
    else:
        pytest.fail("Restricted shared versions did not converge")
    session.expire_all()
    assert session.get(Payload, payload) is None
    assert all(session.get_one(Version, version.id).retention_closed for version in (first, second))
    assert (
        session.scalar(
            select(Link.id).where(Link.owner_id == owner, Link.payload_pending.is_(True))
        )
        is None
    )
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_source_cursor_crosses_healthy_prefix_and_resets_on_policy_epoch(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, _, _ = scope
    versions = []
    for _ in range(40):
        version, _ = source(session, owner)
        publish(session, version)
        versions.append(version)
    positions = set()
    for _ in range(160):
        budget = SourcePurgeBudget(rows_inspected=32)
        complete = expire_scenario_sensitivity_payloads(session, at=NOW, owner=owner, budget=budget)
        assert 0 <= budget.rows_inspected <= 32
        sweep = session.get_one(PremiumRetentionSweepModel, (owner, "sensitivity"))
        if sweep.after_id is not None:
            positions.add(sweep.after_id)
        if complete:
            break
    else:
        pytest.fail("Healthy source prefix starved bounded scan")
    assert len(positions) > 2
    assert session.scalar(select(Marker.id).where(Marker.owner_id == owner)) is None
    # A later original deadline invalidates every previously clean prefix.
    for _ in range(160):
        budget = SourcePurgeBudget(rows_inspected=120)
        if expire_scenario_sensitivity_payloads(
            session, at=NOW + timedelta(days=8), owner=owner, budget=budget
        ):
            break
    else:
        pytest.fail("Previously healthy source prefix did not expire")
    session.expire_all()
    assert all(session.get_one(Version, version.id).retention_closed for version in versions)


def test_evidence_delete_guard_has_no_linked_version_lock_fanout(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, _, _, _ = scope
    definition = session.scalar(
        text("SELECT pg_get_functiondef('scenario_source_guard()'::regprocedure)")
    )
    assert isinstance(definition, str)
    delete_branch = definition.split(
        "IF TG_OP='DELETE' AND TG_TABLE_NAME='scenario_sensitivity_evidence_payloads' THEN", 1
    )[1]
    assert "copy_pending" in delete_branch
    assert "JOIN scenario_sensitivity_versions" not in delete_branch
    assert "FOR UPDATE OF" not in delete_branch
    assert "scenario_run_has_payload" not in definition
