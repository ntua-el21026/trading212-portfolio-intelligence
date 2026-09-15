"""Exact projection MCP commands, account-bound saved reads and safe failure envelopes."""

import json
from dataclasses import replace
from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from pydantic import BaseModel
from trading212_application import projection as app
from trading212_application import projection_presentation as presentation
from trading212_application import projection_views as views
from trading212_application.views import Page
from trading212_domain.serialization import to_primitive
from trading212_mcp import projection_gateway
from trading212_mcp.auth import PrincipalResolver
from trading212_mcp.projection_schemas import (
    ProjectionCreateToolResult,
    ProjectionGoalToolResult,
    ProjectionListToolResult,
    ProjectionRunToolResult,
)
from trading212_mcp.projection_tools import PROJECTION_TOOL_NAMES
from trading212_mcp.projection_widget import PROJECTION_WIDGET_URI
from trading212_mcp.server import create_runtime
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from tests.unit.api.projection_factories import ACCOUNT, NOW, RUN, goal, queued, run, saved


def arguments() -> dict[str, Any]:
    raw = cast(dict[str, Any], to_primitive(saved().capture.selection))
    raw["initial_basis"] = raw.pop("initial")
    raw["idempotency_key"] = "projection:mcp:one"
    return raw


def backend() -> AsyncMock:
    value = AsyncMock(spec=app.ProjectionService)
    value.create_run.return_value = queued()
    value.get_run.return_value = run()
    value.list_goals.return_value = Page((goal(),), None, 25, 1)
    value.get_goal_analysis.return_value = presentation.project_goal_analysis(saved())
    return value


def runtime(service: AsyncMock | None) -> MCPServer[Any]:
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        projection_service=cast(app.ProjectionService, service),
        clock=lambda: NOW,
    ).server


async def call(server: MCPServer[Any], name: str, args: dict[str, Any]) -> CallToolResult:
    result = await server.call_tool(name, args)
    assert isinstance(result, CallToolResult) and result.structured_content is not None
    return result


def payload(result: CallToolResult) -> dict[str, Any]:
    assert result.structured_content is not None
    return cast(dict[str, Any], result.structured_content)


async def test_exact_four_names_annotations_schemas_and_resource() -> None:
    server = runtime(None)
    tools = await server.list_tools()
    assert len(tools) == 38 and tuple(item.name for item in tools[32:36]) == PROJECTION_TOOL_NAMES
    required = (
        {
            "account_id",
            "idempotency_key",
            "assumption_version_id",
            "initial_basis",
            "schedule",
            "seed",
            "months",
            "paths",
            "retained_months",
            "allocation",
        },
        {"account_id", "run_id"},
        {"account_id"},
        {"account_id", "run_id"},
    )
    optional: tuple[set[str], ...] = (
        {"goal_version_id", "sensitivity"},
        {"point_limit", "point_cursor"},
        {"limit", "cursor"},
        set(),
    )
    models: tuple[type[BaseModel], ...] = (
        ProjectionCreateToolResult,
        ProjectionRunToolResult,
        ProjectionListToolResult,
        ProjectionGoalToolResult,
    )
    for tool, required_fields, optional_fields, model in zip(
        tools[32:36], required, optional, models, strict=True
    ):
        descriptor = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        schema = descriptor["inputSchema"]
        assert set(schema["required"]) == required_fields
        assert set(schema["properties"]) == required_fields | optional_fields
        assert schema["additionalProperties"] is False
        assert all(
            item.get("additionalProperties") is False
            for item in schema.get("$defs", {}).values()
            if item.get("type") == "object"
        )
        assert descriptor["outputSchema"] == model.model_json_schema(by_alias=True)
        assert descriptor["annotations"] == {
            "readOnlyHint": tool.name != "create_projection_run",
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
                    *(["projections:write"] if tool.name == "create_projection_run" else []),
                ],
            }
        ]
        if tool.name == "list_goals":
            assert "ui" not in descriptor["_meta"]
        else:
            assert descriptor["_meta"]["ui"] == {
                "resourceUri": PROJECTION_WIDGET_URI,
                "visibility": ["model", "app"],
            }
            assert descriptor["_meta"]["openai/outputTemplate"] == PROJECTION_WIDGET_URI
            assert descriptor["_meta"]["openai/widgetAccessible"] is True
    resources = await server.list_resources()
    assert len(resources) == 11
    resource = next(item for item in resources if str(item.uri) == PROJECTION_WIDGET_URI)
    assert resource.mime_type == "text/html;profile=mcp-app" and resource.meta is not None
    assert resource.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}


async def test_same_rest_values_and_exact_application_selection_without_new_finance() -> None:
    service = backend()
    server = runtime(service)
    created = await call(server, "create_projection_run", arguments())
    assert not created.is_error and payload(created)["data"] == to_primitive(queued())
    assert service.create_run.call_args.args[1].selection == saved().capture.selection
    assert service.create_run.call_args.args[1].idempotency_key == "projection:mcp:one"
    for name, args, expected in (
        ("get_projection", {"account_id": str(ACCOUNT), "run_id": str(RUN)}, run()),
        ("list_goals", {"account_id": str(ACCOUNT)}, Page((goal(),), None, 25, 1)),
        (
            "get_goal_analysis",
            {"account_id": str(ACCOUNT), "run_id": str(RUN)},
            presentation.project_goal_analysis(saved()),
        ),
    ):
        result = await call(server, name, args)
        assert not result.is_error and payload(result)["data"] == to_primitive(expected)
        assert payload(result)["execution_allowed"] is False
    assert service.get_run.call_args.kwargs == {"expected_account_id": ACCOUNT}
    assert service.get_goal_analysis.call_args.kwargs == {"expected_account_id": ACCOUNT}
    assert (
        service.cancel_run.await_count
        == service.create_goal.await_count
        == service.create_assumption_set.await_count
        == 0
    )


async def test_account_pin_precedes_private_cursor_and_goal_reads() -> None:
    service = backend()
    foreign = UUID(int=999)
    for name, method, extra in (
        ("get_projection", "get_run", {"point_cursor": "untrusted_cursor", "point_limit": 100}),
        ("get_goal_analysis", "get_goal_analysis", {}),
    ):
        getattr(service, method).side_effect = app.ProjectionServiceError(
            app.ProjectionErrorCode.NOT_FOUND
        )
        result = await call(
            runtime(service), name, {"account_id": str(foreign), "run_id": str(RUN), **extra}
        )
        assert result.is_error and payload(result)["error"]["code"] == "NOT_FOUND"
        assert getattr(service, method).call_args.kwargs == {"expected_account_id": foreign}
    assert service.get_run.call_args.args[2] == app.ProjectionPointPageQuery(
        point_limit=100, point_cursor="untrusted_cursor"
    )


@pytest.mark.parametrize(
    "missing", [Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.PROJECTIONS_WRITE]
)
async def test_command_scopes_fail_before_service(
    missing: Scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolve(_: PrincipalResolver) -> Principal:
        return Principal(
            "projection-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "trusted-issuer",
            "subject",
            frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.PROJECTIONS_WRITE})
            - {missing},
            NOW,
            NOW + timedelta(hours=1),
        )

    monkeypatch.setattr(PrincipalResolver, "resolve", resolve)
    service = backend()
    result = await call(runtime(service), "create_projection_run", arguments())
    assert result.is_error and payload(result)["error"]["code"] == "ACCESS_DENIED"
    assert not service.mock_calls


async def test_token_expiry_after_service_call_clears_financial_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [NOW]

    async def resolve(_: PrincipalResolver) -> Principal:
        return Principal(
            "projection-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "trusted-issuer",
            "subject",
            frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}),
            NOW,
            NOW + timedelta(seconds=1),
        )

    async def read(*args: Any, **kwargs: Any) -> object:
        clock[0] = NOW + timedelta(seconds=2)
        return run()

    monkeypatch.setattr(PrincipalResolver, "resolve", resolve)
    service = backend()
    service.get_run.side_effect = read
    server = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        projection_service=cast(app.ProjectionService, service),
        clock=lambda: clock[0],
    ).server
    result = await call(server, "get_projection", {"account_id": str(ACCOUNT), "run_id": str(RUN)})
    assert result.is_error and payload(result)["data"] is None


@pytest.mark.parametrize(
    "name,changes",
    [
        ("create_projection_run", {"owner_id": "private-canary"}),
        ("create_projection_run", {"seed": True}),
        ("create_projection_run", {"paths": "7"}),
        ("create_projection_run", {"months": 601}),
        ("create_projection_run", {"retained_months": [0, 0, 3]}),
        ("create_projection_run", {"idempotency_key": ""}),
        ("get_projection", {"point_limit": "25"}),
        ("get_projection", {"point_limit": 101}),
        ("get_projection", {"point_cursor": "x" * 2049}),
        ("get_goal_analysis", {"point_limit": 25}),
        ("list_goals", {"limit": True}),
    ],
)
async def test_literal_bounded_arguments_reject_before_service(
    name: str, changes: dict[str, Any]
) -> None:
    service = backend()
    args = (
        arguments()
        if name == "create_projection_run"
        else {"account_id": str(ACCOUNT), **({} if name == "list_goals" else {"run_id": str(RUN)})}
    )
    with pytest.raises(ToolError) as caught:
        await runtime(service).call_tool(name, {**args, **changes})
    assert "private-canary" not in str(caught.value) and not service.mock_calls


async def test_observed_value_injection_rejects_and_exact_modeled_dates_survive() -> None:
    service = backend()
    server = runtime(service)
    args = arguments()
    args["initial_basis"]["modeled_value"] = {"amount": "999", "currency": "EUR"}
    with pytest.raises(ToolError):
        await server.call_tool("create_projection_run", args)
    assert not service.mock_calls
    args["initial_basis"] = {
        "kind": "modeled_value",
        "modeled_value": {"amount": "123.123456789012345678", "currency": "EUR"},
        "modeled_anchor_date": "2025-01-31",
    }
    result = await call(server, "create_projection_run", args)
    assert not result.is_error
    initial = service.create_run.call_args.args[1].selection.initial
    assert (
        initial.modeled_value is not None
        and str(initial.modeled_value.amount) == "123.123456789012345678"
    )
    assert (
        initial.modeled_anchor_date is not None
        and initial.modeled_anchor_date.isoformat() == "2025-01-31"
    )


async def test_every_read_rechecks_source_authority_and_sanitizes_canaries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = backend()
    server = runtime(service)
    args = {"account_id": str(ACCOUNT), "run_id": str(RUN)}
    first = await call(server, "get_projection", args)
    assert not first.is_error
    service.get_run.side_effect = app.ProjectionServiceError(
        app.ProjectionErrorCode.SOURCE_UNAVAILABLE, "private-license-canary"
    )
    denied = await call(server, "get_projection", args)
    assert denied.is_error and payload(denied)["data"] is None
    assert payload(denied)["error"]["code"] == "SOURCE_UNAVAILABLE"
    assert "canary" not in denied.model_dump_json() and "canary" not in caplog.text
    assert service.get_run.await_count == 2


@pytest.mark.parametrize(
    "failure", [AuthenticationError("private-token-canary"), RuntimeError("private-db-canary")]
)
async def test_raw_failures_never_return_private_exception_text(failure: Exception) -> None:
    service = backend()
    service.get_goal_analysis.side_effect = failure
    result = await call(
        runtime(service), "get_goal_analysis", {"account_id": str(ACCOUNT), "run_id": str(RUN)}
    )
    assert result.is_error and "canary" not in result.model_dump_json()


async def test_response_account_run_page_and_create_version_mismatches_fail_closed() -> None:
    cases: list[tuple[str, str, object, dict[str, Any]]] = [
        (
            "get_projection",
            "get_run",
            replace(run(), account_id=UUID(int=900)),
            {"account_id": str(ACCOUNT), "run_id": str(RUN)},
        ),
        (
            "get_projection",
            "get_run",
            run(limit=1),
            {"account_id": str(ACCOUNT), "run_id": str(RUN), "point_limit": 25},
        ),
        (
            "create_projection_run",
            "create_run",
            replace(queued(), assumption_version_id=UUID(int=901)),
            arguments(),
        ),
        (
            "get_goal_analysis",
            "get_goal_analysis",
            replace(presentation.project_goal_analysis(saved()), run_id=UUID(int=902)),
            {"account_id": str(ACCOUNT), "run_id": str(RUN)},
        ),
    ]
    for name, method, wrong, args in cases:
        service = backend()
        getattr(service, method).return_value = wrong
        result = await call(runtime(service), name, args)
        assert result.is_error and payload(result)["data"] is None


async def test_operational_create_has_no_finance_and_no_goal_is_explicit() -> None:
    service = backend()
    service.create_run.return_value = run()
    result = await call(runtime(service), "create_projection_run", arguments())
    assert result.is_error and payload(result)["data"] is None
    service = backend()
    service.get_goal_analysis.return_value = presentation.unavailable_goal_analysis(
        replace(queued(), goal_version_id=None)
    )
    result = await call(
        runtime(service), "get_goal_analysis", {"account_id": str(ACCOUNT), "run_id": str(RUN)}
    )
    assert not result.is_error and payload(result)["data"]["reason"] == "no_goal_pinned"
    assert payload(result)["data"]["context"] is None


async def test_final_full_mcp_envelope_includes_text_metadata_and_utf8_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = backend()
    server = runtime(service)
    args = {"account_id": str(ACCOUNT), "run_id": str(RUN)}
    first = await call(server, "get_projection", args)
    assert not first.is_error
    size = len(first.model_dump_json(by_alias=True).encode("utf-8"))
    structured = len(
        json.dumps(first.structured_content, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    assert size > structured
    monkeypatch.setattr(views, "PROJECTION_PUBLIC_RESPONSE_BYTES", size - 1)
    denied = await call(server, "get_projection", args)
    assert denied.is_error and payload(denied)["error"]["code"] == "RESULT_TOO_LARGE"
    assert payload(denied)["data"] is None


async def test_missing_service_is_honest_and_bounded_input_never_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await call(
        runtime(None), "get_projection", {"account_id": str(ACCOUNT), "run_id": str(RUN)}
    )
    assert result.is_error and payload(result)["error"]["code"] == "PROJECTION_UNAVAILABLE"
    service = backend()
    monkeypatch.setattr(projection_gateway, "MAX_PROJECTION_INPUT_BYTES", 1)
    result = await call(runtime(service), "create_projection_run", arguments())
    assert result.is_error and payload(result)["error"]["code"] == "REQUEST_TOO_LARGE"
    assert not service.mock_calls
