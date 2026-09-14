"""Bounded risk definitions and canonical series; no transport or calculation policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from .enums import QualityState
from .errors import fail_validation
from .sources import source_integer, source_key, source_tuple
from .values import CurrencyCode, exact_decimal, require_bounded_text, require_utc

RISK_METHOD = "risk_v1"
RISK_VERSION = "1.0.0"
RISK_NUMERIC_PROFILE = "premium_decimal96_q18_v1"


class RiskReason(StrEnum):
    INSUFFICIENT_HISTORY = "insufficient_history"
    INSUFFICIENT_TAIL = "insufficient_tail"
    MISSING_INTERVAL = "missing_interval"
    NON_OBSERVED_INTERVAL = "non_observed_interval"
    LOG_UNAVAILABLE = "nonpositive_gross_return"
    BENCHMARK_UNAVAILABLE = "benchmark_unavailable"
    ZERO_DENOMINATOR = "zero_denominator"
    INCOMPLETE_UNIVERSE = "incomplete_universe"
    UNSUPPORTED_PARAMETRIC = "unsupported_parametric"
    INCOMPATIBLE_BASIS = "incompatible_basis"


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskDefinitionContent:
    name: str
    description: str
    calendar_id: str
    calendar_version: str
    frequency: Literal["daily", "monthly"] = "daily"
    return_kind: Literal["simple", "log"] = "simple"
    annual_risk_free: Decimal = Decimal("0")
    annual_minimum_acceptable_return: Decimal = Decimal("0")
    rolling_window: int = 20
    confidence: Decimal = Decimal("0.95")
    horizon: int = 1
    regularization: Literal["none", "diagonal_shrinkage"] = "none"
    shrinkage: Decimal = Decimal("0")
    method_version: Literal["1.0.0"] = "1.0.0"

    def __post_init__(self) -> None:
        require_bounded_text(self.name, field="name", maximum=120)
        require_bounded_text(self.description, field="description", maximum=1024, allow_empty=True)
        source_key(self.calendar_id, "calendar_id")
        source_key(self.calendar_version, "calendar_version")
        if self.frequency not in ("daily", "monthly") or self.return_kind not in ("simple", "log"):
            fail_validation("Unsupported risk return/frequency.", field="risk")
        if (
            self.regularization not in ("none", "diagonal_shrinkage")
            or self.method_version != RISK_VERSION
        ):
            fail_validation("Unsupported risk method.", field="method_version")
        for field in ("annual_risk_free", "annual_minimum_acceptable_return"):
            amount = exact_decimal(getattr(self, field), field=field)
            if not Decimal("-1") < amount <= Decimal("1"):
                fail_validation("Annual risk assumption is outside supported bounds.", field=field)
            object.__setattr__(self, field, amount)
        shrinkage = exact_decimal(self.shrinkage, field="shrinkage")
        if not Decimal(0) <= shrinkage <= Decimal(1) or (
            self.regularization == "none" and shrinkage != 0
        ):
            fail_validation("Shrinkage must be explicit and within bounds.", field="shrinkage")
        object.__setattr__(self, "shrinkage", shrinkage)
        confidence = exact_decimal(self.confidence, field="confidence")
        if confidence not in (Decimal(".90"), Decimal(".95"), Decimal(".99")):
            fail_validation("Unsupported tail confidence.", field="confidence")
        object.__setattr__(self, "confidence", confidence)
        source_integer(
            self.rolling_window, "rolling_window", 20, 252 if self.frequency == "daily" else 120
        )
        source_integer(self.horizon, "horizon", 1, 20 if self.frequency == "daily" else 12)


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskInterval:
    start_at: datetime
    end_at: datetime
    simple_return: Decimal | None
    quality: QualityState
    reason: RiskReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_at", require_utc(self.start_at))
        object.__setattr__(self, "end_at", require_utc(self.end_at))
        if self.start_at >= self.end_at or not isinstance(self.quality, QualityState):
            fail_validation("Invalid risk interval boundary/quality.", field="interval")
        if self.reason is not None and not isinstance(self.reason, RiskReason):
            fail_validation("Invalid risk interval reason.", field="reason")
        if self.simple_return is None:
            if self.reason is None or self.quality is QualityState.FRESH:
                fail_validation(
                    "Unavailable interval requires reason and degraded quality.", field="interval"
                )
        else:
            amount = exact_decimal(self.simple_return, field="simple_return")
            if amount < -1 or self.reason is not None:
                fail_validation("Invalid available risk interval.", field="simple_return")
            object.__setattr__(self, "simple_return", amount)


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskSeries:
    key: str
    reporting_currency: CurrencyCode
    calendar_id: str
    calendar_version: str
    frequency: Literal["daily", "monthly"]
    source_cutoff_at: datetime
    basis: Literal["total_return"]
    intervals: tuple[RiskInterval, ...]

    def __post_init__(self) -> None:
        for field in ("key", "calendar_id", "calendar_version"):
            source_key(getattr(self, field), field)
        if (
            not isinstance(self.reporting_currency, CurrencyCode)
            or self.frequency not in ("daily", "monthly")
            or self.basis != "total_return"
        ):
            fail_validation("Unsupported risk series basis.", field="series")
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
        source_tuple(self.intervals, RiskInterval, "intervals", 3660)
        if any(item.end_at > self.source_cutoff_at for item in self.intervals):
            fail_validation("Risk interval exceeds source cutoff.", field="source_cutoff_at")
        if any(
            a.end_at != b.start_at for a, b in zip(self.intervals, self.intervals[1:], strict=False)
        ):
            fail_validation(
                "Risk intervals must preserve consecutive calendar boundaries.", field="intervals"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskMetric:
    value: Decimal | None
    reason: RiskReason | None = None

    def __post_init__(self) -> None:
        if (self.value is None) != (self.reason is not None):
            fail_validation("Risk availability and reason disagree.", field="metric")
        if self.reason is not None and not isinstance(self.reason, RiskReason):
            fail_validation("Invalid risk metric reason.", field="reason")
        if self.value is not None:
            object.__setattr__(self, "value", exact_decimal(self.value))


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskRollingPoint:
    end_at: datetime
    volatility: RiskMetric
    observations: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "end_at", require_utc(self.end_at))
        source_integer(self.observations, "observations", 0, 252)
        if not isinstance(self.volatility, RiskMetric):
            fail_validation("A canonical rolling risk metric is required.", field="volatility")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskSeriesStatistics:
    requested_observations: int
    used_observations: int
    omitted_observations: int
    outlier_observations: int
    mean_periodic_return: RiskMetric
    volatility_periodic: RiskMetric
    volatility_annualized: RiskMetric
    downside_annualized: RiskMetric
    beta: RiskMetric
    alpha_annualized: RiskMetric
    benchmark_pairs: int
    rolling: tuple[RiskRollingPoint, ...]

    def __post_init__(self) -> None:
        source_integer(self.requested_observations, "requested_observations", 0, 3660)
        for field in (
            "used_observations",
            "omitted_observations",
            "outlier_observations",
            "benchmark_pairs",
        ):
            source_integer(getattr(self, field), field, 0, self.requested_observations)
        if self.used_observations + self.omitted_observations != self.requested_observations:
            fail_validation("Risk coverage counts disagree.", field="observations")
        for field in (
            "mean_periodic_return",
            "volatility_periodic",
            "volatility_annualized",
            "downside_annualized",
            "beta",
            "alpha_annualized",
        ):
            if not isinstance(getattr(self, field), RiskMetric):
                fail_validation("Canonical risk metrics are required.", field=field)
        source_tuple(self.rolling, RiskRollingPoint, "rolling", 3660)
