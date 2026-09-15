"""Three closed offline resource registrations and two expressly authorized UI deltas."""

from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import AnyHttpUrl

from .allocation_widget import ALLOCATION_WIDGET_HTML, ALLOCATION_WIDGET_URI
from .drift_widget import DRIFT_WIDGET_HTML, DRIFT_WIDGET_URI


def register_read_resource(
    server: MCPServer[Any],
    *,
    uri: str,
    html: str,
    name: str,
    title: str,
    description: str,
    widget_domain: AnyHttpUrl | None,
) -> None:
    ui: dict[str, Any] = {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
    }
    meta: dict[str, Any] = {
        "ui": ui,
        "openai/widgetDescription": description,
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    }
    if widget_domain is not None:
        ui["domain"] = str(widget_domain).rstrip("/")
        meta["openai/widgetDomain"] = str(widget_domain).rstrip("/")

    @server.resource(
        uri,
        name=name,
        title=title,
        description=description,
        mime_type="text/html;profile=mcp-app",
        meta=meta,
    )
    def widget() -> str:
        return html


def register_analysis_widgets(server: MCPServer[Any], *, widget_domain: AnyHttpUrl | None) -> None:
    for tool, uri, html, name, title, description in (
        (
            "get_direct_allocation",
            ALLOCATION_WIDGET_URI,
            ALLOCATION_WIDGET_HTML,
            "allocation-v1",
            "Direct portfolio allocation",
            "Exact observed positions and cash allocation with quality and source proof.",
        ),
        (
            "get_drift_analysis",
            DRIFT_WIDGET_URI,
            DRIFT_WIDGET_HTML,
            "drift-v1",
            "Portfolio allocation drift",
            (
                "Bounded drift rows with full-universe totals, exact ratios and i"
                "mmutable source context."
            ),
        ),
    ):
        internal = server._tool_manager.get_tool(tool)
        if internal is None:
            raise RuntimeError("The frozen analysis tool registration is incomplete.")
        internal.meta = {
            **(internal.meta or {}),
            "ui": {"resourceUri": uri, "visibility": ["model", "app"]},
            "openai/outputTemplate": uri,
            "openai/widgetAccessible": True,
        }
        register_read_resource(
            server,
            uri=uri,
            html=html,
            name=name,
            title=title,
            description=description,
            widget_domain=widget_domain,
        )
