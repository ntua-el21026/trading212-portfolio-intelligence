"""Actual one-child resume, acknowledgement, resource and immutable-input regressions."""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from hashlib import sha256
from multiprocessing.connection import Connection
from typing import Any
from unittest.mock import mock_open, patch

import pytest
from trading212_analytics import projection as kernel
from trading212_application import projection_jobs as jobs
from trading212_application.projection_capture import projection_capture_digest
from trading212_domain.projection_result import ProjectionChunk
from trading212_domain.projection_serialization import (
    decode_projection_chunk,
    projection_canonical_bytes,
)
from trading212_worker import projection_process as process

from tests.unit.persistence.projection_codec_factories import capture

pytestmark = pytest.mark.unit


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process memory accounting")
def test_child_high_water_excludes_pre_exec_parent_address_space() -> None:
    # A separate small parent makes the inherited peak reproducible without
    # growing the long-lived test runner or depending on earlier test order.
    child = (
        "import resource; from trading212_worker.projection_process import _high_water_frame; "
        "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024, "
        "int(_high_water_frame()))"
    )
    parent = (
        "import os, subprocess, sys; payload = bytearray(256 * 1024 * 1024); "
        "read_fd, write_fd = os.pipe(); "
        "subprocess.run([sys.executable, '-B', '-c', sys.argv[1]], "
        "pass_fds=(write_fd,), check=True); os.close(read_fd); os.close(write_fd)"
    )
    result = subprocess.run(  # noqa: S603 - fixed regression program, no external input
        [sys.executable, "-B", "-c", parent, child],
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"},
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    inherited, actual = map(int, result.stdout.split())
    assert inherited >= 256 * 1024 * 1024
    assert 0 < actual < inherited - 32 * 1024 * 1024


@pytest.mark.parametrize("status", ["VmRSS:\t42 kB\n", "VmHWM:\tbad kB\n", "VmHWM:\t42 B\n"])
def test_absent_or_invalid_child_high_water_is_explicitly_unavailable(status: str) -> None:
    with patch("builtins.open", mock_open(read_data=status)):
        assert process._high_water_frame() == b"-"


def _empty(_: process.ChunkCursor | None) -> tuple[ProjectionChunk, ...]:
    return ()


def test_actual_child_matches_exact_three_variant_result_with_short_resume_pages() -> None:
    plan = capture(observed=False)
    # A middle path is retained; this intentionally is not a prefix checkpoint.
    saved = tuple(
        kernel.calculate_projection_chunk(plan.inputs, 1, 1, variant=v)
        for v in plan.inputs.variants
    )
    cursors: list[process.ChunkCursor | None] = []
    created: list[ProjectionChunk] = []

    def load(after: process.ChunkCursor | None) -> tuple[ProjectionChunk, ...]:
        cursors.append(after)
        return tuple(c for c in saved if after is None or (c.variant, c.paths[0].index) > after)[:1]

    def save(chunk: ProjectionChunk) -> bool:
        created.append(chunk)
        return True

    with patch(
        "trading212_worker.projection_process.subprocess.Popen", wraps=subprocess.Popen
    ) as launched:
        actual = process.calculate_private_projection(
            plan,
            input_digest=projection_capture_digest(plan),
            load_chunks=load,
            save_chunk=save,
            cancelled=threading.Event(),
        )
    assert launched.call_count == 1
    assert len(cursors) == 4
    assert {(c.variant, p.index) for c in created for p in c.paths} == {
        (v, index) for v in plan.inputs.variants for index in (0, 2)
    }
    assert projection_canonical_bytes(actual.calculation) == projection_canonical_bytes(
        kernel.calculate_projection(plan.inputs)
    )
    assert actual.peak_rss_bytes is not None and 0 < actual.peak_rss_bytes <= 512 * 1024 * 1024
    assert launched.call_args.kwargs["env"] == {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}
    assert launched.call_args.kwargs["stdout"] is subprocess.DEVNULL
    assert "-B" in launched.call_args.args[0]


def test_lost_ack_resumes_durable_chunk_without_republishing_it() -> None:
    plan = capture(observed=False)
    saved: list[ProjectionChunk] = []

    def interrupted_save(chunk: ProjectionChunk) -> bool:
        saved.append(chunk)
        raise jobs.ProjectionJobInputError(
            jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE, retryable=True
        )

    with pytest.raises(jobs.ProjectionJobInputError) as failure:
        process.calculate_private_projection(
            plan,
            input_digest=projection_capture_digest(plan),
            load_chunks=_empty,
            save_chunk=interrupted_save,
            cancelled=threading.Event(),
        )
    assert failure.value.retryable and len(saved) == 1
    durable = saved[0]
    published: list[ProjectionChunk] = []

    def load(after: process.ChunkCursor | None) -> tuple[ProjectionChunk, ...]:
        return (durable,) if after is None else ()

    def save(chunk: ProjectionChunk) -> bool:
        published.append(chunk)
        return True

    actual = process.calculate_private_projection(
        plan,
        input_digest=projection_capture_digest(plan),
        load_chunks=load,
        save_chunk=save,
        cancelled=threading.Event(),
    )
    assert all(c.variant != durable.variant for c in published)
    assert projection_canonical_bytes(actual.calculation) == projection_canonical_bytes(
        kernel.calculate_projection(plan.inputs)
    )


def _start_session() -> tuple[Connection, threading.Thread, list[Exception]]:
    parent, child = multiprocessing.Pipe(duplex=True)
    failures: list[Exception] = []

    def run() -> None:
        try:
            process._child_session(child)
        except Exception as error:
            failures.append(error)
        finally:
            child.close()

    thread = threading.Thread(target=run)
    thread.start()
    return parent, thread, failures


def _input(connection: Connection) -> None:
    plan = capture(observed=False)
    connection.send_bytes(process._PROTOCOL)
    connection.send_bytes(plan.numerical_input_digest.encode("ascii"))
    connection.send_bytes(projection_canonical_bytes(plan.inputs))


def test_child_waits_for_exact_ack_and_never_samples_saved_or_later_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = capture(observed=False)
    saved = kernel.calculate_projection_chunk(plan.inputs, 1, 1)
    calls: list[tuple[str, int, int]] = []
    original = kernel.calculate_projection_chunk

    def calculate(
        inputs: Any, start: int, count: int, *, variant: Any = "baseline"
    ) -> ProjectionChunk:
        calls.append((variant, start, count))
        assert not (variant == "baseline" and start <= 1 < start + count)
        return original(inputs, start, count, variant=variant)

    monkeypatch.setattr(kernel, "calculate_projection_chunk", calculate)
    parent, thread, failures = _start_session()
    try:
        _input(parent)
        parent.send_bytes(b"S" + projection_canonical_bytes(saved))
        parent.send_bytes(b"E")
        assert parent.poll(5)
        first = parent.recv_bytes()
        assert first.startswith(b"C") and decode_projection_chunk(first[1:]).paths[0].index == 0
        assert not parent.poll(0.05)
        assert calls == [("baseline", 0, 1)]
        parent.send_bytes(b"A" + b"0" * 64)
        thread.join(timeout=5)
        assert not thread.is_alive() and len(failures) == 1
        assert calls == [("baseline", 0, 1)]
    finally:
        parent.close()
        thread.join(timeout=5)


@pytest.mark.parametrize("bad_frame", [b"unknown-version", b"E", b"A" + b"0" * 64])
def test_child_closed_protocol_rejects_unexpected_initial_state(bad_frame: bytes) -> None:
    parent, thread, failures = _start_session()
    try:
        parent.send_bytes(bad_frame)
        thread.join(timeout=5)
        assert not thread.is_alive() and len(failures) == 1
    finally:
        parent.close()
        thread.join(timeout=5)


@pytest.mark.parametrize("kind", ["overlap", "foreign", "oversized_page", "cursor_repeat"])
def test_bad_saved_partition_fails_before_any_new_checkpoint(kind: str) -> None:
    plan = capture(observed=False)
    chunk = kernel.calculate_projection_chunk(plan.inputs, 0, 1)
    calls = 0

    def load(_: process.ChunkCursor | None) -> tuple[ProjectionChunk, ...]:
        nonlocal calls
        calls += 1
        if kind == "overlap":
            return (chunk, chunk)
        if kind == "foreign":
            return (
                ProjectionChunk(input_digest="a" * 64, variant=chunk.variant, paths=chunk.paths),
            )
        if kind == "oversized_page":
            return (chunk,) * 33
        return (chunk,)

    with (
        patch("builtins.print") as output,
        patch("trading212_worker.projection_process._resident_bytes", return_value=None),
        pytest.raises(jobs.ProjectionJobInputError),
    ):
        process.calculate_private_projection(
            plan,
            input_digest=projection_capture_digest(plan),
            load_chunks=load,
            save_chunk=lambda _: pytest.fail("Invalid saved partition reached publication."),
            cancelled=threading.Event(),
        )
    assert calls <= 2
    output.assert_not_called()


@pytest.mark.parametrize("invalid", ["digest", "cancelled"])
def test_invalid_admission_never_starts_child(invalid: str) -> None:
    plan = capture(observed=False)
    cancelled = threading.Event()
    if invalid == "cancelled":
        cancelled.set()
    with (
        patch("trading212_worker.projection_process.subprocess.Popen") as launched,
        pytest.raises(jobs.ProjectionJobInputError) as error,
    ):
        process.calculate_private_projection(
            plan,
            input_digest="a" * 64 if invalid == "digest" else projection_capture_digest(plan),
            load_chunks=_empty,
            save_chunk=lambda _: True,
            cancelled=cancelled,
        )
    assert error.value.code is (
        jobs.ProjectionJobFailureCode.INPUT_CHANGED
        if invalid == "digest"
        else jobs.ProjectionJobFailureCode.LEASE_EXPIRED
    )
    launched.assert_not_called()


@pytest.mark.parametrize("limit", ["deadline", "rss"])
def test_watchdog_kills_and_reaps_actual_child(limit: str) -> None:
    plan = capture(observed=False)
    children: list[subprocess.Popen[bytes]] = []
    original = subprocess.Popen

    def launch(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        child = original(*args, **kwargs)
        children.append(child)
        return child

    observed: Callable[[int], int | None] = (
        (lambda _: 513 * 1024 * 1024) if limit == "rss" else process._resident_bytes
    )
    with (
        patch("trading212_worker.projection_process.subprocess.Popen", side_effect=launch),
        patch("trading212_worker.projection_process._resident_bytes", side_effect=observed),
        pytest.raises(jobs.ProjectionJobInputError) as error,
    ):
        process.calculate_private_projection(
            plan,
            input_digest=projection_capture_digest(plan),
            load_chunks=_empty,
            save_chunk=lambda _: True,
            cancelled=threading.Event(),
            maximum_seconds=0.000001 if limit == "deadline" else 240,
        )
    assert error.value.code is jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED
    assert len(children) == 1 and children[0].poll() is not None
    assert not any(t.name == "projection-child-deadline" for t in threading.enumerate())


def test_full_saved_partition_can_finalize_without_sampler(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = capture(observed=False)
    saved = tuple(
        kernel.calculate_projection_chunk(plan.inputs, 0, plan.inputs.paths, variant=v)
        for v in plan.inputs.variants
    )
    expected = kernel.finalize_projection(plan.inputs, saved)
    monkeypatch.setattr(
        kernel,
        "calculate_projection_chunk",
        lambda *args, **kwargs: pytest.fail("Retained paths were resampled."),
    )
    parent, thread, failures = _start_session()
    try:
        _input(parent)
        for chunk in saved:
            parent.send_bytes(b"S" + projection_canonical_bytes(chunk))
        parent.send_bytes(b"E")
        assert parent.poll(5) and parent.recv_bytes().startswith(b"M")
        assert parent.poll(5)
        assert parent.recv_bytes() == b"R" + projection_canonical_bytes(expected)
        thread.join(timeout=5)
        assert not thread.is_alive() and failures == []
    finally:
        parent.close()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "event,args",
    [("socket.__new__", ()), ("subprocess.Popen", ()), ("open", ("scratch", "wb", os.O_WRONLY))],
)
def test_numerical_child_rejects_network_subprocess_and_scratch_writes(
    event: str, args: tuple[object, ...]
) -> None:
    with pytest.raises(PermissionError):
        process._restrict_external_work(event, args)
    process._restrict_external_work("open", ("installed-module.py", "r", os.O_RDONLY))


def test_checkpoint_bytes_are_checked_cumulatively_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = capture(observed=False)
    first = kernel.calculate_projection_chunk(plan.inputs, 0, 1)
    second = kernel.calculate_projection_chunk(plan.inputs, 1, 1)
    encoded = projection_canonical_bytes(first)
    inventory = process._Inventory(plan.inputs)
    monkeypatch.setattr(process, "PROJECTION_MAX_BYTES", inventory.bytes_used + len(encoded))
    inventory.add(first, encoded)
    with pytest.raises(ValueError):
        inventory.add(second, projection_canonical_bytes(second))
    assert tuple(inventory.paths) == (("baseline", 0),)
    assert (
        sha256(projection_canonical_bytes(first.paths[0])).hexdigest()
        == inventory.paths[("baseline", 0)]
    )
