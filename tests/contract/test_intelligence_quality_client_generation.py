"""Fixed metadata-quality union and shared company schema generation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
from trading212_api_contracts.typescript import (
    TargetClientGenerator,
    render_planning_client,
    render_source_client,
    render_target_client,
)

pytestmark = pytest.mark.contract


def contract() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text()),
    )


def quality_union(value: dict[str, Any]) -> dict[str, Any]:
    schema = value["paths"]["/api/v1/accounts/{account_id}/intelligence-data-quality"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert isinstance(schema, dict)
    return schema


def test_sources_emit_one_fixed_discriminated_quality_read_without_open_values() -> None:
    value = contract()
    generated = render_source_client(value)
    assert generated == render_source_client(copy.deepcopy(value))
    assert generated.count("async get_intelligence_data_quality(") == 1
    assert generated.count("async ") == 16
    assert 'z.discriminatedUnion("state"' in generated
    assert "export const IntelligenceDataQualitySchema" in generated
    assert "export const IntelligenceQualityPermissionRequiredSchema" in generated
    assert "z.any(" not in generated and "z.unknown(" not in generated
    assert "async get_intelligence_data_quality(" not in render_planning_client(value)
    assert "async get_intelligence_data_quality(" not in render_target_client(value)
    permission = value["components"]["schemas"]["IntelligenceQualityPermissionRequired"]
    assert set(permission["properties"]) == {
        "state",
        "account_id",
        "analytics_kind",
        "checked_at",
        "missing_scope",
        "supported_kinds",
    }
    assert permission["additionalProperties"] is False
    metric = value["components"]["schemas"]["IntelligenceMetricQuality"]
    assert not {"value", "amount", "count", "source_ids"} & set(metric["properties"])


@pytest.mark.parametrize("mutation", ["optional", "duplicate", "wrong_mapping", "open", "inline"])
def test_quality_discriminator_rejects_ambiguous_open_or_unbound_branches(mutation: str) -> None:
    value = contract()
    union = quality_union(value)
    first = value["components"]["schemas"]["IntelligenceDataQuality"]
    if mutation == "optional":
        first["required"].remove("state")
    elif mutation == "duplicate":
        value["components"]["schemas"]["IntelligenceQualityPermissionRequired"]["properties"][
            "state"
        ]["const"] = "quality"
    elif mutation == "wrong_mapping":
        union["discriminator"]["mapping"]["quality"] = (
            "#/components/schemas/IntelligenceQualityPermissionRequired"
        )
    elif mutation == "open":
        first["additionalProperties"] = True
    else:
        union["oneOf"][0] = first
    with pytest.raises(ValueError):
        TargetClientGenerator(value, tag="sources").schema(union)


def test_planning_reuses_existing_xray_models_without_duplicate_public_exports() -> None:
    value = contract()
    generated = render_planning_client(value)
    assert 'from "./xray.generated";' in generated
    for name in ("XrayContext", "XrayDimensionSummary", "XrayRatioMetric", "XrayMoneyMetric"):
        assert name + "Schema" in generated
        assert "export const " + name + "Schema" not in generated
    assert "export const PlanningCompanyWeightSchema" in generated
    assert "export const PlanningCompanyBindingSchema" in generated
    assert "async get_effective_exposure(" not in generated
    assert generated.count("async ") == 6


@pytest.mark.parametrize("module", ["./unknown", "https://untrusted.invalid/schema", "../outside"])
def test_generated_shared_imports_remain_a_closed_local_module_set(module: str) -> None:
    with pytest.raises(
        ValueError,
        match=r"^Only existing shared source, X-ray and report schema modules are supported$",
    ):
        TargetClientGenerator(contract(), imported_module=module)
