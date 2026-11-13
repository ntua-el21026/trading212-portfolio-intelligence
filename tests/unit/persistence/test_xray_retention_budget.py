"""Exact parent lookup boundaries defer before unbudgeted X-ray inspection."""

from typing import cast
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.orm import Session
from sqlalchemy.sql import ClauseElement
from trading212_persistence import xray_retention
from trading212_persistence.source_retention import SourcePurgeBudget

pytestmark = pytest.mark.unit
OWNER = UUID(int=1)
RUN = UUID(int=2)
ANALYTICS = UUID(int=3)
PARENT = UUID(int=4)


def _unchanged_allowances(budget: SourcePurgeBudget) -> tuple[int, ...]:
    return (
        budget.captures,
        budget.runs,
        budget.rows_removed,
        budget.bytes_inspected,
        budget.bytes_removed,
        budget.artifacts,
    )


def _assert_point_lookups(session: Mock, expected_tables: tuple[str, ...]) -> None:
    assert session.scalar.call_count == len(expected_tables)
    for call, table in zip(session.scalar.call_args_list, expected_tables, strict=True):
        statement = call.args[0]
        assert isinstance(statement, ClauseElement)
        compiled = statement.compile(dialect=PGDialect())  # type: ignore[no-untyped-call]  # SQLAlchemy dialect constructor.
        sql = str(compiled)
        assert f"FROM {table}" in sql
        assert f"{table}.owner_id =" in sql and compiled.params["owner_id_1"] == OWNER
        assert f"{table}.run_id =" in sql and compiled.params["run_id_1"] == RUN
        assert "ORDER BY" in sql and compiled.params["param_1"] == 1
        if table != "xray_collection_bindings":
            assert f"{table}.canonical_payload !=" in sql
            assert compiled.params["canonical_payload_1"] == b""
    session.execute.assert_not_called()


@pytest.mark.parametrize(
    ("parent_kind", "allowance", "lookups", "remaining"),
    (
        ("path", 2, ("xray_collection_bindings",), 1),
        ("path", 3, ("xray_collection_bindings", "xray_exposure_paths"), 0),
        ("composition", 3, ("xray_collection_bindings", "xray_exposure_paths"), 1),
        (
            "composition",
            4,
            ("xray_collection_bindings", "xray_exposure_paths", "xray_fund_compositions"),
            0,
        ),
    ),
    ids=("path-one-short", "path-exact", "composition-one-short", "composition-exact"),
)
def test_parent_lookup_reserves_scope_and_returned_identity_before_sql(
    parent_kind: str,
    allowance: int,
    lookups: tuple[str, ...],
    remaining: int,
) -> None:
    session = Mock(spec=Session)
    # The actual collection probe is empty. For a composition boundary the actual
    # path probe is also empty; neither helper is replaced by a budget-free stub.
    session.scalar.side_effect = [None, PARENT] if parent_kind == "path" else [None, None, PARENT]
    budget = SourcePurgeBudget(
        captures=2,
        runs=2,
        rows_inspected=allowance,
        rows_removed=3,
        bytes_inspected=127,
        bytes_removed=113,
        artifacts=1,
    )
    untouched = _unchanged_allowances(budget)

    assert not xray_retention._run_payloads(cast(Session, session), OWNER, RUN, ANALYTICS, budget)

    assert budget.rows_inspected == remaining
    assert _unchanged_allowances(budget) == untouched
    _assert_point_lookups(session, lookups)


def test_empty_parent_probes_charge_one_row_each_without_reserving_a_returned_identity() -> None:
    session = Mock(spec=Session)
    session.scalar.side_effect = [None, None, None]
    budget = SourcePurgeBudget(rows_inspected=4)
    untouched = _unchanged_allowances(budget)

    assert not xray_retention._run_payloads(cast(Session, session), OWNER, RUN, ANALYTICS, budget)

    assert budget.rows_inspected == 1
    assert _unchanged_allowances(budget) == untouched
    _assert_point_lookups(
        session,
        ("xray_collection_bindings", "xray_exposure_paths", "xray_fund_compositions"),
    )
