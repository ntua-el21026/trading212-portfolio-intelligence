from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from celery import Celery  # type: ignore[import-untyped]
from psycopg import sql
from sqlalchemy import Engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session
from trading212_api.refresh_queue import PostgresRefreshQueue
from trading212_application.ingestion import (
    CURRENT_REFRESH_ORDER,
    FULL_REFRESH_ORDER,
    BrokerAccountDataProvider,
    Checkpoint,
    IngestionCapability,
    IngestionCoordinator,
    RunMode,
    RunStatus,
    SourcePage,
    SourceRecord,
)
from trading212_domain import build_synthetic_identity
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.models import (
    IngestionCheckpointModel,
    PortfolioSnapshotModel,
    SourceRecordModel,
)
from trading212_persistence.seed import seed_synthetic
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.synthetic import SyntheticIngestionProvider

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
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, Any]]] = []

    def send_task(self, name: str, *, kwargs: dict[str, Any]) -> None:
        self.messages.append((name, kwargs))


@pytest.mark.asyncio
async def test_api_queue_persists_before_publish_and_worker_resumes_same_run(
    isolated_database: tuple[str, Engine],
) -> None:
    _, engine = isolated_database
    sessions = create_session_factory(engine)
    recorder = RecordingCelery()
    owner_id, account_id = _identity()
    queue = PostgresRefreshQueue(
        sessions=sessions,
        celery=cast(Celery, recorder),
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
    assert queued.status == RunStatus.QUEUED.value
    assert duplicate.id == queued.id
    assert len(recorder.messages) == 1
    task_name, payload = recorder.messages[0]
    assert task_name == "portfolio.refresh"
    assert not any("secret" in key or "credential" in key for key in payload)
    assert payload["mode"] == RunMode.FULL.value
    assert payload["capabilities"] == [capability.value for capability in FULL_REFRESH_ORDER]
    assert queued.capabilities == tuple(capability.value for capability in FULL_REFRESH_ORDER)
    assert queued.warnings == (
        "initial synchronization promoted the request to full/all capability coverage",
    )

    completed = await IngestionCoordinator(
        provider=SyntheticIngestionProvider(clock=lambda: NOW),
        store=PostgresIngestionStore(sessions, provider="synthetic"),
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
    assert len(recorder.messages) == 2
    _, pre_snapshot_payload = recorder.messages[1]
    assert pre_snapshot_payload["mode"] == RunMode.FULL.value
    assert pre_snapshot_payload["capabilities"] == [
        capability.value for capability in FULL_REFRESH_ORDER
    ]
    assert pre_snapshot.capabilities == tuple(capability.value for capability in FULL_REFRESH_ORDER)

    pre_snapshot_completed = await IngestionCoordinator(
        provider=SyntheticIngestionProvider(clock=lambda: NOW + timedelta(minutes=1)),
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
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
    assert len(recorder.messages) == 3
    _, current_payload = recorder.messages[2]
    assert current_payload["mode"] == RunMode.INCREMENTAL.value
    assert current_payload["capabilities"] == [
        capability.value for capability in CURRENT_REFRESH_ORDER
    ]
    assert current.capabilities == tuple(capability.value for capability in CURRENT_REFRESH_ORDER)
    assert current.warnings == ()

    current_completed = await IngestionCoordinator(
        provider=SyntheticIngestionProvider(clock=lambda: NOW + timedelta(minutes=2)),
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
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
    first, acquired = await store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key="active-a",
        correlation_id="active-a",
        now=NOW + timedelta(hours=1),
        lease_duration=timedelta(minutes=5),
    )
    coalesced, second_acquired = await store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key="active-b",
        correlation_id="active-b",
        now=NOW + timedelta(hours=1, seconds=1),
        lease_duration=timedelta(minutes=5),
    )
    assert acquired is True
    assert second_acquired is False
    assert coalesced.id == first.id
    await store.finish_run(
        run_id=first.id,
        status=RunStatus.CANCELLED,
        steps=(),
        now=NOW + timedelta(hours=1, seconds=2),
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
    run, acquired = await store.begin_run(
        owner_id=owner_id,
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key="atomic-failure",
        correlation_id="atomic-failure",
        now=NOW + timedelta(hours=2),
        lease_duration=timedelta(minutes=5),
    )
    assert acquired is True
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
        now=NOW + timedelta(hours=2, seconds=1),
    )
