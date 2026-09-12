"""Routine synthetic access-path measurement; not retention/runtime acceptance."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from psycopg import sql
from sqlalchemy import Connection, Engine, event
from sqlalchemy.orm import Session, sessionmaker
from trading212_persistence.alert_retention import expire_alert_payloads
from trading212_persistence.report_retention import expire_report_payloads

from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration
AT = datetime(2026, 9, 11, 12, tzinfo=UTC)
OWNERS, PER_OWNER = 32, 1024
ROWS = OWNERS * PER_OWNER
TABLES = ("report_input_snapshots", "alert_input_snapshots")


class CapturedSelect(Exception):
    """Stop the actual retention function before its first database statement."""


def _capture(connection: Connection, function: Any, at: datetime, table: str) -> tuple[str, Any]:
    captured: list[tuple[str, Any]] = []

    def intercept(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        # The first SQL must be the real unqualified table SELECT. Never allow
        # the retention owner lock, purge body or a changed first statement to run.
        compiled = context.compiled
        assert compiled is not None and compiled.statement.is_select
        sources = compiled.statement.get_final_froms()
        assert len(sources) == 1 and sources[0].name == table and sources[0].schema is None
        assert not executemany and statement.lstrip().upper().startswith("SELECT ")
        captured.append(
            (statement, parameters.copy() if isinstance(parameters, dict) else parameters)
        )
        raise CapturedSelect

    with Session(bind=connection) as session:
        event.listen(connection, "before_cursor_execute", intercept)
        try:
            with pytest.raises(CapturedSelect):
                function(session, at=at, limit=1)
        finally:
            event.remove(connection, "before_cursor_execute", intercept)
    assert len(captured) == 1
    return captured[0]


def _seed(connection: Connection, schema: str) -> None:
    # Ordinary logged tables retain normal parallel/planner eligibility. LIKE
    # copies the migrated columns, CHECKs and indexes, not triggers or foreign keys.
    connection.exec_driver_sql(
        sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)).as_string()
    )
    for table in TABLES:
        connection.exec_driver_sql(
            sql.SQL("CREATE TABLE {}.{} (LIKE public.{} INCLUDING ALL)")
            .format(sql.Identifier(schema), sql.Identifier(table), sql.Identifier(table))
            .as_string()
        )
    common = """
        WITH population AS (
            SELECT n, n / 1024 AS owner_n, n %% 1024 AS slot
            FROM generate_series(0, %(last)s) AS n
        ), sample AS (
            SELECT *,
                md5('p210-owner-' || owner_n)::uuid AS owner_id,
                md5('p210-account-' || owner_n)::uuid AS account_id,
                CASE WHEN slot = 0 THEN %(at)s::timestamptz - interval '1 second'
                     WHEN slot < 256 THEN %(at)s::timestamptz + interval '1 day'
                                           + slot * interval '1 second'
                     WHEN slot < 768 THEN %(at)s::timestamptz + interval '30 days'
                                           + slot * interval '1 second'
                     ELSE %(at)s::timestamptz - interval '2 days'
                                           + slot * interval '1 second' END AS expires_at,
                CASE WHEN slot >= 768 THEN %(at)s::timestamptz - interval '1 day'
                     ELSE NULL END AS purged_at,
                %(at)s::timestamptz - interval '30 days' AS created_at,
                CASE WHEN slot < 768 THEN convert_to(repeat('0123456789abcdef', 32), 'UTF8')
                     ELSE NULL END AS payload
            FROM population
        )
    """
    parameters = {"last": ROWS - 1, "at": AT}
    connection.exec_driver_sql(
        (
            sql.SQL(common)
            + sql.SQL("""
        INSERT INTO {}.report_input_snapshots (
            id, owner_id, account_id, created_at, kind, snapshot_id,
            start_date, end_date, valuation_at, source_cutoff_at, reporting_currency,
            input_digest, document_digest, canonical_byte_length, chunk_count,
            pin_count, source_count, canonical_manifest, canonical_context,
            sealed_at, expires_at, purged_at
        )
        SELECT md5('p210-report-' || n)::uuid, owner_id, account_id, created_at,
            CASE WHEN n %% 2 = 0 THEN 'report' ELSE 'export' END,
            md5('p210-snapshot-' || owner_n)::uuid, created_at::date, created_at::date,
            created_at, created_at, 'EUR', repeat(md5('input-' || n), 2),
            repeat(md5('document-' || n), 2), 1024, 0, 1, 0, payload, payload,
            created_at, expires_at, purged_at
        FROM sample
        """).format(sql.Identifier(schema))
        ).as_string(),
        parameters,
    )
    connection.exec_driver_sql(
        (
            sql.SQL(common)
            + sql.SQL("""
        INSERT INTO {}.alert_input_snapshots (
            id, owner_id, account_id, created_at, rule_version_id, scheduled_for,
            source_cutoff_at, execution_intent, input_digest, byte_length,
            payload, sealed_at, expires_at, purged_at
        )
        SELECT md5('p210-alert-' || n)::uuid, owner_id, account_id, created_at,
            md5('p210-rule-' || owner_n)::uuid,
            created_at + slot * interval '1 second',
            created_at + slot * interval '1 second', 'live',
            repeat(md5('alert-input-' || n), 2), 512, payload,
            created_at, expires_at, purged_at
        FROM sample
        """).format(sql.Identifier(schema))
        ).as_string(),
        parameters,
    )
    for table in TABLES:
        connection.exec_driver_sql(
            sql.SQL("ANALYZE {}.{}")
            .format(sql.Identifier(schema), sql.Identifier(table))
            .as_string()
        )


def _write(path: Path, value: object) -> None:
    # A run never replaces an earlier measurement, including a partial failure.
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, default=str)
        stream.write("\n")


def test_record_actual_global_ttl_select_plans(
    alert_database: tuple[Engine, sessionmaker[Session]],
    tmp_path: Path,
    record_property: Callable[[str, object], None],
) -> None:
    requested_output = os.environ.get("P210_RETENTION_PLAN_OUTPUT")
    output = (
        Path(requested_output) if requested_output else tmp_path / "retention-query-plans"
    ).resolve()
    output.mkdir(parents=True, exist_ok=False)
    record_property("p210_retention_plan_output", str(output))
    engine, _ = alert_database
    assert engine.url.database is not None and engine.url.database.startswith("t212pi_alerts_")
    schema = "p210_ttl_" + uuid4().hex
    _write(
        output / "run.json",
        {
            "status": "started",
            "schema": schema,
            "owners": OWNERS,
            "rows_per_owner_per_table": PER_OWNER,
            "rows_per_table": ROWS,
            "population": "synthetic metadata, not canonical financial input",
            "payload_bytes_unpurged": 512,
            "warning": "LIKE omits FK/trigger behavior; no retention mutation is measured",
        },
    )
    with engine.begin() as connection:
        assert (
            connection.exec_driver_sql("SELECT current_database()").scalar_one()
            == engine.url.database
        )
        _seed(connection, schema)
    # Fixture data commits before planning, avoiding a transaction-local table or
    # uncommitted-insert restriction on normal planner choices.
    scenarios = (
        ("none", AT - timedelta(days=3), 0),
        ("sparse", AT, OWNERS),
        ("dense", AT + timedelta(days=2), OWNERS * 256),
    )
    with engine.connect() as connection, connection.begin():
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        connection.exec_driver_sql(
            sql.SQL("SET LOCAL search_path TO {}, public")
            .format(sql.Identifier(schema))
            .as_string()
        )
        settings = [
            dict(row._mapping)
            for row in connection.exec_driver_sql("""
            SELECT name, setting, unit, source, reset_val
            FROM pg_settings
            WHERE category LIKE 'Query Tuning%%'
               OR name IN ('work_mem','shared_buffers','default_statistics_target',
                           'track_io_timing','server_version','plan_cache_mode')
            ORDER BY name
        """)
        ]
        by_name = {row["name"]: row["setting"] for row in settings}
        for name in (
            "enable_seqscan",
            "enable_indexscan",
            "enable_indexonlyscan",
            "enable_bitmapscan",
        ):
            assert by_name[name] == "on", f"Nonstandard forced access-path setting: {name}"
        _write(output / "settings.json", settings)
        _write(
            output / "indexes.json",
            [
                dict(row._mapping)
                for row in connection.exec_driver_sql(
                    """
                SELECT schemaname, tablename, indexname, indexdef
                FROM pg_indexes WHERE schemaname IN (%(schema)s, 'public')
                  AND tablename IN ('report_input_snapshots','alert_input_snapshots')
                ORDER BY schemaname, tablename, indexname
            """,
                    {"schema": schema},
                )
            ],
        )
        observed = []
        for table, function in zip(
            TABLES, (expire_report_payloads, expire_alert_payloads), strict=True
        ):
            # Explicitly confirm the production SQL name resolves to scratch data.
            assert (
                connection.exec_driver_sql(
                    "SELECT to_regclass(%(table)s)::oid = to_regclass(%(qualified)s)::oid",
                    {"table": table, "qualified": f"{schema}.{table}"},
                ).scalar_one()
                is True
            )
            for scenario, at, expected in scenarios:
                # Inventory only. The measured statement is captured below from
                # the actual function; this COUNT is never used as its substitute.
                distribution = [
                    dict(row._mapping)
                    for row in connection.exec_driver_sql(
                        sql.SQL("""SELECT owner_id, count(*) AS total,
                        count(*) FILTER (WHERE purged_at IS NOT NULL) AS purged,
                        count(*) FILTER (WHERE purged_at IS NULL AND expires_at <= %(at)s)
                            AS expired_live,
                        count(*) FILTER (WHERE purged_at IS NULL AND expires_at > %(at)s)
                            AS future_live
                        FROM {}.{} GROUP BY owner_id ORDER BY owner_id""")
                        .format(sql.Identifier(schema), sql.Identifier(table))
                        .as_string(),
                        {"at": at},
                    )
                ]
                assert len(distribution) == OWNERS
                assert all(
                    row["total"] == PER_OWNER and row["purged"] == 256 for row in distribution
                )
                assert sum(row["expired_live"] for row in distribution) == expected
                statement, parameters = _capture(connection, function, at, table)
                prefix = f"{table}-{scenario}"
                returned = list(connection.exec_driver_sql(statement, parameters))
                assert len(returned) == int(expected > 0)
                _write(
                    output / f"{prefix}-selection.json",
                    {
                        "production_function": f"{function.__module__}.{function.__name__}",
                        "statement": statement,
                        "parameters": parameters,
                        "cutoff": at,
                        "distribution": distribution,
                        "returned_rows": [list(row) for row in returned],
                        "relation_bytes": connection.exec_driver_sql(
                            "SELECT pg_relation_size(to_regclass(%(table)s))",
                            {"table": table},
                        ).scalar_one(),
                    },
                )
                for repetition in ("first-explain", "repeat-explain"):
                    plan = connection.exec_driver_sql(
                        "EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS, FORMAT JSON) " + statement,
                        parameters,
                    ).scalar_one()
                    assert isinstance(plan, list) and plan and "Plan" in plan[0]
                    _write(output / f"{prefix}-{repetition}.json", plan)
                observed.append({"table": table, "scenario": scenario, "eligible_rows": expected})
        _write(
            output / "complete.json",
            {
                "status": "measured",
                "selections": observed,
                "explain_files": 12,
                "cache_note": (
                    "Seed, ANALYZE, inventory and selected-row read warm caches; not cold-start."
                ),
                "index_decision": "No index shape or latency threshold is asserted.",
            },
        )
    # The existing fixture drops only its freshly named disposable database.
    # No global purge, DELETE, DROP SCHEMA or production schema alteration occurs.
