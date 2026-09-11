"""One read-only, finite alert summary operation; no alert commands or widgets."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field, StrictInt
from trading212_api_contracts import alerts as wire
from trading212_api_contracts.sources import CalendarDate
from trading212_api_contracts.targets import AwareInstant, Cursor, UUIDString
from trading212_security.principals import Scope

from .alert_gateway import AlertMcpGateway
from .alert_schemas import AlertSummaryToolResult
from .sdk_compat import finalize_tool_contract, harden_target_arguments

ALERT_TOOL_NAMES = ("get_alert_summary",)
McpCalendarDate = Annotated[CalendarDate, Field(strict=False)]
McpAwareInstant = Annotated[AwareInstant, Field(strict=False)]


def register_alert_tools(server: MCPServer[Any], gateway: AlertMcpGateway) -> None:
    @server.tool(
        name="get_alert_summary",
        title="Read alert history and summary",
        description=(
            "Read authorized alert events and exact full-filter counts as known at the requested "
            "UTC source cutoff and date window. Acknowledgment and resolution are independent. "
            "The cursor freezes scoped membership; proof and unavailable states remain explicit. "
            "This tool cannot create rules, acknowledge events, deliver notifications or trade."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
        meta={
            "securitySchemes": [
                {"type": "oauth2", "scopes": [Scope.PORTFOLIO_READ.value, Scope.ALERTS_READ.value]}
            ]
        },
        structured_output=False,
    )
    async def get_alert_summary(
        account_id: UUIDString,
        start_date: McpCalendarDate,
        end_date: McpCalendarDate,
        source_cutoff_at: McpAwareInstant,
        context: Context[Any, Any],
        state: Literal["open", "acknowledged", "resolved", "all"] = "open",
        severity: Literal["info", "warning", "critical", "all"] = "all",
        cursor: Cursor | None = None,
        limit: Annotated[StrictInt, Field(ge=1, le=100)] = 25,
    ) -> CallToolResult:
        request = wire.McpAlertSummaryRequest.model_validate(
            {
                "account_id": account_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "source_cutoff_at": source_cutoff_at.isoformat(),
                "state": state,
                "severity": severity,
                "cursor": cursor,
                "limit": limit,
            }
        )
        return await gateway.get_alert_summary(request, context=context)

    finalize_tool_contract(server, name="get_alert_summary", output_model=AlertSummaryToolResult)
    harden_target_arguments(server, name="get_alert_summary")
