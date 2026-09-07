"""Real PostgreSQL HTTP/MCP planning parity, authorization and durable revisions."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from mcp.types import CallToolResult
from psycopg import sql
from sqlalchemy import Engine, func, select
from sqlalchemy.engine import make_url
from trading212_analytics.planning import calculate_contribution_plan
from trading212_api.main import create_app
from trading212_api_contracts import planning as wire
from trading212_application import planning as app
from trading212_domain import build_synthetic_identity
from trading212_domain.serialization import to_primitive
from trading212_domain.values import CurrencyCode
from trading212_mcp.server import create_runtime
from trading212_persistence import (
    PostgresPlanningService,
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.models import CollectionQuerySnapshotModel, PortfolioSnapshotModel
from trading212_persistence.planning_models import ContributionPlanJobModel
from trading212_persistence.target_models import TargetVersionModel, VirtualPortfolioModel
from trading212_persistence.target_service import PostgresTargetService
from trading212_provider.client import Trading212Client
from trading212_provider.configuration import BrokerEnvironment, Trading212Settings
from trading212_provider.credentials import StaticCredentialProvider, Trading212Credentials
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.plan_tasks import PlanExecutionState, execute_plan_message
from trading212_worker.seed import seed_materialized_synthetic

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
ORIGIN = "https://testserver"
KEY = b"planning-api-postgres-synthetic-cursor-key"
ACCOUNT = str(build_synthetic_identity().account.id)
SETTINGS = SecuritySettings(
    environment=RuntimeEnvironment.TEST,
    local_synthetic_auth_enabled=True,
    allowed_hosts=("testserver",),
    allowed_origins=(ORIGIN,),
)


@pytest.fixture(scope="module")
def planning_api_database() -> Iterator[Engine]:
    parsed = make_url(
        os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio"
        ).replace("postgresql://", "postgresql+psycopg://", 1)
    )
    name = "t212pi_planningapi_" + uuid4().hex[:12]
    admin = (
        parsed.set(database="postgres")
        .render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = parsed.set(database=name).render_as_string(hide_password=False)
    engine = None
    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        asyncio.run(seed_materialized_synthetic(url, app_environment="test"))
        engine = create_database_engine(url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if not name.startswith("t212pi_planningapi_"):
            raise RuntimeError("Unexpected disposable planning API database.")
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


class _Bearer:
    async def authenticate(self, token: str) -> Principal:
        if token != "foreign-owner":
            raise AuthenticationError("Invalid synthetic credential.")
        return Principal(
            "foreign-planning-owner",
            str(uuid4()),
            "test",
            "test",
            frozenset(Scope),
            NOW - timedelta(days=1),
            NOW + timedelta(days=1),
        )


def _services(
    engine: Engine,
    *,
    clock: Callable[[], datetime] | None = None,
) -> tuple[PostgresPortfolioService, PostgresTargetService, PostgresPlanningService]:
    sessions = create_session_factory(engine)
    return (
        PostgresPortfolioService(
            sessions=sessions, cursor_signing_key=KEY, clock=clock or (lambda: NOW)
        ),
        PostgresTargetService(
            sessions=sessions, cursor_signing_key=KEY, clock=clock or (lambda: NOW)
        ),
        PostgresPlanningService(
            sessions=sessions, cursor_signing_key=KEY, clock=clock or (lambda: NOW)
        ),
    )


def _body(engine: Engine) -> dict[str, Any]:
    with create_session_factory(engine)() as session:
        version = session.scalar(
            select(TargetVersionModel)
            .join(VirtualPortfolioModel)
            .where(VirtualPortfolioModel.broker_account_id == UUID(ACCOUNT))
        )
        snapshot = session.scalar(
            select(PortfolioSnapshotModel).where(
                PortfolioSnapshotModel.broker_account_id == UUID(ACCOUNT)
            )
        )
        assert version is not None and snapshot is not None
        return {
            "account_id": ACCOUNT,
            "virtual_portfolio_id": str(version.virtual_portfolio_id),
            "target_version_id": str(version.id),
            "snapshot_id": str(snapshot.id),
            "contribution": {"amount": "20", "currency": "EUR"},
            "mode": "global",
            "coverage_policy": "allow_degraded",
        }


def _job_count(engine: Engine) -> int:
    with create_session_factory(engine)() as session:
        return session.scalar(select(func.count()).select_from(ContributionPlanJobModel)) or 0


async def _deliver(service: PostgresPlanningService, job_id: str) -> None:
    claims = await service.claim_plan_dispatches(dispatcher_id="api-parity", limit=100)
    claim = next(item for item in claims if item.message.job_id == job_id)
    assert await service.acknowledge_plan_dispatch(claim)
    assert (
        await execute_plan_message(
            service,
            claim.message,
            consumer_id="api-parity",
            calculate=calculate_contribution_plan,
        )
        is PlanExecutionState.COMPLETED
    )
    assert (
        await execute_plan_message(
            service,
            claim.message,
            consumer_id="api-parity-replay",
            calculate=calculate_contribution_plan,
        )
        is PlanExecutionState.NOT_CLAIMED
    )


def _structured(result: Any) -> dict[str, Any]:
    assert isinstance(result, CallToolResult) and not result.is_error, result
    assert result.structured_content is not None
    return cast(dict[str, Any], result.structured_content)


async def test_actual_drift_and_saved_plan_match_mcp_with_real_worker_and_revision_history(
    planning_api_database: Engine,
) -> None:
    observations, targets, planning = _services(planning_api_database)
    api = create_app(
        settings=SETTINGS,
        service=observations,
        target_service=targets,
        planning_service=planning,
        clock=lambda: NOW,
    )
    runtime = create_runtime(
        security_settings=SETTINGS,
        service=observations,
        target_service=targets,
        planning_service=planning,
        clock=lambda: NOW,
    )
    body = _body(planning_api_database)
    pins = {key: body[key] for key in ("snapshot_id", "virtual_portfolio_id", "target_version_id")}
    pins["reporting_currency"] = "EUR"
    before = _job_count(planning_api_database)
    principal = Principal(
        "wire-parity",
        str(build_synthetic_identity().owner.id),
        "test",
        "test",
        frozenset(Scope),
        NOW - timedelta(days=1),
        NOW + timedelta(days=1),
    )
    value = await planning.get_actual_vs_target(
        principal,
        ACCOUNT,
        query=app.ActualVsTargetQuery(
            **{key: value for key, value in pins.items() if key != "reporting_currency"},
            reporting_currency=CurrencyCode("EUR"),
        ),
    )
    wire.ActualVsTargetResult.model_validate(
        wire.canonical_planning_payload(to_primitive(value), wire.ActualVsTargetResult)
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        session = await client.post("/api/v1/auth/local-session")
        assert session.status_code == 201
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": session.json()["csrf_token"],
            "X-Idempotency-Key": uuid4().hex,
        }
        actual = await client.get(f"/api/v1/accounts/{ACCOUNT}/actual-vs-target", params=pins)
        assert actual.status_code == 200, actual.text
        canonical = actual.json()
        mcp = _structured(
            await runtime.server.call_tool("get_actual_vs_target", {"account_id": ACCOUNT, **pins})
        )
        assert mcp["data"] == canonical
        assert canonical["rows"]["total"] == len(canonical["rows"]["items"]) > 0
        holdings = [row for row in canonical["target_identities"] if row["holding_id"] is not None]
        assert holdings and all(row["id"] != row["holding_id"] for row in holdings)
        sampled = await client.get(f"/api/v1/accounts/{ACCOUNT}/drift", params={**pins, "top_n": 1})
        assert sampled.status_code == 200, sampled.text
        sample = sampled.json()
        mcp_drift = _structured(
            await runtime.server.call_tool(
                "get_drift_analysis", {"account_id": ACCOUNT, **pins, "top_n": 1}
            )
        )
        assert mcp_drift["data"] == sample
        assert sample["totals"] == canonical["totals"]
        assert sample["omitted_rows"] == sample["eligible_rows"] - 1
        effective = await client.get(
            f"/api/v1/accounts/{ACCOUNT}/drift", params={**pins, "basis": "effective"}
        )
        assert effective.status_code == 200, effective.text
        assert effective.json()["context"]["availability"] == "unavailable"
        for row in [
            *effective.json()["groups"],
            *effective.json()["leaves"],
            *effective.json()["cash_and_unclassified"],
        ]:
            assert row["effective_weight"] is None and row["signed_drift"] is None
            assert row["effective_weight_reason"] == "effective_exposure_target_unavailable"
        assert _job_count(planning_api_database) == before
        accepted = await client.post("/api/v1/contribution-plans", json=body, headers=headers)
        assert accepted.status_code == 202, accepted.text
        job = accepted.json()
        assert job["state"] == "queued" and job["outcome"] is None
        assert job["execution_allowed"] is False and _job_count(planning_api_database) == before + 1
        replay = await client.post("/api/v1/contribution-plans", json=body, headers=headers)
        assert replay.json() == job and replay.headers["etag"] == accepted.headers["etag"]
        conflict = await client.post(
            "/api/v1/contribution-plans",
            json={**body, "contribution": {"amount": "21", "currency": "EUR"}},
            headers=headers,
        )
        assert conflict.status_code == 409
        route = f"/api/v1/contribution-plans/{job['plan_id']}"
        pending = await client.get(route)
        assert pending.status_code == 200 and pending.json()["result"] is None
        assert pending.json()["lines"]["items"] == []
        assert pending.headers["etag"] != pending.json()["revision_etag"]
        assert (
            await client.get(route, headers={"If-None-Match": pending.headers["etag"]})
        ).status_code == 304
        await _deliver(planning, job["job_id"])
        ready = await client.get(route, headers={"If-None-Match": pending.headers["etag"]})
        assert ready.status_code == 200, ready.text
        detail = ready.json()
        assert detail["job"]["state"] == "succeeded" and detail["result"]["outcome"] == "optimal"
        assert detail["content_digest"] and detail["result"]["execution_allowed"] is False
        assert detail["revision_etag"] == pending.json()["revision_etag"]
        mcp_plan = _structured(
            await runtime.server.call_tool(
                "get_contribution_plan", {"account_id": ACCOUNT, "plan_id": job["plan_id"]}
            )
        )
        assert mcp_plan["data"] == detail
        assert mcp_plan["pagination"]["total"] == detail["lines"]["total"]
        listing = await client.get(
            "/api/v1/contribution-plans", params={"account_id": ACCOUNT, "limit": 1}
        )
        assert (
            listing.status_code == 200
            and listing.json()["items"][0]["job"]["plan_id"] == job["plan_id"]
        )
        revision_headers = {**headers, "X-Idempotency-Key": uuid4().hex}
        missing = await client.post(route + "/revisions", json=body, headers=revision_headers)
        assert missing.status_code == 428
        stale = await client.post(
            route + "/revisions", json=body, headers={**revision_headers, "If-Match": '"stale"'}
        )
        assert stale.status_code == 412
        revised = await client.post(
            route + "/revisions",
            json=body,
            headers={**revision_headers, "If-Match": detail["revision_etag"]},
        )
        assert revised.status_code == 202, revised.text
        assert revised.json()["request_revision"] == 2
        retry = await client.post(route + "/revisions", json=body, headers=revision_headers)
        assert retry.json() == revised.json() and retry.status_code == 202
        history = await client.get(
            "/api/v1/contribution-plans",
            params={
                "account_id": ACCOUNT,
                "plan_id": job["plan_id"],
                "include_revisions": "true",
                "limit": 1,
            },
        )
        assert history.status_code == 200, history.text
        assert (
            history.json()["total"] == 2
            and history.json()["items"][0]["job"]["request_revision"] == 2
        )
        assert history.json()["next_cursor"]
        older = await client.get(
            route, params={"plan_revision_id": detail["job"]["plan_revision_id"]}
        )
        assert older.status_code == 200 and older.json() == detail
        assert _job_count(planning_api_database) == before + 2


async def test_persisted_authorization_csrf_identity_and_unsupported_commands_fail_closed(
    planning_api_database: Engine,
) -> None:
    observations, targets, planning = _services(planning_api_database)
    api = create_app(
        settings=SETTINGS,
        service=observations,
        target_service=targets,
        planning_service=planning,
        bearer_authenticator=_Bearer(),
        clock=lambda: NOW,
    )
    body = _body(planning_api_database)
    before = _job_count(planning_api_database)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        session = await client.post("/api/v1/auth/local-session")
        headers = {
            "X-Idempotency-Key": uuid4().hex,
            "Origin": ORIGIN,
            "X-CSRF-Token": session.json()["csrf_token"],
        }
        no_csrf = await client.post(
            "/api/v1/contribution-plans", json=body, headers={"X-Idempotency-Key": uuid4().hex}
        )
        assert no_csrf.status_code == 401
        foreign = await client.post(
            "/api/v1/contribution-plans",
            json=body,
            headers={**headers, "Authorization": "Bearer foreign-owner"},
        )
        assert foreign.status_code in {403, 404}
        cross_account = await client.post(
            "/api/v1/contribution-plans", json={**body, "account_id": str(uuid4())}, headers=headers
        )
        assert cross_account.status_code in {403, 404}
        invalid_holding = await client.post(
            "/api/v1/contribution-plans",
            json={**body, "eligible_holding_ids": [str(uuid4())]},
            headers=headers,
        )
        assert invalid_holding.status_code == 422
        assert (await client.delete("/api/v1/contribution-plans")).status_code == 405
        accepted = await client.post("/api/v1/contribution-plans", json=body, headers=headers)
        assert accepted.status_code == 202
        route = f"/api/v1/contribution-plans/{accepted.json()['plan_id']}"
        own = await client.get(route)
        denied = await client.get(
            route,
            headers={"Authorization": "Bearer foreign-owner", "If-None-Match": own.headers["etag"]},
        )
        assert denied.status_code in {403, 404} and denied.status_code != 304
        assert (await client.delete(route)).status_code == 405
        assert _job_count(planning_api_database) == before + 1


async def test_mcp_command_persists_holding_overrides_and_api_recalculation_retains_them(
    planning_api_database: Engine,
) -> None:
    observations, targets, planning = _services(planning_api_database)
    runtime = create_runtime(
        security_settings=SETTINGS,
        service=observations,
        target_service=targets,
        planning_service=planning,
        clock=lambda: NOW,
    )
    body = _body(planning_api_database)
    pins = {key: body[key] for key in ("snapshot_id", "virtual_portfolio_id", "target_version_id")}
    actual = _structured(
        await runtime.server.call_tool(
            "get_actual_vs_target", {"account_id": ACCOUNT, **pins, "reporting_currency": "EUR"}
        )
    )["data"]
    holding = next(row for row in actual["target_identities"] if row["holding_id"])
    overrides = [
        {
            "holding_id": holding["holding_id"],
            "minimum_amount": "0",
            "value_increment": "0.01",
            "maximum_post_weight": "1",
        }
    ]
    args = {**body, "allocation_constraints": overrides, "idempotency_key": uuid4().hex}
    accepted = _structured(await runtime.server.call_tool("create_contribution_plan", args))["data"]
    replay = _structured(await runtime.server.call_tool("create_contribution_plan", args))["data"]
    assert replay == accepted and accepted["state"] == "queued"
    await _deliver(planning, accepted["job_id"])
    api = create_app(
        settings=SETTINGS,
        service=observations,
        target_service=targets,
        planning_service=planning,
        clock=lambda: NOW,
    )
    route = f"/api/v1/contribution-plans/{accepted['plan_id']}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        session = await client.post("/api/v1/auth/local-session")
        detail = await client.get(route)
        assert detail.status_code == 200, detail.text
        stored = detail.json()
        assert stored["request"]["options"]["holding_constraints"] == overrides
        assert stored["request"]["options"]["allocation_constraints"] == []
        assert any(line["holding_id"] == holding["holding_id"] for line in stored["lines"]["items"])
        revised = await client.post(
            route + "/revisions",
            json={**body, "holding_constraints": overrides},
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": session.json()["csrf_token"],
                "X-Idempotency-Key": uuid4().hex,
                "If-Match": stored["revision_etag"],
            },
        )
        assert revised.status_code == 202, revised.text
        persisted = await client.get(route)
        assert persisted.json()["request"]["options"]["holding_constraints"] == overrides
        assert revised.json()["input_digest"] == accepted["input_digest"]


async def test_repeated_pinned_reads_and_conditional_job_polling_do_not_consume_new_capacity(
    planning_api_database: Engine,
) -> None:
    current_time = [NOW]
    observations, targets, planning = _services(
        planning_api_database, clock=lambda: current_time[0]
    )
    api = create_app(
        settings=SETTINGS,
        service=observations,
        target_service=targets,
        planning_service=planning,
        clock=lambda: current_time[0],
    )
    body = _body(planning_api_database)
    pins = {key: body[key] for key in ("snapshot_id", "virtual_portfolio_id", "target_version_id")}
    pins["reporting_currency"] = "EUR"

    def snapshot_count() -> int:
        with create_session_factory(planning_api_database)() as session:
            return (
                session.scalar(select(func.count()).select_from(CollectionQuerySnapshotModel)) or 0
            )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        session = await client.post("/api/v1/auth/local-session")
        accepted = await client.post(
            "/api/v1/contribution-plans",
            json=body,
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": session.json()["csrf_token"],
                "X-Idempotency-Key": uuid4().hex,
            },
        )
        assert accepted.status_code == 202
        route = f"/api/v1/contribution-plans/{accepted.json()['plan_id']}"
        first = await client.get(route)
        actual_route = f"/api/v1/accounts/{ACCOUNT}/actual-vs-target"
        actual = await client.get(actual_route, params=pins)
        assert first.status_code == actual.status_code == 200
        initial = snapshot_count()
        for _ in range(100):
            current_time[0] += timedelta(seconds=1)
            unchanged = await client.get(route, headers={"If-None-Match": first.headers["etag"]})
            assert unchanged.status_code == 304
            repeated = await client.get(actual_route, params=pins)
            assert repeated.status_code == 200 and repeated.json() == actual.json()
        assert snapshot_count() == initial
        await _deliver(planning, accepted.json()["job_id"])
        finalized = await client.get(route)
        assert finalized.status_code == 200 and finalized.json()["job"]["state"] == "succeeded"
        after_completion = snapshot_count()
        for _ in range(100):
            current_time[0] += timedelta(seconds=1)
            unchanged = await client.get(
                route, headers={"If-None-Match": finalized.headers["etag"]}
            )
            assert unchanged.status_code == 304
        assert snapshot_count() == after_completion


async def test_planning_success_invalid_retry_and_duplicate_delivery_never_send_to_broker(
    planning_api_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This is the HTTP transport used by Trading212Client's default AsyncClient.
    # ASGITransport remains untouched, so all application requests below are real.
    phase = "probe"
    attempts = {"probe": 0, "planning": 0}

    async def forbid_network(
        _transport: httpx.AsyncHTTPTransport,
        _request: httpx.Request,
    ) -> httpx.Response:
        attempts[phase] += 1
        raise AssertionError("Unexpected outbound provider transport dispatch.")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbid_network)
    # Positive control proves a real typed broker capability reaches this spy;
    # the guard fails before any socket/DNS operation and retains no request data.
    async with Trading212Client(
        settings=Trading212Settings(),
        credential_provider=StaticCredentialProvider(
            Trading212Credentials("planning-test", "synthetic-only", BrokerEnvironment.DEMO)
        ),
        credential_reference="synthetic:planning-transport-probe",
    ) as broker:
        with pytest.raises(AssertionError, match="Unexpected outbound provider transport"):
            await broker.get_account_summary(correlation_id="planning-transport-probe")
    assert attempts == {"probe": 1, "planning": 0}
    phase = "planning"

    observations, targets, planning = _services(planning_api_database)
    api = create_app(
        settings=SETTINGS,
        service=observations,
        target_service=targets,
        planning_service=planning,
        clock=lambda: NOW,
    )
    body = _body(planning_api_database)
    initial_jobs = _job_count(planning_api_database)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url=ORIGIN) as client:
        session = await client.post("/api/v1/auth/local-session")
        assert session.status_code == 201
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": session.json()["csrf_token"],
            "X-Idempotency-Key": uuid4().hex,
        }
        for invalid in (
            {**body, "execution_allowed": True},
            {**body, "contribution": {"amount": "-1", "currency": "EUR"}},
        ):
            rejected = await client.post(
                "/api/v1/contribution-plans", json=invalid, headers=headers
            )
            assert rejected.status_code == 422
            assert attempts["planning"] == 0 and _job_count(planning_api_database) == initial_jobs
        accepted = await client.post("/api/v1/contribution-plans", json=body, headers=headers)
        assert accepted.status_code == 202, accepted.text
        queued = accepted.json()
        assert queued["execution_allowed"] is False and queued["outcome"] is None
        replay = await client.post("/api/v1/contribution-plans", json=body, headers=headers)
        assert replay.status_code == 202 and replay.json() == queued
        assert _job_count(planning_api_database) == initial_jobs + 1
        assert attempts["planning"] == 0
        conflict = await client.post(
            "/api/v1/contribution-plans",
            json={**body, "contribution": {"amount": "21", "currency": "EUR"}},
            headers=headers,
        )
        assert conflict.status_code == 409 and attempts["planning"] == 0
        # The production delivery helper claims the durable job, calls the real
        # solver, fences completion, and proves duplicate delivery is not claimed.
        await _deliver(planning, queued["job_id"])
        assert attempts["planning"] == 0
        final = await client.get(f"/api/v1/contribution-plans/{queued['plan_id']}")
        assert final.status_code == 200, final.text
        result = final.json()
        assert result["job"]["state"] == "succeeded" and result["result"]["outcome"] == "optimal"
        assert result["execution_allowed"] is result["result"]["execution_allowed"] is False
        assert result["content_digest"] and result["lines"]["total"] > 0
        assert attempts == {"probe": 1, "planning": 0}
        assert _job_count(planning_api_database) == initial_jobs + 1
