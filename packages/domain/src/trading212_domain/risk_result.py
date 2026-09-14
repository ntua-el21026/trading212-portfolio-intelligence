"""Immutable private risk calculation and normalized matrix/model projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from .enums import QualityState
from .errors import fail_validation
from .historical import historical_digest
from .risk import RiskDefinitionContent, RiskMetric, RiskSeriesStatistics
from .risk_history import RiskHistory
from .sources import source_id, source_integer, source_tuple
from .values import exact_decimal, require_utc


def _metrics(*values: RiskMetric) -> None:
    if any(not isinstance(item, RiskMetric) for item in values):
        fail_validation("Canonical risk metrics are required.", field="metrics")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskMatrix:
    keys: tuple[str, ...]
    requested_intervals: int
    used_intervals: int
    omitted_intervals: int
    covariance_periodic: tuple[tuple[RiskMetric, ...], ...]
    regularized_covariance_periodic: tuple[tuple[RiskMetric, ...], ...]
    correlation: tuple[tuple[RiskMetric, ...], ...]
    numerical_zero_pivots: tuple[int, ...]

    def __post_init__(self) -> None:
        source_tuple(self.keys, str, "keys", 32)
        if len(set(self.keys)) != len(self.keys) or tuple(sorted(self.keys)) != self.keys:
            fail_validation("Matrix identities must be canonical and unique.", field="keys")
        for key in self.keys:
            source_id(key, "instrument_id")
        source_integer(self.requested_intervals, "requested_intervals", 0, 3660)
        source_integer(self.used_intervals, "used_intervals", 0, self.requested_intervals)
        if (
            type(self.omitted_intervals) is not int
            or self.used_intervals + self.omitted_intervals != self.requested_intervals
        ):
            fail_validation("Matrix coverage does not reconcile.", field="intervals")
        for matrix in (
            self.covariance_periodic,
            self.regularized_covariance_periodic,
            self.correlation,
        ):
            source_tuple(matrix, tuple, "matrix", 32)
            if len(matrix) != len(self.keys):
                fail_validation("Matrix dimensions differ.", field="matrix")
            for i, row in enumerate(matrix):
                source_tuple(row, RiskMetric, "row", len(self.keys))
                if len(row) != len(self.keys):
                    fail_validation("Matrix dimensions differ.", field="matrix")
                if any(matrix[i][j] != matrix[j][i] for j in range(i)):
                    fail_validation("Published matrix is asymmetric.", field="matrix")
        source_tuple(self.numerical_zero_pivots, int, "pivots", len(self.keys))
        if tuple(sorted(set(self.numerical_zero_pivots))) != self.numerical_zero_pivots:
            fail_validation("Matrix pivots must be unique and ordered.", field="pivots")
        for pivot in self.numerical_zero_pivots:
            source_integer(pivot, "pivot", 0, len(self.keys) - 1)


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskTail:
    method: Literal["historical", "parametric_lognormal"]
    confidence: Decimal
    horizon: int
    observations: int
    tail_mass: Decimal | None
    value_at_risk: RiskMetric
    expected_shortfall: RiskMetric
    loss_sign: Literal["positive_is_loss"] = "positive_is_loss"
    quantile: Literal["nearest_rank_fractional_tail", "gaussian_log_wealth"] = (
        "nearest_rank_fractional_tail"
    )
    horizon_policy: Literal["overlapping_compounded", "iid_log_returns"] = "overlapping_compounded"

    def __post_init__(self) -> None:
        confidence = exact_decimal(self.confidence)
        if confidence not in (Decimal(".9"), Decimal(".95"), Decimal(".99")):
            fail_validation("Unsupported risk confidence.", field="confidence")
        object.__setattr__(self, "confidence", confidence)
        source_integer(self.horizon, "horizon", 1, 20)
        source_integer(self.observations, "observations", 0, 3660)
        if (
            self.method not in ("historical", "parametric_lognormal")
            or self.loss_sign != "positive_is_loss"
        ):
            fail_validation("Unsupported tail method.", field="method")
        if self.method == "historical":
            if (
                self.quantile != "nearest_rank_fractional_tail"
                or self.horizon_policy != "overlapping_compounded"
                or self.tail_mass is None
            ):
                fail_validation("Historical tail conventions differ.", field="tail")
        elif (
            self.quantile != "gaussian_log_wealth"
            or self.horizon_policy != "iid_log_returns"
            or self.tail_mass is not None
        ):
            fail_validation("Parametric tail conventions differ.", field="tail")
        if self.tail_mass is not None:
            amount = exact_decimal(self.tail_mass)
            if not Decimal(0) <= amount <= self.observations:
                fail_validation("Invalid tail mass.", field="tail_mass")
            object.__setattr__(self, "tail_mass", amount)
        _metrics(self.value_at_risk, self.expected_shortfall)
        if self.value_at_risk.reason != self.expected_shortfall.reason:
            fail_validation("Tail availability differs.", field="tail")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskComponent:
    instrument_id: str
    weight: RiskMetric
    marginal_annualized: RiskMetric
    component_annualized: RiskMetric

    def __post_init__(self) -> None:
        source_id(self.instrument_id, "instrument_id")
        _metrics(self.weight, self.marginal_annualized, self.component_annualized)
        if self.weight.value is not None and not Decimal(0) <= self.weight.value <= 1:
            fail_validation("Risk weight is outside the portfolio.", field="weight")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskModel:
    coverage: RiskMetric
    complete_universe: bool
    volatility_annualized: RiskMetric
    diversification_ratio: RiskMetric
    components: tuple[RiskComponent, ...]
    component_sum: RiskMetric
    component_display_residual: RiskMetric
    weight_display_residual: RiskMetric

    def __post_init__(self) -> None:
        _metrics(
            self.coverage,
            self.volatility_annualized,
            self.diversification_ratio,
            self.component_sum,
            self.component_display_residual,
            self.weight_display_residual,
        )
        if type(self.complete_universe) is not bool:
            fail_validation("Risk coverage flag is invalid.", field="complete_universe")
        source_tuple(self.components, RiskComponent, "components", 32)
        keys = tuple(item.instrument_id for item in self.components)
        if tuple(sorted(set(keys))) != keys:
            fail_validation("Risk components are not unique and ordered.", field="components")
        if self.coverage.value is not None and not Decimal(0) <= self.coverage.value <= 1:
            fail_validation("Risk coverage is outside the portfolio.", field="coverage")
        if not self.complete_universe and self.volatility_annualized.value is not None:
            fail_validation("Incomplete universe cannot publish full modeled risk.", field="model")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskConcentration:
    hhi: RiskMetric
    effective_holdings: RiskMetric
    company_known_weight: RiskMetric
    cash_weight: RiskMetric
    unresolved_weight: RiskMetric
    lower_bound: bool
    quality: QualityState
    basis: Literal["economic_companies_absolute_portfolio"] = (
        "economic_companies_absolute_portfolio"
    )

    def __post_init__(self) -> None:
        _metrics(
            self.hhi,
            self.effective_holdings,
            self.company_known_weight,
            self.cash_weight,
            self.unresolved_weight,
        )
        if (
            type(self.lower_bound) is not bool
            or not isinstance(self.quality, QualityState)
            or self.basis != "economic_companies_absolute_portfolio"
        ):
            fail_validation("Concentration basis is invalid.", field="concentration")
        if self.lower_bound and self.effective_holdings.value is not None:
            fail_validation(
                "Partial concentration cannot publish effective holdings.", field="concentration"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskCalculation:
    history: RiskHistory
    definition: RiskDefinitionContent
    observed: RiskSeriesStatistics
    matrix: RiskMatrix
    historical_tail: RiskTail
    parametric_tail: RiskTail
    modeled: RiskModel
    concentration: RiskConcentration
    xray_result_digest: str | None
    portfolio_snapshot_id: str | None
    modeled_valuation_at: datetime | None
    annualization_factor: int
    covariance_degrees_of_freedom: Literal[1] = 1
    family: Literal["risk"] = "risk"
    method_version: Literal["1.0.0"] = "1.0.0"
    schema_version: Literal["1.0.0"] = "1.0.0"
    numerical_profile: Literal["premium_decimal96_q18_v1"] = "premium_decimal96_q18_v1"

    def __post_init__(self) -> None:
        for field, kind in (
            ("history", RiskHistory),
            ("definition", RiskDefinitionContent),
            ("observed", RiskSeriesStatistics),
            ("matrix", RiskMatrix),
            ("historical_tail", RiskTail),
            ("parametric_tail", RiskTail),
            ("modeled", RiskModel),
            ("concentration", RiskConcentration),
        ):
            if not isinstance(getattr(self, field), kind):
                fail_validation("A typed risk calculation is required.", field=field)
        portfolio = self.history.portfolio
        if (portfolio.calendar_id, portfolio.calendar_version, portfolio.frequency) != (
            self.definition.calendar_id,
            self.definition.calendar_version,
            self.definition.frequency,
        ) or self.observed.requested_observations != len(portfolio.intervals):
            fail_validation("Risk definition or coverage differs from history.", field="history")
        if (
            self.family != "risk"
            or self.method_version != "1.0.0"
            or self.schema_version != "1.0.0"
            or self.numerical_profile != "premium_decimal96_q18_v1"
        ):
            fail_validation("Unsupported risk calculation version.", field="method")
        if (
            type(self.covariance_degrees_of_freedom) is not int
            or self.covariance_degrees_of_freedom != 1
            or type(self.annualization_factor) is not int
            or self.annualization_factor != (252 if self.definition.frequency == "daily" else 12)
        ):
            fail_validation("Risk estimation conventions differ.", field="annualization")
        if (self.xray_result_digest is None) != (self.portfolio_snapshot_id is None):
            fail_validation("X-ray source identity is incomplete.", field="xray")
        if (self.modeled_valuation_at is None) != (self.portfolio_snapshot_id is None):
            fail_validation(
                "Modeled valuation identity is incomplete.", field="modeled_valuation_at"
            )
        if self.modeled_valuation_at is not None:
            require_utc(self.modeled_valuation_at)
            if self.modeled_valuation_at < self.history.canonical_performance_context.window.end_at:
                fail_validation("Modeled valuation precedes history.", field="modeled_valuation_at")
        if self.xray_result_digest is not None:
            historical_digest(self.xray_result_digest, "xray_result_digest")
        if self.portfolio_snapshot_id is not None:
            source_id(self.portfolio_snapshot_id, "portfolio_snapshot_id")
        if (
            tuple(sorted(row.key for row in self.history.assets)) != self.matrix.keys
            or tuple(row.instrument_id for row in self.modeled.components) != self.matrix.keys
        ):
            fail_validation("Risk result universes differ.", field="matrix")
        if (
            self.historical_tail.method != "historical"
            or self.parametric_tail.method != "parametric_lognormal"
            or any(
                tail.confidence != self.definition.confidence
                or tail.horizon != self.definition.horizon
                for tail in (self.historical_tail, self.parametric_tail)
            )
        ):
            fail_validation("Risk tail definition differs.", field="tails")
