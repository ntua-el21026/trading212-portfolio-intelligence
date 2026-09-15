"""Additive legacy maintenance metadata preserves populated 0024 and exact guards."""

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


def test_populated_0024_preservation_repeat_parity_and_guard_restoration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "t212pi_legacy_report_upgrade_" + uuid4().hex[:12]
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
        command.upgrade(config, "20260915_0024")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        legacy = MetaData()
        legacy.reflect(bind=engine)
        signatures = (
            "report_owned_guard()",
            "report_retention_guard()",
            "report_source_copy_guard()",
        )
        with engine.connect() as connection:
            guards = {
                signature: connection.scalar(
                    text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"),
                    {"name": signature},
                )
                for signature in signatures
            }
        before = fingerprints(engine, legacy)
        command.upgrade(config, "20260915_0025")
        command.upgrade(config, "20260915_0025")
        assert fingerprints(engine, legacy) == before
        assert set(inspect(engine).get_table_names()) == set(legacy.tables) | {
            "legacy_report_retention_scans",
            "legacy_report_retention_sweeps",
        }
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260915_0025"
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM report_input_dependencies WHERE "
                        "copy_pending IS DISTINCT FROM "
                        "report_capture_pending(owner_id,input_id)"
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE "
                        "tgname='z_legacy_report_retention_epoch' AND NOT tgisinternal"
                    )
                )
                == 3
            )
            indexes = tuple(
                connection.scalars(
                    text(
                        "SELECT indexdef FROM pg_indexes WHERE indexname IN ('ix_report_s"
                        "ource_pending','ix_report_source_pending_input','ix_report_legac"
                        "y_pending')"
                    )
                )
            )
            assert len(indexes) == 3
            assert any(
                "WHERE" in definition and "copy_pending" in definition for definition in indexes
            )
            # Missing/foreign witnesses cannot independently authorize a purge.
            assert (
                connection.scalar(
                    text(
                        "SELECT legacy_report_witness_restricted(:owner,:input,'physical'"
                        ",:source,CURRENT_TIMESTAMP)"
                    ),
                    {"owner": uuid4(), "input": uuid4(), "source": uuid4()},
                )
                is False
            )
        command.downgrade(config, "20260915_0024")
        assert fingerprints(engine, legacy) == before
        with engine.connect() as connection:
            for signature, previous in guards.items():
                assert (
                    connection.scalar(
                        text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"),
                        {"name": signature},
                    )
                    == previous
                )
        command.upgrade(config, "20260915_0025")
        # A live global continuation is operational work, so downgrade refuses
        # until it has actually completed instead of silently losing its cursor.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO legacy_report_retention_sweeps(id,after_id,deferred) "
                    "VALUES(1,:after,false)"
                ),
                {"after": uuid4()},
            )
        with pytest.raises(DBAPIError, match="cleanup must finish"):
            command.downgrade(config, "20260915_0024")
        with engine.begin() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260915_0025"
            )
            connection.execute(
                text(
                    "UPDATE legacy_report_retention_sweeps SET "
                    "after_id=NULL,deferred=false WHERE id=1"
                )
            )
        command.upgrade(config, "head")
        command.check(config)
    finally:
        if engine is not None:
            engine.dispose()
        assert name.startswith("t212pi_legacy_report_upgrade_")
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
