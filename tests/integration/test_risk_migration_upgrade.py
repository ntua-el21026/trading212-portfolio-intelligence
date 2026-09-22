"""Populated 0016 through current premium head preserves legacy bytes and canonical replay."""

import asyncio
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, MetaData, Text, func, inspect, select
from sqlalchemy.engine import make_url
from trading212_application import historical as app
from trading212_domain import historical as d
from trading212_domain import historical_results as results
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_worker.historical_seed import (
    CURSOR_KEY,
    history_principal,
    seed_historical_scenarios,
)
from trading212_worker.seed import seed_materialized_synthetic

from tests.integration.test_historical_seed import NOW, window
from tests.integration.test_migrations import _database_url

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def fingerprints(engine: Engine, legacy: MetaData) -> dict[str, tuple[int, str]]:
    result = {}
    with engine.connect() as connection:
        for name, table in sorted(legacy.tables.items()):
            if name == "alembic_version":
                continue
            # The retained projection names exactly the pre-upgrade columns. PostgreSQL
            # serializes NUMERIC directly to text; Python never parses financial JSON numbers.
            projection = select(*table.columns).subquery()
            records = sorted(
                connection.scalars(select(func.row_to_json(projection.table_valued()).cast(Text)))
            )
            digest = sha256()
            for record in records:
                payload = record.encode("utf-8")
                digest.update(len(payload).to_bytes(8, "big"))
                digest.update(payload)
            result[name] = len(records), digest.hexdigest()
    return result


def test_populated_phase2_upgrade_keeps_rows_values_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "t212pi_risk_upgrade_" + uuid4().hex[:12]
    parsed = make_url(_database_url())
    admin = parsed.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    url = parsed.set(database=name).render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    engine = None
    try:
        monkeypatch.setenv("DATABASE_URL", url)
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "20260911_0016")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        sessions = create_session_factory(engine)
        ids = asyncio.run(seed_historical_scenarios(sessions, app_environment="test"))
        service = PostgresHistoricalService(
            sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW
        )
        query = app.PerformanceSummaryQuery(
            window=window("annual"),
            options=results.PerformanceOptions(frequency=d.HistoricalFrequency.DAILY),
        )
        original = asyncio.run(
            service.get_performance_summary(
                history_principal(NOW), ids["annual_account_id"], query=query
            )
        )
        legacy = MetaData()
        legacy.reflect(bind=engine)
        before = fingerprints(engine, legacy)
        assert len(before) == 212
        assert before["historical_input_snapshots"][0] > 0
        assert before["historical_analytics_runs"][0] > 0
        command.upgrade(config, "20260914_0017")
        command.upgrade(config, "head")
        command.check(config)
        assert fingerprints(engine, legacy) == before
        assert len(inspect(engine).get_table_names()) - 1 == 344
        replay = asyncio.run(
            service.get_performance_summary(
                history_principal(NOW),
                ids["annual_account_id"],
                query=app.PerformanceSummaryQuery(
                    window=query.window,
                    options=query.options,
                    input_snapshot_id=original.context.input_snapshot_id,
                ),
            )
        )
        assert replay.summary == original.summary and replay.series == original.series
        assert replay.context.content_digest == original.context.content_digest
    finally:
        if engine is not None:
            engine.dispose()
        assert name.startswith("t212pi_risk_upgrade_")
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
