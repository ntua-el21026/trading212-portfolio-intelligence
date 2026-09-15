"""Independent MCP inventory and preservation of accepted Phase 1 input behavior."""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from trading212_application.services import SyntheticPortfolioService
from trading212_mcp.schemas import RESULT_MODELS
from trading212_mcp.server import create_runtime
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.mcp_registry_cases import CASES, LEGACY_CASES

pytestmark = pytest.mark.contract


def _settings() -> SecuritySettings:
    return SecuritySettings(
        environment=RuntimeEnvironment.TEST,
        local_synthetic_auth_enabled=True,
    )


def _closed_objects(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        if value.get("type") == "object" or "properties" in value:
            assert value.get("additionalProperties") is False, path
        for key, child in value.items():
            _closed_objects(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _closed_objects(child, f"{path}[{index}]")


async def test_independent_exact_25_names_fields_scopes_and_annotations_after_p208() -> None:
    server = create_runtime(security_settings=_settings()).server
    tools = await server.list_tools()
    expected_names = tuple(case.name for case in CASES)
    assert len(set(expected_names)) == 25
    premium = {
        "create_risk_run",
        "get_risk_summary",
        "get_risk_matrix",
        "list_scenarios",
        "create_scenario_run",
        "get_scenario_result",
        "compare_scenarios",
    }
    assert len(tools) == 32
    assert {tool.name for tool in tools} == set(expected_names) | premium
    assert tuple(tool.name for tool in tools[:9]) == expected_names[:9]
    assert set(RESULT_MODELS) == set(expected_names) | premium
    descriptors = {
        tool.name: tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools
    }
    for case in CASES:
        descriptor = descriptors[case.name]
        schema = descriptor["inputSchema"]
        assert set(schema["required"]) == case.required, case.name
        assert set(schema["properties"]) == case.required | set(case.optional), case.name
        _closed_objects(schema, case.name)
        schemes = descriptor["_meta"]["securitySchemes"]
        assert len(schemes) == 1 and schemes[0]["type"] == "oauth2"
        assert set(schemes[0]["scopes"]) == set(case.scopes), case.name
        assert len(schemes[0]["scopes"]) == len(case.scopes), case.name
        assert descriptor["annotations"] == {
            "readOnlyHint": not case.command,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }, case.name
        assert descriptor["outputSchema"] == RESULT_MODELS[case.name].model_json_schema(
            by_alias=True
        ), case.name
        assert descriptor["outputSchema"]["additionalProperties"] is False

        for field in ("limit", "top_n", "recent_limit", "issue_limit"):
            if field not in schema["properties"]:
                continue
            parameter = schema["properties"][field]
            upper = (
                25 if field == "recent_limit" else (50 if case.legacy or field == "top_n" else 100)
            )
            default = 10 if field == "recent_limit" else 25
            assert parameter["minimum"] == 1, (case.name, field)
            assert parameter["maximum"] == upper, (case.name, field)
            assert parameter["default"] == default, (case.name, field)


async def test_original_nine_keep_opaque_ids_coercion_dates_and_decimal_output() -> None:
    server = create_runtime(security_settings=_settings()).server
    account_id = SyntheticPortfolioService.ACCOUNT_ID
    for case in LEGACY_CASES:
        args = {**case.arguments, "account_id": account_id}
        result = await server.call_tool(case.name, args)
        assert isinstance(result, CallToolResult) and not result.is_error, case.name
        assert result.structured_content is not None
        envelope = result.structured_content
        RESULT_MODELS[case.name].model_validate(envelope)
        assert envelope["reporting_currency"] == "EUR"
        assert envelope["calculation"]["version"]
        assert envelope["data_quality"]["source_cutoff_at"]
        assert envelope["error"] is None

    positions = await server.call_tool(
        "list_positions",
        {"account_id": account_id, "limit": "2", "search": "null"},
    )
    assert isinstance(positions, CallToolResult) and not positions.is_error
    assert positions.structured_content is not None
    page = positions.structured_content
    assert page["pagination"]["limit"] == 2
    assert page["data"]["search"] is None
    assert len(page["data"]["positions"]) == 2
    assert all(isinstance(row["quantity"], str) for row in page["data"]["positions"])
    snapshot = await server.call_tool(
        "get_portfolio_snapshot",
        {"account_id": account_id, "snapshot_id": "snapshot-2026-08-31"},
    )
    assert isinstance(snapshot, CallToolResult) and not snapshot.is_error
    assert snapshot.structured_content is not None
    assert snapshot.structured_content["data"]["id"] == "snapshot-2026-08-31"

    # Legacy bounds remain narrower than the new tool pagination/window contracts.
    with pytest.raises(ToolError):
        await server.call_tool("list_positions", {"account_id": account_id, "limit": 51})
    rejected = await server.call_tool(
        "list_recent_transactions",
        {"account_id": account_id, "start_date": "2025-01-01", "end_date": "2026-08-31"},
    )
    assert isinstance(rejected, CallToolResult) and rejected.is_error
    assert rejected.structured_content is not None
    assert rejected.structured_content["error"]["code"] == "VALIDATION_FAILED"
