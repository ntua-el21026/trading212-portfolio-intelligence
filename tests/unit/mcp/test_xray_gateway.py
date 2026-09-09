"""Frozen MCP X-ray contracts delegate canonical requests and hide private failures."""

from dataclasses import replace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from trading212_application import xray as app
from trading212_application.xray_projection import xray_public_primitive
from trading212_domain.enums import QualityState
from trading212_mcp.server import create_runtime
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.unit.api.xray_factories import ACCOUNT, NOW, QUERY, context, exposures, ratio, summary


def runtime(service: AsyncMock) -> MCPServer[Any]:
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        xray_service=cast(app.XrayService, service),
        clock=lambda: NOW,
    ).server


def top_pair() -> app.McpTopPairView:
    left = app.XrayHeldFundView(
        instrument_id=str(UUID(int=5)),
        name="Synthetic Fund A",
        position_count=1,
        composition_root_key=f"position:{UUID(int=10)}",
        constituent_snapshot_id=str(UUID(int=20)),
        source_at=NOW,
        unit_coverage=ratio("0.9"),
        cash_weight=ratio(),
        unresolved_weight=ratio("0.1"),
        complete=False,
        quality=QualityState.PARTIAL,
        confidence=None,
    )
    right = replace(left, instrument_id=str(UUID(int=6)), name="Synthetic Fund B")
    return app.McpTopPairView(
        context=context(),
        summary=summary(),
        pair=app.XrayOverlapPairView(
            id=str(UUID(int=30)),
            left=left,
            right=right,
            overlap=ratio("0.5"),
            common_entity_count=1,
        ),
        common_entities=(),
        total_count=1,
        returned_count=0,
        omitted_count=1,
        omitted_common_weight=ratio("0.5"),
    )


def args(name: str) -> dict[str, Any]:
    base = {"account_id": ACCOUNT, **QUERY}
    if name == "get_etf_overlap":
        base.pop("reporting_currency")
        base.update(left_fund_id=str(UUID(int=5)), right_fund_id=str(UUID(int=6)))
    return base


@pytest.mark.parametrize("name", ("get_effective_exposure", "get_etf_overlap"))
async def test_typed_canonical_data_and_currency_selection_delegate_once(name: str) -> None:
    service = AsyncMock(spec=app.XrayService)
    value = exposures() if name == "get_effective_exposure" else top_pair()
    getattr(service, name).return_value = value
    result = await runtime(service).call_tool(name, args(name))
    assert isinstance(result, CallToolResult) and not result.is_error, result
    assert result.structured_content is not None
    assert result.structured_content["data"] == xray_public_primitive(value)
    query = getattr(service, name).call_args.kwargs["query"]
    assert len(service.mock_calls) == 1
    if name == "get_effective_exposure":
        assert isinstance(query.request.currency, app.ExplicitCurrency)
        assert query.options.normalized_known_only is False
    else:
        assert isinstance(query.request.currency, app.SnapshotCurrency)
        assert query.options.top_n == 25 and query.request.run_id is None
        assert result.structured_content["data"]["omitted_common_weight"]["value"] == "0.5"


@pytest.mark.parametrize(
    ("name", "extra"),
    [
        ("get_effective_exposure", {"view": "paths"}),
        ("get_effective_exposure", {"normalized_known_only": True}),
        ("get_effective_exposure", {"limit": 101}),
        ("get_effective_exposure", {"limit": "25"}),
        ("get_etf_overlap", {"reporting_currency": "EUR"}),
        ("get_etf_overlap", {"run_id": str(UUID(int=3))}),
        ("get_etf_overlap", {"cursor": "opaque"}),
        ("get_etf_overlap", {"top_n": True}),
        ("get_etf_overlap", {"top_n": 51}),
        ("get_etf_overlap", {"provider_url": "private-canary"}),
    ],
)
async def test_http_only_and_unknown_selectors_are_rejected(
    name: str, extra: dict[str, Any]
) -> None:
    service = AsyncMock(spec=app.XrayService)
    with pytest.raises(ToolError) as error:
        await runtime(service).call_tool(name, {**args(name), **extra})
    assert "canary" not in str(error.value) and not service.mock_calls


async def test_wrong_owner_result_and_private_service_error_are_not_disclosed() -> None:
    service = AsyncMock(spec=app.XrayService)
    value = exposures()
    service.get_effective_exposure.return_value = replace(
        value, context=replace(value.context, account_id=str(UUID(int=99)))
    )
    server = runtime(service)
    wrong_owner = await server.call_tool("get_effective_exposure", args("get_effective_exposure"))
    assert isinstance(wrong_owner, CallToolResult) and wrong_owner.is_error
    assert wrong_owner.structured_content is not None
    assert wrong_owner.structured_content["error"]["code"] == "INTERNAL_ERROR"
    service.get_effective_exposure.side_effect = app.XrayServiceError(
        app.XrayServiceErrorCode.ACCESS_DENIED, "private-license-canary"
    )
    denied = await server.call_tool("get_effective_exposure", args("get_effective_exposure"))
    assert isinstance(denied, CallToolResult) and denied.is_error
    assert "canary" not in denied.model_dump_json()
    assert (
        denied.structured_content is not None
        and denied.structured_content["error"]["code"] == "ACCESS_DENIED"
    )


async def test_registry_exposes_exact_scopes_and_network_isolated_resource() -> None:
    server = runtime(AsyncMock(spec=app.XrayService))
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert len(tools) == 21
    for name in ("get_effective_exposure", "get_etf_overlap"):
        tool = tools[name]
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
        assert tool.meta is not None
        assert tool.meta["securitySchemes"] == [
            {"type": "oauth2", "scopes": ["portfolio:read", "analytics:read"]}
        ]
        assert tool.input_schema["additionalProperties"] is False
        assert tool.output_schema is not None
    resources = await server.list_resources()
    widget = next(
        item for item in resources if str(item.uri) == "ui://trading212-portfolio/xray-v1.html"
    )
    assert widget.meta is not None
    assert widget.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}
