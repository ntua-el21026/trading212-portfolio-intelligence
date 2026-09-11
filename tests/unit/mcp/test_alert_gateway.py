"""The one alert MCP operation is bounded, read-only and shares exact retained proof."""

from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from trading212_application import alerts as app
from trading212_application.alert_projection import alert_content
from trading212_mcp.server import create_runtime
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.unit.api.alert_factories import ACCOUNT, NOW, summary_page

ARGS: dict[str, Any] = {
    "account_id": ACCOUNT,
    "start_date": "2026-09-01",
    "end_date": "2026-09-10",
    "source_cutoff_at": NOW.isoformat(),
}


def runtime(service: AsyncMock) -> MCPServer[Any]:
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        alert_service=cast(app.AlertService, service),
        clock=lambda: NOW,
    ).server


async def test_exact_alert_descriptor_has_only_window_filters_and_no_widget_or_command() -> None:
    server = runtime(AsyncMock(spec=app.AlertService))
    descriptor = next(
        item for item in await server.list_tools() if item.name == "get_alert_summary"
    ).model_dump(by_alias=True)
    assert set(descriptor["inputSchema"]["required"]) == {
        "account_id",
        "start_date",
        "end_date",
        "source_cutoff_at",
    }
    assert set(descriptor["inputSchema"]["properties"]) == set(ARGS) | {
        "state",
        "severity",
        "cursor",
        "limit",
    }
    assert descriptor["inputSchema"]["additionalProperties"] is False
    assert descriptor["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
        "title": None,
    }
    assert "ui" not in descriptor["_meta"]
    assert descriptor["_meta"]["securitySchemes"] == [
        {"type": "oauth2", "scopes": ["portfolio:read", "alerts:read"]}
    ]


async def test_summary_uses_same_typed_counts_history_and_proof_without_private_basis() -> None:
    service = AsyncMock(spec=app.AlertService)
    service.get_summary.return_value = summary_page()
    result = await runtime(service).call_tool("get_alert_summary", ARGS)
    assert isinstance(result, CallToolResult) and not result.is_error and result.structured_content
    assert result.structured_content["data"] == alert_content(summary_page())
    assert result.structured_content["pagination"]["total"] == 1
    assert (
        "comparison_basis" not in result.model_dump_json()
        and "owner_id" not in result.model_dump_json()
    )
    query = service.get_summary.await_args.kwargs["query"]
    assert (
        isinstance(query, app.AlertSummaryWindowQuery)
        and query.source_cutoff_at == NOW
        and query.limit == 25
    )
    service.create_rule.assert_not_awaited()
    service.acknowledge_event.assert_not_awaited()


@pytest.mark.parametrize(
    "extra",
    [
        {"top_n": 5},
        {"rule_id": ACCOUNT},
        {"action": "resolve"},
        {"destination": "private-alert-canary"},
        {"limit": True},
        {"limit": 101},
        {"limit": "25"},
    ],
)
async def test_unsupported_alert_arguments_never_reach_service(extra: dict[str, object]) -> None:
    service = AsyncMock(spec=app.AlertService)
    with pytest.raises(ToolError) as failure:
        await runtime(service).call_tool("get_alert_summary", {**ARGS, **extra})
    assert "private-alert-canary" not in str(failure.value)
    service.get_summary.assert_not_awaited()


async def test_invalid_result_and_private_errors_fail_closed() -> None:
    service = AsyncMock(spec=app.AlertService)
    service.get_summary.return_value = {"count": 0}
    result = await runtime(service).call_tool("get_alert_summary", ARGS)
    assert isinstance(result, CallToolResult) and result.is_error
    service.get_summary.side_effect = app.AlertServiceError(
        app.AlertServiceErrorCode.ACCESS_DENIED, "private-alert-canary"
    )
    result = await runtime(service).call_tool("get_alert_summary", ARGS)
    assert (
        isinstance(result, CallToolResult)
        and result.is_error
        and "private-alert-canary" not in result.model_dump_json()
    )
