"""Additive premium cleanup preserves populated 0025 and exact old-column bytes."""

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


def test_populated_0025_preservation_repeat_parity_and_guard_restoration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "t212pi_premium_cleanup_upgrade_" + uuid4().hex[:12]
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
        command.upgrade(config, "20260915_0025")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        legacy = MetaData()
        legacy.reflect(bind=engine)
        signatures = (
            "scenario_source_guard()",
            "scenario_source_copy_pending(uuid)",
            "scenario_retention_copy_guard()",
            "scenario_capacity_complete()",
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
        command.upgrade(config, "20260915_0026")
        command.upgrade(config, "20260915_0026")
        assert fingerprints(engine, legacy) == before
        assert set(inspect(engine).get_table_names()) == set(legacy.tables) | {
            "premium_retention_scans",
            "premium_retention_sweeps",
            "premium_retained_parents",
            "premium_retention_state",
        }
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260915_0026"
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM premium_retention_state WHERE kind "
                        "NOT IN ('risk','scenario')"
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE "
                        "tgname='z_premium_retention_counter' AND NOT tgisinternal"
                    )
                )
                == 15
            )
            indices = set(
                connection.scalars(
                    text("SELECT indexname FROM pg_indexes WHERE indexname LIKE 'ix_sensitivity_%'")
                )
            )
            assert {
                "ix_sensitivity_evidence_owned",
                "ix_sensitivity_version_owned",
                "ix_sensitivity_version_payload",
                "ix_sensitivity_observation_pending",
            } <= indices
        command.downgrade(config, "20260915_0025")
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
        command.upgrade(config, "20260915_0026")
        # A live global continuation is operational work, so downgrade refuses
        # until it has actually completed instead of silently losing its cursor.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO premium_retention_sweeps(scope_id,family,after_id,deferred) "
                    "VALUES('00000000-0000-0000-0000-000000000000','scenario',:after,false)"
                ),
                {"after": uuid4()},
            )
        with pytest.raises(
            DBAPIError, match="Premium cleanup continuation must finish before downgrade"
        ):
            command.downgrade(config, "20260915_0025")
        with engine.begin() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260915_0026"
            )
            connection.execute(
                text("UPDATE premium_retention_sweeps SET after_id=NULL,deferred=false")
            )
        command.upgrade(config, "head")
        command.check(config)
    finally:
        if engine is not None:
            engine.dispose()
        assert name.startswith("t212pi_premium_cleanup_upgrade_")
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
