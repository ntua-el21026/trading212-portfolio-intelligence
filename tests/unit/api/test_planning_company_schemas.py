"""Closed inputs and lossless company-cell transport."""

from dataclasses import replace
from uuid import UUID

import pytest
from pydantic import ValidationError
from trading212_analytics.planning import calculate_drift
from trading212_api_contracts import planning as wire
from trading212_application.xray_projection import xray_public_primitive
from trading212_domain.planning_company import company_row_view

from tests.unit.analytics.planning_company_factories import company_inputs, project
from tests.unit.api.test_planning_schemas import BODY

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("schema", [wire.ActualVsTargetQuery, wire.DriftAnalysisQuery])
def test_optional_selected_run_is_strict_and_does_not_enable_plan_postweights(
    schema: type[wire.ActualVsTargetQuery] | type[wire.DriftAnalysisQuery],
) -> None:
    query = {key: BODY[key] for key in ("snapshot_id", "virtual_portfolio_id", "target_version_id")}
    query["reporting_currency"] = "EUR"
    assert schema.model_validate(query).xray_run_id is None
    query["xray_run_id"] = str(UUID(int=9001))
    assert schema.model_validate(query).xray_run_id == query["xray_run_id"]
    for invalid in (True, 42, "latest", "", "wrong-private-run"):
        with pytest.raises(ValidationError):
            schema.model_validate({**query, "xray_run_id": invalid})
    with pytest.raises(ValidationError):
        schema.model_validate({**query, "company_target_weight": "0.4"})
    with pytest.raises(ValidationError):
        wire.CreateContributionPlanRequest.model_validate(
            {**BODY, "xray_run_id": query["xray_run_id"]}
        )


def company_row() -> wire.PlanningDriftRow:
    planning, value = company_inputs()
    cell = next(row for row in project(planning, value).weights if row.row_key == "target/A")
    row = next(row for row in calculate_drift(planning).rows if row.key == cell.row_key)
    payload = xray_public_primitive(company_row_view(row, cell))
    return wire.PlanningDriftRow.model_validate(payload)


def test_company_cell_preserves_exact_decimal_and_bounded_full_source_counts() -> None:
    planning, value = company_inputs()
    cell = next(row for row in project(planning, value).weights if row.row_key == "target/A")
    assert cell.metric is not None
    references = tuple(UUID(int=index) for index in range(1000, 1065))
    # This alteration tests DTO projection only, not a claim about calculator output.
    metric = replace(cell.metric, source_reference_ids=references)
    rendered = xray_public_primitive(replace(cell, metric=metric))
    checked = wire.PlanningCompanyWeight.model_validate(rendered)
    assert checked.metric is not None and checked.metric.value == "0.56"
    assert len(checked.metric.source_reference_ids) == 64
    assert checked.metric.source_count == 65 and checked.metric.source_omitted_count == 1
    assert "exact_buckets" not in checked.model_dump_json()


@pytest.mark.parametrize(
    "location", ["float", "scope", "echo", "count", "duplicate", "proof", "unavailable"]
)
def test_inconsistent_or_unbounded_company_cell_is_rejected(location: str) -> None:
    payload = company_row().model_dump(mode="json")
    cell = payload["company"]
    if location == "float":
        cell["metric"]["value"] = 0.56
    elif location == "scope":
        cell["row_key"] = "target/another"
    elif location == "echo":
        payload["effective_weight"] = "0.95"
    elif location == "count":
        cell["path_count"] += 1
    elif location == "duplicate":
        cell["path_keys"] *= 2
        cell["path_count"] *= 2
    elif location == "proof":
        cell["proof_digest"] = None
    else:
        cell["reason"] = "company_identity_unavailable"
    with pytest.raises(ValidationError):
        wire.PlanningDriftRow.model_validate(payload)
