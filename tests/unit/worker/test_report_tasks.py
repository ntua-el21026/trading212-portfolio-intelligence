"""Durable worker orchestration, isolated rendering and private cleanup."""

import asyncio
import hashlib
import os
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from trading212_application import report_jobs as jobs
from trading212_application import reports as app
from trading212_domain.reports import ReportFailureCode, ReportFormat
from trading212_worker import report_render_process as process
from trading212_worker.report_renderers import PrivateReportRenderer
from trading212_worker.report_tasks import (
    ReportExecutionState,
    dispatch_reports_once,
    execute_report_message,
)

from tests.unit.domain.report_factories import AT, ReportFixture, document, uid

pytestmark = pytest.mark.unit


def message() -> jobs.ReportTaskMessage:
    return jobs.ReportTaskMessage(
        job_id=uid(101),
        owner_id=uid(102),
        account_id=uid(1),
        capture_id=uid(103),
        input_digest="a" * 64,
    )


def store(value: ReportFixture) -> Mock:
    claim = jobs.ReportJobClaim(
        message=message(),
        lease_id=uid(104),
        fence=1,
        lease_expires_at=AT + timedelta(seconds=60),
        consumer_attempt=1,
    )
    result = Mock()
    result.claim_report_job = AsyncMock(return_value=claim)
    result.heartbeat_report_job = AsyncMock(return_value=True)
    result.complete_report_job = AsyncMock(return_value=True)
    result.fail_report_job = AsyncMock(return_value=True)

    @contextmanager
    def opening(_claim: jobs.ReportJobClaim):  # type: ignore[no-untyped-def]
        try:
            yield value
        finally:
            result.document_closed()

    result.open_report_document = opening
    return result


def test_worker_publishes_all_requested_formats_once_then_closes_document() -> None:
    value = document((ReportFormat.JSON, ReportFormat.CSV))
    retained = store(value)
    outcome = asyncio.run(
        execute_report_message(
            cast(jobs.ReportJobStore, retained),
            message(),
            consumer_id="unit-report",
            renderer=PrivateReportRenderer(),
        )
    )
    assert outcome is ReportExecutionState.COMPLETED
    retained.complete_report_job.assert_awaited_once()
    artifacts = retained.complete_report_job.await_args.kwargs["artifacts"]
    assert {item.format for item in artifacts} == {ReportFormat.JSON, ReportFormat.CSV}
    assert all(
        item.content_digest == hashlib.sha256(item.content).hexdigest() for item in artifacts
    )
    retained.fail_report_job.assert_not_awaited()
    retained.document_closed.assert_called_once()


def test_second_format_failure_never_publishes_first_format() -> None:
    retained = store(document((ReportFormat.JSON, ReportFormat.CSV)))
    renderer = Mock()
    real = PrivateReportRenderer()
    calls = 0

    def render(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise app.ReportRenderError(ReportFailureCode.LIMIT_EXCEEDED)
        return real.render(*args, **kwargs)  # type: ignore[arg-type]

    renderer.render.side_effect = render
    outcome = asyncio.run(
        execute_report_message(
            cast(jobs.ReportJobStore, retained),
            message(),
            consumer_id="unit-report",
            renderer=renderer,
        )
    )
    assert outcome is ReportExecutionState.FAILED
    retained.complete_report_job.assert_not_awaited()
    assert retained.fail_report_job.await_args.kwargs["failure"] is ReportFailureCode.LIMIT_EXCEEDED
    retained.document_closed.assert_called_once()


def test_unclaimed_delivery_never_opens_document() -> None:
    retained = store(document((ReportFormat.JSON,)))
    retained.claim_report_job.return_value = None
    retained.open_report_document = Mock()
    assert (
        asyncio.run(
            execute_report_message(
                cast(jobs.ReportJobStore, retained), message(), consumer_id="unit-report"
            )
        )
        is ReportExecutionState.NOT_CLAIMED
    )
    retained.open_report_document.assert_not_called()


def test_dispatch_failure_returns_to_persistent_retry_without_celery_retry() -> None:
    retained, publisher = Mock(), Mock()
    claim = jobs.ReportDispatchClaim(
        message=message(),
        claim_token=uid(105),
        claim_expires_at=AT + timedelta(seconds=30),
        publication_attempt=1,
    )
    retained.claim_report_dispatches = AsyncMock(return_value=(claim,))
    retained.defer_report_dispatch = AsyncMock(return_value=True)
    retained.acknowledge_report_dispatch = AsyncMock()
    publisher.publish_report = AsyncMock(side_effect=OSError("private failure text"))
    result = asyncio.run(dispatch_reports_once(retained, publisher, dispatcher_id="unit-dispatch"))
    assert result.claimed == 1 and result.deferred == 1 and result.published == 0
    retained.acknowledge_report_dispatch.assert_not_awaited()
    retained.defer_report_dispatch.assert_awaited_once_with(
        claim, failure=ReportFailureCode.PUBLICATION_UNAVAILABLE
    )


@pytest.mark.parametrize("format", tuple(ReportFormat))
def test_real_renderer_child_returns_canonical_artifact_and_removes_scratch(
    format: ReportFormat,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    value = document((format,))
    artifact = process.render_private_artifact(value, format, cancelled=threading.Event())
    assert artifact.content_digest == hashlib.sha256(artifact.content).hexdigest()
    assert artifact.byte_length == len(artifact.content) > 0
    root = tmp_path / f"t212pi-report-render-{os.getuid()}"
    assert tuple(root.iterdir()) == ()


def test_cancelled_child_and_spawn_failure_remove_owned_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(app.ReportRenderError):
        process.render_private_artifact(
            document((ReportFormat.JSON,)), ReportFormat.JSON, cancelled=cancelled
        )
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=OSError("private spawn error")))
    with pytest.raises(app.ReportRenderError):
        process.render_private_artifact(
            document((ReportFormat.JSON,)), ReportFormat.JSON, cancelled=threading.Event()
        )
    assert tuple((tmp_path / f"t212pi-report-render-{os.getuid()}").iterdir()) == ()


def test_orphan_recovery_preserves_live_and_unrelated_workspaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with process._workspace() as live:
        root = Path(live).parent
        stale = root / "job-stale"
        stale.mkdir()
        (stale / "owner").write_text("2147483647:missing")
        (stale / "partial.xlsx").write_bytes(b"private incomplete artifact")
        unrelated = root / "unrelated"
        unrelated.mkdir()
        with process._workspace():
            assert not stale.exists()
            assert Path(live).exists() and unrelated.exists()
