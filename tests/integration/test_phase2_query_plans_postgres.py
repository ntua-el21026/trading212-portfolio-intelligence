"""Observe the actual bounded collection page query on a local PostgreSQL fixture.

This is a query-plan regression and a local measurement, not a capacity benchmark.
No planner method is disabled and no index is forced.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.queries import CursorCodec
from trading212_persistence import CollectionSnapshotStore

from tests.integration.test_collection_query_snapshots import (
    CURSOR_KEY,
    _create_isolated_scope,
    _scoped_definition,
)
from tests.integration.test_collection_query_snapshots import (
    collection_snapshot_database as collection_snapshot_database,
)

pytestmark = pytest.mark.integration


def _nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [plan, *(item for child in plan.get("Plans", []) for item in _nodes(child))]


def test_actual_keyset_query_retains_quota_plus_one_index_bound_at_deep_page(
    collection_snapshot_database: tuple[Engine, sessionmaker[Session]],
    record_property: Callable[[str, object], None],
) -> None:
    engine, sessions = collection_snapshot_database
    with sessions.begin() as session:
        owner_id, account_id = _create_isolated_scope(session, label="p210-query-plan")
    definition = _scoped_definition(
        owner_id,
        account_id,
        filter_name="p210-10001-member-plan",
    )
    expected = tuple(
        uuid5(NAMESPACE_URL, f"p210/query-plan/member/{ordinal}") for ordinal in range(10_001)
    )
    with sessions.begin() as session:
        first = CollectionSnapshotStore(session, CursorCodec(CURSOR_KEY)).materialize(
            definition,
            expected,
            limit=100,
        )
    assert first.record_ids == expected[:100] and first.exact_total == len(expected)
    assert first.next_cursor is not None

    # Statistics belong to this disposable fixture database; retain normal planner settings.
    with engine.begin() as connection:
        connection.exec_driver_sql("ANALYZE collection_query_snapshot_members")
    cursor = first.next_cursor
    consumed = 100
    while consumed < 9_900:
        with sessions.begin() as session:
            page = CollectionSnapshotStore(session, CursorCodec(CURSOR_KEY)).resume(
                definition,
                cursor,
                limit=100,
            )
        assert page.record_ids == expected[consumed : consumed + 100]
        assert page.next_cursor is not None
        cursor = page.next_cursor
        consumed += 100

    captured: list[tuple[str, Any]] = []

    def observe(
        _connection: Connection,
        _cursor: Any,
        statement: str,
        parameters: Any,
        _context: Any,
        executemany: bool,
    ) -> None:
        if (
            not executemany
            and statement.lstrip().upper().startswith("SELECT ")
            and "FROM collection_query_snapshot_members" in statement
        ):
            captured.append((statement, parameters))

    started = perf_counter()
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with sessions.begin() as session:
            deep = CollectionSnapshotStore(session, CursorCodec(CURSOR_KEY)).resume(
                definition,
                cursor,
                limit=100,
            )
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    local_page_seconds = perf_counter() - started
    assert deep.record_ids == expected[9_900:10_000]
    assert deep.next_cursor is not None and deep.exact_total == 10_001
    assert len(captured) == 1
    statement, parameters = captured[0]
    assert " OFFSET " not in " ".join(statement.upper().split())
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL statement_timeout = '10s'")
        connection.exec_driver_sql("SET LOCAL lock_timeout = '1s'")
        version = connection.exec_driver_sql("SHOW server_version").scalar_one()
        planner = {
            setting: connection.exec_driver_sql("SHOW " + setting).scalar_one()
            for setting in ("enable_seqscan", "enable_indexscan", "enable_bitmapscan", "work_mem")
        }
        # Replay only the SELECT captured from the real store, with its original DBAPI binds.
        raw = connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
            parameters,
        ).scalar_one()
    assert isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict)
    observation = {
        "schema": "local-query-observation/v1",
        "query": "collection_members_keyset_page",
        "observed_at": datetime.now(UTC).isoformat(),
        "fixture": {"members": 10_001, "after_ordinal": 9_900, "requested_limit": 100},
        "postgres_version": version,
        "planner_settings": planner,
        "sql_sha256": hashlib.sha256(statement.encode()).hexdigest(),
        "application_page_seconds": local_page_seconds,
        "explain": raw[0],
        "production_capacity_claim": False,
    }
    # Preserve the actual plan in the JUnit receipt even when a following predicate fails.
    record_property("p210_query_plan", json.dumps(observation, sort_keys=True))
    plan = raw[0]["Plan"]
    assert plan["Node Type"] == "Limit"
    assert plan["Actual Rows"] == 101 and plan["Actual Loops"] == 1
    scans = [
        node
        for node in _nodes(plan)
        if node.get("Relation Name") == "collection_query_snapshot_members"
    ]
    assert scans
    for node in scans:
        index_node = node
        if node["Node Type"] == "Bitmap Heap Scan":
            # A selective bitmap may sort the bounded suffix under normal planner settings.
            assert node["Lossy Heap Blocks"] == 0
            assert node["Rows Removed by Index Recheck"] == 0
            children = node.get("Plans", [])
            assert len(children) == 1
            index_node = children[0]
            assert index_node["Node Type"] == "Bitmap Index Scan"
            assert not index_node.get("Plans")
            assert index_node["Actual Rows"] <= 101
            assert index_node["Actual Loops"] == 1
            assert index_node.get("Rows Removed by Filter", 0) == 0
        else:
            assert node["Node Type"] in {"Index Scan", "Index Only Scan"}
        assert "snapshot_id" in index_node.get("Index Cond", "")
        assert "ordinal" in index_node.get("Index Cond", "")
        assert node["Actual Rows"] <= 101
        assert node["Actual Loops"] == 1
        assert node.get("Rows Removed by Filter", 0) == 0
    assert all(
        planner[setting] == "on"
        for setting in ("enable_seqscan", "enable_indexscan", "enable_bitmapscan")
    )
    with sessions.begin() as session:
        tail = CollectionSnapshotStore(session, CursorCodec(CURSOR_KEY)).resume(
            definition,
            deep.next_cursor,
            limit=100,
        )
    assert tail.record_ids == expected[10_000:] and tail.next_cursor is None
