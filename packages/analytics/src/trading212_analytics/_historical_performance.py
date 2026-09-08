"""Exact historical returns and bounded daily/period projections."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from trading212_domain import Coverage, Instant, Money
from trading212_domain import historical as d
from trading212_domain import historical_results as r

from ._decimal import persisted_decimal
from ._historical_core import (
    ONE,
    ZERO,
    HistoricalEngine,
    amount,
    close_boundaries,
    dividend_parts,
    elapsed,
    event_money,
    known,
    midnight,
    money_metric,
    projection_boundaries,
    ratio_metric,
)
from .performance import (
    MODIFIED_DIETZ_METHOD_ID,
    PERFORMANCE_VERSION,
    TWR_METHOD_ID,
    XIRR_METHOD_ID,
    DatedExternalFlow,
    SubperiodReturnInput,
    calculate_modified_dietz,
    calculate_time_weighted_return,
    calculate_xirr,
)


@dataclass(frozen=True, slots=True)
class PeriodReturns:
    twr: d.HistoricalRatioMetric
    mwr: d.HistoricalRatioMetric
    dietz: d.HistoricalRatioMetric
    annual_twr: d.HistoricalRatioMetric
    annual_dietz: d.HistoricalRatioMetric
    denominator: Decimal | None


def annual(value: Decimal | None, start: datetime, end: datetime) -> d.HistoricalRatioMetric:
    duration = elapsed(start, end)
    if duration < 365 * 86400:
        return ratio_metric(None, reason=d.HistoricalReason.SHORT_PERIOD)
    if value is None or value + ONE <= 0:
        return ratio_metric(None, reason=d.HistoricalReason.NONPOSITIVE_DENOMINATOR)
    return ratio_metric((value + ONE) ** (Decimal(365 * 86400) / duration) - ONE)


def period_events(
    engine: HistoricalEngine, start: datetime, end: datetime
) -> tuple[d.HistoricalEvent, ...]:
    return tuple(item for item in engine.events(end)[0] if start <= item.identity.economic_at < end)


def converted_event(
    engine: HistoricalEngine, event: d.HistoricalEvent, native: Money | None = None
) -> Decimal | None:
    native = native if native is not None else event_money(event)
    if native is None:
        return None
    return engine.convert(
        native,
        event.identity.economic_at,
        r.HistoricalUseConsumer(kind="event", event_revision_id=event.identity.revision_id),
    )


def event_total(
    engine: HistoricalEngine,
    events: tuple[d.HistoricalEvent, ...],
    measure: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> d.HistoricalMoneyMetric:
    total = ZERO
    start, end = start or engine.window.start_at, end or engine.window.end_at
    complete = engine.activity_complete(start, end, end)
    missing = d.HistoricalReason.EVENT_COVERAGE
    for event in events:
        native: Money | None = None
        applicable = False
        if measure in ("flow", "deposit", "withdrawal") and isinstance(
            event, d.HistoricalExternalFlow
        ):
            applicable = (
                measure == "flow"
                or (measure == "deposit" and event.signed_amount.amount >= 0)
                or (measure == "withdrawal" and event.signed_amount.amount < 0)
            )
            native = event.signed_amount
        elif measure == "income":
            if isinstance(event, d.HistoricalDividend):
                applicable, native = True, event.net
            elif isinstance(event, d.HistoricalCashEffect) and event.effect_kind == "interest":
                applicable, native = True, event.signed_amount
        elif measure in ("fee", "tax"):
            if isinstance(event, d.HistoricalExecution):
                applicable = True
                native = known(event.fees if measure == "fee" else event.taxes)
                missing = (
                    d.HistoricalReason.FEE_UNKNOWN
                    if measure == "fee"
                    else d.HistoricalReason.WITHHOLDING_UNKNOWN
                )
            elif isinstance(event, d.HistoricalDividend) and measure == "tax":
                applicable, native = True, dividend_parts(engine, event)[1]
                missing = d.HistoricalReason.WITHHOLDING_UNKNOWN
            elif isinstance(event, d.HistoricalCashEffect) and event.effect_kind == measure:
                applicable, native = (
                    True,
                    Money(-event.signed_amount.amount, event.signed_amount.currency),
                )
        if not applicable:
            continue
        converted = converted_event(engine, event, native) if native is not None else None
        if converted is None:
            complete = False
            if native is not None:
                missing = d.HistoricalReason.FX_MISSING
        else:
            total += -converted if measure == "withdrawal" else converted
    degraded = engine.window.coverage_policy.value == "allow_degraded"
    return money_metric(
        total if complete or degraded else None,
        engine.currency,
        reason=missing,
        coverage=d.HistoricalCoverageKey.EVENTS,
        partial=not complete and degraded,
    )


def _transition(engine: HistoricalEngine, start: datetime, end: datetime) -> bool:
    if engine.window.knowledge_policy is not d.KnowledgePolicy.POINT_IN_TIME:
        return False
    before = {
        item.identity.economic_key: item.identity.revision_id
        for item in engine.events(start)[0]
        if item.identity.economic_at <= start
    }
    after = {
        item.identity.economic_key: item.identity.revision_id
        for item in engine.events(end)[0]
        if item.identity.economic_at <= start
    }
    return before != after or engine.source_transition(start, end)


def period_returns(
    engine: HistoricalEngine, start: datetime, end: datetime, *, xirr: bool = True
) -> PeriodReturns:
    beginning, ending = engine.valuation(start), engine.valuation(end)
    unavailable = ratio_metric(None)
    short = ratio_metric(None, reason=d.HistoricalReason.SHORT_PERIOD)
    if beginning.total is None or ending.total is None or beginning.partial or ending.partial:
        return PeriodReturns(unavailable, unavailable, unavailable, short, short, None)
    if _transition(engine, start, end):
        unavailable = ratio_metric(None, reason=d.HistoricalReason.KNOWLEDGE_TRANSITION)
        engine.warnings.add(d.HistoricalReason.KNOWLEDGE_TRANSITION)
        return PeriodReturns(unavailable, unavailable, unavailable, short, short, None)
    events = period_events(engine, start, end)
    flows: list[DatedExternalFlow] = []
    grouped: dict[datetime, Decimal] = defaultdict(lambda: ZERO)
    for event in events:
        if isinstance(event, d.HistoricalExternalFlow):
            converted = converted_event(engine, event)
            if converted is None:
                unavailable = ratio_metric(None, reason=d.HistoricalReason.FX_MISSING)
                return PeriodReturns(unavailable, unavailable, unavailable, short, short, None)
            grouped[event.identity.economic_at] += converted
    for at, total in sorted(grouped.items()):
        flows.append(
            DatedExternalFlow(Money(persisted_decimal(total), engine.currency), Instant(at))
        )
    coverage = Coverage(Instant(start), Instant(end), engine.activity_complete(start, end, end))
    engine.primitive_methods.add((MODIFIED_DIETZ_METHOD_ID, PERFORMANCE_VERSION))
    dietz = calculate_modified_dietz(
        beginning_value=Money(persisted_decimal(beginning.total), engine.currency),
        ending_value=Money(persisted_decimal(ending.total), engine.currency),
        period_start=Instant(start),
        period_end=Instant(end),
        external_flows=tuple(flows),
        coverage=coverage,
    )
    dietz_value = dietz.value.value if dietz.value else None
    duration = elapsed(start, end)
    denominator: Decimal | None = beginning.total + sum(
        (elapsed(at, end) / duration * flow for at, flow in grouped.items()), ZERO
    )
    denominator = denominator if denominator is not None and denominator > 0 else None
    dm = ratio_metric(
        dietz_value,
        reason=d.HistoricalReason.NONPOSITIVE_DENOMINATOR
        if denominator is None
        else d.HistoricalReason.EVENT_COVERAGE,
    )
    annual_dm = annual(dietz_value, start, end)
    if xirr:
        engine.primitive_methods.add((XIRR_METHOD_ID, PERFORMANCE_VERSION))
        irr = calculate_xirr(
            beginning_value=Money(persisted_decimal(beginning.total), engine.currency),
            ending_value=Money(persisted_decimal(ending.total), engine.currency),
            period_start=Instant(start),
            period_end=Instant(end),
            external_flows=tuple(flows),
            coverage=coverage,
        )
        reasons = {
            "xirr_ambiguous_roots": d.HistoricalReason.XIRR_NONCONVENTIONAL,
            "xirr_no_root": d.HistoricalReason.XIRR_NO_ROOT,
            "xirr_not_bracketed": d.HistoricalReason.XIRR_NOT_BRACKETED,
            "xirr_non_convergence": d.HistoricalReason.XIRR_NOT_CONVERGED,
            "xirr_numeric_failure": d.HistoricalReason.NUMERIC_FAILURE,
            "xirr_prerequisites_missing": d.HistoricalReason.EVENT_COVERAGE,
        }
        irr_reason = next(
            (reasons[warning.code] for warning in irr.warnings if warning.code in reasons),
            d.HistoricalReason.XIRR_NO_ROOT,
        )
        mwr = ratio_metric(irr.value.value if irr.value else None, reason=irr_reason)
    else:
        mwr = unavailable
    segments: list[SubperiodReturnInput] = []
    previous_at, previous_value = start, beginning.total + grouped.get(start, ZERO)
    reason = d.HistoricalReason.TWR_FLOW_ANCHOR
    for at in sorted(instant for instant in grouped if instant > start):
        post = engine.valuation(at, after=True)
        if not post.exact or post.total is None or post.partial:
            return PeriodReturns(
                ratio_metric(None, reason=reason),
                mwr,
                dm,
                annual(None, start, end),
                annual_dm,
                denominator,
            )
        segments.append(
            SubperiodReturnInput(
                Instant(previous_at),
                Instant(at),
                Money(persisted_decimal(previous_value), engine.currency),
                Money(persisted_decimal(post.total), engine.currency),
                Money(persisted_decimal(grouped[at]), engine.currency),
            )
        )
        previous_at, previous_value = at, post.total
    segments.append(
        SubperiodReturnInput(
            Instant(previous_at),
            Instant(end),
            Money(persisted_decimal(previous_value), engine.currency),
            Money(persisted_decimal(ending.total), engine.currency),
            Money(ZERO, engine.currency),
        )
    )
    engine.primitive_methods.add((TWR_METHOD_ID, PERFORMANCE_VERSION))
    twr = calculate_time_weighted_return(subperiods=tuple(segments), coverage=coverage)
    twr_value = twr.value.value if twr.value else None
    return PeriodReturns(
        ratio_metric(twr_value, reason=d.HistoricalReason.NONPOSITIVE_DENOMINATOR),
        mwr,
        dm,
        annual(twr_value, start, end),
        annual_dm,
        denominator,
    )


def metric_for(returns: PeriodReturns, method: d.ReturnMethod) -> d.HistoricalRatioMetric:
    return {
        d.ReturnMethod.TWR: returns.twr,
        d.ReturnMethod.MWR: returns.mwr,
        d.ReturnMethod.MODIFIED_DIETZ: returns.dietz,
    }[method]


def performance(
    engine: HistoricalEngine, options: r.PerformanceOptions
) -> r.PerformanceCalculation:
    start, end = engine.window.start_at, engine.window.end_at
    beginning, ending = engine.valuation(start), engine.valuation(end)
    returns = period_returns(engine, start, end)
    events = period_events(engine, start, end)
    flows = event_total(engine, events, "flow")
    deposits, withdrawals = (
        event_total(engine, events, "deposit"),
        event_total(engine, events, "withdrawal"),
    )
    net = amount(flows)
    gain = (
        ending.total - beginning.total - net
        if ending.total is not None and beginning.total is not None and net is not None
        else None
    )
    realized = (
        sum(ending.state.realized.values(), ZERO) - sum(beginning.state.realized.values(), ZERO)
        if ending.state.cost_complete and beginning.state.cost_complete
        else None
    )
    unrealized: Decimal | None = ZERO if ending.state.cost_complete else None
    if unrealized is not None:
        for listing, quantity in ending.state.quantities.items():
            if quantity == 0:
                continue
            cost = ending.state.costs.get(listing)
            market = ending.holdings.get(listing)
            if cost is None or market is None:
                unrealized = None
                break
            converted = engine.convert(
                cost,
                end,
                r.HistoricalUseConsumer(kind="holding", listing_id=listing),
                "holding_valuation",
            )
            if converted is None:
                unrealized = None
                break
            unrealized += market - converted
    daily: list[r.PerformancePoint] = []
    peak, maximum_drawdown = ONE, ZERO
    max_complete = True
    previous = start
    chosen_boundaries = set(projection_boundaries(engine.value, options.frequency))
    mwr_selected = options.method is d.ReturnMethod.MWR
    xirr_identity = (XIRR_METHOD_ID, PERFORMANCE_VERSION)
    for ordinal, at in enumerate(close_boundaries(engine.value)):
        current = engine.valuation(at)
        # Projected intervals replace every daily interval return. Retain only the
        # first eligible XIRR invocation if an unavailable summary did not record it.
        interval = period_returns(
            engine,
            previous,
            at,
            xirr=mwr_selected and xirr_identity not in engine.primitive_methods,
        )
        cumulative = period_returns(
            engine,
            start,
            at,
            xirr=mwr_selected
            and (at in chosen_boundaries or xirr_identity not in engine.primitive_methods),
        )
        interval_events = period_events(engine, previous, at)
        cumulative_events = period_events(engine, start, at)
        cumulative_twr = cumulative.twr.value
        wealth = cumulative_twr + ONE if cumulative_twr is not None else None
        drawdown = None
        if wealth is not None:
            peak = max(peak, wealth)
            drawdown = wealth / peak - ONE if peak > 0 else None
            if drawdown is not None:
                maximum_drawdown = min(maximum_drawdown, drawdown)
        else:
            max_complete = False
        references = tuple(
            item.identity.revision_id
            for item in interval_events
            if isinstance(item, d.HistoricalExternalFlow)
        )
        daily.append(
            r.PerformancePoint(
                ordinal=ordinal,
                date=(at - timedelta(days=1)).date(),
                valuation_at=at,
                portfolio_value=money_metric(
                    current.total,
                    engine.currency,
                    partial=current.partial and current.total is not None,
                ),
                invested_value=money_metric(
                    current.invested,
                    engine.currency,
                    partial=current.partial and current.invested is not None,
                ),
                cash_value=money_metric(
                    current.cash,
                    engine.currency,
                    partial=current.partial and current.cash is not None,
                ),
                external_flow=event_total(engine, interval_events, "flow", start=previous, end=at),
                deposits=event_total(engine, cumulative_events, "deposit", start=start, end=at),
                withdrawals=event_total(
                    engine, cumulative_events, "withdrawal", start=start, end=at
                ),
                net_contributions=event_total(
                    engine, cumulative_events, "flow", start=start, end=at
                ),
                income=event_total(engine, cumulative_events, "income", start=start, end=at),
                fees=event_total(engine, cumulative_events, "fee", start=start, end=at),
                withholding_taxes=event_total(
                    engine, cumulative_events, "tax", start=start, end=at
                ),
                interval_return=metric_for(interval, options.method),
                cumulative_return=metric_for(cumulative, options.method),
                twr_wealth=ratio_metric(wealth),
                drawdown=ratio_metric(drawdown),
                flow_count=len(references),
                flow_revision_ids=references,
            )
        )
        previous = at
    summary = r.PerformanceMetrics(
        beginning_value=money_metric(
            beginning.total,
            engine.currency,
            partial=beginning.partial and beginning.total is not None,
        ),
        ending_value=money_metric(
            ending.total, engine.currency, partial=ending.partial and ending.total is not None
        ),
        deposits=deposits,
        withdrawals=withdrawals,
        net_contributions=flows,
        investment_gain=money_metric(
            gain,
            engine.currency,
            partial=beginning.partial or ending.partial if gain is not None else False,
        ),
        income=event_total(engine, events, "income"),
        fees=event_total(engine, events, "fee"),
        withholding_taxes=event_total(engine, events, "tax"),
        realized_profit_loss=money_metric(
            realized,
            engine.currency,
            reason=d.HistoricalReason.COST_COVERAGE,
            coverage=d.HistoricalCoverageKey.COST,
        ),
        unrealized_profit_loss=money_metric(
            unrealized,
            engine.currency,
            reason=d.HistoricalReason.COST_COVERAGE,
            coverage=d.HistoricalCoverageKey.COST,
        ),
        time_weighted_return=returns.twr,
        money_weighted_return=returns.mwr,
        modified_dietz_return=returns.dietz,
        annualized_time_weighted_return=returns.annual_twr,
        annualized_modified_dietz_return=returns.annual_dietz,
        maximum_drawdown=ratio_metric(maximum_drawdown if max_complete else None),
    )
    projected: list[r.PerformancePoint] = []
    previous = start
    for point in daily:
        if point.valuation_at not in chosen_boundaries:
            continue
        interval_events = period_events(engine, previous, point.valuation_at)
        refs = tuple(
            item.identity.revision_id
            for item in interval_events
            if isinstance(item, d.HistoricalExternalFlow)
        )
        from dataclasses import replace

        projected.append(
            replace(
                point,
                ordinal=len(projected),
                interval_return=metric_for(
                    period_returns(
                        engine,
                        previous,
                        point.valuation_at,
                        xirr=options.method is d.ReturnMethod.MWR,
                    ),
                    options.method,
                ),
                external_flow=event_total(
                    engine, interval_events, "flow", start=previous, end=point.valuation_at
                ),
                flow_count=len(refs),
                flow_revision_ids=refs,
            )
        )
        previous = point.valuation_at
    rolling, calendar = period_projections(engine, options)
    return r.PerformanceCalculation(
        context=engine.context(
            "performance_v2",
            available=gain is not None,
            partial=beginning.partial or ending.partial,
        ),
        options=options,
        summary=summary,
        points=tuple(projected),
        rolling_returns=rolling,
        calendar_returns=calendar,
        source_uses=engine.ordered_uses(),
        conversions=engine.ordered_conversions(),
    )


def period_projections(
    engine: HistoricalEngine, options: r.PerformanceOptions
) -> tuple[tuple[r.HistoricalPeriodReturn, ...], tuple[r.HistoricalPeriodReturn, ...]]:
    rolling: list[r.HistoricalPeriodReturn] = []
    calendar: list[r.HistoricalPeriodReturn] = []
    if options.rolling_window is not d.RollingWindow.NONE:
        days = {
            d.RollingWindow.DAYS_30: 30,
            d.RollingWindow.DAYS_90: 90,
            d.RollingWindow.DAYS_365: 365,
        }[options.rolling_window]
        for at in projection_boundaries(engine.value, options.frequency):
            start = at - timedelta(days=days)
            supported = start >= engine.window.start_at or any(
                item.start_at <= start and item.end_at >= at
                for item in engine.value.selection.support_windows
            )
            result = period_returns(engine, start, at) if supported else None
            value = (
                metric_for(result, options.method)
                if result
                else ratio_metric(None, reason=d.HistoricalReason.ROLLING_BOUNDARY)
            )
            rolling_kind: Literal["rolling_30", "rolling_90", "rolling_365"] = (
                "rolling_30" if days == 30 else "rolling_90" if days == 90 else "rolling_365"
            )
            rolling.append(
                r.HistoricalPeriodReturn(
                    period_start_at=start,
                    period_end_at=at,
                    kind=rolling_kind,
                    method=options.method,
                    value=value,
                    annualized_value=annual(value.value, start, at),
                )
            )
    if options.calendar_period is not d.CalendarPeriod.NONE:
        starts = set()
        for at in close_boundaries(engine.value):
            day = (at - timedelta(days=1)).date()
            month = (
                1
                if options.calendar_period is d.CalendarPeriod.YEAR
                else ((day.month - 1) // 3) * 3 + 1
                if options.calendar_period is d.CalendarPeriod.QUARTER
                else day.month
            )
            starts.add(day.replace(month=month, day=1))
        for day in sorted(starts):
            months = (
                12
                if options.calendar_period is d.CalendarPeriod.YEAR
                else 3
                if options.calendar_period is d.CalendarPeriod.QUARTER
                else 1
            )
            absolute_month = day.year * 12 + day.month - 1 + months
            finish = day.replace(year=absolute_month // 12, month=absolute_month % 12 + 1)
            start, end = midnight(day), midnight(finish)
            supported = start >= engine.window.start_at and end <= engine.window.end_at
            result = period_returns(engine, start, end) if supported else None
            value = (
                metric_for(result, options.method)
                if result
                else ratio_metric(None, reason=d.HistoricalReason.INCOMPLETE_CALENDAR)
            )
            kind: Literal["calendar_month", "calendar_quarter", "calendar_year"] = (
                "calendar_month"
                if options.calendar_period is d.CalendarPeriod.MONTH
                else "calendar_quarter"
                if options.calendar_period is d.CalendarPeriod.QUARTER
                else "calendar_year"
            )
            calendar.append(
                r.HistoricalPeriodReturn(
                    period_start_at=start,
                    period_end_at=end,
                    kind=kind,
                    method=options.method,
                    value=value,
                    annualized_value=annual(value.value, start, end),
                )
            )
    return tuple(rolling), tuple(calendar)
