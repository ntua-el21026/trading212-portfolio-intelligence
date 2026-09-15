"""Closed research tool schemas, current scope, exact response and account pin."""

from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from trading212_api import research_schemas as adapter
from trading212_api_contracts import research as wire
from trading212_application import research as app
from trading212_mcp.auth import PrincipalResolver
from trading212_mcp.research_tools import RESEARCH_TOOL_NAMES
from trading212_mcp.server import create_runtime
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.unit.api.test_research_routes import ACCOUNT, ITEM, item
from tests.unit.domain.research_factories import AT, pin, uid


def backend() -> AsyncMock:
    service = AsyncMock(spec=app.ResearchService)
    service.get_research_item.return_value = item()
    service.get_research_summary.return_value = app.ResearchSummary(
        pin=pin(),
        source_cutoff_at=AT,
        items=(item(),),
        next_cursor=None,
        limit=25,
        total=1,
        unknown_exposure_total=0,
    )
    return service


def runtime(
    monkeypatch: pytest.MonkeyPatch,
    service: AsyncMock | None,
    scopes: frozenset[Scope] = app.RESEARCH_READ_SCOPES,
) -> MCPServer[Any]:
    async def resolve(self: PrincipalResolver) -> Principal:
        return Principal(
            "research-mcp", str(uid(1)), "test", "test", scopes, AT, AT + timedelta(hours=1)
        )

    monkeypatch.setattr(PrincipalResolver, "resolve", resolve)
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        research_service=cast(app.ResearchService, service),
        clock=lambda: AT,
    ).server


def arguments() -> dict[str, Any]:
    return {
        "account_id": str(ACCOUNT),
        "xray_run_id": str(pin().run_id),
        "source_cutoff_at": AT.isoformat(),
    }


async def call(server: MCPServer[Any], name: str, args: dict[str, Any]) -> CallToolResult:
    result = await server.call_tool(name, args)
    assert isinstance(result, CallToolResult) and result.structured_content is not None
    return result


async def test_exact_last_two_contracts_and_rest_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    service = backend()
    server = runtime(monkeypatch, service)
    tools = await server.list_tools()
    assert len(tools) == 38 and tuple(t.name for t in tools[36:]) == RESEARCH_TOOL_NAMES
    for t in tools[36:]:
        assert t.input_schema["additionalProperties"] is False and t.output_schema is not None
        assert t.annotations is not None
        assert t.annotations.model_dump(by_alias=True, exclude_none=True) == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        assert t.meta is not None and t.meta["securitySchemes"] == [
            {"type": "oauth2", "scopes": ["portfolio:read", "analytics:read", "research:read"]}
        ]
    summary = await call(server, "get_research_summary", arguments())
    detail = await call(
        server, "get_research_item", {"account_id": str(ACCOUNT), "item_id": str(ITEM)}
    )
    assert not summary.is_error and not detail.is_error
    assert summary.structured_content["data"] == wire.ResearchSummary.model_validate(
        adapter.research_view(service.get_research_summary.return_value)
    ).model_dump(mode="json")
    assert detail.structured_content["data"] == wire.ResearchItemView.model_validate(
        adapter.research_view(item())
    ).model_dump(mode="json")
    assert service.get_research_item.call_args.kwargs == {"expected_account_id": ACCOUNT}
    assert service.get_research_summary.call_args.args[1] == app.ResearchSummaryQuery(
        account_id=ACCOUNT, xray_run_id=pin().run_id, source_cutoff_at=AT
    )
    assert (
        service.review_research_event.await_count == service.create_research_note.await_count == 0
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"owner_id": "secret-canary"},
        {"url": "https://secret-canary.invalid"},
        {"limit": 1.5},
        {"limit": 101},
        {"entity_id": "not-a-uuid"},
        {"event_kind": "earnings"},
        {"cursor": "secret-canary" * 200},
    ],
)
async def test_unknown_and_malformed_inputs_fail_before_service(
    monkeypatch: pytest.MonkeyPatch, extra: dict[str, Any]
) -> None:
    service = backend()
    server = runtime(monkeypatch, service)
    with pytest.raises(ToolError) as error:
        await server.call_tool("get_research_summary", {**arguments(), **extra})
    assert "secret-canary" not in str(error.value)
    assert service.get_research_summary.await_count == 0


async def test_missing_scope_and_service_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    service = backend()
    server = runtime(monkeypatch, service, frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}))
    result = await call(server, "get_research_summary", arguments())
    assert result.is_error and result.structured_content["error"]["code"] == "ACCESS_DENIED"
    assert service.get_research_summary.await_count == 0
    unavailable = await call(runtime(monkeypatch, None), "get_research_summary", arguments())
    assert unavailable.is_error and unavailable.structured_content["data"] is None


async def test_service_exception_never_reflects_private_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = backend()
    service.get_research_item.side_effect = RuntimeError("secret-canary")
    result = await call(
        runtime(monkeypatch, service),
        "get_research_item",
        {"account_id": str(ACCOUNT), "item_id": str(ITEM)},
    )
    assert result.is_error and "secret-canary" not in result.model_dump_json()


async def test_whole_transport_envelope_bound_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    from trading212_mcp import research_gateway

    monkeypatch.setattr(research_gateway, "MAX_RESEARCH_RESPONSE_BYTES", 100)
    result = await call(runtime(monkeypatch, backend()), "get_research_summary", arguments())
    assert result.is_error and result.structured_content["error"]["code"] == "RESULT_TOO_LARGE"


async def test_returned_foreign_account_is_not_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    service = backend()
    result = await call(
        runtime(monkeypatch, service),
        "get_research_item",
        {"account_id": str(uid(999)), "item_id": str(ITEM)},
    )
    assert result.is_error and result.structured_content["data"] is None
    assert service.get_research_item.call_args.kwargs == {"expected_account_id": uid(999)}


async def test_allocation_result_delta_is_only_authorized_widget_account_metadata() -> None:
    from trading212_application.services import SyntheticPortfolioService
    from trading212_mcp.schemas import DirectAllocationResult

    server = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        clock=lambda: AT,
    ).server
    result = await call(
        server, "get_direct_allocation", {"account_id": SyntheticPortfolioService.ACCOUNT_ID}
    )
    assert not result.is_error
    assert result.meta is not None and set(result.meta) == {"correlationId", "accountId"}
    assert result.meta["accountId"] == SyntheticPortfolioService.ACCOUNT_ID
    payload = DirectAllocationResult.model_validate(result.structured_content)
    assert payload.model_dump(mode="json") == result.structured_content
    assert (
        "account_id" not in result.structured_content
        and "accountId" not in result.structured_content
    )
