"""Income and cash-flow accounting over the same deduplicated economic events."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from trading212_domain import CurrencyCode, Money
from trading212_domain import historical as d
from trading212_domain import historical_results as r

from ._historical_core import (
    ZERO,
    HistoricalEngine,
    dividend_parts,
    elapsed,
    event_kind,
    event_money,
    money_metric,
    period_bounds,
    ratio_metric,
)
from ._historical_performance import converted_event, period_events


def group_for(engine: HistoricalEngine, listing: str | None, at: datetime) -> tuple[str, str, bool]:
    grouping = engine.value.target_grouping
    if grouping is None or listing is None:
        return "unresolved", "Unresolved", True
    if grouping.policy == "historical_assignment" and (
        grouping.effective_at > at or grouping.published_at > engine.cutoff(at)
    ):
        return "unresolved", "Unresolved", True
    assignment = next((item for item in grouping.assignments if item.listing_id == listing), None)
    return (
        (assignment.group_key, assignment.group_name, False)
        if assignment
        else ("unresolved", "Unresolved", True)
    )


def event_point(
    engine: HistoricalEngine, event: d.HistoricalEvent, ordinal: int
) -> r.HistoricalCashFlowPoint:
    native = event_money(event)
    converted = converted_event(engine, event)
    listing = (
        event.listing_id
        if isinstance(event, (d.HistoricalDividend, d.HistoricalExecution))
        else None
    )
    instrument = (
        event.instrument_id
        if isinstance(event, (d.HistoricalDividend, d.HistoricalExecution))
        else None
    )
    group, _, unresolved = group_for(engine, listing, event.identity.economic_at)
    currency = native.currency if native else engine.currency
    refs = (event.identity.source_record_id,) + (
        (event.identity.source_occurrence_id,) if event.identity.source_occurrence_id else ()
    )
    return r.HistoricalCashFlowPoint(
        ordinal=ordinal,
        event_revision_id=event.identity.revision_id,
        economic_key=event.identity.economic_key,
        economic_at=event.identity.economic_at,
        kind=event_kind(event),
        classification="external"
        if isinstance(event, d.HistoricalExternalFlow)
        else "unresolved"
        if isinstance(event, d.HistoricalUnknownActivity)
        else "internal",
        native_amount=money_metric(
            native.amount if native else None,
            currency,
            reason=d.HistoricalReason.UNKNOWN_EVENT,
            coverage=d.HistoricalCoverageKey.EVENTS,
        ),
        reporting_amount=money_metric(
            converted,
            engine.currency,
            reason=d.HistoricalReason.FX_MISSING,
            coverage=d.HistoricalCoverageKey.EVENTS,
        ),
        instrument_id=instrument,
        listing_id=listing,
        group_key=None if unresolved else group,
        correction_of=event.correction_of if isinstance(event, d.HistoricalDividend) else None,
        source_ref_ids=refs,
    )


def _income_totals(
    engine: HistoricalEngine,
    events: tuple[d.HistoricalDividend, ...],
    currency: CurrencyCode,
    *,
    reporting: bool,
    start: datetime | None = None,
    end: datetime | None = None,
) -> r.CurrencyIncomeTotals:
    net = gross = withholding = positive = corrections = ZERO
    start, end = start or engine.window.start_at, end or engine.window.end_at
    event_complete = engine.activity_complete(
        start, end, end, capabilities=("historical_dividends",)
    )
    gross_complete = tax_complete = net_complete = True
    positive_count = correction_count = 0
    for event in events:

        def convert(value: Money | None, selected: d.HistoricalDividend = event) -> Decimal | None:
            return (
                converted_event(engine, selected, value)
                if reporting and value is not None
                else value.amount
                if value is not None and value.currency == currency
                else None
            )

        value = convert(event.net)
        if value is None:
            net_complete = False
        else:
            net += value
            if event.net.amount > 0:
                positive += value
            elif event.net.amount < 0:
                corrections += value
        positive_count += event.net.amount > 0
        correction_count += event.net.amount < 0
        gross_native, tax_native = dividend_parts(engine, event)
        gross_value, tax_value = convert(gross_native), convert(tax_native)
        if gross_value is None:
            gross_complete = False
        else:
            gross += gross_value
        if tax_value is None:
            tax_complete = False
        else:
            withholding += tax_value

    def metric(
        value: Decimal, complete: bool, reason: d.HistoricalReason
    ) -> d.HistoricalMoneyMetric:
        overall_complete = complete and event_complete
        degraded = engine.window.coverage_policy.value == "allow_degraded"
        return money_metric(
            value if overall_complete or degraded else None,
            currency,
            reason=reason if event_complete else d.HistoricalReason.EVENT_COVERAGE,
            coverage=d.HistoricalCoverageKey.EVENTS,
            partial=not overall_complete and degraded,
        )

    return r.CurrencyIncomeTotals(
        currency=currency,
        net=metric(net, net_complete, d.HistoricalReason.FX_MISSING),
        gross=metric(gross, gross_complete, d.HistoricalReason.GROSS_UNKNOWN),
        withholding=metric(withholding, tax_complete, d.HistoricalReason.WITHHOLDING_UNKNOWN),
        positive_income=metric(positive, net_complete, d.HistoricalReason.FX_MISSING),
        negative_corrections=metric(corrections, net_complete, d.HistoricalReason.FX_MISSING),
        event_count=len(events),
        positive_event_count=positive_count,
        correction_count=correction_count,
    )


def invested_mean(engine: HistoricalEngine, start: datetime, end: datetime) -> Decimal | None:
    instants = {start, end}
    instants.update(event.identity.economic_at for event in period_events(engine, start, end))
    instants.update(
        session.close_at
        for calendar in engine.value.calendars
        for session in calendar.sessions
        if start < session.close_at < end
    )
    ordered = sorted(instants)
    integral = ZERO
    for left, right in pairwise(ordered):
        value = engine.valuation(left, after=True)
        if value.invested is None or value.partial:
            return None
        integral += value.invested * elapsed(left, right)
    return integral / elapsed(start, end)


def income(engine: HistoricalEngine, options: r.IncomeOptions) -> r.IncomeCalculation:
    start, end = engine.window.start_at, engine.window.end_at
    all_events = period_events(engine, start, end)
    events = tuple(item for item in all_events if isinstance(item, d.HistoricalDividend))
    currencies = sorted({item.net.currency for item in events}, key=str)
    native = tuple(
        _income_totals(
            engine,
            tuple(item for item in events if item.net.currency == currency),
            currency,
            reporting=False,
        )
        for currency in currencies
    )
    reporting = _income_totals(engine, events, engine.currency, reporting=True)
    mean = invested_mean(engine, start, end)
    net_value = reporting.net.value.amount if reporting.net.value else None
    yield_value = (
        net_value / mean if net_value is not None and mean is not None and mean > 0 else None
    )
    previous: Decimal | None = None
    prior_start, prior_end = d.historical_previous_income_period(engine.window)
    support = any(
        item.reason == "previous_calendar_income"
        and item.start_at <= prior_start
        and item.end_at >= prior_end
        for item in engine.value.selection.support_windows
    )
    prior_events: tuple[d.HistoricalDividend, ...] = ()
    prior_complete = False
    if support:
        prior_events = tuple(
            item
            for item in engine.events(end)[0]
            if isinstance(item, d.HistoricalDividend)
            and prior_start <= item.identity.economic_at < prior_end
        )
        prior_totals = _income_totals(
            engine, prior_events, engine.currency, reporting=True, start=prior_start, end=prior_end
        )
        previous = (
            prior_totals.net.value.amount
            if prior_totals.net.value is not None
            and prior_totals.net.availability is d.MetricAvailability.AVAILABLE
            else None
        )
        prior_complete = previous is not None
    growth = (
        (net_value - previous) / previous
        if net_value is not None and previous is not None and previous > 0
        else None
    )
    positive_total = (
        reporting.positive_income.value.amount if reporting.positive_income.value else None
    )
    instrument_groups: dict[str, list[d.HistoricalDividend]] = defaultdict(list)
    group_groups: dict[str, list[d.HistoricalDividend]] = defaultdict(list)
    group_labels: dict[str, str] = {}
    for event in events:
        instrument_groups[event.instrument_id or "unresolved"].append(event)
        group, label, _ = group_for(engine, event.listing_id, event.identity.economic_at)
        group_groups[group].append(event)
        group_labels[group] = label

    def component(
        identity: str, subset: list[d.HistoricalDividend], grouping: bool
    ) -> r.IncomeComponent:
        totals = _income_totals(engine, tuple(subset), engine.currency, reporting=True)
        positive = totals.positive_income.value.amount if totals.positive_income.value else None
        concentration = (
            positive / positive_total
            if positive is not None and positive_total is not None and positive_total > 0
            else None
        )
        return r.IncomeComponent(
            key=identity,
            label=group_labels[identity] if grouping else identity,
            instrument_id=None if grouping or identity == "unresolved" else identity,
            group_key=identity if grouping and identity != "unresolved" else None,
            currency=engine.currency,
            net=totals.net,
            gross=totals.gross,
            withholding=totals.withholding,
            positive_income=totals.positive_income,
            negative_corrections=totals.negative_corrections,
            concentration=ratio_metric(
                concentration,
                reason=d.HistoricalReason.NO_POSITIVE_INCOME,
                coverage=d.HistoricalCoverageKey.EVENTS,
            ),
            event_count=len(subset),
            unresolved=identity == "unresolved",
        )

    instruments = tuple(
        component(identity, subset, False) for identity, subset in sorted(instrument_groups.items())
    )
    groups = tuple(
        component(identity, subset, True) for identity, subset in sorted(group_groups.items())
    )
    periods: dict[tuple[object, object], list[d.HistoricalDividend]] = defaultdict(list)
    for event in events:
        periods[period_bounds(event.identity.economic_at, d.HistoricalFrequency.MONTHLY)].append(
            event
        )
    period_rows = []
    for (period_start, period_end), subset in sorted(periods.items()):
        from datetime import date

        assert isinstance(period_start, date) and isinstance(period_end, date)
        period_native = tuple(
            _income_totals(
                engine,
                tuple(item for item in subset if item.net.currency == currency),
                currency,
                reporting=False,
            )
            for currency in sorted({item.net.currency for item in subset}, key=str)
        )
        period_rows.append(
            r.IncomePeriod(
                start_date=max(period_start, engine.window.start_date),
                end_date=min(period_end, engine.window.end_date),
                totals=period_native,
                reporting_net=_income_totals(
                    engine, tuple(subset), engine.currency, reporting=True
                ).net,
            )
        )
    complete = engine.activity_complete(
        engine.window.start_at, engine.window.end_at, engine.window.end_at
    )
    if not complete:
        engine.warnings.add(d.HistoricalReason.EVENT_COVERAGE)
    summary = r.IncomeMetrics(
        net_income=reporting.net,
        gross_income=reporting.gross,
        withholding=reporting.withholding,
        positive_income=reporting.positive_income,
        negative_corrections=reporting.negative_corrections,
        mean_invested_value=money_metric(mean, engine.currency),
        income_yield=ratio_metric(yield_value, reason=d.HistoricalReason.NONPOSITIVE_DENOMINATOR),
        previous_period_income=money_metric(
            previous,
            engine.currency,
            reason=d.HistoricalReason.PREVIOUS_PERIOD,
            coverage=d.HistoricalCoverageKey.PRIOR_INCOME,
        ),
        dividend_growth=ratio_metric(
            growth,
            reason=d.HistoricalReason.PREVIOUS_PERIOD,
            coverage=d.HistoricalCoverageKey.PRIOR_INCOME,
        ),
        event_count=len(events),
    )
    context = engine.context("income_v1", available=net_value is not None, partial=not complete)
    prior_measure = d.HistoricalCoverageMeasure(
        key=d.HistoricalCoverageKey.PRIOR_INCOME,
        expected_count=len(prior_events) + 1,
        available_count=len(prior_events) + 1 if prior_complete else 0,
        complete=prior_complete,
        reasons=() if prior_complete else (d.HistoricalReason.PREVIOUS_PERIOD,),
    )
    context = replace(
        context,
        coverage=d.HistoricalCoverage(
            measures=(
                *(
                    item
                    for item in context.coverage.measures
                    if item.key is not d.HistoricalCoverageKey.PRIOR_INCOME
                ),
                prior_measure,
            )
        ),
        assumptions=(*context.assumptions, "income_holdings_and_fx_may_change"),
    )
    return r.IncomeCalculation(
        context=context,
        options=options,
        summary=summary,
        native_currency_totals=native,
        reporting_totals=reporting,
        instrument_rows=instruments,
        group_rows=groups,
        period_rows=tuple(period_rows),
        events=tuple(event_point(engine, item, ordinal) for ordinal, item in enumerate(events)),
        source_uses=engine.ordered_uses(),
        conversions=engine.ordered_conversions(),
    )


def cash_totals(
    engine: HistoricalEngine,
    events: tuple[d.HistoricalEvent, ...],
    currency: CurrencyCode,
    *,
    reporting: bool,
) -> r.CurrencyCashFlowTotals:
    values = {
        name: ZERO
        for name in (
            "external_net",
            "deposits",
            "withdrawals",
            "internal_net",
            "income",
            "fees",
            "taxes",
            "purchases",
            "sales",
            "unresolved_amount",
        )
    }
    missing: set[str] = set()
    external = internal = unresolved = 0
    for event in events:
        native = event_money(event)
        value = (
            converted_event(engine, event)
            if reporting
            else native.amount
            if native is not None and native.currency == currency
            else None
        )
        names: list[tuple[str, int]] = []
        if isinstance(event, d.HistoricalExternalFlow):
            external += 1
            names = (
                [("external_net", 1), ("deposits", 1)]
                if event.signed_amount.amount >= 0
                else [("external_net", 1), ("withdrawals", -1)]
            )
        elif isinstance(event, d.HistoricalUnknownActivity):
            unresolved += 1
            names = [("unresolved_amount", 1)]
        else:
            internal += 1
            names = [("internal_net", 1)]
            kind = event_kind(event)
            if kind in (d.HistoricalCashFlowKind.DIVIDEND, d.HistoricalCashFlowKind.INTEREST):
                names.append(("income", 1))
            elif kind in (d.HistoricalCashFlowKind.FEE, d.HistoricalCashFlowKind.TAX):
                names.append(("fees" if kind is d.HistoricalCashFlowKind.FEE else "taxes", -1))
            elif isinstance(event, d.HistoricalExecution):
                names.append(
                    (
                        "purchases" if event.side == "buy" else "sales",
                        -1 if event.side == "buy" else 1,
                    )
                )
        for name, sign in names:
            if value is None:
                # Noncash reference actions are not missing monetary receipts.
                if isinstance(event, d.HistoricalCorporateAction):
                    continue
                missing.add(name)
            else:
                values[name] += sign * value
    complete = engine.activity_complete(
        engine.window.start_at, engine.window.end_at, engine.window.end_at
    )
    degraded = engine.window.coverage_policy.value == "allow_degraded"
    metrics = {
        name: money_metric(
            value if (name not in missing and complete) or degraded else None,
            currency,
            reason=d.HistoricalReason.EVENT_COVERAGE
            if not complete
            else d.HistoricalReason.FX_MISSING
            if reporting
            else d.HistoricalReason.UNKNOWN_EVENT,
            coverage=d.HistoricalCoverageKey.EVENTS,
            partial=degraded and (not complete or name in missing),
        )
        for name, value in values.items()
    }
    return r.CurrencyCashFlowTotals(
        currency=currency,
        external_net=metrics["external_net"],
        deposits=metrics["deposits"],
        withdrawals=metrics["withdrawals"],
        internal_net=metrics["internal_net"],
        income=metrics["income"],
        fees=metrics["fees"],
        taxes=metrics["taxes"],
        purchases=metrics["purchases"],
        sales=metrics["sales"],
        unresolved_amount=metrics["unresolved_amount"],
        external_count=external,
        internal_count=internal,
        unresolved_count=unresolved,
    )


def cash_flows(engine: HistoricalEngine, options: r.CashFlowOptions) -> r.CashFlowCalculation:
    events = period_events(engine, engine.window.start_at, engine.window.end_at)
    currencies = sorted(
        {
            event_native.currency
            for item in events
            if (event_native := event_money(item)) is not None
        },
        key=str,
    )
    native = tuple(
        cash_totals(
            engine,
            tuple(
                item
                for item in events
                if (value := event_money(item)) is not None and value.currency == currency
            ),
            currency,
            reporting=False,
        )
        for currency in currencies
    )
    reporting = cash_totals(engine, events, engine.currency, reporting=True)
    selected = tuple(
        item for item in events if options.kind is None or event_kind(item) is options.kind
    )
    periods: dict[tuple[object, object], list[d.HistoricalEvent]] = defaultdict(list)
    for event in events:
        periods[period_bounds(event.identity.economic_at, options.frequency)].append(event)
    period_rows = []
    for (start, end), subset in sorted(periods.items()):
        from datetime import date

        assert isinstance(start, date) and isinstance(end, date)
        sub = tuple(subset)
        period_native = tuple(
            cash_totals(
                engine,
                tuple(
                    item
                    for item in sub
                    if (value := event_money(item)) is not None and value.currency == currency
                ),
                currency,
                reporting=False,
            )
            for currency in currencies
            if any(
                (value := event_money(item)) is not None and value.currency == currency
                for item in sub
            )
        )
        period_rows.append(
            r.CashFlowPeriod(
                start_date=max(start, engine.window.start_date),
                end_date=min(end, engine.window.end_date),
                native_totals=period_native,
                reporting_totals=cash_totals(engine, sub, engine.currency, reporting=True),
            )
        )
    points = tuple(event_point(engine, event, ordinal) for ordinal, event in enumerate(selected))
    summary = r.CashFlowMetrics(
        event_count=len(events),
        filtered_count=len(selected),
        external_count=reporting.external_count,
        internal_count=reporting.internal_count,
        unresolved_count=reporting.unresolved_count,
    )
    return r.CashFlowCalculation(
        context=engine.context(
            "cash_flow_intelligence_v1",
            partial=reporting.unresolved_count > 0
            or not engine.activity_complete(
                engine.window.start_at, engine.window.end_at, engine.window.end_at
            ),
        ),
        options=options,
        summary=summary,
        native_currency_totals=native,
        reporting_totals=reporting,
        period_rows=tuple(period_rows),
        events=points,
        source_uses=engine.ordered_uses(),
        conversions=engine.ordered_conversions(),
    )
