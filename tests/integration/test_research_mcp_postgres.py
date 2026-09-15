"""Real signed SDK research reads over retained PostgreSQL sources and X-ray proof."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import httpx2
import pytest
from trading212_api import research_schemas as adapter
from trading212_api_contracts import research as wire
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_persistence import PostgresPortfolioService
from trading212_persistence.models import PrincipalModel
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_security.principals import Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import JwtAuthenticator
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.real_jwt_mcp_support import (
    ISSUER,
    ORIGIN,
    RESOURCE,
    SecretGuard,
    SignedTransport,
)
from tests.integration.research_case import ResearchCase
from tests.integration.research_case import research_case as research_case
from tests.integration.test_real_jwt_mcp_postgres import guard as guard
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case
from tests.jwt_support import JwtTestSigner

pytestmark = pytest.mark.integration


async def test_signed_sdk_current_scopes_source_revocation_and_exact_saved_item(
    research_case: ResearchCase,
    guard: SecretGuard,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    __tracebackhide__ = True
    case = research_case
    case.publish(
        case.incoming(
            "sdk-owned-news",
            summary="<script>untrusted_research()</script>\nThis is inert retained source text.",
        )
    )
    principal = replace(
        case.xray.principal,
        principal_id=str(uuid4()),
        issuer=ISSUER,
        subject="research-mcp-" + uuid4().hex,
    )
    with case.xray.sessions() as session, session.begin():
        session.add(
            PrincipalModel(
                id=UUID(principal.principal_id),
                owner_id=UUID(principal.owner_id),
                issuer=principal.issuer,
                subject=principal.subject,
                status="active",
            )
        )
        session.flush()
        for scope in principal.scopes:
            session.add(
                PrincipalScopeGrantModel(
                    principal_id=UUID(principal.principal_id),
                    scope=scope.value,
                    granted_at=case.xray.now[0],
                    expires_at=None,
                    revoked_at=None,
                )
            )
    outbound = AsyncMock(
        side_effect=AssertionError("Research reads must not dispatch provider HTTP.")
    )
    monkeypatch.setattr(httpx.AsyncClient, "send", outbound)
    signer = JwtTestSigner.generate("ES256")

    def authorization(**changes: object) -> str:
        now = int(datetime.now(UTC).timestamp())
        token = signer.sign_raw_claims(
            {
                "iss": principal.issuer,
                "aud": RESOURCE,
                "sub": principal.subject,
                "owner_id": principal.owner_id,
                "principal_id": principal.principal_id,
                "scope": " ".join(sorted(scope.value for scope in principal.scopes)),
                "iat": now - 1,
                "exp": now + 3600,
                **changes,
            }
        )
        guard.remember(token)
        return "Bearer " + token

    runtime = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            local_synthetic_auth_enabled=False,
            issuer=principal.issuer,
            audience=RESOURCE,
            allowed_hosts=("portfolio.example",),
            allowed_origins=(ORIGIN,),
        ),
        mcp_settings=McpSettings.model_validate({"public_base_url": ORIGIN}),
        service=PostgresPortfolioService(
            sessions=case.xray.sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            clock=lambda: case.xray.now[0],
        ),
        research_service=case.service,
        bearer_authenticator=JwtAuthenticator(
            issuer=principal.issuer,
            audience=RESOURCE,
            public_key=signer.public_key,
            clock_skew_seconds=0,
        ),
        clock=lambda: case.xray.now[0],
    )
    http_app = runtime.asgi_app()
    arguments = {
        "account_id": str(case.account_id),
        "xray_run_id": str(case.run_id),
        "source_cutoff_at": case.xray.now[0].isoformat(),
    }
    async with (
        runtime.server.session_manager.run(),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(http_app),
            base_url=ORIGIN,
            headers={"Authorization": authorization()},
            follow_redirects=False,
            trust_env=False,
            timeout=20,
        ) as http,
    ):
        connection = SignedTransport(http, guard)
        async with connection.session() as client:
            tools = await client.list_tools()
            resources = await client.list_resources()
            assert len(tools.tools) == 38 and len(resources.resources) == 11
            summary = await connection.call(client, "get_research_summary", arguments)
            assert not summary.is_error and summary.structured_content is not None
            assert len(summary.model_dump_json(by_alias=True).encode()) <= 2 * 1024 * 1024
            expected = await case.service.get_research_summary(principal, case.query())
            assert summary.structured_content["data"] == wire.ResearchSummary.model_validate(
                adapter.research_view(expected)
            ).model_dump(mode="json")
            saved = summary.structured_content["data"]["items"][0]
            identity = {"account_id": str(case.account_id), "item_id": saved["item_id"]}
            detail = await connection.call(client, "get_research_item", identity)
            assert not detail.is_error and detail.structured_content is not None
            assert detail.structured_content["data"] == saved
            assert (
                "<script>untrusted_research()</script>"
                in detail.structured_content["data"]["source"]["facts"]["summary"]
            )
            assert detail.structured_content["data"]["synthesis"]["availability"] == "unavailable"
            foreign = await connection.call(
                client, "get_research_item", {**identity, "account_id": str(uuid4())}
            )
            assert foreign.is_error and foreign.structured_content is not None
            assert foreign.structured_content["error"]["code"] == "NOT_FOUND"
            case.authority.revoked = True
            revoked = await connection.call(client, "get_research_item", identity)
            assert (
                revoked.is_error
                and revoked.structured_content is not None
                and revoked.structured_content["data"] is None
            )
            assert revoked.structured_content["error"]["code"] == "SOURCE_UNAVAILABLE"
            case.authority.revoked = False
            with case.xray.sessions() as session, session.begin():
                session.get_one(
                    PrincipalScopeGrantModel,
                    (UUID(principal.principal_id), Scope.RESEARCH_READ.value),
                ).revoked_at = case.xray.now[0]
            denied = await connection.call(
                client, "get_research_summary", {**arguments, "cursor": "malformed"}
            )
            assert denied.is_error and denied.structured_content is not None
            assert (
                denied.structured_content["error"]["code"] == "ACCESS_DENIED"
                and denied.structured_content["data"] is None
            )
        http.headers["Authorization"] = authorization(aud=RESOURCE + "/wrong")
        assert (await connection.raw("tools/list", {})).status_code == 401
    assert outbound.await_count == 0
    guard.finish()
