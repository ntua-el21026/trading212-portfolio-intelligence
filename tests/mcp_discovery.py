"""Independent current MCP inventory over the preserved 25-case catalogue."""

from collections.abc import Sequence

from mcp.types import Tool

from tests.mcp_registry_cases import CASES

# Explicit authorized additions, independent of production registration constants.
# The historical projection-only and research delta oracles retain their own scopes.
PREMIUM_TOOL_NAMES = (
    "create_risk_run",
    "get_risk_summary",
    "get_risk_matrix",
    "list_scenarios",
    "create_scenario_run",
    "get_scenario_result",
    "compare_scenarios",
    "create_projection_run",
    "get_projection",
    "list_goals",
    "get_goal_analysis",
    "get_research_summary",
    "get_research_item",
)


def assert_current_tool_inventory(tools: Sequence[Tool]) -> None:
    original_names = {case.name for case in CASES}
    assert len(CASES) == len(original_names) == 25
    additions = set(PREMIUM_TOOL_NAMES)
    assert len(PREMIUM_TOOL_NAMES) == len(additions) == 13
    assert original_names.isdisjoint(additions)
    names = tuple(tool.name for tool in tools)
    assert len(names) == len(set(names)) == 38
    assert set(names) == original_names | additions
    assert names[-2:] == ("get_research_summary", "get_research_item")
