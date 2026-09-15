"""Retained population, row identity, byte and goal projection regressions."""

from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Context, Decimal, Inexact, Rounded, localcontext
from hashlib import sha256
from typing import Any
from uuid import UUID

import pytest
from trading212_application import projection_presentation as p
from trading212_application import projection_views as v
from trading212_application.projection import ProjectionErrorCode, ProjectionServiceError
from trading212_application.risk import PremiumJobState
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.projection_serialization import projection_canonical_bytes
from trading212_domain.serialization import canonical_json
from trading212_domain.values import Money

from tests.unit.application.projection_presentation_factories import GOAL, retained

D = Decimal
pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def saved() -> p.RetainedProjectionPresentation:
    return retained()


def page(
    saved: p.RetainedProjectionPresentation, *, offset: int = 0, limit: int = 25
) -> v.ProjectionResultPage:
    selected = p.select_projection_page(saved, offset=offset, limit=limit)
    cursor = f"signed_{selected.next_ordinal}" if selected.next_ordinal is not None else None
    return p.finalize_projection_page(selected, next_cursor=cursor)


def test_all_saved_rows_are_accessible_in_canonical_order_without_recalculation(
    saved: p.RetainedProjectionPresentation, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("The saved presenter must not sample paths.")

    monkeypatch.setattr("trading212_analytics.projection.calculate_projection", forbidden)
    monkeypatch.setattr("trading212_analytics.projection.calculate_projection_chunk", forbidden)
    original = projection_canonical_bytes(saved.calculation)
    rows: list[v.ProjectionPointRow] = []
    summaries = None
    while len(rows) < 84:
        result = page(saved, offset=len(rows), limit=5)
        assert result.points.total == 84
        assert result.points.point_limit == 5
        assert (result.points.next_cursor is not None) == (
            len(rows) + len(result.points.items) < 84
        )
        if summaries is not None:
            assert result.variants == summaries
        summaries = result.variants
        rows.extend(result.points.items)
    for ordinal, row in enumerate(rows):
        variant_index, rest = divmod(ordinal, 28)
        path_index, point_index = divmod(rest, 4)
        variant = saved.calculation.variants[variant_index]
        path = variant.paths[path_index]
        point = path.points[point_index]
        assert (row.ordinal, row.variant, row.path_index, row.point_index) == (
            ordinal,
            variant.variant,
            path_index,
            point_index,
        )
        assert row.path_point_count == 4 and row.first_unpaid_month == path.first_unpaid_month
        assert row.on == saved.capture.calendar.boundaries[point.month]
        for field in fields(point):
            actual, expected = getattr(row.point, field.name), getattr(point, field.name)
            if isinstance(actual, Money):
                assert actual.amount == expected and actual.currency == path.reporting_currency
            elif field.name == "assets":
                assert [(item.key, item.value.amount, item.value.currency) for item in actual] == [
                    (item.key, item.value, path.reporting_currency) for item in expected
                ]
            else:
                assert actual == expected
    assert projection_canonical_bytes(saved.calculation) == original


def test_cash_flow_summaries_use_every_terminal_path_even_on_initial_single_row_page(
    saved: p.RetainedProjectionPresentation,
) -> None:
    result = page(saved, limit=1)
    assert result.points.items[0].point.month == 0
    for summary, variant in zip(result.variants, saved.calculation.variants, strict=True):
        for name in (
            "contributions",
            "withdrawals_requested",
            "withdrawals_funded",
            "unpaid_withdrawals",
            "investment_effect",
            "fees",
            "tax_drag",
        ):
            values = sorted(getattr(path.points[-1], name) for path in variant.paths)
            with localcontext(Context(prec=120, rounding=ROUND_HALF_EVEN)):
                expected_mean = (sum(values, D(0)) / D(7)).quantize(D("1e-18"))
            amount = getattr(summary.cash_flows, name)
            assert amount.mean.amount == expected_mean
            assert tuple(item.amount for item in amount.quantiles.values) == tuple(
                values[index] for index in (0, 1, 3, 5, 6)
            )
        assert summary.cash_flows.contributions.mean.amount > 0
        assert (
            summary.nominal_histogram.observed_minimum.amount
            == variant.nominal_histogram.observed_minimum
        )
        assert [
            (item.lower.amount, item.upper.amount, item.count, item.upper_inclusive)
            for item in summary.real_histogram.bins
        ] == [
            (item.lower, item.upper, item.count, item.upper_inclusive)
            for item in variant.real_histogram.bins
        ]
        assert len(summary.distributions) == 4
        assert tuple(item.nominal_mean.amount for item in summary.distributions) == tuple(
            item.nominal_mean for item in variant.distributions
        )


def test_signed_effect_and_hostile_decimal_context_preserve_exact_saved_summary() -> None:
    saved = retained(loss_only=True)
    expected = page(saved)
    assert all(item.cash_flows.investment_effect.mean.amount < 0 for item in expected.variants)
    with localcontext(
        Context(prec=2, rounding=ROUND_DOWN, Emin=-2, Emax=2, traps=[Inexact, Rounded])
    ):
        assert p.projection_public_bytes(page(saved)) == p.projection_public_bytes(expected)


def test_unpaid_below_quantum_remains_a_failed_funding_path() -> None:
    saved = retained(tiny_unpaid=True, sensitive=False)
    result = page(saved, offset=3, limit=1)
    terminal = result.points.items[0].point
    assert terminal.funding_failed and terminal.unpaid_positive_below_quantum
    assert terminal.unpaid_withdrawals.amount == 0
    assert result.variants[0].cash_flows.funding_failed_paths == 7
    assert result.variants[0].cash_flows.unpaid_positive_below_quantum_paths == 7
    assert result.points.items[0].first_unpaid_month == 2
    assert "unpaid_positive_below_quantum" in result.context.warnings.items


def test_full_evidence_quality_precedes_bounded_preview_and_preserves_original_clocks() -> None:
    saved = retained(source_count=20)
    hidden = replace(saved.source_evidence[-2], quality=QualityState.PARTIAL)
    saved = replace(
        saved, source_evidence=(*saved.source_evidence[:-2], hidden, saved.source_evidence[-1])
    )
    result = page(saved)
    assert result.context.quality is QualityState.PARTIAL
    assert all(item.quality is QualityState.FRESH for item in result.context.source_evidence.items)
    assert len(result.context.source_evidence.items) == 16
    assert result.context.source_evidence.omitted_count == 5
    assert all(
        item.source_reference_ids.omitted_count == 4
        for item in result.context.source_evidence.items
    )
    assert "source_partial" in result.context.warnings.items
    assert result.context.source_cutoff_at == saved.source_cutoff_at
    assert result.context.calculated_at == saved.calculated_at
    assert result.context.snapshot_valuation_at == datetime(
        2025, 1, 31, 23, 17, 21, 123456, tzinfo=UTC
    )
    assert result.points.items[1].on == date(2025, 2, 28)
    assert result.points.items[2].on == date(2025, 3, 31)


@pytest.mark.parametrize(
    "field,value",
    [
        ("capture_digest", "0" * 64),
        ("saved_result_digest", "0" * 64),
        ("account_id", UUID(int=999)),
    ],
)
def test_cross_record_identity_mismatch_fails_before_projection(
    saved: p.RetainedProjectionPresentation, field: str, value: Any
) -> None:
    with pytest.raises(ProjectionServiceError) as caught:
        replace(saved, **{field: value})
    assert caught.value.code is ProjectionErrorCode.PROJECTION_UNAVAILABLE


def test_missing_duplicate_or_mismatched_evidence_is_rejected(
    saved: p.RetainedProjectionPresentation,
) -> None:
    for evidence in (
        saved.source_evidence[:-1],
        (*saved.source_evidence, saved.source_evidence[0]),
        (replace(saved.source_evidence[0], content_digest="e" * 64), *saved.source_evidence[1:]),
    ):
        with pytest.raises(ProjectionServiceError):
            replace(saved, source_evidence=evidence)
    with pytest.raises(ProjectionServiceError):
        replace(saved, source_cutoff_at=saved.calculated_at + timedelta(seconds=1))


def test_page_digest_covers_actual_cursor_and_is_distinct_from_saved_digests(
    saved: p.RetainedProjectionPresentation,
) -> None:
    selection = p.select_projection_page(saved, limit=1)
    result = p.finalize_projection_page(selection, next_cursor="one")
    another = p.finalize_projection_page(selection, next_cursor="two")
    assert result.content_digest != another.content_digest
    content = {
        item.name: getattr(result, item.name)
        for item in fields(result)
        if item.name != "content_digest"
    }
    assert (
        result.content_digest
        == sha256(b"t212pi.projection.public.v1\0" + canonical_json(content).encode()).hexdigest()
    )
    assert (
        len(
            {
                result.content_digest,
                saved.saved_result_digest,
                saved.capture_digest,
                saved.calculation.input_digest,
            }
        )
        == 4
    )


@pytest.mark.parametrize("cursor", [None, "", "x" * 2049, "π", 'quote"', "slash\\", "has space"])
def test_finalizer_rejects_missing_oversized_or_non_urlsafe_cursors(
    saved: p.RetainedProjectionPresentation, cursor: str | None
) -> None:
    with pytest.raises(DomainError):
        p.finalize_projection_page(p.select_projection_page(saved, limit=1), next_cursor=cursor)


def test_byte_bound_shortens_only_complete_rows_and_preserves_requested_limit(
    saved: p.RetainedProjectionPresentation, monkeypatch: pytest.MonkeyPatch
) -> None:
    one = p.select_projection_page(saved, limit=1)
    one = replace(one, point_limit=25)
    maximum_cursor = "x" * 2048
    full_one = p.finalize_projection_page(one, next_cursor=maximum_cursor)
    monkeypatch.setattr(v, "PROJECTION_PUBLIC_PAGE_BYTES", len(p.projection_public_bytes(full_one)))
    selected = p.select_projection_page(saved, limit=25)
    assert len(selected.items) == 1 and selected.next_ordinal == 1 and selected.point_limit == 25
    actual = p.finalize_projection_page(selected, next_cursor=maximum_cursor)
    assert len(p.projection_public_bytes(actual)) == v.PROJECTION_PUBLIC_PAGE_BYTES
    monkeypatch.setattr(v, "PROJECTION_PUBLIC_PAGE_BYTES", v.PROJECTION_PUBLIC_PAGE_BYTES - 1)
    with pytest.raises(ProjectionServiceError) as caught:
        p.select_projection_page(saved, limit=25)
    assert caught.value.code is ProjectionErrorCode.INPUT_BOUND_EXCEEDED


def test_common_context_and_actual_utf8_page_and_outer_envelope_bounds(
    saved: p.RetainedProjectionPresentation, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = p.select_projection_page(saved, limit=1)
    # The final byte guard still rejects an oversized internal record; transport
    # DTO validation independently rejects this non-contract warning text.
    oversized_context = replace(
        selected.context, warnings=v.ProjectionPreview(items=("π" * (1024 * 512),), omitted_count=0)
    )
    with pytest.raises(ProjectionServiceError):
        p.finalize_projection_page(replace(selected, context=oversized_context), next_cursor="next")
    p.validate_projection_response_bytes(b"x" * (2 * 1024 * 1024))
    with pytest.raises(ProjectionServiceError):
        p.validate_projection_response_bytes(("π" * (1024 * 1024) + "x").encode())
    monkeypatch.setattr(v, "PROJECTION_PUBLIC_PAGE_BYTES", 1)
    with pytest.raises(ProjectionServiceError):
        p.select_projection_page(saved)


@pytest.mark.parametrize("offset,limit", [(-1, 1), (84, 1), (True, 1), (0, 0), (0, 101), (0, True)])
def test_invalid_page_boundaries_are_rejected(
    saved: p.RetainedProjectionPresentation, offset: int, limit: int
) -> None:
    with pytest.raises(DomainError):
        p.select_projection_page(saved, offset=offset, limit=limit)


@pytest.mark.parametrize("basis", ["nominal", "real"])
def test_goal_analysis_copies_all_saved_estimates_in_pinned_basis(basis: Any) -> None:
    saved = retained(basis=basis)
    result = p.project_goal_analysis(saved)
    assert result.availability == "available" and result.context is not None
    assert len(result.variants) == 3
    for item, variant in zip(result.variants, saved.calculation.variants, strict=True):
        assert variant.goal is not None
        assert (
            tuple(money.amount for money in item.terminal.values)
            == getattr(variant.distributions[-1], basis).values
        )
        assert item.estimate.probability == variant.goal.probability
        assert (item.estimate.interval_low, item.estimate.interval_high) == (
            variant.goal.interval_low,
            variant.goal.interval_high,
        )
        assert item.estimate.successes == variant.goal.successes
        assert item.estimate.automatic_goal_acceptance is False
    assert result.context.saved_result_digest == saved.saved_result_digest


def test_modeled_no_goal_requires_no_observed_source_and_has_explicit_unavailable_reason() -> None:
    saved = retained(goal=False, observed=False, source_count=0, sensitive=False)
    result = p.project_goal_analysis(saved)
    assert result.reason == "no_goal_pinned" and result.availability == "unavailable"
    assert result.state is PremiumJobState.SUCCEEDED and result.result_availability == "available"
    assert result.context is None and result.variants == ()
    ordinary = page(saved)
    assert (
        ordinary.context.snapshot_valuation_at is None and ordinary.context.source_cutoff_at is None
    )


@pytest.mark.parametrize(
    "state,availability,reason",
    [
        (PremiumJobState.QUEUED, "pending", "run_pending"),
        (PremiumJobState.RUNNING, "pending", "run_pending"),
        (PremiumJobState.FAILED, "unavailable", "run_failed"),
        (PremiumJobState.CANCELLED, "unavailable", "run_cancelled"),
        (PremiumJobState.SUCCEEDED, "expired", "run_expired"),
        (PremiumJobState.EXPIRED, "expired", "run_expired"),
    ],
)
def test_goal_unavailability_preserves_actual_job_and_retention_states(
    saved: p.RetainedProjectionPresentation, state: PremiumJobState, availability: Any, reason: str
) -> None:
    run = v.ProjectionOperationalRunView(
        id=saved.run_id,
        account_id=saved.account_id,
        assumption_version_id=saved.capture.selection.assumption_version_id,
        goal_version_id=GOAL,
        job_id=UUID(int=200),
        capture_digest=saved.capture_digest,
        numerical_input_digest=saved.calculation.input_digest,
        state=state,
        result_availability=availability,
        created_at=saved.calculated_at,
        expires_at=saved.calculated_at + timedelta(days=1),
        completed_at=None,
        failure_code=None,
    )
    result = p.unavailable_goal_analysis(run)
    assert result.state is state and result.result_availability == availability
    assert result.reason == reason and result.context is None and result.variants == ()


def test_final_page_does_not_reserve_a_nonexistent_continuation_cursor(
    saved: p.RetainedProjectionPresentation, monkeypatch: pytest.MonkeyPatch
) -> None:
    final = page(saved, offset=83, limit=25)
    monkeypatch.setattr(v, "PROJECTION_PUBLIC_PAGE_BYTES", len(p.projection_public_bytes(final)))
    assert page(saved, offset=83, limit=25) == final
    assert final.points.next_cursor is None
    with pytest.raises(DomainError):
        p.finalize_projection_page(p.select_projection_page(saved, offset=83), next_cursor="extra")


def test_generated_views_validate_against_frozen_exact_dtos(
    saved: p.RetainedProjectionPresentation,
) -> None:
    from trading212_api_contracts.projection_results import ProjectionResultPage
    from trading212_api_contracts.projections import GoalAnalysisResponse
    from trading212_domain.serialization import to_primitive

    result = page(saved, limit=1)
    dto = ProjectionResultPage.model_validate(to_primitive(result))
    assert (
        dto.points.total == 84
        and dto.points.items[0].point.nominal.amount == "100.123456789012345678"
    )
    analysis = GoalAnalysisResponse.model_validate(to_primitive(p.project_goal_analysis(saved)))
    assert len(analysis.variants) == 3 and analysis.availability == "available"


def test_goal_analysis_fails_when_its_complete_common_context_exceeds_budget(
    saved: p.RetainedProjectionPresentation, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis = p.project_goal_analysis(saved)
    monkeypatch.setattr(
        v, "PROJECTION_PUBLIC_PAGE_BYTES", len(p.projection_public_bytes(analysis)) - 1
    )
    with pytest.raises(ProjectionServiceError) as caught:
        p.project_goal_analysis(saved)
    assert caught.value.code is ProjectionErrorCode.INPUT_BOUND_EXCEEDED
