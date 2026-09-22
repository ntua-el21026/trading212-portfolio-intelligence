"""Populated 0026 bytes and empty repeat/downgrade parity for the acquisition seam."""

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


def test_populated_0026_is_unchanged_and_acquisition_metadata_has_schema_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "t212pi_acquisition_upgrade_" + uuid4().hex[:12]
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
        command.upgrade(config, "20260915_0026")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        legacy = MetaData()
        legacy.reflect(bind=engine)
        before = fingerprints(engine, legacy)
        command.upgrade(config, "20260915_0027")
        command.upgrade(config, "20260915_0027")
        assert fingerprints(engine, legacy) == before
        tables = {
            "provider_capability_scopes",
            "provider_capability_grants",
            "provider_acquisition_policies",
            "provider_acquisition_mappings",
            "provider_acquisition_requests",
            "provider_acquisition_days",
            "provider_acquisition_attempts",
            "provider_acquisition_slots",
            "provider_acquisition_publications",
            "provider_acquisition_market_results",
        }
        assert set(inspect(engine).get_table_names()) == set(legacy.tables) | tables
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE tgname='acquisiti"
                        "on_owned' AND NOT tgisinternal"
                    )
                )
                == 9
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE tgname='acquisiti"
                        "on_complete' AND NOT tgisinternal"
                    )
                )
                == 4
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE tgname='acquisiti"
                        "on_publication_complete' AND NOT tgisinternal"
                    )
                )
                == 4
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT acquisition_source_restricted(:owner,'unknown',:"
                        "source,now(),'store')"
                    ),
                    {"owner": uuid4(), "source": uuid4()},
                )
                is True
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT acquisition_source_restricted(:owner,'price',:source,now(),'store')"
                    ),
                    {"owner": uuid4(), "source": uuid4()},
                )
                is True
            )
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE tgname='acquisition_market_result' "
                        "AND NOT tgisinternal"
                    )
                )
                == 1
            )
        command.downgrade(config, "20260915_0026")
        assert fingerprints(engine, legacy) == before
        assert set(inspect(engine).get_table_names()) == set(legacy.tables)
        command.upgrade(config, "head")
        command.check(config)
    finally:
        if engine is not None:
            engine.dispose()
        assert name.startswith("t212pi_acquisition_upgrade_")
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
