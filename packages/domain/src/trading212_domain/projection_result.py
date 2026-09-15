"""Strict Q18 retained path, distribution and goal result records."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .errors import fail_validation
from .historical import historical_digest
from .projection import (
    PROJECTION_NUMERIC_PROFILE,
    PROJECTION_PERCENTILES,
    PROJECTION_SAMPLER,
    ProjectionInput,
    ProjectionVariant,
    exact_sum,
    financial_decimal,
)
from .projection_validation import (
    validate_point_envelopes,
    validate_projection_path_basis,
    validate_projection_summaries,
    validate_wealth_envelope,
)
from .sources import source_id, source_integer, source_key, source_tuple
from .values import CurrencyCode


def _amounts(record: object, fields: tuple[str, ...], *, signed: bool = False) -> None:
    for field in fields:
        value = financial_decimal(getattr(record, field), field)
        if not signed and value < 0:
            fail_validation("Projection result amount is negative.", field=field)
        object.__setattr__(record, field, value)


def _bool(value: bool, field: str) -> None:
    if type(value) is not bool:
        fail_validation("A boolean projection state is required.", field=field)


def _variant(value: ProjectionVariant) -> None:
    if value not in ("baseline", "contribution_delta", "mean_log_delta"):
        fail_validation("Unknown projection variant.", field="variant")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionAssetValue:
    key: str
    value: Decimal

    def __post_init__(self) -> None:
        source_key(self.key, "asset.key")
        _amounts(self, ("value",))


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionPoint:
    month: int
    nominal: Decimal
    real: Decimal
    assets: tuple[ProjectionAssetValue, ...]
    contributions: Decimal
    withdrawals_requested: Decimal
    withdrawals_funded: Decimal
    unpaid_withdrawals: Decimal
    investment_effect: Decimal
    fees: Decimal
    tax_drag: Decimal
    wealth_residual: Decimal
    allocation_residual: Decimal
    withdrawal_residual: Decimal
    funding_failed: bool
    unpaid_positive_below_quantum: bool

    def __post_init__(self) -> None:
        source_integer(self.month, "month", 0, 600)
        _amounts(
            self,
            (
                "nominal",
                "real",
                "contributions",
                "withdrawals_requested",
                "withdrawals_funded",
                "unpaid_withdrawals",
                "fees",
                "tax_drag",
            ),
        )
        _amounts(
            self,
            ("investment_effect", "wealth_residual", "allocation_residual", "withdrawal_residual"),
            signed=True,
        )
        source_tuple(self.assets, ProjectionAssetValue, "assets", 12)
        if not self.assets or tuple(a.key for a in self.assets) != tuple(
            sorted({a.key for a in self.assets})
        ):
            fail_validation("Retained assets must be unique and canonical.", field="assets")
        for field in ("funding_failed", "unpaid_positive_below_quantum"):
            _bool(getattr(self, field), field)
        if self.unpaid_withdrawals > 0 and not self.funding_failed:
            fail_validation(
                "Unpaid withdrawal cannot have successful funding.", field="funding_failed"
            )
        if self.unpaid_positive_below_quantum != (
            self.funding_failed and self.unpaid_withdrawals == 0
        ):
            fail_validation(
                "Subquantum unpaid evidence is inconsistent.", field="unpaid_positive_below_quantum"
            )
        if self.withdrawals_funded > self.withdrawals_requested:
            fail_validation(
                "Funding exceeds the requested withdrawals.", field="withdrawals_funded"
            )
        if (
            exact_sum((self.nominal, exact_sum(tuple(a.value for a in self.assets)).copy_negate()))
            != self.allocation_residual
        ):
            fail_validation("Retained allocation residual differs.", field="allocation_residual")
        if (
            exact_sum(
                (
                    self.withdrawals_requested,
                    self.withdrawals_funded.copy_negate(),
                    self.unpaid_withdrawals.copy_negate(),
                )
            )
            != self.withdrawal_residual
        ):
            fail_validation("Retained withdrawal residual differs.", field="withdrawal_residual")
        validate_point_envelopes(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionPath:
    index: int
    reporting_currency: CurrencyCode
    points: tuple[ProjectionPoint, ...]
    first_unpaid_month: int | None

    def __post_init__(self) -> None:
        source_integer(self.index, "path.index", 0, 4095)
        if not isinstance(self.reporting_currency, CurrencyCode):
            fail_validation("Path currency is required.", field="reporting_currency")
        source_tuple(self.points, ProjectionPoint, "points", 121)
        if (
            len(self.points) < 2
            or self.points[0].month != 0
            or tuple(p.month for p in self.points) != tuple(sorted({p.month for p in self.points}))
        ):
            fail_validation("Path checkpoints are not canonical.", field="points")
        if self.first_unpaid_month is not None:
            source_integer(self.first_unpaid_month, "first_unpaid_month", 1, self.points[-1].month)
        initial = self.points[0]
        cumulative = (
            "contributions",
            "withdrawals_requested",
            "withdrawals_funded",
            "unpaid_withdrawals",
            "fees",
            "tax_drag",
        )
        if (
            initial.nominal != initial.real
            or initial.investment_effect != 0
            or any(getattr(initial, field) != 0 for field in cumulative)
        ):
            fail_validation("Initial projection point contains later flows.", field="points")
        keys = tuple(a.key for a in initial.assets)
        previous = initial
        for point in self.points:
            expected = (
                self.first_unpaid_month is not None and point.month >= self.first_unpaid_month
            )
            if point.funding_failed != expected:
                fail_validation("Path funding history is inconsistent.", field="funding_failed")
            residual = exact_sum(
                (
                    point.nominal,
                    initial.nominal.copy_negate(),
                    point.contributions.copy_negate(),
                    point.withdrawals_funded,
                    point.investment_effect.copy_negate(),
                    point.fees,
                    point.tax_drag,
                )
            )
            if (
                point.wealth_residual != residual
                or tuple(a.key for a in point.assets) != keys
                or any(getattr(point, field) < getattr(previous, field) for field in cumulative)
            ):
                fail_validation("Retained projection path does not reconcile.", field="points")
            validate_wealth_envelope(initial.nominal, point)
            previous = point


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionChunk:
    input_digest: str
    variant: ProjectionVariant
    paths: tuple[ProjectionPath, ...]

    def __post_init__(self) -> None:
        historical_digest(self.input_digest, "input_digest")
        _variant(self.variant)
        source_tuple(self.paths, ProjectionPath, "paths", 32)
        if not self.paths or tuple(p.index for p in self.paths) != tuple(
            range(self.paths[0].index, self.paths[0].index + len(self.paths))
        ):
            fail_validation("A chunk contains one contiguous absolute path range.", field="paths")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionQuantiles:
    probabilities: tuple[Decimal, ...]
    values: tuple[Decimal, ...]

    def __post_init__(self) -> None:
        source_tuple(self.probabilities, Decimal, "probabilities", 5)
        if self.probabilities != PROJECTION_PERCENTILES:
            fail_validation("Projection percentile set differs.", field="probabilities")
        source_tuple(self.values, Decimal, "values", 5)
        if len(self.values) != 5 or tuple(sorted(self.values)) != self.values:
            fail_validation("Projection quantiles are invalid.", field="values")
        for value in self.values:
            if financial_decimal(value, "quantile") < 0:
                fail_validation("Quantile is negative.", field="quantile")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionDistributionPoint:
    month: int
    nominal_mean: Decimal
    real_mean: Decimal
    nominal: ProjectionQuantiles
    real: ProjectionQuantiles
    funding_failed_paths: int

    def __post_init__(self) -> None:
        source_integer(self.month, "month", 0, 600)
        source_integer(self.funding_failed_paths, "funding_failed_paths", 0, 4096)
        _amounts(self, ("nominal_mean", "real_mean"))
        if not isinstance(self.nominal, ProjectionQuantiles) or not isinstance(
            self.real, ProjectionQuantiles
        ):
            fail_validation("Typed projection quantiles are required.", field="quantiles")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionHistogramBin:
    lower: Decimal
    upper: Decimal
    upper_inclusive: bool
    count: int

    def __post_init__(self) -> None:
        _amounts(self, ("lower", "upper"))
        _bool(self.upper_inclusive, "upper_inclusive")
        source_integer(self.count, "count", 0, 4096)
        if self.lower > self.upper or (self.lower == self.upper and not self.upper_inclusive):
            fail_validation("Histogram interval is invalid.", field="histogram")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionHistogram:
    observed_minimum: Decimal
    observed_maximum: Decimal
    bins: tuple[ProjectionHistogramBin, ...]
    boundary_rule: Literal["q18_enclosing_ceiling_v1"] = "q18_enclosing_ceiling_v1"

    def __post_init__(self) -> None:
        _amounts(self, ("observed_minimum", "observed_maximum"))
        source_tuple(self.bins, ProjectionHistogramBin, "histogram.bins", 20)
        if self.boundary_rule != "q18_enclosing_ceiling_v1" or not self.bins:
            fail_validation("Histogram boundary rule is invalid.", field="histogram")
        if (
            not self.bins[0].lower
            == self.observed_minimum
            <= self.observed_maximum
            <= self.bins[-1].upper
        ):
            fail_validation("Histogram does not enclose its observations.", field="histogram")
        width = exact_sum((self.bins[0].upper, self.bins[0].lower.copy_negate()))
        for i, item in enumerate(self.bins):
            if (
                item.upper_inclusive != (i == len(self.bins) - 1)
                or (i and self.bins[i - 1].upper != item.lower)
                or exact_sum((item.upper, item.lower.copy_negate())) != width
            ):
                fail_validation(
                    "Histogram intervals are not contiguous equal widths.", field="histogram"
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionGoalResult:
    goal_version_id: str
    basis: Literal["nominal", "real"]
    target: Decimal
    paths: int
    successes: int
    probability: Decimal
    interval_low: Decimal
    interval_high: Decimal
    probability_objective: Decimal
    objective_met: bool
    mean_shortfall: Decimal
    shortfalls: ProjectionQuantiles
    funding_failed_paths: int
    method: Literal["goal_analysis_v1"] = "goal_analysis_v1"
    interval_method: Literal["wilson_95_v1"] = "wilson_95_v1"

    def __post_init__(self) -> None:
        source_id(self.goal_version_id, "goal_version_id")
        if (
            self.basis not in ("nominal", "real")
            or self.method != "goal_analysis_v1"
            or self.interval_method != "wilson_95_v1"
        ):
            fail_validation("Goal result method differs.", field="goal")
        source_integer(self.paths, "paths", 1, 4096)
        source_integer(self.successes, "successes", 0, self.paths)
        source_integer(self.funding_failed_paths, "funding_failed_paths", 0, self.paths)
        _amounts(
            self,
            (
                "target",
                "probability",
                "interval_low",
                "interval_high",
                "probability_objective",
                "mean_shortfall",
            ),
        )
        if (
            not 0 <= self.interval_low <= self.probability <= self.interval_high <= 1
            or self.probability_objective > 1
        ):
            fail_validation("Goal sampling interval is invalid.", field="interval")
        _bool(self.objective_met, "objective_met")
        if self.objective_met != (self.probability >= self.probability_objective) or not isinstance(
            self.shortfalls, ProjectionQuantiles
        ):
            fail_validation("Goal result objective/quantiles differ.", field="goal")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionVariantResult:
    variant: ProjectionVariant
    paths: tuple[ProjectionPath, ...]
    distributions: tuple[ProjectionDistributionPoint, ...]
    nominal_histogram: ProjectionHistogram
    real_histogram: ProjectionHistogram
    goal: ProjectionGoalResult | None

    def __post_init__(self) -> None:
        _variant(self.variant)
        source_tuple(self.paths, ProjectionPath, "paths", 4096)
        if not self.paths or tuple(p.index for p in self.paths) != tuple(range(len(self.paths))):
            fail_validation("Complete result requires every absolute path.", field="paths")
        source_tuple(self.distributions, ProjectionDistributionPoint, "distributions", 121)
        if tuple(p.month for p in self.distributions) != tuple(
            p.month for p in self.paths[0].points
        ):
            fail_validation("Distribution checkpoints differ.", field="distributions")
        for histogram in (self.nominal_histogram, self.real_histogram):
            if not isinstance(histogram, ProjectionHistogram) or sum(
                b.count for b in histogram.bins
            ) != len(self.paths):
                fail_validation("Histogram count differs.", field="histogram")
        if self.goal is not None and (
            not isinstance(self.goal, ProjectionGoalResult) or self.goal.paths != len(self.paths)
        ):
            fail_validation("Goal path count differs.", field="goal")
        if self.goal is not None:
            successes = sum(
                (p.points[-1].nominal if self.goal.basis == "nominal" else p.points[-1].real)
                >= self.goal.target
                and not p.points[-1].funding_failed
                for p in self.paths
            )
            if self.goal.successes != successes or self.goal.funding_failed_paths != sum(
                p.points[-1].funding_failed for p in self.paths
            ):
                fail_validation("Goal outcomes disagree with canonical paths.", field="goal")
        validate_projection_summaries(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionCalculation:
    inputs: ProjectionInput
    input_digest: str
    variants: tuple[ProjectionVariantResult, ...]
    numerical_zero_pivots: tuple[int, ...]
    method: Literal["projection_v1"] = "projection_v1"
    method_version: Literal["1.0.0"] = "1.0.0"
    numeric_profile: Literal["premium_decimal96_q18_v1"] = "premium_decimal96_q18_v1"
    sampler: Literal["sha256_counter_polar_v1"] = "sha256_counter_polar_v1"

    def __post_init__(self) -> None:
        if not isinstance(self.inputs, ProjectionInput):
            fail_validation("Canonical projection inputs are required.", field="inputs")
        historical_digest(self.input_digest, "input_digest")
        from .projection_serialization import projection_input_digest

        if projection_input_digest(self.inputs) != self.input_digest:
            fail_validation("Projection result input digest differs.", field="input_digest")
        if (
            self.method != "projection_v1"
            or self.method_version != "1.0.0"
            or self.numeric_profile != PROJECTION_NUMERIC_PROFILE
            or self.sampler != PROJECTION_SAMPLER
        ):
            fail_validation("Projection method/profile differs.", field="method")
        source_tuple(self.variants, ProjectionVariantResult, "variants", 3)
        if tuple(v.variant for v in self.variants) != self.inputs.variants or any(
            len(v.paths) != self.inputs.paths for v in self.variants
        ):
            fail_validation("Projection variants or paths are incomplete.", field="variants")
        keys = tuple(a.key for a in self.inputs.assumptions.assets)
        for variant in self.variants:
            for path in variant.paths:
                if (
                    path.reporting_currency != self.inputs.assumptions.reporting_currency
                    or tuple(p.month for p in path.points) != self.inputs.retained_months
                    or tuple(a.key for a in path.points[0].assets) != keys
                    or path.points[0].nominal != self.inputs.initial.value.amount
                ):
                    fail_validation("Projection path and pinned input differ.", field="paths")
                validate_projection_path_basis(self.inputs, path, variant.variant)
            if (variant.goal is None) != (self.inputs.goal is None):
                fail_validation("Projection goal result is missing or unexpected.", field="goal")
            if (
                variant.goal is not None
                and self.inputs.goal is not None
                and (
                    variant.goal.goal_version_id != self.inputs.goal.version_id
                    or variant.goal.target != self.inputs.goal.target.amount
                    or variant.goal.basis != self.inputs.goal.basis
                    or variant.goal.probability_objective != self.inputs.goal.probability_objective
                )
            ):
                fail_validation("Projection goal and pinned definition differ.", field="goal")
        source_tuple(self.numerical_zero_pivots, int, "numerical_zero_pivots", 12)
        if tuple(sorted(set(self.numerical_zero_pivots))) != self.numerical_zero_pivots:
            fail_validation("Repeated numerical pivot.", field="numerical_zero_pivots")
        for pivot in self.numerical_zero_pivots:
            source_integer(pivot, "pivot", 0, len(self.inputs.assumptions.assets) - 1)
