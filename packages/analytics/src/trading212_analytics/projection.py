"""Bounded deterministic projection paths; no jobs, clocks or source acquisition."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from decimal import Decimal

from trading212_domain.errors import fail_validation
from trading212_domain.projection import (
    PROJECTION_MAX_BYTES,
    ProjectionAsset,
    ProjectionInput,
    ProjectionSchedule,
    ProjectionVariant,
)
from trading212_domain.projection_result import (
    ProjectionAssetValue,
    ProjectionCalculation,
    ProjectionChunk,
    ProjectionPath,
    ProjectionPoint,
    ProjectionVariantResult,
)
from trading212_domain.projection_serialization import (
    projection_canonical_bytes,
    projection_input_digest,
)
from trading212_domain.projection_validation import validate_projection_path_basis
from trading212_domain.sources import source_integer
from trading212_domain.values import Money

from ._premium_numeric import (
    ONE,
    Q18,
    TOLERANCE,
    ZERO,
    Matrix,
    arithmetic,
    finite,
    invalid,
    q18,
    semidefinite_factor,
)
from ._projection_random import normal_at
from .projection_summary import analyze_goal, histogram, summarize_paths


def validate_projection_capacity(inputs: ProjectionInput) -> None:
    """Run before reservation: complete typed bounds, PSD and all sensitivity variants."""
    if type(inputs) is not ProjectionInput:
        invalid("projection.inputs")
    # Input construction validates financial ranges, exact weights and combined work.
    semidefinite_factor(inputs.assumptions.correlation)
    projection_canonical_bytes(inputs)


def _effective(
    inputs: ProjectionInput, variant: ProjectionVariant
) -> tuple[tuple[ProjectionAsset, ...], ProjectionSchedule]:
    if variant not in inputs.variants:
        invalid("projection.variant")
    assets, schedule = inputs.assumptions.assets, inputs.schedule
    sensitivity = inputs.sensitivity
    with arithmetic():
        if variant == "contribution_delta":
            if sensitivity is None:
                fail_validation("Projection sensitivity is missing.", field="sensitivity")
            schedule = replace(
                schedule,
                base_monthly=Money(
                    schedule.base_monthly.amount + sensitivity.contribution_delta.amount,
                    schedule.base_monthly.currency,
                ),
            )
        elif variant == "mean_log_delta":
            if sensitivity is None:
                fail_validation("Projection sensitivity is missing.", field="sensitivity")
            assets = tuple(
                replace(
                    a,
                    annual_mean_log_return=a.annual_mean_log_return
                    + sensitivity.annual_mean_log_delta,
                )
                for a in assets
            )
    return assets, schedule


@dataclass(slots=True)
class _State:
    values: list[Decimal]
    contributions: Decimal = ZERO
    requested: Decimal = ZERO
    funded: Decimal = ZERO
    unpaid: Decimal = ZERO
    investment: Decimal = ZERO
    fees: Decimal = ZERO
    tax: Decimal = ZERO
    first_unpaid: int | None = None


def _point(
    inputs: ProjectionInput,
    assets: tuple[ProjectionAsset, ...],
    state: _State,
    month: int,
    inflation_factor: Decimal,
) -> ProjectionPoint:
    nominal = q18(sum(state.values, ZERO))
    real = q18(sum(state.values, ZERO) / inflation_factor)
    values = tuple(
        ProjectionAssetValue(key=a.key, value=q18(v))
        for a, v in zip(assets, state.values, strict=True)
    )
    contributions, requested = q18(state.contributions), q18(state.requested)
    funded, unpaid = q18(state.funded), q18(state.unpaid)
    investment, fees, tax = q18(state.investment), q18(state.fees), q18(state.tax)
    residual = nominal - (
        inputs.initial.value.amount + contributions - funded + investment - fees - tax
    )
    allocation_residual = nominal - sum((a.value for a in values), ZERO)
    withdrawal_residual = requested - funded - unpaid
    # Each published term can contribute half a quantum; finite internal drift is separate.
    scale = max(
        ONE, inputs.initial.value.amount, nominal, contributions, funded, abs(investment), fees, tax
    )
    if (
        abs(residual) > 8 * Q18 + TOLERANCE * scale
        or abs(allocation_residual) > (len(assets) + 1) * Q18
        or abs(withdrawal_residual) > 3 * Q18
    ):
        invalid("projection.reconciliation")
    return ProjectionPoint(
        month=month,
        nominal=nominal,
        real=real,
        assets=values,
        contributions=contributions,
        withdrawals_requested=requested,
        withdrawals_funded=funded,
        unpaid_withdrawals=unpaid,
        investment_effect=investment,
        fees=fees,
        tax_drag=tax,
        wealth_residual=q18(residual),
        allocation_residual=q18(allocation_residual),
        withdrawal_residual=q18(withdrawal_residual),
        funding_failed=state.first_unpaid is not None,
        unpaid_positive_below_quantum=state.first_unpaid is not None and unpaid == ZERO,
    )


def _run_path(
    inputs: ProjectionInput,
    index: int,
    assets: tuple[ProjectionAsset, ...],
    schedule: ProjectionSchedule,
    lower: Matrix,
) -> ProjectionPath:
    with arithmetic():
        state = _State([inputs.initial.value.amount * a.weight for a in assets])
        points = [_point(inputs, assets, state, 0, ONE)]
        retained = frozenset(inputs.retained_months)
        paused = frozenset(schedule.paused_months)
        lump: dict[int, Decimal] = {}
        withdrawal: dict[int, Decimal] = {}
        for entry in schedule.entries:
            destination = lump if entry.kind == "lump_sum" else withdrawal
            destination[entry.month] = destination.get(entry.month, ZERO) + entry.value.amount
        fee_factor = ((ONE - inputs.assumptions.annual_fee).ln() / 12).exp()
        tax_drag = inputs.assumptions.annual_tax_drag
        tax_factor = ONE if tax_drag is None else ((ONE - tax_drag).ln() / 12).exp()
        inflation_log = (ONE + inputs.assumptions.annual_inflation).ln()
        root_twelve = Decimal(12).sqrt()
        stochastic = any(a.annual_volatility != ZERO for a in assets)
        for month in range(1, inputs.months + 1):
            year = (month - 1) // 12
            growth = ONE if year == 0 else (ONE + schedule.annual_growth) ** year
            recurring = ZERO if month in paused else schedule.base_monthly.amount * growth
            incoming = recurring + lump.get(month, ZERO)
            state.contributions += incoming
            state.values = [
                value + incoming * a.weight for a, value in zip(assets, state.values, strict=True)
            ]
            requested = withdrawal.get(month, ZERO)
            available = sum(state.values, ZERO)
            funded = min(requested, available)
            unpaid = requested - funded
            state.requested += requested
            state.funded += funded
            state.unpaid += unpaid
            if unpaid > ZERO and state.first_unpaid is None:
                state.first_unpaid = month
            if funded:
                state.values = (
                    [ZERO for _ in assets]
                    if funded == available
                    else [value * (ONE - funded / available) for value in state.values]
                )
            # A stochastic coordinate can depend on an independent normal whose own asset
            # has sigma=0; only the all-zero-volatility case can omit the entire draw vector.
            independent = (
                tuple(
                    normal_at(inputs.seed, index, month, ordinal) for ordinal in range(len(assets))
                )
                if stochastic
                else tuple(ZERO for _ in assets)
            )
            for ordinal, asset in enumerate(assets):
                innovation = sum(
                    (lower[ordinal][j] * independent[j] for j in range(ordinal + 1)), ZERO
                )
                exponent = (
                    asset.annual_mean_log_return / 12
                    + asset.annual_volatility * innovation / root_twelve
                )
                before = state.values[ordinal]
                after_growth = before * exponent.exp()
                after_fee = after_growth * fee_factor
                after_tax = after_fee * tax_factor
                state.investment += after_growth - before
                state.fees += after_growth - after_fee
                state.tax += after_fee - after_tax
                state.values[ordinal] = finite(after_tax)
            rebalance = inputs.assumptions.rebalance
            if rebalance == "monthly" or (rebalance == "annual" and month % 12 == 0):
                total = sum(state.values, ZERO)
                state.values = [total * a.weight for a in assets]
            inflation_factor = (inflation_log * month / 12).exp()
            # Validate every month, including non-retained points; a temporary overflow
            # must not disappear behind a later withdrawal or sparse checkpoint choice.
            point = _point(inputs, assets, state, month, inflation_factor)
            if month in retained:
                points.append(point)
        return ProjectionPath(
            index=index,
            reporting_currency=inputs.assumptions.reporting_currency,
            points=tuple(points),
            first_unpaid_month=state.first_unpaid,
        )


def calculate_projection_chunk(
    inputs: ProjectionInput,
    path_start: int,
    path_count: int,
    *,
    variant: ProjectionVariant = "baseline",
) -> ProjectionChunk:
    validate_projection_capacity(inputs)
    source_integer(path_start, "path_start", 0, inputs.paths - 1)
    source_integer(path_count, "path_count", 1, min(32, inputs.paths - path_start))
    assets, schedule = _effective(inputs, variant)
    factor = semidefinite_factor(inputs.assumptions.correlation)
    paths = tuple(
        _run_path(inputs, index, assets, schedule, factor.lower)
        for index in range(path_start, path_start + path_count)
    )
    result = ProjectionChunk(
        input_digest=projection_input_digest(inputs), variant=variant, paths=paths
    )
    projection_canonical_bytes(result)
    return result


def finalize_projection(
    inputs: ProjectionInput, chunks: Iterable[ProjectionChunk]
) -> ProjectionCalculation:
    """Reject incomplete/duplicated/foreign chunks before making a complete result."""
    validate_projection_capacity(inputs)
    expected_digest = projection_input_digest(inputs)
    variants: dict[ProjectionVariant, dict[int, ProjectionPath]] = {v: {} for v in inputs.variants}
    bytes_used = len(projection_canonical_bytes(inputs))
    keys = tuple(a.key for a in inputs.assumptions.assets)
    for count, chunk in enumerate(chunks, start=1):
        if (
            count > inputs.paths * len(inputs.variants)
            or type(chunk) is not ProjectionChunk
            or chunk.input_digest != expected_digest
            or chunk.variant not in variants
        ):
            invalid("projection.chunks.identity")
        destination = variants[chunk.variant]
        for path in chunk.paths:
            if (
                path.index >= inputs.paths
                or path.index in destination
                or path.reporting_currency != inputs.assumptions.reporting_currency
                or tuple(p.month for p in path.points) != inputs.retained_months
                or any(tuple(a.key for a in p.assets) != keys for p in path.points)
                or path.points[0].nominal != inputs.initial.value.amount
            ):
                invalid("projection.chunks.basis")
            validate_projection_path_basis(inputs, path, chunk.variant)
            bytes_used += len(projection_canonical_bytes(path))
            if bytes_used > PROJECTION_MAX_BYTES:
                invalid("projection.bytes")
            destination[path.index] = path
    results: list[ProjectionVariantResult] = []
    for variant in inputs.variants:
        saved = variants[variant]
        if set(saved) != set(range(inputs.paths)):
            invalid("projection.chunks.incomplete")
        paths = tuple(saved[i] for i in range(inputs.paths))
        results.append(
            ProjectionVariantResult(
                variant=variant,
                paths=paths,
                distributions=summarize_paths(paths),
                nominal_histogram=histogram(tuple((p.index, p.points[-1].nominal) for p in paths)),
                real_histogram=histogram(tuple((p.index, p.points[-1].real) for p in paths)),
                goal=analyze_goal(paths, inputs.goal) if inputs.goal is not None else None,
            )
        )
    result = ProjectionCalculation(
        inputs=inputs,
        input_digest=expected_digest,
        variants=tuple(results),
        numerical_zero_pivots=semidefinite_factor(
            inputs.assumptions.correlation
        ).numerical_zero_pivots,
    )
    projection_canonical_bytes(result)
    return result


def calculate_projection(inputs: ProjectionInput) -> ProjectionCalculation:
    """Serial convenience runner over the same bounded chunk/finalization interfaces."""
    validate_projection_capacity(inputs)

    def chunks() -> Iterator[ProjectionChunk]:
        for variant in inputs.variants:
            for start in range(0, inputs.paths, 32):
                yield calculate_projection_chunk(
                    inputs, start, min(32, inputs.paths - start), variant=variant
                )

    return finalize_projection(inputs, chunks())
