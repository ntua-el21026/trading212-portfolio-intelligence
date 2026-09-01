"""Deterministic, restartable, provider-independent ingestion orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, TypeVar

_Awaited = TypeVar("_Awaited")


class IngestionCapability(StrEnum):
    INSTRUMENTS = "metadata_instruments"
    EXCHANGES = "metadata_exchanges"
    ACCOUNT = "account_summary"
    POSITIONS = "portfolio_positions"
    PENDING_ORDERS = "pending_orders"
    HISTORICAL_ORDERS = "historical_orders"
    TRANSACTIONS = "historical_transactions"
    DIVIDENDS = "historical_dividends"
    EXPORT_METADATA = "historical_exports"


class RefreshScope(StrEnum):
    ALL = "all"
    CURRENT = "current"
    HISTORY = "history"


CURRENT_REFRESH_ORDER = (
    IngestionCapability.INSTRUMENTS,
    IngestionCapability.EXCHANGES,
    IngestionCapability.ACCOUNT,
    IngestionCapability.POSITIONS,
    IngestionCapability.PENDING_ORDERS,
)

HISTORY_REFRESH_ORDER = (
    IngestionCapability.HISTORICAL_ORDERS,
    IngestionCapability.TRANSACTIONS,
    IngestionCapability.DIVIDENDS,
    IngestionCapability.EXPORT_METADATA,
)

FULL_REFRESH_ORDER = CURRENT_REFRESH_ORDER + HISTORY_REFRESH_ORDER
DEFAULT_INCREMENTAL_OVERLAP = timedelta(days=7)
_REFRESH_CAPABILITIES = {
    RefreshScope.ALL: FULL_REFRESH_ORDER,
    RefreshScope.CURRENT: CURRENT_REFRESH_ORDER,
    RefreshScope.HISTORY: HISTORY_REFRESH_ORDER,
}


def capabilities_for_scope(scope: RefreshScope) -> tuple[IngestionCapability, ...]:
    """Return the frozen provider-independent capability order for a public scope."""

    if not isinstance(scope, RefreshScope):
        raise ValueError("only typed refresh scopes are accepted")
    return _REFRESH_CAPABILITIES[scope]


def validate_refresh_capabilities(
    capabilities: Sequence[IngestionCapability],
) -> tuple[IngestionCapability, ...]:
    """Close internal refresh requests to the three supported high-level scopes."""

    selected = tuple(capabilities)
    if any(not isinstance(capability, IngestionCapability) for capability in selected):
        raise ValueError("only typed ingestion capabilities are accepted")
    if selected not in _REFRESH_CAPABILITIES.values():
        raise ValueError("capabilities must match a supported refresh scope")
    return selected


class RunMode(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FailureCategory(StrEnum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    TRANSIENT = "transient"
    CONTRACT = "contract"
    CONFIGURATION = "configuration"
    PAGINATION = "pagination"
    PERSISTENCE = "persistence"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class IngestionFailure(RuntimeError):
    def __init__(self, category: FailureCategory, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


def _require_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Checkpoint:
    cursor: str | None = None
    source_timestamp: datetime | None = None
    provider_id: str | None = None
    page_fingerprint: str | None = None
    overlap_started_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("source_timestamp", "overlap_started_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _require_utc(value, name))
        for name in ("cursor", "provider_id", "page_fingerprint"):
            value = getattr(self, name)
            if value is not None and (not value or len(value) > 1_024):
                raise ValueError(f"{name} must be non-empty and bounded")


@dataclass(frozen=True, slots=True)
class SourceRecord:
    provider_record_id: str | None
    source_timestamp: datetime
    observed_at: datetime
    payload: Mapping[str, object]
    schema_version: str
    payload_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_timestamp", _require_utc(self.source_timestamp, "source_timestamp")
        )
        object.__setattr__(self, "observed_at", _require_utc(self.observed_at, "observed_at"))
        if self.provider_record_id is not None and (
            not self.provider_record_id or len(self.provider_record_id) > 512
        ):
            raise ValueError("provider_record_id must be non-empty and bounded")
        if not self.schema_version or len(self.schema_version) > 128:
            raise ValueError("schema_version must be non-empty and bounded")
        _reject_sensitive_keys(self.payload)
        frozen_payload = MappingProxyType(dict(self.payload))
        object.__setattr__(self, "payload", frozen_payload)
        object.__setattr__(self, "payload_sha256", _fingerprint(self.payload))

    @property
    def idempotency_key(self) -> str:
        return self.provider_record_id or self.payload_sha256


@dataclass(frozen=True, slots=True)
class RateObservation:
    limit: int
    period_seconds: int
    remaining: int
    reset_at: datetime
    used: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "reset_at", _require_utc(self.reset_at, "reset_at"))
        if any(value < 0 for value in (self.limit, self.period_seconds, self.remaining, self.used)):
            raise ValueError("rate observation values must be non-negative")


@dataclass(frozen=True, slots=True)
class SourcePage:
    records: tuple[SourceRecord, ...]
    next_checkpoint: Checkpoint | None
    complete: bool
    rate: RateObservation | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.complete != (self.next_checkpoint is None):
            raise ValueError("complete and next_checkpoint must agree")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "records": [record.payload_sha256 for record in self.records],
                "next": _checkpoint_json(self.next_checkpoint),
                "complete": self.complete,
            }
        )


@dataclass(frozen=True, slots=True)
class PageCommitResult:
    inserted: int
    updated: int
    unchanged: int


@dataclass(frozen=True, slots=True)
class RunLease:
    """Opaque fencing authority held by exactly one ingestion consumer."""

    token: str
    duration: timedelta

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.token)
        except (ValueError, AttributeError) as exc:
            raise ValueError("run lease token must be a UUID") from exc
        if self.duration <= timedelta(0):
            raise ValueError("run lease duration must be positive")


@dataclass(frozen=True, slots=True)
class StepResult:
    capability: IngestionCapability
    status: RunStatus
    pages: int
    records_seen: int
    inserted: int
    updated: int
    unchanged: int
    warnings: tuple[str, ...] = ()
    failure_category: FailureCategory | None = None
    failure_message: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionRun:
    id: str
    owner_id: str
    account_id: str
    mode: RunMode
    idempotency_key: str
    correlation_id: str
    status: RunStatus
    scheduled_at: datetime
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    completed_at: datetime | None = None
    steps: tuple[StepResult, ...] = ()


class BrokerAccountDataProvider(Protocol):
    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage: ...


class IngestionStore(Protocol):
    async def begin_run(
        self,
        *,
        owner_id: str,
        account_id: str,
        mode: RunMode,
        capabilities: tuple[IngestionCapability, ...],
        idempotency_key: str,
        correlation_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> tuple[IngestionRun, RunLease | None]: ...

    async def get_checkpoint(
        self,
        *,
        account_id: str,
        capability: IngestionCapability,
        mode: RunMode,
        overlap_window: timedelta,
    ) -> Checkpoint | None: ...

    async def commit_page(
        self,
        *,
        run_id: str,
        account_id: str,
        capability: IngestionCapability,
        page: SourcePage,
        lease_token: str,
        now: datetime,
    ) -> PageCommitResult: ...

    async def heartbeat(self, *, run_id: str, lease_token: str, now: datetime) -> None: ...

    async def finish_run(
        self,
        *,
        run_id: str,
        status: RunStatus,
        steps: Sequence[StepResult],
        lease_token: str,
        now: datetime,
    ) -> IngestionRun: ...


class RateCoordinator(Protocol):
    async def before_read(self, *, account_id: str, capability: IngestionCapability) -> None: ...

    async def observe(
        self,
        *,
        account_id: str,
        capability: IngestionCapability,
        observation: RateObservation | None,
    ) -> None: ...


class NoopRateCoordinator:
    async def before_read(self, *, account_id: str, capability: IngestionCapability) -> None:
        del account_id, capability

    async def observe(
        self,
        *,
        account_id: str,
        capability: IngestionCapability,
        observation: RateObservation | None,
    ) -> None:
        del account_id, capability, observation


class InMemoryRateCoordinator:
    """Deterministic local/test coordinator; distributed mode persists the same state."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._locks: dict[tuple[str, IngestionCapability], asyncio.Lock] = {}
        self._next_eligible: dict[tuple[str, IngestionCapability], datetime] = {}

    async def before_read(self, *, account_id: str, capability: IngestionCapability) -> None:
        key = (account_id, capability)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            eligible = self._next_eligible.get(key)
            now = _require_utc(self._clock(), "clock")
            if eligible is not None and eligible > now:
                await self._sleep((eligible - now).total_seconds())

    async def observe(
        self,
        *,
        account_id: str,
        capability: IngestionCapability,
        observation: RateObservation | None,
    ) -> None:
        if observation is None:
            return
        key = (account_id, capability)
        if observation.remaining == 0:
            current = self._next_eligible.get(key)
            if current is None or observation.reset_at > current:
                self._next_eligible[key] = observation.reset_at


class IngestionCoordinator:
    def __init__(
        self,
        *,
        provider: BrokerAccountDataProvider,
        store: IngestionStore,
        rate_coordinator: RateCoordinator | None = None,
        clock: Callable[[], datetime] | None = None,
        max_pages_per_capability: int = 500,
        lease_duration: timedelta = timedelta(minutes=5),
        incremental_overlap: timedelta = DEFAULT_INCREMENTAL_OVERLAP,
    ) -> None:
        if max_pages_per_capability < 1:
            raise ValueError("max_pages_per_capability must be positive")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if incremental_overlap <= timedelta(0):
            raise ValueError("incremental overlap must be positive")
        self._provider = provider
        self._store = store
        self._rate = rate_coordinator or NoopRateCoordinator()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_pages = max_pages_per_capability
        self._lease_duration = lease_duration
        self._incremental_overlap = incremental_overlap

    async def refresh(
        self,
        *,
        owner_id: str,
        account_id: str,
        mode: RunMode,
        idempotency_key: str,
        capabilities: Sequence[IngestionCapability] | None = None,
        correlation_id: str | None = None,
    ) -> IngestionRun:
        _bounded_identifier(owner_id, "owner_id")
        _bounded_identifier(account_id, "account_id")
        _bounded_identifier(idempotency_key, "idempotency_key")
        selected = tuple(FULL_REFRESH_ORDER if capabilities is None else capabilities)
        if not selected or len(selected) != len(set(selected)):
            raise ValueError("capabilities must be non-empty and unique")
        if any(not isinstance(capability, IngestionCapability) for capability in selected):
            raise ValueError("only typed ingestion capabilities are accepted")
        safe_correlation = correlation_id or str(uuid.uuid4())
        _bounded_identifier(safe_correlation, "correlation_id")
        now = _require_utc(self._clock(), "clock")
        run, lease = await self._store.begin_run(
            owner_id=owner_id,
            account_id=account_id,
            mode=mode,
            capabilities=selected,
            idempotency_key=idempotency_key,
            correlation_id=safe_correlation,
            now=now,
            lease_duration=self._lease_duration,
        )
        if lease is None:
            return run
        steps: list[StepResult] = []
        for capability in selected:
            step = await self._ingest_capability(
                run=run,
                capability=capability,
                lease=lease,
            )
            steps.append(step)
        failures = sum(step.status is RunStatus.FAILED for step in steps)
        final_status = (
            RunStatus.SUCCEEDED
            if failures == 0
            else RunStatus.FAILED
            if failures == len(steps)
            else RunStatus.PARTIAL
        )
        return await self._store.finish_run(
            run_id=run.id,
            status=final_status,
            steps=steps,
            lease_token=lease.token,
            now=_require_utc(self._clock(), "clock"),
        )

    async def _ingest_capability(
        self,
        *,
        run: IngestionRun,
        capability: IngestionCapability,
        lease: RunLease,
    ) -> StepResult:
        checkpoint = await self._store.get_checkpoint(
            account_id=run.account_id,
            capability=capability,
            mode=run.mode,
            overlap_window=self._incremental_overlap,
        )
        seen_pages: set[str] = set()
        totals = PageCommitResult(0, 0, 0)
        records_seen = 0
        warnings: list[str] = []
        for page_number in range(1, self._max_pages + 1):
            try:
                await self._await_with_lease_renewal(
                    self._rate.before_read(
                        account_id=run.account_id,
                        capability=capability,
                    ),
                    run_id=run.id,
                    lease=lease,
                )
                page = await self._await_with_lease_renewal(
                    self._provider.read_page(
                        owner_id=run.owner_id,
                        account_id=run.account_id,
                        capability=capability,
                        checkpoint=checkpoint,
                        correlation_id=run.correlation_id,
                    ),
                    run_id=run.id,
                    lease=lease,
                )
                if page.fingerprint in seen_pages:
                    raise IngestionFailure(
                        FailureCategory.PAGINATION,
                        "repeated provider page detected",
                    )
                seen_pages.add(page.fingerprint)
                if not page.records and not page.complete:
                    warnings.append("provider returned an empty intermediate page")
                await self._await_with_lease_renewal(
                    self._rate.observe(
                        account_id=run.account_id,
                        capability=capability,
                        observation=page.rate,
                    ),
                    run_id=run.id,
                    lease=lease,
                )
                commit = await self._store.commit_page(
                    run_id=run.id,
                    account_id=run.account_id,
                    capability=capability,
                    page=page,
                    lease_token=lease.token,
                    now=_require_utc(self._clock(), "clock"),
                )
                totals = PageCommitResult(
                    inserted=totals.inserted + commit.inserted,
                    updated=totals.updated + commit.updated,
                    unchanged=totals.unchanged + commit.unchanged,
                )
                records_seen += len(page.records)
                warnings.extend(page.warnings)
                await self._store.heartbeat(
                    run_id=run.id,
                    lease_token=lease.token,
                    now=_require_utc(self._clock(), "clock"),
                )
                if page.complete:
                    return StepResult(
                        capability=capability,
                        status=RunStatus.SUCCEEDED,
                        pages=page_number,
                        records_seen=records_seen,
                        inserted=totals.inserted,
                        updated=totals.updated,
                        unchanged=totals.unchanged,
                        warnings=tuple(warnings),
                    )
                checkpoint = page.next_checkpoint
            except IngestionFailure as exc:
                return _failed_step(
                    capability,
                    page_number - 1,
                    records_seen,
                    totals,
                    warnings,
                    exc.category,
                    str(exc),
                )
            except Exception as exc:
                return _failed_step(
                    capability,
                    page_number - 1,
                    records_seen,
                    totals,
                    warnings,
                    FailureCategory.UNKNOWN,
                    f"{type(exc).__name__}: ingestion unit failed",
                )
        return _failed_step(
            capability,
            self._max_pages,
            records_seen,
            totals,
            warnings,
            FailureCategory.PAGINATION,
            "maximum page bound exceeded",
        )

    async def _await_with_lease_renewal(
        self,
        operation: Awaitable[_Awaited],
        *,
        run_id: str,
        lease: RunLease,
    ) -> _Awaited:
        """Renew the fenced lease while awaiting provider or coordinator I/O."""

        interval = min(max(lease.duration.total_seconds() / 3, 0.05), 30.0)
        task = asyncio.ensure_future(operation)
        try:
            while True:
                done, _pending = await asyncio.wait((task,), timeout=interval)
                if done:
                    result = await task
                    await self._store.heartbeat(
                        run_id=run_id,
                        lease_token=lease.token,
                        now=_require_utc(self._clock(), "clock"),
                    )
                    return result
                await self._store.heartbeat(
                    run_id=run_id,
                    lease_token=lease.token,
                    now=_require_utc(self._clock(), "clock"),
                )
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


class InMemoryIngestionStore:
    """Atomic reference store used by fixtures; PostgreSQL implements the same contract."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.runs: dict[str, IngestionRun] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self._active: dict[tuple[str, str], tuple[str, datetime, str, timedelta]] = {}
        self.checkpoints: dict[tuple[str, IngestionCapability], Checkpoint | None] = {}
        self._checkpoint_complete: dict[tuple[str, IngestionCapability], bool] = {}
        self.source_records: dict[tuple[str, IngestionCapability, str, str], SourceRecord] = {}
        self.latest_provider_records: dict[tuple[str, IngestionCapability, str], str] = {}
        self.fail_next_commit = False

    async def begin_run(
        self,
        *,
        owner_id: str,
        account_id: str,
        mode: RunMode,
        capabilities: tuple[IngestionCapability, ...],
        idempotency_key: str,
        correlation_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> tuple[IngestionRun, RunLease | None]:
        from .refresh_semantics import (
            RefreshIdempotencyConflictError,
            RefreshRequestSemantics,
        )

        key = (account_id, idempotency_key)
        timestamp = _require_utc(now, "now")
        if lease_duration <= timedelta(0):
            raise ValueError("lease duration must be positive")
        requested = RefreshRequestSemantics.create(
            owner_id=owner_id,
            account_id=account_id,
            mode=mode,
            capabilities=capabilities,
        )
        async with self._lock:
            binding = self._idempotency.get(key)
            if binding is not None:
                run_id, request_fingerprint = binding
                if request_fingerprint != requested.fingerprint:
                    raise RefreshIdempotencyConflictError(
                        "idempotency key is already bound to different refresh semantics"
                    )
                run = self.runs[run_id]
                if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                    return run, None

                active = self._active.get(key)
                if active is not None and active[0] != run_id:
                    raise IngestionFailure(
                        FailureCategory.PERSISTENCE,
                        "in-memory idempotency binding is inconsistent",
                    )
                if active is not None and active[1] > timestamp:
                    return run, None

                # The fingerprint remains bound to the original requested command;
                # never rebuild it from execution fields that may have been promoted.
                lease_token = str(uuid.uuid4())
                run = replace(
                    run,
                    status=RunStatus.RUNNING,
                    correlation_id=correlation_id,
                    heartbeat_at=timestamp,
                    completed_at=None,
                )
                self.runs[run_id] = run
                self._active[key] = (
                    run_id,
                    timestamp + lease_duration,
                    lease_token,
                    lease_duration,
                )
                return run, RunLease(token=lease_token, duration=lease_duration)

            active = self._active.get(key)
            if active is not None:
                raise IngestionFailure(
                    FailureCategory.PERSISTENCE,
                    "in-memory active run lacks an idempotency binding",
                )
            run = IngestionRun(
                id=str(uuid.uuid4()),
                owner_id=owner_id,
                account_id=account_id,
                mode=mode,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                status=RunStatus.RUNNING,
                scheduled_at=timestamp,
                started_at=timestamp,
                heartbeat_at=timestamp,
            )
            lease_token = str(uuid.uuid4())
            self.runs[run.id] = run
            self._idempotency[key] = (run.id, requested.fingerprint)
            self._active[key] = (
                run.id,
                timestamp + lease_duration,
                lease_token,
                lease_duration,
            )
            return run, RunLease(token=lease_token, duration=lease_duration)

    async def get_checkpoint(
        self,
        *,
        account_id: str,
        capability: IngestionCapability,
        mode: RunMode,
        overlap_window: timedelta,
    ) -> Checkpoint | None:
        async with self._lock:
            key = (account_id, capability)
            checkpoint = self.checkpoints.get(key)
            if checkpoint is None or not self._checkpoint_complete.get(key, False):
                return checkpoint
            if mode is RunMode.FULL or capability is not IngestionCapability.TRANSACTIONS:
                return None
            high_water = checkpoint.source_timestamp
            if high_water is None:
                return None
            return Checkpoint(
                source_timestamp=high_water,
                overlap_started_at=_subtract_overlap(high_water, overlap_window),
            )

    async def commit_page(
        self,
        *,
        run_id: str,
        account_id: str,
        capability: IngestionCapability,
        page: SourcePage,
        lease_token: str,
        now: datetime,
    ) -> PageCommitResult:
        async with self._lock:
            if run_id not in self.runs or self.runs[run_id].status is not RunStatus.RUNNING:
                raise IngestionFailure(FailureCategory.PERSISTENCE, "run is not active")
            self._renew_memory_lease(run_id=run_id, lease_token=lease_token, now=now)
            if self.fail_next_commit:
                self.fail_next_commit = False
                raise IngestionFailure(
                    FailureCategory.PERSISTENCE, "injected atomic commit failure"
                )
            records_copy = dict(self.source_records)
            latest_copy = dict(self.latest_provider_records)
            inserted = updated = unchanged = 0
            for record in page.records:
                source_key = (
                    account_id,
                    capability,
                    record.idempotency_key,
                    record.payload_sha256,
                )
                if source_key in records_copy:
                    unchanged += 1
                    continue
                records_copy[source_key] = record
                if record.provider_record_id is None:
                    inserted += 1
                    continue
                latest_key = (account_id, capability, record.provider_record_id)
                prior_hash = latest_copy.get(latest_key)
                if prior_hash is None:
                    inserted += 1
                elif prior_hash == record.payload_sha256:
                    unchanged += 1
                else:
                    updated += 1
                latest_copy[latest_key] = record.payload_sha256
            self.source_records = records_copy
            self.latest_provider_records = latest_copy
            checkpoint_key = (account_id, capability)
            prior_checkpoint = self.checkpoints.get(checkpoint_key)
            prior_high_water = (
                prior_checkpoint.source_timestamp if prior_checkpoint is not None else None
            )
            page_high_water = max(
                (record.source_timestamp for record in page.records),
                default=None,
            )
            next_high_water = (
                page.next_checkpoint.source_timestamp if page.next_checkpoint is not None else None
            )
            high_water = _latest_timestamp(
                _latest_timestamp(prior_high_water, page_high_water),
                next_high_water,
            )
            if page.complete:
                durable_checkpoint = Checkpoint(
                    source_timestamp=high_water,
                    page_fingerprint=page.fingerprint,
                )
            else:
                assert page.next_checkpoint is not None
                durable_checkpoint = replace(
                    page.next_checkpoint,
                    source_timestamp=high_water,
                )
            self.checkpoints[checkpoint_key] = durable_checkpoint
            self._checkpoint_complete[checkpoint_key] = page.complete
            return PageCommitResult(inserted, updated, unchanged)

    async def heartbeat(self, *, run_id: str, lease_token: str, now: datetime) -> None:
        async with self._lock:
            run = self.runs[run_id]
            self._renew_memory_lease(run_id=run_id, lease_token=lease_token, now=now)
            self.runs[run_id] = replace(run, heartbeat_at=now)

    async def finish_run(
        self,
        *,
        run_id: str,
        status: RunStatus,
        steps: Sequence[StepResult],
        lease_token: str,
        now: datetime,
    ) -> IngestionRun:
        async with self._lock:
            self._require_memory_lease(run_id=run_id, lease_token=lease_token, now=now)
            run = replace(
                self.runs[run_id],
                status=status,
                steps=tuple(steps),
                heartbeat_at=now,
                completed_at=now,
            )
            self.runs[run_id] = run
            for key, active in tuple(self._active.items()):
                if active[0] == run_id:
                    del self._active[key]
            return run

    def _require_memory_lease(
        self, *, run_id: str, lease_token: str, now: datetime
    ) -> tuple[tuple[str, str], tuple[str, datetime, str, timedelta]]:
        for key, active in self._active.items():
            if active[0] == run_id:
                if active[1] <= now or active[2] != lease_token:
                    break
                return key, active
        raise IngestionFailure(FailureCategory.PERSISTENCE, "run lease is no longer active")

    def _renew_memory_lease(self, *, run_id: str, lease_token: str, now: datetime) -> None:
        key, active = self._require_memory_lease(
            run_id=run_id,
            lease_token=lease_token,
            now=now,
        )
        self._active[key] = (active[0], now + active[3], active[2], active[3])


def _latest_timestamp(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _subtract_overlap(high_water: datetime, overlap_window: timedelta) -> datetime:
    if overlap_window <= timedelta(0):
        raise ValueError("incremental overlap must be positive")
    try:
        return high_water - overlap_window
    except OverflowError:
        return datetime.min.replace(tzinfo=UTC)


def _failed_step(
    capability: IngestionCapability,
    pages: int,
    records_seen: int,
    totals: PageCommitResult,
    warnings: Sequence[str],
    category: FailureCategory,
    message: str,
) -> StepResult:
    return StepResult(
        capability=capability,
        status=RunStatus.FAILED,
        pages=pages,
        records_seen=records_seen,
        inserted=totals.inserted,
        updated=totals.updated,
        unchanged=totals.unchanged,
        warnings=tuple(warnings),
        failure_category=category,
        failure_message=message[:256],
    )


def _bounded_identifier(value: str, name: str) -> None:
    if not value or len(value) > 512 or any(character.isspace() for character in value):
        raise ValueError(f"{name} must be non-empty, whitespace-free, and bounded")


def _reject_sensitive_keys(value: object) -> None:
    forbidden = ("authorization", "password", "secret", "credential", "api_key", "token")
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(name in normalized for name in forbidden):
                raise ValueError("source payload contains a forbidden sensitive field")
            _reject_sensitive_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_sensitive_keys(child)


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("source payload decimal must be finite")
        return {"$decimal": str(value)}
    if isinstance(value, datetime):
        return {"$datetime": _require_utc(value, "payload timestamp").isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, MappingProxyType):
        return dict(value)
    raise TypeError(f"unsupported source value: {type(value).__name__}")


def _checkpoint_json(checkpoint: Checkpoint | None) -> object:
    if checkpoint is None:
        return None
    return {
        "cursor": checkpoint.cursor,
        "source_timestamp": checkpoint.source_timestamp,
        "provider_id": checkpoint.provider_id,
        "page_fingerprint": checkpoint.page_fingerprint,
        "overlap_started_at": checkpoint.overlap_started_at,
    }
