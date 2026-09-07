from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from itertools import product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from trading212_analytics.planning import (
    calculate_contribution_plan,
    verify_contribution_plan_result,
)
from trading212_domain.planning import PlanningMode, PlanOutcome
from trading212_domain.planning_serialization import planning_input_digest
from trading212_domain.targets import TargetConstraint, TargetNode, TargetNodeKind
from trading212_domain.targets import TargetConstraintKind as Kind

from tests.unit.analytics.planning_factories import EUR, planning_input, uid, with_content

pytestmark = pytest.mark.property


def rational_quantize(value: Fraction) -> Decimal:
    scaled = value * 10**18
    integer, remainder = divmod(scaled.numerator, scaled.denominator)
    if 2 * remainder > scaled.denominator or (2 * remainder == scaled.denominator and integer % 2):
        integer += 1
    return Decimal(integer).scaleb(-18)


@given(
    a=st.integers(0, 30),
    b=st.integers(0, 30),
    contribution=st.integers(1, 12),
    step_a=st.integers(1, 5),
    step_b=st.integers(1, 5),
    cash=st.integers(0, 10),
)
@settings(max_examples=80, deadline=None)
def test_discrete_global_optimum_matches_independent_rational_enumeration(
    a: int, b: int, contribution: int, step_a: int, step_b: int, cash: int
) -> None:
    value = planning_input(
        (str(a), str(b)),
        contribution=str(contribution),
        increments=(str(step_a), str(step_b)),
        cash=str(cash),
    )
    result = calculate_contribution_plan(value)
    denominator = a + b + cash + contribution
    candidates = []
    for x, y in product(range(0, contribution + 1, step_a), range(0, contribution + 1, step_b)):
        if x + y <= contribution:
            residual = contribution - x - y
            score = (
                (Fraction(a + x, denominator) - Fraction(1, 2)) ** 2
                + (Fraction(b + y, denominator) - Fraction(1, 2)) ** 2
                + Fraction(cash + residual, denominator) ** 2
            )
            candidates.append(
                (rational_quantize(score), Decimal(residual), (Decimal(x), Decimal(y)))
            )
    expected = min(candidates)
    assert result.summary.outcome is PlanOutcome.OPTIMAL
    assert result.summary.objective_after is not None
    assert result.summary.objective_after.scores == (expected[0],)
    assert result.summary.residual_cash is not None
    assert result.summary.residual_cash.amount == expected[1]
    assert tuple(line.recommended_amount.amount for line in result.lines) == expected[2]
    verify_contribution_plan_result(value, result)


@given(a=st.integers(0, 50), b=st.integers(0, 50), contribution=st.integers(1, 15))
@settings(max_examples=35, deadline=None)
def test_permutations_preserve_hash_and_result_and_exact_conservation(
    a: int, b: int, contribution: int
) -> None:
    value = planning_input((str(a), str(b)), contribution=str(contribution))
    shuffled = replace(
        value,
        valuation=replace(value.valuation, positions=tuple(reversed(value.valuation.positions))),
        target_content=replace(
            value.target_content,
            nodes=tuple(reversed(value.target_content.nodes)),
            constraints=tuple(reversed(value.target_content.constraints)),
        ),
        node_identities=tuple(reversed(value.node_identities)),
        catalog=replace(
            value.catalog,
            listings=tuple(reversed(value.catalog.listings)),
            instruments=tuple(reversed(value.catalog.instruments)),
        ),
    )
    assert planning_input_digest(value) == planning_input_digest(shuffled)
    original = calculate_contribution_plan(value)
    assert original == calculate_contribution_plan(shuffled)
    assert original.summary.residual_cash is not None
    assert (
        sum((x.recommended_amount.amount for x in original.lines), Decimal(0))
        + original.summary.residual_cash.amount
        == contribution
    )
    assert all(
        x.recommended_amount.amount >= 0 and x.post_value.amount >= x.current_value.amount
        for x in original.lines
    )


@given(
    values=st.tuples(st.integers(0, 3), st.integers(0, 3), st.integers(0, 3)),
    contribution=st.integers(1, 6),
    cash=st.integers(0, 2),
    steps=st.tuples(st.integers(1, 3), st.integers(1, 3)),
    minimum=st.integers(0, 7),
    eligible_a=st.booleans(),
    excluded_b=st.booleans(),
    hierarchical=st.booleans(),
    holding_cap=st.integers(0, 4),
    group_cap=st.integers(0, 4),
    group_min=st.integers(0, 7),
    maximum_lines=st.integers(0, 3),
)
@settings(max_examples=60, deadline=None)
def test_constrained_hierarchy_matches_independent_rational_exhaustion(
    values: tuple[int, int, int],
    contribution: int,
    cash: int,
    steps: tuple[int, int],
    minimum: int,
    eligible_a: bool,
    excluded_b: bool,
    hierarchical: bool,
    holding_cap: int,
    group_cap: int,
    group_min: int,
    maximum_lines: int,
) -> None:
    value = planning_input(
        tuple(map(str, values)),
        ("0.25", "0.25", "0.5"),
        str(contribution),
        cash=str(cash),
        increments=(str(steps[0]), str(steps[1]), "1"),
        mode=PlanningMode.HIERARCHICAL if hierarchical else PlanningMode.GLOBAL,
    )
    a, b, c = value.target_content.nodes
    value = with_content(
        value,
        replace(
            value.target_content,
            nodes=(
                TargetNode("G", None, TargetNodeKind.GROUP, "Group", 0, Decimal("0.5")),
                replace(a, parent_key="G", weight=Decimal("0.5")),
                replace(b, parent_key="G", weight=Decimal("0.5")),
                c,
            ),
            constraints=(
                *value.target_content.constraints,
                TargetConstraint(
                    "minimum-A",
                    Kind.MINIMUM_FUNDED_AMOUNT,
                    "A",
                    amount=Decimal(minimum),
                    currency=EUR,
                ),
                TargetConstraint("eligible-A", Kind.ELIGIBLE, "A", enabled=eligible_a),
                TargetConstraint(
                    "cap-A", Kind.MAXIMUM_POST_WEIGHT, "A", weight=Decimal(holding_cap) / 4
                ),
                TargetConstraint(
                    "cap-G", Kind.MAXIMUM_POST_WEIGHT, "G", weight=Decimal(group_cap) / 4
                ),
                TargetConstraint(
                    "minimum-G",
                    Kind.MINIMUM_GROUP_FUNDING,
                    "G",
                    amount=Decimal(group_min),
                    currency=EUR,
                ),
                TargetConstraint("lines", Kind.MAXIMUM_FUNDED_LINES, count=maximum_lines),
            ),
        ),
    )
    value = replace(
        value,
        options=replace(value.options, excluded_holding_ids=(uid(501),) if excluded_b else ()),
    )
    result = calculate_contribution_plan(value)
    denominator = sum(values) + cash + contribution
    candidates = []
    for x, y, z in product(range(contribution + 1), repeat=3):
        if (
            x + y + z > contribution
            or x % steps[0]
            or y % steps[1]
            or (0 < x < minimum)
            or (x > 0 and not eligible_a)
            or (y > 0 and excluded_b)
            or sum(amount > 0 for amount in (x, y, z)) > maximum_lines
            or Fraction(values[0] + x, denominator) > Fraction(holding_cap, 4)
            or Fraction(values[0] + values[1] + x + y, denominator) > Fraction(group_cap, 4)
            or x + y < group_min
        ):
            continue
        residual = contribution - x - y - z
        cash_score = Fraction(cash + residual, denominator) ** 2
        c_score = (Fraction(values[2] + z, denominator) - Fraction(1, 2)) ** 2
        leaf = rational_quantize(
            (Fraction(values[0] + x, denominator) - Fraction(1, 4)) ** 2
            + (Fraction(values[1] + y, denominator) - Fraction(1, 4)) ** 2
            + c_score
            + cash_score
        )
        group = rational_quantize(
            (Fraction(values[0] + values[1] + x + y, denominator) - Fraction(1, 2)) ** 2
            + c_score
            + cash_score
        )
        scores = (group, *(leaf for _ in range(8))) if hierarchical else (leaf,)
        candidates.append((scores, Decimal(residual), (Decimal(x), Decimal(y), Decimal(z))))
    assert result.summary.exhaustive
    if candidates:
        expected = min(candidates)
        assert result.summary.outcome is PlanOutcome.OPTIMAL
        assert result.summary.objective_after is not None
        assert result.summary.objective_after.scores == expected[0]
        assert result.summary.residual_cash is not None
        assert result.summary.residual_cash.amount == expected[1]
        assert tuple(x.recommended_amount.amount for x in result.lines) == expected[2]
    else:
        assert result.summary.outcome is PlanOutcome.INFEASIBLE
        assert result.lines == ()
    verify_contribution_plan_result(value, result)
