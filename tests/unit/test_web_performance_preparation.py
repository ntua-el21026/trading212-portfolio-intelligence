"""Preparation readiness and owned-database teardown, without running the workload."""

from __future__ import annotations

import json
import os
from threading import Event
from typing import Any

import psycopg
import pytest
from sqlalchemy.engine import make_url

from scripts import api_e2e_web_performance as performance
from scripts import run_api_backed_e2e as runner

pytestmark = pytest.mark.unit


def _preparation(prepare: Any) -> tuple[Any, Event]:
    constructor = getattr(performance, "WebPerformancePreparation", None)
    assert constructor is not None, "The background preparation lifecycle is not implemented."
    cleanup_ready = Event()
    cleanup_ready.set()
    return constructor(prepare, cleanup_ready=cleanup_ready), cleanup_ready


def test_preparation_stays_no_store_503_until_complete_metadata_is_ready() -> None:
    entered, release = Event(), Event()
    expected: dict[str, object] = {"holdings": 100, "events": 1000, "verified": "state-test-only"}

    def prepare(_stop: Event) -> dict[str, object]:
        entered.set()
        assert release.wait(2)
        return expected

    preparation, cleanup_ready = _preparation(prepare)
    preparation.start()
    try:
        assert entered.wait(1)
        pending = preparation.response()
        assert pending.status_code == 503
        assert json.loads(pending.body) == {"state": "preparing"}
        assert pending.headers["cache-control"] == "no-store"
        assert pending.headers["retry-after"] == "1"
        assert not cleanup_ready.is_set()
        release.set()
        assert preparation.stop_and_join(timeout=1)
        ready = preparation.response()
        assert ready.status_code == 200
        assert json.loads(ready.body) == expected
        assert ready.headers["cache-control"] == "no-store"
        assert cleanup_ready.is_set()
    finally:
        release.set()
        assert preparation.stop_and_join(timeout=1)


def test_preparation_failure_is_no_store_500_without_exception_payload() -> None:
    def prepare(_stop: Event) -> dict[str, object]:
        raise RuntimeError("PRIVATE_PREPARATION_EXCEPTION_CANARY")

    preparation, cleanup_ready = _preparation(prepare)
    preparation.start()
    assert preparation.stop_and_join(timeout=1)
    failed = preparation.response()
    assert failed.status_code == 500
    assert json.loads(failed.body) == {"state": "failed", "error_type": "RuntimeError"}
    assert failed.headers["cache-control"] == "no-store"
    assert b"PRIVATE_PREPARATION_EXCEPTION_CANARY" not in failed.body
    assert cleanup_ready.is_set()


def test_teardown_signals_preparation_and_joins_before_allowing_database_cleanup() -> None:
    entered = Event()

    def prepare(stop: Event) -> dict[str, object]:
        entered.set()
        assert stop.wait(2)
        raise InterruptedError("Synthetic cancellation after observing stop.")

    preparation, cleanup_ready = _preparation(prepare)
    preparation.start()
    try:
        assert entered.wait(1)
        assert not cleanup_ready.is_set()
        assert preparation.stop_and_join(timeout=1)
        assert cleanup_ready.is_set()
        assert preparation.response().status_code == 500
    finally:
        assert preparation.stop_and_join(timeout=1)


def test_failed_join_keeps_database_cleanup_denied_until_that_worker_exits() -> None:
    entered, release = Event(), Event()

    def prepare(_stop: Event) -> dict[str, object]:
        entered.set()
        assert release.wait(2)
        return {"state": "synthetic-uncooperative-worker"}

    preparation, cleanup_ready = _preparation(prepare)
    preparation.start()
    try:
        assert entered.wait(1)
        assert preparation.stop_and_join(timeout=0.001) is False
        assert not cleanup_ready.is_set()
    finally:
        release.set()
        assert preparation.stop_and_join(timeout=1)
        assert cleanup_ready.is_set()


@pytest.mark.parametrize("joined", [False, True])
def test_disposable_database_drops_only_after_preparation_join_or_retains_exact_name(
    monkeypatch: pytest.MonkeyPatch, joined: bool
) -> None:
    commands: list[str] = []

    class Admin:
        def __enter__(self) -> Admin:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: Any) -> None:
            commands.append(statement.as_string())

    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: Admin())
    monkeypatch.setenv("DATABASE_URL", "previous-fixture-environment")
    cleanup_ready = Event()
    if joined:
        cleanup_ready.set()
    name: str | None = None

    def exercise() -> None:
        nonlocal name
        with runner._disposable_database(
            "postgresql+psycopg://portfolio:portfolio@127.0.0.1:55432/portfolio",
            cleanup_ready=cleanup_ready.is_set,
        ) as database_url:
            name = make_url(database_url).database
            assert name is not None and name.startswith("t212pi_web_e2e_")

    if joined:
        exercise()
    else:
        with pytest.raises(RuntimeError) as caught:
            exercise()
        assert name is not None and name in str(caught.value)
    assert commands[0].startswith('CREATE DATABASE "t212pi_web_e2e_')
    assert sum(command.startswith("DROP DATABASE") for command in commands) == int(joined)
    assert len(commands) == 1 + int(joined)
    assert os.environ["DATABASE_URL"] == "previous-fixture-environment"
