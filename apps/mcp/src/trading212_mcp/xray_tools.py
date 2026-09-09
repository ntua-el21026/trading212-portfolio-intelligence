"""The two frozen P2-05 read tools and isolated X-ray resource."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import AnyHttpUrl, Field, StrictInt
from trading212_api_contracts import xray as wire
from trading212_api_contracts.targets import AwareInstant, CurrencyString, Cursor, UUIDString
from trading212_security.principals import Scope

from .sdk_compat import finalize_tool_contract, harden_target_arguments
from .xray_gateway import XrayMcpGateway
from .xray_schemas import XrayExposureToolResult, XrayOverlapToolResult
from .xray_widget import XRAY_WIDGET_HTML, XRAY_WIDGET_MIME, XRAY_WIDGET_URI

McpAwareInstant = Annotated[AwareInstant, Field(strict=False)]
XRAY_TOOL_NAMES = ("get_effective_exposure", "get_etf_overlap")


def register_xray_tools(
    server: MCPServer[Any], gateway: XrayMcpGateway, *, widget_domain: AnyHttpUrl | None
) -> None:
    reads = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    metadata = {
        "securitySchemes": [
            {"type": "oauth2", "scopes": [Scope.PORTFOLIO_READ.value, Scope.ANALYTICS_READ.value]}
        ],
        "openai/toolInvocation/invoking": "Reading portfolio X-ray",
        "openai/toolInvocation/invoked": "Portfolio X-ray ready",
        "ui": {"resourceUri": XRAY_WIDGET_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": XRAY_WIDGET_URI,
    }

    @server.tool(
        name="get_effective_exposure",
        title="Read effective portfolio exposure",
        description=(
            "Read immutable direct and fund look-through exposure in one dimension with "
            "unresolved weight, source dates, confidence, methodology and bounded pagination. "
            "No provider refresh or broker writes."
        ),
        annotations=reads,
        meta=metadata,
        structured_output=False,
    )
    async def get_effective_exposure(
        account_id: UUIDString,
        snapshot_id: UUIDString,
        source_cutoff_at: McpAwareInstant,
        reporting_currency: CurrencyString,
        context: Context[Any, Any],
        dimension: wire.XrayDimension = "company",
        cursor: Cursor | None = None,
        limit: Annotated[StrictInt, Field(ge=1, le=100)] = 25,
    ) -> CallToolResult:
        query = wire.XrayMcpEffectiveExposureQuery.model_validate(
            {
                "snapshot_id": snapshot_id,
                "source_cutoff_at": source_cutoff_at.isoformat(),
                "reporting_currency": reporting_currency,
                "dimension": dimension,
                "cursor": cursor,
                "limit": limit,
            }
        )
        return await gateway.get_effective_exposure(account_id, query, context=context)

    @server.tool(
        name="get_etf_overlap",
        title="Read overlap between two held funds",
        description=(
            "Read canonical overlap and the Top common entities between two held funds. "
            "Reporting currency comes from the authorized immutable snapshot. Includes "
            "exact omission counts and omitted common weight; no provider refresh or broker writes."
        ),
        annotations=reads,
        meta=metadata,
        structured_output=False,
    )
    async def get_etf_overlap(
        account_id: UUIDString,
        snapshot_id: UUIDString,
        source_cutoff_at: McpAwareInstant,
        left_fund_id: UUIDString,
        right_fund_id: UUIDString,
        context: Context[Any, Any],
        top_n: Annotated[StrictInt, Field(ge=1, le=50)] = 25,
    ) -> CallToolResult:
        query = wire.XrayMcpOverlapQuery.model_validate(
            {
                "snapshot_id": snapshot_id,
                "source_cutoff_at": source_cutoff_at.isoformat(),
                "left_fund_id": left_fund_id,
                "right_fund_id": right_fund_id,
                "top_n": top_n,
            }
        )
        return await gateway.get_etf_overlap(account_id, query, context=context)

    for name, model in (
        ("get_effective_exposure", XrayExposureToolResult),
        ("get_etf_overlap", XrayOverlapToolResult),
    ):
        finalize_tool_contract(server, name=name, output_model=model)
        harden_target_arguments(server, name=name)
    ui: dict[str, Any] = {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
    }
    resource_metadata: dict[str, Any] = {
        "ui": ui,
        "openai/widgetDescription": (
            "Exact portfolio X-ray with direct and indirect exposure, unresolved weight, "
            "confidence and source evidence."
        ),
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    }
    if widget_domain is not None:
        ui["domain"] = str(widget_domain).rstrip("/")
        resource_metadata["openai/widgetDomain"] = str(widget_domain).rstrip("/")

    @server.resource(
        XRAY_WIDGET_URI,
        name="xray-v1",
        title="Portfolio X-ray",
        description="Isolated read-only presentation of authorized canonical exposure and overlap.",
        mime_type=XRAY_WIDGET_MIME,
        meta=resource_metadata,
    )
    def xray_widget() -> str:
        return XRAY_WIDGET_HTML
