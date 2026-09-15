"""Closed projection inputs; only exact decimal strings cross the wire."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StringConstraints, model_validator

from .historical import HistoricalPageLimit, HistoricalSchema
from .sources import CalendarDate, SourceKey
from .targets import CurrencyString, Cursor, DecimalString, Digest, UUIDString, WeightString

ProjectionRevision = Annotated[StrictInt, Field(ge=1, le=512)]
ProjectionMonths = Annotated[StrictInt, Field(ge=1, le=600)]
ProjectionPathCount = Annotated[StrictInt, Field(ge=1, le=4096)]
ProjectionMonth = Annotated[StrictInt, Field(ge=0, le=600)]
ProjectionName = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=120, pattern=r"^[^\x00]*$")
]
ProjectionDescription = Annotated[
    str, StringConstraints(strict=True, max_length=1024, pattern=r"^[^\x00]*$")
]


class ProjectionSchema(HistoricalSchema):
    pass


def exact_sum(values: list[Decimal]) -> Decimal:
    with localcontext(
        Context(prec=96, rounding=ROUND_HALF_EVEN, Emin=-999, Emax=999, flags=[], traps=[])
    ):
        return sum(values, Decimal(0))


class ProjectionMoney(ProjectionSchema):
    amount: DecimalString
    currency: CurrencyString


class ProjectionNonnegativeMoney(ProjectionMoney):
    @model_validator(mode="after")
    def nonnegative(self) -> Self:
        if Decimal(self.amount) < 0:
            raise ValueError("Projection money must be nonnegative.")
        return self


class ProjectionVersionMetadata(ProjectionSchema):
    name: ProjectionName
    description: ProjectionDescription = ""

    @model_validator(mode="after")
    def named(self) -> Self:
        if not self.name.strip():
            raise ValueError("A definition name is required.")
        return self


class ProjectionSourcePin(ProjectionSchema):
    subject_id: UUIDString
    content_digest: Digest


class ProjectionAsset(ProjectionSchema):
    key: SourceKey
    annual_mean_log_return: DecimalString
    annual_volatility: DecimalString
    weight: WeightString

    @model_validator(mode="after")
    def ranges(self) -> Self:
        if (
            not Decimal("-.5") <= Decimal(self.annual_mean_log_return) <= Decimal(".5")
            or not 0 <= Decimal(self.annual_volatility) <= 1
        ):
            raise ValueError("Projection asset assumptions exceed supported bounds.")
        return self


class ProjectionAllocation(ProjectionSchema):
    key: SourceKey
    weight: WeightString


class AssumptionVersionContent(ProjectionSchema):
    assets: Annotated[list[ProjectionAsset], Field(min_length=1, max_length=12)]
    correlation: Annotated[
        list[Annotated[list[DecimalString], Field(min_length=1, max_length=12)]],
        Field(min_length=1, max_length=12),
    ]
    reporting_currency: CurrencyString
    annual_inflation: DecimalString = "0"
    annual_fee: DecimalString = "0"
    annual_tax_drag: DecimalString | None = None
    rebalance: Literal["monthly", "annual", "none"] = "none"
    calibration_pins: Annotated[list[ProjectionSourcePin], Field(max_length=256)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def canonical_assumptions(self) -> Self:
        size = len(self.assets)
        if (
            len({item.key for item in self.assets}) != size
            or exact_sum([Decimal(item.weight) for item in self.assets]) != 1
        ):
            raise ValueError("Unique asset weights must sum exactly to one.")
        if len(self.correlation) != size or any(len(row) != size for row in self.correlation):
            raise ValueError("Correlation dimensions differ from the asset order.")
        for i, row in enumerate(self.correlation):
            for j, cell in enumerate(row):
                value = Decimal(cell)
                if (
                    not -1 <= value <= 1
                    or value != Decimal(self.correlation[j][i])
                    or (i == j and value != 1)
                ):
                    raise ValueError("Correlation must be symmetric with unit diagonal.")
        if (
            not Decimal("-.1") <= Decimal(self.annual_inflation) <= Decimal(".5")
            or not 0 <= Decimal(self.annual_fee) <= Decimal(".2")
            or (
                self.annual_tax_drag is not None
                and not 0 <= Decimal(self.annual_tax_drag) <= Decimal(".2")
            )
        ):
            raise ValueError("Inflation, fees or modeled tax drag exceed supported bounds.")
        if len({pin.subject_id for pin in self.calibration_pins}) != len(self.calibration_pins):
            raise ValueError("Calibration subjects must be unique.")
        order = sorted(range(size), key=lambda index: self.assets[index].key)
        self.assets = [self.assets[index] for index in order]
        self.correlation = [[self.correlation[i][j] for j in order] for i in order]
        self.calibration_pins = sorted(self.calibration_pins, key=lambda pin: pin.subject_id)
        # PSD is checked by the application using the exact frozen Decimal96 gate.
        return self


class ProjectionDatedEntry(ProjectionSchema):
    key: SourceKey
    on: CalendarDate
    kind: Literal["lump_sum", "withdrawal"]
    value: ProjectionNonnegativeMoney


class ProjectionDatedSchedule(ProjectionSchema):
    base_monthly: ProjectionNonnegativeMoney
    annual_growth: DecimalString = "0"
    paused_dates: Annotated[list[CalendarDate], Field(max_length=128)] = Field(default_factory=list)
    entries: Annotated[list[ProjectionDatedEntry], Field(max_length=128)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def exact_schedule(self) -> Self:
        if not -1 <= Decimal(self.annual_growth) <= 1:
            raise ValueError("Contribution growth exceeds its supported bounds.")
        if (
            len(self.paused_dates) + len(self.entries) > 128
            or len(set(self.paused_dates)) != len(self.paused_dates)
            or len({entry.key for entry in self.entries}) != len(self.entries)
        ):
            raise ValueError("The schedule has duplicate identities or too many entries.")
        if any(entry.value.currency != self.base_monthly.currency for entry in self.entries):
            raise ValueError("Schedule currencies differ.")
        self.paused_dates = sorted(self.paused_dates)
        self.entries = sorted(self.entries, key=lambda entry: (entry.on, entry.kind, entry.key))
        return self


class ProjectionInitialSelection(ProjectionSchema):
    kind: Literal["observed_snapshot", "modeled_value"]
    snapshot_id: UUIDString | None = None
    modeled_value: ProjectionNonnegativeMoney | None = None
    modeled_anchor_date: CalendarDate | None = None

    @model_validator(mode="after")
    def one_basis(self) -> Self:
        if self.kind == "observed_snapshot":
            if (
                self.snapshot_id is None
                or self.modeled_value is not None
                or self.modeled_anchor_date is not None
            ):
                raise ValueError("An observed initial basis accepts only a saved snapshot ID.")
        elif (
            self.snapshot_id is not None
            or self.modeled_value is None
            or self.modeled_anchor_date is None
        ):
            raise ValueError("A modeled initial basis requires explicit money and anchor date.")
        return self


class ProjectionSensitivity(ProjectionSchema):
    contribution_delta: ProjectionMoney
    annual_mean_log_delta: DecimalString


class GoalVersionContent(ProjectionSchema):
    assumption_version_id: UUIDString
    target: ProjectionNonnegativeMoney
    target_date: CalendarDate
    months: ProjectionMonths
    basis: Literal["nominal", "real"]
    probability_objective: WeightString
    schedule: ProjectionDatedSchedule

    @model_validator(mode="after")
    def matching_currency(self) -> Self:
        if self.target.currency != self.schedule.base_monthly.currency:
            raise ValueError("Goal and schedule currencies differ.")
        return self


class ProjectionRunFields(ProjectionSchema):
    assumption_version_id: UUIDString
    goal_version_id: UUIDString | None = None
    schedule: ProjectionDatedSchedule
    seed: Annotated[StrictInt, Field(ge=0, le=2**32 - 1)]
    months: ProjectionMonths
    paths: ProjectionPathCount
    retained_months: Annotated[list[ProjectionMonth], Field(min_length=2, max_length=121)]
    allocation: Annotated[list[ProjectionAllocation], Field(min_length=1, max_length=12)]
    sensitivity: ProjectionSensitivity | None = None

    @model_validator(mode="after")
    def selection_bounds(self) -> Self:
        months = self.retained_months
        if (
            len(set(months)) != len(months)
            or 0 not in months
            or self.months not in months
            or any(month > self.months for month in months)
        ):
            raise ValueError("Retained months must be unique, bounded and include both endpoints.")
        if (
            len({item.key for item in self.allocation}) != len(self.allocation)
            or exact_sum([Decimal(item.weight) for item in self.allocation]) != 1
        ):
            raise ValueError("Allocation must be unique and sum exactly to one.")
        variants = 3 if self.sensitivity is not None else 1
        if len(self.allocation) * self.months * self.paths * variants > 1_000_000:
            raise ValueError("Projection exceeds the shared work bound.")
        if self.sensitivity is not None and (
            self.sensitivity.contribution_delta.currency != self.schedule.base_monthly.currency
            or exact_sum(
                [
                    Decimal(self.schedule.base_monthly.amount),
                    Decimal(self.sensitivity.contribution_delta.amount),
                ]
            )
            < 0
        ):
            raise ValueError("Contribution sensitivity has an invalid money basis.")
        self.retained_months = sorted(months)
        self.allocation = sorted(self.allocation, key=lambda item: item.key)
        return self

    def validate_initial_currency(self, initial: ProjectionInitialSelection) -> None:
        if (
            initial.modeled_value is not None
            and initial.modeled_value.currency != self.schedule.base_monthly.currency
        ):
            raise ValueError("Initial value and schedule currencies differ.")


class CreateProjectionRunRequest(ProjectionRunFields):
    initial_basis: ProjectionInitialSelection

    @model_validator(mode="after")
    def initial_currency(self) -> Self:
        self.validate_initial_currency(self.initial_basis)
        return self


class ProjectionRunSelection(ProjectionRunFields):
    account_id: UUIDString
    initial: ProjectionInitialSelection

    @model_validator(mode="after")
    def initial_currency(self) -> Self:
        self.validate_initial_currency(self.initial)
        return self


class CreateAssumptionSetRequest(ProjectionSchema):
    metadata: ProjectionVersionMetadata
    content: AssumptionVersionContent


class CreateAssumptionVersionRequest(CreateAssumptionSetRequest):
    pass


class CreateGoalRequest(ProjectionSchema):
    metadata: ProjectionVersionMetadata
    content: GoalVersionContent


class CreateGoalVersionRequest(CreateGoalRequest):
    pass


class CancelProjectionRunRequest(ProjectionSchema):
    pass


class ProjectionPageQuery(ProjectionSchema):
    limit: HistoricalPageLimit = 25
    cursor: Cursor | None = None


class ProjectionPointPageQuery(ProjectionSchema):
    point_limit: HistoricalPageLimit = 25
    point_cursor: Cursor | None = None
