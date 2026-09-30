"""Test-only reversible clock substitution in one disposable PostgreSQL database."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import text

from tests.integration.test_xray_reads_postgres import XrayReadCase


@contextmanager
def controlled_aggregate_retention_clock(
    case: XrayReadCase, now: list[datetime]
) -> Iterator[Callable[[datetime], None]]:
    """Control the clock input, preserving every guard in this disposable DB.

    Waiting thirty days for real expiry is neither bounded nor deterministic. Replace
    only clock calls in the exact trigger function, then restore its definition.
    The test still exercises all state, quota, identity and deadline comparisons.
    No production function exposes a caller-controlled clock.
    """
    definition = text("SELECT pg_get_functiondef('aggregate_retention_guard()'::regprocedure)")
    with case.engine.begin() as connection:
        original = connection.scalar(definition)
        assert isinstance(original, str) and "clock_timestamp()" in original
        connection.exec_driver_sql("CREATE SCHEMA aggregate_retention_test_clock")
        connection.exec_driver_sql(
            "CREATE TABLE aggregate_retention_test_clock.instant "
            "(id integer PRIMARY KEY CHECK(id=1), at timestamptz NOT NULL)"
        )
        connection.execute(
            text("INSERT INTO aggregate_retention_test_clock.instant VALUES(1,:at)"), {"at": now[0]}
        )
        connection.exec_driver_sql(
            "CREATE FUNCTION aggregate_retention_test_clock.now() RETURNS timestamptz "
            "LANGUAGE sql STABLE AS $$ SELECT at FROM aggregate_retention_test_clock.instant "
            "WHERE id=1 $$"
        )
        controlled = original.replace("clock_timestamp()", "aggregate_retention_test_clock.now()")
        assert (
            controlled.replace("aggregate_retention_test_clock.now()", "clock_timestamp()")
            == original
        )
        connection.exec_driver_sql(controlled)

    def advance(value: datetime) -> None:
        now[0] = value
        with case.engine.begin() as connection:
            connection.execute(
                text("UPDATE aggregate_retention_test_clock.instant SET at=:at WHERE id=1"),
                {"at": value},
            )

    try:
        yield advance
    finally:
        with case.engine.begin() as connection:
            connection.exec_driver_sql(original)
            assert connection.scalar(definition) == original
            connection.exec_driver_sql("DROP FUNCTION aggregate_retention_test_clock.now()")
            connection.exec_driver_sql("DROP TABLE aggregate_retention_test_clock.instant")
            connection.exec_driver_sql("DROP SCHEMA aggregate_retention_test_clock")
