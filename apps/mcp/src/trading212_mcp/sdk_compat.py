"""Narrow compatibility hardening for the repository-pinned MCP Python SDK."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.types import Tool as WireTool
from pydantic import BaseModel, ConfigDict, create_model, model_validator

# MCP Python 2.1.1's wire model does not yet expose the OpenAI descriptor extension.
# The documented `_meta.securitySchemes` compatibility mirror is therefore emitted.
TOP_LEVEL_SECURITY_SCHEMES_SUPPORTED = "security_schemes" in WireTool.model_fields
TOP_LEVEL_SECURITY_SCHEMES_BLOCKER = (
    "mcp==2.1.1 mcp.types.Tool has no top-level securitySchemes field; "
    "the official _meta.securitySchemes compatibility mirror is emitted instead"
)


class _PrivateArguments(ArgModelBase):
    # Keep Phase 1 coercion and the SDK's JSON pre-parser unchanged.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def reject_private_unknown_keys(cls, value: object) -> object:
        allowed = set(cls.model_fields)
        allowed.update(field.alias for field in cls.model_fields.values() if field.alias)
        if isinstance(value, dict) and any(key not in allowed for key in value):
            # An ordinary extra-field error exposes the caller-controlled field name.
            raise ValueError("Extra inputs are not permitted.")
        return value


class _StrictTargetArguments(ArgModelBase):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def reject_unknown_keys(cls, value: object) -> object:
        allowed = set(cls.model_fields)
        allowed.update(field.alias for field in cls.model_fields.values() if field.alias)
        if not isinstance(value, dict) or any(key not in allowed for key in value):
            # Pydantic's ordinary extra-field location would repeat the caller's key.
            raise ValueError("The bounded target arguments contain unexpected fields.")
        return value


class _StrictTargetMetadata(FuncMetadata):
    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        # SDK 2.1.1 otherwise turns the string "null" into None for optional strings.
        return data


def harden_target_arguments(server: MCPServer[Any], *, name: str) -> None:
    """Preserve literal input types and suppress unknown argument-name reflection."""
    internal = server._tool_manager.get_tool(name)
    if internal is None:  # pragma: no cover - fixed registration invariant
        raise RuntimeError("Target tool registration is incomplete")
    metadata = internal.fn_metadata
    argument_model = create_model(
        metadata.arg_model.__name__,
        __base__=(metadata.arg_model, _StrictTargetArguments),
    )
    internal.fn_metadata = _StrictTargetMetadata(
        arg_model=argument_model,
        output_model=metadata.output_model,
        output_schema=metadata.output_schema,
        wrap_output=metadata.wrap_output,
    )
    internal.parameters = argument_model.model_json_schema(by_alias=True)


def finalize_tool_contract(
    server: MCPServer[Any],
    *,
    name: str,
    output_model: type[BaseModel],
) -> None:
    """Make input rejection and structured output schemas exact under MCP 2.1.1.

    MCP 2.1.1 builds function-argument Pydantic models with the default
    ``extra=ignore`` behavior. The repository contract is fail-closed, so this
    pinned adapter adds unknown-field rejection and private validation errors
    without changing legacy coercion. It publishes the matching schema and lets
    handlers return ``CallToolResult``
    (for concise content and widget-only metadata) while validating structured
    content against the declared result model.
    """
    internal = server._tool_manager.get_tool(name)
    if internal is None:  # pragma: no cover - authoring invariant
        raise RuntimeError(f"MCP tool {name!r} was not registered")

    argument_model = create_model(
        internal.fn_metadata.arg_model.__name__,
        __base__=(internal.fn_metadata.arg_model, _PrivateArguments),
    )
    internal.fn_metadata.arg_model = argument_model
    internal.parameters = argument_model.model_json_schema(by_alias=True)

    internal.fn_metadata.output_model = output_model
    internal.fn_metadata.output_schema = output_model.model_json_schema(by_alias=True)
    internal.fn_metadata.wrap_output = False
