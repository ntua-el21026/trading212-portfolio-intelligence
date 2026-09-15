"""X-ray adds only four typed GETs and bounded local discriminated client schemas."""

import base64
import copy
import hashlib
import json
import re
from pathlib import Path

import pytest
from trading212_api_contracts.typescript import TargetClientGenerator, render_xray_client
from trading212_mcp.server import create_runtime
from trading212_mcp.xray_tools import XRAY_TOOL_NAMES
from trading212_mcp.xray_widget import XRAY_WIDGET_HTML, XRAY_WIDGET_URI

pytestmark = pytest.mark.contract


def test_four_gets_and_closed_response_unions_generate_deterministically() -> None:
    contract = json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text())
    operations = [
        (method, operation["operationId"])
        for methods in contract["paths"].values()
        for method, operation in methods.items()
        if "xray" in operation.get("tags", [])
    ]
    assert set(operations) == {
        ("get", name)
        for name in (
            "get_effective_exposure",
            "get_etf_overlap",
            "get_constituent_snapshot",
            "list_constituent_holdings",
        )
    }
    rendered = render_xray_client(contract)
    assert rendered == render_xray_client(copy.deepcopy(contract))
    assert 'z.discriminatedUnion("view"' in rendered
    assert "z.any(" not in rendered and "z.unknown(" not in rendered
    assert '"source_reference_ids": z.array(' in rendered
    assert '"coefficient"' not in rendered


@pytest.mark.parametrize("mutation", ("optional", "duplicate", "wrong_mapping", "open", "inline"))
def test_discriminator_admission_rejects_ambiguous_or_open_branches(mutation: str) -> None:
    contract = json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text())
    union = contract["components"]["schemas"]["XrayEffectiveExposureResponse"]
    first = contract["components"]["schemas"]["XrayExposuresResponse"]
    if mutation == "optional":
        first["required"].remove("view")
    elif mutation == "duplicate":
        contract["components"]["schemas"]["XrayPathsResponse"]["properties"]["view"]["const"] = (
            "exposures"
        )
    elif mutation == "wrong_mapping":
        union["discriminator"]["mapping"]["exposures"] = "#/components/schemas/XrayPathsResponse"
    elif mutation == "open":
        first["additionalProperties"] = True
    else:
        union["oneOf"][0] = first
    with pytest.raises(ValueError):
        TargetClientGenerator(contract, tag="xray").schema(union)


async def test_exact_xray_tool_fields_scopes_bounds_and_isolated_resource() -> None:
    server = create_runtime().server
    tools = await server.list_tools()
    assert len(tools) == 32 and tuple(tool.name for tool in tools[19:21]) == XRAY_TOOL_NAMES
    common = {"account_id", "snapshot_id", "source_cutoff_at"}
    extra = (
        {"reporting_currency", "dimension", "cursor", "limit"},
        {"left_fund_id", "right_fund_id", "top_n"},
    )
    for tool, fields in zip(tools[19:21], extra, strict=True):
        descriptor = tool.model_dump(by_alias=True)
        schema = descriptor["inputSchema"]
        assert set(schema["properties"]) == common | fields
        assert schema["additionalProperties"] is False
        assert descriptor["outputSchema"]["additionalProperties"] is False
        assert descriptor["annotations"] == {
            "title": None,
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        assert descriptor["_meta"]["securitySchemes"] == [
            {"type": "oauth2", "scopes": ["portfolio:read", "analytics:read"]}
        ]
        assert descriptor["_meta"]["ui"]["resourceUri"] == XRAY_WIDGET_URI
        assert descriptor["_meta"]["openai/outputTemplate"] == XRAY_WIDGET_URI
    assert tools[19].input_schema["properties"]["limit"]["maximum"] == 100
    assert tools[20].input_schema["properties"]["top_n"]["maximum"] == 50
    resources = await server.list_resources()
    resource = next(item for item in resources if str(item.uri) == XRAY_WIDGET_URI)
    metadata = resource.model_dump(by_alias=True)["_meta"]
    assert metadata["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}
    assert metadata["openai/widgetCSP"] == {"connect_domains": [], "resource_domains": []}


def test_xray_widget_hashes_bound_static_code_and_uses_exact_returned_strings() -> None:
    html = XRAY_WIDGET_HTML
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
        'scope="col"',
        'tabindex="0"',
        "prefers-reduced-motion",
        'role="status"',
        "positive_below_quantum",
        "omitted_common_weight",
        "quality_evaluated_at",
    ):
        assert required in html
