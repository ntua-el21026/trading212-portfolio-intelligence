"""Exact, currency-bearing projection point pages and saved goal estimates."""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from .projection_inputs import (
    AssumptionVersionContent,
    ProjectionMoney,
    ProjectionNonnegativeMoney,
    ProjectionPathCount,
    ProjectionRunSelection,
    ProjectionSchema,
    exact_sum,
)
from .sources import CalendarDate, SourceKey, SourceQuality
from .targets import (
    AwareInstant,
    CurrencyString,
    Cursor,
    Digest,
    UUIDString,
    WeightString,
)

ProjectionVariant = Literal["baseline", "contribution_delta", "mean_log_delta"]
ProjectionDerivedQuality = Literal["estimated", "partial", "unreconciled", "failed"]
ProjectionCount = Annotated[StrictInt, Field(ge=0, le=4096)]
ProjectionOrdinal = Annotated[StrictInt, Field(ge=0, le=3 * 4096 * 121)]
ProjectionWarning = Literal[
    "model_assumptions",
    "sampling_uncertainty",
    "model_uncertainty",
    "modeled_tax_drag",
    "numerical_zero_pivots",
    "source_stale",
    "source_partial",
    "source_unreconciled",
    "source_failed",
    "funding_failed",
    "unpaid_positive_below_quantum",
]
PERCENTILES = (Decimal(".05"), Decimal(".25"), Decimal(".50"), Decimal(".75"), Decimal(".95"))


def same_currency(values: list[ProjectionMoney]) -> str:
    if not values or len({value.currency for value in values}) != 1:
        raise ValueError("Projection financial currencies differ.")
    return values[0].currency


def boundary(anchor: date, month: int) -> date:
    year, zero_month = divmod((anchor.year - 1) * 12 + anchor.month - 1 + month, 12)
    if year >= 9999:
        raise ValueError("Projection calendar exceeds supported dates.")
    return date(year + 1, zero_month + 1, min(anchor.day, monthrange(year + 1, zero_month + 1)[1]))


class ProjectionPreview[T](ProjectionSchema):
    items: Annotated[list[T], Field(max_length=64)]
    omitted_count: Annotated[StrictInt, Field(ge=0, le=250000)]


class ProjectionEvidenceView(ProjectionSchema):
    role: Literal["observed_snapshot", "calibration"]
    subject_id: UUIDString
    content_digest: Digest
    quality: SourceQuality
    source_reference_ids: ProjectionPreview[UUIDString]


class ProjectionQuantilesView(ProjectionSchema):
    probabilities: Annotated[list[WeightString], Field(min_length=5, max_length=5)]
    values: Annotated[list[ProjectionMoney], Field(min_length=5, max_length=5)]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if tuple(Decimal(value) for value in self.probabilities) != PERCENTILES:
            raise ValueError("Projection quantile probabilities differ.")
        amounts = [Decimal(value.amount) for value in self.values]
        if amounts != sorted(amounts):
            raise ValueError("Projection quantiles are unordered.")
        same_currency(self.values)
        return self


class ProjectionNonnegativeQuantilesView(ProjectionQuantilesView):
    @model_validator(mode="after")
    def nonnegative(self) -> Self:
        if any(Decimal(value.amount) < 0 for value in self.values):
            raise ValueError("Wealth or shortfall quantiles cannot be negative.")
        return self


class ProjectionAmountSummaryView(ProjectionSchema):
    mean: ProjectionMoney
    quantiles: ProjectionQuantilesView

    @model_validator(mode="after")
    def currency(self) -> Self:
        same_currency([self.mean, *self.quantiles.values])
        return self


class ProjectionCashFlowSummaryView(ProjectionSchema):
    contributions: ProjectionAmountSummaryView
    withdrawals_requested: ProjectionAmountSummaryView
    withdrawals_funded: ProjectionAmountSummaryView
    unpaid_withdrawals: ProjectionAmountSummaryView
    investment_effect: ProjectionAmountSummaryView
    fees: ProjectionAmountSummaryView
    tax_drag: ProjectionAmountSummaryView
    funding_failed_paths: ProjectionCount
    unpaid_positive_below_quantum_paths: ProjectionCount

    @model_validator(mode="after")
    def flow_states(self) -> Self:
        nonnegative = [
            self.contributions,
            self.withdrawals_requested,
            self.withdrawals_funded,
            self.unpaid_withdrawals,
            self.fees,
            self.tax_drag,
        ]
        for summary in nonnegative:
            if any(
                Decimal(value.amount) < 0 for value in [summary.mean, *summary.quantiles.values]
            ):
                raise ValueError("Cumulative cash flow cannot be negative.")
        same_currency([value.mean for value in [*nonnegative, self.investment_effect]])
        if self.unpaid_positive_below_quantum_paths > self.funding_failed_paths:
            raise ValueError("Subquantum unpaid paths exceed funding failures.")
        return self


class ProjectionDistributionView(ProjectionSchema):
    month: Annotated[StrictInt, Field(ge=0, le=600)]
    on: CalendarDate
    nominal_mean: ProjectionNonnegativeMoney
    real_mean: ProjectionNonnegativeMoney
    nominal: ProjectionNonnegativeQuantilesView
    real: ProjectionNonnegativeQuantilesView
    funding_failed_paths: ProjectionCount

    @model_validator(mode="after")
    def currency(self) -> Self:
        same_currency([self.nominal_mean, self.real_mean, *self.nominal.values, *self.real.values])
        return self


class ProjectionHistogramBinView(ProjectionSchema):
    lower: ProjectionNonnegativeMoney
    upper: ProjectionNonnegativeMoney
    upper_inclusive: StrictBool
    count: ProjectionCount

    @model_validator(mode="after")
    def interval(self) -> Self:
        same_currency([self.lower, self.upper])
        if Decimal(self.lower.amount) > Decimal(self.upper.amount) or (
            Decimal(self.lower.amount) == Decimal(self.upper.amount) and not self.upper_inclusive
        ):
            raise ValueError("Histogram interval is invalid.")
        return self


class ProjectionHistogramView(ProjectionSchema):
    observed_minimum: ProjectionNonnegativeMoney
    observed_maximum: ProjectionNonnegativeMoney
    bins: Annotated[list[ProjectionHistogramBinView], Field(min_length=1, max_length=20)]
    boundary_rule: Literal["q18_enclosing_ceiling_v1"] = "q18_enclosing_ceiling_v1"

    @model_validator(mode="after")
    def enclosed(self) -> Self:
        same_currency(
            [self.observed_minimum, self.observed_maximum, *(item.lower for item in self.bins)]
        )
        if (
            not Decimal(self.bins[0].lower.amount)
            == Decimal(self.observed_minimum.amount)
            <= Decimal(self.observed_maximum.amount)
            <= Decimal(self.bins[-1].upper.amount)
        ):
            raise ValueError("Histogram does not enclose observed extrema.")
        widths = [
            exact_sum([Decimal(item.upper.amount), Decimal(item.lower.amount).copy_negate()])
            for item in self.bins
        ]
        if any(width != widths[0] for width in widths):
            raise ValueError("Histogram widths differ.")
        for index, item in enumerate(self.bins):
            if item.upper_inclusive != (index == len(self.bins) - 1) or (
                index and Decimal(self.bins[index - 1].upper.amount) != Decimal(item.lower.amount)
            ):
                raise ValueError("Histogram bins are not contiguous with a final inclusive edge.")
        return self


class ProjectionGoalEstimateView(ProjectionSchema):
    goal_version_id: UUIDString
    basis: Literal["nominal", "real"]
    target: ProjectionNonnegativeMoney
    paths: ProjectionPathCount
    successes: ProjectionCount
    probability: WeightString
    interval_low: WeightString
    interval_high: WeightString
    probability_objective: WeightString
    objective_met: StrictBool
    mean_shortfall: ProjectionNonnegativeMoney
    shortfalls: ProjectionNonnegativeQuantilesView
    funding_failed_paths: ProjectionCount
    method: Literal["goal_analysis_v1"] = "goal_analysis_v1"
    interval_method: Literal["wilson_95_v1"] = "wilson_95_v1"
    automatic_goal_acceptance: Literal[False] = False

    @model_validator(mode="after")
    def probability_basis(self) -> Self:
        same_currency([self.target, self.mean_shortfall, *self.shortfalls.values])
        if self.successes + self.funding_failed_paths > self.paths:
            raise ValueError("Successful paths cannot have unpaid funding events.")
        with localcontext(
            Context(prec=96, rounding=ROUND_HALF_EVEN, Emin=-999, Emax=999, flags=[], traps=[])
        ):
            expected = (Decimal(self.successes) / Decimal(self.paths)).quantize(Decimal("1e-18"))
        probability = Decimal(self.probability)
        if probability != expected or not Decimal(self.interval_low) <= probability <= Decimal(
            self.interval_high
        ):
            raise ValueError("Goal probability does not agree with saved outcome counts.")
        if self.objective_met != (probability >= Decimal(self.probability_objective)):
            raise ValueError("The modeled objective decision differs.")
        return self


class ProjectionVariantSummaryView(ProjectionSchema):
    variant: ProjectionVariant
    distributions: Annotated[list[ProjectionDistributionView], Field(min_length=2, max_length=121)]
    nominal_histogram: ProjectionHistogramView
    real_histogram: ProjectionHistogramView
    cash_flows: ProjectionCashFlowSummaryView
    goal: ProjectionGoalEstimateView | None


class ProjectionAssetValueView(ProjectionSchema):
    key: SourceKey
    value: ProjectionNonnegativeMoney


class ProjectionPointView(ProjectionSchema):
    month: Annotated[StrictInt, Field(ge=0, le=600)]
    nominal: ProjectionNonnegativeMoney
    real: ProjectionNonnegativeMoney
    assets: Annotated[list[ProjectionAssetValueView], Field(min_length=1, max_length=12)]
    contributions: ProjectionNonnegativeMoney
    withdrawals_requested: ProjectionNonnegativeMoney
    withdrawals_funded: ProjectionNonnegativeMoney
    unpaid_withdrawals: ProjectionNonnegativeMoney
    investment_effect: ProjectionMoney
    fees: ProjectionNonnegativeMoney
    tax_drag: ProjectionNonnegativeMoney
    wealth_residual: ProjectionMoney
    allocation_residual: ProjectionMoney
    withdrawal_residual: ProjectionMoney
    funding_failed: StrictBool
    unpaid_positive_below_quantum: StrictBool

    @model_validator(mode="after")
    def financial_identity(self) -> Self:
        values = [
            self.nominal,
            self.real,
            self.contributions,
            self.withdrawals_requested,
            self.withdrawals_funded,
            self.unpaid_withdrawals,
            self.investment_effect,
            self.fees,
            self.tax_drag,
            self.wealth_residual,
            self.allocation_residual,
            self.withdrawal_residual,
            *(item.value for item in self.assets),
        ]
        same_currency(values)
        keys = [item.key for item in self.assets]
        if keys != sorted(set(keys)):
            raise ValueError("Point assets must be unique and canonical.")
        funded, requested, unpaid = (
            Decimal(value.amount)
            for value in (
                self.withdrawals_funded,
                self.withdrawals_requested,
                self.unpaid_withdrawals,
            )
        )
        if (
            funded > requested
            or (unpaid > 0 and not self.funding_failed)
            or self.unpaid_positive_below_quantum != (self.funding_failed and unpaid == 0)
        ):
            raise ValueError("Unpaid funding flags are inconsistent.")
        if exact_sum([requested, funded.copy_negate(), unpaid.copy_negate()]) != Decimal(
            self.withdrawal_residual.amount
        ):
            raise ValueError("Withdrawal residual differs.")
        if exact_sum(
            [
                Decimal(self.nominal.amount),
                *(Decimal(item.value.amount).copy_negate() for item in self.assets),
            ]
        ) != Decimal(self.allocation_residual.amount):
            raise ValueError("Asset allocation residual differs.")
        if self.month == 0 and (
            Decimal(self.nominal.amount) != Decimal(self.real.amount)
            or any(
                Decimal(value.amount) != 0
                for value in [
                    self.contributions,
                    self.withdrawals_requested,
                    self.withdrawals_funded,
                    self.unpaid_withdrawals,
                    self.investment_effect,
                    self.fees,
                    self.tax_drag,
                ]
            )
            or self.funding_failed
        ):
            raise ValueError("Month zero cannot contain later flows or funding events.")
        return self


class ProjectionPointRow(ProjectionSchema):
    ordinal: ProjectionOrdinal
    variant: ProjectionVariant
    path_index: Annotated[StrictInt, Field(ge=0, le=4095)]
    point_index: Annotated[StrictInt, Field(ge=0, le=120)]
    path_point_count: Annotated[StrictInt, Field(ge=2, le=121)]
    first_unpaid_month: Annotated[StrictInt, Field(ge=1, le=600)] | None
    on: CalendarDate
    point: ProjectionPointView

    @model_validator(mode="after")
    def retained_path_identity(self) -> Self:
        if self.point_index >= self.path_point_count or self.point.funding_failed != (
            self.first_unpaid_month is not None and self.point.month >= self.first_unpaid_month
        ):
            raise ValueError("Retained point and path funding identity differ.")
        return self


class ProjectionPointPage(ProjectionSchema):
    items: Annotated[list[ProjectionPointRow], Field(max_length=100)]
    point_limit: Annotated[StrictInt, Field(ge=1, le=100)]
    next_cursor: Cursor | None
    total: ProjectionOrdinal
    start_ordinal: ProjectionOrdinal

    @model_validator(mode="after")
    def contiguous_page(self) -> Self:
        end = self.start_ordinal + len(self.items)
        if (
            len(self.items) > self.point_limit
            or end > self.total
            or [item.ordinal for item in self.items] != list(range(self.start_ordinal, end))
            or (self.next_cursor is not None) != (end < self.total)
            or (not self.items and self.total)
        ):
            raise ValueError("Projection point page is not a contiguous complete-row slice.")
        return self


class ProjectionResultContextView(ProjectionSchema):
    account_id: UUIDString
    run_id: UUIDString
    result_id: UUIDString
    capture_digest: Digest
    numerical_input_digest: Digest
    saved_result_digest: Digest
    assumption_version_digest: Digest
    goal_version_digest: Digest | None
    selection: ProjectionRunSelection
    assumptions: AssumptionVersionContent
    anchor_date: CalendarDate
    terminal_date: CalendarDate
    snapshot_valuation_at: AwareInstant | None
    source_cutoff_at: AwareInstant | None
    calculated_at: AwareInstant
    reporting_currency: CurrencyString
    quality: ProjectionDerivedQuality
    source_evidence: ProjectionPreview[ProjectionEvidenceView]
    warnings: ProjectionPreview[ProjectionWarning]
    numerical_zero_pivots: Annotated[
        list[Annotated[StrictInt, Field(ge=0, le=11)]], Field(max_length=12)
    ]
    method: Literal["projection_v1"] = "projection_v1"
    method_version: Literal["1.0.0"] = "1.0.0"
    schema_version: Literal["1.0.0"] = "1.0.0"
    numeric_profile: Literal["premium_decimal96_q18_v1"] = "premium_decimal96_q18_v1"
    sampler: Literal["sha256_counter_polar_v1"] = "sha256_counter_polar_v1"
    calendar_rule: Literal["calendar_anniversary_clamped_v1"] = "calendar_anniversary_clamped_v1"
    interpretation: Literal["model_estimate_not_guaranteed_forecast"] = (
        "model_estimate_not_guaranteed_forecast"
    )

    @model_validator(mode="after")
    def saved_basis(self) -> Self:
        selection = self.selection
        if (
            self.account_id != selection.account_id
            or self.reporting_currency != self.assumptions.reporting_currency
            or self.reporting_currency != selection.schedule.base_monthly.currency
        ):
            raise ValueError("Saved projection account or currency differs.")
        if [(item.key, Decimal(item.weight)) for item in selection.allocation] != [
            (item.key, Decimal(item.weight)) for item in self.assumptions.assets
        ]:
            raise ValueError("Saved allocation differs from the immutable assumptions.")
        if boundary(self.anchor_date, selection.months) != self.terminal_date:
            raise ValueError("Saved terminal calendar boundary differs.")
        if (selection.goal_version_id is None) != (self.goal_version_digest is None):
            raise ValueError("Goal version and digest differ.")
        initial = selection.initial
        if initial.kind == "observed_snapshot":
            if (
                self.snapshot_valuation_at is None
                or self.snapshot_valuation_at.date() != self.anchor_date
            ):
                raise ValueError("Observed anchor must preserve the UTC snapshot valuation.")
        elif (
            self.snapshot_valuation_at is not None
            or initial.modeled_anchor_date != self.anchor_date
        ):
            raise ValueError("Modeled anchor differs from the explicit selection.")
        quality_order = {
            "fresh": 0,
            "stale": 1,
            "estimated": 2,
            "unreconciled": 3,
            "partial": 4,
            "failed": 5,
        }
        if any(
            quality_order[item.quality] > quality_order[self.quality]
            for item in self.source_evidence.items
        ):
            raise ValueError("Projection quality cannot improve retained source quality.")
        if self.numerical_zero_pivots != sorted(set(self.numerical_zero_pivots)) or any(
            index >= len(self.assumptions.assets) for index in self.numerical_zero_pivots
        ):
            raise ValueError("Numerical zero pivots differ from the selected assets.")
        return self


class ProjectionResultPage(ProjectionSchema):
    context: ProjectionResultContextView
    variants: Annotated[list[ProjectionVariantSummaryView], Field(min_length=1, max_length=3)]
    points: ProjectionPointPage
    content_digest: Digest
    view_version: Literal["projection_points_v1"] = "projection_points_v1"

    @model_validator(mode="after")
    def complete_summary_and_page(self) -> Self:
        selected = self.context.selection
        variants = (
            ["baseline", "contribution_delta", "mean_log_delta"]
            if selected.sensitivity is not None
            else ["baseline"]
        )
        months, paths = selected.retained_months, selected.paths
        if [item.variant for item in self.variants] != variants or self.points.total != len(
            variants
        ) * paths * len(months):
            raise ValueError("Projection variant or point totals differ.")
        for variant in self.variants:
            if [point.month for point in variant.distributions] != months:
                raise ValueError("Retained distribution months differ.")
            for point in variant.distributions:
                if (
                    point.on != boundary(self.context.anchor_date, point.month)
                    or point.funding_failed_paths > paths
                    or point.nominal_mean.currency != self.context.reporting_currency
                ):
                    raise ValueError("Saved distribution calendar/currency/count differs.")
            if any(
                sum(item.count for item in histogram.bins) != paths
                or histogram.observed_minimum.currency != self.context.reporting_currency
                for histogram in (variant.nominal_histogram, variant.real_histogram)
            ):
                raise ValueError("Terminal histogram counts or currency differ.")
            if (
                variant.cash_flows.funding_failed_paths
                != variant.distributions[-1].funding_failed_paths
                or variant.cash_flows.contributions.mean.currency != self.context.reporting_currency
            ):
                raise ValueError("Cash flow summary count or currency differs.")
            if (variant.goal is None) != (selected.goal_version_id is None) or (
                variant.goal is not None
                and (
                    variant.goal.goal_version_id != selected.goal_version_id
                    or variant.goal.paths != paths
                    or variant.goal.funding_failed_paths
                    != variant.distributions[-1].funding_failed_paths
                    or variant.goal.target.currency != self.context.reporting_currency
                )
            ):
                raise ValueError("Goal summary and saved selection differ.")
        for row in self.points.items:
            variant_index, within_variant = divmod(row.ordinal, paths * len(months))
            path_index, point_index = divmod(within_variant, len(months))
            if (
                row.variant != variants[variant_index]
                or row.path_index != path_index
                or row.point_index != point_index
                or row.path_point_count != len(months)
                or row.point.month != months[point_index]
                or row.on != boundary(self.context.anchor_date, row.point.month)
                or row.point.nominal.currency != self.context.reporting_currency
                or [asset.key for asset in row.point.assets]
                != [asset.key for asset in self.context.assumptions.assets]
                or (row.first_unpaid_month is not None and row.first_unpaid_month > selected.months)
            ):
                raise ValueError("Point page does not match the saved path/point identity.")
        if (
            len(
                json.dumps(
                    self.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            )
            > 1024 * 1024
        ):
            raise ValueError("Projection financial page exceeds 1 MiB.")
        return self
