"""Terminal conservation and exact economic-currency evidence, with no wrapper inference."""

from dataclasses import replace
from decimal import Decimal

import pytest
from trading212_analytics.xray import calculate_xray, convert_xray_money
from trading212_domain.errors import DomainError
from trading212_domain.scenario import ScenarioReason
from trading212_domain.scenario_exposure import extract_scenario_exposures
from trading212_domain.values import CurrencyCode, Money
from trading212_domain.xray import XrayDimension, XrayLicensedFx

from tests.unit.analytics.xray_factories import Builder, fixture, reversed_input, uid


def test_one_terminal_amount_per_path_and_no_fund_wrapper_double_count() -> None:
    source = fixture()
    result = calculate_xray(source)
    exposures = extract_scenario_exposures(source, result)
    paths = {path.key: path for path in result.terminal_paths}
    assert len(exposures) == len(paths)
    assert len({item.path_key for item in exposures}) == len(paths)
    for exposure in exposures:
        assert exposure.pre_value.value == paths[exposure.path_key].reporting_value.value
        if exposure.root_instrument_id in (uid(20), uid(30)):
            assert exposure.instrument.subject_id not in (uid(20), uid(30))
    assert sum(
        item.pre_value.value.amount for item in exposures if item.pre_value.value
    ) == Decimal("1000")
    assert extract_scenario_exposures(reversed_input(source), result) == exposures


def test_economic_currency_joins_taxonomy_and_does_not_follow_reporting_currency() -> None:
    builder = Builder()
    builder.position(uid(10), "100", listing=uid(501))
    builder.identity(uid(10), uid(110), listing=uid(501))
    builder.classifications_for(uid(110), key="technology")
    batch = builder.classifications[0]
    builder.classifications[0] = replace(
        batch,
        assignments=tuple(
            replace(item, bucket_key="USD") if item.dimension is XrayDimension.CURRENCY else item
            for item in batch.assignments
        ),
    )
    source = builder.finish()
    result = calculate_xray(source)
    (exposure,) = extract_scenario_exposures(source, result)
    assert exposure.pre_value.value is not None
    assert exposure.pre_value.value.currency == CurrencyCode("EUR")
    assert exposure.economic_currency.currency == CurrencyCode("USD")
    assert exposure.economic_currency.basis == "economic_classification"
    assert exposure.economic_currency.evidence_ids == (batch.evidence.id,)
    sector = next(
        item for item in builder.policy.taxonomy_versions if item.dimension is XrayDimension.SECTOR
    )
    assert (
        exposure.sector.taxonomy_id,
        exposure.sector.taxonomy_version,
        exposure.sector.bucket_key,
    ) == (sector.taxonomy_id, sector.version, "technology")


def test_constituent_cash_has_its_own_currency_and_header_cash_stays_unknown() -> None:
    builder = Builder()
    builder.position(uid(20), "100")
    candidate = builder.fund(uid(20), ((None, "0.4"),))
    builder.constituents[0] = replace(
        candidate,
        holdings=(replace(candidate.holdings[0], source_currency=CurrencyCode("USD")),),
        cash_weight=Decimal("1"),
    )
    source = builder.finish()
    exposures = extract_scenario_exposures(source, calculate_xray(source))
    cash = [item for item in exposures if item.explicit_cash]
    known = next(item for item in cash if item.economic_currency.holding_id is not None)
    header = next(item for item in cash if item.economic_currency.holding_id is None)
    assert known.economic_currency.currency == CurrencyCode("USD")
    assert known.economic_currency.basis == "constituent_cash"
    assert header.economic_currency.currency is None
    assert header.economic_currency.reason is ScenarioReason.MISSING_ECONOMIC_CURRENCY
    assert all(
        item.instrument.state == "not_applicable" and item.sector.state == "not_applicable"
        for item in cash
    )


def test_snapshot_cash_retains_original_currency_without_classification() -> None:
    builder = Builder()
    builder.cash_row("25")
    cash = builder.cash[0]
    usd = CurrencyCode("USD")
    original = replace(cash.original_value, value=Money.parse("25", usd))
    leg = builder.fx_leg(usd, builder.reporting_currency, "0.8")
    builder.cash[0] = replace(
        cash,
        root=replace(cash.root, original_currency=usd),
        original_value=original,
        reporting_value=convert_xray_money(original, builder.reporting_currency, legs=(leg,)),
        fx_refs=(leg.source_reference_id,),
    )
    builder.licensed_fx.append(
        XrayLicensedFx(cash.root.key, original, builder.reporting_currency, (leg,))
    )
    source = builder.finish()
    (exposure,) = extract_scenario_exposures(source, calculate_xray(source))
    assert exposure.economic_currency.currency == CurrencyCode("USD")
    assert exposure.economic_currency.basis == "snapshot_cash"
    assert exposure.economic_currency.cash_id == builder.cash[0].root.snapshot_cash_id


def test_claimed_classification_without_captured_assignment_fails_closed() -> None:
    source = fixture()
    result = calculate_xray(source)
    decision = next(
        item for item in result.classification_decisions if item.dimension is XrayDimension.SECTOR
    )
    corrupt = replace(
        result,
        classification_decisions=tuple(
            replace(item, assignment_ids=(uid(999_999),)) if item.key == decision.key else item
            for item in result.classification_decisions
        ),
    )
    with pytest.raises(DomainError):
        extract_scenario_exposures(source, corrupt)
    with pytest.raises(DomainError):
        extract_scenario_exposures(source, replace(result, input_digest="0" * 64))


def test_constituent_entity_identity_uses_its_exact_holding_evidence() -> None:
    from trading212_domain.xray import XrayHoldingKind

    builder = Builder()
    builder.position(uid(20), "100")
    candidate = builder.fund(uid(20), ((None, "1"),))
    holding = replace(
        candidate.holdings[0],
        kind=XrayHoldingKind.ENTITY,
        entity_id=uid(110),
        evidence_key="fixture:entity-holding",
    )
    builder.constituents[0] = replace(
        candidate,
        holdings=(holding,),
        stated_coverage=Decimal("1"),
        cash_weight=Decimal("0"),
    )
    builder.classifications_for(uid(110))
    source = builder.finish()
    (exposure,) = extract_scenario_exposures(source, calculate_xray(source))
    assert exposure.entity.subject_id == uid(110)
    assert holding.id in exposure.entity.identity_decision_ids
    assert exposure.instrument.state == "unknown"
    assert exposure.sector.state == "known"
