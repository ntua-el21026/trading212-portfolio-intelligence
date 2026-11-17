"""Worker-clock opt-in leaves controlled financial fixture time unchanged."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from trading212_application import reports as app
from trading212_domain import reports
from trading212_worker.report_tasks import ReportExecutionState

import tests.integration.research_report_case as fixture

AT = datetime(2026, 11, 17, tzinfo=UTC)


def case_with_clock_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[fixture.ResearchReportCase, app.ReportJobStatus, list[Callable[[], datetime]]]:
    status = cast(
        app.ReportJobStatus,
        SimpleNamespace(
            job_id=UUID(int=1), state=reports.ReportJobState.SUCCEEDED, failure_code=None
        ),
    )
    case = cast(
        fixture.ResearchReportCase,
        SimpleNamespace(
            research=SimpleNamespace(
                xray=SimpleNamespace(now=[AT], sessions=object(), principal=object()),
                account_id=UUID(int=2),
            ),
            reports=SimpleNamespace(get_report_status=AsyncMock(return_value=status)),
        ),
    )
    clocks: list[Callable[[], datetime]] = []

    def store(_sessions: object, *, clock: Callable[[], datetime]) -> object:
        clocks.append(clock)
        return object()

    monkeypatch.setattr(fixture, "PostgresReportJobStore", store)
    monkeypatch.setattr(fixture, "message", Mock(return_value=object()))
    monkeypatch.setattr(
        fixture,
        "execute_report_message",
        AsyncMock(return_value=ReportExecutionState.COMPLETED),
    )
    return case, status, clocks


async def test_default_completion_retains_the_controlled_fixture_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, pending, clocks = case_with_clock_spy(monkeypatch)
    assert await fixture.complete(case, pending) is pending
    assert len(clocks) == 1 and clocks[0]() == AT
    case.research.xray.now[0] += timedelta(days=31)
    assert clocks[0]() == case.research.xray.now[0]


async def test_live_worker_clock_is_opt_in_and_never_advances_financial_fixture_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, pending, clocks = case_with_clock_spy(monkeypatch)
    observed = [AT + timedelta(seconds=30)]

    def worker_clock() -> datetime:
        return observed[0]

    assert await fixture.complete(case, pending, worker_clock=worker_clock) is pending
    assert len(clocks) == 1 and clocks[0]() == observed[0]
    observed[0] += timedelta(seconds=30)
    assert clocks[0]() == observed[0]
    assert case.research.xray.now[0] == AT
