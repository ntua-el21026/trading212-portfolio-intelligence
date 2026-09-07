"""Bounded deterministic integer-grid search with independently checked results."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from trading212_domain.planning import (
    PLAN_METHOD,
    ContributionPlanLine,
    ContributionPlanResult,
    ContributionPlanResultSummary,
    PlanningExplanation,
    PlanningMode,
    PlanObjective,
    PlanOutcome,
)
from trading212_domain.targets import TargetConstraintKind as Kind
from trading212_domain.targets import TargetNodeKind

from .planning import (
    ONE,
    ZERO,
    _Component,
    _drift,
    _empty_result,
    _money,
    _priority,
    _Problem,
    _result_context,
    quantized,
)

MAX_MOVES = 10_000
MAX_ASSIGNMENTS = 100_000
BISECTIONS = 128


def _floor(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _ceil(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True, slots=True)
class _Domain:
    step: int
    first: int
    last: int
    zero: bool
    lower: Decimal
    upper: Decimal
    minimum_funded: Decimal
    lower_keys: tuple[str, ...]
    upper_keys: tuple[str, ...]
    minimum_keys: tuple[str, ...]
    maximum_keys: tuple[str, ...]

    @property
    def minimum(self) -> int:
        return 0 if self.zero else self.first * self.step

    @property
    def maximum(self) -> int:
        return self.last * self.step if self.last >= self.first else 0

    @property
    def empty(self) -> bool:
        return not self.zero and self.last < self.first

    def values(self, guide: Decimal, quantum: Decimal) -> Iterator[int]:
        """Merge the two monotone distances and optional zero without materializing a grid."""
        center = guide / (quantum * self.step)
        left = min(_floor(center), self.last)
        right = max(left + 1, self.first)
        has_zero = self.zero
        while has_zero or left >= self.first or right <= self.last:
            candidates: list[tuple[Decimal, int, str]] = []
            if has_zero:
                candidates.append((abs(guide), 0, "zero"))
            if left >= self.first:
                amount = left * self.step
                candidates.append((abs(Decimal(amount) * quantum - guide), amount, "left"))
            if right <= self.last:
                amount = right * self.step
                candidates.append((abs(Decimal(amount) * quantum - guide), amount, "right"))
            _, amount, side = min(candidates)
            yield amount
            if side == "zero":
                has_zero = False
            elif side == "left":
                left -= 1
            else:
                right += 1


@dataclass(frozen=True, slots=True)
class _GroupBound:
    key: str
    indices: tuple[int, ...]
    low: int
    high: int
    low_keys: tuple[str, ...]
    high_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Model:
    problem: _Problem
    quantum: Decimal
    contribution: int
    denominator: Decimal
    domains: tuple[_Domain, ...]
    groups: tuple[_GroupBound, ...]
    cash_minimum: int
    cash_keys: tuple[str, ...]
    max_lines: int
    max_lines_keys: tuple[str, ...]
    descendants: dict[str, tuple[int, ...]]
    frontiers: tuple[tuple[_Component, ...], ...]

    @property
    def contradiction(self) -> bool:
        return contradiction_explanation(self) is not None


def contradiction_explanation(model: _Model) -> PlanningExplanation | None:
    """Name only bounds used by the first deterministic necessary-condition proof.

    This is a supporting set, not a claimed minimal unsatisfiable core. Request
    modes, exclusions, contribution and quantum are fixed inputs without invented
    target-constraint keys. Objective priorities never establish infeasibility.
    """

    def proof(message: str, nodes: tuple[str, ...], keys: tuple[str, ...]) -> PlanningExplanation:
        return PlanningExplanation(
            "proved_constraint_contradiction",
            message,
            node_keys=tuple(sorted(set(nodes))),
            constraint_keys=tuple(sorted(set(keys))),
        )

    def node_keys(indices: tuple[int, ...]) -> tuple[str, ...]:
        return tuple(
            item.node.key for i in indices if (item := model.problem.holdings[i]).node is not None
        )

    if model.cash_minimum > model.contribution:
        return proof(
            "The required post-plan cash reserve exceeds existing cash plus the contribution.",
            (),
            model.cash_keys,
        )
    for i, domain in enumerate(model.domains):
        if domain.empty:
            keys = (
                (*domain.lower_keys, *domain.upper_keys)
                if domain.lower > domain.upper
                else (*domain.minimum_keys, *domain.maximum_keys)
            )
            return proof(
                "The holding has no non-negative permitted funding amount within its post-weight "
                "bounds, funded minimum, increment and fixed contribution/eligibility limits.",
                node_keys((i,)),
                keys,
            )
    required = tuple(i for i, domain in enumerate(model.domains) if domain.minimum > 0)
    required_keys = tuple(key for i in required for key in model.domains[i].minimum_keys)
    if sum(x.minimum for x in model.domains) > model.contribution - model.cash_minimum:
        reserve_needed = sum(x.minimum for x in model.domains) <= model.contribution
        return proof(
            "The mandatory holding funding exceeds the contribution available after the "
            "required cash reserve; existing cash cannot fund purchases.",
            node_keys(required),
            (*required_keys, *(model.cash_keys if reserve_needed else ())),
        )
    if len(required) > model.max_lines:
        return proof(
            "The number of holdings requiring positive funding exceeds the maximum funded lines.",
            node_keys(required),
            (
                *(key for i in required for key in model.domains[i].lower_keys),
                *model.max_lines_keys,
            ),
        )
    for group in model.groups:
        if group.low > group.high:
            return proof(
                "The group's minimum funding/post-weight requirement exceeds its maximum "
                "funding/post-weight or fixed contribution bound.",
                (group.key,),
                (*group.low_keys, *group.high_keys),
            )
        if sum(model.domains[i].maximum for i in group.indices) < group.low:
            return proof(
                "The group's minimum requirement exceeds the funding capacity of its permitted "
                "holdings under their bounds, increments and fixed eligibility limits.",
                (group.key, *node_keys(group.indices)),
                (
                    *group.low_keys,
                    *(key for i in group.indices for key in model.domains[i].maximum_keys),
                ),
            )
        if sum(model.domains[i].minimum for i in group.indices) > group.high:
            mandatory = tuple(i for i in group.indices if model.domains[i].minimum > 0)
            return proof(
                "The group's maximum funding/post-weight or fixed contribution bound is below "
                "the mandatory funding of its holdings.",
                (group.key, *node_keys(mandatory)),
                (
                    *group.high_keys,
                    *(key for i in mandatory for key in model.domains[i].minimum_keys),
                ),
            )
    return None


def _model(problem: _Problem) -> _Model:
    value = problem.input
    quantum = value.options.monetary_quantum
    assert quantum is not None and problem.total is not None and problem.current_cash is not None
    contribution = value.options.contribution.amount
    denominator = problem.total + contribution
    by_key = {x.node.key: x for x in problem.components if x.node is not None}
    paths = {x.node.key: x.path_keys for x in problem.flattened}
    descendants = {
        key: tuple(i for i, x in enumerate(problem.holdings) if x.node and key in paths[x.node.key])
        for key in by_key
    }
    max_lines = next(
        (
            x.count
            for x in problem.constraints
            if x.kind is Kind.MAXIMUM_FUNDED_LINES and x.count is not None
        ),
        256,
    )
    max_lines_keys = tuple(
        x.key for x in problem.constraints if x.kind is Kind.MAXIMUM_FUNDED_LINES
    )
    domains: list[_Domain] = []
    for item, enabled in zip(problem.holdings, problem.enabled, strict=True):
        assert item.node is not None and item.value is not None
        constraints = [x for x in problem.constraints if x.node_key == item.node.key]
        lower, upper, minimum, step = (
            ZERO,
            contribution if enabled and max_lines > 0 else ZERO,
            ZERO,
            quantum,
        )
        lower_keys: tuple[str, ...] = ()
        upper_keys = (
            max_lines_keys
            if max_lines == 0
            else tuple(x.key for x in constraints if x.kind is Kind.ELIGIBLE and not x.enabled)
            if not enabled
            else ()
        )
        minimum_keys: tuple[str, ...] = ()
        step_keys: tuple[str, ...] = ()
        for constraint in constraints:
            if constraint.kind is Kind.MINIMUM_FUNDED_AMOUNT:
                assert constraint.amount is not None
                minimum = constraint.amount
                minimum_keys = (constraint.key,)
            elif constraint.kind is Kind.AMOUNT_INCREMENT:
                assert constraint.amount is not None
                step = constraint.amount
                step_keys = (constraint.key,)
            elif constraint.kind is Kind.MINIMUM_POST_WEIGHT:
                assert constraint.weight is not None
                candidate = constraint.weight * denominator - item.value
                if candidate > lower:
                    lower, lower_keys = candidate, (constraint.key,)
            elif constraint.kind is Kind.MAXIMUM_POST_WEIGHT:
                assert constraint.weight is not None
                candidate = constraint.weight * denominator - item.value
                if candidate < upper:
                    upper, upper_keys = candidate, (constraint.key,)
        first = max(1, _ceil(max(lower, minimum) / step))
        last = _floor(upper / step)
        positive_keys = (
            *lower_keys,
            *(minimum_keys if minimum > max(lower, step) else ()),
            *(step_keys if first * step > max(lower, minimum) else ()),
        )
        maximum_keys = upper_keys
        if upper > 0:
            if last < first:
                if step > upper:
                    maximum_keys += step_keys
                elif minimum > upper:
                    maximum_keys += minimum_keys
                else:
                    maximum_keys += (
                        *(minimum_keys if minimum > max(lower, step) else ()),
                        *step_keys,
                    )
            elif last * step < upper:
                maximum_keys += step_keys
        domains.append(
            _Domain(
                int(step / quantum),
                first,
                last,
                lower <= 0 <= upper,
                lower,
                upper,
                minimum,
                lower_keys,
                upper_keys,
                positive_keys if lower > 0 else (),
                maximum_keys,
            )
        )
    groups: list[_GroupBound] = []
    for key, component in by_key.items():
        if component.node is None or component.node.kind is not TargetNodeKind.GROUP:
            continue
        assert component.value is not None
        low, high = ZERO, contribution
        low_keys: tuple[str, ...] = ()
        high_keys: tuple[str, ...] = ()
        for constraint in problem.constraints:
            if constraint.node_key != key:
                continue
            if constraint.kind is Kind.MINIMUM_POST_WEIGHT:
                assert constraint.weight is not None
                candidate = constraint.weight * denominator - component.value
                if candidate > low:
                    low, low_keys = candidate, (constraint.key,)
            elif constraint.kind is Kind.MAXIMUM_POST_WEIGHT:
                assert constraint.weight is not None
                candidate = constraint.weight * denominator - component.value
                if candidate < high:
                    high, high_keys = candidate, (constraint.key,)
            elif constraint.kind is Kind.MINIMUM_GROUP_FUNDING:
                assert constraint.amount is not None
                if constraint.amount > low:
                    low, low_keys = constraint.amount, (constraint.key,)
            elif constraint.kind is Kind.MAXIMUM_GROUP_FUNDING:
                assert constraint.amount is not None
                if constraint.amount < high:
                    high, high_keys = constraint.amount, (constraint.key,)
        groups.append(
            _GroupBound(
                key,
                descendants[key],
                _ceil(low / quantum),
                _floor(high / quantum),
                low_keys,
                high_keys,
            )
        )
    reserve = value.options.cash_reserve or ZERO
    cash_keys: tuple[str, ...] = ()
    max_lines = 256
    for constraint in problem.constraints:
        if constraint.kind is Kind.CASH_RESERVE:
            candidate = max(constraint.amount or ZERO, (constraint.weight or ZERO) * denominator)
            if candidate > reserve:
                reserve, cash_keys = candidate, (constraint.key,)
        elif constraint.kind is Kind.MAXIMUM_FUNDED_LINES:
            assert constraint.count is not None
            max_lines = constraint.count
    cash_minimum = _ceil(max(ZERO, reserve - problem.current_cash) / quantum)
    if cash_minimum == 0:
        cash_keys = ()
    frontiers: list[tuple[_Component, ...]] = []
    if value.options.mode is PlanningMode.HIERARCHICAL:
        frontiers.extend(
            tuple(
                x
                for x in problem.components
                if (
                    x.depth == depth
                    or (
                        x.depth < depth
                        and (x.node is None or x.node.kind is not TargetNodeKind.GROUP)
                    )
                )
            )
            for depth in range(1, 9)
        )
    frontiers.append(
        tuple(
            x
            for x in problem.components
            if x.node is None or x.node.kind is not TargetNodeKind.GROUP
        )
    )
    return _Model(
        problem,
        quantum,
        int(contribution / quantum),
        denominator,
        tuple(domains),
        tuple(groups),
        cash_minimum,
        cash_keys,
        max_lines,
        max_lines_keys,
        descendants,
        tuple(frontiers),
    )


def valid_allocation(problem: _Problem, amounts: tuple[Decimal, ...], residual: Decimal) -> bool:
    """Check original constraints directly, independently of search domains or pruning."""
    value = problem.input
    q = value.options.monetary_quantum
    if (
        q is None
        or problem.total is None
        or problem.current_cash is None
        or len(amounts) != len(problem.holdings)
    ):
        return False
    if any(not x.is_finite() or x < 0 or x % q for x in (*amounts, residual)):
        return False
    if sum(amounts, ZERO) + residual != value.options.contribution.amount:
        return False
    if any(
        amount and not enabled for amount, enabled in zip(amounts, problem.enabled, strict=True)
    ):
        return False
    denominator = problem.total + value.options.contribution.amount
    if denominator <= 0:
        return False
    funded = {
        x.node.key: amount for x, amount in zip(problem.holdings, amounts, strict=True) if x.node
    }
    post = {x.node.key: x.value for x in problem.components if x.node}
    for key, amount in funded.items():
        if post[key] is None:
            return False
        post[key] += amount  # type: ignore[operator]
    for flat in reversed(problem.flattened):
        if flat.node.kind is TargetNodeKind.GROUP:
            keys = [x.node.key for x in problem.flattened if x.node.parent_key == flat.node.key]
            if any(post[key] is None for key in keys):
                return False
            post[flat.node.key] = sum(
                (child for key in keys if (child := post[key]) is not None), ZERO
            )
            funded[flat.node.key] = sum((funded.get(key, ZERO) for key in keys), ZERO)
    current_cash = problem.current_cash + residual
    if current_cash < (value.options.cash_reserve or ZERO):
        return False
    for item in problem.constraints:
        amount = funded.get(item.node_key, ZERO) if item.node_key else ZERO
        post_value = post.get(item.node_key) if item.node_key else None
        if (
            item.kind is Kind.MINIMUM_FUNDED_AMOUNT
            and amount
            and (item.amount is None or amount < item.amount)
        ):
            return False
        if item.kind is Kind.AMOUNT_INCREMENT and (item.amount is None or amount % item.amount):
            return False
        if item.kind is Kind.MINIMUM_POST_WEIGHT and (
            post_value is None or item.weight is None or post_value < item.weight * denominator
        ):
            return False
        if item.kind is Kind.MAXIMUM_POST_WEIGHT and (
            post_value is None or item.weight is None or post_value > item.weight * denominator
        ):
            return False
        if item.kind is Kind.MINIMUM_GROUP_FUNDING and (
            item.amount is None or amount < item.amount
        ):
            return False
        if item.kind is Kind.MAXIMUM_GROUP_FUNDING and (
            item.amount is None or amount > item.amount
        ):
            return False
        if item.kind is Kind.ELIGIBLE and item.enabled is False and amount:
            return False
        if item.kind is Kind.MAXIMUM_FUNDED_LINES and (
            item.count is None or sum(x > 0 for x in amounts) > item.count
        ):
            return False
        if item.kind is Kind.CASH_RESERVE and current_cash < max(
            item.amount or ZERO, (item.weight or ZERO) * denominator
        ):
            return False
    return True


def objective(
    model: _Model, amounts: tuple[Decimal, ...], residual: Decimal
) -> tuple[Decimal, ...]:
    values = {x.key: x.value for x in model.problem.components}
    for component in model.problem.components:
        assert component.value is not None
        if component.node is not None:
            values[component.key] = component.value + sum(
                (amounts[i] for i in model.descendants[component.node.key]), ZERO
            )
    cash = values[model.problem.cash_key]
    assert cash is not None
    values[model.problem.cash_key] = cash + residual
    scores = []
    for frontier in model.frontiers:
        score = ZERO
        for component in frontier:
            post = values[component.key]
            assert post is not None
            drift = post / model.denominator - component.target
            score += _priority(model.problem, component) * drift * drift
        scores.append(quantized(score))
    return tuple(scores)


def _guide(model: _Model) -> tuple[Decimal, ...]:
    problem = model.problem
    assert problem.current_cash is not None
    cash_component = next(x for x in problem.components if x.key == problem.cash_key)
    centers = [x.target * model.denominator - (x.value or ZERO) for x in problem.holdings]
    centers.append(cash_component.target * model.denominator - problem.current_cash)
    priorities = [_priority(problem, x) for x in problem.holdings] + [ONE]
    lows = [max(ZERO, x.lower) for x in model.domains] + [model.cash_minimum * model.quantum]
    highs = [max(ZERO, x.upper) for x in model.domains] + [
        problem.input.options.contribution.amount
    ]
    left = min(
        2 * alpha * (a - hi) for a, alpha, hi in zip(centers, priorities, highs, strict=True)
    )
    right = max(
        2 * alpha * (a - lo) for a, alpha, lo in zip(centers, priorities, lows, strict=True)
    )
    guide = tuple(lows)
    for _ in range(BISECTIONS):
        middle = (left + right) / 2
        guide = tuple(
            min(hi, max(lo, a - middle / (2 * alpha)))
            for a, alpha, lo, hi in zip(centers, priorities, lows, highs, strict=True)
        )
        if sum(guide, ZERO) > problem.input.options.contribution.amount:
            left = middle
        else:
            right = middle
    return guide[:-1]


Candidate = tuple[tuple[Decimal, ...], Decimal, tuple[Decimal, ...]]


def _candidate(model: _Model, units: tuple[int, ...]) -> Candidate | None:
    amounts = tuple(Decimal(x) * model.quantum for x in units)
    residual = Decimal(model.contribution - sum(units)) * model.quantum
    if not valid_allocation(model.problem, amounts, residual):
        return None
    return objective(model, amounts, residual), residual, amounts


def _search(model: _Model) -> tuple[Candidate | None, int, int, bool]:
    guide = _guide(model)
    seed = []
    for center, domain in zip(guide, model.domains, strict=True):
        count = _floor(center / (model.quantum * domain.step))
        seed.append(count * domain.step if domain.first <= count <= domain.last else 0)
    incumbent = _candidate(model, tuple(seed))
    examined = 0
    if incumbent is not None:
        while examined < MAX_MOVES:
            current_units = tuple(int(x / model.quantum) for x in incumbent[2])
            best = incumbent
            for i, domain in enumerate(model.domains):
                if examined == MAX_MOVES:
                    break
                examined += 1
                next_units = list(current_units)
                next_units[i] += domain.step if next_units[i] else domain.first * domain.step
                candidate = _candidate(model, tuple(next_units))
                if candidate is not None and candidate < best:
                    best = candidate
            if best == incumbent:
                break
            incumbent = best
    count = 0
    exhausted = True
    assigned: list[int] = []
    suffix_minimum = [0] * (len(model.domains) + 1)
    for i in range(len(model.domains) - 1, -1, -1):
        suffix_minimum[i] = suffix_minimum[i + 1] + model.domains[i].minimum

    def visit(depth: int, spent: int, funded: int) -> None:
        nonlocal count, exhausted, incumbent
        if depth == len(model.domains):
            candidate = _candidate(model, tuple(assigned))
            if candidate is not None and (incumbent is None or candidate < incumbent):
                incumbent = candidate
            return
        for units in model.domains[depth].values(guide[depth], model.quantum):
            if count == MAX_ASSIGNMENTS:
                exhausted = False
                return
            count += 1
            next_spent, next_funded = spent + units, funded + (units > 0)
            if (
                next_spent + suffix_minimum[depth + 1] > model.contribution - model.cash_minimum
                or next_funded > model.max_lines
            ):
                continue
            assigned.append(units)
            possible = True
            for group in model.groups:
                actual = sum(assigned[i] for i in group.indices if i <= depth)
                low = actual + sum(model.domains[i].minimum for i in group.indices if i > depth)
                high = actual + sum(model.domains[i].maximum for i in group.indices if i > depth)
                if low > group.high or high < group.low:
                    possible = False
                    break
            if possible:
                visit(depth + 1, next_spent, next_funded)
            assigned.pop()
            if not exhausted:
                return

    visit(0, 0, 0)
    return incumbent, examined, count, exhausted


def _result(
    model: _Model, candidate: Candidate, *, examined: int, attempted: int, exhaustive: bool
) -> ContributionPlanResult:
    problem, value = model.problem, model.problem.input
    scores, residual, amounts = candidate
    assert problem.total is not None and problem.current_cash is not None
    identities = {x.key: x for x in value.node_identities}
    lines = []
    for ordinal, (component, amount, domain, enabled, listing) in enumerate(
        zip(
            problem.holdings,
            amounts,
            model.domains,
            problem.enabled,
            problem.funding_listings,
            strict=True,
        )
    ):
        assert component.node is not None and component.value is not None
        identity = identities[component.node.key]
        assert identity.holding_id is not None
        # Binding diagnostics are explanatory only; the direct validator controls acceptance.
        bindings = tuple(
            x.key
            for x in problem.constraints
            if x.node_key == component.node.key
            and (
                (x.kind is Kind.MINIMUM_FUNDED_AMOUNT and amount > 0 and amount == x.amount)
                or (
                    x.kind in {Kind.MINIMUM_POST_WEIGHT, Kind.MAXIMUM_POST_WEIGHT}
                    and x.weight is not None
                    and component.value + amount == x.weight * model.denominator
                )
                or (x.kind is Kind.ELIGIBLE and not enabled)
            )
        )
        lines.append(
            ContributionPlanLine(
                ordinal,
                identity.id,
                identity.holding_id,
                component.node.key,
                component.instrument_id,
                listing,
                _money(component.value, value),
                quantized(component.target),
                quantized(component.value / problem.total) if problem.total > 0 else None,
                _money(amount, value),
                _money(component.value + amount, value),
                quantized((component.value + amount) / model.denominator),
                _money(domain.minimum_funded, value),
                _money(Decimal(domain.step) * model.quantum, value),
                not enabled,
                bindings,
            )
        )
    outcome = PlanOutcome.OPTIMAL if exhaustive else PlanOutcome.FEASIBLE_NONOPTIMAL
    before = _drift(problem)
    after = _drift(problem, amounts=amounts, residual_cash=residual)
    zeros = tuple(ZERO for _ in scores)
    explanations = (
        PlanningExplanation(
            "finite_domain_exhausted" if exhaustive else "search_budget_exhausted",
            (
                "Every feasible finite-domain candidate was considered "
                "or excluded by a necessary constraint."
            )
            if exhaustive
            else (
                "The deterministic assignment budget ended with a verified feasible incumbent; "
                "global optimality is not established."
            ),
            "info",
        ),
    )
    summary = ContributionPlanResultSummary(
        _result_context(problem, PLAN_METHOD),
        outcome,
        value.options.mode,
        value.options.contribution,
        model.quantum,
        value.currency_policy_version,
        _money(residual, value),
        _money(problem.current_cash, value),
        _money(problem.current_cash + residual, value),
        _money(model.denominator, value),
        PlanObjective(
            objective(model, tuple(ZERO for _ in amounts), value.options.contribution.amount)
        ),
        PlanObjective(scores),
        PlanObjective(scores if exhaustive else zeros),
        PlanObjective(zeros if exhaustive else scores),
        "finite_domain_exhaustion" if exhaustive else "nonnegative_objective_bound",
        examined,
        attempted,
        exhaustive,
        problem.constraints,
        explanations,
        tuple(
            x.node.key
            for x, enabled in zip(problem.holdings, problem.enabled, strict=True)
            if not enabled and x.node
        ),
        problem.unresolved,
        before.totals,
        after.totals,
    )
    return ContributionPlanResult(summary, tuple(lines))


def solve(problem: _Problem) -> ContributionPlanResult:
    model = _model(problem)
    if (proof := contradiction_explanation(model)) is not None:
        return _empty_result(
            problem,
            PlanOutcome.INFEASIBLE,
            "proved_constraint_contradiction",
            (proof,),
            exhaustive=True,
        )
    # Singleton domains carry a direct exhaustive proof without burning the DFS budget.
    if all(x.minimum == x.maximum for x in model.domains):
        candidate = _candidate(model, tuple(x.minimum for x in model.domains))
        if candidate is None:
            return _empty_result(
                problem, PlanOutcome.INFEASIBLE, "finite_domain_exhausted", exhaustive=True
            )
        return _result(model, candidate, examined=0, attempted=0, exhaustive=True)
    candidate, examined, attempted, exhaustive = _search(model)
    if candidate is None:
        return _empty_result(
            problem,
            PlanOutcome.INFEASIBLE if exhaustive else PlanOutcome.UNAVAILABLE,
            "finite_domain_exhausted" if exhaustive else "search_budget_exhausted",
            examined=examined,
            attempted=attempted,
            exhaustive=exhaustive,
        )
    return _result(model, candidate, examined=examined, attempted=attempted, exhaustive=exhaustive)
