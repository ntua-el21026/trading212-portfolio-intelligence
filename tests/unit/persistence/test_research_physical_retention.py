"""Physical-row budget includes completed prefixes and triggered copy transitions."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from trading212_persistence import research_retention as module
from trading212_persistence.research_models import (
    ResearchRetentionCursorModel,
    ResearchSourceVersionModel,
)
from trading212_persistence.research_retention_costs import research_mutation_cost
from trading212_persistence.source_retention import PayloadCopyCost, SourcePurgeBudget

from tests.unit.domain.research_factories import AT, uid


def test_raw_completed_prefix_advances_and_charges_without_hidden_payload_predicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, version = uid(1), uid(99)
    cursor = ResearchRetentionCursorModel(
        key=f"research:{owner}",
        scope_owner_id=owner,
        last_owner_id=None,
        last_version_id=None,
        updated_at=AT,
    )
    row = ResearchSourceVersionModel(id=version, owner_id=owner, sealed=True)
    marker = SimpleNamespace(completed_at=AT - timedelta(seconds=1))
    session = Mock(spec=Session)
    session.scalar.side_effect = (cursor, row, marker)
    session.execute.side_effect = (Mock(), Mock(all=lambda: [(owner, version)]))
    monkeypatch.setattr(module, "_owner", lambda *args: True)
    budget = SourcePurgeBudget(rows_inspected=24)
    assert not module.expire_research_payloads(
        session,
        at=AT,
        budget=budget,
        capability_authority=None,
        owner=owner,
    )
    assert (cursor.last_owner_id, cursor.last_version_id) == (owner, version)
    assert budget.rows_inspected == 5  # cursor16 + header1 + locked header1 + marker1
    selected = session.execute.call_args_list[1].args[0]
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]  # SQLAlchemy dialect.
    sql = str(selected.compile(dialect=dialect)).lower()
    assert "exists" not in sql and "payload" not in sql and "sealed" not in sql
    assert "order by research_source_versions.owner_id, research_source_versions.id" in sql
    assert selected._limit_clause.value == 1


def test_empty_indexed_source_authority_probes_are_charged_before_query() -> None:
    session = Mock(spec=Session)
    session.scalar.return_value = None
    row = ResearchSourceVersionModel(
        owner_id=uid(1),
        origin_id=uid(2),
        provider_id=uid(3),
        license_version_id=uid(4),
    )
    budget = SourcePurgeBudget(rows_inspected=4)
    assert module._restricted(session, row, at=AT, authority=None, budget=budget)
    assert budget.rows_inspected == 0 and session.scalar.call_count == 4


def test_event_copy_mutation_reserves_whole_fanout_and_double_payload_inspection() -> None:
    profile = research_mutation_cost("research_event_payloads", delete_rows=True)
    assert profile is not None
    cost = PayloadCopyCost(
        row_id=uid(1),
        payload_bytes=100,
        inspection_rows=profile.mutation_rows,
        payload_inspections=profile.payload_inspections,
    )
    blocked = SourcePurgeBudget(rows_inspected=383)
    assert blocked.reserve_clear_batch((cost,)) == () and blocked.rows_inspected == 383
    budget = SourcePurgeBudget(rows_inspected=512, bytes_inspected=200, bytes_removed=100)
    assert budget.reserve_clear_batch((cost,)) == (uid(1),)
    assert budget.rows_inspected == 128 and budget.rows_removed == 4095
    assert budget.bytes_inspected == 0 and budget.bytes_removed == 0
    assert budget.reserve_clear_batch((cost,)) == ()


def test_research_copy_clear_cannot_be_relabelled_as_partial_update() -> None:
    with pytest.raises(ValueError):
        research_mutation_cost("research_event_payloads", delete_rows=False)
    assert research_mutation_cost("unrelated_table", delete_rows=True) is None
