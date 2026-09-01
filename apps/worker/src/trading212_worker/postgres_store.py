"""PostgreSQL implementation of the restartable ingestion store contract."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.ingestion import (
    Checkpoint,
    FailureCategory,
    IngestionCapability,
    IngestionFailure,
    IngestionRun,
    PageCommitResult,
    RunLease,
    RunMode,
    RunStatus,
    SourcePage,
    StepResult,
)
from trading212_application.refresh_semantics import (
    RefreshIdempotencyConflictError,
    RefreshRequestSemantics,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    IngestionCheckpointModel,
    IngestionLeaseModel,
    IngestionRunModel,
    RefreshDispatchOutboxModel,
    SourceRecordModel,
    SourceRecordOccurrenceModel,
)
from trading212_persistence.refresh_semantics import MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS

from .materializer import PostgresCanonicalMaterializer

_RETRYABLE_TERMINAL_FAILURES = {
    FailureCategory.RATE_LIMIT.value,
    FailureCategory.TRANSIENT.value,
    FailureCategory.PERSISTENCE.value,
    FailureCategory.INTERRUPTED.value,
}


class RunLeaseBusyError(RuntimeError):
    """The requested durable run cannot claim its account lease yet."""

    def __init__(self, *, available_at: datetime) -> None:
        super().__init__("refresh account lease is busy")
        self.available_at = available_at


class ConsumerExecutionBudgetExhaustedError(RuntimeError):
    """The durable run has consumed its bounded economic execution budget."""


class PostgresIngestionStore:
    """Atomic source-record/checkpoint persistence with a DB-backed account lease."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        provider: str,
        lease_duration: timedelta = timedelta(minutes=5),
        materializer: PostgresCanonicalMaterializer | None = None,
        expected_run_id: str | None = None,
    ) -> None:
        if provider not in {"trading212", "synthetic"}:
            raise ValueError("unsupported source-record provider")
        if lease_duration <= timedelta(0):
            raise ValueError("lease duration must be positive")
        self._sessions = session_factory
        self._provider = provider
        self._lease_duration = lease_duration
        self._materializer = materializer
        self._expected_run_id = (
            _uuid(expected_run_id, "expected_run_id") if expected_run_id is not None else None
        )

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
        owner_uuid = _uuid(owner_id, "owner_id")
        account_uuid = _uuid(account_id, "account_id")
        timestamp = _utc(now)
        semantics = RefreshRequestSemantics.create(
            owner_id=owner_uuid,
            account_id=account_uuid,
            mode=mode,
            capabilities=capabilities,
        )
        effective_lease = min(lease_duration, self._lease_duration)
        if effective_lease <= timedelta(0):
            raise ValueError("lease duration must be positive")
        with self._sessions.begin() as session:
            _lock_account(session, account_uuid)
            if not _account_is_owned(session, owner_uuid, account_uuid):
                raise IngestionFailure(FailureCategory.AUTHORIZATION, "account access denied")

            existing = session.scalar(
                select(IngestionRunModel)
                .where(
                    IngestionRunModel.broker_account_id == account_uuid,
                    IngestionRunModel.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if self._expected_run_id is not None and (
                existing is None or existing.id != self._expected_run_id
            ):
                raise IngestionFailure(
                    FailureCategory.PERSISTENCE,
                    "durable dispatch does not match the requested run",
                )
            if (
                self._expected_run_id is None
                and existing is not None
                and existing.request_fingerprint != semantics.fingerprint
            ):
                raise RefreshIdempotencyConflictError(
                    "idempotency key is already bound to different refresh semantics"
                )
            dispatch = None
            if self._expected_run_id is not None:
                dispatch = session.scalar(
                    select(RefreshDispatchOutboxModel)
                    .where(RefreshDispatchOutboxModel.ingestion_run_id == self._expected_run_id)
                    .with_for_update()
                )
                if dispatch is None:
                    raise IngestionFailure(
                        FailureCategory.PERSISTENCE,
                        "durable dispatch does not exist",
                    )
            retryable_terminal = False
            if existing is not None and existing.status not in {
                RunStatus.QUEUED.value,
                RunStatus.RUNNING.value,
            }:
                if existing.error_code not in _RETRYABLE_TERMINAL_FAILURES:
                    return _domain_run(session, existing, owner_uuid), None
                retryable_terminal = True

            lease = session.scalar(
                select(IngestionLeaseModel)
                .where(
                    IngestionLeaseModel.broker_account_id == account_uuid,
                    IngestionLeaseModel.lease_type == "refresh",
                )
                .with_for_update()
            )
            if lease is not None and lease.expires_at > timestamp:
                if self._expected_run_id is not None:
                    raise RunLeaseBusyError(available_at=lease.expires_at)
                if (
                    lease.run_id is not None
                    and existing is not None
                    and lease.run_id == existing.id
                ):
                    return _domain_run(session, existing, owner_uuid), None
                if lease.run_id is not None:
                    active = session.get(IngestionRunModel, lease.run_id)
                    if active is not None:
                        return _domain_run(session, active, owner_uuid), None
                raise IngestionFailure(
                    FailureCategory.PERSISTENCE,
                    "refresh account lease is busy",
                )
            if (
                dispatch is not None
                and dispatch.consumer_attempt_count >= MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS
            ):
                raise ConsumerExecutionBudgetExhaustedError(
                    "durable refresh consumer execution budget is exhausted"
                )
            if retryable_terminal and existing is not None:
                existing.status = RunStatus.QUEUED.value
                existing.completed_at = None

            if existing is None:
                existing = IngestionRunModel(
                    id=uuid4(),
                    broker_account_id=account_uuid,
                    capability="multi_capability_refresh",
                    mode=mode.value,
                    status=RunStatus.RUNNING.value,
                    idempotency_key=idempotency_key,
                    request_schema_version=semantics.schema_version,
                    requested_mode=semantics.mode.value,
                    requested_create_snapshot=semantics.create_snapshot,
                    requested_capabilities=semantics.capability_values,
                    effective_capabilities=semantics.capability_values,
                    request_fingerprint=semantics.fingerprint,
                    correlation_id=correlation_id,
                    started_at=timestamp,
                    heartbeat_at=timestamp,
                )
                session.add(existing)
                session.flush()
            else:
                existing.status = RunStatus.RUNNING.value
                existing.heartbeat_at = timestamp
                existing.correlation_id = correlation_id
            if dispatch is not None:
                dispatch.consumer_attempt_count += 1

            fencing_token = uuid4()
            if lease is None:
                lease = IngestionLeaseModel(
                    broker_account_id=account_uuid,
                    lease_type="refresh",
                    lease_owner=correlation_id,
                    fencing_token=fencing_token,
                    acquired_at=timestamp,
                    heartbeat_at=timestamp,
                    expires_at=timestamp + effective_lease,
                    run_id=existing.id,
                )
                session.add(lease)
            else:
                lease.lease_owner = correlation_id
                lease.fencing_token = fencing_token
                lease.acquired_at = timestamp
                lease.heartbeat_at = timestamp
                lease.expires_at = timestamp + effective_lease
                lease.run_id = existing.id
            session.flush()
            return _domain_run(session, existing, owner_uuid), RunLease(
                token=str(fencing_token),
                duration=effective_lease,
            )

    async def get_checkpoint(
        self,
        *,
        account_id: str,
        capability: IngestionCapability,
        mode: RunMode,
        overlap_window: timedelta,
    ) -> Checkpoint | None:
        account_uuid = _uuid(account_id, "account_id")
        with self._sessions() as session:
            model = session.scalar(
                select(IngestionCheckpointModel).where(
                    IngestionCheckpointModel.broker_account_id == account_uuid,
                    IngestionCheckpointModel.capability == capability.value,
                )
            )
            if model is None:
                return None
            if not bool(model.state.get("complete")):
                return _checkpoint_from_state(model.state)
            if mode is RunMode.FULL or capability is not IngestionCapability.TRANSACTIONS:
                return None
            high_water = model.coverage_end_at
            if high_water is None:
                try:
                    high_water = _checkpoint_from_state(model.state).source_timestamp
                except IngestionFailure:
                    return None
            if high_water is None:
                return None
            normalized_high_water = _utc(high_water)
            return Checkpoint(
                source_timestamp=normalized_high_water,
                overlap_started_at=_subtract_overlap(normalized_high_water, overlap_window),
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
        run_uuid = _uuid(run_id, "run_id")
        account_uuid = _uuid(account_id, "account_id")
        timestamp = _utc(now)
        with self._sessions.begin() as session:
            run = session.scalar(
                select(IngestionRunModel).where(IngestionRunModel.id == run_uuid).with_for_update()
            )
            if (
                run is None
                or run.broker_account_id != account_uuid
                or run.status != RunStatus.RUNNING.value
            ):
                raise IngestionFailure(FailureCategory.PERSISTENCE, "run is not active")
            lease = _require_active_lease(
                session,
                run=run,
                lease_token=lease_token,
                now=timestamp,
            )
            inserted_count = updated_count = unchanged_count = 0
            for record in page.records:
                prior = _latest_source_record(
                    session,
                    account_uuid=account_uuid,
                    capability=capability,
                    provider_record_id=record.provider_record_id,
                    payload_fingerprint=record.payload_sha256,
                )
                if prior is not None and prior.payload_fingerprint == record.payload_sha256:
                    unchanged_count += 1
                    source_record_id = prior.id
                else:
                    statement = (
                        insert(SourceRecordModel)
                        .values(
                            id=uuid4(),
                            ingestion_run_id=run_uuid,
                            broker_account_id=account_uuid,
                            provider=self._provider,
                            capability=capability.value,
                            provider_record_type=capability.value,
                            provider_record_id=record.provider_record_id,
                            payload_fingerprint=record.payload_sha256,
                            source_updated_at=record.source_timestamp,
                            observed_at=record.observed_at,
                            schema_version=record.schema_version,
                            sanitized_payload=_json_value(record.payload),
                        )
                        .on_conflict_do_nothing()
                        .returning(SourceRecordModel.id)
                    )
                    created = session.scalar(statement)
                    if created is None:
                        source_record_id = _source_record_by_version(
                            session,
                            account_uuid=account_uuid,
                            capability=capability,
                            provider_record_id=record.provider_record_id,
                            payload_fingerprint=record.payload_sha256,
                        ).id
                        unchanged_count += 1
                    elif prior is None:
                        source_record_id = created
                        inserted_count += 1
                    else:
                        source_record_id = created
                        updated_count += 1
                session.execute(
                    insert(SourceRecordOccurrenceModel)
                    .values(
                        id=uuid4(),
                        ingestion_run_id=run_uuid,
                        source_record_id=source_record_id,
                        observed_at=record.observed_at,
                        source_updated_at=record.source_timestamp,
                    )
                    .on_conflict_do_update(
                        constraint="uq_source_record_occurrences_run_record",
                        set_={
                            "observed_at": record.observed_at,
                            "source_updated_at": record.source_timestamp,
                        },
                    )
                )

            checkpoint = session.scalar(
                select(IngestionCheckpointModel)
                .where(
                    IngestionCheckpointModel.broker_account_id == account_uuid,
                    IngestionCheckpointModel.capability == capability.value,
                )
                .with_for_update()
            )
            source_times = [record.source_timestamp for record in page.records]
            prior_high_water = checkpoint.coverage_end_at if checkpoint is not None else None
            next_high_water = (
                page.next_checkpoint.source_timestamp if page.next_checkpoint is not None else None
            )
            high_water = _latest(
                _latest(prior_high_water, max(source_times, default=None)),
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
            state = _checkpoint_state(durable_checkpoint, complete=page.complete)
            if checkpoint is None:
                checkpoint = IngestionCheckpointModel(
                    broker_account_id=account_uuid,
                    capability=capability.value,
                    state=state,
                    version=1,
                    coverage_start_at=min(source_times, default=None),
                    coverage_end_at=high_water,
                    coverage_complete=page.complete,
                    advanced_by_run_id=run_uuid,
                )
                session.add(checkpoint)
            else:
                checkpoint.state = state
                checkpoint.version += 1
                new_start = min(source_times, default=None)
                new_end = high_water
                checkpoint.coverage_start_at = _earliest(checkpoint.coverage_start_at, new_start)
                checkpoint.coverage_end_at = _latest(checkpoint.coverage_end_at, new_end)
                checkpoint.coverage_complete = page.complete
                checkpoint.advanced_by_run_id = run_uuid
            run.request_count += 1
            run.records_received += len(page.records)
            run.heartbeat_at = timestamp
            _renew_lease(lease, now=timestamp)
            session.flush()
            return PageCommitResult(inserted_count, updated_count, unchanged_count)

    async def heartbeat(self, *, run_id: str, lease_token: str, now: datetime) -> None:
        run_uuid = _uuid(run_id, "run_id")
        timestamp = _utc(now)
        with self._sessions.begin() as session:
            run = session.scalar(
                select(IngestionRunModel).where(IngestionRunModel.id == run_uuid).with_for_update()
            )
            if run is None or run.status != RunStatus.RUNNING.value:
                raise IngestionFailure(FailureCategory.PERSISTENCE, "run is not active")
            lease = _require_active_lease(
                session,
                run=run,
                lease_token=lease_token,
                now=timestamp,
            )
            run.heartbeat_at = timestamp
            _renew_lease(lease, now=timestamp)

    async def finish_run(
        self,
        *,
        run_id: str,
        status: RunStatus,
        steps: Sequence[StepResult],
        lease_token: str,
        now: datetime,
    ) -> IngestionRun:
        run_uuid = _uuid(run_id, "run_id")
        timestamp = _utc(now)
        if status in {RunStatus.QUEUED, RunStatus.RUNNING}:
            raise ValueError("finish status must be terminal")
        with self._sessions.begin() as session:
            account_id = session.scalar(
                select(IngestionRunModel.broker_account_id).where(IngestionRunModel.id == run_uuid)
            )
            if account_id is None:
                raise IngestionFailure(FailureCategory.PERSISTENCE, "run does not exist")
            _lock_account(session, account_id)
            run = session.scalar(
                select(IngestionRunModel).where(IngestionRunModel.id == run_uuid).with_for_update()
            )
            if run is None:
                raise IngestionFailure(FailureCategory.PERSISTENCE, "run does not exist")
            if run.status != RunStatus.RUNNING.value:
                raise IngestionFailure(FailureCategory.PERSISTENCE, "run is not active")
            _require_active_lease(
                session,
                run=run,
                lease_token=lease_token,
                now=timestamp,
            )
            effective_status = status
            effective_steps = tuple(steps)
            selected_capabilities = tuple(step.capability for step in effective_steps)
            retained_metadata = [
                dict(item)
                for item in run.warnings or ()
                if isinstance(item, Mapping)
                and "capability" not in item
                and item.get("kind") != "refresh_selection"
            ]
            previous_selection = next(
                (
                    dict(item)
                    for item in run.warnings or ()
                    if isinstance(item, Mapping) and item.get("kind") == "refresh_selection"
                ),
                {},
            )
            selection_metadata = {
                **previous_selection,
                "kind": "refresh_selection",
                "actual_mode": run.mode,
                "capabilities": [capability.value for capability in selected_capabilities],
            }
            run.warnings = [
                *retained_metadata,
                selection_metadata,
                *(_step_state(step) for step in effective_steps),
            ]
            session.flush()
            normalized_count = sum(step.inserted + step.updated for step in steps)
            if status is RunStatus.SUCCEEDED and self._materializer is not None:
                try:
                    with session.begin_nested():
                        materialization = self._materializer.materialize(
                            session,
                            run_id=run_uuid,
                            account_id=run.broker_account_id,
                            now=timestamp,
                            capabilities=selected_capabilities,
                        )
                    normalized_count = materialization.normalized_rows
                except Exception:
                    effective_status = RunStatus.FAILED
                    normalized_count = 0
                    if effective_steps:
                        last = effective_steps[-1]
                        effective_steps = (
                            *effective_steps[:-1],
                            replace(
                                last,
                                status=RunStatus.FAILED,
                                warnings=(*last.warnings, "canonical materialization failed"),
                                failure_category=FailureCategory.PERSISTENCE,
                                failure_message="canonical materialization failed",
                            ),
                        )
            run.status = effective_status.value
            run.heartbeat_at = timestamp
            run.completed_at = timestamp
            run.records_normalized = normalized_count
            run.records_rejected = sum(
                step.records_seen if step.status is RunStatus.FAILED else 0
                for step in effective_steps
            )
            run.warnings = [
                *retained_metadata,
                selection_metadata,
                *(_step_state(step) for step in effective_steps),
            ]
            failed_categories = [
                step.failure_category.value
                for step in effective_steps
                if step.failure_category is not None
            ]
            run.error_code = failed_categories[0] if failed_categories else None
            session.execute(
                delete(IngestionLeaseModel).where(
                    IngestionLeaseModel.run_id == run_uuid,
                    IngestionLeaseModel.fencing_token == _uuid(lease_token, "lease_token"),
                )
            )
            session.flush()
            owner_id = session.scalar(
                select(BrokerConnectionModel.owner_id)
                .join(
                    BrokerAccountModel,
                    BrokerAccountModel.connection_id == BrokerConnectionModel.id,
                )
                .where(BrokerAccountModel.id == run.broker_account_id)
            )
            if owner_id is None:
                raise IngestionFailure(FailureCategory.PERSISTENCE, "run account is missing")
            return _domain_run(session, run, owner_id)


def _uuid(value: str, name: str) -> UUID:
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _advisory_key(account_id: UUID) -> int:
    raw = int.from_bytes(hashlib.sha256(account_id.bytes).digest()[:8], "big")
    return raw if raw < 2**63 else raw - 2**64


def _lock_account(session: Session, account_id: UUID) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(:account_lock)"),
        {"account_lock": _advisory_key(account_id)},
    )


def _require_active_lease(
    session: Session,
    *,
    run: IngestionRunModel,
    lease_token: str,
    now: datetime,
) -> IngestionLeaseModel:
    token = _uuid(lease_token, "lease_token")
    lease = session.scalar(
        select(IngestionLeaseModel)
        .where(
            IngestionLeaseModel.broker_account_id == run.broker_account_id,
            IngestionLeaseModel.lease_type == "refresh",
        )
        .with_for_update()
    )
    if (
        lease is None
        or lease.run_id != run.id
        or lease.fencing_token != token
        or lease.expires_at <= now
    ):
        raise IngestionFailure(FailureCategory.PERSISTENCE, "run lease is no longer active")
    return lease


def _renew_lease(lease: IngestionLeaseModel, *, now: datetime) -> None:
    duration = lease.expires_at - lease.heartbeat_at
    if duration <= timedelta(0):
        raise IngestionFailure(FailureCategory.PERSISTENCE, "run lease duration is invalid")
    lease.heartbeat_at = now
    lease.expires_at = now + duration


def _account_is_owned(session: Session, owner_id: UUID, account_id: UUID) -> bool:
    return (
        session.scalar(
            select(BrokerAccountModel.id)
            .join(
                BrokerConnectionModel,
                BrokerConnectionModel.id == BrokerAccountModel.connection_id,
            )
            .where(
                BrokerAccountModel.id == account_id,
                BrokerConnectionModel.owner_id == owner_id,
            )
        )
        is not None
    )


def _latest_source_record(
    session: Session,
    *,
    account_uuid: UUID,
    capability: IngestionCapability,
    provider_record_id: str | None,
    payload_fingerprint: str,
) -> SourceRecordModel | None:
    query = select(SourceRecordModel).where(
        SourceRecordModel.broker_account_id == account_uuid,
        SourceRecordModel.capability == capability.value,
    )
    if provider_record_id is None:
        query = query.where(
            SourceRecordModel.provider_record_id.is_(None),
            SourceRecordModel.payload_fingerprint == payload_fingerprint,
        )
    else:
        query = query.where(SourceRecordModel.provider_record_id == provider_record_id)
    return session.scalar(
        query.order_by(
            SourceRecordModel.observed_at.desc(), SourceRecordModel.created_at.desc()
        ).limit(1)
    )


def _source_record_by_version(
    session: Session,
    *,
    account_uuid: UUID,
    capability: IngestionCapability,
    provider_record_id: str | None,
    payload_fingerprint: str,
) -> SourceRecordModel:
    query = select(SourceRecordModel).where(
        SourceRecordModel.broker_account_id == account_uuid,
        SourceRecordModel.capability == capability.value,
        SourceRecordModel.payload_fingerprint == payload_fingerprint,
    )
    if provider_record_id is None:
        query = query.where(SourceRecordModel.provider_record_id.is_(None))
    else:
        query = query.where(SourceRecordModel.provider_record_id == provider_record_id)
    model = session.scalar(query.limit(1))
    if model is None:
        raise IngestionFailure(
            FailureCategory.PERSISTENCE,
            "source record conflict could not be resolved",
        )
    return model


def _checkpoint_state(checkpoint: Checkpoint | None, *, complete: bool) -> dict[str, Any]:
    return {
        "complete": complete,
        "cursor": checkpoint.cursor if checkpoint is not None else None,
        "source_timestamp": (
            checkpoint.source_timestamp.isoformat()
            if checkpoint is not None and checkpoint.source_timestamp is not None
            else None
        ),
        "provider_id": checkpoint.provider_id if checkpoint is not None else None,
        "page_fingerprint": checkpoint.page_fingerprint if checkpoint is not None else None,
        "overlap_started_at": (
            checkpoint.overlap_started_at.isoformat()
            if checkpoint is not None and checkpoint.overlap_started_at is not None
            else None
        ),
    }


def _checkpoint_from_state(state: Mapping[str, Any]) -> Checkpoint:
    return Checkpoint(
        cursor=_optional_string(state.get("cursor")),
        source_timestamp=_optional_datetime(state.get("source_timestamp")),
        provider_id=_optional_string(state.get("provider_id")),
        page_fingerprint=_optional_string(state.get("page_fingerprint")),
        overlap_started_at=_optional_datetime(state.get("overlap_started_at")),
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IngestionFailure(FailureCategory.PERSISTENCE, "checkpoint string is invalid")
    return value


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IngestionFailure(FailureCategory.PERSISTENCE, "checkpoint timestamp is invalid")
    return _utc(datetime.fromisoformat(value))


def _json_value(value: object) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("source decimal must be finite")
        return {"$decimal": format(value, "f")}
    if isinstance(value, datetime):
        return {"$datetime": _utc(value).isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, MappingProxyType):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(child) for child in value]
    raise TypeError(f"unsupported source payload value: {type(value).__name__}")


def _step_state(step: StepResult) -> dict[str, Any]:
    return {
        "capability": step.capability.value,
        "status": step.status.value,
        "pages": step.pages,
        "records_seen": step.records_seen,
        "inserted": step.inserted,
        "updated": step.updated,
        "unchanged": step.unchanged,
        "warnings": list(step.warnings),
        "failure_category": (
            step.failure_category.value if step.failure_category is not None else None
        ),
        "failure_message": step.failure_message,
    }


def _step_from_state(state: Mapping[str, Any]) -> StepResult:
    category = state.get("failure_category")
    return StepResult(
        capability=IngestionCapability(str(state["capability"])),
        status=RunStatus(str(state["status"])),
        pages=int(state["pages"]),
        records_seen=int(state["records_seen"]),
        inserted=int(state["inserted"]),
        updated=int(state["updated"]),
        unchanged=int(state["unchanged"]),
        warnings=tuple(str(item) for item in state.get("warnings", [])),
        failure_category=FailureCategory(str(category)) if category is not None else None,
        failure_message=(
            str(state["failure_message"]) if state.get("failure_message") is not None else None
        ),
    )


def _domain_run(session: Session, model: IngestionRunModel, owner_id: UUID) -> IngestionRun:
    del session
    raw_steps = model.warnings or []
    steps = tuple(_step_from_state(state) for state in raw_steps if "capability" in state)
    return IngestionRun(
        id=str(model.id),
        owner_id=str(owner_id),
        account_id=str(model.broker_account_id),
        mode=RunMode(model.mode),
        idempotency_key=model.idempotency_key,
        correlation_id=model.correlation_id,
        status=RunStatus(model.status),
        scheduled_at=model.started_at,
        started_at=model.started_at,
        heartbeat_at=model.heartbeat_at,
        completed_at=model.completed_at,
        steps=steps,
    )


def _earliest(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _latest(left: datetime | None, right: datetime | None) -> datetime | None:
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
