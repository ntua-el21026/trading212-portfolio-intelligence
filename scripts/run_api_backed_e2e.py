#!/usr/bin/env python3
"""Serve the real API over a deterministic persisted mismatch E2E fixture."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from queue import Empty, Queue
from types import FrameType
from typing import NoReturn
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from trading212_analytics.planning import calculate_contribution_plan
from trading212_api.main import create_app
from trading212_application.planning_jobs import PlanTaskMessage
from trading212_application.report_jobs import ExportTaskMessage, ReportTaskMessage
from trading212_domain import build_synthetic_identity
from trading212_persistence import (
    PostgresPlanningService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import SourceRecordModel, TransactionModel
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.plan_tasks import dispatch_plans_once, execute_plan_message
from trading212_worker.report_seed import seed_synthetic_report_grants
from trading212_worker.report_tasks import (
    dispatch_exports_once,
    dispatch_reports_once,
    execute_export_message,
    execute_report_message,
)
from trading212_worker.scenarios import persist_quantity_cash_mismatch_scenario
from trading212_worker.seed import SEED_TIME, seed_complete_synthetic, seed_materialized_synthetic

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATABASE_URL = "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio"
_FIXTURE_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "trading212-portfolio-intelligence/api-backed-browser-e2e",
)
_TARGET_ACTIVITY_COUNT = 65


def _fixture_uuid(name: str) -> UUID:
    return uuid5(_FIXTURE_NAMESPACE, name)


@contextmanager
def _disposable_database(server_url: str) -> Iterator[str]:
    """Use configured server credentials without mutating its supplied database."""
    parsed = make_url(server_url.replace("postgresql://", "postgresql+psycopg://", 1))
    if parsed.drivername != "postgresql+psycopg":
        raise RuntimeError("API-backed browser fixtures require PostgreSQL")
    name = "t212pi_web_e2e_" + uuid4().hex
    admin_dsn = (
        parsed.set(database="postgres")
        .render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    # Each viewport process needs a fresh owner capacity budget, including in CI.
    # Pin Alembic's environment override before migration or seed code executes.
    database_url = parsed.set(database=name).render_as_string(hide_password=False)
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        yield database_url
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        # Creation must have succeeded above; never drop a caller-supplied database.
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


def _persist_large_activity_fixture(
    session: Session,
    *,
    account_id: UUID,
    listing_id: UUID,
    as_of: datetime,
) -> None:
    source_record_id = session.scalar(
        select(SourceRecordModel.id)
        .where(SourceRecordModel.broker_account_id == account_id)
        .order_by(SourceRecordModel.observed_at, SourceRecordModel.id)
        .limit(1)
    )
    if source_record_id is None:
        raise RuntimeError("API-backed browser fixture requires retained source evidence")
    previously_inserted = session.get(
        TransactionModel,
        _fixture_uuid(f"activity:{account_id}:inserted-newer"),
    )
    if previously_inserted is not None:
        session.delete(previously_inserted)
        session.flush()
    existing_count = (
        session.scalar(
            select(func.count())
            .select_from(TransactionModel)
            .where(TransactionModel.broker_account_id == account_id)
        )
        or 0
    )
    for index in range(max(0, _TARGET_ACTIVITY_COUNT - existing_count)):
        sequence = index + 1
        transaction_id = _fixture_uuid(f"activity:{account_id}:{sequence}")
        if session.get(TransactionModel, transaction_id) is not None:
            continue
        session.add(
            TransactionModel(
                id=transaction_id,
                broker_account_id=account_id,
                provider_transaction_id=f"browser-e2e-{sequence:03d}",
                transaction_type="buy" if sequence % 2 else "sell",
                status="posted",
                instrument_listing_id=listing_id,
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                gross_amount=Decimal("100"),
                fees=Decimal("0"),
                taxes=Decimal("0"),
                net_cash_amount=Decimal("-100") if sequence % 2 else Decimal("100"),
                currency="EUR",
                occurred_at=as_of - timedelta(days=30 + sequence),
                settlement_date=None,
                source_record_id=source_record_id,
                mapping_version="browser-e2e-fixture/1.0.0",
                created_at=as_of - timedelta(seconds=1),
            )
        )


def _persist_newer_activity(
    session: Session,
    *,
    account_id: UUID,
    listing_id: UUID,
) -> UUID:
    transaction_id = _fixture_uuid(f"activity:{account_id}:inserted-newer")
    if session.get(TransactionModel, transaction_id) is not None:
        return transaction_id
    source_record_id = session.scalar(
        select(SourceRecordModel.id)
        .where(SourceRecordModel.broker_account_id == account_id)
        .order_by(SourceRecordModel.observed_at, SourceRecordModel.id)
        .limit(1)
    )
    if source_record_id is None:
        raise RuntimeError("API-backed browser fixture requires retained source evidence")
    now = datetime.now(UTC)
    session.add(
        TransactionModel(
            id=transaction_id,
            broker_account_id=account_id,
            provider_transaction_id="browser-e2e-inserted-newer",
            transaction_type="interest",
            status="posted",
            instrument_listing_id=listing_id,
            quantity=None,
            unit_price=None,
            gross_amount=Decimal("1"),
            fees=Decimal("0"),
            taxes=Decimal("0"),
            net_cash_amount=Decimal("1"),
            currency="EUR",
            occurred_at=now + timedelta(days=1),
            settlement_date=None,
            source_record_id=source_record_id,
            mapping_version="browser-e2e-fixture/1.0.0",
            created_at=now,
        )
    )
    return transaction_id


class _FixturePlanPublisher:
    """Test transport only; canonical outbox, leases and consumer remain production code."""

    def __init__(self) -> None:
        self.messages: Queue[PlanTaskMessage] = Queue(maxsize=100)

    def publish(self, message: PlanTaskMessage) -> None:
        self.messages.put_nowait(message)


async def _deliver_fixture_plans(service: PostgresPlanningService, stopped: asyncio.Event) -> None:
    publisher = _FixturePlanPublisher()
    while not stopped.is_set():
        await dispatch_plans_once(service, publisher, dispatcher_id="browser-fixture")
        while not publisher.messages.empty():
            try:
                message = publisher.messages.get_nowait()
            except Empty:
                break
            await execute_plan_message(
                service,
                message,
                consumer_id="browser-fixture",
                calculate=calculate_contribution_plan,
            )
        with suppress(TimeoutError):
            await asyncio.wait_for(stopped.wait(), timeout=0.25)


class _FixtureReportPublisher:
    """Bounded test transport for the production report dispatcher and consumer."""

    def __init__(self) -> None:
        self.messages: Queue[ReportTaskMessage] = Queue(maxsize=100)

    async def publish_report(self, message: ReportTaskMessage) -> None:
        self.messages.put_nowait(message)


class _FixtureExportPublisher:
    """Exports retain their separate typed production task boundary."""

    def __init__(self) -> None:
        self.messages: Queue[ExportTaskMessage] = Queue(maxsize=100)

    async def publish_export(self, message: ExportTaskMessage) -> None:
        self.messages.put_nowait(message)


async def _deliver_fixture_reports(store: PostgresReportJobStore, stopped: asyncio.Event) -> None:
    reports, exports = _FixtureReportPublisher(), _FixtureExportPublisher()
    while not stopped.is_set():
        await dispatch_reports_once(store, reports, dispatcher_id="browser-fixture")
        while not reports.messages.empty():
            try:
                message = reports.messages.get_nowait()
            except Empty:
                break
            await execute_report_message(store, message, consumer_id="browser-fixture")
        await dispatch_exports_once(store, exports, dispatcher_id="browser-fixture")
        while not exports.messages.empty():
            try:
                export = exports.messages.get_nowait()
            except Empty:
                break
            await execute_export_message(store, export, consumer_id="browser-fixture")
        with suppress(TimeoutError):
            await asyncio.wait_for(stopped.wait(), timeout=0.25)


def main() -> None:
    # Direct script launches also need the repository's test-helper namespace.
    sys.path.insert(0, str(_REPOSITORY_ROOT))
    from scripts.api_e2e_timings import timings_enabled

    timings_enabled(os.environ.get("T212PI_E2E_TIMINGS", "0"))
    server_url = os.environ.get("TEST_DATABASE_URL") or _DEFAULT_DATABASE_URL
    # Uvicorn restores and re-raises SIGTERM after its lifespan exits. Raising
    # SystemExit here lets the database context clean up before this process ends.
    previous_handler = signal.signal(signal.SIGTERM, _exit_fixture)
    try:
        with _disposable_database(server_url) as database_url:
            _serve_fixture(database_url)
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


def _exit_fixture(signum: int, frame: FrameType | None) -> NoReturn:
    raise SystemExit(128 + signum)


def _serve_fixture(database_url: str) -> None:
    from scripts.api_e2e_timings import fixture_timings, timings_enabled

    historical = os.environ.get("T212PI_E2E_HISTORICAL", "0")
    if historical not in {"0", "1"}:
        raise RuntimeError("The historical browser fixture selector must be 0 or 1.")
    xray = os.environ.get("T212PI_E2E_XRAY", "0")
    if xray not in {"0", "1"}:
        raise RuntimeError("The X-ray browser fixture selector must be 0 or 1.")
    reports = os.environ.get("T212PI_E2E_REPORTS", "0")
    if reports not in {"0", "1"}:
        raise RuntimeError("The reports browser fixture selector must be 0 or 1.")
    alerts = os.environ.get("T212PI_E2E_ALERTS", "0")
    if alerts not in {"0", "1"}:
        raise RuntimeError("The alerts browser fixture selector must be 0 or 1.")
    migration_config = Config(str(_REPOSITORY_ROOT / "alembic.ini"))
    migration_config.set_main_option("script_location", str(_REPOSITORY_ROOT / "migrations"))
    migration_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(migration_config, "head")
    seed = seed_complete_synthetic if historical == "1" else seed_materialized_synthetic
    asyncio.run(seed(database_url, app_environment="test"))

    engine = create_database_engine(database_url)
    if xray == "1":
        from trading212_worker.xray_seed import seed_xray_scenario

        try:
            asyncio.run(seed_xray_scenario(create_session_factory(engine), app_environment="test"))
        except BaseException:
            engine.dispose()
            raise
    identity = build_synthetic_identity()
    scenario_time = max(
        SEED_TIME,
        datetime.now(UTC).replace(microsecond=0),
    )
    try:
        if reports == "1" or alerts == "1":
            seed_synthetic_report_grants(
                create_session_factory(engine), app_environment="test", at=scenario_time
            )
        with Session(engine) as session, session.begin():
            persist_quantity_cash_mismatch_scenario(
                session,
                account_id=identity.account.id,
                listing_id=identity.listing.id,
                as_of=scenario_time,
            )
            _persist_large_activity_fixture(
                session,
                account_id=identity.account.id,
                listing_id=identity.listing.id,
                as_of=scenario_time,
            )
        if alerts == "1":
            from scripts.api_e2e_alerts import seed_alert_browser_scenario

            asyncio.run(seed_alert_browser_scenario(create_session_factory(engine)))
    finally:
        engine.dispose()

    os.environ["DATABASE_URL"] = database_url
    os.environ["CELERY_BROKER_URL"] = "memory://"
    app = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=True,
            cookie_secure=False,
            allowed_origins=("http://127.0.0.1:3001",),
            allowed_hosts=("127.0.0.1", "localhost"),
        ),
        clock=lambda: datetime.now(UTC),
    )

    control_engine = create_database_engine(database_url)
    fixture_plans = PostgresPlanningService(
        sessions=create_session_factory(control_engine),
        cursor_signing_key=b"browser-fixture-planning-cursor-key",
    )
    fixture_reports = PostgresReportJobStore(create_session_factory(control_engine))
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def fixture_lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with original_lifespan(application):
            stopped = asyncio.Event()
            try:
                async with asyncio.TaskGroup() as deliveries:
                    deliveries.create_task(_deliver_fixture_plans(fixture_plans, stopped))
                    if reports == "1" or alerts == "1":
                        deliveries.create_task(_deliver_fixture_reports(fixture_reports, stopped))
                    try:
                        yield
                    finally:
                        stopped.set()
            finally:
                control_engine.dispose()

    app.router.lifespan_context = fixture_lifespan

    @app.post("/__e2e__/insert-newer-activity", include_in_schema=False)
    def insert_newer_activity() -> dict[str, str]:
        with Session(control_engine) as session, session.begin():
            transaction_id = _persist_newer_activity(
                session,
                account_id=identity.account.id,
                listing_id=identity.listing.id,
            )
        return {"id": str(transaction_id)}

    @app.post("/__e2e__/reset-newer-activity", include_in_schema=False)
    def reset_newer_activity() -> dict[str, bool]:
        with Session(control_engine) as session, session.begin():
            existing = session.get(
                TransactionModel,
                _fixture_uuid(f"activity:{identity.account.id}:inserted-newer"),
            )
            if existing is not None:
                session.delete(existing)
        return {"reset": True}

    enabled = timings_enabled(os.environ.get("T212PI_E2E_TIMINGS", "0"))
    with fixture_timings(app, enabled=enabled and historical == "1") as observed_app:
        uvicorn.run(
            observed_app,
            host="127.0.0.1",
            port=18_000,
            access_log=False,
            log_config=None,
        )


if __name__ == "__main__":
    main()
