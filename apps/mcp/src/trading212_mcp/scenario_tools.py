"""Exactly the four frozen scenario tools and one isolated MCP Apps resource."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import AnyHttpUrl, Field
from trading212_api_contracts import scenarios as wire
from trading212_api_contracts.targets import (
    AwareInstant,
    CurrencyString,
    Cursor,
    IdempotencyKey,
    UUIDString,
)
from trading212_security.principals import Scope

from .scenario_gateway import ScenarioMcpGateway
from .scenario_schemas import (
    ScenarioComparisonToolResult,
    ScenarioCreateToolResult,
    ScenarioListToolResult,
    ScenarioRunToolResult,
)
from .scenario_widget import SCENARIO_WIDGET_HTML, SCENARIO_WIDGET_MIME, SCENARIO_WIDGET_URI
from .sdk_compat import finalize_tool_contract, harden_target_arguments

SCENARIO_TOOL_NAMES = (
    "list_scenarios",
    "create_scenario_run",
    "get_scenario_result",
    "compare_scenarios",
)

# The SDK validates a Python argument dictionary. Preserve the DTO's explicit
# instant checks while allowing its JSON string to become an aware datetime.
McpAwareInstant = Annotated[AwareInstant, Field(strict=False)]


def _metadata(*, command: bool = False, widget: bool = True) -> dict[str, Any]:
    scopes = (
        Scope.PORTFOLIO_READ,
        Scope.ANALYTICS_READ,
        *((Scope.SCENARIOS_WRITE,) if command else ()),
    )
    result: dict[str, Any] = {
        "securitySchemes": [{"type": "oauth2", "scopes": [scope.value for scope in scopes]}],
        "openai/toolInvocation/invoking": "Saving scenario request"
        if command
        else "Reading saved scenarios",
        "openai/toolInvocation/invoked": "Scenario request saved"
        if command
        else "Scenario read complete",
    }
    if widget:
        result.update(
            {
                "ui": {"resourceUri": SCENARIO_WIDGET_URI, "visibility": ["model", "app"]},
                "openai/outputTemplate": SCENARIO_WIDGET_URI,
                "openai/widgetAccessible": True,
            }
        )
    return result


def register_scenario_tools(
    server: MCPServer[Any], gateway: ScenarioMcpGateway, *, widget_domain: AnyHttpUrl | None
) -> None:
    reads = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    command = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    @server.tool(
        name="list_scenarios",
        title="List saved scenario definitions",
        description="Use this when choosing an owned saved scenario definition. Read its name, "
        "current immutable version and revision using a bounded stable page. Account and current "
        "grants are required. This returns definition metadata and creates no scenario run.",
        annotations=reads,
        meta=_metadata(widget=False),
        structured_output=False,
    )
    async def list_scenarios(
        account_id: UUIDString,
        context: Context[Any, Any],
        limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 25,
        cursor: Cursor | None = None,
    ) -> CallToolResult:
        return await gateway.list_scenarios(
            account_id, wire.ScenarioPageQuery(limit=limit, cursor=cursor), context=context
        )

    @server.tool(
        name="create_scenario_run",
        title="Create an internal scenario analysis",
        description="Use this when requesting a private stress analysis from an owned immutable "
        "scenario version, portfolio snapshot and saved X-ray run, with explicit reporting "
        "currency, source cutoff and optional saved replay selection. Reuse the idempotency key "
        "only for identical inputs. Returns job metadata; use get_scenario_result for results. "
        "No supplied valuations, provider calls or broker operations.",
        annotations=command,
        meta=_metadata(command=True),
        structured_output=False,
    )
    async def create_scenario_run(
        account_id: UUIDString,
        idempotency_key: IdempotencyKey,
        scenario_version_id: UUIDString,
        portfolio_snapshot_id: UUIDString,
        xray_run_id: UUIDString,
        reporting_currency: CurrencyString,
        source_cutoff_at: McpAwareInstant,
        context: Context[Any, Any],
        replay: wire.ScenarioReplaySelection | None = None,
    ) -> CallToolResult:
        request = wire.CreateScenarioRunRequest.model_validate(
            {
                "scenario_version_id": scenario_version_id,
                "portfolio_snapshot_id": portfolio_snapshot_id,
                "xray_run_id": xray_run_id,
                "reporting_currency": reporting_currency,
                "source_cutoff_at": source_cutoff_at.isoformat(),
                "replay": None if replay is None else replay.model_dump(mode="json"),
            }
        )
        return await gateway.create_scenario_run(
            account_id, request, idempotency_key, context=context
        )

    @server.tool(
        name="get_scenario_result",
        title="Read a saved scenario result",
        description="Use this when checking an owned scenario job or reading its saved stress "
        "result. Returns operational state and, after atomic success, a common summary and whole "
        "component page with exact financial strings, quality, confidence and explicit source "
        "omissions. Continue with component_cursor and the same account, run and component_limit. "
        "Current grants and source rights are checked before cursor or financial reads.",
        annotations=reads,
        meta=_metadata(),
        structured_output=False,
    )
    async def get_scenario_result(
        account_id: UUIDString,
        run_id: UUIDString,
        context: Context[Any, Any],
        component_limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 25,
        component_cursor: Cursor | None = None,
    ) -> CallToolResult:
        return await gateway.get_scenario_result(
            account_id,
            run_id,
            wire.ScenarioComponentPageQuery(
                component_limit=component_limit,
                component_cursor=component_cursor,
            ),
            context=context,
        )

    @server.tool(
        name="compare_scenarios",
        title="Compare two saved scenarios",
        description="Use this when comparing exactly two distinct ordered saved scenario runs "
        "for the same owned account. The first run is before and the second is after. Read the "
        "retained common summaries and bounded union of component paths. Compatible bases have "
        "saved-value differences; incompatible bases preserve both sides and mismatch reasons "
        "without differences. Continue with the same ordered IDs, component_limit and returned "
        "component_cursor. No calculation is rerun.",
        annotations=reads,
        meta=_metadata(),
        structured_output=False,
    )
    async def compare_scenarios(
        account_id: UUIDString,
        run_ids: Annotated[list[UUIDString], Field(min_length=2, max_length=2)],
        context: Context[Any, Any],
        component_limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 25,
        component_cursor: Cursor | None = None,
    ) -> CallToolResult:
        return await gateway.compare_scenarios(
            account_id,
            wire.ScenarioComparisonQuery(
                run_ids=run_ids,
                component_limit=component_limit,
                component_cursor=component_cursor,
            ),
            context=context,
        )

    for name, model in (
        ("list_scenarios", ScenarioListToolResult),
        ("create_scenario_run", ScenarioCreateToolResult),
        ("get_scenario_result", ScenarioRunToolResult),
        ("compare_scenarios", ScenarioComparisonToolResult),
    ):
        finalize_tool_contract(server, name=name, output_model=model)
        harden_target_arguments(server, name=name)

    ui: dict[str, Any] = {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
    }
    metadata: dict[str, Any] = {
        "ui": ui,
        "openai/widgetDescription": (
            "Saved stress scenarios and comparisons with exact-value component tables."
        ),
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    }
    if widget_domain is not None:
        ui["domain"] = str(widget_domain).rstrip("/")
        metadata["openai/widgetDomain"] = str(widget_domain).rstrip("/")

    @server.resource(
        SCENARIO_WIDGET_URI,
        name="scenario-v1",
        title="Portfolio scenario analysis",
        description="Saved scenario tables, bounded host-mediated pagination and comparison, "
        "with no network access.",
        mime_type=SCENARIO_WIDGET_MIME,
        meta=metadata,
    )
    def scenario_widget() -> str:
        return SCENARIO_WIDGET_HTML
