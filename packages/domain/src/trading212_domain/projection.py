"""Closed canonical inputs for the finite monthly projection model.

Calendar mapping, ownership and source authorization belong to the capture boundary.
The kernel receives resolved monthly indices and an explicit canonical money basis.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Literal

from .errors import fail_validation
from .historical import historical_digest
from .sources import source_id, source_integer, source_key, source_tuple
from .values import CurrencyCode, Money, exact_decimal

PROJECTION_METHOD = "projection_v1"
PROJECTION_VERSION = "1.0.0"
PROJECTION_NUMERIC_PROFILE = "premium_decimal96_q18_v1"
PROJECTION_SAMPLER = "sha256_counter_polar_v1"
PROJECTION_MAX_WORK = 1_000_000
PROJECTION_MAX_BYTES = 32 * 1024 * 1024
PROJECTION_PERCENTILES = tuple(Decimal(v) for v in (".05", ".25", ".50", ".75", ".95"))
type ProjectionVariant = Literal["baseline", "contribution_delta", "mean_log_delta"]


def financial_decimal(value: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal):
        fail_validation("A finite canonical Decimal is required.", field=field)
    parsed = exact_decimal(value, field=field)
    return parsed.copy_abs() if parsed.is_zero() else parsed


def exact_sum(values: tuple[Decimal, ...]) -> Decimal:
    # Validation adds at most bounded Q18 inputs; 96 digits leave this sum exact.
    with localcontext(Context(prec=96, rounding=ROUND_HALF_EVEN, Emin=-999, Emax=999)):
        return sum(values, Decimal(0))


def _bounded(value: Decimal, field: str, low: str, high: str) -> Decimal:
    value = financial_decimal(value, field)
    if not Decimal(low) <= value <= Decimal(high):
        fail_validation("Projection assumption exceeds its supported bounds.", field=field)
    return value


def _money(value: Money, field: str, *, negative: bool = False) -> None:
    if not isinstance(value, Money) or (not negative and value.amount < 0):
        fail_validation("Explicit nonnegative money is required.", field=field)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionSourcePin:
    subject_id: str
    content_digest: str

    def __post_init__(self) -> None:
        source_id(self.subject_id)
        historical_digest(self.content_digest, "content_digest")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionAsset:
    key: str
    annual_mean_log_return: Decimal
    annual_volatility: Decimal
    weight: Decimal

    def __post_init__(self) -> None:
        source_key(self.key, "asset.key")
        for field, low, high in (
            ("annual_mean_log_return", "-.5", ".5"),
            ("annual_volatility", "0", "1"),
            ("weight", "0", "1"),
        ):
            object.__setattr__(self, field, _bounded(getattr(self, field), field, low, high))


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionAllocation:
    key: str
    weight: Decimal

    def __post_init__(self) -> None:
        source_key(self.key, "allocation.key")
        object.__setattr__(self, "weight", _bounded(self.weight, "allocation.weight", "0", "1"))


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionAssumptions:
    assets: tuple[ProjectionAsset, ...]
    correlation: tuple[tuple[Decimal, ...], ...]
    reporting_currency: CurrencyCode
    annual_inflation: Decimal = Decimal(0)
    annual_fee: Decimal = Decimal(0)
    annual_tax_drag: Decimal | None = None
    rebalance: Literal["monthly", "annual", "none"] = "none"
    calibration_pins: tuple[ProjectionSourcePin, ...] = ()

    def __post_init__(self) -> None:
        source_tuple(self.assets, ProjectionAsset, "assets", 12)
        if not self.assets or len({a.key for a in self.assets}) != len(self.assets):
            fail_validation("Projection assets must be unique and nonempty.", field="assets")
        if not isinstance(self.reporting_currency, CurrencyCode):
            fail_validation("Projection currency is required.", field="reporting_currency")
        if self.rebalance not in ("monthly", "annual", "none"):
            fail_validation("Unknown projection rebalance policy.", field="rebalance")
        if exact_sum(tuple(a.weight for a in self.assets)) != 1:
            fail_validation("Projection weights must sum exactly to one.", field="weights")
        source_tuple(self.correlation, tuple, "correlation", len(self.assets))
        if len(self.correlation) != len(self.assets):
            fail_validation("Correlation dimensions differ.", field="correlation")
        for row in self.correlation:
            source_tuple(row, Decimal, "correlation.row", len(self.assets))
            if len(row) != len(self.assets):
                fail_validation("Correlation dimensions differ.", field="correlation")
        for i, row in enumerate(self.correlation):
            for j, cell in enumerate(row):
                _bounded(cell, "correlation.cell", "-1", "1")
                if (i == j and cell != 1) or cell != self.correlation[j][i]:
                    fail_validation(
                        "Correlation must be symmetric with unit diagonal.", field="correlation"
                    )
        # The incoming matrix follows incoming asset order. Canonicalize both together.
        order = sorted(range(len(self.assets)), key=lambda i: self.assets[i].key)
        object.__setattr__(self, "assets", tuple(self.assets[i] for i in order))
        object.__setattr__(
            self, "correlation", tuple(tuple(self.correlation[i][j] for j in order) for i in order)
        )
        for field, low, high in (("annual_inflation", "-.1", ".5"), ("annual_fee", "0", ".2")):
            object.__setattr__(self, field, _bounded(getattr(self, field), field, low, high))
        if self.annual_tax_drag is not None:
            object.__setattr__(
                self,
                "annual_tax_drag",
                _bounded(self.annual_tax_drag, "annual_tax_drag", "0", ".2"),
            )
        source_tuple(self.calibration_pins, ProjectionSourcePin, "calibration_pins", 256)
        if len({p.subject_id for p in self.calibration_pins}) != len(self.calibration_pins):
            fail_validation("Calibration pins must be unique.", field="calibration_pins")
        object.__setattr__(
            self,
            "calibration_pins",
            tuple(sorted(self.calibration_pins, key=lambda p: p.subject_id)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionInitialBasis:
    kind: Literal["observed_snapshot", "modeled_value"]
    value: Money
    snapshot_pin: ProjectionSourcePin | None = None

    def __post_init__(self) -> None:
        _money(self.value, "initial.value")
        if (
            self.kind not in ("observed_snapshot", "modeled_value")
            or (
                (self.kind == "observed_snapshot")
                != isinstance(self.snapshot_pin, ProjectionSourcePin)
            )
            or (self.kind == "modeled_value" and self.snapshot_pin is not None)
        ):
            fail_validation("Initial wealth requires exactly its declared basis.", field="initial")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionScheduleEntry:
    key: str
    month: int
    kind: Literal["lump_sum", "withdrawal"]
    value: Money

    def __post_init__(self) -> None:
        source_key(self.key, "schedule.key")
        source_integer(self.month, "schedule.month", 1, 600)
        if self.kind not in ("lump_sum", "withdrawal"):
            fail_validation("Unknown projection schedule kind.", field="schedule.kind")
        _money(self.value, "schedule.value")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionSchedule:
    base_monthly: Money
    annual_growth: Decimal = Decimal(0)
    paused_months: tuple[int, ...] = ()
    entries: tuple[ProjectionScheduleEntry, ...] = ()

    def __post_init__(self) -> None:
        _money(self.base_monthly, "schedule.base_monthly")
        object.__setattr__(
            self, "annual_growth", _bounded(self.annual_growth, "annual_growth", "-1", "1")
        )
        source_tuple(self.paused_months, int, "paused_months", 128)
        for month in self.paused_months:
            source_integer(month, "paused_month", 1, 600)
        if len(set(self.paused_months)) != len(self.paused_months):
            fail_validation("Repeated paused month.", field="paused_months")
        source_tuple(self.entries, ProjectionScheduleEntry, "schedule.entries", 128)
        if len(self.entries) + len(self.paused_months) > 128:
            fail_validation("Projection schedule exceeds 128 entries.", field="schedule")
        if len({e.key for e in self.entries}) != len(self.entries):
            fail_validation("Repeated schedule identity.", field="schedule.entries")
        if any(e.value.currency != self.base_monthly.currency for e in self.entries):
            fail_validation("Projection schedule currencies differ.", field="schedule")
        object.__setattr__(self, "paused_months", tuple(sorted(self.paused_months)))
        object.__setattr__(
            self, "entries", tuple(sorted(self.entries, key=lambda e: (e.month, e.kind, e.key)))
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionSensitivity:
    contribution_delta: Money
    annual_mean_log_delta: Decimal

    def __post_init__(self) -> None:
        _money(self.contribution_delta, "contribution_delta", negative=True)
        object.__setattr__(
            self,
            "annual_mean_log_delta",
            financial_decimal(self.annual_mean_log_delta, "annual_mean_log_delta"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionGoal:
    version_id: str
    assumption_version_id: str
    target: Money
    basis: Literal["nominal", "real"]
    months: int
    probability_objective: Decimal
    schedule: ProjectionSchedule

    def __post_init__(self) -> None:
        source_id(self.version_id, "goal.version_id")
        source_id(self.assumption_version_id, "goal.assumption_version_id")
        _money(self.target, "goal.target")
        source_integer(self.months, "goal.months", 1, 600)
        if self.basis not in ("nominal", "real"):
            fail_validation("Goal money basis is invalid.", field="goal.basis")
        object.__setattr__(
            self,
            "probability_objective",
            _bounded(self.probability_objective, "probability_objective", "0", "1"),
        )
        if (
            not isinstance(self.schedule, ProjectionSchedule)
            or self.schedule.base_monthly.currency != self.target.currency
        ):
            fail_validation(
                "Goal schedule is required in its target currency.", field="goal.schedule"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionInput:
    assumption_version_id: str
    assumptions: ProjectionAssumptions
    initial: ProjectionInitialBasis
    schedule: ProjectionSchedule
    seed: int
    months: int
    paths: int
    retained_months: tuple[int, ...]
    allocation: tuple[ProjectionAllocation, ...]
    goal: ProjectionGoal | None = None
    sensitivity: ProjectionSensitivity | None = None

    def __post_init__(self) -> None:
        source_id(self.assumption_version_id, "assumption_version_id")
        for field, kind in (
            ("assumptions", ProjectionAssumptions),
            ("initial", ProjectionInitialBasis),
            ("schedule", ProjectionSchedule),
        ):
            if not isinstance(getattr(self, field), kind):
                fail_validation("Typed projection input is required.", field=field)
        source_integer(self.seed, "seed", 0, 2**32 - 1)
        source_integer(self.months, "months", 1, 600)
        source_integer(self.paths, "paths", 1, 4096)
        source_tuple(self.retained_months, int, "retained_months", 121)
        for month in self.retained_months:
            source_integer(month, "retained_month", 0, self.months)
        if (
            len(set(self.retained_months)) != len(self.retained_months)
            or 0 not in self.retained_months
            or self.months not in self.retained_months
        ):
            fail_validation(
                "Retained months must be unique and contain both endpoints.",
                field="retained_months",
            )
        object.__setattr__(self, "retained_months", tuple(sorted(self.retained_months)))
        currency = self.assumptions.reporting_currency
        if (
            self.initial.value.currency != currency
            or self.schedule.base_monthly.currency != currency
        ):
            fail_validation("Projection money currencies differ.", field="currency")
        if any(m > self.months for m in self.schedule.paused_months) or any(
            e.month > self.months for e in self.schedule.entries
        ):
            fail_validation("Schedule extends beyond the horizon.", field="schedule")
        source_tuple(self.allocation, ProjectionAllocation, "allocation", 12)
        ordered = tuple(sorted(self.allocation, key=lambda item: item.key))
        if tuple((item.key, item.weight) for item in ordered) != tuple(
            (a.key, a.weight) for a in self.assumptions.assets
        ):
            fail_validation(
                "Request allocation must equal immutable assumption weights.", field="allocation"
            )
        object.__setattr__(self, "allocation", ordered)
        if self.goal is not None and (
            not isinstance(self.goal, ProjectionGoal)
            or self.goal.target.currency != currency
            or self.goal.months != self.months
            or self.goal.assumption_version_id != self.assumption_version_id
            or self.goal.schedule != self.schedule
        ):
            fail_validation("Goal and projection basis differ.", field="goal")
        if self.sensitivity is not None:
            if (
                not isinstance(self.sensitivity, ProjectionSensitivity)
                or self.sensitivity.contribution_delta.currency != currency
            ):
                fail_validation("Sensitivity money currency differs.", field="sensitivity")
            base = exact_sum(
                (self.schedule.base_monthly.amount, self.sensitivity.contribution_delta.amount)
            )
            if base < 0:
                fail_validation("Sensitivity makes contributions negative.", field="sensitivity")
            financial_decimal(base, "sensitivity.base")
            for asset in self.assumptions.assets:
                _bounded(
                    exact_sum(
                        (asset.annual_mean_log_return, self.sensitivity.annual_mean_log_delta)
                    ),
                    "sensitivity.mean",
                    "-.5",
                    ".5",
                )
        if self.work_units > PROJECTION_MAX_WORK:
            fail_validation("Projection exceeds the shared work bound.", field="projection.work")

    @property
    def variants(self) -> tuple[ProjectionVariant, ...]:
        return (
            ("baseline", "contribution_delta", "mean_log_delta")
            if self.sensitivity is not None
            else ("baseline",)
        )

    @property
    def work_units(self) -> int:
        return len(self.assumptions.assets) * self.months * self.paths * len(self.variants)
