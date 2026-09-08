"""Opt-in, bounded diagnostics for the real historical browser fixture only."""

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
from time import perf_counter
from typing import Literal
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
    "other",
]
Phase = Literal["capture", "capture_decode", "calculate", "verify", "persist_uses", "read_result"]
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
]
Origin = Literal["historical", "source"]
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


_active: ContextVar[_Request | None] = ContextVar("e2e_timing_request", default=None)


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
            if status is not None:
                fields["status"] = status
            if failed:
                fields["failed"] = True
            self._write(fields)

    def close(self) -> None:
        with self.lock:
            self.closed = True


def _timed[**P, T](function: Callable[P, T], phase: Phase) -> Callable[P, T]:
    @wraps(function)
    def call(*args: P.args, **kwargs: P.kwargs) -> T:
        request = _active.get()
        if request is None:
            return function(*args, **kwargs)
        request.recorder.emit(request, "phase_start", phase=phase)
        started, failed = perf_counter(), True
        try:
            result = function(*args, **kwargs)
            failed = False
            return result
        finally:
            request.recorder.emit(
                request, "phase_done", phase=phase, seconds=perf_counter() - started, failed=failed
            )

    return call


class _ThreadBridge:
    """Replace only two fixture-scoped module bindings, never global asyncio."""

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
    def __init__(self, app: ASGIApp, recorder: _Recorder) -> None:
        self.app, self.recorder = app, recorder

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = (
            self.recorder.request(route_label(scope["path"]))
            if (scope["type"] == "http" and scope["path"].startswith("/api/v1/"))
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


@contextmanager
def fixture_timings(app: ASGIApp, *, enabled: bool) -> Iterator[ASGIApp]:
    if not enabled:
        yield app
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
