import json
from dataclasses import replace
from datetime import timedelta
from decimal import ROUND_UP, Decimal, Inexact, Rounded, localcontext
from pathlib import Path
from typing import Any

import pytest
from trading212_analytics.planning import (
    calculate_contribution_plan,
    calculate_drift,
    effective_constraints,
    validate_planning_input,
    verify_contribution_plan_result,
)
from trading212_domain import CurrencyCode, DomainError, Money, QualityState, canonical_json
from trading212_domain.currency_policy import CURRENCY_MINOR_DIGITS, monetary_quantum
from trading212_domain.planning import (
    CoveragePolicy,
    DriftBasis,
    PlanningConstraint,
    PlanningFxRate,
    PlanningHoldingConstraint,
    PlanningMode,
    PlanningSource,
    PlanOutcome,
    ValuationPosition,
)
from trading212_domain.planning_serialization import (
    contribution_plan_result_from_json,
    drift_calculation_from_json,
    planning_input_digest,
    planning_input_from_json,
)
from trading212_domain.targets import TargetConstraint, TargetNode, TargetNodeKind
from trading212_domain.targets import TargetConstraintKind as Kind

from .planning_factories import AT, EUR, oracle_input, planning_input, uid, with_content

pytestmark = pytest.mark.unit
CASES = json.loads(
    (Path(__file__).parents[2] / "fixtures/analytics/planning-oracle-cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda x: x["id"])
def test_independent_rational_exhaustive_oracle(case: dict[str, Any]) -> None:
    value = oracle_input(case)
    result = calculate_contribution_plan(value)
    expected = case["expected"]
    assert result.summary.outcome.value == expected["outcome"], result.summary
    assert result.summary.exhaustive
    assert result.summary.execution_allowed is False
    if result.summary.outcome is PlanOutcome.OPTIMAL:
        assert [x.recommended_amount.amount for x in result.lines] == [
            Decimal(x) for x in expected["allocations"]
        ]
        assert result.summary.residual_cash is not None
        assert result.summary.residual_cash.amount == Decimal(expected["residual_cash"])
        assert result.summary.objective_after is not None
        assert result.summary.objective_after.scores == tuple(
            Decimal(x) for x in expected["scores"]
        )
    else:
        assert result.lines == ()
    verify_contribution_plan_result(value, result)


def test_budget_without_incumbent_does_not_claim_infeasible() -> None:
    value = planning_input(
        ("0", "0"), contribution="1", increments=("0.00000001", "0.3"), grouped=True
    )
    value = replace(value, options=replace(value.options, monetary_quantum=Decimal("0.00000001")))
    value = with_content(
        value,
        replace(
            value.target_content,
            constraints=(
                *value.target_content.constraints,
                TargetConstraint(
                    "mandatory-group",
                    Kind.MINIMUM_GROUP_FUNDING,
                    "G",
                    amount=Decimal(1),
                    currency=EUR,
                ),
            ),
        ),
    )
    result = calculate_contribution_plan(value)
    assert result.summary.outcome is PlanOutcome.UNAVAILABLE
    assert result.summary.context.reason_code == "search_budget_exhausted"
    assert result.summary.attempted_assignments == 100000
    assert result.lines == ()
    verify_contribution_plan_result(value, result)


def test_zero_gap_incumbent_after_budget_is_still_not_proven_optimal() -> None:
    value = planning_input(
        tuple("0" for _ in range(20)),
        tuple("0.05" for _ in range(20)),
        "1",
        increments=tuple("0.01" for _ in range(20)),
    )
    result = calculate_contribution_plan(value)
    assert result.summary.outcome is PlanOutcome.FEASIBLE_NONOPTIMAL
    assert result.summary.attempted_assignments == 100000
    assert result.summary.exhaustive is False
    assert result.summary.objective_after is not None
    assert result.summary.objective_after is not None
    assert result.summary.objective_after.scores == (Decimal(0),)
    assert result.summary.objective_gap is not None
    assert result.summary.objective_gap.scores == (Decimal(0),)
    assert result.summary.bound_kind == "nonnegative_objective_bound"
    verify_contribution_plan_result(value, result)


@pytest.mark.parametrize(
    "contribution,total,expected",
    [
        ("0", "1", PlanOutcome.OPTIMAL),
        ("0", "0", PlanOutcome.UNAVAILABLE),
        ("1", "0", PlanOutcome.OPTIMAL),
    ],
)
def test_zero_amount_and_denominator_are_distinct(
    contribution: str, total: str, expected: PlanOutcome
) -> None:
    result = calculate_contribution_plan(planning_input((total,), ("1",), contribution))
    assert result.summary.outcome is expected
    if total == "0" and expected is PlanOutcome.OPTIMAL:
        assert result.lines[0].current_weight is None
        assert result.lines[0].post_weight == 1


def test_drift_keeps_unclassified_cash_full_denominator_and_identity() -> None:
    value = planning_input(("60",), ("1",), "0", cash="20")
    valuation = replace(
        value.valuation,
        positions=(
            *value.valuation.positions,
            ValuationPosition(uid(900), uid(901), Money(Decimal(20), EUR), QualityState.FRESH),
        ),
        portfolio_total=Money(Decimal(100), EUR),
    )
    value = replace(value, valuation=valuation)
    result = calculate_drift(value)
    holding = next(x for x in result.rows if x.kind == "holding")
    assert holding.actual_direct_weight == Decimal("0.6")
    assert holding.node_id == uid(300) and holding.holding_id == uid(500)
    assert result.totals.unclassified.amount == 20
    assert result.totals.cash is not None
    assert result.totals.cash.amount == 20
    assert result.totals.l1_drift == Decimal("0.4")
    assert result.totals.weighted_squared_drift == Decimal("0.24")
    assert result.context.input_digest == planning_input_digest(validate_planning_input(value))
    effective = calculate_drift(value, basis=DriftBasis.EFFECTIVE)
    assert effective.context.reason_code == "effective_exposure_target_unavailable"
    assert all(x.effective_weight is None for x in effective.rows)


def test_group_product_retains_exact_factors_and_declares_display_residual() -> None:
    value = planning_input(("0", "0", "0"), ("0.2", "0.3", "0.5"), "0")
    nodes = (
        TargetNode("G", None, TargetNodeKind.GROUP, "G", 0, Decimal("0.333333333333333333")),
        TargetNode("H", None, TargetNodeKind.GROUP, "H", 1, Decimal("0.666666666666666667")),
        replace(value.target_content.nodes[0], parent_key="G", weight=Decimal("0.5")),
        replace(value.target_content.nodes[1], parent_key="G", weight=Decimal("0.5")),
        replace(value.target_content.nodes[2], parent_key="H", weight=Decimal(1)),
    )
    value = with_content(value, replace(value.target_content, nodes=nodes))
    result = calculate_drift(value)
    assert result.totals.effective_weight_rounding_residual == Decimal("0.000000000000000001")
    assert next(x.target_weight for x in result.rows if x.key == "target/A") == Decimal(
        "0.166666666666666666"
    )


def test_nonzero_group_holding_cash_drift_matches_independent_reference() -> None:
    # V=100: G=(A=40,B=20), H=(C=20), cash=20. Targets G/H/cash=.4/.4/.2.
    value = planning_input(
        ("40", "20", "20"), ("0.2", "0.2", "0.4"), "0", cash="20", cash_target="0.2"
    )
    a, b, c, cash = value.target_content.nodes
    nodes = (
        TargetNode("G", None, TargetNodeKind.GROUP, "Group G", 0, Decimal("0.4")),
        TargetNode("H", None, TargetNodeKind.GROUP, "Group H", 1, Decimal("0.4")),
        replace(a, parent_key="G", weight=Decimal("0.5")),
        replace(b, parent_key="G", weight=Decimal("0.5")),
        replace(c, parent_key="H", weight=Decimal(1)),
        cash,
    )
    result = calculate_drift(with_content(value, replace(value.target_content, nodes=nodes)))
    expected = {
        "G": ("0.4", "60", "0.6", "0.2", "0.5", "-20"),
        "H": ("0.4", "20", "0.2", "-0.2", "-0.5", "20"),
        "A": ("0.2", "40", "0.4", "0.2", "1", "-20"),
        "B": ("0.2", "20", "0.2", "0", "0", "0"),
        "C": ("0.4", "20", "0.2", "-0.2", "-0.5", "20"),
        "cash": ("0.2", "20", "0.2", "0", "0", "0"),
    }
    for row in result.rows:
        target, amount, weight, signed, relative, gap = map(
            Decimal, expected[row.key.removeprefix("target/")]
        )
        assert row.target_weight == target
        assert row.actual_value == Money(amount, EUR)
        assert row.actual_direct_weight == weight
        assert row.signed_drift == signed
        assert row.absolute_drift == abs(signed)
        assert row.relative_drift == relative
        assert row.monetary_gap == Money(gap, EUR)
    assert result.totals.value == Money(Decimal(100), EUR)
    # Group diagnostics do not double-count the leaf frontier: (.2 + .2)/2=.2; .2²+.2²=.08.
    assert result.totals.l1_drift == Decimal("0.2")
    assert result.totals.weighted_squared_drift == Decimal("0.08")


@pytest.mark.parametrize(
    "kind,group_target,bound,expected,residual,score",
    [
        (Kind.MINIMUM_POST_WEIGHT, "0.2", "0.3", ("3", "3", "4"), "0", "0.015"),
        (Kind.MAXIMUM_POST_WEIGHT, "0.5", "0.4", ("4", "4", "1"), "1", "0.01"),
    ],
)
def test_group_post_weight_uses_full_post_contribution_denominator(
    kind: Kind, group_target: str, bound: str, expected: tuple[str, ...], residual: str, score: str
) -> None:
    # D=20 and C starts at10. Bounds apply to A+B over20, not within-group shares.
    value = planning_input(("0", "0", "10"), ("0.25", "0.25", "0.5"), "10")
    a, b, c = value.target_content.nodes
    nodes = (
        TargetNode("G", None, TargetNodeKind.GROUP, "Group", 0, Decimal(group_target)),
        replace(a, parent_key="G", weight=Decimal("0.5")),
        replace(b, parent_key="G", weight=Decimal("0.5")),
        replace(c, weight=1 - Decimal(group_target)),
    )
    value = with_content(
        value,
        replace(
            value.target_content,
            nodes=nodes,
            constraints=(
                *value.target_content.constraints,
                TargetConstraint("group-weight", kind, "G", weight=Decimal(bound)),
            ),
        ),
    )
    result = calculate_contribution_plan(value)
    assert result.summary.outcome is PlanOutcome.OPTIMAL
    assert tuple(x.recommended_amount.amount for x in result.lines) == tuple(map(Decimal, expected))
    assert result.summary.residual_cash == Money(Decimal(residual), EUR)
    assert result.summary.objective_after is not None
    assert result.summary.objective_after.scores == (Decimal(score),)
    assert sum((x.post_weight for x in result.lines[:2]), Decimal(0)) == Decimal(bound)
    verify_contribution_plan_result(value, result)


def test_unresolved_material_mapping_requires_explicit_exclusion_and_retains_valuation() -> None:
    from trading212_domain.targets import TargetIdentifier, TargetIdentifierKind, TargetMappingState

    value = planning_input()
    a, b = value.target_content.nodes
    assert a.holding is not None
    a = replace(
        a,
        holding=replace(
            a.holding,
            state=TargetMappingState.UNRESOLVED,
            requested_identifier=TargetIdentifier(
                TargetIdentifierKind.PROVIDER_KEY, "pending", "synthetic"
            ),
            reason="Pending explicit owner mapping decision.",
        ),
    )
    value = with_content(value, replace(value.target_content, nodes=(a, b)))
    unavailable = calculate_contribution_plan(value)
    assert unavailable.summary.outcome is PlanOutcome.UNAVAILABLE
    assert unavailable.summary.context.reason_code == "unresolved_material_mapping"
    assert unavailable.lines == ()
    excluded = replace(value, options=replace(value.options, excluded_holding_ids=(uid(500),)))
    result = calculate_contribution_plan(excluded)
    assert result.summary.outcome is PlanOutcome.OPTIMAL
    assert result.summary.unresolved_node_keys == ("A",)
    assert result.summary.excluded_node_keys == ("A",)
    assert result.summary.context.quality is QualityState.PARTIAL
    assert result.summary.context.coverage.unresolved_target_weight == Decimal("0.5")
    assert tuple(x.recommended_amount.amount for x in result.lines) == (Decimal(0), Decimal(20))
    assert result.lines[0].current_value == Money(Decimal(60), EUR)
    assert result.summary.post_total == Money(Decimal(120), EUR)
    assert "unresolved_target_mapping" in {x.code for x in result.summary.context.warnings}
    # An exclusion permits no funding; it cannot turn missing valuation into zero.
    missing = replace(
        excluded,
        valuation=replace(
            excluded.valuation,
            positions=(
                replace(excluded.valuation.positions[0], value=None),
                excluded.valuation.positions[1],
            ),
        ),
    )
    assert calculate_contribution_plan(missing).summary.outcome is PlanOutcome.UNAVAILABLE


@pytest.mark.parametrize(
    "case",
    (
        "group",
        "reserve",
        "holding",
        "capacity",
        "mandatory",
        "cardinality",
        "budget",
        "grid",
        "activation",
        "grid_capacity",
        "request_reserve",
    ),
)
def test_infeasibility_proof_names_only_supporting_constraints(case: str) -> None:
    value = planning_input(("0", "0"), contribution="10", grouped=True)
    constraints: tuple[TargetConstraint, ...]
    expected: tuple[str, ...]
    if case == "group":
        constraints = (
            TargetConstraint(
                "group-min", Kind.MINIMUM_GROUP_FUNDING, "G", amount=Decimal(11), currency=EUR
            ),
        )
        expected = ("group-min",)
    elif case in {"reserve", "request_reserve"}:
        constraints = (
            TargetConstraint(
                "reserve",
                Kind.CASH_RESERVE,
                amount=Decimal(11 if case == "reserve" else 5),
                currency=EUR,
            ),
        )
        expected = ("reserve",) if case == "reserve" else ()
        if case == "request_reserve":
            value = replace(value, options=replace(value.options, cash_reserve=Decimal(11)))
    elif case == "holding":
        value = planning_input(("60", "40"), contribution="20", grouped=True)
        constraints = (
            TargetConstraint("holding-cap", Kind.MAXIMUM_POST_WEIGHT, "A", weight=Decimal("0.4")),
            TargetConstraint(
                "unused-minimum",
                Kind.MINIMUM_FUNDED_AMOUNT,
                "A",
                amount=Decimal(1000),
                currency=EUR,
            ),
        )
        expected = ("holding-cap",)
    elif case == "capacity":
        constraints = (
            TargetConstraint(
                "group-min", Kind.MINIMUM_GROUP_FUNDING, "G", amount=Decimal(5), currency=EUR
            ),
            TargetConstraint("cap-A", Kind.MAXIMUM_POST_WEIGHT, "A", weight=Decimal("0.2")),
            TargetConstraint("cap-B", Kind.MAXIMUM_POST_WEIGHT, "B", weight=Decimal("0.2")),
        )
        expected = ("cap-A", "cap-B", "group-min")
    elif case == "grid":
        value = planning_input(("0", "0"), contribution="10", increments=("3", "1"), grouped=True)
        constraints = (
            TargetConstraint("min-A", Kind.MINIMUM_POST_WEIGHT, "A", weight=Decimal("0.21")),
            TargetConstraint("cap-A", Kind.MAXIMUM_POST_WEIGHT, "A", weight=Decimal("0.29")),
            TargetConstraint(
                "unused-minimum", Kind.MINIMUM_FUNDED_AMOUNT, "A", amount=Decimal(1), currency=EUR
            ),
        )
        expected = ("cap-A", "min-A", "step-A")
    elif case in {"activation", "grid_capacity"}:
        value = planning_input(
            ("0", "0"),
            contribution="10",
            increments=("11" if case == "grid_capacity" else "1", "1"),
            grouped=True,
        )
        constraints = (
            TargetConstraint(
                "minimum-A",
                Kind.MINIMUM_FUNDED_AMOUNT,
                "A",
                amount=Decimal(11 if case == "activation" else 1),
                currency=EUR,
            ),
            TargetConstraint("eligible-B", Kind.ELIGIBLE, "B", enabled=False),
            TargetConstraint(
                "group-min", Kind.MINIMUM_GROUP_FUNDING, "G", amount=Decimal(1), currency=EUR
            ),
        )
        expected = ("eligible-B", "group-min", "minimum-A" if case == "activation" else "step-A")
    elif case == "mandatory":
        constraints = (
            TargetConstraint("min-A", Kind.MINIMUM_POST_WEIGHT, "A", weight=Decimal("0.6")),
            TargetConstraint(
                "group-max", Kind.MAXIMUM_GROUP_FUNDING, "G", amount=Decimal(5), currency=EUR
            ),
        )
        expected = ("group-max", "min-A")
    else:
        constraints = (
            TargetConstraint(
                "min-A",
                Kind.MINIMUM_POST_WEIGHT,
                "A",
                weight=Decimal("0.6" if case == "budget" else "0.2"),
            ),
            TargetConstraint(
                "min-B",
                Kind.MINIMUM_POST_WEIGHT,
                "B",
                weight=Decimal("0.6" if case == "budget" else "0.2"),
            ),
            TargetConstraint(
                "lines", Kind.MAXIMUM_FUNDED_LINES, count=1 if case == "cardinality" else 2
            ),
        )
        expected = ("lines", "min-A", "min-B") if case == "cardinality" else ("min-A", "min-B")
    value = with_content(
        value,
        replace(
            value.target_content,
            constraints=(
                *value.target_content.constraints,
                *constraints,
                TargetConstraint("unrelated-priority", Kind.PRIORITY, "B", coefficient=Decimal(2)),
            ),
        ),
    )
    result = calculate_contribution_plan(value)
    assert result.summary.outcome is PlanOutcome.INFEASIBLE
    assert result.summary.context.reason_code == "proved_constraint_contradiction"
    assert result.summary.explanations[0].constraint_keys == expected
    assert result.summary.explanations[0].code == "proved_constraint_contradiction"
    assert result.lines == ()
    verify_contribution_plan_result(value, result)
    reversed_input = replace(
        value,
        target_content=replace(
            value.target_content, constraints=tuple(reversed(value.target_content.constraints))
        ),
    )
    assert calculate_contribution_plan(reversed_input) == result
    forged = replace(
        result,
        summary=replace(
            result.summary,
            explanations=(
                replace(
                    result.summary.explanations[0],
                    constraint_keys=(*expected, "unrelated-priority"),
                ),
            ),
        ),
    )
    with pytest.raises(DomainError, match="independent verification"):
        verify_contribution_plan_result(value, forged)


def test_maximum_funded_lines_and_group_bounds_are_joint_hard_constraints() -> None:
    value = planning_input(("0", "0"), ("0.5", "0.5"), "10", grouped=True)
    constraints = (
        *value.target_content.constraints,
        TargetConstraint(
            "group-min", Kind.MINIMUM_GROUP_FUNDING, "G", amount=Decimal(9), currency=EUR
        ),
        TargetConstraint(
            "group-max", Kind.MAXIMUM_GROUP_FUNDING, "G", amount=Decimal(9), currency=EUR
        ),
        TargetConstraint("lines", Kind.MAXIMUM_FUNDED_LINES, count=1),
    )
    value = with_content(value, replace(value.target_content, constraints=constraints))
    result = calculate_contribution_plan(value)
    assert result.summary.outcome is PlanOutcome.OPTIMAL
    assert tuple(x.recommended_amount.amount for x in result.lines) == (Decimal(0), Decimal(9))
    assert result.summary.residual_cash is not None
    assert result.summary.residual_cash.amount == 1
    forged = replace(
        result,
        lines=(
            replace(result.lines[0], recommended_amount=Money(Decimal(1), EUR)),
            result.lines[1],
        ),
    )
    with pytest.raises(DomainError, match="independent verification"):
        verify_contribution_plan_result(value, forged)


def test_cash_only_preserves_input_gates_and_group_constraints() -> None:
    value = planning_input(("0",), ("1",), "10", mode=PlanningMode.CASH_ONLY, grouped=True)
    value = with_content(
        value,
        replace(
            value.target_content,
            constraints=(
                *value.target_content.constraints,
                TargetConstraint(
                    "group-min", Kind.MINIMUM_GROUP_FUNDING, "G", amount=Decimal(1), currency=EUR
                ),
            ),
        ),
    )
    assert calculate_contribution_plan(value).summary.outcome is PlanOutcome.INFEASIBLE
    missing = replace(
        value,
        valuation=replace(
            value.valuation, positions=(replace(value.valuation.positions[0], value=None),)
        ),
    )
    assert calculate_contribution_plan(missing).summary.outcome is PlanOutcome.UNAVAILABLE


def test_missing_future_and_valid_fx_are_distinct_and_not_double_applied() -> None:
    value = planning_input(("10",), ("1",), "2")
    source = PlanningSource("provider_fx_observation", uid(950), "b" * 64, "1", AT, AT)
    rate = PlanningFxRate(source, CurrencyCode("USD"), EUR, Decimal("0.5"))
    foreign = replace(
        value.valuation.positions[0], value=Money(Decimal(20), CurrencyCode("USD")), fx=rate
    )
    fixed = replace(
        value,
        valuation=replace(
            value.valuation, positions=(foreign,), sources=(*value.valuation.sources, source)
        ),
    )
    assert calculate_contribution_plan(fixed).summary.outcome is PlanOutcome.OPTIMAL
    assert calculate_contribution_plan(value).lines[0].current_value.amount == 10
    missing = replace(
        fixed, valuation=replace(fixed.valuation, positions=(replace(foreign, fx=None),))
    )
    assert calculate_contribution_plan(missing).summary.context.reason_code == "missing_fx"
    future = replace(
        foreign,
        fx=replace(rate, source=replace(source, first_observed_at=AT + timedelta(seconds=1))),
    )
    assert future.fx is not None
    assert (
        calculate_contribution_plan(
            replace(
                fixed,
                valuation=replace(
                    fixed.valuation,
                    positions=(future,),
                    sources=(*value.valuation.sources, future.fx.source),
                ),
            )
        ).summary.context.reason_code
        == "source_after_cutoff"
    )


def test_explicit_later_target_is_disclosed_and_pinned() -> None:
    value = planning_input()
    newer = replace(value, target_published_at=AT + timedelta(days=1))
    result = calculate_contribution_plan(newer)
    assert result.summary.outcome is PlanOutcome.OPTIMAL
    assert "explicit_later_target" in {x.code for x in result.summary.context.warnings}
    assert planning_input_digest(value) != planning_input_digest(newer)


def test_degraded_policy_cannot_invent_missing_money() -> None:
    value = planning_input()
    degraded = replace(value, valuation=replace(value.valuation, quality=QualityState.STALE))
    assert calculate_contribution_plan(degraded).summary.outcome is PlanOutcome.UNAVAILABLE
    permitted = replace(
        degraded, options=replace(degraded.options, coverage_policy=CoveragePolicy.ALLOW_DEGRADED)
    )
    result = calculate_contribution_plan(permitted)
    assert result.summary.outcome is PlanOutcome.OPTIMAL
    assert result.summary.context.quality is not QualityState.FRESH
    missing = replace(permitted, valuation=replace(permitted.valuation, portfolio_total=None))
    assert calculate_contribution_plan(missing).summary.outcome is PlanOutcome.UNAVAILABLE


def test_default_currency_quantum_and_explicit_tightening_are_versioned() -> None:
    assert len(CURRENCY_MINOR_DIGITS) == 165
    for code, quantum in (("EUR", "0.01"), ("JPY", "1"), ("KWD", "0.001"), ("CLF", "0.0001")):
        assert monetary_quantum(CurrencyCode(code)) == Decimal(quantum)
    assert monetary_quantum(CurrencyCode("XAU")) is None
    assert monetary_quantum(CurrencyCode("ZZZ"), Decimal("0.0001")) is None
    with pytest.raises(DomainError):
        monetary_quantum(EUR, Decimal("0.1"))
    with pytest.raises(DomainError):
        monetary_quantum(EUR, Decimal("0.005"))
    value = planning_input(contribution="0.005")
    with pytest.raises(DomainError, match="quantum"):
        validate_planning_input(value)
    value = replace(value, options=replace(value.options, monetary_quantum=Decimal("0.001")))
    assert calculate_contribution_plan(value).summary.outcome is PlanOutcome.OPTIMAL


def test_overrides_use_holding_ids_and_cannot_relax_or_duplicate_published_constraints() -> None:
    value = planning_input()
    composite = PlanningHoldingConstraint(uid(500), Decimal(2), Decimal(2), Decimal("0.5"))
    value = replace(value, options=replace(value.options, holding_constraints=(composite,)))
    assert len(effective_constraints(value)) == 4
    assert calculate_contribution_plan(value).summary.outcome is PlanOutcome.OPTIMAL
    with pytest.raises(DomainError):
        validate_planning_input(
            replace(value, options=replace(value.options, excluded_holding_ids=(uid(300),)))
        )
    with pytest.raises(DomainError, match="grid"):
        validate_planning_input(
            replace(
                value,
                options=replace(
                    value.options,
                    holding_constraints=(replace(composite, value_increment=Decimal("0.5")),),
                ),
            )
        )
    duplicate = PlanningConstraint(
        "other", Kind.AMOUNT_INCREMENT, uid(300), amount=Decimal(2), currency=EUR
    )
    with pytest.raises(DomainError, match="unique scope"):
        validate_planning_input(
            replace(value, options=replace(value.options, allocation_constraints=(duplicate,)))
        )


def test_serialization_roundtrip_closed_types_and_ambient_decimal_independence() -> None:
    value = planning_input()
    result = calculate_contribution_plan(value)
    assert planning_input_from_json(canonical_json(value)) == value
    assert contribution_plan_result_from_json(canonical_json(result)) == result
    assert drift_calculation_from_json(canonical_json(calculate_drift(value))) == calculate_drift(
        value
    )
    with localcontext() as context:
        context.prec = 5
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        assert calculate_contribution_plan(value) == result
    payload = json.loads(canonical_json(value))
    payload["options"]["contribution"]["amount"] = 20.0
    with pytest.raises(DomainError):
        planning_input_from_json(json.dumps(payload))
    marker = "_".join(("PLANNING", "PRIVATE", "CANARY"))
    payload[marker] = marker
    with pytest.raises(DomainError) as failure:
        planning_input_from_json(json.dumps(payload))
    assert marker not in str(failure.value)


def test_missing_cash_observation_is_not_zero_cash() -> None:
    value = planning_input()
    value = replace(value, valuation=replace(value.valuation, cash_components=()))
    result = calculate_contribution_plan(value)
    assert result.summary.outcome is PlanOutcome.UNAVAILABLE
    assert result.summary.current_cash is None
    assert result.summary.context.reason_code == "missing_cash_valuation"


def test_aggregate_overflow_is_rejected_before_request_persistence() -> None:
    value = planning_input(("99999999999999999999",), ("1",), "1")
    with pytest.raises(DomainError, match="NUMERIC"):
        validate_planning_input(value)


def test_tiny_effective_target_can_make_only_relative_drift_unrepresentable() -> None:
    value = planning_input(("1", "0"), ("0.5", "0.5"), "0")
    nodes = (
        TargetNode("G", None, TargetNodeKind.GROUP, "G", 0, Decimal("0.000000000000000001")),
        replace(
            value.target_content.nodes[0], parent_key="G", weight=Decimal("0.000000000000000001")
        ),
        replace(
            value.target_content.nodes[1], parent_key="G", weight=Decimal("0.999999999999999999")
        ),
        TargetNode("cash", None, TargetNodeKind.CASH, "Cash", 1, Decimal("0.999999999999999999")),
    )
    value = with_content(value, replace(value.target_content, nodes=nodes))
    result = calculate_drift(value)
    row = next(x for x in result.rows if x.key == "target/A")
    assert row.actual_value is not None
    assert row.actual_value.amount == 1
    assert row.absolute_drift is not None
    assert row.relative_drift is None
    assert row.relative_drift_reason == "numeric_range_exceeded"


def test_snapshot_creation_time_is_real_provenance_and_does_not_admit_future_observations() -> None:
    value = planning_input()
    source = replace(value.valuation.sources[0], first_observed_at=AT + timedelta(seconds=10))
    value = replace(value, valuation=replace(value.valuation, sources=(source,)))
    result = calculate_contribution_plan(value)
    assert result.summary.outcome is PlanOutcome.OPTIMAL
    assert source in result.summary.context.sources
    future = PlanningSource(
        "provider_observation", uid(999), "c" * 64, "1", AT, AT + timedelta(seconds=1)
    )
    value = replace(value, valuation=replace(value.valuation, sources=(source, future)))
    assert calculate_contribution_plan(value).summary.context.reason_code == "source_after_cutoff"
    with pytest.raises(DomainError, match="snapshot reference"):
        replace(value.valuation, sources=())


def test_full_256_composite_rows_expand_without_artificial_85_holding_limit() -> None:
    from uuid import UUID

    from trading212_domain.planning import PlanningNodeIdentity
    from trading212_domain.targets import (
        TargetCatalog,
        TargetHoldingMapping,
        TargetInstrumentReference,
        TargetListingReference,
        TargetMappingState,
    )

    value = planning_input(("0",), ("1",), "0", cash="1")
    nodes = tuple(
        TargetNode(
            str(i).zfill(3),
            None,
            TargetNodeKind.HOLDING,
            "Holding",
            i,
            Decimal("0.00390625"),
            TargetHoldingMapping(
                TargetMappingState.RESOLVED, UUID(int=10000 + i), UUID(int=20000 + i)
            ),
        )
        for i in range(256)
    )
    value = with_content(value, replace(value.target_content, nodes=nodes, constraints=()))
    value = replace(
        value,
        node_identities=tuple(
            PlanningNodeIdentity(uid(30000 + i), n.key, uid(40000 + i)) for i, n in enumerate(nodes)
        ),
        catalog=TargetCatalog(
            tuple(TargetInstrumentReference(UUID(int=10000 + i)) for i in range(256)),
            tuple(
                TargetListingReference(UUID(int=20000 + i), UUID(int=10000 + i)) for i in range(256)
            ),
        ),
        options=replace(
            value.options,
            holding_constraints=tuple(
                PlanningHoldingConstraint(uid(40000 + i), Decimal(0), Decimal("0.01"), Decimal(1))
                for i in range(256)
            ),
        ),
    )
    assert len(effective_constraints(value)) == 768
    assert calculate_contribution_plan(value).summary.outcome is PlanOutcome.OPTIMAL


def test_examined_moves_cap_counts_invalid_attempts_and_retains_bounded_outcome() -> None:
    value = planning_input(("0", "0"), ("0.9", "0.1"), "100", increments=("1", "0.001"))
    value = replace(value, options=replace(value.options, monetary_quantum=Decimal("0.001")))
    value = with_content(
        value,
        replace(
            value.target_content,
            constraints=(
                *value.target_content.constraints,
                TargetConstraint(
                    "minimum", Kind.MINIMUM_FUNDED_AMOUNT, "A", amount=Decimal(1000), currency=EUR
                ),
            ),
        ),
    )
    result = calculate_contribution_plan(value)
    assert result.summary.outcome is PlanOutcome.FEASIBLE_NONOPTIMAL
    assert result.summary.examined_moves == 10000
    assert result.summary.attempted_assignments == 100000
    assert not result.summary.exhaustive


def test_zero_funded_lines_and_zero_contribution_do_not_need_arbitrary_listing_choice() -> None:
    from uuid import UUID

    from trading212_domain.targets import TargetListingReference

    value = planning_input(("1",), ("1",), "1")
    assert value.target_content.nodes[0].holding is not None
    node = replace(
        value.target_content.nodes[0],
        holding=replace(value.target_content.nodes[0].holding, listing_id=None),
    )
    value = with_content(value, replace(value.target_content, nodes=(node,)))
    value = replace(
        value,
        catalog=replace(
            value.catalog,
            listings=(
                *value.catalog.listings,
                TargetListingReference(UUID(int=250), UUID(int=100)),
            ),
        ),
    )
    assert (
        calculate_contribution_plan(value).summary.context.reason_code == "listing_choice_required"
    )
    zero = replace(value, options=replace(value.options, contribution=Money(Decimal(0), EUR)))
    assert calculate_contribution_plan(zero).summary.outcome is PlanOutcome.OPTIMAL
    zero_lines = with_content(
        value,
        replace(
            value.target_content,
            constraints=(
                *value.target_content.constraints,
                TargetConstraint("none", Kind.MAXIMUM_FUNDED_LINES, count=0),
            ),
        ),
    )
    result = calculate_contribution_plan(zero_lines)
    assert result.summary.outcome is PlanOutcome.OPTIMAL
    assert result.summary.residual_cash is not None
    assert result.summary.residual_cash.amount == 1
    assert result.summary.attempted_assignments == 0


def test_listing_exclusion_applies_to_auto_funding_choice_for_instrument_wide_leaf() -> None:
    from uuid import UUID

    from trading212_domain.targets import TargetExclusion, TargetListingReference

    value = planning_input(("1",), ("1",), "1")
    assert value.target_content.nodes[0].holding is not None
    node = replace(
        value.target_content.nodes[0],
        holding=replace(value.target_content.nodes[0].holding, listing_id=None),
    )
    value = with_content(
        value,
        replace(
            value.target_content,
            nodes=(node,),
            exclusions=(TargetExclusion("excluded", listing_id=UUID(int=200)),),
        ),
    )
    value = replace(
        value,
        catalog=replace(
            value.catalog,
            listings=(
                *value.catalog.listings,
                TargetListingReference(UUID(int=250), UUID(int=100)),
            ),
        ),
    )
    result = calculate_contribution_plan(value)
    assert result.summary.outcome is PlanOutcome.OPTIMAL
    assert result.lines[0].listing_id == uid(250)
    assert result.lines[0].recommended_amount.amount == 1


def test_priority_changes_the_discrete_objective_without_changing_hard_domain() -> None:
    value = planning_input(("0", "0"), ("0.5", "0.5"), "20", increments=("15", "15"))
    baseline = calculate_contribution_plan(value)
    assert tuple(x.recommended_amount.amount for x in baseline.lines) == (Decimal(0), Decimal(15))
    value = with_content(
        value,
        replace(
            value.target_content,
            constraints=(
                *value.target_content.constraints,
                TargetConstraint("priority", Kind.PRIORITY, "A", coefficient=Decimal(4)),
            ),
        ),
    )
    result = calculate_contribution_plan(value)
    assert tuple(x.recommended_amount.amount for x in result.lines) == (Decimal(15), Decimal(0))
    assert result.summary.objective_after is not None
    assert result.summary.objective_after.scores == (Decimal("0.5625"),)


def test_internal_solver_failure_never_returns_apparent_recommendations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trading212_analytics import _contribution_solver

    def broken(_: object) -> None:
        raise ArithmeticError("_".join(("PRIVATE", "SOLVER", "CANARY")))

    monkeypatch.setattr(_contribution_solver, "solve", broken)
    result = calculate_contribution_plan(planning_input())
    assert result.summary.outcome is PlanOutcome.FAILED
    assert result.summary.context.reason_code == "internal_calculation_failure"
    assert result.lines == ()
    assert "_".join(("PRIVATE", "SOLVER", "CANARY")) not in canonical_json(result)
