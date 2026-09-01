from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import trading212_api.refresh_queue as api_refresh_queue
import trading212_application.services as application_services
import trading212_worker.postgres_store as worker_postgres_store
from trading212_application.ingestion import CURRENT_REFRESH_ORDER, RunMode
from trading212_application.refresh_semantics import RefreshRequestSemantics
from trading212_persistence.refresh_semantics import (
    RefreshRequestSemantics as PersistenceRefreshRequestSemantics,
)
from trading212_security.settings import RuntimeEnvironment
from trading212_worker.outbox_dispatcher import (
    OutboxDispatcherSettings,
    RefreshDispatchMessage,
    dispatcher_dependencies_ready,
)

ROOT = Path(__file__).resolve().parents[3]


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "DATABASE_URL": "postgresql+psycopg://portfolio:portfolio@postgres/portfolio",
        "CELERY_BROKER_URL": "redis://redis:6379/0",
    }
    values.update(overrides)
    return values


def test_dispatcher_settings_are_typed_and_bounded() -> None:
    settings = OutboxDispatcherSettings.from_environment(_environment())
    assert settings.batch_size == 20
    assert settings.claim_timeout_seconds == 30
    assert settings.dispatcher_id == "dispatcher-local"
    assert settings.max_attempts == 8
    assert settings.collection_cleanup_batch_size == 100
    assert settings.metrics_host == "127.0.0.1"
    assert settings.metrics_port == 9464

    with pytest.raises(ValueError, match="batch size"):
        OutboxDispatcherSettings.from_environment(_environment(T212PI_OUTBOX_BATCH_SIZE="0"))
    with pytest.raises(ValueError, match="integer"):
        OutboxDispatcherSettings.from_environment(
            _environment(T212PI_OUTBOX_MAX_ATTEMPTS="unbounded")
        )
    with pytest.raises(ValueError, match="identity"):
        OutboxDispatcherSettings.from_environment(
            _environment(T212PI_OUTBOX_DISPATCHER_ID="contains a secret-shaped space")
        )
    with pytest.raises(ValueError, match="metrics host"):
        OutboxDispatcherSettings.from_environment(
            _environment(T212PI_OUTBOX_METRICS_HOST="dispatcher.internal")
        )
    with pytest.raises(ValueError, match="metrics port"):
        OutboxDispatcherSettings.from_environment(_environment(T212PI_OUTBOX_METRICS_PORT="80"))
    with pytest.raises(ValueError, match="collection cleanup batch size"):
        OutboxDispatcherSettings.from_environment(
            _environment(T212PI_COLLECTION_SNAPSHOT_CLEANUP_BATCH_SIZE="0")
        )
    for app_environment in ("staging", "production"):
        with pytest.raises(ValueError, match="shared Celery broker"):
            OutboxDispatcherSettings.from_environment(
                _environment(
                    T212PI_ENVIRONMENT=app_environment,
                    CELERY_BROKER_URL="memory://",
                )
            )
    deployed = OutboxDispatcherSettings.from_environment(
        _environment(T212PI_ENVIRONMENT="production")
    )
    assert deployed.app_environment is RuntimeEnvironment.PRODUCTION


def test_refresh_dispatch_metadata_is_exact_and_fixed_task_only() -> None:
    dispatch_id = uuid4()
    run_id = uuid4()
    account_id = uuid4()
    message = RefreshDispatchMessage.from_metadata(
        {
            "dispatch_id": str(dispatch_id),
            "run_id": str(run_id),
            "account_id": str(account_id),
            "request_fingerprint": "a" * 64,
            "request_schema_version": 1,
            "task_name": "portfolio.refresh",
            "task_version": 1,
        }
    )
    assert message.dispatch_id == dispatch_id
    assert message.run_id == run_id
    assert message.account_id == account_id
    assert message.task_id == str(run_id)

    with pytest.raises(ValueError, match="invalid shape"):
        RefreshDispatchMessage.from_metadata(
            {**message.kwargs(), "owner_id": "must-not-enter-the-task-payload"}
        )
    with pytest.raises(ValueError, match="unsupported contract"):
        RefreshDispatchMessage.from_metadata({**message.kwargs(), "task_name": "arbitrary.task"})


def test_refresh_request_fingerprint_is_deterministic_and_semantic() -> None:
    owner_id = uuid4()
    account_id = uuid4()
    request = RefreshRequestSemantics.create(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        capabilities=CURRENT_REFRESH_ORDER,
    )
    duplicate = RefreshRequestSemantics.create(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        capabilities=CURRENT_REFRESH_ORDER,
    )
    changed_mode = RefreshRequestSemantics.create(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=CURRENT_REFRESH_ORDER,
    )
    changed_account = RefreshRequestSemantics.create(
        owner_id=owner_id,
        account_id=uuid4(),
        mode=RunMode.INCREMENTAL,
        capabilities=CURRENT_REFRESH_ORDER,
    )

    assert request.fingerprint == duplicate.fingerprint
    assert request.fingerprint != changed_mode.fingerprint
    assert request.fingerprint != changed_account.fingerprint
    changed_owner = RefreshRequestSemantics.create(
        owner_id=uuid4(),
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        capabilities=CURRENT_REFRESH_ORDER,
    )
    changed_snapshot_behavior = RefreshRequestSemantics(
        owner_id=str(owner_id),
        account_id=str(account_id),
        mode=RunMode.INCREMENTAL,
        capabilities=CURRENT_REFRESH_ORDER,
        create_snapshot=False,
    )
    assert request.fingerprint != changed_owner.fingerprint
    assert request.fingerprint != changed_snapshot_behavior.fingerprint
    assert len(request.fingerprint) == 64


def test_refresh_request_fingerprint_authority_is_shared_by_all_adapters() -> None:
    assert vars(application_services)["RefreshRequestSemantics"] is RefreshRequestSemantics
    assert vars(api_refresh_queue)["RefreshRequestSemantics"] is RefreshRequestSemantics
    assert vars(worker_postgres_store)["RefreshRequestSemantics"] is RefreshRequestSemantics
    assert PersistenceRefreshRequestSemantics is RefreshRequestSemantics


class _Connection:
    def __init__(self, value: int) -> None:
        self.value = value

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def scalar(self, _: object) -> int:
        return self.value


class _Engine:
    def __init__(self, value: int) -> None:
        self.value = value

    def connect(self) -> _Connection:
        return _Connection(self.value)


class _Broker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.released = False

    def ensure_connection(self, **_: object) -> None:
        if self.fail:
            raise OSError("sanitized test failure")

    def release(self) -> None:
        self.released = True


class _Celery:
    def __init__(self, broker: _Broker) -> None:
        self.broker = broker

    def connection_for_write(self) -> _Broker:
        return self.broker


def test_dispatcher_health_requires_database_and_broker() -> None:
    healthy_broker = _Broker()
    assert dispatcher_dependencies_ready(
        engine=_Engine(1),
        celery=_Celery(healthy_broker),
        broker_url="redis://broker:6379/0",
    )
    assert healthy_broker.released is True

    failed_broker = _Broker(fail=True)
    assert not dispatcher_dependencies_ready(
        engine=_Engine(1),
        celery=_Celery(failed_broker),
        broker_url="redis://broker:6379/0",
    )
    assert failed_broker.released is True
    assert not dispatcher_dependencies_ready(
        engine=_Engine(1),
        celery=_Celery(_Broker()),
        broker_url="memory://",
    )


def test_compose_runs_dispatcher_as_a_separate_hardened_component() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    api = compose.split("  api:", maxsplit=1)[1].split("  worker:", maxsplit=1)[0]
    dispatcher = compose.split("  dispatcher:", maxsplit=1)[1].split("  mcp:", maxsplit=1)[0]
    assert "CELERY_BROKER_URL" not in api
    assert "redis:" not in api
    assert 'command: ["python", "-m", "trading212_worker.outbox_dispatcher"]' in dispatcher
    assert "T212PI_OUTBOX_DISPATCHER_ID: local-compose-dispatcher" in dispatcher
    assert "T212PI_OUTBOX_METRICS_HOST: 0.0.0.0" in dispatcher
    assert 'T212PI_OUTBOX_METRICS_PORT: "9464"' in dispatcher
    assert 'expose:\n      - "9464"' in dispatcher
    assert "ports:" not in dispatcher
    assert '"--healthcheck"' in dispatcher
    assert "read_only: true" in dispatcher
    assert "no-new-privileges:true" in dispatcher
    assert "cap_drop:\n      - ALL" in dispatcher
