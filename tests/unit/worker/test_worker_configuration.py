from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from celery.exceptions import Reject  # type: ignore[import-untyped]
from redis.asyncio import Redis
from sqlalchemy.exc import OperationalError
from trading212_application.ingestion import (
    IngestionCapability,
    IngestionRun,
    RateObservation,
    RunMode,
    RunStatus,
)
from trading212_provider.configuration import BrokerEnvironment
from trading212_security.secrets import EnvironmentSecretProvider
from trading212_security.settings import RuntimeEnvironment
from trading212_worker import tasks as worker_tasks
from trading212_worker.credentials import SecretReferenceCredentialProvider
from trading212_worker.outbox_dispatcher import (
    ConsumerDispatchTransition,
    RefreshDispatchMessage,
)
from trading212_worker.rate_coordinator import RedisRateCoordinator
from trading212_worker.tasks import WorkerSettings, create_celery_app


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "DATABASE_URL": "postgresql+psycopg://portfolio:portfolio@localhost/portfolio",
        "T212PI_ENVIRONMENT": "test",
        "T212PI_WORKER_PROVIDER": "synthetic",
    }
    values.update(overrides)
    return values


def test_local_worker_defaults_to_durable_database_and_eager_memory_queue() -> None:
    settings = WorkerSettings.from_environment(_environment())
    assert settings.app_environment is RuntimeEnvironment.TEST
    assert settings.eager is True
    assert settings.celery_broker_url == "memory://"
    application = create_celery_app(settings)
    assert "portfolio.refresh" in application.tasks
    assert application.conf.task_acks_late is True
    assert application.conf.task_reject_on_worker_lost is True
    assert application.conf.worker_prefetch_multiplier == 1


def test_celery_refresh_payload_is_converted_to_closed_typed_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = WorkerSettings.from_environment(_environment())
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    owner_id = "5ec35e13-018f-4670-a606-25f743976e13"
    account_id = "8daec4ea-b5ba-4a80-8ecf-0b18bd5be56c"
    captured: dict[str, Any] = {}

    async def fake_execute_refresh(
        selected_settings: WorkerSettings, **kwargs: Any
    ) -> IngestionRun:
        assert selected_settings == settings
        captured.update(kwargs)
        return IngestionRun(
            id="9fd8096d-0168-424d-9c65-6d6c18450ee0",
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.FULL,
            idempotency_key="worker-contract",
            correlation_id="worker-contract",
            status=RunStatus.SUCCEEDED,
            scheduled_at=now,
            started_at=now,
            completed_at=now,
        )

    monkeypatch.setattr(worker_tasks, "execute_refresh", fake_execute_refresh)
    application = create_celery_app(settings)
    dispatch_id = str(uuid4())
    result = application.tasks["portfolio.refresh"].apply(
        kwargs={
            "dispatch_id": dispatch_id,
            "run_id": "9fd8096d-0168-424d-9c65-6d6c18450ee0",
            "account_id": account_id,
            "request_fingerprint": "a" * 64,
            "request_schema_version": 1,
            "task_name": "portfolio.refresh",
            "task_version": 1,
        },
        task_id="9fd8096d-0168-424d-9c65-6d6c18450ee0",
    )

    assert result.get()["status"] == RunStatus.SUCCEEDED.value
    assert str(captured["message"].dispatch_id) == dispatch_id
    assert str(captured["message"].run_id) == "9fd8096d-0168-424d-9c65-6d6c18450ee0"


def test_celery_refresh_rejects_unbound_non_deterministic_task_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = WorkerSettings.from_environment(_environment())

    async def reject_unbound_delivery(*_: object, **__: object) -> IngestionRun:
        raise worker_tasks.InvalidRefreshDispatchError(
            "durable refresh dispatch does not exist",
            disposition=worker_tasks.InvalidRefreshDispatchDisposition.POISON,
        )

    monkeypatch.setattr(worker_tasks, "execute_refresh", reject_unbound_delivery)
    application = create_celery_app(settings)
    dispatch_id = str(uuid4())

    result = application.tasks["portfolio.refresh"].apply(
        kwargs={
            "dispatch_id": dispatch_id,
            "run_id": str(uuid4()),
            "account_id": str(uuid4()),
            "request_fingerprint": "a" * 64,
            "request_schema_version": 1,
            "task_name": "portfolio.refresh",
            "task_version": 1,
        },
        task_id=str(uuid4()),
        throw=False,
    )

    assert result.failed()
    assert isinstance(result.result, ValueError)
    assert "durable refresh dispatch" in str(result.result)


def test_retryable_economic_failure_defers_durably_without_celery_retry_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = WorkerSettings.from_environment(_environment())
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    account_id = "8daec4ea-b5ba-4a80-8ecf-0b18bd5be56c"
    application = create_celery_app(settings)
    refresh_task = application.tasks["portfolio.refresh"]
    observed_retry_counts: list[int] = []

    async def fake_execute_refresh(selected_settings: WorkerSettings, **_: Any) -> IngestionRun:
        assert selected_settings == settings
        observed_retry_counts.append(refresh_task.request.retries)
        raise worker_tasks.RetryableRefreshError("sanitized transient failure")

    def durable_defer(*_: object, **__: object) -> ConsumerDispatchTransition:
        return ConsumerDispatchTransition(
            run_status=RunStatus.FAILED.value,
            completed_at=now,
            deferred=True,
        )

    monkeypatch.setattr(worker_tasks, "execute_refresh", fake_execute_refresh)
    monkeypatch.setattr(
        worker_tasks,
        "defer_retryable_refresh_dispatch",
        durable_defer,
    )
    dispatch_id = str(uuid4())
    result = refresh_task.apply(
        kwargs={
            "dispatch_id": dispatch_id,
            "run_id": "9fd8096d-0168-424d-9c65-6d6c18450ee0",
            "account_id": account_id,
            "request_fingerprint": "a" * 64,
            "request_schema_version": 1,
            "task_name": "portfolio.refresh",
            "task_version": 1,
        },
        task_id="9fd8096d-0168-424d-9c65-6d6c18450ee0",
        throw=False,
    )

    assert result.successful()
    assert result.get()["status"] == RunStatus.FAILED.value
    assert result.get()["deferred"] is True
    assert observed_retry_counts == [0]


def test_terminalization_database_failure_retries_only_the_terminal_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = WorkerSettings.from_environment(_environment())
    application = create_celery_app(settings)
    application.conf.task_eager_propagates = False
    refresh_task = application.tasks["portfolio.refresh"]
    run_id = "9fd8096d-0168-424d-9c65-6d6c18450ee0"
    account_id = "8daec4ea-b5ba-4a80-8ecf-0b18bd5be56c"
    execute_calls = 0
    terminalize_calls = 0

    async def configuration_failure(*_: object, **__: object) -> IngestionRun:
        nonlocal execute_calls
        execute_calls += 1
        raise worker_tasks.RefreshConsumerConfigurationError("sanitized configuration failure")

    def eventually_terminal(*_: object, **__: object) -> ConsumerDispatchTransition:
        nonlocal terminalize_calls
        terminalize_calls += 1
        if terminalize_calls == 1:
            raise OperationalError(
                "terminalize",
                {},
                OSError("database unavailable"),
            )
        return ConsumerDispatchTransition(
            run_status=RunStatus.FAILED.value,
            completed_at=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        )

    monkeypatch.setattr(worker_tasks, "execute_refresh", configuration_failure)
    monkeypatch.setattr(worker_tasks, "terminalize_refresh_dispatch", eventually_terminal)
    result = refresh_task.apply(
        kwargs={
            "dispatch_id": str(uuid4()),
            "run_id": run_id,
            "account_id": account_id,
            "request_fingerprint": "a" * 64,
            "request_schema_version": 1,
            "task_name": "portfolio.refresh",
            "task_version": 1,
        },
        task_id=run_id,
        throw=False,
    )

    assert result.failed()
    assert isinstance(result.result, worker_tasks.RefreshConsumerTerminalError)
    assert execute_calls == 1
    assert terminalize_calls == 2


def test_retry_publication_failure_requeues_the_current_late_ack_delivery() -> None:
    run_id = uuid4()
    message = RefreshDispatchMessage.from_metadata(
        {
            "dispatch_id": str(uuid4()),
            "run_id": str(run_id),
            "account_id": str(uuid4()),
            "request_fingerprint": "a" * 64,
            "request_schema_version": 1,
            "task_name": "portfolio.refresh",
            "task_version": 1,
        }
    )

    class FailedRetryPublisher:
        request = type("Request", (), {"retries": 0})()

        def retry(self, **_: object) -> None:
            raise Reject("retry publication failed", requeue=False)

    with pytest.raises(Reject) as rejected:
        worker_tasks._retry_refresh_task(
            cast(Any, FailedRetryPublisher()),
            message=message,
            cause=RuntimeError("sanitized retry cause"),
        )

    assert rejected.value.requeue is True


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"T212PI_ENVIRONMENT": "production"}, "synthetic provider"),
        (
            {
                "T212PI_WORKER_PROVIDER": "trading212",
                "T212PI_TRADING212_ENVIRONMENT": "live",
            },
            "explicit enablement",
        ),
        (
            {
                "T212PI_WORKER_PROVIDER": "trading212",
                "T212PI_TRADING212_LIVE_ENABLED": "true",
            },
            "Demo environment",
        ),
        (
            {"T212PI_WORKER_PROVIDER": "trading212"},
            "RATE_COORDINATION_URL",
        ),
    ],
)
def test_unsafe_worker_configuration_fails_closed(overrides: dict[str, str], message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        WorkerSettings.from_environment(_environment(**overrides))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({}, "shared Celery broker"),
        (
            {
                "CELERY_BROKER_URL": "redis://broker:6379/0",
                "CELERY_RESULT_BACKEND": "cache+memory://",
            },
            "shared Celery result backend",
        ),
        (
            {
                "CELERY_BROKER_URL": "redis://broker:6379/0",
                "CELERY_RESULT_BACKEND": "redis://broker:6379/1",
                "T212PI_WORKER_EAGER": "true",
            },
            "forbids eager",
        ),
    ],
)
@pytest.mark.parametrize("app_environment", ["staging", "production"])
def test_deployed_worker_rejects_process_local_delivery(
    overrides: dict[str, str], message: str, app_environment: str
) -> None:
    environment = _environment(
        T212PI_ENVIRONMENT=app_environment,
        T212PI_WORKER_PROVIDER="trading212",
        T212PI_RATE_COORDINATION_URL="redis://coordination:6379/2",
        **overrides,
    )
    with pytest.raises(RuntimeError, match=message):
        WorkerSettings.from_environment(environment)


@pytest.mark.asyncio
async def test_secret_bundle_is_strict_and_credentials_never_repr_plaintext() -> None:
    raw = json.dumps({"api_key": "fixture-key", "api_secret": "fixture-secret"})
    secrets = EnvironmentSecretProvider(
        allowed_variables=frozenset({"T212_FIXTURE"}),
        environment={"T212_FIXTURE": raw},
    )
    adapter = SecretReferenceCredentialProvider(secrets)
    credentials = await adapter.resolve_trading212(
        credential_reference="env://T212_FIXTURE",
        environment=BrokerEnvironment.DEMO,
    )
    assert "fixture-key" not in repr(credentials)
    assert "fixture-secret" not in repr(credentials)
    assert repr(credentials) == "Trading212Credentials(environment='demo', redacted=True)"


@pytest.mark.asyncio
async def test_secret_bundle_rejects_additive_fields() -> None:
    secrets = EnvironmentSecretProvider(
        allowed_variables=frozenset({"T212_FIXTURE"}),
        environment={
            "T212_FIXTURE": json.dumps(
                {"api_key": "key", "api_secret": "secret", "path": "/unsafe"}
            )
        },
    )
    adapter = SecretReferenceCredentialProvider(secrets)
    with pytest.raises(RuntimeError, match="invalid shape"):
        await adapter.resolve_trading212(
            credential_reference="env://T212_FIXTURE",
            environment=BrokerEnvironment.DEMO,
        )


@pytest.mark.asyncio
async def test_secret_bundle_rejects_duplicate_fields_without_reconciliation() -> None:
    secrets = EnvironmentSecretProvider(
        allowed_variables=frozenset({"T212_FIXTURE"}),
        environment={
            "T212_FIXTURE": ('{"api_key":"first","api_key":"second","api_secret":"secret"}')
        },
    )
    adapter = SecretReferenceCredentialProvider(secrets)
    with pytest.raises(RuntimeError, match="invalid shape"):
        await adapter.resolve_trading212(
            credential_reference="env://T212_FIXTURE",
            environment=BrokerEnvironment.DEMO,
        )


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.closed = False

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, **_: Any) -> bool:
        self.values[key] = value
        return True

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_redis_rate_coordination_persists_hashed_endpoint_cooldown() -> None:
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    backend = MemoryRedis()
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    coordinator = RedisRateCoordinator(
        cast(Redis, backend),
        clock=lambda: now,
        sleep=record_sleep,
        max_cooldown_seconds=4,
    )
    observation = RateObservation(
        limit=1,
        period_seconds=5,
        remaining=0,
        reset_at=now + timedelta(seconds=5),
        used=1,
    )
    await coordinator.observe(
        account_id="private-account-id",
        capability=IngestionCapability.TRANSACTIONS,
        observation=observation,
    )
    await coordinator.before_read(
        account_id="private-account-id",
        capability=IngestionCapability.TRANSACTIONS,
    )
    await coordinator.aclose()

    assert delays == [4.0]
    assert len(backend.values) == 1
    assert "private-account-id" not in next(iter(backend.values))
    assert backend.closed is True
