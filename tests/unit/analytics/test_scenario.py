"""Independent stress arithmetic, evidence uncertainty, and conservative complete money."""

from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Literal

import pytest
from trading212_analytics.scenario import calculate_scenario, validate_scenario_capacity
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.scenario import (
    ScenarioCurrencySelector,
    ScenarioEntitySelector,
    ScenarioExclusion,
    ScenarioFxShock,
    ScenarioInstrumentSelector,
    ScenarioPriceShock,
    ScenarioReason,
    ScenarioSectorSelector,
)
from trading212_domain.scenario_result import ScenarioMoneyMetric
from trading212_domain.scenario_serialization import canonical_scenario_bytes
from trading212_domain.sources import ObservationState
from trading212_domain.values import CurrencyCode, Money
from trading212_domain.xray import XrayDimension

from tests.unit.analytics.scenario_factories import (
    alias_capture,
    content,
    entity_only,
    input_for,
    portfolio,
    price,
    rate,
    with_observation,
)
from tests.unit.analytics.xray_factories import uid
from tests.unit.domain.scenario_factories import sensitivity_capture


def available_money(metric: ScenarioMoneyMetric) -> Money:
    assert metric.value is not None
    return metric.value


def fx(size: str) -> ScenarioFxShock:
    return ScenarioFxShock(
        selector=ScenarioCurrencySelector(currency=CurrencyCode("USD")), size=Decimal(size)
    )


@pytest.mark.parametrize(
    "mode,expected,interaction", [("compounded", "82.8", "0.8"), ("first_order", "82", "0")]
)
def test_original_basis_channel_effects_and_interaction(
    mode: Literal["compounded", "first_order"], expected: str, interaction: str
) -> None:
    result = calculate_scenario(
        input_for(portfolio(), content(price(10, "-0.2"), price(11, "0.1"), fx("-0.1"), mode=mode))
    )
    assert available_money(result.summary.post_value).amount == Decimal(expected)
    assert available_money(result.summary.effects.price).amount == Decimal("-8")
    assert available_money(result.summary.effects.fx).amount == Decimal("-10")
    assert available_money(result.summary.effects.interaction).amount == Decimal(interaction)
    assert available_money(result.summary.terminal_pre_value).amount == Decimal("100")
    assert available_money(result.upstream_partition_difference).amount == 0
    assert available_money(result.summary.component_sum_residual).amount == 0
    assert available_money(result.summary.rounding_residual).amount == 0
    assert result.summary.covered_count == 2


def test_hostile_decimal_context_and_rule_permutations_preserve_exact_result_bytes() -> None:
    definition = content(price(10, "-0.2"), price(11, "0.1"), fx("-0.1"))
    selected = input_for(portfolio(), definition)
    expected = canonical_scenario_bytes(calculate_scenario(selected))
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        assert canonical_scenario_bytes(calculate_scenario(selected)) == expected
    permuted = input_for(
        selected.xray_input, replace(definition, shocks=tuple(reversed(definition.shocks)))
    )
    assert canonical_scenario_bytes(calculate_scenario(permuted)) == expected


def test_known_instrument_winner_is_not_blocked_by_missing_lower_priority_sector() -> None:
    source = portfolio(("100",))
    source = replace(
        source,
        classification_batches=tuple(
            replace(
                batch,
                assignments=tuple(
                    row for row in batch.assignments if row.dimension is not XrayDimension.SECTOR
                ),
            )
            for batch in source.classification_batches
        ),
    )
    taxonomy = next(
        item for item in source.policy.taxonomy_versions if item.dimension is XrayDimension.SECTOR
    )
    sector = ScenarioPriceShock(
        selector=ScenarioSectorSelector(
            taxonomy_id=taxonomy.taxonomy_id,
            taxonomy_version=taxonomy.version,
            bucket_key="technology",
        ),
        size=Decimal("-0.9"),
    )
    result = calculate_scenario(input_for(source, content(price(10, "-0.2"), sector)))
    assert available_money(result.summary.post_value).amount == Decimal("80")
    assert result.summary.covered_count == 1


@pytest.mark.parametrize("lower,expected", [("0.5", None), ("0", "100")])
def test_unknown_higher_price_rule_does_not_take_a_favorable_lower_fallback(
    lower: str, expected: str | None
) -> None:
    entity = ScenarioPriceShock(
        selector=ScenarioEntitySelector(entity_id=uid(110)), size=Decimal(lower)
    )
    result = calculate_scenario(input_for(entity_only(), content(price(999, "0"), entity)))
    (component,) = result.components
    assert component.partition == "uncovered"
    assert component.winning_price_rule_key is None
    assert any(
        item.reason is ScenarioReason.UNCERTAIN_PRICE_PRIORITY for item in result.diagnostics
    )
    if expected is None:
        assert result.summary.post_value.value is None
        assert component.money_basis == "unavailable"
    else:
        assert available_money(result.summary.post_value).amount == Decimal(expected)
        assert component.money_basis == "provably_zero_effect"


def test_missing_positive_sensitivity_blocks_full_value_and_explicit_exclusion_restores_it() -> (
    None
):
    capture = sensitivity_capture()
    source = portfolio(economic="EUR")
    definition = content(rate(capture, "0.01"))
    missing = calculate_scenario(input_for(source, definition, capture))
    assert missing.summary.post_value.value is None
    assert available_money(missing.summary.covered_post_value).amount == Decimal("58.8")
    assert available_money(missing.summary.uncovered_pre_value).amount == Decimal("40")
    excluded = replace(
        definition,
        exclusions=(ScenarioExclusion(selector=ScenarioInstrumentSelector(instrument_id=uid(11))),),
    )
    result = calculate_scenario(input_for(source, excluded, capture))
    assert available_money(result.summary.post_value).amount == Decimal("98.8")
    assert available_money(result.summary.excluded_pre_value).amount == Decimal("40")
    assert result.summary.excluded_count == 1
    assert (
        next(item for item in result.components if item.partition == "excluded").sensitivity_uses
        == ()
    )


def test_zero_shock_proves_effect_without_assigning_zero_to_missing_coefficient() -> None:
    capture = sensitivity_capture()
    observation = replace(
        capture.observations[0],
        state=ObservationState.MISSING,
        coefficient=None,
        reason=ScenarioReason.MISSING_SENSITIVITY,
        quality=QualityState.PARTIAL,
    )
    capture = with_observation(capture, observation)
    result = calculate_scenario(
        input_for(portfolio(("100",), economic="EUR"), content(rate(capture, "0")), capture)
    )
    (component,) = result.components
    assert component.partition == "uncovered"
    assert component.money_basis == "provably_zero_effect"
    assert component.sensitivity_uses[0].coefficient is None
    assert component.sensitivity_uses[0].effect_ratio.value == 0
    assert available_money(result.summary.post_value).amount == Decimal("100")
    assert available_money(result.summary.provably_unchanged_uncovered_value).amount == Decimal(
        "100"
    )


def test_zero_original_value_keeps_diagnostics_and_does_not_bypass_invalid_multipliers() -> None:
    capture = sensitivity_capture()
    absent = with_observation(
        capture,
        replace(
            capture.observations[0],
            state=ObservationState.MISSING,
            coefficient=None,
            reason=ScenarioReason.MISSING_SENSITIVITY,
            quality=QualityState.PARTIAL,
        ),
    )
    result = calculate_scenario(
        input_for(portfolio(("0",), economic="EUR"), content(rate(absent, "0.01")), absent)
    )
    assert result.components[0].partition == "uncovered"
    assert result.components[0].money_basis == "zero_pre_value"
    assert available_money(result.summary.post_value).amount == 0
    severe = with_observation(
        capture, replace(capture.observations[0], coefficient=Decimal("-100"))
    )
    with pytest.raises(DomainError):
        calculate_scenario(
            input_for(
                portfolio(("0",), economic="EUR"),
                content(price(10, "-1"), rate(severe, "0.01")),
                severe,
            )
        )


def test_canonical_economic_driver_aliases_reject_even_with_zero_shocks() -> None:
    capture = alias_capture()
    first = rate(capture, "0")
    second_source = replace(
        capture,
        versions=(capture.versions[1],),
        observations=(capture.observations[1],),
        memberships=(capture.memberships[1],),
    )
    second = rate(second_source, "0")
    with pytest.raises(DomainError):
        calculate_scenario(
            input_for(portfolio(("100",), economic="EUR"), content(first, second), capture)
        )


def test_future_known_coefficients_do_not_replace_an_available_at_cutoff_gap() -> None:
    from datetime import timedelta

    capture = sensitivity_capture()
    base = input_for(portfolio(("100",), economic="EUR"), content(rate(capture, "0.01")), capture)
    capture = with_observation(
        capture,
        replace(
            capture.observations[0],
            first_known_at=base.pins.source_cutoff_at + timedelta(seconds=1),
        ),
    )
    result = calculate_scenario(input_for(base.xray_input, content(rate(capture, "0.01")), capture))
    assert result.summary.post_value.value is None
    assert result.components[0].sensitivity_uses[0].coefficient is None
    assert result.components[0].sensitivity_uses[0].reason is ScenarioReason.MISSING_SENSITIVITY


def test_nonzero_reporting_currency_fx_rule_is_rejected_at_admission() -> None:
    own_fx = ScenarioFxShock(
        selector=ScenarioCurrencySelector(currency=CurrencyCode("EUR")), size=Decimal("0.1")
    )
    with pytest.raises(DomainError, match="nonzero FX shock cannot select the reporting currency"):
        validate_scenario_capacity(input_for(portfolio(), content(own_fx)))
    zero = replace(own_fx, size=Decimal("0"))
    result = calculate_scenario(input_for(portfolio(("100",), economic="EUR"), content(zero)))
    assert available_money(result.summary.post_value).amount == Decimal("100")


def test_explicit_cash_is_not_a_security_sensitivity_subject() -> None:
    from tests.unit.analytics.xray_factories import Builder

    builder = Builder()
    builder.cash_row("100")
    capture = sensitivity_capture()
    result = calculate_scenario(
        input_for(builder.finish(), content(rate(capture, "0.01")), capture)
    )
    assert result.summary.covered_count == 1
    assert available_money(result.summary.post_value).amount == Decimal("100")
    assert result.components[0].sensitivity_uses == ()
    assert result.components[0].effects.factor_ratio.value == 0


def test_uncertain_exclusion_preserves_known_negative_multiplier_rejection() -> None:
    capture = sensitivity_capture()
    severe = with_observation(
        capture, replace(capture.observations[0], coefficient=Decimal("-100"))
    )
    exclusion = ScenarioExclusion(
        selector=ScenarioSectorSelector(
            taxonomy_id=uid(999_999), taxonomy_version="unrelated", bucket_key="technology"
        )
    )
    definition = replace(content(price(10, "-1"), rate(severe, "0.01")), exclusions=(exclusion,))
    with pytest.raises(DomainError, match="multiplier"):
        calculate_scenario(input_for(portfolio(("0",), economic="EUR"), definition, severe))


def test_applied_use_and_proof_byte_budget_fail_before_reserving_an_overflow_row() -> None:
    from trading212_analytics._scenario_sensitivities import ScenarioOutputBudget
    from trading212_domain.errors import ErrorCode
    from trading212_domain.scenario import MAX_SCENARIO_BYTES

    budget = ScenarioOutputBudget(source_rows=99_999)
    budget.reserve_use(0)
    with pytest.raises(DomainError) as caught:
        budget.reserve_use(0)
    assert caught.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert budget.applied_uses == 1
    with pytest.raises(DomainError) as caught:
        ScenarioOutputBudget(source_rows=0).reserve_use(MAX_SCENARIO_BYTES // 39 + 1)
    assert caught.value.code is ErrorCode.INPUT_BOUND_EXCEEDED


def test_known_factor_cancellation_proves_unchanged_with_uncertain_exclusion() -> None:
    from trading212_domain.scenario_serialization import (
        scenario_sensitivity_observation_digest,
        scenario_sensitivity_version_digest,
    )
    from trading212_domain.scenario_sources import ScenarioRateEquivalence

    capture = alias_capture()
    second_version = replace(
        capture.versions[1],
        driver=replace(
            capture.versions[1].driver,
            equivalence=ScenarioRateEquivalence(rate_id=uid(9399), currency=CurrencyCode("EUR")),
        ),
    )
    second_version = replace(
        second_version, content_digest=scenario_sensitivity_version_digest(second_version)
    )
    second_observation = replace(capture.observations[1], coefficient=Decimal("2"))
    second_observation = replace(
        second_observation,
        content_digest=scenario_sensitivity_observation_digest(second_observation),
    )
    capture = replace(
        capture,
        versions=(capture.versions[0], second_version),
        observations=(capture.observations[0], second_observation),
        memberships=(
            capture.memberships[0],
            replace(
                capture.memberships[1],
                version_digest=second_version.content_digest,
                observation_digest=second_observation.content_digest,
            ),
        ),
    )
    second_only = replace(
        capture,
        versions=(second_version,),
        observations=(second_observation,),
        memberships=(capture.memberships[1],),
    )
    exclusion = ScenarioExclusion(
        selector=ScenarioSectorSelector(
            taxonomy_id=uid(999_999), taxonomy_version="unrelated", bucket_key="technology"
        )
    )
    definition = replace(
        content(rate(capture, "0.01"), rate(second_only, "0.01")), exclusions=(exclusion,)
    )
    result = calculate_scenario(input_for(portfolio(("100",), economic="EUR"), definition, capture))
    (component,) = result.components
    assert component.partition == "uncovered"
    assert component.money_basis == "provably_zero_effect"
    assert component.effects.factor_ratio.value == 0
    assert {item.effect_ratio.value for item in component.sensitivity_uses} == {
        Decimal("-0.02"),
        Decimal("0.02"),
    }
    assert available_money(result.summary.post_value).amount == Decimal("100")


def test_factor_driver_uses_its_evidenced_simple_return_coefficient() -> None:
    from trading212_domain.scenario import ScenarioFactorShock
    from trading212_domain.scenario_serialization import (
        scenario_sensitivity_observation_digest,
        scenario_sensitivity_version_digest,
    )
    from trading212_domain.scenario_sources import ScenarioFactorEquivalence

    capture = sensitivity_capture()
    version = replace(
        capture.versions[0],
        driver=replace(
            capture.versions[0].driver,
            kind="factor",
            shock_unit="simple_factor_return",
            equivalence=ScenarioFactorEquivalence(factor_id=uid(9400)),
        ),
    )
    version = replace(version, content_digest=scenario_sensitivity_version_digest(version))
    observation = replace(
        capture.observations[0], coefficient=Decimal("4"), shock_unit="simple_factor_return"
    )
    observation = replace(
        observation, content_digest=scenario_sensitivity_observation_digest(observation)
    )
    capture = replace(
        capture,
        versions=(version,),
        observations=(observation,),
        memberships=(
            replace(
                capture.memberships[0],
                version_digest=version.content_digest,
                observation_digest=observation.content_digest,
            ),
        ),
    )
    shock = ScenarioFactorShock(source=rate(capture, "0").source, size=Decimal("-0.1"))
    result = calculate_scenario(
        input_for(portfolio(("100",), economic="EUR"), content(shock), capture)
    )
    assert available_money(result.summary.post_value).amount == Decimal("60")
    assert result.components[0].sensitivity_uses[0].coefficient == Decimal("4")
    assert result.components[0].effects.factor_ratio.value == Decimal("-0.4")


def test_competing_applicable_sensitivities_are_ambiguous_not_latest_wins() -> None:
    from trading212_domain.scenario_serialization import scenario_sensitivity_observation_digest

    capture = sensitivity_capture()
    alternative = replace(
        capture.observations[0], observation_id=uid(9401), coefficient=Decimal("-9"), revision=2
    )
    alternative = replace(
        alternative, content_digest=scenario_sensitivity_observation_digest(alternative)
    )
    capture = replace(
        capture,
        observations=(*capture.observations, alternative),
        memberships=(
            *capture.memberships,
            replace(
                capture.memberships[0],
                observation_id=alternative.observation_id,
                observation_digest=alternative.content_digest,
            ),
        ),
    )
    result = calculate_scenario(
        input_for(portfolio(("100",), economic="EUR"), content(rate(capture, "0.01")), capture)
    )
    (use,) = result.components[0].sensitivity_uses
    assert use.reason is ScenarioReason.AMBIGUOUS_SENSITIVITY
    assert use.coefficient is None
    assert len(use.candidate_observation_ids) == 2
    assert result.summary.post_value.value is None


def test_sensitivity_response_currency_is_economic_not_reporting_currency() -> None:
    capture = sensitivity_capture()  # EUR local response evidence
    result = calculate_scenario(
        input_for(portfolio(("100",), economic="USD"), content(rate(capture, "0.01")), capture)
    )
    assert available_money(result.components[0].exposure.pre_value).currency == CurrencyCode("EUR")
    assert (
        result.components[0].sensitivity_uses[0].reason
        is ScenarioReason.INCOMPATIBLE_SENSITIVITY_CURRENCY
    )
    assert result.summary.post_value.value is None


@pytest.mark.parametrize("size,available", [("-0.1", False), ("0", True)])
def test_header_cash_never_inherits_reporting_currency_for_fx(size: str, available: bool) -> None:
    from tests.unit.analytics.xray_factories import Builder

    builder = Builder()
    builder.position(uid(20), "100")
    candidate = builder.fund(uid(20), ())
    builder.constituents[0] = replace(candidate, cash_weight=Decimal("1"))
    result = calculate_scenario(input_for(builder.finish(), content(fx(size))))
    (component,) = result.components
    assert component.exposure.explicit_cash
    assert component.exposure.economic_currency.currency is None
    assert component.partition == "uncovered"
    if available:
        assert component.money_basis == "provably_zero_effect"
        assert available_money(result.summary.post_value).amount == Decimal("100")
    else:
        assert result.summary.post_value.value is None
