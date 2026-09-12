"""Authenticated MCP application composition root."""

from .server import FROZEN_TOOL_NAMES, McpRuntime, create_asgi_app, create_runtime

__version__ = "0.2.0"

__all__ = [
    "FROZEN_TOOL_NAMES",
    "McpRuntime",
    "create_asgi_app",
    "create_runtime",
]
