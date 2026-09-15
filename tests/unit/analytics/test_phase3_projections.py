"""Independent deterministic references and retained-path projection regressions."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import ROUND_DOWN, Context, Decimal, Inexact, Rounded, localcontext
from typing import Any, Literal, cast

import pytest
from trading212_analytics import projection as kernel
from trading212_analytics.projection import (
    calculate_projection,
    calculate_projection_chunk,
    finalize_projection,
)
from trading212_analytics.projection_summary import (
    analyze_goal,
    histogram,
    nearest_rank,
    summarize_paths,
    wilson_interval,
)
from trading212_domain.errors import DomainError
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
    ProjectionGoal,
    ProjectionInitialBasis,
    ProjectionInput,
    ProjectionSchedule,
    ProjectionScheduleEntry,
    ProjectionSensitivity,
    ProjectionSourcePin,
)
from trading212_domain.projection_result import (
    ProjectionAssetValue,
    ProjectionPath,
    ProjectionPoint,
)
from trading212_domain.projection_serialization import (
    decode_projection_chunk,
    decode_projection_input,
    decode_projection_result,
    projection_canonical_bytes,
    projection_input_digest,
)
from trading212_domain.values import CurrencyCode, Money

D = Decimal
EUR = CurrencyCode("EUR")
VERSION = "00000000-0000-4000-8000-000000000001"
GOAL = "00000000-0000-4000-8000-000000000002"
pytestmark = pytest.mark.unit


def _asset(
    key: str = "cash", mean: str = "0", sigma: str = "0", weight: str = "1"
) -> ProjectionAsset:
    return ProjectionAsset(
        key=key, annual_mean_log_return=D(mean), annual_volatility=D(sigma), weight=D(weight)
    )


def _input(
    *,
    assets: tuple[ProjectionAsset, ...] | None = None,
    correlation: tuple[tuple[Decimal, ...], ...] | None = None,
    **changes: Any,
) -> ProjectionInput:
    selected = assets or (_asset(),)
    assumptions = ProjectionAssumptions(
        assets=selected,
        correlation=correlation
        or tuple(tuple(D(i == j) for j in range(len(selected))) for i in range(len(selected))),
        reporting_currency=EUR,
    )
    return replace(
        ProjectionInput(
            assumption_version_id=VERSION,
            assumptions=assumptions,
            initial=ProjectionInitialBasis(kind="modeled_value", value=Money(D(100), EUR)),
            schedule=ProjectionSchedule(base_monthly=Money(D(0), EUR)),
            seed=1243,
            months=2,
            paths=5,
            retained_months=(0, 1, 2),
            allocation=tuple(
                ProjectionAllocation(key=a.key, weight=a.weight) for a in assumptions.assets
            ),
        ),
        **changes,
    )


def _entry(
    key: str, month: int, kind: Literal["lump_sum", "withdrawal"], amount: str
) -> ProjectionScheduleEntry:
    return ProjectionScheduleEntry(key=key, month=month, kind=kind, value=Money(D(amount), EUR))


def _goal(
    inputs: ProjectionInput, target: str, basis: Literal["nominal", "real"] = "nominal"
) -> ProjectionInput:
    return replace(
        inputs,
        goal=ProjectionGoal(
            version_id=GOAL,
            assumption_version_id=VERSION,
            target=Money(D(target), EUR),
            basis=basis,
            months=inputs.months,
            probability_objective=D(".95"),
            schedule=inputs.schedule,
        ),
    )


def _round(value: Decimal) -> Decimal:
    with localcontext(Context(prec=180)):
        return value.quantize(D("1e-18"))


def test_projection_flows() -> None:
    schedule = ProjectionSchedule(
        base_monthly=Money(D(10), EUR),
        entries=(_entry("lump", 1, "lump_sum", "5"), _entry("withdraw", 2, "withdrawal", "20")),
    )
    result = calculate_projection(_input(schedule=schedule))
    for path in result.variants[0].paths:
        assert tuple(p.nominal for p in path.points) == (D(100), D(115), D(105))
        last = path.points[-1]
        assert last.contributions == 25 and last.withdrawals_funded == 20
        assert (
            last.unpaid_withdrawals
            == last.wealth_residual
            == last.allocation_residual
            == last.withdrawal_residual
            == 0
        )


def test_growth_pauses_lumps_and_prior_unpaid_liability() -> None:
    schedule = ProjectionSchedule(
        base_monthly=Money(D(10), EUR),
        annual_growth=D(".1"),
        paused_months=(2, 13),
        entries=(
            _entry("lump2", 2, "lump_sum", "7"),
            _entry("lump13", 13, "lump_sum", "3"),
            _entry("w1", 1, "withdrawal", "20"),
            _entry("w2", 2, "withdrawal", "50"),
            _entry("w3", 3, "withdrawal", "100"),
            _entry("w13", 13, "withdrawal", "10"),
        ),
    )
    inputs = _goal(
        _input(schedule=schedule, months=14, retained_months=(0, 1, 2, 3, 12, 13, 14)), "90"
    )
    result = calculate_projection(inputs).variants[0]
    assert tuple(p.nominal for p in result.paths[0].points) == tuple(
        D(v) for v in (100, 90, 47, 0, 90, 83, 94)
    )
    assert result.paths[0].points[-1].unpaid_withdrawals == 43
    assert result.goal is not None and result.goal.probability == result.goal.mean_shortfall == 0
    assert result.goal.funding_failed_paths == inputs.paths


def test_growth_minus_one_keeps_year_one_and_avoids_zero_power_zero() -> None:
    inputs = _input(
        initial=ProjectionInitialBasis(kind="modeled_value", value=Money(D(0), EUR)),
        schedule=ProjectionSchedule(base_monthly=Money(D(10), EUR), annual_growth=D(-1)),
        months=13,
        retained_months=(0, 1, 12, 13),
    )
    assert tuple(
        p.nominal for p in calculate_projection(inputs).variants[0].paths[0].points
    ) == tuple(map(D, (0, 10, 120, 120)))


def test_projection_fees() -> None:
    inputs = _input(months=12, retained_months=(0, 1, 12))
    inputs = replace(
        inputs,
        assumptions=replace(inputs.assumptions, annual_fee=D(".12"), annual_inflation=D(".10")),
    )
    point = calculate_projection(inputs).variants[0].paths[0].points[-1]
    assert point.nominal == 88 and point.real == 80 and point.fees == 12
    assert point.tax_drag == 0 and point.wealth_residual == 0
    taxed = (
        calculate_projection(
            replace(inputs, assumptions=replace(inputs.assumptions, annual_tax_drag=D(".1")))
        )
        .variants[0]
        .paths[0]
    )
    assert taxed.points[-1].nominal == D("79.2") and taxed.points[-1].real == 72
    with localcontext(Context(prec=180)):
        a = D(".88") ** (D(1) / 12)
        b = D(".9") ** (D(1) / 12)
        assert taxed.points[1].fees == _round(100 * (1 - a))
        assert taxed.points[1].tax_drag == _round(100 * a * (1 - b))
        assert abs(taxed.points[-1].fees + taxed.points[-1].tax_drag - D("20.8")) <= D("1e-18")


def test_annual_log_mean_is_not_simple_growth() -> None:
    inputs = _input(assets=(_asset(mean=".12"),), months=12, retained_months=(0, 12))
    terminal = calculate_projection(inputs).variants[0].paths[0].points[-1]
    with localcontext(Context(prec=180)):
        assert terminal.nominal == _round(100 * D(".12").exp())
    assert terminal.nominal != 112


def test_simulated_rebalancing_has_exact_analytical_reference() -> None:
    inputs = _input(assets=(_asset("a", ".5", "0", ".5"), _asset("b", "0", "0", ".5")))
    none = calculate_projection(inputs).variants[0].paths[0].points[-1]
    monthly = (
        calculate_projection(
            replace(inputs, assumptions=replace(inputs.assumptions, rebalance="monthly"))
        )
        .variants[0]
        .paths[0]
        .points[-1]
    )
    with localcontext(Context(prec=180)):
        a = (D(1) / 24).exp()
        assert none.nominal == _round(50 * (a * a + 1))
        assert monthly.nominal == _round(25 * (a + 1) ** 2)
    long = replace(inputs, months=13, retained_months=(0, 12, 13))
    annual = (
        calculate_projection(
            replace(long, assumptions=replace(long.assumptions, rebalance="annual"))
        )
        .variants[0]
        .paths[0]
    )
    with localcontext(Context(prec=180)):
        twelfth = 50 * (D(".5").exp() + 1)
        assert annual.points[1].nominal == _round(twelfth)
        assert annual.points[2].nominal == _round(twelfth * (a + 1) / 2)
    assert annual.points[1].assets[0].value == annual.points[1].assets[1].value


def test_zero_volatility_coordinate_can_drive_another_correlated_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int] = []

    def draw(seed: int, path: int, month: int, asset: int) -> Decimal:
        seen.append(asset)
        return D(1) if asset == 0 else D(-5)

    monkeypatch.setattr(kernel, "normal_at", draw)
    inputs = _input(
        assets=(_asset("a", "0", "0", ".5"), _asset("b", "0", ".24", ".5")),
        correlation=((D(1), D(1)), (D(1), D(1))),
        months=1,
        retained_months=(0, 1),
        paths=1,
    )
    result = calculate_projection(inputs)
    with localcontext(Context(prec=180)):
        expected = _round(50 + 50 * (D(".24") / D(12).sqrt()).exp())
    assert result.variants[0].paths[0].points[-1].nominal == expected
    assert seen == [0, 1] and result.numerical_zero_pivots == (1,)


def test_projection_insolvency() -> None:
    inputs = _goal(
        _input(
            schedule=ProjectionSchedule(
                base_monthly=Money(D(10), EUR),
                entries=(_entry("withdraw", 1, "withdrawal", "200"),),
            )
        ),
        "10",
    )
    result = calculate_projection(inputs).variants[0]
    assert result.paths[0].points[1].nominal == 0 and result.paths[0].points[-1].nominal == 10
    assert result.paths[0].points[-1].unpaid_withdrawals == 90
    assert (
        result.goal is not None and result.goal.successes == 0 and result.goal.mean_shortfall == 0
    )
    funded = _goal(
        _input(
            schedule=ProjectionSchedule(
                base_monthly=Money(D(0), EUR), entries=(_entry("withdraw", 1, "withdrawal", "100"),)
            )
        ),
        "0",
    )
    complete = calculate_projection(funded).variants[0]
    assert complete.paths[0].first_unpaid_month is None
    assert complete.goal is not None and complete.goal.successes == funded.paths


def test_positive_unpaid_below_q18_never_becomes_success() -> None:
    inputs = _input(
        assets=(_asset(mean="-.000000000000000001"),),
        initial=ProjectionInitialBasis(kind="modeled_value", value=Money(D(1), EUR)),
        months=3,
        retained_months=(0, 1, 2, 3),
        schedule=ProjectionSchedule(
            base_monthly=Money(D(0), EUR),
            entries=(
                _entry("withdraw", 2, "withdrawal", "1"),
                _entry("recovery", 3, "lump_sum", "1"),
            ),
        ),
    )
    result = calculate_projection(_goal(inputs, "0")).variants[0]
    last = result.paths[0].points[-1]
    assert last.nominal == 1 and last.unpaid_withdrawals == 0
    assert last.funding_failed and last.unpaid_positive_below_quantum
    assert result.paths[0].first_unpaid_month == 2
    assert result.goal is not None and result.goal.successes == 0


def test_projection_identity() -> None:
    inputs = _input(
        assets=(_asset("a", ".03", ".2", ".6"), _asset("b", ".01", ".1", ".4")),
        correlation=((D(1), D(".3")), (D(".3"), D(1))),
        paths=11,
        months=4,
        retained_months=(0, 2, 4),
        sensitivity=ProjectionSensitivity(
            contribution_delta=Money(D(5), EUR), annual_mean_log_delta=D(".01")
        ),
    )
    expected = calculate_projection(inputs)
    chunks = tuple(
        calculate_projection_chunk(inputs, start, size, variant=variant)
        for variant in inputs.variants
        for start, size in ((0, 1), (1, 3), (4, 7))
    )
    assert projection_canonical_bytes(
        finalize_projection(inputs, reversed(chunks))
    ) == projection_canonical_bytes(expected)
    assert calculate_projection_chunk(inputs, 4, 7) == chunks[2]
    with pytest.raises(DomainError):
        finalize_projection(inputs, chunks[:-1])
    with pytest.raises(DomainError):
        finalize_projection(inputs, (*chunks, chunks[0]))
    with pytest.raises(DomainError):
        finalize_projection(replace(inputs, seed=inputs.seed + 1), chunks)
    with pytest.raises(DomainError):
        calculate_projection_chunk(inputs, 0, 33)


def test_goal_sensitivity() -> None:
    base = _input(
        schedule=ProjectionSchedule(base_monthly=Money(D(10), EUR)),
        sensitivity=ProjectionSensitivity(
            contribution_delta=Money(D(5), EUR), annual_mean_log_delta=D(0)
        ),
    )
    result = calculate_projection(_goal(base, "125"))
    assert tuple(v.paths[0].points[-1].nominal for v in result.variants) == tuple(
        map(D, (120, 130, 120))
    )
    assert tuple(v.goal.probability for v in result.variants if v.goal is not None) == tuple(
        map(D, (0, 1, 0))
    )
    assert result.inputs.work_units == 30
    stochastic = _input(
        assets=(_asset("a", ".01", ".2"),),
        sensitivity=ProjectionSensitivity(
            contribution_delta=Money(D(5), EUR), annual_mean_log_delta=D(".02")
        ),
    )
    cases = calculate_projection(stochastic).variants
    shifted = replace(
        stochastic,
        sensitivity=None,
        assumptions=replace(
            stochastic.assumptions,
            assets=(replace(stochastic.assumptions.assets[0], annual_mean_log_return=D(".03")),),
        ),
    )
    assert cases[2].paths == calculate_projection(shifted).variants[0].paths


def _reference_paths() -> tuple[ProjectionPath, ...]:
    paths = []
    for index, value in enumerate((0, 50, 100, 100, 200)):
        start = ProjectionPoint(
            month=0,
            nominal=D(100),
            real=D(100),
            assets=(ProjectionAssetValue(key="cash", value=D(100)),),
            contributions=D(0),
            withdrawals_requested=D(0),
            withdrawals_funded=D(0),
            unpaid_withdrawals=D(0),
            investment_effect=D(0),
            fees=D(0),
            tax_drag=D(0),
            wealth_residual=D(0),
            allocation_residual=D(0),
            withdrawal_residual=D(0),
            funding_failed=False,
            unpaid_positive_below_quantum=False,
        )
        failed = index == 3
        final = replace(
            start,
            month=2,
            nominal=D(value),
            real=D(value),
            assets=(ProjectionAssetValue(key="cash", value=D(value)),),
            contributions=D(100 if failed else 0),
            withdrawals_requested=D(110 if failed else 0),
            withdrawals_funded=D(100 if failed else 0),
            unpaid_withdrawals=D(10 if failed else 0),
            investment_effect=D(value - 100),
            funding_failed=failed,
        )
        paths.append(
            ProjectionPath(
                index=index,
                reporting_currency=EUR,
                points=(start, final),
                first_unpaid_month=1 if failed else None,
            )
        )
    return tuple(paths)


def test_goal_reference() -> None:
    paths = _reference_paths()
    goal = _goal(_input(retained_months=(0, 2)), "100").goal
    assert goal is not None
    summary = summarize_paths(paths)[-1]
    assert summary.nominal_mean == 90
    assert summary.nominal.values == tuple(map(D, (0, 50, 100, 100, 200)))
    result = analyze_goal(paths, goal)
    assert result.successes == 2 and result.probability == D(".4")
    assert result.mean_shortfall == 30 and result.shortfalls.values == tuple(
        map(D, (0, 0, 0, 50, 100))
    )
    assert result.funding_failed_paths == 1 and not result.objective_met
    z = D("1.9599639845400542355245944305205515279555500778695")
    with localcontext(Context(prec=180)):
        square = z * z
        for n in (1, 5, 100):
            low, high = wilson_interval(0, n)
            assert low == 0 and high == _round(square / (n + square))
            low, high = wilson_interval(n, n)
            assert low == _round(D(n) / (n + square)) and high == 1
        low, high = wilson_interval(50, 100)
        radius = z / (2 * (100 + square).sqrt())
        assert (low, high) == (_round(D(".5") - radius), _round(D(".5") + radius))


def test_quantiles_and_exact_visible_histogram_boundaries() -> None:
    values = tuple(enumerate(map(D, (0, 50, 100, 100, 200))))
    assert nearest_rank(values, D(0)) == 0 and nearest_rank(values, D(".25")) == 50
    distribution = histogram(values)
    bins = distribution.bins
    assert tuple(b.count for b in bins) == (1, 1, 2, 0, 1)
    assert tuple(b.lower for b in bins) == tuple(map(D, (0, 40, 80, 120, 160)))
    assert bins[-1].upper == 200 and bins[-1].upper_inclusive
    tiny = histogram(((0, D(0)), (1, D("1e-18")), (2, D(0)), (3, D("1e-18"))))
    assert len(tiny.bins) == 1 and tiny.bins[0].count == 4
    equal = histogram(((0, D(7)), (1, D(7))))
    assert len(equal.bins) == 1 and equal.bins[0].lower == equal.bins[0].upper == 7
    prime = histogram(
        ((0, D(0)), (1, D(20)), (2, D(50)), (3, D(75)), (4, D("100.000000000000000003")))
    )
    assert len(prime.bins) == 5
    assert prime.observed_maximum == D("100.000000000000000003")
    assert prime.bins[-1].upper == D("100.000000000000000005")
    with localcontext(Context(prec=180)):
        maximum = D("99999999999999999999.999999999999999999")
        lower = maximum - D("1.000000000000000001")
    bounded = histogram(((0, lower), (1, maximum), (2, lower)))
    assert len(bounded.bins) == 1 and bounded.bins[-1].upper == maximum
    with pytest.raises(DomainError):
        nearest_rank(((0, D(1)), (0, D(2))), D(".5"))


def test_canonical_codecs_and_strict_mutations() -> None:
    inputs = _input()
    result = calculate_projection(inputs)
    chunk = calculate_projection_chunk(inputs, 0, 2)
    assert decode_projection_input(projection_canonical_bytes(inputs)) == inputs
    assert decode_projection_result(projection_canonical_bytes(result)) == result
    assert decode_projection_chunk(projection_canonical_bytes(chunk)) == chunk
    assert projection_input_digest(replace(inputs, seed=inputs.seed + 1)) != result.input_digest
    raw = json.loads(projection_canonical_bytes(inputs))
    for name, value in (("seed", True), ("extra", "unknown")):
        changed = dict(raw)
        changed[name] = value
        with pytest.raises(DomainError):
            decode_projection_input(
                json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
            )
    with pytest.raises(DomainError):
        decode_projection_input(b" " + projection_canonical_bytes(inputs))
    with pytest.raises(DomainError):
        decode_projection_input(b'{"seed":1,"seed":2}')


def test_context_isolation_includes_inputs_paths_and_summaries() -> None:
    inputs = _input(assets=(_asset(mean=".03", sigma=".2"),))
    expected = projection_canonical_bytes(calculate_projection(inputs))
    with localcontext(Context(prec=5, rounding=ROUND_DOWN, Emin=-9, Emax=9)) as context:
        context.traps[Inexact] = context.traps[Rounded] = True
        before = context.copy()
        assert (
            projection_canonical_bytes(
                calculate_projection(_input(assets=(_asset(mean=".03", sigma=".2"),)))
            )
            == expected
        )
        assert context.prec == before.prec and context.rounding == before.rounding
        assert context.flags == before.flags and context.traps == before.traps


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", True),
        ("seed", -1),
        ("seed", 2**32),
        ("months", 0),
        ("months", 601),
        ("paths", 0),
        ("paths", 4097),
        ("retained_months", (0, 1)),
        ("retained_months", (0, 1, 1, 2)),
    ],
)
def test_projection_input_bounds(field: str, value: Any) -> None:
    with pytest.raises(DomainError):
        _input(**{field: value})


def test_capacity_allocation_goal_and_numeric_rejections(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(DomainError):
        _input(months=600, retained_months=(0, 600), paths=2000)
    with pytest.raises(DomainError):
        _input(
            paths=1000,
            months=400,
            retained_months=(0, 400),
            sensitivity=ProjectionSensitivity(
                contribution_delta=Money(D(1), EUR), annual_mean_log_delta=D(0)
            ),
        )
    with pytest.raises(DomainError):
        _input(allocation=(ProjectionAllocation(key="cash", weight=D(".9")),))
    with pytest.raises(DomainError):
        _input(
            sensitivity=ProjectionSensitivity(
                contribution_delta=Money(D(-1), EUR), annual_mean_log_delta=D(0)
            )
        )
    with pytest.raises(DomainError):
        _input(
            sensitivity=ProjectionSensitivity(
                contribution_delta=Money(D(0), EUR), annual_mean_log_delta=D(".6")
            )
        )
    with pytest.raises(DomainError):
        ProjectionInitialBasis(kind="observed_snapshot", value=Money(D(1), EUR))
    observed = ProjectionInitialBasis(
        kind="observed_snapshot",
        value=Money(D(100), EUR),
        snapshot_pin=ProjectionSourcePin(subject_id=VERSION, content_digest="a" * 64),
    )
    assert _input(initial=observed).initial.kind == "observed_snapshot"
    goal_input = _goal(_input(), "100")
    with pytest.raises(DomainError):
        replace(goal_input, schedule=ProjectionSchedule(base_monthly=Money(D(1), EUR)))
    for value in (D("NaN"), D("Infinity"), 0.1, True):
        with pytest.raises(DomainError):
            ProjectionAsset(
                key="bad",
                annual_mean_log_return=cast("Any", value),
                annual_volatility=D(0),
                weight=D(1),
            )
    called = False

    def forbidden(*args: Any) -> None:
        nonlocal called
        called = True
        raise AssertionError("path computation before PSD validation")

    monkeypatch.setattr(kernel, "_run_path", forbidden)
    bad = _input(
        assets=(_asset("a", weight=".4"), _asset("b", weight=".3"), _asset("c", weight=".3")),
        correlation=(
            (D(1), D(".9"), D(".9")),
            (D(".9"), D(1), D("-.9")),
            (D(".9"), D("-.9"), D(1)),
        ),
    )
    with pytest.raises(DomainError):
        calculate_projection(bad)
    assert not called


def test_public_overflow_cannot_be_hidden_by_sparse_retention() -> None:
    inputs = _input(
        assets=(_asset(mean=".5"),),
        initial=ProjectionInitialBasis(
            kind="modeled_value", value=Money(D("99999999999999999999"), EUR)
        ),
        schedule=ProjectionSchedule(
            base_monthly=Money(D(0), EUR),
            entries=(_entry("later", 2, "withdrawal", "99999999999999999999"),),
        ),
        retained_months=(0, 2),
    )
    with pytest.raises(DomainError):
        calculate_projection(inputs)
