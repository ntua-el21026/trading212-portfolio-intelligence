"""The shared dispatcher schedules bounded source cleanup independently of publication."""

from __future__ import annotations

import signal
from contextlib import nullcontext
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
import trading212_persistence.alert_job_store as alert_jobs
import trading212_persistence.alert_retention as alert_retention
import trading212_persistence.notification_store as notifications
import trading212_persistence.planning_service as plans
import trading212_persistence.report_job_store as reports
import trading212_worker.outbox_dispatcher as dispatcher
from trading212_observability import MetricsHttpServer


@dataclass
class Polls:
    remaining: int = 2
    intervals: list[float] = field(default_factory=list)

    def is_set(self) -> bool:
        return self.remaining == 0

    def set(self) -> None:
        self.remaining = 0

    def wait(self, interval: float) -> None:
        self.intervals.append(interval)
        self.remaining -= 1


@pytest.fixture
def composition(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, AsyncMock, Polls]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://portfolio:portfolio@db/portfolio")
    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
    monkeypatch.setenv("T212PI_ENVIRONMENT", "test")
    monkeypatch.setenv("T212PI_OUTBOX_POLL_SECONDS", "0.25")
    monkeypatch.setenv("T212PI_COLLECTION_SNAPSHOT_CLEANUP_BATCH_SIZE", "1000")
    monkeypatch.setattr(dispatcher, "configure_logging", Mock())
    monkeypatch.setattr(dispatcher, "configure_tracing", Mock())
    monkeypatch.setattr(signal, "signal", Mock())
    monkeypatch.setattr(dispatcher, "create_database_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(dispatcher, "create_session_factory", Mock(return_value=MagicMock()))
    monkeypatch.setattr(dispatcher, "Celery", Mock(return_value=Mock()))
    monkeypatch.setattr(dispatcher, "PostgresOutboxDispatcher", Mock(return_value=Mock()))
    monkeypatch.setattr(
        dispatcher,
        "PostgresTargetService",
        Mock(return_value=SimpleNamespace(activate_due_versions=AsyncMock(return_value=0))),
    )
    monkeypatch.setattr(plans, "PostgresPlanningService", Mock(return_value=Mock()))
    monkeypatch.setattr(
        reports,
        "PostgresReportJobStore",
        Mock(return_value=SimpleNamespace(expire_report_artifacts=AsyncMock(return_value=0))),
    )
    monkeypatch.setattr(
        alert_jobs,
        "PostgresAlertJobStore",
        Mock(return_value=SimpleNamespace(admit_due_evaluations=AsyncMock(return_value=0))),
    )
    monkeypatch.setattr(notifications, "PostgresAlertNotificationStore", Mock())
    monkeypatch.setattr(alert_retention, "expire_alert_payloads", Mock(return_value=0))
    result = SimpleNamespace(published=0, deferred=0, fenced=0)
    for name in (
        "dispatch_plans_once",
        "dispatch_reports_once",
        "dispatch_exports_once",
        "dispatch_alerts_once",
        "dispatch_notifications_once",
    ):
        monkeypatch.setattr(dispatcher, name, AsyncMock(return_value=result))
    publish = AsyncMock(return_value=result)
    monkeypatch.setattr(dispatcher, "dispatch_reports_once", publish)
    cleanup = AsyncMock(return_value=0)
    monkeypatch.setattr(
        dispatcher,
        "PostgresSourceService",
        Mock(return_value=SimpleNamespace(expire_source_snapshots=cleanup)),
    )
    polls = Polls()
    monkeypatch.setattr(dispatcher, "Event", lambda: polls)
    monkeypatch.setattr(MetricsHttpServer, "start", Mock(return_value=nullcontext()))
    return cleanup, publish, polls


def test_once_schedules_one_fixed_source_budget(
    composition: tuple[AsyncMock, AsyncMock, Polls],
) -> None:
    cleanup, _, polls = composition
    assert dispatcher.main(["--once"]) == 0
    cleanup.assert_awaited_once_with(limit=100)
    assert polls.intervals == []


def test_cleanup_runs_despite_publication_failure_and_recovers_next_poll(
    composition: tuple[AsyncMock, AsyncMock, Polls], caplog: pytest.LogCaptureFixture
) -> None:
    cleanup, publish, polls = composition
    canary = "private-source-detail-never-log"
    publish.side_effect = RuntimeError(canary)
    cleanup.side_effect = [RuntimeError(canary), 0]
    assert dispatcher.main([]) == 0
    assert cleanup.await_count == publish.await_count == 2
    assert all(call.kwargs == {"limit": 100} for call in cleanup.await_args_list)
    assert polls.intervals == [0.25, 0.25]
    assert "source_payload_expiry_cycle_failed" in caplog.text
    assert "report_outbox_cycle_failed" in caplog.text
    assert canary not in caplog.text


def test_once_propagates_cleanup_failure_without_claiming_completion(
    composition: tuple[AsyncMock, AsyncMock, Polls],
) -> None:
    cleanup, _, _ = composition
    cleanup.side_effect = RuntimeError("bounded cleanup failure")
    with pytest.raises(RuntimeError, match="bounded cleanup failure"):
        dispatcher.main(["--once"])
    cleanup.assert_awaited_once_with(limit=100)
