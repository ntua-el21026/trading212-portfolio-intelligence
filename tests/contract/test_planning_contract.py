"""Exact P2-02 tool/route/client contracts and network-isolated plan presentation."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
from mcp.server.lowlevel.helper_types import ReadResourceContents
from trading212_api_contracts.typescript import render_planning_client, render_target_client
from trading212_mcp.planning_widget import PLAN_WIDGET_HTML, PLAN_WIDGET_URI
from trading212_mcp.server import create_runtime
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

pytestmark = pytest.mark.contract
NAMES = (
    "get_actual_vs_target",
    "get_drift_analysis",
    "get_contribution_plan",
    "create_contribution_plan",
)


async def test_four_tools_have_exact_scopes_annotations_and_no_future_registry_placeholders() -> (
    None
):
    server = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        )
    ).server
    tools = await server.list_tools()
    assert len(tools) == 28 and tuple(tool.name for tool in tools[11:15]) == NAMES
    assert tools[24].name == "get_alert_summary"
    assert tuple(tool.name for tool in tools[25:]) == (
        "create_risk_run",
        "get_risk_summary",
        "get_risk_matrix",
    )
    for tool in tools[11:15]:
        descriptor = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert descriptor["annotations"] == {
            "readOnlyHint": tool.name != "create_contribution_plan",
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        expected = ["portfolio:read", "targets:read", "analytics:read"]
        if tool.name == "get_contribution_plan":
            expected = ["portfolio:read", "analytics:read"]
        if tool.name == "create_contribution_plan":
            expected.append("plans:write")
        assert descriptor["_meta"]["securitySchemes"] == [{"type": "oauth2", "scopes": expected}]
        assert descriptor["inputSchema"]["additionalProperties"] is False
        assert descriptor["outputSchema"]["additionalProperties"] is False
        if "limit" in descriptor["inputSchema"]["properties"]:
            assert descriptor["inputSchema"]["properties"]["limit"]["maximum"] == 100
        if tool.name == "get_drift_analysis":
            assert descriptor["inputSchema"]["properties"]["top_n"]["maximum"] == 50
        if tool.name in {"get_contribution_plan", "create_contribution_plan"}:
            assert descriptor["_meta"]["ui"] == {
                "resourceUri": PLAN_WIDGET_URI,
                "visibility": ["model", "app"],
            }
            assert descriptor["_meta"]["openai/outputTemplate"] == PLAN_WIDGET_URI


async def test_plan_resource_csp_hashes_bind_every_inline_script_and_style() -> None:
    server = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        )
    ).server
    resources = list(await server.read_resource(PLAN_WIDGET_URI))
    assert len(resources) == 1 and isinstance(resources[0], ReadResourceContents)
    resource = resources[0]
    assert resource.content == PLAN_WIDGET_HTML and resource.meta is not None
    assert resource.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}
    assert resource.meta["openai/widgetCSP"] == {"connect_domains": [], "resource_domains": []}
    for tag in ("script", "style"):
        parts = re.findall(rf"<{tag}>(.*?)</{tag}>", PLAN_WIDGET_HTML, re.S)
        assert len(parts) == 1
        digest = base64.b64encode(hashlib.sha256(parts[0].encode()).digest()).decode()
        assert f"{tag}-src 'sha256-{digest}'" in PLAN_WIDGET_HTML
    assert "default-src 'none'" in PLAN_WIDGET_HTML and "connect-src 'none'" in PLAN_WIDGET_HTML
    assert (
        "textContent" in PLAN_WIDGET_HTML and "event.source !== window.parent" in PLAN_WIDGET_HTML
    )
    assert "ui/notifications/tool-result" in PLAN_WIDGET_HTML
    for unsafe in (
        "innerHTML",
        "eval(",
        "fetch(",
        "<iframe",
        "<script src=",
        "Number(",
        "parseFloat(",
    ):
        assert unsafe not in PLAN_WIDGET_HTML


def _contract() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text()),
    )


def test_six_generated_planning_operations_are_closed_and_separate_from_targets() -> None:
    contract = _contract()
    rendered = render_planning_client(contract)
    names = {
        operation["operationId"]
        for methods in contract["paths"].values()
        for operation in methods.values()
        if "planning" in operation.get("tags", [])
    }
    assert names == {*NAMES, "list_contribution_plans", "create_contribution_plan_revision"}
    assert all(f"async {name}(" in rendered for name in names)
    assert rendered == render_planning_client(copy.deepcopy(contract))
    assert "async create_virtual_portfolio(" not in rendered
    assert "async create_contribution_plan(" not in render_target_client(contract)
    assert "z.any(" not in rendered and "z.unknown(" not in rendered
    assert "z.strictObject(" in rendered and "encodeURIComponent(" in rendered
    for method in ("create_contribution_plan", "create_contribution_plan_revision"):
        operation = next(
            value
            for methods in contract["paths"].values()
            for value in methods.values()
            if value.get("operationId") == method
        )
        assert "202" in operation["responses"]
        assert any(
            p["name"] == "X-Idempotency-Key" and p["required"] for p in operation["parameters"]
        )
