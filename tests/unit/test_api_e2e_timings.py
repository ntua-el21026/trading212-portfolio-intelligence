"""Observational diagnostics must not change the real fixture lifecycle."""

from __future__ import annotations

import asyncio
import builtins
import json
import sys
from datetime import datetime
from threading import Event
from typing import cast
from unittest.mock import patch

import pytest
from starlette.types import Message, Receive, Scope, Send

from scripts import api_e2e_timings as timing
from scripts import run_api_backed_e2e as runner


def _rows(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    output = capsys.readouterr().err
    assert "CANARY" not in output
    return [
        cast(dict[str, object], json.loads(line.removeprefix("e2e.timing ")))
        for line in output.splitlines()
    ]


async def _unused_receive() -> Message:
    pytest.fail("Telemetry must never add a receive call")


async def _unused_send(message: Message) -> None:
    pytest.fail("Unexpected ASGI send")


@pytest.mark.parametrize(("value", "expected"), [("0", False), ("1", True)])
def test_explicit_opt_in(value: str, expected: bool) -> None:
    assert timing.timings_enabled(value) is expected


@pytest.mark.parametrize("value", ["", "true", "01", " 1", "CANARY"])
def test_invalid_opt_in_precedes_database_creation(
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("T212PI_E2E_TIMINGS", value)
    with patch.object(runner, "_disposable_database") as database:
        with pytest.raises(ValueError, match="must be 0 or 1") as raised:
            runner.main()
        database.assert_not_called()
    assert "CANARY" not in str(raised.value)


@pytest.mark.parametrize(
    ("path", "label"),
    [
        ("/api/v1/me", "auth"),
        ("/api/v1/accounts", "accounts"),
        ("/api/v1/accounts/CANARY", "accounts"),
        ("/api/v1/accounts/CANARY/summary", "summary"),
        ("/api/v1/benchmark-definitions", "benchmark_catalog"),
        ("/api/v1/benchmark-definitions/CANARY", "benchmark_catalog"),
        ("/api/v1/benchmark-definitions/CANARY/versions", "benchmark_catalog"),
        ("/api/v1/accounts/CANARY/performance/series", "performance"),
        ("/api/v1/accounts/CANARY/performance/intelligence", "performance"),
        ("/api/v1/accounts/CANARY/benchmark-comparison", "benchmark"),
        ("/api/v1/accounts/CANARY/attribution", "attribution"),
        ("/api/v1/accounts/CANARY/dividend-intelligence", "income"),
        ("/api/v1/accounts/CANARY/cash-flow-intelligence", "cash_flow"),
        ("/api/v1/CANARY", "other"),
        ("/api/v1/accounts/CANARY/summary/unknown", "other"),
    ],
)
def test_route_labels_are_fixed(path: str, label: str) -> None:
    assert timing.route_label(path) == label


def test_disabled_installs_nothing() -> None:
    with (
        patch.object(builtins, "__import__", side_effect=AssertionError("No imports expected")),
        patch.object(patch, "object") as patches,
    ):
        with timing.fixture_timings(_empty_app, enabled=False) as observed:
            assert observed is _empty_app
        patches.assert_not_called()


async def _empty_app(scope: Scope, receive: Receive, send: Send) -> None:
    pass


@pytest.mark.parametrize("fail", [False, True])
def test_patch_restoration(fail: bool) -> None:
    from trading212_analytics import historical as analytics
    from trading212_persistence import historical_base, historical_publication, source_store
    from trading212_persistence.historical_service import PostgresHistoricalService

    originals = (
        historical_base.__dict__["asyncio"],
        source_store.__dict__["asyncio"],
        PostgresHistoricalService._capture,
        PostgresHistoricalService._capture_view,
        analytics.calculate_performance,
        analytics.calculate_benchmark_comparison,
        analytics.calculate_attribution,
        analytics.calculate_income,
        analytics.calculate_cash_flows,
        analytics.verify_historical_result,
        historical_publication.persist_uses,
        historical_publication.read_historical_result,
    )
    error = RuntimeError("CANARY")
    try:
        with timing.fixture_timings(_empty_app, enabled=True) as observed:
            assert observed is not _empty_app
            assert historical_base.__dict__["asyncio"] is not originals[0]
            assert source_store.__dict__["asyncio"] is not originals[1]
            assert analytics.calculate_benchmark_comparison is not originals[5]
            if fail:
                raise error
    except RuntimeError as raised:
        assert raised is error
    assert originals == (
        historical_base.__dict__["asyncio"],
        source_store.__dict__["asyncio"],
        PostgresHistoricalService._capture,
        PostgresHistoricalService._capture_view,
        analytics.calculate_performance,
        analytics.calculate_benchmark_comparison,
        analytics.calculate_attribution,
        analytics.calculate_income,
        analytics.calculate_cash_flows,
        analytics.verify_historical_result,
        historical_publication.persist_uses,
        historical_publication.read_historical_result,
    )


async def test_stream_forwarding_privacy_and_no_extra_receive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    scope: Scope = {
        "type": "http",
        "path": "/api/v1/accounts/CANARY/benchmark-comparison",
        "query_string": b"CANARY",
        "headers": [(b"authorization", b"CANARY")],
    }
    messages: list[Message] = [
        {"type": "http.response.start", "status": 200, "headers": [(b"CANARY", b"CANARY")]},
        {"type": "http.response.body", "body": b"CANARY", "more_body": True},
        {"type": "http.response.body", "body": b"CANARY", "more_body": False},
    ]
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    async def app(actual_scope: Scope, receive: Receive, send: Send) -> None:
        assert actual_scope is scope
        assert receive is _unused_receive
        for message in messages:
            await send(message)

    await timing._Middleware(app, timing._Recorder())(scope, _unused_receive, send)
    assert len(sent) == len(messages)
    assert all(actual is expected for actual, expected in zip(sent, messages, strict=True))
    rows = _rows(capsys)
    assert [row["event"] for row in rows] == ["api_start", "api_headers", "api_body", "api_done"]
    for row in rows:
        assert row["route"] == "benchmark"
        assert row["request"] == 1
        assert datetime.fromisoformat(str(row["utc"])).utcoffset() is not None
        assert set(row) <= {"event", "utc", "request", "route", "elapsed_seconds", "status"}
    assert rows[1]["status"] == 200
    assert timing._active.get() is None


@pytest.mark.parametrize("scope", [{"type": "lifespan"}, {"type": "http", "path": "/health"}])
async def test_non_api_passthrough(scope: Scope, capsys: pytest.CaptureFixture[str]) -> None:
    called = False

    async def app(actual_scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True
        assert actual_scope is scope
        assert receive is _unused_receive
        assert send is _unused_send

    await timing._Middleware(app, timing._Recorder())(scope, _unused_receive, _unused_send)
    assert called
    assert not _rows(capsys)


async def test_worker_context_isolation_nested_phases_and_return_identity(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel = object()
    barrier = asyncio.Event()
    entered = 0
    observations: list[tuple[int, str]] = []

    def calculate() -> object:
        request = timing._active.get()
        assert request is not None
        observations.append((request.ordinal, request.route))
        return sentinel

    nested = timing._timed(timing._timed(calculate, "verify"), "calculate")

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal entered
        entered += 1
        if entered == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=5)
        assert await timing._ThreadBridge("historical").to_thread(nested) is sentinel

    middleware = timing._Middleware(app, timing._Recorder())
    await asyncio.gather(
        *[
            middleware({"type": "http", "path": path}, _unused_receive, _unused_send)
            for path in (
                "/api/v1/accounts/CANARY/benchmark-comparison",
                "/api/v1/accounts/CANARY/attribution",
            )
        ]
    )
    assert sorted(observations) == [(1, "benchmark"), (2, "attribution")]
    rows = _rows(capsys)
    for ordinal, route in observations:
        own = [row for row in rows if row["request"] == ordinal]
        assert all(row["route"] == route for row in own)
        assert [row["event"] for row in own] == [
            "api_start",
            "worker_dispatch",
            "worker_start",
            "phase_start",
            "phase_start",
            "phase_done",
            "phase_done",
            "worker_done",
            "api_done",
        ]
        assert [row["phase"] for row in own if row["event"] == "phase_done"] == [
            "verify",
            "calculate",
        ]
    assert timing._active.get() is None


async def test_exception_identity_and_redaction(capsys: pytest.CaptureFixture[str]) -> None:
    error = RuntimeError("CANARY")

    def failing(value: str) -> None:
        assert value == "CANARY"
        raise error

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await timing._ThreadBridge("source").to_thread(timing._timed(failing, "capture"), "CANARY")

    with pytest.raises(RuntimeError) as raised:
        await timing._Middleware(app, timing._Recorder())(
            {"type": "http", "path": "/api/v1/benchmark-definitions"},
            _unused_receive,
            _unused_send,
        )
    assert raised.value is error
    rows = _rows(capsys)
    assert [row["event"] for row in rows if row.get("failed")] == [
        "phase_done",
        "worker_done",
        "api_done",
    ]
    assert timing._active.get() is None


async def test_cancelled_http_retains_later_worker_completion(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    started, completed = asyncio.Event(), asyncio.Event()
    release = Event()
    recorder = timing._Recorder()
    original_write = recorder._write
    result: list[str] = []

    def write(fields: dict[str, str | int | float | bool]) -> None:
        original_write(fields)
        if fields["event"] == "worker_done":
            loop.call_soon_threadsafe(completed.set)

    monkeypatch.setattr(recorder, "_write", write)

    def work() -> None:
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        result.append("finished")

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await timing._ThreadBridge("historical").to_thread(work)

    task = asyncio.create_task(
        timing._Middleware(app, recorder)(
            {"type": "http", "path": "/api/v1/accounts/CANARY/performance/intelligence"},
            _unused_receive,
            _unused_send,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    await asyncio.wait_for(completed.wait(), timeout=5)
    rows = _rows(capsys)
    assert [row["event"] for row in rows] == [
        "api_start",
        "worker_dispatch",
        "worker_start",
        "api_done",
        "worker_done",
    ]
    assert rows[-2]["failed"] is True
    assert "failed" not in rows[-1]
    assert {row["request"] for row in rows} == {1}
    assert result == ["finished"]
    recorder.close()


def test_output_and_request_caps(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(timing, "MAX_EVENTS", 4)
    recorder = timing._Recorder()
    request = recorder.request("other")
    assert request is not None
    for _ in range(10):
        recorder.emit(request, "api_start")
    assert [row["event"] for row in _rows(capsys)] == ["api_start"] * 3 + ["truncated"]
    assert recorder.request("other") is None
    monkeypatch.setattr(timing, "MAX_REQUESTS", 2)
    recorder = timing._Recorder()
    assert recorder.request("other") is not None
    assert recorder.request("other") is not None
    assert recorder.request("other") is None
    assert recorder.request("other") is None
    assert [row["event"] for row in _rows(capsys)] == ["truncated"]


@pytest.mark.parametrize("closed", [False, True])
def test_closed_sink_does_not_change_work(
    closed: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorder = timing._Recorder()
    request = recorder.request("other")
    assert request is not None
    token = timing._active.set(request)
    sentinel = object()
    if closed:
        recorder.close()
    else:

        def broken_write(value: str) -> int:
            raise ValueError("CANARY")

        monkeypatch.setattr(sys.stderr, "write", broken_write)
    try:
        assert timing._timed(lambda: sentinel, "read_result")() is sentinel
        assert recorder.closed
    finally:
        timing._active.reset(token)
    assert not _rows(capsys)
