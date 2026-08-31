"""Narrow compatibility hardening for the repository-pinned MCP Python SDK."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import Tool as WireTool
from pydantic import BaseModel

# MCP Python 2.1.1's wire model does not yet expose the OpenAI descriptor extension.
# The documented `_meta.securitySchemes` compatibility mirror is therefore emitted.
TOP_LEVEL_SECURITY_SCHEMES_SUPPORTED = "security_schemes" in WireTool.model_fields
TOP_LEVEL_SECURITY_SCHEMES_BLOCKER = (
    "mcp==2.1.1 mcp.types.Tool has no top-level securitySchemes field; "
    "the official _meta.securitySchemes compatibility mirror is emitted instead"
)


def finalize_tool_contract(
    server: MCPServer[Any],
    *,
    name: str,
    output_model: type[BaseModel],
) -> None:
    """Make input rejection and structured output schemas exact under MCP 2.1.1.

    MCP 2.1.1 builds function-argument Pydantic models with the default
    ``extra=ignore`` behavior. The repository contract is fail-closed, so this
    pinned adapter rebuilds each generated model with ``extra=forbid`` and
    publishes the matching schema. It also lets handlers return ``CallToolResult``
    (for concise content and widget-only metadata) while validating structured
    content against the declared result model.
    """
    internal = server._tool_manager.get_tool(name)
    if internal is None:  # pragma: no cover - authoring invariant
        raise RuntimeError(f"MCP tool {name!r} was not registered")

    argument_model = internal.fn_metadata.arg_model
    argument_model.model_config["extra"] = "forbid"
    argument_model.model_rebuild(force=True)
    internal.parameters = argument_model.model_json_schema(by_alias=True)

    internal.fn_metadata.output_model = output_model
    internal.fn_metadata.output_schema = output_model.model_json_schema(by_alias=True)
    internal.fn_metadata.wrap_output = False
