"""Celery composition for fixed refresh and internal planning tasks."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Never, cast
from urllib.parse import urlsplit
from uuid import UUID

from celery import Celery, Task  # type: ignore[import-untyped]
from celery.exceptions import Reject  # type: ignore[import-untyped]
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
from trading212_application.refresh_semantics import RefreshRequestSemantics
from trading212_observability import configure_logging, configure_tracing
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    IngestionRunModel,
    RefreshDispatchOutboxModel,
)
from trading212_persistence.refresh_semantics import (
    INVALID_REFRESH_DISPATCH_ERROR_CODE,
    REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE,
)
from trading212_provider.client import Trading212Client
from trading212_provider.configuration import BrokerEnvironment, Trading212Settings
from trading212_provider.ingestion_adapter import Trading212IngestionAdapter
from trading212_security.secrets import EnvironmentSecretProvider, SecretResolutionError
from trading212_security.settings import CredentialBackend, RuntimeEnvironment, SecuritySettings

from .credentials import SecretReferenceCredentialProvider
from .materializer import PostgresCanonicalMaterializer
from .outbox_dispatcher import (
    ConsumerDispatchTransition,
    RefreshDispatchMessage,
    confirm_refresh_dispatch,
    defer_refresh_dispatch,
    defer_retryable_refresh_dispatch,
    recover_invalid_refresh_dispatch,
    terminalize_refresh_dispatch,
)
from .plan_tasks import register_planning_task
from .postgres_store import (
    ConsumerExecutionBudgetExhaustedError,
    PostgresIngestionStore,
    RunLeaseBusyError,
)
from .rate_coordinator import RedisRateCoordinator
from .synthetic import SyntheticIngestionProvider

_RETRYABLE_CATEGORIES = {
    FailureCategory.RATE_LIMIT,
    FailureCategory.TRANSIENT,
    FailureCategory.PERSISTENCE,
    FailureCategory.INTERRUPTED,
}
_EXECUTION_RETRY_LIMIT = 3
_CONSUMER_CONFIGURATION_ERROR_CODE = "refresh_consumer_configuration_failed"
_CONSUMER_EXECUTION_ERROR_CODE = REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE
_CONSUMER_PERSISTENCE_ERROR_CODE = "refresh_consumer_persistence_failed"
_TERMINAL_ERROR_CODES = frozenset(
    {
        _CONSUMER_CONFIGURATION_ERROR_CODE,
        _CONSUMER_EXECUTION_ERROR_CODE,
        _CONSUMER_PERSISTENCE_ERROR_CODE,
    }
)


class RetryableRefreshError(RuntimeError):
    """Sanitized task error that is safe to pass through Celery retry metadata."""


class RefreshConsumerConfigurationError(RuntimeError):
    """A sanitized pre-execution consumer configuration failure."""


class RefreshConsumerTerminalError(RuntimeError):
    """A consumer failure that has already reached durable terminal state."""


class InvalidRefreshDispatchDisposition(StrEnum):
    """Safe action after a task cannot bind to its durable command."""

    POISON = "poison"
    RESTORE_CANONICAL = "restore_canonical"
    TERMINALIZE_DURABLE = "terminalize_durable"


class InvalidRefreshDispatchError(ValueError):
    """A task delivery that cannot be safely bound to its durable command."""

    def __init__(
        self,
        message: str,
        *,
        disposition: InvalidRefreshDispatchDisposition,
    ) -> None:
        super().__init__(message)
        self.disposition = disposition


class DeferredRefreshError(RuntimeError):
    """A valid durable refresh was deferred behind an active account lease."""

    def __init__(self, *, run_id: UUID, transition: ConsumerDispatchTransition) -> None:
        super().__init__("refresh was durably deferred")
        self.run_id = run_id
        self.transition = transition


@dataclass(frozen=True, slots=True)
class RefreshCommand:
    owner_id: str
    account_id: str
    mode: RunMode
    capabilities: tuple[IngestionCapability, ...]
    idempotency_key: str
    correlation_id: str


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
        if app_environment in {RuntimeEnvironment.STAGING, RuntimeEnvironment.PRODUCTION}:
            if urlsplit(broker_url).scheme == "memory":
                raise RuntimeError("deployed worker requires a shared Celery broker")
            if urlsplit(result_backend).scheme.endswith("memory"):
                raise RuntimeError("deployed worker requires a shared Celery result backend")
            if eager:
                raise RuntimeError("deployed worker forbids eager Celery task execution")
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
    register_planning_task(application, database_url=settings.database_url)
    return application


def _register_tasks(application: Celery, settings: WorkerSettings) -> None:
    # Celery copies shared tasks into each app registry. Tests and embedded
    # composition may construct more than one worker app in one process, so
    # remove an earlier fixed-name binding before capturing these settings.
    application.tasks.pop("portfolio.refresh", None)

    @application.task(  # type: ignore[untyped-decorator]
        bind=True,
        name="portfolio.refresh",
        max_retries=None,
    )
    def refresh_portfolio(
        task: Task,
        *,
        dispatch_id: str,
        run_id: str,
        account_id: str,
        request_fingerprint: str,
        request_schema_version: int,
        task_name: str,
        task_version: int,
        _terminal_error_code: str | None = None,
    ) -> dict[str, Any]:
        message = RefreshDispatchMessage.from_metadata(
            {
                "dispatch_id": dispatch_id,
                "run_id": run_id,
                "account_id": account_id,
                "request_fingerprint": request_fingerprint,
                "request_schema_version": request_schema_version,
                "task_name": task_name,
                "task_version": task_version,
            }
        )
        if _terminal_error_code is not None:
            if _terminal_error_code not in _TERMINAL_ERROR_CODES:
                raise ValueError("refresh terminal error code is unsupported")
            return _terminalize_before_ack(
                task,
                settings=settings,
                message=message,
                error_code=_terminal_error_code,
            )
        try:
            run = asyncio.run(
                execute_refresh(
                    settings,
                    message=message,
                    delivered_task_id=str(task.request.id or ""),
                )
            )
        except DeferredRefreshError as exc:
            return _consumer_transition_result(exc.transition, run_id=exc.run_id)
        except OperationalError as exc:
            if task.request.retries < _EXECUTION_RETRY_LIMIT:
                _retry_refresh_task(task, message=message, cause=exc)
            return _terminalize_before_ack(
                task,
                settings=settings,
                message=message,
                error_code=_CONSUMER_PERSISTENCE_ERROR_CODE,
            )
        except RetryableRefreshError:
            return _defer_retryable_before_ack(
                task,
                settings=settings,
                message=message,
            )
        except ConsumerExecutionBudgetExhaustedError:
            return _terminalize_before_ack(
                task,
                settings=settings,
                message=message,
                error_code=_CONSUMER_EXECUTION_ERROR_CODE,
            )
        except RefreshConsumerConfigurationError:
            return _terminalize_before_ack(
                task,
                settings=settings,
                message=message,
                error_code=_CONSUMER_CONFIGURATION_ERROR_CODE,
            )
        except InvalidRefreshDispatchError as exc:
            if exc.disposition is InvalidRefreshDispatchDisposition.POISON:
                raise
            return _recover_invalid_dispatch_before_ack(
                task,
                settings=settings,
                message=message,
                restore_canonical=(
                    exc.disposition is InvalidRefreshDispatchDisposition.RESTORE_CANONICAL
                ),
            )
        except Exception:
            return _terminalize_before_ack(
                task,
                settings=settings,
                message=message,
                error_code=_CONSUMER_EXECUTION_ERROR_CODE,
            )
        return _task_result(run)


def _retry_refresh_task(
    task: Task,
    *,
    message: RefreshDispatchMessage,
    cause: BaseException,
    terminal_error_code: str | None = None,
) -> Never:
    retry_kwargs = message.kwargs()
    if terminal_error_code is not None:
        retry_kwargs["_terminal_error_code"] = terminal_error_code
    sanitized = RetryableRefreshError("refresh consumer requires a durable retry")
    try:
        retry_signal = task.retry(
            exc=sanitized,
            countdown=min(2 ** min(task.request.retries, 5), 30),
            kwargs=retry_kwargs,
            max_retries=None,
        )
    except Reject as exc:
        # Celery rejects without requeue when publishing the replacement
        # retry fails. Retain the current late-ACK delivery instead.
        if exc.requeue:
            raise
        raise Reject(exc.reason, requeue=True) from exc
    raise retry_signal from cause


def _terminalize_before_ack(
    task: Task,
    *,
    settings: WorkerSettings,
    message: RefreshDispatchMessage,
    error_code: str,
) -> dict[str, Any]:
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        try:
            transition = terminalize_refresh_dispatch(
                sessions,
                message=message,
                error_code=error_code,
            )
        except OperationalError as exc:
            _retry_refresh_task(
                task,
                message=message,
                cause=exc,
                terminal_error_code=error_code,
            )
        except ValueError:
            # A structurally valid but non-canonical delivery cannot be
            # terminalized through the strict message binding. Re-resolve the
            # durable pair and either restore its canonical payload or fail it
            # closed if the durable state itself is corrupt.
            return _recover_invalid_dispatch_before_ack(
                task,
                settings=settings,
                message=message,
                restore_canonical=True,
            )
    finally:
        engine.dispose()
    return _consumer_transition_result(
        transition,
        run_id=message.run_id,
        terminal_error_code=error_code,
    )


def _recover_invalid_dispatch_before_ack(
    task: Task,
    *,
    settings: WorkerSettings,
    message: RefreshDispatchMessage,
    restore_canonical: bool,
) -> dict[str, Any]:
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        try:
            transition = recover_invalid_refresh_dispatch(
                sessions,
                message=message,
                restore_canonical=restore_canonical,
            )
        except OperationalError as exc:
            # Re-run validation after a delayed retry. The durable database,
            # not an untrusted internal kwarg, remains the recovery authority.
            _retry_refresh_task(task, message=message, cause=exc)
        except ValueError as exc:
            raise InvalidRefreshDispatchError(
                "refresh delivery is not bound to one durable command",
                disposition=InvalidRefreshDispatchDisposition.POISON,
            ) from exc
    finally:
        engine.dispose()
    return _consumer_transition_result(
        transition,
        run_id=transition.run_id or message.run_id,
        terminal_error_code=INVALID_REFRESH_DISPATCH_ERROR_CODE,
    )


def _defer_retryable_before_ack(
    task: Task,
    *,
    settings: WorkerSettings,
    message: RefreshDispatchMessage,
) -> dict[str, Any]:
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        try:
            transition = defer_retryable_refresh_dispatch(
                sessions,
                message=message,
            )
        except OperationalError as exc:
            _retry_refresh_task(task, message=message, cause=exc)
        except ValueError:
            return _recover_invalid_dispatch_before_ack(
                task,
                settings=settings,
                message=message,
                restore_canonical=True,
            )
    finally:
        engine.dispose()
    return _consumer_transition_result(
        transition,
        run_id=message.run_id,
        terminal_error_code=_CONSUMER_EXECUTION_ERROR_CODE,
    )


def _consumer_transition_result(
    transition: ConsumerDispatchTransition,
    *,
    run_id: UUID,
    terminal_error_code: str | None = None,
) -> dict[str, Any]:
    if (
        terminal_error_code is not None
        and not transition.deferred
        and transition.run_status
        in {
            RunStatus.FAILED.value,
            RunStatus.PARTIAL.value,
            RunStatus.CANCELLED.value,
        }
    ):
        raise RefreshConsumerTerminalError(terminal_error_code)
    return {
        "run_id": str(run_id),
        "status": transition.run_status,
        "completed_at": (
            transition.completed_at.astimezone(UTC).isoformat()
            if transition.completed_at is not None
            else None
        ),
        "steps": [],
        "deferred": transition.deferred,
    }


async def execute_refresh(
    settings: WorkerSettings,
    *,
    message: RefreshDispatchMessage,
    delivered_task_id: str | None = None,
) -> IngestionRun:
    engine = create_database_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        command = _load_refresh_command(
            sessions,
            message,
            delivered_task_id=delivered_task_id or message.task_id,
        )
        store = PostgresIngestionStore(
            sessions,
            provider=settings.provider,
            materializer=PostgresCanonicalMaterializer(),
            expected_run_id=str(message.run_id),
        )
        try:
            if settings.provider == "synthetic":
                coordinator = IngestionCoordinator(
                    provider=SyntheticIngestionProvider(),
                    store=store,
                )
                run = await coordinator.refresh(
                    owner_id=command.owner_id,
                    account_id=command.account_id,
                    mode=command.mode,
                    capabilities=command.capabilities,
                    idempotency_key=command.idempotency_key,
                    correlation_id=command.correlation_id,
                )
            else:
                security = SecuritySettings()
                if security.credential_backend is CredentialBackend.EXTERNAL:
                    raise RefreshConsumerConfigurationError(
                        "external secret-provider adapter is not configured"
                    )
                credential_reference = _credential_reference(
                    sessions, command.owner_id, command.account_id
                )
                secret_provider = EnvironmentSecretProvider(
                    allowed_variables=frozenset({"T212PI_TRADING212_CREDENTIAL_BUNDLE"})
                )
                credentials = SecretReferenceCredentialProvider(secret_provider)
                provider_settings = Trading212Settings(
                    environment=settings.trading212_environment,
                    live_mode_explicitly_enabled=settings.live_enabled,
                )
                if settings.rate_coordination_url is None:  # validated by composition
                    raise RefreshConsumerConfigurationError(
                        "Trading 212 rate coordination is not configured"
                    )
                rate = RedisRateCoordinator.from_url(settings.rate_coordination_url)
                try:
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
                                owner_id=command.owner_id,
                                account_id=command.account_id,
                                mode=command.mode,
                                capabilities=command.capabilities,
                                idempotency_key=command.idempotency_key,
                                correlation_id=command.correlation_id,
                            )
                    except SecretResolutionError as exc:
                        raise RefreshConsumerConfigurationError(
                            "Trading 212 credentials are unavailable"
                        ) from exc
                finally:
                    await rate.aclose()
        except RunLeaseBusyError as exc:
            transition = defer_refresh_dispatch(
                sessions,
                message=message,
                available_at=exc.available_at,
            )
            raise DeferredRefreshError(run_id=message.run_id, transition=transition) from None
        if run.status in {RunStatus.FAILED, RunStatus.PARTIAL} and any(
            step.failure_category in _RETRYABLE_CATEGORIES for step in run.steps
        ):
            raise RetryableRefreshError("refresh failed with a retryable sanitized category")
        confirm_refresh_dispatch(
            sessions,
            message=message,
            expected_status=run.status.value,
        )
        return run
    finally:
        engine.dispose()


def _load_refresh_command(
    sessions: Any,
    message: RefreshDispatchMessage,
    *,
    delivered_task_id: str,
) -> RefreshCommand:
    with sessions.begin() as session:
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
            raise InvalidRefreshDispatchError(
                "refresh delivery identifiers bind different durable commands",
                disposition=InvalidRefreshDispatchDisposition.POISON,
            )
        binding = by_dispatch or by_run
        if binding is None:
            raise InvalidRefreshDispatchError(
                "durable refresh dispatch does not exist",
                disposition=InvalidRefreshDispatchDisposition.POISON,
            )
        canonical_dispatch_id, canonical_run_id = binding
        row = session.execute(
            select(IngestionRunModel, BrokerConnectionModel.owner_id, RefreshDispatchOutboxModel)
            .join(
                BrokerAccountModel,
                BrokerAccountModel.id == IngestionRunModel.broker_account_id,
            )
            .join(
                BrokerConnectionModel,
                BrokerConnectionModel.id == BrokerAccountModel.connection_id,
            )
            .join(
                RefreshDispatchOutboxModel,
                RefreshDispatchOutboxModel.ingestion_run_id == IngestionRunModel.id,
            )
            .where(
                IngestionRunModel.id == canonical_run_id,
                RefreshDispatchOutboxModel.id == canonical_dispatch_id,
            )
            .with_for_update(of=(IngestionRunModel, RefreshDispatchOutboxModel))
        ).one_or_none()
        if row is None:
            raise InvalidRefreshDispatchError(
                "durable refresh dispatch does not exist",
                disposition=InvalidRefreshDispatchDisposition.POISON,
            )
        run, owner_id, outbox = row
        try:
            persisted_message = RefreshDispatchMessage.from_outbox(outbox)
        except ValueError as exc:
            raise InvalidRefreshDispatchError(
                "durable refresh dispatch is invalid",
                disposition=InvalidRefreshDispatchDisposition.TERMINALIZE_DURABLE,
            ) from exc
        if (
            run.broker_account_id != persisted_message.account_id
            or run.request_fingerprint != persisted_message.request_fingerprint
            or run.request_schema_version != persisted_message.request_schema_version
        ):
            raise InvalidRefreshDispatchError(
                "durable refresh dispatch semantics do not match its run",
                disposition=InvalidRefreshDispatchDisposition.TERMINALIZE_DURABLE,
            )
        try:
            requested_capabilities = validate_refresh_capabilities(
                tuple(IngestionCapability(str(value)) for value in run.requested_capabilities)
            )
            requested_semantics = RefreshRequestSemantics(
                owner_id=str(owner_id),
                account_id=str(run.broker_account_id),
                mode=RunMode(run.requested_mode),
                capabilities=requested_capabilities,
                create_snapshot=run.requested_create_snapshot,
                schema_version=run.request_schema_version,
            )
            capabilities = validate_refresh_capabilities(
                tuple(IngestionCapability(str(value)) for value in run.effective_capabilities)
            )
            mode = RunMode(run.mode)
        except (TypeError, ValueError) as exc:
            raise InvalidRefreshDispatchError(
                "persisted refresh semantics are invalid",
                disposition=InvalidRefreshDispatchDisposition.TERMINALIZE_DURABLE,
            ) from exc
        if requested_semantics.fingerprint != run.request_fingerprint:
            raise InvalidRefreshDispatchError(
                "persisted refresh semantics do not match their fingerprint",
                disposition=InvalidRefreshDispatchDisposition.TERMINALIZE_DURABLE,
            )
        if persisted_message != message or delivered_task_id != persisted_message.task_id:
            raise InvalidRefreshDispatchError(
                "refresh delivery metadata does not match the durable dispatch",
                disposition=InvalidRefreshDispatchDisposition.RESTORE_CANONICAL,
            )
        if outbox.status == "dead" or outbox.attempt_count <= 0:
            raise InvalidRefreshDispatchError(
                "durable refresh dispatch is not deliverable",
                disposition=InvalidRefreshDispatchDisposition.POISON,
            )
        observed_at = datetime.now(UTC)
        outbox.status = "published"
        if outbox.published_at is None:
            outbox.published_at = observed_at
        outbox.available_at = observed_at
        outbox.consecutive_failure_count = 0
        outbox.last_error_code = None
        outbox.claim_token = None
        outbox.claim_owner = None
        outbox.claimed_at = None
        outbox.claim_expires_at = None
        return RefreshCommand(
            owner_id=str(owner_id),
            account_id=str(run.broker_account_id),
            mode=mode,
            capabilities=capabilities,
            idempotency_key=run.idempotency_key,
            correlation_id=run.correlation_id,
        )


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
            raise RefreshConsumerConfigurationError(
                "authorized Trading 212 connection is unavailable"
            )
        if connection.credential_reference is None:
            raise RefreshConsumerConfigurationError(
                "authorized Trading 212 credentials are unavailable"
            )
        return cast(str, connection.credential_reference)


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
