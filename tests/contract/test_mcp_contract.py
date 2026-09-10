"""Wire-contract and API-parity tests for the Phase 1 MCP gateway."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.lowlevel.helper_types import ReadResourceContents
from starlette.testclient import TestClient
from trading212_api.main import create_app as create_api_app
from trading212_application.services import SyntheticPortfolioService
from trading212_mcp.schemas import RESULT_MODELS
from trading212_mcp.sdk_compat import (
    TOP_LEVEL_SECURITY_SCHEMES_BLOCKER,
    TOP_LEVEL_SECURITY_SCHEMES_SUPPORTED,
)
from trading212_mcp.server import FROZEN_TOOL_NAMES, create_runtime
from trading212_mcp.widget import SNAPSHOT_WIDGET_MIME, SNAPSHOT_WIDGET_URI
from trading212_security.settings import RuntimeEnvironment, SecuritySettings


def _test_settings() -> SecuritySettings:
    return SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("localhost", "testserver"),
    )


@pytest.mark.contract
async def test_tool_discovery_is_exact_typed_bounded_and_annotated() -> None:
    runtime = create_runtime(security_settings=_test_settings())
    tools = await runtime.server.list_tools()

    assert tuple(tool.name for tool in tools) == FROZEN_TOOL_NAMES
    assert len(tools) == 24
    for tool in tools:
        descriptor = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert descriptor["inputSchema"]["type"] == "object"
        assert descriptor["inputSchema"]["additionalProperties"] is False
        assert descriptor["outputSchema"]["type"] == "object"
        assert descriptor["outputSchema"]["additionalProperties"] is False
        assert descriptor["annotations"] == {
            "readOnlyHint": tool.name
            not in {"create_contribution_plan", "generate_portfolio_report"},
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        schemes = descriptor["_meta"]["securitySchemes"]
        assert schemes[0]["type"] == "oauth2"
        assert schemes[0]["scopes"]
        assert "outputSchema" in descriptor
        assert tool.name in RESULT_MODELS


@pytest.mark.contract
async def test_python_sdk_security_scheme_upstream_gate_is_explicit() -> None:
    runtime = create_runtime(security_settings=_test_settings())
    descriptor = (await runtime.server.list_tools())[0].model_dump(
        mode="json", by_alias=True, exclude_none=True
    )

    assert TOP_LEVEL_SECURITY_SCHEMES_SUPPORTED is False
    assert "mcp==2.1.1" in TOP_LEVEL_SECURITY_SCHEMES_BLOCKER
    assert "securitySchemes" not in descriptor
    assert descriptor["_meta"]["securitySchemes"] == [
        {"type": "oauth2", "scopes": ["portfolio:read"]}
    ]


@pytest.mark.contract
async def test_snapshot_widget_is_preserved_and_only_declared_tools_add_resources() -> None:
    runtime = create_runtime(security_settings=_test_settings())
    descriptors = {
        tool.name: tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        for tool in await runtime.server.list_tools()
    }

    snapshot_meta = descriptors["get_portfolio_snapshot"]["_meta"]
    assert snapshot_meta["ui"] == {
        "resourceUri": SNAPSHOT_WIDGET_URI,
        "visibility": ["model", "app"],
    }
    assert snapshot_meta["openai/outputTemplate"] == SNAPSHOT_WIDGET_URI
    for name, descriptor in descriptors.items():
        if name not in {
            "get_portfolio_snapshot",
            "get_contribution_plan",
            "create_contribution_plan",
            "get_performance_summary",
            "get_benchmark_comparison",
            "get_effective_exposure",
            "get_etf_overlap",
            "get_report_status",
            "generate_portfolio_report",
        }:
            assert "ui" not in descriptor["_meta"]
            assert "openai/outputTemplate" not in descriptor["_meta"]

    contents = list(await runtime.server.read_resource(SNAPSHOT_WIDGET_URI))
    assert len(contents) == 1
    resource = contents[0]
    assert isinstance(resource, ReadResourceContents)
    assert resource.mime_type == SNAPSHOT_WIDGET_MIME
    assert resource.meta is not None
    assert resource.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}
    assert resource.meta["openai/widgetCSP"] == {
        "connect_domains": [],
        "resource_domains": [],
    }
    html = str(resource.content)
    assert "ui/initialize" in html
    assert "ui/notifications/tool-result" in html
    assert "window.openai?.toolOutput" in html
    assert html.index("ui/notifications/tool-result") < html.index("window.openai?.toolOutput")
    assert "textContent" in html
    assert "Read-only" in html
    assert "Synthetic data" in html
    assert "Quality:" in html
    assert "<script src=" not in html
    assert "fetch(" not in html


@pytest.mark.contract
def test_streamable_http_discovery_and_structured_call() -> None:
    runtime = create_runtime(security_settings=_test_settings())
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "contract-test", "version": "1.0.0"},
        },
    }

    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        initialized = client.post("/mcp", headers=headers, json=initialize)
        tools = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        called = client.post(
            "/mcp",
            headers={**headers, "X-Correlation-ID": "contract-correlation"},
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "get_portfolio_snapshot",
                    "arguments": {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
                },
            },
        )

    assert initialized.status_code == 200
    assert initialized.json()["result"]["protocolVersion"] == "2025-11-25"
    assert tools.status_code == 200
    assert tuple(item["name"] for item in tools.json()["result"]["tools"]) == FROZEN_TOOL_NAMES
    assert called.status_code == 200
    result = called.json()["result"]
    assert result["isError"] is False
    assert result["_meta"]["correlationId"] == "contract-correlation"
    assert result["structuredContent"]["data"]["read_only"] is True
    assert result["structuredContent"]["data"]["synthetic_data"] is True
    assert called.headers["cache-control"] == "no-store"


@pytest.mark.contract
def test_http_api_and_mcp_share_canonical_fixture_values() -> None:
    service = SyntheticPortfolioService()
    settings = _test_settings()
    api = create_api_app(settings=settings, service=service)
    mcp = create_runtime(security_settings=settings, service=service)

    assert api.state.context.service is service
    assert mcp.service is service

    with TestClient(api, base_url="https://testserver") as api_client:
        session = api_client.post("/api/v1/auth/local-session")
        assert session.status_code == 201
        api_response = api_client.get(
            f"/api/v1/accounts/{SyntheticPortfolioService.ACCOUNT_ID}/summary"
        )
        assert api_response.status_code == 200

    with TestClient(mcp.asgi_app(), base_url="http://localhost") as mcp_client:
        mcp_response = mcp_client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_account_summary",
                    "arguments": {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
                },
            },
        )
        assert mcp_response.status_code == 200

    api_data: dict[str, Any] = api_response.json()
    mcp_data: dict[str, Any] = mcp_response.json()["result"]["structuredContent"]["data"]
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
    assert mcp_data["account"] == api_data["account"]
    assert mcp_data["position_count"] == api_data["position_count"]
