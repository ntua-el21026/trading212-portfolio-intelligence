"""Small immutable alert captures; real canonical calculators are used by selector tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from trading212_domain import alerts as a
from trading212_domain.alert_serialization import alert_record_digest
from trading212_domain.enums import QualityState
from trading212_domain.historical import HistoricalCashFlowKind
from trading212_domain.values import CurrencyCode, Money

AT = datetime(2026, 9, 10, 12, tzinfo=UTC)
EUR = CurrencyCode("EUR")


def uid(number: int) -> UUID:
    return UUID(int=number)


def predicate(metric: a.AlertMetric = a.AlertMetric.CASH_WEIGHT) -> a.AlertPredicate:
    m, f, c = a.AlertMetric, a.AlertFamily, a.AlertComparison
    if metric is m.PORTFOLIO_L1_DRIFT:
        return a.AlertPredicate(
            family=f.TARGET_DRIFT,
            metric=metric,
            comparison=c.GT,
            threshold=Decimal("0.1"),
            target_version_id=uid(4),
            frontier_depth=1,
        )
    if metric is m.GROUP_ABSOLUTE_DRIFT:
        return a.AlertPredicate(
            family=f.GROUP_DRIFT,
            metric=metric,
            comparison=c.GT,
            threshold=Decimal("0.1"),
            target_version_id=uid(4),
            group_node_id=uid(5),
        )
    if metric is m.HOLDING_ABSOLUTE_DRIFT:
        return a.AlertPredicate(
            family=f.HOLDING_DRIFT,
            metric=metric,
            comparison=c.GT,
            threshold=Decimal("0.1"),
            target_version_id=uid(4),
            holding_id=uid(6),
        )
    if metric in {m.DIRECT_MAX_WEIGHT, m.DIRECT_TOP_N_WEIGHT, m.DIRECT_HHI}:
        return a.AlertPredicate(
            family=f.CONCENTRATION,
            metric=metric,
            comparison=c.GT,
            threshold=Decimal("0.1"),
            include_cash=False,
        )
    if metric in {m.EFFECTIVE_ENTITY_WEIGHT, m.EFFECTIVE_TOP_N_WEIGHT, m.EFFECTIVE_HHI}:
        return a.AlertPredicate(
            family=f.EFFECTIVE_COMPANY_CONCENTRATION,
            metric=metric,
            comparison=c.GT,
            threshold=Decimal("0.1"),
            entity_id=uid(110) if metric is m.EFFECTIVE_ENTITY_WEIGHT else None,
        )
    if metric in {m.ETF_PAIR_OVERLAP, m.PORTFOLIO_DUPLICATED_EXPOSURE}:
        return a.AlertPredicate(
            family=f.ETF_OVERLAP,
            metric=metric,
            comparison=c.GT,
            threshold=Decimal("0.1"),
            left_fund_id=uid(20) if metric is m.ETF_PAIR_OVERLAP else None,
            right_fund_id=uid(30) if metric is m.ETF_PAIR_OVERLAP else None,
        )
    if metric in {m.CASH_AMOUNT, m.CASH_WEIGHT}:
        return a.AlertPredicate(
            family=f.CASH_THRESHOLD,
            metric=metric,
            comparison=c.GT,
            threshold=Decimal("0.1"),
            currency=EUR if metric is m.CASH_AMOUNT else None,
        )
    if metric in {m.SOURCE_AGE_SECONDS, m.SOURCE_MISSING_SESSIONS}:
        return a.AlertPredicate(
            family=f.STALE_DATA,
            metric=metric,
            comparison=c.GT,
            threshold=1,
            source_family=a.AlertSourceFamily.PRICE,
            source_id=uid(7),
            calendar_version_id=uid(8) if metric is m.SOURCE_MISSING_SESSIONS else None,
        )
    if metric in {m.MISSING_COUNT, m.MISSING_FRACTION}:
        return a.AlertPredicate(
            family=f.MISSING_COVERAGE,
            metric=metric,
            comparison=c.GT,
            threshold=1 if metric is m.MISSING_COUNT else Decimal("0.1"),
            domain=a.AlertSourceFamily.VALUATION,
            source_id=uid(7),
        )
    if metric in {m.RECONCILIATION_FAILED, m.RECONCILIATION_DISCREPANCY_COUNT}:
        return a.AlertPredicate(
            family=f.RECONCILIATION_FAILURE,
            metric=metric,
            comparison=c.EQ if metric is m.RECONCILIATION_FAILED else c.GT,
            threshold=True if metric is m.RECONCILIATION_FAILED else 1,
        )
    if metric in {m.PROVIDER_FAILED, m.PROVIDER_CONSECUTIVE_FAILURES}:
        return a.AlertPredicate(
            family=f.PROVIDER_FAILURE,
            metric=metric,
            comparison=c.EQ if metric is m.PROVIDER_FAILED else c.GT,
            threshold=True if metric is m.PROVIDER_FAILED else 1,
            provider_id=uid(9),
            window_seconds=300,
        )
    if metric is m.REFRESH_FAILED:
        return a.AlertPredicate(family=f.FAILED_REFRESH, metric=metric)
    if metric is m.POSITIVE_DIVIDEND:
        return a.AlertPredicate(family=f.DIVIDEND_RECEIVED, metric=metric)
    if metric is m.REPORT_TERMINAL:
        return a.AlertPredicate(
            family=f.REPORT_OUTCOME, metric=metric, outcome=a.AlertReportOutcome.EITHER
        )
    return a.AlertPredicate(
        family=f.UNUSUAL_ACTIVITY,
        metric=metric,
        window_seconds=300,
        comparison=None if metric is m.UNCLASSIFIED_ACTIVITY else c.GT,
        threshold=None
        if metric is m.UNCLASSIFIED_ACTIVITY
        else 1
        if metric is m.ACTIVITY_COUNT
        else Decimal("0.1"),
        currency=EUR if metric is m.ABSOLUTE_EXTERNAL_FLOW_AMOUNT else None,
    )


def context(*, quality: QualityState = QualityState.FRESH) -> a.AlertResultContext:
    return a.AlertResultContext(
        key="canonical",
        account_id=uid(2),
        source_cutoff_at=AT,
        valuation_at=AT,
        method_key="captured_canonical",
        method_version="1.0.0",
        quality=quality,
        reporting_currency=EUR,
    )


def capture(
    metric: a.AlertMetric = a.AlertMetric.CASH_WEIGHT, *, scalar: Decimal | int | bool | None = None
) -> a.AlertEvaluationInput:
    rule = predicate(metric)
    definition = a.AlertRuleDefinition(
        name="Synthetic rule",
        predicate=rule,
        schedule=a.AlertIntervalSchedule(anchor_at=AT - timedelta(days=1)),
    )
    version = a.AlertRuleVersion(
        id=uid(3),
        rule_id=uid(1),
        owner_id=uid(10),
        account_id=uid(2),
        version_number=1,
        created_at=AT - timedelta(days=1),
        content_digest=alert_record_digest(definition),
        definition=definition,
    )
    kind = a.alert_metric_kind(metric)
    if scalar is None:
        scalar = (
            Decimal("0.5")
            if kind is a.AlertMetricKind.DECIMAL
            else 2
            if kind is a.AlertMetricKind.INTEGER
            else True
        )
    observed = a.AlertObservedMetric(
        metric=metric,
        kind=kind,
        value=scalar,
        availability=a.AlertAvailability.AVAILABLE,
        quality=QualityState.FRESH,
        origin=a.AlertOrigin.DERIVED_DETERMINISTIC,
        context_key="canonical",
        currency=rule.currency,
    )
    observation = a.AlertMetricObservation(observed=observed, comparison_basis=scalar)
    payload: a.AlertThresholdInput | a.AlertEventBatchInput = a.AlertThresholdInput(
        observation=observation
    )
    if kind is a.AlertMetricKind.EVENT or metric is a.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT:
        payload = a.AlertEventBatchInput(
            events=(
                a.AlertEventObservation(
                    identity=uid(20),
                    revision_id=uid(21),
                    economic_at=AT - timedelta(seconds=100),
                    first_eligible_at=AT - timedelta(seconds=1),
                    observation=observation,
                    activity_kind=HistoricalCashFlowKind.DEPOSIT,
                    net_amount=Money(Decimal("2"), EUR),
                    report_outcome=a.AlertReportOutcome.SUCCEEDED,
                ),
            ),
            complete=True,
        )
    return a.AlertEvaluationInput(
        version=version,
        scheduled_for=AT,
        source_cutoff_at=AT,
        observation_window=a.AlertObservationWindow(
            start_at=AT - timedelta(seconds=300), end_at=AT, newly_known_revisions=True
        ),
        payload=payload,
        contexts=(context(),),
    )


def with_rule(
    value: a.AlertEvaluationInput,
    rule: a.AlertPredicate | None = None,
    *,
    policy: a.AlertQualityPolicy | None = None,
) -> a.AlertEvaluationInput:
    definition = replace(
        value.version.definition,
        predicate=rule or value.version.definition.predicate,
        quality_policy=policy or value.version.definition.quality_policy,
    )
    return replace(
        value,
        version=replace(
            value.version, definition=definition, content_digest=alert_record_digest(definition)
        ),
    )
