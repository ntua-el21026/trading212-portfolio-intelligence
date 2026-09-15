"""Frozen scenario REST registry, complete bounded DTOs and legacy API fingerprints."""

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from trading212_api.main import create_app
from trading212_application.services import SyntheticPortfolioService
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

from tests.contract.premium_report_profile_oracle import (
    PROFILE_TWO,
    assert_profile_two_client_declarations,
    assert_profiled_path,
)

pytestmark = pytest.mark.contract
OPERATIONS = {
    "list_scenarios": ("get", "/api/v1/accounts/{account_id}/scenarios"),
    "create_scenario": ("post", "/api/v1/accounts/{account_id}/scenarios"),
    "get_scenario": ("get", "/api/v1/scenarios/{scenario_id}"),
    "list_scenario_versions": ("get", "/api/v1/scenarios/{scenario_id}/versions"),
    "create_scenario_version": ("post", "/api/v1/scenarios/{scenario_id}/versions"),
    "get_scenario_version": ("get", "/api/v1/scenario-versions/{version_id}"),
    "list_scenario_runs": ("get", "/api/v1/accounts/{account_id}/scenario-runs"),
    "create_scenario_run": ("post", "/api/v1/accounts/{account_id}/scenario-runs"),
    "get_scenario_run": ("get", "/api/v1/scenario-runs/{run_id}"),
    "compare_scenarios": ("get", "/api/v1/accounts/{account_id}/scenario-comparison"),
    "cancel_scenario_run": ("post", "/api/v1/scenario-runs/{run_id}/cancel"),
}


def contract() -> dict[str, Any]:
    return create_app(
        service=SyntheticPortfolioService(),
        settings=SecuritySettings(environment=RuntimeEnvironment.TEST),
    ).openapi()


def digest(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def test_frozen_eight_paths_eleven_operations_and_only_additive_legacy_descriptors() -> None:
    document = contract()
    legacy = json.loads(
        (Path(__file__).parent / "fixtures/pre_scenario_api_fingerprints.json").read_text()
    )
    actual = {
        operation["operationId"]: (method, path)
        for path, methods in document["paths"].items()
        for method, operation in methods.items()
        if "scenario" in operation.get("tags", [])
    }
    assert actual == OPERATIONS and len({path for _, path in actual.values()}) == 8
    assert legacy["path_count"] == 101 and legacy["operation_count"] == 112
    assert len(document["paths"]) == 127
    assert sum(len(methods) for methods in document["paths"].values()) == 148
    for path, expected in legacy["paths"].items():
        if path in PROFILE_TWO["paths"]:
            # ADR-0026 permits exactly the explicit profile selector and closed unions.
            assert digest(PROFILE_TWO["paths"][path]) == expected, path
            assert_profiled_path(path, document["paths"][path])
        else:
            assert digest(document["paths"][path]) == expected, path
    for name, expected in legacy["schemas"].items():
        assert digest(document["components"]["schemas"][name]) == expected, name
    for name, (method, path) in actual.items():
        operation = document["paths"][path][method]
        assert operation["security"] == [{"bearerAuth": []}, {"sessionCookie": []}]
        parameters = {item["name"]: item for item in operation.get("parameters", [])}
        if method == "post":
            assert parameters["X-Idempotency-Key"]["required"] is True
            assert ("If-Match" in parameters) == (name == "create_scenario_version")
        if name in ("get_scenario_run", "compare_scenarios"):
            assert parameters["component_limit"]["schema"]["default"] == 25
            assert parameters["component_limit"]["schema"]["maximum"] == 100
            assert "component_cursor" in parameters and "304" in operation["responses"]
        if name == "compare_scenarios":
            assert (
                parameters["run_ids"]["schema"]["minItems"]
                == parameters["run_ids"]["schema"]["maxItems"]
                == 2
            )


def test_transitive_scenario_objects_are_closed_arrays_bounded_and_money_string_only() -> None:
    schemas = contract()["components"]["schemas"]
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
            for child in schema.get("properties", {}).values():
                check(child)
        if schema.get("type") == "array":
            assert "maxItems" in schema
            check(schema["items"])
        for keyword in ("anyOf", "oneOf", "allOf"):
            for child in schema.get(keyword, []):
                check(child)

    for name in (
        "CreateScenarioRequest",
        "CreateScenarioVersionRequest",
        "CreateScenarioRunRequest",
        "ScenarioRunResponse",
        "ScenarioOperationalRunResponse",
        "ScenarioComparisonPage",
    ):
        check(schemas[name])
    assert {
        "ScenarioMoney",
        "ScenarioSensitivityView",
        "ScenarioRatioMetric",
        "ScenarioInputPins",
    } <= visited
    for name in (
        "CreateScenarioRunRequest",
        "CreateScenarioRequest",
        "CreateScenarioVersionRequest",
    ):
        assert (
            not {
                "owner_id",
                "coefficients",
                "returns",
                "sources",
                "exposures",
                "url",
                "sql",
                "shell",
            }
            & schemas[name]["properties"].keys()
        )


def test_scenario_generator_exports_requested_client_and_rejects_changed_fixed_path() -> None:
    from trading212_api_contracts.typescript import render_scenario_client

    document = contract()
    rendered = render_scenario_client(document)
    assert "export class ScenarioApiClient" in rendered
    assert "ScenarioApiResponse" in rendered and "ScenarioApiError" in rendered
    assert 'from "./scenario-transport"' in rendered
    assert "z.discriminatedUnion" in rendered
    assert "async get_scenario_run(run_id: string, query:" in rendered
    assert "async compare_scenarios(account_id: string, query:" in rendered
    changed = document["paths"].pop("/api/v1/scenario-runs/{run_id}")
    document["paths"]["/api/v1/scenario-runs/latest"] = changed
    with pytest.raises(ValueError, match="registry differs"):
        render_scenario_client(document)


def test_delivered_generated_clients_preserve_bytes_or_explicit_profile_two_contracts() -> None:
    legacy = json.loads(
        (Path(__file__).parent / "fixtures/pre_scenario_api_fingerprints.json").read_text()
    )
    for relative, expected in legacy["generated_clients"].items():
        if relative == "packages/api-contracts/src/premium-reports.generated.ts":
            assert_profile_two_client_declarations(expected)
        else:
            assert sha256(Path(relative).read_bytes()).hexdigest() == expected, relative
