"""Durable PostgreSQL refresh queue with a non-authoritative Celery notification."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from celery import Celery  # type: ignore[import-untyped]
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.ingestion import (
    FULL_REFRESH_ORDER,
    IngestionCapability,
    RunMode,
    RunStatus,
    validate_refresh_capabilities,
)
from trading212_application.services import RefreshQueue, RefreshUnavailableError
from trading212_application.views import RefreshRunView
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    IngestionCheckpointModel,
    IngestionRunModel,
    PortfolioSnapshotModel,
)
from trading212_security.principals import AuthorizationError


class PostgresRefreshQueue(RefreshQueue):
    """Persist canonical queue state before publishing an ephemeral worker message."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        celery: Celery,
        clock: Callable[[], datetime],
    ) -> None:
        self._sessions = sessions
        self._celery = celery
        self._clock = clock

    async def enqueue(
        self,
        *,
        owner_id: str,
        account_id: str,
        mode: RunMode,
        capabilities: tuple[IngestionCapability, ...],
        idempotency_key: str,
        correlation_id: str,
    ) -> RefreshRunView:
        owner_uuid = _uuid(owner_id, "owner_id")
        account_uuid = _uuid(account_id, "account_id")
        if not isinstance(mode, RunMode):
            raise ValueError("only typed refresh modes are accepted")
        requested_capabilities = validate_refresh_capabilities(capabilities)
        if not idempotency_key or len(idempotency_key) > 180:
            raise ValueError("invalid idempotency key")
        if not correlation_id or len(correlation_id) > 120:
            raise ValueError("invalid correlation ID")
        now = _utc(self._clock())
        should_publish = False
        publish_mode = mode
        publish_capabilities = requested_capabilities
        publish_correlation_id = correlation_id
        with self._sessions.begin() as session:
            _lock_account(session, account_uuid)
            if not _account_is_owned(session, owner_uuid, account_uuid):
                raise AuthorizationError("access denied")
            run = session.scalar(
                select(IngestionRunModel)
                .where(
                    IngestionRunModel.broker_account_id == account_uuid,
                    IngestionRunModel.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if run is None:
                publish_mode, publish_capabilities, promotion_warning = _effective_selection(
                    session,
                    account_id=account_uuid,
                    requested_mode=mode,
                    requested_capabilities=requested_capabilities,
                )
                run = IngestionRunModel(
                    id=uuid4(),
                    broker_account_id=account_uuid,
                    capability="multi_capability_refresh",
                    mode=publish_mode.value,
                    status=RunStatus.QUEUED.value,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    started_at=now,
                    heartbeat_at=now,
                    warnings=[
                        _selection_state(
                            requested_mode=mode,
                            requested_capabilities=requested_capabilities,
                            actual_mode=publish_mode,
                            actual_capabilities=publish_capabilities,
                            warning=promotion_warning,
                        )
                    ],
                )
                session.add(run)
                session.flush()
                should_publish = True
            elif run.status == RunStatus.FAILED.value and run.error_code == "queue_unavailable":
                run.status = RunStatus.QUEUED.value
                run.error_code = None
                run.completed_at = None
                run.heartbeat_at = now
                should_publish = True
            publish_mode = RunMode(run.mode)
            publish_capabilities = _persisted_capabilities(run)
            publish_correlation_id = run.correlation_id
            view = _view(run)

        if should_publish:
            try:
                self._celery.send_task(
                    "portfolio.refresh",
                    kwargs={
                        "owner_id": owner_id,
                        "account_id": account_id,
                        "mode": publish_mode.value,
                        "capabilities": [capability.value for capability in publish_capabilities],
                        "idempotency_key": idempotency_key,
                        "correlation_id": publish_correlation_id,
                    },
                )
            except Exception as exc:
                self._mark_publish_failed(view.id)
                raise RefreshUnavailableError("refresh queue is unavailable") from exc
        return view

    async def get(self, *, owner_id: str, run_id: str) -> RefreshRunView:
        owner_uuid = _uuid(owner_id, "owner_id")
        run_uuid = _uuid(run_id, "run_id")
        with self._sessions() as session:
            run = session.scalar(
                select(IngestionRunModel)
                .join(
                    BrokerAccountModel,
                    BrokerAccountModel.id == IngestionRunModel.broker_account_id,
                )
                .join(
                    BrokerConnectionModel,
                    BrokerConnectionModel.id == BrokerAccountModel.connection_id,
                )
                .where(
                    IngestionRunModel.id == run_uuid,
                    BrokerConnectionModel.owner_id == owner_uuid,
                )
            )
            if run is None:
                raise LookupError("refresh run not found")
            return _view(run)

    def _mark_publish_failed(self, run_id: str) -> None:
        now = _utc(self._clock())
        with self._sessions.begin() as session:
            run = session.get(IngestionRunModel, UUID(run_id))
            if run is not None and run.status == RunStatus.QUEUED.value:
                run.status = RunStatus.FAILED.value
                run.error_code = "queue_unavailable"
                run.completed_at = now
                run.heartbeat_at = now


def _view(run: IngestionRunModel) -> RefreshRunView:
    warnings = [str(value) for item in (run.warnings or []) for value in item.get("warnings", [])][
        :20
    ]
    return RefreshRunView(
        id=str(run.id),
        account_id=str(run.broker_account_id),
        status=run.status,
        requested_at=run.started_at,
        completed_at=run.completed_at,
        correlation_id=run.correlation_id,
        capabilities=tuple(capability.value for capability in _view_capabilities(run)),
        warnings=tuple(warnings),
    )


def _effective_selection(
    session: Session,
    *,
    account_id: UUID,
    requested_mode: RunMode,
    requested_capabilities: tuple[IngestionCapability, ...],
) -> tuple[RunMode, tuple[IngestionCapability, ...], str | None]:
    required_values = tuple(capability.value for capability in FULL_REFRESH_ORDER)
    required = set(required_values)
    available = set(
        session.scalars(
            select(IngestionCheckpointModel.capability).where(
                IngestionCheckpointModel.broker_account_id == account_id,
                IngestionCheckpointModel.capability.in_(required_values),
                IngestionCheckpointModel.coverage_complete.is_(True),
            )
        )
    )
    has_canonical_snapshot = (
        session.scalar(
            select(PortfolioSnapshotModel.id)
            .where(PortfolioSnapshotModel.broker_account_id == account_id)
            .limit(1)
        )
        is not None
    )
    if required.issubset(available) and has_canonical_snapshot:
        return requested_mode, requested_capabilities, None
    return (
        RunMode.FULL,
        FULL_REFRESH_ORDER,
        "initial synchronization promoted the request to full/all capability coverage",
    )


def _selection_state(
    *,
    requested_mode: RunMode,
    requested_capabilities: tuple[IngestionCapability, ...],
    actual_mode: RunMode,
    actual_capabilities: tuple[IngestionCapability, ...],
    warning: str | None,
) -> dict[str, object]:
    return {
        "kind": "refresh_selection",
        "requested_mode": requested_mode.value,
        "requested_capabilities": [capability.value for capability in requested_capabilities],
        "actual_mode": actual_mode.value,
        "capabilities": [capability.value for capability in actual_capabilities],
        "warnings": [warning] if warning is not None else [],
    }


def _persisted_capabilities(
    run: IngestionRunModel,
) -> tuple[IngestionCapability, ...]:
    for item in run.warnings or []:
        if item.get("kind") != "refresh_selection":
            continue
        raw = item.get("capabilities")
        if not isinstance(raw, list):
            break
        try:
            parsed = tuple(IngestionCapability(str(value)) for value in raw)
        except ValueError as exc:
            raise ValueError("persisted refresh selection is invalid") from exc
        return validate_refresh_capabilities(parsed)
    return FULL_REFRESH_ORDER


def _view_capabilities(run: IngestionRunModel) -> tuple[IngestionCapability, ...]:
    for item in run.warnings or []:
        raw = item.get("capabilities")
        if item.get("kind") != "refresh_selection" or not isinstance(raw, list):
            continue
        try:
            return tuple(IngestionCapability(str(value)) for value in raw)
        except ValueError:
            break
    steps: list[IngestionCapability] = []
    for item in run.warnings or []:
        if "capability" not in item:
            continue
        try:
            steps.append(IngestionCapability(str(item["capability"])))
        except ValueError:
            continue
    return tuple(steps) or FULL_REFRESH_ORDER


def _uuid(value: str, name: str) -> UUID:
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _lock_account(session: Session, account_id: UUID) -> None:
    raw = int.from_bytes(hashlib.sha256(account_id.bytes).digest()[:8], "big")
    key = raw if raw < 2**63 else raw - 2**64
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


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
