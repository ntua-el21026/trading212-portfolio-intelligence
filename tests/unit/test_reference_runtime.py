"""Replay uses deterministic clocks, strict cursor scope and finite retry budgets."""

from dataclasses import dataclass

import pytest
from trading212_reference_data.replay_runtime import ReplayFault, ReplayRuntime, ReplayWindow

pytestmark = pytest.mark.unit


@dataclass
class Clock:
    now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.now += delay


@pytest.mark.parametrize(
    "fault",
    [
        ReplayFault.LICENSE_DENIED,
        ReplayFault.INVALID_SCHEMA,
        ReplayFault.UNSUPPORTED,
        ReplayFault.AUTHENTICATION_FAILED,
    ],
)
async def test_permanent_replay_failures_are_never_retried(fault: ReplayFault) -> None:
    clock = Clock()
    runtime = ReplayRuntime(
        cursor_key=b"x" * 32, monotonic=clock.monotonic, sleep=clock.sleep, faults=(fault,)
    )
    assert await runtime.run_attempts() is fault
    assert len(runtime.attempts) == 1
    assert clock.now == 0


async def test_transient_replay_attempts_stop_at_three_and_recover_when_possible() -> None:
    clock = Clock()
    runtime = ReplayRuntime(
        cursor_key=b"x" * 32,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        faults=(ReplayFault.RATE_LIMITED,) * 4,
    )
    assert await runtime.run_attempts() is ReplayFault.RATE_LIMITED
    assert [item.attempt for item in runtime.attempts] == [1, 2, 3]
    assert clock.now == 3
    assert await runtime.run_attempts() is ReplayFault.NONE
    assert len(runtime.attempts) == 5


async def test_shared_replay_rate_budget_preserves_burst_two_then_one_per_second() -> None:
    clock = Clock()
    runtime = ReplayRuntime(cursor_key=b"x" * 32, monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(5):
        assert await runtime.run_attempts() is ReplayFault.NONE
    assert clock.now == 3


def test_cursor_binds_scope_order_and_row_page_budgets() -> None:
    runtime = ReplayRuntime(cursor_key=b"x" * 32, page_size=2)
    first = runtime.window(scope="price:revision1:owner1:cutoff", count=5, continuation=None)
    assert isinstance(first, ReplayWindow)
    assert (first.start, first.stop) == (0, 2)
    second = runtime.window(
        scope="price:revision1:owner1:cutoff", count=5, continuation=first.continuation
    )
    assert isinstance(second, ReplayWindow) and (second.start, second.stop) == (2, 4)
    assert (
        runtime.window(
            scope="price:revision2:owner1:cutoff", count=5, continuation=first.continuation
        )
        is ReplayFault.PAGINATION_INVALID
    )
    assert (
        runtime.window(
            scope="price:revision1:owner1:cutoff",
            count=5,
            continuation="https://private.example/path",
        )
        is ReplayFault.PAGINATION_INVALID
    )
    assert (
        runtime.window(scope="any", count=100_001, continuation=None)
        is ReplayFault.PAYLOAD_TOO_LARGE
    )


async def test_logical_pagination_deadline_cannot_restart_on_the_next_page() -> None:
    clock = Clock()
    runtime = ReplayRuntime(
        cursor_key=b"x" * 32, page_size=1, monotonic=clock.monotonic, sleep=clock.sleep
    )
    page = runtime.window(scope="fixed-request", count=3, continuation=None)
    assert isinstance(page, ReplayWindow)
    clock.now = 59
    second = runtime.window(scope="fixed-request", count=3, continuation=page.continuation)
    assert isinstance(second, ReplayWindow) and second.deadline == 60
    clock.now = 60
    assert await runtime.run_attempts(deadline=second.deadline) is ReplayFault.TIMEOUT
    assert (
        runtime.window(scope="fixed-request", count=3, continuation=second.continuation)
        is ReplayFault.TIMEOUT
    )


async def test_oversleep_cannot_dispatch_a_retry_after_deadline() -> None:
    clock = Clock()

    async def slow_sleep(_: float) -> None:
        clock.now += 61

    runtime = ReplayRuntime(
        cursor_key=b"x" * 32,
        monotonic=clock.monotonic,
        sleep=slow_sleep,
        faults=(ReplayFault.TIMEOUT,),
    )
    assert await runtime.run_attempts() is ReplayFault.TIMEOUT
    assert len(runtime.attempts) == 1


def test_replay_page_budget_rejects_a_truncated_successful_prefix() -> None:
    runtime = ReplayRuntime(cursor_key=b"x" * 32, page_size=2)
    cursor = None
    for _ in range(99):
        page = runtime.window(scope="bounded", count=201, continuation=cursor)
        assert isinstance(page, ReplayWindow)
        cursor = page.continuation
    assert (
        runtime.window(scope="bounded", count=201, continuation=cursor)
        is ReplayFault.PAYLOAD_TOO_LARGE
    )
