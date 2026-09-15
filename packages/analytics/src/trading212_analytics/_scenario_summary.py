"""Conservative original-value partitions and separate publication residuals."""

from __future__ import annotations

from trading212_domain.enums import QualityState
from trading212_domain.scenario import ScenarioAssumption, ScenarioReason
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import (
    ScenarioCalculation,
    ScenarioChannelEffects,
    ScenarioComponent,
    ScenarioDiagnostic,
    ScenarioMoneyMetric,
    ScenarioPartitionSummary,
    ScenarioRatioMetric,
    ScenarioReplayProof,
)
from trading212_domain.scenario_serialization import canonical_scenario_bytes
from trading212_domain.scenario_sources import sensitivity_row_count

from ._premium_numeric import ZERO, arithmetic
from ._scenario_components import money_metric, ratio_metric, scenario_quality


def assemble_scenario_calculation(
    execution: ScenarioExecutionInput,
    components: tuple[ScenarioComponent, ...],
    diagnostics: tuple[ScenarioDiagnostic, ...],
    *,
    replay: ScenarioReplayProof | None = None,
) -> ScenarioCalculation:
    currency = execution.pins.reporting_currency
    components = tuple(sorted(components, key=lambda item: item.exposure.path_key))
    covered = tuple(item for item in components if item.partition == "covered")
    uncovered = tuple(item for item in components if item.partition == "uncovered")
    excluded = tuple(item for item in components if item.partition == "excluded")

    def total(values: tuple[ScenarioMoneyMetric, ...]) -> ScenarioMoneyMetric:
        quality = scenario_quality(QualityState.ESTIMATED, *(item.quality for item in values))
        if any(item.value is None for item in values):
            return money_metric(None, currency, quality=quality)
        with arithmetic():
            amount = sum((item.value.amount for item in values if item.value is not None), ZERO)
        return money_metric(amount, currency, quality=quality)

    pre = total(tuple(item.exposure.pre_value for item in components))
    post = total(tuple(item.post_value for item in components))
    aggregate_quality = scenario_quality(pre.quality, post.quality)
    impact = money_metric(None, currency, quality=aggregate_quality)
    component_residual = money_metric(
        None,
        currency,
        quality=scenario_quality(aggregate_quality, *(item.impact.quality for item in components)),
    )
    if pre.value is not None and post.value is not None:
        with arithmetic():
            impact = money_metric(
                post.value.amount - pre.value.amount,
                currency,
                quality=scenario_quality(pre.quality, post.quality),
            )
            component_impacts = total(tuple(item.impact for item in components))
            if component_impacts.value is not None:
                assert impact.value is not None
                component_residual = money_metric(
                    impact.value.amount - component_impacts.value.amount,
                    currency,
                    quality=scenario_quality(impact.quality, component_impacts.quality),
                )
    channels = tuple(
        total(tuple(getattr(item.effects, name) for item in components))
        for name in ("price", "factor", "fx", "interaction")
    )

    def ratio(value: ScenarioMoneyMetric) -> ScenarioRatioMetric:
        quality = scenario_quality(pre.quality, value.quality)
        if pre.value is None or value.value is None:
            return ratio_metric(None, quality=quality, reason=ScenarioReason.UNCERTAIN_MONEY)
        if pre.value.amount == ZERO:
            return ratio_metric(None, quality=quality, reason=ScenarioReason.ZERO_DENOMINATOR)
        with arithmetic():
            return ratio_metric(value.value.amount / pre.value.amount, quality=quality)

    effects = ScenarioChannelEffects(
        price_ratio=ratio(channels[0]),
        factor_ratio=ratio(channels[1]),
        fx_ratio=ratio(channels[2]),
        price=channels[0],
        factor=channels[1],
        fx=channels[2],
        interaction=channels[3],
    )
    summary = ScenarioPartitionSummary(
        terminal_pre_value=pre,
        covered_pre_value=total(tuple(item.exposure.pre_value for item in covered)),
        uncovered_pre_value=total(tuple(item.exposure.pre_value for item in uncovered)),
        excluded_pre_value=total(tuple(item.exposure.pre_value for item in excluded)),
        covered_count=len(covered),
        uncovered_count=len(uncovered),
        excluded_count=len(excluded),
        missing_pre_value_count=sum(item.exposure.pre_value.value is None for item in components),
        uncertain_money_count=sum(item.post_value.value is None for item in components),
        covered_post_value=total(tuple(item.post_value for item in covered)),
        excluded_post_value=total(tuple(item.post_value for item in excluded)),
        provably_unchanged_uncovered_value=total(
            tuple(
                item.post_value
                for item in uncovered
                if item.money_basis in ("zero_pre_value", "provably_zero_effect")
            )
        ),
        post_value=post,
        impact=impact,
        effects=effects,
        rounding_residual=total(tuple(item.rounding_residual for item in components)),
        component_sum_residual=component_residual,
    )
    upstream = execution.xray_result.portfolio_summary.total
    original = ScenarioMoneyMetric(
        value=upstream.value,
        quality=upstream.quality,
        reason=ScenarioReason.MISSING_VALUE if upstream.value is None else None,
        confidence=upstream.confidence,
        source_reference_ids=upstream.source_reference_ids,
    )
    difference = money_metric(
        None, currency, quality=scenario_quality(pre.quality, original.quality)
    )
    if pre.value is not None and original.value is not None:
        with arithmetic():
            # Positive means the terminal sum exceeds the separately published upstream total.
            difference = money_metric(
                pre.value.amount - original.value.amount,
                currency,
                quality=scenario_quality(pre.quality, original.quality),
            )
    assumptions = {
        ScenarioAssumption.CANONICAL_TERMINAL_BASIS,
        ScenarioAssumption.NO_LISTING_CURRENCY_INFERENCE,
        ScenarioAssumption.FIRST_ORDER_FORMULA
        if execution.definition.mode == "first_order"
        else ScenarioAssumption.COMPOUNDED_FORMULA,
    }
    if execution.definition.shocks:
        assumptions.add(ScenarioAssumption.OWNER_DEFINED_SHOCKS)
    if any(item.kind == "price" for item in execution.definition.shocks) and any(
        item.kind in ("rate", "factor") for item in execution.definition.shocks
    ):
        assumptions.add(ScenarioAssumption.ADDITIONAL_PRICE_COMPONENT)
    if uncovered:
        assumptions.add(ScenarioAssumption.KNOWN_ONLY_SUBTOTALS)
    if replay is not None:
        assumptions.add(ScenarioAssumption.COUNTERFACTUAL_REPLAY)
        if replay.selection.knowledge_basis == "retrospective":
            assumptions.add(ScenarioAssumption.RETROSPECTIVE_MARKET_KNOWLEDGE)
        if any(item.exposure.explicit_cash for item in components):
            assumptions.add(ScenarioAssumption.FIXED_CASH_BALANCE_REPLAY)
    result = ScenarioCalculation(
        input_digest=execution.input_digest,
        pins=execution.pins,
        definition=execution.definition,
        valuation_at=execution.xray_input.valuation_at.value,
        components=components,
        summary=summary,
        upstream_portfolio_value=original,
        upstream_partition_difference=difference,
        upstream_residual_keys=tuple(sorted(item.key for item in execution.xray_result.residuals)),
        replay=replay,
        diagnostics=tuple(
            sorted({item.key: item for item in diagnostics}.values(), key=lambda item: item.key)
        ),
        assumptions=tuple(sorted(assumptions, key=lambda item: item.value)),
        sensitivity_source_row_count=sensitivity_row_count(execution.sensitivities),
    )
    canonical_scenario_bytes(result)
    return result
