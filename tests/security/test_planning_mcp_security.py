"""Bearer authorization for fixed planning reads and the sole P2-02 internal command."""

from __future__ import annotations

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
ACCOUNT = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee"
PORTFOLIO = "aef0bdf3-3613-4cfe-b15f-bc1f8b9c4119"
TARGET = "19a8b590-9c18-4c43-8dce-d622cb6ae033"
SNAPSHOT = "5dd1049e-7433-43f4-bf5b-3a73c24c0568"
PLAN = "b7e267ab-9f80-4cda-8f5e-e5c28a7f72b9"
ALL = frozenset({Scope.PORTFOLIO_READ, Scope.TARGETS_READ, Scope.ANALYTICS_READ, Scope.PLANS_WRITE})


class PlanningBearer:
    def __init__(self, scopes: frozenset[Scope]) -> None:
        self.scopes = scopes
        self.token = "_".join(("PLANNING", "BEARER", "CANARY"))

    async def authenticate(self, token: str) -> Principal:
        if token != self.token:
            raise AuthenticationError("Invalid credential.")
        return Principal(
            "planning-mcp-test",
            "fb020dd0-1d4c-4203-ac5d-c28203aa2002",
            "issuer.example",
            "planning-mcp-test",
            self.scopes,
            NOW,
            datetime(2099, 1, 1, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "tool",
    [
        "get_actual_vs_target",
        "get_drift_analysis",
        "get_contribution_plan",
        "create_contribution_plan",
    ],
)
@pytest.mark.parametrize("scopes", [frozenset(), *[ALL - {scope} for scope in sorted(ALL)], ALL])
def test_mcp_scopes_precede_service_availability_and_do_not_echo_credentials(
    tool: str, scopes: frozenset[Scope], caplog: pytest.LogCaptureFixture
) -> None:
    bearer = PlanningBearer(scopes)
    runtime = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            issuer="https://issuer.example",
            allowed_hosts=("localhost",),
        ),
        mcp_settings=McpSettings.model_validate({"public_base_url": "https://portfolio.example"}),
        bearer_authenticator=bearer,
        clock=lambda: NOW,
    )
    args: dict[str, Any] = {"account_id": ACCOUNT}
    expected = {Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}
    if tool == "get_contribution_plan":
        args["plan_id"] = PLAN
    else:
        expected.add(Scope.TARGETS_READ)
        args.update(snapshot_id=SNAPSHOT, virtual_portfolio_id=PORTFOLIO, target_version_id=TARGET)
        if tool == "create_contribution_plan":
            expected.add(Scope.PLANS_WRITE)
            args.update(
                idempotency_key="scoped:plan",
                contribution={"amount": "10", "currency": "EUR"},
                mode="cash_only",
            )
        else:
            args["reporting_currency"] = "EUR"
    with (
        caplog.at_level(logging.INFO),
        TestClient(runtime.asgi_app(), base_url="http://localhost") as client,
    ):
        response = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {bearer.token}",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            },
        )
    assert bearer.token not in response.text + caplog.text
    assert ACCOUNT not in caplog.text
    if not scopes:
        assert response.status_code == 401
    else:
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["isError"] is True
        assert result["structuredContent"]["error"]["code"] == (
            "PLANNING_UNAVAILABLE" if expected <= scopes else "ACCESS_DENIED"
        )
        assert result["structuredContent"]["data"] is None
