"""Real report and alert MCP adapters preserve two-owner authorization and durable grants."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

import pytest
from mcp.types import CallToolResult
from starlette.testclient import TestClient
from trading212_api_contracts import alerts as aw
from trading212_api_contracts import reports as rw
from trading212_mcp.server import create_runtime
from trading212_mcp.settings import McpSettings
from trading212_security.principals import Scope

from tests.integration.phase2_authorization_cases import (
    ALERT_STATE,
    REPORT_STATE,
    SETTINGS,
    Actor,
    AlertResources,
    GridBearer,
    OwnerGrid,
    ReportResources,
    retained_state,
    without_grant,
)
from tests.integration.phase2_authorization_cases import alert_resources as alert_resources
from tests.integration.phase2_authorization_cases import owner_grid as owner_grid
from tests.integration.phase2_authorization_cases import report_resources as report_resources
from tests.integration.test_alert_postgres import alert_database as alert_database

pytestmark = pytest.mark.integration


class Tool(StrEnum):
    REPORT_STATUS = "get_report_status"
    REPORT_LIST = "list_reports"
    REPORT_CREATE = "generate_portfolio_report"
    ALERT_SUMMARY = "get_alert_summary"


def arguments(
    grid: OwnerGrid,
    tool: Tool,
    resource: ReportResources,
    *,
    account: UUID | None = None,
) -> dict[str, object]:
    account_id = str(account or resource.pin.account_id)
    if tool is Tool.REPORT_STATUS:
        return {"account_id": account_id, "report_job_id": str(resource.report.job_id)}
    if tool is Tool.REPORT_LIST:
        return {"account_id": account_id, "limit": 100}
    if tool is Tool.ALERT_SUMMARY:
        return {
            "account_id": account_id,
            "start_date": grid.at.date().isoformat(),
            "end_date": grid.at.date().isoformat(),
            # Event publication is observed now; scheduled/financial dates stay pinned.
            "source_cutoff_at": grid.operational_clock().isoformat(),
            "state": "all",
            "limit": 100,
        }
    assert tool is Tool.REPORT_CREATE
    return {
        "account_id": account_id,
        "snapshot_id": str(resource.pin.snapshot_id),
        "start_date": grid.at.date().isoformat(),
        "end_date": grid.at.date().isoformat(),
        "source_cutoff_at": grid.at.isoformat(),
        "reporting_currency": "EUR",
        "report_type": "portfolio_summary",
        "format": "json",
        "sections": ["overview", "allocation", "quality"],
        "idempotency_key": uuid4().hex,
    }


def call(client: TestClient, actor: Actor, tool: Tool, args: dict[str, object]) -> CallToolResult:
    response = client.post(
        "/mcp",
        headers={
            "Authorization": "Bearer " + actor.token,
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool.value, "arguments": args},
        },
    )
    assert response.status_code == 200
    result = CallToolResult.model_validate(response.json()["result"])
    assert result.structured_content is not None
    return result


def data(result: CallToolResult) -> object:
    assert not result.is_error and result.structured_content is not None
    assert result.structured_content["error"] is None
    value: object = result.structured_content["data"]
    return value


def assert_denied(
    result: CallToolResult,
    code: Literal["ACCESS_DENIED", "NOT_FOUND"],
    private: tuple[str, ...],
) -> None:
    assert result.is_error and result.structured_content is not None
    assert result.structured_content["data"] is None
    assert result.structured_content["error"]["code"] == code
    rendered = result.model_dump_json()
    assert all(value not in rendered for value in private)
    assert "p210-owner-" not in rendered


def assert_owned(
    result: CallToolResult,
    tool: Tool,
    report: ReportResources,
    alert: AlertResources,
) -> None:
    account = str(report.pin.account_id)
    if tool is Tool.REPORT_STATUS or tool is Tool.REPORT_CREATE:
        value = rw.ReportJobStatus.model_validate(data(result))
        assert value.account_id == account and value.context is not None
        if tool is Tool.REPORT_STATUS:
            assert value.job_id == str(report.report.job_id) and value.state == "succeeded"
        else:
            assert value.state == "queued"
    elif tool is Tool.REPORT_LIST:
        page = rw.ReportPage.model_validate(data(result))
        assert page.total == len(page.items) and page.next_cursor is None
        assert str(report.report.job_id) in {item.job_id for item in page.items}
        assert all(item.account_id == account for item in page.items)
    else:
        summary = aw.AlertSummaryPage.model_validate(data(result))
        assert summary.account_id == account
        assert summary.page.total == len(summary.page.items) and summary.page.next_cursor is None
        assert str(alert.event.id) in {item.id for item in summary.page.items}
        assert all(item.account_id == account for item in summary.page.items)


@pytest.mark.parametrize("tool", tuple(Tool), ids=lambda tool: tool.value)
def test_report_alert_mcp_transport_uses_real_two_owner_resources_and_current_grants(
    owner_grid: OwnerGrid,
    report_resources: dict[UUID, ReportResources],
    alert_resources: dict[UUID, AlertResources],
    tool: Tool,
) -> None:
    grid = owner_grid
    runtime = create_runtime(
        security_settings=SETTINGS.model_copy(update={"issuer": "https://issuer.example"}),
        mcp_settings=McpSettings.model_validate({"public_base_url": "https://portfolio.example"}),
        service=grid.portfolio,
        report_service=grid.reports,
        alert_service=grid.alerts,
        bearer_authenticator=GridBearer(grid.actors),
        clock=lambda: grid.at,
    )
    tables = ALERT_STATE if tool is Tool.ALERT_SUMMARY else REPORT_STATE
    with TestClient(runtime.asgi_app(), base_url="http://localhost") as client:
        for index, actor in enumerate(grid.actors):
            other = grid.actors[1 - index]
            own = report_resources[actor.accounts[0].account_id]
            own_alert = alert_resources[own.pin.account_id]
            foreign = report_resources[other.accounts[0].account_id]
            second = report_resources[actor.accounts[1].account_id]
            args = arguments(grid, tool, own)
            positive = call(client, actor, tool, args)
            assert_owned(positive, tool, own, own_alert)
            if tool is Tool.REPORT_CREATE:
                before = retained_state(grid, tables)
                replay = call(client, actor, tool, args)
                assert data(replay) == data(positive)
                assert retained_state(grid, tables) == before
            private = (*own.private_values, *own_alert.private_values)
            before = retained_state(grid, tables)
            assert_denied(call(client, other, tool, args), "ACCESS_DENIED", private)
            assert retained_state(grid, tables) == before

            if tool in {Tool.REPORT_STATUS, Tool.REPORT_CREATE}:
                for referenced, account in (
                    (foreign, own.pin.account_id),
                    (own, second.pin.account_id),
                ):
                    mismatch = arguments(grid, tool, referenced, account=account)
                    before = retained_state(grid, tables)
                    assert_denied(
                        call(client, actor, tool, mismatch), "NOT_FOUND", referenced.private_values
                    )
                    assert retained_state(grid, tables) == before
            else:
                isolated = call(client, actor, tool, arguments(grid, tool, second))
                assert_owned(isolated, tool, second, alert_resources[second.pin.account_id])
                rendered = isolated.model_dump_json()
                assert str(own.report.job_id) not in rendered
                assert str(own_alert.event.id) not in rendered

            revoke = (
                Scope.ALERTS_READ
                if tool is Tool.ALERT_SUMMARY
                else Scope.REPORTS_WRITE
                if tool is Tool.REPORT_CREATE
                else Scope.REPORTS_READ
            )
            with without_grant(grid, actor, revoke):
                before = retained_state(grid, tables)
                assert_denied(call(client, actor, tool, args), "ACCESS_DENIED", private)
                assert retained_state(grid, tables) == before
