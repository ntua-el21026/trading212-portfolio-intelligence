from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.testclient import TestClient
from trading212_api.main import create_app as create_api_app
from trading212_application.ingestion import (
    FULL_REFRESH_ORDER,
    IngestionCoordinator,
    RunMode,
    RunStatus,
)
from trading212_domain import build_synthetic_identity
from trading212_mcp.server import create_runtime
from trading212_persistence import (
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import IngestionRunModel
from trading212_persistence.seed import seed_synthetic
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.scenarios import persist_quantity_cash_mismatch_scenario
from trading212_worker.synthetic import SyntheticIngestionProvider

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)


def _base_url() -> str:
    value = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio",
    )
    return value.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def parity_database() -> Iterator[tuple[str, Engine]]:
    parsed = make_url(_base_url())
    database_name = f"t212pi_parity_{uuid4().hex[:12]}"
    admin = parsed.set(database="postgres")
    admin_dsn = admin.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    database_url = parsed.set(database=database_name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    engine: Engine | None = None
    try:
        command.upgrade(config, "head")
        seed_synthetic(database_url, app_environment="test")
        engine = create_database_engine(database_url)
        yield database_url, engine
    finally:
        if engine is not None:
            engine.dispose()
        if not database_name.startswith("t212pi_parity_"):
            raise RuntimeError("refusing to drop an unexpected test database")
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


@pytest.mark.asyncio
async def test_postgres_backed_api_and_mcp_return_identical_canonical_values(
    parity_database: tuple[str, Engine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, engine = parity_database
    identity = build_synthetic_identity()
    account_id = str(identity.account.id)
    sessions = create_session_factory(engine)
    completed = await IngestionCoordinator(
        provider=SyntheticIngestionProvider(clock=lambda: NOW),
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: NOW,
    ).refresh(
        owner_id=str(identity.owner.id),
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key="postgres-api-mcp-parity",
        correlation_id="postgres-api-mcp-parity",
        capabilities=FULL_REFRESH_ORDER,
    )
    assert completed.status is RunStatus.SUCCEEDED
    later = NOW + timedelta(minutes=5)
    updated = await IngestionCoordinator(
        provider=SyntheticIngestionProvider(
            clock=lambda: later,
            current_price=Decimal("600"),
        ),
        store=PostgresIngestionStore(
            sessions,
            provider="synthetic",
            materializer=PostgresCanonicalMaterializer(),
        ),
        clock=lambda: later,
    ).refresh(
        owner_id=str(identity.owner.id),
        account_id=account_id,
        mode=RunMode.INCREMENTAL,
        idempotency_key="postgres-api-mcp-parity-update",
        correlation_id="postgres-api-mcp-parity-update",
        capabilities=FULL_REFRESH_ORDER,
    )
    assert updated.status is RunStatus.SUCCEEDED
    mismatch_at = later + timedelta(seconds=1)
    with Session(engine) as session, session.begin():
        persist_quantity_cash_mismatch_scenario(
            session,
            account_id=identity.account.id,
            listing_id=identity.listing.id,
            as_of=mismatch_at,
        )

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("localhost", "testserver"),
    )
    api = create_api_app(settings=settings, clock=lambda: mismatch_at)
    mcp = create_runtime(
        security_settings=settings,
        database_url=database_url,
        clock=lambda: mismatch_at,
    )
    assert isinstance(api.state.context.service, PostgresPortfolioService)
    assert isinstance(mcp.service, PostgresPortfolioService)

    with TestClient(api, base_url="https://testserver") as api_client:
        assert api_client.post("/api/v1/auth/local-session").status_code == 201
        api_summary = api_client.get(f"/api/v1/accounts/{account_id}/summary")
        api_snapshot = api_client.get(f"/api/v1/accounts/{account_id}/snapshots/latest")
        api_snapshots = api_client.get(
            f"/api/v1/accounts/{account_id}/snapshots",
            params={"limit": 10},
        )
        assert api_snapshots.status_code == 200
        snapshot_rows = api_snapshots.json()["items"]
        assert len(snapshot_rows) == 2
        end_snapshot_id = snapshot_rows[0]["id"]
        start_snapshot_id = snapshot_rows[1]["id"]
        api_allocation = api_client.get(f"/api/v1/accounts/{account_id}/allocation")
        api_comparison = api_client.get(
            f"/api/v1/accounts/{account_id}/snapshots/compare",
            params={"start_id": start_snapshot_id, "end_id": end_snapshot_id},
        )
        api_reconciliation = api_client.get(f"/api/v1/accounts/{account_id}/reconciliation")

    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    with TestClient(mcp.asgi_app(), base_url="http://localhost") as mcp_client:
        mcp_summary = _call_tool(
            mcp_client,
            headers,
            request_id=1,
            name="get_account_summary",
            arguments={"account_id": account_id},
        )
        mcp_snapshot = _call_tool(
            mcp_client,
            headers,
            request_id=2,
            name="get_portfolio_snapshot",
            arguments={"account_id": account_id},
        )
        mcp_allocation = _call_tool(
            mcp_client,
            headers,
            request_id=3,
            name="get_direct_allocation",
            arguments={"account_id": account_id, "top_n": 25},
        )
        mcp_comparison = _call_tool(
            mcp_client,
            headers,
            request_id=4,
            name="compare_portfolio_snapshots",
            arguments={
                "account_id": account_id,
                "start_snapshot_id": start_snapshot_id,
                "end_snapshot_id": end_snapshot_id,
            },
        )
        mcp_reconciliation = _call_tool(
            mcp_client,
            headers,
            request_id=5,
            name="get_reconciliation_status",
            arguments={"account_id": account_id, "issue_limit": 25},
        )

    assert api_summary.status_code == 200
    assert api_snapshot.status_code == 200
    assert mcp_summary.status_code == 200
    assert mcp_snapshot.status_code == 200
    assert api_allocation.status_code == 200
    assert api_comparison.status_code == 200
    assert mcp_allocation.status_code == 200
    assert mcp_comparison.status_code == 200
    assert api_reconciliation.status_code == 200
    assert mcp_reconciliation.status_code == 200
    api_data = api_summary.json()
    mcp_data = mcp_summary.json()["result"]["structuredContent"]["data"]
    for field in (
        "total_value",
        "cash_balance",
        "invested_value",
        "net_contributions",
        "dividends_received",
        "realized_profit_loss",
        "unrealized_profit_loss",
    ):
        assert mcp_data[field] == api_data[field]
    mcp_snapshot_data = mcp_snapshot.json()["result"]["structuredContent"]["data"]
    assert mcp_snapshot_data["id"] == api_snapshot.json()["id"]
    assert mcp_snapshot_data["total_value"] == api_snapshot.json()["total_value"]

    mcp_allocation_data = mcp_allocation.json()["result"]["structuredContent"]["data"]
    assert mcp_allocation_data["allocations"] == api_allocation.json()
    assert mcp_allocation_data["includes_cash"] is True
    assert sum(Decimal(row["weight"]) for row in api_allocation.json()) == Decimal("1")

    api_comparison_data = api_comparison.json()
    mcp_comparison_data = mcp_comparison.json()["result"]["structuredContent"]["data"]
    assert mcp_comparison_data["start"]["id"] == api_comparison_data["start"]["id"]
    assert mcp_comparison_data["end"]["id"] == api_comparison_data["end"]["id"]
    for field in (
        "value_change",
        "net_external_flows",
        "investment_result",
        "reconciliation_residual",
    ):
        assert mcp_comparison_data[field] == api_comparison_data[field]
    assert api_comparison_data["value_change"]["value"] == "4000"
    assert api_comparison_data["net_external_flows"]["value"] == "0"
    assert api_comparison_data["investment_result"]["value"] == "4000"
    assert api_comparison_data["reconciliation_residual"]["value"] == "0"

    api_reconciliation_data = api_reconciliation.json()
    mcp_reconciliation_envelope = mcp_reconciliation.json()["result"]["structuredContent"]
    mcp_reconciliation_data = mcp_reconciliation_envelope["data"]
    assert api_reconciliation_data["status"] == "unreconciled"
    assert mcp_reconciliation_data["status"] == api_reconciliation_data["status"]
    assert mcp_reconciliation_data["evaluated_at"] == api_reconciliation_data["evaluated_at"]
    assert (
        mcp_reconciliation_data["algorithm_version"] == api_reconciliation_data["algorithm_version"]
    )
    assert (
        mcp_reconciliation_data["tolerance_version"] == api_reconciliation_data["tolerance_version"]
    )
    assert mcp_reconciliation_data["discrepancy_count"] == 2
    assert mcp_reconciliation_data["issues"] == api_reconciliation_data["issues"]
    assert {issue["issue_type"] for issue in api_reconciliation_data["issues"]} == {
        "cash_mismatch",
        "quantity_mismatch",
    }
    api_reconciliation_quality = api_reconciliation_data["data_quality"]
    mcp_reconciliation_quality = mcp_reconciliation_envelope["data_quality"]
    assert (
        mcp_reconciliation_quality["state"] == api_reconciliation_quality["state"] == "unreconciled"
    )
    assert (
        mcp_reconciliation_quality["source_cutoff_at"]
        == api_reconciliation_quality["source_timestamp"]
    )
    assert (
        mcp_reconciliation_quality["freshness_threshold_seconds"]
        == api_reconciliation_quality["freshness_threshold_seconds"]
    )
    assert mcp_reconciliation_quality["warnings"] == api_reconciliation_quality["warnings"]
    assert (
        mcp_reconciliation_quality["missing_inputs"] == api_reconciliation_quality["missing_inputs"]
    )

    with Session(engine) as session, session.begin():
        session.add(
            IngestionRunModel(
                id=uuid4(),
                broker_account_id=identity.account.id,
                capability="portfolio_positions",
                mode="incremental",
                status="partial",
                idempotency_key="postgres-api-mcp-partial-overlay",
                correlation_id="postgres-api-mcp-partial-overlay",
                started_at=later + timedelta(minutes=1),
                heartbeat_at=later + timedelta(minutes=1),
                completed_at=later + timedelta(minutes=1),
                request_count=1,
                records_received=0,
                records_normalized=0,
                records_rejected=0,
                warnings=[
                    {
                        "capability": "portfolio_positions",
                        "status": "failed",
                        "pages": 0,
                        "records_seen": 0,
                        "inserted": 0,
                        "updated": 0,
                        "unchanged": 0,
                        "warnings": [],
                        "failure_category": "transient",
                        "failure_message": "sanitized upstream failure",
                    }
                ],
                error_code="transient",
            )
        )

    with TestClient(api, base_url="https://testserver") as api_client:
        assert api_client.post("/api/v1/auth/local-session").status_code == 201
        degraded_summary = api_client.get(f"/api/v1/accounts/{account_id}/summary")
        degraded_quality = api_client.get(f"/api/v1/accounts/{account_id}/data-quality")
    principal = Principal(
        principal_id="partial-overlay-principal",
        owner_id=str(identity.owner.id),
        issuer="local.synthetic",
        subject="synthetic-owner",
        scopes=frozenset({Scope.PORTFOLIO_READ, Scope.ACTIVITY_READ}),
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    await mcp.service.get_summary(principal, account_id)
    await mcp.service.list_snapshots(principal, account_id, cursor=None, limit=1)
    await mcp.service.list_positions(principal, account_id, cursor=None, limit=1)
    await mcp.service.list_activity(principal, account_id, cursor=None, limit=1)
    await mcp.service.list_dividends(principal, account_id, cursor=None, limit=1)
    await mcp.service.get_reconciliation(principal, account_id)
    with TestClient(mcp.asgi_app(), base_url="http://localhost") as mcp_client:
        mcp_quality = _call_tool(
            mcp_client,
            headers,
            request_id=6,
            name="get_data_quality_summary",
            arguments={"account_id": account_id},
        )

    assert degraded_summary.status_code == 200
    assert degraded_quality.status_code == 200
    assert degraded_summary.json()["total_value"] == api_data["total_value"]
    assert degraded_quality.json()["state"] == "unreconciled"
    assert degraded_quality.json()["missing_inputs"] == ["portfolio_positions"]
    assert "retained prior canonical snapshot" in " ".join(degraded_quality.json()["warnings"])
    assert mcp_quality.status_code == 200
    mcp_quality_data = mcp_quality.json()["result"]["structuredContent"]
    assert mcp_quality_data["error"] is None, mcp_quality_data
    assert mcp_quality_data["data_quality"]["state"] == "unreconciled"
    assert mcp_quality_data["data_quality"]["missing_inputs"] == ["portfolio_positions"]
    assert mcp_quality_data["data"]["capabilities"][0]["data_quality"]["state"] == "unreconciled"


def _call_tool(
    client: TestClient,
    headers: dict[str, str],
    *,
    request_id: int,
    name: str,
    arguments: dict[str, Any],
) -> Any:
    return client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
