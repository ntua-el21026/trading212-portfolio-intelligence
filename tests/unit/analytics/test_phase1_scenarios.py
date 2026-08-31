import pytest
from trading212_analytics import (
    PHASE_1_SCENARIOS,
    CashComponentInput,
    ValuedPositionInput,
    aggregate_portfolio,
    get_phase1_scenario,
)
from trading212_domain import CurrencyCode, Money, QualityState, Quantity

from .factories import ACCOUNT_ID, END, LISTING_ID

pytestmark = pytest.mark.unit

EXPECTED_SCENARIO_IDS = (
    "empty_eur_account",
    "single_currency_buy_and_hold",
    "fractional_multi_position",
    "multi_currency_with_fx",
    "external_and_internal_flows",
    "income_fees_withholding",
    "partial_history",
    "duplicate_and_updated_events",
    "unmapped_instrument",
    "unsupported_unknown_activity",
    "reconciliation_mismatch",
    "stale_sources",
    "provider_failure_or_schema_drift",
    "cross_owner_attempt",
)


def test_all_fourteen_normative_phase1_scenarios_have_fixed_metadata() -> None:
    assert tuple(item.scenario_id for item in PHASE_1_SCENARIOS) == EXPECTED_SCENARIO_IDS
    assert len({item.scenario_id for item in PHASE_1_SCENARIOS}) == 14
    assert all(item.authoritative_expectation for item in PHASE_1_SCENARIOS)
    assert all(get_phase1_scenario(item.scenario_id) is item for item in PHASE_1_SCENARIOS)


def test_non_analytics_scenarios_do_not_claim_authorization_or_provider_recovery() -> None:
    provider = get_phase1_scenario("provider_failure_or_schema_drift")
    cross_owner = get_phase1_scenario("cross_owner_attempt")
    assert provider.layer == "ingestion_quality"
    assert cross_owner.layer == "authorization_boundary"
    assert cross_owner.expected_quality is None


def test_partial_capability_output_degrades_only_dependent_portfolio_metric() -> None:
    aggregate = aggregate_portfolio(
        account_id=ACCOUNT_ID,
        positions=(
            ValuedPositionInput(
                ACCOUNT_ID,
                LISTING_ID,
                Quantity.parse("1"),
                CurrencyCode("EUR"),
                provider_market_value=None,
                quality_state=QualityState.PARTIAL,
            ),
        ),
        cash_components=(CashComponentInput(ACCOUNT_ID, "available", Money.parse("25", "EUR")),),
        reporting_currency=CurrencyCode("EUR"),
        fx_quotes=(),
        valuation_at=END,
        source_cutoff_at=END,
    )
    assert aggregate.cash_total == Money.parse("25", "EUR")
    assert aggregate.invested_total is None
    assert aggregate.portfolio_total is None
    assert aggregate.known_portfolio_subtotal == Money.parse("25", "EUR")
    assert aggregate.quality_state is QualityState.PARTIAL


def test_stale_material_source_can_never_become_fresh_downstream() -> None:
    aggregate = aggregate_portfolio(
        account_id=ACCOUNT_ID,
        positions=(
            ValuedPositionInput(
                ACCOUNT_ID,
                LISTING_ID,
                Quantity.parse("1"),
                CurrencyCode("EUR"),
                provider_market_value=Money.parse("25", "EUR"),
                quality_state=QualityState.STALE,
            ),
        ),
        cash_components=(),
        reporting_currency=CurrencyCode("EUR"),
        fx_quotes=(),
        valuation_at=END,
        source_cutoff_at=END,
    )
    assert aggregate.portfolio_total == Money.parse("25", "EUR")
    assert aggregate.quality_state is QualityState.STALE
