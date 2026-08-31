#!/usr/bin/env python3
"""Serve the real API over a deterministic persisted mismatch E2E fixture."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session
from trading212_api.main import create_app
from trading212_domain import build_synthetic_identity
from trading212_persistence import create_database_engine
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.scenarios import persist_quantity_cash_mismatch_scenario
from trading212_worker.seed import SEED_TIME, seed_materialized_synthetic

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATABASE_URL = "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio"


def main() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL", _DEFAULT_DATABASE_URL).replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    migration_config = Config(str(_REPOSITORY_ROOT / "alembic.ini"))
    migration_config.set_main_option("script_location", str(_REPOSITORY_ROOT / "migrations"))
    migration_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(migration_config, "head")
    asyncio.run(seed_materialized_synthetic(database_url, app_environment="test"))

    engine = create_database_engine(database_url)
    identity = build_synthetic_identity()
    scenario_time = max(
        SEED_TIME,
        datetime.now(UTC).replace(microsecond=0),
    )
    try:
        with Session(engine) as session, session.begin():
            persist_quantity_cash_mismatch_scenario(
                session,
                account_id=identity.account.id,
                listing_id=identity.listing.id,
                as_of=scenario_time,
            )
    finally:
        engine.dispose()

    os.environ["DATABASE_URL"] = database_url
    os.environ["CELERY_BROKER_URL"] = "memory://"
    app = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            cookie_secure=False,
            allowed_origins=("http://127.0.0.1:3001",),
            allowed_hosts=("127.0.0.1", "localhost"),
        ),
        clock=lambda: scenario_time,
    )
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=18_000,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
