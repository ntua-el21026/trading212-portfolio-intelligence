"""PostgreSQL-backed relay for the fixed ``portfolio.refresh`` task."""

from __future__ import annotations

import argparse
import logging
import os
import re
import signal
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from threading import Event
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from celery import Celery  # type: ignore[import-untyped]
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.ingestion import RunStatus
from trading212_observability import (
    MetricsHttpServer,
    OperationalMetrics,
    configure_logging,
    configure_tracing,
)
from trading212_persistence import (
    cleanup_expired_collection_snapshots,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import (
    IngestionLeaseModel,
    IngestionRunModel,
    RefreshDispatcherHeartbeatModel,
    RefreshDispatchOutboxModel,
)
from trading212_persistence.refresh_semantics import (
    INVALID_REFRESH_DISPATCH_ERROR_CODE,
    MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS,
    REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE,
    REFRESH_TASK_NAME,
    REFRESH_TASK_VERSION,
)
from trading212_security.settings import RuntimeEnvironment

_LOGGER = logging.getLogger("trading212_worker.outbox_dispatcher")
_PUBLISH_ERROR_CODE = "broker_publish_failed"
_INVALID_PAYLOAD_ERROR_CODE = INVALID_REFRESH_DISPATCH_ERROR_CODE
_DEAD_DISPATCH_ERROR_CODE = "refresh_dispatch_dead"
_ORPHANED_RUN_ERROR_CODE = "queued_run_without_dispatch"
_TERMINAL_WITHOUT_DELIVERY_ERROR_CODE = "terminal_run_without_dispatch"
_CANCELLED_DISPATCH_ERROR_CODE = "refresh_dispatch_cancelled"
_QUEUE_NAME = "refresh_dispatch"
_DELIVERED_TERMINAL_RUN_STATUSES = (
    RunStatus.SUCCEEDED.value,
    RunStatus.PARTIAL.value,
    RunStatus.FAILED.value,
)
_RETRYABLE_TERMINAL_RUN_ERROR_CODES = frozenset(
    {
        "rate_limit",
        "transient",
        "persistence",
        "interrupted",
    }
)
_ALL_TERMINAL_RUN_STATUSES = (*_DELIVERED_TERMINAL_RUN_STATUSES, RunStatus.CANCELLED.value)
_TASK_METADATA_KEYS = frozenset(
    {
        "dispatch_id",
        "run_id",
        "account_id",
        "request_fingerprint",
        "request_schema_version",
        "task_name",
        "task_version",
    }
)
_OUTBOX_PAYLOAD_KEYS = _TASK_METADATA_KEYS - {"dispatch_id", "task_name", "task_version"}
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_DISPATCHER_ID = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


@dataclass(frozen=True, slots=True)
class OutboxDispatcherSettings:
    database_url: str
    broker_url: str
    app_environment: RuntimeEnvironment = RuntimeEnvironment.LOCAL
    dispatcher_id: str = "dispatcher-local"
    poll_interval_seconds: float = 1.0
    batch_size: int = 20
    claim_timeout_seconds: int = 30
    max_attempts: int = 8
    backoff_base_seconds: int = 1
    backoff_max_seconds: int = 60
    collection_cleanup_batch_size: int = 100
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9464

    def __post_init__(self) -> None:
        if not self.database_url:
            raise ValueError("dispatcher database URL is required")
        if not self.broker_url:
            raise ValueError("dispatcher broker URL is required")
        if (
            self.app_environment in {RuntimeEnvironment.STAGING, RuntimeEnvironment.PRODUCTION}
            and urlsplit(self.broker_url).scheme == "memory"
        ):
            raise ValueError("deployed dispatcher requires a shared Celery broker")
        if _DISPATCHER_ID.fullmatch(self.dispatcher_id) is None:
            raise ValueError("dispatcher identity must be bounded and non-secret")
        if not 0.05 <= self.poll_interval_seconds <= 60:
            raise ValueError("dispatcher poll interval is out of bounds")
        if not 1 <= self.batch_size <= 100:
            raise ValueError("dispatcher batch size is out of bounds")
        if not 1 <= self.claim_timeout_seconds <= 300:
            raise ValueError("dispatcher claim timeout is out of bounds")
        if not 1 <= self.max_attempts <= 100:
            raise ValueError("dispatcher maximum attempts is out of bounds")
        if not 1 <= self.backoff_base_seconds <= self.backoff_max_seconds <= 3_600:
            raise ValueError("dispatcher backoff bounds are invalid")
        if not 1 <= self.collection_cleanup_batch_size <= 1_000:
            raise ValueError("collection cleanup batch size is out of bounds")
        object.__setattr__(self, "metrics_host", _metrics_host(self.metrics_host))
        if type(self.metrics_port) is not int or not 1_024 <= self.metrics_port <= 65_535:
            raise ValueError("dispatcher metrics port is out of bounds")

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> OutboxDispatcherSettings:
        values = environment if environment is not None else os.environ
        try:
            app_environment = RuntimeEnvironment(values.get("T212PI_ENVIRONMENT", "local"))
        except ValueError as exc:
            raise ValueError("dispatcher environment configuration is invalid") from exc
        return cls(
            database_url=values.get("DATABASE_URL", ""),
            broker_url=values.get("CELERY_BROKER_URL", ""),
            app_environment=app_environment,
            dispatcher_id=values.get("T212PI_OUTBOX_DISPATCHER_ID", "dispatcher-local"),
            poll_interval_seconds=_float_setting(values, "T212PI_OUTBOX_POLL_SECONDS", default=1.0),
            batch_size=_int_setting(values, "T212PI_OUTBOX_BATCH_SIZE", default=20),
            claim_timeout_seconds=_int_setting(
                values, "T212PI_OUTBOX_CLAIM_TIMEOUT_SECONDS", default=30
            ),
            max_attempts=_int_setting(values, "T212PI_OUTBOX_MAX_ATTEMPTS", default=8),
            backoff_base_seconds=_int_setting(
                values, "T212PI_OUTBOX_BACKOFF_BASE_SECONDS", default=1
            ),
            backoff_max_seconds=_int_setting(
                values, "T212PI_OUTBOX_BACKOFF_MAX_SECONDS", default=60
            ),
            collection_cleanup_batch_size=_int_setting(
                values,
                "T212PI_COLLECTION_SNAPSHOT_CLEANUP_BATCH_SIZE",
                default=100,
            ),
            metrics_host=values.get("T212PI_OUTBOX_METRICS_HOST", "127.0.0.1"),
            metrics_port=_int_setting(values, "T212PI_OUTBOX_METRICS_PORT", default=9464),
        )


@dataclass(frozen=True, slots=True)
class RefreshDispatchMessage:
    dispatch_id: UUID
    run_id: UUID
    account_id: UUID
    request_fingerprint: str
    request_schema_version: int
    task_name: str = REFRESH_TASK_NAME
    task_version: int = REFRESH_TASK_VERSION

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, object]) -> RefreshDispatchMessage:
        if frozenset(metadata) != _TASK_METADATA_KEYS:
            raise ValueError("refresh task metadata has an invalid shape")
        task_name = metadata.get("task_name")
        task_version = metadata.get("task_version")
        if task_name != REFRESH_TASK_NAME or task_version != REFRESH_TASK_VERSION:
            raise ValueError("refresh task metadata has an unsupported contract")
        return cls(
            dispatch_id=_uuid(metadata.get("dispatch_id"), "dispatch_id"),
            run_id=_uuid(metadata.get("run_id"), "run_id"),
            account_id=_uuid(metadata.get("account_id"), "account_id"),
            request_fingerprint=_fingerprint(metadata.get("request_fingerprint")),
            request_schema_version=_schema_version(metadata.get("request_schema_version")),
        )

    @classmethod
    def from_outbox(cls, row: RefreshDispatchOutboxModel) -> RefreshDispatchMessage:
        payload = row.payload
        if not isinstance(payload, Mapping) or frozenset(payload) != _OUTBOX_PAYLOAD_KEYS:
            raise ValueError("refresh outbox payload has an invalid shape")
        message = cls.from_metadata(
            {
                "dispatch_id": str(row.id),
                "run_id": payload.get("run_id"),
                "account_id": payload.get("account_id"),
                "request_fingerprint": payload.get("request_fingerprint"),
                "request_schema_version": payload.get("request_schema_version"),
                "task_name": row.task_name,
                "task_version": row.task_version,
            }
        )
        if message.run_id != row.ingestion_run_id:
            raise ValueError("refresh outbox payload does not match its run")
        return message

    def kwargs(self) -> dict[str, object]:
        return {
            "dispatch_id": str(self.dispatch_id),
            "run_id": str(self.run_id),
            "account_id": str(self.account_id),
            "request_fingerprint": self.request_fingerprint,
            "request_schema_version": self.request_schema_version,
            "task_name": self.task_name,
            "task_version": self.task_version,
        }

    @property
    def task_id(self) -> str:
        """Return the fixed task identity derived from the durable run identity."""

        return str(self.run_id)


@dataclass(frozen=True, slots=True)
class ClaimedDispatch:
    message: RefreshDispatchMessage
    claim_token: UUID
    claim_owner: str


@dataclass(frozen=True, slots=True)
class DispatchCycleResult:
    claimed: int
    published: int
    failed: int
    dead: int
    recovered: int


@dataclass(frozen=True, slots=True)
class OutboxBacklogSnapshot:
    pending: int
    oldest_pending_age_seconds: float
    queued_runs_without_deliverable_event: int


@dataclass(frozen=True, slots=True)
class TerminalDispatchReconciliation:
    recovered: int
    dead: int


@dataclass(frozen=True, slots=True)
class ConsumerDispatchTransition:
    """Result of a durable consumer-side outbox state transition."""

    run_status: str
    completed_at: datetime | None
    deferred: bool = False
    run_id: UUID | None = None


class PostgresOutboxDispatcher:
    """Lease outbox rows, publish outside the transaction, and retain retry state."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        celery: Celery,
        settings: OutboxDispatcherSettings,
        clock: Callable[[], datetime] | None = None,
        metrics: OperationalMetrics | None = None,
    ) -> None:
        self._sessions = sessions
        self._celery = celery
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(UTC))
        self._metrics = metrics or OperationalMetrics(service="outbox-dispatcher")
        self._started_at = _utc(self._clock())

    def dispatch_once(self) -> DispatchCycleResult:
        started = time.perf_counter()
        expired_snapshots_deleted = self._cleanup_expired_collection_snapshots()
        terminal = self._reconcile_terminal_dispatches()
        claimed, dead, expired_recoveries = self._claim_batch()
        dead += terminal.dead
        recovered = terminal.recovered + expired_recoveries
        if expired_recoveries:
            self._metrics.queue_recoveries.labels(queue=_QUEUE_NAME, reason="expired_claim").inc(
                expired_recoveries
            )
        if terminal.recovered:
            self._metrics.queue_recoveries.labels(
                queue=_QUEUE_NAME, reason="terminal_delivery"
            ).inc(terminal.recovered)
        published = failed = 0
        for item in claimed:
            try:
                self._celery.send_task(
                    REFRESH_TASK_NAME,
                    kwargs=item.message.kwargs(),
                    task_id=item.message.task_id,
                    headers={
                        "x-t212pi-dispatch-id": str(item.message.dispatch_id),
                        "x-t212pi-task-version": str(item.message.task_version),
                    },
                )
            except Exception:
                failed += 1
                self._metrics.queue_delivery_attempts.labels(
                    queue=_QUEUE_NAME, outcome="failure"
                ).inc()
                self._metrics.requests.labels(
                    operation="refresh_outbox_publish", outcome="failure"
                ).inc()
                self._metrics.failures.labels(category=_PUBLISH_ERROR_CODE).inc()
                self._metrics.queue_delivery_failures.labels(queue=_QUEUE_NAME).inc()
                if self._mark_failed(item):
                    dead += 1
            else:
                published += 1
                self._metrics.queue_delivery_attempts.labels(
                    queue=_QUEUE_NAME, outcome="success"
                ).inc()
                self._metrics.requests.labels(
                    operation="refresh_outbox_publish", outcome="success"
                ).inc()
                self._mark_published(item)
        self._metrics.duration.labels(operation="refresh_outbox_cycle").observe(
            time.perf_counter() - started
        )
        result = DispatchCycleResult(
            claimed=len(claimed),
            published=published,
            failed=failed,
            dead=dead,
            recovered=recovered,
        )
        backlog = self._record_cycle_state(result)
        self._metrics.queue_pending_items.labels(queue=_QUEUE_NAME).set(backlog.pending)
        self._metrics.queue_oldest_pending_age_seconds.labels(queue=_QUEUE_NAME).set(
            backlog.oldest_pending_age_seconds
        )
        self._metrics.queue_runs_without_deliverable_event.labels(queue=_QUEUE_NAME).set(
            backlog.queued_runs_without_deliverable_event
        )
        self._metrics.readiness.set(
            0
            if result.failed or result.dead or backlog.queued_runs_without_deliverable_event
            else 1
        )
        if any((result.claimed, result.dead, result.recovered)):
            _LOGGER.info(
                "refresh_outbox_cycle claimed=%d published=%d failed=%d dead=%d recovered=%d",
                result.claimed,
                result.published,
                result.failed,
                result.dead,
                result.recovered,
            )
        if expired_snapshots_deleted:
            _LOGGER.info(
                "collection_snapshot_cleanup deleted=%d",
                expired_snapshots_deleted,
            )
        return result

    def _cleanup_expired_collection_snapshots(self) -> int:
        with self._sessions.begin() as session:
            return cleanup_expired_collection_snapshots(
                session,
                batch_size=self._settings.collection_cleanup_batch_size,
            )

    def _reconcile_terminal_dispatches(self) -> TerminalDispatchReconciliation:
        """Finalize stale terminal deliveries only when consumer observation proves delivery."""

        now = _utc(self._clock())
        recovered = dead = 0
        with self._sessions.begin() as session:
            rows = session.execute(
                select(RefreshDispatchOutboxModel, IngestionRunModel)
                .join(
                    IngestionRunModel,
                    IngestionRunModel.id == RefreshDispatchOutboxModel.ingestion_run_id,
                )
                .where(
                    IngestionRunModel.status.in_(_ALL_TERMINAL_RUN_STATUSES),
                    or_(
                        RefreshDispatchOutboxModel.status == "pending",
                        and_(
                            RefreshDispatchOutboxModel.status == "publishing",
                            RefreshDispatchOutboxModel.claim_expires_at <= now,
                        ),
                    ),
                )
                .order_by(
                    RefreshDispatchOutboxModel.available_at,
                    RefreshDispatchOutboxModel.created_at,
                    RefreshDispatchOutboxModel.id,
                )
                .limit(self._settings.batch_size)
                .with_for_update(of=RefreshDispatchOutboxModel, skip_locked=True)
            ).all()
            for row, run in rows:
                if (
                    row.status == "pending"
                    and run.status in {RunStatus.FAILED.value, RunStatus.PARTIAL.value}
                    and run.error_code in _RETRYABLE_TERMINAL_RUN_ERROR_CODES
                ):
                    if row.consumer_attempt_count < MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS:
                        continue
                    row.status = "dead"
                    row.published_at = None
                    row.last_error_code = REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE
                    run.status = RunStatus.FAILED.value
                    run.error_code = REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE
                    _clear_claim(row)
                    dead += 1
                    continue
                consumer_observed_delivery = (
                    row.attempt_count > 0 and run.status in _DELIVERED_TERMINAL_RUN_STATUSES
                )
                if consumer_observed_delivery:
                    row.status = "published"
                    if row.published_at is None:
                        row.published_at = now
                    row.available_at = now
                    row.consecutive_failure_count = 0
                    row.last_error_code = None
                    _clear_claim(row)
                    recovered += 1
                    continue
                row.status = "dead"
                row.published_at = None
                row.last_error_code = (
                    _CANCELLED_DISPATCH_ERROR_CODE
                    if run.status == RunStatus.CANCELLED.value
                    else _TERMINAL_WITHOUT_DELIVERY_ERROR_CODE
                )
                _clear_claim(row)
                dead += 1
        return TerminalDispatchReconciliation(recovered=recovered, dead=dead)

    def _claim_batch(self) -> tuple[list[ClaimedDispatch], int, int]:
        now = _utc(self._clock())
        claimed: list[ClaimedDispatch] = []
        dead = 0
        recovered = 0
        with self._sessions.begin() as session:
            eligible_state = or_(
                and_(
                    RefreshDispatchOutboxModel.status == "pending",
                    RefreshDispatchOutboxModel.available_at <= now,
                ),
                and_(
                    RefreshDispatchOutboxModel.status == "publishing",
                    RefreshDispatchOutboxModel.claim_expires_at <= now,
                ),
            )
            rows = session.execute(
                select(RefreshDispatchOutboxModel, IngestionRunModel)
                .join(
                    IngestionRunModel,
                    IngestionRunModel.id == RefreshDispatchOutboxModel.ingestion_run_id,
                )
                .outerjoin(
                    IngestionLeaseModel,
                    and_(
                        IngestionLeaseModel.broker_account_id
                        == IngestionRunModel.broker_account_id,
                        IngestionLeaseModel.lease_type == "refresh",
                    ),
                )
                .where(
                    eligible_state,
                    or_(
                        IngestionRunModel.status.in_(
                            (RunStatus.QUEUED.value, RunStatus.RUNNING.value)
                        ),
                        and_(
                            RefreshDispatchOutboxModel.status == "pending",
                            IngestionRunModel.status.in_(
                                (RunStatus.FAILED.value, RunStatus.PARTIAL.value)
                            ),
                            IngestionRunModel.error_code.in_(_RETRYABLE_TERMINAL_RUN_ERROR_CODES),
                            RefreshDispatchOutboxModel.consumer_attempt_count
                            < MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS,
                        ),
                    ),
                    or_(
                        IngestionLeaseModel.id.is_(None),
                        IngestionLeaseModel.expires_at <= now,
                    ),
                )
                .order_by(
                    RefreshDispatchOutboxModel.available_at,
                    RefreshDispatchOutboxModel.created_at,
                    RefreshDispatchOutboxModel.id,
                )
                .limit(self._settings.batch_size)
                .with_for_update(of=RefreshDispatchOutboxModel, skip_locked=True)
            ).all()
            for row, run in rows:
                if row.status == "publishing":
                    recovered += 1
                    # Publication may already have been accepted before the
                    # prior dispatcher died. Begin a fresh consecutive-failure
                    # budget so an ambiguous accepted delivery cannot be
                    # falsely dead-lettered by historical broker failures.
                    row.consecutive_failure_count = 0
                    row.published_at = None
                if row.consecutive_failure_count >= self._settings.max_attempts:
                    _mark_dead(
                        session,
                        row,
                        error_code=row.last_error_code or _PUBLISH_ERROR_CODE,
                        now=now,
                    )
                    dead += 1
                    continue
                try:
                    message = RefreshDispatchMessage.from_outbox(row)
                except ValueError:
                    _mark_dead(
                        session,
                        row,
                        error_code=_INVALID_PAYLOAD_ERROR_CODE,
                        now=now,
                    )
                    dead += 1
                    continue
                if (
                    message.account_id != run.broker_account_id
                    or message.request_fingerprint != run.request_fingerprint
                    or message.request_schema_version != run.request_schema_version
                ):
                    _mark_dead(
                        session,
                        row,
                        error_code=_INVALID_PAYLOAD_ERROR_CODE,
                        now=now,
                    )
                    dead += 1
                    continue
                token = uuid4()
                row.status = "publishing"
                row.attempt_count += 1
                row.claim_token = token
                row.claim_owner = self._settings.dispatcher_id
                row.claimed_at = now
                row.claim_expires_at = now + timedelta(seconds=self._settings.claim_timeout_seconds)
                row.last_error_code = None
                claimed.append(
                    ClaimedDispatch(
                        message=message,
                        claim_token=token,
                        claim_owner=self._settings.dispatcher_id,
                    )
                )
        return claimed, dead, recovered

    def _mark_published(self, claimed: ClaimedDispatch) -> None:
        now = _utc(self._clock())
        with self._sessions.begin() as session:
            row = _claimed_row(session, claimed)
            if row is None:
                return
            row.status = "published"
            if row.published_at is None:
                row.published_at = now
            row.available_at = now
            row.consecutive_failure_count = 0
            row.last_error_code = None
            _clear_claim(row)

    def _mark_failed(self, claimed: ClaimedDispatch) -> bool:
        now = _utc(self._clock())
        with self._sessions.begin() as session:
            row = _claimed_row(session, claimed)
            if row is None:
                return False
            live_matching_lease = session.scalar(
                select(IngestionLeaseModel.id).where(
                    IngestionLeaseModel.broker_account_id == claimed.message.account_id,
                    IngestionLeaseModel.lease_type == "refresh",
                    IngestionLeaseModel.run_id == claimed.message.run_id,
                    IngestionLeaseModel.expires_at > now,
                )
            )
            if row.published_at is not None or live_matching_lease is not None:
                # ``send_task`` failures are ambiguous. A consumer-observed
                # marker or its live matching lease proves that this attempt
                # reached the worker, so it must not be falsely dead-lettered.
                row.status = "published"
                if row.published_at is None:
                    row.published_at = now
                row.available_at = now
                row.consecutive_failure_count = 0
                row.last_error_code = None
                _clear_claim(row)
                return False
            row.consecutive_failure_count = min(
                row.consecutive_failure_count + 1,
                self._settings.max_attempts,
            )
            if row.consecutive_failure_count >= self._settings.max_attempts:
                _mark_dead(
                    session,
                    row,
                    error_code=_PUBLISH_ERROR_CODE,
                    now=now,
                )
                is_dead = True
            else:
                row.status = "pending"
                row.published_at = None
                row.available_at = now + timedelta(
                    seconds=self._backoff(row.consecutive_failure_count)
                )
                is_dead = False
                row.last_error_code = _PUBLISH_ERROR_CODE
                _clear_claim(row)
            return is_dead

    def _record_cycle_state(self, result: DispatchCycleResult) -> OutboxBacklogSnapshot:
        now = _utc(self._clock())
        with self._sessions.begin() as session:
            orphaned_runs = session.scalars(
                select(IngestionRunModel)
                .outerjoin(
                    RefreshDispatchOutboxModel,
                    RefreshDispatchOutboxModel.ingestion_run_id == IngestionRunModel.id,
                )
                .where(
                    IngestionRunModel.status == RunStatus.QUEUED.value,
                    or_(
                        RefreshDispatchOutboxModel.id.is_(None),
                        RefreshDispatchOutboxModel.status == "dead",
                    ),
                )
                .order_by(IngestionRunModel.started_at, IngestionRunModel.id)
                .limit(self._settings.batch_size)
                .with_for_update(of=IngestionRunModel, skip_locked=True)
            ).all()
            for run in orphaned_runs:
                run.status = RunStatus.FAILED.value
                run.completed_at = now
                run.heartbeat_at = now
                run.error_code = _ORPHANED_RUN_ERROR_CODE
            orphaned = len(orphaned_runs)
            pending = int(
                session.scalar(
                    select(func.count())
                    .select_from(RefreshDispatchOutboxModel)
                    .join(
                        IngestionRunModel,
                        IngestionRunModel.id == RefreshDispatchOutboxModel.ingestion_run_id,
                    )
                    .where(
                        RefreshDispatchOutboxModel.status == "pending",
                        or_(
                            IngestionRunModel.status.in_(
                                (RunStatus.QUEUED.value, RunStatus.RUNNING.value)
                            ),
                            and_(
                                IngestionRunModel.status.in_(
                                    (RunStatus.FAILED.value, RunStatus.PARTIAL.value)
                                ),
                                IngestionRunModel.error_code.in_(
                                    _RETRYABLE_TERMINAL_RUN_ERROR_CODES
                                ),
                                RefreshDispatchOutboxModel.consumer_attempt_count
                                < MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS,
                            ),
                        ),
                    )
                )
                or 0
            )
            oldest = session.scalar(
                select(func.min(RefreshDispatchOutboxModel.created_at))
                .join(
                    IngestionRunModel,
                    IngestionRunModel.id == RefreshDispatchOutboxModel.ingestion_run_id,
                )
                .where(
                    RefreshDispatchOutboxModel.status == "pending",
                    or_(
                        IngestionRunModel.status.in_(
                            (RunStatus.QUEUED.value, RunStatus.RUNNING.value)
                        ),
                        and_(
                            IngestionRunModel.status.in_(
                                (RunStatus.FAILED.value, RunStatus.PARTIAL.value)
                            ),
                            IngestionRunModel.error_code.in_(_RETRYABLE_TERMINAL_RUN_ERROR_CODES),
                            RefreshDispatchOutboxModel.consumer_attempt_count
                            < MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS,
                        ),
                    ),
                )
            )
            oldest_age = (
                max((now - _utc(oldest)).total_seconds(), 0.0) if oldest is not None else 0.0
            )
            degraded = bool(result.failed or result.dead or orphaned)
            if result.failed:
                error_code = _PUBLISH_ERROR_CODE
            elif result.dead:
                error_code = _DEAD_DISPATCH_ERROR_CODE
            elif orphaned:
                error_code = _ORPHANED_RUN_ERROR_CODE
            else:
                error_code = None
            statement = insert(RefreshDispatcherHeartbeatModel).values(
                id=uuid4(),
                dispatcher_id=self._settings.dispatcher_id,
                started_at=self._started_at,
                heartbeat_at=now,
                last_successful_cycle_at=None if degraded else now,
                state="degraded" if degraded else "healthy",
                last_error_code=error_code,
            )
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[RefreshDispatcherHeartbeatModel.dispatcher_id],
                    set_={
                        "heartbeat_at": now,
                        "last_successful_cycle_at": (
                            RefreshDispatcherHeartbeatModel.last_successful_cycle_at
                            if degraded
                            else now
                        ),
                        "state": "degraded" if degraded else "healthy",
                        "last_error_code": error_code,
                    },
                )
            )
        return OutboxBacklogSnapshot(
            pending=pending,
            oldest_pending_age_seconds=oldest_age,
            queued_runs_without_deliverable_event=orphaned,
        )

    def _backoff(self, failure_count: int) -> int:
        exponent: int = max(failure_count - 1, 0)
        return min(
            self._settings.backoff_base_seconds * (1 << exponent),
            self._settings.backoff_max_seconds,
        )


def recover_invalid_refresh_dispatch(
    sessions: sessionmaker[Session],
    *,
    message: RefreshDispatchMessage,
    restore_canonical: bool,
    now: datetime | None = None,
) -> ConsumerDispatchTransition:
    """Repair a bound corrupt delivery or terminalize corrupt durable state before ACK."""

    observed_at = _utc(now or datetime.now(UTC))
    with sessions.begin() as session:
        run, row = _locked_consumer_dispatch_by_either_identity(session, message)
        if row.status == "dead":
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
                run_id=run.id,
            )

        canonical_is_valid = False
        try:
            canonical = RefreshDispatchMessage.from_outbox(row)
        except ValueError:
            canonical = None
        if canonical is not None:
            canonical_is_valid = (
                canonical.run_id == run.id
                and canonical.account_id == run.broker_account_id
                and canonical.request_fingerprint == run.request_fingerprint
                and canonical.request_schema_version == run.request_schema_version
            )

        if not restore_canonical or not canonical_is_valid:
            _mark_dead(
                session,
                row,
                error_code=_INVALID_PAYLOAD_ERROR_CODE,
                now=observed_at,
            )
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
                run_id=run.id,
            )

        retryable_terminal = (
            run.status in {RunStatus.FAILED.value, RunStatus.PARTIAL.value}
            and run.error_code in _RETRYABLE_TERMINAL_RUN_ERROR_CODES
        )
        if retryable_terminal:
            if row.consumer_attempt_count >= MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS:
                row.status = "dead"
                row.published_at = None
                row.last_error_code = REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE
                _clear_claim(row)
                run.status = RunStatus.FAILED.value
                run.completed_at = run.completed_at or observed_at
                run.heartbeat_at = observed_at
                run.error_code = REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE
                return ConsumerDispatchTransition(
                    run_status=run.status,
                    completed_at=run.completed_at,
                    run_id=run.id,
                )

            # The canonical event already owns a bounded economic retry. A
            # corrupt broker copy cannot convert that retry path to a terminal
            # publication marker or bypass its persisted backoff.
            row.status = "pending"
            row.available_at = max(_utc(row.available_at), observed_at)
            row.published_at = None
            row.consecutive_failure_count = 0
            row.last_error_code = None
            _clear_claim(row)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
                deferred=True,
                run_id=run.id,
            )

        if run.status in _DELIVERED_TERMINAL_RUN_STATUSES:
            _mark_consumer_delivered(row, now=observed_at)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
                run_id=run.id,
            )
        if run.status == RunStatus.CANCELLED.value:
            row.status = "dead"
            row.published_at = None
            row.last_error_code = _CANCELLED_DISPATCH_ERROR_CODE
            _clear_claim(row)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )

        # The broker accepted a corrupt copy, so its published marker cannot
        # prove delivery of the canonical command. Re-enter bounded dispatch
        # using only the persisted payload; never echo delivered metadata.
        row.status = "pending"
        row.available_at = observed_at
        row.published_at = None
        row.consecutive_failure_count = 0
        row.last_error_code = None
        _clear_claim(row)
        return ConsumerDispatchTransition(
            run_status=run.status,
            completed_at=run.completed_at,
            deferred=True,
            run_id=run.id,
        )


def defer_retryable_refresh_dispatch(
    sessions: sessionmaker[Session],
    *,
    message: RefreshDispatchMessage,
    now: datetime | None = None,
) -> ConsumerDispatchTransition:
    """Schedule one bounded economic retry, or seal an exhausted durable run."""

    observed_at = _utc(now or datetime.now(UTC))
    with sessions.begin() as session:
        run, row = _locked_consumer_dispatch(session, message)
        if row.status == "dead":
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )
        if run.status == RunStatus.SUCCEEDED.value:
            _mark_consumer_delivered(row, now=observed_at)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )
        if run.status == RunStatus.CANCELLED.value:
            row.status = "dead"
            row.published_at = None
            row.last_error_code = _CANCELLED_DISPATCH_ERROR_CODE
            _clear_claim(row)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )

        lease_expiry = session.scalar(
            select(IngestionLeaseModel.expires_at).where(
                IngestionLeaseModel.broker_account_id == run.broker_account_id,
                IngestionLeaseModel.lease_type == "refresh",
                IngestionLeaseModel.run_id == run.id,
                IngestionLeaseModel.expires_at > observed_at,
            )
        )
        if lease_expiry is not None:
            # Another accepted copy already owns the next durable execution.
            # ACK this copy only after retaining a pending recovery path.
            row.status = "pending"
            row.available_at = lease_expiry
            row.published_at = None
            row.consecutive_failure_count = 0
            row.last_error_code = None
            _clear_claim(row)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
                deferred=True,
            )

        if row.consumer_attempt_count >= MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS:
            row.status = "dead"
            row.published_at = None
            row.last_error_code = REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE
            _clear_claim(row)
            if run.status in {
                RunStatus.QUEUED.value,
                RunStatus.RUNNING.value,
                RunStatus.FAILED.value,
                RunStatus.PARTIAL.value,
            }:
                run.status = RunStatus.FAILED.value
                run.completed_at = run.completed_at or observed_at
                run.heartbeat_at = observed_at
                run.error_code = REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )

        row.status = "pending"
        row.available_at = observed_at + timedelta(
            seconds=min(1 << max(row.consumer_attempt_count - 1, 0), 30)
        )
        row.published_at = None
        row.consecutive_failure_count = 0
        row.last_error_code = None
        _clear_claim(row)
        return ConsumerDispatchTransition(
            run_status=run.status,
            completed_at=run.completed_at,
            deferred=True,
        )


def defer_refresh_dispatch(
    sessions: sessionmaker[Session],
    *,
    message: RefreshDispatchMessage,
    available_at: datetime,
) -> ConsumerDispatchTransition:
    """Durably defer a valid delivery that encountered a live account lease."""

    timestamp = _utc(available_at)
    observed_at = datetime.now(UTC)
    with sessions.begin() as session:
        run, row = _locked_consumer_dispatch(session, message)
        if row.status == "dead":
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )
        if (
            run.status in {RunStatus.FAILED.value, RunStatus.PARTIAL.value}
            and run.error_code in _RETRYABLE_TERMINAL_RUN_ERROR_CODES
            and row.consumer_attempt_count >= MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS
        ):
            row.status = "dead"
            row.published_at = None
            row.last_error_code = REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE
            run.error_code = REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE
            _clear_claim(row)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )
        if run.status in _DELIVERED_TERMINAL_RUN_STATUSES:
            _mark_consumer_delivered(row, now=observed_at)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )
        if run.status == RunStatus.CANCELLED.value:
            row.status = "dead"
            row.published_at = None
            row.last_error_code = _CANCELLED_DISPATCH_ERROR_CODE
            _clear_claim(row)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )
        row.status = "pending"
        row.available_at = timestamp
        row.published_at = None
        row.consecutive_failure_count = 0
        row.last_error_code = None
        _clear_claim(row)
        return ConsumerDispatchTransition(
            run_status=run.status,
            completed_at=run.completed_at,
            deferred=True,
        )


def confirm_refresh_dispatch(
    sessions: sessionmaker[Session],
    *,
    message: RefreshDispatchMessage,
    expected_status: str,
    now: datetime | None = None,
) -> ConsumerDispatchTransition:
    """Confirm that a consumer reached a durable terminal run before ACK."""

    observed_at = _utc(now or datetime.now(UTC))
    with sessions.begin() as session:
        run, row = _locked_consumer_dispatch(session, message)
        if run.status != expected_status or run.status not in _DELIVERED_TERMINAL_RUN_STATUSES:
            raise ValueError("refresh consumer result does not match the durable terminal run")
        _mark_consumer_delivered(row, now=observed_at)
        return ConsumerDispatchTransition(
            run_status=run.status,
            completed_at=run.completed_at,
        )


def terminalize_refresh_dispatch(
    sessions: sessionmaker[Session],
    *,
    message: RefreshDispatchMessage,
    error_code: str,
    now: datetime | None = None,
) -> ConsumerDispatchTransition:
    """Persist a sanitized terminal failure, or defer behind live work, before ACK."""

    if not error_code or len(error_code) > 100 or re.fullmatch(r"[a-z0-9_]+", error_code) is None:
        raise ValueError("refresh consumer error code is invalid")
    observed_at = _utc(now or datetime.now(UTC))
    with sessions.begin() as session:
        run, row = _locked_consumer_dispatch(session, message)
        if run.status == RunStatus.SUCCEEDED.value:
            _mark_consumer_delivered(row, now=observed_at)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )
        if run.status in {RunStatus.FAILED.value, RunStatus.PARTIAL.value}:
            # Retry exhaustion is a durable consumer lifecycle boundary. Seal
            # retryable terminal runs with a non-retryable sanitized code so a
            # stale original broker copy cannot reopen a fresh retry chain.
            row.status = "dead"
            row.published_at = None
            row.last_error_code = error_code
            _clear_claim(row)
            run.error_code = error_code
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )
        if run.status == RunStatus.CANCELLED.value:
            row.status = "dead"
            row.published_at = None
            row.last_error_code = _CANCELLED_DISPATCH_ERROR_CODE
            _clear_claim(row)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
            )
        lease_expiry = session.scalar(
            select(IngestionLeaseModel.expires_at).where(
                IngestionLeaseModel.broker_account_id == run.broker_account_id,
                IngestionLeaseModel.lease_type == "refresh",
                IngestionLeaseModel.expires_at > observed_at,
            )
        )
        if lease_expiry is not None:
            row.status = "pending"
            row.available_at = lease_expiry
            row.published_at = None
            row.consecutive_failure_count = 0
            row.last_error_code = None
            _clear_claim(row)
            return ConsumerDispatchTransition(
                run_status=run.status,
                completed_at=run.completed_at,
                deferred=True,
            )
        row.status = "dead"
        row.published_at = None
        row.last_error_code = error_code
        _clear_claim(row)
        run.status = RunStatus.FAILED.value
        run.completed_at = observed_at
        run.heartbeat_at = observed_at
        run.error_code = error_code
        return ConsumerDispatchTransition(
            run_status=run.status,
            completed_at=run.completed_at,
        )


def dispatcher_dependencies_ready(*, engine: Any, celery: Celery, broker_url: str) -> bool:
    if urlsplit(broker_url).scheme == "memory":
        return False
    try:
        with engine.connect() as connection:
            if connection.scalar(text("SELECT 1")) != 1:
                return False
        broker = celery.connection_for_write()
        try:
            broker.ensure_connection(max_retries=0, timeout=3)
        finally:
            broker.release()
    except Exception:
        return False
    return True


def _claimed_row(session: Session, claimed: ClaimedDispatch) -> RefreshDispatchOutboxModel | None:
    return session.scalar(
        select(RefreshDispatchOutboxModel)
        .where(
            RefreshDispatchOutboxModel.id == claimed.message.dispatch_id,
            RefreshDispatchOutboxModel.claim_token == claimed.claim_token,
            RefreshDispatchOutboxModel.claim_owner == claimed.claim_owner,
            RefreshDispatchOutboxModel.status == "publishing",
        )
        .with_for_update()
    )


def _locked_consumer_dispatch(
    session: Session,
    message: RefreshDispatchMessage,
) -> tuple[IngestionRunModel, RefreshDispatchOutboxModel]:
    run = session.scalar(
        select(IngestionRunModel).where(IngestionRunModel.id == message.run_id).with_for_update()
    )
    row = session.scalar(
        select(RefreshDispatchOutboxModel)
        .where(
            RefreshDispatchOutboxModel.id == message.dispatch_id,
            RefreshDispatchOutboxModel.ingestion_run_id == message.run_id,
        )
        .with_for_update()
    )
    if run is None or row is None:
        raise ValueError("durable refresh dispatch does not exist")
    if RefreshDispatchMessage.from_outbox(row) != message:
        raise ValueError("refresh task metadata does not match durable dispatch")
    if (
        run.broker_account_id != message.account_id
        or run.request_fingerprint != message.request_fingerprint
        or run.request_schema_version != message.request_schema_version
    ):
        raise ValueError("refresh task semantics do not match the durable run")
    return run, row


def _locked_consumer_dispatch_by_either_identity(
    session: Session,
    message: RefreshDispatchMessage,
) -> tuple[IngestionRunModel, RefreshDispatchOutboxModel]:
    """Resolve one canonical pair without trusting either delivered identifier alone."""

    by_dispatch = session.execute(
        select(
            RefreshDispatchOutboxModel.id,
            RefreshDispatchOutboxModel.ingestion_run_id,
        ).where(RefreshDispatchOutboxModel.id == message.dispatch_id)
    ).one_or_none()
    by_run = session.execute(
        select(
            RefreshDispatchOutboxModel.id,
            RefreshDispatchOutboxModel.ingestion_run_id,
        ).where(RefreshDispatchOutboxModel.ingestion_run_id == message.run_id)
    ).one_or_none()
    if by_dispatch is not None and by_run is not None and tuple(by_dispatch) != tuple(by_run):
        raise ValueError("refresh delivery identifiers bind different durable commands")
    binding = by_dispatch or by_run
    if binding is None:
        raise ValueError("durable refresh dispatch does not exist")
    dispatch_id, run_id = binding
    run = session.scalar(
        select(IngestionRunModel).where(IngestionRunModel.id == run_id).with_for_update()
    )
    row = session.scalar(
        select(RefreshDispatchOutboxModel)
        .where(
            RefreshDispatchOutboxModel.id == dispatch_id,
            RefreshDispatchOutboxModel.ingestion_run_id == run_id,
        )
        .with_for_update()
    )
    if run is None or row is None:
        raise ValueError("durable refresh dispatch does not exist")
    return run, row


def _mark_consumer_delivered(row: RefreshDispatchOutboxModel, *, now: datetime) -> None:
    row.status = "published"
    if row.published_at is None:
        row.published_at = now
    row.available_at = now
    row.consecutive_failure_count = 0
    row.last_error_code = None
    _clear_claim(row)


def _mark_dead(
    session: Session,
    row: RefreshDispatchOutboxModel,
    *,
    error_code: str,
    now: datetime,
) -> None:
    row.status = "dead"
    row.published_at = None
    row.last_error_code = error_code
    _clear_claim(row)
    run = session.get(IngestionRunModel, row.ingestion_run_id)
    if run is None or run.status not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
        return
    run.status = RunStatus.FAILED.value
    run.completed_at = now
    run.heartbeat_at = now
    run.error_code = error_code


def _clear_claim(row: RefreshDispatchOutboxModel) -> None:
    row.claim_token = None
    row.claim_owner = None
    row.claimed_at = None
    row.claim_expires_at = None


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, (str, UUID)):
        raise ValueError(f"{name} must be a UUID")
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def _fingerprint(value: object) -> str:
    if not isinstance(value, str) or _FINGERPRINT.fullmatch(value) is None:
        raise ValueError("request_fingerprint must be a lowercase SHA-256 digest")
    return value


def _schema_version(value: object) -> int:
    if type(value) is not int or value != 1:
        raise ValueError("request_schema_version is unsupported")
    return value


def _metrics_host(value: str) -> str:
    if not value or len(value) > 45:
        raise ValueError("dispatcher metrics host must be a bounded IP address")
    try:
        return str(ip_address(value))
    except ValueError as exc:
        raise ValueError("dispatcher metrics host must be a bounded IP address") from exc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _int_setting(values: Mapping[str, str], name: str, *, default: int) -> int:
    raw = values.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _float_setting(values: Mapping[str, str], name: str, *, default: float) -> float:
    raw = values.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Relay durable refresh outbox events")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    canary = os.environ.get("PHASE1_SECRET_CANARY")
    configure_logging(
        service="trading212-outbox-dispatcher",
        secret_canaries=(canary,) if canary else (),
    )
    configure_tracing(service="trading212-outbox-dispatcher")
    try:
        settings = OutboxDispatcherSettings.from_environment()
    except ValueError:
        _LOGGER.error("refresh_outbox_configuration_invalid")
        return 2
    engine = create_database_engine(settings.database_url)
    celery = Celery("trading212_outbox_dispatcher", broker=settings.broker_url)
    try:
        if args.healthcheck:
            return (
                0
                if dispatcher_dependencies_ready(
                    engine=engine,
                    celery=celery,
                    broker_url=settings.broker_url,
                )
                else 1
            )
        metrics = OperationalMetrics(service="outbox-dispatcher")
        dispatcher = PostgresOutboxDispatcher(
            sessions=create_session_factory(engine),
            celery=celery,
            settings=settings,
            metrics=metrics,
        )
        if args.once:
            dispatcher.dispatch_once()
            return 0
        stopped = Event()

        def request_stop(_signum: int, _frame: object) -> None:
            stopped.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        try:
            metrics_server = MetricsHttpServer.start(
                metrics=metrics,
                host=settings.metrics_host,
                port=settings.metrics_port,
            )
        except OSError:
            _LOGGER.error("refresh_outbox_metrics_bind_failed")
            return 2
        with metrics_server:
            while not stopped.is_set():
                try:
                    dispatcher.dispatch_once()
                except Exception:
                    _LOGGER.error("refresh_outbox_cycle_failed")
                stopped.wait(settings.poll_interval_seconds)
        return 0
    finally:
        celery.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
