"""P2-03 fixed reference APIs, truthful raw benchmarks and reproducible client surface."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
from trading212_api_contracts.typescript import (
    render_planning_client,
    render_source_client,
    render_target_client,
)

pytestmark = pytest.mark.contract
SOURCE_OPERATIONS = {
    "get_market_source_status": "get",
    "get_fx_source_status": "get",
    "get_benchmark_source_status": "get",
    "get_price_snapshot": "get",
    "get_fx_snapshot": "get",
    "get_benchmark_snapshot": "get",
    "list_price_observations": "get",
    "list_fx_observations": "get",
    "list_fx_observation_references": "get",
    "list_benchmark_observations": "get",
    "list_benchmark_definitions": "get",
    "get_benchmark_definition": "get",
    "create_benchmark_definition": "post",
    "create_benchmark_version": "post",
    "archive_benchmark_definition": "post",
    "get_intelligence_data_quality": "get",
}


def _contract() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text()),
    )


def test_exact_fourteen_source_operations_are_bounded_private_and_separate_from_broker() -> None:
    # Keep the accepted historical selector; P208 adds only the fixed quality GET.
    contract = _contract()
    operations = {
        operation["operationId"]: (method, operation)
        for methods in contract["paths"].values()
        for method, operation in methods.items()
        if "sources" in operation.get("tags", [])
    }
    assert {name: method for name, (method, _) in operations.items()} == SOURCE_OPERATIONS
    for name, (method, operation) in operations.items():
        assert operation["security"] == [{"bearerAuth": []}, {"sessionCookie": []}]
        parameters = {item["name"]: item for item in operation["parameters"]}
        assert not {"url", "method", "path", "provider_url", "owner_id"} & parameters.keys()
        if method == "get":
            if name == "get_intelligence_data_quality":
                # Current usability is always rechecked; this read has no 304 path.
                assert "If-None-Match" not in parameters
                assert set(parameters) == {"account_id", "analytics_kind", "cursor", "limit"}
            else:
                assert "If-None-Match" in parameters
            if "limit" in parameters:
                assert parameters["limit"]["schema"]["maximum"] == (
                    25 if name == "list_fx_observation_references" else 100
                )
                assert parameters["limit"]["schema"]["default"] == 25
        else:
            assert parameters["X-Idempotency-Key"]["required"] is True
            assert "X-CSRF-Token" in parameters
            if name != "create_benchmark_definition":
                assert "If-Match" in parameters
    assert not any("refresh" in name or "import" in name for name in operations)


def test_source_client_generation_is_deterministic_and_keeps_old_clients_separate() -> None:
    contract = _contract()
    rendered = render_source_client(contract)
    assert rendered == render_source_client(copy.deepcopy(contract))
    assert all(f"async {name}(" in rendered for name in SOURCE_OPERATIONS)
    assert rendered.count("async ") == 16
    assert "z.any(" not in rendered and "z.unknown(" not in rendered
    assert "SourceApiError" in rendered and "instanceof z.ZodError" in rendered
    for render in (render_target_client, render_planning_client):
        assert "async get_price_snapshot(" not in render(contract)
    assert "async create_contribution_plan(" not in rendered


def test_source_header_schema_exposes_raw_benchmark_and_explicit_bounded_gap_preview() -> None:
    schemas = _contract()["components"]["schemas"]
    header = schemas["BenchmarkSnapshotHeader"]
    assert header["additionalProperties"] is False
    assert header["properties"]["kind"]["const"] == "provider_series"
    assert header["properties"]["benchmark_version_id"]["type"] == "null"
    assert {"series", "provenance", "license"} <= set(header["required"])
    coverage = schemas["SourceCoverage"]["properties"]
    assert coverage["gaps"]["maxItems"] == 100
    assert coverage["gap_count"]["maximum"] == 100000
    assert coverage["gaps_truncated"]["type"] == "boolean"
    assert schemas["ProviderStatus"]["properties"]["capabilities"]["maxItems"] == 7
    assert schemas["ProviderStatus"]["properties"]["supported_price_bases"]["maxItems"] == 3


def test_definition_history_is_bounded_on_existing_detail_and_uses_source_series_ids() -> None:
    schemas = _contract()["components"]["schemas"]
    detail = schemas["BenchmarkDefinitionDetail"]["properties"]
    assert set(detail) == {"definition", "versions", "selected_version"}
    assert schemas["SourcePage_BenchmarkVersion_"]["properties"]["items"]["maxItems"] == 100
    assert schemas["BenchmarkContent"]["properties"]["components"]["maxItems"] == 256
    assert set(schemas["BenchmarkComponent"]["properties"]) == {"source_id", "weight"}
    assert "revision_etag" in schemas["BenchmarkDefinitionSummary"]["properties"]
    paths = _contract()["paths"]
    assert not any("benchmark-versions" in path for path in paths)
