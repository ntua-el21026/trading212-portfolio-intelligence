"""Fail-closed MCP Streamable HTTP process entry point."""

from __future__ import annotations

import os

import uvicorn
from trading212_observability import configure_logging, configure_tracing

from .server import create_runtime


def health() -> dict[str, str]:
    """Return bounded process metadata without exposing configuration."""
    return {"service": "mcp", "status": "ok"}


def main() -> None:
    """Run only when OAuth or explicitly local synthetic authentication is configured."""
    canary = os.environ.get("PHASE1_SECRET_CANARY")
    configure_logging(service="trading212-mcp", secret_canaries=(canary,) if canary else ())
    configure_tracing(service="trading212-mcp")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("MCP refused to start: DATABASE_URL is required")
    runtime = create_runtime(database_url=database_url)
    if not runtime.access_control_configured:
        raise SystemExit(
            "MCP refused to start: configure the deployment bearer-auth composition or enable "
            "explicit local/test synthetic authentication"
        )
    uvicorn.run(
        runtime.asgi_app(),
        host=runtime.mcp_settings.host,
        port=runtime.mcp_settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
