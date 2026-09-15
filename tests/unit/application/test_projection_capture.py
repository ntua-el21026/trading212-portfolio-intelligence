"""Isolated calendar and immutable agreement tests; no storage/authentication stand-in."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Context, Decimal, Inexact, Rounded, localcontext
from typing import Any
from uuid import UUID

import pytest
from trading212_application.projection_calendar import (
    ProjectionCalendar,
    ProjectionCalendarError,
    ProjectionCalendarErrorCode,
)
from trading212_application.projection_capture import (
    ProjectionAssumptionVersion,
    ProjectionDatedEntry,
    ProjectionDatedSchedule,
    ProjectionGoalVersion,
    ProjectionGoalVersionContent,
    ProjectionInitialSelection,
    ProjectionRunSelection,
    ProjectionSnapshotValue,
    preflight_projection,
    projection_capture_bytes,
    projection_capture_digest,
    projection_definition_digest,
)
from trading212_domain.errors import DomainError
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
)
from trading212_domain.values import CurrencyCode, Money

pytestmark = pytest.mark.unit
D = Decimal
EUR = CurrencyCode("EUR")
ACCOUNT, ASSUMPTION, GOAL, SNAPSHOT = (UUID(int=n) for n in range(1, 5))


def _schedule() -> ProjectionDatedSchedule:
    return ProjectionDatedSchedule(
        base_monthly=Money(D(10), EUR),
        annual_growth=D(".1"),
        paused_dates=(date(2025, 2, 28),),
        entries=(
            ProjectionDatedEntry(
                key="withdraw-a", on=date(2025, 3, 31), kind="withdrawal", value=Money(D(3), EUR)
            ),
            ProjectionDatedEntry(
                key="lump-b", on=date(2025, 2, 28), kind="lump_sum", value=Money(D(7), EUR)
            ),
            ProjectionDatedEntry(
                key="lump-a", on=date(2025, 1, 31), kind="lump_sum", value=Money(D(5), EUR)
            ),
            ProjectionDatedEntry(
                key="withdraw-b", on=date(2025, 3, 31), kind="withdrawal", value=Money(D(2), EUR)
            ),
        ),
    )


def _assumption(content: ProjectionAssumptions | None = None) -> ProjectionAssumptionVersion:
    if content is None:
        content = ProjectionAssumptions(
            assets=(
                ProjectionAsset(
                    key="cash", annual_mean_log_return=D(0), annual_volatility=D(0), weight=D(1)
                ),
            ),
            correlation=((D(1),),),
            reporting_currency=EUR,
        )
    return ProjectionAssumptionVersion(
        account_id=ACCOUNT,
        version_id=ASSUMPTION,
        content=content,
        content_digest=projection_definition_digest(content),
    )


def _selection(**changes: Any) -> ProjectionRunSelection:
    baseline = ProjectionRunSelection(
        account_id=ACCOUNT,
        assumption_version_id=ASSUMPTION,
        initial=ProjectionInitialSelection(
            kind="modeled_value",
            modeled_value=Money(D(100), EUR),
            modeled_anchor_date=date(2025, 1, 31),
        ),
        schedule=_schedule(),
        seed=31,
        months=3,
        paths=4,
        retained_months=(3, 0),
        allocation=(ProjectionAllocation(key="cash", weight=D(1)),),
        goal_version_id=GOAL,
    )
    return replace(baseline, **changes)


def _goal(content: ProjectionGoalVersionContent | None = None) -> ProjectionGoalVersion:
    if content is None:
        content = ProjectionGoalVersionContent(
            assumption_version_id=ASSUMPTION,
            target=Money(D(120), EUR),
            target_date=date(2025, 4, 30),
            months=3,
            basis="real",
            probability_objective=D(".75"),
            schedule=_schedule(),
        )
    return ProjectionGoalVersion(
        account_id=ACCOUNT,
        version_id=GOAL,
        content=content,
        content_digest=projection_definition_digest(content),
    )


@pytest.mark.parametrize(
    ("anchor", "expected"),
    [
        (
            date(2025, 1, 31),
            (date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31), date(2025, 4, 30)),
        ),
        (
            date(2024, 1, 31),
            (date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30)),
        ),
        (
            date(2024, 2, 29),
            (date(2024, 2, 29), date(2024, 3, 29), date(2024, 4, 29), date(2024, 5, 29)),
        ),
        (
            date(2025, 12, 30),
            (date(2025, 12, 30), date(2026, 1, 30), date(2026, 2, 28), date(2026, 3, 30)),
        ),
    ],
)
def test_anniversary_boundaries_use_original_day(anchor: date, expected: tuple[date, ...]) -> None:
    calendar = ProjectionCalendar(anchor_date=anchor, months=3)
    assert calendar.boundaries == expected
    assert calendar.terminal_date == expected[-1]
    assert tuple(calendar.flow_month(item) for item in expected[:-1]) == (1, 2, 3)


def test_leap_anniversary_does_not_permanently_clamp() -> None:
    calendar = ProjectionCalendar(anchor_date=date(2024, 2, 29), months=13)
    assert calendar.boundaries[12:] == (date(2025, 2, 28), date(2025, 3, 29))
    assert ProjectionCalendar(anchor_date=date(9949, 12, 31), months=600).terminal_date == date(
        9999, 12, 31
    )
    with pytest.raises(ProjectionCalendarError) as failure:
        ProjectionCalendar(anchor_date=date(9950, 1, 1), months=600)
    assert failure.value.code == ProjectionCalendarErrorCode.CALENDAR_OVERFLOW


@pytest.mark.parametrize(
    ("on", "code"),
    [
        (date(2025, 1, 30), ProjectionCalendarErrorCode.DATE_OUTSIDE_HORIZON),
        (date(2025, 2, 1), ProjectionCalendarErrorCode.DATE_NOT_MONTH_BOUNDARY),
        (date(2025, 3, 28), ProjectionCalendarErrorCode.DATE_NOT_MONTH_BOUNDARY),
        (date(2025, 4, 30), ProjectionCalendarErrorCode.DATE_OUTSIDE_HORIZON),
        (date(2025, 5, 31), ProjectionCalendarErrorCode.DATE_OUTSIDE_HORIZON),
    ],
)
def test_dated_flows_are_never_relocated(on: date, code: ProjectionCalendarErrorCode) -> None:
    calendar = ProjectionCalendar(anchor_date=date(2025, 1, 31), months=3)
    with pytest.raises(ProjectionCalendarError) as failure:
        calendar.flow_month(on)
    assert failure.value.code == code
    assert failure.value.field == "schedule.date"


def test_calendar_and_original_schedule_are_retained_with_exact_kernel_mapping() -> None:
    plan = preflight_projection(_selection(), _assumption(), goal_version=_goal())
    assert plan.inputs.retained_months == (0, 3)
    assert plan.inputs.initial.value == Money(D(100), EUR)
    assert plan.inputs.schedule.base_monthly == Money(D(10), EUR)
    assert plan.inputs.schedule.annual_growth == D(".1")
    assert plan.inputs.schedule.paused_months == (2,)
    assert tuple(
        (entry.key, entry.month, entry.value.amount) for entry in plan.inputs.schedule.entries
    ) == (
        ("lump-a", 1, D(5)),
        ("lump-b", 2, D(7)),
        ("withdraw-a", 3, D(3)),
        ("withdraw-b", 3, D(2)),
    )
    assert plan.inputs.goal is not None and plan.inputs.goal.schedule == plan.inputs.schedule
    payload = json.loads(projection_capture_bytes(plan))
    assert payload["calendar"]["boundaries"] == [
        "2025-01-31",
        "2025-02-28",
        "2025-03-31",
        "2025-04-30",
    ]
    assert payload["selection"]["schedule"]["paused_dates"] == ["2025-02-28"]
    assert payload["goal_version"]["content"]["target_date"] == "2025-04-30"
    assert payload["inputs"]["schedule"]["paused_months"] == [2]
    assert payload["snapshot"] is None
    reordered = replace(
        plan.selection,
        schedule=replace(
            plan.selection.schedule, entries=tuple(reversed(plan.selection.schedule.entries))
        ),
        retained_months=(3, 0),
    )
    assert projection_capture_bytes(
        preflight_projection(reordered, _assumption(), goal_version=_goal())
    ) == projection_capture_bytes(plan)


def test_observed_anchor_uses_actual_utc_valuation_date_and_retains_instant() -> None:
    observed = ProjectionSnapshotValue(
        account_id=ACCOUNT,
        snapshot_id=SNAPSHOT,
        valuation_at=datetime(2024, 3, 1, 1, 15, 30, tzinfo=timezone(timedelta(hours=2))),
        content_digest="a" * 64,
        value=Money(D("123.45"), EUR),
    )
    selection = _selection(
        initial=ProjectionInitialSelection(kind="observed_snapshot", snapshot_id=SNAPSHOT),
        schedule=ProjectionDatedSchedule(base_monthly=Money(D(0), EUR)),
        goal_version_id=None,
    )
    plan = preflight_projection(selection, _assumption(), snapshot=observed)
    assert plan.calendar.anchor_date == date(2024, 2, 29)
    assert plan.calendar.terminal_date == date(2024, 5, 29)
    assert plan.snapshot is not None
    assert plan.snapshot.valuation_at == datetime(2024, 2, 29, 23, 15, 30, tzinfo=UTC)
    assert plan.inputs.initial.value == observed.value
    assert plan.inputs.initial.snapshot_pin is not None
    assert plan.inputs.initial.snapshot_pin.subject_id == str(SNAPSHOT)
    assert plan.inputs.initial.snapshot_pin.content_digest == observed.content_digest
    assert (
        json.loads(projection_capture_bytes(plan))["snapshot"]["valuation_at"]
        == "2024-02-29T23:15:30Z"
    )


def test_calendar_intent_has_distinct_capture_identity_from_numerical_identity() -> None:
    selection = _selection(
        schedule=ProjectionDatedSchedule(base_monthly=Money(D(0), EUR)), goal_version_id=None
    )
    first = preflight_projection(selection, _assumption())
    second = preflight_projection(
        replace(
            selection, initial=replace(selection.initial, modeled_anchor_date=date(2025, 2, 28))
        ),
        _assumption(),
    )
    assert first.numerical_input_digest == second.numerical_input_digest
    assert first.calendar.boundaries != second.calendar.boundaries
    assert projection_capture_digest(first) != projection_capture_digest(second)


@pytest.mark.parametrize("attribute", ["version_id", "account_id"])
def test_selected_version_identity_and_account_must_match(attribute: str) -> None:
    changes: dict[str, Any] = {attribute: UUID(int=99)}
    with pytest.raises(DomainError):
        preflight_projection(_selection(), replace(_assumption(), **changes), goal_version=_goal())
    with pytest.raises(DomainError):
        preflight_projection(_selection(), _assumption(), goal_version=replace(_goal(), **changes))


def test_immutable_goal_schedule_is_not_equated_by_net_amount() -> None:
    saved = _goal()
    original = _selection()
    for schedule in (
        replace(original.schedule, base_monthly=Money(D(11), EUR)),
        replace(original.schedule, annual_growth=D(0)),
        replace(original.schedule, paused_dates=()),
        replace(
            original.schedule,
            entries=tuple(
                replace(e, key="renamed") if e.key == "lump-a" else e
                for e in original.schedule.entries
            ),
        ),
        replace(
            original.schedule,
            entries=tuple(
                replace(e, on=date(2025, 2, 28)) if e.key == "lump-a" else e
                for e in original.schedule.entries
            ),
        ),
        replace(
            original.schedule,
            entries=(
                *(e for e in original.schedule.entries if e.kind != "withdrawal"),
                ProjectionDatedEntry(
                    key="net-withdrawal",
                    on=date(2025, 3, 31),
                    kind="withdrawal",
                    value=Money(D(5), EUR),
                ),
            ),
        ),
    ):
        with pytest.raises(DomainError):
            preflight_projection(
                replace(original, schedule=schedule), _assumption(), goal_version=saved
            )


def test_goal_date_horizon_assumption_currency_and_selection_presence_agree() -> None:
    content = _goal().content
    for changed in (
        replace(content, target_date=date(2025, 4, 29)),
        replace(content, target_date=date(2025, 5, 31)),
    ):
        with pytest.raises(ProjectionCalendarError) as failure:
            preflight_projection(_selection(), _assumption(), goal_version=_goal(changed))
        assert failure.value.code == ProjectionCalendarErrorCode.GOAL_DATE_MISMATCH
    for changed in (
        replace(content, months=4),
        replace(content, assumption_version_id=UUID(int=99)),
    ):
        with pytest.raises(DomainError):
            preflight_projection(_selection(), _assumption(), goal_version=_goal(changed))
    with pytest.raises(DomainError):
        preflight_projection(_selection(), _assumption())
    with pytest.raises(DomainError):
        preflight_projection(_selection(goal_version_id=None), _assumption(), goal_version=_goal())
    with pytest.raises(DomainError):
        replace(content, target=Money(D(120), CurrencyCode("USD")))


def test_version_digest_allocation_and_snapshot_basis_reject_mutations() -> None:
    with pytest.raises(DomainError):
        replace(_assumption(), content=replace(_assumption().content, annual_fee=D(".1")))
    with pytest.raises(DomainError):
        replace(_goal(), content=replace(_goal().content, target=Money(D(121), EUR)))
    for allocation in (
        (ProjectionAllocation(key="cash", weight=D(".5")),),
        (ProjectionAllocation(key="other", weight=D(1)),),
    ):
        with pytest.raises(DomainError):
            preflight_projection(
                _selection(allocation=allocation), _assumption(), goal_version=_goal()
            )
    observed = ProjectionSnapshotValue(
        account_id=ACCOUNT,
        snapshot_id=SNAPSHOT,
        valuation_at=datetime(2025, 1, 31, tzinfo=UTC),
        content_digest="a" * 64,
        value=Money(D(100), EUR),
    )
    selection = _selection(
        initial=ProjectionInitialSelection(kind="observed_snapshot", snapshot_id=SNAPSHOT)
    )
    for snapshot in (
        None,
        replace(observed, account_id=UUID(int=99)),
        replace(observed, snapshot_id=UUID(int=99)),
        replace(observed, value=Money(D(100), CurrencyCode("USD"))),
    ):
        with pytest.raises(DomainError):
            preflight_projection(selection, _assumption(), goal_version=_goal(), snapshot=snapshot)
    with pytest.raises(DomainError):
        preflight_projection(_selection(), _assumption(), goal_version=_goal(), snapshot=observed)


def test_schedule_and_date_inputs_have_finite_strict_bounds() -> None:
    for on in (datetime(2025, 1, 31, tzinfo=UTC), "2025-01-31", None):
        with pytest.raises(DomainError):
            ProjectionCalendar(anchor_date=on, months=3)  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        ProjectionInitialSelection(kind="modeled_value", modeled_value=Money(D(100), EUR))
    with pytest.raises(DomainError):
        ProjectionInitialSelection(
            kind="observed_snapshot", snapshot_id=SNAPSHOT, modeled_anchor_date=date(2025, 1, 31)
        )
    with pytest.raises(DomainError):
        replace(_schedule(), paused_dates=(date(2025, 2, 28), date(2025, 2, 28)))
    with pytest.raises(DomainError):
        replace(_schedule(), entries=(_schedule().entries[0], _schedule().entries[0]))
    dates = tuple(date(2025, 1, 1) + timedelta(days=n) for n in range(128))
    with pytest.raises(DomainError):
        ProjectionDatedSchedule(
            base_monthly=Money(D(0), EUR), paused_dates=dates, entries=(_schedule().entries[0],)
        )
    with pytest.raises(DomainError):
        _selection(seed=True)
    with pytest.raises(DomainError):
        ProjectionSnapshotValue(
            account_id=ACCOUNT,
            snapshot_id=SNAPSHOT,
            valuation_at=datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=2))),
            content_digest="a" * 64,
            value=Money(D(100), EUR),
        )
    invalid = replace(
        _selection(goal_version_id=None),
        schedule=replace(_schedule(), paused_dates=(date(2025, 4, 30),)),
    )
    with pytest.raises(ProjectionCalendarError) as failure:
        preflight_projection(invalid, _assumption())
    assert failure.value.code == ProjectionCalendarErrorCode.DATE_OUTSIDE_HORIZON


def test_preflight_invokes_actual_psd_validation() -> None:
    content = ProjectionAssumptions(
        assets=tuple(
            ProjectionAsset(
                key=key, annual_mean_log_return=D(0), annual_volatility=D(1), weight=weight
            )
            for key, weight in (("a", D(".4")), ("b", D(".3")), ("c", D(".3")))
        ),
        correlation=((D(1), D(1), D(0)), (D(1), D(1), D(1)), (D(0), D(1), D(1))),
        reporting_currency=EUR,
    )
    selection = _selection(
        goal_version_id=None,
        allocation=tuple(ProjectionAllocation(key=a.key, weight=a.weight) for a in content.assets),
    )
    with pytest.raises(DomainError):
        preflight_projection(selection, _assumption(content))


def test_preflight_restores_hostile_decimal_context_and_is_repeatable() -> None:
    expected = projection_capture_bytes(
        preflight_projection(_selection(), _assumption(), goal_version=_goal())
    )
    with localcontext(Context(prec=3, rounding=ROUND_DOWN, Emin=-9, Emax=9)) as hostile:
        for signal in hostile.traps:
            hostile.traps[signal] = True
        hostile.flags[Inexact] = hostile.flags[Rounded] = True
        before = hostile.copy()
        actual = projection_capture_bytes(
            preflight_projection(_selection(), _assumption(), goal_version=_goal())
        )
        assert hostile.prec == before.prec and hostile.rounding == before.rounding
        assert hostile.flags == before.flags and hostile.traps == before.traps
    assert actual == expected
