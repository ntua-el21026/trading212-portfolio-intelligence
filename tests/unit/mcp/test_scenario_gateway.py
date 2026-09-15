"""Frozen scenario MCP requests, exact public views and safe failure boundaries."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from pydantic import BaseModel
from trading212_application import scenario as app
from trading212_application.views import Page
from trading212_domain.serialization import to_primitive
from trading212_mcp import scenario_gateway
from trading212_mcp.auth import PrincipalResolver
from trading212_mcp.scenario_schemas import (
    ScenarioComparisonToolResult,
    ScenarioCreateToolResult,
    ScenarioListToolResult,
    ScenarioRunToolResult,
)
from trading212_mcp.scenario_tools import SCENARIO_TOOL_NAMES
from trading212_mcp.scenario_widget import SCENARIO_WIDGET_URI
from trading212_mcp.server import create_runtime
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from tests.unit.api.scenario_factories import (
    ACCOUNT,
    NOW,
    RUN,
    SECOND_RUN,
    SNAPSHOT,
    VERSION,
    XRAY,
    comparison,
    definition,
    queued,
    run,
)


def arguments() -> dict[str, Any]:
    value = run().result
    assert value is not None
    return {
        "account_id": str(ACCOUNT),
        "idempotency_key": "scenario:mcp:one",
        "scenario_version_id": str(VERSION),
        "portfolio_snapshot_id": str(SNAPSHOT),
        "xray_run_id": str(XRAY),
        "reporting_currency": "EUR",
        "source_cutoff_at": to_primitive(value.context.pins.source_cutoff_at),
    }


def runtime(service: AsyncMock | None) -> MCPServer[Any]:
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        scenario_service=cast(app.ScenarioService, service),
        clock=lambda: NOW,
    ).server


def service() -> AsyncMock:
    value = AsyncMock(spec=app.ScenarioService)
    value.create_run.return_value = queued()
    value.get_run.return_value = run()
    value.list_definitions.return_value = Page((definition(),), None, 25, 1)
    value.compare.return_value = comparison()
    return value


async def call(server: MCPServer[Any], name: str, args: dict[str, Any]) -> CallToolResult:
    value = await server.call_tool(name, args)
    assert isinstance(value, CallToolResult) and value.structured_content is not None
    return value


async def test_exact_four_names_closed_inputs_outputs_scopes_and_annotations() -> None:
    server = runtime(None)
    names = ("list_scenarios", "create_scenario_run", "get_scenario_result", "compare_scenarios")
    assert names == SCENARIO_TOOL_NAMES
    tools = await server.list_tools()
    assert len(tools) == 38 and tuple(x.name for x in tools[28:32]) == names
    required = (
        {"account_id"},
        set(arguments()),
        {"account_id", "run_id"},
        {"account_id", "run_ids"},
    )
    optional = (
        {"limit", "cursor"},
        {"replay"},
        {"component_limit", "component_cursor"},
        {"component_limit", "component_cursor"},
    )
    models: tuple[type[BaseModel], ...] = (
        ScenarioListToolResult,
        ScenarioCreateToolResult,
        ScenarioRunToolResult,
        ScenarioComparisonToolResult,
    )
    for tool, required_fields, optional_fields, model in zip(
        tools[28:32], required, optional, models, strict=True
    ):
        descriptor = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        schema = descriptor["inputSchema"]
        assert set(schema["required"]) == required_fields
        assert set(schema["properties"]) == required_fields | optional_fields
        assert schema["additionalProperties"] is False
        for item in schema.get("$defs", {}).values():
            if item.get("type") == "object":
                assert item["additionalProperties"] is False
        assert descriptor["annotations"] == {
            "readOnlyHint": tool.name != "create_scenario_run",
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        assert descriptor["_meta"]["securitySchemes"] == [
            {
                "type": "oauth2",
                "scopes": [
                    "portfolio:read",
                    "analytics:read",
                    *(["scenarios:write"] if tool.name == "create_scenario_run" else []),
                ],
            }
        ]
        assert descriptor["outputSchema"] == model.model_json_schema(by_alias=True)
        if tool.name == "list_scenarios":
            assert "ui" not in descriptor["_meta"]
        else:
            assert descriptor["_meta"]["ui"] == {
                "resourceUri": SCENARIO_WIDGET_URI,
                "visibility": ["model", "app"],
            }
            assert descriptor["_meta"]["openai/widgetAccessible"] is True
    resource = next(x for x in await server.list_resources() if str(x.uri) == SCENARIO_WIDGET_URI)
    assert resource.mime_type == "text/html;profile=mcp-app" and resource.meta is not None
    assert resource.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}


async def test_same_rest_views_operational_create_and_explicit_account_pin() -> None:
    backend = service()
    server = runtime(backend)
    created = await call(server, "create_scenario_run", arguments())
    assert not created.is_error and created.structured_content["data"] == to_primitive(queued())
    command = backend.create_run.call_args.args[1]
    assert command.account_id == ACCOUNT and command.scenario_version_id == VERSION
    assert command.reporting_currency.value == "EUR" and command.replay is None
    for name, args, expected in (
        ("list_scenarios", {"account_id": str(ACCOUNT)}, Page((definition(),), None, 25, 1)),
        ("get_scenario_result", {"account_id": str(ACCOUNT), "run_id": str(RUN)}, run()),
        (
            "compare_scenarios",
            {"account_id": str(ACCOUNT), "run_ids": [str(RUN), str(SECOND_RUN)]},
            comparison(),
        ),
    ):
        result = await call(server, name, args)
        assert not result.is_error and result.structured_content["data"] == to_primitive(expected)
        assert result.structured_content["execution_allowed"] is False
        assert result.content and result.content[0].type == "text"
    assert backend.get_run.call_args.kwargs == {"expected_account_id": ACCOUNT}
    assert backend.compare.call_args.args[2].run_ids == (RUN, SECOND_RUN)
    assert backend.cancel_run.await_count == backend.create_definition.await_count == 0


async def test_requested_account_pin_reaches_service_before_cursor() -> None:
    backend = service()
    backend.get_run.side_effect = app.ScenarioServiceError(app.ScenarioErrorCode.NOT_FOUND)
    result = await call(
        runtime(backend),
        "get_scenario_result",
        {
            "account_id": str(SNAPSHOT),
            "run_id": str(RUN),
            "component_cursor": "untrusted-cursor",
        },
    )
    assert result.is_error and result.structured_content["error"]["code"] == "NOT_FOUND"
    assert backend.get_run.call_args.kwargs == {"expected_account_id": SNAPSHOT}
    assert backend.get_run.call_args.args[2].component_cursor == "untrusted-cursor"


async def test_saved_replay_selection_reaches_canonical_command_without_substitution() -> None:
    backend = service()
    value = arguments()
    value["replay"] = {
        "historical_input_snapshot_id": str(SNAPSHOT),
        "start_date": (NOW.date() - timedelta(days=30)).isoformat(),
        "end_date": NOW.date().isoformat(),
        "market_knowledge_cutoff_at": NOW.isoformat(),
        "holdings_basis": "current_holdings",
        "knowledge_basis": "point_in_time",
    }
    result = await call(runtime(backend), "create_scenario_run", value)
    assert not result.is_error
    selected = backend.create_run.call_args.args[1].replay
    assert selected.historical_input_snapshot_id == SNAPSHOT
    assert selected.start_date == NOW.date() - timedelta(days=30)
    assert selected.end_date == NOW.date() and selected.market_knowledge_cutoff_at == NOW
    assert selected.holdings_basis == "current_holdings"
    assert selected.knowledge_basis == "point_in_time"


@pytest.mark.parametrize(
    "missing", [Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.SCENARIOS_WRITE]
)
async def test_missing_command_scope_stops_before_service(
    missing: Scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def principal(_: PrincipalResolver) -> Principal:
        return Principal(
            "scenario-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "test",
            "test",
            frozenset(Scope) - {missing},
            NOW - timedelta(hours=1),
            NOW + timedelta(hours=1),
        )

    monkeypatch.setattr(PrincipalResolver, "resolve", principal)
    backend = service()
    result = await call(runtime(backend), "create_scenario_run", arguments())
    assert result.is_error and result.structured_content["error"]["code"] == "ACCESS_DENIED"
    assert not backend.mock_calls


@pytest.mark.parametrize(
    "change",
    [
        {"owner_id": "private-scenario-canary"},
        {"url": "https://private-scenario-canary"},
        {"prices": [0.1]},
        {"idempotency_key": "null "},
        {"scenario_version_id": 0.1},
        {"reporting_currency": 1},
        {"source_cutoff_at": 0.1},
        {"source_cutoff_at": "2026-08-31"},
        {"replay": "null"},
        {"replay": {"owner_id": "private-scenario-canary"}},
    ],
)
async def test_invalid_create_arguments_reject_before_service_without_echo(
    change: dict[str, Any],
) -> None:
    backend = service()
    with pytest.raises(ToolError) as failure:
        await runtime(backend).call_tool("create_scenario_run", {**arguments(), **change})
    assert "private-scenario-canary" not in str(failure.value)
    assert not backend.mock_calls


@pytest.mark.parametrize(
    "change",
    [
        {"run_ids": [str(RUN)]},
        {"run_ids": [str(RUN)] * 2},
        {"run_ids": [str(RUN)] * 3},
        {"component_limit": 0},
        {"component_limit": 101},
        {"component_limit": "25"},
        {"component_limit": True},
        {"component_cursor": "x" * 2049},
        {"component_cursor": 0.1},
    ],
)
async def test_compare_rejects_malformed_ordered_ids_or_page(change: dict[str, Any]) -> None:
    backend = service()
    with pytest.raises(ToolError):
        await runtime(backend).call_tool(
            "compare_scenarios",
            {
                "account_id": str(ACCOUNT),
                "run_ids": [str(RUN), str(SECOND_RUN)],
                **change,
            },
        )
    assert not backend.mock_calls


@pytest.mark.parametrize("code", list(app.ScenarioErrorCode))
async def test_safe_service_errors_remain_distinct_and_hide_private_causes(
    code: app.ScenarioErrorCode,
) -> None:
    backend = service()
    backend.get_run.side_effect = app.ScenarioServiceError(code, "private-scenario-canary")
    result = await call(
        runtime(backend), "get_scenario_result", {"account_id": str(ACCOUNT), "run_id": str(RUN)}
    )
    assert result.is_error and result.structured_content["error"]["code"] == code.value
    assert result.structured_content["data"] is None
    assert "private-scenario-canary" not in result.model_dump_json()


async def test_malformed_financial_output_and_premature_result_are_never_returned() -> None:
    backend = service()
    value = deepcopy(to_primitive(run()))
    value["result"]["context"]["summary"]["post_value"]["value"]["amount"] = 0.1
    backend.get_run.return_value = value
    result = await call(
        runtime(backend), "get_scenario_result", {"account_id": str(ACCOUNT), "run_id": str(RUN)}
    )
    assert result.is_error and result.structured_content["error"]["code"] == "INTERNAL_ERROR"
    backend.create_run.return_value = run()
    result = await call(runtime(backend), "create_scenario_run", arguments())
    assert result.is_error and result.structured_content["data"] is None


async def test_comparison_cannot_swap_the_requested_before_and_after() -> None:
    backend = service()
    result = await call(
        runtime(backend),
        "compare_scenarios",
        {
            "account_id": str(ACCOUNT),
            "run_ids": [str(SECOND_RUN), str(RUN)],
        },
    )
    assert result.is_error and result.structured_content["error"]["code"] == "INTERNAL_ERROR"


async def test_input_and_complete_multibyte_envelope_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = service()
    server = runtime(backend)
    monkeypatch.setattr(scenario_gateway, "MAX_SCENARIO_INPUT_BYTES", 16)
    result = await call(server, "create_scenario_run", arguments())
    assert (
        result.structured_content["error"]["code"] == "REQUEST_TOO_LARGE" and not backend.mock_calls
    )
    monkeypatch.setattr(scenario_gateway, "MAX_SCENARIO_INPUT_BYTES", 65536)
    monkeypatch.setattr(scenario_gateway, "_correlation_id", lambda _: "stable-fixture")
    backend.list_definitions.return_value = Page(
        (replace(definition(), name="界" * 120),), None, 25, 1
    )
    result = await call(server, "list_scenarios", {"account_id": str(ACCOUNT)})
    assert not result.is_error
    length = len(result.model_dump_json(by_alias=True).encode())
    monkeypatch.setattr(scenario_gateway, "MAX_SCENARIO_OUTPUT_BYTES", length)
    assert not (await call(server, "list_scenarios", {"account_id": str(ACCOUNT)})).is_error
    monkeypatch.setattr(scenario_gateway, "MAX_SCENARIO_OUTPUT_BYTES", length - 1)
    result = await call(server, "list_scenarios", {"account_id": str(ACCOUNT)})
    assert result.is_error and result.structured_content["error"]["code"] == "RESULT_TOO_LARGE"


@pytest.mark.parametrize("length", [120, 121, 128])
async def test_full_trace_identity_uses_bounded_durable_hash(
    length: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    correlation = "c" * length
    monkeypatch.setattr(scenario_gateway, "_correlation_id", lambda _: correlation)
    backend = service()
    result = await call(runtime(backend), "create_scenario_run", arguments())
    assert not result.is_error and result.meta == {"correlationId": correlation}
    expected = (
        correlation if length <= 120 else "sha256:" + sha256(correlation.encode()).hexdigest()
    )
    assert backend.create_run.call_args.args[1].correlation_id == expected
