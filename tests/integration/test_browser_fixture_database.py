"""Real PostgreSQL isolation for repeated local and CI browser fixture launches."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from trading212_persistence import create_database_engine

from scripts import run_api_backed_e2e as runner

pytestmark = pytest.mark.integration


def _server_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or runner._DEFAULT_DATABASE_URL


@pytest.mark.parametrize("configuration", ["explicit", "plain-postgresql", "default"])
def test_browser_launches_use_fresh_databases_and_preserve_configured_database(
    monkeypatch: pytest.MonkeyPatch, configuration: str
) -> None:
    with runner._disposable_database(_server_url()) as base_url:
        base = create_database_engine(base_url)
        try:
            with base.begin() as connection:
                connection.execute(text("CREATE TABLE preserved_fixture (value text NOT NULL)"))
                connection.execute(text("INSERT INTO preserved_fixture VALUES ('retained')"))
            if configuration == "default":
                monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
                monkeypatch.setattr(runner, "_DEFAULT_DATABASE_URL", base_url)
            else:
                configured_url = base_url
                if configuration == "plain-postgresql":
                    configured_url = configured_url.replace(
                        "postgresql+psycopg://", "postgresql://", 1
                    )
                monkeypatch.setenv("TEST_DATABASE_URL", configured_url)
            launches: list[str] = []

            def serve(database_url: str) -> None:
                assert database_url != base_url
                assert os.environ["DATABASE_URL"] == database_url
                name = make_url(database_url).database
                assert name is not None
                assert name not in launches
                launches.append(name)
                child = create_database_engine(database_url)
                try:
                    with child.begin() as connection:
                        assert inspect(connection).get_table_names() == []
                        assert connection.scalar(text("SELECT current_database()")) == name
                        connection.execute(
                            text("CREATE TABLE previous_viewport_state (id integer)")
                        )
                    if len(launches) == 2:
                        raise RuntimeError("Synthetic browser startup failure")
                finally:
                    child.dispose()

            monkeypatch.setattr(runner, "_serve_fixture", serve)
            runner.main()
            assert os.environ["DATABASE_URL"] == base_url
            with pytest.raises(RuntimeError, match="Synthetic browser startup failure"):
                runner.main()
            assert os.environ["DATABASE_URL"] == base_url
            assert len(launches) == 2
            with base.connect() as connection:
                assert inspect(connection).get_table_names() == ["preserved_fixture"]
                assert connection.scalar(text("SELECT value FROM preserved_fixture")) == "retained"
                for name in launches:
                    assert (
                        connection.scalar(
                            text("SELECT count(*) FROM pg_database WHERE datname = :name"),
                            {"name": name},
                        )
                        == 0
                    )
        finally:
            base.dispose()


def test_failed_browser_database_creation_never_drops_an_existing_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with runner._disposable_database(_server_url()) as existing_url:
        name = make_url(existing_url).database
        assert name is not None
        collision = UUID(name.removeprefix("t212pi_web_e2e_"))
        monkeypatch.setattr(runner, "uuid4", lambda: collision)
        with (
            pytest.raises(psycopg.errors.DuplicateDatabase),
            runner._disposable_database(existing_url),
        ):
            pytest.fail("A conflicting database must not be reused")
        assert os.environ["DATABASE_URL"] == existing_url
        engine = create_database_engine(existing_url)
        try:
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT current_database()")) == name
        finally:
            engine.dispose()


def test_uvicorn_sigterm_cleans_up_only_its_disposable_database(tmp_path: Path) -> None:
    with runner._disposable_database(_server_url()) as base_url:
        ready = tmp_path / "fixture-database.txt"
        child = """
import sys
from contextlib import asynccontextmanager
from pathlib import Path
import uvicorn
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from scripts import run_api_backed_e2e as runner

def serve(database_url):
    @asynccontextmanager
    async def lifespan(app):
        Path(sys.argv[1]).write_text(make_url(database_url).database)
        yield
    uvicorn.run(FastAPI(lifespan=lifespan), host='127.0.0.1', port=0, log_level='error')

runner._serve_fixture = serve
runner.main()
"""
        process = subprocess.Popen(  # noqa: S603 - fixed child program and pytest-owned output path
            [sys.executable, "-c", child, str(ready)],
            env={**os.environ, "TEST_DATABASE_URL": base_url, "DATABASE_URL": base_url},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 15
            while not ready.is_file() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert ready.is_file(), "Synthetic Uvicorn fixture did not start"
            name = ready.read_text()
            assert name != make_url(base_url).database
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=15)
            assert process.returncode == 128 + signal.SIGTERM
            base = create_database_engine(base_url)
            try:
                with base.connect() as connection:
                    assert (
                        connection.scalar(text("SELECT current_database()"))
                        == make_url(base_url).database
                    )
                    assert (
                        connection.scalar(
                            text("SELECT count(*) FROM pg_database WHERE datname = :name"),
                            {"name": name},
                        )
                        == 0
                    )
            finally:
                base.dispose()
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
