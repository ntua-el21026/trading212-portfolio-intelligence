"""Immutable composite benchmark wealth and aligned portfolio comparisons."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.sources import (
    BenchmarkRebalanceRule,
    BenchmarkSnapshot,
    PriceBasis,
    PriceSnapshot,
)

from ._historical_core import ONE, ZERO, HistoricalEngine, ratio_metric
from ._historical_performance import annual, period_projections, period_returns


def tracking_error(
    active_returns: tuple[Decimal, ...], annual_factor: int
) -> d.HistoricalRatioMetric:
    if len(active_returns) < 20:
        return ratio_metric(
            None,
            reason=d.HistoricalReason.TRACKING_PAIRS,
            coverage=d.HistoricalCoverageKey.BENCHMARK,
        )
    mean = sum(active_returns, ZERO) / len(active_returns)
    variance = sum(((value - mean) ** 2 for value in active_returns), ZERO) / (
        len(active_returns) - 1
    )
    return ratio_metric(
        (variance * annual_factor).sqrt(), coverage=d.HistoricalCoverageKey.BENCHMARK
    )


def benchmark_wealth(
    engine: HistoricalEngine, instants: tuple[datetime, ...]
) -> tuple[dict[datetime, Decimal | None], tuple[r.CompositeBenchmarkComponentRef, ...]]:
    benchmark = engine.value.benchmark_input
    if benchmark is None:
        return {at: None for at in instants}, ()
    content = benchmark.content
    requested_instants = instants
    rebalance_calendar = engine.calendars[(content.calendar_id, content.calendar_version)]
    rebalance_instants = {
        session.close_at
        for session in rebalance_calendar.sessions
        if instants[0] < session.close_at <= instants[-1]
    }
    instants = tuple(sorted({*instants, *rebalance_instants}))
    snapshots: tuple[PriceSnapshot | BenchmarkSnapshot, ...] = (
        *benchmark.price_snapshots,
        *benchmark.benchmark_snapshots,
    )
    if (
        content.reporting_currency != engine.currency
        or sum((item.weight for item in content.components), ZERO) != ONE
    ):
        return {at: None for at in instants}, ()
    components: dict[str, tuple[Decimal, list[Decimal | None]]] = {}
    refs = []
    for component in sorted(content.components, key=lambda item: item.source_id):
        sources = [
            item
            for item in snapshots
            if item.series is not None and item.series.id == component.source_id
        ]
        if not sources or sources[0].series is None:
            return {at: None for at in instants}, ()
        series = sources[0].series
        if series.basis is not content.return_basis:
            return {at: None for at in instants}, ()
        levels = []
        consumer = r.HistoricalUseConsumer(
            kind="benchmark", component_source_id=component.source_id
        )
        for at in instants:
            engine._cell(component.source_id, at)
            level = engine.price(
                component.source_id, at, consumer, "benchmark_component", benchmark=True
            )
            rate = engine.fx(series.currency, at, consumer, "benchmark_component")
            levels.append(level * rate if level is not None and rate is not None else None)
            if level is not None and rate is not None:
                engine.successful_cells.add((component.source_id, at))
        components[component.source_id] = (component.weight, levels)
        refs.append(
            r.CompositeBenchmarkComponentRef(
                source_id=component.source_id,
                weight=component.weight,
                snapshot_ids=tuple(sorted(item.id for item in sources)),
                license_version_ids=tuple(
                    sorted({item.provenance.license_version_id for item in sources})
                ),
                calendar_ref=d.CalendarRef(id=series.calendar_id, version=series.calendar_version),
            )
        )
    values: dict[datetime, Decimal | None] = {}
    last_wealth: Decimal | None = ONE
    rebalance_index = 0
    for index, at in enumerate(instants):
        if any(levels[index] is None or levels[0] is None for _, levels in components.values()):
            values[at] = None
            last_wealth = None
            continue
        if content.rebalance_rule is BenchmarkRebalanceRule.BUY_AND_HOLD:
            wealth = ZERO
            for weight, levels in components.values():
                current, opening = levels[index], levels[0]
                assert current is not None and opening is not None
                wealth += weight * current / opening
        elif index == 0:
            wealth = ONE
        elif last_wealth is None or any(
            levels[rebalance_index] is None for _, levels in components.values()
        ):
            values[at] = None
            continue
        else:
            growth = ZERO
            for weight, levels in components.values():
                current, previous = levels[index], levels[rebalance_index]
                assert current is not None and previous is not None
                growth += weight * current / previous
            wealth = last_wealth * growth
        values[at] = wealth
        if at in rebalance_instants:
            last_wealth = wealth
            rebalance_index = index
    return {at: values[at] for at in requested_instants}, tuple(refs)


def comparison(engine: HistoricalEngine, options: r.ComparisonOptions) -> r.BenchmarkCalculation:
    start, end = engine.window.start_at, engine.window.end_at
    benchmark = engine.value.benchmark_input
    missing = ratio_metric(
        None,
        reason=d.HistoricalReason.BENCHMARK_MISSING,
        coverage=d.HistoricalCoverageKey.BENCHMARK,
    )
    if benchmark is None:
        engine.warnings.add(d.HistoricalReason.BENCHMARK_MISSING)
        summary = r.BenchmarkComparisonMetrics(
            portfolio_return=missing,
            benchmark_return=missing,
            excess_return=missing,
            tracking_difference=missing,
            relative_wealth_return=missing,
            annualized_portfolio_return=missing,
            annualized_benchmark_return=missing,
            annualized_tracking_difference=missing,
            tracking_error=missing,
            paired_observation_count=0,
            comparable_total_return_basis=False,
        )
        return r.BenchmarkCalculation(
            context=engine.context("benchmark_comparison_v1", available=False),
            options=options,
            summary=summary,
            composite=None,
            points=(),
            source_uses=(),
            conversions=(),
        )
    calendar = engine.calendars[(benchmark.content.calendar_id, benchmark.content.calendar_version)]
    sessions = tuple(session for session in calendar.sessions if start < session.close_at < end)
    instants = tuple(sorted({start, end, *(session.close_at for session in sessions)}))
    values, refs = benchmark_wealth(engine, instants)
    points: list[r.BenchmarkComparisonPoint] = []
    composite_points: list[r.CompositeBenchmarkPoint] = []
    active: list[Decimal] = []
    previous = start
    previous_wealth = values[start]
    for ordinal, session in enumerate(sessions):
        at = session.close_at
        wealth = values[at]
        interval = (
            wealth / previous_wealth - ONE
            if wealth is not None and previous_wealth is not None and previous_wealth > 0
            else None
        )
        portfolio_interval = period_returns(engine, previous, at, xirr=False).twr.value
        if interval is not None and portfolio_interval is not None:
            active.append(portfolio_interval - interval)
        portfolio = period_returns(engine, start, at, xirr=False).twr.value
        cumulative = wealth - ONE if wealth is not None else None
        excess = (
            portfolio - cumulative if portfolio is not None and cumulative is not None else None
        )
        relative = (
            (ONE + portfolio) / wealth
            if portfolio is not None and wealth is not None and wealth > 0
            else None
        )
        points.append(
            r.BenchmarkComparisonPoint(
                ordinal=ordinal,
                date=session.session_date,
                valuation_at=at,
                portfolio_return=ratio_metric(portfolio),
                benchmark_return=ratio_metric(cumulative),
                excess_return=ratio_metric(excess),
                portfolio_wealth=ratio_metric(ONE + portfolio if portfolio is not None else None),
                benchmark_wealth=ratio_metric(wealth),
                relative_wealth=ratio_metric(relative),
            )
        )
        composite_points.append(
            r.CompositeBenchmarkPoint(
                ordinal=ordinal,
                session_date=session.session_date,
                effective_at=at,
                wealth=ratio_metric(wealth, coverage=d.HistoricalCoverageKey.BENCHMARK),
                interval_return=ratio_metric(interval, coverage=d.HistoricalCoverageKey.BENCHMARK),
            )
        )
        previous, previous_wealth = at, wealth
    portfolio = period_returns(engine, start, end, xirr=False).twr.value
    terminal = values[end]
    benchmark_return = terminal - ONE if terminal is not None else None
    excess = (
        portfolio - benchmark_return
        if portfolio is not None and benchmark_return is not None
        else None
    )
    relative = (
        (ONE + portfolio) / terminal - ONE
        if portfolio is not None and terminal is not None and terminal > 0
        else None
    )
    ap, ab = annual(portfolio, start, end), annual(benchmark_return, start, end)
    atd = ap.value - ab.value if ap.value is not None and ab.value is not None else None
    comparable = benchmark.content.return_basis is PriceBasis.TOTAL_RETURN
    if not comparable:
        engine.warnings.add(d.HistoricalReason.BENCHMARK_PRICE_ONLY)
    summary = r.BenchmarkComparisonMetrics(
        portfolio_return=ratio_metric(portfolio),
        benchmark_return=ratio_metric(
            benchmark_return,
            reason=d.HistoricalReason.BENCHMARK_GAP,
            coverage=d.HistoricalCoverageKey.BENCHMARK,
        ),
        excess_return=ratio_metric(excess),
        tracking_difference=ratio_metric(excess),
        relative_wealth_return=ratio_metric(relative),
        annualized_portfolio_return=ap,
        annualized_benchmark_return=ab,
        annualized_tracking_difference=ratio_metric(atd, reason=d.HistoricalReason.SHORT_PERIOD),
        tracking_error=tracking_error(
            tuple(active), engine.value.selection.accounting_policy.annual_session_factor
        )
        if len(active) == len(sessions)
        else ratio_metric(
            None,
            reason=d.HistoricalReason.BENCHMARK_GAP,
            coverage=d.HistoricalCoverageKey.BENCHMARK,
        ),
        paired_observation_count=len(active),
        comparable_total_return_basis=comparable,
    )
    rolling, calendar_returns = benchmark_periods(engine, options)
    available_count = sum(values[session.close_at] is not None for session in sessions)
    context = engine.context(
        "benchmark_comparison_v1",
        available=excess is not None,
        partial=available_count != len(sessions),
    )
    measures = tuple(
        item
        for item in context.coverage.measures
        if item.key is not d.HistoricalCoverageKey.BENCHMARK
    )
    coverage = d.HistoricalCoverage(
        measures=(
            *measures,
            d.HistoricalCoverageMeasure(
                key=d.HistoricalCoverageKey.BENCHMARK,
                expected_count=len(sessions),
                available_count=available_count,
                complete=available_count == len(sessions),
                reasons=()
                if available_count == len(sessions)
                else (d.HistoricalReason.BENCHMARK_GAP,),
            ),
        )
    )
    context = replace(
        context,
        coverage=coverage,
        assumptions=(*context.assumptions, *(("price_only_benchmark",) if not comparable else ())),
    )
    composite: r.CompositeBenchmarkSnapshot | None = r.CompositeBenchmarkSnapshot(
        benchmark_version_id=benchmark.benchmark_version_id,
        reporting_currency=engine.currency,
        return_basis=benchmark.content.return_basis,
        calendar_ref=d.CalendarRef(id=calendar.id, version=calendar.version),
        rebalance_rule=benchmark.content.rebalance_rule,
        window=engine.window,
        input_digest=context.input_digest,
        method=r.HistoricalMethod(name="composite_benchmark_wealth", version="1.0.0"),
        coverage=coverage,
        inputs=refs,
        observations=tuple(composite_points),
    )
    if not any(
        isinstance(use, r.HistoricalObservationUse)
        and use.role == "benchmark_component"
        and use.source_kind in ("price", "provider_benchmark")
        for use in engine.uses.values()
    ):
        composite = None
    if options.frequency is d.HistoricalFrequency.MONTHLY:
        points = [
            point
            for index, point in enumerate(points)
            if index == len(points) - 1 or points[index + 1].date.month != point.date.month
        ]
        points = [replace(point, ordinal=index) for index, point in enumerate(points)]
    return r.BenchmarkCalculation(
        context=context,
        options=options,
        summary=summary,
        composite=composite,
        points=tuple(points),
        rolling_returns=rolling,
        calendar_returns=calendar_returns,
        source_uses=engine.ordered_uses(),
        conversions=engine.ordered_conversions(),
    )


def benchmark_periods(
    engine: HistoricalEngine, options: r.ComparisonOptions
) -> tuple[
    tuple[r.HistoricalBenchmarkPeriodReturn, ...], tuple[r.HistoricalBenchmarkPeriodReturn, ...]
]:
    rolling, calendar = period_projections(
        engine,
        r.PerformanceOptions(
            frequency=options.frequency,
            rolling_window=options.rolling_window,
            calendar_period=options.calendar_period,
        ),
    )

    def convert(period: r.HistoricalPeriodReturn) -> r.HistoricalBenchmarkPeriodReturn:
        start, end = period.period_start_at, period.period_end_at
        value = None
        if period.value.value is not None:
            wealth, _ = benchmark_wealth(engine, (start, end))
            terminal = wealth[end]
            if terminal is not None:
                value = terminal - ONE
        portfolio = period.value.value
        excess = portfolio - value if portfolio is not None and value is not None else None
        relative = (
            (ONE + portfolio) / (ONE + value) - ONE
            if portfolio is not None and value is not None and value > -ONE
            else None
        )
        return r.HistoricalBenchmarkPeriodReturn(
            period_start_at=start,
            period_end_at=end,
            kind=period.kind,
            portfolio_return=period.value,
            benchmark_return=ratio_metric(
                value, reason=period.value.reason_code or d.HistoricalReason.BENCHMARK_GAP
            ),
            excess_return=ratio_metric(excess),
            relative_wealth_return=ratio_metric(relative),
            annualized_portfolio_return=period.annualized_value,
            annualized_benchmark_return=annual(value, start, end),
        )

    return tuple(convert(period) for period in rolling), tuple(
        convert(period) for period in calendar
    )
