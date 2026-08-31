from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import DateTime, Engine, Numeric, delete, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from trading212_persistence import (
    AccountRepository,
    Base,
    CheckpointRepository,
    SourceRecordRepository,
    UnitOfWork,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    IngestionCheckpointModel,
    IngestionRunModel,
    InstrumentModel,
    ListingModel,
    OwnerModel,
    PositionObservationModel,
    SourceRecordModel,
)

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def _database_url() -> str:
    url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio",
        ),
    )
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture(scope="module")
def database_engine() -> Iterator[Engine]:
    base_url = make_url(_database_url())
    database_name = f"t212pi_migrations_{uuid4().hex[:12]}"
    admin_url = base_url.set(database="postgres")
    admin_dsn = admin_url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    url = base_url.set(database=database_name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        command.check(config)
        engine = create_database_engine(url)
        yield engine
        engine.dispose()
    finally:
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url
        if not database_name.startswith("t212pi_migrations_"):
            raise RuntimeError("refusing to drop an unexpected test database")
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


def _add_identity_graph(session: Session) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    owner_id = uuid4()
    connection_id = uuid4()
    account_id = uuid4()
    instrument_id = uuid4()
    listing_id = uuid4()
    run_id = uuid4()
    session.add_all(
        (
            OwnerModel(id=owner_id, display_name="Migration fixture"),
            InstrumentModel(
                id=instrument_id,
                canonical_name="Synthetic instrument",
                instrument_type="equity",
                isin=None,
            ),
        )
    )
    session.flush()
    session.add_all(
        (
            BrokerConnectionModel(
                id=connection_id,
                owner_id=owner_id,
                provider="synthetic",
                environment="synthetic",
                credential_reference=f"synthetic://{connection_id}",
                status="active",
            ),
            ListingModel(
                id=listing_id,
                instrument_id=instrument_id,
                provider="synthetic",
                environment="synthetic",
                provider_instrument_id=f"instrument-{listing_id}",
                ticker=f"SYN{str(listing_id)[:6]}",
                trading_currency="EUR",
                status="active",
                valid_from=now,
            ),
        )
    )
    session.flush()
    session.add(
        BrokerAccountModel(
            id=account_id,
            connection_id=connection_id,
            provider_account_id=f"account-{account_id}",
            account_type="invest",
            base_currency="EUR",
            display_name="Synthetic",
            status="active",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    session.flush()
    session.add(
        IngestionRunModel(
            id=run_id,
            broker_account_id=account_id,
            capability="portfolio_positions",
            mode="full",
            status="running",
            idempotency_key=f"run-{run_id}",
            correlation_id=f"correlation-{run_id}",
            started_at=now,
        )
    )
    session.flush()
    return owner_id, connection_id, account_id, instrument_id, listing_id, run_id


def test_empty_to_head_is_idempotent_and_matches_metadata(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    actual = set(inspector.get_table_names()) - {"alembic_version"}
    expected = set(Base.metadata.tables)
    assert actual == expected
    with database_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260831_0003"


def test_schema_uses_exact_numeric_and_timezone_aware_columns(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    position_columns = {
        column["name"]: column["type"] for column in inspector.get_columns("position_observations")
    }
    numeric = cast(Numeric[Decimal], position_columns["quantity"])
    assert numeric.precision == 38
    assert numeric.scale == 18
    observed_at_type = cast(DateTime, position_columns["observed_at"])
    assert observed_at_type.timezone is True


def test_decimal_and_utc_round_trip_preserve_values(database_engine: Engine) -> None:
    session = Session(database_engine)
    transaction = session.begin()
    try:
        _, _, account_id, _, listing_id, run_id = _add_identity_graph(session)
        now = datetime(2026, 8, 31, 12, 34, 56, 123456, tzinfo=UTC)
        source_id = uuid4()
        session.add(
            SourceRecordModel(
                id=source_id,
                ingestion_run_id=run_id,
                broker_account_id=account_id,
                provider="synthetic",
                capability="portfolio_positions",
                provider_record_type="position",
                provider_record_id="position-1",
                payload_fingerprint="a" * 64,
                observed_at=now,
                schema_version="1.0.0",
            )
        )
        session.flush()
        expected = Decimal("12345678901234567890.123456789012345678")
        observation = PositionObservationModel(
            broker_account_id=account_id,
            listing_id=listing_id,
            quantity=expected,
            valuation_currency="EUR",
            observed_at=now,
            source_record_id=source_id,
        )
        session.add(observation)
        session.flush()
        session.expire_all()
        loaded = session.get(PositionObservationModel, observation.id)
        assert loaded is not None
        assert loaded.quantity == expected
        assert loaded.observed_at == now
        assert loaded.observed_at.tzinfo is not None
    finally:
        transaction.rollback()
        session.close()


def test_source_record_deduplication_is_idempotent(database_engine: Engine) -> None:
    session = Session(database_engine)
    transaction = session.begin()
    try:
        _, _, account_id, _, _, run_id = _add_identity_graph(session)
        values = {
            "ingestion_run_id": run_id,
            "broker_account_id": account_id,
            "provider": "synthetic",
            "capability": "portfolio_positions",
            "provider_record_type": "position",
            "provider_record_id": "position-dedup",
            "payload_fingerprint": "b" * 64,
            "observed_at": datetime(2026, 8, 31, tzinfo=UTC),
            "schema_version": "1.0.0",
        }
        repository = SourceRecordRepository(session)
        first_id, first_created = repository.insert_idempotent(values.copy())
        second_id, second_created = repository.insert_idempotent(values.copy())
        assert first_id == second_id
        assert first_created is True
        assert second_created is False
        count = session.scalar(
            select(text("count(*)"))
            .select_from(SourceRecordModel)
            .where(SourceRecordModel.payload_fingerprint == "b" * 64)
        )
        assert count == 1
    finally:
        transaction.rollback()
        session.close()


def test_account_repository_enforces_owner_scope(database_engine: Engine) -> None:
    session = Session(database_engine)
    transaction = session.begin()
    try:
        owner_id, _, account_id, _, _, _ = _add_identity_graph(session)
        different_owner_id = uuid4()
        session.add(OwnerModel(id=different_owner_id, display_name="Other owner"))
        session.flush()
        repository = AccountRepository(session)
        assert repository.get_owned(owner_id, account_id) is not None
        assert repository.get_owned(different_owner_id, account_id) is None
        assert tuple(item.id for item in repository.list_owned(owner_id)) == (account_id,)
    finally:
        transaction.rollback()
        session.close()


def test_atomic_rollback_does_not_advance_checkpoint(database_engine: Engine) -> None:
    setup = Session(database_engine)
    try:
        owner_id, _, account_id, instrument_id, listing_id, run_id = _add_identity_graph(setup)
        setup.commit()
        factory = create_session_factory(database_engine)
        with (
            pytest.raises(RuntimeError, match="simulated page failure"),
            UnitOfWork(factory) as unit_of_work,
        ):
            CheckpointRepository(unit_of_work.require_session()).advance(
                account_id=account_id,
                capability="portfolio_positions",
                state={"cursor": "unsafe-to-commit"},
                run_id=run_id,
                coverage_start_at=datetime(2026, 8, 1, tzinfo=UTC),
                coverage_end_at=datetime(2026, 8, 31, tzinfo=UTC),
                coverage_complete=False,
            )
            raise RuntimeError("simulated page failure")
        with Session(database_engine) as verification:
            checkpoint = verification.scalar(
                select(IngestionCheckpointModel).where(
                    IngestionCheckpointModel.broker_account_id == account_id,
                    IngestionCheckpointModel.capability == "portfolio_positions",
                )
            )
            assert checkpoint is None
    finally:
        setup.rollback()
        setup.close()
        with Session(database_engine) as cleanup, cleanup.begin():
            cleanup.execute(delete(OwnerModel).where(OwnerModel.id == owner_id))
            cleanup.execute(delete(ListingModel).where(ListingModel.id == listing_id))
            cleanup.execute(delete(InstrumentModel).where(InstrumentModel.id == instrument_id))


def test_migration_is_current_and_downgrade_policy_is_explicit(database_engine: Engine) -> None:
    del database_engine
    revision = Path("migrations/versions/20260831_0001_baseline_phase_1_schema.py").read_text(
        encoding="utf-8"
    )
    metadata_revision = Path(
        "migrations/versions/20260831_0002_accounting_persistence_metadata.py"
    ).read_text(encoding="utf-8")
    occurrence_revision = Path(
        "migrations/versions/20260831_0003_source_record_occurrences.py"
    ).read_text(encoding="utf-8")
    policy = Path("migrations/README.md").read_text(encoding="utf-8")
    assert "down_revision" in revision
    assert "def downgrade()" in revision
    assert revision.count("op.drop_table(") + metadata_revision.count(
        "op.drop_table("
    ) + occurrence_revision.count("op.drop_table(") == len(Base.metadata.tables)
    assert 'revision: str = "20260831_0002"' in metadata_revision
    assert 'down_revision: str | None = "20260831_0001"' in metadata_revision
    assert 'revision: str = "20260831_0003"' in occurrence_revision
    assert 'down_revision: str | None = "20260831_0002"' in occurrence_revision
    assert 'op.drop_table("source_record_occurrences")' in occurrence_revision
    expected_metadata_drops = {
        'op.drop_column("calculation_runs", "input_ids")',
        'op.drop_column("reconciliation_runs", "quality_state")',
        'op.drop_column("reconciliation_runs", "coverage_complete")',
        'op.drop_column("reconciliation_runs", "coverage_gaps")',
        'op.drop_column("reconciliation_runs", "provenance")',
    }
    assert all(statement in metadata_revision for statement in expected_metadata_drops)
    assert "Production rollbacks are" in policy
    assert "destructive Alembic downgrades are not an operational rollback mechanism" in policy
