"""Exact alert comparisons, canonical metric selection and deterministic evaluation."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from trading212_domain import alerts as a
from trading212_domain.alert_serialization import alert_input_digest
from trading212_domain.enums import QualityState
from trading212_domain.historical import HistoricalCashFlowKind
from trading212_domain.planning import DriftCalculation, PlanningAvailability
from trading212_domain.values import CurrencyCode, FxRate, Instant, Money
from trading212_domain.xray import XrayBound, XrayDimension
from trading212_domain.xray_result import XrayCalculation

from . import _xray_decimal as xd
from ._decimal import divide, multiply, persisted_decimal, total
from .portfolio import FxQuote, convert_money
from .quality import combine_quality
from .xray import calculate_overlap_pairs

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HEALTH = {
    a.AlertFamily.STALE_DATA,
    a.AlertFamily.MISSING_COVERAGE,
    a.AlertFamily.RECONCILIATION_FAILURE,
    a.AlertFamily.PROVIDER_FAILURE,
    a.AlertFamily.FAILED_REFRESH,
    a.AlertFamily.REPORT_OUTCOME,
}
_EXTERNAL = {
    HistoricalCashFlowKind.DEPOSIT,
    HistoricalCashFlowKind.WITHDRAWAL,
    HistoricalCashFlowKind.TRANSFER_IN,
    HistoricalCashFlowKind.TRANSFER_OUT,
}


def observe_metric(
    metric: a.AlertMetric,
    value: Decimal | int | bool | None,
    *,
    context: a.AlertResultContext,
    currency: CurrencyCode | None = None,
    comparison_basis: Decimal | int | bool | a.AlertRatioBasis | None = None,
    bound: a.AlertBound = a.AlertBound.EXACT,
    material_complete: bool = True,
    reason: a.AlertReason | None = None,
    quality: QualityState | None = None,
    origin: a.AlertOrigin = a.AlertOrigin.DERIVED_DETERMINISTIC,
) -> a.AlertMetricObservation:
    """Retain canonical presentation independently from its exact comparison basis."""
    basis = comparison_basis if comparison_basis is not None else value
    below = (
        isinstance(basis, a.AlertRatioBasis)
        and basis.numerator > 0
        and type(value) is Decimal
        and value == 0
    )
    return a.AlertMetricObservation(
        observed=a.AlertObservedMetric(
            metric=metric,
            kind=a.alert_metric_kind(metric),
            value=value,
            availability=a.AlertAvailability.UNAVAILABLE
            if value is None
            else (
                a.AlertAvailability.AVAILABLE if material_complete else a.AlertAvailability.PARTIAL
            ),
            quality=context.quality if quality is None else quality,
            origin=origin,
            context_key=context.key,
            currency=currency,
            bound=bound,
            positive_below_quantum=below,
            reason=(reason or a.AlertReason.MISSING_INPUT) if value is None else reason,
        ),
        comparison_basis=None if value is None else basis,
        material_complete=material_complete,
    )


def compare_alert_basis(
    basis: Decimal | int | bool | a.AlertRatioBasis,
    threshold: Decimal | int | bool,
    comparison: a.AlertComparison,
    bound: a.AlertBound = a.AlertBound.EXACT,
) -> bool | None:
    """Five exact operators; a lower bound can establish only one-sided facts."""
    if isinstance(basis, a.AlertRatioBasis):
        a.alert_require(type(threshold) is Decimal, "threshold")
        assert isinstance(threshold, Decimal)
        with xd.arithmetic():
            left = basis.numerator * xd.S
            right = basis.denominator * xd.coefficient18(threshold)
            relation = (left > right) - (left < right)
    else:
        a.alert_require(
            type(basis) is type(threshold) and type(basis) in (Decimal, int, bool), "threshold"
        )
        if type(basis) is Decimal:
            a.alert_decimal(basis)
            assert isinstance(threshold, Decimal)
            a.alert_decimal(threshold)
        if type(basis) is bool:
            a.alert_require(
                comparison is a.AlertComparison.EQ and bound is a.AlertBound.EXACT, "comparison"
            )
        relation = (basis > threshold) - (basis < threshold)
    if bound is a.AlertBound.LOWER_BOUND:
        if comparison is a.AlertComparison.GT:
            return True if relation > 0 else None
        if comparison is a.AlertComparison.GTE:
            return True if relation >= 0 else None
        if comparison is a.AlertComparison.LT:
            return False if relation >= 0 else None
        if comparison in {a.AlertComparison.LTE, a.AlertComparison.EQ}:
            return False if relation > 0 else None
    return {
        a.AlertComparison.GT: relation > 0,
        a.AlertComparison.GTE: relation >= 0,
        a.AlertComparison.LT: relation < 0,
        a.AlertComparison.LTE: relation <= 0,
        a.AlertComparison.EQ: relation == 0,
    }[comparison]


def convert_alert_money(
    value: Money, reporting_currency: CurrencyCode, *, legs: tuple[a.AlertFxLeg, ...] = ()
) -> a.AlertMoneyConversion:
    """Use only supplied sourced fixing legs, once; preserve unavailable conversion."""
    a.alert_decimal(value.amount)
    if value.currency == reporting_currency:
        a.alert_require(not legs, "fx.unnecessary")
        return a.AlertMoneyConversion(
            original=value,
            reporting_currency=reporting_currency,
            converted=value,
            comparison_basis=value.amount,
            legs=(),
        )
    if not legs:
        return a.AlertMoneyConversion(
            original=value,
            reporting_currency=reporting_currency,
            converted=None,
            comparison_basis=None,
            legs=(),
            reason=a.AlertReason.MISSING_FX,
        )
    a.alert_require(1 <= len(legs) <= 2, "fx.legs")
    current = value.currency
    for leg in legs:
        source, target = (leg.quote, leg.base) if leg.inverse else (leg.base, leg.quote)
        a.alert_require(current == source, "fx.chain")
        current = target
    a.alert_require(current == reporting_currency, "fx.target")
    if len(legs) == 2:
        first, second = legs
        a.alert_require(
            (first.snapshot_id, first.provider_id, first.observed_at)
            == (second.snapshot_id, second.provider_id, second.observed_at),
            "fx.compatibility",
        )
    if any(leg.rate is None for leg in legs):
        return a.AlertMoneyConversion(
            original=value,
            reporting_currency=reporting_currency,
            converted=None,
            comparison_basis=None,
            legs=legs,
            reason=a.AlertReason.MISSING_FX,
        )
    converted = value
    for leg in legs:
        assert leg.rate is not None
        target = leg.base if leg.inverse else leg.quote
        conversion = convert_money(
            converted,
            reporting_currency=target,
            fx_quotes=(
                FxQuote(
                    FxRate(
                        leg.base,
                        leg.quote,
                        leg.rate,
                        Instant(leg.observed_at),
                        leg.source_reference_key,
                    )
                ),
            ),
            source_cutoff_at=Instant(leg.observed_at),
        )
        assert conversion.converted_value is not None
        converted = conversion.converted_value
    return a.AlertMoneyConversion(
        original=value,
        reporting_currency=reporting_currency,
        converted=converted,
        comparison_basis=converted.amount,
        legs=legs,
    )


def direct_concentration_observation(
    predicate: a.AlertPredicate,
    *,
    positions: tuple[Money, ...],
    cash: tuple[Money, ...],
    portfolio_total: Money | None,
    context: a.AlertResultContext,
) -> a.AlertMetricObservation:
    a.alert_require(predicate.family is a.AlertFamily.CONCENTRATION, "metric")
    a.alert_limit(len(positions) + len(cash) <= 10_000, "direct.universe")
    if portfolio_total is None or portfolio_total.amount <= 0:
        return observe_metric(
            predicate.metric, None, context=context, reason=a.AlertReason.UNKNOWN_DENOMINATOR
        )
    values = positions + (cash if predicate.include_cash else ())
    a.alert_require(
        all(
            item.currency == portfolio_total.currency and item.amount >= 0
            for item in (*positions, *cash)
        ),
        "direct.currency",
    )
    amounts = sorted((item.amount for item in values), reverse=True)
    denominator = portfolio_total.amount
    if predicate.metric is a.AlertMetric.DIRECT_MAX_WEIGHT:
        value = divide(max(amounts, default=_ZERO), denominator)
    elif predicate.metric is a.AlertMetric.DIRECT_TOP_N_WEIGHT:
        assert predicate.top_n is not None
        value = divide(total(amounts[: predicate.top_n]), denominator)
    else:
        value = divide(
            total(multiply(amount, amount) for amount in amounts),
            multiply(denominator, denominator),
        )
    return observe_metric(predicate.metric, persisted_decimal(value), context=context)


def cash_observation(
    predicate: a.AlertPredicate,
    *,
    cash: tuple[Money, ...],
    portfolio_total: Money | None,
    context: a.AlertResultContext,
) -> a.AlertMetricObservation:
    a.alert_require(predicate.family is a.AlertFamily.CASH_THRESHOLD, "metric")
    a.alert_limit(len(cash) <= a.MAX_ALERT_EVENT_CANDIDATES, "cash.universe")
    currency = (
        predicate.currency
        if predicate.metric is a.AlertMetric.CASH_AMOUNT
        else (portfolio_total.currency if portfolio_total else context.reporting_currency)
    )
    if currency is None or any(item.currency != currency for item in cash):
        return observe_metric(
            predicate.metric,
            None,
            context=context,
            currency=predicate.currency,
            reason=a.AlertReason.MISSING_FX,
        )
    amount = total(item.amount for item in cash)
    if predicate.metric is a.AlertMetric.CASH_AMOUNT:
        return observe_metric(
            predicate.metric, persisted_decimal(amount), context=context, currency=currency
        )
    if portfolio_total is None or portfolio_total.amount <= 0:
        return observe_metric(
            predicate.metric, None, context=context, reason=a.AlertReason.UNKNOWN_DENOMINATOR
        )
    return observe_metric(
        predicate.metric, persisted_decimal(divide(amount, portfolio_total.amount)), context=context
    )


def drift_observation(
    predicate: a.AlertPredicate, calculation: DriftCalculation, *, context_key: str
) -> a.AlertMetricObservation:
    """Select the canonical full-denominator frontier without mixing ancestors and leaves."""
    a.alert_require(
        predicate.family
        in {a.AlertFamily.TARGET_DRIFT, a.AlertFamily.GROUP_DRIFT, a.AlertFamily.HOLDING_DRIFT},
        "metric",
    )
    a.alert_require(
        str(predicate.target_version_id) == calculation.context.target_version_id, "drift.target"
    )
    rows = calculation.rows
    if predicate.metric is a.AlertMetric.PORTFOLIO_L1_DRIFT:
        assert predicate.frontier_depth is not None
        depth = predicate.frontier_depth
        selected = tuple(
            row
            for row in rows
            if row.kind == "unclassified"
            or row.depth == depth
            or (row.kind != "group" and row.depth < depth)
        )
    elif predicate.metric is a.AlertMetric.GROUP_ABSOLUTE_DRIFT:
        selected = tuple(
            row
            for row in rows
            if row.kind == "group" and row.node_id == str(predicate.group_node_id)
        )
    else:
        selected = tuple(row for row in rows if row.holding_id == str(predicate.holding_id))
    complete = (
        calculation.context.coverage.complete
        and calculation.context.reconciled
        and calculation.context.availability is PlanningAvailability.AVAILABLE
    )
    quality = combine_quality((calculation.context.quality, *(row.quality for row in selected)))
    value = None
    reason = a.AlertReason.UNKNOWN_IDENTITY if not selected else a.AlertReason.INCOMPLETE_COVERAGE
    if selected and all(row.signed_drift is not None for row in selected):
        value = total(
            row.signed_drift.copy_abs() for row in selected if row.signed_drift is not None
        )
        if predicate.metric is a.AlertMetric.PORTFOLIO_L1_DRIFT:
            value = divide(value, Decimal(2))
        value = persisted_decimal(value)
    observed = a.AlertObservedMetric(
        metric=predicate.metric,
        kind=a.AlertMetricKind.DECIMAL,
        value=value,
        availability=a.AlertAvailability.UNAVAILABLE
        if value is None
        else (a.AlertAvailability.AVAILABLE if complete else a.AlertAvailability.PARTIAL),
        quality=quality,
        origin=a.AlertOrigin.DERIVED_DETERMINISTIC,
        context_key=context_key,
        reason=reason if value is None else None,
    )
    return a.AlertMetricObservation(
        observed=observed, comparison_basis=value, material_complete=complete
    )


def xray_observation(
    predicate: a.AlertPredicate, calculation: XrayCalculation, *, context: a.AlertResultContext
) -> a.AlertMetricObservation:
    a.alert_require(
        predicate.family
        in {a.AlertFamily.EFFECTIVE_COMPANY_CONCENTRATION, a.AlertFamily.ETF_OVERLAP},
        "metric",
    )
    exact = calculation.exact_state
    qualities = [context.quality]
    public_buckets = {
        item.bucket_key: item
        for item in calculation.exposure_buckets
        if item.dimension is XrayDimension.COMPANY
    }
    with xd.arithmetic():
        if predicate.metric is a.AlertMetric.ETF_PAIR_OVERLAP:
            assert predicate.left_fund_id is not None and predicate.right_fund_id is not None
            (pair,) = calculate_overlap_pairs(
                calculation, (predicate.left_fund_id, predicate.right_fund_id)
            )
            if pair.overlap.value is None:
                return observe_metric(
                    predicate.metric,
                    None,
                    context=context,
                    reason=a.AlertReason.INCOMPLETE_COVERAGE,
                )
            qualities.append(pair.overlap.quality)
            numerator, denominator = pair.overlap_coefficient, xd.UNIT
            complete = pair.overlap.bound is XrayBound.EXACT
        else:
            if exact.portfolio_coefficient is None or exact.portfolio_coefficient <= 0:
                return observe_metric(
                    predicate.metric,
                    None,
                    context=context,
                    reason=a.AlertReason.UNKNOWN_DENOMINATOR,
                )
            dimension = next(
                item for item in exact.dimensions if item.dimension is XrayDimension.COMPANY
            )
            complete = dimension.unresolved_coefficient == 0 and all(
                item.money_coefficient is not None for item in exact.roots
            )
            denominator = exact.portfolio_coefficient
            if predicate.metric is a.AlertMetric.PORTFOLIO_DUPLICATED_EXPOSURE:
                qualities.append(calculation.portfolio_summary.duplicated_exposure.quality)
                numerator = exact.duplication_coefficient
            elif predicate.metric is a.AlertMetric.EFFECTIVE_HHI:
                qualities.append(calculation.portfolio_summary.hhi.quality)
                if exact.portfolio_square_coefficient is None:
                    return observe_metric(
                        predicate.metric,
                        None,
                        context=context,
                        reason=a.AlertReason.UNKNOWN_DENOMINATOR,
                    )
                numerator, denominator = exact.hhi_coefficient, exact.portfolio_square_coefficient
            else:
                buckets = [
                    item for item in exact.buckets if item.dimension is XrayDimension.COMPANY
                ]
                if predicate.metric is a.AlertMetric.EFFECTIVE_ENTITY_WEIGHT:
                    matches = [
                        item for item in buckets if item.bucket_key == str(predicate.entity_id)
                    ]
                    if not matches and not complete:
                        return observe_metric(
                            predicate.metric,
                            None,
                            context=context,
                            reason=a.AlertReason.UNKNOWN_IDENTITY,
                        )
                    qualities.extend(
                        public_buckets[item.bucket_key].absolute_weight.quality for item in matches
                    )
                    numerator = sum(
                        (item.direct_coefficient + item.indirect_coefficient for item in matches),
                        _ZERO,
                    )
                else:
                    assert predicate.top_n is not None
                    ordered = sorted(
                        buckets,
                        key=lambda item: (
                            -(item.direct_coefficient + item.indirect_coefficient),
                            item.bucket_key,
                        ),
                    )
                    qualities.extend(
                        public_buckets[item.bucket_key].absolute_weight.quality
                        for item in ordered[: predicate.top_n]
                    )
                    numerator = sum(
                        (
                            item.direct_coefficient + item.indirect_coefficient
                            for item in ordered[: predicate.top_n]
                        ),
                        _ZERO,
                    )
        basis = a.AlertRatioBasis(
            numerator=numerator,
            denominator=denominator,
            numeric_policy_version=calculation.policy.numeric_policy,
        )
        return observe_metric(
            predicate.metric,
            xd.q18(numerator, denominator),
            context=context,
            comparison_basis=basis,
            bound=a.AlertBound.EXACT if complete else a.AlertBound.LOWER_BOUND,
            material_complete=complete,
            quality=combine_quality(qualities),
        )


def _decision(
    predicate: a.AlertPredicate,
    observation: a.AlertMetricObservation,
    quality_policy: a.AlertQualityPolicy,
) -> tuple[a.AlertEvaluationOutcome, bool | None, a.AlertReason | None]:
    observed, basis = observation.observed, observation.comparison_basis
    if predicate.family not in _HEALTH and (
        observed.quality is QualityState.FAILED
        or observed.availability is a.AlertAvailability.FAILED
    ):
        return a.AlertEvaluationOutcome.FAILED, None, a.AlertReason.COMPUTATION_FAILED
    if observed.value is None or basis is None:
        return (
            (
                a.AlertEvaluationOutcome.FAILED
                if observed.availability is a.AlertAvailability.FAILED
                else a.AlertEvaluationOutcome.UNAVAILABLE
            ),
            None,
            observed.reason or a.AlertReason.MISSING_INPUT,
        )
    if isinstance(basis, a.AlertRatioBasis):
        a.alert_require(
            type(observed.value) is Decimal
            and observed.value == xd.q18(basis.numerator, basis.denominator)
            and observed.positive_below_quantum == (basis.numerator > 0 and observed.value == 0),
            "comparison_basis.display",
        )
    if predicate.currency is not None and observed.currency != predicate.currency:
        return a.AlertEvaluationOutcome.UNAVAILABLE, None, a.AlertReason.CURRENCY_MISMATCH
    if (
        predicate.family not in _HEALTH
        and quality_policy is a.AlertQualityPolicy.REQUIRE_COMPLETE
        and (
            not observation.material_complete
            or observed.availability is not a.AlertAvailability.AVAILABLE
            or observed.quality is not QualityState.FRESH
        )
    ):
        return a.AlertEvaluationOutcome.SUPPRESSED, None, a.AlertReason.MATERIAL_QUALITY
    if predicate.comparison is None:
        a.alert_require(type(basis) is bool, "event.basis")
        assert isinstance(basis, bool)
        result: bool | None = basis
    else:
        assert predicate.threshold is not None
        result = compare_alert_basis(
            basis, predicate.threshold, predicate.comparison, observed.bound
        )
    if result is None:
        return a.AlertEvaluationOutcome.UNAVAILABLE, None, a.AlertReason.INCONCLUSIVE_LOWER_BOUND
    return (
        (a.AlertEvaluationOutcome.MATCHED if result else a.AlertEvaluationOutcome.NOT_MATCHED),
        result,
        None,
    )


def _event_observation(
    predicate: a.AlertPredicate, event: a.AlertEventObservation, window: a.AlertObservationWindow
) -> a.AlertMetricObservation:
    observation = event.observation
    eligible_at = event.first_eligible_at if window.newly_known_revisions else event.economic_at
    selected = window.start_at < eligible_at <= window.end_at
    selected = selected and (
        predicate.instrument_id is None or predicate.instrument_id == event.instrument_id
    )
    selected = selected and (
        predicate.activity_kind is None or predicate.activity_kind is event.activity_kind
    )
    selected = selected and (
        predicate.capability_family is None
        or predicate.capability_family is event.capability_family
    )
    selected = selected and (
        predicate.report_type is None or predicate.report_type is event.report_type
    )
    if predicate.metric is a.AlertMetric.REPORT_TERMINAL:
        selected = selected and event.report_outcome in {
            a.AlertReportOutcome.SUCCEEDED,
            a.AlertReportOutcome.FAILED,
        }
        selected = selected and (
            predicate.outcome is a.AlertReportOutcome.EITHER
            or predicate.outcome is event.report_outcome
        )
    if selected and predicate.metric is a.AlertMetric.POSITIVE_DIVIDEND:
        if event.net_amount is None:
            return replace(
                observation,
                observed=replace(
                    observation.observed,
                    value=None,
                    availability=a.AlertAvailability.UNAVAILABLE,
                    reason=a.AlertReason.MISSING_INPUT,
                ),
                comparison_basis=None,
            )
        selected = selected and event.net_amount.amount > 0
        if selected and predicate.minimum_net_amount is not None:
            if event.net_amount.currency != predicate.minimum_net_amount.currency:
                return replace(
                    observation,
                    observed=replace(
                        observation.observed,
                        value=None,
                        availability=a.AlertAvailability.UNAVAILABLE,
                        reason=a.AlertReason.MISSING_FX,
                    ),
                    comparison_basis=None,
                )
            selected = selected and event.net_amount.amount >= predicate.minimum_net_amount.amount
    if predicate.metric is a.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT:
        selected = selected and event.activity_kind in _EXTERNAL
        if selected and type(observation.comparison_basis) is Decimal:
            return replace(
                observation,
                observed=replace(
                    observation.observed, value=observation.comparison_basis.copy_abs()
                ),
                comparison_basis=observation.comparison_basis.copy_abs(),
            )
        if not selected:
            return replace(
                observation,
                observed=replace(
                    observation.observed,
                    value=None,
                    availability=a.AlertAvailability.UNAVAILABLE,
                    reason=a.AlertReason.FILTERED_OUT,
                ),
                comparison_basis=None,
            )
        return observation
    if not selected:
        return replace(
            observation,
            observed=replace(
                observation.observed,
                value=None,
                availability=a.AlertAvailability.UNAVAILABLE,
                reason=a.AlertReason.FILTERED_OUT,
            ),
            comparison_basis=None,
        )
    return observation


def alert_event_digest(
    version_id: UUID, family: a.AlertFamily, identity: UUID, revision_id: UUID | None
) -> str:
    return hashlib.sha256(
        f"alert_event_v1:{version_id}:{family.value}:{identity}:{revision_id or ''}".encode()
    ).hexdigest()


def evaluate_alert(value: a.AlertEvaluationInput) -> a.AlertEvaluationResult:
    """Evaluate only immutable captured inputs. Operational time is deliberately absent."""
    value.__post_init__()
    digest = alert_input_digest(value)
    predicate, policy = value.version.definition.predicate, value.version.definition.quality_policy
    observation = None
    decisions: list[a.AlertEventDecision] = []
    if isinstance(value.payload, a.AlertThresholdInput):
        observation = value.payload.observation.observed
        outcome, decision, reason = _decision(predicate, value.payload.observation, policy)
    else:
        for event in value.payload.events:
            adjusted = _event_observation(predicate, event, value.observation_window)
            if adjusted.observed.reason is a.AlertReason.FILTERED_OUT:
                outcome, decision, reason = a.AlertEvaluationOutcome.NOT_MATCHED, False, None
            else:
                outcome, decision, reason = _decision(predicate, adjusted, policy)
            decisions.append(
                a.AlertEventDecision(
                    identity=event.identity,
                    revision_id=event.revision_id,
                    correction_of=event.correction_of,
                    outcome=outcome,
                    decision=decision,
                    observation=adjusted.observed,
                    reason=reason,
                    deduplication_digest=alert_event_digest(
                        value.version.id, predicate.family, event.identity, event.revision_id
                    ),
                )
            )
        if any(item.decision is True for item in decisions):
            outcome, decision, reason = a.AlertEvaluationOutcome.MATCHED, True, None
        elif not value.payload.complete:
            outcome, decision, reason = (
                a.AlertEvaluationOutcome.UNAVAILABLE,
                None,
                value.payload.reason,
            )
        elif any(item.decision is None for item in decisions):
            first = next(item for item in decisions if item.decision is None)
            outcome, decision, reason = first.outcome, None, first.reason
        else:
            outcome, decision, reason = a.AlertEvaluationOutcome.NOT_MATCHED, False, None
    return a.AlertEvaluationResult(
        rule_version_id=value.version.id,
        input_digest=digest,
        scheduled_for=value.scheduled_for,
        source_cutoff_at=value.source_cutoff_at,
        execution_intent=value.execution_intent,
        outcome=outcome,
        decision=decision,
        reason=reason,
        observation=observation,
        event_decisions=tuple(decisions),
        contexts=value.contexts,
    )


def reduce_alert_condition(
    state: a.AlertConditionState,
    result: a.AlertEvaluationResult,
    *,
    cooldown_seconds: int,
    known_event_digests: frozenset[str] = frozenset(),
) -> a.AlertTransitionPlan:
    """Unknown outcomes retain the latch; persistence assigns winning physical IDs."""
    a.alert_require(
        state.rule_version_id == result.rule_version_id and 0 <= cooldown_seconds <= 604800,
        "condition",
    )
    if result.execution_intent is a.AlertExecutionIntent.OBSERVE_ONLY:
        return a.AlertTransitionPlan(state=state)
    a.alert_require(
        state.last_applied_scheduled_for is None
        or state.last_applied_scheduled_for < result.scheduled_for,
        "condition.order",
    )
    a.alert_limit(len(known_event_digests) <= a.MAX_ALERT_EVENT_CANDIDATES, "known_event_digests")
    next_state = replace(state, last_applied_scheduled_for=result.scheduled_for)
    intents: list[a.AlertTransitionIntent] = []

    def notification() -> a.AlertNotificationState:
        nonlocal next_state
        previous = next_state.last_eligible_notification_at
        if previous is not None and result.scheduled_for - previous < timedelta(
            seconds=cooldown_seconds
        ):
            return a.AlertNotificationState.SUPPRESSED_COOLDOWN
        next_state = replace(next_state, last_eligible_notification_at=result.scheduled_for)
        return a.AlertNotificationState.ELIGIBLE

    if result.observation is None:
        intents.extend(
            a.AlertTransitionIntent(
                deduplication_digest=item.deduplication_digest,
                episode_ordinal=None,
                event_identity=item.identity,
                revision_id=item.revision_id,
                correction_of=item.correction_of,
                notification_state=notification(),
            )
            for item in result.event_decisions
            if item.decision is True and item.deduplication_digest not in known_event_digests
        )
        return a.AlertTransitionPlan(state=next_state, create=tuple(intents))
    if result.decision is None:
        return a.AlertTransitionPlan(state=next_state)
    if result.decision is False:
        next_state = replace(
            next_state, last_conclusive_decision=False, armed=True, open_episode_id=None
        )
        return a.AlertTransitionPlan(
            state=next_state,
            resolve_episode_id=state.open_episode_id,
            resolution_reason=a.AlertResolutionReason.CONDITION_CLEARED
            if state.open_episode_id
            else None,
        )
    if state.armed:
        ordinal = state.next_episode_ordinal
        digest = hashlib.sha256(
            f"alert_episode_v1:{state.rule_version_id}:{ordinal}".encode()
        ).hexdigest()
        intents.append(
            a.AlertTransitionIntent(
                deduplication_digest=digest,
                episode_ordinal=ordinal,
                event_identity=None,
                revision_id=None,
                correction_of=None,
                notification_state=notification(),
            )
        )
        next_state = replace(next_state, next_episode_ordinal=ordinal + 1)
    next_state = replace(next_state, last_conclusive_decision=True, armed=False)
    return a.AlertTransitionPlan(state=next_state, create=tuple(intents))
