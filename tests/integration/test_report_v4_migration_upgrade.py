"""Populated projection schema remains byte-exact across the explicit V4 upgrade."""

import asyncio
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from trading212_persistence import create_database_engine
from trading212_worker.seed import seed_materialized_synthetic

from tests.integration.test_migrations import _database_url
from tests.integration.test_risk_migration_upgrade import fingerprints

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


_SIGNATURES = (
    "report_premium_restricted(uuid,uuid,timestamptz)",
    "report_premium_dependency_guard()",
    "report_premium_capture_complete()",
    "report_command_contract_guard()",
    "report_premium_copy_guard()",
    "projection_parent_has_copies(uuid,text,uuid)",
    "projection_retention_guard()",
    "projection_retained_source_guard()",
    "report_capture_pending(uuid,uuid)",
    "report_retention_guard()",
)


def test_populated_0022_upgrade_repeat_parity_and_exact_guard_restoration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "t212pi_report_v4_upgrade_" + uuid4().hex[:12]
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
        command.upgrade(config, "20260915_0022")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        legacy = MetaData()
        legacy.reflect(bind=engine)
        with engine.connect() as connection:
            old_guards = {
                signature: connection.scalar(
                    text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"),
                    {"name": signature},
                )
                for signature in _SIGNATURES
            }
        before = fingerprints(engine, legacy)
        names = set(inspect(engine).get_table_names())
        assert "projection_runs" in names
        command.upgrade(config, "20260915_0023")
        command.upgrade(config, "20260915_0023")
        assert fingerprints(engine, legacy) == before
        assert set(inspect(engine).get_table_names()) == names
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260915_0023"
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.triggers WHERE trigg"
                        "er_name='reports_premium_copy_guard' AND event_object_table "
                        "LIKE 'projection_%' AND event_manipulation='DELETE'"
                    )
                )
                == 18
            )
            assert (
                connection.scalar(
                    text("SELECT projection_report_sources_restricted(:run,CURRENT_TIMESTAMP)"),
                    {"run": uuid4()},
                )
                is True
            )
        command.downgrade(config, "20260915_0022")
        with engine.connect() as connection:
            for signature, previous in old_guards.items():
                assert (
                    connection.scalar(
                        text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"),
                        {"name": signature},
                    )
                    == previous
                )
        assert fingerprints(engine, legacy) == before
        command.upgrade(config, "20260915_0023")
        # A pending normalized V4-only continuation cannot silently disappear on
        # downgrade. No real report payload or current source authority is forged.
        identifier = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO projection_retention_sweeps
                (id,key,owner_id,purpose,target_kind,target_id,after_id,deferred,policy_epoch,evaluated_at)
                VALUES (:id,:key,NULL,'report_expiry',NULL,NULL,NULL,false,0,CURRENT_TIMESTAMP)"""),
                {"id": identifier, "key": "report_expiry:test-downgrade"},
            )
        with pytest.raises(DBAPIError, match="must be absent before downgrade"):
            command.downgrade(config, "20260915_0022")
        with engine.begin() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260915_0023"
            )
            connection.execute(
                text("DELETE FROM projection_retention_sweeps WHERE id=:id"), {"id": identifier}
            )
        command.upgrade(config, "head")
        command.check(config)
    finally:
        if engine is not None:
            engine.dispose()
        assert name.startswith("t212pi_report_v4_upgrade_")
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
