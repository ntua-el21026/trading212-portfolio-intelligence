"""Small fully calculated synthetic retained results for presentation tests."""

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from uuid import UUID

from trading212_analytics.projection import calculate_projection
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
from trading212_application.projection_presentation import (
    ProjectionRetainedEvidence,
    RetainedProjectionPresentation,
)
from trading212_domain.enums import QualityState
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
    ProjectionSensitivity,
    ProjectionSourcePin,
)
from trading212_domain.projection_serialization import projection_canonical_bytes
from trading212_domain.values import CurrencyCode, Money

D = Decimal
EUR = CurrencyCode("EUR")
ACCOUNT, VERSION, GOAL, SNAPSHOT = (UUID(int=item) for item in (100, 101, 102, 103))


def retained(
    *,
    goal: bool = True,
    sensitive: bool = True,
    source_count: int = 1,
    observed: bool = True,
    basis: Literal["nominal", "real"] = "real",
    loss_only: bool = False,
    tiny_unpaid: bool = False,
) -> RetainedProjectionPresentation:
    assets = (
        ProjectionAsset(
            key="alpha",
            annual_mean_log_return=D("-.2") if loss_only else D(".04"),
            annual_volatility=D(0) if loss_only or tiny_unpaid else D(".2"),
            weight=D(1),
        ),
    )
    assumptions = ProjectionAssumptions(
        assets=assets,
        correlation=((D(1),),),
        reporting_currency=EUR,
        annual_inflation=D(".02"),
        annual_fee=D(".001") if not tiny_unpaid else D(".000000000000000001"),
        annual_tax_drag=D(".003") if not tiny_unpaid else D(0),
        rebalance="annual",
        calibration_pins=tuple(
            ProjectionSourcePin(
                subject_id=str(UUID(int=1000 + index)), content_digest=f"{index:064x}"
            )
            for index in range(source_count)
        ),
    )
    if tiny_unpaid:
        assumptions = ProjectionAssumptions(
            assets=(
                ProjectionAsset(
                    key="alpha", annual_mean_log_return=D(0), annual_volatility=D(0), weight=D(1)
                ),
            ),
            correlation=((D(1),),),
            reporting_currency=EUR,
            annual_fee=D(".000000000000000001"),
            calibration_pins=assumptions.calibration_pins,
        )
    version = ProjectionAssumptionVersion(
        account_id=ACCOUNT,
        version_id=VERSION,
        content=assumptions,
        content_digest=projection_definition_digest(assumptions),
    )
    schedule = ProjectionDatedSchedule(
        base_monthly=Money(D(0) if tiny_unpaid else D(10), EUR),
        entries=(
            ProjectionDatedEntry(
                key="withdrawal",
                on=date(2025, 2, 28),
                kind="withdrawal",
                value=Money(D(1) if tiny_unpaid else D(75), EUR),
            ),
        ),
    )
    initial_value = Money(D(1) if tiny_unpaid else D("100.123456789012345678"), EUR)
    initial = (
        ProjectionInitialSelection(kind="observed_snapshot", snapshot_id=SNAPSHOT)
        if observed
        else ProjectionInitialSelection(
            kind="modeled_value", modeled_value=initial_value, modeled_anchor_date=date(2025, 1, 31)
        )
    )
    selection = ProjectionRunSelection(
        account_id=ACCOUNT,
        assumption_version_id=VERSION,
        initial=initial,
        schedule=schedule,
        seed=23,
        months=3,
        paths=7,
        retained_months=(0, 1, 2, 3),
        allocation=(ProjectionAllocation(key="alpha", weight=D(1)),),
        goal_version_id=GOAL if goal else None,
        sensitivity=ProjectionSensitivity(
            contribution_delta=Money(D(2), EUR), annual_mean_log_delta=D(".005")
        )
        if sensitive
        else None,
    )
    goal_version = None
    if goal:
        content = ProjectionGoalVersionContent(
            assumption_version_id=VERSION,
            target=Money(D(50), EUR),
            target_date=date(2025, 4, 30),
            months=3,
            basis=basis,
            probability_objective=D(".6"),
            schedule=schedule,
        )
        goal_version = ProjectionGoalVersion(
            account_id=ACCOUNT,
            version_id=GOAL,
            content=content,
            content_digest=projection_definition_digest(content),
        )
    snapshot = (
        ProjectionSnapshotValue(
            account_id=ACCOUNT,
            snapshot_id=SNAPSHOT,
            valuation_at=datetime(2025, 1, 31, 23, 17, 21, 123456, tzinfo=UTC),
            content_digest="f" * 64,
            value=initial_value,
        )
        if observed
        else None
    )
    capture = ProjectionCapturePlan(
        selection=selection,
        assumption_version=version,
        goal_version=goal_version,
        snapshot=snapshot,
    )
    calculation = calculate_projection(capture.inputs)
    evidence = tuple(
        ProjectionRetainedEvidence(
            role="calibration",
            subject_id=UUID(pin.subject_id),
            content_digest=pin.content_digest,
            quality=QualityState.FRESH,
            source_reference_ids=tuple(UUID(int=2000 + index) for index in range(20)),
        )
        for pin in assumptions.calibration_pins
    )
    if snapshot is not None:
        evidence += (
            ProjectionRetainedEvidence(
                role="observed_snapshot",
                subject_id=SNAPSHOT,
                content_digest=snapshot.content_digest,
                quality=QualityState.FRESH,
                source_reference_ids=(),
            ),
        )
    return RetainedProjectionPresentation(
        account_id=ACCOUNT,
        run_id=UUID(int=104),
        result_id=UUID(int=105),
        capture_digest=projection_capture_digest(capture),
        saved_result_digest=sha256(projection_canonical_bytes(calculation)).hexdigest(),
        capture=capture,
        calculation=calculation,
        calculated_at=datetime(2025, 2, 1, 0, 0, 1, 999999, tzinfo=UTC),
        source_cutoff_at=datetime(2025, 2, 1, tzinfo=UTC) if evidence else None,
        quality=QualityState.ESTIMATED,
        source_evidence=evidence,
    )
