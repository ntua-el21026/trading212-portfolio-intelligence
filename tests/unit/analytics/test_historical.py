from dataclasses import replace
from decimal import Decimal

import pytest
from trading212_analytics.historical import calculate_performance, verify_historical_result
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.historical_serialization import (
    historical_canonical_bytes,
    historical_input_from_json,
    historical_result_from_json,
)

from .historical_factories import fixture

pytestmark = pytest.mark.unit


def test_fixed_history_growth_and_serialized_roundtrip() -> None:
    value = fixture()
    assert historical_input_from_json(historical_canonical_bytes(value)) == value
    result = calculate_performance(
        value, options=r.PerformanceOptions(frequency=d.HistoricalFrequency.DAILY)
    )
    assert result.summary.beginning_value.value is not None
    assert result.summary.beginning_value.value.amount == 100
    assert result.summary.ending_value.value is not None
    assert result.summary.ending_value.value.amount == 120
    assert result.summary.investment_gain.value is not None
    assert result.summary.investment_gain.value.amount == 20
    assert result.summary.time_weighted_return.value == Decimal(".2")
    assert result.summary.modified_dietz_return.value == Decimal(".2")
    assert (
        result.summary.annualized_time_weighted_return.reason_code
        is d.HistoricalReason.SHORT_PERIOD
    )
    assert [
        point.portfolio_value.value.amount for point in result.points if point.portfolio_value.value
    ] == [100, 110, 120]
    assert historical_result_from_json(historical_canonical_bytes(result)) == result
    verify_historical_result(value, result)


def test_missing_registered_policy_and_opening_produce_truthful_unavailable() -> None:
    value = fixture()
    value = replace(
        value,
        selection=replace(value.selection, source_policy=None, reporting_calendar_ref=None),
        opening=d.UnavailableHistoricalOpening(reasons=(d.HistoricalReason.OPENING_MISSING,)),
    )
    result = calculate_performance(value, options=r.PerformanceOptions())
    assert result.summary.ending_value.value is None
    assert result.context.source_policy_version is None


def test_dividend_native_reporting_unknown_tax_and_negative_correction() -> None:
    from trading212_analytics.historical import calculate_income
    from trading212_domain import Money

    from .historical_factories import START, identity, metric, with_events, with_fx
    from .source_factories import EUR, USD, uid

    value = with_fx(fixture(("1", "1", "1", "1"), quantity="1300"), (".9",) * 4, base=USD)
    events = (
        d.HistoricalDividend(
            identity=identity(100, START),
            dividend_key="eur",
            instrument_id=uid(6),
            listing_id=uid(7),
            net=Money(Decimal(30), EUR),
            gross=metric("36"),
            withholding=metric("6"),
            payment_convention="exact_provider_instant",
        ),
        d.HistoricalDividend(
            identity=identity(101, START),
            dividend_key="usd",
            instrument_id=uid(8),
            listing_id=None,
            net=Money(Decimal(5), USD),
            gross=metric("6", USD),
            withholding=metric("1", USD),
            payment_convention="exact_provider_instant",
        ),
        d.HistoricalDividend(
            identity=identity(102, START),
            dividend_key="correction",
            instrument_id=uid(6),
            listing_id=uid(7),
            net=Money(Decimal(-2), EUR),
            gross=metric("-2"),
            withholding=metric("0"),
            payment_convention="exact_provider_instant",
            correction_of=uid(100),
        ),
    )
    value = with_events(value, *events)
    result = calculate_income(value, options=r.IncomeOptions())
    assert result.summary.net_income.value and result.summary.net_income.value.amount == Decimal(
        "32.5"
    )
    assert (
        result.summary.gross_income.value
        and result.summary.gross_income.value.amount == Decimal("39.4")
    )
    assert result.summary.withholding.value and result.summary.withholding.value.amount == Decimal(
        "6.9"
    )
    assert result.summary.income_yield.value == Decimal(".025")
    assert [row.net.value.amount for row in result.native_currency_totals if row.net.value] == [
        28,
        5,
    ]
    assert result.instrument_rows[0].concentration.value == Decimal("0.869565217391304348")
    unknown = replace(
        value, event_candidates=(replace(events[0], withholding=metric(None)), *events[1:])
    )
    unknown_result = calculate_income(unknown, options=r.IncomeOptions())
    assert unknown_result.summary.net_income == result.summary.net_income
    assert unknown_result.summary.withholding.value is None
    assert unknown_result.summary.withholding.reason_code is d.HistoricalReason.WITHHOLDING_UNKNOWN


@pytest.mark.parametrize(("daily", "expected"), [(False, ".026"), (True, ".0404")])
def test_composite_benchmark_modes_use_exact_original_weights(daily: bool, expected: str) -> None:
    from trading212_analytics.historical import calculate_benchmark_comparison

    from .historical_factories import with_benchmark

    value = with_benchmark(
        fixture(("100", "100", "100")), ("100", "110", "99"), ("100", "90", "108"), daily=daily
    )
    result = calculate_benchmark_comparison(
        value, options=r.ComparisonOptions(frequency=d.HistoricalFrequency.DAILY)
    )
    assert result.summary.benchmark_return.value == Decimal(expected)
    assert result.summary.tracking_error.reason_code is d.HistoricalReason.TRACKING_PAIRS
    assert result.composite is not None
    assert result.composite.kind == "composite"
    verify_historical_result(value, result)


def test_price_fx_interaction_partition_reconciles_independent_amounts() -> None:
    from trading212_analytics.historical import calculate_attribution

    from .historical_factories import with_fx
    from .source_factories import USD

    value = with_fx(fixture(("10", "12"), quantity="2", currency=USD), ("1", "1.1"), base=USD)
    result = calculate_attribution(
        value, options=r.AttributionOptions(method=d.AttributionMethod.MODIFIED_DIETZ)
    )
    effects = {
        effect.kind: effect.amount.value.amount for effect in result.effects if effect.amount.value
    }
    assert effects["price"] == 4
    assert effects["fx"] == 2
    assert effects["interaction"] == Decimal(".4")
    assert (
        result.summary.investment_gain.value
        and result.summary.investment_gain.value.amount == Decimal("6.4")
    )
    assert result.summary.residual.value and result.summary.residual.value.amount == 0
    verify_historical_result(value, result)


def test_cash_flow_detail_filter_keeps_whole_window_totals_and_revision_dedup() -> None:
    from trading212_analytics.historical import calculate_cash_flows
    from trading212_domain import Money

    from .historical_factories import START, identity, with_events
    from .source_factories import EUR

    deposit = d.HistoricalExternalFlow(
        identity=identity(100, START),
        kind="deposit",
        signed_amount=Money(Decimal(50), EUR),
        scope_proof="account_boundary",
    )
    withdrawal = d.HistoricalExternalFlow(
        identity=identity(101, START),
        kind="withdrawal",
        signed_amount=Money(Decimal(-20), EUR),
        scope_proof="account_boundary",
    )
    value = with_events(fixture(), deposit, withdrawal)
    result = calculate_cash_flows(
        value, options=r.CashFlowOptions(kind=d.HistoricalCashFlowKind.WITHDRAWAL)
    )
    assert result.summary.event_count == 2 and result.summary.filtered_count == 1
    assert (
        result.reporting_totals.external_net.value
        and result.reporting_totals.external_net.value.amount == 30
    )
    assert result.events[0].kind is d.HistoricalCashFlowKind.WITHDRAWAL


def test_exact_midyear_flow_reference_twr_dietz_and_xirr() -> None:
    from datetime import timedelta

    from trading212_domain import Money

    from .historical_factories import START, identity, metric, with_events
    from .source_factories import EUR, uid

    value = fixture(("100",) * 365 + ("120",))
    at = START + timedelta(days=182, hours=12)
    flow = d.HistoricalExternalFlow(
        identity=identity(100, at),
        kind="deposit",
        signed_amount=Money(Decimal(100), EUR),
        scope_proof="account_boundary",
    )
    value = with_events(value, flow)
    assert isinstance(value.opening, d.ObservedHistoricalOpening)
    anchor = replace(
        value.opening.anchor,
        id=uid(52),
        at=at,
        positions=(replace(value.opening.anchor.positions[0], market_value=metric("100")),),
        cash=(Money(Decimal(100), EUR),),
        source_refs=(uid(100),),
        reconciliation=replace(value.opening.anchor.reconciliation, anchor_refs=(uid(100),)),
    )
    value = replace(value, valuation_anchors=(anchor,))
    result = calculate_performance(value, options=r.PerformanceOptions())
    assert (
        result.summary.investment_gain.value and result.summary.investment_gain.value.amount == 20
    )
    assert result.summary.time_weighted_return.value == Decimal(".1")
    assert result.summary.modified_dietz_return.value == Decimal("0.133333333333333333")
    assert result.summary.money_weighted_return.value == Decimal("0.134752415750147213")
    assert result.summary.annualized_time_weighted_return.value == Decimal(".1")
    no_anchor = calculate_performance(
        replace(value, valuation_anchors=()), options=r.PerformanceOptions()
    )
    assert no_anchor.summary.time_weighted_return.reason_code is d.HistoricalReason.TWR_FLOW_ANCHOR
    assert no_anchor.summary.modified_dietz_return == result.summary.modified_dietz_return


def test_external_flow_at_opening_is_grouped_once_and_terminal_flow_excluded() -> None:
    from trading212_domain import Money

    from .historical_factories import START, identity, with_events
    from .source_factories import EUR

    value = fixture(("100", "110"))
    opening = d.HistoricalExternalFlow(
        identity=identity(100, START),
        kind="deposit",
        signed_amount=Money(Decimal(100), EUR),
        scope_proof="account_boundary",
    )
    terminal = replace(
        opening,
        identity=identity(101, value.selection.window.end_at),
        signed_amount=Money(Decimal(999), EUR),
    )
    result = calculate_performance(
        with_events(value, opening, terminal), options=r.PerformanceOptions()
    )
    assert (
        result.summary.net_contributions.value
        and result.summary.net_contributions.value.amount == 100
    )
    assert result.summary.ending_value.value and result.summary.ending_value.value.amount == 210
    assert result.summary.time_weighted_return.value == Decimal(".05")
    assert result.summary.modified_dietz_return.value == Decimal(".05")


def test_dated_activity_proof_cannot_borrow_opening_or_future_receipt() -> None:
    from datetime import timedelta

    value = fixture()
    missing = calculate_performance(
        replace(value, activity_coverage=()), options=r.PerformanceOptions()
    )
    assert missing.summary.ending_value.value is None
    short_chunks = tuple(
        replace(chunk, end_at=value.selection.window.start_at) for chunk in value.activity_coverage
    )
    short = calculate_performance(
        replace(value, activity_coverage=short_chunks), options=r.PerformanceOptions()
    )
    assert short.summary.ending_value.value is None
    future = tuple(
        replace(
            chunk, first_observed_at=value.selection.window.source_cutoff_at + timedelta(seconds=1)
        )
        for chunk in value.activity_coverage
    )
    later = calculate_performance(
        replace(value, activity_coverage=future), options=r.PerformanceOptions()
    )
    assert later.summary.ending_value.value is None


def test_missing_expected_price_does_not_use_previous_session_or_become_zero() -> None:
    from trading212_domain import QualityState
    from trading212_domain.sources import ObservationState, SourceCoverage, SourceGap, SourceReason

    value = fixture()
    snapshot = value.price_snapshots[0]
    last = snapshot.observations[-1]
    missing = replace(
        snapshot,
        observations=(
            *snapshot.observations[:-1],
            replace(last, state=ObservationState.MISSING, value=None),
        ),
        coverage=SourceCoverage(
            expected_count=4,
            available_count=3,
            gaps=(SourceGap(session_date=last.session_date, reason=SourceReason.MISSING_SESSION),),
            quality=QualityState.PARTIAL,
        ),
    )
    result = calculate_performance(
        replace(value, price_snapshots=(missing,)), options=r.PerformanceOptions()
    )
    assert result.summary.ending_value.value is None
    assert any(
        isinstance(use, r.HistoricalMissingUse) and use.expected_session == last.session_date
        for use in result.source_uses
    )


def test_effective_mapping_uses_earlier_eligible_identical_identity_revision() -> None:
    from datetime import timedelta

    from .source_factories import uid

    value = fixture()
    later = replace(
        value.mapping_evidence[0],
        id=uid(8),
        valid_from=value.selection.window.end_at + timedelta(days=1),
        first_observed_at=value.selection.window.end_at + timedelta(days=1),
    )
    value = replace(value, mapping_evidence=(later, *value.mapping_evidence))
    result = calculate_performance(value, options=r.PerformanceOptions())
    assert result.summary.time_weighted_return.value == Decimal(".2")
    mapping_uses = [
        use.reference_id
        for use in result.source_uses
        if isinstance(use, r.HistoricalEvidenceUse) and use.reference_kind == "mapping"
    ]
    assert mapping_uses and set(mapping_uses) == {uid(5)}


def test_drawdown_uses_flow_neutral_wealth_path() -> None:
    value = fixture(("100", "110", "99", "120"))
    result = calculate_performance(
        value, options=r.PerformanceOptions(frequency=d.HistoricalFrequency.DAILY)
    )
    assert result.summary.maximum_drawdown.value == Decimal("-.1")
    assert [point.drawdown.value for point in result.points] == [0, Decimal("-.1"), 0]


def test_rolling_and_complete_calendar_are_actual_period_calculations() -> None:
    value = fixture(tuple(str(100 + index) for index in range(32)))
    result = calculate_performance(
        value,
        options=r.PerformanceOptions(
            frequency=d.HistoricalFrequency.DAILY,
            rolling_window=d.RollingWindow.DAYS_30,
            calendar_period=d.CalendarPeriod.MONTH,
        ),
    )
    assert len(result.rolling_returns) == 31
    assert result.rolling_returns[0].value.reason_code is d.HistoricalReason.ROLLING_BOUNDARY
    assert result.rolling_returns[-2].value.value == Decimal(".3")
    assert result.rolling_returns[-1].value.value == Decimal("0.297029702970297030")
    assert result.calendar_returns[0].value.value == Decimal(".31")


def test_point_in_time_receipts_at_boundary_support_covered_history_without_future_use() -> None:
    from .historical_factories import point_in_time

    value = point_in_time(fixture())
    result = calculate_performance(
        value, options=r.PerformanceOptions(frequency=d.HistoricalFrequency.DAILY)
    )
    assert result.summary.time_weighted_return.value == Decimal(".2")
    assert result.context.reconstruction == "point_in_time"
    assert all(use.knowledge_cutoff_at <= use.use_at for use in result.source_uses)
    verify_historical_result(value, result)


def test_late_material_price_revision_gates_point_in_time_return() -> None:
    from datetime import timedelta

    from trading212_domain.sources import source_snapshot_digest

    from .historical_factories import START, point_in_time
    from .source_factories import uid

    value = point_in_time(fixture())
    original = value.price_snapshots[0]
    corrected = replace(
        original,
        id=uid(450),
        observations=(replace(original.observations[0], value=Decimal(90)),),
        provenance=replace(
            original.provenance,
            first_observed_at=START + timedelta(days=1),
            revision_order=2,
            source_revision="revision-2",
        ),
    )
    value = replace(
        value,
        price_snapshots=(*value.price_snapshots, corrected),
        sources=(
            *value.sources,
            d.HistoricalSourceReference(
                kind="price_snapshot",
                id=corrected.id,
                effective_at=corrected.provenance.effective_at,
                first_observed_at=corrected.provenance.first_observed_at,
                semantic_digest=source_snapshot_digest(corrected),
            ),
        ),
    )
    result = calculate_performance(value, options=r.PerformanceOptions())
    assert result.summary.time_weighted_return.value is None
    assert (
        result.summary.time_weighted_return.reason_code is d.HistoricalReason.KNOWLEDGE_TRANSITION
    )


def test_tracking_error_uses_sample_variance_and_twenty_pair_threshold() -> None:
    from trading212_analytics._historical_benchmark import tracking_error
    from trading212_analytics._historical_core import financial

    calculate = financial(tracking_error)
    assert calculate((Decimal(".01"),) * 20, 252).value == 0
    alternating = (Decimal(".01"), Decimal("-.01")) * 10
    assert calculate(alternating, 252).value == Decimal("0.162869014209191075")
    assert calculate(alternating[:-1], 252).reason_code is d.HistoricalReason.TRACKING_PAIRS


def test_income_and_cash_flow_missing_history_do_not_claim_observed_zero_totals() -> None:
    from trading212_analytics.historical import calculate_cash_flows, calculate_income

    value = replace(fixture(), activity_coverage=())
    income = calculate_income(value, options=r.IncomeOptions())
    cash = calculate_cash_flows(value, options=r.CashFlowOptions())
    assert income.summary.net_income.value is None
    assert income.summary.net_income.reason_code is d.HistoricalReason.EVENT_COVERAGE
    assert cash.reporting_totals.external_net.value is None
    assert cash.reporting_totals.external_net.reason_code is d.HistoricalReason.EVENT_COVERAGE


def test_empty_unconfigured_benchmark_never_creates_an_unbacked_composite() -> None:
    from trading212_analytics.historical import calculate_benchmark_comparison

    from .historical_factories import with_benchmark

    value = with_benchmark(
        fixture(("100", "100", "100")), ("100", "110", "99"), ("100", "90", "108")
    )
    value = replace(
        value, selection=replace(value.selection, source_policy=None, reporting_calendar_ref=None)
    )
    result = calculate_benchmark_comparison(value, options=r.ComparisonOptions())
    assert result.composite is None
    assert result.summary.benchmark_return.value is None


def test_prior_income_uses_dated_support_not_an_opening_coverage_flag() -> None:
    from datetime import timedelta

    from trading212_analytics.historical import calculate_income
    from trading212_domain import Money

    from .historical_factories import START, identity, metric, with_events
    from .source_factories import EUR, uid

    value = fixture(("1",) * 7, quantity="1300")
    current_start = START + timedelta(days=3)
    window = replace(value.selection.window, start_date=current_start.date())
    prior_start, prior_end = d.historical_previous_income_period(window)
    assert prior_start == START and prior_end == current_start
    prior = d.HistoricalDividend(
        identity=identity(100, START + timedelta(days=1)),
        dividend_key="prior",
        instrument_id=uid(6),
        listing_id=uid(7),
        net=Money(Decimal(20), EUR),
        gross=metric("20"),
        withholding=metric("0"),
        payment_convention="exact_provider_instant",
    )
    current = replace(
        prior,
        identity=identity(101, current_start),
        dividend_key="current",
        net=Money(Decimal("32.5"), EUR),
        gross=metric("32.5"),
    )
    value = with_events(value, prior, current)
    value = replace(
        value,
        selection=replace(
            value.selection,
            window=window,
            support_windows=(
                d.HistoricalSupportWindow(
                    reason="previous_calendar_income", start_at=prior_start, end_at=prior_end
                ),
            ),
        ),
        coverage=d.HistoricalCoverage(
            measures=tuple(
                item
                for item in value.coverage.measures
                if item.key is not d.HistoricalCoverageKey.PRIOR_INCOME
            )
        ),
    )
    result = calculate_income(value, options=r.IncomeOptions())
    assert (
        result.summary.previous_period_income.value
        and result.summary.previous_period_income.value.amount == 20
    )
    assert result.summary.dividend_growth.value == Decimal(".625")
    assert result.context.coverage.complete(d.HistoricalCoverageKey.PRIOR_INCOME)


def test_previous_month_uses_calendar_boundaries_across_february() -> None:
    from datetime import UTC, date, datetime

    from .source_factories import EUR

    window = d.HistoricalWindow(
        start_date=date(2025, 3, 1),
        end_date=date(2025, 3, 31),
        source_cutoff_at=datetime(2025, 4, 1, tzinfo=UTC),
        reporting_currency=EUR,
    )
    assert d.historical_previous_income_period(window) == (
        datetime(2025, 2, 1, tzinfo=UTC),
        datetime(2025, 3, 1, tzinfo=UTC),
    )


def test_weighted_average_cost_keeps_precision_until_output_boundary() -> None:
    from datetime import timedelta

    from trading212_domain import Money

    from .historical_factories import START, identity, metric, with_events
    from .source_factories import EUR, uid

    value = fixture(("1", "1", "1"), quantity="3")
    assert isinstance(value.opening, d.ObservedHistoricalOpening)
    anchor = replace(
        value.opening.anchor,
        positions=(
            replace(
                value.opening.anchor.positions[0],
                acquisition_cost=metric("1", key=d.HistoricalCoverageKey.COST),
            ),
        ),
    )
    value = replace(value, opening=replace(value.opening, anchor=anchor))
    sales = tuple(
        d.HistoricalExecution(
            identity=identity(100 + index, START + timedelta(days=index)),
            order_key=f"order-{index}",
            fill_key=f"fill-{index}",
            instrument_id=uid(6),
            listing_id=uid(7),
            mapping_id=uid(5),
            side="sell",
            quantity=Decimal(1),
            native_price=Money(Decimal(1), EUR),
            gross_value=Money(Decimal(1), EUR),
            cash_impact=Money(Decimal(1), EUR),
            fees=metric("0"),
            taxes=metric("0"),
        )
        for index in range(2)
    )
    result = calculate_performance(with_events(value, *sales), options=r.PerformanceOptions())
    assert (
        result.summary.realized_profit_loss.value
        and result.summary.realized_profit_loss.value.amount == Decimal("1.333333333333333333")
    )
    assert (
        result.summary.unrealized_profit_loss.value
        and result.summary.unrealized_profit_loss.value.amount == Decimal("0.666666666666666667")
    )


def test_already_reporting_currency_anchor_is_not_converted_using_listing_currency() -> None:
    from .historical_factories import metric
    from .source_factories import USD, uid

    value = fixture(("10", "12"), quantity="2", currency=USD)
    assert isinstance(value.opening, d.ObservedHistoricalOpening)
    opening = value.opening.anchor
    anchors = tuple(
        replace(
            opening,
            id=uid(52 + index),
            at=at,
            timing="before_events",
            positions=(replace(opening.positions[0], market_value=metric(market)),),
        )
        for index, (at, market) in enumerate(
            ((value.selection.window.start_at, "20"), (value.selection.window.end_at, "24"))
        )
    )
    value = replace(value, valuation_anchors=anchors)
    result = calculate_performance(value, options=r.PerformanceOptions())
    assert (
        result.summary.beginning_value.value and result.summary.beginning_value.value.amount == 20
    )
    assert result.summary.ending_value.value and result.summary.ending_value.value.amount == 24
    assert result.summary.time_weighted_return.value == Decimal(".2")


@pytest.mark.parametrize(
    ("family", "method_id", "expected_primitives"),
    [
        ("performance", "performance_v2", {"xirr", "modified_dietz", "snapshot_subperiod_twr"}),
        ("benchmark", "benchmark_comparison_v1", {"modified_dietz", "snapshot_subperiod_twr"}),
        ("income", "income_v1", set()),
        (
            "attribution",
            "attribution_bridge_v1",
            {"xirr", "modified_dietz", "snapshot_subperiod_twr"},
        ),
        ("cash_flows", "cash_flow_intelligence_v1", set()),
    ],
)
def test_frozen_family_registry_records_only_invoked_phase1_primitives(
    family: str, method_id: str, expected_primitives: set[str]
) -> None:
    from trading212_analytics import historical as calculations

    from .historical_factories import with_benchmark

    value = with_benchmark(fixture(), ("100", "100", "110", "120"), ("100",) * 4)
    result: r.HistoricalCalculation
    if family == "performance":
        result = calculations.calculate_performance(value, options=r.PerformanceOptions())
    elif family == "benchmark":
        result = calculations.calculate_benchmark_comparison(value, options=r.ComparisonOptions())
    elif family == "income":
        result = calculations.calculate_income(value, options=r.IncomeOptions())
    elif family == "attribution":
        result = calculations.calculate_attribution(value, options=r.AttributionOptions())
    else:
        result = calculations.calculate_cash_flows(value, options=r.CashFlowOptions())
    assert result.context.method == r.HistoricalMethod(name=method_id, version="1.0.0")
    assert {item.name for item in result.context.primitive_methods} == expected_primitives
    assert all(item.version == "1.0.0" for item in result.context.primitive_methods)
    assert result.context.primitive_methods == tuple(
        sorted(result.context.primitive_methods, key=lambda item: item.name)
    )
    verify_historical_result(value, result)


def test_unavailable_performance_does_not_claim_uninvoked_return_primitives() -> None:
    value = replace(
        fixture(),
        opening=d.UnavailableHistoricalOpening(reasons=(d.HistoricalReason.OPENING_MISSING,)),
    )
    result = calculate_performance(value, options=r.PerformanceOptions())
    assert result.context.method.name == "performance_v2"
    assert result.context.primitive_methods == ()


def test_valuation_capacity_refuses_before_any_source_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trading212_analytics._historical_core import HistoricalEngine
    from trading212_domain import DomainError, ErrorCode

    value = fixture()
    monkeypatch.setattr(d, "MAX_HISTORICAL_CELLS", 1)

    def forbidden_selection(*args: object, **kwargs: object) -> None:
        raise AssertionError("Capacity must be checked before selecting financial inputs.")

    monkeypatch.setattr(HistoricalEngine, "price", forbidden_selection)
    with pytest.raises(DomainError) as captured:
        calculate_performance(value, options=r.PerformanceOptions())
    assert captured.value.code is ErrorCode.INPUT_BOUND_EXCEEDED


def test_tracking_error_refuses_hidden_gap_even_with_twenty_other_pairs() -> None:
    from trading212_analytics.historical import calculate_benchmark_comparison
    from trading212_domain import QualityState
    from trading212_domain.sources import ObservationState, SourceCoverage, SourceGap, SourceReason

    from .historical_factories import with_benchmark

    value = with_benchmark(fixture(("100",) * 25), ("100",) * 25, ("100",) * 25)
    assert value.benchmark_input is not None
    source = value.benchmark_input.benchmark_snapshots[0]
    missing = source.observations[12]
    corrected = replace(
        source,
        observations=tuple(
            replace(item, state=ObservationState.MISSING, level=None) if item == missing else item
            for item in source.observations
        ),
        coverage=SourceCoverage(
            expected_count=25,
            available_count=24,
            gaps=(
                SourceGap(session_date=missing.session_date, reason=SourceReason.MISSING_SESSION),
            ),
            quality=QualityState.PARTIAL,
        ),
    )
    value = replace(
        value,
        benchmark_input=replace(
            value.benchmark_input,
            benchmark_snapshots=(corrected, value.benchmark_input.benchmark_snapshots[1]),
        ),
    )
    result = calculate_benchmark_comparison(value, options=r.ComparisonOptions())
    assert result.summary.paired_observation_count >= 20
    assert result.summary.tracking_error.value is None
    assert result.summary.tracking_error.reason_code is d.HistoricalReason.BENCHMARK_GAP


def test_xirr_wrapper_preserves_nonconventional_and_no_root_reasons() -> None:
    from datetime import timedelta

    from trading212_domain import Money

    from .historical_factories import START, identity, with_events
    from .source_factories import EUR

    value = with_events(
        fixture(("100",) * 4, cash="100"),
        d.HistoricalExternalFlow(
            identity=identity(100, START + timedelta(days=1)),
            kind="withdrawal",
            signed_amount=Money(Decimal(-100), EUR),
            scope_proof="account_boundary",
        ),
        d.HistoricalExternalFlow(
            identity=identity(101, START + timedelta(days=2)),
            kind="deposit",
            signed_amount=Money(Decimal(100), EUR),
            scope_proof="account_boundary",
        ),
    )
    result = calculate_performance(value, options=r.PerformanceOptions())
    assert result.summary.money_weighted_return.value is None
    assert (
        result.summary.money_weighted_return.reason_code is d.HistoricalReason.XIRR_NONCONVENTIONAL
    )
    assert result.summary.investment_gain.value == Money(Decimal(0), EUR)
    empty = calculate_performance(fixture(quantity="0"), options=r.PerformanceOptions())
    assert empty.summary.money_weighted_return.value is None
    assert empty.summary.money_weighted_return.reason_code is d.HistoricalReason.XIRR_NO_ROOT
