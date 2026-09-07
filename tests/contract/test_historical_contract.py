"""Exact additive historical HTTP/MCP contracts and isolated static resource policy."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from trading212_api.main import create_app
from trading212_application.services import SyntheticPortfolioService
from trading212_mcp.historical_tools import HISTORICAL_TOOL_NAMES
from trading212_mcp.historical_widget import HISTORICAL_WIDGET_HTML, HISTORICAL_WIDGET_URI
from trading212_mcp.server import create_runtime

ROOT = Path(__file__).resolve().parents[2]


def test_exact_six_historical_get_routes_leave_existing_performance_summary() -> None:
    contract = create_app(service=SyntheticPortfolioService()).openapi()
    methods = {
        (path, method)
        for path, operations in contract["paths"].items()
        for method, operation in operations.items()
        if "historical" in operation.get("tags", [])
    }
    assert methods == {
        (f"/api/v1/accounts/{{account_id}}/{suffix}", "get")
        for suffix in (
            "performance/series",
            "performance/intelligence",
            "benchmark-comparison",
            "attribution",
            "dividend-intelligence",
            "cash-flow-intelligence",
        )
    }
    assert "/api/v1/accounts/{account_id}/performance/summary" in contract["paths"]
    assert sum(len(methods) for methods in contract["paths"].values()) == 66
    assert contract == json.loads(
        (ROOT / "packages/api-contracts/openapi/phase1-v1.json").read_text()
    )


async def test_exact_four_historical_tools_have_frozen_scopes_fields_annotations_and_resource() -> (
    None
):
    server = create_runtime().server
    tools = await server.list_tools()
    assert len(tools) == 19 and tuple(tool.name for tool in tools[15:]) == HISTORICAL_TOOL_NAMES
    common = {"account_id", "start_date", "end_date", "source_cutoff_at", "reporting_currency"}
    extras = (
        {"method", "frequency"},
        {"benchmark_version_id", "frequency"},
        {"top_n"},
        {"grouping", "target_version_id", "top_n"},
    )
    scopes = (
        ["portfolio:read", "analytics:read"],
        ["portfolio:read", "analytics:read"],
        ["portfolio:read", "activity:read", "analytics:read"],
        ["portfolio:read", "analytics:read", "targets:read"],
    )
    for tool, extra, required in zip(tools[15:], extras, scopes, strict=True):
        descriptor = tool.model_dump(by_alias=True)
        assert set(descriptor["inputSchema"]["properties"]) == common | extra
        assert descriptor["inputSchema"]["additionalProperties"] is False
        assert descriptor["annotations"] == {
            "title": None,
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        assert descriptor["_meta"]["securitySchemes"] == [{"type": "oauth2", "scopes": required}]
        assert descriptor["outputSchema"]["additionalProperties"] is False
        if tool.name in HISTORICAL_TOOL_NAMES[:2]:
            assert descriptor["_meta"]["ui"]["resourceUri"] == HISTORICAL_WIDGET_URI
            assert descriptor["_meta"]["openai/outputTemplate"] == HISTORICAL_WIDGET_URI
    resources = await server.list_resources()
    resource = next(item for item in resources if str(item.uri) == HISTORICAL_WIDGET_URI)
    metadata = resource.model_dump(by_alias=True)["_meta"]
    assert metadata["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}
    assert metadata["openai/widgetCSP"] == {"connect_domains": [], "resource_domains": []}


def test_comparison_widget_has_valid_hash_csp_safe_dom_and_no_network_or_financial_math() -> None:
    html = HISTORICAL_WIDGET_HTML
    for tag, directive in (("script", "script-src"), ("style", "style-src")):
        value = re.search(f"<{tag}>(.*?)</{tag}>", html, re.DOTALL)
        assert value is not None
        digest = base64.b64encode(hashlib.sha256(value[1].encode()).digest()).decode()
        assert f"{directive} 'sha256-{digest}'" in html
    for forbidden in (
        "innerHTML",
        "eval(",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "parseFloat",
        "Number(",
        "<iframe",
        "<form",
        "https://",
    ):
        assert forbidden not in html
    for required in (
        "connect-src 'none'",
        "textContent",
        "event.source !== window.parent",
        "<caption>",
        'scope="col"',
        'tabindex="0"',
        "prefers-reduced-motion",
        'role="status"',
        "point.cumulative_return",
    ):
        assert required in html
