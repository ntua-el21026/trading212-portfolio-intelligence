"""Tools 33-36 and one isolated resource over the frozen projection service."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import AnyHttpUrl, Field
from trading212_api_contracts import projection_inputs as inputs
from trading212_api_contracts import projections as wire
from trading212_api_contracts.targets import Cursor, IdempotencyKey, UUIDString
from trading212_security.principals import Scope

from .projection_gateway import ProjectionMcpGateway
from .projection_schemas import (
    ProjectionCreateToolResult,
    ProjectionGoalToolResult,
    ProjectionListToolResult,
    ProjectionRunToolResult,
)
from .projection_widget import PROJECTION_WIDGET_HTML, PROJECTION_WIDGET_MIME, PROJECTION_WIDGET_URI
from .sdk_compat import finalize_tool_contract, harden_target_arguments

PROJECTION_TOOL_NAMES = (
    "create_projection_run",
    "get_projection",
    "list_goals",
    "get_goal_analysis",
)


def _metadata(*, command: bool = False, widget: bool = True) -> dict[str, Any]:
    scopes = (
        Scope.PORTFOLIO_READ,
        Scope.ANALYTICS_READ,
        *((Scope.PROJECTIONS_WRITE,) if command else ()),
    )
    result: dict[str, Any] = {
        "securitySchemes": [{"type": "oauth2", "scopes": [scope.value for scope in scopes]}],
        "openai/toolInvocation/invoking": "Saving projection request"
        if command
        else "Reading saved projections",
        "openai/toolInvocation/invoked": "Projection request saved"
        if command
        else "Projection read complete",
    }
    if widget:
        result.update(
            {
                "ui": {"resourceUri": PROJECTION_WIDGET_URI, "visibility": ["model", "app"]},
                "openai/outputTemplate": PROJECTION_WIDGET_URI,
                "openai/widgetAccessible": True,
            }
        )
    return result


def register_projection_tools(
    server: MCPServer[Any], gateway: ProjectionMcpGateway, *, widget_domain: AnyHttpUrl | None
) -> None:
    reads = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    command = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    @server.tool(
        name="create_projection_run",
        title="Create a private portfolio projection",
        description=(
            "Use this when requesting a modeled projection from an owned immutable assumption "
            "version and optional goal, an explicit observed snapshot or modeled initial value, "
            "dated schedule, allocation, seed, horizon, paths and optional sensitivity. Reuse the "
            "idempotency key only for identical inputs. Returns job metadata; use get_projection "
            "for saved results. This creates a private application record and never calls a "
            "broker or provider."
        ),
        annotations=command,
        meta=_metadata(command=True),
        structured_output=False,
    )
    async def create_projection_run(
        account_id: UUIDString,
        idempotency_key: IdempotencyKey,
        assumption_version_id: UUIDString,
        initial_basis: inputs.ProjectionInitialSelection,
        schedule: inputs.ProjectionDatedSchedule,
        seed: Annotated[int, Field(strict=True, ge=0, le=2**32 - 1)],
        months: inputs.ProjectionMonths,
        paths: inputs.ProjectionPathCount,
        retained_months: Annotated[
            list[inputs.ProjectionMonth], Field(min_length=2, max_length=121)
        ],
        allocation: Annotated[
            list[inputs.ProjectionAllocation], Field(min_length=1, max_length=12)
        ],
        context: Context[Any, Any],
        goal_version_id: UUIDString | None = None,
        sensitivity: inputs.ProjectionSensitivity | None = None,
    ) -> CallToolResult:
        request = inputs.CreateProjectionRunRequest.model_validate(
            {
                "assumption_version_id": assumption_version_id,
                "goal_version_id": goal_version_id,
                "initial_basis": initial_basis.model_dump(mode="json"),
                "schedule": schedule.model_dump(mode="json"),
                "seed": seed,
                "months": months,
                "paths": paths,
                "retained_months": retained_months,
                "allocation": [item.model_dump(mode="json") for item in allocation],
                "sensitivity": None if sensitivity is None else sensitivity.model_dump(mode="json"),
            }
        )
        return await gateway.create_projection_run(
            account_id, request, idempotency_key, context=context
        )

    @server.tool(
        name="get_projection",
        title="Read a saved projection",
        description="Use this when checking an owned projection job or reading its saved model "
        "result. After atomic success, returns all variant summaries and a bounded page of whole "
        "dated points with exact money, residual and funding values. Continue with point_cursor "
        "and the same account, run and point_limit. Current grants and source rights precede "
        "private reads and cursor parsing. Model estimates are not guaranteed forecasts.",
        annotations=reads,
        meta=_metadata(),
        structured_output=False,
    )
    async def get_projection(
        account_id: UUIDString,
        run_id: UUIDString,
        context: Context[Any, Any],
        point_limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 25,
        point_cursor: Cursor | None = None,
    ) -> CallToolResult:
        return await gateway.get_projection(
            account_id,
            run_id,
            wire.ProjectionPointPageQuery(point_limit=point_limit, point_cursor=point_cursor),
            context=context,
        )

    @server.tool(
        name="list_goals",
        title="List saved portfolio goals",
        description="Use this when choosing an owned saved goal. Returns definition metadata, "
        "current immutable version and revision using a bounded signed page. Requires current "
        "account grants. This read does not create, edit or accept a goal.",
        annotations=reads,
        meta=_metadata(widget=False),
        structured_output=False,
    )
    async def list_goals(
        account_id: UUIDString,
        context: Context[Any, Any],
        limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 25,
        cursor: Cursor | None = None,
    ) -> CallToolResult:
        return await gateway.list_goals(
            account_id, wire.ProjectionPageQuery(limit=limit, cursor=cursor), context=context
        )

    @server.tool(
        name="get_goal_analysis",
        title="Read a saved projection's goal analysis",
        description="Use this when evaluating the exact goal pinned to an owned saved projection. "
        "Returns its saved target, basis, terminal quantiles, modeled success probability and "
        "Wilson sampling interval, shortfalls, funding outcomes and every sensitivity variant. "
        "No pinned goal or unavailable result has an explicit reason. Objective attainment "
        "never automatically accepts a goal, and no sampled paths are rerun.",
        annotations=reads,
        meta=_metadata(),
        structured_output=False,
    )
    async def get_goal_analysis(
        account_id: UUIDString,
        run_id: UUIDString,
        context: Context[Any, Any],
    ) -> CallToolResult:
        return await gateway.get_goal_analysis(account_id, run_id, context=context)

    for name, model in (
        ("create_projection_run", ProjectionCreateToolResult),
        ("get_projection", ProjectionRunToolResult),
        ("list_goals", ProjectionListToolResult),
        ("get_goal_analysis", ProjectionGoalToolResult),
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
            "Saved model projections and goals with exact-value dated point tables."
        ),
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    }
    if widget_domain is not None:
        ui["domain"] = str(widget_domain).rstrip("/")
        metadata["openai/widgetDomain"] = str(widget_domain).rstrip("/")

    @server.resource(
        PROJECTION_WIDGET_URI,
        name="projection-v1",
        title="Portfolio projection analysis",
        description=(
            "Saved model estimates, goals and complete point tables with bounded host reads "
            "and no network access."
        ),
        mime_type=PROJECTION_WIDGET_MIME,
        meta=metadata,
    )
    def projection_widget() -> str:
        return PROJECTION_WIDGET_HTML
