"""A single bounded source read supplies real identities to the frozen aggregate body."""

import copy
import json
from pathlib import Path

import pytest
from trading212_api_contracts.typescript import render_source_client

pytestmark = pytest.mark.contract


def test_fx_reference_schema_query_response_and_generated_method_are_closed() -> None:
    contract = json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text())
    operation = contract["paths"]["/api/v1/fx-snapshots/{snapshot_id}/observation-references"][
        "get"
    ]
    assert operation["operationId"] == "list_fx_observation_references" and operation["tags"] == [
        "sources"
    ]
    parameters = {x["name"]: x for x in operation["parameters"]}
    assert {name for name, item in parameters.items() if item.get("required")} == {
        "snapshot_id",
        "account_id",
        "base",
        "quote",
        "source_cutoff_at",
    }
    assert parameters["limit"]["schema"]["maximum"] == 25
    assert parameters["limit"]["schema"]["default"] == 25
    assert "effective_at_lte" in parameters and "If-None-Match" in parameters
    schemas = contract["components"]["schemas"]
    page = schemas["FxObservationReferencePage"]
    assert page["additionalProperties"] is False
    assert page["properties"]["items"]["maxItems"] == 25
    assert "effective_at_lte" in page["required"] and "total" not in page["properties"]
    row = schemas["FxObservationReference"]
    assert row["additionalProperties"] is False
    assert set(row["properties"]) == {
        "observation_id",
        "session_date",
        "effective_at",
        "rate",
        "state",
    }
    rendered = render_source_client(contract)
    assert rendered == render_source_client(copy.deepcopy(contract))
    assert rendered.count("async list_fx_observation_references(") == 1
    assert "export const FxObservationReferencePageSchema" in rendered
    assert "z.any(" not in rendered and "z.unknown(" not in rendered
    aggregate = [
        operation
        for methods in contract["paths"].values()
        for operation in methods.values()
        if "aggregate" in operation.get("tags", [])
    ]
    assert len(aggregate) == 6
    assert set(schemas["CreateAggregateRunRequest"]["properties"]) == {
        "fx_bindings",
        "activity_window",
    }
