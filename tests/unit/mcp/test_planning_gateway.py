"""Fixed MCP planning delegation, stable identities and no-input-reflection failures."""

from __future__ import annotations

import copy
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from trading212_api_contracts.planning import McpCreateContributionPlanRequest
from trading212_application import planning as app
from trading212_application.views import Page
from trading212_mcp.planning_gateway import _command
from trading212_mcp.server import create_runtime
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
ACCOUNT = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee"
PORTFOLIO = "aef0bdf3-3613-4cfe-b15f-bc1f8b9c4119"
TARGET = "19a8b590-9c18-4c43-8dce-d622cb6ae033"
SNAPSHOT = "5dd1049e-7433-43f4-bf5b-3a73c24c0568"
PLAN = "b7e267ab-9f80-4cda-8f5e-e5c28a7f72b9"
REQUEST = "fedaa769-cba7-4b7e-8f4a-30ab5795ea8e"
JOB = "6fdba70f-39ec-4df5-8e96-1d965c892c04"
BODY: dict[str, Any] = {
    "account_id": ACCOUNT,
    "virtual_portfolio_id": PORTFOLIO,
    "target_version_id": TARGET,
    "snapshot_id": SNAPSHOT,
    "contribution": {"amount": "10", "currency": "EUR"},
    "mode": "global",
    "idempotency_key": "plan:mcp:one",
}


def job() -> app.ContributionPlanJobView:
    return app.ContributionPlanJobView(
        plan_id=PLAN,
        account_id=ACCOUNT,
        virtual_portfolio_id=PORTFOLIO,
        target_version_id=TARGET,
        snapshot_id=SNAPSHOT,
        request_id=REQUEST,
        request_revision=1,
        job_id=JOB,
        state=app.PlanJobState.QUEUED,
        outcome=None,
        requested_at=NOW,
        input_digest="a" * 64,
    )


def runtime(service: AsyncMock | None = None) -> MCPServer[Any]:
    return create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        ),
        planning_service=cast(app.PlanningService, service) if service is not None else None,
        clock=lambda: NOW,
    ).server


async def call(server: MCPServer[Any], name: str, args: dict[str, Any]) -> CallToolResult:
    result = await server.call_tool(name, args)
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    return result


async def test_create_plan_returns_only_committed_job_identity_and_exact_canonical_options() -> (
    None
):
    service = AsyncMock(spec=app.PlanningService)
    service.create_contribution_plan.return_value = job()
    server = runtime(service)
    first = await call(server, "create_contribution_plan", BODY)
    second = await call(server, "create_contribution_plan", BODY)
    assert not first.is_error and not second.is_error
    assert first.structured_content == second.structured_content
    data = first.structured_content["data"]
    assert data["plan_id"] == PLAN and data["request_id"] == REQUEST and data["job_id"] == JOB
    assert data["plan_revision_id"] is None and data["outcome"] is None
    assert data["execution_allowed"] is False and "result" not in data
    assert data["revision_etag"] == f'"{PLAN}:1"'
    _, command = service.create_contribution_plan.call_args.args
    assert command.options.contribution.amount == Decimal("10")
    assert command.options.holding_constraints == ()
    assert (
        service.create_contribution_plan.call_args.kwargs["idempotency_key"]
        == BODY["idempotency_key"]
    )
    assert service.get_actual_vs_target.await_count == 0


def test_mcp_all_256_composite_overrides_preserve_holding_identity_without_node_guessing() -> None:
    constraints = [
        {
            "holding_id": str(UUID(int=index + 1)),
            "minimum_amount": "0",
            "value_increment": "0.01",
            "maximum_post_weight": "1",
        }
        for index in range(256)
    ]
    request = McpCreateContributionPlanRequest.model_validate(
        {**BODY, "allocation_constraints": constraints}
    )
    command = _command(request)
    assert len(command.options.holding_constraints) == 256
    assert command.options.allocation_constraints == ()
    assert command.options.holding_constraints[-1].holding_id == constraints[-1]["holding_id"]
    assert command.options.holding_constraints[-1].value_increment == Decimal("0.01")


async def test_read_pending_plan_never_creates_work_or_fabricates_allocation_lines() -> None:
    service = AsyncMock(spec=app.PlanningService)
    service.get_contribution_plan.return_value = app.ContributionPlanDetailView(
        job=job(),
        request=_command(McpCreateContributionPlanRequest.model_validate(BODY)),
        result=None,
        lines=Page((), None, 25, 0),
        calculated_at=None,
        content_digest=None,
    )
    result = await call(
        runtime(service), "get_contribution_plan", {"account_id": ACCOUNT, "plan_id": PLAN}
    )
    assert not result.is_error
    assert result.structured_content["data"]["result"] is None
    assert result.structured_content["data"]["lines"]["total"] == 0
    assert result.structured_content["pagination"]["truncated"] is False
    assert service.get_contribution_plan.call_args.kwargs["query"].account_id == ACCOUNT
    service.create_contribution_plan.assert_not_awaited()


@pytest.mark.parametrize("location", ["root", "money", "constraint", "listing"])
async def test_unknown_argument_keys_and_values_are_redacted_before_sdk_echo(
    location: str, caplog: pytest.LogCaptureFixture
) -> None:
    private_key = "_".join(("PLANNING", "FIELD", "CANARY"))
    private_value = "_".join(("PLANNING", "VALUE", "CANARY"))
    args = copy.deepcopy(BODY)
    if location == "root":
        args[private_key] = private_value
    elif location == "money":
        args["contribution"][private_key] = private_value
    elif location == "listing":
        args["listing_preferences"] = [
            {"holding_id": TARGET, "listing_id": SNAPSHOT, private_key: private_value}
        ]
    else:
        args["allocation_constraints"] = [
            {
                "holding_id": TARGET,
                "minimum_amount": "0",
                "value_increment": "0.01",
                private_key: private_value,
            }
        ]
    service = AsyncMock(spec=app.PlanningService)
    with caplog.at_level(logging.DEBUG), pytest.raises(ToolError) as caught:
        await runtime(service).call_tool("create_contribution_plan", args)
    rendered = str(caught.value) + caplog.text
    assert private_key not in rendered and private_value not in rendered
    service.create_contribution_plan.assert_not_awaited()


@pytest.mark.parametrize(
    "override",
    [
        {"contribution": {"amount": 1, "currency": "EUR"}},
        {"mode": "execute"},
        {"broker_url": "https://untrusted.invalid"},
        {"idempotency_key": "bad key"},
        {"excluded_holding_ids": "[]"},
        {"eligible_holding_ids": "null"},
    ],
)
async def test_mcp_input_types_fail_before_planning_service(override: dict[str, Any]) -> None:
    service = AsyncMock(spec=app.PlanningService)
    with pytest.raises(ToolError):
        await runtime(service).call_tool("create_contribution_plan", {**BODY, **override})
    service.create_contribution_plan.assert_not_awaited()


@pytest.mark.parametrize("error", list(app.PlanningServiceErrorCode))
async def test_service_errors_never_echo_private_exception_messages(
    error: app.PlanningServiceErrorCode,
) -> None:
    service = AsyncMock(spec=app.PlanningService)
    canary = "_".join(("PRIVATE", "PLANNING", "FAILURE"))
    service.create_contribution_plan.side_effect = app.PlanningServiceError(error, canary)
    result = await call(runtime(service), "create_contribution_plan", BODY)
    assert result.is_error
    assert result.structured_content["error"]["code"] == error.value
    assert canary not in result.model_dump_json()


async def test_invalid_service_result_fails_closed_without_oversized_or_private_output() -> None:
    service = AsyncMock(spec=app.PlanningService)
    service.create_contribution_plan.return_value = {"private": "service-output-canary"}
    result = await call(runtime(service), "create_contribution_plan", BODY)
    assert result.is_error and result.structured_content["error"]["code"] == "INTERNAL_ERROR"
    assert "service-output-canary" not in result.model_dump_json()


async def test_individually_valid_mcp_arrays_still_enforce_64k_total_request_bound() -> None:
    service = AsyncMock(spec=app.PlanningService)
    args = {
        **BODY,
        "allocation_constraints": [
            {
                "holding_id": str(UUID(int=i + 1)),
                "minimum_amount": "0",
                "value_increment": "0.01",
                "maximum_post_weight": "1",
            }
            for i in range(256)
        ],
        "listing_preferences": [
            {"holding_id": str(UUID(int=i + 1)), "listing_id": str(UUID(int=i + 1000))}
            for i in range(256)
        ],
        "excluded_holding_ids": [str(UUID(int=i + 2000)) for i in range(256)],
    }
    McpCreateContributionPlanRequest.model_validate(args)
    result = await call(runtime(service), "create_contribution_plan", args)
    assert result.is_error and result.structured_content["error"]["code"] == "REQUEST_TOO_LARGE"
    service.create_contribution_plan.assert_not_awaited()
