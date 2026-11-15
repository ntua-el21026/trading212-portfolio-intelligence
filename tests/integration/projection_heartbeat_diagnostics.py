"""Private-test timing and own-backend wait metadata; no payload or token tracing."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from contextvars import ContextVar
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from time import perf_counter

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from trading212_application import projection_jobs as jobs
from trading212_persistence.projection_job_store import PostgresProjectionJobStore
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.projection_job_fixture import ProjectionJobCase


class Operation(StrEnum):
    CLAIM = "claim"
    ACKNOWLEDGE = "acknowledge"
    DISPATCH = "dispatch"
    LOAD_INPUT = "load_input"
    LOAD_CHUNKS = "load_chunks"
    SAVE_CHUNK = "save_chunk"
    COMPLETE = "complete"
    HEARTBEAT = "heartbeat"
    FAIL = "fail"
    OTHER = "other"


_OPERATIONS = {
    "claim_projection_job": Operation.CLAIM,
    "acknowledge_projection_dispatch": Operation.ACKNOWLEDGE,
    "claim_projection_dispatches": Operation.DISPATCH,
    "load_projection_job_input": Operation.LOAD_INPUT,
    "load_projection_job_chunks": Operation.LOAD_CHUNKS,
    "save_projection_job_chunk": Operation.SAVE_CHUNK,
    "complete_projection_job": Operation.COMPLETE,
    "heartbeat_projection_job": Operation.HEARTBEAT,
    "fail_projection_job": Operation.FAIL,
}
type DiagnosticValue = str | int | float | bool | list[int] | list[str] | None


class ProjectionTrace:
    def __init__(self) -> None:
        self.started = perf_counter()
        self._lock = Lock()
        self._records: list[dict[str, DiagnosticValue]] = []
        self._backends: dict[int, Operation] = {}
        self.dropped = 0

    def record(self, event: str, phase: Operation, **values: DiagnosticValue) -> None:
        with self._lock:
            if len(self._records) >= 4096:
                self.dropped += 1
                return
            self._records.append(
                {
                    "event": event,
                    "phase": phase.value,
                    "elapsed_seconds": perf_counter() - self.started,
                    **values,
                }
            )

    def backend(self, identifier: int, phase: Operation) -> None:
        with self._lock:
            self._backends[identifier] = phase

    def backends(self) -> dict[int, Operation]:
        with self._lock:
            return dict(self._backends)

    def records(self) -> list[dict[str, DiagnosticValue]]:
        with self._lock:
            return list(self._records)


class ObservedProjectionStore(PostgresProjectionJobStore):
    """Delegate every production operation unchanged while timing its boundaries."""

    def __init__(self, case: ProjectionJobCase, trace: ProjectionTrace) -> None:
        super().__init__(
            case.sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: datetime.now(UTC),
        )
        self.trace = trace
        self._diagnostic_phase: ContextVar[Operation] = ContextVar(
            "projection_diagnostic_operation", default=Operation.OTHER
        )

    async def _worker_run[T](self, action: Callable[[Session], T]) -> T:
        phase = next(
            (
                value
                for key, value in _OPERATIONS.items()
                if f".{key}.<locals>." in action.__qualname__
            ),
            Operation.OTHER,
        )
        token = self._diagnostic_phase.set(phase)
        self.trace.record("operation_started", phase)
        try:
            result = await super()._worker_run(action)
            self.trace.record(
                "operation_returned",
                phase,
                boolean_result=result if isinstance(result, bool) else None,
            )
            return result
        except asyncio.CancelledError:
            self.trace.record("operation_cancelled", phase, reason="asyncio_cancelled")
            raise
        except jobs.ProjectionJobInputError as error:
            self.trace.record("operation_failed", phase, reason=error.code.value)
            raise
        except Exception:
            self.trace.record("operation_failed", phase, reason="unexpected_exception")
            raise
        finally:
            self._diagnostic_phase.reset(token)

    def _global_slot(self, session: Session) -> None:
        phase = self._diagnostic_phase.get()
        identifier = session.scalar(select(func.pg_backend_pid()))
        assert isinstance(identifier, int)
        self.trace.backend(identifier, phase)
        self.trace.record("global_slot_wait_started", phase, backend=identifier)
        started = perf_counter()
        super()._global_slot(session)
        self.trace.record(
            "global_slot_acquired",
            phase,
            backend=identifier,
            wait_seconds=perf_counter() - started,
        )


def sample_own_waits(case: ProjectionJobCase, trace: ProjectionTrace) -> None:
    selected = trace.backends()
    if not selected:
        return
    # Deliberately exclude query text, SQL parameters, application names and
    # every backend not previously observed on this test store's connection.
    try:
        with case.sessions() as session:
            rows = session.execute(
                text(
                    "SELECT pid, state, wait_event_type, wait_event, pg_blocking_pids(pid) "
                    "FROM pg_stat_activity WHERE datname=current_database() AND pid=ANY(:pids)"
                ),
                {"pids": list(selected)},
            ).all()
    except SQLAlchemyError:
        trace.record(
            "sampling_unavailable", Operation.OTHER, reason="database_metadata_unavailable"
        )
        return
    for pid, state, wait_type, wait_event, blockers in rows:
        assert pid in selected
        reason = (
            "advisory_lock_wait"
            if (wait_type, wait_event) == ("Lock", "advisory")
            else "other_lock_wait"
            if wait_type == "Lock"
            else "database_active"
            if state == "active"
            else "database_idle"
        )
        own_blockers = [value for value in blockers if value in selected]
        trace.record(
            "database_wait_sample",
            selected[pid],
            backend=pid,
            reason=reason,
            own_blockers=own_blockers,
            blocking_phases=[selected[value].value for value in own_blockers],
            other_blockers_count=len(blockers) - len(own_blockers),
        )


async def observe_waits(
    case: ProjectionJobCase, trace: ProjectionTrace, stopped: asyncio.Event
) -> None:
    while not stopped.is_set():
        await asyncio.to_thread(sample_own_waits, case, trace)
        with suppress(TimeoutError):
            await asyncio.wait_for(stopped.wait(), timeout=0.25)
