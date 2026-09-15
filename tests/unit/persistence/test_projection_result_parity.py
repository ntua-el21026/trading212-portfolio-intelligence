"""Bounded SQL row batches and exact complete normalized financial parity."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert
from trading212_application.projection import ProjectionErrorCode
from trading212_persistence import projection_models as m
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_result_parity import _rows, _scoped

OWNER, ACCOUNT, RUN, CHUNK = (UUID(int=index) for index in range(1, 5))
AT = datetime(2026, 8, 31, tzinfo=UTC)
pytestmark = pytest.mark.unit


def rows() -> tuple[dict[str, object], ...]:
    return tuple(
        dict(
            id=UUID(int=100 + index),
            run_id=RUN,
            point_id=UUID(int=1000 + index),
            asset_index=index % 12,
            value=Decimal("123.123456789012345678"),
        )
        for index in range(513)
    )


def session_for_rows(*, corrupt: bool = False, extra: bool = False) -> tuple[Any, list[int]]:
    session = MagicMock(spec=Session)
    database: dict[UUID, dict[str, object]] = {}
    batches: list[int] = []

    def execute(statement: Any, parameters: Any = None) -> Any:
        if isinstance(statement, Insert):
            batches.append(len(parameters))
            for item in parameters:
                database[item["id"]] = dict(item)
            return MagicMock()
        identifiers = next(
            value
            for value in statement.compile().params.values()
            if isinstance(value, (list, tuple)) and value and isinstance(value[0], UUID)
        )
        actual = [dict(database[identifier]) for identifier in reversed(identifiers)]
        if corrupt:
            actual[0]["value"] = Decimal("123.123456789012345679")
        result = MagicMock()
        result.mappings.return_value = actual
        return result

    session.execute.side_effect = execute
    session.scalar.side_effect = lambda *args: len(database) + int(extra)
    return session, batches


def invoke(session: Session, records: tuple[dict[str, object], ...]) -> None:
    _rows(
        session,
        m.ProjectionPointAssetModel,
        iter(records),
        owner=OWNER,
        account=ACCOUNT,
        root=RUN,
        child=CHUNK,
        created_at=AT,
        publish=True,
        boundary=lambda: None,
    )


def test_insert_and_compare_never_materialize_more_than_256_financial_rows() -> None:
    session, batches = session_for_rows()
    invoke(session, rows())
    assert batches == [256, 256, 1]
    # Each insert is followed by a scalar-column read; ORM entities are not loaded.
    assert session.execute.call_count == 6
    session.scalars.assert_not_called()


@pytest.mark.parametrize("corrupt,extra", [(True, False), (False, True)])
def test_one_q18_change_or_extra_normalized_row_is_not_accepted(corrupt: bool, extra: bool) -> None:
    session, _ = session_for_rows(corrupt=corrupt, extra=extra)
    with pytest.raises(ProjectionStorageError) as caught:
        invoke(session, rows())
    assert caught.value.code is ProjectionErrorCode.PROJECTION_UNAVAILABLE


def test_unknown_fields_do_not_enter_a_dynamic_sql_escape_hatch() -> None:
    session, _ = session_for_rows()
    original = rows()[0]
    with pytest.raises(ProjectionStorageError):
        invoke(session, (dict(original, arbitrary_financial_field="private-canary"),))
    session.execute.assert_not_called()


def test_child_scope_uses_owner_account_run_and_chunk_parent_for_parity_counts() -> None:
    statement = _scoped(m.ProjectionPointAssetModel, OWNER, ACCOUNT, RUN, CHUNK)
    sql = str(statement.compile(dialect=PGDialect(), compile_kwargs={"literal_binds": True}))  # type: ignore[no-untyped-call]  # SQLAlchemy dialect constructor.
    assert f"projection_point_assets.owner_id = '{OWNER}'" in sql
    assert f"projection_point_assets.account_id = '{ACCOUNT}'" in sql
    assert f"projection_point_assets.run_id = '{RUN}'" in sql
    assert f"projection_paths.chunk_id = '{CHUNK}'" in sql
    assert "JOIN projection_points" in sql and "JOIN projection_paths" in sql
