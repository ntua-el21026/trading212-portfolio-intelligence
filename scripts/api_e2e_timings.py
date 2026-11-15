"""Opt-in bounded diagnostics for fixed synthetic browser-fixture routes."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from threading import RLock
from time import perf_counter, thread_time
from typing import Literal, Protocol
from unittest.mock import patch

from starlette.types import ASGIApp, Message, Receive, Scope, Send

Route = Literal[
    "auth",
    "accounts",
    "summary",
    "benchmark_catalog",
    "performance",
    "benchmark",
    "attribution",
    "income",
    "cash_flow",
    "research",
    "other",
]
Phase = Literal[
    "capture",
    "capture_decode",
    "calculate",
    "verify",
    "persist_uses",
    "read_result",
    "research_authorize",
    "research_summary",
    "research_retained_read",
    "research_candidates",
    "research_payloads",
    "research_copy",
    "research_capabilities",
    "research_provenance",
    "research_response",
    "research_wire",
]
Event = Literal[
    "api_start",
    "api_headers",
    "api_body",
    "api_done",
    "worker_dispatch",
    "worker_start",
    "worker_done",
    "phase_start",
    "phase_done",
    "truncated",
    "sql_done",
]
Origin = Literal["historical", "source", "research"]
SQLKind = Literal["statement", "lock"]
MAX_REQUESTS = 256
MAX_EVENTS = 4096


def timings_enabled(value: str) -> bool:
    if value not in {"0", "1"}:
        raise ValueError("T212PI_E2E_TIMINGS must be 0 or 1.")
    return value == "1"


def route_label(path: str) -> Route:
    if path == "/api/v1/me":
        return "auth"
    if re.fullmatch(r"/api/v1/accounts(?:/[^/]+)?", path):
        return "accounts"
    if re.fullmatch(r"/api/v1/benchmark-definitions(?:/[^/]+(?:/versions)?)?", path):
        return "benchmark_catalog"
    routes: tuple[tuple[str, Route], ...] = (
        ("summary", "summary"),
        ("research", "research"),
        ("performance/(?:series|intelligence)", "performance"),
        ("benchmark-comparison", "benchmark"),
        ("attribution", "attribution"),
        ("dividend-intelligence", "income"),
        ("cash-flow-intelligence", "cash_flow"),
    )
    return next(
        (
            label
            for suffix, label in routes
            if re.fullmatch(r"/api/v1/accounts/[^/]+/" + suffix, path)
        ),
        "other",
    )


@dataclass(frozen=True)
class _Request:
    recorder: _Recorder
    ordinal: int
    route: Route
    started: float


class _ResearchSQLContext(Protocol):
    _research_fixture_timing: tuple[_Request, Phase | None, float, float, SQLKind]


_active: ContextVar[_Request | None] = ContextVar("e2e_timing_request", default=None)
_research_phase: ContextVar[Phase | None] = ContextVar("e2e_research_phase", default=None)


class _Recorder:
    def __init__(self) -> None:
        self.lock = RLock()
        self.requests = 0
        self.events = 0
        self.closed = False

    def request(self, route: Route) -> _Request | None:
        with self.lock:
            if self.closed:
                return None
            if self.requests == MAX_REQUESTS:
                self._truncate()
                return None
            self.requests += 1
            return _Request(self, self.requests, route, perf_counter())

    def _write(self, fields: dict[str, str | int | float | bool]) -> None:
        try:
            sys.stderr.write("e2e.timing " + json.dumps(fields, separators=(",", ":")) + "\n")
            sys.stderr.flush()
        except (OSError, ValueError):
            # Diagnostic output failure must not alter the request or cleanup.
            self.closed = True

    def _truncate(self) -> None:
        self._write({"event": "truncated", "utc": datetime.now(UTC).isoformat()})
        self.closed = True

    def emit(
        self,
        request: _Request,
        name: Event,
        *,
        phase: Phase | None = None,
        origin: Origin | None = None,
        seconds: float | None = None,
        status: int | None = None,
        failed: bool = False,
        cpu_seconds: float | None = None,
        sql_kind: SQLKind | None = None,
    ) -> None:
        with self.lock:
            if self.closed:
                return
            if self.events >= MAX_EVENTS - 1:
                self._truncate()
                return
            self.events += 1
            fields: dict[str, str | int | float | bool] = {
                "event": name,
                "utc": datetime.now(UTC).isoformat(),
                "request": request.ordinal,
                "route": request.route,
                "elapsed_seconds": perf_counter() - request.started,
            }
            if phase is not None:
                fields["phase"] = phase
            if origin is not None:
                fields["origin"] = origin
            if seconds is not None:
                fields["seconds"] = seconds
            if cpu_seconds is not None:
                fields["cpu_seconds"] = cpu_seconds
            if sql_kind is not None:
                fields["sql_kind"] = sql_kind
            if status is not None:
                fields["status"] = status
            if failed:
                fields["failed"] = True
            self._write(fields)

    def close(self) -> None:
        with self.lock:
            self.closed = True


def _timed[**P, T](function: Callable[P, T], phase: Phase, *, cpu: bool = False) -> Callable[P, T]:
    @wraps(function)
    def call(*args: P.args, **kwargs: P.kwargs) -> T:
        request = _active.get()
        if request is None:
            return function(*args, **kwargs)
        request.recorder.emit(request, "phase_start", phase=phase)
        started, failed = perf_counter(), True
        cpu_started = thread_time() if cpu else None
        token = _research_phase.set(phase) if cpu else None
        try:
            result = function(*args, **kwargs)
            failed = False
            return result
        finally:
            request.recorder.emit(
                request,
                "phase_done",
                phase=phase,
                seconds=perf_counter() - started,
                failed=failed,
                cpu_seconds=None if cpu_started is None else thread_time() - cpu_started,
            )
            if token is not None:
                _research_phase.reset(token)

    return call


class _ThreadBridge:
    """Replace selected fixture-module bindings, never global asyncio."""

    def __init__(self, origin: Origin) -> None:
        self.origin = origin

    async def to_thread[**P, T](
        self,
        function: Callable[P, T],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        request = _active.get()
        if request is None:
            return await asyncio.to_thread(function, *args, **kwargs)
        request.recorder.emit(request, "worker_dispatch", origin=self.origin)
        dispatched = perf_counter()

        def execute() -> T:
            request.recorder.emit(
                request, "worker_start", origin=self.origin, seconds=perf_counter() - dispatched
            )
            started, failed = perf_counter(), True
            try:
                result = function(*args, **kwargs)
                failed = False
                return result
            finally:
                # The original callable exits its session/transaction before here.
                request.recorder.emit(
                    request,
                    "worker_done",
                    origin=self.origin,
                    seconds=perf_counter() - started,
                    failed=failed,
                )

        return await asyncio.to_thread(execute)


class _Middleware:
    def __init__(self, app: ASGIApp, recorder: _Recorder, *, research_only: bool = False) -> None:
        self.app, self.recorder = app, recorder
        self.research_only = research_only

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = (
            self.recorder.request(route_label(scope["path"]))
            if (
                scope["type"] == "http"
                and scope["path"].startswith("/api/v1/")
                and (not self.research_only or route_label(scope["path"]) == "research")
            )
            else None
        )
        if request is None:
            await self.app(scope, receive, send)
            return
        token = _active.set(request)
        self.recorder.emit(request, "api_start")

        async def observed_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                self.recorder.emit(request, "api_headers", status=message["status"])
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                self.recorder.emit(request, "api_body")

        failed = True
        try:
            await self.app(scope, receive, observed_send)
            failed = False
        finally:
            self.recorder.emit(request, "api_done", failed=failed)
            _active.reset(token)


def _research_sql_before(
    connection: object,
    cursor: object,
    statement: str,
    parameters: object,
    context: _ResearchSQLContext,
    executemany: bool,
) -> None:
    request = _active.get()
    if request is None or request.route != "research":
        return
    # Inspect only whether this fixed statement requests an advisory lock. Never
    # retain SQL, parameter, resource, column, header or exception material.
    kind: SQLKind = "lock" if "pg_advisory" in statement else "statement"
    context._research_fixture_timing = (
        request,
        _research_phase.get(),
        perf_counter(),
        thread_time(),
        kind,
    )


def _research_sql_after(
    connection: object,
    cursor: object,
    statement: str,
    parameters: object,
    context: _ResearchSQLContext,
    executemany: bool,
) -> None:
    mark: tuple[_Request, Phase | None, float, float, SQLKind] | None = getattr(
        context, "_research_fixture_timing", None
    )
    if mark is None:
        return
    del context._research_fixture_timing
    request, phase, started, cpu_started, kind = mark
    if _active.get() is not request:
        return
    request.recorder.emit(
        request,
        "sql_done",
        phase=phase,
        seconds=perf_counter() - started,
        cpu_seconds=thread_time() - cpu_started,
        sql_kind=kind,
    )


@contextmanager
def _research_fixture_timings(app: ASGIApp) -> Iterator[ASGIApp]:
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from trading212_api import research_routes, research_schemas
    from trading212_persistence import research_service, research_summary_page

    recorder = _Recorder()
    try:
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(research_service, "asyncio", _ThreadBridge("research"))
            )
            targets: tuple[tuple[object, str, Phase], ...] = (
                (research_service, "authorize_research_page", "research_authorize"),
                (research_service, "research_summary_page", "research_summary"),
                (research_summary_page, "read_research_xray", "research_retained_read"),
                (research_summary_page, "research_candidate_page", "research_candidates"),
                (research_summary_page, "research_event_payloads", "research_payloads"),
                (research_summary_page, "copy_research_portfolio_facts_many", "research_copy"),
                (research_summary_page, "require_research_capabilities", "research_capabilities"),
                (research_summary_page, "finish_research_xray", "research_provenance"),
                (research_routes, "research_response", "research_response"),
                (research_schemas, "research_view", "research_wire"),
            )
            for module, name, phase in targets:
                stack.enter_context(
                    patch.object(module, name, _timed(getattr(module, name), phase, cpu=True))
                )
            event.listen(Engine, "before_cursor_execute", _research_sql_before)
            stack.callback(event.remove, Engine, "before_cursor_execute", _research_sql_before)
            event.listen(Engine, "after_cursor_execute", _research_sql_after)
            stack.callback(event.remove, Engine, "after_cursor_execute", _research_sql_after)
            yield _Middleware(app, recorder, research_only=True)
    finally:
        recorder.close()


@contextmanager
def fixture_timings(app: ASGIApp, *, enabled: bool, research: bool = False) -> Iterator[ASGIApp]:
    if not enabled:
        yield app
        return
    if research:
        with _research_fixture_timings(app) as observed:
            yield observed
        return
    from trading212_analytics import historical as analytics
    from trading212_persistence import historical_base, historical_publication, source_store
    from trading212_persistence.historical_service import PostgresHistoricalService as Service

    recorder = _Recorder()
    try:
        with ExitStack() as stack:
            bridges: tuple[tuple[object, Origin], ...] = (
                (historical_base, "historical"),
                (source_store, "source"),
            )
            for module, origin in bridges:
                stack.enter_context(patch.object(module, "asyncio", _ThreadBridge(origin)))
            stack.enter_context(
                patch.object(Service, "_capture", _timed(Service._capture, "capture"))
            )
            stack.enter_context(
                patch.object(
                    Service, "_capture_view", _timed(Service._capture_view, "capture_decode")
                )
            )
            stack.enter_context(
                patch.object(
                    analytics,
                    "calculate_performance",
                    _timed(analytics.calculate_performance, "calculate"),
                )
            )
            stack.enter_context(
                patch.object(
                    analytics,
                    "calculate_benchmark_comparison",
                    _timed(analytics.calculate_benchmark_comparison, "calculate"),
                )
            )
            stack.enter_context(
                patch.object(
                    analytics,
                    "calculate_attribution",
                    _timed(analytics.calculate_attribution, "calculate"),
                )
            )
            stack.enter_context(
                patch.object(
                    analytics, "calculate_income", _timed(analytics.calculate_income, "calculate")
                )
            )
            stack.enter_context(
                patch.object(
                    analytics,
                    "calculate_cash_flows",
                    _timed(analytics.calculate_cash_flows, "calculate"),
                )
            )
            stack.enter_context(
                patch.object(
                    analytics,
                    "verify_historical_result",
                    _timed(analytics.verify_historical_result, "verify"),
                )
            )
            stack.enter_context(
                patch.object(
                    historical_publication,
                    "persist_uses",
                    _timed(historical_publication.persist_uses, "persist_uses"),
                )
            )
            stack.enter_context(
                patch.object(
                    historical_publication,
                    "read_historical_result",
                    _timed(historical_publication.read_historical_result, "read_result"),
                )
            )
            yield _Middleware(app, recorder)
    finally:
        # A cancelled HTTP task can leave an executor worker running after exit.
        recorder.close()
