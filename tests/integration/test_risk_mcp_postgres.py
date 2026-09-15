"""Signed SDK transport, persisted current rights, real worker and HTTP risk parity."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from inspect import unwrap
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import httpx2
import pytest
from sqlalchemy import func, select
from trading212_api.main import create_app
from trading212_application import xray as xray_app
from trading212_application.xray_ingestion import XrayPolicyRegistration, XrayTaxonomyRegistration
from trading212_domain.serialization import to_primitive
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_persistence import PostgresPortfolioService
from trading212_persistence.historical_capture import HistoricalCaptureStore
from trading212_persistence.models import PrincipalModel
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    PrincipalScopeGrantModel,
)
from trading212_persistence.risk_models import RiskResultModel
from trading212_persistence.xray_service import PostgresXrayService
from trading212_security.principals import Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import JwtAuthenticator
from trading212_worker.historical_seed import CURSOR_KEY
from trading212_worker.risk_tasks import RiskExecutionState, execute_risk_message
from trading212_worker.xray_fixture import synthetic_xray_policy

from tests.integration.real_jwt_mcp_support import (
    ISSUER,
    ORIGIN,
    RESOURCE,
    SecretGuard,
    SignedTransport,
)
from tests.integration.test_historical_postgres import historical_database as _historical_database
from tests.integration.test_historical_seed import NOW
from tests.integration.test_historical_seed import seeded_history as _seeded_history
from tests.integration.test_real_jwt_mcp_postgres import guard as guard
from tests.integration.test_risk_jobs_postgres import store
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case
from tests.integration.test_risk_source_authorization import restrict
from tests.jwt_support import JwtTestSigner

pytestmark = pytest.mark.integration
# Rights revocation must not contaminate another transport or source fixture.
historical_database = pytest.fixture(scope="function")(unwrap(_historical_database))
seeded_history = pytest.fixture(scope="function")(unwrap(_seeded_history))


def provision(case: RunCase) -> None:
    identifier = uuid4()
    subject = "risk-owner-" + uuid4().hex
    with case.sessions() as session, session.begin():
        session.add(
            PrincipalModel(
                id=identifier,
                owner_id=UUID(case.principal.owner_id),
                issuer=ISSUER,
                subject=subject,
                status="active",
            )
        )
        session.flush()
        for scope in case.principal.scopes:
            session.add(
                PrincipalScopeGrantModel(
                    principal_id=identifier,
                    scope=scope.value,
                    granted_at=NOW,
                    expires_at=None,
                    revoked_at=None,
                )
            )
    case.principal = replace(
        case.principal, principal_id=str(identifier), issuer=ISSUER, subject=subject
    )


def token(case: RunCase, signer: JwtTestSigner, guard: SecretGuard, **changes: object) -> str:
    __tracebackhide__ = True
    auth_now = datetime.now(UTC)
    value = signer.sign_raw_claims(
        {
            "iss": ISSUER,
            "aud": RESOURCE,
            "sub": case.principal.subject,
            "owner_id": case.principal.owner_id,
            "principal_id": case.principal.principal_id,
            "scope": " ".join(sorted(s.value for s in case.principal.scopes)),
            "iat": int(auth_now.timestamp()) - 1,
            "exp": int(auth_now.timestamp()) + 3600,
            **changes,
        }
    )
    guard.remember(value)
    return value


def authenticator(signer: JwtTestSigner, audience: str = RESOURCE) -> JwtAuthenticator:
    return JwtAuthenticator(
        issuer=ISSUER,
        audience=audience,
        public_key=signer.public_key,
        # The SDK middleware also checks real wall time; only financial fixtures use NOW.
        clock_skew_seconds=0,
    )


def settings() -> SecuritySettings:
    return SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=False,
        issuer=ISSUER,
        audience=RESOURCE,
        allowed_hosts=("portfolio.example",),
        allowed_origins=(ORIGIN,),
    )


@asynccontextmanager
async def transport(
    case: RunCase, signer: JwtTestSigner, guard: SecretGuard
) -> AsyncIterator[SignedTransport]:
    __tracebackhide__ = True
    runtime = create_runtime(
        security_settings=settings(),
        mcp_settings=McpSettings.model_validate({"public_base_url": ORIGIN}),
        service=PostgresPortfolioService(
            sessions=case.sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW
        ),
        risk_service=case.service,
        bearer_authenticator=authenticator(signer),
        clock=lambda: NOW,
    )
    application = runtime.asgi_app()
    async with (
        runtime.server.session_manager.run(),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(application),
            base_url=ORIGIN,
            headers={"Authorization": "Bearer " + token(case, signer, guard)},
            follow_redirects=False,
            trust_env=False,
            timeout=20,
        ) as client,
    ):
        yield SignedTransport(client, guard)
    guard.finish()


def arguments(case: RunCase) -> dict[str, Any]:
    value = to_primitive(case.command)
    del value["correlation_id"]
    return value  # type: ignore[no-any-return]


async def execute(case: RunCase, identifier: str) -> None:
    worker = store(case)
    claims = await worker.claim_risk_dispatches(dispatcher_id="risk-mcp-test")
    assert len(claims) == 1 and claims[0].message.run_id == identifier
    assert await worker.acknowledge_risk_dispatch(claims[0])
    assert (
        await execute_risk_message(
            worker, claims[0].message, consumer_id="risk-mcp-test", clock=lambda: NOW
        )
        is RiskExecutionState.SUCCEEDED
    )


async def test_signed_sdk_command_concurrent_replay_worker_and_http_canonical_parity(
    run_case: RunCase, guard: SecretGuard
) -> None:
    __tracebackhide__ = True
    case = run_case
    provision(case)
    signer = JwtTestSigner.generate("ES256")
    async with transport(case, signer, guard) as connection, connection.session() as client:
        descriptors = await client.list_tools()
        guard.check(descriptors.model_dump_json())
        assert len(descriptors.tools) == 36
        correlation = "c" * 128
        connection.client.headers["X-Correlation-ID"] = correlation
        results = await asyncio.gather(
            *(connection.call(client, "create_risk_run", arguments(case)) for _ in range(2))
        )
        assert all(not result.is_error for result in results)
        assert all(result.meta == {"correlationId": correlation} for result in results)
        assert results[0].structured_content is not None
        queued = results[0].structured_content["data"]
        assert (
            results[1].structured_content is not None
            and results[1].structured_content["data"] == queued
        )
        assert queued["state"] == "queued" and queued["result"] is None
        identifier = queued["id"]
        with case.sessions() as session:
            stored_reference = session.scalar(
                select(ApplicationCommandIdentityModel.premium_correlation_id).where(
                    ApplicationCommandIdentityModel.command == "risk.run.create.v1",
                    ApplicationCommandIdentityModel.premium_resource_id == UUID(identifier),
                )
            )
            assert stored_reference == "sha256:" + sha256(correlation.encode()).hexdigest()
        connection.client.headers["X-Correlation-ID"] = "d" * 121
        replay = await connection.call(client, "create_risk_run", arguments(case))
        assert not replay.is_error and replay.structured_content == results[0].structured_content
        assert replay.meta == {"correlationId": "d" * 121}
        query = {"account_id": str(case.command.account_id), "run_id": identifier}
        changed = arguments(case)
        changed["window"] = {**changed["window"], "end_date": "2025-12-30"}
        conflict = await connection.call(client, "create_risk_run", changed)
        assert (
            conflict.structured_content is not None
            and conflict.structured_content["error"]["code"] == "CONFLICT"
        )
        await execute(case, identifier)
        summary = await connection.call(client, "get_risk_summary", query)
        matrix = await connection.call(client, "get_risk_matrix", query)
        assert not summary.is_error and not matrix.is_error
        assert summary.structured_content is not None and matrix.structured_content is not None
        canonical = to_primitive(await case.service.get_run(case.principal, UUID(identifier)))
        assert summary.structured_content["data"] == canonical
        assert matrix.structured_content["data"]["matrix"] == canonical["result"]["matrix"]
        assert (
            matrix.structured_content["data"]["content_digest"]
            == canonical["result"]["content_digest"]
        )
        api = create_app(
            settings=settings(),
            service=PostgresPortfolioService(
                sessions=case.sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW
            ),
            risk_service=case.service,
            bearer_authenticator=authenticator(signer, RESOURCE + "/api"),
            clock=lambda: NOW,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(api),
            base_url=ORIGIN,
            follow_redirects=False,
            trust_env=False,
        ) as http:
            for suffix, expected in (
                ("", canonical),
                ("/matrix", matrix.structured_content["data"]),
            ):
                response = await http.get(
                    "/api/v1/risk-runs/" + identifier + suffix,
                    headers={
                        "Authorization": "Bearer "
                        + token(case, signer, guard, aud=RESOURCE + "/api")
                    },
                )
                guard.check(response.text)
                assert response.status_code == 200
                assert response.json() == expected
        with case.sessions() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RiskResultModel)
                    .where(RiskResultModel.run_id == UUID(identifier))
                )
                == 1
            )
        with case.sessions() as session, session.begin():
            session.get_one(
                PrincipalScopeGrantModel,
                (UUID(case.principal.principal_id), Scope.ANALYTICS_READ.value),
            ).revoked_at = NOW
        for name in ("get_risk_summary", "get_risk_matrix", "create_risk_run"):
            result = await connection.call(
                client, name, arguments(case) if name == "create_risk_run" else query
            )
            assert result.is_error and result.structured_content is not None
            assert result.structured_content["data"] is None
            assert result.structured_content["error"]["code"] == "ACCESS_DENIED"


async def test_signed_identity_account_scope_and_current_license_checks_precede_decode(
    run_case: RunCase, guard: SecretGuard
) -> None:
    __tracebackhide__ = True
    case = run_case
    provision(case)
    signer = JwtTestSigner.generate("ES256")
    async with transport(case, signer, guard) as connection, connection.session() as client:
        created = await connection.call(client, "create_risk_run", arguments(case))
        assert not created.is_error and created.structured_content is not None
        query = {
            "account_id": str(case.command.account_id),
            "run_id": created.structured_content["data"]["id"],
        }
        for changes in (
            {"iss": ISSUER + "/"},
            {"aud": RESOURCE + "/"},
            {"owner_id": None},
            {"exp": int(NOW.timestamp()) - 1},
        ):
            response = await connection.client.post(
                RESOURCE,
                headers={
                    "Authorization": "Bearer " + token(case, signer, guard, **changes),
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {"name": "get_risk_summary", "arguments": query},
                },
            )
            guard.check(response.text)
            assert response.status_code == 401
        for name in ("get_risk_summary", "get_risk_matrix"):
            denied = await connection.call(client, name, {**query, "account_id": str(uuid4())})
            assert denied.is_error and denied.structured_content is not None
            # Matrix can be unavailable for a queued run before it has any body to disclose.
            assert denied.structured_content["error"]["code"] in {"NOT_FOUND", "RISK_UNAVAILABLE"}
            assert denied.structured_content["data"] is None
        for scope in (Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.RISK_WRITE):
            connection.client.headers["Authorization"] = "Bearer " + token(
                case,
                signer,
                guard,
                scope=" ".join(sorted(s.value for s in case.principal.scopes - {scope})),
            )
            denied = await connection.call(client, "create_risk_run", arguments(case))
            assert (
                denied.structured_content is not None
                and denied.structured_content["error"]["code"] == "ACCESS_DENIED"
            )
        connection.client.headers["Authorization"] = "Bearer " + token(case, signer, guard)
        restrict(case, store="denied", days=1)
        with patch.object(
            HistoricalCaptureStore, "_capture_view", side_effect=AssertionError("private decode")
        ) as decode:
            for name in ("create_risk_run", "get_risk_summary", "get_risk_matrix"):
                result = await connection.call(
                    client, name, arguments(case) if name == "create_risk_run" else query
                )
                assert result.is_error and result.structured_content is not None
                assert result.structured_content["data"] is None
                assert result.structured_content["error"]["code"] == "SOURCE_UNAVAILABLE"
            decode.assert_not_called()


async def test_real_xray_capture_is_pinned_through_worker_and_mcp_result(
    run_case: RunCase, guard: SecretGuard
) -> None:
    __tracebackhide__ = True
    case = run_case
    provision(case)
    signer = JwtTestSigner.generate("ES256")
    xray = PostgresXrayService(
        sessions=case.sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW
    )
    policy = replace(synthetic_xray_policy(), id=uuid4())
    await xray.register_xray_policy(
        case.principal,
        str(case.command.account_id),
        XrayPolicyRegistration(
            key="risk-test-xray",
            effective_at=case.command.window.source_cutoff_at.replace(year=2024),
            policy=policy,
            taxonomies=tuple(
                XrayTaxonomyRegistration(
                    id=str(t.taxonomy_id), dimension=t.dimension, key=t.key, version=t.version
                )
                for t in policy.taxonomy_versions
            ),
        ),
        idempotency_key="risk-xray-policy",
        correlation_id="risk-xray-test",
    )
    exposure = await xray.get_effective_exposure(
        case.principal,
        str(case.command.account_id),
        query=xray_app.EffectiveExposureQuery(
            request=xray_app.XrayRunRequest(
                snapshot_id=str(case.command.portfolio_snapshot_id),
                source_cutoff_at=case.command.window.source_cutoff_at,
                currency=xray_app.ExplicitCurrency(
                    reporting_currency=case.command.window.reporting_currency
                ),
            ),
            limit=1,
        ),
    )
    case.command = replace(case.command, xray_run_id=UUID(exposure.context.run_id))
    async with transport(case, signer, guard) as connection, connection.session() as client:
        created = await connection.call(client, "create_risk_run", arguments(case))
        assert not created.is_error and created.structured_content is not None
        identifier = created.structured_content["data"]["id"]
        await execute(case, identifier)
        value = await connection.call(
            client,
            "get_risk_summary",
            {"account_id": str(case.command.account_id), "run_id": identifier},
        )
        assert not value.is_error and value.structured_content is not None
        data = value.structured_content["data"]
        assert data["xray_run_id"] == exposure.context.run_id
        assert data["result"]["xray_result_digest"] == exposure.context.content_digest
        assert data["result"]["concentration"]["basis"] == "economic_companies_absolute_portfolio"
        canonical = await case.service.get_run(case.principal, UUID(identifier))
        assert data == to_primitive(canonical)
