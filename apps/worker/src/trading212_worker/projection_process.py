"""One fenced checkpoint conversation with one credential-free numerical child."""

from __future__ import annotations

import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from multiprocessing.connection import Connection

from trading212_application import projection_jobs as jobs
from trading212_application.projection_capture import (
    ProjectionCapturePlan,
    projection_capture_digest,
)
from trading212_domain.projection import PROJECTION_MAX_BYTES, ProjectionInput, ProjectionVariant
from trading212_domain.projection_result import ProjectionCalculation, ProjectionChunk
from trading212_domain.projection_serialization import (
    decode_projection_chunk,
    decode_projection_input,
    decode_projection_result,
    projection_canonical_bytes,
    projection_input_digest,
)
from trading212_domain.projection_validation import validate_projection_path_basis

_PROTOCOL = b"t212pi.projection.worker.v1"
_MAX_RSS = 512 * 1024 * 1024
_MAX_FRAME = PROJECTION_MAX_BYTES + 1
type ChunkCursor = tuple[ProjectionVariant, int]
type LoadChunks = Callable[[ChunkCursor | None], tuple[ProjectionChunk, ...]]
type SaveChunk = Callable[[ProjectionChunk], bool]


@dataclass(frozen=True, slots=True)
class ProjectionProcessResult:
    calculation: ProjectionCalculation
    # Observed child-only resident high water, never whole-worker-tree memory.
    peak_rss_bytes: int | None


def _failure(code: jobs.ProjectionJobFailureCode) -> jobs.ProjectionJobInputError:
    return jobs.ProjectionJobInputError(code)


def _receive(connection: Connection) -> bytes:
    value = connection.recv_bytes(maxlength=_MAX_FRAME)
    if not value:
        raise ValueError("Empty projection protocol frame.")
    return value


class _Inventory:
    """Bound complete proof and absolute membership before accepting any path."""

    def __init__(self, inputs: ProjectionInput) -> None:
        self.inputs = inputs
        self.digest = projection_input_digest(inputs)
        self.bytes_used = len(projection_canonical_bytes(inputs))
        self.paths: dict[tuple[ProjectionVariant, int], str] = {}
        self.chunks = 0

    def add(self, chunk: ProjectionChunk, payload: bytes) -> None:
        if (
            type(chunk) is not ProjectionChunk
            or chunk.input_digest != self.digest
            or chunk.variant not in self.inputs.variants
            or self.chunks >= self.inputs.paths * len(self.inputs.variants)
            or self.bytes_used + len(payload) > PROJECTION_MAX_BYTES
        ):
            raise ValueError("Projection checkpoint identity or bound differs.")
        additions: dict[tuple[ProjectionVariant, int], str] = {}
        for path in chunk.paths:
            key = (chunk.variant, path.index)
            if key in self.paths or path.index >= self.inputs.paths:
                raise ValueError("Projection checkpoint overlaps or exceeds requested paths.")
            validate_projection_path_basis(self.inputs, path, chunk.variant)
            additions[key] = sha256(projection_canonical_bytes(path)).hexdigest()
        self.paths.update(additions)
        self.bytes_used += len(payload)
        self.chunks += 1

    def verify_result(self, result: ProjectionCalculation) -> None:
        if (
            result.inputs != self.inputs
            or result.input_digest != self.digest
            or len(self.paths) != self.inputs.paths * len(self.inputs.variants)
        ):
            raise ValueError("Projection result is not the complete requested partition.")
        for variant in result.variants:
            for path in variant.paths:
                if (
                    self.paths.get((variant.variant, path.index))
                    != sha256(projection_canonical_bytes(path)).hexdigest()
                ):
                    raise ValueError("Projection result changes a saved checkpoint.")


def _resident_bytes(pid: int) -> int | None:
    """Linux RSS only; unsupported/unavailable measurement remains explicitly absent."""
    return _status_memory_bytes(pid, "VmRSS:")


def _status_memory_bytes(pid: int, field: str) -> int | None:
    try:
        with open(f"/proc/{pid}/status", encoding="ascii") as status:
            for line in status:
                if line.startswith(field):
                    pieces = line.split()
                    if len(pieces) == 3 and pieces[2] == "kB":
                        return int(pieces[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


def calculate_private_projection(
    plan: ProjectionCapturePlan,
    *,
    input_digest: str,
    load_chunks: LoadChunks,
    save_chunk: SaveChunk,
    cancelled: threading.Event,
    maximum_seconds: float = 240,
) -> ProjectionProcessResult:
    """Callbacks must be cancellation/deadline bounded; no store credentials cross the pipe."""
    if not 0 < maximum_seconds <= 240:
        raise _failure(jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED)
    if cancelled.is_set():
        raise _failure(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
    started = time.monotonic()
    if projection_capture_digest(plan) != input_digest:
        raise _failure(jobs.ProjectionJobFailureCode.INPUT_CHANGED)
    payload = projection_canonical_bytes(plan.inputs)
    inventory = _Inventory(plan.inputs)
    parent, child = multiprocessing.Pipe(duplex=True)
    process: subprocess.Popen[bytes] | None = None
    stop, exceeded = threading.Event(), threading.Event()
    watchdog: threading.Thread | None = None
    peak: int | None = None

    def check() -> None:
        if time.monotonic() - started >= maximum_seconds:
            exceeded.set()
        if cancelled.is_set():
            raise _failure(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
        if exceeded.is_set():
            raise _failure(jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED)

    try:
        process = subprocess.Popen(  # noqa: S603 - fixed module and private inherited descriptor
            [sys.executable, "-B", "-m", __name__, str(child.fileno()), str(os.getpid())],
            pass_fds=(child.fileno(),),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"},
        )
        child.close()

        def watch() -> None:
            nonlocal peak
            while not stop.wait(0.05):
                if process is None:
                    return
                observed = _resident_bytes(process.pid)
                if observed is not None:
                    peak = max(peak or 0, observed)
                    if observed > _MAX_RSS:
                        exceeded.set()
                if time.monotonic() - started >= maximum_seconds:
                    exceeded.set()
                if exceeded.is_set() or cancelled.is_set():
                    with suppress(ProcessLookupError):
                        process.kill()
                    return

        watchdog = threading.Thread(target=watch, name="projection-child-deadline", daemon=True)
        watchdog.start()
        parent.send_bytes(_PROTOCOL)
        parent.send_bytes(plan.numerical_input_digest.encode("ascii"))
        parent.send_bytes(payload)
        cursor: ChunkCursor | None = None
        while True:
            check()
            page = load_chunks(cursor)
            check()
            if type(page) is not tuple or len(page) > 32:
                raise ValueError("Projection checkpoint page exceeds its bound.")
            if not page:
                break
            for chunk in page:
                key = (chunk.variant, chunk.paths[0].index)
                if cursor is not None and key <= cursor:
                    raise ValueError("Projection checkpoint cursor does not advance.")
                encoded = projection_canonical_bytes(chunk)
                inventory.add(chunk, encoded)
                parent.send_bytes(b"S" + encoded)
                cursor = key
        parent.send_bytes(b"E")
        terminal_memory = False
        while True:
            check()
            if not parent.poll(0.05):
                if process.poll() is not None:
                    raise EOFError
                continue
            frame = _receive(parent)
            check()
            if frame.startswith(b"F"):
                raise _failure(jobs.ProjectionJobFailureCode(frame[1:].decode("ascii")))
            if frame.startswith(b"M"):
                if terminal_memory:
                    raise ValueError("Repeated projection memory observation.")
                terminal_memory = True
                raw = frame[1:]
                if raw != b"-":
                    if not raw.isdigit() or len(raw) > 12 or str(int(raw)).encode() != raw:
                        raise ValueError("Invalid projection memory observation.")
                    observed = int(raw)
                    if not 0 < observed <= _MAX_RSS:
                        raise _failure(jobs.ProjectionJobFailureCode.LIMIT_EXCEEDED)
                    peak = max(peak or 0, observed)
            elif frame.startswith(b"C") and not terminal_memory:
                chunk = decode_projection_chunk(frame[1:])
                inventory.add(chunk, frame[1:])
                if not save_chunk(chunk):
                    cancelled.set()
                    raise _failure(jobs.ProjectionJobFailureCode.LEASE_EXPIRED)
                check()
                parent.send_bytes(b"A" + sha256(frame[1:]).hexdigest().encode("ascii"))
            elif frame.startswith(b"R") and terminal_memory:
                result = decode_projection_result(frame[1:])
                inventory.verify_result(result)
                # A terminal frame must be followed by clean EOF, not extra output.
                process.wait(timeout=max(0.001, maximum_seconds - (time.monotonic() - started)))
                if process.returncode != 0:
                    raise EOFError
                try:
                    extra = parent.recv_bytes(maxlength=_MAX_FRAME)
                except EOFError:
                    pass
                else:
                    raise ValueError(f"Unexpected terminal protocol frame length {len(extra)}.")
                check()
                return ProjectionProcessResult(result, peak)
            else:
                raise ValueError("Unexpected projection protocol state.")
    except jobs.ProjectionJobInputError:
        raise
    except (EOFError, OSError, subprocess.TimeoutExpired):
        check()
        raise _failure(jobs.ProjectionJobFailureCode.CALCULATION_FAILED) from None
    except Exception:
        raise _failure(jobs.ProjectionJobFailureCode.CALCULATION_FAILED) from None
    finally:
        stop.set()
        parent.close()
        child.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        if watchdog is not None:
            watchdog.join(timeout=1)


def _child_session(connection: Connection) -> None:
    from trading212_analytics.projection import calculate_projection_chunk, finalize_projection

    if _receive(connection) != _PROTOCOL:
        raise ValueError("Unknown projection worker protocol.")
    expected = connection.recv_bytes(maxlength=64).decode("ascii")
    inputs = decode_projection_input(connection.recv_bytes(maxlength=PROJECTION_MAX_BYTES))
    if projection_input_digest(inputs) != expected:
        raise ValueError("Projection numerical input differs.")
    inventory = _Inventory(inputs)
    chunks: list[ProjectionChunk] = []
    previous: ChunkCursor | None = None
    while True:
        frame = _receive(connection)
        if frame == b"E":
            break
        if not frame.startswith(b"S"):
            raise ValueError("Expected saved projection checkpoint.")
        chunk = decode_projection_chunk(frame[1:])
        key = (chunk.variant, chunk.paths[0].index)
        if previous is not None and key <= previous:
            raise ValueError("Saved projection checkpoint order differs.")
        inventory.add(chunk, frame[1:])
        chunks.append(chunk)
        previous = key
    for variant in inputs.variants:
        start = 0
        while start < inputs.paths:
            if (variant, start) in inventory.paths:
                start += 1
                continue
            end = start + 1
            while end < min(start + 32, inputs.paths) and (variant, end) not in inventory.paths:
                end += 1
            chunk = calculate_projection_chunk(inputs, start, end - start, variant=variant)
            encoded = projection_canonical_bytes(chunk)
            inventory.add(chunk, encoded)
            connection.send_bytes(b"C" + encoded)
            acknowledgement = connection.recv_bytes(maxlength=65)
            if acknowledgement != b"A" + sha256(encoded).hexdigest().encode("ascii"):
                raise ValueError("Projection checkpoint was not durably acknowledged.")
            chunks.append(chunk)
            start = end
    result = finalize_projection(inputs, chunks)
    inventory.verify_result(result)
    encoded_result = projection_canonical_bytes(result)
    connection.send_bytes(b"M" + _high_water_frame())
    connection.send_bytes(b"R" + encoded_result)


def _high_water_frame() -> bytes:
    # ru_maxrss survives exec and can include the parent's pre-exec RSS. VmHWM
    # belongs to this executable's address space and includes peaks polling missed.
    # Both /proc RSS fields are kernel estimates, not whole-worker-tree evidence.
    if sys.platform != "linux":
        return b"-"
    peak = _status_memory_bytes(os.getpid(), "VmHWM:")
    return b"-" if peak is None else str(peak).encode("ascii")


def _restrict_external_work(event: str, args: tuple[object, ...]) -> None:
    if event.startswith("socket.") or event in ("subprocess.Popen", "os.system"):
        raise PermissionError("The numerical child cannot perform external work.")
    if event == "open" and len(args) >= 3:
        mode, flags = args[1:3]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        ):
            raise PermissionError("The numerical child cannot write files.")


def _main() -> None:
    import ctypes
    import resource

    if len(sys.argv) != 3:
        raise SystemExit(2)
    descriptor, parent_pid = sys.argv[1:]
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != int(parent_pid):
        raise SystemExit(2)
    resource.setrlimit(resource.RLIMIT_AS, (_MAX_RSS, _MAX_RSS))
    resource.setrlimit(resource.RLIMIT_CPU, (240, 241))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    sys.addaudithook(_restrict_external_work)
    connection = Connection(int(descriptor))
    try:
        _child_session(connection)
    except MemoryError:
        with suppress(OSError):
            connection.send_bytes(b"Flimit_exceeded")
    except BaseException:
        with suppress(OSError):
            connection.send_bytes(b"Fcalculation_failed")
    finally:
        connection.close()


if __name__ == "__main__":
    _main()
