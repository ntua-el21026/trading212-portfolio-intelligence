"""Closed service boundary tests; no persistence/worker authorization stand-in."""

from dataclasses import replace
from datetime import date
from decimal import Context, Decimal, Inexact, Rounded, localcontext
from uuid import UUID

import pytest
from trading212_application.projection import (
    CreateAssumptionSet,
    CreateAssumptionVersion,
    CreateGoal,
    CreateProjectionRun,
    ProjectionPointPageQuery,
    ProjectionService,
)
from trading212_application.projection_calendar import ProjectionCalendarError
from trading212_application.projection_capture import (
    ProjectionDatedEntry,
    ProjectionDatedSchedule,
    ProjectionGoalVersionContent,
    ProjectionInitialSelection,
    ProjectionRunSelection,
)
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_domain.errors import DomainError
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
    ProjectionSensitivity,
)
from trading212_domain.values import CurrencyCode, Money

pytestmark = pytest.mark.unit
D = Decimal
EUR = CurrencyCode("EUR")
ACCOUNT, ASSUMPTION = UUID(int=1), UUID(int=2)


def content() -> ProjectionAssumptions:
    return ProjectionAssumptions(
        assets=(
            ProjectionAsset(
                key="cash", annual_mean_log_return=D(0), annual_volatility=D(0), weight=D(1)
            ),
        ),
        correlation=((D(1),),),
        reporting_currency=EUR,
    )


def selection() -> ProjectionRunSelection:
    return ProjectionRunSelection(
        account_id=ACCOUNT,
        assumption_version_id=ASSUMPTION,
        initial=ProjectionInitialSelection(
            kind="modeled_value",
            modeled_value=Money(D(100), EUR),
            modeled_anchor_date=date(2025, 1, 31),
        ),
        schedule=ProjectionDatedSchedule(base_monthly=Money(D(10), EUR)),
        seed=0,
        months=2,
        paths=2,
        retained_months=(0, 2),
        allocation=(ProjectionAllocation(key="cash", weight=D(1)),),
    )


def test_frozen_seventeen_service_operations_have_no_source_or_broker_dispatch() -> None:
    names = {name for name in vars(ProjectionService) if not name.startswith("_")}
    assert names == {
        "create_assumption_set",
        "get_assumption_set",
        "list_assumption_sets",
        "create_assumption_version",
        "get_assumption_version",
        "list_assumption_versions",
        "create_goal",
        "get_goal",
        "list_goals",
        "create_goal_version",
        "get_goal_version",
        "list_goal_versions",
        "create_run",
        "list_runs",
        "get_run",
        "get_goal_analysis",
        "cancel_run",
    }


def test_metadata_does_not_change_numerical_content_and_hostile_context_is_isolated() -> None:
    original = content()
    metadata = ProjectionVersionMetadata(name="First assumptions")
    with localcontext(Context(prec=2, traps=[Inexact, Rounded])):
        command = CreateAssumptionSet(
            account_id=ACCOUNT,
            metadata=metadata,
            content=original,
            idempotency_key="assumption-1",
            correlation_id="projection-test",
        )
        changed = replace(command, metadata=ProjectionVersionMetadata(name="Changed label"))
        assert changed != command and changed.content is command.content
    with pytest.raises(DomainError):
        replace(command, account_id="owner-override")  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        replace(command, idempotency_key="")


def test_psd_gate_rejects_a_symmetric_indefinite_assumption_before_publication() -> None:
    assumptions = ProjectionAssumptions(
        assets=tuple(
            ProjectionAsset(
                key=key, annual_mean_log_return=D(0), annual_volatility=D(".1"), weight=weight
            )
            for key, weight in zip(("a", "b", "c"), (D(".25"), D(".25"), D(".5")), strict=True)
        ),
        correlation=(
            (D(1), D(".9"), D(".9")),
            (D(".9"), D(1), D("-.9")),
            (D(".9"), D("-.9"), D(1)),
        ),
        reporting_currency=EUR,
    )
    with pytest.raises(DomainError):
        CreateAssumptionSet(
            account_id=ACCOUNT,
            metadata=ProjectionVersionMetadata(name="Not PSD"),
            content=assumptions,
            idempotency_key="not-psd",
            correlation_id="projection-test",
        )


@pytest.mark.parametrize("revision", [0, 513, True])
def test_version_revision_bounds_are_required(revision: int) -> None:
    with pytest.raises(DomainError):
        CreateAssumptionVersion(
            set_id=ASSUMPTION,
            expected_revision=revision,
            metadata=ProjectionVersionMetadata(name="Version"),
            content=content(),
            idempotency_key="version",
            correlation_id="projection-test",
        )


def test_modeled_schedule_rejects_midperiod_before_service_but_observed_needs_capture() -> None:
    dated = ProjectionDatedSchedule(
        base_monthly=Money(D(0), EUR),
        entries=(
            ProjectionDatedEntry(
                key="lump", on=date(2025, 2, 15), kind="lump_sum", value=Money(D(1), EUR)
            ),
        ),
    )
    with pytest.raises(ProjectionCalendarError):
        CreateProjectionRun(
            selection=replace(selection(), schedule=dated),
            idempotency_key="midperiod",
            correlation_id="projection-test",
        )
    observed = replace(
        selection(),
        schedule=dated,
        initial=ProjectionInitialSelection(kind="observed_snapshot", snapshot_id=UUID(int=3)),
    )
    assert (
        CreateProjectionRun(
            selection=observed, idempotency_key="observed", correlation_id="projection-test"
        ).selection
        is observed
    )


def test_sensitivity_counts_all_three_variants_before_admission() -> None:
    selected = replace(
        selection(),
        months=600,
        paths=600,
        retained_months=(0, 600),
        sensitivity=ProjectionSensitivity(
            contribution_delta=Money(D(1), EUR), annual_mean_log_delta=D(".01")
        ),
    )
    with pytest.raises(DomainError):
        CreateProjectionRun(
            selection=selected, idempotency_key="work", correlation_id="projection-test"
        )


def test_goal_content_preserves_original_dates_and_does_not_accept_an_objective() -> None:
    selected = selection()
    goal = ProjectionGoalVersionContent(
        assumption_version_id=ASSUMPTION,
        target=Money(D(1000), EUR),
        target_date=date(2025, 3, 31),
        months=2,
        basis="real",
        probability_objective=D(".9"),
        schedule=selected.schedule,
    )
    command = CreateGoal(
        account_id=ACCOUNT,
        metadata=ProjectionVersionMetadata(name="Saved goal"),
        content=goal,
        idempotency_key="goal",
        correlation_id="projection-test",
    )
    assert command.content.target_date == date(2025, 3, 31)
    assert not hasattr(command, "accepted")


@pytest.mark.parametrize(
    "limit,cursor", [(True, None), (0, None), (101, None), (25, ""), (25, "a" * 2049)]
)
def test_point_page_boundaries(limit: int, cursor: str | None) -> None:
    with pytest.raises(DomainError):
        ProjectionPointPageQuery(point_limit=limit, point_cursor=cursor)
