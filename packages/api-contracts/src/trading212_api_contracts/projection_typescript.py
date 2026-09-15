"""Closed projection client registry; existing client render paths remain unchanged."""

from __future__ import annotations

from typing import Any

from .typescript import TargetClientGenerator

PROJECTION_OPERATIONS = frozenset(
    {
        ("get", "/api/v1/accounts/{account_id}/assumption-sets", "list_assumption_sets"),
        ("post", "/api/v1/accounts/{account_id}/assumption-sets", "create_assumption_set"),
        ("get", "/api/v1/assumption-sets/{set_id}", "get_assumption_set"),
        ("get", "/api/v1/assumption-sets/{set_id}/versions", "list_assumption_versions"),
        ("post", "/api/v1/assumption-sets/{set_id}/versions", "create_assumption_version"),
        ("get", "/api/v1/assumption-versions/{version_id}", "get_assumption_version"),
        ("get", "/api/v1/accounts/{account_id}/goals", "list_goals"),
        ("post", "/api/v1/accounts/{account_id}/goals", "create_goal"),
        ("get", "/api/v1/goals/{goal_id}", "get_goal"),
        ("get", "/api/v1/goals/{goal_id}/versions", "list_goal_versions"),
        ("post", "/api/v1/goals/{goal_id}/versions", "create_goal_version"),
        ("get", "/api/v1/goal-versions/{version_id}", "get_goal_version"),
        ("get", "/api/v1/accounts/{account_id}/projection-runs", "list_projection_runs"),
        ("post", "/api/v1/accounts/{account_id}/projection-runs", "create_projection_run"),
        ("get", "/api/v1/projection-runs/{run_id}", "get_projection_run"),
        ("get", "/api/v1/projection-runs/{run_id}/goal-analysis", "get_goal_analysis"),
        ("post", "/api/v1/projection-runs/{run_id}/cancel", "cancel_projection_run"),
    }
)


class ProjectionClientGenerator(TargetClientGenerator):
    def __init__(self, contract: dict[str, Any]) -> None:
        super().__init__(contract, tag="projection")

    def render(self) -> str:
        rendered = super().render()
        for name in (
            "Transport",
            "ApiClient",
            "ApiResponse",
            "ReadOptions",
            "CommandOptions",
            "ClientOptions",
        ):
            rendered = rendered.replace(f"Target{name}", f"Projection{name}")
        return rendered.replace("./target-transport", "./projection-transport").replace(
            "ProjectionTransport, type", "ProjectionTransport, ProjectionApiError, type"
        )


def render_projection_client(contract: dict[str, Any]) -> str:
    actual = [
        (method, path, operation["operationId"])
        for path, methods in contract["paths"].items()
        for method, operation in methods.items()
        if "projection" in operation.get("tags", [])
    ]
    if len(actual) != len(PROJECTION_OPERATIONS) or set(actual) != PROJECTION_OPERATIONS:
        raise ValueError("The frozen projection operation registry differs.")
    return ProjectionClientGenerator(contract).render()
