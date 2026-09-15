"""Actual published projections cross all report formats without numerical replay."""

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from trading212_application import projection as projection_app
from trading212_application import reports as app
from trading212_application.projection_calendar import ProjectionCalendar
from trading212_application.projection_capture import ProjectionGoalVersionContent
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_domain import reports as r
from trading212_domain.projection import ProjectionSensitivity
from trading212_domain.projection_result import ProjectionCalculation
from trading212_domain.report_projection_schema import (
    PROJECTION_POINT_MONEY,
    PROJECTION_TABLE_COLUMNS,
)
from trading212_domain.report_v4 import ReportProjectionRunSelection
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.report_input_store import ReportInputSink
from trading212_persistence.report_models import ReportInputPremiumDependencyModel, ReportJobModel

from tests.integration.premium_report_v4_artifacts import DownloadedReportV4, download_v4
from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.projection_report_runtime import (
    complete_report,
    execute_saved,
    no_private_reads,
    no_resampling,
    report_selection,
    report_service,
    saved_projection,
)
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def money(cell: r.ReportCell, amount: Decimal, original: ProjectionCalculation) -> None:
    assert cell.kind is r.CellKind.DECIMAL and cell.state is r.CellState.AVAILABLE
    assert cell.value == amount and cell.currency == original.inputs.assumptions.reporting_currency


def financial_parity(
    report: DownloadedReportV4, original: ProjectionCalculation, calendar: ProjectionCalendar
) -> None:
    expected = [
        (variant.variant, path.index, index, point)
        for variant in original.variants
        for path in variant.paths
        for index, point in enumerate(path.points)
    ]
    rows = report.rows(r.ReportTableKey.PROJECTION_POINTS_V1)
    assert len(rows) == len(expected)
    for actual, (variant, path, index, point) in zip(rows, expected, strict=True):
        assert (
            actual["variant"].value,
            actual["path_index"].value,
            actual["point_index"].value,
            actual["month"].value,
        ) == (variant, path, index, point.month)
        assert actual["on"].value == calendar.boundaries[point.month]
        for name in PROJECTION_POINT_MONEY:
            money(actual[name], getattr(point, name), original)
        assert actual["funding_failed"].value is point.funding_failed
        assert actual["unpaid_positive_below_quantum"].value is point.unpaid_positive_below_quantum
    assets = [
        (variant, path, index, asset_index, asset)
        for variant, path, index, point in expected
        for asset_index, asset in enumerate(point.assets)
    ]
    for actual, (variant, path, index, asset_index, asset) in zip(
        report.rows(r.ReportTableKey.PROJECTION_POINT_ASSETS_V1), assets, strict=True
    ):
        assert tuple(
            actual[key].value
            for key in ("variant", "path_index", "point_index", "asset_index", "key")
        ) == (variant, path, index, asset_index, asset.key)
        money(actual["value"], asset.value, original)
    distributions = [
        (variant.variant, value) for variant in original.variants for value in variant.distributions
    ]
    for actual, (variant, value) in zip(
        report.rows(r.ReportTableKey.PROJECTION_DISTRIBUTIONS_V1), distributions, strict=True
    ):
        assert (actual["variant"].value, actual["month"].value) == (variant, value.month)
        money(actual["nominal_mean"], value.nominal_mean, original)
        money(actual["real_mean"], value.real_mean, original)
        assert actual["funding_failed_paths"].value == value.funding_failed_paths
    quantiles = [
        (variant.variant, kind, point.month, index, probability, amount)
        for variant in original.variants
        for point in variant.distributions
        for kind, values in (("nominal", point.nominal), ("real", point.real))
        for index, (probability, amount) in enumerate(
            zip(values.probabilities, values.values, strict=True)
        )
    ]
    # Goal shortfalls follow each variant's distribution quantiles in canonical capture order.
    expected_quantiles: list[tuple[str, str, int | None, int, Decimal, Decimal]] = []
    for variant_result in original.variants:
        expected_quantiles.extend(row for row in quantiles if row[0] == variant_result.variant)
        if variant_result.goal is not None:
            expected_quantiles.extend(
                (variant_result.variant, "goal_shortfall", None, index, probability, amount)
                for index, (probability, amount) in enumerate(
                    zip(
                        variant_result.goal.shortfalls.probabilities,
                        variant_result.goal.shortfalls.values,
                        strict=True,
                    )
                )
            )
    for actual, (quantile_variant, kind, month, index, probability, amount) in zip(
        report.rows(r.ReportTableKey.PROJECTION_QUANTILES_V1), expected_quantiles, strict=True
    ):
        assert tuple(
            actual[key].value for key in ("variant", "kind", "month", "ordinal", "probability")
        ) == (quantile_variant, kind, month, index, probability)
        money(actual["value"], amount, original)
    histograms = [
        (variant.variant, basis, histogram)
        for variant in original.variants
        for basis, histogram in (
            ("nominal", variant.nominal_histogram),
            ("real", variant.real_histogram),
        )
    ]
    for actual, (variant, basis, histogram) in zip(
        report.rows(r.ReportTableKey.PROJECTION_HISTOGRAMS_V1), histograms, strict=True
    ):
        assert (actual["variant"].value, actual["basis"].value, actual["boundary_rule"].value) == (
            variant,
            basis,
            histogram.boundary_rule,
        )
        money(actual["observed_minimum"], histogram.observed_minimum, original)
        money(actual["observed_maximum"], histogram.observed_maximum, original)
    bins = [
        (variant, basis, index, item)
        for variant, basis, histogram in histograms
        for index, item in enumerate(histogram.bins)
    ]
    for actual, (variant, basis, index, item) in zip(
        report.rows(r.ReportTableKey.PROJECTION_HISTOGRAM_BINS_V1), bins, strict=True
    ):
        assert (actual["variant"].value, actual["basis"].value, actual["ordinal"].value) == (
            variant,
            basis,
            index,
        )
        money(actual["lower"], item.lower, original)
        money(actual["upper"], item.upper, original)
        assert (
            actual["upper_inclusive"].value is item.upper_inclusive
            and actual["count"].value == item.count
        )
    goals = [
        (variant.variant, variant.goal) for variant in original.variants if variant.goal is not None
    ]
    for actual, (variant, goal) in zip(
        report.rows(r.ReportTableKey.PROJECTION_GOAL_RESULTS_V1), goals, strict=True
    ):
        assert goal is not None and actual["variant"].value == variant
        for field in fields(goal):
            if field.name == "shortfalls":
                continue
            value = getattr(goal, field.name)
            if field.name in ("target", "mean_shortfall"):
                money(actual[field.name], value, original)
            else:
                assert actual[field.name].value == value
    (state,) = report.rows(r.ReportTableKey.PROJECTION_GOAL_STATE_V1)
    assert (
        state["available"].value is bool(goals)
        and state["automatic_goal_acceptance"].value is False
    )
    if not goals:
        assert state["reason"].value == "no_goal_pinned"


@pytest.mark.parametrize("goal", [False, True])
async def test_real_projection_report_four_formats_preserve_saved_points_and_goal(
    projection_job_case: ProjectionJobCase, goal: bool
) -> None:
    case = projection_job_case
    original = case.command.selection
    initial = original.initial.modeled_value
    anchor = original.initial.modeled_anchor_date
    assert initial is not None and anchor is not None
    calendar = ProjectionCalendar(anchor_date=anchor, months=original.months)
    if goal:
        await case.service.cancel_run(
            case.principal,
            projection_app.CancelProjectionRun(
                run_id=case.run.id,
                idempotency_key=str(uuid4()),
                correlation_id="report-fixture-cancel",
            ),
        )
        definition = await case.service.create_goal(
            case.principal,
            projection_app.CreateGoal(
                account_id=original.account_id,
                metadata=ProjectionVersionMetadata(
                    name="Saved report goal", description="Exact synthetic objective"
                ),
                content=ProjectionGoalVersionContent(
                    assumption_version_id=original.assumption_version_id,
                    target=Money(Decimal("120.123456789012345678"), initial.currency),
                    target_date=calendar.terminal_date,
                    months=original.months,
                    basis="real",
                    probability_objective=Decimal(".75"),
                    schedule=original.schedule,
                ),
                idempotency_key=str(uuid4()),
                correlation_id="report-fixture-goal",
            ),
        )
        case.command = replace(
            case.command,
            idempotency_key=str(uuid4()),
            selection=replace(
                original,
                goal_version_id=definition.current_version_id,
                sensitivity=ProjectionSensitivity(
                    contribution_delta=Money(Decimal("2.000000000000000001"), initial.currency),
                    annual_mean_log_delta=Decimal(".005"),
                ),
            ),
        )
        case.run = await case.service.create_run(case.principal, case.command)
    saved = await execute_saved(case)
    case.now = max(case.now + timedelta(days=2), datetime.now(UTC))
    service = report_service(case)
    selected = report_selection(case)
    if goal:
        selected = replace(selected, sections=(*selected.sections, r.ReportSection.GOAL))
    request = app.GenerateReportCommand(
        selection=selected, idempotency_key=str(uuid4()), ttl_days=30
    )
    with no_resampling():
        pending = await service.generate_report(case.principal, request)
        assert pending.expires_at <= saved.expires_at < case.now + timedelta(days=30)
        assert isinstance(pending.context, app.ReportPinnedContextV4)
        with patch.object(
            ReportInputSink, "__init__", side_effect=AssertionError("idempotent retry recaptured")
        ):
            assert await service.generate_report(case.principal, request) == pending
            with pytest.raises(app.ReportServiceError) as conflict:
                await service.generate_report(case.principal, replace(request, ttl_days=7))
            assert conflict.value.code is app.ReportServiceErrorCode.CONFLICT
        with case.sessions() as session:
            job = session.get_one(ReportJobModel, pending.job_id)
            dependency = session.scalar(
                select(ReportInputPremiumDependencyModel).where(
                    ReportInputPremiumDependencyModel.input_id == job.input_id
                )
            )
            assert dependency is not None and dependency.kind == "projection"
            assert (
                dependency.run_id,
                dependency.input_digest,
                dependency.result_id,
                dependency.result_digest,
            ) == (case.run.id, saved.capture_digest, saved.result_id, saved.result_digest)
            assert dependency.expires_at <= saved.expires_at
            assert (
                session.scalar(
                    text("""
                SELECT report_projection_manifest_valid(d,i)
                FROM report_input_premium_dependencies d
                JOIN report_input_snapshots i ON i.id=d.input_id
                WHERE i.id=:input
            """),
                    {"input": job.input_id},
                )
                is True
            )
            # JSON record copies exercise the SQL validator without mutating immutable rows.
            for leaf in ("numerical_input_digest", "capture_digest"):
                valid = session.scalar(
                    text("""
                    SELECT report_projection_manifest_valid(d,
                        jsonb_populate_record(i, jsonb_build_object(
                            'canonical_manifest', to_jsonb(convert_to(jsonb_set(
                                convert_from(i.canonical_manifest,'UTF8')::jsonb,
                                CAST(:path AS text[]), to_jsonb(repeat('f',64))
                            )::text,'UTF8')))))
                    FROM report_input_premium_dependencies d
                    JOIN report_input_snapshots i ON i.id=d.input_id
                    WHERE i.id=:input
                """),
                    {"path": "{document,premium_binding," + leaf + "}", "input": job.input_id},
                )
                assert valid is False
        status = await complete_report(case, service, pending)
        report = await download_v4(service, case.principal, original.account_id, status)
    assert set(PROJECTION_TABLE_COLUMNS) <= set(report.tables)
    pin = report.manifest.document.premium_binding
    assert (
        pin.capture_digest,
        pin.numerical_input_digest,
        pin.result_digest,
        pin.input_id,
        pin.result_id,
    ) == (
        saved.capture_digest,
        saved.numerical_digest,
        saved.result_digest,
        saved.input_id,
        saved.result_id,
    )
    assert pin.observed is None and pin.source_cutoff_at is None
    assert (
        pin.report_context.snapshot_id == selected.snapshot_id
        and pin.report_context.source_cutoff_at == selected.source_cutoff_at
    )
    assert len(saved.value.variants) == (3 if goal else 1)
    financial_parity(report, saved.value, calendar)
    assert "not observed" in report.pdf_text and "not supplied" in report.pdf_text
    with no_private_reads(case):
        for version in (1, 2, 3):
            with pytest.raises(app.ReportServiceError) as wrong_profile:
                await report_service(case, version).get_report_status(
                    case.principal, original.account_id, status.job_id
                )
            assert wrong_profile.value.code is app.ReportServiceErrorCode.NOT_FOUND
        for identifier in (uuid4(), selected.snapshot_id):
            bad = replace(
                request,
                idempotency_key=str(uuid4()),
                selection=replace(
                    selected, premium_run=ReportProjectionRunSelection(run_id=identifier)
                ),
            )
            with pytest.raises(app.ReportServiceError):
                await service.generate_report(case.principal, bad)
        with pytest.raises(app.ReportServiceError):
            await service.generate_report(
                case.principal,
                replace(
                    request,
                    idempotency_key=str(uuid4()),
                    selection=replace(selected, reporting_currency=CurrencyCode("USD")),
                ),
            )
        foreign = replace(case.principal, owner_id=str(uuid4()))
        with pytest.raises(app.ReportServiceError):
            await service.get_report_manifest(foreign, original.account_id, status.job_id)
    assert saved_projection(case) == saved
