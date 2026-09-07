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
from sqlalchemy import Engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.testclient import TestClient
from trading212_api.main import create_app as create_api_app
from trading212_application.ingestion import (
    FULL_REFRESH_ORDER,
    IngestionCapability,
    IngestionCoordinator,
    RunMode,
    RunStatus,
)
from trading212_application.queries import (
    ActivityQuery,
    DividendQuery,
    PageQuery,
    PositionQuery,
)
from trading212_application.refresh_semantics import RefreshRequestSemantics
from trading212_domain import build_synthetic_identity
from trading212_mcp.server import create_runtime
from trading212_persistence import (
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import (
    CashFlowModel,
    CollectionQuerySnapshotMemberModel,
    CollectionQuerySnapshotModel,
    IngestionCheckpointModel,
    IngestionRunModel,
    PortfolioSnapshotModel,
    ReconciliationDiscrepancyModel,
    ReconciliationRunModel,
    SourceRecordModel,
    TransactionModel,
)
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
async def test_hard_collection_capacity_reaches_api_and_mcp_without_cursor_state(
    parity_database: tuple[str, Engine],
) -> None:
    _, engine = parity_database
    identity = build_synthetic_identity()
    account_id = str(identity.account.id)
    sessions = create_session_factory(engine)
    completed = await IngestionCoordinator(
        provider=SyntheticIngestionProvider(clock=lambda: NOW),
        store=PostgresIngestionStore(
            sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
        ),
        clock=lambda: NOW,
    ).refresh(
        owner_id=str(identity.owner.id),
        account_id=account_id,
        mode=RunMode.FULL,
        idempotency_key="hard-capacity-interface-regression",
        correlation_id="hard-capacity-interface-regression",
        capabilities=FULL_REFRESH_ORDER,
    )
    assert completed.status is RunStatus.SUCCEEDED
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(TransactionModel)) == 2
    service = PostgresPortfolioService(
        sessions=sessions,
        cursor_signing_key=b"hard-capacity-interface-regression-key",
        clock=lambda: NOW,
        max_active_collection_members_per_owner=1,
    )
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("localhost", "testserver"),
    )
    api = create_api_app(settings=settings, service=service, clock=lambda: NOW)
    with TestClient(api, base_url="https://testserver") as client:
        assert client.post("/api/v1/auth/local-session").status_code == 201
        # A failed first attempt must not leave resumable state or alter retries.
        for _ in range(2):
            response = client.get(f"/api/v1/accounts/{account_id}/transactions")
            assert response.status_code == 429
            assert response.json()["error"] == {
                "code": "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
                "message": "Active pagination capacity is temporarily exhausted.",
                "correlation_id": response.headers["x-correlation-id"],
                "retryable": True,
                "details": {},
            }
            for forbidden in (account_id, str(identity.owner.id), "next_cursor", "total"):
                assert forbidden not in response.text

    runtime = create_runtime(security_settings=settings, service=service, clock=lambda: NOW)
    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        response = _call_tool(
            client,
            {"Accept": "application/json, text/event-stream"},
            request_id=1,
            name="list_recent_transactions",
            arguments={
                "account_id": account_id,
                "limit": 1,
                "start_date": "2026-01-01",
                "end_date": "2026-08-31",
            },
        )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == ("COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED")
    assert len(response.content) < 2_048
    for forbidden in (account_id, str(identity.owner.id), "next_cursor", "snapshot_id"):
        assert forbidden not in response.text
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CollectionQuerySnapshotModel)) == 0
        assert (
            session.scalar(select(func.count()).select_from(CollectionQuerySnapshotMemberModel))
            == 0
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
    later = NOW + timedelta(days=365)
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

    # This controlled fixture supplies the complete opening-history assertion that
    # the real provider cannot infer. It makes the latest deterministic material
    # inputs explicitly reconciled so the application coverage gate may open.
    with Session(engine) as session, session.begin():
        complete_reconciliation = session.scalar(
            select(ReconciliationRunModel)
            .where(ReconciliationRunModel.broker_account_id == identity.account.id)
            .order_by(ReconciliationRunModel.as_of.desc(), ReconciliationRunModel.id.desc())
            .limit(1)
        )
        assert complete_reconciliation is not None
        complete_reconciliation.status = "reconciled"
        complete_reconciliation.quality_state = "fresh"
        complete_reconciliation.coverage_complete = True
        complete_reconciliation.coverage_gaps = []
        complete_reconciliation.discrepancy_count = 0
        complete_reconciliation.warnings = []
        reconciliation_id = complete_reconciliation.id
        reconciliation_coverage_start = complete_reconciliation.coverage_start_at
        transaction_checkpoint = session.scalar(
            select(IngestionCheckpointModel).where(
                IngestionCheckpointModel.broker_account_id == identity.account.id,
                IngestionCheckpointModel.capability == IngestionCapability.TRANSACTIONS.value,
            )
        )
        assert transaction_checkpoint is not None
        transaction_checkpoint.coverage_start_at = NOW
        transaction_checkpoint.coverage_end_at = later
        transaction_checkpoint.coverage_complete = True

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("localhost", "testserver"),
    )
    available_performance_api = create_api_app(settings=settings, clock=lambda: later)
    with TestClient(available_performance_api, base_url="https://testserver") as api_client:
        assert api_client.post("/api/v1/auth/local-session").status_code == 201
        available_performance = api_client.get(f"/api/v1/accounts/{account_id}/performance/summary")
    assert available_performance.status_code == 200
    performance_data = available_performance.json()
    assert performance_data["time_weighted_return"]["availability"] == "available", performance_data
    assert performance_data["time_weighted_return"]["value"] == "0.016101032692060062"
    assert performance_data["modified_dietz_return"]["availability"] == "available"
    assert performance_data["modified_dietz_return"]["value"] == "0.016101032692060062"
    assert performance_data["money_weighted_return"]["availability"] == "available"
    assert performance_data["money_weighted_return"]["value"] == "0.016101032692060062"
    assert performance_data["time_weighted_return"]["method_id"] == "snapshot_subperiod_twr"
    assert performance_data["data_quality"]["state"] == "stale"

    with Session(engine) as session, session.begin():
        stale_reconciliation = session.get(ReconciliationRunModel, reconciliation_id)
        assert stale_reconciliation is not None
        stale_reconciliation.quality_state = "stale"
    with TestClient(available_performance_api, base_url="https://testserver") as api_client:
        assert api_client.post("/api/v1/auth/local-session").status_code == 201
        stale_performance = api_client.get(f"/api/v1/accounts/{account_id}/performance/summary")
        stale_quality = api_client.get(f"/api/v1/accounts/{account_id}/data-quality")
    assert stale_performance.status_code == 200
    assert stale_performance.json()["money_weighted_return"]["availability"] == "unavailable"
    assert (
        "fresh_reconciliation_inputs"
        in stale_performance.json()["money_weighted_return"]["missing_inputs"]
    )
    assert stale_quality.status_code == 200
    assert stale_quality.json()["materialization_state"] == "partial"
    assert stale_quality.json()["reconciliation_status"] == "partial"

    with Session(engine) as session, session.begin():
        incomplete_reconciliation = session.get(ReconciliationRunModel, reconciliation_id)
        assert incomplete_reconciliation is not None
        incomplete_reconciliation.quality_state = "fresh"
        incomplete_reconciliation.coverage_complete = False
        incomplete_reconciliation.coverage_gaps = ["opening_history"]
    with TestClient(available_performance_api, base_url="https://testserver") as api_client:
        assert api_client.post("/api/v1/auth/local-session").status_code == 201
        incomplete_performance = api_client.get(
            f"/api/v1/accounts/{account_id}/performance/summary"
        )
        incomplete_quality = api_client.get(f"/api/v1/accounts/{account_id}/data-quality")
    assert incomplete_performance.status_code == 200
    assert (
        "complete_reconciliation_coverage"
        in incomplete_performance.json()["money_weighted_return"]["missing_inputs"]
    )
    assert incomplete_quality.status_code == 200
    assert incomplete_quality.json()["materialization_state"] == "partial"
    assert incomplete_quality.json()["reconciliation_status"] == "partial"

    with Session(engine) as session, session.begin():
        narrow_reconciliation = session.get(ReconciliationRunModel, reconciliation_id)
        assert narrow_reconciliation is not None
        narrow_reconciliation.coverage_complete = True
        narrow_reconciliation.coverage_gaps = []
        narrow_reconciliation.coverage_start_at = NOW + timedelta(seconds=1)
    with TestClient(available_performance_api, base_url="https://testserver") as api_client:
        assert api_client.post("/api/v1/auth/local-session").status_code == 201
        narrow_performance = api_client.get(f"/api/v1/accounts/{account_id}/performance/summary")
    assert narrow_performance.status_code == 200
    assert (
        "reconciliation_coverage_at_period_start"
        in narrow_performance.json()["money_weighted_return"]["missing_inputs"]
    )

    with Session(engine) as session, session.begin():
        old_reconciliation = session.get(ReconciliationRunModel, reconciliation_id)
        assert old_reconciliation is not None
        old_reconciliation.coverage_start_at = reconciliation_coverage_start
        old_reconciliation.coverage_end_at = later - timedelta(seconds=1)
        old_reconciliation.as_of = later - timedelta(seconds=1)
    with TestClient(available_performance_api, base_url="https://testserver") as api_client:
        assert api_client.post("/api/v1/auth/local-session").status_code == 201
        old_performance = api_client.get(f"/api/v1/accounts/{account_id}/performance/summary")
    assert old_performance.status_code == 200
    assert (
        "reconciliation_coverage_at_period_end"
        in old_performance.json()["money_weighted_return"]["missing_inputs"]
    )
    assert (
        "reconciliation_at_period_end"
        in old_performance.json()["money_weighted_return"]["missing_inputs"]
    )
    with Session(engine) as session, session.begin():
        restored_reconciliation = session.get(ReconciliationRunModel, reconciliation_id)
        assert restored_reconciliation is not None
        restored_reconciliation.coverage_end_at = later
        restored_reconciliation.as_of = later

    reversed_transaction_id = uuid4()
    reversed_flow_id = uuid4()
    ambiguous_transaction_id = uuid4()
    with Session(engine) as session, session.begin():
        fixture_source = session.scalar(
            select(SourceRecordModel)
            .where(SourceRecordModel.broker_account_id == identity.account.id)
            .order_by(SourceRecordModel.id)
            .limit(1)
        )
        assert fixture_source is not None
        session.add(
            TransactionModel(
                id=reversed_transaction_id,
                broker_account_id=identity.account.id,
                provider_transaction_id="performance-reversed-deposit",
                transaction_type="deposit",
                status="reversed",
                instrument_listing_id=None,
                quantity=None,
                unit_price=None,
                gross_amount=None,
                fees=None,
                taxes=None,
                net_cash_amount=Decimal("100000"),
                currency="EUR",
                occurred_at=NOW + timedelta(days=180),
                settlement_date=None,
                source_record_id=fixture_source.id,
                mapping_version="performance-reversal-fixture/1",
            )
        )
        session.flush()
        session.add(
            CashFlowModel(
                id=reversed_flow_id,
                broker_account_id=identity.account.id,
                source_transaction_id=reversed_transaction_id,
                classification="external",
                flow_type="deposit",
                amount=Decimal("100000"),
                currency="EUR",
                occurred_at=NOW + timedelta(days=180),
                quality="fresh",
                active=False,
                idempotency_key="performance-reversed-deposit",
                source_record_id=fixture_source.id,
            )
        )
    with TestClient(available_performance_api, base_url="https://testserver") as api_client:
        assert api_client.post("/api/v1/auth/local-session").status_code == 201
        after_reversal = api_client.get(f"/api/v1/accounts/{account_id}/performance/summary")
    assert after_reversal.status_code == 200
    assert (
        after_reversal.json()["money_weighted_return"]["value"]
        == performance_data["money_weighted_return"]["value"]
    )

    with Session(engine) as session, session.begin():
        fixture_source = session.scalar(
            select(SourceRecordModel)
            .where(SourceRecordModel.broker_account_id == identity.account.id)
            .order_by(SourceRecordModel.id)
            .limit(1)
        )
        assert fixture_source is not None
        session.add(
            TransactionModel(
                id=ambiguous_transaction_id,
                broker_account_id=identity.account.id,
                provider_transaction_id="performance-ambiguous-cash-activity",
                transaction_type="adjustment",
                status="posted",
                instrument_listing_id=None,
                quantity=None,
                unit_price=None,
                gross_amount=None,
                fees=None,
                taxes=None,
                net_cash_amount=Decimal("1000"),
                currency="EUR",
                occurred_at=NOW + timedelta(days=180),
                settlement_date=None,
                source_record_id=fixture_source.id,
                mapping_version="performance-ambiguous-fixture/1",
            )
        )
    with TestClient(available_performance_api, base_url="https://testserver") as api_client:
        assert api_client.post("/api/v1/auth/local-session").status_code == 201
        ambiguous_performance = api_client.get(f"/api/v1/accounts/{account_id}/performance/summary")
    assert ambiguous_performance.status_code == 200
    assert ambiguous_performance.json()["money_weighted_return"]["availability"] == "unavailable"
    assert (
        "unambiguous_external_flow_classification"
        in ambiguous_performance.json()["money_weighted_return"]["missing_inputs"]
    )
    with Session(engine) as session, session.begin():
        ambiguous = session.get(TransactionModel, ambiguous_transaction_id)
        assert ambiguous is not None
        session.delete(ambiguous)

    duplicate_snapshot_id = uuid4()
    with Session(engine) as session, session.begin():
        latest_snapshot = session.scalar(
            select(PortfolioSnapshotModel)
            .where(PortfolioSnapshotModel.broker_account_id == identity.account.id)
            .order_by(
                PortfolioSnapshotModel.valuation_at.desc(),
                PortfolioSnapshotModel.id.desc(),
            )
            .limit(1)
        )
        assert latest_snapshot is not None
        session.add(
            PortfolioSnapshotModel(
                id=duplicate_snapshot_id,
                broker_account_id=latest_snapshot.broker_account_id,
                calculation_run_id=latest_snapshot.calculation_run_id,
                valuation_at=latest_snapshot.valuation_at,
                source_cutoff_at=latest_snapshot.source_cutoff_at,
                reporting_currency=latest_snapshot.reporting_currency,
                cash_total=latest_snapshot.cash_total,
                invested_total=latest_snapshot.invested_total,
                portfolio_total=latest_snapshot.portfolio_total,
                net_contributions=latest_snapshot.net_contributions,
                calculation_version="duplicate-revision-fixture",
                quality_state=latest_snapshot.quality_state,
                coverage=latest_snapshot.coverage,
                warnings=latest_snapshot.warnings,
            )
        )
    with TestClient(available_performance_api, base_url="https://testserver") as api_client:
        assert api_client.post("/api/v1/auth/local-session").status_code == 201
        duplicate_performance = api_client.get(f"/api/v1/accounts/{account_id}/performance/summary")
    assert duplicate_performance.status_code == 200
    assert duplicate_performance.json()["money_weighted_return"]["availability"] == ("unavailable")
    assert (
        "unique_snapshot_valuation_revisions"
        in duplicate_performance.json()["money_weighted_return"]["missing_inputs"]
    )
    with Session(engine) as session, session.begin():
        duplicate_snapshot = session.get(PortfolioSnapshotModel, duplicate_snapshot_id)
        assert duplicate_snapshot is not None
        session.delete(duplicate_snapshot)

    mismatch_at = later + timedelta(seconds=1)
    with Session(engine) as session, session.begin():
        persist_quantity_cash_mismatch_scenario(
            session,
            account_id=identity.account.id,
            listing_id=identity.listing.id,
            as_of=mismatch_at,
        )
        fx_reconciliation = session.scalar(
            select(ReconciliationRunModel)
            .where(
                ReconciliationRunModel.broker_account_id == identity.account.id,
                ReconciliationRunModel.as_of == mismatch_at,
            )
            .limit(1)
        )
        assert fx_reconciliation is not None
        for sequence in range(2):
            session.add(
                ReconciliationDiscrepancyModel(
                    id=uuid4(),
                    reconciliation_run_id=fx_reconciliation.id,
                    broker_account_id=identity.account.id,
                    listing_id=identity.listing.id,
                    discrepancy_type="currency_fx_gap",
                    severity="warning",
                    resolution_state="open",
                    expected_value=None,
                    observed_value=None,
                    residual=None,
                    tolerance=None,
                    currency="USD",
                    first_seen_at=mismatch_at,
                    last_seen_at=mismatch_at + timedelta(microseconds=sequence),
                    likely_cause="missing explicit FX fixture",
                    downstream_effect="Reporting-currency valuation remains unavailable.",
                    resolution_reason=None,
                    resolved_at=None,
                    resolved_by_principal_id=None,
                    provenance={"fixture": "deduplicated-latest-reconciliation-fx-gap"},
                )
            )
        fx_reconciliation.discrepancy_count += 2

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
        api_old_snapshot = api_client.get(
            f"/api/v1/accounts/{account_id}/snapshots/{start_snapshot_id}"
        )
        api_allocation = api_client.get(f"/api/v1/accounts/{account_id}/allocation")
        api_comparison = api_client.get(
            f"/api/v1/accounts/{account_id}/snapshots/compare",
            params={"start_id": start_snapshot_id, "end_id": end_snapshot_id},
        )
        api_reconciliation = api_client.get(f"/api/v1/accounts/{account_id}/reconciliation")
        api_discrepancies = api_client.get(
            f"/api/v1/accounts/{account_id}/reconciliation/discrepancies",
            params={"limit": 25},
        )
        api_connections = api_client.get("/api/v1/broker-connections")
        api_positions = api_client.get(
            f"/api/v1/accounts/{account_id}/positions",
            params={"limit": 50, "sort": "market_value_desc", "search": "SYNEQ"},
        )
        api_transactions = api_client.get(
            f"/api/v1/accounts/{account_id}/transactions",
            params={
                "limit": 50,
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "activity_type": "all",
            },
        )

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
        mcp_old_snapshot = _call_tool(
            mcp_client,
            headers,
            request_id=9,
            name="get_portfolio_snapshot",
            arguments={"account_id": account_id, "snapshot_id": start_snapshot_id},
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
        mcp_positions = _call_tool(
            mcp_client,
            headers,
            request_id=7,
            name="list_positions",
            arguments={
                "account_id": account_id,
                "limit": 50,
                "sort": "market_value_desc",
                "search": "SYNEQ",
            },
        )
        mcp_transactions = _call_tool(
            mcp_client,
            headers,
            request_id=8,
            name="list_recent_transactions",
            arguments={
                "account_id": account_id,
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "type_filter": "all",
                "limit": 50,
            },
        )

    assert api_summary.status_code == 200
    assert api_snapshot.status_code == 200
    assert api_old_snapshot.status_code == 200
    assert mcp_summary.status_code == 200
    assert mcp_snapshot.status_code == 200
    assert mcp_old_snapshot.status_code == 200
    assert api_allocation.status_code == 200
    assert api_comparison.status_code == 200
    assert mcp_allocation.status_code == 200
    assert mcp_comparison.status_code == 200
    assert api_reconciliation.status_code == 200
    assert api_discrepancies.status_code == 200
    assert mcp_reconciliation.status_code == 200
    assert api_connections.status_code == 200
    assert api_positions.status_code == 200
    assert api_transactions.status_code == 200
    assert mcp_positions.status_code == 200
    assert mcp_transactions.status_code == 200

    connections = api_connections.json()
    assert connections == [
        {
            "id": str(identity.connection.id),
            "provider": "synthetic",
            "environment": "synthetic",
            "status": "active",
            "state": "active",
            "credential_state": "configured",
            "last_successful_refresh_at": later.isoformat().replace("+00:00", "Z"),
            "read_only": True,
        }
    ]
    assert "credential_reference" not in connections[0]
    assert "synthetic://" not in str(connections)

    api_position_page = api_positions.json()
    mcp_position_envelope = mcp_positions.json()["result"]["structuredContent"]
    assert mcp_position_envelope["pagination"]["total"] == api_position_page["total"] == 1
    assert mcp_position_envelope["pagination"]["next_cursor"] == api_position_page["next_cursor"]
    api_position = api_position_page["items"][0]
    mcp_position = mcp_position_envelope["data"]["positions"][0]
    for field in (
        "id",
        "ticker",
        "name",
        "instrument_type",
        "quantity",
        "trading_currency",
        "current_price",
        "market_value",
        "provider_cost_basis",
        "provider_unrealized_profit_loss",
        "direct_weight",
    ):
        assert mcp_position[field] == api_position[field]

    api_transaction_page = api_transactions.json()
    mcp_transaction_envelope = mcp_transactions.json()["result"]["structuredContent"]
    assert mcp_transaction_envelope["pagination"]["total"] == api_transaction_page["total"]
    assert [row["id"] for row in mcp_transaction_envelope["data"]["transactions"]] == [
        row["id"] for row in api_transaction_page["items"]
    ]
    for api_row, mcp_row in zip(
        api_transaction_page["items"],
        mcp_transaction_envelope["data"]["transactions"],
        strict=True,
    ):
        for field in (
            "occurred_at",
            "activity_type",
            "direction",
            "amount",
            "ticker",
            "quantity",
            "description",
        ):
            assert mcp_row[field] == api_row[field]
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
    api_old_snapshot_data = api_old_snapshot.json()
    mcp_old_snapshot_data = mcp_old_snapshot.json()["result"]["structuredContent"]["data"]
    assert api_old_snapshot_data["id"] == start_snapshot_id
    assert mcp_old_snapshot_data["id"] == start_snapshot_id
    assert api_old_snapshot_data["total_value"] != api_snapshot.json()["total_value"]
    for field in (
        "dividends_received",
        "realized_profit_loss",
        "unrealized_profit_loss",
    ):
        assert api_old_snapshot_data[field]["availability"] == "unavailable"
        assert mcp_old_snapshot_data[field] == api_old_snapshot_data[field]
        assert mcp_snapshot_data[field] == api_snapshot.json()[field]
    assert api_summary.json()["dividends_received"]["availability"] == "available"
    assert api_old_snapshot_data["dividends_received"] != api_summary.json()["dividends_received"]

    mcp_allocation_data = mcp_allocation.json()["result"]["structuredContent"]["data"]
    api_allocation_data = api_allocation.json()
    mcp_allocation_pagination = mcp_allocation.json()["result"]["structuredContent"]["pagination"]
    assert mcp_allocation_data["allocations"] == api_allocation_data["items"]
    assert mcp_allocation_data["returned_count"] == api_allocation_data["returned_count"]
    assert mcp_allocation_pagination["total"] == api_allocation_data["total"]
    assert mcp_allocation_pagination["limit"] == 25
    assert api_allocation_data["limit"] == 50
    assert mcp_allocation_pagination["truncated"] == api_allocation_data["truncated"]
    assert mcp_allocation_data["includes_cash"] is True
    assert sum(Decimal(row["weight"]) for row in api_allocation_data["items"]) == Decimal("1")

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
    assert mcp_reconciliation_data["discrepancy_count"] == 4
    assert mcp_reconciliation_data["issues"] == api_discrepancies.json()["items"]
    assert {issue["issue_type"] for issue in api_discrepancies.json()["items"]} == {
        "cash_mismatch",
        "currency_fx_gap",
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

    overlay_semantics = RefreshRequestSemantics.create(
        owner_id=identity.owner.id,
        account_id=identity.account.id,
        mode=RunMode.INCREMENTAL,
        capabilities=FULL_REFRESH_ORDER,
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
                request_schema_version=overlay_semantics.schema_version,
                requested_mode=overlay_semantics.mode.value,
                requested_create_snapshot=overlay_semantics.create_snapshot,
                requested_capabilities=overlay_semantics.capability_values,
                effective_capabilities=overlay_semantics.capability_values,
                request_fingerprint=overlay_semantics.fingerprint,
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
        authenticated_at=mismatch_at,
        expires_at=mismatch_at + timedelta(hours=1),
    )
    await mcp.service.get_summary(principal, account_id)
    await mcp.service.list_snapshots(principal, account_id, query=PageQuery(limit=1))
    await mcp.service.list_positions(principal, account_id, query=PositionQuery(limit=1))
    await mcp.service.list_activity(principal, account_id, query=ActivityQuery(limit=1))
    await mcp.service.list_dividends(principal, account_id, query=DividendQuery(limit=1))
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
    api_quality_data = degraded_quality.json()
    assert api_quality_data["data_quality"]["state"] == "unreconciled"
    assert {
        "external_flow_fx_conversion",
        "portfolio_positions",
    }.issubset(api_quality_data["data_quality"]["missing_inputs"])
    assert api_quality_data["missing_fx_record_count"] == 1
    assert "retained prior canonical snapshot" in " ".join(
        api_quality_data["data_quality"]["warnings"]
    )
    assert api_quality_data["latest_refresh_run"]["status"] == "partial"
    assert api_quality_data["latest_refresh_run"]["steps"][0]["capability"] == (
        "portfolio_positions"
    )
    assert any(item["status"] == "partial" for item in api_quality_data["latest_runs_by_status"])
    assert api_quality_data["materialization_state"] == "partial"
    assert mcp_quality.status_code == 200
    mcp_quality_data = mcp_quality.json()["result"]["structuredContent"]
    assert mcp_quality_data["error"] is None, mcp_quality_data
    assert mcp_quality_data["data_quality"]["state"] == "unreconciled"
    assert (
        mcp_quality_data["data_quality"]["missing_inputs"]
        == api_quality_data["data_quality"]["missing_inputs"]
    )
    assert mcp_quality_data["data"]["capabilities"][0]["data_quality"]["state"] == "unreconciled"
    assert mcp_quality_data["data"]["latest_refresh_run"] == api_quality_data["latest_refresh_run"]
    assert (
        mcp_quality_data["data"]["latest_runs_by_status"]
        == api_quality_data["latest_runs_by_status"]
    )
    assert mcp_quality_data["data"]["checkpoints"] == api_quality_data["checkpoints"]
    for field in (
        "latest_snapshot_id",
        "latest_snapshot_source_cutoff_at",
        "materialization_state",
        "reconciliation_status",
        "missing_fx_record_count",
        "unknown_mapping_record_count",
    ):
        assert mcp_quality_data["data"][field] == api_quality_data[field]


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
