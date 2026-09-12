"""Persisted two-owner accounts and canonical report/alert resources for adapter tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_api.main import create_app
from trading212_application import alert_jobs as aj
from trading212_application import alerts as aa
from trading212_application import report_jobs as rj
from trading212_application import reports as ra
from trading212_application.ingestion import IngestionCoordinator, RunMode, RunStatus
from trading212_domain import CurrencyCode, build_synthetic_identity
from trading212_domain import alerts as ad
from trading212_domain import reports as rd
from trading212_persistence import PostgresPortfolioService
from trading212_persistence.alert_job_store import PostgresAlertJobStore
from trading212_persistence.alert_models import AlertEvaluationJobModel, AlertEventModel
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.base import Base
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    OwnerModel,
    PortfolioSnapshotModel,
    PrincipalModel,
)
from trading212_persistence.notification_store import provision_notification_destination
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_models import ExportJobModel, ReportJobModel
from trading212_persistence.report_service import PostgresReportService
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.alert_tasks import AlertExecutionState, execute_alert_message
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.report_tasks import (
    ReportExecutionState,
    execute_export_message,
    execute_report_message,
)
from trading212_worker.synthetic import SyntheticIngestionProvider

KEY = b"p210-two-owner-synthetic-cursor-key"
ORIGIN = "https://testserver"
SETTINGS = SecuritySettings(
    environment=RuntimeEnvironment.TEST,
    allowed_hosts=("testserver", "localhost"),
    allowed_origins=(ORIGIN,),
)


@dataclass(frozen=True)
class AccountPin:
    account_id: UUID
    snapshot_id: UUID


@dataclass(frozen=True)
class Actor:
    principal: Principal
    token: str
    accounts: tuple[AccountPin, AccountPin]


class GridBearer:
    def __init__(self, actors: tuple[Actor, Actor]) -> None:
        self._actors = actors

    async def authenticate(self, token: str) -> Principal:
        for actor in self._actors:
            if token == actor.token:
                return actor.principal
        raise AuthenticationError("Authentication is required.")


@dataclass(frozen=True)
class OwnerGrid:
    sessions: sessionmaker[Session]
    at: datetime
    operational_clock: Callable[[], datetime]
    actors: tuple[Actor, Actor]
    portfolio: PostgresPortfolioService
    reports: PostgresReportService
    report_jobs: PostgresReportJobStore
    alerts: PostgresAlertService
    alert_jobs: PostgresAlertJobStore
    api: FastAPI

    def report_selection(self, pin: AccountPin) -> rd.ReportSelection:
        return rd.ReportSelection(
            account_id=pin.account_id,
            snapshot_id=pin.snapshot_id,
            start_date=self.at.date(),
            end_date=self.at.date(),
            source_cutoff_at=self.at,
            reporting_currency=CurrencyCode("EUR"),
            report_type=rd.ReportType.PORTFOLIO_SUMMARY,
            sections=(
                rd.ReportSection.OVERVIEW,
                rd.ReportSection.ALLOCATION,
                rd.ReportSection.QUALITY,
            ),
            formats=(rd.ReportFormat.JSON,),
        )

    def export_selection(self, pin: AccountPin) -> rd.ExportSelection:
        selection = self.report_selection(pin)
        return rd.ExportSelection(
            account_id=pin.account_id,
            snapshot_id=pin.snapshot_id,
            start_date=selection.start_date,
            end_date=selection.end_date,
            source_cutoff_at=selection.source_cutoff_at,
            reporting_currency=selection.reporting_currency,
            dataset=rd.ExportDataset.POSITIONS,
            field_set=rd.ExportFieldSet.AUDIT,
            format=rd.ExportFormat.JSON,
        )

    def definition(self, destination: UUID) -> ad.AlertRuleDefinition:
        return ad.AlertRuleDefinition(
            name="Owned cash rule " + uuid4().hex[:8],
            predicate=ad.AlertPredicate(
                family=ad.AlertFamily.CASH_THRESHOLD,
                metric=ad.AlertMetric.CASH_AMOUNT,
                comparison=ad.AlertComparison.GT,
                threshold=Decimal("1"),
                currency=CurrencyCode("EUR"),
            ),
            schedule=ad.AlertIntervalSchedule(anchor_at=self.at),
            destination_ids=(destination,),
        )


def _new_account(session: Session, owner: UUID, now: datetime) -> UUID:
    connection, account = uuid4(), uuid4()
    session.add(
        BrokerConnectionModel(
            id=connection,
            owner_id=owner,
            provider="synthetic",
            environment="synthetic",
            credential_reference=None,
            status="active",
        )
    )
    session.flush()
    session.add(
        BrokerAccountModel(
            id=account,
            connection_id=connection,
            provider_account_id=str(account),
            account_type="synthetic",
            base_currency="EUR",
            display_name="Private synthetic account",
            status="active",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    session.flush()
    return account


@pytest.fixture(scope="module")
def owner_grid(alert_database: tuple[Engine, sessionmaker[Session]]) -> OwnerGrid:
    _, sessions = alert_database
    identity = build_synthetic_identity()
    before = datetime.now(UTC)
    other_owner, other_principal = uuid4(), uuid4()
    issuer, subject = "p210-grid", str(other_principal)
    with sessions() as session, session.begin():
        session.add(OwnerModel(id=other_owner, display_name="Second persisted owner"))
        session.flush()
        session.add(
            PrincipalModel(
                id=other_principal,
                owner_id=other_owner,
                issuer=issuer,
                subject=subject,
                status="active",
                last_authenticated_at=before,
            )
        )
        session.flush()
        account_ids = (
            (identity.account.id, _new_account(session, identity.owner.id, before)),
            (
                _new_account(session, other_owner, before),
                _new_account(session, other_owner, before),
            ),
        )
        for identifier in (identity.principal.id, other_principal):
            provision_principal_scopes(
                session,
                principal_id=identifier,
                scopes=frozenset(Scope),
                now=before - timedelta(seconds=1),
            )

    async def materialize(owner: UUID, account: UUID) -> AccountPin:
        observed = datetime.now(UTC)
        result = await IngestionCoordinator(
            provider=SyntheticIngestionProvider(clock=lambda: observed),
            store=PostgresIngestionStore(
                sessions,
                provider="synthetic",
                materializer=PostgresCanonicalMaterializer(),
            ),
            clock=lambda: observed,
        ).refresh(
            owner_id=str(owner),
            account_id=str(account),
            mode=RunMode.FULL,
            idempotency_key="p210-grid-" + uuid4().hex,
            correlation_id="p210-owner-grid",
        )
        assert result.status is RunStatus.SUCCEEDED
        with sessions() as session:
            snapshot = session.scalar(
                select(PortfolioSnapshotModel)
                .where(PortfolioSnapshotModel.broker_account_id == account)
                .order_by(PortfolioSnapshotModel.valuation_at.desc(), PortfolioSnapshotModel.id)
                .limit(1)
            )
            assert snapshot is not None and snapshot.portfolio_total is not None
            assert snapshot.portfolio_total > 0
            return AccountPin(account, snapshot.id)

    own = tuple(asyncio.run(materialize(identity.owner.id, account)) for account in account_ids[0])
    other = tuple(asyncio.run(materialize(other_owner, account)) for account in account_ids[1])
    # Take a real database instant after ingestion; do not rewrite retained timestamps.
    with sessions() as session:
        at = session.scalar(select(func.clock_timestamp()))
    assert isinstance(at, datetime)
    principals = (
        Principal(
            str(identity.principal.id),
            str(identity.owner.id),
            "local.synthetic",
            "synthetic-owner",
            frozenset(Scope),
            before - timedelta(seconds=1),
            at + timedelta(days=1),
        ),
        Principal(
            str(other_principal),
            str(other_owner),
            issuer,
            subject,
            frozenset(Scope),
            before - timedelta(seconds=1),
            at + timedelta(days=1),
        ),
    )
    actors = (
        Actor(principals[0], "p210-owner-a", (own[0], own[1])),
        Actor(principals[1], "p210-owner-b", (other[0], other[1])),
    )

    def operational_now() -> datetime:
        # Publication leases use PostgreSQL wall time; financial pins keep at.
        return max(at, datetime.now(UTC))

    portfolio = PostgresPortfolioService(
        sessions=sessions, cursor_signing_key=KEY, clock=lambda: at
    )
    reports = PostgresReportService(sessions, cursor_signing_key=KEY, clock=operational_now)
    alerts = PostgresAlertService(sessions, cursor_signing_key=KEY, clock=operational_now)
    api = create_app(
        settings=SETTINGS,
        service=portfolio,
        report_service=reports,
        alert_service=alerts,
        bearer_authenticator=GridBearer(actors),
        clock=lambda: at,
    )
    return OwnerGrid(
        sessions,
        at,
        operational_now,
        actors,
        portfolio,
        reports,
        PostgresReportJobStore(sessions, clock=operational_now),
        alerts,
        PostgresAlertJobStore(sessions, cursor_signing_key=KEY, clock=operational_now),
        api,
    )


@dataclass(frozen=True)
class ReportResources:
    pin: AccountPin
    report: ra.ReportJobStatus
    export: ra.ExportJobStatus
    report_grant: str
    export_grant: str

    @property
    def private_values(self) -> tuple[str, ...]:
        return (
            str(self.pin.account_id),
            str(self.pin.snapshot_id),
            str(self.report.job_id),
            str(self.export.export_id),
            str(self.report.artifacts[0].artifact_id),
            str(self.export.artifacts[0].artifact_id),
            self.report.artifacts[0].content_digest,
            self.export.artifacts[0].content_digest,
            self.report_grant,
            self.export_grant,
        )


async def build_reports(grid: OwnerGrid, actor: Actor, pin: AccountPin) -> ReportResources:
    pending = await grid.reports.generate_report(
        actor.principal,
        ra.GenerateReportCommand(selection=grid.report_selection(pin), idempotency_key=uuid4().hex),
    )
    with grid.sessions() as session:
        report = session.get_one(ReportJobModel, pending.job_id)
        message = rj.ReportTaskMessage(
            job_id=report.id,
            owner_id=report.owner_id,
            account_id=report.account_id,
            capture_id=report.input_id,
            input_digest=report.input_digest,
        )
    assert (
        await execute_report_message(
            grid.report_jobs,
            message,
            consumer_id="p210-report-owner-grid",
        )
        is ReportExecutionState.COMPLETED
    )
    saved = await grid.reports.get_report_status(actor.principal, pin.account_id, pending.job_id)
    assert saved.state is rd.ReportJobState.SUCCEEDED and len(saved.artifacts) == 1
    exporting = await grid.reports.create_export(
        actor.principal,
        ra.CreateExportCommand(selection=grid.export_selection(pin), idempotency_key=uuid4().hex),
    )
    with grid.sessions() as session:
        export = session.get_one(ExportJobModel, exporting.export_id)
        export_message = rj.ExportTaskMessage(
            job_id=export.id,
            owner_id=export.owner_id,
            account_id=export.account_id,
            capture_id=export.input_id,
            input_digest=export.input_digest,
        )
    assert (
        await execute_export_message(
            grid.report_jobs,
            export_message,
            consumer_id="p210-export-owner-grid",
        )
        is ReportExecutionState.COMPLETED
    )
    exported = await grid.reports.get_export_status(
        actor.principal, pin.account_id, exporting.export_id
    )
    assert exported.state is rd.ReportJobState.SUCCEEDED and len(exported.artifacts) == 1
    report_grant = await grid.reports.create_report_download_grant(
        actor.principal,
        pin.account_id,
        saved.job_id,
        saved.artifacts[0].artifact_id,
    )
    export_grant = await grid.reports.create_export_download_grant(
        actor.principal,
        pin.account_id,
        exported.export_id,
        exported.artifacts[0].artifact_id,
    )
    return ReportResources(pin, saved, exported, report_grant.token, export_grant.token)


@pytest.fixture(scope="module")
def report_resources(owner_grid: OwnerGrid) -> dict[UUID, ReportResources]:
    return {
        pin.account_id: asyncio.run(build_reports(owner_grid, actor, pin))
        for actor in owner_grid.actors
        for pin in actor.accounts
    }


@dataclass(frozen=True)
class AlertResources:
    pin: AccountPin
    destination: UUID
    rule: aa.AlertRuleDetail
    event: aa.AlertEventDetail

    @property
    def private_values(self) -> tuple[str, ...]:
        return (
            str(self.pin.account_id),
            str(self.rule.id),
            str(self.rule.latest_version.id),
            str(self.event.id),
            str(self.event.evaluation_id),
            str(self.destination),
            self.event.deduplication_digest,
        )


async def draft_rule(
    grid: OwnerGrid, actor: Actor, pin: AccountPin, destination: UUID
) -> aa.AlertRuleDetail:
    return await grid.alerts.create_rule(
        actor.principal,
        aa.CreateAlertRuleCommand(
            account_id=pin.account_id, definition=grid.definition(destination)
        ),
        idempotency_key=uuid4().hex,
        correlation_id="p210-alert-owner-grid",
    )


async def build_alert(grid: OwnerGrid, actor: Actor, pin: AccountPin) -> AlertResources:
    with grid.sessions() as session, session.begin():
        destination = provision_notification_destination(
            session,
            owner_id=UUID(actor.principal.owner_id),
            account_id=pin.account_id,
            configuration_key="p210-in-app-" + uuid4().hex,
            channel=aa.NotificationChannel.IN_APP,
            label="Private in-app destination",
            secret_reference=None,
            state=aa.NotificationDestinationState.CONFIGURED,
            now=grid.at,
        )
    # Admit the original financial slot with a fixed-clock real arranger.
    # Only the operational consumer and subsequent reads use the advancing clock.
    scheduled_alerts = PostgresAlertService(
        grid.sessions,
        cursor_signing_key=KEY,
        clock=lambda: grid.at,
    )
    rule = await scheduled_alerts.create_rule(
        actor.principal,
        aa.CreateAlertRuleCommand(
            account_id=pin.account_id, definition=grid.definition(destination)
        ),
        idempotency_key=uuid4().hex,
        correlation_id="p210-alert-owner-grid",
    )
    active = await scheduled_alerts.activate_rule(
        actor.principal,
        rule.id,
        rule.latest_version.id,
        idempotency_key=uuid4().hex,
        expected_revision=rule.revision,
        correlation_id="p210-alert-owner-grid",
    )
    admission = PostgresAlertJobStore(
        grid.sessions,
        cursor_signing_key=KEY,
        clock=lambda: grid.at,
    )
    await admission.admit_due_evaluations()
    with grid.sessions() as session:
        job = session.scalar(
            select(AlertEvaluationJobModel).where(
                AlertEvaluationJobModel.rule_id == rule.id,
                AlertEvaluationJobModel.scheduled_for == grid.at,
            )
        )
        assert job is not None
        message = aj.AlertEvaluationTaskMessage(
            job_id=job.id,
            owner_id=job.owner_id,
            account_id=job.account_id,
            rule_version_id=job.rule_version_id,
            capture_id=job.input_id,
            input_digest=job.input_digest,
            scheduled_for=job.scheduled_for,
            execution_intent=ad.AlertExecutionIntent(job.execution_intent),
        )
    assert (
        await execute_alert_message(
            grid.alert_jobs,
            message,
            consumer_id="p210-alert-owner-grid",
        )
        is AlertExecutionState.COMPLETED
    )
    with grid.sessions() as session:
        event_id = session.scalar(
            select(AlertEventModel.id).where(AlertEventModel.rule_id == rule.id)
        )
        assert event_id is not None
    event = await grid.alerts.get_event(actor.principal, event_id)
    assert event.evaluation.outcome is ad.AlertEvaluationOutcome.MATCHED
    assert event.evaluation.reproducibility is aa.AlertReproducibility.RETAINED
    return AlertResources(pin, destination, active, event)


@pytest.fixture(scope="module")
def alert_resources(owner_grid: OwnerGrid) -> dict[UUID, AlertResources]:
    return {
        pin.account_id: asyncio.run(build_alert(owner_grid, actor, pin))
        for actor in owner_grid.actors
        for pin in actor.accounts
    }


@dataclass(frozen=True)
class HttpCase:
    operation: str
    method: Literal["GET", "POST"]
    path: str
    success: int
    query: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


async def send(client: httpx.AsyncClient, actor: Actor, request: HttpCase) -> httpx.Response:
    headers = {"Authorization": "Bearer " + actor.token, **request.headers}
    if request.body is not None:
        headers["Content-Type"] = "application/json"
    return await client.request(
        request.method,
        request.path,
        params=request.query,
        content=request.body,
        headers=headers,
    )


def denied(
    response: httpx.Response, code: Literal["ACCESS_DENIED", "NOT_FOUND"], private: tuple[str, ...]
) -> None:
    assert response.status_code == (403 if code == "ACCESS_DENIED" else 404)
    assert response.json()["error"]["code"] == code
    assert "etag" not in response.headers
    assert all(value not in response.text for value in private)
    assert "p210-owner-" not in response.text


@contextmanager
def without_grant(grid: OwnerGrid, actor: Actor, scope: Scope) -> Iterator[None]:
    # The bearer remains unchanged; only trusted physical current grants change.
    with grid.sessions() as session, session.begin():
        provision_principal_scopes(
            session,
            principal_id=UUID(actor.principal.principal_id),
            scopes=frozenset(Scope) - {scope},
            now=grid.at,
        )
    try:
        yield
    finally:
        with grid.sessions() as session, session.begin():
            provision_principal_scopes(
                session,
                principal_id=UUID(actor.principal.principal_id),
                scopes=frozenset(Scope),
                now=grid.at,
            )


# Fixed operational tables; audit rows are expected on denials and grant changes.
# Fingerprinting all columns also detects a mutation that preserves the row count.
REPORT_STATE = (
    "report_jobs",
    "export_jobs",
    "report_dispatch_outbox",
    "export_dispatch_outbox",
    "report_definitions",
    "report_input_snapshots",
    "report_input_chunks",
    "report_input_dependencies",
    "report_input_pins",
    "report_input_licenses",
    "report_manifests",
    "export_manifests",
    "report_artifacts",
    "export_artifacts",
    "application_command_identities",
    "artifact_download_grants",
)
ALERT_STATE = (
    "alert_rules",
    "alert_rule_versions",
    "alert_rule_events",
    "alert_command_identities",
    "alert_conditions",
    "alert_evaluation_jobs",
    "alert_evaluation_outbox",
    "alert_evaluations",
    "alert_input_snapshots",
    "alert_events",
    "alert_event_transitions",
    "alert_acknowledgments",
    "in_app_notifications",
    "notification_delivery_jobs",
    "notification_delivery_outbox",
    "notification_destinations",
    "notification_destination_versions",
)


def retained_state(
    grid: OwnerGrid,
    tables: tuple[str, ...],
    *,
    include_collections: bool = True,
) -> tuple[tuple[str, int, str], ...]:
    if include_collections:
        tables = (*tables, "collection_query_snapshots", "collection_query_snapshot_members")
    result = []
    with grid.sessions() as session:
        for name in tables:
            table = Base.metadata.tables[name]
            rows = session.execute(select(table).order_by(*table.primary_key.columns)).all()
            # Synthetic raw bytes are hashed in memory and never emitted on failure.
            digest = sha256()
            for row in rows:
                digest.update(repr(tuple(row)).encode())
                digest.update(b"\n")
            result.append((name, len(rows), digest.hexdigest()))
    return tuple(result)
