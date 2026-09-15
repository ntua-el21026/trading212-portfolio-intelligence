"""Populated scenario schema upgrade preserves every legacy column and restores old guards."""

import asyncio
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import make_url
from trading212_persistence import create_database_engine
from trading212_worker.seed import seed_materialized_synthetic

from tests.integration.test_migrations import _database_url
from tests.integration.test_risk_migration_upgrade import fingerprints

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def test_populated_0020_upgrade_preserves_all_columns_and_restores_guard_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "t212pi_report_v3_upgrade_" + uuid4().hex[:12]
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
        command.upgrade(config, "20260915_0020")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        legacy = MetaData()
        legacy.reflect(bind=engine)
        with engine.connect() as connection:
            prior_guard = connection.scalar(
                text(
                    "SELECT pg_get_functiondef("
                    "'report_premium_restricted(uuid,uuid,timestamptz)'::regprocedure)"
                )
            )
        before = fingerprints(engine, legacy)
        names = set(inspect(engine).get_table_names())
        assert "scenario_runs" in names and "report_input_snapshots" in names
        command.upgrade(config, "20260915_0021")
        command.upgrade(config, "20260915_0021")
        assert fingerprints(engine, legacy) == before
        assert set(inspect(engine).get_table_names()) == names
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260915_0021"
            )
        command.downgrade(config, "20260915_0020")
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT pg_get_functiondef("
                        "'report_premium_restricted(uuid,uuid,timestamptz)'::regprocedure)"
                    )
                )
                == prior_guard
            )
        assert fingerprints(engine, legacy) == before
        assert set(inspect(engine).get_table_names()) == names
        command.upgrade(config, "20260915_0021")
        command.upgrade(config, "head")
        command.check(config)
    finally:
        if engine is not None:
            engine.dispose()
        assert name.startswith("t212pi_report_v3_upgrade_")
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
