"""Pure projection preflight over typed version/snapshot content supplied by a service.

The caller must authorize identities and current source entitlements before loading
these records. Matching account fields here does not perform authorization, source
acquisition, persistence, reservation or worker publication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from uuid import UUID

from trading212_analytics.projection import validate_projection_capacity
from trading212_domain.errors import fail_validation
from trading212_domain.historical import historical_digest
from trading212_domain.projection import (
    PROJECTION_MAX_BYTES,
    ProjectionAllocation,
    ProjectionAssumptions,
    ProjectionGoal,
    ProjectionInitialBasis,
    ProjectionInput,
    ProjectionSchedule,
    ProjectionScheduleEntry,
    ProjectionSensitivity,
    ProjectionSourcePin,
    financial_decimal,
)
from trading212_domain.projection_serialization import projection_input_digest
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import source_integer, source_key, source_tuple
from trading212_domain.values import Money, require_utc

from .projection_calendar import ProjectionCalendar, require_projection_date


def _ids(*values: UUID) -> None:
    if any(type(value) is not UUID for value in values):
        fail_validation("Canonical UUID identities are required.", field="id")


def _nonnegative_money(value: Money, field_name: str) -> None:
    if not isinstance(value, Money) or value.amount < 0:
        fail_validation("Explicit nonnegative money is required.", field=field_name)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionDatedEntry:
    key: str
    on: date
    kind: Literal["lump_sum", "withdrawal"]
    value: Money

    def __post_init__(self) -> None:
        source_key(self.key, "schedule.key")
        require_projection_date(self.on, "schedule.date")
        ProjectionScheduleEntry(key=self.key, month=1, kind=self.kind, value=self.value)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionDatedSchedule:
    base_monthly: Money
    annual_growth: Decimal = Decimal(0)
    paused_dates: tuple[date, ...] = ()
    entries: tuple[ProjectionDatedEntry, ...] = ()

    def __post_init__(self) -> None:
        source_tuple(self.paused_dates, date, "schedule.paused_dates", 128)
        source_tuple(self.entries, ProjectionDatedEntry, "schedule.entries", 128)
        for paused in self.paused_dates:
            require_projection_date(paused, "schedule.paused_dates")
        if len(set(self.paused_dates)) != len(self.paused_dates):
            fail_validation("Repeated paused date.", field="schedule.paused_dates")
        # Reuse the kernel contract's money, growth, identity and aggregate bounds.
        validated = ProjectionSchedule(
            base_monthly=self.base_monthly,
            annual_growth=self.annual_growth,
            paused_months=tuple(range(1, len(self.paused_dates) + 1)),
            entries=tuple(
                ProjectionScheduleEntry(key=e.key, month=1, kind=e.kind, value=e.value)
                for e in self.entries
            ),
        )
        object.__setattr__(self, "annual_growth", validated.annual_growth)
        object.__setattr__(self, "paused_dates", tuple(sorted(self.paused_dates)))
        object.__setattr__(
            self, "entries", tuple(sorted(self.entries, key=lambda e: (e.on, e.kind, e.key)))
        )

    def resolve(self, calendar: ProjectionCalendar) -> ProjectionSchedule:
        if type(calendar) is not ProjectionCalendar:
            fail_validation("A typed projection calendar is required.", field="calendar")
        return ProjectionSchedule(
            base_monthly=self.base_monthly,
            annual_growth=self.annual_growth,
            paused_months=tuple(
                calendar.flow_month(on, field_name="schedule.paused_dates")
                for on in self.paused_dates
            ),
            entries=tuple(
                ProjectionScheduleEntry(
                    key=e.key,
                    month=calendar.flow_month(e.on),
                    kind=e.kind,
                    value=e.value,
                )
                for e in self.entries
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionGoalVersionContent:
    assumption_version_id: UUID
    target: Money
    target_date: date
    months: int
    basis: Literal["nominal", "real"]
    probability_objective: Decimal
    schedule: ProjectionDatedSchedule

    def __post_init__(self) -> None:
        _ids(self.assumption_version_id)
        _nonnegative_money(self.target, "goal.target")
        require_projection_date(self.target_date, "goal.target_date")
        source_integer(self.months, "goal.months", 1, 600)
        objective = financial_decimal(self.probability_objective, "goal.probability_objective")
        if not 0 <= objective <= 1 or self.basis not in ("nominal", "real"):
            fail_validation("Goal basis or objective is invalid.", field="goal")
        object.__setattr__(self, "probability_objective", objective)
        if (
            type(self.schedule) is not ProjectionDatedSchedule
            or self.schedule.base_monthly.currency != self.target.currency
        ):
            fail_validation("Goal schedule currency differs.", field="goal.schedule")


def projection_definition_digest(
    content: ProjectionAssumptions | ProjectionGoalVersionContent,
) -> str:
    if type(content) not in (ProjectionAssumptions, ProjectionGoalVersionContent):
        fail_validation("A closed projection definition is required.", field="content")
    return sha256(canonical_json(content).encode()).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionAssumptionVersion:
    account_id: UUID
    version_id: UUID
    content: ProjectionAssumptions
    content_digest: str

    def __post_init__(self) -> None:
        _ids(self.account_id, self.version_id)
        if type(self.content) is not ProjectionAssumptions:
            fail_validation("Immutable assumptions are required.", field="assumptions")
        historical_digest(self.content_digest, "assumption.content_digest")
        if projection_definition_digest(self.content) != self.content_digest:
            fail_validation("Immutable assumption content digest differs.", field="assumptions")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionGoalVersion:
    account_id: UUID
    version_id: UUID
    content: ProjectionGoalVersionContent
    content_digest: str

    def __post_init__(self) -> None:
        _ids(self.account_id, self.version_id)
        if type(self.content) is not ProjectionGoalVersionContent:
            fail_validation("Immutable goal content is required.", field="goal")
        historical_digest(self.content_digest, "goal.content_digest")
        if projection_definition_digest(self.content) != self.content_digest:
            fail_validation("Immutable goal content digest differs.", field="goal")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionSnapshotValue:
    """Canonical server-derived reporting value, not a caller valuation override."""

    account_id: UUID
    snapshot_id: UUID
    valuation_at: datetime
    content_digest: str
    value: Money

    def __post_init__(self) -> None:
        _ids(self.account_id, self.snapshot_id)
        try:
            normalized = require_utc(self.valuation_at)
        except (OverflowError, ValueError):
            fail_validation("Snapshot UTC valuation exceeds supported dates.", field="valuation_at")
        object.__setattr__(self, "valuation_at", normalized)
        historical_digest(self.content_digest, "snapshot.content_digest")
        _nonnegative_money(self.value, "snapshot.value")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionInitialSelection:
    kind: Literal["observed_snapshot", "modeled_value"]
    snapshot_id: UUID | None = None
    modeled_value: Money | None = None
    modeled_anchor_date: date | None = None

    def __post_init__(self) -> None:
        if self.kind == "observed_snapshot":
            if (
                type(self.snapshot_id) is not UUID
                or self.modeled_value is not None
                or self.modeled_anchor_date is not None
            ):
                fail_validation(
                    "Observed initial basis accepts only a snapshot ID.", field="initial"
                )
        elif self.kind == "modeled_value":
            if self.snapshot_id is not None or self.modeled_value is None:
                fail_validation(
                    "Modeled initial basis requires explicit money and date.", field="initial"
                )
            _nonnegative_money(self.modeled_value, "initial.modeled_value")
            require_projection_date(self.modeled_anchor_date, "initial.modeled_anchor_date")
        else:
            fail_validation("Unknown projection initial basis.", field="initial.kind")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionRunSelection:
    account_id: UUID
    assumption_version_id: UUID
    initial: ProjectionInitialSelection
    schedule: ProjectionDatedSchedule
    seed: int
    months: int
    paths: int
    retained_months: tuple[int, ...]
    allocation: tuple[ProjectionAllocation, ...]
    goal_version_id: UUID | None = None
    sensitivity: ProjectionSensitivity | None = None

    def __post_init__(self) -> None:
        _ids(self.account_id, self.assumption_version_id)
        if self.goal_version_id is not None:
            _ids(self.goal_version_id)
        if (
            type(self.initial) is not ProjectionInitialSelection
            or type(self.schedule) is not ProjectionDatedSchedule
        ):
            fail_validation("Typed projection selection is required.", field="selection")
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
                "Retained months must be unique with both endpoints.", field="retained_months"
            )
        object.__setattr__(self, "retained_months", tuple(sorted(self.retained_months)))
        source_tuple(self.allocation, ProjectionAllocation, "allocation", 12)
        if not self.allocation or len({a.key for a in self.allocation}) != len(self.allocation):
            fail_validation(
                "Projection allocation must be unique and nonempty.", field="allocation"
            )
        object.__setattr__(self, "allocation", tuple(sorted(self.allocation, key=lambda a: a.key)))
        if self.sensitivity is not None and type(self.sensitivity) is not ProjectionSensitivity:
            fail_validation("Typed sensitivity is required.", field="sensitivity")


def _initial(
    selection: ProjectionRunSelection, snapshot: ProjectionSnapshotValue | None
) -> tuple[date, ProjectionInitialBasis]:
    initial = selection.initial
    if initial.kind == "observed_snapshot":
        if (
            type(snapshot) is not ProjectionSnapshotValue
            or snapshot.account_id != selection.account_id
            or snapshot.snapshot_id != initial.snapshot_id
        ):
            fail_validation("Selected snapshot basis differs.", field="initial.snapshot_id")
        return snapshot.valuation_at.date(), ProjectionInitialBasis(
            kind="observed_snapshot",
            value=snapshot.value,
            snapshot_pin=ProjectionSourcePin(
                subject_id=str(snapshot.snapshot_id), content_digest=snapshot.content_digest
            ),
        )
    if snapshot is not None or initial.modeled_anchor_date is None or initial.modeled_value is None:
        fail_validation("Modeled initial basis has unexpected source data.", field="initial")
    return initial.modeled_anchor_date, ProjectionInitialBasis(
        kind="modeled_value", value=initial.modeled_value
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionCapturePlan:
    selection: ProjectionRunSelection
    assumption_version: ProjectionAssumptionVersion
    goal_version: ProjectionGoalVersion | None = None
    snapshot: ProjectionSnapshotValue | None = None
    calendar: ProjectionCalendar = field(init=False)
    inputs: ProjectionInput = field(init=False)
    numerical_input_digest: str = field(init=False)
    schema_version: Literal["1.0.0"] = "1.0.0"

    def __post_init__(self) -> None:
        selection, version = self.selection, self.assumption_version
        if (
            type(selection) is not ProjectionRunSelection
            or type(version) is not ProjectionAssumptionVersion
            or version.account_id != selection.account_id
            or version.version_id != selection.assumption_version_id
            or self.schema_version != "1.0.0"
        ):
            fail_validation(
                "Selected immutable assumption basis differs.", field="assumption_version_id"
            )
        anchor, initial = _initial(selection, self.snapshot)
        calendar = ProjectionCalendar(anchor_date=anchor, months=selection.months)
        schedule = selection.schedule.resolve(calendar)
        goal: ProjectionGoal | None = None
        if selection.goal_version_id is None:
            if self.goal_version is not None:
                fail_validation("Unselected goal content was supplied.", field="goal_version_id")
        else:
            saved = self.goal_version
            if (
                type(saved) is not ProjectionGoalVersion
                or saved.account_id != selection.account_id
                or saved.version_id != selection.goal_version_id
            ):
                fail_validation("Selected immutable goal basis differs.", field="goal_version_id")
            content = saved.content
            if (
                content.assumption_version_id != selection.assumption_version_id
                or content.months != selection.months
                or content.schedule != selection.schedule
            ):
                fail_validation("Goal assumption, horizon or exact schedule differs.", field="goal")
            calendar.validate_target_date(content.target_date)
            goal = ProjectionGoal(
                version_id=str(saved.version_id),
                assumption_version_id=str(content.assumption_version_id),
                target=content.target,
                basis=content.basis,
                months=content.months,
                probability_objective=content.probability_objective,
                schedule=content.schedule.resolve(calendar),
            )
        inputs = ProjectionInput(
            assumption_version_id=str(version.version_id),
            assumptions=version.content,
            initial=initial,
            schedule=schedule,
            seed=selection.seed,
            months=selection.months,
            paths=selection.paths,
            retained_months=selection.retained_months,
            allocation=selection.allocation,
            goal=goal,
            sensitivity=selection.sensitivity,
        )
        validate_projection_capacity(inputs)
        object.__setattr__(self, "calendar", calendar)
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "numerical_input_digest", projection_input_digest(inputs))
        projection_capture_bytes(self)


def preflight_projection(
    selection: ProjectionRunSelection,
    assumption_version: ProjectionAssumptionVersion,
    *,
    goal_version: ProjectionGoalVersion | None = None,
    snapshot: ProjectionSnapshotValue | None = None,
) -> ProjectionCapturePlan:
    return ProjectionCapturePlan(
        selection=selection,
        assumption_version=assumption_version,
        goal_version=goal_version,
        snapshot=snapshot,
    )


def projection_capture_bytes(plan: ProjectionCapturePlan) -> bytes:
    """Bound complete calendar/source intent separately from numerical identity."""
    if type(plan) is not ProjectionCapturePlan:
        fail_validation("A typed capture plan is required.", field="capture")
    result = canonical_json(plan).encode()
    if len(result) > PROJECTION_MAX_BYTES:
        fail_validation(
            "Projection capture exceeds its complete byte bound.", field="capture.bytes"
        )
    return result


def projection_capture_digest(plan: ProjectionCapturePlan) -> str:
    return sha256(b"t212pi.projection.capture.v1\0" + projection_capture_bytes(plan)).hexdigest()
