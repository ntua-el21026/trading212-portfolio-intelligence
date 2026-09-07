"""Five pure historical families over an immutable, validated capture."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from decimal import Decimal

from trading212_domain import CurrencyCode
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.errors import fail_validation
from trading212_domain.historical_serialization import (
    historical_canonical_bytes,
    historical_input_digest,
)
from trading212_domain.historical_validation import validate_historical_input
from trading212_domain.source_details import CorporateActionSnapshot
from trading212_domain.sources import FxOperation, FxSnapshot, SourceSnapshot

from ._decimal import persisted_decimal
from ._historical_attribution import attribution
from ._historical_benchmark import comparison
from ._historical_core import HistoricalEngine, financial
from ._historical_income import cash_flows, income
from ._historical_performance import performance


@financial
def calculate_performance(
    value: d.HistoricalInput, *, options: r.PerformanceOptions
) -> r.PerformanceCalculation:
    result = performance(HistoricalEngine(validate_historical_input(value)), options)
    historical_canonical_bytes(result)
    return result


@financial
def calculate_benchmark_comparison(
    value: d.HistoricalInput, *, options: r.ComparisonOptions
) -> r.BenchmarkCalculation:
    result = comparison(HistoricalEngine(validate_historical_input(value)), options)
    historical_canonical_bytes(result)
    return result


@financial
def calculate_income(value: d.HistoricalInput, *, options: r.IncomeOptions) -> r.IncomeCalculation:
    result = income(HistoricalEngine(validate_historical_input(value)), options)
    historical_canonical_bytes(result)
    return result


@financial
def calculate_attribution(
    value: d.HistoricalInput, *, options: r.AttributionOptions
) -> r.AttributionCalculation:
    result = attribution(HistoricalEngine(validate_historical_input(value)), options)
    historical_canonical_bytes(result)
    return result


@financial
def calculate_cash_flows(
    value: d.HistoricalInput, *, options: r.CashFlowOptions
) -> r.CashFlowCalculation:
    result = cash_flows(HistoricalEngine(validate_historical_input(value)), options)
    historical_canonical_bytes(result)
    return result


@financial
def verify_historical_result(value: d.HistoricalInput, result: r.HistoricalCalculation) -> None:
    """Check fixed scope, selected-use foreign references and exact accounting identities."""
    validate_historical_input(value)
    if (
        result.context.input_digest != historical_input_digest(value)
        or result.context.window != value.selection.window
        or result.context.account_id != value.account_id
    ):
        fail_validation("Historical result differs from its sealed input.", field="result")
    expected_sources = tuple(sorted(value.sources, key=lambda item: (item.kind, item.id)))
    method_ids = {
        "performance": "performance_v2",
        "benchmark": "benchmark_comparison_v1",
        "income": "income_v1",
        "attribution": "attribution_bridge_v1",
        "cash_flows": "cash_flow_intelligence_v1",
    }
    primitive_ids = {"xirr", "modified_dietz", "snapshot_subperiod_twr"}
    if (
        result.context.sources != expected_sources
        or result.context.method.version != value.method_version
        or result.context.method.name != method_ids[result.family]
        or any(
            item.name not in primitive_ids or item.version != "1.0.0"
            for item in result.context.primitive_methods
        )
    ):
        fail_validation("Historical result provenance or method differs.", field="context")
    currency = value.selection.window.reporting_currency
    _verify_currency(result.summary, currency)
    if isinstance(result, (r.PerformanceCalculation, r.BenchmarkCalculation)):
        _verify_currency(result.points, currency)
        _verify_currency(result.rolling_returns, currency)
        _verify_currency(result.calendar_returns, currency)
        if tuple(item.ordinal for item in result.points) != tuple(range(len(result.points))):
            fail_validation("Historical point order is invalid.", field="points")
        if any(
            item.valuation_at < value.selection.window.start_at
            or item.valuation_at > value.selection.window.end_at
            for item in result.points
        ):
            fail_validation("Historical point leaves its window.", field="points")
    elif isinstance(result, r.AttributionCalculation):
        _verify_currency(result.rows, currency)
        _verify_currency(result.effects, currency)
    else:
        _verify_currency(result.reporting_totals, currency)
        for native in result.native_currency_totals:
            _verify_currency(native, native.currency)
        for event in result.events:
            _verify_currency(event.reporting_amount, currency)
        if isinstance(result, r.IncomeCalculation):
            _verify_currency(result.instrument_rows, currency)
            _verify_currency(result.group_rows, currency)
    sources: list[SourceSnapshot | CorporateActionSnapshot] = [
        *value.price_snapshots,
        *value.fx_snapshots,
        *value.action_snapshots,
    ]
    if value.benchmark_input:
        sources.extend(value.benchmark_input.price_snapshots)
        sources.extend(value.benchmark_input.benchmark_snapshots)
    snapshots = {item.id: item for item in sources}
    for use in result.source_uses:
        if isinstance(use, r.HistoricalObservationUse):
            snapshot = snapshots.get(use.snapshot_id)
            if snapshot is None or use.observation_index >= len(snapshot.observations):
                fail_validation(
                    "Selected observation is outside the sealed source.", field="source_uses"
                )
            observation = snapshot.observations[use.observation_index]
            if (
                observation.effective_at > use.use_at
                or observation.effective_at > use.knowledge_cutoff_at
                or snapshot.provenance.first_observed_at > use.knowledge_cutoff_at
            ):
                fail_validation(
                    "Selected observation violates its economic/knowledge cutoff.",
                    field="source_uses",
                )
    references = (
        {item.id for item in value.sources}
        | {item.id for item in value.mapping_evidence}
        | {item.id for item in value.classification_evidence}
        | {item.identity.revision_id for item in value.event_candidates}
    )
    uses = {item.use_key: item for item in result.source_uses}
    for use in result.source_uses:
        expected_cutoff = (
            min(value.selection.window.source_cutoff_at, use.use_at)
            if value.selection.window.knowledge_policy is d.KnowledgePolicy.POINT_IN_TIME
            else value.selection.window.source_cutoff_at
        )
        if use.knowledge_cutoff_at != expected_cutoff:
            fail_validation("Selected use has an incorrect knowledge cutoff.", field="source_uses")
        if isinstance(use, r.HistoricalEvidenceUse):
            if use.reference_id not in references:
                fail_validation(
                    "Selected evidence is outside the immutable input.", field="source_uses"
                )
            if use.reference_kind == "action_coverage":
                action_snapshot = snapshots.get(use.reference_id)
                if not isinstance(action_snapshot, CorporateActionSnapshot) or (
                    action_snapshot.provenance.first_observed_at > use.knowledge_cutoff_at
                    or action_snapshot.provenance.effective_at > use.knowledge_cutoff_at
                ):
                    fail_validation(
                        "Action absence evidence violates its cutoff or type.", field="source_uses"
                    )
            evidence_times = {item.id: item.first_observed_at for item in value.mapping_evidence}
            evidence_times.update(
                {item.id: item.first_observed_at for item in value.classification_evidence}
            )
            evidence = evidence_times.get(use.reference_id)
            if evidence is not None and evidence > use.knowledge_cutoff_at:
                fail_validation(
                    "Selected evidence violates its knowledge cutoff.", field="source_uses"
                )
        if isinstance(use, r.HistoricalMissingUse) and not set(use.candidate_snapshot_ids) <= set(
            snapshots
        ):
            fail_validation(
                "Missing-use candidates are outside the immutable input.", field="source_uses"
            )
    for conversion in result.conversions:
        expected_rate = Decimal(1)
        current = conversion.base
        if conversion.operation is FxOperation.IDENTITY:
            if (
                conversion.base != conversion.quote
                or conversion.leg_use_keys
                or conversion.rate != 1
            ):
                fail_validation(
                    "Identity FX conversion differs from its proof.", field="conversions"
                )
            continue
        if len(conversion.leg_use_keys) != (
            2 if conversion.operation is FxOperation.TRIANGULATED else 1
        ):
            fail_validation(
                "FX conversion leg count differs from its operation.", field="conversions"
            )
        for ordinal, use_key in enumerate(conversion.leg_use_keys):
            leg_use = uses.get(use_key)
            if (
                not isinstance(leg_use, r.HistoricalObservationUse)
                or leg_use.conversion_leg is None
                or leg_use.conversion_leg.conversion_key != conversion.conversion_key
                or leg_use.conversion_leg.ordinal != ordinal
            ):
                fail_validation(
                    "FX conversion leg lacks its exact source use.", field="conversions"
                )
            fx_snapshot = snapshots[leg_use.snapshot_id]
            if not isinstance(fx_snapshot, FxSnapshot):
                fail_validation(
                    "FX conversion leg must reference FX observations.", field="conversions"
                )
            observation = fx_snapshot.observations[leg_use.observation_index]
            if observation.rate is None:
                fail_validation("FX conversion cannot use a missing rate.", field="conversions")
            inverse = leg_use.conversion_leg.direction == "inverse"
            base, quote = (
                (observation.quote, observation.base)
                if inverse
                else (observation.base, observation.quote)
            )
            if (
                current != base
                or leg_use.conversion_leg.base != base
                or leg_use.conversion_leg.quote != quote
            ):
                fail_validation("FX conversion direction is inconsistent.", field="conversions")
            expected_rate *= 1 / observation.rate if inverse else observation.rate
            current = quote
        if current != conversion.quote or persisted_decimal(expected_rate) != conversion.rate:
            fail_validation(
                "FX conversion rate does not reconcile to its observations.", field="conversions"
            )
    if isinstance(result, r.PerformanceCalculation):
        summary = result.summary
        if all(
            item.value is not None
            for item in (
                summary.beginning_value,
                summary.ending_value,
                summary.net_contributions,
                summary.investment_gain,
            )
        ):
            assert (
                summary.beginning_value.value
                and summary.ending_value.value
                and summary.net_contributions.value
                and summary.investment_gain.value
            )
            if abs(
                summary.ending_value.value.amount
                - summary.beginning_value.value.amount
                - summary.net_contributions.value.amount
                - summary.investment_gain.value.amount
            ) > Decimal("0.000000000000000002"):
                fail_validation("Performance gain does not reconcile.", field="summary")
    elif isinstance(result, r.AttributionCalculation):
        attribution_summary = result.summary
        if (
            attribution_summary.investment_gain.value
            and attribution_summary.attributed_amount.value
            and attribution_summary.residual.value
            and attribution_summary.investment_gain.value.amount
            != attribution_summary.attributed_amount.value.amount
            + attribution_summary.residual.value.amount
        ):
            fail_validation(
                "Attribution partition does not reconcile.", field="attribution_summary"
            )
    historical_canonical_bytes(result)


def _verify_currency(value: object, currency: CurrencyCode) -> None:
    if isinstance(value, d.HistoricalMoneyMetric):
        if value.value is not None and value.value.currency != currency:
            fail_validation("Historical reporting metric currency differs.", field="currency")
    elif isinstance(value, tuple):
        for item in value:
            _verify_currency(item, currency)
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            _verify_currency(getattr(value, field.name), currency)
