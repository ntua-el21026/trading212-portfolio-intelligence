"""The four frozen P2-04 read tools and one static performance comparison resource."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import AnyHttpUrl, Field, StrictInt
from trading212_api_contracts import historical as wire
from trading212_api_contracts.sources import CalendarDate
from trading212_api_contracts.targets import AwareInstant, CurrencyString, UUIDString
from trading212_security.principals import Scope

from .historical_gateway import HistoricalMcpGateway
from .historical_schemas import (
    HistoricalAttributionToolResult,
    HistoricalBenchmarkToolResult,
    HistoricalDividendToolResult,
    HistoricalPerformanceToolResult,
)
from .historical_widget import HISTORICAL_WIDGET_HTML, HISTORICAL_WIDGET_MIME, HISTORICAL_WIDGET_URI
from .sdk_compat import finalize_tool_contract, harden_target_arguments

McpCalendarDate = Annotated[CalendarDate, Field(strict=False)]
McpAwareInstant = Annotated[AwareInstant, Field(strict=False)]


def _query[T: wire.HistoricalWindowQuery](
    schema: type[T],
    *,
    start_date: date,
    end_date: date,
    source_cutoff_at: datetime,
    reporting_currency: str,
    **selectors: object,
) -> T:
    return schema.model_validate(
        {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "source_cutoff_at": source_cutoff_at.isoformat(),
            "reporting_currency": reporting_currency,
            **selectors,
        }
    )


HISTORICAL_TOOL_NAMES = (
    "get_performance_summary",
    "get_benchmark_comparison",
    "get_dividend_intelligence",
    "get_attribution_summary",
)


def _metadata(scopes: tuple[Scope, ...], *, widget: bool = False) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "securitySchemes": [{"type": "oauth2", "scopes": [scope.value for scope in scopes]}],
        "openai/toolInvocation/invoking": "Reading historical portfolio analytics",
        "openai/toolInvocation/invoked": "Historical analytics ready",
    }
    if widget:
        metadata.update(
            {
                "ui": {"resourceUri": HISTORICAL_WIDGET_URI, "visibility": ["model", "app"]},
                "openai/outputTemplate": HISTORICAL_WIDGET_URI,
            }
        )
    return metadata


def register_historical_tools(
    server: MCPServer[Any], gateway: HistoricalMcpGateway, *, widget_domain: AnyHttpUrl | None
) -> None:
    reads = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    scopes = (Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ)

    @server.tool(
        name="get_performance_summary",
        title="Read historical portfolio performance",
        description=(
            "Read exact historical portfolio metrics and the complete bounded "
            "series, with external-flow treatment, methodology, immutable source "
            "cutoff, coverage and root limitations. No refresh or provider access."
        ),
        annotations=reads,
        meta=_metadata(scopes, widget=True),
        structured_output=False,
    )
    async def get_performance_summary(
        account_id: UUIDString,
        start_date: McpCalendarDate,
        end_date: McpCalendarDate,
        source_cutoff_at: McpAwareInstant,
        reporting_currency: CurrencyString,
        context: Context[Any, Any],
        method: Literal["twr", "mwr", "modified_dietz"] = "twr",
        frequency: Literal["daily", "monthly"] = "monthly",
    ) -> CallToolResult:
        return await gateway.get_performance_summary(
            account_id,
            _query(
                wire.HistoricalPerformanceSummaryQuery,
                start_date=start_date,
                end_date=end_date,
                source_cutoff_at=source_cutoff_at,
                reporting_currency=reporting_currency,
                method=method,
                frequency=frequency,
            ),
            context=context,
        )

    @server.tool(
        name="get_benchmark_comparison",
        title="Compare historical benchmark performance",
        description=(
            "Read an authorized immutable benchmark version and complete bounded "
            "comparison series with explicit calendars, currencies, return basis, "
            "alignment, coverage and methodology. No refresh or provider access."
        ),
        annotations=reads,
        meta=_metadata(scopes, widget=True),
        structured_output=False,
    )
    async def get_benchmark_comparison(
        account_id: UUIDString,
        start_date: McpCalendarDate,
        end_date: McpCalendarDate,
        source_cutoff_at: McpAwareInstant,
        reporting_currency: CurrencyString,
        benchmark_version_id: UUIDString,
        context: Context[Any, Any],
        frequency: Literal["daily", "monthly"] = "monthly",
    ) -> CallToolResult:
        return await gateway.get_benchmark_comparison(
            account_id,
            _query(
                wire.HistoricalBenchmarkComparisonQuery,
                start_date=start_date,
                end_date=end_date,
                source_cutoff_at=source_cutoff_at,
                reporting_currency=reporting_currency,
                benchmark_version_id=benchmark_version_id,
                frequency=frequency,
            ),
            context=context,
        )

    @server.tool(
        name="get_dividend_intelligence",
        title="Read historical dividend intelligence",
        description=(
            "Read bounded income components with full-window native and explicitly "
            "converted totals, yield, growth, concentration, fees, withholding and "
            "unavailable reasons. No implicit FX or provider access."
        ),
        annotations=reads,
        meta=_metadata((Scope.PORTFOLIO_READ, Scope.ACTIVITY_READ, Scope.ANALYTICS_READ)),
        structured_output=False,
    )
    async def get_dividend_intelligence(
        account_id: UUIDString,
        start_date: McpCalendarDate,
        end_date: McpCalendarDate,
        source_cutoff_at: McpAwareInstant,
        reporting_currency: CurrencyString,
        context: Context[Any, Any],
        top_n: Annotated[StrictInt, Field(ge=1, le=50)] = 25,
    ) -> CallToolResult:
        return await gateway.get_dividend_intelligence(
            account_id,
            _query(
                wire.HistoricalDividendIntelligenceQuery,
                start_date=start_date,
                end_date=end_date,
                source_cutoff_at=source_cutoff_at,
                reporting_currency=reporting_currency,
                top_n=top_n,
            ),
            context=context,
        )

    @server.tool(
        name="get_attribution_summary",
        title="Read historical return attribution",
        description=(
            "Read bounded holding, target-group or directly sourced sector "
            "attribution with full-scope reconciliation, residuals and explicit "
            "unavailable inputs. Group attribution requires an authorized target "
            "version; no ETF look-through is inferred."
        ),
        annotations=reads,
        meta=_metadata((*scopes, Scope.TARGETS_READ)),
        structured_output=False,
    )
    async def get_attribution_summary(
        account_id: UUIDString,
        start_date: McpCalendarDate,
        end_date: McpCalendarDate,
        source_cutoff_at: McpAwareInstant,
        reporting_currency: CurrencyString,
        context: Context[Any, Any],
        grouping: Literal["holding", "group", "sector"] = "holding",
        target_version_id: UUIDString | None = None,
        top_n: Annotated[StrictInt, Field(ge=1, le=50)] = 25,
    ) -> CallToolResult:
        return await gateway.get_attribution_summary(
            account_id,
            _query(
                wire.HistoricalAttributionQuery,
                start_date=start_date,
                end_date=end_date,
                source_cutoff_at=source_cutoff_at,
                reporting_currency=reporting_currency,
                grouping=grouping,
                target_version_id=target_version_id,
                top_n=top_n,
            ),
            context=context,
        )

    for name, model in (
        ("get_performance_summary", HistoricalPerformanceToolResult),
        ("get_benchmark_comparison", HistoricalBenchmarkToolResult),
        ("get_dividend_intelligence", HistoricalDividendToolResult),
        ("get_attribution_summary", HistoricalAttributionToolResult),
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
            "Exact historical performance and comparison with explicit coverage, "
            "methodology and unavailable values."
        ),
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    }
    if widget_domain is not None:
        ui["domain"] = str(widget_domain).rstrip("/")
        metadata["openai/widgetDomain"] = str(widget_domain).rstrip("/")

    @server.resource(
        HISTORICAL_WIDGET_URI,
        name="performance-comparison-v1",
        title="Historical performance comparison",
        description="Isolated read-only presentation of authorized canonical historical metrics.",
        mime_type=HISTORICAL_WIDGET_MIME,
        meta=metadata,
    )
    def historical_widget() -> str:
        return HISTORICAL_WIDGET_HTML
