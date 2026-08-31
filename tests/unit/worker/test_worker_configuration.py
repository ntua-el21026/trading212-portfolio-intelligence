from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from redis.asyncio import Redis
from trading212_application.ingestion import (
    HISTORY_REFRESH_ORDER,
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
    result = application.tasks["portfolio.refresh"].apply(
        kwargs={
            "owner_id": owner_id,
            "account_id": account_id,
            "mode": RunMode.FULL.value,
            "capabilities": [capability.value for capability in HISTORY_REFRESH_ORDER],
            "idempotency_key": "worker-contract",
            "correlation_id": "worker-contract",
        }
    )

    assert result.get()["status"] == RunStatus.SUCCEEDED.value
    assert captured["mode"] is RunMode.FULL
    assert captured["capabilities"] == HISTORY_REFRESH_ORDER


def test_celery_refresh_retries_once_after_retryable_refresh_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = WorkerSettings.from_environment(_environment())
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    owner_id = "5ec35e13-018f-4670-a606-25f743976e13"
    account_id = "8daec4ea-b5ba-4a80-8ecf-0b18bd5be56c"
    application = create_celery_app(settings)
    refresh_task = application.tasks["portfolio.refresh"]
    observed_retry_counts: list[int] = []

    async def fake_execute_refresh(selected_settings: WorkerSettings, **_: Any) -> IngestionRun:
        assert selected_settings == settings
        observed_retry_counts.append(refresh_task.request.retries)
        if len(observed_retry_counts) == 1:
            raise worker_tasks.RetryableRefreshError("sanitized transient failure")
        return IngestionRun(
            id="9fd8096d-0168-424d-9c65-6d6c18450ee0",
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.FULL,
            idempotency_key="worker-retry-contract",
            correlation_id="worker-retry-contract",
            status=RunStatus.SUCCEEDED,
            scheduled_at=now,
            started_at=now,
            completed_at=now,
        )

    monkeypatch.setattr(worker_tasks, "execute_refresh", fake_execute_refresh)
    result = refresh_task.apply(
        kwargs={
            "owner_id": owner_id,
            "account_id": account_id,
            "mode": RunMode.FULL.value,
            "capabilities": [capability.value for capability in HISTORY_REFRESH_ORDER],
            "idempotency_key": "worker-retry-contract",
            "correlation_id": "worker-retry-contract",
        },
        throw=False,
    )

    assert result.successful()
    assert result.get()["status"] == RunStatus.SUCCEEDED.value
    assert observed_retry_counts == [0, 1]


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
