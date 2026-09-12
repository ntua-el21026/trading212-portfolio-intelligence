"""Real queue, source and SQL observations retain authorization and bounded labels."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

import pytest
import trading212_worker.phase2_metrics as queues
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import report_jobs as jobs
from trading212_application import sources as sources
from trading212_domain.reports import ReportFailureCode
from trading212_observability import OperationalMetrics
from trading212_persistence.query_telemetry import DatabaseQueryTiming
from trading212_persistence.report_models import ReportJobModel

from tests.integration.test_report_postgres import ReportCase, generate
from tests.integration.test_report_postgres import report_case as report_case
from tests.integration.test_sources_postgres import attach_account, ingest, source_case
from tests.integration.test_sources_postgres import sources_database as sources_database
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def sample(metrics: OperationalMetrics, state: str, *, saturated: bool = False) -> float:
    name = "phase2_queue_saturated" if saturated else "phase2_queue_items"
    value = metrics.registry.get_sample_value(
        "t212pi_queue_test_" + name, {"queue": "report", "state": state}
    )
    assert value is not None
    return value


def test_queue_counts_are_bounded_current_state_and_never_read_report_payloads(
    report_case: ReportCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = report_case

    async def arrange() -> list[UUID]:
        return [
            (await generate(case, key=f"queue-observation-{index}")).job_id for index in range(4)
        ]

    identifiers = asyncio.run(arrange())
    metrics = OperationalMetrics(service="queue-test")
    monkeypatch.setattr(queues, "QUEUE_SAMPLE_LIMIT", 2)
    at = datetime.now(UTC)
    queues.observe_phase2_queues(case.base.sessions, metrics, at=at)
    assert sample(metrics, "queued") == 2
    assert sample(metrics, "queued", saturated=True) == 1
    assert sample(metrics, "job_failed") == 0
    with case.base.sessions() as session:
        job = session.get(ReportJobModel, identifiers[0])
        assert job is not None
        message = jobs.ReportTaskMessage(
            job_id=job.id,
            owner_id=job.owner_id,
            account_id=job.account_id,
            capture_id=job.input_id,
            input_digest=job.input_digest,
        )

    async def fail() -> None:
        claim = await case.jobs.claim_report_job(message, consumer_id="queue-observation")
        assert claim is not None
        assert await case.jobs.fail_report_job(
            claim, failure=ReportFailureCode.RENDER_FAILED, retryable=False
        )

    asyncio.run(fail())
    monkeypatch.setattr(queues, "QUEUE_SAMPLE_LIMIT", 4)
    queues.observe_phase2_queues(case.base.sessions, metrics, at=at)
    assert sample(metrics, "queued") == 3
    assert sample(metrics, "queued", saturated=True) == 0
    assert sample(metrics, "job_failed") == 1
    rendered = metrics.render().decode()
    for value in (
        str(case.account_id),
        case.principal.owner_id,
        str(identifiers[0]),
        "queue-observation-",
        "input_digest",
        "source_id",
        "payload",
        "report_name",
    ):
        assert value not in rendered
    samples = [
        value
        for family in metrics.registry.collect()
        for value in family.samples
        if "phase2_queue_items" in value.name
    ]
    assert {value.labels["queue"] for value in samples} == {
        "plan",
        "report",
        "export",
        "alert",
        "notification",
    }
    assert all(set(value.labels) == {"queue", "state"} for value in samples)


def test_postgres_failed_statement_finishes_timing_before_next_success(
    sources_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    engine, _ = sources_database
    metrics = OperationalMetrics(service="postgres-query-test")
    observations: list[tuple[float, bool]] = []

    def observe(duration: float, failed: bool) -> None:
        observations.append((duration, failed))
        metrics.observe_database_query(duration, failed)

    timing = DatabaseQueryTiming(engine, observe)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT :value"), {"value": "PG-PRIVATE-CANARY"})
                == "PG-PRIVATE-CANARY"
            )
            with pytest.raises(DBAPIError):
                connection.execute(text("SELECT 1 / 0"))
            connection.rollback()
            assert connection.scalar(text("SELECT 4")) == 4
        assert [failed for _, failed in observations] == [False, True, False]
        assert not timing._starts
        rendered = metrics.render().decode()
        assert "PG-PRIVATE-CANARY" not in rendered
        assert "SELECT" not in rendered
    finally:
        timing.close()


def test_source_observation_follows_real_owner_authorization(
    sources_database: tuple[Engine, sessionmaker[Session]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, sessions = sources_database
    caplog.set_level(logging.INFO, logger="trading212.phase2.telemetry")

    async def run() -> None:
        first, second = await source_case(sessions), await source_case(sessions)
        account = attach_account(first)
        await ingest(first)
        response = await first.service.get_market_source_status(
            first.principal, account, query=sources.SourceStatusQuery()
        )
        observations = [
            record
            for record in caplog.records
            if record.getMessage() == "phase2_source_status_observed"
        ]
        assert len(observations) == len(response.series.items) > 0
        for record, row in zip(observations, response.series.items, strict=True):
            assert record.__dict__["availability"] == row.availability.value
            assert row.latest_snapshot is not None
            assert record.__dict__["freshness"] == row.latest_snapshot.freshness.state.value
        caplog.clear()
        with pytest.raises(sources.SourceServiceError):
            await second.service.get_market_source_status(
                second.principal, account, query=sources.SourceStatusQuery()
            )
        assert not [
            record
            for record in caplog.records
            if record.getMessage() == "phase2_source_status_observed"
        ]

    asyncio.run(run())
