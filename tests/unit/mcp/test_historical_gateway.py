"""Historical MCP strict inputs, exact read-only delegation, bounded outputs and private errors."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from trading212_application import historical as app
from trading212_mcp.auth import PrincipalResolver
from trading212_mcp.server import create_runtime
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from tests.unit.api.historical_factories import ACCOUNT, QUERY, VERSION, payload

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
NAMES = (
    "get_performance_summary",
    "get_benchmark_comparison",
    "get_dividend_intelligence",
    "get_attribution_summary",
)


def runtime(service: AsyncMock | None = None) -> MCPServer[Any]:
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        historical_service=cast(app.PerformanceIntelligenceService, service)
        if service is not None
        else None,
        clock=lambda: NOW,
    ).server


def args(name: str) -> dict[str, Any]:
    return {
        "account_id": ACCOUNT,
        **QUERY,
        **({"benchmark_version_id": VERSION} if name == "get_benchmark_comparison" else {}),
    }


async def call(server: MCPServer[Any], name: str, arguments: dict[str, Any]) -> CallToolResult:
    result = await server.call_tool(name, arguments)
    assert isinstance(result, CallToolResult) and result.structured_content is not None
    return result


@pytest.mark.parametrize("name", NAMES)
async def test_four_tools_delegate_once_and_preserve_canonical_full_result(name: str) -> None:
    service = AsyncMock(spec=app.PerformanceIntelligenceService)
    getattr(service, name).return_value = payload(name)
    result = await call(runtime(service), name, args(name))
    assert not result.is_error, result
    assert result.structured_content["data"] == payload(name)
    assert len(service.mock_calls) == 1
    _, account = getattr(service, name).call_args.args
    query = getattr(service, name).call_args.kwargs["query"]
    assert account == ACCOUNT and query.input_snapshot_id is None
    assert query.window.knowledge_policy.value == "as_of_cutoff"
    assert query.window.coverage_policy.value == "require_complete"
    assert result.structured_content["selection"]["omitted"] == 0


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    "extra",
    [
        {"private-selector-canary": "private-value-canary"},
        {"knowledge_policy": "point_in_time"},
        {"input_snapshot_id": VERSION},
        {"rolling_window": "calendar_days_30"},
        {"cursor": "abc"},
    ],
)
async def test_no_extra_api_options_or_unknown_keys_are_exposed_by_mcp(
    name: str, extra: dict[str, str]
) -> None:
    service = AsyncMock(spec=app.PerformanceIntelligenceService)
    with pytest.raises(ToolError) as error:
        await call(runtime(service), name, {**args(name), **extra})
    assert "canary" not in str(error.value)
    assert not service.mock_calls


@pytest.mark.parametrize(
    "extra",
    [
        {"top_n": 51},
        {"top_n": True},
        {"top_n": "25"},
        {"grouping": "asset_class"},
        {"grouping": "group"},
        {"method": "modified_dietz"},
        {"benchmark_version_id": VERSION},
    ],
)
async def test_attribution_frozen_bounds_and_group_reference(extra: dict[str, Any]) -> None:
    service = AsyncMock(spec=app.PerformanceIntelligenceService)
    with pytest.raises(ToolError):
        await call(
            runtime(service),
            "get_attribution_summary",
            {**args("get_attribution_summary"), **extra},
        )
    assert not service.mock_calls


@pytest.mark.parametrize(
    ("name", "missing"),
    [
        ("get_performance_summary", Scope.ANALYTICS_READ),
        ("get_benchmark_comparison", Scope.PORTFOLIO_READ),
        ("get_dividend_intelligence", Scope.ACTIVITY_READ),
        ("get_attribution_summary", Scope.TARGETS_READ),
    ],
)
async def test_scope_denial_precedes_service(
    name: str, missing: Scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def principal(_: PrincipalResolver) -> Principal:
        return Principal(
            "historical-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "test",
            "test",
            frozenset(Scope) - {missing},
            NOW - timedelta(hours=1),
            NOW + timedelta(hours=1),
        )

    monkeypatch.setattr(PrincipalResolver, "resolve", principal)
    service = AsyncMock(spec=app.PerformanceIntelligenceService)
    result = await call(runtime(service), name, args(name))
    assert result.is_error and result.structured_content["error"]["code"] == "ACCESS_DENIED"
    assert not service.mock_calls


@pytest.mark.parametrize("mode", ["owner", "unknown", "float", "bound", "oversized"])
async def test_invalid_output_is_sanitized_before_tool_result(mode: str) -> None:
    service = AsyncMock(spec=app.PerformanceIntelligenceService)
    data = copy.deepcopy(payload("get_performance_summary"))
    if mode == "owner":
        data["context"]["account_id"] = VERSION
    elif mode == "unknown":
        data["context"]["provider-private-canary"] = "private-value-canary"
    elif mode == "float":
        data["summary"]["ending_value"]["value"]["amount"] = 0.1
    elif mode == "bound":
        data["series"] *= 3662
    else:
        data["series"] *= 3661
    service.get_performance_summary.return_value = data
    result = await call(
        runtime(service), "get_performance_summary", args("get_performance_summary")
    )
    assert result.is_error
    assert result.structured_content["error"]["code"] == (
        "RESULT_TOO_LARGE" if mode == "oversized" else "INTERNAL_ERROR"
    )
    assert "canary" not in result.model_dump_json()
    assert (
        result.structured_content["data"] is None and result.structured_content["selection"] is None
    )


async def test_typed_service_failure_and_missing_runtime_never_invent_data() -> None:
    service = AsyncMock(spec=app.PerformanceIntelligenceService)
    service.get_performance_summary.side_effect = app.HistoricalServiceError(
        app.HistoricalServiceErrorCode.ACCESS_DENIED, "provider-private-canary"
    )
    denied = await call(
        runtime(service), "get_performance_summary", args("get_performance_summary")
    )
    unavailable = await call(runtime(), "get_performance_summary", args("get_performance_summary"))
    assert denied.is_error and denied.structured_content["error"]["code"] == "ACCESS_DENIED"
    assert "canary" not in denied.model_dump_json()
    assert (
        unavailable.is_error
        and unavailable.structured_content["error"]["code"] == "HISTORICAL_UNAVAILABLE"
    )


@pytest.mark.parametrize(
    "override",
    [
        {"start_date": 20260101},
        {"start_date": True},
        {"start_date": "2026-02-30"},
        {"start_date": "2026-01-01T00:00:00Z"},
        {"end_date": "2025-12-31"},
        {"source_cutoff_at": 1767225600},
        {"source_cutoff_at": "2026-02-01T00:00:00"},
        {"source_cutoff_at": "2026-02-01"},
    ],
)
async def test_literal_date_instant_validation_survives_strict_sdk_model(
    override: dict[str, Any],
) -> None:
    service = AsyncMock(spec=app.PerformanceIntelligenceService)
    with pytest.raises(ToolError):
        await call(
            runtime(service),
            "get_performance_summary",
            {**args("get_performance_summary"), **override},
        )
    assert not service.mock_calls
