"""Exact registration of three report tools and the private static status resource."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import AnyHttpUrl, Field, StrictInt
from trading212_api_contracts import reports as wire
from trading212_api_contracts.sources import CalendarDate
from trading212_api_contracts.targets import (
    AwareInstant,
    CurrencyString,
    Cursor,
    IdempotencyKey,
    UUIDString,
)
from trading212_security.principals import Scope

from .report_gateway import ReportMcpGateway
from .report_schemas import GenerateReportToolResult, ReportListToolResult, ReportStatusToolResult
from .report_widget import REPORT_WIDGET_HTML, REPORT_WIDGET_MIME, REPORT_WIDGET_URI
from .sdk_compat import finalize_tool_contract, harden_target_arguments

REPORT_TOOL_NAMES = ("get_report_status", "list_reports", "generate_portfolio_report")
McpCalendarDate = Annotated[CalendarDate, Field(strict=False)]
McpAwareInstant = Annotated[AwareInstant, Field(strict=False)]


def _metadata(
    scopes: tuple[Scope, ...], *, command: bool = False, widget: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "securitySchemes": [{"type": "oauth2", "scopes": [scope.value for scope in scopes]}],
        "openai/toolInvocation/invoking": "Saving private report request"
        if command
        else "Reading private report metadata",
        "openai/toolInvocation/invoked": "Private report request saved"
        if command
        else "Private report metadata ready",
    }
    if widget:
        result.update(
            {
                "ui": {"resourceUri": REPORT_WIDGET_URI, "visibility": ["model", "app"]},
                "openai/outputTemplate": REPORT_WIDGET_URI,
            }
        )
    return result


def register_report_tools(
    server: MCPServer[Any], gateway: ReportMcpGateway, *, widget_domain: AnyHttpUrl | None
) -> None:
    reads = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    command = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    read_scopes = (Scope.PORTFOLIO_READ, Scope.REPORTS_READ)
    command_scopes = (
        Scope.PORTFOLIO_READ,
        Scope.ANALYTICS_READ,
        Scope.REPORTS_WRITE,
        Scope.ACTIVITY_READ,
        Scope.TARGETS_READ,
    )

    @server.tool(
        name="get_report_status",
        title="Read private report status",
        description=(
            "Read an authorized stored report job, immutable input pins, quality, safe failure "
            "and manifest identity. No artifact bytes, grants, URLs or provider access."
        ),
        annotations=reads,
        meta=_metadata(read_scopes, widget=True),
        structured_output=False,
    )
    async def get_report_status(
        account_id: UUIDString, report_job_id: UUIDString, context: Context[Any, Any]
    ) -> CallToolResult:
        return await gateway.get_report_status(account_id, report_job_id, context=context)

    @server.tool(
        name="list_reports",
        title="List private reports",
        description=(
            "Read a bounded owner/account-scoped history of real report jobs in stable "
            "created-descending order. No generation, artifact bytes or download grants."
        ),
        annotations=reads,
        meta=_metadata(read_scopes),
        structured_output=False,
    )
    async def list_reports(
        account_id: UUIDString,
        context: Context[Any, Any],
        cursor: Cursor | None = None,
        limit: Annotated[StrictInt, Field(ge=1, le=100)] = 25,
        state: wire.ReportJobState | Literal["all"] = "all",
        report_type: wire.ReportType | Literal["all"] = "all",
        sort: Literal["created_desc"] = "created_desc",
    ) -> CallToolResult:
        return await gateway.list_reports(
            wire.ReportListQuery(
                account_id=account_id,
                cursor=cursor,
                limit=limit,
                state=state,
                report_type=report_type,
                sort=sort,
            ),
            context=context,
        )

    @server.tool(
        name="generate_portfolio_report",
        title="Generate a private portfolio report",
        description=(
            "Persist a private durable report request over authorized immutable portfolio inputs. "
            "Equal idempotent retries return the same job. The server pins canonical inputs and "
            "its fixed profile; generation never performs broker writes. "
            "No custom template, destination, grant or download URL."
        ),
        annotations=command,
        meta=_metadata(command_scopes, command=True, widget=True),
        structured_output=False,
    )
    async def generate_portfolio_report(
        account_id: UUIDString,
        idempotency_key: IdempotencyKey,
        start_date: McpCalendarDate,
        end_date: McpCalendarDate,
        source_cutoff_at: McpAwareInstant,
        snapshot_id: UUIDString,
        reporting_currency: CurrencyString,
        report_type: wire.ReportType,
        format: wire.ReportFormat,
        sections: wire.ReportSections,
        context: Context[Any, Any],
        target_version_id: UUIDString | None = None,
        plan_revision_id: UUIDString | None = None,
        benchmark_version_id: UUIDString | None = None,
        constituent_snapshot_id: UUIDString | None = None,
    ) -> CallToolResult:
        request = wire.McpGenerateReportRequest.model_validate(
            {
                "account_id": account_id,
                "idempotency_key": idempotency_key,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "source_cutoff_at": source_cutoff_at.isoformat(),
                "snapshot_id": snapshot_id,
                "reporting_currency": reporting_currency,
                "report_type": report_type,
                "format": format,
                "sections": sections,
                "target_version_id": target_version_id,
                "plan_revision_id": plan_revision_id,
                "benchmark_version_id": benchmark_version_id,
                "constituent_snapshot_id": constituent_snapshot_id,
            }
        )
        return await gateway.generate_portfolio_report(request, context=context)

    for name, model in (
        ("get_report_status", ReportStatusToolResult),
        ("list_reports", ReportListToolResult),
        ("generate_portfolio_report", GenerateReportToolResult),
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
            "Private report state, pinned canonical inputs and bounded quality metadata."
        ),
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    }
    if widget_domain is not None:
        ui["domain"] = str(widget_domain).rstrip("/")
        metadata["openai/widgetDomain"] = str(widget_domain).rstrip("/")

    @server.resource(
        REPORT_WIDGET_URI,
        name="report-status-v1",
        title="Private report status",
        description="Static report metadata without artifact grants or external requests.",
        mime_type=REPORT_WIDGET_MIME,
        meta=metadata,
    )
    def report_status_widget() -> str:
        return REPORT_WIDGET_HTML
