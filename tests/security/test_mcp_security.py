"""Adversarial checks for the MCP authentication and exposure boundary."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient
from trading212_application.services import SyntheticPortfolioService
from trading212_mcp.server import FROZEN_TOOL_NAMES, create_runtime
from trading212_mcp.settings import McpSettings
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import (
    CredentialBackend,
    RuntimeEnvironment,
    SecuritySettings,
)

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _tool_call(
    *,
    tool_name: str = "get_account_summary",
    account_id: str = SyntheticPortfolioService.ACCOUNT_ID,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {"account_id": account_id}},
    }


class StaticBearerAuthenticator:
    """Test double for the shared, server-side bearer validation boundary."""

    accepted_token = "test-valid-oauth-token"

    def __init__(self, scopes: frozenset[Scope] | None = None) -> None:
        self.scopes = scopes or frozenset(
            {
                Scope.PORTFOLIO_READ,
                Scope.ACTIVITY_READ,
                Scope.CONFIGURATION_READ,
            }
        )

    async def authenticate(self, token: str) -> Principal:
        if token != self.accepted_token:
            raise AuthenticationError("invalid bearer credential")
        return Principal(
            principal_id="test-principal",
            owner_id=SyntheticPortfolioService.OWNER_ID,
            issuer="issuer.example",
            subject="test-subject",
            scopes=self.scopes,
            authenticated_at=datetime(2026, 1, 1, tzinfo=UTC),
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )


@pytest.mark.security
def test_missing_auth_configuration_fails_closed_but_health_remains_observable() -> None:
    runtime = create_runtime()

    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        denied = client.post("/mcp", headers=MCP_HEADERS, json=_tool_call())
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"
    assert denied.json() == {
        "error": "invalid_token",
        "error_description": "Authentication required",
    }
    assert live.status_code == 200
    assert live.json() == {"service": "mcp", "status": "ok"}
    assert ready.status_code == 503
    assert ready.json()["reason"] == "authentication_not_configured"
    for response in (denied, live, ready):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.security
def test_local_synthetic_non_loopback_bind_requires_explicit_local_container_opt_in() -> None:
    test_security = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
    )

    with pytest.raises(ValueError, match="explicit local-container bind opt-in"):
        create_runtime(
            security_settings=test_security,
            mcp_settings=McpSettings(host="192.0.2.1"),
        )
    with pytest.raises(ValueError, match="explicit local-container bind opt-in"):
        create_runtime(
            security_settings=test_security,
            mcp_settings=McpSettings(
                host="192.0.2.1",
                allow_non_loopback_local_synthetic_bind=True,
            ),
        )

    local_security = SecuritySettings(
        environment=RuntimeEnvironment.LOCAL,
        local_synthetic_auth_enabled=True,
    )
    runtime = create_runtime(
        security_settings=local_security,
        mcp_settings=McpSettings(
            host="192.0.2.1",
            allow_non_loopback_local_synthetic_bind=True,
        ),
    )
    assert runtime.access_control_configured is True


@pytest.mark.security
def test_public_urls_require_https() -> None:
    with pytest.raises(ValueError, match="public_base_url must use HTTPS"):
        McpSettings.model_validate({"public_base_url": "http://portfolio.example"})
    with pytest.raises(ValueError, match="widget_domain must use HTTPS"):
        McpSettings.model_validate({"widget_domain": "http://widgets.example"})


@pytest.mark.security
def test_deployed_runtime_requires_explicit_portfolio_store_composition() -> None:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.PRODUCTION,
        issuer="https://identity.example.test",
        audience="portfolio-mcp",
        jwt_public_key_reference="vault://jwt-public-key",
        session_signing_key_reference="vault://session-key",
        cursor_signing_key_reference="vault://cursor-signing-key",
        credential_backend=CredentialBackend.EXTERNAL,
        outbox_dispatcher_configured=True,
        allowed_origins=("https://portfolio.example.test",),
        allowed_hosts=("portfolio.example.test",),
    )

    with pytest.raises(ValueError, match="explicit service or DATABASE_URL"):
        create_runtime(security_settings=settings)


@pytest.mark.security
def test_transport_rejects_untrusted_hosts_and_oversized_bodies() -> None:
    security = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("localhost",),
    )
    runtime = create_runtime(
        security_settings=security,
        mcp_settings=McpSettings(max_request_body_bytes=16_384),
    )

    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        bad_host = client.post(
            "/mcp",
            headers={**MCP_HEADERS, "Host": "attacker.example"},
            json=_tool_call(),
        )
        oversized = client.post(
            "/mcp",
            headers=MCP_HEADERS,
            content=b'{"padding":"' + (b"x" * 17_000) + b'"}',
        )

    assert bad_host.status_code == 421
    assert "attacker.example" not in bad_host.text
    assert oversized.status_code == 413


@pytest.mark.security
def test_shared_oauth_boundary_rejects_invalid_tokens_and_never_echoes_valid_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    authenticator = StaticBearerAuthenticator()
    security = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        issuer="https://issuer.example",
        allowed_hosts=("localhost",),
    )
    runtime = create_runtime(
        security_settings=security,
        mcp_settings=McpSettings.model_validate({"public_base_url": "https://portfolio.example"}),
        bearer_authenticator=authenticator,
    )
    caplog.set_level(logging.INFO, logger="trading212_mcp.audit")

    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        missing = client.post("/mcp", headers=MCP_HEADERS, json=_tool_call())
        invalid = client.post(
            "/mcp",
            headers={**MCP_HEADERS, "Authorization": "Bearer invalid-oauth-token"},
            json=_tool_call(),
        )
        valid = client.post(
            "/mcp",
            headers={
                **MCP_HEADERS,
                "Authorization": f"Bearer {authenticator.accepted_token}",
            },
            json=_tool_call(),
        )
        resource_metadata = client.get("/.well-known/oauth-protected-resource/mcp")

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200
    assert (
        'resource_metadata="https://portfolio.example/.well-known/oauth-protected-resource/mcp"'
        in (missing.headers["www-authenticate"])
    )
    assert resource_metadata.status_code == 200
    assert resource_metadata.json() == {
        "resource": "https://portfolio.example/mcp",
        "authorization_servers": ["https://issuer.example"],
        # Per-tool scopes are advertised in each descriptor and enforced by application services.
        "scopes_supported": [],
        "bearer_methods_supported": ["header"],
    }
    assert resource_metadata.headers.get_list("cache-control") == ["no-store"]
    assert valid.json()["result"]["isError"] is False
    rendered = f"{valid.text}\n{caplog.text}"
    assert authenticator.accepted_token not in rendered
    assert "invalid-oauth-token" not in rendered
    assert SyntheticPortfolioService.ACCOUNT_ID not in caplog.text
    assert SyntheticPortfolioService.OWNER_ID not in caplog.text


@pytest.mark.security
@pytest.mark.parametrize(
    "scopes",
    [
        frozenset({Scope.PORTFOLIO_READ}),
        frozenset({Scope.ACTIVITY_READ}),
    ],
)
def test_data_quality_tool_metadata_matches_runtime_scope_enforcement(
    scopes: frozenset[Scope],
) -> None:
    authenticator = StaticBearerAuthenticator(scopes)
    security = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        issuer="https://issuer.example",
        allowed_hosts=("localhost",),
    )
    runtime = create_runtime(
        security_settings=security,
        mcp_settings=McpSettings.model_validate({"public_base_url": "https://portfolio.example"}),
        bearer_authenticator=authenticator,
    )
    tools = asyncio.run(runtime.server.list_tools())
    descriptor = next(tool for tool in tools if tool.name == "get_data_quality_summary")

    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers={
                **MCP_HEADERS,
                "Authorization": f"Bearer {authenticator.accepted_token}",
            },
            json=_tool_call(tool_name="get_data_quality_summary"),
        )

    result = response.json()["result"]
    assert descriptor.meta is not None
    assert descriptor.meta["securitySchemes"] == [
        {
            "type": "oauth2",
            "scopes": [Scope.PORTFOLIO_READ.value, Scope.ACTIVITY_READ.value],
        }
    ]
    assert response.status_code == 200
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "ACCESS_DENIED"


class ExplodingService(SyntheticPortfolioService):
    async def get_summary(self, principal: Any, account_id: str) -> Any:
        del principal, account_id
        raise RuntimeError("Bearer raw-provider-secret-and-stack-detail")


@pytest.mark.security
def test_internal_failure_and_hostile_correlation_value_are_structured_and_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
    )
    runtime = create_runtime(security_settings=settings, service=ExplodingService())
    caplog.set_level(logging.INFO, logger="trading212_mcp.audit")

    hostile_correlation = "Bearer raw-correlation-secret"
    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers={**MCP_HEADERS, "X-Correlation-ID": hostile_correlation},
            json=_tool_call(),
        )

    assert response.status_code == 200
    result = response.json()["result"]
    rendered = response.text + caplog.text
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "INTERNAL_ERROR"
    assert "raw-provider-secret" not in rendered
    assert "stack-detail" not in rendered
    assert "RuntimeError" not in rendered
    assert hostile_correlation not in rendered
    assert SyntheticPortfolioService.ACCOUNT_ID not in caplog.text


@pytest.mark.security
def test_mcp_source_has_no_provider_transport_orm_or_generic_proxy_surface() -> None:
    source_root = Path(__file__).parents[2] / "apps" / "mcp" / "src"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))
    forbidden_imports = (
        "import httpx",
        "import requests",
        "import sqlalchemy",
        "import trading212_provider",
        "from trading212_provider",
    )
    forbidden_tools = {
        "generic_http",
        "request_url",
        "provider_request",
        "execute_sql",
        "place_order",
        "cancel_order",
    }

    assert all(value not in sources for value in forbidden_imports)
    assert forbidden_tools.isdisjoint(FROZEN_TOOL_NAMES)
    assert len(FROZEN_TOOL_NAMES) == 25
    assert FROZEN_TOOL_NAMES[15:] == (
        "get_performance_summary",
        "get_benchmark_comparison",
        "get_dividend_intelligence",
        "get_attribution_summary",
        "get_effective_exposure",
        "get_etf_overlap",
        "get_report_status",
        "list_reports",
        "generate_portfolio_report",
        "get_alert_summary",
    )
