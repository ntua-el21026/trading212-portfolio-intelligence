"""Streamable HTTP with fixed portfolio reads and bounded internal manual planning."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, cast

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import AnyHttpUrl, Field, StrictInt, TypeAdapter
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from trading212_api_contracts.targets import UUIDString
from trading212_application.historical import PerformanceIntelligenceService
from trading212_application.planning import PlanningService
from trading212_application.reports import ReportService
from trading212_application.services import PortfolioService, SyntheticPortfolioService
from trading212_application.targets import TargetService
from trading212_application.xray import XrayService
from trading212_persistence import (
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
)
from trading212_persistence.target_service import PostgresTargetService
from trading212_security.principals import Scope as PortfolioScope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import BearerAuthenticator

from .auth import PrincipalResolver, SharedTokenVerifier
from .gateway import PortfolioMcpGateway
from .historical_gateway import HistoricalMcpGateway
from .historical_tools import HISTORICAL_TOOL_NAMES, register_historical_tools
from .planning_gateway import PlanningMcpGateway
from .planning_tools import PLANNING_TOOL_NAMES, register_planning_tools
from .report_gateway import ReportMcpGateway
from .report_tools import REPORT_TOOL_NAMES, register_report_tools
from .schemas import (
    AccountSummaryResult,
    ActivityTypeFilter,
    DataQualitySummaryResult,
    DirectAllocationResult,
    DividendSummaryResult,
    PortfolioSnapshotResult,
    PositionSort,
    PositionsResult,
    ReconciliationResult,
    SnapshotComparisonResult,
    TransactionsResult,
)
from .sdk_compat import finalize_tool_contract, harden_target_arguments
from .settings import McpSettings
from .target_gateway import TargetMcpGateway
from .target_schemas import VirtualPieResult, VirtualPiesResult
from .widget import SNAPSHOT_WIDGET_HTML, SNAPSHOT_WIDGET_MIME, SNAPSHOT_WIDGET_URI
from .xray_gateway import XrayMcpGateway
from .xray_tools import XRAY_TOOL_NAMES, register_xray_tools

FROZEN_TOOL_NAMES = (
    "get_account_summary",
    "get_portfolio_snapshot",
    "list_positions",
    "list_recent_transactions",
    "get_dividend_summary",
    "get_direct_allocation",
    "compare_portfolio_snapshots",
    "get_reconciliation_status",
    "get_data_quality_summary",
    "list_virtual_pies",
    "get_virtual_pie",
    *PLANNING_TOOL_NAMES,
    *HISTORICAL_TOOL_NAMES,
    *XRAY_TOOL_NAMES,
    *REPORT_TOOL_NAMES,
)

AccountId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="Opaque account ID returned by an authorized account surface.",
    ),
]
SnapshotId = Annotated[
    str,
    Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._:-]+$"),
]
Cursor = Annotated[str, Field(min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9_-]+$")]
_LOCAL_CURSOR_SIGNING_KEY = hashlib.sha256(
    b"trading212-portfolio-intelligence/local-cursor-signing-key/v1"
).digest()


@dataclass(frozen=True, slots=True)
class McpRuntime:
    server: MCPServer[Any]
    service: PortfolioService
    security_settings: SecuritySettings
    mcp_settings: McpSettings
    access_control_configured: bool
    target_service: TargetService | None = None
    planning_service: PlanningService | None = None
    historical_service: PerformanceIntelligenceService | None = None
    xray_service: XrayService | None = None
    report_service: ReportService | None = None

    def asgi_app(self) -> ASGIApp:
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_allowed_hosts(self.security_settings.allowed_hosts),
            allowed_origins=list(self.security_settings.allowed_origins),
        )
        application: ASGIApp = self.server.streamable_http_app(
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
            max_request_body_size=self.mcp_settings.max_request_body_bytes,
            transport_security=transport_security,
            host=self.mcp_settings.host,
        )
        if not self.access_control_configured:
            application = _FailClosedMcpMiddleware(application)
        return _SecurityHeadersMiddleware(application)


def create_runtime(
    *,
    security_settings: SecuritySettings | None = None,
    mcp_settings: McpSettings | None = None,
    service: PortfolioService | None = None,
    target_service: TargetService | None = None,
    planning_service: PlanningService | None = None,
    historical_service: PerformanceIntelligenceService | None = None,
    xray_service: XrayService | None = None,
    report_service: ReportService | None = None,
    database_url: str | None = None,
    bearer_authenticator: BearerAuthenticator | None = None,
    clock: Callable[[], datetime] | None = None,
    cursor_signing_key: bytes | None = None,
) -> McpRuntime:
    """Create an injectable MCP composition without resolving secrets itself."""
    runtime_clock = clock or (lambda: datetime.now(UTC))
    security = security_settings or SecuritySettings()
    transport = mcp_settings or McpSettings()
    if security.local_synthetic_auth_enabled and not _is_loopback_host(transport.host):
        explicit_local_container_bind = (
            security.environment is RuntimeEnvironment.LOCAL
            and transport.allow_non_loopback_local_synthetic_bind
        )
        if not explicit_local_container_bind:
            raise ValueError(
                "local synthetic MCP authentication requires a loopback bind host or the "
                "explicit local-container bind opt-in"
            )
    deployed = security.environment in {
        RuntimeEnvironment.STAGING,
        RuntimeEnvironment.PRODUCTION,
    }
    service_readiness: Callable[[], Awaitable[bool]] = _ready
    if service is not None:
        portfolio_service = service
    elif database_url:
        if deployed and cursor_signing_key is None:
            raise ValueError(
                "deployed MCP database service requires an explicit cursor signing key"
            )
        engine = create_database_engine(database_url)
        portfolio_service = PostgresPortfolioService(
            sessions=create_session_factory(engine),
            clock=runtime_clock,
            cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
            cursor_ttl_seconds=security.cursor_ttl_seconds,
        )
        if target_service is None:
            target_service = PostgresTargetService(
                sessions=create_session_factory(engine),
                clock=runtime_clock,
                cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
                cursor_ttl_seconds=security.cursor_ttl_seconds,
            )

        if planning_service is None:
            from trading212_persistence.planning_service import PostgresPlanningService

            planning_service = PostgresPlanningService(
                sessions=create_session_factory(engine),
                clock=runtime_clock,
                cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
                cursor_ttl_seconds=security.cursor_ttl_seconds,
            )

        if historical_service is None:
            from trading212_persistence.historical_service import PostgresHistoricalService

            historical_service = PostgresHistoricalService(
                create_session_factory(engine),
                clock=runtime_clock,
                cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
                cursor_ttl_seconds=security.cursor_ttl_seconds,
            )

        if xray_service is None:
            from trading212_persistence.xray_service import PostgresXrayService

            xray_service = PostgresXrayService(
                sessions=create_session_factory(engine),
                clock=runtime_clock,
                cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
                cursor_ttl_seconds=security.cursor_ttl_seconds,
            )

        if report_service is None:
            from trading212_persistence.report_service import PostgresReportService

            report_service = PostgresReportService(
                create_session_factory(engine),
                clock=runtime_clock,
                cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
                cursor_ttl_seconds=security.cursor_ttl_seconds,
            )

        async def database_readiness() -> bool:
            def probe() -> bool:
                try:
                    with engine.connect() as connection:
                        value = cast(int, connection.exec_driver_sql("SELECT 1").scalar_one())
                        return value == 1
                except Exception:
                    return False

            return await asyncio.to_thread(probe)

        service_readiness = database_readiness
    elif deployed:
        raise ValueError("deployed MCP requires an explicit service or DATABASE_URL")
    else:
        portfolio_service = SyntheticPortfolioService(
            clock=runtime_clock if clock is not None else None,
            cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
            cursor_ttl_seconds=security.cursor_ttl_seconds,
        )
    principal_resolver = PrincipalResolver.from_settings(security, clock=runtime_clock)

    auth_settings: AuthSettings | None = None
    token_verifier: SharedTokenVerifier | None = None
    if bearer_authenticator is not None:
        if security.issuer is None or transport.resource_server_url is None:
            raise ValueError(
                "bearer-authenticated MCP requires issuer and public resource-server URL"
            )
        issuer = TypeAdapter(AnyHttpUrl).validate_python(security.issuer)
        resource_url = TypeAdapter(AnyHttpUrl).validate_python(transport.resource_server_url)
        auth_settings = AuthSettings(
            issuer_url=issuer,
            resource_server_url=resource_url,
            # Authentication is global; exact scopes are enforced per application use case.
            required_scopes=[],
        )
        token_verifier = SharedTokenVerifier(
            bearer_authenticator,
            resource=transport.resource_server_url,
        )

    access_control_configured = security.local_synthetic_auth_enabled or token_verifier is not None
    server = MCPServer(
        name="trading212-portfolio-intelligence",
        title="Trading 212 Portfolio Intelligence",
        description="Private portfolio observations, canonical analytics, and virtual targets.",
        instructions=(
            "Read the authenticated user's canonical portfolio and create only authorized "
            "internal manual contribution-planning requests with an idempotency identity. "
            "Values are observations or deterministic analytics, never trade instructions; "
            "preserve quality warnings, timestamps, unavailable fields, and reporting currency."
        ),
        version="0.1.0",
        auth=auth_settings,
        token_verifier=token_verifier,
        log_level="INFO",
    )
    gateway = PortfolioMcpGateway(service=portfolio_service, principals=principal_resolver)
    _register_health(
        server,
        access_control_configured=access_control_configured,
        service_readiness=service_readiness,
    )
    _register_widget(server, widget_domain=transport.widget_domain)
    _register_tools(server, gateway)
    _register_target_tools(
        server,
        TargetMcpGateway(
            service=target_service,
            principals=principal_resolver,
            clock=runtime_clock,
        ),
    )
    register_planning_tools(
        server,
        PlanningMcpGateway(
            service=planning_service, principals=principal_resolver, clock=runtime_clock
        ),
        widget_domain=transport.widget_domain,
    )
    register_historical_tools(
        server,
        HistoricalMcpGateway(
            service=historical_service, principals=principal_resolver, clock=runtime_clock
        ),
        widget_domain=transport.widget_domain,
    )
    register_xray_tools(
        server,
        XrayMcpGateway(service=xray_service, principals=principal_resolver, clock=runtime_clock),
        widget_domain=transport.widget_domain,
    )
    register_report_tools(
        server,
        ReportMcpGateway(
            service=report_service, principals=principal_resolver, clock=runtime_clock
        ),
        widget_domain=transport.widget_domain,
    )
    return McpRuntime(
        server=server,
        service=portfolio_service,
        security_settings=security,
        mcp_settings=transport,
        access_control_configured=access_control_configured,
        target_service=target_service,
        planning_service=planning_service,
        historical_service=historical_service,
        xray_service=xray_service,
        report_service=report_service,
    )


async def _ready() -> bool:
    return True


def _register_health(
    server: MCPServer[Any],
    *,
    access_control_configured: bool,
    service_readiness: Callable[[], Awaitable[bool]],
) -> None:
    @server.custom_route(  # type: ignore[untyped-decorator]
        "/health/live", methods=["GET"], include_in_schema=False
    )
    async def liveness(_: Request) -> JSONResponse:
        return JSONResponse({"service": "mcp", "status": "ok"})

    @server.custom_route(  # type: ignore[untyped-decorator]
        "/health/ready", methods=["GET"], include_in_schema=False
    )
    async def readiness(_: Request) -> JSONResponse:
        if not access_control_configured:
            return JSONResponse(
                {
                    "service": "mcp",
                    "status": "not_ready",
                    "reason": "authentication_not_configured",
                },
                status_code=503,
            )
        if await service_readiness():
            return JSONResponse({"service": "mcp", "status": "ready"})
        return JSONResponse(
            {
                "service": "mcp",
                "status": "not_ready",
                "reason": "portfolio_store_unavailable",
            },
            status_code=503,
        )


def _register_widget(server: MCPServer[Any], *, widget_domain: AnyHttpUrl | None) -> None:
    ui_meta: dict[str, Any] = {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
    }
    if widget_domain is not None:
        ui_meta["domain"] = str(widget_domain).rstrip("/")
    resource_meta: dict[str, Any] = {
        "ui": ui_meta,
        "openai/widgetDescription": (
            "Read-only canonical portfolio snapshot with explicit synthetic-data and "
            "quality disclosures."
        ),
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {
            "connect_domains": [],
            "resource_domains": [],
        },
    }
    if widget_domain is not None:
        resource_meta["openai/widgetDomain"] = str(widget_domain).rstrip("/")

    @server.resource(
        SNAPSHOT_WIDGET_URI,
        name="portfolio-snapshot-v1",
        title="Portfolio snapshot card",
        description="Accessible read-only portfolio snapshot presentation.",
        mime_type=SNAPSHOT_WIDGET_MIME,
        meta=resource_meta,
    )
    def portfolio_snapshot_widget() -> str:
        return SNAPSHOT_WIDGET_HTML


def _register_tools(server: MCPServer[Any], gateway: PortfolioMcpGateway) -> None:
    annotations = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )

    @server.tool(
        name="get_account_summary",
        title="Get account summary",
        description=(
            "Return bounded canonical account totals, freshness, and reconciliation state for an "
            "authorized portfolio. This is observational and cannot place or modify trades."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ,),
            invoking="Reading account summary…",
            invoked="Account summary ready",
        ),
        structured_output=False,
    )
    async def get_account_summary(
        account_id: AccountId, context: Context[Any, Any]
    ) -> CallToolResult:
        return await gateway.get_account_summary(account_id, context)

    finalize_tool_contract(server, name="get_account_summary", output_model=AccountSummaryResult)

    @server.tool(
        name="get_portfolio_snapshot",
        title="Get portfolio snapshot",
        description=(
            "Return one immutable canonical portfolio snapshot, defaulting to the latest covered "
            "snapshot, with explicit quality and unavailable fields. It never places trades."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ,),
            invoking="Reading portfolio snapshot…",
            invoked="Portfolio snapshot ready",
            widget=True,
        ),
        structured_output=False,
    )
    async def get_portfolio_snapshot(
        account_id: AccountId,
        context: Context[Any, Any],
        snapshot_id: SnapshotId | None = None,
    ) -> CallToolResult:
        return await gateway.get_portfolio_snapshot(account_id, snapshot_id, context)

    finalize_tool_contract(
        server, name="get_portfolio_snapshot", output_model=PortfolioSnapshotResult
    )

    @server.tool(
        name="list_positions",
        title="List portfolio positions",
        description=(
            "List a bounded page of canonical position observations with direct weights, values, "
            "timestamps, and quality. Search and sort are local to authorized portfolio data; "
            "no trades."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ,),
            invoking="Reading positions…",
            invoked="Positions ready",
        ),
        structured_output=False,
    )
    async def list_positions(
        account_id: AccountId,
        context: Context[Any, Any],
        cursor: Cursor | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 25,
        sort: PositionSort = PositionSort.MARKET_VALUE_DESC,
        search: Annotated[str | None, Field(min_length=1, max_length=80)] = None,
    ) -> CallToolResult:
        return await gateway.list_positions(
            account_id,
            cursor=cursor,
            limit=limit,
            sort=sort,
            search=search,
            context=context,
        )

    finalize_tool_contract(server, name="list_positions", output_model=PositionsResult)

    @server.tool(
        name="list_recent_transactions",
        title="List recent transactions",
        description=(
            "List normalized read-only portfolio activity within a required date window of at most "
            "366 days. Unknown activity types remain explicit; this cannot submit broker actions."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ, PortfolioScope.ACTIVITY_READ),
            invoking="Reading transactions…",
            invoked="Transactions ready",
        ),
        structured_output=False,
    )
    async def list_recent_transactions(
        account_id: AccountId,
        start_date: date,
        end_date: date,
        context: Context[Any, Any],
        type_filter: ActivityTypeFilter = ActivityTypeFilter.ALL,
        cursor: Cursor | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 25,
    ) -> CallToolResult:
        return await gateway.list_recent_transactions(
            account_id,
            start_date=start_date,
            end_date=end_date,
            type_filter=type_filter,
            cursor=cursor,
            limit=limit,
            context=context,
        )

    finalize_tool_contract(server, name="list_recent_transactions", output_model=TransactionsResult)

    @server.tool(
        name="get_dividend_summary",
        title="Get dividend summary",
        description=(
            "Summarize covered dividend observations over a required bounded period, grouped by "
            "currency with recent rows and coverage warnings. No FX or dividend value is "
            "fabricated."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ, PortfolioScope.ACTIVITY_READ),
            invoking="Summarizing dividends…",
            invoked="Dividend summary ready",
        ),
        structured_output=False,
    )
    async def get_dividend_summary(
        account_id: AccountId,
        start_date: date,
        end_date: date,
        context: Context[Any, Any],
        recent_limit: Annotated[int, Field(ge=1, le=25)] = 10,
    ) -> CallToolResult:
        return await gateway.get_dividend_summary(
            account_id,
            start_date=start_date,
            end_date=end_date,
            recent_limit=recent_limit,
            context=context,
        )

    finalize_tool_contract(server, name="get_dividend_summary", output_model=DividendSummaryResult)

    @server.tool(
        name="get_direct_allocation",
        title="Get direct allocation",
        description=(
            "Return bounded direct position weights and cash allocation only. Phase 1 performs no "
            "ETF look-through, target optimization, or broker mutation."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ,),
            invoking="Calculating direct allocation…",
            invoked="Direct allocation ready",
        ),
        structured_output=False,
    )
    async def get_direct_allocation(
        account_id: AccountId,
        context: Context[Any, Any],
        top_n: Annotated[int, Field(ge=1, le=50)] = 25,
    ) -> CallToolResult:
        return await gateway.get_direct_allocation(
            account_id,
            top_n=top_n,
            context=context,
        )

    finalize_tool_contract(
        server, name="get_direct_allocation", output_model=DirectAllocationResult
    )

    @server.tool(
        name="compare_portfolio_snapshots",
        title="Compare portfolio snapshots",
        description=(
            "Compare two authorized immutable snapshot IDs using covered Phase 1 value, cash, "
            "flow, "
            "and residual effects. It does not fabricate attribution or place trades."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ,),
            invoking="Comparing snapshots…",
            invoked="Snapshot comparison ready",
        ),
        structured_output=False,
    )
    async def compare_portfolio_snapshots(
        account_id: AccountId,
        start_snapshot_id: SnapshotId,
        end_snapshot_id: SnapshotId,
        context: Context[Any, Any],
    ) -> CallToolResult:
        return await gateway.compare_portfolio_snapshots(
            account_id,
            start_snapshot_id=start_snapshot_id,
            end_snapshot_id=end_snapshot_id,
            context=context,
        )

    finalize_tool_contract(
        server,
        name="compare_portfolio_snapshots",
        output_model=SnapshotComparisonResult,
    )

    @server.tool(
        name="get_reconciliation_status",
        title="Get reconciliation status",
        description=(
            "Return bounded reconciliation status, discrepancies, residuals, versions, and safe "
            "remediation guidance for an authorized portfolio. It is strictly read-only."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ,),
            invoking="Reading reconciliation…",
            invoked="Reconciliation ready",
        ),
        structured_output=False,
    )
    async def get_reconciliation_status(
        account_id: AccountId,
        context: Context[Any, Any],
        issue_limit: Annotated[int, Field(ge=1, le=50)] = 25,
    ) -> CallToolResult:
        return await gateway.get_reconciliation_status(
            account_id,
            issue_limit=issue_limit,
            context=context,
        )

    finalize_tool_contract(
        server, name="get_reconciliation_status", output_model=ReconciliationResult
    )

    @server.tool(
        name="get_data_quality_summary",
        title="Get data-quality summary",
        description=(
            "Return freshness and quality states by bounded Phase 1 dataset, including source "
            "cutoffs "
            "and warnings. It reports missing coverage explicitly and never refreshes or trades."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ, PortfolioScope.ACTIVITY_READ),
            invoking="Reading data quality…",
            invoked="Data quality ready",
        ),
        structured_output=False,
    )
    async def get_data_quality_summary(
        account_id: AccountId,
        context: Context[Any, Any],
    ) -> CallToolResult:
        return await gateway.get_data_quality_summary(account_id, context)

    finalize_tool_contract(
        server, name="get_data_quality_summary", output_model=DataQualitySummaryResult
    )


def _register_target_tools(server: MCPServer[Any], gateway: TargetMcpGateway) -> None:
    annotations = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )

    @server.tool(
        name="list_virtual_pies",
        title="List virtual portfolios",
        description=(
            "Read an authorized bounded page of virtual portfolio configuration. "
            "An explicit null account selects private templates. No broker mutation."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ, PortfolioScope.TARGETS_READ),
            invoking="Reading virtual portfolios",
            invoked="Virtual portfolios ready",
        ),
        structured_output=False,
    )
    async def list_virtual_pies(
        account_id: UUIDString | None,
        context: Context[Any, Any],
        cursor: Cursor | None = None,
        limit: Annotated[StrictInt, Field(ge=1, le=100)] = 25,
        state: Literal["draft", "active", "archived", "all"] = "active",
        search: Annotated[str | None, Field(max_length=80)] = None,
        sort: Literal["name_asc", "updated_desc"] = "name_asc",
    ) -> CallToolResult:
        return await gateway.list_virtual_pies(
            account_id,
            cursor=cursor,
            limit=limit,
            state=state,
            search=search,
            sort=sort,
            context=context,
        )

    finalize_tool_contract(server, name="list_virtual_pies", output_model=VirtualPiesResult)

    @server.tool(
        name="get_virtual_pie",
        title="Read virtual portfolio targets",
        description=(
            "Read one authorized virtual portfolio and its selected target version, "
            "with bounded hierarchy, validation, and unresolved mapping states. "
            "An omitted version selects the current active version; no broker action."
        ),
        annotations=annotations,
        meta=_tool_meta(
            (PortfolioScope.PORTFOLIO_READ, PortfolioScope.TARGETS_READ),
            invoking="Reading virtual targets",
            invoked="Virtual targets ready",
        ),
        structured_output=False,
    )
    async def get_virtual_pie(
        account_id: UUIDString | None,
        virtual_portfolio_id: UUIDString,
        context: Context[Any, Any],
        target_version_id: UUIDString | None = None,
        parent_node_id: UUIDString | None = None,
        cursor: Cursor | None = None,
        limit: Annotated[StrictInt, Field(ge=1, le=100)] = 25,
    ) -> CallToolResult:
        return await gateway.get_virtual_pie(
            account_id,
            virtual_portfolio_id,
            target_version_id=target_version_id,
            parent_node_id=parent_node_id,
            cursor=cursor,
            limit=limit,
            context=context,
        )

    finalize_tool_contract(server, name="get_virtual_pie", output_model=VirtualPieResult)
    # Apply strict/no-input-echo validation only to new tools; the nine existing
    # descriptor schemas and argument behavior retain their Phase 1 contract.
    for name in ("list_virtual_pies", "get_virtual_pie"):
        harden_target_arguments(server, name=name)


def _tool_meta(
    scopes: tuple[PortfolioScope, ...],
    *,
    invoking: str,
    invoked: str,
    widget: bool = False,
) -> dict[str, Any]:
    security_schemes = [
        {
            "type": "oauth2",
            "scopes": [scope.value for scope in scopes],
        }
    ]
    meta: dict[str, Any] = {
        "securitySchemes": security_schemes,
        "openai/toolInvocation/invoking": invoking,
        "openai/toolInvocation/invoked": invoked,
    }
    if widget:
        meta.update(
            {
                "ui": {"resourceUri": SNAPSHOT_WIDGET_URI, "visibility": ["model", "app"]},
                "openai/outputTemplate": SNAPSHOT_WIDGET_URI,
            }
        )
    return meta


def _allowed_hosts(hosts: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for host in hosts:
        values.append(host)
        if ":" not in host and host != "*":
            values.append(f"{host}:*")
    return values


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().casefold().removeprefix("[").removesuffix("]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class _FailClosedMcpMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            await JSONResponse(
                {"error": "invalid_token", "error_description": "Authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        await self._app(scope, receive, send)


class _SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                protected_names = {
                    b"cache-control",
                    b"x-content-type-options",
                    b"referrer-policy",
                }
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in protected_names
                ]
                headers.extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self._app(scope, receive, send_with_headers)


def create_asgi_app(**kwargs: Any) -> ASGIApp:
    """Uvicorn-compatible application factory."""
    return create_runtime(**kwargs).asgi_app()
