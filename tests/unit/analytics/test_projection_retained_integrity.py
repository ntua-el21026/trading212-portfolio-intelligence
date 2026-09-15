"""Reject internally well-typed retained evidence that contradicts its financial basis."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import ROUND_DOWN, Context, Decimal, Inexact, Rounded, localcontext
from typing import Any

import pytest
from trading212_analytics.projection import (
    calculate_projection,
    calculate_projection_chunk,
    finalize_projection,
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
)
from trading212_domain.projection_result import ProjectionAssetValue, ProjectionChunk
from trading212_domain.projection_serialization import (
    decode_projection_chunk,
    decode_projection_result,
    projection_canonical_bytes,
    projection_input_digest,
)
from trading212_domain.values import CurrencyCode, Money

D = Decimal
EUR = CurrencyCode("EUR")
VERSION = "00000000-0000-4000-8000-000000000001"
pytestmark = pytest.mark.unit


def _input(*, inflation: str = "0", stochastic: bool = False) -> ProjectionInput:
    assumptions = ProjectionAssumptions(
        assets=(
            ProjectionAsset(
                key="a",
                annual_mean_log_return=D(0),
                annual_volatility=D(".2") if stochastic else D(0),
                weight=D(".6"),
            ),
            ProjectionAsset(
                key="b", annual_mean_log_return=D(0), annual_volatility=D(0), weight=D(".4")
            ),
        ),
        correlation=((D(1), D(0)), (D(0), D(1))),
        reporting_currency=EUR,
        annual_inflation=D(inflation),
    )
    schedule = ProjectionSchedule(base_monthly=Money(D(0), EUR))
    return ProjectionInput(
        assumption_version_id=VERSION,
        assumptions=assumptions,
        initial=ProjectionInitialBasis(kind="modeled_value", value=Money(D(100), EUR)),
        schedule=schedule,
        seed=1243,
        months=2,
        paths=2,
        retained_months=(0, 2),
        allocation=tuple(
            ProjectionAllocation(key=a.key, weight=a.weight) for a in assumptions.assets
        ),
        goal=ProjectionGoal(
            version_id="00000000-0000-4000-8000-000000000002",
            assumption_version_id=VERSION,
            target=Money(D(200), EUR),
            basis="real",
            months=2,
            probability_objective=D(".5"),
            schedule=schedule,
        ),
    )


def _bytes(raw: dict[str, Any]) -> bytes:
    return json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()


@pytest.mark.parametrize("kind", ["wealth", "allocation", "withdrawal"])
def test_material_residuals_are_rejected_by_chunk_decoder(kind: str) -> None:
    raw = json.loads(projection_canonical_bytes(calculate_projection_chunk(_input(), 0, 2)))
    point = raw["paths"][0]["points"][-1]
    if kind == "wealth":
        point.update(nominal="200", real="200", wealth_residual="100")
        point["assets"][0]["value"] = "160"
    elif kind == "allocation":
        point["assets"][0]["value"] = "0"
        point["allocation_residual"] = "60"
    else:
        point.update(withdrawals_requested="100", withdrawal_residual="100")
    with pytest.raises(DomainError):
        decode_projection_chunk(_bytes(raw))


def test_total_preserving_initial_allocation_change_is_not_the_pinned_basis() -> None:
    inputs = _input()
    chunk = calculate_projection_chunk(inputs, 0, 2)
    path = chunk.paths[0]
    first = replace(
        path.points[0],
        assets=(
            ProjectionAssetValue(key="a", value=D(50)),
            ProjectionAssetValue(key="b", value=D(50)),
        ),
    )
    changed = replace(chunk, paths=(replace(path, points=(first, path.points[-1])), chunk.paths[1]))
    with pytest.raises(DomainError):
        finalize_projection(inputs, (changed,))


@pytest.mark.parametrize("inflation", ["0", ".1", "-.1"])
def test_real_wealth_must_follow_declared_inflation(inflation: str) -> None:
    inputs = _input(inflation=inflation)
    chunk = calculate_projection_chunk(inputs, 0, 2)
    path = chunk.paths[0]
    changed = replace(
        chunk,
        paths=(
            replace(path, points=(path.points[0], replace(path.points[-1], real=D(0)))),
            chunk.paths[1],
        ),
    )
    with pytest.raises(DomainError):
        finalize_projection(inputs, (changed,))


@pytest.mark.parametrize("kind", ["contribution", "fee", "tax"])
def test_reconciling_fabricated_flows_still_contradict_inputs(kind: str) -> None:
    inputs = _input()
    chunk = calculate_projection_chunk(inputs, 0, 2)
    path = chunk.paths[0]
    final = path.points[-1]
    if kind == "contribution":
        final = replace(
            final,
            nominal=D(101),
            real=D(101),
            contributions=D(1),
            assets=(replace(final.assets[0], value=D(61)), final.assets[1]),
        )
    elif kind == "fee":
        final = replace(final, investment_effect=D(1), fees=D(1))
    else:
        final = replace(final, investment_effect=D(1), tax_drag=D(1))
    changed = replace(chunk, paths=(replace(path, points=(path.points[0], final)), chunk.paths[1]))
    assert isinstance(decode_projection_chunk(projection_canonical_bytes(changed)), ProjectionChunk)
    with pytest.raises(DomainError):
        finalize_projection(inputs, (changed,))


@pytest.mark.parametrize(
    "field", ["probability", "interval", "shortfall", "mean", "quantile", "funding"]
)
def test_result_decoder_checks_statistics_against_retained_paths(field: str) -> None:
    raw = json.loads(projection_canonical_bytes(calculate_projection(_input())))
    variant = raw["variants"][0]
    goal = variant["goal"]
    if field == "probability":
        # Counts remain correctly zero; the former record accepted 75% and objective_met.
        goal.update(probability="0.75", interval_low="0", interval_high="1", objective_met=True)
    elif field == "interval":
        goal.update(interval_low="0", interval_high="1")
    elif field == "shortfall":
        goal["mean_shortfall"] = "1"
    elif field == "mean":
        variant["distributions"][-1]["nominal_mean"] = "101"
    elif field == "quantile":
        variant["distributions"][-1]["real"]["values"] = ["1"] * 5
    else:
        variant["distributions"][-1]["funding_failed_paths"] = 1
    with pytest.raises(DomainError):
        decode_projection_result(_bytes(raw))


def test_histogram_membership_cannot_change_while_total_count_is_preserved() -> None:
    raw = json.loads(projection_canonical_bytes(calculate_projection(_input(stochastic=True))))
    bins = raw["variants"][0]["nominal_histogram"]["bins"]
    assert len(bins) == 2 and [item["count"] for item in bins] == [1, 1]
    bins[0]["count"], bins[1]["count"] = 2, 0
    with pytest.raises(DomainError):
        decode_projection_result(_bytes(raw))


def test_valid_retained_rounding_and_statistics_ignore_hostile_context() -> None:
    inputs = _input(inflation=".1", stochastic=True)
    chunk = calculate_projection_chunk(inputs, 0, 2)
    result = calculate_projection(inputs)
    encoded = projection_canonical_bytes(result)
    with localcontext(Context(prec=3, rounding=ROUND_DOWN, Emin=-9, Emax=9)) as hostile:
        for signal in hostile.traps:
            hostile.traps[signal] = True
        hostile.flags[Inexact] = hostile.flags[Rounded] = True
        before = hostile.copy()
        assert decode_projection_result(encoded) == result
        assert (
            finalize_projection(
                inputs, (decode_projection_chunk(projection_canonical_bytes(chunk)),)
            )
            == result
        )
        assert hostile.prec == before.prec and hostile.rounding == before.rounding
        assert hostile.flags == before.flags and hostile.traps == before.traps


@pytest.mark.parametrize("withdrawal", ["absent", "zero", "later"])
def test_funding_failure_requires_a_positive_withdrawal_in_its_original_month(
    withdrawal: str,
) -> None:
    inputs = _input()
    schedule = replace(
        inputs.schedule,
        entries=()
        if withdrawal == "absent"
        else (
            ProjectionScheduleEntry(
                key="scheduled-withdrawal",
                month=2 if withdrawal == "later" else 1,
                kind="withdrawal",
                value=Money(D(1) if withdrawal == "later" else D(0), EUR),
            ),
        ),
    )
    assert inputs.goal is not None
    inputs = replace(inputs, schedule=schedule, goal=replace(inputs.goal, schedule=schedule))
    chunk = calculate_projection_chunk(inputs, 0, inputs.paths)
    path = chunk.paths[0]
    final = replace(path.points[-1], funding_failed=True, unpaid_positive_below_quantum=True)
    changed = replace(
        chunk,
        paths=(
            replace(path, points=(path.points[0], final), first_unpaid_month=1),
            chunk.paths[1],
        ),
    )
    # A standalone chunk has no schedule; the saved input provides this missing evidence.
    restored = decode_projection_chunk(projection_canonical_bytes(changed))
    with pytest.raises(DomainError, match="positive scheduled withdrawal"):
        finalize_projection(inputs, (restored,))


def test_result_codec_rejects_unpaid_evidence_after_its_withdrawal_schedule_is_removed() -> None:
    original = _input()
    schedule = replace(
        original.schedule,
        entries=(
            ProjectionScheduleEntry(
                key="funding-request", month=1, kind="withdrawal", value=Money(D(200), EUR)
            ),
        ),
    )
    assert original.goal is not None
    inputs = replace(original, schedule=schedule, goal=replace(original.goal, schedule=schedule))
    result = calculate_projection(inputs)
    assert result.variants[0].paths[0].first_unpaid_month == 1
    assert decode_projection_result(projection_canonical_bytes(result)) == result
    raw = json.loads(projection_canonical_bytes(result))
    raw["inputs"] = json.loads(projection_canonical_bytes(original))
    raw["input_digest"] = projection_input_digest(original)
    with pytest.raises(DomainError, match="positive scheduled withdrawal"):
        decode_projection_result(_bytes(raw))
