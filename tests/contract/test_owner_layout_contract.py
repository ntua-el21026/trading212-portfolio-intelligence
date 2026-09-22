"""Explicit five-operation registry, strict client and unchanged previous client bytes."""

from copy import deepcopy

import pytest
from trading212_api_contracts import typescript as generation
from trading212_api_contracts.owner_layout_typescript import OWNER_LAYOUT_OPERATIONS
from trading212_application import owner_layouts as app

from tests.unit.api.test_owner_layout_routes import application

pytestmark = pytest.mark.contract


def test_exact_five_ports_three_paths_and_conditional_revision_contract() -> None:
    api, _ = application()
    contract = api.openapi()
    actual = {
        (method, path, op["operationId"])
        for path, methods in contract["paths"].items()
        for method, op in methods.items()
        if "owner-layouts" in op.get("tags", [])
    }
    assert actual == OWNER_LAYOUT_OPERATIONS
    assert len({path for _, path, _ in actual}) == 3
    assert {name for _, _, name in actual} == {
        name
        for name, member in app.OwnerLayoutService.__dict__.items()
        if callable(member) and not name.startswith("_")
    }
    for method, path, name in actual:
        operation = contract["paths"][path][method]
        assert operation["security"] == [{"bearerAuth": []}, {"sessionCookie": []}]
        parameters = {item["name"]: item for item in operation.get("parameters", [])}
        if method != "get":
            assert parameters["X-Idempotency-Key"]["required"] is True
        else:
            assert "304" in operation["responses"]
        if name in {"update_owner_layout", "archive_owner_layout"}:
            assert parameters["If-Match"]["required"] is True
    rendered = generation.render_owner_layout_client(contract)
    assert rendered == generation.render_owner_layout_client(deepcopy(contract))
    assert rendered.count("async ") == 5
    assert (
        "class OwnerLayoutApiClient" in rendered
        and "z.any(" not in rendered
        and "z.unknown(" not in rendered
    )
    assert "async request(" not in rendered


@pytest.mark.parametrize("mutation", ["extra", "method", "path", "missing"])
def test_unknown_layout_gateway_cannot_generate(mutation: str) -> None:
    api, _ = application()
    contract = api.openapi()
    path = "/api/v1/preferences/layouts/{layout_id}"
    if mutation == "extra":
        contract["paths"]["/api/v1/preferences/query"] = deepcopy(contract["paths"][path])
    elif mutation == "method":
        contract["paths"][path]["delete"] = contract["paths"][path].pop("patch")
    elif mutation == "path":
        contract["paths"][path + "/raw"] = contract["paths"].pop(path)
    else:
        del contract["paths"][path]
    with pytest.raises(ValueError, match="fixed owner layout operation registry"):
        generation.render_owner_layout_client(contract)


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
        "render_projection_client",
        "render_research_client",
    ],
)
def test_layout_extension_does_not_change_any_existing_client(name: str) -> None:
    api, _ = application()
    after = api.openapi()
    before = deepcopy(after)
    for path in tuple(before["paths"]):
        if any(
            "owner-layouts" in operation.get("tags", [])
            for operation in before["paths"][path].values()
        ):
            del before["paths"][path]
    render = getattr(generation, name)
    assert render(before) == render(after)
