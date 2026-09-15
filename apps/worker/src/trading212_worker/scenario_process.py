"""One memory/time bounded child with fixed codecs, no credentials, files or network work."""

from __future__ import annotations

import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import suppress
from hashlib import sha256
from multiprocessing.connection import Connection

from trading212_application import scenario_jobs as jobs
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_domain.scenario_serialization import (
    ScenarioExecutionParts,
    canonical_scenario_bytes,
    decode_scenario_execution,
    scenario_result_from_json,
)

_MAX_BYTES = 33554432


def calculate_private_scenario(
    value: jobs.ScenarioExecutionInput, *, cancelled: threading.Event, maximum_seconds: float = 240
) -> ScenarioCalculation:
    """Wall timing is operational; all financial transforms stay in the Decimal core."""
    if not 0 < maximum_seconds <= 240:
        raise jobs.ScenarioJobInputError(jobs.ScenarioJobFailureCode.LIMIT_EXCEEDED)
    if cancelled.is_set():
        raise jobs.ScenarioJobInputError(jobs.ScenarioJobFailureCode.LEASE_EXPIRED)
    parts = jobs.scenario_execution_bytes(value)
    parent, child = multiprocessing.Pipe(duplex=True)
    process: subprocess.Popen[bytes] | None = None
    stop = threading.Event()
    timed_out = threading.Event()
    watchdog: threading.Thread | None = None
    started = time.monotonic()
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed module and private inherited descriptor
            [sys.executable, "-m", __name__, str(child.fileno()), str(os.getpid())],
            pass_fds=(child.fileno(),),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"},
        )
        child.close()

        def watch() -> None:
            while not stop.wait(0.1):
                if time.monotonic() - started >= maximum_seconds:
                    timed_out.set()
                if timed_out.is_set() or cancelled.is_set():
                    with suppress(ProcessLookupError):
                        if process is not None:
                            process.kill()
                    return

        # This also interrupts a blocked pipe write/read if the child stops responding.
        watchdog = threading.Thread(target=watch, name="scenario-child-deadline", daemon=True)
        watchdog.start()
        parent.send_bytes(value.input_digest.encode("ascii"))
        for payload in (parts.main, parts.xray_input, parts.xray_result, parts.historical_input):
            parent.send_bytes(payload)
        while not parent.poll(0.1):
            if process.poll() is not None:
                raise EOFError
        response = parent.recv_bytes(maxlength=_MAX_BYTES + 64)
        if response.startswith(b"failed:"):
            raise jobs.ScenarioJobInputError(
                jobs.ScenarioJobFailureCode(response[7:].decode("ascii"))
            )
        if not response.startswith(b"ok:") or len(response) > _MAX_BYTES + 3:
            raise jobs.ScenarioJobInputError(jobs.ScenarioJobFailureCode.CALCULATION_FAILED)
        result = response[3:]
        if time.monotonic() - started >= maximum_seconds:
            timed_out.set()
        if cancelled.is_set() or timed_out.is_set():
            raise EOFError
        decoded = scenario_result_from_json(
            result, expected_digest=sha256(b"t212pi.scenario.result.v1\0" + result).hexdigest()
        )
        if decoded.input_digest != value.input_digest or decoded.pins != value.pins:
            raise jobs.ScenarioJobInputError(jobs.ScenarioJobFailureCode.INPUT_CHANGED)
        return decoded
    except (EOFError, OSError):
        code = (
            jobs.ScenarioJobFailureCode.LEASE_EXPIRED
            if cancelled.is_set()
            else jobs.ScenarioJobFailureCode.LIMIT_EXCEEDED
            if timed_out.is_set()
            else jobs.ScenarioJobFailureCode.CALCULATION_FAILED
        )
        raise jobs.ScenarioJobInputError(code) from None
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


def _main() -> None:
    import ctypes
    import resource

    if len(sys.argv) != 3:
        raise SystemExit(2)
    descriptor, parent_pid = sys.argv[1:]
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != int(parent_pid):
        raise SystemExit(2)
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (240, 241))
    connection = Connection(int(descriptor))
    try:
        from trading212_analytics.scenario import calculate_scenario

        expected_digest = connection.recv_bytes(maxlength=64).decode("ascii")
        if len(expected_digest) != 64 or any(c not in "0123456789abcdef" for c in expected_digest):
            raise ValueError("Invalid scenario input identity.")
        remaining = _MAX_BYTES
        parts = []
        for _ in range(4):
            payload = connection.recv_bytes(maxlength=remaining)
            remaining -= len(payload)
            parts.append(payload)
        value = decode_scenario_execution(
            ScenarioExecutionParts(
                main=parts[0],
                xray_input=parts[1],
                xray_result=parts[2],
                historical_input=parts[3],
            ),
            expected_digest=expected_digest,
        )
        result = calculate_scenario(value)
        connection.send_bytes(b"ok:" + canonical_scenario_bytes(result))
    except MemoryError:
        with suppress(OSError):
            connection.send_bytes(b"failed:limit_exceeded")
    except BaseException:
        with suppress(OSError):
            connection.send_bytes(b"failed:calculation_failed")
    finally:
        connection.close()


if __name__ == "__main__":
    _main()
