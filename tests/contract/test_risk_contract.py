"""The additive risk registry is bounded and cannot grow a generic execution surface."""

import json
from pathlib import Path
from typing import Any

import pytest
from trading212_api.main import create_app
from trading212_api_contracts.typescript import render_risk_client
from trading212_application.services import SyntheticPortfolioService
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

pytestmark = pytest.mark.contract
OPERATIONS = {
    "list_risk_definitions": ("get", "/api/v1/accounts/{account_id}/risk-definitions"),
    "create_risk_definition": ("post", "/api/v1/accounts/{account_id}/risk-definitions"),
    "get_risk_definition": ("get", "/api/v1/risk-definitions/{definition_id}"),
    "list_risk_versions": ("get", "/api/v1/risk-definitions/{definition_id}/versions"),
    "create_risk_version": ("post", "/api/v1/risk-definitions/{definition_id}/versions"),
    "get_risk_version": ("get", "/api/v1/risk-definition-versions/{version_id}"),
    "list_risk_runs": ("get", "/api/v1/accounts/{account_id}/risk-runs"),
    "create_risk_run": ("post", "/api/v1/accounts/{account_id}/risk-runs"),
    "get_risk_run": ("get", "/api/v1/risk-runs/{run_id}"),
    "get_risk_matrix": ("get", "/api/v1/risk-runs/{run_id}/matrix"),
    "cancel_risk_run": ("post", "/api/v1/risk-runs/{run_id}/cancel"),
}


def contract() -> dict[str, Any]:
    return create_app(
        service=SyntheticPortfolioService(),
        settings=SecuritySettings(environment=RuntimeEnvironment.TEST),
    ).openapi()


def test_exact_eleven_operations_authentication_commands_and_concurrency() -> None:
    document = contract()
    actual = {
        operation["operationId"]: (method, path)
        for path, methods in document["paths"].items()
        for method, operation in methods.items()
        if "risk" in operation.get("tags", [])
    }
    assert actual == OPERATIONS
    for name, (method, path) in actual.items():
        operation = document["paths"][path][method]
        assert operation["security"] == [{"bearerAuth": []}, {"sessionCookie": []}]
        if method == "post":
            parameters = {
                item["name"]: item for item in operation["parameters"] if item["in"] == "header"
            }
            assert parameters["X-Idempotency-Key"]["required"] is True
            assert ("If-Match" in parameters) == (name == "create_risk_version")
    schemas = document["components"]["schemas"]
    visited: set[str] = set()

    def check(schema: dict[str, Any]) -> None:
        if "$ref" in schema:
            name = schema["$ref"].removeprefix("#/components/schemas/")
            if name not in visited:
                visited.add(name)
                check(schemas[name])
        assert schema.get("type") != "number"
        if schema.get("type") == "object":
            assert schema["additionalProperties"] is False
            assert not (
                {"owner_id", "url", "sql", "shell", "returns"} & set(schema.get("properties", {}))
            )
            for child in schema.get("properties", {}).values():
                check(child)
        if schema.get("type") == "array":
            assert "maxItems" in schema
            check(schema["items"])
        for child in schema.get("anyOf", []):
            check(child)

    for name in (
        "CreateRiskRunRequest",
        "CreateRiskDefinitionRequest",
        "CreateRiskVersionRequest",
        "RiskRunResponse",
        "RiskMatrixResponse",
    ):
        check(schemas[name])
    assert {"RiskAvailableMetric", "RiskUnavailableMetric"} <= visited


def test_generator_rejects_unknown_operation_and_preserves_committed_contract() -> None:
    document = contract()
    assert document == json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text())
    rendered = render_risk_client(document)
    assert "z.literal(12)" in rendered and "z.literal(252)" in rendered
    assert 'from "./historical.generated"' in rendered
    document["paths"]["/api/v1/risk-runs/{run_id}"]["get"]["operationId"] = "execute_broker_command"
    with pytest.raises(ValueError, match="registry differs"):
        render_risk_client(document)
