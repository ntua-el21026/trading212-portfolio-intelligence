from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.testclient import TestClient
from trading212_api.main import create_app as create_api_app
from trading212_application.ingestion import (
    FULL_REFRESH_ORDER,
    Checkpoint,
    IngestionCapability,
    IngestionCoordinator,
    RunMode,
    RunStatus,
    SourcePage,
)
from trading212_domain import build_synthetic_identity
from trading212_mcp.server import create_runtime
from trading212_persistence import (
    Base,
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import (
    PortfolioSnapshotModel,
    SourceRecordModel,
    SourceRecordOccurrenceModel,
)
from trading212_persistence.seed import seed_synthetic
from trading212_provider.client import Trading212Client
from trading212_provider.configuration import BrokerEnvironment, Trading212Settings
from trading212_provider.credentials import StaticCredentialProvider, Trading212Credentials
from trading212_provider.ingestion_adapter import Trading212IngestionAdapter
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.synthetic import SyntheticIngestionProvider

pytestmark = [pytest.mark.integration, pytest.mark.security]
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


@pytest.fixture
def privacy_database() -> Iterator[Engine]:
    base_url = make_url(
        os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio",
        ).replace("postgresql://", "postgresql+psycopg://", 1)
    )
    database_name = f"t212pi_export_privacy_{uuid4().hex[:12]}"
    admin_dsn = (
        base_url.set(database="postgres")
        .render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    database_url = base_url.set(database=database_name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    engine: Engine | None = None
    try:
        command.upgrade(config, "head")
        seed_synthetic(database_url, app_environment="test")
        engine = create_database_engine(database_url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if not database_name.startswith("t212pi_export_privacy_"):
            raise RuntimeError("refusing to drop an unexpected test database")
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


class ExportAdapterProvider(SyntheticIngestionProvider):
    """Use the sealed real export adapter in an otherwise synthetic full refresh."""

    def __init__(self, adapter: Trading212IngestionAdapter) -> None:
        super().__init__(clock=lambda: NOW)
        self._exports = adapter

    async def read_page(
        self,
        *,
        owner_id: str,
        account_id: str,
        capability: IngestionCapability,
        checkpoint: Checkpoint | None,
        correlation_id: str,
    ) -> SourcePage:
        read_page = (
            self._exports.read_page
            if capability is IngestionCapability.EXPORT_METADATA
            else super().read_page
        )
        return await read_page(
            owner_id=owner_id,
            account_id=account_id,
            capability=capability,
            checkpoint=checkpoint,
            correlation_id=correlation_id,
        )


@pytest.mark.asyncio
async def test_export_url_never_reaches_persistence_canonical_api_mcp_or_telemetry(
    privacy_database: Engine,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "_".join(("EXPORT", "URL", "CANARY"))
    host = ".".join(("signed", "example", "invalid"))
    path = "/" + "report" + ".csv"
    signature = "-".join(("private", "export", "signature"))
    url = f"https://{host}{path}?token={token}&signature={signature}"
    forbidden = (url, token, host, path, signature)
    rotation = "initial"
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        return httpx.Response(
            200,
            json=[
                {
                    "reportId": 17,
                    "status": "Finished",
                    "timeFrom": "2026-01-01T00:00:00Z",
                    "timeTo": "2026-09-07T00:00:00Z",
                    "dataIncluded": {"includeTransactions": True, "futureField": url},
                    "downloadLink": url + "&rotation=" + rotation,
                    "download_link": url,
                    "futureField": {"location": url},
                }
            ],
        )

    broker = Trading212Client(
        settings=Trading212Settings(),
        credential_provider=StaticCredentialProvider(
            Trading212Credentials("synthetic-key", "synthetic-secret", BrokerEnvironment.DEMO)
        ),
        credential_reference="secret://synthetic/demo",
        transport=httpx.MockTransport(handler),
        now=lambda: NOW,
    )
    identity = build_synthetic_identity()
    account_id = str(identity.account.id)
    sessions = create_session_factory(privacy_database)
    provider = ExportAdapterProvider(Trading212IngestionAdapter(broker))
    store = PostgresIngestionStore(
        sessions,
        provider="synthetic",
        materializer=PostgresCanonicalMaterializer(),
    )
    caplog.set_level(logging.INFO)
    try:
        for index in range(2):
            rotation = "initial" if index == 0 else "rotated"
            refreshed_at = NOW + timedelta(minutes=index)

            def clock(value: datetime = refreshed_at) -> datetime:
                return value

            completed = await IngestionCoordinator(
                provider=provider,
                store=store,
                clock=clock,
            ).refresh(
                owner_id=str(identity.owner.id),
                account_id=account_id,
                mode=RunMode.FULL,
                idempotency_key=f"export-privacy-{index}",
                correlation_id=f"export-privacy-{index}",
                capabilities=FULL_REFRESH_ORDER,
            )
            assert completed.status is RunStatus.SUCCEEDED
            export_step = next(
                step
                for step in completed.steps
                if step.capability is IngestionCapability.EXPORT_METADATA
            )
            assert export_step.updated == 0
            assert export_step.inserted == (1 if index == 0 else 0)
            assert export_step.unchanged == index
    finally:
        await broker.aclose()

    with Session(privacy_database) as session:
        exports = session.scalars(
            select(SourceRecordModel).where(
                SourceRecordModel.capability == IngestionCapability.EXPORT_METADATA.value
            )
        ).all()
        assert len(exports) == 1
        assert exports[0].sanitized_payload is not None
        assert exports[0].sanitized_payload["downloadAvailable"] is True
        assert set(exports[0].sanitized_payload) == {
            "reportId",
            "status",
            "timeFrom",
            "timeTo",
            "dataIncluded",
            "downloadAvailable",
        }
        occurrences = session.scalars(
            select(SourceRecordOccurrenceModel).where(
                SourceRecordOccurrenceModel.source_record_id == exports[0].id
            )
        ).all()
        assert len(occurrences) == 2
        snapshots = session.scalars(
            select(PortfolioSnapshotModel).order_by(PortfolioSnapshotModel.valuation_at)
        ).all()
        assert len(snapshots) == 2
        start_id, end_id = (str(snapshot.id) for snapshot in snapshots)
        # Scan every real persisted table, including canonical calculations,
        # snapshot positions, source fingerprints, checkpoints and run metadata.
        retained = repr(
            {
                table.name: session.execute(select(table)).mappings().all()
                for table in Base.metadata.sorted_tables
            }
        )
        for component in forbidden:
            assert component not in retained

    service = PostgresPortfolioService(
        sessions=sessions,
        cursor_signing_key=b"export-privacy-pagination-regression-key",
        clock=lambda: NOW + timedelta(minutes=1),
    )
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("localhost", "testserver"),
    )
    api = create_api_app(settings=settings, service=service, clock=lambda: NOW)
    surfaces = [json.dumps(api.openapi())]
    account_path = f"/api/v1/accounts/{account_id}"
    with TestClient(api, base_url="https://testserver") as client:
        assert client.post("/api/v1/auth/local-session").status_code == 201
        for resource in (
            "",
            "/summary",
            "/positions",
            "/transactions",
            "/dividends",
            "/orders",
            "/snapshots",
            "/snapshots/latest",
            f"/snapshots/{end_id}",
            "/allocation",
            "/performance/summary",
            "/reconciliation",
            "/reconciliation/discrepancies",
            "/data-quality",
            f"/snapshots/compare?start_id={start_id}&end_id={end_id}",
        ):
            response = client.get(account_path + resource)
            assert response.status_code == 200, resource
            surfaces.append(response.text)
        for resource in (
            "/api/v1/me",
            "/api/v1/broker-connections",
            "/api/v1/accounts",
            "/api/v1/instruments",
            "/internal/metrics",
        ):
            response = client.get(resource)
            assert response.status_code == 200, resource
            surfaces.append(response.text)

    runtime = create_runtime(security_settings=settings, service=service, clock=lambda: NOW)
    tools = (
        "get_account_summary",
        "get_portfolio_snapshot",
        "list_positions",
        "list_recent_transactions",
        "get_dividend_summary",
        "get_direct_allocation",
        "compare_portfolio_snapshots",
        "get_reconciliation_status",
        "get_data_quality_summary",
    )
    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        for request_id, name in enumerate(tools, start=1):
            arguments = {"account_id": account_id}
            if name in {"list_recent_transactions", "get_dividend_summary"}:
                arguments.update(start_date="2026-01-01", end_date="2026-09-07")
            if name == "compare_portfolio_snapshots":
                arguments.update(start_snapshot_id=start_id, end_snapshot_id=end_id)
            response = client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            assert response.status_code == 200
            assert response.json()["result"].get("isError") is False, name
            surfaces.append(response.text)
    surfaces.append(caplog.text)
    captured = capsys.readouterr()
    surfaces.extend((captured.out, captured.err))
    for component in forbidden:
        assert all(component not in surface for surface in surfaces)
    assert requests == [("GET", "https://demo.trading212.com/api/v0/equity/history/exports")] * 2


@pytest.mark.asyncio
async def test_legacy_export_fingerprint_transitions_once_to_selected_format(
    privacy_database: Engine,
) -> None:
    token = "_".join(("EXPORT", "URL", "CANARY"))
    host = ".".join(("signed", "example", "invalid"))
    url = f"https://{host}/" + "report" + ".csv?token=" + token
    rotation = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "reportId": 17,
                    "status": "Finished",
                    "timeFrom": "2026-01-01T00:00:00Z",
                    "timeTo": "2026-09-07T00:00:00Z",
                    "dataIncluded": {"includeTransactions": True},
                    "downloadLink": url + f"&rotation={rotation}",
                }
            ],
        )

    client = Trading212Client(
        settings=Trading212Settings(),
        credential_provider=StaticCredentialProvider(
            Trading212Credentials("synthetic-key", "synthetic-secret", BrokerEnvironment.DEMO)
        ),
        credential_reference="secret://synthetic/demo",
        transport=httpx.MockTransport(handler),
        now=lambda: NOW,
    )
    identity = build_synthetic_identity()
    coordinator = IngestionCoordinator(
        provider=Trading212IngestionAdapter(client),
        store=PostgresIngestionStore(
            create_session_factory(privacy_database), provider="synthetic"
        ),
        clock=lambda: NOW,
    )
    try:
        for rotation in range(3):
            run = await coordinator.refresh(
                owner_id=str(identity.owner.id),
                account_id=str(identity.account.id),
                mode=RunMode.FULL,
                idempotency_key=f"legacy-export-format-{rotation}",
                correlation_id=f"legacy-export-format-{rotation}",
                capabilities=(IngestionCapability.EXPORT_METADATA,),
            )
            assert run.status is RunStatus.SUCCEEDED
            step = run.steps[0]
            assert (step.inserted, step.updated, step.unchanged) == (
                (1, 0, 0),
                (0, 1, 0),
                (0, 0, 1),
            )[rotation]
            if rotation == 0:
                # Model the result of the privacy migration: its old-format
                # identity digest is preserved and its URL fields are gone.
                with Session(privacy_database) as session, session.begin():
                    legacy = session.scalar(select(SourceRecordModel))
                    assert legacy is not None
                    legacy.payload_fingerprint = "f" * 64
                    assert legacy.sanitized_payload is not None
                    legacy.sanitized_payload = {
                        key: value
                        for key, value in legacy.sanitized_payload.items()
                        if key != "downloadAvailable"
                    }
        with Session(privacy_database) as session:
            records = session.scalars(select(SourceRecordModel)).all()
            assert len(records) == 2
            assert sum(record.payload_fingerprint == "f" * 64 for record in records) == 1
            assert all(token not in repr(record.sanitized_payload) for record in records)
    finally:
        await client.aclose()
