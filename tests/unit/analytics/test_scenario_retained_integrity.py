"""Saved scenario sums cannot be forged by supplying a matching new content hash."""

import hashlib
import json
from dataclasses import replace
from decimal import Context, Decimal, Inexact, Rounded, localcontext

import pytest
from trading212_analytics.scenario import calculate_scenario, compare_scenario_results
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.scenario import ScenarioReason
from trading212_domain.scenario_serialization import (
    canonical_scenario_bytes,
    scenario_result_digest,
    scenario_result_from_json,
)
from trading212_domain.sources import ObservationState
from trading212_domain.values import Money

from tests.unit.analytics.scenario_factories import (
    content,
    input_for,
    portfolio,
    price,
    rate,
    with_observation,
)
from tests.unit.domain.scenario_factories import sensitivity_capture


def test_retained_definition_must_match_its_original_source_pin() -> None:
    result = calculate_scenario(input_for(portfolio(("100",)), content(price(10, "-0.2"))))
    with pytest.raises(DomainError, match="definition differs from its source pin"):
        replace(result, definition=replace(result.definition, name="Changed after capture"))
    raw = json.loads(canonical_scenario_bytes(result))
    raw["definition"]["name"] = "Changed after capture"
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(b"t212pi.scenario.result.v1\0" + payload).hexdigest()
    with pytest.raises(DomainError, match="definition differs from its source pin"):
        scenario_result_from_json(payload, expected_digest=digest)


@pytest.mark.parametrize(
    "field",
    [
        "terminal_pre_value",
        "covered_pre_value",
        "uncovered_pre_value",
        "excluded_pre_value",
        "covered_post_value",
        "excluded_post_value",
        "provably_unchanged_uncovered_value",
        "post_value",
        "impact",
        "rounding_residual",
        "component_sum_residual",
    ],
)
def test_retained_summary_rejects_money_unrelated_to_components(field: str) -> None:
    result = calculate_scenario(input_for(portfolio(("100",)), content(price(10, "-0.2"))))
    raw = json.loads(canonical_scenario_bytes(result))
    raw["summary"][field]["value"]["amount"] = "123"
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(b"t212pi.scenario.result.v1\0" + payload).hexdigest()
    with pytest.raises(DomainError, match="retained components"):
        scenario_result_from_json(payload, expected_digest=digest)


@pytest.mark.parametrize("kind", ["post", "negative", "residual", "channel", "ratio", "upstream"])
def test_retained_component_and_ratio_consistency(kind: str) -> None:
    result = calculate_scenario(input_for(portfolio(("100",)), content(price(10, "-0.2"))))
    raw = json.loads(canonical_scenario_bytes(result))
    component = raw["components"][0]
    if kind == "post":
        component["post_value"]["value"]["amount"] = "81"
    elif kind == "negative":
        component["post_value"]["value"]["amount"] = "-1"
    elif kind == "residual":
        # Preserve every arithmetic identity while trying to hide 100 EUR as rounding.
        component["effects"]["price"]["value"]["amount"] = "-120"
        component["rounding_residual"]["value"]["amount"] = "100"
    elif kind == "channel":
        raw["summary"]["effects"]["price"]["value"]["amount"] = "-19"
    elif kind == "ratio":
        raw["summary"]["effects"]["price_ratio"]["value"] = "0"
    else:
        raw["upstream_partition_difference"]["value"]["amount"] = "100"
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(b"t212pi.scenario.result.v1\0" + payload).hexdigest()
    with pytest.raises(DomainError) as caught:
        scenario_result_from_json(payload, expected_digest=digest)
    assert "digest" not in caught.value.message.lower()


def test_comparison_difference_is_bound_to_saved_sides() -> None:
    left = calculate_scenario(input_for(portfolio(("100",)), content(price(10, "-0.2"))))
    right = calculate_scenario(input_for(portfolio(("100",)), content(price(10, "-0.1"))))
    comparison = compare_scenario_results(left, right)
    bad = replace(comparison.post_value.difference, value=Money.parse("11", "EUR"))
    with pytest.raises(DomainError):
        replace(comparison, post_value=replace(comparison.post_value, difference=bad))
    other_currency = replace(bad, value=Money.parse("10", "USD"))
    with pytest.raises(DomainError):
        replace(comparison, post_value=replace(comparison.post_value, difference=other_currency))


def test_retained_result_validation_preserves_hostile_decimal_context() -> None:
    value = input_for(portfolio(("100",)), content(price(10, "-0.123456789123456789")))
    expected = calculate_scenario(value)
    payload, digest = canonical_scenario_bytes(expected), scenario_result_digest(expected)
    with localcontext(Context(prec=3, Emin=-9, Emax=9)) as hostile:
        for signal in hostile.traps:
            hostile.traps[signal] = True
        hostile.flags[Inexact] = hostile.flags[Rounded] = True
        before = hostile.copy()
        assert calculate_scenario(value) == expected
        assert scenario_result_from_json(payload, expected_digest=digest) == expected
        assert hostile.prec == before.prec and hostile.traps == before.traps
        assert hostile.flags == before.flags
    assert expected.summary.effects.price_ratio.value == Decimal("-0.123456789123456789")


@pytest.mark.parametrize("field", ["coefficient", "shock", "effect", "missing"])
def test_resolved_sensitivity_product_is_bound_in_replace_and_retained_codec(field: str) -> None:
    capture = sensitivity_capture()
    result = calculate_scenario(
        input_for(portfolio(("100",), economic="EUR"), content(rate(capture, ".01")), capture)
    )
    use = result.components[0].sensitivity_uses[0]
    assert use.coefficient == Decimal(-2) and use.effect_ratio.value == Decimal("-.02")
    with pytest.raises(DomainError, match="retained product"):
        if field == "coefficient":
            replace(use, coefficient=Decimal(-3))
        elif field == "shock":
            replace(use, shock_size=Decimal(".02"))
        elif field == "effect":
            replace(use, effect_ratio=replace(use.effect_ratio, value=Decimal("-.03")))
        else:
            replace(
                use,
                effect_ratio=replace(
                    use.effect_ratio,
                    value=None,
                    quality=QualityState.PARTIAL,
                    reason=ScenarioReason.MISSING_SENSITIVITY,
                ),
            )
    raw = json.loads(canonical_scenario_bytes(result))
    stored = raw["components"][0]["sensitivity_uses"][0]
    if field == "coefficient":
        stored["coefficient"] = "-3"
    elif field == "shock":
        stored["shock_size"] = "0.02"
    elif field == "effect":
        stored["effect_ratio"]["value"] = "-0.03"
    else:
        stored["effect_ratio"].update(
            value=None, quality="partial", reason=ScenarioReason.MISSING_SENSITIVITY.value
        )
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(b"t212pi.scenario.result.v1\0" + payload).hexdigest()
    with pytest.raises(DomainError, match="retained product"):
        scenario_result_from_json(payload, expected_digest=digest)


@pytest.mark.parametrize(
    "coefficient,expected",
    [
        ("0.000000000000000001", "0"),
        ("0.000000000000000003", "0.000000000000000002"),
        ("-0.000000000000000003", "-0.000000000000000002"),
    ],
)
def test_resolved_sensitivity_product_preserves_half_even_ties_in_hostile_context(
    coefficient: str, expected: str
) -> None:
    capture = sensitivity_capture()
    capture = with_observation(
        capture, replace(capture.observations[0], coefficient=Decimal(coefficient))
    )
    inputs = input_for(portfolio(("100",), economic="EUR"), content(rate(capture, ".5")), capture)
    result = calculate_scenario(inputs)
    payload, digest = canonical_scenario_bytes(result), scenario_result_digest(result)
    with localcontext(Context(prec=3, Emin=-9, Emax=9)) as hostile:
        for signal in hostile.traps:
            hostile.traps[signal] = True
        hostile.flags[Inexact] = hostile.flags[Rounded] = True
        before = hostile.copy()
        assert calculate_scenario(inputs) == result
        assert scenario_result_from_json(payload, expected_digest=digest) == result
        assert hostile.prec == before.prec and hostile.traps == before.traps
        assert hostile.flags == before.flags
    assert result.components[0].sensitivity_uses[0].effect_ratio.value == Decimal(expected)


def test_unresolved_zero_shock_retains_missing_coefficient_and_zero_effect() -> None:
    capture = sensitivity_capture()
    capture = with_observation(
        capture,
        replace(
            capture.observations[0],
            coefficient=None,
            state=ObservationState.MISSING,
            quality=QualityState.PARTIAL,
            reason=ScenarioReason.MISSING_SENSITIVITY,
        ),
    )
    result = calculate_scenario(
        input_for(portfolio(("100",), economic="EUR"), content(rate(capture, "0")), capture)
    )
    use = result.components[0].sensitivity_uses[0]
    assert use.coefficient is None and use.reason is ScenarioReason.MISSING_SENSITIVITY
    assert use.effect_ratio.value == 0
    assert (
        scenario_result_from_json(
            canonical_scenario_bytes(result), expected_digest=scenario_result_digest(result)
        )
        == result
    )
