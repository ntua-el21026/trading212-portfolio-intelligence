"""Generated target clients remain closed, bounded and tied to actual API operations."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
from trading212_api_contracts.typescript import TargetClientGenerator, render_target_client

pytestmark = pytest.mark.contract


@pytest.fixture
def contract() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text()),
    )


def test_generated_operations_match_all_target_routes_deterministically(
    contract: dict[str, Any],
) -> None:
    rendered = render_target_client(contract)
    operations = [
        operation["operationId"]
        for methods in contract["paths"].values()
        for operation in methods.values()
        if "targets" in operation.get("tags", [])
    ]
    assert len(operations) == 15
    assert all(f"async {name}(" in rendered for name in operations)
    assert rendered == render_target_client(copy.deepcopy(contract))
    assert "z.any(" not in rendered and "z.unknown(" not in rendered
    assert "z.strictObject(" in rendered
    assert "encodeURIComponent(" in rendered


@pytest.mark.parametrize(
    "keyword", ["oneOf", "allOf", "patternProperties", "unevaluatedProperties"]
)
def test_generator_rejects_unsupported_validation_keywords(
    contract: dict[str, Any], keyword: str
) -> None:
    with pytest.raises(ValueError, match="Unsupported target schema fields"):
        TargetClientGenerator(contract).schema({"type": "string", keyword: {}})


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "additionalProperties": True},
        {"type": "object"},
        {"$ref": "https://untrusted.invalid/schema"},
        {"type": "string", "format": "unknown"},
        {"enum": [1, 2]},
        {},
    ],
)
def test_generator_never_silently_accepts_open_or_unrecognized_shapes(
    contract: dict[str, Any], schema: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        TargetClientGenerator(contract).schema(schema)


def test_generator_rejects_recursive_content_before_emitting_types(
    contract: dict[str, Any],
) -> None:
    contract["components"]["schemas"]["RecursiveTarget"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"child": {"$ref": "#/components/schemas/RecursiveTarget"}},
    }
    with pytest.raises(ValueError, match="Recursive"):
        TargetClientGenerator(contract).reference("#/components/schemas/RecursiveTarget")


def test_financial_fields_are_generated_as_bounded_strings(contract: dict[str, Any]) -> None:
    generator = TargetClientGenerator(contract)
    generator.reference("#/components/schemas/TargetNode")
    weight = contract["components"]["schemas"]["TargetNode"]["properties"]["weight"]
    assert weight["type"] == "string"
    assert "{0,19}" in weight["pattern"]
    assert "{1,18}" in weight["pattern"]
    assert "z.string().regex(" in generator.schema(weight)
