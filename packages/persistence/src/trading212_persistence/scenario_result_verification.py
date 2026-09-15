"""Bind retained scenario outputs to exact saved inputs without recalculating the scenario."""

from trading212_analytics._premium_numeric import arithmetic, q18
from trading212_analytics._scenario_components import ratio_metric, scenario_quality
from trading212_analytics._scenario_matching import (
    resolve_exclusions,
    resolve_price,
    selector_match,
)
from trading212_analytics._scenario_sensitivities import SensitivityIndex
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.scenario import (
    ScenarioAssumption,
    ScenarioFactorShock,
    ScenarioFxShock,
    ScenarioPriceShock,
    ScenarioRateShock,
    ScenarioReason,
    scenario_exclusion_key,
    scenario_rule_key,
)
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_exposure import extract_scenario_exposures
from trading212_domain.scenario_result import (
    ScenarioCalculation,
    ScenarioComponent,
    ScenarioMoneyMetric,
)
from trading212_domain.scenario_serialization import encode_scenario_execution
from trading212_domain.scenario_sources import sensitivity_row_count
from trading212_domain.sources import ObservationState

from .scenario_store_types import ScenarioStorageError
from .scenario_store_types import ScenarioStorageErrorCode as Code


def _require(condition: bool) -> None:
    if not condition:
        raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)


def _sensitivity_membership(
    inputs: ScenarioExecutionInput, component: ScenarioComponent, index: SensitivityIndex
) -> None:
    shocks = {
        scenario_rule_key(item): item
        for item in inputs.definition.shocks
        if isinstance(item, (ScenarioRateShock, ScenarioFactorShock))
    }
    exposure = component.exposure
    not_applicable = exposure.instrument.state == exposure.entity.state == "not_applicable"
    required = set() if component.partition == "excluded" or not_applicable else set(shocks)
    _require({item.rule_key for item in component.sensitivity_uses} == required)
    for use in component.sensitivity_uses:
        shock = shocks[use.rule_key]
        version = index.versions[shock.source.version_id]
        _require(
            use.version_id == version.version_id
            and use.driver == version.driver
            and use.shock_size == shock.size
        )
        # These indexed predicates inspect captured identities and dates only. They do not
        # choose a new source revision, calculate channels, or query a provider/history service.
        definite_groups, uncertain_groups = index._candidates(version.version_id, exposure)
        candidates = [item for group in (*definite_groups, *uncertain_groups) for item in group]
        _require(
            tuple(sorted(item.observation_id for item in candidates))
            == use.candidate_observation_ids
        )
        eligible = [
            item for group in definite_groups for item in group if index._observation_eligible(item)
        ]
        uncertain = [
            item
            for group in uncertain_groups
            for item in group
            if index._observation_eligible(item)
        ]
        selected = (
            eligible[0]
            if index._version_eligible(version) and len(eligible) == 1 and not uncertain
            else None
        )
        _require(use.observation_id == (None if selected is None else selected.observation_id))
        _require(use.coefficient == (None if selected is None else selected.coefficient))
        price = resolve_price(
            tuple(
                item for item in inputs.definition.shocks if isinstance(item, ScenarioPriceShock)
            ),
            exposure,
        )
        fx_matched = any(
            isinstance(item, ScenarioFxShock) and selector_match(item.selector, exposure) == "match"
            for item in inputs.definition.shocks
        )
        reason = index._equivalence(version, exposure, price, fx_matched)
        if not index._version_eligible(version):
            reason = reason or ScenarioReason.MISSING_SENSITIVITY
        elif len(eligible) > 1 or uncertain:
            reason = reason or ScenarioReason.AMBIGUOUS_SENSITIVITY
        elif selected is None:
            reason = reason or ScenarioReason.MISSING_SENSITIVITY
        elif selected.state is not ObservationState.AVAILABLE:
            reason = reason or selected.reason or ScenarioReason.MISSING_SENSITIVITY
        elif (
            selected.response_basis != "local_economic_value" or selected.response_currency is None
        ):
            reason = reason or ScenarioReason.UNSUPPORTED_SENSITIVITY
        elif exposure.economic_currency.currency is None:
            reason = reason or ScenarioReason.MISSING_ECONOMIC_CURRENCY
        elif selected.response_currency != exposure.economic_currency.currency:
            reason = reason or ScenarioReason.INCOMPATIBLE_SENSITIVITY_CURRENCY
        _require(use.reason == reason)
        zero = use.shock_size == 0 and all(
            item.state is not ObservationState.UNSUPPORTED and item.response_basis != "fx_inclusive"
            for item in (*eligible, *uncertain)
        )
        _require((use.effect_ratio.value is not None) == (reason is None or zero))
        _require(
            use.effect_ratio
            == ratio_metric(
                use.effect_ratio.value,
                quality=scenario_quality(
                    version.quality,
                    selected.quality if selected is not None else QualityState.PARTIAL,
                    QualityState.ESTIMATED,
                ),
                reason=reason or ScenarioReason.MISSING_SENSITIVITY,
            )
        )
        if use.reason is None:
            _require(
                selected is not None
                and selected.state is ObservationState.AVAILABLE
                and selected.response_basis == "local_economic_value"
                and selected.response_currency == exposure.economic_currency.currency
                and use.coefficient is not None
            )
            assert use.coefficient is not None
            with arithmetic():
                _require(use.effect_ratio.value == q18(use.coefficient * use.shock_size))
        elif use.effect_ratio.value is not None:
            _require(
                use.shock_size == 0
                and use.effect_ratio.value == 0
                and all(
                    item.state is not ObservationState.UNSUPPORTED
                    and item.response_basis != "fx_inclusive"
                    for item in (*eligible, *uncertain)
                )
            )


def verify_scenario_result_inputs(
    inputs: ScenarioExecutionInput, result: ScenarioCalculation
) -> None:
    """Bind the original partition and coefficient proof without full formula replay."""
    try:
        encode_scenario_execution(inputs)
        _require(
            type(result) is ScenarioCalculation
            and result.input_digest == inputs.input_digest
            and result.pins == inputs.pins
            and result.definition == inputs.definition
            and result.valuation_at == inputs.xray_input.valuation_at.value
            and result.sensitivity_source_row_count == sensitivity_row_count(inputs.sensitivities)
        )
        exposures = extract_scenario_exposures(inputs.xray_input, inputs.xray_result)
        _require(tuple(item.exposure for item in result.components) == exposures)
        upstream = inputs.xray_result.portfolio_summary.total
        _require(
            result.upstream_portfolio_value
            == ScenarioMoneyMetric(
                value=upstream.value,
                quality=upstream.quality,
                reason=ScenarioReason.MISSING_VALUE if upstream.value is None else None,
                confidence=upstream.confidence,
                source_reference_ids=upstream.source_reference_ids,
            )
        )
        _require(
            result.upstream_residual_keys
            == tuple(sorted(item.key for item in inputs.xray_result.residuals))
        )
        assumptions = {
            ScenarioAssumption.CANONICAL_TERMINAL_BASIS,
            ScenarioAssumption.NO_LISTING_CURRENCY_INFERENCE,
            ScenarioAssumption.FIRST_ORDER_FORMULA
            if inputs.definition.mode == "first_order"
            else ScenarioAssumption.COMPOUNDED_FORMULA,
        }
        kinds = {item.kind for item in inputs.definition.shocks}
        if kinds:
            assumptions.add(ScenarioAssumption.OWNER_DEFINED_SHOCKS)
        if "price" in kinds and kinds & {"rate", "factor"}:
            assumptions.add(ScenarioAssumption.ADDITIONAL_PRICE_COMPONENT)
        if result.summary.uncovered_count:
            assumptions.add(ScenarioAssumption.KNOWN_ONLY_SUBTOTALS)
        if inputs.replay is not None:
            assumptions.add(ScenarioAssumption.COUNTERFACTUAL_REPLAY)
            if inputs.replay.selection.knowledge_basis == "retrospective":
                assumptions.add(ScenarioAssumption.RETROSPECTIVE_MARKET_KNOWLEDGE)
            if any(item.exposure.explicit_cash for item in result.components):
                assumptions.add(ScenarioAssumption.FIXED_CASH_BALANCE_REPLAY)
        _require(set(result.assumptions) == assumptions)
        prices = tuple(
            item for item in inputs.definition.shocks if isinstance(item, ScenarioPriceShock)
        )
        fx_rules = tuple(
            item for item in inputs.definition.shocks if isinstance(item, ScenarioFxShock)
        )
        shock_keys = {scenario_rule_key(item) for item in inputs.definition.shocks}
        exclusions = {scenario_exclusion_key(item) for item in inputs.definition.exclusions}
        index = SensitivityIndex(inputs)
        for component in result.components:
            matched = resolve_exclusions(inputs.definition.exclusions, component.exposure)
            _require((component.partition == "excluded") == matched.excluded)
            _require(
                component.matching_exclusion_keys
                == tuple(sorted(scenario_exclusion_key(item) for item in matched.matched))
            )
            price = resolve_price(prices, component.exposure)
            expected_winner = (
                None
                if matched.excluded or price.winner is None
                else scenario_rule_key(price.winner)
            )
            _require(component.winning_price_rule_key == expected_winner)
            uncertain: set[str] = set()
            if not matched.excluded:
                uncertain.update(scenario_exclusion_key(item) for item in matched.uncertain)
                uncertain.update(scenario_rule_key(item) for item in price.uncertain)
                uncertain.update(
                    scenario_rule_key(item)
                    for item in fx_rules
                    if selector_match(item.selector, component.exposure) == "unknown"
                )
            _require(set(component.uncertain_rule_keys) == uncertain)
            _sensitivity_membership(inputs, component, index)
        paths = {item.exposure.path_key for item in result.components}
        for diagnostic in result.diagnostics:
            _require(diagnostic.path_key is None or diagnostic.path_key in paths)
            _require(diagnostic.rule_key is None or diagnostic.rule_key in shock_keys | exclusions)
        _require((inputs.replay is None) == (result.replay is None))
        if inputs.replay is not None and result.replay is not None:
            from .scenario_result_replay_proof import verify_scenario_replay_proof

            verify_scenario_replay_proof(inputs, result)
    except DomainError as error:
        code = (
            Code.INPUT_BOUND_EXCEEDED
            if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
            else Code.SCENARIO_UNAVAILABLE
        )
        raise ScenarioStorageError(code) from None
