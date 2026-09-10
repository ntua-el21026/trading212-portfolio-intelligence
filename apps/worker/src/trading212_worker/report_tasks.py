"""Fixed report/export delivery and rendering under PostgreSQL-owned leases."""

from __future__ import annotations

import asyncio
import logging
import secrets
import threading
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from celery import Celery, Task  # type: ignore[import-untyped]
from trading212_application import report_jobs as jobs
from trading212_application import reports as app
from trading212_domain.errors import DomainError
from trading212_domain.reports import ReportFailureCode, ReportManifest
from trading212_persistence import create_database_engine, create_session_factory

_LOGGER = logging.getLogger("trading212_worker.reports")
type JobStore = jobs.ReportJobStore | jobs.ExportJobStore
type TaskMessage = jobs.ReportTaskMessage | jobs.ExportTaskMessage
type JobClaim = jobs.ReportJobClaim | jobs.ExportJobClaim


class CeleryReportPublisher:
    def __init__(self, application: Celery) -> None:
        self._application = application

    async def publish_report(self, message: jobs.ReportTaskMessage) -> None:
        await asyncio.to_thread(
            self._application.send_task,
            jobs.REPORT_TASK_NAME,
            kwargs=message.to_wire(),
            task_id=str(message.job_id),
            retry=False,
            ignore_result=True,
        )


class CeleryExportPublisher:
    def __init__(self, application: Celery) -> None:
        self._application = application

    async def publish_export(self, message: jobs.ExportTaskMessage) -> None:
        await asyncio.to_thread(
            self._application.send_task,
            jobs.EXPORT_TASK_NAME,
            kwargs=message.to_wire(),
            task_id=str(message.job_id),
            retry=False,
            ignore_result=True,
        )


@dataclass(frozen=True, slots=True)
class ReportDispatchResult:
    claimed: int
    published: int
    deferred: int
    fenced: int


async def dispatch_reports_once(
    store: jobs.ReportJobStore,
    publisher: jobs.ReportTaskPublisher,
    *,
    dispatcher_id: str,
    limit: int = 20,
) -> ReportDispatchResult:
    claims = await store.claim_report_dispatches(dispatcher_id=dispatcher_id, limit=limit)
    published = deferred = fenced = 0
    for claim in claims:
        try:
            await publisher.publish_report(claim.message)
        except Exception:
            retained = await store.defer_report_dispatch(
                claim, failure=ReportFailureCode.PUBLICATION_UNAVAILABLE
            )
            deferred += int(retained)
            fenced += int(not retained)
        else:
            retained = await store.acknowledge_report_dispatch(claim)
            published += int(retained)
            fenced += int(not retained)
    return ReportDispatchResult(len(claims), published, deferred, fenced)


async def dispatch_exports_once(
    store: jobs.ExportJobStore,
    publisher: jobs.ExportTaskPublisher,
    *,
    dispatcher_id: str,
    limit: int = 20,
) -> ReportDispatchResult:
    claims = await store.claim_export_dispatches(dispatcher_id=dispatcher_id, limit=limit)
    published = deferred = fenced = 0
    for claim in claims:
        try:
            await publisher.publish_export(claim.message)
        except Exception:
            retained = await store.defer_export_dispatch(
                claim, failure=ReportFailureCode.PUBLICATION_UNAVAILABLE
            )
            deferred += int(retained)
            fenced += int(not retained)
        else:
            retained = await store.acknowledge_export_dispatch(claim)
            published += int(retained)
            fenced += int(not retained)
    return ReportDispatchResult(len(claims), published, deferred, fenced)


class ReportExecutionState(StrEnum):
    COMPLETED = "completed"
    NOT_CLAIMED = "not_claimed"
    FENCED = "fenced"
    FAILED = "failed"
    DEFERRED = "deferred"
    RECOVERY_PENDING = "recovery_pending"


class _RenderGuard:
    def __init__(self, cancelled: threading.Event) -> None:
        self._cancelled = cancelled

    def check(self) -> None:
        if self._cancelled.is_set():
            raise app.ReportRenderError(ReportFailureCode.LEASE_EXPIRED)


def _render(
    store: JobStore,
    claim: JobClaim,
    cancelled: threading.Event,
    renderer: app.ReportRendererPort | None,
) -> tuple[ReportManifest, tuple[app.RenderedArtifact, ...]]:
    from .report_render_process import render_private_artifact
    from .report_renderers import BoundedArtifactBuffer

    opening = (
        cast(jobs.ReportJobStore, store).open_report_document(claim)
        if isinstance(claim, jobs.ReportJobClaim)
        else cast(jobs.ExportJobStore, store).open_export_document(claim)
    )
    artifacts: list[app.RenderedArtifact] = []
    guard = _RenderGuard(cancelled)
    try:
        with opening as document:
            manifest = document.manifest
            formats = tuple(
                version.format for version in manifest.renderer_profile.renderer_versions
            )
            if not 1 <= len(formats) <= 4 or len(set(formats)) != len(formats):
                raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
            for format in formats:
                guard.check()
                if renderer is None:
                    artifact = render_private_artifact(document, format, cancelled=cancelled)
                else:
                    # A bounded explicit test port; production always uses the isolated child.
                    with BoundedArtifactBuffer(guard=guard) as buffer:
                        receipt = renderer.render(
                            document,
                            format=format,
                            profile=manifest.renderer_profile,
                            sink=buffer,
                            guard=guard,
                        )
                        artifact = buffer.finish(receipt)
                artifacts.append(artifact)
                if sum(item.byte_length for item in artifacts) > 25 * 1024 * 1024:
                    raise app.ReportRenderError(ReportFailureCode.LIMIT_EXCEEDED)
            guard.check()
            if document.manifest != manifest:
                raise app.ReportRenderError(ReportFailureCode.INPUT_CHANGED)
            return manifest, tuple(artifacts)
    except BaseException:
        artifacts.clear()
        raise


async def _execute(
    store: JobStore,
    message: TaskMessage,
    *,
    consumer_id: str,
    renderer: app.ReportRendererPort | None,
) -> ReportExecutionState:
    claim: JobClaim | None
    if isinstance(message, jobs.ReportTaskMessage):
        claim = await cast(jobs.ReportJobStore, store).claim_report_job(
            message, consumer_id=consumer_id
        )
    else:
        claim = await cast(jobs.ExportJobStore, store).claim_export_job(
            message, consumer_id=consumer_id
        )
    if claim is None:
        return ReportExecutionState.NOT_CLAIMED
    stopped = asyncio.Event()
    cancelled = threading.Event()

    async def heartbeat() -> None:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=jobs.REPORT_HEARTBEAT_SECONDS)
            except TimeoutError:
                try:
                    retained = (
                        await cast(jobs.ReportJobStore, store).heartbeat_report_job(claim)
                        if isinstance(claim, jobs.ReportJobClaim)
                        else await cast(jobs.ExportJobStore, store).heartbeat_export_job(claim)
                    )
                except Exception:
                    retained = False
                if not retained:
                    cancelled.set()
                    return

    async def fail(code: ReportFailureCode, retryable: bool) -> ReportExecutionState:
        if cancelled.is_set():
            return ReportExecutionState.FENCED
        try:
            retained = (
                await cast(jobs.ReportJobStore, store).fail_report_job(
                    claim, failure=code, retryable=retryable
                )
                if isinstance(claim, jobs.ReportJobClaim)
                else await cast(jobs.ExportJobStore, store).fail_export_job(
                    claim, failure=code, retryable=retryable
                )
            )
        except Exception:
            return ReportExecutionState.RECOVERY_PENDING
        if not retained:
            return ReportExecutionState.FENCED
        return ReportExecutionState.DEFERRED if retryable else ReportExecutionState.FAILED

    pulse = asyncio.create_task(heartbeat())
    work = asyncio.create_task(asyncio.to_thread(_render, store, claim, cancelled, renderer))
    try:
        try:
            manifest, artifacts = await asyncio.shield(work)
        except (app.ReportRenderError, jobs.ReportJobInputError) as error:
            return await fail(error.code, error.retryable)
        except DomainError:
            return await fail(ReportFailureCode.INPUT_CHANGED, False)
        except Exception:
            return await fail(ReportFailureCode.RENDER_FAILED, False)
        if cancelled.is_set():
            return ReportExecutionState.FENCED
        try:
            retained = (
                await cast(jobs.ReportJobStore, store).complete_report_job(
                    claim, manifest=manifest, artifacts=artifacts
                )
                if isinstance(claim, jobs.ReportJobClaim)
                else await cast(jobs.ExportJobStore, store).complete_export_job(
                    claim, manifest=manifest, artifacts=artifacts
                )
            )
        except jobs.ReportJobInputError as error:
            return await fail(error.code, error.retryable)
        except Exception:
            return await fail(ReportFailureCode.STORAGE_UNAVAILABLE, True)
        return ReportExecutionState.COMPLETED if retained else ReportExecutionState.FENCED
    finally:
        cancelled.set()
        stopped.set()
        await pulse
        if not work.done():
            # Cancelling to_thread alone leaves its child running. Await the bounded
            # pipe loop's termination and scratch cleanup before returning.
            with suppress(Exception):
                await asyncio.shield(work)


async def execute_report_message(
    store: jobs.ReportJobStore,
    message: jobs.ReportTaskMessage,
    *,
    consumer_id: str,
    renderer: app.ReportRendererPort | None = None,
) -> ReportExecutionState:
    return await _execute(store, message, consumer_id=consumer_id, renderer=renderer)


async def execute_export_message(
    store: jobs.ExportJobStore,
    message: jobs.ExportTaskMessage,
    *,
    consumer_id: str,
    renderer: app.ReportRendererPort | None = None,
) -> ReportExecutionState:
    return await _execute(store, message, consumer_id=consumer_id, renderer=renderer)


def _run(database_url: str, message: TaskMessage) -> ReportExecutionState:
    from trading212_persistence.report_job_store import PostgresReportJobStore

    engine = create_database_engine(database_url)
    try:
        store = PostgresReportJobStore(create_session_factory(engine))
        consumer = "report-worker:" + secrets.token_hex(12)
        if isinstance(message, jobs.ReportTaskMessage):
            return asyncio.run(execute_report_message(store, message, consumer_id=consumer))
        return asyncio.run(execute_export_message(store, message, consumer_id=consumer))
    finally:
        engine.dispose()


def register_report_tasks(application: Celery, *, database_url: str) -> None:
    application.tasks.pop(jobs.REPORT_TASK_NAME, None)
    application.tasks.pop(jobs.EXPORT_TASK_NAME, None)

    def invoke(
        task: Task, args: tuple[object, ...], payload: dict[str, object], *, export: bool
    ) -> dict[str, str]:
        try:
            if args:
                return {"state": "rejected"}
            message = (
                jobs.ExportTaskMessage.from_wire(payload)
                if export
                else jobs.ReportTaskMessage.from_wire(payload)
            )
            if task.request.id != str(message.job_id):
                return {"state": "rejected"}
        except (DomainError, ValueError, TypeError):
            return {"state": "rejected"}
        try:
            outcome = _run(database_url, message)
        except Exception:
            _LOGGER.error("report_consumer_recovery_pending")
            return {"state": ReportExecutionState.RECOVERY_PENDING.value}
        _LOGGER.info("report_consumer_finished", extra={"outcome": outcome.value})
        return {"state": outcome.value}

    @application.task(bind=True, name=jobs.REPORT_TASK_NAME, ignore_result=True, max_retries=0)  # type: ignore[untyped-decorator]
    def generate_report(task: Task, *args: object, **payload: object) -> dict[str, str]:
        return invoke(task, args, payload, export=False)

    @application.task(bind=True, name=jobs.EXPORT_TASK_NAME, ignore_result=True, max_retries=0)  # type: ignore[untyped-decorator]
    def generate_export(task: Task, *args: object, **payload: object) -> dict[str, str]:
        return invoke(task, args, payload, export=True)
