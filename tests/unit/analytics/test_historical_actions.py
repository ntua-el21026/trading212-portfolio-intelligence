"""Independent split-unit and event-partition references, not engine-derived oracles."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from trading212_analytics.historical import (
    calculate_attribution,
    calculate_benchmark_comparison,
    calculate_performance,
    verify_historical_result,
)
from trading212_domain import Money, QualityState
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.historical_serialization import historical_result_digest
from trading212_domain.source_details import CorporateActionKind, CorporateActionObservation
from trading212_domain.sources import (
    ObservationState,
    SourceCoverage,
    SourceGap,
    SourceReason,
    source_snapshot_digest,
)

from .historical_factories import (
    START,
    fixture,
    identity,
    metric,
    source_ref,
    with_benchmark,
    with_events,
)
from .source_factories import EUR, uid

pytestmark = pytest.mark.unit


def split_input() -> d.HistoricalInput:
    value = fixture(("10", "10", "5", "6"))
    original = value.action_snapshots[0]
    action = CorporateActionObservation(
        source_key="split-one",
        session_date=(START + timedelta(days=1)).date(),
        effective_at=START + timedelta(days=1),
        kind=CorporateActionKind.SPLIT,
        state=ObservationState.AVAILABLE,
        ratio=Decimal(2),
        source_revision="action-v1",
    )
    snapshot = replace(
        original,
        observations=(action,),
        coverage=SourceCoverage(
            expected_count=1, available_count=1, gaps=(), quality=QualityState.FRESH
        ),
    )
    return replace(
        value,
        action_snapshots=(snapshot,),
        sources=tuple(
            replace(item, semantic_digest=source_snapshot_digest(snapshot))
            if item.id == snapshot.id
            else item
            for item in value.sources
        ),
    )


def test_source_split_reconstructs_once_and_conserves_cost_wealth_and_attribution() -> None:
    value = split_input()
    result = calculate_performance(
        value, options=r.PerformanceOptions(frequency=d.HistoricalFrequency.DAILY)
    )
    assert (
        result.summary.beginning_value.value and result.summary.beginning_value.value.amount == 10
    )
    assert result.summary.ending_value.value and result.summary.ending_value.value.amount == 12
    assert (
        result.summary.unrealized_profit_loss.value
        and result.summary.unrealized_profit_loss.value.amount == 2
    )
    assert result.summary.time_weighted_return.value == Decimal(".2")
    assert result.summary.maximum_drawdown.value == 0
    assert [
        point.portfolio_value.value.amount for point in result.points if point.portfolio_value.value
    ] == [10, 10, 12]
    bridge = calculate_attribution(value, options=r.AttributionOptions())
    assert bridge.summary.investment_gain.value and bridge.summary.investment_gain.value.amount == 2
    assert (
        bridge.summary.attributed_amount.value
        and bridge.summary.attributed_amount.value.amount == 2
    )
    assert bridge.summary.residual.value and bridge.summary.residual.value.amount == 0
    assert bridge.summary.attributed_return.value == Decimal(".2")
    assert next(
        effect for effect in bridge.effects if effect.kind == "price"
    ).amount.value == Money(Decimal(2), EUR)
    assert any(
        isinstance(use, r.HistoricalObservationUse) and use.source_kind == "corporate_action"
        for use in bridge.source_uses
    )
    verify_historical_result(value, bridge)
    corroboration = d.HistoricalCorporateAction(
        identity=identity(110, START + timedelta(days=1)),
        snapshot_id=value.action_snapshots[0].id,
        observation_index=0,
        account_effect_evidence=(uid(110),),
    )
    corroborated = calculate_performance(
        with_events(value, corroboration), options=r.PerformanceOptions()
    )
    assert corroborated.summary == result.summary


def test_missing_action_absence_proof_gates_quantity_and_cost_but_not_known_cash() -> None:
    value = replace(fixture(cash="5"), action_snapshots=())
    result = calculate_performance(value, options=r.PerformanceOptions())
    assert result.summary.ending_value.value is None
    assert result.summary.unrealized_profit_loss.value is None
    assert all(point.cash_value.value == Money(Decimal(5), EUR) for point in result.points)
    assert any(
        warning.reason_code is d.HistoricalReason.ACTION_COVERAGE
        for warning in result.context.warnings
    )
    assert not result.context.coverage.complete(d.HistoricalCoverageKey.ACTIONS)


def test_unsupported_source_spinoff_gates_quantity_without_inventing_target_holding() -> None:
    value = split_input()
    snapshot = value.action_snapshots[0]
    snapshot = replace(
        snapshot,
        observations=(
            replace(
                snapshot.observations[0],
                kind=CorporateActionKind.SPINOFF,
                target_instrument_id=uid(999),
            ),
        ),
    )
    result = calculate_performance(
        replace(value, action_snapshots=(snapshot,)), options=r.PerformanceOptions()
    )
    assert result.summary.ending_value.value is None
    assert any(
        warning.reason_code is d.HistoricalReason.ACTION_UNSUPPORTED
        for warning in result.context.warnings
    )


def test_cash_only_internal_effects_have_cash_partition_and_exact_linked_return() -> None:
    value = fixture(("1",) * 4, quantity="0", cash="100")
    value = with_events(
        value,
        d.HistoricalCashEffect(
            identity=identity(100, START + timedelta(days=1)),
            effect_kind="interest",
            signed_amount=Money(Decimal(5), EUR),
        ),
        d.HistoricalCashEffect(
            identity=identity(101, START + timedelta(days=1)),
            effect_kind="fee",
            signed_amount=Money(Decimal(-2), EUR),
        ),
    )
    result = calculate_attribution(value, options=r.AttributionOptions())
    assert result.summary.investment_gain.value == Money(Decimal(3), EUR)
    assert result.summary.attributed_amount.value == Money(Decimal(3), EUR)
    assert result.summary.attributed_return.value == Decimal(".03")
    assert result.summary.residual.value == Money(Decimal(0), EUR)
    assert [row.key for row in result.rows] == ["cash:EUR"]
    assert {item.kind: item.amount.value.amount for item in result.effects if item.amount.value}[
        "income"
    ] == 5
    assert {item.kind: item.amount.value.amount for item in result.effects if item.amount.value}[
        "fees"
    ] == -2


def test_dividend_partition_uses_its_holding_not_last_reconstructed_holding() -> None:
    value = fixture(("100",) * 4)
    assert isinstance(value.opening, d.ObservedHistoricalOpening)
    second_series = replace(
        value.price_snapshots[0].series,
        id=uid(11),
        listing_id=uid(10),
        instrument_id=uid(8),
        mapping_id=uid(12),
    )
    second_price = replace(value.price_snapshots[0], id=uid(22), series=second_series)
    second_actions = replace(value.action_snapshots[0], id=uid(23), series=second_series)
    anchor = value.opening.anchor
    value = replace(
        value,
        instruments=(
            *value.instruments,
            replace(
                value.instruments[0],
                listing_id=uid(10),
                instrument_id=uid(8),
                source_series_ids=(uid(11),),
            ),
        ),
        opening=replace(
            value.opening,
            anchor=replace(
                anchor,
                positions=(
                    *anchor.positions,
                    replace(anchor.positions[0], listing_id=uid(10), instrument_id=uid(8)),
                ),
            ),
        ),
        mapping_evidence=(
            *value.mapping_evidence,
            replace(
                value.mapping_evidence[0],
                id=uid(12),
                source_ref=uid(12),
                listing_id=uid(10),
                instrument_id=uid(8),
            ),
        ),
        price_snapshots=(*value.price_snapshots, second_price),
        action_snapshots=(*value.action_snapshots, second_actions),
        sources=(
            *value.sources,
            source_ref(12),
            d.HistoricalSourceReference(
                kind="corporate_action_snapshot",
                id=second_actions.id,
                effective_at=second_actions.provenance.effective_at,
                first_observed_at=second_actions.provenance.first_observed_at,
                semantic_digest=source_snapshot_digest(second_actions),
            ),
        ),
    )
    value = with_events(
        value,
        d.HistoricalDividend(
            identity=identity(100, START),
            dividend_key="first-holding-income",
            instrument_id=uid(6),
            listing_id=uid(7),
            net=Money(Decimal(4), EUR),
            gross=metric("5"),
            withholding=metric("1"),
            payment_convention="exact_provider_instant",
        ),
    )
    result = calculate_attribution(value, options=r.AttributionOptions())
    rows = {row.listing_id: row for row in result.rows if row.listing_id}
    assert rows[uid(7)].amount.value == Money(Decimal(4), EUR)
    assert rows[uid(10)].amount.value == Money(Decimal(0), EUR)
    assert result.summary.residual.value == Money(Decimal(0), EUR)


def test_cash_drag_obeys_twr_and_modified_dietz_denominators() -> None:
    value = with_benchmark(
        fixture(("100", "110", "121"), cash="100"), ("100", "110", "121"), ("100", "110", "121")
    )
    assert isinstance(value.opening, d.ObservedHistoricalOpening)
    at = START + timedelta(days=1)
    deposit = d.HistoricalExternalFlow(
        identity=identity(100, at),
        kind="deposit",
        scope_proof="account_boundary",
        signed_amount=Money(Decimal(100), EUR),
    )
    anchor = replace(
        value.opening.anchor,
        id=uid(55),
        at=at,
        timing="after_events",
        positions=(replace(value.opening.anchor.positions[0], market_value=metric("110")),),
        cash=(Money(Decimal(200), EUR),),
    )
    value = replace(with_events(value, deposit), valuation_anchors=(anchor,))
    twr = calculate_attribution(value, options=r.AttributionOptions())
    dietz = calculate_attribution(
        value, options=r.AttributionOptions(method=d.AttributionMethod.MODIFIED_DIETZ)
    )
    assert twr.summary.cash_drag.value == Decimal("-.116290322580645161")
    assert dietz.summary.dietz_denominator.value == Money(Decimal(250), EUR)
    assert dietz.summary.cash_drag.value == Decimal("-.12")


def test_missing_fx_decomposition_retains_partial_subtotals_and_uncovered_residual() -> None:
    from .source_factories import USD

    value = fixture(("10", "12"), quantity="2", currency=USD)
    assert isinstance(value.opening, d.ObservedHistoricalOpening)
    anchors = tuple(
        replace(
            value.opening.anchor,
            id=uid(52 + index),
            at=at,
            timing="before_events",
            positions=(replace(value.opening.anchor.positions[0], market_value=metric(amount)),),
        )
        for index, (at, amount) in enumerate(
            ((value.selection.window.start_at, "20"), (value.selection.window.end_at, "24"))
        )
    )
    result = calculate_attribution(
        replace(value, valuation_anchors=anchors), options=r.AttributionOptions()
    )
    assert result.summary.investment_gain.value == Money(Decimal(4), EUR)
    assert result.summary.uncovered_residual.value == Money(Decimal(4), EUR)
    for effect in result.effects:
        if effect.kind in ("price", "fx", "interaction"):
            assert effect.amount.availability is d.MetricAvailability.PARTIAL
            assert effect.amount.quality is QualityState.PARTIAL
            assert effect.amount.reason_code is d.HistoricalReason.PARTIAL_COVERAGE


def test_action_gap_and_late_point_in_time_receipt_are_not_absence_proof() -> None:
    from .historical_factories import point_in_time

    value = point_in_time(fixture())
    missing_day = value.action_snapshots[1]
    missing = replace(
        value,
        action_snapshots=tuple(
            item for item in value.action_snapshots if item.id != missing_day.id
        ),
    )
    result = calculate_performance(missing, options=r.PerformanceOptions())
    assert result.summary.ending_value.value is None
    assert not result.context.coverage.complete(d.HistoricalCoverageKey.ACTIONS)
    late = replace(
        value,
        action_snapshots=tuple(
            replace(
                item,
                provenance=replace(
                    item.provenance, first_observed_at=value.selection.window.source_cutoff_at
                ),
            )
            for item in value.action_snapshots
        ),
    )
    result = calculate_performance(late, options=r.PerformanceOptions())
    assert result.summary.beginning_value.value is None


def test_explicit_reference_correction_replaces_prior_split_without_double_application() -> None:
    value = split_input()
    snapshot = value.action_snapshots[0]
    old = replace(snapshot.observations[0], ratio=Decimal(3))
    corrected = replace(
        snapshot.observations[0],
        source_key="split-corrected",
        correction_source_key=old.source_key,
        source_revision="action-v2",
    )
    snapshot = replace(
        snapshot,
        observations=(old, corrected),
        coverage=SourceCoverage(
            expected_count=2, available_count=2, gaps=(), quality=QualityState.FRESH
        ),
    )
    result = calculate_performance(
        replace(value, action_snapshots=(snapshot,)), options=r.PerformanceOptions()
    )
    assert result.summary.ending_value.value == Money(Decimal(12), EUR)
    assert result.summary.time_weighted_return.value == Decimal(".2")


def test_conflicting_known_income_components_preserve_net_without_false_reconciliation() -> None:
    from trading212_analytics.historical import calculate_income

    event = d.HistoricalDividend(
        identity=identity(100, START),
        dividend_key="unreconciled-income",
        instrument_id=uid(6),
        listing_id=uid(7),
        net=Money(Decimal(4), EUR),
        gross=metric("7"),
        withholding=metric("1"),
        payment_convention="exact_provider_instant",
    )
    value = with_events(fixture(("100",) * 4), event)
    income = calculate_income(value, options=r.IncomeOptions())
    assert income.summary.net_income.value == Money(Decimal(4), EUR)
    assert income.summary.gross_income.value is None
    assert income.summary.withholding.value is None
    attribution = calculate_attribution(value, options=r.AttributionOptions())
    assert attribution.summary.investment_gain.value == Money(Decimal(4), EUR)
    assert next(
        item for item in attribution.effects if item.kind == "income"
    ).amount.value == Money(Decimal(4), EUR)
    assert (
        next(item for item in attribution.effects if item.kind == "taxes").amount.availability
        is d.MetricAvailability.PARTIAL
    )
    performance = calculate_performance(value, options=r.PerformanceOptions())
    assert performance.summary.withholding_taxes.value is None


@pytest.mark.parametrize("ordered", [False, True])
def test_action_candidate_fast_path_preserves_revision_and_conflict_rules(ordered: bool) -> None:
    from trading212_analytics._historical_actions import _choose

    original = split_input().action_snapshots[0]
    original = replace(
        original,
        provenance=replace(original.provenance, revision_order=1 if ordered else None),
    )
    day = original.observations[0].session_date
    revised = replace(
        original,
        id=uid(901),
        provenance=replace(
            original.provenance,
            first_observed_at=original.provenance.first_observed_at + timedelta(hours=1),
            revision_order=2 if ordered else None,
        ),
        observations=(replace(original.observations[0], ratio=Decimal(3)),),
    )
    assert _choose((original,), day) is original
    assert _choose((original,), original.period.end + timedelta(days=1)) is None
    assert _choose((original, revised), day) is (revised if ordered else None)
    # Reordering input cannot turn receipt recency into authority.
    assert _choose((revised, original), day) is (revised if ordered else None)


def test_equal_overlapping_action_proofs_keep_earliest_receipt_and_quality_conflicts() -> None:
    from trading212_analytics._historical_actions import _choose

    original = split_input().action_snapshots[0]
    original = replace(original, provenance=replace(original.provenance, revision_order=None))
    later = replace(
        original,
        id=uid(902),
        provenance=replace(
            original.provenance,
            first_observed_at=original.provenance.first_observed_at + timedelta(hours=1),
        ),
    )
    day = original.observations[0].session_date
    assert _choose((later, original), day) is original
    partial = replace(later, coverage=replace(later.coverage, quality=QualityState.PARTIAL))
    assert _choose((original, partial), day) is None


@pytest.mark.parametrize(
    ("boundary", "offset", "included"),
    [
        ("start", -1, False),
        ("start", 0, True),
        ("start", 1, True),
        ("end", -1, True),
        ("end", 0, True),
        ("end", 1, False),
    ],
)
def test_original_singleton_preserves_inclusive_period_and_empty_selection(
    boundary: str, offset: int, included: bool
) -> None:
    from trading212_analytics._historical_actions import _choose

    snapshot = split_input().action_snapshots[0]
    day = (snapshot.period.start if boundary == "start" else snapshot.period.end) + timedelta(
        days=offset
    )
    assert _choose((snapshot,), day) is (snapshot if included else None)
    assert _choose((), day) is None


@pytest.mark.parametrize("late_field", [None, "first_observed_at", "effective_at"])
def test_original_singleton_is_selected_only_after_both_cutoff_checks(
    late_field: str | None,
) -> None:
    from trading212_analytics._historical_actions import select_actions

    value = split_input()
    original = value.action_snapshots[0]
    cutoff = value.selection.window.source_cutoff_at
    snapshot = replace(
        original,
        provenance=replace(
            original.provenance,
            first_observed_at=cutoff
            + timedelta(microseconds=1 if late_field == "first_observed_at" else 0),
            effective_at=cutoff + timedelta(microseconds=1 if late_field == "effective_at" else 0),
        ),
    )
    assert snapshot.series.listing_id is not None
    selected = select_actions(
        replace(value, action_snapshots=(snapshot,)),
        listing_ids=frozenset((snapshot.series.listing_id,)),
        start=value.selection.window.start_at,
        through=value.selection.window.end_at,
        cutoff=cutoff,
    )
    assert selected.complete is (late_field is None)
    assert selected.observations == (((snapshot, 0),) if late_field is None else ())
    assert selected.coverage_snapshots == ((snapshot,) if late_field is None else ())


@pytest.mark.parametrize("ordered", [False, True])
def test_multiple_action_snapshots_preserve_revised_gaps_and_input_order(ordered: bool) -> None:
    from trading212_analytics._historical_actions import _choose, select_actions

    value = split_input()
    original = value.action_snapshots[0]
    original = replace(
        original, provenance=replace(original.provenance, revision_order=1 if ordered else None)
    )
    day = original.observations[0].session_date
    gap = replace(
        original,
        id=uid(903),
        provenance=replace(original.provenance, revision_order=2 if ordered else None),
        observations=(),
        coverage=SourceCoverage(
            expected_count=1,
            available_count=0,
            gaps=(SourceGap(session_date=day, reason=SourceReason.MISSING_SESSION),),
            quality=QualityState.PARTIAL,
        ),
    )
    assert original.series.listing_id is not None
    for snapshots in ((original, gap), (gap, original)):
        assert _choose(snapshots, day) is (gap if ordered else None)
        selected = select_actions(
            replace(value, action_snapshots=snapshots),
            listing_ids=frozenset((original.series.listing_id,)),
            start=value.selection.window.start_at,
            through=value.selection.window.end_at,
            cutoff=value.selection.window.source_cutoff_at,
        )
        assert not selected.complete
        assert selected.observations == ()
        assert selected.coverage_snapshots == ((gap,) if ordered else ())


# Full canonical hashes captured from a573343 before the original-singleton change.
# These cover context, selected uses, conversions and primitive inventory as well as values.
@pytest.mark.parametrize(
    ("family", "frequency", "expected"),
    [
        (
            "performance",
            d.HistoricalFrequency.DAILY,
            "e1d9b2efb07731a3ac1783264b453b7d0407f8b45fb83b7f260d1a70ced8a7f8",
        ),
        (
            "performance",
            d.HistoricalFrequency.MONTHLY,
            "bdcfb9154b5e74ab27f7c1e1ba490d3eccb72d04ed4b0f2b40794c018b4b994c",
        ),
        (
            "benchmark",
            d.HistoricalFrequency.DAILY,
            "e691064f5468e2e4c6abb0683f6faaf96a7f1c2c9702184d897a2cbd9cd1586b",
        ),
        (
            "benchmark",
            d.HistoricalFrequency.MONTHLY,
            "b5f3f244e01bfde18712884dfd7877794be6b04fb613e20e78c87478ca2f6b74",
        ),
        (
            "attribution",
            d.HistoricalFrequency.DAILY,
            "ec472c3f5e59fef2181863f5161ffbd57d346c662e51eb42515c383b668bfc85",
        ),
    ],
)
def test_original_singleton_preserves_full_historical_canonical_result(
    family: str, frequency: d.HistoricalFrequency, expected: str
) -> None:
    value = with_benchmark(split_input(), ("10", "11", "12", "13"), ("10", "9", "8", "7"))
    assert len(value.action_snapshots) == 1
    if family == "performance":
        result: r.HistoricalCalculation = calculate_performance(
            value, options=r.PerformanceOptions(frequency=frequency)
        )
    elif family == "benchmark":
        result = calculate_benchmark_comparison(
            value,
            options=r.ComparisonOptions(frequency=frequency, calendar_period=d.CalendarPeriod.YEAR),
        )
    else:
        assert family == "attribution"
        result = calculate_attribution(value, options=r.AttributionOptions())
    verify_historical_result(value, result)
    assert historical_result_digest(result) == expected
