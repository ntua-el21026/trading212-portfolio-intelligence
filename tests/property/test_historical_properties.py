from dataclasses import replace
from decimal import ROUND_UP, Decimal, Inexact, Rounded, localcontext

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from trading212_analytics.historical import (
    calculate_attribution,
    calculate_cash_flows,
    calculate_performance,
    verify_historical_result,
)
from trading212_domain import Money
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.historical_serialization import (
    historical_input_digest,
    historical_result_digest,
)

from tests.unit.analytics.historical_factories import START, fixture, identity, with_events
from tests.unit.analytics.source_factories import EUR

pytestmark = pytest.mark.property


@settings(max_examples=60, deadline=None)
@given(st.integers(1, 10000), st.integers(1, 10000), st.integers(1, 100))
def test_positive_constant_quantity_growth_and_attribution_conserve_exact_value(
    begin: int, end: int, quantity: int
) -> None:
    value = fixture((str(begin), str(end)), quantity=str(quantity))
    result = calculate_performance(value, options=r.PerformanceOptions())
    attribution = calculate_attribution(
        value, options=r.AttributionOptions(method=d.AttributionMethod.MODIFIED_DIETZ)
    )
    assert result.summary.investment_gain.value is not None
    assert result.summary.investment_gain.value.amount == quantity * (end - begin)
    assert attribution.summary.investment_gain == result.summary.investment_gain
    assert (
        attribution.summary.residual.value is not None
        and attribution.summary.residual.value.amount == 0
    )
    verify_historical_result(value, result)
    verify_historical_result(value, attribution)


@settings(max_examples=40, deadline=None)
@given(st.integers(1, 1000), st.integers(1, 1000))
def test_ambient_decimal_precision_rounding_and_traps_do_not_change_financial_result(
    begin: int, end: int
) -> None:
    value = fixture((str(begin), str(end)))
    expected = calculate_performance(value, options=r.PerformanceOptions())
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        actual = calculate_performance(value, options=r.PerformanceOptions())
    assert historical_result_digest(actual) == historical_result_digest(expected)


@settings(max_examples=40, deadline=None)
@given(st.lists(st.integers(-1000, 1000), min_size=1, max_size=8))
def test_event_permutation_preserves_signed_external_totals_and_digests(amounts: list[int]) -> None:
    events = tuple(
        d.HistoricalExternalFlow(
            identity=identity(100 + index, START),
            kind="deposit" if amount >= 0 else "withdrawal",
            signed_amount=Money(Decimal(amount), EUR),
            scope_proof="account_boundary",
        )
        for index, amount in enumerate(amounts)
    )
    value = with_events(fixture(), *events)
    permuted = replace(
        value,
        event_candidates=tuple(reversed(events)),
        sources=tuple(reversed(value.sources)),
        activity_coverage=tuple(reversed(value.activity_coverage)),
    )
    assert historical_input_digest(value) == historical_input_digest(permuted)
    result = calculate_cash_flows(value, options=r.CashFlowOptions())
    same = calculate_cash_flows(permuted, options=r.CashFlowOptions())
    assert result.reporting_totals.external_net.value is not None
    assert result.reporting_totals.external_net.value.amount == sum(amounts)
    assert historical_result_digest(result) == historical_result_digest(same)
