"""Planning failures cannot become executable or leak untrusted exception data."""

import json
import traceback
from dataclasses import replace
from decimal import Decimal

import pytest
from trading212_analytics import _contribution_solver
from trading212_analytics.planning import (
    calculate_contribution_plan,
    verify_contribution_plan_result,
)
from trading212_domain import DomainError, Money, canonical_json
from trading212_domain.planning import ContributionPlanResult, PlanOutcome
from trading212_domain.planning_serialization import (
    MAX_PLANNING_DOCUMENT_BYTES,
    planning_input_from_json,
)

from tests.unit.analytics.planning_factories import EUR, planning_input

pytestmark = pytest.mark.security


def test_forged_solver_recommendation_is_rejected_before_becoming_a_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = planning_input()
    good = calculate_contribution_plan(value)
    forged = replace(
        good,
        lines=(replace(good.lines[0], recommended_amount=Money(Decimal(1), EUR)), *good.lines[1:]),
    )

    def poison(_: object) -> ContributionPlanResult:
        return forged

    monkeypatch.setattr(_contribution_solver, "solve", poison)
    result = calculate_contribution_plan(value)
    assert result.summary.outcome is PlanOutcome.FAILED
    assert result.lines == ()
    assert result.summary.execution_allowed is False


def test_execution_or_identity_tampering_fails_the_independent_check() -> None:
    value = planning_input()
    good = calculate_contribution_plan(value)
    for forged in (
        replace(good, summary=replace(good.summary, execution_allowed=True)),
        replace(
            good,
            lines=(replace(good.lines[0], holding_id=good.lines[1].holding_id), *good.lines[1:]),
        ),
        replace(good, summary=replace(good.summary, attempted_assignments=100001)),
    ):
        with pytest.raises(DomainError, match="independent verification"):
            verify_contribution_plan_result(value, forged)


def test_unknown_canonical_fields_and_duplicate_keys_have_no_exception_reflection() -> None:
    marker = "_".join(("PRIVATE", "PLANNING", "VALUE"))
    document = json.loads(canonical_json(planning_input()))
    document[marker] = marker
    for poisoned in (
        json.dumps(document),
        '{"' + marker + '":"' + marker + '","' + marker + '":1}',
    ):
        with pytest.raises(DomainError) as captured:
            planning_input_from_json(poisoned)
        assert marker not in str(captured.value)
        assert marker not in "".join(traceback.format_exception(captured.value))
        assert captured.value.__context__ is None


def test_canonical_storage_input_size_and_financial_number_boundaries_fail_closed() -> None:
    with pytest.raises(DomainError, match="bound"):
        planning_input_from_json(b" " * (MAX_PLANNING_DOCUMENT_BYTES + 1))
    payload = json.loads(canonical_json(planning_input()))
    for invalid in (True, 1.25, "NaN", "Infinity", "100000000000000000000"):
        payload["options"]["contribution"]["amount"] = invalid
        with pytest.raises(DomainError, match="invalid"):
            planning_input_from_json(json.dumps(payload))
