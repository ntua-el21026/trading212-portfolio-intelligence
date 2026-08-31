"""Conservative coverage-gated return primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException
from itertools import pairwise
from typing import Literal

from trading212_domain import (
    Coverage,
    CurrencyCode,
    DomainError,
    DomainWarning,
    ErrorCode,
    Instant,
    Money,
    QualityState,
    Ratio,
)

from ._decimal import add, divide, multiply, persisted_decimal, power, product, subtract, total
from .quality import combine_quality, degrade_quality

PERFORMANCE_VERSION = "1.0.0"
XIRR_METHOD_ID = "xirr"
TWR_METHOD_ID = "snapshot_subperiod_twr"
MODIFIED_DIETZ_METHOD_ID = "modified_dietz"
ANNUALIZATION_MINIMUM_DAYS = 365
_SECONDS_PER_DAY = Decimal(86400)
_SECONDS_PER_YEAR = Decimal(31536000)
_RATE_LOW = Decimal("-0.999999999999")
_RATE_HIGH_LIMIT = Decimal("1000000")
_RATE_INTERVAL_TOLERANCE = Decimal("0.000000000000000000000001")
_NPV_RELATIVE_TOLERANCE = Decimal("0.0000000000000000000000000001")
_MAX_XIRR_ITERATIONS = 256


@dataclass(frozen=True, slots=True)
class DatedExternalFlow:
    """Portfolio-perspective flow: contribution positive, withdrawal negative."""

    amount: Money
    occurred_at: Instant
    quality_state: QualityState = QualityState.FRESH


@dataclass(frozen=True, slots=True)
class SubperiodReturnInput:
    """Valuation-bounded subperiod using an end-of-subperiod flow convention."""

    starts_at: Instant
    ends_at: Instant
    beginning_value: Money
    ending_value: Money
    external_flow_at_end: Money | None
    complete: bool = True
    quality_state: QualityState = QualityState.FRESH

    def __post_init__(self) -> None:
        if self.ends_at <= self.starts_at:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "subperiod end must follow start",
                "ends_at",
            )
        values = (self.ending_value, self.external_flow_at_end)
        if any(
            value is not None and value.currency != self.beginning_value.currency
            for value in values
        ):
            raise DomainError(
                ErrorCode.CURRENCY_MISMATCH,
                "subperiod values must use one currency",
                "currency",
            )


@dataclass(frozen=True, slots=True)
class ReturnMetric:
    method_id: str
    version: str
    value_kind: Literal["annual_rate", "cumulative_return"]
    period_start: Instant
    period_end: Instant
    reporting_currency: CurrencyCode
    coverage: Coverage
    value: Ratio | None
    annualized_value: Ratio | None
    quality_state: QualityState
    converged: bool | None
    iterations: int | None
    warnings: tuple[DomainWarning, ...]
    missing_inputs: tuple[str, ...]
    assumptions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    version: str
    xirr: ReturnMetric | None
    time_weighted_return: ReturnMetric | None
    modified_dietz: ReturnMetric | None
    quality_state: QualityState
    warnings: tuple[DomainWarning, ...]


def _elapsed_seconds(start: Instant, end: Instant) -> Decimal:
    delta = end.value - start.value
    whole_seconds = delta.days * 86400 + delta.seconds
    return add(Decimal(whole_seconds), divide(Decimal(delta.microseconds), Decimal(1000000)))


def _coverage_missing(
    coverage: Coverage,
    period_start: Instant,
    period_end: Instant,
) -> tuple[str, ...]:
    missing: list[str] = []
    if not coverage.complete:
        missing.append("complete_history_coverage")
    if coverage.start_at is None or coverage.start_at > period_start:
        missing.append("coverage_at_period_start")
    if coverage.end_at is None or coverage.end_at < period_end:
        missing.append("coverage_at_period_end")
    return tuple(missing)


def _reliable_for_performance(state: QualityState) -> bool:
    return state in (QualityState.FRESH, QualityState.STALE)


def _unavailable_metric(
    *,
    method_id: str,
    value_kind: Literal["annual_rate", "cumulative_return"],
    period_start: Instant,
    period_end: Instant,
    currency: CurrencyCode,
    coverage: Coverage,
    quality: QualityState,
    warning_code: str,
    warning_message: str,
    missing_inputs: tuple[str, ...],
    assumptions: tuple[str, ...],
    converged: bool | None = None,
    iterations: int | None = None,
) -> ReturnMetric:
    state = quality
    if state not in (QualityState.FAILED, QualityState.UNRECONCILED):
        state = degrade_quality(state, QualityState.PARTIAL)
    return ReturnMetric(
        method_id=method_id,
        version=PERFORMANCE_VERSION,
        value_kind=value_kind,
        period_start=period_start,
        period_end=period_end,
        reporting_currency=currency,
        coverage=coverage,
        value=None,
        annualized_value=None,
        quality_state=state,
        converged=converged,
        iterations=iterations,
        warnings=(DomainWarning(warning_code, warning_message),),
        missing_inputs=missing_inputs,
        assumptions=assumptions,
    )


def _validate_period_values(
    beginning_value: Money,
    ending_value: Money,
    period_start: Instant,
    period_end: Instant,
) -> None:
    if beginning_value.currency != ending_value.currency:
        raise DomainError(
            ErrorCode.CURRENCY_MISMATCH,
            "beginning and ending values must use one currency",
            "currency",
        )
    if period_end <= period_start:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "performance period end must follow start",
            "period_end",
        )
    if beginning_value.amount < 0 or ending_value.amount < 0:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "portfolio boundary values must not be negative",
            "portfolio_value",
        )


def _validate_flows(
    flows: tuple[DatedExternalFlow, ...],
    *,
    currency: CurrencyCode,
    period_start: Instant,
    period_end: Instant,
) -> tuple[str, ...]:
    missing: list[str] = []
    for flow in flows:
        if flow.amount.currency != currency:
            raise DomainError(
                ErrorCode.CURRENCY_MISMATCH,
                "external flows must use the reporting currency",
                "currency",
            )
        if flow.occurred_at < period_start or flow.occurred_at > period_end:
            missing.append("external_flow_outside_period")
    return tuple(dict.fromkeys(missing))


def _group_cash_flows(
    cash_flows: tuple[tuple[Instant, Decimal], ...],
) -> tuple[tuple[Instant, Decimal], ...]:
    grouped: dict[Instant, list[Decimal]] = {}
    for occurred_at, value in cash_flows:
        grouped.setdefault(occurred_at, []).append(value)
    return tuple(
        (occurred_at, total(grouped[occurred_at]))
        for occurred_at in sorted(grouped, key=lambda item: item.value)
        if total(grouped[occurred_at]) != 0
    )


def _sign_changes(values: tuple[Decimal, ...]) -> int:
    return sum(
        1
        for previous, current in pairwise(values)
        if (previous < 0 < current) or (previous > 0 > current)
    )


def _xnpv(
    rate: Decimal,
    cash_flows: tuple[tuple[Instant, Decimal], ...],
) -> Decimal:
    base = add(Decimal(1), rate)
    if base <= 0:
        raise ArithmeticError("XIRR rate must be greater than -1")
    origin = cash_flows[0][0]
    discounted: list[Decimal] = []
    for occurred_at, amount in cash_flows:
        years = divide(_elapsed_seconds(origin, occurred_at), _SECONDS_PER_YEAR)
        discounted.append(divide(amount, power(base, years)))
    return total(discounted)


def calculate_xirr(
    *,
    beginning_value: Money,
    ending_value: Money,
    period_start: Instant,
    period_end: Instant,
    external_flows: tuple[DatedExternalFlow, ...],
    coverage: Coverage,
    beginning_quality: QualityState = QualityState.FRESH,
    ending_quality: QualityState = QualityState.FRESH,
) -> ReturnMetric:
    """Solve the conventional unique XIRR root with deterministic bisection."""

    _validate_period_values(beginning_value, ending_value, period_start, period_end)
    assumptions = (
        "portfolio-perspective external flows are negated for the investor XIRR equation",
        "actual UTC elapsed seconds divided by 365 days",
        "only a conventional one-sign-change cash-flow series is solved",
        "deterministic bounded bisection on rates greater than -1",
    )
    quality = combine_quality(
        (beginning_quality, ending_quality, *(flow.quality_state for flow in external_flows))
    )
    missing = list(_coverage_missing(coverage, period_start, period_end))
    missing.extend(
        _validate_flows(
            external_flows,
            currency=beginning_value.currency,
            period_start=period_start,
            period_end=period_end,
        )
    )
    if not _reliable_for_performance(quality):
        missing.append("reliable_material_inputs")
    if missing:
        return _unavailable_metric(
            method_id=XIRR_METHOD_ID,
            value_kind="annual_rate",
            period_start=period_start,
            period_end=period_end,
            currency=beginning_value.currency,
            coverage=coverage,
            quality=quality,
            warning_code="xirr_prerequisites_missing",
            warning_message=(
                "XIRR is unavailable because coverage or material inputs are unreliable."
            ),
            missing_inputs=tuple(dict.fromkeys(missing)),
            assumptions=assumptions,
            converged=False,
            iterations=0,
        )

    cash_flows = _group_cash_flows(
        (
            (period_start, -beginning_value.amount),
            *((flow.occurred_at, -flow.amount.amount) for flow in external_flows),
            (period_end, ending_value.amount),
        )
    )
    values = tuple(value for _, value in cash_flows)
    if (
        len(values) < 2
        or not any(value < 0 for value in values)
        or not any(value > 0 for value in values)
    ):
        return _unavailable_metric(
            method_id=XIRR_METHOD_ID,
            value_kind="annual_rate",
            period_start=period_start,
            period_end=period_end,
            currency=beginning_value.currency,
            coverage=coverage,
            quality=quality,
            warning_code="xirr_no_root",
            warning_message=(
                "XIRR requires at least one positive and one negative investor cash flow."
            ),
            missing_inputs=("opposite_sign_cash_flows",),
            assumptions=assumptions,
            converged=False,
            iterations=0,
        )
    if values[0] >= 0 or values[-1] <= 0 or _sign_changes(values) != 1:
        return _unavailable_metric(
            method_id=XIRR_METHOD_ID,
            value_kind="annual_rate",
            period_start=period_start,
            period_end=period_end,
            currency=beginning_value.currency,
            coverage=coverage,
            quality=quality,
            warning_code="xirr_ambiguous_roots",
            warning_message=(
                "XIRR is not claimed for a non-conventional or multiple-sign-change series."
            ),
            missing_inputs=("unique_conventional_root",),
            assumptions=assumptions,
            converged=False,
            iterations=0,
        )

    scale = total(abs(value) for value in values)
    npv_tolerance = max(
        _RATE_INTERVAL_TOLERANCE,
        multiply(scale, _NPV_RELATIVE_TOLERANCE),
    )
    try:
        low = _RATE_LOW
        low_value = _xnpv(low, cash_flows)
        high = Decimal(1)
        high_value = _xnpv(high, cash_flows)
        while (low_value < 0) == (high_value < 0) and high < _RATE_HIGH_LIMIT:
            high = min(multiply(high, Decimal(10)), _RATE_HIGH_LIMIT)
            high_value = _xnpv(high, cash_flows)
    except (ArithmeticError, DecimalException):
        return _unavailable_metric(
            method_id=XIRR_METHOD_ID,
            value_kind="annual_rate",
            period_start=period_start,
            period_end=period_end,
            currency=beginning_value.currency,
            coverage=coverage,
            quality=quality,
            warning_code="xirr_numeric_failure",
            warning_message="XIRR could not be evaluated safely within the fixed numerical policy.",
            missing_inputs=("numerically_stable_root",),
            assumptions=assumptions,
            converged=False,
            iterations=0,
        )
    if abs(low_value) <= npv_tolerance:
        root = low
        iterations = 0
    elif abs(high_value) <= npv_tolerance:
        root = high
        iterations = 0
    elif (low_value < 0) == (high_value < 0):
        return _unavailable_metric(
            method_id=XIRR_METHOD_ID,
            value_kind="annual_rate",
            period_start=period_start,
            period_end=period_end,
            currency=beginning_value.currency,
            coverage=coverage,
            quality=quality,
            warning_code="xirr_not_bracketed",
            warning_message="No XIRR root was found inside the fixed search interval.",
            missing_inputs=("root_within_search_interval",),
            assumptions=assumptions,
            converged=False,
            iterations=0,
        )
    else:
        root = Decimal(0)
        iterations = 0
        converged = False
        for iteration in range(1, _MAX_XIRR_ITERATIONS + 1):
            root = divide(add(low, high), Decimal(2))
            value = _xnpv(root, cash_flows)
            iterations = iteration
            if abs(value) <= npv_tolerance or abs(subtract(high, low)) <= _RATE_INTERVAL_TOLERANCE:
                converged = True
                break
            if (low_value < 0) == (value < 0):
                low = root
                low_value = value
            else:
                high = root
        if not converged:
            return _unavailable_metric(
                method_id=XIRR_METHOD_ID,
                value_kind="annual_rate",
                period_start=period_start,
                period_end=period_end,
                currency=beginning_value.currency,
                coverage=coverage,
                quality=quality,
                warning_code="xirr_non_convergence",
                warning_message="XIRR did not converge within the fixed iteration bound.",
                missing_inputs=("converged_root",),
                assumptions=assumptions,
                converged=False,
                iterations=iterations,
            )

    result = Ratio(persisted_decimal(root))
    return ReturnMetric(
        method_id=XIRR_METHOD_ID,
        version=PERFORMANCE_VERSION,
        value_kind="annual_rate",
        period_start=period_start,
        period_end=period_end,
        reporting_currency=beginning_value.currency,
        coverage=coverage,
        value=result,
        annualized_value=result,
        quality_state=quality,
        converged=True,
        iterations=iterations,
        warnings=(),
        missing_inputs=(),
        assumptions=assumptions,
    )


def _annualized_return(
    value: Decimal,
    *,
    period_start: Instant,
    period_end: Instant,
    minimum_days: int,
) -> Ratio | None:
    elapsed_days = divide(_elapsed_seconds(period_start, period_end), _SECONDS_PER_DAY)
    if elapsed_days < Decimal(minimum_days) or add(Decimal(1), value) <= 0:
        return None
    exponent = divide(Decimal(365), elapsed_days)
    try:
        annualized = subtract(power(add(Decimal(1), value), exponent), Decimal(1))
    except DecimalException:
        return None
    return Ratio(persisted_decimal(annualized))


def calculate_modified_dietz(
    *,
    beginning_value: Money,
    ending_value: Money,
    period_start: Instant,
    period_end: Instant,
    external_flows: tuple[DatedExternalFlow, ...],
    coverage: Coverage,
    beginning_quality: QualityState = QualityState.FRESH,
    ending_quality: QualityState = QualityState.FRESH,
    annualization_minimum_days: int = ANNUALIZATION_MINIMUM_DAYS,
) -> ReturnMetric:
    _validate_period_values(beginning_value, ending_value, period_start, period_end)
    if annualization_minimum_days < 1:
        raise ValueError("annualization minimum must be positive")
    assumptions = (
        "portfolio-perspective external-flow signs",
        "flow weight is the fraction of exact UTC period seconds remaining",
        "flow is treated at its recorded instant",
        "Modified Dietz is not labeled time-weighted return",
    )
    quality = combine_quality(
        (beginning_quality, ending_quality, *(flow.quality_state for flow in external_flows))
    )
    missing = list(_coverage_missing(coverage, period_start, period_end))
    missing.extend(
        _validate_flows(
            external_flows,
            currency=beginning_value.currency,
            period_start=period_start,
            period_end=period_end,
        )
    )
    if not _reliable_for_performance(quality):
        missing.append("reliable_material_inputs")
    if missing:
        return _unavailable_metric(
            method_id=MODIFIED_DIETZ_METHOD_ID,
            value_kind="cumulative_return",
            period_start=period_start,
            period_end=period_end,
            currency=beginning_value.currency,
            coverage=coverage,
            quality=quality,
            warning_code="modified_dietz_prerequisites_missing",
            warning_message="Modified Dietz is unavailable because prerequisites are incomplete.",
            missing_inputs=tuple(dict.fromkeys(missing)),
            assumptions=assumptions,
        )

    period_seconds = _elapsed_seconds(period_start, period_end)
    flow_total = total(flow.amount.amount for flow in external_flows)
    weighted_flows = total(
        multiply(
            divide(_elapsed_seconds(flow.occurred_at, period_end), period_seconds),
            flow.amount.amount,
        )
        for flow in external_flows
    )
    numerator = subtract(
        subtract(ending_value.amount, beginning_value.amount),
        flow_total,
    )
    denominator = add(beginning_value.amount, weighted_flows)
    if denominator <= 0:
        return _unavailable_metric(
            method_id=MODIFIED_DIETZ_METHOD_ID,
            value_kind="cumulative_return",
            period_start=period_start,
            period_end=period_end,
            currency=beginning_value.currency,
            coverage=coverage,
            quality=quality,
            warning_code="modified_dietz_invalid_denominator",
            warning_message=(
                "Modified Dietz is unavailable for a non-positive economic denominator."
            ),
            missing_inputs=("positive_modified_dietz_denominator",),
            assumptions=assumptions,
        )
    result_value = divide(numerator, denominator)
    result = Ratio(persisted_decimal(result_value))
    annualized = _annualized_return(
        result_value,
        period_start=period_start,
        period_end=period_end,
        minimum_days=annualization_minimum_days,
    )
    return ReturnMetric(
        method_id=MODIFIED_DIETZ_METHOD_ID,
        version=PERFORMANCE_VERSION,
        value_kind="cumulative_return",
        period_start=period_start,
        period_end=period_end,
        reporting_currency=beginning_value.currency,
        coverage=coverage,
        value=result,
        annualized_value=annualized,
        quality_state=quality,
        converged=None,
        iterations=None,
        warnings=(),
        missing_inputs=(),
        assumptions=assumptions,
    )


def calculate_time_weighted_return(
    *,
    subperiods: tuple[SubperiodReturnInput, ...],
    coverage: Coverage,
    annualization_minimum_days: int = ANNUALIZATION_MINIMUM_DAYS,
) -> ReturnMetric:
    if not subperiods:
        raise ValueError("at least one TWR subperiod is required")
    if annualization_minimum_days < 1:
        raise ValueError("annualization minimum must be positive")
    ordered = tuple(sorted(subperiods, key=lambda item: item.starts_at.value))
    period_start = ordered[0].starts_at
    period_end = ordered[-1].ends_at
    currency = ordered[0].beginning_value.currency
    assumptions = (
        "each subperiod is bounded by recorded valuations",
        "external flow is applied at the end of its subperiod",
        "no interpolation is used for missing valuations",
    )
    missing = list(_coverage_missing(coverage, period_start, period_end))
    states = [item.quality_state for item in ordered]
    for index, subperiod in enumerate(ordered):
        if subperiod.beginning_value.currency != currency:
            raise DomainError(
                ErrorCode.CURRENCY_MISMATCH,
                "TWR subperiods must use one reporting currency",
                "currency",
            )
        if index:
            previous = ordered[index - 1]
            if previous.ends_at != subperiod.starts_at:
                missing.append("contiguous_subperiod_valuations")
            elif previous.ending_value != subperiod.beginning_value:
                missing.append("subperiod_boundary_value_continuity")
        if not subperiod.complete:
            missing.append("complete_subperiod")
        if subperiod.external_flow_at_end is None:
            missing.append("known_subperiod_external_flow")
        if subperiod.beginning_value.amount <= 0:
            missing.append("positive_subperiod_beginning_value")
    quality = combine_quality(states)
    if not _reliable_for_performance(quality):
        missing.append("reliable_material_inputs")
    if missing:
        return _unavailable_metric(
            method_id=TWR_METHOD_ID,
            value_kind="cumulative_return",
            period_start=period_start,
            period_end=period_end,
            currency=currency,
            coverage=coverage,
            quality=quality,
            warning_code="twr_prerequisites_missing",
            warning_message="TWR is unavailable because required subperiod valuations are missing.",
            missing_inputs=tuple(dict.fromkeys(missing)),
            assumptions=assumptions,
        )

    growth_factors: list[Decimal] = []
    for subperiod in ordered:
        assert subperiod.external_flow_at_end is not None
        growth = divide(
            subtract(
                subperiod.ending_value.amount,
                subperiod.external_flow_at_end.amount,
            ),
            subperiod.beginning_value.amount,
        )
        if growth < 0:
            return _unavailable_metric(
                method_id=TWR_METHOD_ID,
                value_kind="cumulative_return",
                period_start=period_start,
                period_end=period_end,
                currency=currency,
                coverage=coverage,
                quality=quality,
                warning_code="twr_invalid_growth_factor",
                warning_message="A subperiod implies a return below -100 percent.",
                missing_inputs=("nonnegative_subperiod_growth",),
                assumptions=assumptions,
            )
        growth_factors.append(growth)
    result_value = subtract(product(growth_factors), Decimal(1))
    result = Ratio(persisted_decimal(result_value))
    annualized = _annualized_return(
        result_value,
        period_start=period_start,
        period_end=period_end,
        minimum_days=annualization_minimum_days,
    )
    return ReturnMetric(
        method_id=TWR_METHOD_ID,
        version=PERFORMANCE_VERSION,
        value_kind="cumulative_return",
        period_start=period_start,
        period_end=period_end,
        reporting_currency=currency,
        coverage=coverage,
        value=result,
        annualized_value=annualized,
        quality_state=quality,
        converged=None,
        iterations=None,
        warnings=(),
        missing_inputs=(),
        assumptions=assumptions,
    )


def build_performance_summary(
    *,
    xirr: ReturnMetric | None,
    time_weighted_return: ReturnMetric | None,
    modified_dietz: ReturnMetric | None,
) -> PerformanceSummary:
    metrics = tuple(
        metric for metric in (xirr, time_weighted_return, modified_dietz) if metric is not None
    )
    return PerformanceSummary(
        version=PERFORMANCE_VERSION,
        xirr=xirr,
        time_weighted_return=time_weighted_return,
        modified_dietz=modified_dietz,
        quality_state=combine_quality(metric.quality_state for metric in metrics),
        warnings=tuple(warning for metric in metrics for warning in metric.warnings),
    )
