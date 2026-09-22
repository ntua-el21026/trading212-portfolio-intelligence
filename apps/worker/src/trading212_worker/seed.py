"""Materialize the deterministic local/test demo through the production worker path."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from trading212_application.ingestion import IngestionCoordinator, RunMode, RunStatus
from trading212_domain import build_synthetic_identity
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.seed import seed_synthetic
from trading212_security.principals import Scope

from .historical_seed import seed_historical_scenarios
from .materializer import PostgresCanonicalMaterializer
from .postgres_store import PostgresIngestionStore
from .report_seed import seed_synthetic_report_grants
from .source_seed import seed_source_scenarios
from .synthetic import SyntheticIngestionProvider
from .synthetic_grants import seed_synthetic_grants
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
        await seed_source_scenarios(sessions, app_environment=app_environment, at=SEED_TIME)
    finally:
        engine.dispose()


async def seed_complete_synthetic(database_url: str, *, app_environment: str) -> None:
    """Seed separate regression, historical and X-ray scenarios through real ingestion."""
    from .xray_seed import seed_xray_scenario

    await seed_materialized_synthetic(database_url, app_environment=app_environment)
    engine = create_database_engine(database_url)
    try:
        await seed_historical_scenarios(
            create_session_factory(engine), app_environment=app_environment
        )
        await seed_xray_scenario(create_session_factory(engine), app_environment=app_environment)
        seed_synthetic_report_grants(
            create_session_factory(engine), app_environment=app_environment, at=SEED_TIME
        )
        seed_synthetic_grants(
            create_session_factory(engine),
            app_environment=app_environment,
            at=SEED_TIME,
            scopes=frozenset(
                {
                    Scope.ALERTS_READ,
                    Scope.ALERTS_WRITE,
                    Scope.RISK_WRITE,
                    Scope.SCENARIOS_WRITE,
                    Scope.PROJECTIONS_WRITE,
                    Scope.GOALS_WRITE,
                    Scope.PREFERENCES_READ,
                    Scope.PREFERENCES_WRITE,
                }
            ),
        )
    finally:
        engine.dispose()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    app_environment = os.environ.get("T212PI_ENVIRONMENT", "local")
    asyncio.run(
        seed_complete_synthetic(
            database_url,
            app_environment=app_environment,
        )
    )


if __name__ == "__main__":
    main()
