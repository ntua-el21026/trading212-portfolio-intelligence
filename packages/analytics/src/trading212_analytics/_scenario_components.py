"""Shared scenario channel publication and conservative component coverage."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from typing import Literal
from uuid import UUID

from trading212_domain.enums import QualityState
from trading212_domain.scenario import ScenarioReason, scenario_exclusion_key
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import (
    ScenarioChannelEffects,
    ScenarioComponent,
    ScenarioDiagnostic,
    ScenarioMoneyMetric,
    ScenarioRatioMetric,
    ScenarioSensitivityUse,
    ScenarioTerminalExposure,
)
from trading212_domain.serialization import canonical_json
from trading212_domain.values import CurrencyCode, Money

from ._premium_numeric import ZERO, q18
from ._scenario_effects import scenario_value_flow
from ._scenario_matching import resolve_exclusions

_QUALITY_ORDER = {
    QualityState.FRESH: 0,
    QualityState.STALE: 1,
    QualityState.ESTIMATED: 2,
    QualityState.UNRECONCILED: 3,
    QualityState.PARTIAL: 4,
    QualityState.FAILED: 5,
}


def scenario_quality(*values: QualityState) -> QualityState:
    return max(values, key=_QUALITY_ORDER.__getitem__, default=QualityState.ESTIMATED)


def money_metric(
    value: Decimal | None,
    currency: CurrencyCode,
    *,
    quality: QualityState = QualityState.ESTIMATED,
    reason: ScenarioReason = ScenarioReason.UNCERTAIN_MONEY,
    confidence: Decimal | None = None,
    source_reference_ids: tuple[UUID, ...] = (),
) -> ScenarioMoneyMetric:
    return ScenarioMoneyMetric(
        value=None if value is None else Money(q18(value), currency),
        quality=scenario_quality(quality, QualityState.PARTIAL) if value is None else quality,
        reason=reason if value is None else None,
        confidence=confidence,
        source_reference_ids=tuple(sorted(set(source_reference_ids))),
    )


def ratio_metric(
    value: Decimal | None,
    *,
    quality: QualityState = QualityState.ESTIMATED,
    reason: ScenarioReason = ScenarioReason.UNCERTAIN_MONEY,
) -> ScenarioRatioMetric:
    return ScenarioRatioMetric(
        value=None if value is None else q18(value),
        quality=scenario_quality(quality, QualityState.PARTIAL) if value is None else quality,
        reason=reason if value is None else None,
    )


def scenario_diagnostic(
    exposure: ScenarioTerminalExposure,
    reason: ScenarioReason,
    *,
    rule_key: str | None = None,
    references: tuple[UUID, ...] = (),
) -> ScenarioDiagnostic:
    refs = tuple(sorted(set(references)))
    key = sha256(canonical_json((exposure.path_key, rule_key, reason, refs)).encode()).hexdigest()
    return ScenarioDiagnostic(
        key="scenario:" + key,
        reason=reason,
        path_key=exposure.path_key,
        rule_key=rule_key,
        upstream_xray_reason=exposure.upstream_reason,
        upstream_historical_reason=None,
        source_reference_ids=refs,
        source_use_keys=(),
    )


def component_from_channels(
    execution: ScenarioExecutionInput,
    exposure: ScenarioTerminalExposure,
    *,
    price: Decimal | None,
    factor: Decimal | None,
    fx: Decimal | None,
    reasons: tuple[ScenarioReason | None, ScenarioReason | None, ScenarioReason | None],
    zero_effect_proven: bool,
    sensitivity_uses: tuple[ScenarioSensitivityUse, ...] = (),
    sensitivity_confidences: tuple[Decimal | None, ...] | None = None,
    winning_price_rule_key: str | None = None,
    uncertain_rule_keys: tuple[str, ...] = (),
    diagnostics: tuple[ScenarioDiagnostic, ...] = (),
) -> tuple[ScenarioComponent, tuple[ScenarioDiagnostic, ...]]:
    """Publish one terminal component; mapping uncertainty never becomes favorable treatment."""
    exclusions = resolve_exclusions(execution.definition.exclusions, exposure)
    pre = None if exposure.pre_value.value is None else exposure.pre_value.value.amount
    issues = {item.key: item for item in diagnostics}
    matched = tuple(sorted(scenario_exclusion_key(item) for item in exclusions.matched))
    uncertain = set(uncertain_rule_keys)
    partition: Literal["covered", "uncovered", "excluded"]
    if exclusions.excluded:
        partition = "excluded"
        price = factor = fx = ZERO
        reasons = (None, None, None)
        sensitivity_uses = ()
        winning_price_rule_key = None
        uncertain.clear()
        issues.clear()
        zero_effect_proven = True
    else:
        # Validate the actually known formula before masking uncertain applicability.
        scenario_value_flow(None, price, factor, fx, execution.definition.mode)
        for exclusion in exclusions.uncertain:
            key = scenario_exclusion_key(exclusion)
            uncertain.add(key)
            diagnostic = scenario_diagnostic(
                exposure, ScenarioReason.UNCERTAIN_EXCLUSION, rule_key=key
            )
            issues[diagnostic.key] = diagnostic
        unresolved = bool(exclusions.uncertain) or any(reason is not None for reason in reasons)
        unresolved = (
            unresolved or any(value is None for value in (price, factor, fx)) or pre is None
        )
        partition = "uncovered" if unresolved else "covered"
        if exclusions.uncertain:
            # Without definite permission to shock, only zero channel money is unconditional.
            price, factor, fx = tuple(
                value if value == ZERO else None for value in (price, factor, fx)
            )
            reasons = (
                ScenarioReason.UNCERTAIN_EXCLUSION if price is None else reasons[0],
                ScenarioReason.UNCERTAIN_EXCLUSION if factor is None else reasons[1],
                ScenarioReason.UNCERTAIN_EXCLUSION if fx is None else reasons[2],
            )
    for reason in reasons:
        if reason is not None:
            diagnostic = scenario_diagnostic(exposure, reason)
            issues[diagnostic.key] = diagnostic
    if pre is None:
        diagnostic = scenario_diagnostic(
            exposure,
            ScenarioReason.MISSING_VALUE,
            references=exposure.pre_value.source_reference_ids,
        )
        issues[diagnostic.key] = diagnostic
    quality = scenario_quality(
        exposure.quality,
        exposure.pre_value.quality,
        QualityState.ESTIMATED,
        *(item.effect_ratio.quality for item in sensitivity_uses),
        QualityState.PARTIAL if partition == "uncovered" else QualityState.FRESH,
    )
    flow = scenario_value_flow(
        pre,
        price,
        factor,
        fx,
        execution.definition.mode,
        proved_unchanged=zero_effect_proven and partition == "uncovered",
    )
    # A missing channel and a mapped-but-unresolved nonzero treatment both deny complete money.
    if partition == "uncovered" and pre is not None and pre != ZERO and not zero_effect_proven:
        # Known channel money may remain usable, but the total cannot rely on a selected fallback.
        flow = type(flow)(flow.price, flow.factor, flow.fx, flow.interaction, None, None, None)
    basis: Literal["resolved", "zero_pre_value", "provably_zero_effect", "unavailable"] = (
        "unavailable"
        if flow.post is None
        else "zero_pre_value"
        if partition == "uncovered" and pre == ZERO
        else "provably_zero_effect"
        if partition == "uncovered" and zero_effect_proven
        else "resolved"
    )
    currency = execution.pins.reporting_currency

    required_sensitivities = sum(item.shock_size != ZERO for item in sensitivity_uses)
    derived_confidence = exposure.confidence
    if pre != ZERO and required_sensitivities:
        # Missing metadata cannot silently inherit stronger valuation confidence.
        if (
            sensitivity_confidences is None
            or len(sensitivity_confidences) != required_sensitivities
            or exposure.confidence is None
            or any(value is None for value in sensitivity_confidences)
        ):
            derived_confidence = None
        else:
            derived_confidence = min(
                exposure.confidence,
                *(value for value in sensitivity_confidences if value is not None),
            )

    def money(value: Decimal | None, *, sensitivity_dependent: bool = True) -> ScenarioMoneyMetric:
        confidence = derived_confidence if sensitivity_dependent else exposure.confidence
        return money_metric(
            value,
            currency,
            quality=quality,
            confidence=confidence if value is not None else None,
            source_reference_ids=exposure.source_reference_ids,
        )

    effects = ScenarioChannelEffects(
        price_ratio=ratio_metric(
            price, quality=quality, reason=reasons[0] or ScenarioReason.UNCERTAIN_MONEY
        ),
        factor_ratio=ratio_metric(
            factor, quality=quality, reason=reasons[1] or ScenarioReason.UNCERTAIN_MONEY
        ),
        fx_ratio=ratio_metric(
            fx, quality=quality, reason=reasons[2] or ScenarioReason.UNCERTAIN_MONEY
        ),
        price=money(flow.price, sensitivity_dependent=False),
        factor=money(flow.factor),
        fx=money(flow.fx, sensitivity_dependent=False),
        interaction=money(
            flow.interaction,
            sensitivity_dependent=execution.definition.mode == "compounded" and fx != ZERO,
        ),
    )
    ordered_issues = tuple(sorted(issues.values(), key=lambda item: item.key))
    component = ScenarioComponent(
        exposure=exposure,
        partition=partition,
        winning_price_rule_key=winning_price_rule_key,
        matching_exclusion_keys=matched,
        uncertain_rule_keys=tuple(sorted(uncertain)),
        sensitivity_uses=sensitivity_uses,
        effects=effects,
        post_value=money(flow.post),
        impact=money(flow.impact),
        rounding_residual=money(flow.rounding_residual),
        money_basis=basis,
        diagnostic_keys=tuple(item.key for item in ordered_issues),
    )
    return component, ordered_issues
