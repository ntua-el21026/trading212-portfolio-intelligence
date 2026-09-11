from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest
from trading212_analytics.alerts import (
    cash_observation,
    compare_alert_basis,
    convert_alert_money,
    direct_concentration_observation,
    drift_observation,
    evaluate_alert,
    reduce_alert_condition,
    xray_observation,
)
from trading212_analytics.planning import calculate_drift
from trading212_analytics.xray import calculate_xray
from trading212_domain import alerts as a
from trading212_domain.alert_serialization import (
    decode_alert_input,
    encode_alert_input,
    encode_alert_result,
)
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.values import CurrencyCode, Money

from .alert_factories import AT, EUR, capture, context, predicate, uid, with_rule
from .planning_factories import planning_input
from .xray_factories import fixture as xray_fixture

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("metric", tuple(a.AlertMetric))
def test_all_27_closed_metrics_evaluate_from_immutable_typed_capture(metric: a.AlertMetric) -> None:
    value = capture(metric)
    result = evaluate_alert(value)
    assert result.outcome is a.AlertEvaluationOutcome.MATCHED
    assert result.decision is True
    assert result.source_cutoff_at == AT
    assert result.input_digest
    assert encode_alert_result(
        evaluate_alert(decode_alert_input(encode_alert_input(value)))
    ) == encode_alert_result(result)


@pytest.mark.parametrize(
    "operator,expected",
    [
        (a.AlertComparison.GT, (None, None, True)),
        (a.AlertComparison.GTE, (None, True, True)),
        (a.AlertComparison.LT, (None, False, False)),
        (a.AlertComparison.LTE, (None, None, False)),
        (a.AlertComparison.EQ, (None, None, False)),
    ],
)
def test_lower_bound_decisions_do_not_invent_false_or_equality(
    operator: a.AlertComparison, expected: tuple[bool | None, ...]
) -> None:
    actual = tuple(
        compare_alert_basis(
            a.AlertRatioBasis(numerator=Decimal(n), denominator=Decimal(10)),
            Decimal("0.5"),
            operator,
            a.AlertBound.LOWER_BOUND,
        )
        for n in (4, 5, 6)
    )
    assert actual == expected


@pytest.mark.parametrize("operator", tuple(a.AlertComparison))
def test_exact_ratio_comparison_matches_independent_fraction(operator: a.AlertComparison) -> None:
    for numerator in (0, 1, 5, 10, 10**180 + 1):
        denominator = 10 if numerator < 20 else 10**181
        basis = a.AlertRatioBasis(numerator=Decimal(numerator), denominator=Decimal(denominator))
        expected = Fraction(numerator, denominator)
        threshold = Fraction(1, 2)
        truth = {
            a.AlertComparison.GT: expected > threshold,
            a.AlertComparison.GTE: expected >= threshold,
            a.AlertComparison.LT: expected < threshold,
            a.AlertComparison.LTE: expected <= threshold,
            a.AlertComparison.EQ: expected == threshold,
        }
        with localcontext() as ambient:
            ambient.prec = 2
            assert compare_alert_basis(basis, Decimal("0.5"), operator) is truth[operator]


@pytest.mark.parametrize(
    "quality",
    (QualityState.STALE, QualityState.ESTIMATED, QualityState.PARTIAL, QualityState.UNRECONCILED),
)
def test_financial_quality_suppresses_default_and_degraded_policy_preserves_state(
    quality: QualityState,
) -> None:
    value = capture()
    assert isinstance(value.payload, a.AlertThresholdInput)
    observation = replace(
        value.payload.observation,
        observed=replace(value.payload.observation.observed, quality=quality),
    )
    value = replace(value, payload=a.AlertThresholdInput(observation=observation))
    assert evaluate_alert(value).outcome is a.AlertEvaluationOutcome.SUPPRESSED
    result = evaluate_alert(with_rule(value, policy=a.AlertQualityPolicy.ALLOW_DEGRADED))
    assert result.decision is True and result.observation and result.observation.quality is quality


@pytest.mark.parametrize(
    "metric",
    (
        a.AlertMetric.SOURCE_AGE_SECONDS,
        a.AlertMetric.MISSING_COUNT,
        a.AlertMetric.RECONCILIATION_FAILED,
        a.AlertMetric.PROVIDER_FAILED,
    ),
)
def test_health_rules_can_evaluate_the_degradation_they_observe(metric: a.AlertMetric) -> None:
    value = capture(metric)
    assert isinstance(value.payload, a.AlertThresholdInput)
    value = replace(
        value,
        payload=a.AlertThresholdInput(
            observation=replace(
                value.payload.observation,
                observed=replace(value.payload.observation.observed, quality=QualityState.FAILED),
                material_complete=False,
            )
        ),
    )
    assert evaluate_alert(value).decision is True


def test_unknown_denominator_is_unavailable_for_both_quality_policies() -> None:
    value = capture()
    obs = cash_observation(
        predicate(),
        cash=(Money(Decimal(0), EUR),),
        portfolio_total=Money(Decimal(0), EUR),
        context=context(),
    )
    value = replace(value, payload=a.AlertThresholdInput(observation=obs))
    for policy in a.AlertQualityPolicy:
        result = evaluate_alert(with_rule(value, policy=policy))
        assert result.decision is None and result.reason is a.AlertReason.UNKNOWN_DENOMINATOR


@pytest.mark.parametrize("policy", tuple(a.AlertQualityPolicy))
@pytest.mark.parametrize("amount", (Decimal("0"), Decimal("1")))
@pytest.mark.parametrize("failed_availability", (False, True))
def test_failed_material_cannot_emit_or_clear_under_either_policy(
    policy: a.AlertQualityPolicy, amount: Decimal, failed_availability: bool
) -> None:
    value = with_rule(capture(scalar=amount), policy=policy)
    assert isinstance(value.payload, a.AlertThresholdInput)
    observation = value.payload.observation
    observation = replace(
        observation,
        observed=replace(
            observation.observed,
            quality=QualityState.FRESH if failed_availability else QualityState.FAILED,
            availability=a.AlertAvailability.FAILED
            if failed_availability
            else a.AlertAvailability.AVAILABLE,
            value=None if failed_availability else amount,
            reason=a.AlertReason.COMPUTATION_FAILED if failed_availability else None,
        ),
        comparison_basis=None if failed_availability else amount,
    )
    value = replace(value, payload=a.AlertThresholdInput(observation=observation))
    result = evaluate_alert(value)
    assert result.outcome is a.AlertEvaluationOutcome.FAILED
    assert result.reason is a.AlertReason.COMPUTATION_FAILED and result.decision is None
    state = a.AlertConditionState(
        rule_version_id=value.version.id,
        armed=False,
        open_episode_id=uid(801),
        last_conclusive_decision=True,
    )
    transition = reduce_alert_condition(state, result, cooldown_seconds=0)
    assert not transition.create and transition.resolve_episode_id is None
    assert not transition.state.armed and transition.state.open_episode_id == state.open_episode_id


@pytest.mark.parametrize("metric", (a.AlertMetric.REFRESH_FAILED, a.AlertMetric.REPORT_TERMINAL))
def test_known_terminal_outcome_is_observable_without_financial_quality_suppression(
    metric: a.AlertMetric,
) -> None:
    value = capture(metric)
    assert isinstance(value.payload, a.AlertEventBatchInput)
    event = value.payload.events[0]
    observation = replace(
        event.observation,
        observed=replace(event.observation.observed, quality=QualityState.FAILED),
        material_complete=False,
    )
    value = replace(
        value, payload=replace(value.payload, events=(replace(event, observation=observation),))
    )
    assert evaluate_alert(value).decision is True


@pytest.mark.parametrize(
    "include_cash,expected", [(False, Decimal("0.37")), (True, Decimal("0.38"))]
)
def test_direct_hhi_uses_complete_full_denominator_with_explicit_cash(
    include_cash: bool, expected: Decimal
) -> None:
    p = replace(predicate(a.AlertMetric.DIRECT_HHI), include_cash=include_cash)
    with localcontext() as ambient:
        ambient.prec = 2
        observed = direct_concentration_observation(
            p,
            positions=(Money(Decimal(60), EUR), Money(Decimal(10), EUR)),
            cash=(Money(Decimal(10), EUR),),
            portfolio_total=Money(Decimal(100), EUR),
            context=context(),
        )
    assert observed.observed.value == expected
    assert type(observed.comparison_basis) is Decimal


def test_cash_negative_amount_and_missing_fx_remain_distinct() -> None:
    p = predicate(a.AlertMetric.CASH_AMOUNT)
    observed = cash_observation(
        p, cash=(Money(Decimal(-2), EUR),), portfolio_total=None, context=context()
    )
    assert observed.observed.value == Decimal(-2) and observed.observed.currency == EUR
    missing = cash_observation(
        p, cash=(Money(Decimal(2), CurrencyCode("USD")),), portfolio_total=None, context=context()
    )
    assert missing.observed.value is None and missing.observed.reason is a.AlertReason.MISSING_FX


def test_sourced_fx_general_canonical_boundary_and_compatible_two_leg_order() -> None:
    usd, gbp = CurrencyCode("USD"), CurrencyCode("GBP")
    legs = (
        a.AlertFxLeg(
            base=EUR,
            quote=usd,
            rate=Decimal(3),
            source_reference_key="first",
            snapshot_id=uid(40),
            provider_id=uid(41),
            observed_at=AT,
        ),
        a.AlertFxLeg(
            base=usd,
            quote=gbp,
            rate=Decimal("0.2"),
            source_reference_key="second",
            snapshot_id=uid(40),
            provider_id=uid(41),
            observed_at=AT,
        ),
    )
    value = convert_alert_money(Money(Decimal(-1), EUR), gbp, legs=legs)
    assert value.converted == Money(Decimal("-0.6"), gbp) and value.comparison_basis == Decimal(
        "-0.6"
    )
    inverse = replace(legs[0], inverse=True)
    converted = convert_alert_money(Money(Decimal(1), usd), EUR, legs=(inverse,))
    assert converted.comparison_basis == Decimal("0.333333333333333333")
    assert type(converted.comparison_basis) is Decimal
    with pytest.raises(DomainError):
        convert_alert_money(
            Money(Decimal(1), EUR), gbp, legs=(legs[0], replace(legs[1], snapshot_id=uid(42)))
        )
    assert convert_alert_money(Money(Decimal(1), EUR), usd).converted is None


def test_drift_named_frontier_keeps_groups_leaves_cash_and_original_identity() -> None:
    calculation = calculate_drift(planning_input(("60", "20"), cash="20", grouped=True))
    p = replace(
        predicate(a.AlertMetric.PORTFOLIO_L1_DRIFT),
        target_version_id=uid(int(calculation.context.target_version_id.replace("-", ""), 16)),
        frontier_depth=1,
    )
    shallow = drift_observation(p, calculation, context_key="drift")
    deep = drift_observation(replace(p, frontier_depth=8), calculation, context_key="drift")
    assert shallow.observed.value == Decimal("0.2")
    assert deep.observed.value == calculation.totals.l1_drift == Decimal("0.3")
    group = next(row for row in calculation.rows if row.kind == "group")
    assert group.node_id is not None
    gp = replace(
        predicate(a.AlertMetric.GROUP_ABSOLUTE_DRIFT),
        target_version_id=p.target_version_id,
        group_node_id=uid(int(group.node_id.replace("-", ""), 16)),
    )
    assert drift_observation(gp, calculation, context_key="drift").observed.value == Decimal("0.2")
    unknown = drift_observation(
        replace(gp, group_node_id=uid(999)), calculation, context_key="drift"
    )
    assert unknown.observed.reason is a.AlertReason.UNKNOWN_IDENTITY


@pytest.mark.parametrize(
    "metric,expected",
    [
        (a.AlertMetric.EFFECTIVE_ENTITY_WEIGHT, "0.56"),
        (a.AlertMetric.EFFECTIVE_TOP_N_WEIGHT, "0.95"),
        (a.AlertMetric.EFFECTIVE_HHI, "0.4657"),
        (a.AlertMetric.ETF_PAIR_OVERLAP, "0.5"),
        (a.AlertMetric.PORTFOLIO_DUPLICATED_EXPOSURE, "0.41"),
    ],
)
def test_xray_uses_full_private_exact_basis_and_preserves_lower_bound(
    metric: a.AlertMetric, expected: str
) -> None:
    result = xray_observation(predicate(metric), calculate_xray(xray_fixture()), context=context())
    assert result.observed.value == Decimal(expected)
    assert isinstance(result.comparison_basis, a.AlertRatioBasis)
    assert result.observed.bound is a.AlertBound.LOWER_BOUND
    assert result.material_complete is False


def test_episode_unknown_manual_close_rearm_and_cooldown_are_independent() -> None:
    result = evaluate_alert(capture())
    state = a.AlertConditionState(rule_version_id=result.rule_version_id)
    first = reduce_alert_condition(state, result, cooldown_seconds=600)
    assert len(first.create) == 1 and not first.state.armed
    open_state = replace(first.state, open_episode_id=uid(60))
    unknown = replace(
        result,
        scheduled_for=AT + timedelta(seconds=300),
        source_cutoff_at=AT + timedelta(seconds=300),
        contexts=(),
        observation=None,
        outcome=a.AlertEvaluationOutcome.UNAVAILABLE,
        decision=None,
        reason=a.AlertReason.MISSING_INPUT,
    )
    gap = reduce_alert_condition(open_state, unknown, cooldown_seconds=600)
    assert gap.state.open_episode_id == uid(60) and not gap.state.armed and not gap.create
    # Manually resolved continuously true state retains the latch.
    manual = replace(gap.state, open_episode_id=None)
    later = replace(
        result,
        scheduled_for=AT + timedelta(seconds=400),
        source_cutoff_at=AT + timedelta(seconds=400),
        contexts=(replace(context(), source_cutoff_at=AT + timedelta(seconds=400)),),
    )
    assert not reduce_alert_condition(manual, later, cooldown_seconds=600).create
    false = replace(later, outcome=a.AlertEvaluationOutcome.NOT_MATCHED, decision=False)
    reset = reduce_alert_condition(manual, false, cooldown_seconds=600)
    assert reset.state.armed
    last = replace(
        later,
        scheduled_for=AT + timedelta(seconds=500),
        source_cutoff_at=AT + timedelta(seconds=500),
        contexts=(replace(context(), source_cutoff_at=AT + timedelta(seconds=500)),),
    )
    reopened = reduce_alert_condition(reset.state, last, cooldown_seconds=600)
    assert reopened.create[0].episode_ordinal == 2
    assert reopened.create[0].notification_state is a.AlertNotificationState.SUPPRESSED_COOLDOWN
    assert (
        reduce_alert_condition(
            open_state,
            replace(result, execution_intent=a.AlertExecutionIntent.OBSERVE_ONLY),
            cooldown_seconds=600,
        ).state
        == open_state
    )


def test_event_replay_correction_and_empty_batch_never_rearm_threshold_latch() -> None:
    value = capture(a.AlertMetric.POSITIVE_DIVIDEND)
    result = evaluate_alert(value)
    initial = a.AlertConditionState(
        rule_version_id=value.version.id, armed=False, last_conclusive_decision=True
    )
    digest = result.event_decisions[0].deduplication_digest
    plan = reduce_alert_condition(
        initial, result, cooldown_seconds=60, known_event_digests=frozenset({digest})
    )
    assert plan.create == () and plan.state.last_eligible_notification_at is None
    assert isinstance(value.payload, a.AlertEventBatchInput)
    event = value.payload.events[0]
    corrected = replace(
        value,
        payload=replace(
            value.payload,
            events=(replace(event, revision_id=uid(22), correction_of=event.revision_id),),
        ),
    )
    correction = evaluate_alert(corrected).event_decisions[0]
    assert (
        correction.deduplication_digest != digest and correction.correction_of == event.revision_id
    )
    empty = evaluate_alert(replace(value, payload=a.AlertEventBatchInput(events=(), complete=True)))
    assert empty.decision is False
    assert not reduce_alert_condition(initial, empty, cooldown_seconds=60).state.armed


def test_event_window_filters_before_quality_and_negative_flow_uses_each_absolute_revision() -> (
    None
):
    value = capture(a.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT, scalar=Decimal("-2"))
    assert evaluate_alert(value).decision is True
    assert isinstance(value.payload, a.AlertEventBatchInput)
    event = value.payload.events[0]
    outside = replace(event, first_eligible_at=value.observation_window.start_at)
    result = evaluate_alert(replace(value, payload=replace(value.payload, events=(outside,))))
    assert (
        result.decision is False
        and result.event_decisions[0].observation.reason is a.AlertReason.FILTERED_OUT
    )


def test_subquantum_xray_positive_lower_bound_compares_exactly_and_replays() -> None:
    value = capture(a.AlertMetric.EFFECTIVE_ENTITY_WEIGHT)
    assert isinstance(value.payload, a.AlertThresholdInput)
    observation = replace(
        value.payload.observation,
        observed=replace(
            value.payload.observation.observed,
            value=Decimal("0"),
            availability=a.AlertAvailability.PARTIAL,
            quality=QualityState.PARTIAL,
            bound=a.AlertBound.LOWER_BOUND,
            positive_below_quantum=True,
        ),
        comparison_basis=a.AlertRatioBasis(numerator=Decimal(1), denominator=Decimal(10**30)),
        material_complete=False,
    )
    value = replace(value, payload=a.AlertThresholdInput(observation=observation))
    rule = replace(
        value.version.definition.predicate, comparison=a.AlertComparison.GT, threshold=Decimal(0)
    )
    value = with_rule(value, rule)
    assert evaluate_alert(value).outcome is a.AlertEvaluationOutcome.SUPPRESSED
    allowed = with_rule(value, policy=a.AlertQualityPolicy.ALLOW_DEGRADED)
    result = evaluate_alert(allowed)
    assert result.decision is True and result.observation is not None
    assert result.observation.value == 0 and result.observation.positive_below_quantum
    assert encode_alert_result(
        evaluate_alert(decode_alert_input(encode_alert_input(allowed)))
    ) == encode_alert_result(result)
    assert b"comparison_basis" not in encode_alert_result(result)
    invalid = replace(
        allowed,
        payload=a.AlertThresholdInput(
            observation=replace(
                observation, observed=replace(observation.observed, positive_below_quantum=False)
            )
        ),
    )
    with pytest.raises(DomainError):
        evaluate_alert(invalid)


@pytest.mark.parametrize("irrelevant", ("negative", "wrong_instrument"))
def test_irrelevant_dividend_is_filtered_before_net_or_fx_requirements(irrelevant: str) -> None:
    value = capture(a.AlertMetric.POSITIVE_DIVIDEND)
    assert isinstance(value.payload, a.AlertEventBatchInput)
    event = value.payload.events[0]
    rule = replace(
        value.version.definition.predicate,
        minimum_net_amount=Money(Decimal("2"), EUR),
        instrument_id=uid(400) if irrelevant == "wrong_instrument" else None,
    )
    event = replace(
        event,
        net_amount=Money(Decimal("-3"), CurrencyCode("USD")) if irrelevant == "negative" else None,
        instrument_id=uid(401) if irrelevant == "wrong_instrument" else event.instrument_id,
        observation=replace(
            event.observation,
            observed=replace(event.observation.observed, quality=QualityState.FAILED),
        ),
    )
    value = with_rule(replace(value, payload=replace(value.payload, events=(event,))), rule)
    result = evaluate_alert(value)
    assert result.decision is False
    assert result.event_decisions[0].observation.reason is a.AlertReason.FILTERED_OUT
    assert result.event_decisions[0].decision is False


@pytest.mark.parametrize(
    "metric",
    (
        a.AlertMetric.EFFECTIVE_ENTITY_WEIGHT,
        a.AlertMetric.EFFECTIVE_TOP_N_WEIGHT,
        a.AlertMetric.EFFECTIVE_HHI,
        a.AlertMetric.ETF_PAIR_OVERLAP,
        a.AlertMetric.PORTFOLIO_DUPLICATED_EXPOSURE,
    ),
)
def test_xray_selected_metric_quality_and_slot_limitation_preserve_exact_basis(
    metric: a.AlertMetric,
) -> None:
    saved = calculate_xray(xray_fixture())
    selected = replace(
        saved,
        exposure_buckets=tuple(
            replace(
                bucket,
                absolute_weight=replace(bucket.absolute_weight, quality=QualityState.UNRECONCILED),
            )
            for bucket in saved.exposure_buckets
        ),
        portfolio_summary=replace(
            saved.portfolio_summary,
            hhi=replace(saved.portfolio_summary.hhi, quality=QualityState.UNRECONCILED),
            duplicated_exposure=replace(
                saved.portfolio_summary.duplicated_exposure, quality=QualityState.UNRECONCILED
            ),
        ),
        fund_compositions=tuple(
            replace(fund, quality=QualityState.UNRECONCILED) for fund in saved.fund_compositions
        ),
    )
    original_digest = selected.content_digest
    original = xray_observation(predicate(metric), saved, context=context())
    observed = xray_observation(
        predicate(metric), selected, context=context(quality=QualityState.STALE)
    )
    # The canonical pair calculator reports PARTIAL when its composition is incomplete;
    # the alert retains that selected metric state rather than the private fund state.
    assert observed.observed.quality is (
        QualityState.PARTIAL
        if metric is a.AlertMetric.ETF_PAIR_OVERLAP
        else QualityState.UNRECONCILED
    )
    assert observed.observed.value == original.observed.value
    assert observed.comparison_basis == original.comparison_basis
    assert selected.content_digest == original_digest
    unreconciled = xray_observation(
        predicate(metric), saved, context=context(quality=QualityState.UNRECONCILED)
    )
    assert unreconciled.observed.quality is QualityState.UNRECONCILED
    failed = xray_observation(
        predicate(metric), selected, context=context(quality=QualityState.FAILED)
    )
    assert failed.observed.quality is QualityState.FAILED
