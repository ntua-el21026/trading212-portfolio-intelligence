"""Exactly seventeen projection operations; prior clients and schemas stay frozen."""

from copy import deepcopy
from typing import Any

import pytest
from trading212_api_contracts import typescript as generation
from trading212_api_contracts.projection_typescript import PROJECTION_OPERATIONS
from trading212_application import projection as app

from tests.unit.api.test_projection_routes import application

pytestmark = pytest.mark.contract


def contract() -> dict[str, Any]:
    api, _ = application()
    return api.openapi()


def test_exact_twelve_paths_seventeen_operations_and_security_metadata() -> None:
    source = contract()
    operations = [
        (method, path, operation["operationId"])
        for path, methods in source["paths"].items()
        for method, operation in methods.items()
        if "projection" in operation.get("tags", [])
    ]
    assert len(operations) == 17 and set(operations) == PROJECTION_OPERATIONS
    assert len({path for _, path, _ in operations}) == 12
    ports = {
        name
        for name, value in app.ProjectionService.__dict__.items()
        if callable(value) and not name.startswith("_")
    }
    mapped = {
        name.replace("projection_", "")
        if name
        in {
            "create_projection_run",
            "list_projection_runs",
            "get_projection_run",
            "cancel_projection_run",
        }
        else name
        for _, _, name in operations
    }
    assert mapped == ports
    for method, path, name in operations:
        operation = source["paths"][path][method]
        assert operation["security"] == [{"bearerAuth": []}, {"sessionCookie": []}]
        parameters = {item["name"]: item for item in operation.get("parameters", [])}
        if method == "post":
            assert parameters["X-Idempotency-Key"]["required"] is True
        if name in {"create_assumption_version", "create_goal_version"}:
            assert parameters["If-Match"]["required"] is True
        if name.startswith("get_"):
            assert "304" in operation["responses"]
        if name == "get_projection_run":
            assert set(parameters) == {"run_id", "point_limit", "point_cursor"}
            assert parameters["point_limit"]["schema"]["default"] == 25
            assert parameters["point_limit"]["schema"]["maximum"] == 100
        if name == "get_goal_analysis":
            assert set(parameters) == {"run_id"}


def test_generation_is_closed_deterministic_and_does_not_mutate_contract() -> None:
    source = contract()
    before = deepcopy(source)
    rendered = generation.render_projection_client(source)
    assert source == before and rendered == generation.render_projection_client(deepcopy(source))
    assert "class ProjectionApiClient" in rendered
    assert "ProjectionTransport, ProjectionApiError" in rendered
    assert "z.any(" not in rendered and "z.unknown(" not in rendered
    assert "async request(" not in rendered
    assert rendered.count("async ") == 17
    for _, _, name in PROJECTION_OPERATIONS:
        assert f"async {name}(" in rendered
    assert "point_cursor" in rendered and "point_limit" in rendered
    assert 'z.literal("projection_points_v1")' in rendered
    assert 'z.literal("goal_analysis_compact_v1")' in rendered
    assert 'z.literal("1.0.0")' in rendered
    assert "model_estimate_not_guaranteed_forecast" in rendered


@pytest.mark.parametrize("change", ["method", "path", "name", "missing", "extra"])
def test_unknown_registry_shapes_cannot_generate_generic_dispatch(change: str) -> None:
    source = contract()
    path = "/api/v1/projection-runs/{run_id}"
    operation = source["paths"][path]["get"]
    if change == "method":
        source["paths"][path]["post"] = source["paths"][path].pop("get")
    elif change == "path":
        source["paths"][path + "/unreviewed"] = source["paths"].pop(path)
    elif change == "name":
        operation["operationId"] = "dispatch_projection"
    elif change == "missing":
        del source["paths"][path]
    else:
        source["paths"]["/api/v1/projection-provider-dispatch"] = {"get": operation}
    with pytest.raises(ValueError, match="frozen projection operation registry"):
        generation.render_projection_client(source)


@pytest.mark.parametrize(
    "name",
    [
        "render_target_client",
        "render_planning_client",
        "render_source_client",
        "render_historical_client",
        "render_xray_client",
        "render_report_client",
        "render_premium_report_client",
        "render_alert_client",
        "render_risk_client",
        "render_scenario_client",
    ],
)
def test_projection_registration_does_not_change_prior_client_rendering(name: str) -> None:
    source = contract()
    old = deepcopy(source)
    old["paths"] = {
        path: {
            method: operation
            for method, operation in methods.items()
            if "projection" not in operation.get("tags", [])
        }
        for path, methods in old["paths"].items()
    }
    old["paths"] = {path: methods for path, methods in old["paths"].items() if methods}
    render = getattr(generation, name)
    assert render(source) == render(old)


def test_new_point_rows_expose_complete_money_residual_and_funding_contract() -> None:
    schemas = contract()["components"]["schemas"]
    point = schemas["ProjectionPointView"]
    assert point["additionalProperties"] is False
    assert set(point["required"]) == {
        "month",
        "nominal",
        "real",
        "assets",
        "contributions",
        "withdrawals_requested",
        "withdrawals_funded",
        "unpaid_withdrawals",
        "investment_effect",
        "fees",
        "tax_drag",
        "wealth_residual",
        "allocation_residual",
        "withdrawal_residual",
        "funding_failed",
        "unpaid_positive_below_quantum",
    }
    for name in ("ProjectionResultContextView", "ProjectionRunResponse", "GoalAnalysisResponse"):
        assert schemas[name]["additionalProperties"] is False
    for name in ("ProjectionMoney", "ProjectionNonnegativeMoney"):
        assert schemas[name]["properties"]["amount"]["type"] == "string"
        assert schemas[name]["properties"]["currency"]["type"] == "string"
