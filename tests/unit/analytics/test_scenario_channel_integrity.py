"""Independent Q18 envelopes and retained scenario quality/availability regressions."""

from dataclasses import replace
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from typing import Literal

import pytest
from trading212_analytics._scenario_components import component_from_channels
from trading212_analytics._scenario_summary import assemble_scenario_calculation
from trading212_analytics.scenario import calculate_scenario, compare_scenario_results
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.scenario import ScenarioReason
from trading212_domain.scenario_exposure import extract_scenario_exposures
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_domain.scenario_result_validation import validate_scenario_summary_money
from trading212_domain.values import Money

from tests.unit.analytics.scenario_factories import content, input_for, portfolio, price
from tests.unit.analytics.test_scenario_replay import _execution, _history

D = Decimal
pytestmark = pytest.mark.unit


def _result() -> ScenarioCalculation:
    return calculate_scenario(input_for(portfolio(("100",)), content(price(10, "-0.2"))))


def test_reconciling_channel_money_cannot_contradict_its_ratio() -> None:
    component = _result().components[0]
    assert component.post_value.value is not None
    currency = component.post_value.value.currency
    with pytest.raises(DomainError, match="retained ratio"):
        replace(
            component,
            effects=replace(
                component.effects,
                price=replace(component.effects.price, value=Money(D(-10), currency)),
            ),
            post_value=replace(component.post_value, value=Money(D(90), currency)),
            impact=replace(component.impact, value=Money(D(-10), currency)),
        )


@pytest.mark.parametrize("ratio", ["-1.000000000000000001", "5.000000000000000001"])
def test_component_channel_ratio_bounds_are_retained(ratio: str) -> None:
    component = _result().components[0]
    with pytest.raises(DomainError, match="ratio exceeds"):
        replace(
            component,
            effects=replace(
                component.effects,
                price_ratio=replace(component.effects.price_ratio, value=D(ratio)),
            ),
        )


def test_partial_known_channel_is_checked_before_unavailable_post_return() -> None:
    execution = input_for(portfolio(("100",)), content())
    exposure = extract_scenario_exposures(execution.xray_input, execution.xray_result)[0]
    component, _ = component_from_channels(
        execution,
        exposure,
        price=D("-.2"),
        factor=None,
        fx=D(0),
        reasons=(None, ScenarioReason.MISSING_SENSITIVITY, None),
        zero_effect_proven=False,
    )
    assert component.post_value.value is None
    assert component.effects.price.value is not None
    assert exposure.pre_value.value is not None
    with pytest.raises(DomainError, match="retained ratio"):
        replace(
            component,
            effects=replace(
                component.effects,
                price=replace(
                    component.effects.price, value=Money(D(-10), exposure.pre_value.value.currency)
                ),
            ),
        )


def test_missing_original_money_never_creates_known_channel_money() -> None:
    execution = input_for(portfolio(("100",)), content())
    exposure = extract_scenario_exposures(execution.xray_input, execution.xray_result)[0]
    exposure = replace(
        exposure,
        pre_value=replace(
            exposure.pre_value,
            value=None,
            quality=QualityState.PARTIAL,
            reason=ScenarioReason.MISSING_VALUE,
        ),
    )
    component, _ = component_from_channels(
        execution,
        exposure,
        price=D("-.2"),
        factor=D(0),
        fx=D(0),
        reasons=(None, None, None),
        zero_effect_proven=False,
    )
    assert component.effects.price.value is None
    with pytest.raises(DomainError, match="retained components"):
        replace(
            component,
            effects=replace(
                component.effects,
                price=replace(component.effects.price, value=Money.parse("1", "EUR"), reason=None),
            ),
        )


@pytest.mark.parametrize("mode", ["first_order", "compounded"])
def test_interaction_requires_the_declared_formula(
    mode: Literal["first_order", "compounded"],
) -> None:
    result = calculate_scenario(
        input_for(portfolio(("100",)), content(price(10, "-0.2"), mode=mode))
    )
    component = result.components[0]
    assert component.post_value.value is not None
    currency = component.post_value.value.currency
    changed = replace(
        component,
        effects=replace(
            component.effects,
            interaction=replace(component.effects.interaction, value=Money(D(10), currency)),
        ),
        post_value=replace(component.post_value, value=Money(D(90), currency)),
        impact=replace(component.impact, value=Money(D(-10), currency)),
    )
    # Interaction needs the enclosing mode; component identities themselves still reconcile.
    with pytest.raises(DomainError, match=r"interaction|retained components"):
        replace(result, components=(changed,))


def _q_fraction(value: Fraction) -> Decimal:
    with localcontext(Context(prec=180)):
        return (D(value.numerator) / D(value.denominator)).quantize(D("1e-18"))


def test_large_original_value_preserves_independently_rounded_negative_channels() -> None:
    execution = input_for(portfolio(("10000000000000000000",)), content())
    exposure = extract_scenario_exposures(execution.xray_input, execution.xray_result)[0]
    p, f, fx = D("-.12345678912345678949"), D(".00000000000000000049"), D("-.33333333333333333349")
    component, diagnostics = component_from_channels(
        execution,
        exposure,
        price=p,
        factor=f,
        fx=fx,
        reasons=(None, None, None),
        zero_effect_proven=False,
    )
    result = assemble_scenario_calculation(execution, (component,), diagnostics)
    original = Fraction(10**19)
    expected_post = original * (1 + Fraction(p) + Fraction(f)) * (1 + Fraction(fx))
    expected_interaction = original * (Fraction(p) + Fraction(f)) * Fraction(fx)
    assert component.post_value.value is not None
    assert component.effects.interaction.value is not None
    assert component.post_value.value.amount == _q_fraction(expected_post)
    assert component.effects.interaction.value.amount == _q_fraction(expected_interaction)
    assert component.effects.price.value is not None
    with localcontext(Context(prec=180)):
        assert component.effects.price_ratio.value is not None
        assert abs(
            component.effects.price.value.amount - D(10**19) * component.effects.price_ratio.value
        ) == D("4.9")
    validate_scenario_summary_money(result)


def test_negative_replay_thirds_remain_valid_after_ratio_publication() -> None:
    result = calculate_scenario(_execution(_history(prices=("3", "3", "3", "2"))))
    component = result.components[0]
    assert component.effects.price_ratio.value == D("-.333333333333333333")
    assert component.effects.price.value is not None
    assert component.effects.price.value.amount == _q_fraction(Fraction(-100, 3))
    assert component.post_value.value is not None
    assert component.post_value.value.amount == D(60)


@pytest.mark.parametrize("field", ["money", "ratio", "post", "summary"])
def test_derived_results_cannot_be_relabelled_fresh(field: str) -> None:
    result = _result()
    component = result.components[0]
    with pytest.raises(DomainError, match="quality"):
        if field == "money":
            replace(
                component,
                effects=replace(
                    component.effects,
                    price=replace(component.effects.price, quality=QualityState.FRESH),
                ),
            )
        elif field == "ratio":
            replace(
                component,
                effects=replace(
                    component.effects,
                    price_ratio=replace(component.effects.price_ratio, quality=QualityState.FRESH),
                ),
            )
        elif field == "post":
            replace(component, post_value=replace(component.post_value, quality=QualityState.FRESH))
        else:
            replace(
                result,
                summary=replace(
                    result.summary,
                    post_value=replace(result.summary.post_value, quality=QualityState.FRESH),
                ),
            )


def test_failed_original_quality_survives_component_summary_and_comparison() -> None:
    execution = input_for(portfolio(("100",)), content())
    exposure = extract_scenario_exposures(execution.xray_input, execution.xray_result)[0]
    exposure = replace(exposure, pre_value=replace(exposure.pre_value, quality=QualityState.FAILED))
    component, diagnostics = component_from_channels(
        execution,
        exposure,
        price=D("-.2"),
        factor=None,
        fx=D(0),
        reasons=(None, ScenarioReason.MISSING_SENSITIVITY, None),
        zero_effect_proven=False,
    )
    result = assemble_scenario_calculation(execution, (component,), diagnostics)
    assert component.post_value.quality is QualityState.FAILED
    assert result.summary.impact.quality is QualityState.FAILED
    assert result.summary.effects.price_ratio.quality is QualityState.FAILED
    comparison = compare_scenario_results(result, result)
    assert comparison.post_value.difference.value is None
    assert comparison.post_value.difference.quality is QualityState.FAILED


def test_observed_original_and_upstream_quality_remain_fresh() -> None:
    result = _result()
    assert result.components[0].exposure.pre_value.quality is QualityState.FRESH
    assert result.upstream_portfolio_value.quality is QualityState.FRESH
    assert result.summary.post_value.quality is QualityState.ESTIMATED


@pytest.mark.parametrize("mode", ["first_order", "compounded"])
def test_zero_original_money_cannot_hide_definitely_negative_multiplier(
    mode: Literal["first_order", "compounded"],
) -> None:
    result = calculate_scenario(input_for(portfolio(("0",)), content(mode=mode)))
    component = result.components[0]
    effects = replace(
        component.effects,
        price_ratio=replace(component.effects.price_ratio, value=D("-.8")),
        factor_ratio=replace(component.effects.factor_ratio, value=D("-.8")),
        fx_ratio=replace(component.effects.fx_ratio, value=D(0)),
    )
    changed = replace(component, effects=effects)
    with pytest.raises(DomainError, match="multiplier"):
        replace(result, components=(changed,))


def test_zero_raw_multiplier_can_have_negative_rounded_combined_multiplier() -> None:
    execution = input_for(portfolio(("0",)), content(mode="first_order"))
    exposure = extract_scenario_exposures(execution.xray_input, execution.xray_result)[0]
    # Exact sum is -1; independently rounded channels sum to -1 - one quantum.
    p = f = D("-.4000000000000000006")
    fx = D("-.1999999999999999988")
    component, diagnostics = component_from_channels(
        execution,
        exposure,
        price=p,
        factor=f,
        fx=fx,
        reasons=(None, None, None),
        zero_effect_proven=False,
    )
    result = assemble_scenario_calculation(execution, (component,), diagnostics)
    assert result.summary.post_value.value is not None
    assert result.summary.post_value.value.amount == 0
