"""Isolated production attempt and externally sampled, task-owned Linux process tree."""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import signal
from contextlib import suppress
from dataclasses import dataclass
from itertools import pairwise
from multiprocessing.connection import Connection
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch

_SAMPLE_SECONDS = 0.050
_MAX_RSS_BYTES = 512 * 1024 * 1024
_ATTEMPT_SECONDS = 240
_STARTUP_SECONDS = 60


def _send(connection: Connection, kind: str, **metadata: Any) -> None:
    # This diagnostic channel carries identities/counts/metrics, never a financial result.
    encoded = json.dumps({"kind": kind, **metadata}, allow_nan=False).encode()
    assert len(encoded) < 64 * 1024
    connection.send_bytes(encoded)


def projection_budget_worker(
    database_url: str, payload: dict[str, str], observation: Connection
) -> None:
    """Fresh interpreter, fresh DB connections, unmodified numerical child and UTC clock."""
    os.setsid()
    _send(observation, "ready", pid=os.getpid(), process_group=os.getpgrp())
    engine = None
    try:
        assert observation.poll(_STARTUP_SECONDS)
        assert observation.recv_bytes(maxlength=16) == b"execute"
        # Import only in this dedicated process, rather than inheriting pytest's heap.
        from uuid import UUID

        from sqlalchemy import select
        from trading212_application import projection_jobs as jobs
        from trading212_application.projection_capture import (
            ProjectionCapturePlan,
            projection_capture_digest,
        )
        from trading212_persistence import create_database_engine, create_session_factory
        from trading212_persistence.projection_job_store import PostgresProjectionJobStore
        from trading212_persistence.projection_models import ProjectionResultModel
        from trading212_worker import projection_process, projection_tasks
        from trading212_worker.projection_process import (
            ProjectionProcessResult,
            calculate_private_projection,
        )
        from trading212_worker.xray_seed import XRAY_CURSOR_KEY

        repository = Path(__file__).resolve().parents[2]
        sources = {}
        for module in (projection_process, projection_tasks):
            assert module.__file__ is not None
            path = Path(module.__file__).resolve()
            assert path.is_relative_to(repository / "apps/worker/src")
            sources[str(path.relative_to(repository))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        message = jobs.ProjectionTaskMessage.from_wire(payload)
        engine = create_database_engine(database_url)
        sessions = create_session_factory(engine)
        # The production defaults use actual UTC for claims, heartbeats and deadlines.
        store = PostgresProjectionJobStore(sessions, cursor_signing_key=XRAY_CURSOR_KEY)
        original = calculate_private_projection
        observed: list[dict[str, Any]] = []

        def measured(plan: ProjectionCapturePlan, **arguments: Any) -> ProjectionProcessResult:
            assert type(plan) is ProjectionCapturePlan
            assert plan.inputs.work_units == 1_000_000
            assert projection_capture_digest(plan) == message.input_digest
            observed.append(
                {
                    "work_units": plan.inputs.work_units,
                    "assets": len(plan.inputs.assumptions.assets),
                    "months": plan.inputs.months,
                    "paths": plan.inputs.paths,
                    "variants": len(plan.inputs.variants),
                    "retained_months": list(plan.inputs.retained_months),
                    "captured_input_digest": message.input_digest,
                    "numerical_input_digest": plan.numerical_input_digest,
                }
            )
            result = original(plan, **arguments)
            observed[-1]["peak_child_rss_bytes"] = result.peak_rss_bytes
            return result

        async def execute() -> str:
            attempt = asyncio.create_task(
                projection_tasks.execute_projection_message(
                    store, message, consumer_id="isolated-maximum-work-measured"
                )
            )
            loop = asyncio.get_running_loop()
            # Parent timeout first requests normal production cancellation/child reaping.
            loop.add_signal_handler(signal.SIGTERM, attempt.cancel)
            try:
                return (await attempt).value
            finally:
                loop.remove_signal_handler(signal.SIGTERM)

        started = perf_counter()
        _send(observation, "attempt_started", monotonic_seconds=started, sources=sources)
        try:
            with patch.object(projection_tasks, "calculate_private_projection", measured):
                outcome = asyncio.run(execute())
        finally:
            elapsed = perf_counter() - started
        # Query only persisted identity/header fields after the timed attempt.
        with sessions() as session:
            result_headers = [
                {
                    "input_digest": row.input_digest,
                    "result_digest": row.content_digest,
                    "byte_length": row.byte_length,
                    "sealed": row.sealed,
                }
                for row in session.execute(
                    select(
                        ProjectionResultModel.input_digest,
                        ProjectionResultModel.content_digest,
                        ProjectionResultModel.byte_length,
                        ProjectionResultModel.sealed,
                    ).where(ProjectionResultModel.run_id == UUID(message.run_id))
                )
            ]
        _send(
            observation,
            "terminal",
            outcome=outcome,
            attempt_seconds=elapsed,
            loaded_plans=observed,
            result_count=len(result_headers),
            result_headers=result_headers,
        )
    except BaseException as error:
        # Exception messages/tracebacks can contain connection strings or source payloads.
        with suppress(BrokenPipeError, EOFError, OSError):
            _send(observation, "error", error_type=type(error).__name__)
    finally:
        if engine is not None:
            engine.dispose()
        observation.close()


@dataclass(frozen=True, slots=True)
class _Process:
    pid: int
    parent: int
    group: int
    session: int
    started: int
    state: str


def _process(pid: int) -> _Process | None:
    try:
        # comm may itself contain spaces or ')'; the remaining fields are numeric/state.
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
        return _Process(
            pid, int(fields[1]), int(fields[2]), int(fields[3]), int(fields[19]), fields[0]
        )
    except (OSError, ValueError, IndexError):
        return None


def _rss(process: _Process, *, measurement: dict[str, str] | None = None) -> int | None:
    if measurement is not None:
        measurement["source"] = "unavailable"
    try:
        for line in Path(f"/proc/{process.pid}/status").read_text(encoding="ascii").splitlines():
            if line.startswith("VmRSS:"):
                value, unit = line.split()[1:]
                assert unit == "kB"
                resident = int(value)
                if resident < 0:
                    raise ValueError("A resident counter cannot be negative.")
                if measurement is not None:
                    measurement["source"] = "proc_status_vmrss"
                return resident * 1024
    except (OSError, ValueError):
        pass
    # A task can transiently lack VmRSS while its memory map changes. statm's
    # resident field is an independent observed page count, including actual zero.
    try:
        fields = Path(f"/proc/{process.pid}/statm").read_text(encoding="ascii").split()
        resident_pages = int(fields[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
        if resident_pages < 0 or page_size <= 0:
            raise ValueError("Resident page counters must be nonnegative.")
        if measurement is not None:
            measurement["source"] = "proc_statm_resident_pages"
        return resident_pages * page_size
    except (OSError, ValueError, IndexError):
        pass
    if process.state == "Z" and measurement is not None:
        measurement["source"] = "observed_zombie_state"
    return 0 if process.state == "Z" else None


def _children(process: _Process) -> set[int]:
    children: set[int] = set()
    try:
        # Popen runs in the calculation thread, so inspect every task's children.
        for task in Path(f"/proc/{process.pid}/task").iterdir():
            with suppress(OSError, ValueError):
                children.update(int(pid) for pid in (task / "children").read_text().split())
    except OSError:
        pass
    return children


class _OwnedTree:
    def __init__(self, root: _Process) -> None:
        assert root.parent == os.getpid()
        self.root = root
        self.known = {root.pid: root.started}
        self.isolated = False

    def _owned(self, process: _Process) -> bool:
        return (
            process.started >= self.root.started
            and process.group == self.root.pid
            and process.session == self.root.pid
        )

    def members(self, *, find_orphans: bool = False) -> list[_Process]:
        if find_orphans and self.isolated:
            # A terminated worker can reparent its child before the next 50 ms sample.
            # Only the session/group created by this exact owned leader is eligible.
            for entry in Path("/proc").iterdir():
                if entry.name.isdecimal():
                    process = _process(int(entry.name))
                    if process is not None and self._owned(process):
                        self.known.setdefault(process.pid, process.started)
        pending, found = list(self.known), {}
        while pending:
            pid = pending.pop()
            if pid in found:
                continue
            process = _process(pid)
            if process is None or process.started != self.known[pid]:
                continue
            if self.isolated:
                assert self._owned(process), "Owned process changed its private session/group."
            else:
                assert pid == self.root.pid and process.parent == os.getpid()
            found[pid] = process
            if self.isolated:
                for child_pid in _children(process):
                    child = _process(child_pid)
                    if child is not None and child.parent == pid and self._owned(child):
                        self.known.setdefault(child_pid, child.started)
                        pending.append(child_pid)
        return sorted(found.values(), key=lambda process: process.pid)

    def sample(self, elapsed: float) -> dict[str, Any]:
        readings: list[dict[str, Any]] = []
        for process in self.members():
            measurement: dict[str, str] = {}
            rss = _rss(process, measurement=measurement)
            confirmed = _process(process.pid)
            if confirmed is None or confirmed.started != process.started:
                continue
            if confirmed.state == "Z":
                rss = 0
                measurement["source"] = "confirmed_zombie_state"
            readings.append(
                {
                    "pid": process.pid,
                    "parent_pid": process.parent,
                    "start_ticks": process.started,
                    "state": confirmed.state,
                    "rss_bytes": rss,
                    "rss_source": measurement["source"],
                }
            )
        available = all(reading["rss_bytes"] is not None for reading in readings)
        return {
            "elapsed_seconds": elapsed,
            "pid_count": len(readings),
            "rss_bytes": sum(reading["rss_bytes"] or 0 for reading in readings),
            "measurement_available": available,
            "processes": readings,
        }

    def signal(self, process: _Process, value: signal.Signals) -> None:
        current = _process(process.pid)
        if current is not None and current.started == process.started:
            assert self.known.get(current.pid) == current.started
            assert self._owned(current) if self.isolated else current.pid == self.root.pid
            with suppress(ProcessLookupError):
                os.kill(current.pid, value)


async def measure_projection_attempt(database_url: str, payload: dict[str, str]) -> dict[str, Any]:
    """Sample the dedicated worker and every discovered descendant, never pytest RSS."""
    assert await asyncio.to_thread(Path("/proc/self/stat").is_file), (
        "This measured budget requires Linux /proc."
    )
    context = multiprocessing.get_context("spawn")
    parent, child_pipe = context.Pipe(duplex=True)
    child = context.Process(
        target=projection_budget_worker, args=(database_url, payload, child_pipe)
    )
    started = perf_counter()
    child.start()
    child_pipe.close()
    assert child.pid is not None
    root = _process(child.pid)
    if root is None:
        # A failed bootstrap must not escape the owned Process handle's cleanup.
        if child.is_alive():
            child.terminate()
            child.join(timeout=2)
        if child.is_alive():
            child.kill()
            child.join(timeout=2)
        parent.close()
        child.close()
        raise AssertionError("Could not observe the dedicated worker's initial Linux identity.")
    tree = _OwnedTree(root)
    samples: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    failure: str | None = None
    attempt_started: float | None = None
    try:
        while True:
            at = perf_counter()
            samples.append(tree.sample(at - started))
            if samples[-1]["rss_bytes"] > _MAX_RSS_BYTES:
                failure = "observed_worker_tree_rss_limit"
                break
            while parent.poll():
                try:
                    event = json.loads(parent.recv_bytes(maxlength=64 * 1024))
                except EOFError:
                    break
                assert isinstance(event, dict)
                events.append(event)
                if event["kind"] == "ready":
                    assert event["pid"] == child.pid == event["process_group"]
                    actual = _process(child.pid)
                    assert actual is not None and actual.started == root.started
                    assert actual.group == actual.session == child.pid
                    tree.isolated = True
                    parent.send_bytes(b"execute")
                elif event["kind"] == "attempt_started":
                    assert attempt_started is None
                    attempt_started = float(event["monotonic_seconds"])
                elif event["kind"] in {"terminal", "error"}:
                    terminal = event
            if terminal is not None and not child.is_alive():
                break
            if not child.is_alive():
                failure = "worker_exited_without_terminal_metrics"
                break
            if attempt_started is None and at - started > _STARTUP_SECONDS:
                failure = "worker_startup_timeout"
                break
            if attempt_started is not None and at - attempt_started > _ATTEMPT_SECONDS + 5:
                failure = "attempt_timeout_including_five_second_cancellation_grace"
                break
            await asyncio.sleep(_SAMPLE_SECONDS)
    finally:
        # Graceful cancellation lets production finally blocks kill and wait for their child.
        for process in tree.members(find_orphans=True):
            if process.pid == child.pid and process.state != "Z":
                tree.signal(process, signal.SIGTERM)
        cleanup_started = perf_counter()
        while child.is_alive() and perf_counter() - cleanup_started < 5:
            samples.append(tree.sample(perf_counter() - started))
            await asyncio.sleep(_SAMPLE_SECONDS)
        # Kill descendants before the worker, allowing the worker to reap them normally.
        for process in tree.members(find_orphans=True):
            if process.pid != child.pid and process.state != "Z":
                tree.signal(process, signal.SIGKILL)
        for _ in range(20):
            if not child.is_alive():
                break
            await asyncio.sleep(_SAMPLE_SECONDS)
        for process in tree.members(find_orphans=True):
            if process.state != "Z":
                tree.signal(process, signal.SIGKILL)
        child.join(timeout=2)
        reaped_by = perf_counter() + 2
        while True:
            remaining = tree.members(find_orphans=True)
            live = [process for process in remaining if process.state != "Z"]
            if not remaining or perf_counter() >= reaped_by:
                break
            for process in live:
                tree.signal(process, signal.SIGKILL)
            await asyncio.sleep(_SAMPLE_SECONDS)
        parent.close()
        cleanup = {
            "seconds": perf_counter() - cleanup_started,
            "worker_exitcode": child.exitcode,
            "remaining_live_pids": [process.pid for process in remaining if process.state != "Z"],
            "remaining_zombie_pids": [process.pid for process in remaining if process.state == "Z"],
        }
        if not child.is_alive():
            child.close()
    peak = max(sample["rss_bytes"] for sample in samples)
    intervals = [
        right["elapsed_seconds"] - left["elapsed_seconds"] for left, right in pairwise(samples)
    ]
    return {
        "failure": failure,
        "terminal": terminal,
        "events": events,
        "worker_startup_seconds": None if attempt_started is None else attempt_started - started,
        "total_observation_seconds": perf_counter() - started,
        "sample_interval_target_seconds": _SAMPLE_SECONDS,
        "sample_intervals_seconds": intervals,
        "maximum_sample_interval_seconds": max(intervals, default=0),
        "rss_samples": samples,
        "peak_worker_tree_rss_bytes": peak,
        "maximum_pid_count": max(sample["pid_count"] for sample in samples),
        "cleanup": cleanup,
    }
