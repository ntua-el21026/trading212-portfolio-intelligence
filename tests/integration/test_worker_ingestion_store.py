from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from queue import Queue
from threading import Barrier, Event, Lock
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from celery import Celery  # type: ignore[import-untyped]
from psycopg import sql
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, OperationalError
from sqlalchemy.orm import Session
from trading212_api.refresh_queue import IdempotencyConflictError, PostgresRefreshQueue
from trading212_application.ingestion import (
    CURRENT_REFRESH_ORDER,
    FULL_REFRESH_ORDER,
    BrokerAccountDataProvider,
    Checkpoint,
    FailureCategory,
    IngestionCapability,
    IngestionCoordinator,
    IngestionFailure,
    RunMode,
    RunStatus,
    SourcePage,
    SourceRecord,
    StepResult,
)
from trading212_application.refresh_semantics import RefreshIdempotencyConflictError
from trading212_domain import build_synthetic_identity
from trading212_observability import OperationalMetrics
from trading212_persistence import (
    collection_filter_fingerprint,
    create_database_engine,
    create_session_factory,
    refresh_dispatcher_is_ready,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CashBalanceObservationModel,
    CashFlowModel,
    CollectionQuerySnapshotModel,
    DividendModel,
    IngestionCheckpointModel,
    IngestionLeaseModel,
    IngestionRunModel,
    OrderObservationModel,
    OwnerModel,
    PortfolioSnapshotModel,
    PositionObservationModel,
    RefreshDispatcherHeartbeatModel,
    RefreshDispatchOutboxModel,
    SourceRecordModel,
    TransactionModel,
)
from trading212_persistence.seed import seed_synthetic
from trading212_worker import tasks as worker_tasks
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.outbox_dispatcher import (
    DispatchCycleResult,
    OutboxDispatcherSettings,
    PostgresOutboxDispatcher,
    RefreshDispatchMessage,
    defer_refresh_dispatch,
    terminalize_refresh_dispatch,
)
from trading212_worker.postgres_store import PostgresIngestionStore, RunLeaseBusyError
from trading212_worker.synthetic import SyntheticIngestionProvider
from trading212_worker.tasks import WorkerSettings, create_celery_app

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


def _base_url() -> str:
    value = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio",
    )
    return value.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="module")
def isolated_database() -> Iterator[tuple[str, Engine]]:
    parsed = make_url(_base_url())
    database_name = f"t212pi_worker_{uuid4().hex[:12]}"
    admin = parsed.set(database="postgres")
    admin_dsn = admin.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    test_url = parsed.set(database=database_name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_url)
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    engine: Engine | None = None
    try:
        command.upgrade(config, "head")
        seed_synthetic(test_url, app_environment="test")
        engine = create_database_engine(test_url)
        yield test_url, engine
    finally:
        if engine is not None:
            engine.dispose()
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url
        if not database_name.startswith("t212pi_worker_"):
            raise RuntimeError("refusing to drop an unexpected test database")
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


class RevisionProvider(BrokerAccountDataProvider):
    def __init__(self, revision: str) -> None:
        self._revision = revision

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        del owner_id, account_id, checkpoint, correlation_id
        record = SourceRecord(
            provider_record_id="stable-provider-id",
            source_timestamp=NOW,
            observed_at=NOW,
            payload={"revision": self._revision},
            schema_version="test-v1",
        )
        return SourcePage(records=(record,), next_checkpoint=None, complete=True)


class TimestampProvider(BrokerAccountDataProvider):
    def __init__(self, source_timestamp: datetime | None) -> None:
        self._source_timestamp = source_timestamp
        self.checkpoints: list[Checkpoint | None] = []

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        del owner_id, account_id, correlation_id
        self.checkpoints.append(checkpoint)
        if self._source_timestamp is None:
            return SourcePage(records=(), next_checkpoint=None, complete=True)
        record = SourceRecord(
            provider_record_id=f"watermark-{capability.value}",
            source_timestamp=self._source_timestamp,
            observed_at=self._source_timestamp,
            payload={"sourceTimestamp": self._source_timestamp},
            schema_version="test-watermark-v1",
        )
        return SourcePage(records=(record,), next_checkpoint=None, complete=True)


def _identity() -> tuple[str, str]:
    fixture = build_synthetic_identity()
    return str(fixture.owner.id), str(fixture.account.id)


class RecordingCelery:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[tuple[str, dict[str, Any], str, dict[str, str]]] = []

    def send_task(
        self,
        name: str,
        *,
        kwargs: dict[str, Any],
        task_id: str,
        headers: dict[str, str],
    ) -> None:
        if self.fail:
            raise OSError("sanitized broker failure")
        self.messages.append((name, kwargs, task_id, headers))


class AcceptThenInterruptCelery(RecordingCelery):
    def send_task(
        self,
        name: str,
        *,
        kwargs: dict[str, Any],
        task_id: str,
        headers: dict[str, str],
    ) -> None:
        super().send_task(name, kwargs=kwargs, task_id=task_id, headers=headers)
        raise KeyboardInterrupt


class BlockingRecordingCelery(RecordingCelery):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()
        self._message_lock = Lock()

    def send_task(
        self,
        name: str,
        *,
        kwargs: dict[str, Any],
        task_id: str,
        headers: dict[str, str],
    ) -> None:
        with self._message_lock:
            self.messages.append((name, kwargs, task_id, headers))
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("test recorder was not released")


def _canonical_row_counts(engine: Engine) -> dict[str, int]:
    models = {
        "source_records": SourceRecordModel,
        "transactions": TransactionModel,
        "cash_flows": CashFlowModel,
        "dividends": DividendModel,
        "orders": OrderObservationModel,
        "positions": PositionObservationModel,
        "cash_balances": CashBalanceObservationModel,
        "snapshots": PortfolioSnapshotModel,
    }
    with Session(engine) as session:
        return {
            name: int(session.scalar(select(func.count()).select_from(model)) or 0)
            for name, model in models.items()
        }


async def _apply_refresh_task(
    application: Celery,
    *,
    metadata: dict[str, Any],
    task_id: str,
) -> Any:
    return await asyncio.to_thread(
        application.tasks["portfolio.refresh"].apply,
        kwargs=metadata,
        task_id=task_id,
        throw=False,
    )


@pytest.mark.asyncio
async def test_api_queue_persists_before_publish_and_worker_resumes_same_run(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queue = PostgresRefreshQueue(
        sessions=sessions,
        clock=lambda: NOW - timedelta(minutes=5),
    )
    queued = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        capabilities=CURRENT_REFRESH_ORDER,
        idempotency_key="api-queued-refresh",
        correlation_id="api-correlation",
    )
    duplicate = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        capabilities=CURRENT_REFRESH_ORDER,
        idempotency_key="api-queued-refresh",
        correlation_id="duplicate-correlation",
    )
    with pytest.raises(IdempotencyConflictError):
        await queue.enqueue(
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.FULL,
            capabilities=CURRENT_REFRESH_ORDER,
            idempotency_key="api-queued-refresh",
            correlation_id="conflicting-correlation",
        )
    with pytest.raises(IdempotencyConflictError):
        await queue.enqueue(
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.INCREMENTAL,
            capabilities=FULL_REFRESH_ORDER,
            idempotency_key="api-queued-refresh",
            correlation_id="conflicting-scope-correlation",
        )
    assert queued.status == RunStatus.QUEUED.value
    assert duplicate.id == queued.id
    with Session(engine) as session:
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        persisted_run = session.get(IngestionRunModel, UUID(queued.id))
        assert outbox is not None
        assert outbox.status == "pending"
        assert outbox.task_name == "portfolio.refresh"
        assert persisted_run is not None
        assert outbox.payload == {
            "run_id": queued.id,
            "account_id": account_id,
            "request_fingerprint": persisted_run.request_fingerprint,
            "request_schema_version": 1,
        }
        assert persisted_run.requested_mode == RunMode.INCREMENTAL.value
        assert persisted_run.requested_create_snapshot is True
        assert persisted_run.requested_capabilities == [
            capability.value for capability in CURRENT_REFRESH_ORDER
        ]
        assert persisted_run.mode == RunMode.FULL.value
        assert persisted_run.effective_capabilities == [
            capability.value for capability in FULL_REFRESH_ORDER
        ]
    assert queued.capabilities == tuple(capability.value for capability in FULL_REFRESH_ORDER)
    assert queued.warnings == (
        "initial synchronization promoted the request to full/all capability coverage",
    )

    completed = await IngestionCoordinator(
        provider=SyntheticIngestionProvider(clock=lambda: NOW),
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            expected_run_id=queued.id,
        ),
        clock=lambda: NOW,
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        idempotency_key="api-queued-refresh",
        correlation_id="api-correlation",
        capabilities=FULL_REFRESH_ORDER,
    )
    persisted = await queue.get(owner_id=owner_id, run_id=queued.id)
    assert completed.id == queued.id
    assert persisted.status == RunStatus.SUCCEEDED.value
    assert persisted.capabilities == tuple(capability.value for capability in FULL_REFRESH_ORDER)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(PortfolioSnapshotModel)) == 0

    pre_snapshot = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        capabilities=CURRENT_REFRESH_ORDER,
        idempotency_key="api-pre-snapshot-refresh",
        correlation_id="api-pre-snapshot-correlation",
    )
    assert pre_snapshot.capabilities == tuple(capability.value for capability in FULL_REFRESH_ORDER)

    pre_snapshot_completed = await IngestionCoordinator(
        provider=SyntheticIngestionProvider(clock=lambda: NOW + timedelta(minutes=1)),
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
            expected_run_id=pre_snapshot.id,
        ),
        clock=lambda: NOW + timedelta(minutes=1),
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key="api-pre-snapshot-refresh",
        correlation_id="api-pre-snapshot-correlation",
        capabilities=FULL_REFRESH_ORDER,
    )
    assert pre_snapshot_completed.status is RunStatus.SUCCEEDED

    current = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        capabilities=CURRENT_REFRESH_ORDER,
        idempotency_key="api-current-refresh",
        correlation_id="api-current-correlation",
    )
    assert current.capabilities == tuple(capability.value for capability in CURRENT_REFRESH_ORDER)
    assert current.warnings == ()

    current_completed = await IngestionCoordinator(
        provider=SyntheticIngestionProvider(clock=lambda: NOW + timedelta(minutes=2)),
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
            expected_run_id=current.id,
        ),
        clock=lambda: NOW + timedelta(minutes=2),
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        idempotency_key="api-current-refresh",
        correlation_id="api-current-correlation",
        capabilities=CURRENT_REFRESH_ORDER,
    )
    assert current_completed.id == current.id
    assert current_completed.status is RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_idempotency_keys_are_account_scoped(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    fixture = build_synthetic_identity()
    owner_id, first_account_id = _identity()
    second_account_id = uuid4()
    other_owner_id = uuid4()
    other_connection_id = uuid4()
    other_account_id = uuid4()
    requested_at = NOW + timedelta(hours=2, minutes=30)
    with Session(engine) as session, session.begin():
        session.add(OwnerModel(id=other_owner_id, display_name="Independent owner"))
        session.flush()
        session.add(
            BrokerConnectionModel(
                id=other_connection_id,
                owner_id=other_owner_id,
                provider="synthetic",
                environment="synthetic",
                credential_reference=f"synthetic://{other_connection_id}",
                status="active",
            )
        )
        session.flush()
        session.add_all(
            (
                BrokerAccountModel(
                    id=other_account_id,
                    connection_id=other_connection_id,
                    provider_account_id=f"synthetic-{other_account_id}",
                    account_type="invest",
                    base_currency="EUR",
                    display_name="Independent synthetic account",
                    status="active",
                    first_seen_at=requested_at,
                    last_seen_at=requested_at,
                ),
                BrokerAccountModel(
                    id=second_account_id,
                    connection_id=fixture.connection.id,
                    provider_account_id=f"synthetic-{second_account_id}",
                    account_type="invest",
                    base_currency="EUR",
                    display_name="Second synthetic account",
                    status="active",
                    first_seen_at=requested_at,
                    last_seen_at=requested_at,
                ),
            )
        )
    queue = PostgresRefreshQueue(
        sessions=sessions,
        clock=lambda: requested_at,
    )
    first = await queue.enqueue(
        owner_id=owner_id,
        account_id=first_account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="shared-account-local-key",
        correlation_id="first-account-correlation",
    )
    second = await queue.enqueue(
        owner_id=owner_id,
        account_id=str(second_account_id),
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="shared-account-local-key",
        correlation_id="second-account-correlation",
    )
    independent_owner = await queue.enqueue(
        owner_id=str(other_owner_id),
        account_id=str(other_account_id),
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="shared-account-local-key",
        correlation_id="independent-owner-correlation",
    )

    assert len({first.id, second.id, independent_owner.id}) == 3
    with Session(engine) as session, session.begin():
        runs = session.scalars(
            select(IngestionRunModel).where(
                IngestionRunModel.id.in_(
                    (UUID(first.id), UUID(second.id), UUID(independent_owner.id))
                )
            )
        ).all()
        assert len(runs) == 3
        assert len({run.request_fingerprint for run in runs}) == 3
        for run in runs:
            run.status = RunStatus.CANCELLED.value
            run.completed_at = requested_at


def test_concurrent_identical_and_mismatched_refresh_requests_are_serialized(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    requested_at = NOW + timedelta(hours=2, minutes=45)

    def submit(
        *,
        barrier: Barrier,
        mode: RunMode,
        capabilities: tuple[IngestionCapability, ...],
        key: str,
        correlation_id: str,
    ) -> tuple[str, str]:
        barrier.wait(timeout=10)
        try:
            run = asyncio.run(
                PostgresRefreshQueue(sessions=sessions, clock=lambda: requested_at).enqueue(
                    owner_id=owner_id,
                    account_id=account_id,
                    mode=mode,
                    capabilities=capabilities,
                    idempotency_key=key,
                    correlation_id=correlation_id,
                )
            )
        except IdempotencyConflictError:
            return "conflict", ""
        return "ok", run.id

    identical_barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        identical_futures = tuple(
            executor.submit(
                submit,
                barrier=identical_barrier,
                mode=RunMode.INCREMENTAL,
                capabilities=CURRENT_REFRESH_ORDER,
                key="concurrent-identical-refresh",
                correlation_id=f"concurrent-identical-{index}",
            )
            for index in range(2)
        )
        identical = tuple(future.result(timeout=20) for future in identical_futures)
    assert {status for status, _run_id in identical} == {"ok"}
    identical_run_ids = {run_id for _status, run_id in identical}
    assert len(identical_run_ids) == 1

    mismatched_barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            submit,
            barrier=mismatched_barrier,
            mode=RunMode.FULL,
            capabilities=FULL_REFRESH_ORDER,
            key="concurrent-mismatched-refresh",
            correlation_id="concurrent-mismatched-full",
        )
        second = executor.submit(
            submit,
            barrier=mismatched_barrier,
            mode=RunMode.INCREMENTAL,
            capabilities=CURRENT_REFRESH_ORDER,
            key="concurrent-mismatched-refresh",
            correlation_id="concurrent-mismatched-current",
        )
        mismatched = (first.result(timeout=20), second.result(timeout=20))
    assert sorted(status for status, _run_id in mismatched) == ["conflict", "ok"]
    successful_run_ids = identical_run_ids | {
        run_id for status, run_id in mismatched if status == "ok"
    }
    with Session(engine) as session, session.begin():
        assert (
            session.scalar(
                select(func.count())
                .select_from(RefreshDispatchOutboxModel)
                .where(
                    RefreshDispatchOutboxModel.ingestion_run_id.in_(
                        tuple(UUID(run_id) for run_id in successful_run_ids)
                    )
                )
            )
            == 2
        )
        runs = session.scalars(
            select(IngestionRunModel).where(
                IngestionRunModel.id.in_(tuple(UUID(run_id) for run_id in successful_run_ids))
            )
        )
        for run in runs:
            run.status = RunStatus.CANCELLED.value
            run.completed_at = requested_at


@pytest.mark.asyncio
async def test_dispatcher_publishes_fixed_sanitized_metadata_with_deterministic_task_id(
    isolated_database: tuple[str, Engine],
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = NOW + timedelta(hours=3)
    queue = PostgresRefreshQueue(
        sessions=sessions,
        clock=lambda: queued_at,
    )
    queued = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-deterministic-task",
        correlation_id="outbox-deterministic-task",
    )

    class InspectingCelery(RecordingCelery):
        def send_task(
            self,
            name: str,
            *,
            kwargs: dict[str, Any],
            task_id: str,
            headers: dict[str, str],
        ) -> None:
            with Session(engine) as session:
                claimed = session.scalar(
                    select(RefreshDispatchOutboxModel).where(
                        RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
                    )
                )
                assert claimed is not None
                assert claimed.status == "publishing"
                assert claimed.claim_owner == "deterministic-dispatcher"
                assert claimed.claim_token is not None
                assert claimed.claim_expires_at is not None
            super().send_task(name, kwargs=kwargs, task_id=task_id, headers=headers)

    recorder = InspectingCelery()
    dispatcher = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, recorder),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="deterministic-dispatcher",
        ),
        clock=lambda: queued_at,
    )

    result = dispatcher.dispatch_once()

    assert result.published == 1
    assert result.failed == 0
    assert len(recorder.messages) == 1
    task_name, metadata, task_id, headers = recorder.messages[0]
    assert task_name == "portfolio.refresh"
    assert metadata == {
        "dispatch_id": metadata["dispatch_id"],
        "run_id": queued.id,
        "account_id": account_id,
        "request_fingerprint": metadata["request_fingerprint"],
        "request_schema_version": 1,
        "task_name": "portfolio.refresh",
        "task_version": 1,
    }
    assert set(metadata) == {
        "dispatch_id",
        "run_id",
        "account_id",
        "request_fingerprint",
        "request_schema_version",
        "task_name",
        "task_version",
    }
    assert task_id == queued.id
    assert metadata["dispatch_id"] != task_id
    assert len(str(metadata["request_fingerprint"])) == 64
    assert headers == {
        "x-t212pi-dispatch-id": metadata["dispatch_id"],
        "x-t212pi-task-version": "1",
    }
    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    corrupt_deliveries = (
        ({**metadata, "account_id": str(uuid4())}, task_id),
        ({**metadata, "request_fingerprint": "f" * 64}, task_id),
        (metadata, str(uuid4())),
    )
    for delivered_metadata, delivered_task_id in corrupt_deliveries:
        recovered = await _apply_refresh_task(
            worker,
            metadata=delivered_metadata,
            task_id=delivered_task_id,
        )
        assert recovered.successful()
        assert recovered.get()["run_id"] == queued.id
        assert recovered.get()["status"] == RunStatus.QUEUED.value
        assert recovered.get()["deferred"] is True
        with Session(engine) as session:
            restored = session.scalar(
                select(RefreshDispatchOutboxModel).where(
                    RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
                )
            )
            assert restored is not None
            assert restored.status == "pending"
            assert restored.published_at is None
            assert restored.claim_token is None

    with Session(engine) as session:
        restored_at = session.scalar(
            select(RefreshDispatchOutboxModel.available_at).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
    assert restored_at is not None
    canonical_redelivery = RecordingCelery()
    redelivery = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, canonical_redelivery),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="canonical-recovery-dispatcher",
        ),
        clock=lambda: restored_at,
    ).dispatch_once()
    assert redelivery.published == 1
    assert len(canonical_redelivery.messages) == 1
    _task_name, restored_metadata, restored_task_id, _headers = canonical_redelivery.messages[0]
    assert restored_metadata == metadata
    assert restored_task_id == task_id

    task_result = await _apply_refresh_task(
        worker,
        metadata=restored_metadata,
        task_id=restored_task_id,
    )
    assert task_result.successful()
    assert task_result.get()["run_id"] == queued.id
    assert task_result.get()["status"] == RunStatus.SUCCEEDED.value
    with Session(engine) as session:
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert outbox is not None
        assert str(outbox.id) == metadata["dispatch_id"]
        assert outbox.status == "published"
        assert outbox.attempt_count == 2
        assert outbox.consumer_attempt_count == 1
        assert outbox.consecutive_failure_count == 0
        assert outbox.claim_owner is None
        assert outbox.last_error_code is None
        persisted_run = session.get(IngestionRunModel, UUID(queued.id))
        assert persisted_run is not None
        assert persisted_run.status == RunStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_consumer_terminalizes_internally_corrupt_durable_dispatch_without_republication(
    isolated_database: tuple[str, Engine],
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = datetime.now(UTC)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-corrupt-durable-consumer-state",
        correlation_id="outbox-corrupt-durable-consumer-state",
    )
    broker = RecordingCelery()
    PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, broker),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="corrupt-durable-consumer-state",
        ),
        clock=lambda: queued_at,
    ).dispatch_once()
    with Session(engine) as session, session.begin():
        run = session.get(IngestionRunModel, UUID(queued.id))
        assert run is not None
        run.requested_create_snapshot = False

    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    worker.conf.task_eager_propagates = False
    _task_name, metadata, task_id, _headers = broker.messages[0]
    result = await _apply_refresh_task(worker, metadata=metadata, task_id=task_id)

    assert result.failed()
    assert isinstance(result.result, worker_tasks.RefreshConsumerTerminalError)
    assert str(result.result) == "invalid_dispatch_payload"
    with Session(engine) as session:
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        run = session.get(IngestionRunModel, UUID(queued.id))
        assert outbox is not None
        assert outbox.status == "dead"
        assert outbox.published_at is None
        assert outbox.last_error_code == "invalid_dispatch_payload"
        assert run is not None
        assert run.status == RunStatus.FAILED.value
        assert run.error_code == "invalid_dispatch_payload"


@pytest.mark.asyncio
async def test_conflicting_durable_delivery_identifiers_are_poison_without_mutation(
    isolated_database: tuple[str, Engine],
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = datetime.now(UTC)
    queue = PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at)
    first = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-conflicting-delivery-first",
        correlation_id="outbox-conflicting-delivery-first",
    )
    second = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-conflicting-delivery-second",
        correlation_id="outbox-conflicting-delivery-second",
    )
    broker = RecordingCelery()
    PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, broker),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="conflicting-delivery-identifiers",
        ),
        clock=lambda: queued_at,
    ).dispatch_once()
    messages = {item[1]["run_id"]: item for item in broker.messages}
    first_message = messages[first.id]
    second_message = messages[second.id]
    conflicting = {
        **first_message[1],
        "run_id": second_message[1]["run_id"],
    }
    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    worker.conf.task_eager_propagates = False
    poison = await _apply_refresh_task(
        worker,
        metadata=conflicting,
        task_id=second.id,
    )
    assert poison.failed()
    assert isinstance(poison.result, ValueError)
    assert str(poison.result) == "refresh delivery identifiers bind different durable commands"
    with Session(engine) as session:
        outboxes = session.scalars(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id.in_((UUID(first.id), UUID(second.id)))
            )
        ).all()
        runs = session.scalars(
            select(IngestionRunModel).where(
                IngestionRunModel.id.in_((UUID(first.id), UUID(second.id)))
            )
        ).all()
        assert {row.status for row in outboxes} == {"published"}
        assert {run.status for run in runs} == {RunStatus.QUEUED.value}

    for canonical in (first_message, second_message):
        consumed = await _apply_refresh_task(
            worker,
            metadata=canonical[1],
            task_id=canonical[2],
        )
        assert consumed.successful()


@pytest.mark.asyncio
async def test_dispatcher_rejects_structurally_valid_payload_mismatched_to_durable_run(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = NOW + timedelta(hours=3, minutes=15)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-corrupted-durable-metadata",
        correlation_id="outbox-corrupted-durable-metadata",
    )
    with Session(engine) as session, session.begin():
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert outbox is not None
        outbox.payload = {
            **outbox.payload,
            "account_id": str(uuid4()),
        }

    recorder = RecordingCelery()
    metrics = OperationalMetrics(service="outbox-invalid-metadata-test")
    result = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, recorder),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="invalid-metadata-dispatcher",
        ),
        clock=lambda: queued_at,
        metrics=metrics,
    ).dispatch_once()

    assert result.claimed == 0
    assert result.published == 0
    assert result.dead == 1
    assert recorder.messages == []
    with Session(engine) as session:
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        run = session.get(IngestionRunModel, UUID(queued.id))
        heartbeat = session.scalar(
            select(RefreshDispatcherHeartbeatModel).where(
                RefreshDispatcherHeartbeatModel.dispatcher_id == "invalid-metadata-dispatcher"
            )
        )
        assert outbox is not None
        assert outbox.status == "dead"
        assert outbox.last_error_code == "invalid_dispatch_payload"
        assert run is not None
        assert run.status == RunStatus.FAILED.value
        assert run.error_code == "invalid_dispatch_payload"
        assert heartbeat is not None
        assert heartbeat.state == "degraded"
    assert "t212pi_outbox_invalid_metadata_test_ready 0.0" in metrics.render().decode()


@pytest.mark.asyncio
async def test_scenario_14_outbox_dispatcher_restart_executes_committed_run_once(
    isolated_database: tuple[str, Engine],
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = NOW + timedelta(hours=3, minutes=30)
    queue = PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at)
    before = _canonical_row_counts(engine)

    queued = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="scenario-14-outbox-restart",
        correlation_id="scenario-14-outbox-restart",
    )
    duplicate_before_publication = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="scenario-14-outbox-restart",
        correlation_id="scenario-14-duplicate-before-publication",
    )
    assert duplicate_before_publication.id == queued.id
    with Session(engine) as session:
        committed_event = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert committed_event is not None
        assert committed_event.status == "pending"
        assert committed_event.attempt_count == 0
    del queue

    settings = OutboxDispatcherSettings(
        database_url="postgresql+psycopg://unused",
        broker_url="memory://",
        dispatcher_id="scenario-14-dispatcher",
        backoff_base_seconds=1,
    )
    recorder = RecordingCelery()
    restarted_metrics = OperationalMetrics(service="scenario-14-dispatcher")
    restarted = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, recorder),
        settings=settings,
        clock=lambda: queued_at + timedelta(seconds=1),
        metrics=restarted_metrics,
    ).dispatch_once()
    assert restarted.published == 1
    assert restarted.recovered == 0
    assert len(recorder.messages) == 1
    _task_name, metadata, task_id, _headers = recorder.messages[0]
    assert task_id == queued.id

    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    first_delivery = await _apply_refresh_task(
        worker,
        metadata=metadata,
        task_id=task_id,
    )
    assert first_delivery.successful()
    assert first_delivery.get()["run_id"] == queued.id
    after_first_delivery = _canonical_row_counts(engine)
    assert after_first_delivery["source_records"] > before["source_records"]
    assert after_first_delivery["snapshots"] > before["snapshots"]
    assert (
        sum(
            after_first_delivery[name]
            for name in (
                "transactions",
                "cash_flows",
                "dividends",
                "orders",
                "positions",
                "cash_balances",
            )
        )
        > 0
    )

    duplicate_during_or_after_success = await _apply_refresh_task(
        worker,
        metadata=metadata,
        task_id=task_id,
    )
    assert duplicate_during_or_after_success.successful()
    assert duplicate_during_or_after_success.get()["run_id"] == queued.id
    duplicate_after_success = await PostgresRefreshQueue(
        sessions=sessions,
        clock=lambda: queued_at + timedelta(seconds=2),
    ).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="scenario-14-outbox-restart",
        correlation_id="scenario-14-duplicate-after-success",
    )
    assert duplicate_after_success.id == queued.id
    assert _canonical_row_counts(engine) == after_first_delivery

    terminal_cycle = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, recorder),
        settings=settings,
        clock=lambda: queued_at + timedelta(minutes=1),
        metrics=restarted_metrics,
    ).dispatch_once()
    assert terminal_cycle.claimed == 0
    assert len(recorder.messages) == 1
    rendered_metrics = restarted_metrics.render().decode()
    assert 'queue_pending_items{queue="refresh_dispatch"} 0.0' in rendered_metrics
    assert (
        'queue_delivery_attempts_total{outcome="success",queue="refresh_dispatch"} 1.0'
        in rendered_metrics
    )


@pytest.mark.asyncio
async def test_dispatcher_restart_reconciles_consumer_observed_terminal_delivery_without_redelivery(
    isolated_database: tuple[str, Engine],
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = NOW + timedelta(hours=3, minutes=45)
    queue = PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at)
    before = _canonical_row_counts(engine)
    queued = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="dispatcher-crash-after-broker-accept",
        correlation_id="dispatcher-crash-after-broker-accept",
    )
    interrupted_broker = AcceptThenInterruptCelery()
    settings = OutboxDispatcherSettings(
        database_url="postgresql+psycopg://unused",
        broker_url="memory://",
        dispatcher_id="crash-before-publish-ack",
        claim_timeout_seconds=1,
    )

    with pytest.raises(KeyboardInterrupt):
        PostgresOutboxDispatcher(
            sessions=sessions,
            celery=cast(Celery, interrupted_broker),
            settings=settings,
            clock=lambda: queued_at,
        ).dispatch_once()
    assert len(interrupted_broker.messages) == 1
    _task_name, metadata, task_id, _headers = interrupted_broker.messages[0]
    with Session(engine) as session:
        claimed = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert claimed is not None
        assert claimed.status == "publishing"
        assert claimed.attempt_count == 1
        assert claimed.published_at is None
        assert claimed.claim_owner == "crash-before-publish-ack"

    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    delivered = await _apply_refresh_task(worker, metadata=metadata, task_id=task_id)
    assert delivered.successful()
    assert delivered.get()["run_id"] == queued.id
    after_delivery = _canonical_row_counts(engine)
    assert after_delivery["source_records"] > before["source_records"]
    with Session(engine) as session:
        consumer_observed = session.scalar(
            select(RefreshDispatchOutboxModel.published_at).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        persisted_run = session.get(IngestionRunModel, UUID(queued.id))
        logical_runs = session.scalar(
            select(func.count())
            .select_from(IngestionRunModel)
            .where(
                IngestionRunModel.broker_account_id == UUID(account_id),
                IngestionRunModel.idempotency_key == "dispatcher-crash-after-broker-accept",
            )
        )
        assert consumer_observed is not None
        assert persisted_run is not None
        assert persisted_run.status == RunStatus.SUCCEEDED.value
        assert logical_runs == 1

    restarted_broker = RecordingCelery()
    restarted_metrics = OperationalMetrics(service="terminal-delivery-recovery")
    recovered = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, restarted_broker),
        settings=settings,
        clock=lambda: queued_at + timedelta(seconds=2),
        metrics=restarted_metrics,
    ).dispatch_once()
    assert recovered.claimed == 0
    assert recovered.published == 0
    assert recovered.recovered == 0
    assert recovered.dead == 0
    assert restarted_broker.messages == []
    assert _canonical_row_counts(engine) == after_delivery
    with Session(engine) as session:
        finalized = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert finalized is not None
        assert finalized.status == "published"
        assert finalized.published_at == consumer_observed
        assert finalized.claim_token is None
        assert finalized.claim_owner is None
        assert finalized.claim_expires_at is None
    rendered = restarted_metrics.render().decode()
    assert 'reason="terminal_delivery"' not in rendered
    assert 'queue_pending_items{queue="refresh_dispatch"} 0.0' in rendered


@pytest.mark.asyncio
async def test_expired_ambiguous_dispatch_republishes_same_task_before_both_copies_are_consumed(
    isolated_database: tuple[str, Engine],
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = datetime.now(UTC)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-ambiguous-two-copies",
        correlation_id="outbox-ambiguous-two-copies",
    )
    interrupted = AcceptThenInterruptCelery()
    settings = OutboxDispatcherSettings(
        database_url="postgresql+psycopg://unused",
        broker_url="memory://",
        dispatcher_id="ambiguous-two-copies",
        claim_timeout_seconds=1,
    )
    with pytest.raises(KeyboardInterrupt):
        PostgresOutboxDispatcher(
            sessions=sessions,
            celery=cast(Celery, interrupted),
            settings=settings,
            clock=lambda: queued_at,
        ).dispatch_once()
    first_message = interrupted.messages[0]

    restarted = RecordingCelery()
    recovered = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, restarted),
        settings=settings,
        clock=lambda: queued_at + timedelta(seconds=2),
    ).dispatch_once()
    assert recovered.recovered == 1
    assert recovered.published == 1
    second_message = restarted.messages[0]
    assert second_message[2] == first_message[2] == queued.id
    assert second_message[1] == first_message[1]

    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    first = await _apply_refresh_task(
        worker,
        metadata=first_message[1],
        task_id=first_message[2],
    )
    assert first.successful()
    after_first = _canonical_row_counts(engine)
    second = await _apply_refresh_task(
        worker,
        metadata=second_message[1],
        task_id=second_message[2],
    )
    assert second.successful()
    assert _canonical_row_counts(engine) == after_first
    with Session(engine) as session:
        logical_runs = session.scalar(
            select(func.count())
            .select_from(IngestionRunModel)
            .where(
                IngestionRunModel.broker_account_id == UUID(account_id),
                IngestionRunModel.idempotency_key == "outbox-ambiguous-two-copies",
            )
        )
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert logical_runs == 1
        assert outbox is not None
        assert outbox.status == "published"
        assert outbox.attempt_count == 2


@pytest.mark.asyncio
async def test_terminal_pending_cancelled_and_orphaned_runs_fail_closed_without_false_publication(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = NOW + timedelta(hours=3, minutes=50)
    queue = PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at)
    no_attempt = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="terminal-without-dispatch-attempt",
        correlation_id="terminal-without-dispatch-attempt",
    )
    cancelled = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="cancelled-after-consumer-observation",
        correlation_id="cancelled-after-consumer-observation",
    )
    orphaned = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="queued-without-deliverable-event",
        correlation_id="queued-without-deliverable-event",
    )
    proven_delivery = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="consumer-observed-then-deferred",
        correlation_id="consumer-observed-then-deferred",
    )
    observed_at = queued_at + timedelta(seconds=1)
    with Session(engine) as session, session.begin():
        no_attempt_run = session.get(IngestionRunModel, UUID(no_attempt.id))
        cancelled_run = session.get(IngestionRunModel, UUID(cancelled.id))
        cancelled_event = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(cancelled.id)
            )
        )
        proven_run = session.get(IngestionRunModel, UUID(proven_delivery.id))
        proven_event = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(proven_delivery.id)
            )
        )
        assert no_attempt_run is not None
        assert cancelled_run is not None
        assert cancelled_event is not None
        assert proven_run is not None
        assert proven_event is not None
        no_attempt_run.status = RunStatus.SUCCEEDED.value
        no_attempt_run.completed_at = observed_at
        cancelled_run.status = RunStatus.CANCELLED.value
        cancelled_run.completed_at = observed_at
        cancelled_event.status = "publishing"
        cancelled_event.attempt_count = 1
        cancelled_event.claim_token = uuid4()
        cancelled_event.claim_owner = "cancelled-dispatcher"
        cancelled_event.claimed_at = queued_at
        cancelled_event.claim_expires_at = observed_at
        proven_run.status = RunStatus.SUCCEEDED.value
        proven_run.completed_at = observed_at
        proven_event.status = "pending"
        proven_event.attempt_count = 1
        proven_event.published_at = None
        session.execute(
            delete(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(orphaned.id)
            )
        )

    metrics = OperationalMetrics(service="terminal-dispatch-anomalies")
    result = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, RecordingCelery()),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="terminal-anomaly-dispatcher",
        ),
        clock=lambda: observed_at + timedelta(seconds=1),
        metrics=metrics,
    ).dispatch_once()
    assert result.claimed == 0
    assert result.published == 0
    assert result.recovered == 1
    assert result.dead == 2
    with Session(engine) as session:
        terminal_event = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(no_attempt.id)
            )
        )
        cancelled_event = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(cancelled.id)
            )
        )
        proven_event = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(proven_delivery.id)
            )
        )
        orphaned_run = session.get(IngestionRunModel, UUID(orphaned.id))
        assert terminal_event is not None
        assert terminal_event.status == "dead"
        assert terminal_event.attempt_count == 0
        assert terminal_event.published_at is None
        assert terminal_event.last_error_code == "terminal_run_without_dispatch"
        assert cancelled_event is not None
        assert cancelled_event.status == "dead"
        assert cancelled_event.last_error_code == "refresh_dispatch_cancelled"
        assert cancelled_event.claim_owner is None
        assert cancelled_event.published_at is None
        assert proven_event is not None
        assert proven_event.status == "published"
        assert proven_event.last_error_code is None
        assert proven_event.published_at == observed_at + timedelta(seconds=1)
        assert orphaned_run is not None
        assert orphaned_run.status == RunStatus.FAILED.value
        assert orphaned_run.error_code == "queued_run_without_dispatch"
        assert orphaned_run.completed_at == observed_at + timedelta(seconds=1)
    rendered = metrics.render().decode()
    assert 'queue_runs_without_deliverable_event{queue="refresh_dispatch"} 1.0' in rendered
    assert "ready 0.0" in rendered


@pytest.mark.asyncio
async def test_two_dispatchers_contend_for_one_event_with_exactly_one_delivery_attempt(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = NOW + timedelta(hours=3, minutes=55)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="two-dispatcher-one-event-contention",
        correlation_id="two-dispatcher-one-event-contention",
    )
    recorder = BlockingRecordingCelery()
    start = Barrier(2)
    results: Queue[tuple[str, DispatchCycleResult]] = Queue()
    dispatcher_ids = ("contention-dispatcher-a", "contention-dispatcher-b")
    metrics_by_dispatcher = {
        dispatcher_id: OperationalMetrics(service=dispatcher_id) for dispatcher_id in dispatcher_ids
    }

    def run_dispatcher(dispatcher_id: str) -> None:
        start.wait(timeout=10)
        result = PostgresOutboxDispatcher(
            sessions=sessions,
            celery=cast(Celery, recorder),
            settings=OutboxDispatcherSettings(
                database_url="postgresql+psycopg://unused",
                broker_url="memory://",
                dispatcher_id=dispatcher_id,
            ),
            clock=lambda: queued_at,
            metrics=metrics_by_dispatcher[dispatcher_id],
        ).dispatch_once()
        results.put((dispatcher_id, result))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run_dispatcher, dispatcher_id) for dispatcher_id in dispatcher_ids
        ]
        claimed_by: str | None = None
        try:
            assert recorder.entered.wait(timeout=10)
            losing_dispatcher, losing_result = results.get(timeout=10)
            assert losing_result.claimed == 0
            assert losing_result.published == 0
            assert losing_result.failed == 0
            with Session(engine) as session:
                in_flight = session.scalar(
                    select(RefreshDispatchOutboxModel).where(
                        RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
                    )
                )
                assert in_flight is not None
                assert in_flight.status == "publishing"
                assert in_flight.attempt_count == 1
                assert in_flight.claim_owner in dispatcher_ids
                assert in_flight.claim_token is not None
                assert in_flight.claim_expires_at is not None
                claimed_by = in_flight.claim_owner
        finally:
            recorder.release.set()
        winning_dispatcher, winning_result = results.get(timeout=10)
        for future in futures:
            future.result(timeout=10)

    assert winning_dispatcher != losing_dispatcher
    assert winning_dispatcher == claimed_by
    cycle_results = (losing_result, winning_result)
    assert sum(result.claimed for result in cycle_results) == 1
    assert sum(result.published for result in cycle_results) == 1
    assert sum(result.failed for result in cycle_results) == 0
    assert sum(result.dead for result in cycle_results) == 0
    assert sum(result.recovered for result in cycle_results) == 0
    assert len(recorder.messages) == 1
    task_name, metadata, task_id, _headers = recorder.messages[0]
    assert task_name == "portfolio.refresh"
    assert task_id == queued.id
    assert metadata["run_id"] == queued.id

    rendered_metrics = tuple(
        metrics.render().decode() for metrics in metrics_by_dispatcher.values()
    )
    assert (
        sum(
            rendered.count(
                'queue_delivery_attempts_total{outcome="success",queue="refresh_dispatch"} 1.0'
            )
            for rendered in rendered_metrics
        )
        == 1
    )
    assert all(
        'queue_delivery_attempts_total{outcome="failure"' not in rendered
        for rendered in rendered_metrics
    )

    with Session(engine) as session, session.begin():
        events = session.scalars(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        ).all()
        assert len(events) == 1
        event = events[0]
        assert event.status == "published"
        assert event.attempt_count == 1
        assert event.published_at == queued_at
        assert event.claim_token is None
        assert event.claim_owner is None
        assert event.claimed_at is None
        assert event.claim_expires_at is None
        assert event.last_error_code is None
        heartbeat_ids = set(
            session.scalars(
                select(RefreshDispatcherHeartbeatModel.dispatcher_id).where(
                    RefreshDispatcherHeartbeatModel.dispatcher_id.in_(dispatcher_ids)
                )
            )
        )
        assert heartbeat_ids == set(dispatcher_ids)
        run = session.get(IngestionRunModel, UUID(queued.id))
        assert run is not None
        run.status = RunStatus.CANCELLED.value
        run.completed_at = queued_at
        run.heartbeat_at = queued_at


@pytest.mark.asyncio
async def test_dispatcher_reclaims_expired_claim_and_bounds_sanitized_publish_failures(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = NOW + timedelta(hours=4)
    queue = PostgresRefreshQueue(
        sessions=sessions,
        clock=lambda: queued_at,
    )
    queued = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-expired-claim",
        correlation_id="outbox-expired-claim",
    )
    with Session(engine) as session, session.begin():
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert outbox is not None
        outbox.status = "publishing"
        outbox.claim_token = uuid4()
        outbox.claim_owner = "crashed-dispatcher"
        outbox.claimed_at = queued_at - timedelta(minutes=2)
        outbox.claim_expires_at = queued_at - timedelta(minutes=1)

    failing = RecordingCelery(fail=True)
    metrics = OperationalMetrics(service="outbox-dispatcher-test")
    settings = OutboxDispatcherSettings(
        database_url="postgresql+psycopg://unused",
        broker_url="memory://",
        dispatcher_id="expired-claim-dispatcher",
        max_attempts=2,
        backoff_base_seconds=1,
        backoff_max_seconds=2,
    )
    first = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, failing),
        settings=settings,
        clock=lambda: queued_at,
        metrics=metrics,
    ).dispatch_once()
    assert first.claimed == 1
    assert first.failed == 1
    assert first.recovered == 1
    with Session(engine) as session:
        failed_once = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert failed_once is not None
        assert failed_once.attempt_count == 1
        assert failed_once.consecutive_failure_count == 1
    duplicate_after_publish_failure = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-expired-claim",
        correlation_id="outbox-expired-claim-duplicate",
    )
    assert duplicate_after_publish_failure.id == queued.id

    second = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, failing),
        settings=settings,
        clock=lambda: queued_at + timedelta(seconds=2),
        metrics=metrics,
    ).dispatch_once()
    assert second.claimed == 1
    assert second.failed == 1
    assert second.dead == 1
    with Session(engine) as session:
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert outbox is not None
        assert outbox.status == "dead"
        assert outbox.attempt_count == 2
        assert outbox.consecutive_failure_count == 2
        assert outbox.last_error_code == "broker_publish_failed"
        assert "sanitized broker failure" not in str(outbox.payload)
        run = session.get(IngestionRunModel, UUID(queued.id))
        assert run is not None
        assert run.status == RunStatus.FAILED.value
        assert run.error_code == "broker_publish_failed"
    rendered_metrics = metrics.render().decode()
    assert (
        "t212pi_outbox_dispatcher_test_queue_recoveries_total"
        '{queue="refresh_dispatch",reason="expired_claim"} 1.0' in rendered_metrics
    )
    assert (
        't212pi_outbox_dispatcher_test_queue_delivery_failures_total{queue="refresh_dispatch"} 2.0'
        in rendered_metrics
    )
    assert (
        "t212pi_outbox_dispatcher_test_queue_delivery_attempts_total"
        '{outcome="failure",queue="refresh_dispatch"} 2.0' in rendered_metrics
    )
    assert (
        "t212pi_outbox_dispatcher_test_queue_runs_without_deliverable_event"
        '{queue="refresh_dispatch"} 0.0' in rendered_metrics
    )


@pytest.mark.asyncio
async def test_expired_ambiguous_publication_starts_a_fresh_failure_budget(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    recovery_at = NOW + timedelta(hours=4, minutes=15)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: recovery_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-ambiguous-accepted-crash",
        correlation_id="outbox-ambiguous-accepted-crash",
    )
    with Session(engine) as session, session.begin():
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert outbox is not None
        outbox.status = "publishing"
        outbox.attempt_count = 3
        outbox.consecutive_failure_count = 2
        outbox.claim_token = uuid4()
        outbox.claim_owner = "accepted-before-crash"
        outbox.claimed_at = recovery_at - timedelta(minutes=2)
        outbox.claim_expires_at = recovery_at - timedelta(minutes=1)

    result = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, RecordingCelery(fail=True)),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="ambiguous-accepted-recovery",
            max_attempts=3,
            backoff_base_seconds=1,
            backoff_max_seconds=1,
        ),
        clock=lambda: recovery_at,
    ).dispatch_once()

    assert result.recovered == 1
    assert result.failed == 1
    assert result.dead == 0
    with Session(engine) as session, session.begin():
        recovered = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        run = session.get(IngestionRunModel, UUID(queued.id))
        assert recovered is not None
        assert recovered.status == "pending"
        assert recovered.attempt_count == 4
        assert recovered.consecutive_failure_count == 1
        assert recovered.last_error_code == "broker_publish_failed"
        assert run is not None
        assert run.status == RunStatus.QUEUED.value
        recovered.status = "dead"
        recovered.published_at = None
        recovered.last_error_code = "refresh_dispatch_cancelled"
        run.status = RunStatus.CANCELLED.value
        run.completed_at = recovery_at
        run.heartbeat_at = recovery_at


@pytest.mark.asyncio
async def test_max_attempt_send_error_honors_concurrent_consumer_evidence(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    attempted_at = datetime.now(UTC)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: attempted_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-accept-then-send-error",
        correlation_id="outbox-accept-then-send-error",
    )
    settings = OutboxDispatcherSettings(
        database_url="postgresql+psycopg://unused",
        broker_url="memory://",
        dispatcher_id="accept-then-error",
        max_attempts=2,
        backoff_base_seconds=1,
        backoff_max_seconds=1,
    )
    first = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, RecordingCelery(fail=True)),
        settings=settings,
        clock=lambda: attempted_at,
    ).dispatch_once()
    assert first.failed == 1
    assert first.dead == 0

    class ConsumerObservedThenError:
        def send_task(self, *_: object, **__: object) -> None:
            with sessions.begin() as session:
                outbox = session.scalar(
                    select(RefreshDispatchOutboxModel).where(
                        RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
                    )
                )
                run = session.get(IngestionRunModel, UUID(queued.id))
                assert outbox is not None
                assert run is not None
                run.status = RunStatus.RUNNING.value
                session.add(
                    IngestionLeaseModel(
                        id=uuid4(),
                        broker_account_id=UUID(account_id),
                        lease_type="refresh",
                        lease_owner="accepted-consumer",
                        fencing_token=uuid4(),
                        acquired_at=attempted_at + timedelta(seconds=1),
                        heartbeat_at=attempted_at + timedelta(seconds=1),
                        expires_at=attempted_at + timedelta(minutes=1),
                        run_id=UUID(queued.id),
                    )
                )
            raise OSError("ambiguous broker send failure")

    second = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, ConsumerObservedThenError()),
        settings=settings,
        clock=lambda: attempted_at + timedelta(seconds=1),
    ).dispatch_once()
    assert second.failed == 1
    assert second.dead == 0
    with Session(engine) as session, session.begin():
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        run = session.get(IngestionRunModel, UUID(queued.id))
        lease = session.scalar(
            select(IngestionLeaseModel).where(IngestionLeaseModel.run_id == UUID(queued.id))
        )
        assert outbox is not None
        assert outbox.status == "published"
        assert outbox.published_at == attempted_at + timedelta(seconds=1)
        assert outbox.attempt_count == 2
        assert outbox.consecutive_failure_count == 0
        assert outbox.last_error_code is None
        assert run is not None
        assert run.status == RunStatus.RUNNING.value
        run.status = RunStatus.CANCELLED.value
        run.completed_at = attempted_at + timedelta(seconds=1)
        run.heartbeat_at = attempted_at + timedelta(seconds=1)
        if lease is not None:
            session.delete(lease)


def test_dispatcher_cycles_recover_expired_collection_snapshot_storage_in_batches(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    database_now = datetime.now(UTC)
    snapshot_ids = tuple(uuid4() for _ in range(3))
    with Session(engine) as session, session.begin():
        session.add_all(
            CollectionQuerySnapshotModel(
                id=snapshot_id,
                schema_version=1,
                resource="activity",
                owner_id=UUID(owner_id),
                broker_account_id=UUID(account_id),
                source_snapshot_id=None,
                sort_specification="occurred_at_desc_id_desc",
                filter_fingerprint=collection_filter_fingerprint(
                    "dispatcher-expiry-cleanup",
                    snapshot_id,
                ),
                exact_total=0,
                created_at=database_now - timedelta(hours=2),
                expires_at=database_now - timedelta(hours=1),
            )
            for snapshot_id in snapshot_ids
        )

    dispatcher = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, RecordingCelery()),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="collection-expiry-cleanup",
            collection_cleanup_batch_size=2,
        ),
        clock=lambda: database_now,
    )
    dispatcher.dispatch_once()
    with Session(engine) as session:
        remaining_after_first = session.scalar(
            select(func.count())
            .select_from(CollectionQuerySnapshotModel)
            .where(CollectionQuerySnapshotModel.id.in_(snapshot_ids))
        )
    dispatcher.dispatch_once()
    with Session(engine) as session:
        remaining_after_second = session.scalar(
            select(func.count())
            .select_from(CollectionQuerySnapshotModel)
            .where(CollectionQuerySnapshotModel.id.in_(snapshot_ids))
        )

    assert remaining_after_first == 1
    assert remaining_after_second == 0


@pytest.mark.asyncio
async def test_confirmed_publication_is_terminal_until_worker_recovers(
    isolated_database: tuple[str, Engine],
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = NOW + timedelta(hours=4, minutes=30)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-worker-outage-single-publication",
        correlation_id="outbox-worker-outage-single-publication",
    )
    broker = RecordingCelery()
    metrics = OperationalMetrics(service="outbox-worker-outage-test")
    settings = OutboxDispatcherSettings(
        database_url="postgresql+psycopg://unused",
        broker_url="memory://",
        dispatcher_id="worker-outage-dispatcher",
    )

    initial = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, broker),
        settings=settings,
        clock=lambda: queued_at,
        metrics=metrics,
    ).dispatch_once()
    assert initial.published == 1
    assert len(broker.messages) == 1

    for offset in (1, 60, 3_600):
        cycle_at = queued_at + timedelta(seconds=offset)

        def cycle_clock(cycle_at: datetime = cycle_at) -> datetime:
            return cycle_at

        cycle = PostgresOutboxDispatcher(
            sessions=sessions,
            celery=cast(Celery, broker),
            settings=settings,
            clock=cycle_clock,
            metrics=metrics,
        ).dispatch_once()
        assert cycle.claimed == 0
        assert cycle.published == 0
        assert cycle.failed == 0
        assert cycle.dead == 0

    with Session(engine) as session:
        published = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        run = session.get(IngestionRunModel, UUID(queued.id))
        assert published is not None
        assert published.status == "published"
        assert published.published_at == queued_at
        assert published.attempt_count == 1
        assert published.consecutive_failure_count == 0
        assert run is not None
        assert run.status == RunStatus.QUEUED.value

    _task_name, metadata, task_id, _headers = broker.messages[0]
    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    consumed = await _apply_refresh_task(worker, metadata=metadata, task_id=task_id)
    assert consumed.successful()
    assert consumed.get()["run_id"] == queued.id
    assert consumed.get()["status"] == RunStatus.SUCCEEDED.value
    assert len(broker.messages) == 1
    rendered_metrics = metrics.render().decode()
    assert (
        "t212pi_outbox_worker_outage_test_queue_delivery_attempts_total"
        '{outcome="success",queue="refresh_dispatch"} 1.0' in rendered_metrics
    )


@pytest.mark.asyncio
async def test_operational_consumer_failure_exhaustion_reaches_one_durable_terminal_state(
    isolated_database: tuple[str, Engine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = datetime.now(UTC)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="consumer-operational-exhaustion",
        correlation_id="consumer-operational-exhaustion",
    )
    broker = RecordingCelery()
    PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, broker),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="consumer-operational-exhaustion",
        ),
        clock=lambda: queued_at,
    ).dispatch_once()
    calls = 0
    original_execute_refresh = worker_tasks.execute_refresh

    async def unavailable_database(*_: object, **__: object) -> Any:
        nonlocal calls
        calls += 1
        if calls == 4:
            with Session(engine) as session, session.begin():
                run = session.get(IngestionRunModel, UUID(queued.id))
                assert run is not None
                run.status = RunStatus.FAILED.value
                run.completed_at = queued_at + timedelta(seconds=4)
                run.heartbeat_at = queued_at + timedelta(seconds=4)
                run.error_code = FailureCategory.TRANSIENT.value
        raise OperationalError("refresh", {}, OSError("database unavailable"))

    monkeypatch.setattr(worker_tasks, "execute_refresh", unavailable_database)
    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    worker.conf.task_eager_propagates = False
    _task_name, metadata, task_id, _headers = broker.messages[0]
    result = await _apply_refresh_task(worker, metadata=metadata, task_id=task_id)
    assert result.failed()
    assert calls == 4
    with Session(engine) as session:
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        run = session.get(IngestionRunModel, UUID(queued.id))
        assert outbox is not None
        assert outbox.status == "dead"
        assert outbox.published_at is None
        assert outbox.last_error_code == "refresh_consumer_persistence_failed"
        assert run is not None
        assert run.status == RunStatus.FAILED.value
        assert run.error_code == "refresh_consumer_persistence_failed"
    after_exhaustion = _canonical_row_counts(engine)
    monkeypatch.setattr(worker_tasks, "execute_refresh", original_execute_refresh)
    stale_duplicate = await _apply_refresh_task(worker, metadata=metadata, task_id=task_id)
    assert stale_duplicate.failed()
    assert calls == 4
    assert _canonical_row_counts(engine) == after_exhaustion
    with Session(engine) as session:
        run = session.get(IngestionRunModel, UUID(queued.id))
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert run is not None
        assert run.status == RunStatus.FAILED.value
        assert run.error_code == "refresh_consumer_persistence_failed"
        assert outbox is not None
        assert outbox.status == "dead"


@pytest.mark.asyncio
async def test_durable_consumer_budget_fences_stale_copy_during_exhaustion_seal(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = datetime.now(UTC)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="consumer-durable-exhaustion-race",
        correlation_id="consumer-durable-exhaustion-race",
    )
    broker = RecordingCelery()
    PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, broker),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="consumer-durable-exhaustion-race",
        ),
        clock=lambda: queued_at,
    ).dispatch_once()
    _task_name, metadata, _task_id, _headers = broker.messages[0]
    message = RefreshDispatchMessage.from_metadata(metadata)
    store = PostgresIngestionStore(
        sessions,
        provider="synthetic",
        expected_run_id=queued.id,
    )
    failure = StepResult(
        capability=IngestionCapability.INSTRUMENTS,
        status=RunStatus.FAILED,
        pages=0,
        records_seen=0,
        inserted=0,
        updated=0,
        unchanged=0,
        failure_category=FailureCategory.TRANSIENT,
        failure_message="sanitized transient failure",
    )
    before = _canonical_row_counts(engine)

    for attempt in range(1, 4):
        active, lease = await store.begin_run(
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.FULL,
            capabilities=FULL_REFRESH_ORDER,
            idempotency_key="consumer-durable-exhaustion-race",
            correlation_id=f"consumer-durable-attempt-{attempt}",
            now=queued_at + timedelta(seconds=attempt),
            lease_duration=timedelta(seconds=60),
        )
        assert active.id == queued.id
        assert lease is not None
        await store.finish_run(
            run_id=queued.id,
            status=RunStatus.FAILED,
            steps=(failure,),
            lease_token=lease.token,
            now=queued_at + timedelta(seconds=attempt, milliseconds=500),
        )

    fourth, fourth_lease = await store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="consumer-durable-exhaustion-race",
        correlation_id="consumer-durable-attempt-4",
        now=queued_at + timedelta(seconds=4),
        lease_duration=timedelta(seconds=60),
    )
    assert fourth.id == queued.id
    assert fourth_lease is not None
    with pytest.raises(RunLeaseBusyError) as stale_busy:
        await PostgresIngestionStore(
            sessions,
            provider="synthetic",
            expected_run_id=queued.id,
        ).begin_run(
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.FULL,
            capabilities=FULL_REFRESH_ORDER,
            idempotency_key="consumer-durable-exhaustion-race",
            correlation_id="consumer-stale-copy",
            now=queued_at + timedelta(seconds=4, milliseconds=100),
            lease_duration=timedelta(seconds=60),
        )
    with Session(engine) as session:
        reserved = session.scalar(
            select(RefreshDispatchOutboxModel.consumer_attempt_count).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
    assert reserved == 4

    await store.finish_run(
        run_id=queued.id,
        status=RunStatus.FAILED,
        steps=(failure,),
        lease_token=fourth_lease.token,
        now=queued_at + timedelta(seconds=5),
    )
    race = Barrier(2)

    def seal_exhausted_copy() -> str:
        race.wait(timeout=10)
        return terminalize_refresh_dispatch(
            sessions,
            message=message,
            error_code="refresh_consumer_execution_failed",
        ).run_status

    def complete_paused_stale_deferral() -> str:
        race.wait(timeout=10)
        return defer_refresh_dispatch(
            sessions,
            message=message,
            available_at=stale_busy.value.available_at,
        ).run_status

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                lambda operation: operation(),
                (seal_exhausted_copy, complete_paused_stale_deferral),
            )
        )
    assert outcomes == (RunStatus.FAILED.value, RunStatus.FAILED.value)

    sealed, no_lease = await PostgresIngestionStore(
        sessions,
        provider="synthetic",
        expected_run_id=queued.id,
    ).begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="consumer-durable-exhaustion-race",
        correlation_id="consumer-stale-copy-after-seal",
        now=queued_at + timedelta(seconds=6),
        lease_duration=timedelta(seconds=60),
    )
    assert sealed.status is RunStatus.FAILED
    assert no_lease is None
    assert _canonical_row_counts(engine) == before
    with Session(engine) as session:
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        run = session.get(IngestionRunModel, UUID(queued.id))
        assert outbox is not None
        assert outbox.status == "dead"
        assert outbox.published_at is None
        assert outbox.consumer_attempt_count == 4
        assert outbox.last_error_code == "refresh_consumer_execution_failed"
        assert run is not None
        assert run.status == RunStatus.FAILED.value
        assert run.error_code == "refresh_consumer_execution_failed"


@pytest.mark.asyncio
async def test_task_path_publishes_exactly_four_retryable_executions_then_seals(
    isolated_database: tuple[str, Engine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = datetime.now(UTC)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="consumer-task-path-global-budget",
        correlation_id="consumer-task-path-global-budget",
    )

    class AlwaysTransientProvider(BrokerAccountDataProvider):
        def __init__(self) -> None:
            self.calls = 0

        async def read_page(
            self,
            *,
            owner_id: str,
            account_id: str,
            capability: IngestionCapability,
            checkpoint: Checkpoint | None,
            correlation_id: str,
        ) -> SourcePage:
            del owner_id, account_id, capability, checkpoint, correlation_id
            self.calls += 1
            raise IngestionFailure(
                FailureCategory.TRANSIENT,
                "sanitized transient provider failure",
                retryable=True,
            )

    transient_provider = AlwaysTransientProvider()
    monkeypatch.setattr(
        worker_tasks,
        "SyntheticIngestionProvider",
        lambda: transient_provider,
    )
    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    worker.conf.task_eager_propagates = False
    broker = RecordingCelery()
    before = _canonical_row_counts(engine)

    for attempt in range(1, 5):
        with Session(engine) as session:
            dispatch_at = session.scalar(
                select(RefreshDispatchOutboxModel.available_at).where(
                    RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
                )
            )
        assert dispatch_at is not None

        def dispatch_clock(value: datetime = dispatch_at) -> datetime:
            return value

        cycle = PostgresOutboxDispatcher(
            sessions=sessions,
            celery=cast(Celery, broker),
            settings=OutboxDispatcherSettings(
                database_url="postgresql+psycopg://unused",
                broker_url="memory://",
                dispatcher_id="consumer-task-path-global-budget",
            ),
            clock=dispatch_clock,
        ).dispatch_once()
        assert cycle.published == 1
        _task_name, metadata, task_id, _headers = broker.messages[-1]
        result = await _apply_refresh_task(worker, metadata=metadata, task_id=task_id)
        if attempt < 4:
            assert result.successful()
            assert result.get()["deferred"] is True
            if attempt == 1:
                with Session(engine) as session:
                    retry_available_at = session.scalar(
                        select(RefreshDispatchOutboxModel.available_at).where(
                            RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
                        )
                    )
                assert retry_available_at is not None
                corrupt = await _apply_refresh_task(
                    worker,
                    metadata={**metadata, "account_id": str(uuid4())},
                    task_id=task_id,
                )
                assert corrupt.successful()
                assert corrupt.get()["run_id"] == queued.id
                assert corrupt.get()["status"] == RunStatus.FAILED.value
                assert corrupt.get()["deferred"] is True
                assert transient_provider.calls == len(FULL_REFRESH_ORDER)
                with Session(engine) as session:
                    recovered = session.scalar(
                        select(RefreshDispatchOutboxModel).where(
                            RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
                        )
                    )
                    assert recovered is not None
                    assert recovered.status == "pending"
                    assert recovered.consumer_attempt_count == 1
                    assert recovered.published_at is None
                    assert recovered.available_at >= retry_available_at
        else:
            assert result.failed()
            assert isinstance(result.result, worker_tasks.RefreshConsumerTerminalError)
            assert str(result.result) == "refresh_consumer_execution_failed"

    assert len(broker.messages) == 4
    assert transient_provider.calls == 4 * len(FULL_REFRESH_ORDER)
    assert _canonical_row_counts(engine) == before
    exhausted_corrupt = await _apply_refresh_task(
        worker,
        metadata={**metadata, "request_fingerprint": "f" * 64},
        task_id=task_id,
    )
    assert exhausted_corrupt.failed()
    assert isinstance(exhausted_corrupt.result, worker_tasks.RefreshConsumerTerminalError)
    no_fifth = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, broker),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="consumer-task-path-global-budget",
        ),
        clock=lambda: datetime.now(UTC) + timedelta(minutes=5),
    ).dispatch_once()
    assert no_fifth.claimed == 0
    assert len(broker.messages) == 4
    with Session(engine) as session:
        outbox = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        run = session.get(IngestionRunModel, UUID(queued.id))
        assert outbox is not None
        assert outbox.status == "dead"
        assert outbox.attempt_count == 4
        assert outbox.consumer_attempt_count == 4
        assert outbox.published_at is None
        assert run is not None
        assert run.status == RunStatus.FAILED.value
        assert run.error_code == "refresh_consumer_execution_failed"


@pytest.mark.asyncio
async def test_missing_trading212_credentials_terminalize_before_any_run_lease(
    isolated_database: tuple[str, Engine],
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = datetime.now(UTC)
    queued = await PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at).enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="consumer-missing-credentials",
        correlation_id="consumer-missing-credentials",
    )
    broker = RecordingCelery()
    PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, broker),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="consumer-missing-credentials",
        ),
        clock=lambda: queued_at,
    ).dispatch_once()
    with Session(engine) as session, session.begin():
        connection = session.scalar(
            select(BrokerConnectionModel)
            .join(
                BrokerAccountModel,
                BrokerAccountModel.connection_id == BrokerConnectionModel.id,
            )
            .where(
                BrokerConnectionModel.owner_id == UUID(owner_id),
                BrokerAccountModel.id == UUID(account_id),
            )
        )
        assert connection is not None
        original_provider = connection.provider
        original_reference = connection.credential_reference
        connection.provider = "trading212"
        connection.credential_reference = None
    try:
        worker = create_celery_app(
            WorkerSettings.from_environment(
                {
                    "DATABASE_URL": database_url,
                    "CELERY_BROKER_URL": "memory://",
                    "CELERY_RESULT_BACKEND": "cache+memory://",
                    "T212PI_ENVIRONMENT": "test",
                    "T212PI_WORKER_PROVIDER": "trading212",
                    "T212PI_WORKER_EAGER": "true",
                    "T212PI_RATE_COORDINATION_URL": "redis://127.0.0.1:6379/0",
                }
            )
        )
        worker.conf.task_eager_propagates = False
        _task_name, metadata, task_id, _headers = broker.messages[0]
        result = await _apply_refresh_task(worker, metadata=metadata, task_id=task_id)
        assert result.failed()
        with Session(engine) as session:
            outbox = session.scalar(
                select(RefreshDispatchOutboxModel).where(
                    RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
                )
            )
            run = session.get(IngestionRunModel, UUID(queued.id))
            lease = session.scalar(
                select(IngestionLeaseModel).where(IngestionLeaseModel.run_id == UUID(queued.id))
            )
            assert outbox is not None
            assert outbox.status == "dead"
            assert outbox.published_at is None
            assert outbox.last_error_code == "refresh_consumer_configuration_failed"
            assert run is not None
            assert run.status == RunStatus.FAILED.value
            assert run.error_code == "refresh_consumer_configuration_failed"
            assert lease is None
    finally:
        with Session(engine) as session, session.begin():
            connection = session.scalar(
                select(BrokerConnectionModel)
                .join(
                    BrokerAccountModel,
                    BrokerAccountModel.connection_id == BrokerConnectionModel.id,
                )
                .where(
                    BrokerConnectionModel.owner_id == UUID(owner_id),
                    BrokerAccountModel.id == UUID(account_id),
                )
            )
            assert connection is not None
            connection.provider = original_provider
            connection.credential_reference = original_reference


@pytest.mark.asyncio
async def test_distinct_run_lease_deferral_reenters_bounded_pending_publication(
    isolated_database: tuple[str, Engine],
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = datetime.now(UTC)
    queue = PostgresRefreshQueue(sessions=sessions, clock=lambda: queued_at)
    active_run = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-distinct-active-run",
        correlation_id="outbox-distinct-active-run",
    )
    deferred_run = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-distinct-deferred-run",
        correlation_id="outbox-distinct-deferred-run",
    )
    recorder = RecordingCelery()
    initial = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, recorder),
        settings=OutboxDispatcherSettings(
            database_url="postgresql+psycopg://unused",
            broker_url="memory://",
            dispatcher_id="distinct-run-initial-publication",
        ),
        clock=lambda: queued_at,
    ).dispatch_once()
    assert initial.published == 2
    messages = {message[1]["run_id"]: message for message in recorder.messages}
    assert set(messages) == {active_run.id, deferred_run.id}

    persisted_active, active_lease = await PostgresIngestionStore(
        sessions,
        provider="synthetic",
        expected_run_id=active_run.id,
    ).begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-distinct-active-run",
        correlation_id="outbox-distinct-active-run",
        now=queued_at + timedelta(seconds=1),
        lease_duration=timedelta(seconds=60),
    )
    assert persisted_active.id == active_run.id
    assert active_lease is not None
    lease_expiry = queued_at + timedelta(seconds=61)

    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    _task_name, deferred_metadata, deferred_task_id, _headers = messages[deferred_run.id]
    deferred = await _apply_refresh_task(
        worker,
        metadata=deferred_metadata,
        task_id=deferred_task_id,
    )
    assert deferred.successful()
    assert deferred.get() == {
        "run_id": deferred_run.id,
        "status": RunStatus.QUEUED.value,
        "completed_at": None,
        "steps": [],
        "deferred": True,
    }
    with Session(engine) as session:
        event = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(deferred_run.id)
            )
        )
        assert event is not None
        assert event.status == "pending"
        assert event.available_at == lease_expiry
        assert event.published_at is None
        assert event.attempt_count == 1
        assert event.consecutive_failure_count == 0
        assert event.last_error_code is None

    failing_broker = RecordingCelery(fail=True)
    failure_metrics = OperationalMetrics(service="outbox-deferred-failure-budget-test")
    failure_settings = OutboxDispatcherSettings(
        database_url="postgresql+psycopg://unused",
        broker_url="memory://",
        dispatcher_id="distinct-run-deferred-publication",
        max_attempts=2,
        backoff_base_seconds=1,
        backoff_max_seconds=1,
    )
    before_expiry = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, failing_broker),
        settings=failure_settings,
        clock=lambda: lease_expiry - timedelta(seconds=1),
        metrics=failure_metrics,
    ).dispatch_once()
    assert before_expiry.claimed == 0

    first_failure = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, failing_broker),
        settings=failure_settings,
        clock=lambda: lease_expiry,
        metrics=failure_metrics,
    ).dispatch_once()
    assert first_failure.failed == 1
    assert first_failure.dead == 0
    second_failure = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, failing_broker),
        settings=failure_settings,
        clock=lambda: lease_expiry + timedelta(seconds=1),
        metrics=failure_metrics,
    ).dispatch_once()
    assert second_failure.failed == 1
    assert second_failure.dead == 1
    assert failing_broker.messages == []
    with Session(engine) as session, session.begin():
        event = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(deferred_run.id)
            )
        )
        deferred_model = session.get(IngestionRunModel, UUID(deferred_run.id))
        active_model = session.get(IngestionRunModel, UUID(active_run.id))
        lease = session.scalar(
            select(IngestionLeaseModel).where(
                IngestionLeaseModel.broker_account_id == UUID(account_id),
                IngestionLeaseModel.lease_type == "refresh",
            )
        )
        assert event is not None
        assert event.status == "dead"
        assert event.attempt_count == 3
        assert event.consecutive_failure_count == 2
        assert event.last_error_code == "broker_publish_failed"
        assert deferred_model is not None
        assert deferred_model.status == RunStatus.FAILED.value
        assert deferred_model.error_code == "broker_publish_failed"
        assert active_model is not None
        active_model.status = RunStatus.CANCELLED.value
        active_model.completed_at = lease_expiry
        active_model.heartbeat_at = lease_expiry
        if lease is not None:
            session.delete(lease)
    rendered = failure_metrics.render().decode()
    assert (
        "t212pi_outbox_deferred_failure_budget_test_queue_delivery_failures_total"
        '{queue="refresh_dispatch"} 2.0' in rendered
    )


@pytest.mark.asyncio
async def test_dispatcher_skips_locked_rows_and_recovers_after_account_lease_expiry(
    isolated_database: tuple[str, Engine],
) -> None:
    database_url, engine = isolated_database
    sessions = create_session_factory(engine)
    owner_id, account_id = _identity()
    queued_at = datetime.now(UTC)
    queue = PostgresRefreshQueue(
        sessions=sessions,
        clock=lambda: queued_at,
    )
    queued = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-lease-recovery",
        correlation_id="outbox-lease-recovery",
    )
    recorder = RecordingCelery()
    settings = OutboxDispatcherSettings(
        database_url="postgresql+psycopg://unused",
        broker_url="memory://",
    )
    first_dispatcher = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, recorder),
        settings=settings,
        clock=lambda: queued_at,
    )
    with Session(engine) as locking_session, locking_session.begin():
        locked = locking_session.scalar(
            select(RefreshDispatchOutboxModel)
            .where(RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id))
            .with_for_update()
        )
        assert locked is not None
        skipped = first_dispatcher.dispatch_once()
        assert skipped.claimed == 0

    first = first_dispatcher.dispatch_once()
    assert first.published == 1
    task_name, metadata, task_id, _headers = recorder.messages[0]
    assert task_name == "portfolio.refresh"
    with Session(engine) as session:
        first_published_at = session.scalar(
            select(RefreshDispatchOutboxModel.published_at).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
    assert first_published_at == queued_at

    lease_store = PostgresIngestionStore(
        sessions,
        provider="synthetic",
        lease_duration=timedelta(seconds=60),
        expected_run_id=queued.id,
    )
    acquired_run, acquired_lease = await lease_store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-lease-recovery",
        correlation_id="outbox-lease-recovery-active",
        now=queued_at,
        lease_duration=timedelta(seconds=60),
    )
    assert acquired_lease is not None
    assert acquired_run.id == queued.id
    duplicate_during_run = await queue.enqueue(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="outbox-lease-recovery",
        correlation_id="outbox-lease-recovery-duplicate",
    )
    assert duplicate_during_run.id == queued.id
    with pytest.raises(RunLeaseBusyError) as overlap:
        await PostgresIngestionStore(
            sessions,
            provider="synthetic",
            expected_run_id=queued.id,
        ).begin_run(
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.FULL,
            capabilities=FULL_REFRESH_ORDER,
            idempotency_key="outbox-lease-recovery",
            correlation_id="overlapping-broker-redelivery",
            now=queued_at + timedelta(seconds=1),
            lease_duration=timedelta(seconds=60),
        )
    assert overlap.value.available_at == queued_at + timedelta(seconds=60)
    worker = create_celery_app(
        WorkerSettings.from_environment(
            {
                "DATABASE_URL": database_url,
                "CELERY_BROKER_URL": "memory://",
                "CELERY_RESULT_BACKEND": "cache+memory://",
                "T212PI_ENVIRONMENT": "test",
                "T212PI_WORKER_PROVIDER": "synthetic",
                "T212PI_WORKER_EAGER": "true",
            }
        )
    )
    overlapping_delivery = await _apply_refresh_task(
        worker,
        metadata=metadata,
        task_id=task_id,
    )
    assert overlapping_delivery.successful()
    assert overlapping_delivery.get()["run_id"] == queued.id
    assert overlapping_delivery.get()["status"] == RunStatus.RUNNING.value
    assert overlapping_delivery.get()["deferred"] is True
    with Session(engine) as session:
        still_deliverable = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert still_deliverable is not None
        assert still_deliverable.status == "pending"
        assert still_deliverable.published_at is None
        assert still_deliverable.available_at == queued_at + timedelta(seconds=60)
        live_lease = session.scalar(
            select(IngestionLeaseModel).where(IngestionLeaseModel.run_id == UUID(queued.id))
        )
        assert live_lease is not None

    active_lease = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, recorder),
        settings=settings,
        clock=lambda: queued_at + timedelta(seconds=30),
    ).dispatch_once()
    assert active_lease.claimed == 0

    recovered = PostgresOutboxDispatcher(
        sessions=sessions,
        celery=cast(Celery, recorder),
        settings=settings,
        clock=lambda: queued_at + timedelta(seconds=61),
    ).dispatch_once()
    assert recovered.published == 1
    assert len(recorder.messages) == 2
    assert recorder.messages[1][2] == task_id
    assert recorder.messages[1][1] == metadata
    with Session(engine) as session:
        redelivered = session.scalar(
            select(RefreshDispatchOutboxModel).where(
                RefreshDispatchOutboxModel.ingestion_run_id == UUID(queued.id)
            )
        )
        assert redelivered is not None
        assert redelivered.published_at == queued_at + timedelta(seconds=61)
        assert redelivered.attempt_count == 2

    with Session(engine) as session, session.begin():
        live_lease = session.scalar(
            select(IngestionLeaseModel).where(IngestionLeaseModel.run_id == UUID(queued.id))
        )
        assert live_lease is not None
        live_lease.expires_at = live_lease.acquired_at + timedelta(microseconds=1)

    task_result = await _apply_refresh_task(
        worker,
        metadata=metadata,
        task_id=task_id,
    )
    assert task_result.successful()
    assert task_result.get()["run_id"] == queued.id
    assert task_result.get()["status"] == RunStatus.SUCCEEDED.value
    assert refresh_dispatcher_is_ready(
        sessions,
        now=queued_at + timedelta(seconds=62),
        max_age=timedelta(seconds=30),
    )
    assert not refresh_dispatcher_is_ready(
        sessions,
        now=queued_at + timedelta(minutes=10),
        max_age=timedelta(seconds=30),
    )

    concurrent_at = queued_at + timedelta(seconds=64)

    def run_empty_cycle(dispatcher_id: str) -> int:
        result = PostgresOutboxDispatcher(
            sessions=sessions,
            celery=cast(Celery, RecordingCelery()),
            settings=OutboxDispatcherSettings(
                database_url="postgresql+psycopg://unused",
                broker_url="memory://",
                dispatcher_id=dispatcher_id,
            ),
            clock=lambda: concurrent_at,
        ).dispatch_once()
        return result.claimed

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed_counts = tuple(
            executor.map(run_empty_cycle, ("dispatcher-concurrent-a", "dispatcher-concurrent-b"))
        )
    assert claimed_counts == (0, 0)
    with Session(engine) as session:
        identities = set(
            session.scalars(
                select(RefreshDispatcherHeartbeatModel.dispatcher_id).where(
                    RefreshDispatcherHeartbeatModel.dispatcher_id.in_(
                        ("dispatcher-concurrent-a", "dispatcher-concurrent-b")
                    )
                )
            )
        )
    assert identities == {"dispatcher-concurrent-a", "dispatcher-concurrent-b"}


@pytest.mark.asyncio
async def test_postgres_refresh_is_coalesced_idempotent_and_retains_revisions(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    store = PostgresIngestionStore(sessions, provider="synthetic")
    owner_id, account_id = _identity()
    with Session(engine) as session:
        initial_count = session.scalar(select(func.count()).select_from(SourceRecordModel)) or 0

    first = await IngestionCoordinator(
        provider=RevisionProvider("v1"), store=store, clock=lambda: NOW
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        idempotency_key="revision-1",
        correlation_id="correlation-1",
        capabilities=(IngestionCapability.ACCOUNT,),
    )
    duplicate = await IngestionCoordinator(
        provider=RevisionProvider("must-not-run"), store=store, clock=lambda: NOW
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        idempotency_key="revision-1",
        correlation_id="correlation-duplicate",
        capabilities=(IngestionCapability.ACCOUNT,),
    )
    updated = await IngestionCoordinator(
        provider=RevisionProvider("v2"),
        store=store,
        clock=lambda: NOW + timedelta(minutes=1),
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        idempotency_key="revision-2",
        correlation_id="correlation-2",
        capabilities=(IngestionCapability.ACCOUNT,),
    )

    assert first.status is RunStatus.SUCCEEDED
    assert duplicate.id == first.id
    assert updated.steps[0].updated == 1
    with Session(engine) as session:
        assert (
            session.scalar(select(func.count()).select_from(SourceRecordModel)) == initial_count + 2
        )
        checkpoint = session.scalar(select(IngestionCheckpointModel))
        assert checkpoint is not None
        assert checkpoint.coverage_complete is True


@pytest.mark.asyncio
async def test_postgres_completed_watermark_is_monotonic_and_mode_aware(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    store = PostgresIngestionStore(sessions, provider="synthetic")
    owner_id, account_id = _identity()
    high_water = NOW + timedelta(days=365)

    baseline_provider = TimestampProvider(high_water)
    baseline = await IngestionCoordinator(
        provider=baseline_provider,
        store=store,
        clock=lambda: high_water,
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key="watermark-postgres-full",
        correlation_id="watermark-postgres-full",
        capabilities=(IngestionCapability.TRANSACTIONS,),
    )
    assert baseline.status is RunStatus.SUCCEEDED

    overlap = timedelta(days=7)
    incremental_checkpoint = await store.get_checkpoint(
        account_id=account_id,
        capability=IngestionCapability.TRANSACTIONS,
        mode=RunMode.INCREMENTAL,
        overlap_window=overlap,
    )
    assert incremental_checkpoint == Checkpoint(
        source_timestamp=high_water,
        overlap_started_at=high_water - overlap,
    )
    assert (
        await store.get_checkpoint(
            account_id=account_id,
            capability=IngestionCapability.TRANSACTIONS,
            mode=RunMode.FULL,
            overlap_window=overlap,
        )
        is None
    )

    empty_provider = TimestampProvider(None)
    empty = await IngestionCoordinator(
        provider=empty_provider,
        store=store,
        clock=lambda: high_water + timedelta(minutes=1),
    ).refresh(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        idempotency_key="watermark-postgres-empty",
        correlation_id="watermark-postgres-empty",
        capabilities=(IngestionCapability.TRANSACTIONS,),
    )
    assert empty.status is RunStatus.SUCCEEDED
    assert empty_provider.checkpoints == [incremental_checkpoint]
    assert (
        await store.get_checkpoint(
            account_id=account_id,
            capability=IngestionCapability.TRANSACTIONS,
            mode=RunMode.INCREMENTAL,
            overlap_window=overlap,
        )
        == incremental_checkpoint
    )
    assert (
        await store.get_checkpoint(
            account_id=account_id,
            capability=IngestionCapability.DIVIDENDS,
            mode=RunMode.INCREMENTAL,
            overlap_window=overlap,
        )
        is None
    )


@pytest.mark.asyncio
async def test_account_lease_coalesces_distinct_concurrent_refresh_keys(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    store = PostgresIngestionStore(create_session_factory(engine), provider="synthetic")
    owner_id, account_id = _identity()
    first, first_lease = await store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="active-a",
        correlation_id="active-a",
        now=NOW + timedelta(hours=1),
        lease_duration=timedelta(minutes=5),
    )
    coalesced, second_lease = await store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="active-b",
        correlation_id="active-b",
        now=NOW + timedelta(hours=1, seconds=1),
        lease_duration=timedelta(minutes=5),
    )
    assert first_lease is not None
    with pytest.raises(RefreshIdempotencyConflictError):
        await store.begin_run(
            owner_id=owner_id,
            account_id=account_id,
            mode=RunMode.INCREMENTAL,
            capabilities=FULL_REFRESH_ORDER,
            idempotency_key="active-a",
            correlation_id="active-a-conflict",
            now=NOW + timedelta(hours=1, milliseconds=500),
            lease_duration=timedelta(minutes=5),
        )
    assert second_lease is None
    assert coalesced.id == first.id
    await store.finish_run(
        run_id=first.id,
        status=RunStatus.CANCELLED,
        steps=(),
        lease_token=first_lease.token,
        now=NOW + timedelta(hours=1, seconds=2),
    )


@pytest.mark.asyncio
async def test_expired_lease_takeover_fences_every_stale_worker_mutation(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    store = PostgresIngestionStore(sessions, provider="synthetic")
    owner_id, account_id = _identity()
    started_at = NOW + timedelta(hours=1, minutes=15)
    first, first_lease = await store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="fenced-lease-takeover",
        correlation_id="fenced-lease-first",
        now=started_at,
        lease_duration=timedelta(seconds=1),
    )
    assert first_lease is not None
    takeover_at = started_at + timedelta(seconds=2)
    second, second_lease = await store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="fenced-lease-takeover",
        correlation_id="fenced-lease-second",
        now=takeover_at,
        lease_duration=timedelta(seconds=1),
    )
    assert second.id == first.id
    assert second_lease is not None
    assert second_lease.token != first_lease.token
    page = SourcePage(records=(), next_checkpoint=None, complete=True)

    with pytest.raises(IngestionFailure, match="lease is no longer active"):
        await store.commit_page(
            run_id=first.id,
            account_id=account_id,
            capability=IngestionCapability.ACCOUNT,
            page=page,
            lease_token=first_lease.token,
            now=takeover_at + timedelta(milliseconds=100),
        )
    with pytest.raises(IngestionFailure, match="lease is no longer active"):
        await store.heartbeat(
            run_id=first.id,
            lease_token=first_lease.token,
            now=takeover_at + timedelta(milliseconds=100),
        )
    with pytest.raises(IngestionFailure, match="lease is no longer active"):
        await store.finish_run(
            run_id=first.id,
            status=RunStatus.FAILED,
            steps=(),
            lease_token=first_lease.token,
            now=takeover_at + timedelta(milliseconds=100),
        )

    await store.commit_page(
        run_id=second.id,
        account_id=account_id,
        capability=IngestionCapability.ACCOUNT,
        page=page,
        lease_token=second_lease.token,
        now=takeover_at + timedelta(milliseconds=200),
    )
    completed = await store.finish_run(
        run_id=second.id,
        status=RunStatus.SUCCEEDED,
        steps=(),
        lease_token=second_lease.token,
        now=takeover_at + timedelta(milliseconds=300),
    )
    assert completed.status is RunStatus.SUCCEEDED
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionRunModel)
                .where(IngestionRunModel.id == UUID(first.id))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionLeaseModel)
                .where(IngestionLeaseModel.run_id == UUID(first.id))
            )
            == 0
        )


@pytest.mark.asyncio
async def test_failed_page_transaction_does_not_advance_checkpoint(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    store = PostgresIngestionStore(create_session_factory(engine), provider="synthetic")
    owner_id, account_id = _identity()
    with Session(engine) as session:
        prior_checkpoint = session.scalar(
            select(IngestionCheckpointModel).where(
                IngestionCheckpointModel.capability == IngestionCapability.POSITIONS.value
            )
        )
        checkpoint_before = (
            None
            if prior_checkpoint is None
            else (
                prior_checkpoint.id,
                prior_checkpoint.version,
                prior_checkpoint.advanced_by_run_id,
                prior_checkpoint.updated_at,
            )
        )
    run, lease = await store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        capabilities=FULL_REFRESH_ORDER,
        idempotency_key="atomic-failure",
        correlation_id="atomic-failure",
        now=NOW + timedelta(hours=2),
        lease_duration=timedelta(minutes=5),
    )
    assert lease is not None
    invalid_record = SourceRecord(
        provider_record_id="x" * 300,
        source_timestamp=NOW,
        observed_at=NOW,
        payload={"valid": True},
        schema_version="test-v1",
    )
    with pytest.raises(DataError):
        await store.commit_page(
            run_id=run.id,
            account_id=account_id,
            capability=IngestionCapability.POSITIONS,
            page=SourcePage(records=(invalid_record,), next_checkpoint=None, complete=True),
            lease_token=lease.token,
            now=NOW + timedelta(hours=2),
        )
    with Session(engine) as session:
        checkpoint = session.scalar(
            select(IngestionCheckpointModel).where(
                IngestionCheckpointModel.capability == IngestionCapability.POSITIONS.value
            )
        )
        failed_record = session.scalar(
            select(SourceRecordModel).where(SourceRecordModel.provider_record_id == "x" * 300)
        )
        checkpoint_after = (
            None
            if checkpoint is None
            else (
                checkpoint.id,
                checkpoint.version,
                checkpoint.advanced_by_run_id,
                checkpoint.updated_at,
            )
        )
        assert checkpoint_after == checkpoint_before
        assert failed_record is None
    await store.finish_run(
        run_id=run.id,
        status=RunStatus.CANCELLED,
        steps=(),
        lease_token=lease.token,
        now=NOW + timedelta(hours=2, seconds=1),
    )
