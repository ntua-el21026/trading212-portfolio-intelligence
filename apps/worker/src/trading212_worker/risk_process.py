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
from dataclasses import replace
from hashlib import sha256
from multiprocessing.connection import Connection

from trading212_application import risk_jobs as jobs
from trading212_domain.historical_serialization import (
    historical_value_from_json,
)
from trading212_domain.risk_result import RiskCalculation
from trading212_domain.risk_serialization import canonical_risk_bytes, risk_result_from_json
from trading212_domain.xray_codec import decode_xray_result

_MAX_BYTES = 33554432


def calculate_private_risk(
    value: jobs.RiskExecutionInput, *, cancelled: threading.Event, maximum_seconds: float = 240
) -> RiskCalculation:
    """Wall timing is operational; all financial transforms stay in the Decimal core."""
    if not 0 < maximum_seconds <= 240:
        raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.LIMIT_EXCEEDED)
    if cancelled.is_set():
        raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.LEASE_EXPIRED)
    payload, xray = jobs.risk_execution_bytes(value)
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
        watchdog = threading.Thread(target=watch, name="risk-child-deadline", daemon=True)
        watchdog.start()
        parent.send_bytes(payload)
        parent.send_bytes(xray)
        while not parent.poll(0.1):
            if process.poll() is not None:
                raise EOFError
        response = parent.recv_bytes(maxlength=_MAX_BYTES + 64)
        if response.startswith(b"failed:"):
            raise jobs.RiskJobInputError(jobs.RiskJobFailureCode(response[7:].decode("ascii")))
        if not response.startswith(b"ok:") or len(response) > _MAX_BYTES + 3:
            raise jobs.RiskJobInputError(jobs.RiskJobFailureCode.CALCULATION_FAILED)
        result = response[3:]
        if time.monotonic() - started >= maximum_seconds:
            timed_out.set()
        if cancelled.is_set() or timed_out.is_set():
            raise EOFError
        return risk_result_from_json(result, expected_digest=sha256(result).hexdigest())
    except (EOFError, OSError):
        code = (
            jobs.RiskJobFailureCode.LEASE_EXPIRED
            if cancelled.is_set()
            else jobs.RiskJobFailureCode.LIMIT_EXCEEDED
            if timed_out.is_set()
            else jobs.RiskJobFailureCode.CALCULATION_FAILED
        )
        raise jobs.RiskJobInputError(code) from None
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
        from trading212_analytics.risk import calculate_risk

        payload = connection.recv_bytes(maxlength=_MAX_BYTES)
        xray = connection.recv_bytes(maxlength=_MAX_BYTES - len(payload))
        value = historical_value_from_json(payload, jobs.RiskExecutionInput)
        if value.xray is not None:
            raise ValueError("X-ray must use its fixed exact codec.")
        value = replace(value, xray=None if not xray else decode_xray_result(xray))
        result = calculate_risk(
            value.historical, value.definition, assets=value.assets, xray=value.xray
        )
        connection.send_bytes(b"ok:" + canonical_risk_bytes(result))
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
