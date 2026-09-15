"""Source uncertainty must never become a stronger derived confidence claim."""

from dataclasses import replace
from decimal import Decimal
from typing import Literal

import pytest
from trading212_analytics.scenario import calculate_scenario
from trading212_domain.enums import QualityState
from trading212_domain.scenario import (
    ScenarioExclusion,
    ScenarioInstrumentSelector,
    ScenarioReason,
)
from trading212_domain.sources import ObservationState
from trading212_domain.values import CurrencyCode

from tests.unit.analytics.scenario_factories import (
    content,
    input_for,
    portfolio,
    price,
    rate,
    with_observation,
)
from tests.unit.analytics.test_scenario import available_money, fx
from tests.unit.analytics.xray_factories import Builder, uid
from tests.unit.domain.scenario_factories import sensitivity_capture


@pytest.mark.parametrize("source_confidence", [Decimal("0.2"), Decimal("0.99"), None])
def test_nonzero_sensitivity_uses_the_weaker_confidence_and_preserves_channel_basis(
    source_confidence: Decimal | None,
) -> None:
    capture = sensitivity_capture()
    capture = with_observation(
        capture, replace(capture.observations[0], confidence=source_confidence)
    )
    result = calculate_scenario(
        input_for(
            portfolio(("100",), economic="EUR"),
            content(price(10, "-0.1"), rate(capture, "0.01")),
            capture,
        )
    )
    (component,) = result.components
    original = component.exposure.confidence
    assert original == Decimal("0.8")
    expected = None if source_confidence is None else min(original, source_confidence)
    # 100 * (1 - 0.1 - 2 * 0.01) = 88; confidence changes no arithmetic.
    assert available_money(component.post_value).amount == Decimal("88")
    assert available_money(component.effects.factor).amount == Decimal("-2")
    for metric in (
        component.post_value,
        component.impact,
        component.effects.factor,
        component.rounding_residual,
    ):
        assert metric.confidence == expected
        assert metric.quality is QualityState.ESTIMATED
    assert component.effects.price.confidence == original
    assert component.effects.fx.confidence == original
    # With zero FX, the interaction has no coefficient dependency.
    assert available_money(component.effects.interaction).amount == 0
    assert component.effects.interaction.confidence == original
    assert result.summary.post_value.confidence is None


@pytest.mark.parametrize("mode", ["compounded", "first_order"])
def test_only_compounded_nonzero_fx_interaction_depends_on_sensitivity_confidence(
    mode: Literal["compounded", "first_order"],
) -> None:
    capture = sensitivity_capture()
    capture = with_observation(
        capture,
        replace(capture.observations[0], response_currency=CurrencyCode("USD"), confidence=None),
    )
    result = calculate_scenario(
        input_for(
            portfolio(("100",)),
            content(rate(capture, "0.01"), fx("-0.1"), mode=mode),
            capture,
        )
    )
    (component,) = result.components
    assert available_money(component.effects.fx).amount == Decimal("-10")
    assert component.effects.fx.confidence == Decimal("0.8")
    assert component.post_value.confidence is None
    if mode == "compounded":
        assert available_money(component.post_value).amount == Decimal("88.2")
        assert available_money(component.effects.interaction).amount == Decimal("0.2")
        assert component.effects.interaction.confidence is None
    else:
        assert available_money(component.post_value).amount == Decimal("88")
        assert available_money(component.effects.interaction).amount == 0
        assert component.effects.interaction.confidence == Decimal("0.8")


def test_known_coefficient_confidence_does_not_fill_unknown_exposure_confidence() -> None:
    source = portfolio(("100",), economic="EUR")
    (identity,) = source.entity_evidence
    source = replace(
        source,
        entity_evidence=(replace(identity, evidence=replace(identity.evidence, confidence=None)),),
    )
    capture = sensitivity_capture()
    result = calculate_scenario(input_for(source, content(rate(capture, "0.01")), capture))
    (component,) = result.components
    assert component.exposure.confidence is None
    assert available_money(component.post_value).amount == Decimal("98")
    assert component.post_value.confidence is None
    assert component.effects.factor.confidence is None
    assert component.effects.price.confidence is None


@pytest.mark.parametrize(
    "pre,shock,basis",
    [("100", "0", "provably_zero_effect"), ("0", "0.01", "zero_pre_value")],
)
def test_money_independent_of_a_missing_coefficient_keeps_original_confidence(
    pre: str,
    shock: str,
    basis: str,
) -> None:
    capture = sensitivity_capture()
    capture = with_observation(
        capture,
        replace(
            capture.observations[0],
            state=ObservationState.MISSING,
            coefficient=None,
            reason=ScenarioReason.MISSING_SENSITIVITY,
            quality=QualityState.PARTIAL,
            confidence=None,
        ),
    )
    result = calculate_scenario(
        input_for(portfolio((pre,), economic="EUR"), content(rate(capture, shock)), capture)
    )
    (component,) = result.components
    assert component.partition == "uncovered"
    assert component.money_basis == basis
    assert component.sensitivity_uses[0].coefficient is None
    assert available_money(component.post_value).amount == Decimal(pre)
    assert component.post_value.confidence == Decimal("0.8")
    assert component.post_value.quality is QualityState.PARTIAL


def test_missing_nonzero_coefficient_has_neither_money_nor_confidence() -> None:
    capture = sensitivity_capture()
    capture = with_observation(
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
        input_for(portfolio(("100",), economic="EUR"), content(rate(capture, "0.01")), capture)
    )
    (component,) = result.components
    assert component.post_value.value is None
    assert component.post_value.confidence is None
    assert component.effects.factor.value is None
    assert component.effects.factor.confidence is None


def test_a_known_zero_coefficient_still_requires_its_source_confidence() -> None:
    capture = sensitivity_capture()
    capture = with_observation(
        capture, replace(capture.observations[0], coefficient=Decimal("0"), confidence=None)
    )
    result = calculate_scenario(
        input_for(portfolio(("100",), economic="EUR"), content(rate(capture, "0.01")), capture)
    )
    (component,) = result.components
    assert component.partition == "covered"
    assert available_money(component.post_value).amount == Decimal("100")
    assert component.post_value.confidence is None
    assert component.effects.factor.confidence is None


@pytest.mark.parametrize("kind", ["baseline", "excluded", "cash"])
def test_unused_sensitivity_does_not_reduce_original_money_confidence(kind: str) -> None:
    capture = sensitivity_capture()
    capture = with_observation(capture, replace(capture.observations[0], confidence=None))
    source = portfolio(("100",), economic="EUR")
    definition = content() if kind == "baseline" else content(rate(capture, "0.01"))
    if kind == "excluded":
        definition = replace(
            definition,
            exclusions=(
                ScenarioExclusion(selector=ScenarioInstrumentSelector(instrument_id=uid(10))),
            ),
        )
    elif kind == "cash":
        builder = Builder()
        builder.cash_row("100")
        source = builder.finish()
    result = calculate_scenario(
        input_for(source, definition, None if kind == "baseline" else capture)
    )
    (component,) = result.components
    assert component.sensitivity_uses == ()
    assert component.exposure.confidence is not None
    assert available_money(component.post_value).amount == Decimal("100")
    assert component.post_value.confidence == component.exposure.confidence


def test_source_quality_remains_distinct_from_numeric_confidence() -> None:
    capture = sensitivity_capture()
    capture = with_observation(
        capture,
        replace(
            capture.observations[0], quality=QualityState.UNRECONCILED, confidence=Decimal("0.2")
        ),
    )
    result = calculate_scenario(
        input_for(portfolio(("100",), economic="EUR"), content(rate(capture, "0.01")), capture)
    )
    (component,) = result.components
    assert available_money(component.post_value).amount == Decimal("98")
    assert component.post_value.quality is QualityState.UNRECONCILED
    assert component.post_value.confidence == Decimal("0.2")
