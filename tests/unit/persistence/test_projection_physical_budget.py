"""SQL-trigger inspections share the same physical ceiling and stable prefix."""

from uuid import UUID

import pytest
from trading212_persistence.projection_retention_costs import projection_mutation_cost
from trading212_persistence.source_retention import PayloadCopyCost, SourcePurgeBudget


def cost(identifier: int, size: int = 7) -> PayloadCopyCost:
    profile = projection_mutation_cost("projection_points", delete_rows=True)
    return PayloadCopyCost(
        row_id=UUID(int=identifier),
        payload_bytes=size,
        inspection_rows=profile.mutation_rows,
        payload_inspections=profile.payload_inspections,
    )


def test_trigger_rows_are_reserved_before_mutation_and_never_reset_per_batch() -> None:
    budget = SourcePurgeBudget(rows_inspected=60, rows_removed=100)
    assert budget.inspect(rows=3)
    assert budget.reserve_clear_batch((cost(1), cost(2), cost(3))) == (UUID(int=1), UUID(int=2))
    assert budget.rows_inspected == 7 and budget.rows_removed == 98
    assert budget.bytes_inspected == 64 * 1024 * 1024 - 28
    assert budget.bytes_removed == 64 * 1024 * 1024 - 14
    assert budget.reserve_clear_batch((cost(3),)) == ()
    assert budget.rows_inspected == 7


def test_largest_legal_payload_and_counter_reread_fit_exactly_one_fresh_budget() -> None:
    budget = SourcePurgeBudget()
    assert budget.inspect(rows=1)
    assert budget.reserve_clear_batch((cost(1, 32 * 1024 * 1024),)) == (UUID(int=1),)
    assert budget.bytes_inspected == 0
    assert budget.bytes_removed == 32 * 1024 * 1024
    assert budget.reserve_clear_batch((cost(2, 1),)) == ()


def test_weighted_sql_batch_never_exceeds_512_inspected_rows() -> None:
    budget = SourcePurgeBudget()
    rows = tuple(cost(i) for i in range(1, 513))
    selected = budget.reserve_clear_batch(rows)
    assert len(selected) == 20  # 20 * 25 fixed physical inspections <=512
    assert budget.rows_inspected == 4096 - 500
    assert budget.rows_removed == 4096 - 20


def test_mixed_families_consume_one_budget_with_unchanged_legacy_defaults() -> None:
    budget = SourcePurgeBudget(rows_inspected=27)
    assert budget.reserve_clear_batch((cost(1),)) == (UUID(int=1),)
    legacy = PayloadCopyCost(row_id=UUID(int=2), payload_bytes=1)
    assert budget.reserve_clear_batch((legacy,)) == (UUID(int=2),)
    assert budget.rows_inspected == 1
    assert budget.reserve_clear_batch((cost(3),)) == ()


@pytest.mark.parametrize("rows,reads", [(0, 1), (513, 1), (True, 1), (1, 0), (1, 3), (1, True)])
def test_invalid_inspection_cost_cannot_reduce_the_physical_ceiling(rows: int, reads: int) -> None:
    with pytest.raises(ValueError):
        PayloadCopyCost(
            row_id=UUID(int=1), payload_bytes=1, inspection_rows=rows, payload_inspections=reads
        )


def test_indirect_cleanup_visits_empty_parents_explicitly_and_uses_exact_parent_predicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import cast
    from unittest.mock import Mock

    from sqlalchemy import Table
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.elements import ColumnElement
    from trading212_persistence import projection_retention as retention
    from trading212_persistence.premium_models import PremiumRunModel
    from trading212_persistence.projection_models import ProjectionDistributionQuantileModel
    from trading212_persistence.source_retention_sql import PayloadPurgeResult

    root = PremiumRunModel(id=UUID(int=1), owner_id=UUID(int=2), account_id=UUID(int=3))
    session = Mock(spec=Session)
    # Exact result header, two parent headers (first already empty), final keyset probe.
    session.scalar.side_effect = (UUID(int=4), UUID(int=5), UUID(int=6), None)
    predicates: list[str] = []

    def clear(*args: object, **kwargs: object) -> PayloadPurgeResult:
        assert len(args) == 3
        predicate = cast(ColumnElement[bool], args[2])
        predicates.append(
            str(
                predicate.compile(
                    dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]  # SQLAlchemy dialect.
                    compile_kwargs={"literal_binds": True},
                )
            )
        )
        return PayloadPurgeResult(complete=True, removed_rows=0, removed_bytes=0)

    monkeypatch.setattr(retention, "purge_payload_rows", clear)
    budget = SourcePurgeBudget()
    assert retention._clear_indirect(
        cast(Session, session),
        root,
        cast(Table, ProjectionDistributionQuantileModel.__table__),
        ("value",),
        budget,
    )
    assert len(predicates) == 2 and all(" IN (SELECT" not in value for value in predicates)
    assert str(UUID(int=5)) in predicates[0] and str(UUID(int=6)) in predicates[1]
    assert budget.rows_inspected == 4092
