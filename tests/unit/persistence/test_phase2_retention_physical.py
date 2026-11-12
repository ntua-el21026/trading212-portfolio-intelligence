"""Physical budgets are reserved before rows or triggered child work are touched."""

from datetime import UTC, datetime
from types import GeneratorType, SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.sql import ClauseElement
from trading212_persistence.phase2_retention_costs import (
    PHASE2_PAYLOAD_MUTATION_ROWS,
    phase2_mutation_cost,
)
from trading212_persistence.phase2_retention_runtime import physical_source_candidates, rotation
from trading212_persistence.source_models import PriceSnapshotModel, SourceRetentionWorkModel
from trading212_persistence.source_retention import PayloadCopyCost, SourcePurgeBudget


@pytest.mark.parametrize(
    "table",
    ["performance_points", "xray_fund_entities", "fx_observations", "benchmark_composite_points"],
)
def test_financial_write_reserves_all_guard_work_and_two_exact_byte_inspections(table: str) -> None:
    cost = phase2_mutation_cost(table, delete_rows=False)
    assert cost is not None and cost.mutation_rows == PHASE2_PAYLOAD_MUTATION_ROWS
    item = PayloadCopyCost(
        row_id=uuid4(),
        payload_bytes=32 * 1024 * 1024,
        inspection_rows=cost.mutation_rows,
        payload_inspections=cost.payload_inspections,
    )
    insufficient = SourcePurgeBudget(rows_inspected=cost.mutation_rows - 1)
    assert insufficient.reserve_clear_batch((item,)) == ()
    assert insufficient.rows_removed == 4096
    exact = SourcePurgeBudget(rows_inspected=cost.mutation_rows)
    assert exact.reserve_clear_batch((item,)) == (item.row_id,)
    assert exact.bytes_inspected == 0 and exact.bytes_removed == 32 * 1024 * 1024
    assert exact.rows_inspected == 0 and exact.rows_removed == 4095


def test_dispatch_rotation_uses_one_shared_budget_and_reaches_every_family() -> None:
    row = SimpleNamespace(next_family=0)
    session = MagicMock()
    session.scalar.side_effect = lambda query, *args: (
        True if "pg_try_advisory" in str(query) else row
    )
    # The dispatcher currently has eight frozen participants, including the
    # Phase 3 family; retain four inspected rows per turn and one shared budget.
    budget = SourcePurgeBudget(rows_inspected=32)
    first = [rotation(session, "dispatch", 8, budget)[0] for _ in range(8)]
    assert first == list(range(8)) and row.next_family == 0
    assert budget.rows_inspected == 0
    before = session.execute.call_count
    assert rotation(session, "dispatch", 8, budget) == ()
    assert session.execute.call_count == before


def test_pending_and_physical_keysets_are_independent_and_never_filter_healthy_roots() -> None:
    at = datetime(2026, 9, 15, tzinfo=UTC)
    owner = uuid4()
    first, second = UUID(int=1), UUID(int=2)
    work = UUID(int=50)
    sweep = SimpleNamespace(after_id=None, pending_id=None, evaluated_at=None)
    session = MagicMock()
    session.get.return_value = sweep
    statements: list[str] = []
    reads = iter(
        [
            SimpleNamespace(id=work, source_id=first, owner_id=owner),
            SimpleNamespace(id=first, owner_id=owner, expires_at=at),
            SimpleNamespace(id=second, owner_id=owner, expires_at=at),
            None,
        ]
    )

    def execute(statement: object) -> MagicMock:
        assert isinstance(statement, ClauseElement)
        sql = str(statement.compile(dialect=PGDialect()))  # type: ignore[no-untyped-call]  # SQLAlchemy dialect constructor.
        statements.append(sql)
        result = MagicMock()
        if sql.lstrip().startswith("SELECT"):
            result.first.return_value = next(reads)
        return result

    session.execute.side_effect = execute
    budget = SourcePurgeBudget(rows_inspected=32)
    candidates = list(
        physical_source_candidates(
            session,
            cast(Table, PriceSnapshotModel.__table__),
            cast(Table, SourceRetentionWorkModel.__table__),
            "price_snapshot_id",
            "price",
            at,
            budget,
        )
    )
    assert [(c.id, c.pending) for c in candidates] == [(first, True), (second, False)]
    assert sweep.pending_id == work and sweep.after_id is None
    physical = [sql for sql in statements if "FROM price_snapshots" in sql]
    assert len(physical) == 3 and all(
        "NOT EXISTS" not in sql and "expires_at <=" not in sql for sql in physical
    )
    assert all("canonical" not in sql and "payload" not in sql for sql in statements)
    assert 0 < budget.rows_inspected < 32


def test_too_small_source_budget_performs_no_database_operation() -> None:
    session = MagicMock()
    assert (
        list(
            physical_source_candidates(
                session,
                cast(Table, PriceSnapshotModel.__table__),
                cast(Table, SourceRetentionWorkModel.__table__),
                "price_snapshot_id",
                "price",
                datetime(2026, 9, 15, tzinfo=UTC),
                SourcePurgeBudget(rows_inspected=2),
            )
        )
        == []
    )
    session.execute.assert_not_called()


def test_a_budget_return_cannot_checkpoint_an_uninspected_source() -> None:
    owner, identifier = uuid4(), uuid4()
    sweep = SimpleNamespace(after_id=None, pending_id=None, evaluated_at=None)
    session = MagicMock()
    session.get.return_value = sweep
    reads = iter(
        [
            None,
            SimpleNamespace(
                id=identifier, owner_id=owner, expires_at=datetime(2026, 9, 15, tzinfo=UTC)
            ),
        ]
    )

    def execute(statement: object) -> MagicMock:
        result = MagicMock()
        if str(statement).lstrip().startswith("SELECT"):
            result.first.return_value = next(reads)
        return result

    session.execute.side_effect = execute
    iterator = physical_source_candidates(
        session,
        cast(Table, PriceSnapshotModel.__table__),
        cast(Table, SourceRetentionWorkModel.__table__),
        "price_snapshot_id",
        "price",
        datetime(2026, 9, 15, tzinfo=UTC),
        SourcePurgeBudget(rows_inspected=32),
    )
    assert next(iterator).id == identifier
    assert isinstance(iterator, GeneratorType)
    iterator.close()  # Caller could not reserve its authority/header work.
    assert sweep.after_id is None and sweep.pending_id is None
