"""Complete normalized retained rows, copied without resampling or rounding.

The fixed iterators permit bounded insertion and comparison batches. Stable child
identities depend on absolute paths/checkpoints rather than delivery attempts.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid5

from trading212_domain.projection_result import ProjectionCalculation, ProjectionChunk

_POINT_FIELDS = (
    "month",
    "nominal",
    "real",
    "contributions",
    "withdrawals_requested",
    "withdrawals_funded",
    "unpaid_withdrawals",
    "investment_effect",
    "fees",
    "tax_drag",
    "wealth_residual",
    "allocation_residual",
    "withdrawal_residual",
    "funding_failed",
    "unpaid_positive_below_quantum",
)


def projection_path_id(run_id: UUID, variant: str, index: int) -> UUID:
    return uuid5(run_id, f"projection_paths:{variant}:{index}")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionChunkRows:
    run_id: UUID
    chunk_id: UUID
    value: ProjectionChunk

    def paths(self) -> Iterator[dict[str, object]]:
        for path in self.value.paths:
            yield dict(
                id=projection_path_id(self.run_id, self.value.variant, path.index),
                run_id=self.run_id,
                chunk_id=self.chunk_id,
                variant=self.value.variant,
                path_index=path.index,
                first_unpaid_month=path.first_unpaid_month,
            )

    def points(self) -> Iterator[dict[str, object]]:
        for path in self.value.paths:
            parent = projection_path_id(self.run_id, self.value.variant, path.index)
            for index, point in enumerate(path.points):
                yield dict(
                    id=uuid5(parent, f"projection_points:{point.month}"),
                    run_id=self.run_id,
                    path_id=parent,
                    point_index=index,
                    **{field: getattr(point, field) for field in _POINT_FIELDS},
                )

    def assets(self) -> Iterator[dict[str, object]]:
        for path in self.value.paths:
            parent = projection_path_id(self.run_id, self.value.variant, path.index)
            for point in path.points:
                identifier = uuid5(parent, f"projection_points:{point.month}")
                for index, asset in enumerate(point.assets):
                    yield dict(
                        id=uuid5(identifier, f"projection_point_assets:{index}"),
                        run_id=self.run_id,
                        point_id=identifier,
                        asset_index=index,
                        value=asset.value,
                    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionResultRows:
    result_id: UUID
    value: ProjectionCalculation

    def pivots(self) -> Iterator[dict[str, object]]:
        for index in self.value.numerical_zero_pivots:
            yield dict(
                id=uuid5(self.result_id, f"projection_zero_pivots:{index}"),
                result_id=self.result_id,
                asset_index=index,
            )

    def distributions(self) -> Iterator[dict[str, object]]:
        for variant in self.value.variants:
            for point in variant.distributions:
                yield dict(
                    id=uuid5(
                        self.result_id, f"projection_distributions:{variant.variant}:{point.month}"
                    ),
                    result_id=self.result_id,
                    variant=variant.variant,
                    month=point.month,
                    nominal_mean=point.nominal_mean,
                    real_mean=point.real_mean,
                    funding_failed_paths=point.funding_failed_paths,
                )

    def distribution_quantiles(self) -> Iterator[dict[str, object]]:
        for variant in self.value.variants:
            for point in variant.distributions:
                parent = uuid5(
                    self.result_id, f"projection_distributions:{variant.variant}:{point.month}"
                )
                for basis, quantiles in (("nominal", point.nominal), ("real", point.real)):
                    for index, (probability, value) in enumerate(
                        zip(quantiles.probabilities, quantiles.values, strict=True)
                    ):
                        yield dict(
                            id=uuid5(parent, f"projection_distribution_quantiles:{basis}:{index}"),
                            distribution_id=parent,
                            basis=basis,
                            probability=probability,
                            value=value,
                        )

    def histograms(self) -> Iterator[dict[str, object]]:
        for variant in self.value.variants:
            for basis, histogram in (
                ("nominal", variant.nominal_histogram),
                ("real", variant.real_histogram),
            ):
                yield dict(
                    id=uuid5(self.result_id, f"projection_histograms:{variant.variant}:{basis}"),
                    result_id=self.result_id,
                    variant=variant.variant,
                    basis=basis,
                    observed_minimum=histogram.observed_minimum,
                    observed_maximum=histogram.observed_maximum,
                    bin_count=len(histogram.bins),
                    boundary_rule=histogram.boundary_rule,
                )

    def histogram_bins(self) -> Iterator[dict[str, object]]:
        for variant in self.value.variants:
            for basis, histogram in (
                ("nominal", variant.nominal_histogram),
                ("real", variant.real_histogram),
            ):
                parent = uuid5(self.result_id, f"projection_histograms:{variant.variant}:{basis}")
                for index, item in enumerate(histogram.bins):
                    yield dict(
                        id=uuid5(parent, f"projection_histogram_bins:{index}"),
                        histogram_id=parent,
                        bin_index=index,
                        lower=item.lower,
                        upper=item.upper,
                        upper_inclusive=item.upper_inclusive,
                        count=item.count,
                    )

    def goals(self) -> Iterator[dict[str, object]]:
        for variant in self.value.variants:
            goal = variant.goal
            if goal is None:
                continue
            yield dict(
                id=uuid5(self.result_id, f"projection_goal_analyses:{variant.variant}"),
                result_id=self.result_id,
                variant=variant.variant,
                goal_version_id=UUID(goal.goal_version_id),
                basis=goal.basis,
                target=goal.target,
                paths=goal.paths,
                successes=goal.successes,
                probability=goal.probability,
                interval_low=goal.interval_low,
                interval_high=goal.interval_high,
                probability_objective=goal.probability_objective,
                mean_shortfall=goal.mean_shortfall,
                objective_met=goal.objective_met,
                funding_failed_paths=goal.funding_failed_paths,
                method=goal.method,
                interval_method=goal.interval_method,
            )

    def goal_quantiles(self) -> Iterator[dict[str, object]]:
        for variant in self.value.variants:
            goal = variant.goal
            if goal is None:
                continue
            parent = uuid5(self.result_id, f"projection_goal_analyses:{variant.variant}")
            for index, (probability, value) in enumerate(
                zip(goal.shortfalls.probabilities, goal.shortfalls.values, strict=True)
            ):
                yield dict(
                    id=uuid5(parent, f"projection_goal_shortfall_quantiles:{index}"),
                    analysis_id=parent,
                    probability=probability,
                    value=value,
                )
