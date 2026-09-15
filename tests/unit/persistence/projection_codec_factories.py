"""Synthetic canonical projection graphs for private codec tests only."""

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from trading212_application.projection_capture import (
    ProjectionAssumptionVersion,
    ProjectionCapturePlan,
    ProjectionDatedEntry,
    ProjectionDatedSchedule,
    ProjectionGoalVersion,
    ProjectionGoalVersionContent,
    ProjectionInitialSelection,
    ProjectionRunSelection,
    ProjectionSnapshotValue,
    projection_capture_digest,
    projection_definition_digest,
)
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
    ProjectionSensitivity,
    ProjectionSourcePin,
)
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.projection_capture_codec import ProjectionCaptureBinding

EUR = CurrencyCode("EUR")
D = Decimal
ACCOUNT, VERSION, GOAL, SNAPSHOT = (UUID(int=i) for i in (100, 101, 102, 103))


def capture(
    *, observed: bool = True, goal: bool = True, sensitive: bool = True
) -> ProjectionCapturePlan:
    assumptions = ProjectionAssumptions(
        assets=(
            ProjectionAsset(
                key="alpha",
                annual_mean_log_return=D(".04"),
                annual_volatility=D(".1"),
                weight=D(".6"),
            ),
            ProjectionAsset(
                key="beta",
                annual_mean_log_return=D(".02"),
                annual_volatility=D(".05"),
                weight=D(".4"),
            ),
        ),
        correlation=((D(1), D(".25")), (D(".25"), D(1))),
        reporting_currency=EUR,
        annual_inflation=D(".02"),
        annual_fee=D(".001"),
        annual_tax_drag=D(".003"),
        rebalance="annual",
        calibration_pins=(
            ProjectionSourcePin(subject_id=str(UUID(int=110)), content_digest="a" * 64),
        ),
    )
    version = ProjectionAssumptionVersion(
        account_id=ACCOUNT,
        version_id=VERSION,
        content=assumptions,
        content_digest=projection_definition_digest(assumptions),
    )
    schedule = ProjectionDatedSchedule(
        base_monthly=Money(D(10), EUR),
        annual_growth=D(".1"),
        paused_dates=(date(2025, 2, 28),),
        entries=(
            ProjectionDatedEntry(
                key="lump", on=date(2025, 1, 31), kind="lump_sum", value=Money(D(7), EUR)
            ),
            ProjectionDatedEntry(
                key="withdrawal", on=date(2025, 3, 31), kind="withdrawal", value=Money(D(3), EUR)
            ),
        ),
    )
    initial = (
        ProjectionInitialSelection(kind="observed_snapshot", snapshot_id=SNAPSHOT)
        if observed
        else ProjectionInitialSelection(
            kind="modeled_value",
            modeled_value=Money(D("1500.123456789012345678"), EUR),
            modeled_anchor_date=date(2025, 1, 31),
        )
    )
    selection = ProjectionRunSelection(
        account_id=ACCOUNT,
        assumption_version_id=VERSION,
        initial=initial,
        schedule=schedule,
        seed=1945,
        months=3,
        paths=3,
        retained_months=(0, 1, 2, 3),
        allocation=tuple(
            ProjectionAllocation(key=a.key, weight=a.weight) for a in assumptions.assets
        ),
        goal_version_id=GOAL if goal else None,
        sensitivity=ProjectionSensitivity(
            contribution_delta=Money(D(2), EUR), annual_mean_log_delta=D(".005")
        )
        if sensitive
        else None,
    )
    snapshot = (
        ProjectionSnapshotValue(
            account_id=ACCOUNT,
            snapshot_id=SNAPSHOT,
            valuation_at=datetime(2025, 1, 31, 23, 17, 21, 123456, tzinfo=UTC),
            content_digest="b" * 64,
            value=Money(D("1500.123456789012345678"), EUR),
        )
        if observed
        else None
    )
    goal_version = None
    if goal:
        content = ProjectionGoalVersionContent(
            assumption_version_id=VERSION,
            target=Money(D(999), EUR),
            target_date=date(2025, 4, 30),
            months=3,
            basis="real",
            probability_objective=D(".6"),
            schedule=schedule,
        )
        goal_version = ProjectionGoalVersion(
            account_id=ACCOUNT,
            version_id=GOAL,
            content=content,
            content_digest=projection_definition_digest(content),
        )
    return ProjectionCapturePlan(
        selection=selection,
        assumption_version=version,
        goal_version=goal_version,
        snapshot=snapshot,
    )


def binding(
    value: ProjectionCapturePlan, *, payload: bytes | None = None
) -> ProjectionCaptureBinding:
    digest = (
        projection_capture_digest(value)
        if payload is None
        else sha256(b"t212pi.projection.capture.v1\0" + payload).hexdigest()
    )
    return ProjectionCaptureBinding(
        account_id=value.selection.account_id,
        assumption_version_id=value.selection.assumption_version_id,
        goal_version_id=value.selection.goal_version_id,
        capture_digest=digest,
        numerical_input_digest=value.numerical_input_digest,
    )
