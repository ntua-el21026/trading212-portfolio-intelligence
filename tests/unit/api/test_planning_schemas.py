"""Financial and closed nested planning request boundaries."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError
from trading212_api_contracts.planning import (
    CreateContributionPlanRequest,
    McpCreateContributionPlanRequest,
    PlanningConstraint,
    PlanningObjective,
)

ACCOUNT = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee"
PORTFOLIO = "aef0bdf3-3613-4cfe-b15f-bc1f8b9c4119"
TARGET = "19a8b590-9c18-4c43-8dce-d622cb6ae033"
SNAPSHOT = "5dd1049e-7433-43f4-bf5b-3a73c24c0568"
NODE = "41bd2bac-3ec0-4887-8d9b-6a7d882ee26b"
BODY: dict[str, Any] = {
    "account_id": ACCOUNT,
    "virtual_portfolio_id": PORTFOLIO,
    "target_version_id": TARGET,
    "snapshot_id": SNAPSHOT,
    "contribution": {"amount": "10", "currency": "EUR"},
    "mode": "global",
}


@pytest.mark.parametrize(
    "amount",
    [1, 1.5, True, None, "-1", "1e2", "+1", "01", "NaN", "Infinity", "1" * 21, "0." + "1" * 19],
)
def test_planning_money_rejects_unsafe_or_negative_inputs(amount: object) -> None:
    body = copy.deepcopy(BODY)
    body["contribution"]["amount"] = amount
    with pytest.raises(ValidationError):
        CreateContributionPlanRequest.model_validate(body)


@pytest.mark.parametrize(
    "amount", ["0", "0.000000000000000001", "99999999999999999999.999999999999999999"]
)
def test_planning_money_preserves_exact_financial_strings(amount: str) -> None:
    body = copy.deepcopy(BODY)
    body["contribution"]["amount"] = amount
    assert CreateContributionPlanRequest.model_validate(body).contribution.amount == amount


@pytest.mark.parametrize("location", ["root", "money", "listing", "constraint"])
def test_nested_unknown_field_names_and_values_are_not_reflected(location: str) -> None:
    canary = "planning-private-unknown-key"
    body = copy.deepcopy(BODY)
    if location == "money":
        body["contribution"][canary] = canary
    elif location == "listing":
        body["listing_preferences"] = [{"holding_id": NODE, "listing_id": TARGET, canary: canary}]
    elif location == "constraint":
        body["allocation_constraints"] = [
            {
                "key": "min",
                "kind": "minimum_funded_amount",
                "node_id": NODE,
                "amount": "0",
                "currency": "EUR",
                canary: canary,
            }
        ]
    else:
        body[canary] = canary
    with pytest.raises(ValidationError) as caught:
        CreateContributionPlanRequest.model_validate(body)
    assert canary not in str(caught.value)


@pytest.mark.parametrize(
    "override",
    [
        {"eligible_holding_ids": [NODE, NODE]},
        {"eligible_holding_ids": [NODE], "excluded_holding_ids": [NODE]},
        {"mode": "restricted"},
        {"mode": "global", "restricted_group_ids": [NODE]},
        {"cash_reserve": "-0.01"},
        {"monetary_quantum": "0"},
        {"monetary_quantum": "0.05"},
        {"listing_preferences": [{"holding_id": NODE, "listing_id": TARGET}] * 2},
    ],
)
def test_planning_selection_and_quantum_are_explicit(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CreateContributionPlanRequest.model_validate({**BODY, **override})


def test_constraint_variants_reject_unused_fields_and_preserve_minimum_semantics() -> None:
    value = {
        "key": "minimum",
        "kind": "minimum_funded_amount",
        "node_id": NODE,
        "amount": "0",
        "currency": "EUR",
    }
    assert PlanningConstraint.model_validate(value).amount == "0"
    with pytest.raises(ValidationError):
        PlanningConstraint.model_validate({**value, "enabled": True})
    with pytest.raises(ValidationError):
        PlanningConstraint.model_validate({**value, "kind": "amount_increment"})


def test_mcp_subset_is_closed_and_bounded_independently_of_api_variants() -> None:
    body = {
        **BODY,
        "idempotency_key": "plan:one",
        "allocation_constraints": [
            {
                "holding_id": NODE,
                "minimum_amount": "0",
                "value_increment": "0.01",
                "maximum_post_weight": "1",
            }
        ],
    }
    assert McpCreateContributionPlanRequest.model_validate(body).idempotency_key == "plan:one"
    with pytest.raises(ValidationError):
        CreateContributionPlanRequest.model_validate(body)
    with pytest.raises(ValidationError):
        McpCreateContributionPlanRequest.model_validate(
            {**body, "allocation_constraints": body["allocation_constraints"] * 257}
        )


def test_hierarchical_objective_accepts_eight_frontiers_plus_leaf_score() -> None:
    objective = {
        "scores": ["0"] * 9,
        "quantum": "0.000000000000000001",
        "rounding": "ROUND_HALF_EVEN",
        "rounding_error_bound": "half_quantum",
    }
    assert len(PlanningObjective.model_validate(objective).scores) == 9
    with pytest.raises(ValidationError):
        PlanningObjective.model_validate({**objective, "scores": ["0"] * 10})
