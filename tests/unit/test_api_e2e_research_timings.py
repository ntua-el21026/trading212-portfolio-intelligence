"""Research fixture diagnostics preserve privacy, forwarding and original work."""

from __future__ import annotations

import builtins
import json
from types import ModuleType, SimpleNamespace
from typing import Protocol, cast
from unittest.mock import patch

import pytest
from starlette.types import Message, Receive, Scope, Send

from scripts import api_e2e_timings as timing

pytestmark = pytest.mark.unit


class _SyntheticCallable(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> object: ...


class _SyntheticThreadBridge(Protocol):
    async def to_thread(
        self, function: _SyntheticCallable, *args: object, **kwargs: object
    ) -> object: ...


def _binding(module: ModuleType, name: str) -> object:
    # Tests inspect and replace exact module bindings, including private imported
    # aliases. This is not an assertion that the production API accepts canaries.
    return cast(object, vars(module)[name])


def _rows(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    text = capsys.readouterr().err
    assert "CANARY" not in text
    return [
        cast(dict[str, object], json.loads(line.removeprefix("e2e.timing ")))
        for line in text.splitlines()
    ]


async def _unused_receive() -> Message:
    pytest.fail("The diagnostic must not consume an ASGI receive.")


@pytest.mark.parametrize("enabled", [False, True])
async def test_research_fixed_route_forwards_original_stream_and_hides_private_values(
    enabled: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    scope: Scope = {
        "type": "http",
        "path": "/api/v1/accounts/CANARY/research",
        "query_string": b"CANARY",
        "headers": [(b"cookie", b"CANARY")],
    }
    messages: list[Message] = [
        {"type": "http.response.start", "status": 200, "headers": [(b"CANARY", b"CANARY")]},
        {"type": "http.response.body", "body": b"CANARY", "more_body": True},
        {"type": "http.response.body", "body": b"CANARY", "more_body": False},
    ]
    sent: list[Message] = []

    async def original(actual: Scope, receive: Receive, send: Send) -> None:
        assert actual is scope and receive is _unused_receive
        for message in messages:
            await send(message)

    async def capture(message: Message) -> None:
        sent.append(message)

    with timing.fixture_timings(original, enabled=enabled, research=True) as observed:
        await observed(scope, _unused_receive, capture)
    assert len(sent) == len(messages)
    assert all(actual is expected for actual, expected in zip(sent, messages, strict=True))
    rows = _rows(capsys)
    if not enabled:
        assert not rows
    else:
        assert [row["event"] for row in rows] == [
            "api_start",
            "api_headers",
            "api_body",
            "api_done",
        ]
        assert all(row["route"] == "research" and row["request"] == 1 for row in rows)
        assert all(
            set(row) <= {"event", "utc", "request", "route", "elapsed_seconds", "status"}
            for row in rows
        )
    assert timing._active.get() is None


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/api/v1/me",
        "/api/v1/accounts/CANARY/summary",
        "/api/v1/research/items/CANARY",
        "/api/v1/accounts/CANARY/research/unknown",
    ],
)
async def test_research_observer_passes_other_routes_without_recording(
    path: str, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = 0

    async def original(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal calls
        calls += 1
        assert scope["path"] == path

    async def send(message: Message) -> None:
        pytest.fail("Original handler sends no messages.")

    with timing.fixture_timings(original, enabled=True, research=True) as observed:
        await observed({"type": "http", "path": path}, _unused_receive, send)
    assert calls == 1 and _rows(capsys) == []


def test_research_disabled_performs_no_import_or_patch() -> None:
    async def original(scope: Scope, receive: Receive, send: Send) -> None:
        pass

    with (
        patch.object(builtins, "__import__", side_effect=AssertionError("No imports expected")),
        timing.fixture_timings(original, enabled=False, research=True) as observed,
    ):
        assert observed is original


@pytest.mark.parametrize("failed", [False, True])
def test_research_observer_restores_only_its_exact_module_bindings(failed: bool) -> None:
    from trading212_api import research_routes, research_schemas
    from trading212_persistence import research_service, research_summary_page

    async def original(scope: Scope, receive: Receive, send: Send) -> None:
        pass

    originals = (
        _binding(research_service, "asyncio"),
        _binding(research_service, "authorize_research_page"),
        _binding(research_service, "research_summary_page"),
        _binding(research_summary_page, "read_research_xray"),
        _binding(research_summary_page, "research_candidate_page"),
        _binding(research_summary_page, "research_event_payloads"),
        _binding(research_routes, "research_response"),
        research_schemas.research_view,
    )
    error = RuntimeError("CANARY")
    try:
        with timing.fixture_timings(original, enabled=True, research=True):
            assert _binding(research_service, "asyncio") is not originals[0]
            assert _binding(research_service, "research_summary_page") is not originals[2]
            assert _binding(research_routes, "research_response") is not originals[6]
            if failed:
                raise error
    except RuntimeError as observed:
        assert observed is error
    assert originals == (
        _binding(research_service, "asyncio"),
        _binding(research_service, "authorize_research_page"),
        _binding(research_service, "research_summary_page"),
        _binding(research_summary_page, "read_research_xray"),
        _binding(research_summary_page, "research_candidate_page"),
        _binding(research_summary_page, "research_event_payloads"),
        _binding(research_routes, "research_response"),
        research_schemas.research_view,
    )


async def test_research_thread_work_and_serialization_are_called_once_with_safe_metadata(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from trading212_api import research_routes, research_schemas
    from trading212_persistence import research_service

    calls = {"summary": 0, "wire": 0, "response": 0}
    private = object()

    def summary(*args: object, **kwargs: object) -> object:
        calls["summary"] += 1
        return private

    def wire(*args: object, **kwargs: object) -> object:
        calls["wire"] += 1
        return private

    def response(*args: object, **kwargs: object) -> object:
        calls["response"] += 1
        converted = cast(_SyntheticCallable, _binding(research_schemas, "research_view"))
        assert converted(private) is private
        return private

    monkeypatch.setattr(research_service, "research_summary_page", summary)
    monkeypatch.setattr(research_schemas, "research_view", wire)
    monkeypatch.setattr(research_routes, "research_response", response)

    async def original(scope: Scope, receive: Receive, send: Send) -> None:
        bridge = cast(_SyntheticThreadBridge, _binding(research_service, "asyncio"))
        selected_summary = cast(
            _SyntheticCallable, _binding(research_service, "research_summary_page")
        )
        selected_response = cast(_SyntheticCallable, _binding(research_routes, "research_response"))
        copied = await bridge.to_thread(selected_summary, "CANARY")
        assert copied is private
        assert selected_response("CANARY", copied, "CANARY") is private
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"CANARY", "more_body": False})

    async def send(message: Message) -> None:
        pass

    with timing.fixture_timings(original, enabled=True, research=True) as observed:
        await observed(
            {"type": "http", "path": "/api/v1/accounts/CANARY/research"}, _unused_receive, send
        )
    assert calls == {"summary": 1, "wire": 1, "response": 1}
    rows = _rows(capsys)
    phases = [row for row in rows if row["event"] == "phase_done"]
    assert {row["phase"] for row in phases} >= {
        "research_summary",
        "research_wire",
        "research_response",
    }
    assert all(float(cast(float, row["seconds"])) >= 0 for row in phases)
    assert all(float(cast(float, row["cpu_seconds"])) >= 0 for row in phases)
    assert all(row.get("origin", "research") == "research" for row in rows)
    assert all(
        set(row)
        <= {
            "event",
            "utc",
            "request",
            "route",
            "elapsed_seconds",
            "status",
            "phase",
            "origin",
            "seconds",
            "cpu_seconds",
            "failed",
        }
        for row in rows
    )
    assert timing._active.get() is None


async def test_research_sql_observer_emits_only_fixed_kinds_and_durations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def original(scope: Scope, receive: Receive, send: Send) -> None:
        for statement in ("SELECT pg_advisory_xact_lock(CANARY)", "SELECT CANARY"):
            context = SimpleNamespace()
            timing._research_sql_before(None, None, statement, {"CANARY": "CANARY"}, context, False)
            timing._research_sql_after(None, None, statement, {"CANARY": "CANARY"}, context, False)

    async def send(message: Message) -> None:
        pass

    with timing.fixture_timings(original, enabled=True, research=True) as observed:
        await observed(
            {"type": "http", "path": "/api/v1/accounts/CANARY/research"}, _unused_receive, send
        )
    rows = _rows(capsys)
    sql = [row for row in rows if row["event"] == "sql_done"]
    assert [row["sql_kind"] for row in sql] == ["lock", "statement"]
    assert all(
        set(row)
        <= {
            "event",
            "utc",
            "request",
            "route",
            "elapsed_seconds",
            "seconds",
            "cpu_seconds",
            "sql_kind",
        }
        for row in sql
    )
    assert all(
        float(cast(float, row["seconds"])) >= 0 and float(cast(float, row["cpu_seconds"])) >= 0
        for row in sql
    )
    assert timing._active.get() is None
