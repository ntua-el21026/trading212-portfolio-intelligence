"""Explicit discrete monthly calendar; no clocks or source authorization."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal

from trading212_domain.errors import fail_validation
from trading212_domain.sources import source_integer

PROJECTION_CALENDAR_RULE = "calendar_anniversary_clamped_v1"


class ProjectionCalendarErrorCode(StrEnum):
    CALENDAR_OVERFLOW = "CALENDAR_OVERFLOW"
    DATE_OUTSIDE_HORIZON = "DATE_OUTSIDE_HORIZON"
    DATE_NOT_MONTH_BOUNDARY = "DATE_NOT_MONTH_BOUNDARY"
    GOAL_DATE_MISMATCH = "GOAL_DATE_MISMATCH"


@dataclass(slots=True)
class ProjectionCalendarError(Exception):
    code: ProjectionCalendarErrorCode
    field: str
    message: str

    def __str__(self) -> str:
        return self.message


def require_projection_date(value: object, field_name: str) -> None:
    # datetime is a date subclass but is not an accepted monthly date spelling.
    if type(value) is not date:
        fail_validation("An explicit calendar date is required.", field=field_name)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionCalendar:
    anchor_date: date
    months: int
    rule: Literal["calendar_anniversary_clamped_v1"] = "calendar_anniversary_clamped_v1"
    boundaries: tuple[date, ...] = field(init=False)

    def __post_init__(self) -> None:
        require_projection_date(self.anchor_date, "anchor_date")
        source_integer(self.months, "months", 1, 600)
        if self.rule != PROJECTION_CALENDAR_RULE:
            fail_validation("Unknown projection calendar rule.", field="calendar.rule")
        origin = (self.anchor_date.year - 1) * 12 + self.anchor_date.month - 1
        if origin + self.months >= 9999 * 12:
            raise ProjectionCalendarError(
                ProjectionCalendarErrorCode.CALENDAR_OVERFLOW,
                "anchor_date",
                "The requested monthly horizon exceeds supported calendar dates.",
            )
        result: list[date] = []
        for ordinal in range(self.months + 1):
            year_index, month_index = divmod(origin + ordinal, 12)
            year, month = year_index + 1, month_index + 1
            day = min(self.anchor_date.day, monthrange(year, month)[1])
            result.append(date(year, month, day))
        object.__setattr__(self, "boundaries", tuple(result))

    @property
    def terminal_date(self) -> date:
        return self.boundaries[-1]

    def flow_month(self, value: date, *, field_name: str = "schedule.date") -> int:
        """Map only an exact start boundary to the ensuing one-based month."""
        require_projection_date(value, field_name)
        if value < self.anchor_date or value >= self.terminal_date:
            raise ProjectionCalendarError(
                ProjectionCalendarErrorCode.DATE_OUTSIDE_HORIZON,
                field_name,
                "A flow date must precede the terminal date and not precede the anchor.",
            )
        try:
            return self.boundaries[:-1].index(value) + 1
        except ValueError:
            raise ProjectionCalendarError(
                ProjectionCalendarErrorCode.DATE_NOT_MONTH_BOUNDARY,
                field_name,
                "Use an exact modeled month start; mid-period dates are not shifted.",
            ) from None

    def validate_target_date(self, value: date) -> None:
        require_projection_date(value, "goal.target_date")
        if value != self.terminal_date:
            raise ProjectionCalendarError(
                ProjectionCalendarErrorCode.GOAL_DATE_MISMATCH,
                "goal.target_date",
                "The goal target date must equal the terminal monthly boundary.",
            )
