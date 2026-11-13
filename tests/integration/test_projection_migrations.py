"""0022 preserves old exact observations; repetition/parity and safe downgrade policy."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from trading212_persistence.base import Base
from trading212_persistence.models import PositionObservationModel, SourceRecordModel

from tests.integration.test_migrations import _add_identity_graph
from tests.integration.test_migrations import database_engine as database_engine
from tests.integration.test_projection_definitions_postgres import ProjectionDefinitionCase
from tests.integration.test_projection_definitions_postgres import (
    projection_definition_case as projection_definition_case,
)

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def config_for(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Config:
    url = engine.url.render_as_string(hide_password=False)
    # env.py prioritizes DATABASE_URL; pin this isolated, disposable test DB.
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_old_exact_financial_rows_survive_upgrade_repeat_parity_and_empty_downgrade(
    database_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(database_engine, monkeypatch)
    command.downgrade(config, "20260915_0021")
    at = datetime(2026, 8, 31, 12, 34, 56, 123456, tzinfo=UTC)
    amount = Decimal("12345678901234567890.123456789012345678")
    with Session(database_engine) as session, session.begin():
        _, _, account, _, listing, run = _add_identity_graph(session)
        source = SourceRecordModel(
            id=uuid4(),
            ingestion_run_id=run,
            broker_account_id=account,
            provider="synthetic",
            capability="portfolio_positions",
            provider_record_type="position",
            provider_record_id="projection-migration-baseline",
            payload_fingerprint="a" * 64,
            observed_at=at,
            schema_version="1.0.0",
        )
        session.add(source)
        session.flush()
        observation = PositionObservationModel(
            broker_account_id=account,
            listing_id=listing,
            quantity=amount,
            valuation_currency="EUR",
            observed_at=at,
            source_record_id=source.id,
        )
        session.add(observation)
        session.flush()
        identifier = observation.id
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)
    with Session(database_engine) as session:
        row = session.get(PositionObservationModel, identifier)
        assert row is not None
        assert row.quantity == amount and row.observed_at == at
    assert set(inspect(database_engine).get_table_names()) - {"alembic_version"} == set(
        Base.metadata.tables
    )
    command.downgrade(config, "20260915_0021")
    with Session(database_engine) as session:
        row = session.get(PositionObservationModel, identifier)
        assert row is not None
        assert row.quantity == amount and row.observed_at == at
    command.upgrade(config, "head")
    command.check(config)


def test_nonempty_projection_definitions_prevent_destructive_downgrade(
    projection_definition_case: ProjectionDefinitionCase,
    database_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = projection_definition_case
    c.store.publish_assumption_set(c.session, c.auth, c.assumption())
    c.session.commit()
    config = config_for(database_engine, monkeypatch)
    with pytest.raises(DBAPIError, match="Projection metadata prevents downgrade"):
        command.downgrade(config, "20260915_0021")
    with database_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261113_0034"
    command.upgrade(config, "head")
    command.check(config)
