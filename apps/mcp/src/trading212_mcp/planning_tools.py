"""Explicit registration of the four P2-02 MCP tools and private plan resource."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import AnyHttpUrl, Field, StrictInt
from trading212_api_contracts import planning as wire
from trading212_api_contracts.targets import CurrencyString, Cursor, IdempotencyKey, UUIDString
from trading212_security.principals import Scope

from .planning_gateway import PlanningMcpGateway
from .planning_schemas import (
    ActualVsTargetToolResult,
    ContributionPlanToolResult,
    CreateContributionPlanToolResult,
    DriftAnalysisToolResult,
)
from .planning_widget import PLAN_WIDGET_HTML, PLAN_WIDGET_MIME, PLAN_WIDGET_URI
from .sdk_compat import finalize_tool_contract, harden_target_arguments

# MCP metadata creates a fresh list for each parsed invocation.
_DEFAULT_LIST: Any = Field(default_factory=list)

PLANNING_TOOL_NAMES = (
    "get_actual_vs_target",
    "get_drift_analysis",
    "get_contribution_plan",
    "create_contribution_plan",
)


def _metadata(
    scopes: tuple[Scope, ...], *, command: bool = False, widget: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "securitySchemes": [{"type": "oauth2", "scopes": [scope.value for scope in scopes]}],
        "openai/toolInvocation/invoking": "Saving manual planning request"
        if command
        else "Reading canonical planning data",
        "openai/toolInvocation/invoked": "Manual planning request saved"
        if command
        else "Planning data ready",
    }
    if widget:
        result.update(
            {
                "ui": {"resourceUri": PLAN_WIDGET_URI, "visibility": ["model", "app"]},
                "openai/outputTemplate": PLAN_WIDGET_URI,
            }
        )
    return result


def register_planning_tools(
    server: MCPServer[Any], gateway: PlanningMcpGateway, *, widget_domain: AnyHttpUrl | None
) -> None:
    reads = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    command = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    scopes = (Scope.PORTFOLIO_READ, Scope.TARGETS_READ, Scope.ANALYTICS_READ)

    @server.tool(
        name="get_actual_vs_target",
        title="Compare actual and target allocation",
        description=(
            "Read bounded canonical actual-versus-target rows for immutable authorized "
            "portfolio and target snapshots. Full-scope totals include cash and unmapped "
            "exposure. No provider access or job creation."
        ),
        annotations=reads,
        meta=_metadata(scopes),
        structured_output=False,
    )
    async def get_actual_vs_target(
        account_id: UUIDString,
        snapshot_id: UUIDString,
        virtual_portfolio_id: UUIDString,
        target_version_id: UUIDString,
        reporting_currency: CurrencyString,
        context: Context[Any, Any],
        node_id: UUIDString | None = None,
        xray_run_id: UUIDString | None = None,
        cursor: Cursor | None = None,
        limit: Annotated[StrictInt, Field(ge=1, le=100)] = 25,
    ) -> CallToolResult:
        return await gateway.get_actual_vs_target(
            account_id,
            wire.ActualVsTargetQuery(
                snapshot_id=snapshot_id,
                virtual_portfolio_id=virtual_portfolio_id,
                target_version_id=target_version_id,
                reporting_currency=reporting_currency,
                node_id=node_id,
                xray_run_id=xray_run_id,
                cursor=cursor,
                limit=limit,
            ),
            context=context,
        )

    @server.tool(
        name="get_drift_analysis",
        title="Read allocation drift",
        description=(
            "Read a bounded ranked sample with full-universe drift totals, immutable "
            "inputs and explicit quality. An optional retained X-ray run supplies full "
            "company actual weights; listing targets do not define company drift. "
            "No provider access or job creation."
        ),
        annotations=reads,
        meta=_metadata(scopes),
        structured_output=False,
    )
    async def get_drift_analysis(
        account_id: UUIDString,
        snapshot_id: UUIDString,
        virtual_portfolio_id: UUIDString,
        target_version_id: UUIDString,
        reporting_currency: CurrencyString,
        context: Context[Any, Any],
        basis: Literal["direct", "effective"] = "direct",
        xray_run_id: UUIDString | None = None,
        top_n: Annotated[StrictInt, Field(ge=1, le=50)] = 25,
    ) -> CallToolResult:
        return await gateway.get_drift_analysis(
            account_id,
            wire.DriftAnalysisQuery(
                snapshot_id=snapshot_id,
                virtual_portfolio_id=virtual_portfolio_id,
                target_version_id=target_version_id,
                reporting_currency=reporting_currency,
                basis=basis,
                xray_run_id=xray_run_id,
                top_n=top_n,
            ),
            context=context,
        )

    @server.tool(
        name="get_contribution_plan",
        title="Read a saved manual contribution plan",
        description=(
            "Read an authorized persisted plan and a bounded page of immutable "
            "allocation lines. Whole-plan totals, solver outcome and omitted detail "
            "remain explicit. This read creates no job and cannot execute trades."
        ),
        annotations=reads,
        meta=_metadata((Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ), widget=True),
        structured_output=False,
    )
    async def get_contribution_plan(
        account_id: UUIDString,
        plan_id: UUIDString,
        context: Context[Any, Any],
        plan_revision_id: UUIDString | None = None,
        cursor: Cursor | None = None,
        limit: Annotated[StrictInt, Field(ge=1, le=100)] = 25,
    ) -> CallToolResult:
        return await gateway.get_contribution_plan(
            account_id,
            plan_id,
            wire.ContributionPlanDetailQuery(
                plan_revision_id=plan_revision_id, cursor=cursor, limit=limit
            ),
            context=context,
        )

    @server.tool(
        name="create_contribution_plan",
        title="Create a manual contribution plan",
        description=(
            "Persist an authorized durable request for contribution-only planning using "
            "immutable target and valuation inputs. Equal idempotent retries return the "
            "same durable identity. Queued requests have no invented result; execution "
            "is disabled and no broker or provider is contacted."
        ),
        annotations=command,
        meta=_metadata((*scopes, Scope.PLANS_WRITE), command=True, widget=True),
        structured_output=False,
    )
    async def create_contribution_plan(
        account_id: UUIDString,
        snapshot_id: UUIDString,
        virtual_portfolio_id: UUIDString,
        target_version_id: UUIDString,
        idempotency_key: IdempotencyKey,
        contribution: wire.ContributionMoney,
        mode: wire.PlanMode,
        context: Context[Any, Any],
        restricted_group_ids: wire.UUIDSet = _DEFAULT_LIST,
        eligible_holding_ids: wire.UUIDSet | None = None,
        excluded_holding_ids: wire.UUIDSet = _DEFAULT_LIST,
        listing_preferences: Annotated[
            list[wire.PlanningListingPreference], Field(max_length=256)
        ] = _DEFAULT_LIST,
        allocation_constraints: Annotated[
            list[wire.McpPlanAllocationConstraint], Field(max_length=256)
        ] = _DEFAULT_LIST,
        cash_reserve: wire.NonnegativeDecimal | None = None,
        monetary_quantum: wire.QuantumString | None = None,
        coverage_policy: wire.CoveragePolicy = "require_complete",
    ) -> CallToolResult:
        request = wire.McpCreateContributionPlanRequest(
            account_id=account_id,
            snapshot_id=snapshot_id,
            virtual_portfolio_id=virtual_portfolio_id,
            target_version_id=target_version_id,
            idempotency_key=idempotency_key,
            contribution=contribution,
            mode=mode,
            restricted_group_ids=restricted_group_ids,
            eligible_holding_ids=eligible_holding_ids,
            excluded_holding_ids=excluded_holding_ids,
            listing_preferences=listing_preferences,
            allocation_constraints=allocation_constraints,
            cash_reserve=cash_reserve,
            monetary_quantum=monetary_quantum,
            coverage_policy=coverage_policy,
        )
        return await gateway.create_contribution_plan(request, context=context)

    for name, model in (
        ("get_actual_vs_target", ActualVsTargetToolResult),
        ("get_drift_analysis", DriftAnalysisToolResult),
        ("get_contribution_plan", ContributionPlanToolResult),
        ("create_contribution_plan", CreateContributionPlanToolResult),
    ):
        finalize_tool_contract(server, name=name, output_model=model)
        harden_target_arguments(server, name=name)
    ui: dict[str, Any] = {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
    }
    resource_meta: dict[str, Any] = {
        "ui": ui,
        "openai/widgetDescription": (
            "Canonical saved manual contribution plan with pending, quality "
            "and execution-disabled disclosures."
        ),
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    }
    if widget_domain is not None:
        ui["domain"] = str(widget_domain).rstrip("/")
        resource_meta["openai/widgetDomain"] = str(widget_domain).rstrip("/")

    @server.resource(
        PLAN_WIDGET_URI,
        name="contribution-plan-v1",
        title="Manual contribution plan",
        description="Read-only bounded presentation of authorized canonical planning data.",
        mime_type=PLAN_WIDGET_MIME,
        meta=resource_meta,
    )
    def contribution_plan_widget() -> str:
        return PLAN_WIDGET_HTML
