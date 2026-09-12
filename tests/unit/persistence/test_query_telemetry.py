"""Cursor timing observes failures and owns only the explicitly selected engine."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from trading212_observability import OperationalMetrics
from trading212_persistence import create_database_engine
from trading212_persistence.query_telemetry import DatabaseQueryTiming


def test_success_failure_and_next_statement_each_end_one_observation() -> None:
    engine = create_engine("sqlite:///:memory:")
    untouched = create_engine("sqlite:///:memory:")
    samples: list[tuple[float, bool]] = []
    metrics = OperationalMetrics(service="query-test")

    def observe(duration: float, failed: bool) -> None:
        samples.append((duration, failed))
        metrics.observe_database_query(duration, failed)

    timing = DatabaseQueryTiming(engine, observe)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT :private"), {"private": "QUERY-CANARY"})
                == "QUERY-CANARY"
            )
            with pytest.raises(DBAPIError):
                connection.execute(text("SELECT * FROM missing_private_table"))
            connection.rollback()
            assert connection.scalar(text("SELECT 7")) == 7
        with untouched.connect() as connection:
            assert connection.scalar(text("SELECT 9")) == 9
        assert [failed for _, failed in samples] == [False, True, False]
        assert all(duration >= 0 for duration, _ in samples)
        rendered = metrics.render().decode()
        assert 'database_query_duration_seconds_count{outcome="success"} 2.0' in rendered
        assert 'database_query_duration_seconds_count{outcome="failure"} 1.0' in rendered
        for private in ("QUERY-CANARY", "missing_private_table", "SELECT", "private", "table="):
            assert private not in rendered
        assert not timing._starts
    finally:
        timing.close()
        engine.dispose()
        untouched.dispose()


def test_disposal_detaches_query_listeners_and_explicit_close_removes_lifecycle_hook() -> None:
    engine = create_engine("sqlite:///:memory:")
    samples: list[tuple[float, bool]] = []
    timing = DatabaseQueryTiming(
        engine, lambda duration, failed: samples.append((duration, failed))
    )
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    engine.dispose()
    for name, callback in (
        ("before_cursor_execute", timing._before),
        ("after_cursor_execute", timing._after),
        ("handle_error", timing._error),
    ):
        assert not event.contains(engine, name, callback)
    assert timing._observer is None and not timing._starts
    # SQLAlchemy permits reuse after disposal. Monitoring stays detached until an
    # explicit new adapter is installed; a stale registry must receive no samples.
    with engine.connect() as connection:
        connection.execute(text("SELECT 2"))
    assert len(samples) == 1
    timing.close()
    timing.close()
    assert not event.contains(engine, "engine_disposed", timing._disposed)
    engine.dispose()


def test_observer_failure_does_not_replace_success_or_database_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_engine("sqlite:///:memory:")

    def broken(_duration: float, _failed: bool) -> None:
        raise RuntimeError("PRIVATE-OBSERVER-CANARY")

    timing = DatabaseQueryTiming(engine, broken)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 3")) == 3
            with pytest.raises(DBAPIError):
                connection.execute(text("SELECT * FROM missing_telemetry_relation"))
        assert "database_query_observer_failed" in caplog.text
        assert "PRIVATE-OBSERVER-CANARY" not in caplog.text
        assert not timing._starts
    finally:
        timing.close()
        engine.dispose()


def test_factory_instrumentation_is_opt_in_without_connecting() -> None:
    url = "postgresql+psycopg://portfolio:portfolio@localhost/unused"
    plain = create_database_engine(url)
    measured = create_database_engine(url, query_observer=lambda _duration, _failed: None)
    try:
        assert not plain.dispatch.before_cursor_execute
        assert measured.dispatch.before_cursor_execute
    finally:
        plain.dispose()
        measured.dispose()
    assert not measured.dispatch.before_cursor_execute
