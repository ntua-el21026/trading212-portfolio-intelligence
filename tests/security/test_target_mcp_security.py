"""OAuth scope parity for account and template target MCP reads."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from starlette.testclient import TestClient
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

pytestmark = pytest.mark.security
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


class TargetScopesBearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes
        self.token = "_".join(("TARGET", "BEARER", "CANARY"))

    async def authenticate(self, token: str) -> Principal:
        if token != self.token:
            raise AuthenticationError("Invalid test credential.")
        return Principal(
            "target-mcp-test",
            "fb020dd0-1d4c-4203-ac5d-c28203aa2002",
            "issuer.example",
            "target-mcp-test",
            self.scopes,
            NOW,
            datetime(2099, 1, 1, tzinfo=UTC),
        )


@pytest.mark.parametrize("tool_name", ["list_virtual_pies", "get_virtual_pie"])
@pytest.mark.parametrize("account_id", [None, "6390976b-402a-4813-835d-8a33e49c0643"])
@pytest.mark.parametrize(
    "scopes",
    [
        frozenset(),
        frozenset({Scope.PORTFOLIO_READ}),
        frozenset({Scope.TARGETS_READ}),
        frozenset({Scope.TARGETS_WRITE}),
        frozenset({Scope.PORTFOLIO_READ, Scope.TARGETS_READ}),
    ],
)
def test_target_tools_require_both_scopes_before_availability_without_secret_echo(
    tool_name: str,
    account_id: str | None,
    scopes: frozenset[Scope],
    caplog: pytest.LogCaptureFixture,
) -> None:
    authenticator = TargetScopesBearer(scopes)
    runtime = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            issuer="https://issuer.example",
            allowed_hosts=("localhost",),
        ),
        mcp_settings=McpSettings.model_validate({"public_base_url": "https://portfolio.example"}),
        bearer_authenticator=authenticator,
        clock=lambda: NOW,
    )
    descriptor = next(
        tool for tool in asyncio.run(runtime.server.list_tools()) if tool.name == tool_name
    )
    assert descriptor.meta is not None
    assert descriptor.meta["securitySchemes"] == [
        {
            "type": "oauth2",
            "scopes": ["portfolio:read", "targets:read"],
        }
    ]
    arguments: dict[str, Any] = {"account_id": account_id}
    if tool_name == "get_virtual_pie":
        arguments["virtual_portfolio_id"] = "1a15511f-015a-493f-aeba-4d293e9ecb76"
    with (
        caplog.at_level(logging.INFO),
        TestClient(runtime.asgi_app(), base_url="http://localhost") as client,
    ):
        response = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {authenticator.token}",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
    assert authenticator.token not in response.text + caplog.text
    if not scopes:
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"
        return
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    expected = (
        "TARGETS_UNAVAILABLE"
        if {Scope.PORTFOLIO_READ, Scope.TARGETS_READ} <= scopes
        else "ACCESS_DENIED"
    )
    assert result["structuredContent"]["error"]["code"] == expected
    if account_id is not None:
        assert account_id not in caplog.text
