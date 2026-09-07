"""Deterministic bounded scheduling and opaque continuations for replay adapters."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

MAX_PAGES = 100
MAX_ROWS = 100_000
MAX_PAGE_ROWS = 1000
MAX_ATTEMPTS = 3
OPERATION_SECONDS = 60


class ReplayFault(StrEnum):
    NONE = "none"
    NOT_CONFIGURED = "not_configured"
    UNSUPPORTED = "unsupported"
    AUTHENTICATION_FAILED = "authentication_failed"
    LICENSE_DENIED = "license_denied"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    TRANSIENT_FAILURE = "transient_failure"
    INVALID_SCHEMA = "invalid_schema"
    PAGINATION_INVALID = "pagination_invalid"
    PAYLOAD_TOO_LARGE = "payload_too_large"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayWindow:
    start: int
    stop: int
    continuation: str | None
    deadline: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayAttempt:
    attempt: int
    elapsed_seconds: float
    fault: ReplayFault


class ReplayRuntime:
    """Local, in-process replay scheduling; this is never an HTTP dispatch port.

    Fault scripts, clocks and cursor keys are trusted adapter construction inputs.
    The one-request/second burst-two budget is serialized across concurrent calls.
    A real HTTP implementation would additionally require the committed fixed-origin
    manifest, Redis coordination and pinned-address transport from the provider ADR.
    """

    def __init__(
        self,
        *,
        cursor_key: bytes,
        page_size: int = 1000,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        faults: tuple[ReplayFault, ...] = (),
    ) -> None:
        if (
            not isinstance(cursor_key, bytes)
            or len(cursor_key) < 32
            or type(page_size) is not int
            or not 1 <= page_size <= MAX_PAGE_ROWS
        ):
            raise ValueError("invalid replay runtime configuration")
        if (
            not isinstance(faults, tuple)
            or len(faults) > MAX_PAGES * MAX_ATTEMPTS
            or any(not isinstance(fault, ReplayFault) for fault in faults)
        ):
            raise ValueError("invalid replay failure script")
        self._key = cursor_key
        self._page_size = page_size
        self._clock = monotonic
        self._sleep = sleep
        self._faults = faults
        self._fault_index = 0
        self._tokens = 2.0
        self._refill_at = monotonic()
        if not math.isfinite(self._refill_at):
            raise ValueError("invalid replay scheduling clock")
        self._lock = asyncio.Lock()
        self.attempts: deque[ReplayAttempt] = deque(maxlen=MAX_PAGES * MAX_ATTEMPTS)

    async def _admit(self, deadline: float) -> bool:
        async with self._lock:
            now = self._clock()
            if (
                not math.isfinite(now)
                or not math.isfinite(deadline)
                or now < self._refill_at
                or now >= deadline
            ):
                return False
            self._tokens = min(2.0, self._tokens + now - self._refill_at)
            self._refill_at = now
            if self._tokens < 1:
                delay = 1 - self._tokens
                if now + delay >= deadline:
                    return False
                await self._sleep(delay)
                now = self._clock()
                if not math.isfinite(now) or now < self._refill_at or now >= deadline:
                    return False
                self._tokens = min(2.0, self._tokens + now - self._refill_at)
                self._refill_at = now
            self._tokens -= 1
            return True

    async def run_attempts(self, *, deadline: float | None = None) -> ReplayFault:
        """Exercise one fixed adapter operation with a finite retry budget."""
        start = self._clock()
        deadline = (
            min(deadline, start + OPERATION_SECONDS)
            if deadline is not None
            else start + OPERATION_SECONDS
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if not await self._admit(deadline):
                return ReplayFault.TIMEOUT
            fault = (
                self._faults[self._fault_index]
                if self._fault_index < len(self._faults)
                else ReplayFault.NONE
            )
            self._fault_index += 1
            self.attempts.append(
                ReplayAttempt(attempt=attempt, elapsed_seconds=self._clock() - start, fault=fault)
            )
            if (
                fault
                not in {
                    ReplayFault.RATE_LIMITED,
                    ReplayFault.TIMEOUT,
                    ReplayFault.TRANSIENT_FAILURE,
                }
                or attempt == MAX_ATTEMPTS
            ):
                return fault
            delay = min(2 ** (attempt - 1), 5)
            if self._clock() + delay >= deadline:
                return ReplayFault.TIMEOUT
            await self._sleep(delay)
        raise AssertionError("bounded replay attempt invariant")

    def window(
        self, *, scope: str, count: int, continuation: str | None
    ) -> ReplayWindow | ReplayFault:
        """Bind offset, page budget and canonical request scope to one signed cursor."""
        if type(count) is not int or count > MAX_ROWS or count < 0:
            return ReplayFault.PAYLOAD_TOO_LARGE
        offset, page = 0, 1
        deadline = self._clock() + OPERATION_SECONDS
        if not math.isfinite(deadline):
            return ReplayFault.TIMEOUT
        if continuation is not None:
            if len(continuation) > 256:
                return ReplayFault.PAGINATION_INVALID
            try:
                padding = "=" * (-len(continuation) % 4)
                decoded = base64.b64decode(continuation + padding, altchars=b"-_", validate=True)
                body, signature = decoded[:-32], decoded[-32:]
                valid = hmac.compare_digest(hmac.digest(self._key, body, "sha256"), signature)
                scope_digest, raw_offset, raw_page, raw_deadline = body.decode("ascii").split(":")
                offset, page = int(raw_offset), int(raw_page)
                deadline = float(raw_deadline)
                valid = valid and scope_digest == hashlib.sha256(scope.encode()).hexdigest()
            except (ValueError, UnicodeError):
                valid = False
            if (
                not valid
                or not math.isfinite(deadline)
                or not 1 <= offset <= count
                or not 2 <= page <= MAX_PAGES
                or offset != (page - 1) * self._page_size
                or deadline > self._clock() + OPERATION_SECONDS
            ):
                return ReplayFault.PAGINATION_INVALID
            if self._clock() >= deadline:
                return ReplayFault.TIMEOUT
        stop = min(offset + self._page_size, count)
        next_cursor = None
        if stop < count:
            if page == MAX_PAGES:
                return ReplayFault.PAYLOAD_TOO_LARGE
            scope_hash = hashlib.sha256(scope.encode()).hexdigest()
            body = f"{scope_hash}:{stop}:{page + 1}:{deadline}".encode()
            next_cursor = (
                base64.urlsafe_b64encode(body + hmac.digest(self._key, body, "sha256"))
                .decode("ascii")
                .rstrip("=")
            )
        return ReplayWindow(start=offset, stop=stop, continuation=next_cursor, deadline=deadline)
