"""Eight research operations leave existing source, finance and broker contracts intact."""

from copy import deepcopy
from typing import Any

import pytest
from trading212_api_contracts import typescript as generation
from trading212_api_contracts.research_typescript import RESEARCH_OPERATIONS
from trading212_application import research as app

from tests.unit.api.test_research_routes import application

pytestmark = pytest.mark.contract


def contract() -> dict[str, Any]:
    api, _ = application()
    return api.openapi()


def test_exact_eight_ports_six_paths_and_authentication_metadata() -> None:
    source = contract()
    operations = [
        (method, path, operation["operationId"])
        for path, methods in source["paths"].items()
        for method, operation in methods.items()
        if "research" in operation.get("tags", [])
    ]
    assert len(operations) == 8 and set(operations) == RESEARCH_OPERATIONS
    assert len({path for _, path, _ in operations}) == 6
    assert {name for _, _, name in operations} == {
        name
        for name, member in app.ResearchService.__dict__.items()
        if callable(member) and not name.startswith("_")
    }
    for method, path, name in operations:
        operation = source["paths"][path][method]
        assert operation["security"] == [{"bearerAuth": []}, {"sessionCookie": []}]
        params = {entry["name"]: entry for entry in operation.get("parameters", [])}
        if method == "post":
            assert params["X-Idempotency-Key"]["required"] is True
        if name == "create_research_note_version":
            assert params["If-Match"]["required"] is True
        if name.startswith("get_"):
            assert "304" in operation["responses"]
        if name == "get_research_summary":
            assert set(params) == {
                "account_id",
                "xray_run_id",
                "source_cutoff_at",
                "entity_id",
                "event_kind",
                "review_state",
                "limit",
                "cursor",
            }
            assert params["limit"]["schema"]["maximum"] == 100
            assert params["limit"]["schema"]["default"] == 25
        if name == "get_research_item":
            assert set(params) == {"item_id"}


def test_closed_generation_is_deterministic_and_imports_existing_source_schemas() -> None:
    source = contract()
    before = deepcopy(source)
    rendered = generation.render_research_client(source)
    assert source == before and rendered == generation.render_research_client(deepcopy(source))
    assert (
        "class ResearchApiClient" in rendered and "ResearchTransport, ResearchApiError" in rendered
    )
    assert rendered.count("async ") == 8 and "async request(" not in rendered
    assert 'from "./sources.generated"' in rendered
    assert "export const SourceLicenseSchema" not in rendered
    assert "z.any(" not in rendered and "z.unknown(" not in rendered
    for _, _, name in RESEARCH_OPERATIONS:
        assert f"async {name}(" in rendered
    for value in (
        "research_summary_v1",
        "research_portfolio_preview_v1",
        "source_facts",
        "portfolio_facts",
        "owner_revision",
        "optional_synthesis",
        "provider_publication_unavailable",
    ):
        assert f'z.literal("{value}")' in rendered


@pytest.mark.parametrize("change", ["method", "path", "name", "missing", "extra"])
def test_unreviewed_registry_shapes_cannot_generate_a_generic_gateway(change: str) -> None:
    source = contract()
    path = "/api/v1/research/items/{item_id}"
    operation = source["paths"][path]["get"]
    if change == "method":
        source["paths"][path]["post"] = source["paths"][path].pop("get")
    elif change == "path":
        source["paths"][path + "/fetch"] = source["paths"].pop(path)
    elif change == "name":
        operation["operationId"] = "fetch_article"
    elif change == "missing":
        del source["paths"][path]
    else:
        source["paths"]["/api/v1/provider-request"] = {"get": operation}
    with pytest.raises(ValueError, match="frozen research operation registry"):
        generation.render_research_client(source)


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
    ],
)
def test_research_registration_does_not_change_existing_client_bytes(name: str) -> None:
    source = contract()
    old = deepcopy(source)
    old["paths"] = {
        path: {
            method: operation
            for method, operation in methods.items()
            if "research" not in operation.get("tags", [])
        }
        for path, methods in old["paths"].items()
    }
    old["paths"] = {path: methods for path, methods in old["paths"].items() if methods}
    render = getattr(generation, name)
    assert render(source) == render(old)


def test_prose_and_research_proof_have_closed_separate_shapes() -> None:
    schemas = contract()["components"]["schemas"]
    for name in (
        "ResearchItemView",
        "ResearchSummary",
        "ResearchSourceVersion",
        "ResearchCitation",
        "ResearchNoteContent",
        "ResearchPortfolioPreview",
        "ResearchSynthesisUnavailable",
    ):
        assert schemas[name]["additionalProperties"] is False
        assert not {"url", "destination", "request_path", "headers", "tools"} & set(
            schemas[name]["properties"]
        )
    assert schemas["ResearchMoney"]["properties"]["amount"]["type"] == "string"
    assert schemas["ResearchMoney"]["properties"]["currency"]["type"] == "string"
    assert (
        schemas["ResearchSynthesisUnavailable"]["properties"]["availability"]["const"]
        == "unavailable"
    )
    assert (
        schemas["ResearchPortfolioPreview"]["properties"]["source_reference_ids"]["maxItems"] == 64
    )
    assert schemas["ResearchNewsFacts"]["properties"]["summary"]["maxLength"] == 4096
