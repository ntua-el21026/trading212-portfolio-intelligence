"""Independent split-unit and event-partition references, not engine-derived oracles."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from trading212_analytics.historical import (
    calculate_attribution,
    calculate_performance,
    verify_historical_result,
)
from trading212_domain import Money, QualityState
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.source_details import CorporateActionKind, CorporateActionObservation
from trading212_domain.sources import ObservationState, SourceCoverage, source_snapshot_digest

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
