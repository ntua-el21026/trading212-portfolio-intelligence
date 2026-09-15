"""Risk MCP parity, exact closed registry and private failure boundaries."""

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
from trading212_application import risk as app
from trading212_domain.serialization import to_primitive
from trading212_mcp import risk_gateway
from trading212_mcp.auth import PrincipalResolver
from trading212_mcp.risk_schemas import RiskMatrixToolResult, RiskRunToolResult
from trading212_mcp.risk_tools import RISK_TOOL_NAMES
from trading212_mcp.risk_widget import RISK_WIDGET_URI
from trading212_mcp.server import create_runtime
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from tests.unit.api.risk_factories import NOW, RUN, SNAPSHOT, VERSION, matrix, queued, run

ACCOUNT = run().account_id


def arguments() -> dict[str, Any]:
    result = run().result
    assert result is not None
    return {
        "account_id": str(ACCOUNT),
        "idempotency_key": "risk:mcp:one",
        "definition_version_id": str(VERSION),
        "portfolio_snapshot_id": str(SNAPSHOT),
        "historical_input_snapshot_id": str(SNAPSHOT),
        "window": to_primitive(result.historical_context.window),
    }


def runtime(service: AsyncMock | None) -> MCPServer[Any]:
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        risk_service=cast(app.RiskService, service),
        clock=lambda: NOW,
    ).server


def service() -> AsyncMock:
    result = AsyncMock(spec=app.RiskService)
    result.create_run.return_value = queued()
    result.get_run.return_value = run()
    result.get_matrix.return_value = matrix()
    return result


async def call(server: MCPServer[Any], name: str, args: dict[str, Any]) -> CallToolResult:
    value = await server.call_tool(name, args)
    assert isinstance(value, CallToolResult) and value.structured_content is not None
    return value


async def test_independent_three_names_nested_closed_fields_and_annotations() -> None:
    server = runtime(None)
    names = ("create_risk_run", "get_risk_summary", "get_risk_matrix")
    assert names == RISK_TOOL_NAMES
    tools = {t.name: t for t in await server.list_tools() if t.name in names}
    assert tuple(tools) == names
    for name, tool in tools.items():
        descriptor = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        schema = descriptor["inputSchema"]
        expected = {"account_id", "run_id"} if name != "create_risk_run" else set(arguments())
        assert set(schema["required"]) == expected
        assert set(schema["properties"]) == expected | (
            {"assets", "benchmark_version_id", "xray_run_id"}
            if name == "create_risk_run"
            else set()
        )
        assert schema["additionalProperties"] is False
        for definition in schema.get("$defs", {}).values():
            if definition.get("type") == "object":
                assert definition["additionalProperties"] is False
        assert descriptor["annotations"] == {
            "readOnlyHint": name != "create_risk_run",
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
                    *(["risk:write"] if name == "create_risk_run" else []),
                ],
            }
        ]
        assert descriptor["_meta"]["ui"] == {
            "resourceUri": RISK_WIDGET_URI,
            "visibility": ["model", "app"],
        }
        assert descriptor["_meta"]["openai/widgetAccessible"] is True
        model = RiskMatrixToolResult if name == "get_risk_matrix" else RiskRunToolResult
        assert descriptor["outputSchema"] == model.model_json_schema(by_alias=True)
    resources = await server.list_resources()
    assert len(resources) == 6
    resource = next(x for x in resources if str(x.uri) == RISK_WIDGET_URI)
    assert resource.mime_type == "text/html;profile=mcp-app"
    assert resource.meta is not None
    assert resource.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}


async def test_exact_canonical_views_preserve_unavailable_values_and_request_pins() -> None:
    backend = service()
    server = runtime(backend)
    create = await call(server, "create_risk_run", arguments())
    assert not create.is_error and create.structured_content["data"] == to_primitive(queued())
    command = backend.create_run.call_args.args[1]
    assert command.account_id == ACCOUNT and command.assets == ()
    assert to_primitive(command.window) == arguments()["window"]
    assert command.idempotency_key == arguments()["idempotency_key"]
    for name, expected in (("get_risk_summary", run()), ("get_risk_matrix", matrix())):
        value = await call(server, name, {"account_id": str(ACCOUNT), "run_id": str(RUN)})
        assert not value.is_error and value.structured_content["data"] == to_primitive(expected)
        assert value.structured_content["execution_allowed"] is False
    assert backend.create_definition.await_count == backend.cancel_run.await_count == 0


@pytest.mark.parametrize("missing", [Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.RISK_WRITE])
async def test_missing_command_scope_stops_before_service(
    missing: Scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def principal(_: PrincipalResolver) -> Principal:
        return Principal(
            "risk-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "test",
            "test",
            frozenset(Scope) - {missing},
            NOW - timedelta(hours=1),
            NOW + timedelta(hours=1),
        )

    monkeypatch.setattr(PrincipalResolver, "resolve", principal)
    backend = service()
    result = await call(runtime(backend), "create_risk_run", arguments())
    assert result.is_error and result.structured_content["error"]["code"] == "ACCESS_DENIED"
    assert not backend.mock_calls


@pytest.mark.parametrize(
    "change",
    [
        {"owner_id": "private-risk-canary"},
        {"returns": ["0.1"]},
        {"url": "https://private-risk-canary"},
        {"idempotency_key": "null "},
        {"benchmark_version_id": "null"},
        {"definition_version_id": 12},
        {"assets": None},
        {"assets": [{"instrument_id": str(VERSION), "series_id": str(SNAPSHOT)}] * 2},
        {"assets": [{"instrument_id": str(VERSION), "series_id": str(SNAPSHOT)}] * 33},
        {
            "assets": [
                {
                    "instrument_id": str(VERSION),
                    "series_id": str(SNAPSHOT),
                    "secret": "private-risk-canary",
                }
            ]
        },
    ],
)
async def test_unsafe_arguments_rejected_before_service_without_echo(
    change: dict[str, Any],
) -> None:
    backend = service()
    with pytest.raises(ToolError) as failure:
        await runtime(backend).call_tool("create_risk_run", {**arguments(), **change})
    assert "private-risk-canary" not in str(failure.value)
    assert not backend.mock_calls


@pytest.mark.parametrize(
    "change",
    [
        {"start_date": 20250101},
        {"source_cutoff_at": 0.1},
        {"source_cutoff_at": "2026-09-14"},
        {"reporting_currency": "eur"},
        {"returns": [0.1]},
        {"knowledge_policy": "future"},
        {"start_date": "2025-02-30"},
        {"start_date": "2000-01-01"},
    ],
)
async def test_window_schema_is_strict_and_bounded(change: dict[str, Any]) -> None:
    backend = service()
    args = arguments()
    args["window"] = {**args["window"], **change}
    with pytest.raises(ToolError):
        await runtime(backend).call_tool("create_risk_run", args)
    assert not backend.mock_calls


@pytest.mark.parametrize("code", list(app.RiskErrorCode))
async def test_canonical_service_failures_remain_distinct_and_hide_causes(
    code: app.RiskErrorCode,
) -> None:
    backend = service()
    backend.get_run.side_effect = app.RiskServiceError(code, "private-risk-canary")
    result = await call(
        runtime(backend), "get_risk_summary", {"account_id": str(ACCOUNT), "run_id": str(RUN)}
    )
    assert result.is_error and result.structured_content["error"]["code"] == code.value
    assert result.structured_content["data"] is None
    assert "private-risk-canary" not in result.model_dump_json()


async def test_unavailable_service_wrong_account_and_malformed_output_are_safe() -> None:
    args = {"account_id": str(ACCOUNT), "run_id": str(RUN)}
    result = await call(runtime(None), "get_risk_summary", args)
    assert result.structured_content["error"]["code"] == "RISK_UNAVAILABLE"
    backend = service()
    backend.get_run.return_value = replace(run(), account_id=SNAPSHOT)
    result = await call(runtime(backend), "get_risk_summary", args)
    assert result.structured_content["error"]["code"] == "NOT_FOUND"
    data = deepcopy(to_primitive(run()))
    data["result"]["observed"]["volatility_annualized"]["value"] = 0.1
    backend.get_run.return_value = data
    result = await call(runtime(backend), "get_risk_summary", args)
    assert result.structured_content["error"]["code"] == "INTERNAL_ERROR"
    backend.get_run.side_effect = RuntimeError("private-risk-canary")
    result = await call(runtime(backend), "get_risk_summary", args)
    assert "private-risk-canary" not in result.model_dump_json()


async def test_request_and_envelope_byte_budgets_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = service()
    server = runtime(backend)
    monkeypatch.setattr(risk_gateway, "MAX_RISK_INPUT_BYTES", 16)
    value = await call(server, "create_risk_run", arguments())
    assert value.structured_content["error"]["code"] == "REQUEST_TOO_LARGE"
    assert not backend.mock_calls
    monkeypatch.setattr(risk_gateway, "MAX_RISK_INPUT_BYTES", 65536)
    monkeypatch.setattr(risk_gateway, "MAX_RISK_OUTPUT_BYTES", 16)
    value = await call(server, "get_risk_summary", {"account_id": str(ACCOUNT), "run_id": str(RUN)})
    assert value.structured_content["error"]["code"] == "RESULT_TOO_LARGE"
    assert value.structured_content["data"] is None


@pytest.mark.parametrize("length", [120, 121, 128])
async def test_transport_correlation_is_preserved_with_bounded_audit_reference(
    length: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    correlation = "c" * length
    monkeypatch.setattr(risk_gateway, "_correlation_id", lambda _: correlation)
    backend = service()
    value = await call(runtime(backend), "create_risk_run", arguments())
    assert not value.is_error and value.meta == {"correlationId": correlation}
    expected = (
        correlation if length <= 120 else "sha256:" + sha256(correlation.encode()).hexdigest()
    )
    assert backend.create_run.call_args.args[1].correlation_id == expected
    assert len(expected) <= 120
