"""Idempotently seed deterministic synthetic identity/reference data."""

from __future__ import annotations

import os

from sqlalchemy.dialects.postgresql import insert
from trading212_domain import build_synthetic_identity

from .database import create_database_engine, create_session_factory
from .mappers import (
    account_to_model,
    connection_to_model,
    instrument_to_model,
    listing_to_model,
    owner_to_model,
    principal_to_model,
)


def seed_synthetic(database_url: str, *, app_environment: str) -> None:
    if app_environment not in {"local", "test"}:
        raise RuntimeError("synthetic seed is restricted to local/test environments")
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    fixture = build_synthetic_identity()
    models = (
        owner_to_model(fixture.owner),
        principal_to_model(fixture.principal),
        connection_to_model(fixture.connection),
        account_to_model(fixture.account),
        instrument_to_model(fixture.instrument, observed_at=fixture.listing.valid_from),
        listing_to_model(fixture.listing),
    )
    with session_factory.begin() as session:
        for model in models:
            values = {
                column.name: getattr(model, column.name)
                for column in model.__table__.columns
                if getattr(model, column.name) is not None or column.server_default is None
            }
            statement = insert(type(model)).values(**values).on_conflict_do_nothing()
            session.execute(statement)
    engine.dispose()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    seed_synthetic(database_url, app_environment=os.environ.get("T212PI_ENVIRONMENT", "local"))


if __name__ == "__main__":
    main()
