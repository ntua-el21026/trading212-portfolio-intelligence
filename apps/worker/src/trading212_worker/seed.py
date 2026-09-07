"""Materialize the deterministic local/test demo through the production worker path."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from trading212_application.ingestion import IngestionCoordinator, RunMode, RunStatus
from trading212_domain import build_synthetic_identity
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.seed import seed_synthetic

from .materializer import PostgresCanonicalMaterializer
from .postgres_store import PostgresIngestionStore
from .synthetic import SyntheticIngestionProvider
from .target_seed import seed_target_scenarios

SEED_TIME = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
SEED_IDEMPOTENCY_KEY = "synthetic-canonical-seed-v1"


async def seed_materialized_synthetic(database_url: str, *, app_environment: str) -> None:
    """Seed identity and canonical facts idempotently for local/test environments."""

    seed_synthetic(database_url, app_environment=app_environment)
    engine = create_database_engine(database_url)
    sessions = create_session_factory(engine)
    fixture = build_synthetic_identity()
    try:
        run = await IngestionCoordinator(
            provider=SyntheticIngestionProvider(clock=lambda: SEED_TIME),
            store=PostgresIngestionStore(
                sessions,
                provider="synthetic",
                materializer=PostgresCanonicalMaterializer(),
            ),
            clock=lambda: SEED_TIME,
        ).refresh(
            owner_id=str(fixture.owner.id),
            account_id=str(fixture.account.id),
            mode=RunMode.FULL,
            idempotency_key=SEED_IDEMPOTENCY_KEY,
            correlation_id=SEED_IDEMPOTENCY_KEY,
        )
        if run.status is not RunStatus.SUCCEEDED:
            raise RuntimeError("synthetic canonical seed did not complete successfully")
        await seed_target_scenarios(sessions, app_environment=app_environment, at=SEED_TIME)
    finally:
        engine.dispose()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    app_environment = os.environ.get("T212PI_ENVIRONMENT", "local")
    asyncio.run(
        seed_materialized_synthetic(
            database_url,
            app_environment=app_environment,
        )
    )


if __name__ == "__main__":
    main()
