"""Saved-result comparison only: incompatible bases retain each side without invented deltas."""

from __future__ import annotations

from typing import Literal

from trading212_domain.errors import fail_validation
from trading212_domain.scenario import MAX_SCENARIO_COMPONENTS, ScenarioReason
from trading212_domain.scenario_result import (
    ScenarioBasisMismatch,
    ScenarioCalculation,
    ScenarioComparison,
    ScenarioComponentDelta,
    ScenarioMetricDelta,
    ScenarioMoneyMetric,
)
from trading212_domain.scenario_serialization import (
    canonical_scenario_bytes,
    scenario_record_bytes,
    scenario_result_digest,
)
from trading212_domain.scenario_validation import scenario_bound
from trading212_domain.serialization import canonical_json

from ._premium_numeric import arithmetic
from ._scenario_components import money_metric, scenario_quality


def compare_scenario_results(
    left: ScenarioCalculation, right: ScenarioCalculation
) -> ScenarioComparison:
    if type(left) is not ScenarioCalculation or type(right) is not ScenarioCalculation:
        fail_validation("Two complete saved scenario results are required.")
    if (left.pins.owner_id, left.pins.account_id) != (right.pins.owner_id, right.pins.account_id):
        fail_validation("Scenario comparison requires the same owned account.")
    canonical_scenario_bytes(left)
    canonical_scenario_bytes(right)
    mismatches: list[ScenarioBasisMismatch] = []

    def compare(
        field: Literal[
            "method",
            "numerical_profile",
            "currency",
            "holdings_basis",
            "holdings_partition",
            "knowledge_basis",
            "market_window",
            "source_cutoff",
        ],
        a: object,
        b: object,
    ) -> None:
        if a != b:
            mismatches.append(
                ScenarioBasisMismatch(field=field, left=canonical_json(a), right=canonical_json(b))
            )

    compare(
        "method",
        (left.method, left.method_version, left.definition.mode),
        (right.method, right.method_version, right.definition.mode),
    )
    compare("numerical_profile", left.numerical_profile, right.numerical_profile)
    compare("currency", left.pins.reporting_currency, right.pins.reporting_currency)
    compare(
        "holdings_basis",
        (
            left.pins.portfolio_snapshot_id,
            left.pins.portfolio_snapshot_digest,
            left.pins.xray_input_digest,
            left.pins.xray_result_digest,
            None if left.replay is None else left.replay.selection.holdings_basis,
        ),
        (
            right.pins.portfolio_snapshot_id,
            right.pins.portfolio_snapshot_digest,
            right.pins.xray_input_digest,
            right.pins.xray_result_digest,
            None if right.replay is None else right.replay.selection.holdings_basis,
        ),
    )
    left_components = {
        (item.exposure.root_key, item.exposure.path_key): item for item in left.components
    }
    right_components = {
        (item.exposure.root_key, item.exposure.path_key): item for item in right.components
    }
    left_basis = tuple((key, item.exposure) for key, item in sorted(left_components.items()))
    right_basis = tuple((key, item.exposure) for key, item in sorted(right_components.items()))
    if left_basis != right_basis:
        # Bound mismatch text without repeating a whole portfolio in one scalar field.
        from hashlib import sha256

        compare(
            "holdings_partition",
            sha256(canonical_json(left_basis).encode()).hexdigest(),
            sha256(canonical_json(right_basis).encode()).hexdigest(),
        )

    def knowledge(value: ScenarioCalculation) -> object:
        return (
            None
            if value.replay is None
            else (
                value.replay.selection.knowledge_basis,
                value.replay.holdings_evidence_at,
                value.replay.holdings_knowledge_cutoff_at,
            )
        )

    def window(value: ScenarioCalculation) -> object:
        return (
            None
            if value.replay is None
            else (
                value.replay.selection.start_date,
                value.replay.selection.end_date,
                value.replay.selection.market_knowledge_cutoff_at,
                value.replay.selection.historical_input_snapshot_id,
                value.replay.context.input_digest,
            )
        )

    compare("knowledge_basis", knowledge(left), knowledge(right))
    compare("market_window", window(left), window(right))
    compare("source_cutoff", left.pins.source_cutoff_at, right.pins.source_cutoff_at)
    compatible = not mismatches
    currency = left.pins.reporting_currency

    def delta(before: ScenarioMoneyMetric, after: ScenarioMoneyMetric) -> ScenarioMetricDelta:
        difference = money_metric(
            None,
            currency,
            quality=scenario_quality(before.quality, after.quality),
            reason=ScenarioReason.INCOMPATIBLE_BASIS
            if not compatible
            else ScenarioReason.UNCERTAIN_MONEY,
        )
        if compatible and before.value is not None and after.value is not None:
            with arithmetic():
                difference = money_metric(
                    after.value.amount - before.value.amount,
                    currency,
                    quality=scenario_quality(before.quality, after.quality),
                )
        return ScenarioMetricDelta(before=before, after=after, difference=difference)

    keys = sorted(set(left_components) | set(right_components))
    scenario_bound(len(keys) <= MAX_SCENARIO_COMPONENTS, "comparison.components")
    components = []
    for key in keys:
        a, b = left_components.get(key), right_components.get(key)
        missing_left = money_metric(
            None, left.pins.reporting_currency, reason=ScenarioReason.INCOMPATIBLE_BASIS
        )
        missing_right = money_metric(
            None, right.pins.reporting_currency, reason=ScenarioReason.INCOMPATIBLE_BASIS
        )
        components.append(
            ScenarioComponentDelta(
                root_key=key[0],
                path_key=key[1],
                post_value=delta(
                    missing_left if a is None else a.post_value,
                    missing_right if b is None else b.post_value,
                ),
                impact=delta(
                    missing_left if a is None else a.impact,
                    missing_right if b is None else b.impact,
                ),
            )
        )
    result = ScenarioComparison(
        left_result_digest=scenario_result_digest(left),
        right_result_digest=scenario_result_digest(right),
        compatible=compatible,
        mismatches=tuple(mismatches),
        post_value=delta(left.summary.post_value, right.summary.post_value),
        impact=delta(left.summary.impact, right.summary.impact),
        components=tuple(components),
    )
    scenario_record_bytes(result)
    return result
