"""Explicit engine-local cursor timing; SQL and parameters never enter observations."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import Lock
from weakref import WeakKeyDictionary, ref

from sqlalchemy import Engine, event
from sqlalchemy.engine import Connection
from sqlalchemy.engine.interfaces import ExceptionContext, ExecutionContext

type QueryObserver = Callable[[float, bool], None]

_LOGGER = logging.getLogger("trading212.persistence.telemetry")


class DatabaseQueryTiming:
    """Own listeners for one engine, with disposal cleanup and explicit unregistration."""

    def __init__(self, engine: Engine, observer: QueryObserver) -> None:
        self._engine = ref(engine)
        self._observer: QueryObserver | None = observer
        self._starts: WeakKeyDictionary[ExecutionContext, float] = WeakKeyDictionary()
        self._lock = Lock()
        self._active = True
        self._disposal_registered = True
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)
        event.listen(engine, "handle_error", self._error)
        event.listen(engine, "engine_disposed", self._disposed)

    def _before(
        self,
        _connection: Connection,
        _cursor: object,
        _statement: str,
        _parameters: object,
        context: ExecutionContext | None,
        _executemany: bool,
    ) -> None:
        if context is not None:
            with self._lock:
                if self._active:
                    self._starts[context] = time.perf_counter()

    def _finish(self, context: ExecutionContext | None, failed: bool) -> None:
        if context is None:
            return
        with self._lock:
            started = self._starts.pop(context, None)
            observer = self._observer
        if started is not None and observer is not None:
            try:
                observer(max(0.0, time.perf_counter() - started), failed)
            except Exception:
                _LOGGER.error("database_query_observer_failed")

    def _after(
        self,
        _connection: Connection,
        _cursor: object,
        _statement: str,
        _parameters: object,
        context: ExecutionContext | None,
        _executemany: bool,
    ) -> None:
        self._finish(context, False)

    def _error(self, context: ExceptionContext) -> None:
        self._finish(context.execution_context, True)

    def _detach_queries(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._starts.clear()
            self._observer = None
        engine = self._engine()
        if engine is not None:
            event.remove(engine, "before_cursor_execute", self._before)
            event.remove(engine, "after_cursor_execute", self._after)
            event.remove(engine, "handle_error", self._error)

    def _disposed(self, _engine: Engine) -> None:
        # Do not mutate the currently dispatching disposal-listener deque.
        # This inert hook retains neither observer nor a strong engine reference.
        self._detach_queries()

    def close(self) -> None:
        self._detach_queries()
        engine = self._engine()
        if self._disposal_registered and engine is not None:
            event.remove(engine, "engine_disposed", self._disposed)
        self._disposal_registered = False
