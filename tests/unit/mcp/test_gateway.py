"""Unit coverage for bounded Phase 1 MCP use-case adaptation."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel
from trading212_application.services import SyntheticPortfolioService
from trading212_application.views import Page, SnapshotView, ViewQuality
from trading212_mcp.schemas import RESULT_MODELS
from trading212_mcp.server import create_runtime
from trading212_persistence import PostgresPortfolioService
from trading212_security.settings import RuntimeEnvironment, SecuritySettings


def _runtime(service: SyntheticPortfolioService | None = None) -> MCPServer[Any]:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
    )
    return create_runtime(security_settings=settings, service=service).server


@pytest.mark.unit
def test_runtime_composes_postgres_service_when_database_url_is_supplied() -> None:
    settings = SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
    )
    runtime = create_runtime(
        security_settings=settings,
        database_url="postgresql+psycopg://portfolio:portfolio@localhost/portfolio",
    )

    assert isinstance(runtime.service, PostgresPortfolioService)


async def _call_tool(
    server: MCPServer[Any], tool_name: str, arguments: dict[str, Any]
) -> CallToolResult:
    result = await server.call_tool(tool_name, arguments)
    assert isinstance(result, CallToolResult)
    return result


def _text(result: CallToolResult) -> str:
    content = result.content[0]
    assert isinstance(content, TextContent)
    return content.text


SUCCESS_CASES = {
    "get_account_summary": {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
    "get_portfolio_snapshot": {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
    "list_positions": {"account_id": SyntheticPortfolioService.ACCOUNT_ID, "limit": 2},
    "list_recent_transactions": {
        "account_id": SyntheticPortfolioService.ACCOUNT_ID,
        "start_date": "2026-01-01",
        "end_date": "2026-08-31",
    },
    "get_dividend_summary": {
        "account_id": SyntheticPortfolioService.ACCOUNT_ID,
        "start_date": "2026-01-01",
        "end_date": "2026-08-31",
    },
    "get_direct_allocation": {
        "account_id": SyntheticPortfolioService.ACCOUNT_ID,
        "top_n": 3,
    },
    "compare_portfolio_snapshots": {
        "account_id": SyntheticPortfolioService.ACCOUNT_ID,
        "start_snapshot_id": "snapshot-2026-07-31",
        "end_snapshot_id": "snapshot-2026-08-31",
    },
    "get_reconciliation_status": {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
    "get_data_quality_summary": {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
}


@pytest.mark.unit
@pytest.mark.parametrize(("tool_name", "arguments"), SUCCESS_CASES.items())
async def test_each_frozen_tool_returns_schema_valid_structured_content(
    tool_name: str, arguments: dict[str, Any]
) -> None:
    result = await _call_tool(_runtime(), tool_name, arguments)

    assert result.is_error is False
    assert result.structured_content is not None
    result_model = cast(type[BaseModel], RESULT_MODELS[tool_name])
    result_model.model_validate(result.structured_content)
    assert result.structured_content["error"] is None
    assert result.structured_content["reporting_currency"] == "EUR"
    assert result.structured_content["data_quality"]["state"] == "fresh"
    assert result.structured_content["calculation"]["version"]
    assert 1 <= len(_text(result)) <= 360
    assert "{" not in _text(result)


@pytest.mark.unit
async def test_repeated_read_is_idempotent_and_deterministic() -> None:
    server = _runtime()
    arguments = {"account_id": SyntheticPortfolioService.ACCOUNT_ID, "limit": 2}

    first = await _call_tool(server, "list_positions", arguments)
    second = await _call_tool(server, "list_positions", arguments)

    assert first.structured_content == second.structured_content
    assert first.structured_content["pagination"] == {
        "next_cursor": "p1:2",
        "limit": 2,
        "total": 5,
        "truncated": False,
    }


@pytest.mark.unit
async def test_position_search_sort_and_cursor_remain_bounded() -> None:
    result = await _call_tool(
        _runtime(),
        "list_positions",
        {
            "account_id": SyntheticPortfolioService.ACCOUNT_ID,
            "search": "world",
            "sort": "ticker_asc",
            "limit": 1,
        },
    )

    assert result.is_error is False
    assert [row["ticker"] for row in result.structured_content["data"]["positions"]] == ["IWDA"]
    assert result.structured_content["pagination"]["total"] == 2


@pytest.mark.unit
async def test_cross_account_access_is_safely_denied() -> None:
    result = await _call_tool(
        _runtime(), "get_account_summary", {"account_id": "another-private-account"}
    )

    assert result.is_error is True
    error = result.structured_content["error"]
    assert error["code"] == "ACCESS_DENIED"
    assert "another-private-account" not in str(result.model_dump(mode="json"))


@pytest.mark.unit
async def test_oversized_date_window_returns_structured_safe_validation_error() -> None:
    result = await _call_tool(
        _runtime(),
        "list_recent_transactions",
        {
            "account_id": SyntheticPortfolioService.ACCOUNT_ID,
            "start_date": "2024-01-01",
            "end_date": "2026-08-31",
        },
    )

    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "VALIDATION_FAILED"
    assert "date range" not in _text(result).casefold()


class EmptySnapshotsService(SyntheticPortfolioService):
    async def list_snapshots(
        self,
        principal: Any,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Page[SnapshotView]:
        await super().list_snapshots(principal, account_id, cursor=cursor, limit=limit)
        return Page(items=(), next_cursor=None, limit=limit, total=0)


@pytest.mark.unit
async def test_empty_snapshot_history_returns_not_found_without_fabrication() -> None:
    result = await _call_tool(
        _runtime(EmptySnapshotsService()),
        "get_portfolio_snapshot",
        {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
    )

    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "NOT_FOUND"
    assert result.structured_content["data"] is None


class StaleSummaryService(SyntheticPortfolioService):
    async def get_summary(self, principal: Any, account_id: str) -> Any:
        summary = await super().get_summary(principal, account_id)
        stale = replace(
            summary.quality,
            state=ViewQuality.STALE,
            warnings=("Synthetic source observation is stale.",),
        )
        return replace(summary, quality=stale)


@pytest.mark.unit
async def test_stale_quality_is_preserved_not_upgraded() -> None:
    result = await _call_tool(
        _runtime(StaleSummaryService()),
        "get_account_summary",
        {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
    )

    assert result.is_error is False
    assert result.structured_content["data_quality"]["state"] == "stale"
    assert result.structured_content["data_quality"]["warnings"] == [
        "Synthetic source observation is stale."
    ]


class UnavailableService(SyntheticPortfolioService):
    async def get_summary(self, principal: Any, account_id: str) -> Any:
        del principal, account_id
        raise TimeoutError("Bearer top-secret-upstream-detail")


@pytest.mark.unit
async def test_provider_failure_is_stable_and_redacted() -> None:
    result = await _call_tool(
        _runtime(UnavailableService()),
        "get_account_summary",
        {"account_id": SyntheticPortfolioService.ACCOUNT_ID},
    )

    rendered = str(result.model_dump(mode="json"))
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert "top-secret-upstream-detail" not in rendered
    assert "TimeoutError" not in rendered


class PositionSpyService(SyntheticPortfolioService):
    calls = 0

    async def list_positions(
        self,
        principal: Any,
        account_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> Any:
        self.calls += 1
        return await super().list_positions(principal, account_id, cursor=cursor, limit=limit)


@pytest.mark.unit
async def test_unknown_input_and_unknown_tool_fail_before_application_dispatch() -> None:
    service = PositionSpyService()
    server = _runtime(service)

    with pytest.raises(ToolError, match="Extra inputs are not permitted"):
        await server.call_tool(
            "list_positions",
            {
                "account_id": SyntheticPortfolioService.ACCOUNT_ID,
                "limit": 2,
                "provider_path": "/orders",
            },
        )
    with pytest.raises(ToolError, match="Unknown tool"):
        await server.call_tool("generic_http", {"url": "https://example.invalid"})

    assert service.calls == 0
