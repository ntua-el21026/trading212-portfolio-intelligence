"""Actual task-container outages and a killed projection consumer preserve recovery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import signal
import subprocess
import time
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Any, Literal, cast
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from celery import Celery  # type: ignore[import-untyped]
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import Table, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from trading212_analytics.projection import calculate_projection, calculate_projection_chunk
from trading212_application import projection as app
from trading212_application import projection_jobs as jobs
from trading212_application.risk import PremiumJobState
from trading212_domain.projection_serialization import projection_canonical_bytes
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.premium_models import PremiumOutboxModel
from trading212_persistence.projection_job_store import PostgresProjectionJobStore
from trading212_persistence.projection_models import (
    ProjectionChunkModel,
    ProjectionPathModel,
    ProjectionPointAssetModel,
    ProjectionPointModel,
    ProjectionResultModel,
)
from trading212_persistence.projection_service import PostgresProjectionService
from trading212_worker.projection_tasks import (
    CeleryProjectionPublisher,
    ProjectionExecutionState,
    dispatch_projections_once,
    execute_projection_message,
)
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.phase3_operational_fixture import evidence, inventory, task_postgres
from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _docker(*arguments: str) -> str:
    assert arguments and arguments[0] in {"ps", "inspect", "kill", "start", "exec"}
    return subprocess.run(  # noqa: S603 -- fixed binary; call sites validate task container IDs.
        ["/usr/bin/docker", *arguments], check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def _container(service: Literal["postgres", "redis"]) -> str:
    project = os.environ["T212PI_PHASE3_TASK_PROJECT"]
    assert project == "t212pi_batch2_20261114"
    identifiers = _docker(
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        f"label=com.docker.compose.service={service}",
    ).split()
    assert len(identifiers) == 1
    identifier = identifiers[0]
    labels = json.loads(_docker("inspect", "--format", "{{json .Config.Labels}}", identifier))
    assert labels["com.docker.compose.project"] == project
    assert labels["com.docker.compose.service"] == service
    if service == "postgres":
        assert task_postgres() == identifier
    return identifier


def _mapped_port(identifier: str, container_port: str, actual_port: int) -> None:
    ports = json.loads(
        _docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", identifier)
    )
    assert any(
        entry["HostIp"] in {"127.0.0.1", "::1"} and int(entry["HostPort"]) == actual_port
        for entry in ports[container_port]
    )


def _celery(broker: str, queue: str) -> Any:
    application = Celery("phase3-process-recovery", broker=broker)
    application.conf.update(
        task_default_queue=queue,
        task_default_exchange=queue,
        task_default_routing_key=queue,
        broker_connection_retry_on_startup=False,
        broker_connection_max_retries=0,
        broker_transport_options={"socket_timeout": 2, "socket_connect_timeout": 2},
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,
    )
    return application


class _ObservedStore(PostgresProjectionJobStore):
    """Observe the actual successful claim without changing any worker transition."""

    observation: Connection

    async def claim_projection_job(
        self, message: jobs.ProjectionTaskMessage, *, consumer_id: str
    ) -> jobs.ProjectionJobClaim | None:
        claimed = await super().claim_projection_job(message, consumer_id=consumer_id)
        if claimed is not None:
            self.observation.send(("resumed_claim", claimed))
        return claimed


def _consumer(
    database_url: str, broker: str, queue: str, observation: Connection, *, checkpoint: bool
) -> None:
    """Spawned consumer owns fresh connections and uses the unmodified real clock."""
    engine = create_database_engine(database_url)
    application = _celery(broker, queue)
    try:
        worker = _ObservedStore(create_session_factory(engine), cursor_signing_key=XRAY_CURSOR_KEY)
        worker.observation = observation
        with (
            application.connection_for_read() as connection,
            connection.SimpleQueue(queue) as incoming,
        ):
            delivery = incoming.get(block=True, timeout=10)
            payload = delivery.payload
            assert delivery.headers["task"] == jobs.PROJECTION_TASK_NAME
            assert isinstance(payload, (list, tuple)) and len(payload) == 3
            assert payload[0] == [] and isinstance(payload[1], dict)
            message = jobs.ProjectionTaskMessage.from_wire(payload[1])
            if checkpoint:
                # The acknowledgement is sent only after the real transaction commits.
                async def persist() -> jobs.ProjectionJobClaim:
                    claim = await PostgresProjectionJobStore.claim_projection_job(
                        worker, message, consumer_id="phase3-killed-consumer"
                    )
                    assert claim is not None
                    plan = await worker.load_projection_job_input(claim)
                    assert await worker.save_projection_job_chunk(
                        claim, calculate_projection_chunk(plan.inputs, 0, 2)
                    )
                    return claim

                observation.send(("committed_checkpoint", asyncio.run(persist())))
                # Keep the real broker delivery unacknowledged until parent SIGKILL.
                while True:
                    signal.pause()
            state = asyncio.run(
                execute_projection_message(worker, message, consumer_id="phase3-resumed-consumer")
            )
            delivery.ack()
            observation.send(("terminal", state.value))
    finally:
        application.close()
        engine.dispose()
        observation.close()


async def _ready(case: ProjectionJobCase, redis: Redis) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with case.engine.connect() as connection:
                assert connection.scalar(text("SELECT 1")) == 1
            assert redis.ping()
            return
        except (SQLAlchemyError, RedisError):
            await asyncio.sleep(0.25)
    pytest.fail("The exact task PostgreSQL/Redis containers did not recover within30 seconds.")


def _counts(case: ProjectionJobCase) -> dict[str, int]:
    counts = {}
    with case.sessions() as session:
        for model in (
            ProjectionChunkModel,
            ProjectionPathModel,
            ProjectionPointModel,
            ProjectionPointAssetModel,
            ProjectionResultModel,
        ):
            table = cast(Table, model.__table__)
            count = session.scalar(
                select(func.count()).select_from(table).where(table.c.run_id == case.run.id)
            )
            assert isinstance(count, int)
            counts[table.name] = count
    return counts


def _checkpoint(case: ProjectionJobCase) -> tuple[object, ...]:
    with case.sessions() as session:
        row = session.execute(
            select(
                ProjectionChunkModel.id,
                ProjectionChunkModel.created_at,
                ProjectionChunkModel.lease_token,
                ProjectionChunkModel.consumer_attempt,
                ProjectionChunkModel.content_digest,
                ProjectionChunkModel.canonical_chunk,
            ).where(
                ProjectionChunkModel.run_id == case.run.id,
                ProjectionChunkModel.variant == "baseline",
                ProjectionChunkModel.first_path == 0,
            )
        ).one()
        return tuple(row)


async def test_sigkill_redis_loss_and_postgres_outage_resume_original_projection_chunk(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    postgres, redis_container = _container("postgres"), _container("redis")
    assert case.engine.url.database is not None
    assert case.engine.url.database.startswith("t212pi_xray_reads_")
    assert case.engine.url.host in {"localhost", "127.0.0.1", "::1"}
    assert case.engine.url.port is not None
    _mapped_port(postgres, "5432/tcp", case.engine.url.port)
    broker = os.environ["REDIS_URL"]
    parsed = urlparse(broker)
    assert parsed.scheme == "redis" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    _mapped_port(redis_container, "6379/tcp", parsed.port or 6379)
    redis = Redis.from_url(broker, socket_timeout=2, socket_connect_timeout=2)
    assert cast(dict[str, str], redis.config_get("appendonly"))["appendonly"] == "no"
    assert cast(dict[str, str], redis.config_get("save"))["save"] == ""
    queue = "phase3-projection-" + uuid4().hex
    application = _celery(broker, queue)
    worker = PostgresProjectionJobStore(case.sessions, cursor_signing_key=XRAY_CURSOR_KEY)
    context = multiprocessing.get_context("spawn")
    observed, child_pipe = context.Pipe(duplex=False)
    child = context.Process(
        target=_consumer,
        args=(case.engine.url.render_as_string(hide_password=False), broker, queue, child_pipe),
        kwargs={"checkpoint": True},
    )
    resumed: BaseProcess | None = None
    containers_killed = False
    started = time.perf_counter()
    try:
        dispatched = await dispatch_projections_once(
            worker, CeleryProjectionPublisher(application), dispatcher_id="phase3-before-kill"
        )
        assert (dispatched.claimed, dispatched.published, dispatched.deferred) == (1, 1, 0)
        assert redis.llen(queue) == 1
        child.start()
        child_pipe.close()
        assert observed.poll(30), "The spawned consumer never acknowledged a committed chunk."
        event, old_claim = observed.recv()
        assert event == "committed_checkpoint" and isinstance(old_claim, jobs.ProjectionJobClaim)
        assert old_claim.consumer_attempt == 1
        original = _checkpoint(case)
        plan = await worker.load_projection_job_input(old_claim)
        old_chunks = await worker.load_projection_job_chunks(old_claim)
        assert len(old_chunks) == 1
        expected = calculate_projection(plan.inputs)
        expected_digest = hashlib.sha256(projection_canonical_bytes(expected)).hexdigest()
        assert redis.llen(queue) == 0 and redis.hlen("unacked") == 1
        child.kill()
        child.join(timeout=10)
        assert child.exitcode == -signal.SIGKILL
        before_outage = inventory(case.sessions)
        with case.sessions() as session:
            outbox = session.scalar(
                select(PremiumOutboxModel).where(
                    PremiumOutboxModel.job_id == UUID(old_claim.message.job_id)
                )
            )
            assert outbox is not None and outbox.state == "published"
            outbox_identity = (outbox.id, outbox.publication_attempts, outbox.published_at)
        outage_started = time.perf_counter()
        containers_killed = True
        _docker("kill", "--signal", "KILL", redis_container, postgres)
        case.engine.dispose()
        with pytest.raises(SQLAlchemyError), case.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        with pytest.raises(jobs.ProjectionJobInputError) as unavailable:
            await worker.claim_projection_dispatches(dispatcher_id="phase3-database-down")
        assert unavailable.value.code is jobs.ProjectionJobFailureCode.STORAGE_UNAVAILABLE
        assert unavailable.value.retryable
        with pytest.raises(RedisError):
            redis.ping()
        _docker("start", postgres, redis_container)
        await _ready(case, redis)
        outage_seconds = time.perf_counter() - outage_started
        assert redis.llen(queue) == 0 and redis.hlen("unacked") == 0
        assert inventory(case.sessions) == before_outage
        assert _checkpoint(case) == original
        with case.sessions() as session:
            durable = session.scalar(
                select(PremiumOutboxModel).where(
                    PremiumOutboxModel.job_id == UUID(old_claim.message.job_id)
                )
            )
            assert durable is not None
            assert (
                durable.id,
                durable.publication_attempts,
                durable.published_at,
            ) == outbox_identity
        # Wait for the actual60-second lease; no fixture or persisted clock is advanced.
        wait_started = time.monotonic()
        while time.time() <= old_claim.expires_at.timestamp() + 1:
            assert time.monotonic() - wait_started < 75
            await asyncio.sleep(0.25)
        lease_wait_seconds = time.monotonic() - wait_started
        claim_to_redispatch_seconds = time.time() - (
            old_claim.expires_at.timestamp() - jobs.PROJECTION_WORKER_LEASE_SECONDS
        )
        assert claim_to_redispatch_seconds >= 61
        queue_age = time.time() - case.run.created_at.timestamp()
        replay = await dispatch_projections_once(
            worker, CeleryProjectionPublisher(application), dispatcher_id="phase3-after-real-lease"
        )
        assert (replay.claimed, replay.published, replay.deferred) == (1, 1, 0)
        assert redis.llen(queue) == 1
        resumed_parent, resumed_pipe = context.Pipe(duplex=False)
        resumed = context.Process(
            target=_consumer,
            args=(
                case.engine.url.render_as_string(hide_password=False),
                broker,
                queue,
                resumed_pipe,
            ),
            kwargs={"checkpoint": False},
        )
        resumed.start()
        resumed_pipe.close()
        assert resumed_parent.poll(30)
        event, new_claim = resumed_parent.recv()
        assert event == "resumed_claim" and isinstance(new_claim, jobs.ProjectionJobClaim)
        assert new_claim.message == old_claim.message and new_claim.consumer_attempt == 2
        assert new_claim.claim_token != old_claim.claim_token
        assert new_claim.deadline_at == old_claim.deadline_at
        assert resumed_parent.poll(90)
        assert resumed_parent.recv() == ("terminal", ProjectionExecutionState.SUCCEEDED.value)
        resumed.join(timeout=10)
        resumed_parent.close()
        assert resumed.exitcode == 0
        assert _checkpoint(case) == original
        assert not await worker.save_projection_job_chunk(old_claim, old_chunks[0])
        reader = PostgresProjectionService(case.sessions, cursor_signing_key=XRAY_CURSOR_KEY)
        saved = await reader.get_run(
            case.principal, case.run.id, app.ProjectionPointPageQuery(point_limit=1)
        )
        assert saved.state is PremiumJobState.SUCCEEDED and saved.result is not None
        assert saved.result.context.saved_result_digest == expected_digest
        counts = _counts(case)
        assert counts["projection_results"] == 1
        assert plan.inputs.variants == ("baseline",)
        assert counts["projection_chunks"] == 2  # The original2 paths plus the remaining5.
        assert counts["projection_paths"] == plan.inputs.paths
        assert counts["projection_points"] == plan.inputs.paths * len(plan.inputs.retained_months)
        assert counts["projection_point_assets"] == counts["projection_points"]
        final_inventory = inventory(case.sessions)
        assert (
            await execute_projection_message(
                worker, old_claim.message, consumer_id="phase3-duplicate-after-recovery"
            )
            is ProjectionExecutionState.FENCED
        )
        assert _counts(case) == counts and inventory(case.sessions) == final_inventory
        evidence(
            "process-outages",
            {
                "scope": "projection consumer plus task PostgreSQL/Redis; not full-stack restart",
                "postgres_container_id": postgres,
                "redis_container_id": redis_container,
                "actual_sigkill_exit_code": child.exitcode,
                "actual_database_failure_retryable": True,
                "actual_redis_unacked_message_lost": True,
                "before_outage_inventory": before_outage,
                "database_inventory_preserved": True,
                "original_chunk_sha256": hashlib.sha256(cast(bytes, original[5])).hexdigest(),
                "original_chunk_identity_and_bytes_preserved": True,
                "original_input_digest": old_claim.message.input_digest,
                "canonical_result_digest": expected_digest,
                "original_consumer_attempt": old_claim.consumer_attempt,
                "resumed_consumer_attempt": new_claim.consumer_attempt,
                "new_fence_same_original_deadline": True,
                "duplicate_fenced": True,
                "retained_rows_after_recovery": counts,
                "container_outage_through_ready_seconds": outage_seconds,
                "real_lease_wait_seconds": lease_wait_seconds,
                "claim_through_redispatch_seconds": claim_to_redispatch_seconds,
                "queue_age_at_redelivery_seconds": queue_age,
                "exercise_seconds": time.perf_counter() - started,
            },
        )
    finally:
        for process in (child, resumed):
            if process is not None and process.pid is not None:
                if process.is_alive():
                    process.kill()
                process.join(timeout=10)
        observed.close()
        child_pipe.close()
        if containers_killed:
            for identifier in (postgres, redis_container):
                if _docker("inspect", "--format", "{{.State.Running}}", identifier) != "true":
                    _docker("start", identifier)
            case.engine.dispose()
            await _ready(case, redis)
        redis.delete(queue, "_kombu.binding." + queue)
        redis.close()
        application.close()
