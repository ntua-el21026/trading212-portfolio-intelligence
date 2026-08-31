"""Minimal real PostgreSQL integration proof for the P1-01 local stack."""

import os

import psycopg
import pytest


@pytest.mark.integration
def test_postgres_18_is_reachable() -> None:
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://portfolio:portfolio@127.0.0.1:5432/portfolio",
    )
    database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("SHOW server_version")
        version = cursor.fetchone()

    assert version is not None
    assert version[0].startswith("18.")
