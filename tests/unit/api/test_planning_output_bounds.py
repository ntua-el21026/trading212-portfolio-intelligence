"""Full valid canonical provenance is bounded before HTTP/MCP serialization escapes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
from mcp.types import CallToolResult
from trading212_analytics.planning import calculate_drift
from trading212_api.main import create_app
from trading212_api_contracts import planning as wire
from trading212_application import planning as app
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import Page
from trading212_domain.serialization import to_primitive
from trading212_mcp.server import create_runtime
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.unit.analytics.planning_factories import planning_input

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


def _large_result() -> app.ActualVsTargetResult:
    pinned = planning_input()
    result = calculate_drift(pinned)
    source = result.context.sources[0]
    context = replace(
        result.context,
        sources=tuple(
            replace(source, id=str(UUID(int=index + 1)), version="v" * 80) for index in range(8192)
        ),
    )
    value = app.ActualVsTargetResult(
        context,
        NOW,
        result.totals,
        Page(result.rows, None, 25, len(result.rows)),
        "a" * 64,
        pinned.node_identities,
    )
    # Prove this tests the aggregate byte boundary, not a malformed schema fallback.
    wire.ActualVsTargetResult.model_validate(
        wire.canonical_planning_payload(to_primitive(value), wire.ActualVsTargetResult)
    )
    return value


async def test_valid_large_provenance_is_rejected_by_both_http_and_mcp() -> None:
    value = _large_result()
    service = AsyncMock(spec=app.PlanningService)
    service.get_actual_vs_target.return_value = value
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
        allowed_hosts=("testserver",),
    )
    api = create_app(
        settings=settings,
        service=SyntheticPortfolioService(clock=lambda: NOW),
        planning_service=cast(app.PlanningService, service),
        clock=lambda: NOW,
    )
    pins = {
        "snapshot_id": value.context.snapshot_id,
        "virtual_portfolio_id": value.context.virtual_portfolio_id,
        "target_version_id": value.context.target_version_id,
        "reporting_currency": "EUR",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api), base_url="https://testserver"
    ) as client:
        assert (await client.post("/api/v1/auth/local-session")).status_code == 201
        response = await client.get(
            f"/api/v1/accounts/{value.context.account_id}/actual-vs-target", params=pins
        )
        assert (
            response.status_code == 422 and response.json()["error"]["code"] == "RESULT_TOO_LARGE"
        )
        assert len(response.content) < 1024
    runtime = create_runtime(
        security_settings=settings,
        planning_service=cast(app.PlanningService, service),
        clock=lambda: NOW,
    )
    mcp = await runtime.server.call_tool(
        "get_actual_vs_target", {"account_id": value.context.account_id, **pins}
    )
    assert isinstance(mcp, CallToolResult) and mcp.is_error and mcp.structured_content is not None
    assert mcp.structured_content["error"]["code"] == "RESULT_TOO_LARGE"
    assert len(mcp.model_dump_json()) < 2048
