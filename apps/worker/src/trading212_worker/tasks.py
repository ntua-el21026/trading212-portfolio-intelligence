"""Celery composition and the single bounded Phase 1 refresh task."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

from celery import Celery, Task  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from trading212_application.ingestion import (
    FailureCategory,
    IngestionCapability,
    IngestionCoordinator,
    IngestionRun,
    RunMode,
    RunStatus,
    validate_refresh_capabilities,
)
from trading212_observability import configure_logging, configure_tracing
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.models import BrokerAccountModel, BrokerConnectionModel
from trading212_provider.client import Trading212Client
from trading212_provider.configuration import BrokerEnvironment, Trading212Settings
from trading212_provider.ingestion_adapter import Trading212IngestionAdapter
from trading212_security.secrets import EnvironmentSecretProvider
from trading212_security.settings import CredentialBackend, RuntimeEnvironment, SecuritySettings

from .credentials import SecretReferenceCredentialProvider
from .materializer import PostgresCanonicalMaterializer
from .postgres_store import PostgresIngestionStore
from .rate_coordinator import RedisRateCoordinator
from .synthetic import SyntheticIngestionProvider

_RETRYABLE_CATEGORIES = {
    FailureCategory.RATE_LIMIT,
    FailureCategory.TRANSIENT,
    FailureCategory.PERSISTENCE,
    FailureCategory.INTERRUPTED,
}


class RetryableRefreshError(RuntimeError):
    """Sanitized task error that is safe to pass through Celery retry metadata."""


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    database_url: str
    app_environment: RuntimeEnvironment
    provider: str
    celery_broker_url: str
    celery_result_backend: str
    eager: bool
    trading212_environment: BrokerEnvironment
    live_enabled: bool
    rate_coordination_url: str | None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> WorkerSettings:
        values = environment if environment is not None else os.environ
        database_url = values.get("DATABASE_URL", "")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for the durable worker")
        try:
            app_environment = RuntimeEnvironment(values.get("T212PI_ENVIRONMENT", "local"))
            trading212_environment = BrokerEnvironment(
                values.get("T212PI_TRADING212_ENVIRONMENT", "demo")
            )
        except ValueError as exc:
            raise RuntimeError("worker environment configuration is invalid") from exc
        provider = values.get("T212PI_WORKER_PROVIDER", "synthetic")
        if provider not in {"synthetic", "trading212"}:
            raise RuntimeError("T212PI_WORKER_PROVIDER must be synthetic or trading212")
        if provider == "synthetic" and app_environment not in {
            RuntimeEnvironment.LOCAL,
            RuntimeEnvironment.TEST,
        }:
            raise RuntimeError("synthetic provider is restricted to local/test")
        live_enabled = values.get("T212PI_TRADING212_LIVE_ENABLED", "false").casefold() == "true"
        if trading212_environment is BrokerEnvironment.LIVE and not live_enabled:
            raise RuntimeError("Trading 212 Live requires an explicit enablement gate")
        if trading212_environment is BrokerEnvironment.DEMO and live_enabled:
            raise RuntimeError("Live enablement cannot be set for the Demo environment")
        broker_url = values.get("CELERY_BROKER_URL", "memory://")
        result_backend = values.get("CELERY_RESULT_BACKEND", "cache+memory://")
        rate_coordination_url = values.get("T212PI_RATE_COORDINATION_URL")
        if provider == "trading212":
            if not rate_coordination_url:
                raise RuntimeError("T212PI_RATE_COORDINATION_URL is required for Trading 212 reads")
            parsed_rate_url = urlsplit(rate_coordination_url)
            if (
                parsed_rate_url.scheme not in {"redis", "rediss"}
                or parsed_rate_url.hostname is None
            ):
                raise RuntimeError("Trading 212 rate coordination requires a Redis URL")
        eager_default = broker_url == "memory://"
        eager = values.get("T212PI_WORKER_EAGER", str(eager_default)).casefold() == "true"
        return cls(
            database_url=database_url,
            app_environment=app_environment,
            provider=provider,
            celery_broker_url=broker_url,
            celery_result_backend=result_backend,
            eager=eager,
            trading212_environment=trading212_environment,
            live_enabled=live_enabled,
            rate_coordination_url=rate_coordination_url,
        )


def create_celery_app(settings: WorkerSettings) -> Celery:
    application = Celery(
        "trading212_worker",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    application.conf.update(
        accept_content=["json"],
        broker_connection_retry_on_startup=False,
        enable_utc=True,
        result_accept_content=["json"],
        result_expires=3_600,
        task_acks_late=True,
        task_always_eager=settings.eager,
        task_eager_propagates=True,
        task_ignore_result=False,
        task_reject_on_worker_lost=True,
        task_serializer="json",
        result_serializer="json",
        timezone="UTC",
        worker_hijack_root_logger=False,
        worker_prefetch_multiplier=1,
    )
    _register_tasks(application, settings)
    return application


def _register_tasks(application: Celery, settings: WorkerSettings) -> None:
    @application.task(  # type: ignore[untyped-decorator]
        bind=True,
        name="portfolio.refresh",
        max_retries=3,
        autoretry_for=(OperationalError,),
        retry_backoff=True,
        retry_backoff_max=30,
        retry_jitter=True,
    )
    def refresh_portfolio(
        task: Task,
        *,
        owner_id: str,
        account_id: str,
        mode: str,
        capabilities: list[str],
        idempotency_key: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        try:
            selected_capabilities = validate_refresh_capabilities(
                tuple(IngestionCapability(value) for value in capabilities)
            )
            run = asyncio.run(
                execute_refresh(
                    settings,
                    owner_id=owner_id,
                    account_id=account_id,
                    mode=RunMode(mode),
                    capabilities=selected_capabilities,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                )
            )
        except RetryableRefreshError as exc:
            raise task.retry(exc=exc, countdown=min(2**task.request.retries, 30)) from exc
        return _task_result(run)


async def execute_refresh(
    settings: WorkerSettings,
    *,
    owner_id: str,
    account_id: str,
    mode: RunMode,
    capabilities: tuple[IngestionCapability, ...],
    idempotency_key: str,
    correlation_id: str,
) -> IngestionRun:
    _validate_uuid(owner_id, "owner_id")
    _validate_uuid(account_id, "account_id")
    if not isinstance(mode, RunMode):
        raise ValueError("only typed refresh modes are accepted")
    selected_capabilities = validate_refresh_capabilities(capabilities)
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        store = PostgresIngestionStore(
            sessions,
            provider=settings.provider,
            materializer=PostgresCanonicalMaterializer(),
        )
        if settings.provider == "synthetic":
            coordinator = IngestionCoordinator(
                provider=SyntheticIngestionProvider(),
                store=store,
            )
            run = await coordinator.refresh(
                owner_id=owner_id,
                account_id=account_id,
                mode=mode,
                capabilities=selected_capabilities,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        else:
            security = SecuritySettings()
            if security.credential_backend is CredentialBackend.EXTERNAL:
                raise RuntimeError("external secret-provider adapter is not configured")
            credential_reference = _credential_reference(sessions, owner_id, account_id)
            secret_provider = EnvironmentSecretProvider(
                allowed_variables=frozenset({"T212PI_TRADING212_CREDENTIAL_BUNDLE"})
            )
            credentials = SecretReferenceCredentialProvider(secret_provider)
            provider_settings = Trading212Settings(
                environment=settings.trading212_environment,
                live_mode_explicitly_enabled=settings.live_enabled,
            )
            if settings.rate_coordination_url is None:  # validated by composition
                raise RuntimeError("Trading 212 rate coordination is not configured")
            rate = RedisRateCoordinator.from_url(settings.rate_coordination_url)
            try:
                async with Trading212Client(
                    settings=provider_settings,
                    credential_provider=credentials,
                    credential_reference=credential_reference,
                ) as client:
                    coordinator = IngestionCoordinator(
                        provider=Trading212IngestionAdapter(client),
                        store=store,
                        rate_coordinator=rate,
                    )
                    run = await coordinator.refresh(
                        owner_id=owner_id,
                        account_id=account_id,
                        mode=mode,
                        capabilities=selected_capabilities,
                        idempotency_key=idempotency_key,
                        correlation_id=correlation_id,
                    )
            finally:
                await rate.aclose()
        if run.status in {RunStatus.FAILED, RunStatus.PARTIAL} and any(
            step.failure_category in _RETRYABLE_CATEGORIES for step in run.steps
        ):
            raise RetryableRefreshError("refresh failed with a retryable sanitized category")
        return run
    finally:
        engine.dispose()


def _credential_reference(
    sessions: Any,
    owner_id: str,
    account_id: str,
) -> str:
    with sessions() as session:
        connection = session.scalar(
            select(BrokerConnectionModel)
            .join(
                BrokerAccountModel,
                BrokerAccountModel.connection_id == BrokerConnectionModel.id,
            )
            .where(
                BrokerAccountModel.id == UUID(account_id),
                BrokerConnectionModel.owner_id == UUID(owner_id),
                BrokerConnectionModel.provider == "trading212",
            )
        )
        if connection is None:
            raise RuntimeError("authorized Trading 212 connection is unavailable")
        return cast(str, connection.credential_reference)


def _validate_uuid(value: str, name: str) -> None:
    try:
        UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def _task_result(run: IngestionRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "status": run.status.value,
        "completed_at": (
            run.completed_at.astimezone(UTC).isoformat() if run.completed_at is not None else None
        ),
        "steps": [
            {
                "capability": step.capability.value,
                "status": step.status.value,
                "records_seen": step.records_seen,
                "failure_category": (
                    step.failure_category.value if step.failure_category is not None else None
                ),
            }
            for step in run.steps
        ],
    }


def build_default_app() -> Celery:
    canary = os.environ.get("PHASE1_SECRET_CANARY")
    configure_logging(service="trading212-worker", secret_canaries=(canary,) if canary else ())
    configure_tracing(service="trading212-worker")
    return create_celery_app(WorkerSettings.from_environment())


celery_app: Celery | None = None
if os.environ.get("DATABASE_URL"):
    celery_app = build_default_app()
