#!/usr/bin/env python3
"""Serve the real API over a deterministic persisted mismatch E2E fixture."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from trading212_api.main import create_app
from trading212_domain import build_synthetic_identity
from trading212_persistence import create_database_engine
from trading212_persistence.models import SourceRecordModel, TransactionModel
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.scenarios import persist_quantity_cash_mismatch_scenario
from trading212_worker.seed import SEED_TIME, seed_materialized_synthetic

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATABASE_NAME = "portfolio_web_e2e"
_DEFAULT_DATABASE_URL = (
    f"postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/{_DEFAULT_DATABASE_NAME}"
)
_FIXTURE_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "trading212-portfolio-intelligence/api-backed-browser-e2e",
)
_TARGET_ACTIVITY_COUNT = 65


def _fixture_uuid(name: str) -> UUID:
    return uuid5(_FIXTURE_NAMESPACE, name)


def _reset_default_database(database_url: str) -> None:
    """Recreate only the dedicated local browser-E2E database."""
    parsed = make_url(database_url)
    if parsed.database != _DEFAULT_DATABASE_NAME:
        raise RuntimeError("refusing to reset a non-E2E database")
    admin_engine = create_database_engine(parsed.set(database="postgres"))
    try:
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{_DEFAULT_DATABASE_NAME}" WITH (FORCE)'
            )
            connection.exec_driver_sql(f'CREATE DATABASE "{_DEFAULT_DATABASE_NAME}"')
    finally:
        admin_engine.dispose()


def _persist_large_activity_fixture(
    session: Session,
    *,
    account_id: UUID,
    listing_id: UUID,
    as_of: datetime,
) -> None:
    source_record_id = session.scalar(
        select(SourceRecordModel.id)
        .where(SourceRecordModel.broker_account_id == account_id)
        .order_by(SourceRecordModel.observed_at, SourceRecordModel.id)
        .limit(1)
    )
    if source_record_id is None:
        raise RuntimeError("API-backed browser fixture requires retained source evidence")
    previously_inserted = session.get(
        TransactionModel,
        _fixture_uuid(f"activity:{account_id}:inserted-newer"),
    )
    if previously_inserted is not None:
        session.delete(previously_inserted)
        session.flush()
    existing_count = (
        session.scalar(
            select(func.count())
            .select_from(TransactionModel)
            .where(TransactionModel.broker_account_id == account_id)
        )
        or 0
    )
    for index in range(max(0, _TARGET_ACTIVITY_COUNT - existing_count)):
        sequence = index + 1
        transaction_id = _fixture_uuid(f"activity:{account_id}:{sequence}")
        if session.get(TransactionModel, transaction_id) is not None:
            continue
        session.add(
            TransactionModel(
                id=transaction_id,
                broker_account_id=account_id,
                provider_transaction_id=f"browser-e2e-{sequence:03d}",
                transaction_type="buy" if sequence % 2 else "sell",
                status="posted",
                instrument_listing_id=listing_id,
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                gross_amount=Decimal("100"),
                fees=Decimal("0"),
                taxes=Decimal("0"),
                net_cash_amount=Decimal("-100") if sequence % 2 else Decimal("100"),
                currency="EUR",
                occurred_at=as_of - timedelta(days=30 + sequence),
                settlement_date=None,
                source_record_id=source_record_id,
                mapping_version="browser-e2e-fixture/1.0.0",
                created_at=as_of - timedelta(seconds=1),
            )
        )


def _persist_newer_activity(
    session: Session,
    *,
    account_id: UUID,
    listing_id: UUID,
) -> UUID:
    transaction_id = _fixture_uuid(f"activity:{account_id}:inserted-newer")
    if session.get(TransactionModel, transaction_id) is not None:
        return transaction_id
    source_record_id = session.scalar(
        select(SourceRecordModel.id)
        .where(SourceRecordModel.broker_account_id == account_id)
        .order_by(SourceRecordModel.observed_at, SourceRecordModel.id)
        .limit(1)
    )
    if source_record_id is None:
        raise RuntimeError("API-backed browser fixture requires retained source evidence")
    now = datetime.now(UTC)
    session.add(
        TransactionModel(
            id=transaction_id,
            broker_account_id=account_id,
            provider_transaction_id="browser-e2e-inserted-newer",
            transaction_type="interest",
            status="posted",
            instrument_listing_id=listing_id,
            quantity=None,
            unit_price=None,
            gross_amount=Decimal("1"),
            fees=Decimal("0"),
            taxes=Decimal("0"),
            net_cash_amount=Decimal("1"),
            currency="EUR",
            occurred_at=now + timedelta(days=1),
            settlement_date=None,
            source_record_id=source_record_id,
            mapping_version="browser-e2e-fixture/1.0.0",
            created_at=now,
        )
    )
    return transaction_id


def main() -> None:
    configured_database_url = os.environ.get("TEST_DATABASE_URL")
    database_url = (configured_database_url or _DEFAULT_DATABASE_URL).replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    if not configured_database_url:
        _reset_default_database(database_url)
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
            _persist_large_activity_fixture(
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
        clock=lambda: datetime.now(UTC),
    )

    control_engine = create_database_engine(database_url)

    @app.post("/__e2e__/insert-newer-activity", include_in_schema=False)
    def insert_newer_activity() -> dict[str, str]:
        with Session(control_engine) as session, session.begin():
            transaction_id = _persist_newer_activity(
                session,
                account_id=identity.account.id,
                listing_id=identity.listing.id,
            )
        return {"id": str(transaction_id)}

    @app.post("/__e2e__/reset-newer-activity", include_in_schema=False)
    def reset_newer_activity() -> dict[str, bool]:
        with Session(control_engine) as session, session.begin():
            existing = session.get(
                TransactionModel,
                _fixture_uuid(f"activity:{identity.account.id}:inserted-newer"),
            )
            if existing is not None:
                session.delete(existing)
        return {"reset": True}

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=18_000,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
