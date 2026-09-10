"""Report MCP descriptors, exact command parity and rejection without secret reflection."""

import copy
from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from trading212_application import reports as app
from trading212_application.views import Page
from trading212_mcp.auth import PrincipalResolver
from trading212_mcp.report_tools import REPORT_TOOL_NAMES
from trading212_mcp.report_widget import REPORT_WIDGET_URI
from trading212_mcp.server import create_runtime
from trading212_security.principals import Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import LOCAL_SYNTHETIC_OWNER_ID

from tests.unit.api.report_factories import ACCOUNT, BODY, JOB, NOW, job

ARGS = {
    **{key: value for key, value in BODY.items() if key != "formats"},
    "format": "json",
    "idempotency_key": "report:mcp:one",
}


def runtime(service: AsyncMock) -> MCPServer[Any]:
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        report_service=cast(app.ReportService, service),
        clock=lambda: NOW,
    ).server


async def call(server: MCPServer[Any], name: str, args: dict[str, Any]) -> CallToolResult:
    value = await server.call_tool(name, args)
    assert isinstance(value, CallToolResult) and value.structured_content is not None
    return value


async def test_three_descriptors_have_exact_closed_fields_scopes_and_private_widget() -> None:
    service = AsyncMock(spec=app.ReportService)
    server = runtime(service)
    tools = {
        tool.name: tool for tool in await server.list_tools() if tool.name in REPORT_TOOL_NAMES
    }
    assert set(tools) == set(REPORT_TOOL_NAMES)
    command = tools["generate_portfolio_report"].model_dump(by_alias=True)
    assert set(command["inputSchema"]["required"]) == {
        "account_id",
        "idempotency_key",
        "start_date",
        "end_date",
        "source_cutoff_at",
        "snapshot_id",
        "reporting_currency",
        "report_type",
        "format",
        "sections",
    }
    assert set(command["inputSchema"]["properties"]) - set(command["inputSchema"]["required"]) == {
        "target_version_id",
        "plan_revision_id",
        "benchmark_version_id",
        "constituent_snapshot_id",
    }
    assert command["inputSchema"]["additionalProperties"] is False
    assert set(command["_meta"]["securitySchemes"][0]["scopes"]) == {
        "portfolio:read",
        "analytics:read",
        "reports:write",
        "activity:read",
        "targets:read",
    }
    assert command["annotations"]["readOnlyHint"] is False
    assert command["_meta"]["ui"]["resourceUri"] == REPORT_WIDGET_URI
    for name in ("get_report_status", "list_reports"):
        descriptor = tools[name].model_dump(by_alias=True)
        assert set(descriptor["_meta"]["securitySchemes"][0]["scopes"]) == {
            "portfolio:read",
            "reports:read",
        }
        assert descriptor["annotations"]["readOnlyHint"] is True


async def test_create_status_list_share_exact_job_without_grants_or_an_invented_result() -> None:
    service = AsyncMock(spec=app.ReportService)
    service.generate_report.return_value = job()
    service.get_report_status.return_value = job()
    service.list_reports.return_value = Page((job(),), None, 25, 1)
    server = runtime(service)
    generated = await call(server, "generate_portfolio_report", ARGS)
    status = await call(server, "get_report_status", {"account_id": ACCOUNT, "report_job_id": JOB})
    listed = await call(server, "list_reports", {"account_id": ACCOUNT})
    assert not generated.is_error and not status.is_error and not listed.is_error
    assert generated.structured_content["data"] == status.structured_content["data"]
    assert listed.structured_content["data"]["items"] == [status.structured_content["data"]]
    data = generated.structured_content["data"]
    assert data["state"] == "queued" and data["manifest_digest"] is None and data["artifacts"] == []
    assert data["context"]["input_digest"] == "a" * 64
    assert service.generate_report.call_args.args[1].ttl_days == 7
    service.create_report_download_grant.assert_not_awaited()
    service.download_report_artifact.assert_not_awaited()


@pytest.mark.parametrize(
    "key", ["formats", "ttl_days", "template_version", "xray_run_id", "destination"]
)
async def test_forbidden_command_extension_rejected_before_service_without_echo(key: str) -> None:
    service = AsyncMock(spec=app.ReportService)
    args = copy.deepcopy(ARGS)
    args[key] = "private-report-canary"
    with pytest.raises(ToolError) as failure:
        await runtime(service).call_tool("generate_portfolio_report", args)
    assert "private-report-canary" not in str(failure.value)
    service.generate_report.assert_not_awaited()


async def test_wrong_account_result_and_raw_failure_cannot_escape_gateway() -> None:
    service = AsyncMock(spec=app.ReportService)
    service.get_report_status.return_value = {
        "account_id": "wrong",
        "token": "private-report-canary",
    }
    denied = await call(
        runtime(service), "get_report_status", {"account_id": ACCOUNT, "report_job_id": JOB}
    )
    assert denied.is_error and denied.structured_content["error"]["code"] == "INTERNAL_ERROR"
    assert "private-report-canary" not in denied.model_dump_json()
    service.get_report_status.side_effect = app.ReportServiceError(
        app.ReportServiceErrorCode.ACCESS_DENIED, "private-report-canary"
    )
    denied = await call(
        runtime(service), "get_report_status", {"account_id": ACCOUNT, "report_job_id": JOB}
    )
    assert denied.structured_content["error"]["code"] == "ACCESS_DENIED"
    assert "private-report-canary" not in denied.model_dump_json()


@pytest.mark.parametrize(
    ("name", "missing"),
    [
        ("generate_portfolio_report", Scope.PORTFOLIO_READ),
        ("generate_portfolio_report", Scope.ANALYTICS_READ),
        ("generate_portfolio_report", Scope.REPORTS_WRITE),
        ("generate_portfolio_report", Scope.ACTIVITY_READ),
        ("generate_portfolio_report", Scope.TARGETS_READ),
        ("get_report_status", Scope.REPORTS_READ),
        ("list_reports", Scope.PORTFOLIO_READ),
    ],
)
async def test_missing_scope_denied_before_service(
    name: str,
    missing: Scope,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def principal(_: PrincipalResolver) -> Principal:
        return Principal(
            "report-test",
            LOCAL_SYNTHETIC_OWNER_ID,
            "test",
            "test",
            frozenset(Scope) - {missing},
            NOW - timedelta(hours=1),
            NOW + timedelta(hours=1),
        )

    monkeypatch.setattr(PrincipalResolver, "resolve", principal)
    args = ARGS if name == "generate_portfolio_report" else {"account_id": ACCOUNT}
    if name == "get_report_status":
        args = {**args, "report_job_id": JOB}
    service = AsyncMock(spec=app.ReportService)
    result = await call(runtime(service), name, args)
    assert result.is_error and result.structured_content["error"]["code"] == "ACCESS_DENIED"
    assert not service.mock_calls


@pytest.mark.parametrize(
    ("error_code", "wire_code", "retryable"),
    [
        (app.ReportServiceErrorCode.CONFLICT, "IDEMPOTENCY_KEY_REUSED", False),
        (app.ReportServiceErrorCode.INVALID_STATE_TRANSITION, "INVALID_STATE_TRANSITION", False),
        (app.ReportServiceErrorCode.RATE_LIMITED, "RATE_LIMITED", True),
    ],
)
async def test_lifecycle_rate_and_idempotency_errors_remain_distinct_without_private_causes(
    error_code: app.ReportServiceErrorCode,
    wire_code: str,
    retryable: bool,
) -> None:
    service = AsyncMock(spec=app.ReportService)
    service.generate_report.side_effect = app.ReportServiceError(
        error_code, "private-report-state-canary", retryable=retryable
    )
    result = await call(runtime(service), "generate_portfolio_report", ARGS)
    assert result.is_error and result.structured_content is not None
    error = result.structured_content["error"]
    assert error["code"] == wire_code and error["retryable"] is retryable
    assert result.structured_content["data"] is None
    assert "private-report-state-canary" not in result.model_dump_json()
    if wire_code != "IDEMPOTENCY_KEY_REUSED":
        assert "idempotency" not in error["message"]
        assert "idempotency" not in error["remediation"]
