"""Saved-result deltas preserve incompatible sides and never revalue either portfolio."""

from dataclasses import replace
from decimal import Decimal

from trading212_analytics.scenario import calculate_scenario, compare_scenario_results
from trading212_domain.scenario import ScenarioReason
from trading212_domain.scenario_result import ScenarioMoneyMetric
from trading212_domain.values import Money

from tests.unit.analytics.scenario_factories import content, input_for, portfolio, price


def available_money(metric: ScenarioMoneyMetric) -> Money:
    assert metric.value is not None
    return metric.value


def test_changed_owner_shock_compares_on_the_same_retained_economic_basis() -> None:
    source = portfolio(("100",))
    left = calculate_scenario(input_for(source, content(price(10, "-0.2"))))
    right = calculate_scenario(input_for(source, content(price(10, "-0.1"))))
    result = compare_scenario_results(left, right)
    assert result.compatible
    assert result.mismatches == ()
    assert available_money(result.post_value.before).amount == Decimal("80")
    assert available_money(result.post_value.after).amount == Decimal("90")
    assert available_money(result.post_value.difference).amount == Decimal("10")
    assert available_money(result.components[0].impact.difference).amount == Decimal("10")


def test_formula_change_preserves_each_saved_value_with_unavailable_deltas() -> None:
    from tests.unit.analytics.test_scenario import fx

    source = portfolio(("100",))
    left = calculate_scenario(input_for(source, content(price(10, "-0.2"), fx("-0.1"))))
    right = calculate_scenario(
        input_for(source, content(price(10, "-0.2"), fx("-0.1"), mode="first_order"))
    )
    result = compare_scenario_results(left, right)
    assert not result.compatible
    assert [item.field for item in result.mismatches] == ["method"]
    assert available_money(result.post_value.before).amount == Decimal("72")
    assert available_money(result.post_value.after).amount == Decimal("70")
    assert result.post_value.difference.value is None
    assert result.post_value.difference.reason is ScenarioReason.INCOMPATIBLE_BASIS
    assert result.components[0].post_value.difference.value is None


def test_changed_retained_partition_has_no_assumed_component_alignment() -> None:
    left = calculate_scenario(input_for(portfolio(("100",)), content(price(10, "-0.2"))))
    right = calculate_scenario(input_for(portfolio(("80", "20")), content(price(10, "-0.2"))))
    result = compare_scenario_results(left, right)
    assert not result.compatible
    assert {item.field for item in result.mismatches} == {"holdings_basis", "holdings_partition"}
    assert available_money(result.post_value.before).amount == Decimal("80")
    assert available_money(result.post_value.after).amount == Decimal("84")
    assert all(item.post_value.difference.value is None for item in result.components)
    added = next(item for item in result.components if item.post_value.before.value is None)
    assert available_money(added.post_value.after).amount == Decimal("20")


def test_saved_comparison_has_no_dependency_on_new_source_availability() -> None:
    source = portfolio(("100",))
    left = calculate_scenario(input_for(source, content(price(10, "-0.2"))))
    right = calculate_scenario(input_for(source, content(price(10, "-0.1"))))
    # Operational expiry belongs to execution, absent from saved result comparison.
    copied = replace(left)
    assert compare_scenario_results(copied, right) == compare_scenario_results(left, right)
