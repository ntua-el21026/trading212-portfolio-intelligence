"""Deterministic saved-input scenario calculation; no live source lookups or portfolio recalc."""

from __future__ import annotations

from decimal import Decimal

from trading212_domain.errors import fail_validation
from trading212_domain.scenario import (
    MAX_SCENARIO_COMPONENTS,
    ScenarioFxShock,
    ScenarioPriceShock,
    ScenarioReason,
    scenario_rule_key,
)
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_exposure import extract_scenario_exposures
from trading212_domain.scenario_result import (
    ScenarioCalculation,
    ScenarioComponent,
    ScenarioDiagnostic,
)
from trading212_domain.scenario_serialization import (
    encode_scenario_execution,
    scenario_record_bytes,
)
from trading212_domain.scenario_sources import sensitivity_row_count
from trading212_domain.scenario_validation import scenario_bound

from ._premium_numeric import ZERO
from ._scenario_components import component_from_channels, scenario_diagnostic
from ._scenario_matching import resolve_exclusions, resolve_price, selector_match
from ._scenario_sensitivities import SensitivityIndex
from ._scenario_summary import assemble_scenario_calculation
from .scenario_comparison import compare_scenario_results as compare_scenario_results
from .scenario_replay import build_scenario_replay


def validate_scenario_capacity(value: ScenarioExecutionInput) -> None:
    if type(value) is not ScenarioExecutionInput:
        fail_validation("A complete saved scenario execution is required.", field="input")
    sensitivity_row_count(value.sensitivities)
    scenario_bound(len(value.xray_result.terminal_paths) <= MAX_SCENARIO_COMPONENTS, "components")
    encode_scenario_execution(value)
    for shock in value.definition.shocks:
        if (
            isinstance(shock, ScenarioFxShock)
            and shock.selector.currency == value.pins.reporting_currency
            and shock.size != ZERO
        ):
            fail_validation(
                "A nonzero FX shock cannot select the reporting currency.", field="shocks"
            )


def calculate_scenario(value: ScenarioExecutionInput) -> ScenarioCalculation:
    validate_scenario_capacity(value)
    exposures = extract_scenario_exposures(value.xray_input, value.xray_result)
    sources = SensitivityIndex(value)
    components: list[ScenarioComponent] = []
    diagnostics: list[ScenarioDiagnostic] = []
    if value.replay is not None:
        material = build_scenario_replay(value, exposures)
        channels = {item.path_key: item for item in material.channels}
        if len(channels) != len(exposures) or set(channels) != {
            item.path_key for item in exposures
        }:
            fail_validation("Replay channel inventory differs from canonical terminal paths.")
        replay_diagnostics: dict[str, list[ScenarioDiagnostic]] = {}
        for issue in material.proof.diagnostics:
            if issue.path_key is not None:
                replay_diagnostics.setdefault(issue.path_key, []).append(issue)
        for exposure in exposures:
            channel = channels[exposure.path_key]
            component, issues = component_from_channels(
                value,
                exposure,
                price=channel.price,
                factor=ZERO,
                fx=channel.fx,
                reasons=channel.reasons,
                zero_effect_proven=channel.price == ZERO and channel.fx == ZERO,
                diagnostics=tuple(replay_diagnostics.get(exposure.path_key, ())),
            )
            sources.budget.reserve_component(len(scenario_record_bytes(component)))
            components.append(component)
            diagnostics.extend(issues)
        diagnostics.extend(material.proof.diagnostics)
        return assemble_scenario_calculation(
            value, tuple(components), tuple(diagnostics), replay=material.proof
        )
    prices = tuple(item for item in value.definition.shocks if isinstance(item, ScenarioPriceShock))
    fx_shocks = tuple(item for item in value.definition.shocks if isinstance(item, ScenarioFxShock))
    for exposure in exposures:
        exclusion = resolve_exclusions(value.definition.exclusions, exposure)
        price_decision = resolve_price(prices, exposure)
        if exclusion.excluded:
            component, issues = component_from_channels(
                value,
                exposure,
                price=ZERO,
                factor=ZERO,
                fx=ZERO,
                reasons=(None, None, None),
                zero_effect_proven=True,
            )
        else:
            price_reason = (
                None if price_decision.resolved else ScenarioReason.UNCERTAIN_PRICE_PRIORITY
            )
            price_zero = all(item.size == ZERO for item in price_decision.possible)
            price: Decimal | None = (
                price_decision.winner.size
                if price_decision.winner is not None
                else ZERO
                if price_decision.resolved or price_zero
                else None
            )
            fx_matches = tuple(
                item for item in fx_shocks if selector_match(item.selector, exposure) == "match"
            )
            fx_unknown = tuple(
                item for item in fx_shocks if selector_match(item.selector, exposure) == "unknown"
            )
            if len(fx_matches) > 1:
                fail_validation(
                    "Competing scenario FX rules select the same currency.", field="shocks"
                )
            fx_reason = ScenarioReason.MISSING_ECONOMIC_CURRENCY if fx_unknown else None
            fx_zero = not fx_matches and all(item.size == ZERO for item in fx_unknown)
            fx: Decimal | None = (
                ZERO
                if exposure.economic_currency.currency == value.pins.reporting_currency
                else fx_matches[0].size
                if fx_matches
                else ZERO
                if not fx_unknown or fx_zero
                else None
            )
            if fx is not None:
                fx_zero = fx == ZERO
            sensitivity = sources.resolve(exposure, price_decision, fx_matched=bool(fx_matches))
            uncertain = tuple(
                sorted(
                    [scenario_rule_key(item) for item in price_decision.uncertain]
                    + [scenario_rule_key(item) for item in fx_unknown]
                )
            )
            issues_before = list(sensitivity.diagnostics)
            issues_before.extend(
                scenario_diagnostic(
                    exposure,
                    ScenarioReason.UNCERTAIN_PRICE_PRIORITY,
                    rule_key=scenario_rule_key(shock),
                )
                for shock in price_decision.uncertain
            )
            issues_before.extend(
                scenario_diagnostic(
                    exposure,
                    ScenarioReason.MISSING_ECONOMIC_CURRENCY,
                    rule_key=scenario_rule_key(shock),
                )
                for shock in fx_unknown
            )
            component, issues = component_from_channels(
                value,
                exposure,
                price=price,
                factor=sensitivity.value,
                fx=fx,
                reasons=(price_reason, sensitivity.reason, fx_reason),
                zero_effect_proven=price_zero and sensitivity.zero_effect_proven and fx_zero,
                sensitivity_uses=sensitivity.uses,
                sensitivity_confidences=sensitivity.confidences,
                winning_price_rule_key=None
                if price_decision.winner is None
                else scenario_rule_key(price_decision.winner),
                uncertain_rule_keys=uncertain,
                diagnostics=tuple(issues_before),
            )
        sources.budget.reserve_component(len(scenario_record_bytes(component)))
        components.append(component)
        diagnostics.extend(issues)
    return assemble_scenario_calculation(value, tuple(components), tuple(diagnostics))
