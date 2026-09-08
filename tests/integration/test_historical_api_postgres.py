"""Historical HTTP/MCP reads share persisted captures and enforce ownership boundaries."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult
from psycopg import sql
from sqlalchemy import Engine, func, select
from sqlalchemy.engine import make_url
from trading212_api.main import create_app
from trading212_domain import build_synthetic_identity
from trading212_domain.sources import LicensePermission, SourceLicense
from trading212_mcp.server import create_runtime
from trading212_persistence import (
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence import historical_models as hm
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_persistence.source_models import BenchmarkVersionModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_provider.client import Trading212Client
from trading212_reference_data.replay import (
    ReplayBenchmarkProvider,
    ReplayFxReferenceProvider,
    ReplayMarketPriceHistoryProvider,
)
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.historical_fixture import HISTORY_RECEIPT, build_history_scenario, history_id
from trading212_worker.historical_seed import history_principal, seed_historical_scenarios
from trading212_worker.historical_target_seed import seed_historical_target
from trading212_worker.seed import seed_materialized_synthetic

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
ACCOUNT = str(build_synthetic_identity().account.id)
KEY = b"historical-api-synthetic-cursor-key-v1"
HEADERS = {"Authorization": "Bearer historical-owned"}
QUERY = {
    "start_date": "2026-08-01",
    "end_date": "2026-08-31",
    "source_cutoff_at": NOW.isoformat(),
    "reporting_currency": "EUR",
}
OPERATIONS = (
    ("get_performance_series", "performance/series"),
    ("get_performance_summary", "performance/intelligence"),
    ("get_benchmark_comparison", "benchmark-comparison"),
    ("get_attribution_summary", "attribution"),
    ("get_dividend_intelligence", "dividend-intelligence"),
    ("get_cash_flow_intelligence", "cash-flow-intelligence"),
)
METHODS = {
    "get_performance_series": "performance_v2",
    "get_performance_summary": "performance_v2",
    "get_benchmark_comparison": "benchmark_comparison_v1",
    "get_attribution_summary": "attribution_bridge_v1",
    "get_dividend_intelligence": "income_v1",
    "get_cash_flow_intelligence": "cash_flow_intelligence_v1",
}


@pytest.fixture(scope="module")
def historical_api_database() -> Iterator[Engine]:
    parsed = make_url(
        os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio"
        )
    )
    name = "t212pi_historical_api_" + uuid4().hex[:12]
    admin = parsed.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = parsed.set(drivername="postgresql+psycopg", database=name).render_as_string(
        hide_password=False
    )
    engine = None
    try:
        configuration = Config("alembic.ini")
        configuration.set_main_option("sqlalchemy.url", url)
        command.upgrade(configuration, "head")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


class _Bearer:
    async def authenticate(self, token: str) -> Principal:
        if token not in {"historical-owned", "historical-foreign", "historical-summary-only"}:
            raise AuthenticationError("Invalid synthetic credential.")
        identity = build_synthetic_identity()
        return Principal(
            str(identity.principal.id),
            str(uuid4()) if token == "historical-foreign" else str(identity.owner.id),
            "test",
            "test",
            frozenset(Scope) - {Scope.ACTIVITY_READ}
            if token == "historical-summary-only"
            else frozenset(Scope),
            NOW - timedelta(hours=1),
            NOW + timedelta(hours=1),
        )


def _runtime(engine: Engine) -> tuple[FastAPI, MCPServer[Any]]:
    sessions = create_session_factory(engine)
    historical = PostgresHistoricalService(sessions, cursor_signing_key=KEY, clock=lambda: NOW)
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("testserver",),
    )
    portfolio = PostgresPortfolioService(
        sessions=sessions, cursor_signing_key=KEY, clock=lambda: NOW
    )
    application = create_app(
        settings=settings,
        service=portfolio,
        historical_service=historical,
        source_service=PostgresSourceService(
            sessions=sessions, cursor_signing_key=KEY, clock=lambda: NOW
        ),
        bearer_authenticator=_Bearer(),
        clock=lambda: NOW,
    )
    mcp = create_runtime(
        security_settings=settings,
        service=portfolio,
        historical_service=historical,
        clock=lambda: NOW,
    ).server
    return application, mcp


def _counts(engine: Engine) -> tuple[int, int]:
    with create_session_factory(engine)() as session:
        return (
            session.scalar(select(func.count()).select_from(hm.HistoricalInputModel)) or 0,
            session.scalar(select(func.count()).select_from(hm.HistoricalRunModel)) or 0,
        )


async def test_six_reads_and_four_tools_share_unavailable_capture_without_provider_dispatch(
    historical_api_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, mcp = _runtime(historical_api_database)
    with create_session_factory(historical_api_database)() as session:
        benchmark_id = session.scalar(select(BenchmarkVersionModel.id))
        assert benchmark_id is not None
    spies = []
    for owner, method in (
        (Trading212Client, "_send_with_retry"),
        (ReplayMarketPriceHistoryProvider, "get_price_history"),
        (ReplayFxReferenceProvider, "get_rates"),
        (ReplayBenchmarkProvider, "get_series"),
    ):
        spy = AsyncMock(side_effect=AssertionError("Retained historical reads cannot dispatch."))
        monkeypatch.setattr(owner, method, spy)
        spies.append(spy)
    responses: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url="https://testserver"
    ) as client:
        for name, suffix in OPERATIONS:
            params = {
                **QUERY,
                **({"benchmark_version_id": str(benchmark_id)} if "benchmark" in name else {}),
            }
            response = await client.get(
                f"/api/v1/accounts/{ACCOUNT}/{suffix}", params=params, headers=HEADERS
            )
            assert response.status_code == 200, (name, response.text)
            body = response.json()
            assert body["context"]["method"] == {"name": METHODS[name], "version": "1.0.0"}
            assert body["context"]["source_policy_version"] is None
            assert body["context"]["availability"] in {"unavailable", "partial"}, name
            if name in {"get_performance_series", "get_performance_summary"}:
                assert body["summary"]["ending_value"]["value"] is None
                assert body["summary"]["ending_value"]["availability"] == "unavailable"
            assert body["context"]["content_digest"] and body["context"]["input_digest"]
            responses[name] = body
            if name not in {"get_performance_series", "get_cash_flow_intelligence"}:
                result = await mcp.call_tool(name, {"account_id": ACCOUNT, **params})
                assert isinstance(result, CallToolResult) and not result.is_error, result
                assert result.structured_content is not None
                assert result.structured_content["data"] == body
        before = _counts(historical_api_database)
        assert before[0] > 0 and before[1] == 5
        for name, suffix in OPERATIONS:
            params = {
                **QUERY,
                "input_snapshot_id": responses[name]["context"]["input_snapshot_id"],
                **({"benchmark_version_id": str(benchmark_id)} if "benchmark" in name else {}),
            }
            replay = await client.get(
                f"/api/v1/accounts/{ACCOUNT}/{suffix}", params=params, headers=HEADERS
            )
            assert replay.status_code == 200 and replay.json() == responses[name], replay.text
        assert _counts(historical_api_database) == before
    for spy in spies:
        spy.assert_not_called()


async def test_persisted_capture_replay_etag_rechecks_owner_window_and_activity_scope(
    historical_api_database: Engine,
) -> None:
    application, _ = _runtime(historical_api_database)
    path = f"/api/v1/accounts/{ACCOUNT}/performance/intelligence"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url="https://testserver"
    ) as client:
        original = await client.get(path, params=QUERY, headers=HEADERS)
        assert original.status_code == 200, original.text
        pinned = {
            **QUERY,
            "input_snapshot_id": original.json()["context"]["input_snapshot_id"],
        }
        conditional = {**HEADERS, "If-None-Match": original.headers["etag"]}
        unchanged = await client.get(path, params=pinned, headers=conditional)
        assert unchanged.status_code == 304 and unchanged.content == b""
        assert unchanged.headers["cache-control"] == "private, no-store"
        before = _counts(historical_api_database)
        for changed in (
            {"start_date": "2026-08-02"},
            {"reporting_currency": "USD"},
            {"knowledge_policy": "point_in_time"},
            {"source_cutoff_at": "2026-09-06T12:00:00Z"},
        ):
            mismatch = await client.get(path, params={**pinned, **changed}, headers=conditional)
            assert mismatch.status_code == 409, mismatch.text
            assert mismatch.json()["error"]["code"] == "INPUT_SNAPSHOT_MISMATCH"
        foreign = await client.get(
            path,
            params=pinned,
            headers={**conditional, "Authorization": "Bearer historical-foreign"},
        )
        assert foreign.status_code in {403, 404}, foreign.text
        assert original.json()["context"]["input_digest"] not in foreign.text
        denied = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/cash-flow-intelligence",
            params={"private-name-canary": "private-value-canary"},
            headers={"Authorization": "Bearer historical-summary-only"},
        )
        assert denied.status_code == 403 and "canary" not in denied.text
        assert _counts(historical_api_database) == before
    # A newly composed adapter reconstructs the exact sealed public representation.
    restarted, _ = _runtime(historical_api_database)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(restarted), base_url="https://testserver"
    ) as client:
        replay = await client.get(path, params=pinned, headers=HEADERS)
        assert replay.status_code == 200 and replay.json() == original.json()
        assert replay.headers["etag"] == original.headers["etag"]


async def test_available_annual_results_pages_scope_projection_and_live_license_recheck(
    historical_api_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = create_session_factory(historical_api_database)
    ids = await seed_historical_scenarios(sessions, app_environment="test")
    assert (
        await seed_historical_target(
            sessions,
            history_principal(HISTORY_RECEIPT),
            build_history_scenario("annual"),
            HISTORY_RECEIPT,
        )
        == ids["annual_target_version_id"]
    )
    account = ids["annual_account_id"]
    benchmark = ids["annual_benchmark_version_id"]
    application, mcp = _runtime(historical_api_database)
    spies = []
    for owner, method in (
        (Trading212Client, "_send_with_retry"),
        (ReplayMarketPriceHistoryProvider, "get_price_history"),
        (ReplayFxReferenceProvider, "get_rates"),
        (ReplayBenchmarkProvider, "get_series"),
    ):
        spy = AsyncMock(side_effect=AssertionError("Historical reads cannot dispatch providers."))
        monkeypatch.setattr(owner, method, spy)
        spies.append(spy)
    query = {**QUERY, "start_date": "2025-01-01", "end_date": "2025-12-31"}
    responses: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url="https://testserver"
    ) as client:
        for name, suffix in OPERATIONS:
            params = {
                **query,
                **({"frequency": "daily"} if "performance" in name else {}),
                **({"benchmark_version_id": benchmark} if "benchmark" in name else {}),
                **(
                    {"top_n": "1"}
                    if name in {"get_attribution_summary", "get_dividend_intelligence"}
                    else {}
                ),
            }
            response = await client.get(
                f"/api/v1/accounts/{account}/{suffix}", params=params, headers=HEADERS
            )
            assert response.status_code == 200, (name, response.text)
            body = response.json()
            responses[name] = body
            assert body["context"]["method"] == {"name": METHODS[name], "version": "1.0.0"}
            assert body["context"]["source_policy_version"] == "history-prior-complete-close-1"
            assert body["context"]["availability"] in {"available", "partial"}, name
            assert body["context"]["source_count"] == (
                len(body["context"]["sources"]) + body["context"]["source_omitted_count"]
            )
            if name not in {"get_performance_series", "get_cash_flow_intelligence"}:
                arguments: dict[str, Any] = {"account_id": account, **params}
                if "top_n" in arguments:
                    arguments["top_n"] = 1
                tool = await mcp.call_tool(name, arguments)
                assert isinstance(tool, CallToolResult) and not tool.is_error, tool
                assert tool.structured_content is not None
                assert tool.structured_content["data"] == body

        performance = responses["get_performance_summary"]
        assert performance["summary"]["ending_value"]["value"] == {
            "amount": "2191.280575",
            "currency": "EUR",
        }
        assert len(performance["series"]) == 365
        assert any(row["flow_revision_ids"] for row in performance["series"])
        first = responses["get_performance_series"]
        assert first["points"]["total"] == 365 and first["points"]["next_cursor"]
        points = list(first["points"]["items"])
        cursor = first["points"]["next_cursor"]
        while cursor is not None:
            page = await client.get(
                f"/api/v1/accounts/{account}/performance/series",
                params={
                    **query,
                    "frequency": "daily",
                    "cursor": cursor,
                    "input_snapshot_id": first["context"]["input_snapshot_id"],
                },
                headers=HEADERS,
            )
            assert page.status_code == 200, page.text
            assert page.json()["context"] == first["context"]
            points.extend(page.json()["points"]["items"])
            cursor = page.json()["points"]["next_cursor"]
        assert points == performance["series"]
        wrong_filter = await client.get(
            f"/api/v1/accounts/{account}/performance/series",
            params={
                **query,
                "frequency": "monthly",
                "cursor": first["points"]["next_cursor"],
            },
            headers=HEADERS,
        )
        assert (
            wrong_filter.status_code == 400
            and wrong_filter.json()["error"]["code"] == "CURSOR_INVALID"
        )

        summary_only = await client.get(
            f"/api/v1/accounts/{account}/performance/intelligence",
            params={
                **query,
                "frequency": "daily",
                "input_snapshot_id": first["context"]["input_snapshot_id"],
            },
            headers={"Authorization": "Bearer historical-summary-only"},
        )
        assert summary_only.status_code == 200, summary_only.text
        limited = summary_only.json()
        assert limited["summary"] == performance["summary"]
        assert limited["context"]["content_digest"] == performance["context"]["content_digest"]
        assert all(not row["flow_revision_ids"] for row in limited["series"])
        assert all(
            row["flow_revision_omitted_count"] == row["flow_count"] for row in limited["series"]
        )
        assert all(not issue["reference_ids"] for issue in limited["context"]["warnings"])
        assert not any(
            ref["kind"] in {"broker_source_record", "broker_source_occurrence", "ingestion_run"}
            for ref in limited["context"]["sources"]
        )
        assert (
            len(limited["context"]["sources"]) + limited["context"]["source_omitted_count"]
            == limited["context"]["source_count"]
        )

        income = responses["get_dividend_intelligence"]
        assert {row["currency"] for row in income["native_currency_totals"]} == {"EUR", "USD"}
        assert income["reporting_totals"]["currency"] == "EUR"
        assert len(income["rows"]) == 1 and income["omitted_count"] > 0
        assert len(responses["get_attribution_summary"]["rows"]) == 1
        flows = responses["get_cash_flow_intelligence"]
        assert flows["summary"]["external_count"] > 0 and flows["summary"]["internal_count"] > 0
        assert {row["classification"] for row in flows["events"]["items"]} >= {
            "external",
            "internal",
        }

        for name, suffix in (
            ("get_attribution_summary", "attribution"),
            ("get_dividend_intelligence", "dividend-intelligence"),
        ):
            grouped_params = {
                **query,
                "grouping": "group",
                "target_version_id": ids["annual_target_version_id"],
            }
            grouped = await client.get(
                f"/api/v1/accounts/{account}/{suffix}", params=grouped_params, headers=HEADERS
            )
            assert grouped.status_code == 200, grouped.text
            grouped_body = grouped.json()
            assert {row["group_key"] for row in grouped_body["rows"] if row["group_key"]} == {
                "eur",
                "usd",
            }
            assert "explicit_target_comparison" in grouped_body["context"]["assumptions"]
            if name == "get_attribution_summary":
                tool = await mcp.call_tool(name, {"account_id": account, **grouped_params})
                assert isinstance(tool, CallToolResult) and not tool.is_error, tool
                assert tool.structured_content is not None
                assert tool.structured_content["data"] == grouped_body

        comparison = responses["get_benchmark_comparison"]
        composite = comparison["composite_snapshot"]
        assert composite["kind"] == "composite" and composite["inputs"]
        header_path = f"/api/v1/benchmark-snapshots/{composite['id']}"
        header = await client.get(header_path, headers=HEADERS)
        assert header.status_code == 200 and header.json() == composite, header.text
        observation_path = header_path + "/observations"
        observations = await client.get(observation_path, params={"limit": 1}, headers=HEADERS)
        assert observations.status_code == 200, observations.text
        assert observations.json()["kind"] == "composite" and observations.json()["next_cursor"]
        assert observations.json()["total"] == composite["observation_count"]

        # A new current license decision must deny even an already retained result,
        # source header and cursor before a matching If-None-Match could return 304.
        principal = await _Bearer().authenticate("historical-owned")
        await PostgresSourceService(
            sessions=sessions, cursor_signing_key=KEY, clock=lambda: NOW
        ).register_source_license(
            principal,
            SourceLicense(
                id=str(uuid4()),
                provider_id=history_id("annual/provider"),
                version="historical-api-denied",
                effective_at=NOW,
                store=LicensePermission.ALLOWED,
                display=LicensePermission.DENIED,
                report=LicensePermission.DENIED,
                export=LicensePermission.DENIED,
                retention_days=3650,
                attribution="Synthetic current-license denial regression.",
                evidence_key="historical-api-denied",
            ),
            idempotency_key="historical-api-license-denied",
            correlation_id="historical-api-license-test",
        )
        from trading212_persistence import historical_source_reads as detail

        # A revoked current license denies header and retained cursor/ETag reads
        # before any retained composite is decoded or its financial data is returned.
        denied_decode = Mock(side_effect=AssertionError("Denied composite must not be decoded."))
        monkeypatch.setattr(detail, "historical_value_from_json", denied_decode)
        for path, params, etag in (
            (
                f"/api/v1/accounts/{account}/performance/intelligence",
                {
                    **query,
                    "frequency": "daily",
                    "input_snapshot_id": first["context"]["input_snapshot_id"],
                },
                summary_only.headers["etag"],
            ),
            (header_path, {}, header.headers["etag"]),
            (
                observation_path,
                {"limit": 1, "cursor": observations.json()["next_cursor"]},
                observations.headers["etag"],
            ),
        ):
            denied = await client.get(
                path, params=params, headers={**HEADERS, "If-None-Match": etag}
            )
            assert denied.status_code == 403, denied.text
            assert composite["content_digest"] not in denied.text
        denied_decode.assert_not_called()
    for spy in spies:
        spy.assert_not_called()
