"""Three frozen risk tools and a static, network-isolated interactive resource."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import AnyHttpUrl, Field
from trading212_api_contracts import risk as wire
from trading212_api_contracts.targets import IdempotencyKey, UUIDString
from trading212_security.principals import Scope

from .risk_gateway import RiskMcpGateway
from .risk_schemas import RiskMatrixToolResult, RiskRunToolResult
from .risk_widget import RISK_WIDGET_HTML, RISK_WIDGET_MIME, RISK_WIDGET_URI
from .sdk_compat import finalize_tool_contract, harden_target_arguments

RISK_TOOL_NAMES = ("create_risk_run", "get_risk_summary", "get_risk_matrix")
# The pinned SDK consumes this field factory before invoking the handler.
_EMPTY_ASSETS: list[wire.RiskAssetSource] = Field(default_factory=list)


def _metadata(*, command: bool = False) -> dict[str, Any]:
    scopes = (Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, *((Scope.RISK_WRITE,) if command else ()))
    return {
        "securitySchemes": [{"type": "oauth2", "scopes": [scope.value for scope in scopes]}],
        "ui": {"resourceUri": RISK_WIDGET_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": RISK_WIDGET_URI,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": "Saving risk analysis"
        if command
        else "Reading risk analysis",
        "openai/toolInvocation/invoked": "Risk request saved" if command else "Risk analysis ready",
    }


def register_risk_tools(
    server: MCPServer[Any], gateway: RiskMcpGateway, *, widget_domain: AnyHttpUrl | None
) -> None:
    reads = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    command = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    @server.tool(
        name="create_risk_run",
        title="Create an internal risk analysis",
        description="Create a bounded private risk job using an owned immutable definition, "
        "portfolio snapshot, historical capture and optional sourced asset/benchmark/X-ray pins. "
        "Reuse the idempotency key only for the same inputs. No supplied returns, provider calls "
        "or broker operations. Poll get_risk_summary before using completed results.",
        annotations=command,
        meta=_metadata(command=True),
        structured_output=False,
    )
    async def create_risk_run(
        account_id: UUIDString,
        idempotency_key: IdempotencyKey,
        definition_version_id: UUIDString,
        portfolio_snapshot_id: UUIDString,
        historical_input_snapshot_id: UUIDString,
        window: wire.RiskWindow,
        context: Context[Any, Any],
        assets: Annotated[list[wire.RiskAssetSource], Field(max_length=32)] = _EMPTY_ASSETS,
        benchmark_version_id: UUIDString | None = None,
        xray_run_id: UUIDString | None = None,
    ) -> CallToolResult:
        request = wire.CreateRiskRunRequest.model_validate(
            {
                "definition_version_id": definition_version_id,
                "portfolio_snapshot_id": portfolio_snapshot_id,
                "historical_input_snapshot_id": historical_input_snapshot_id,
                "window": window.model_dump(mode="json"),
                "assets": [item.model_dump(mode="json") for item in assets],
                "benchmark_version_id": benchmark_version_id,
                "xray_run_id": xray_run_id,
            }
        )
        return await gateway.create_risk_run(account_id, request, idempotency_key, context=context)

    @server.tool(
        name="get_risk_summary",
        title="Read a canonical risk analysis",
        description="Read an owned risk run's actual state, canonical historical/model estimates, "
        "unavailable reasons, immutable assumptions, coverage, source cutoff and digest. "
        "Rechecks grants and source rights. No recalculation or broker/provider requests.",
        annotations=reads,
        meta=_metadata(),
        structured_output=False,
    )
    async def get_risk_summary(
        account_id: UUIDString, run_id: UUIDString, context: Context[Any, Any]
    ) -> CallToolResult:
        return await gateway.get_risk_summary(account_id, run_id, context=context)

    @server.tool(
        name="get_risk_matrix",
        title="Read a canonical risk matrix",
        description="Read bounded covariance/correlation matrices for an owned completed "
        "risk run. Preserve ordered assets, missingness, exact decimal values, regularization, "
        "coverage and source metadata. No covariance computation in the client.",
        annotations=reads,
        meta=_metadata(),
        structured_output=False,
    )
    async def get_risk_matrix(
        account_id: UUIDString, run_id: UUIDString, context: Context[Any, Any]
    ) -> CallToolResult:
        return await gateway.get_risk_matrix(account_id, run_id, context=context)

    for name, model in (
        ("create_risk_run", RiskRunToolResult),
        ("get_risk_summary", RiskRunToolResult),
        ("get_risk_matrix", RiskMatrixToolResult),
    ):
        finalize_tool_contract(server, name=name, output_model=model)
        harden_target_arguments(server, name=name)
    ui: dict[str, Any] = {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
    }
    metadata: dict[str, Any] = {
        "ui": ui,
        "openai/widgetDescription": "Risk estimates, sources and accessible exact-value tables.",
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    }
    if widget_domain is not None:
        ui["domain"] = str(widget_domain).rstrip("/")
        metadata["openai/widgetDomain"] = str(widget_domain).rstrip("/")

    @server.resource(
        RISK_WIDGET_URI,
        name="risk-v1",
        title="Portfolio risk analysis",
        description="Private risk UI with bounded host-mediated refresh and no network access.",
        mime_type=RISK_WIDGET_MIME,
        meta=metadata,
    )
    def risk_widget() -> str:
        return RISK_WIDGET_HTML
