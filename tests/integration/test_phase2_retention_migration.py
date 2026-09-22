"""Populated additive0028, immutable old bytes and exact guard restoration."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from trading212_domain import build_synthetic_identity
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.xray_service import PostgresXrayService
from trading212_security.principals import Principal, Scope
from trading212_worker.seed import seed_materialized_synthetic
from trading212_worker.xray_fixture import XRAY_AT
from trading212_worker.xray_seed import XRAY_CURSOR_KEY, seed_xray_scenario

from tests.integration.test_migrations import _database_url
from tests.integration.test_risk_migration_upgrade import fingerprints
from tests.integration.test_xray_reads_postgres import XrayReadCase, company

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def test_populated_0027_repeat_parity_and_exact_downgrade_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "t212pi_phase2_physical_" + uuid4().hex[:12]
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
        command.upgrade(config, "20260915_0027")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        legacy = MetaData()
        legacy.reflect(bind=engine)
        signatures = (
            "source_retention_work_guard()",
            "source_expiry_guard()",
            "historical_retention_guard()",
            "historical_retention_write(text,jsonb,jsonb)",
            "xray_retention_guard()",
            "xray_payloads_pending(uuid)",
            "enrichment_retention_guard()",
        )
        with engine.connect() as connection:
            guards = {
                name: connection.scalar(
                    text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": name}
                )
                for name in signatures
            }
        before = fingerprints(engine, legacy)
        command.upgrade(config, "20260915_0028")
        command.upgrade(config, "20260915_0028")
        assert fingerprints(engine, legacy) == before
        assert set(inspect(engine).get_table_names()) == set(legacy.tables) | {
            "xray_physical_state",
            "historical_physical_runs",
            "historical_composite_physical",
            "historical_composite_erasures",
            "xray_retained_sources",
            "historical_retained_sources",
            "phase2_retention_sweeps",
            "source_retention_dispatch",
        }
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM xray_physical_state s WHERE s.payl"
                        "oad_rows<>phase2_xray_rows_oracle(s.input_id)"
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM historical_physical_runs s WHERE s"
                        ".child_rows<>phase2_historical_rows_oracle(s.run_id)"
                    )
                )
                == 0
            )
        sessions = create_session_factory(engine)
        seed = asyncio.run(seed_xray_scenario(sessions, app_environment="test"))
        identity = build_synthetic_identity()
        principal = Principal(
            str(identity.principal.id),
            str(identity.owner.id),
            "local.synthetic",
            "synthetic-owner",
            frozenset(Scope),
            XRAY_AT - timedelta(minutes=1),
            XRAY_AT + timedelta(days=800),
        )
        service = PostgresXrayService(
            sessions=sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: XRAY_AT
        )
        view = asyncio.run(
            company(XrayReadCase(engine, sessions, service, principal, [XRAY_AT], seed))
        )
        assert view.context.input_snapshot_id
        before = fingerprints(engine, legacy)
        command.downgrade(config, "20260915_0027")
        assert fingerprints(engine, legacy) == before
        with engine.connect() as connection:
            for signature, expected in guards.items():
                assert (
                    connection.scalar(
                        text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"),
                        {"name": signature},
                    )
                    == expected
                )
        command.upgrade(config, "20260915_0028")
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM xray_physical_state WHERE payload_rows>0")
                )
                > 0
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM xray_physical_state s WHERE s.payl"
                        "oad_rows<>phase2_xray_rows_oracle(s.input_id)"
                    )
                )
                == 0
            )
            assert connection.scalar(text("SELECT count(*) FROM xray_retained_sources")) > 0
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO phase2_retention_sweeps(family,scope_id,aft"
                    "er_id) VALUES('price','00000000-0000-0000-0000-00000000"
                    "0000',:after)"
                ),
                {"after": uuid4()},
            )
        with pytest.raises(DBAPIError, match="Finish Phase2 retention"):
            command.downgrade(config, "20260915_0027")
        with engine.begin() as connection:
            connection.execute(text("UPDATE phase2_retention_sweeps SET after_id=NULL"))
        command.upgrade(config, "head")
        command.check(config)
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
