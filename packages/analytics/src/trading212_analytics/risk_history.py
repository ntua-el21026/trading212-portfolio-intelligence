"""Assemble risk intervals from retained Phase 2 accounting and source selectors."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from trading212_domain import historical as d
from trading212_domain import historical_results as h
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError, ErrorCode, fail_validation
from trading212_domain.historical_serialization import historical_input_digest
from trading212_domain.historical_validation import validate_historical_input
from trading212_domain.risk import RiskDefinitionContent, RiskInterval, RiskReason, RiskSeries
from trading212_domain.risk_history import RiskAssetSource, RiskHistory
from trading212_domain.sources import MarketSession, PriceBasis, SourceSeries, source_tuple

from ._historical_benchmark import benchmark_wealth
from ._historical_core import HistoricalEngine, financial
from ._historical_performance import performance, period_returns
from ._premium_numeric import ONE, arithmetic, q18


def _sessions(
    value: d.HistoricalInput, definition: RiskDefinitionContent
) -> tuple[MarketSession, ...]:
    reference = value.selection.reporting_calendar_ref
    if reference is None or (reference.id, reference.version) != (
        definition.calendar_id,
        definition.calendar_version,
    ):
        fail_validation("Risk calendar differs from captured reporting calendar.", field="calendar")
    calendar = next(
        (
            item
            for item in value.calendars
            if (item.id, item.version) == (reference.id, reference.version)
        ),
        None,
    )
    if calendar is None:
        fail_validation("Risk calendar is not captured.", field="calendar")
    window = value.selection.window
    return tuple(
        item for item in calendar.sessions if window.start_at <= item.close_at <= window.end_at
    )


def _monthly_ends(
    value: d.HistoricalInput, sessions: tuple[MarketSession, ...], definition: RiskDefinitionContent
) -> frozenset[datetime]:
    calendar = next(
        item
        for item in value.calendars
        if (item.id, item.version) == (definition.calendar_id, definition.calendar_version)
    )
    eligible: set[datetime] = set()
    for i, session in enumerate(calendar.sessions):
        month = (session.session_date.year, session.session_date.month)
        next_session = calendar.sessions[i + 1] if i + 1 < len(calendar.sessions) else None
        closes_month = (
            next_session is not None
            and (next_session.session_date.year, next_session.session_date.month) != month
        )
        last_date = session.session_date.replace(day=monthrange(*month)[1])
        if closes_month or (next_session is None and calendar.period.end >= last_date):
            eligible.add(session.close_at)
    return frozenset(item.close_at for item in sessions if item.close_at in eligible)


def _interval(
    start: datetime,
    end: datetime,
    value: Decimal | None,
    *,
    reason: RiskReason = RiskReason.MISSING_INTERVAL,
    quality: QualityState = QualityState.FRESH,
) -> RiskInterval:
    return RiskInterval(
        start_at=start,
        end_at=end,
        simple_return=q18(value) if value is not None else None,
        quality=quality if value is not None else QualityState.PARTIAL,
        reason=None if value is not None else reason,
    )


def _series(
    value: d.HistoricalInput,
    definition: RiskDefinitionContent,
    key: str,
    intervals: tuple[RiskInterval, ...],
    month_ends: frozenset[datetime],
) -> RiskSeries:
    if definition.frequency == "monthly":
        # A month is bounded by two proven month ends; never label a partial final
        # request window as a full calendar month or bridge an unavailable daily cell.
        monthly: list[RiskInterval] = []
        active_start: datetime | None = None
        gross: Decimal | None = ONE
        for interval in intervals:
            if interval.start_at in month_ends:
                active_start, gross = interval.start_at, ONE
            if active_start is None:
                continue
            with arithmetic():
                if interval.simple_return is None or interval.quality is not QualityState.FRESH:
                    gross = None
                elif gross is not None:
                    gross *= ONE + interval.simple_return
                if interval.end_at in month_ends:
                    monthly.append(
                        _interval(
                            active_start,
                            interval.end_at,
                            gross - ONE if gross is not None else None,
                        )
                    )
        intervals = tuple(monthly)
    return RiskSeries(
        key=key,
        reporting_currency=value.selection.window.reporting_currency,
        calendar_id=definition.calendar_id,
        calendar_version=definition.calendar_version,
        frequency=definition.frequency,
        source_cutoff_at=value.selection.window.source_cutoff_at,
        basis="total_return",
        intervals=intervals,
    )


def _asset_metadata(value: d.HistoricalInput, source: RiskAssetSource) -> SourceSeries:
    captured = tuple(item for item in value.price_snapshots if item.series.id == source.series_id)
    if not captured or any(item.series.instrument_id != source.instrument_id for item in captured):
        fail_validation("Asset source does not match captured instrument.", field="asset_source")
    if source.instrument_id not in {item.instrument_id for item in value.instruments}:
        fail_validation("Asset instrument is outside the historical capture.", field="asset_source")
    series = captured[0].series
    if any(item.series != series for item in captured):
        fail_validation("Immutable asset series metadata conflicts.", field="asset_source")
    return series


def _asset_series(
    engine: HistoricalEngine,
    definition: RiskDefinitionContent,
    source: RiskAssetSource,
    sessions: tuple[MarketSession, ...],
    month_ends: frozenset[datetime],
) -> RiskSeries:
    series = _asset_metadata(engine.value, source)
    consumer = h.HistoricalUseConsumer(kind="benchmark", component_source_id=source.series_id)
    levels: list[Decimal | None] = []
    for session in sessions:
        if series.basis is not PriceBasis.TOTAL_RETURN:
            # Raw/adjusted prices cannot be silently promoted to a reinvested index.
            engine.warnings.add(d.HistoricalReason.UNSUPPORTED_BASIS)
            levels.append(None)
            continue
        engine._cell(source.series_id, session.close_at)
        price = engine.price(
            source.series_id, session.close_at, consumer, "benchmark_component", benchmark=True
        )
        rate = engine.fx(series.currency, session.close_at, consumer, "benchmark_component")
        with arithmetic():
            levels.append(price * rate if price is not None and rate is not None else None)
    intervals: list[RiskInterval] = []
    with arithmetic():
        for i, (start, end) in enumerate(pairwise(sessions)):
            opening, closing = levels[i], levels[i + 1]
            change = (
                closing / opening - ONE
                if opening is not None and opening > 0 and closing is not None
                else None
            )
            intervals.append(
                _interval(
                    start.close_at,
                    end.close_at,
                    change,
                    reason=RiskReason.INCOMPATIBLE_BASIS
                    if series.basis is not PriceBasis.TOTAL_RETURN
                    else RiskReason.MISSING_INTERVAL,
                )
            )
    return _series(engine.value, definition, source.instrument_id, tuple(intervals), month_ends)


def _prepare_risk_history(
    value: d.HistoricalInput,
    definition: RiskDefinitionContent,
    assets: tuple[RiskAssetSource, ...],
) -> tuple[HistoricalEngine, tuple[MarketSession, ...], frozenset[datetime]]:
    validate_historical_input(value)
    if not isinstance(definition, RiskDefinitionContent):
        fail_validation("A risk definition is required.", field="definition")
    source_tuple(assets, RiskAssetSource, "assets", 32)
    if len({item.instrument_id for item in assets}) != len(assets) or len(
        {item.series_id for item in assets}
    ) != len(assets):
        fail_validation("Risk asset mappings must be unique.", field="assets")
    sessions = _sessions(value, definition)
    if len(sessions) * max(1, len(assets)) > 100000:
        fail_validation("Risk history exceeds valuation work capacity.", field="assets")
    month_ends = (
        _monthly_ends(value, sessions, definition)
        if definition.frequency == "monthly"
        else frozenset()
    )
    for source in assets:
        _asset_metadata(value, source)
    engine = HistoricalEngine(value)
    # The canonical preflight already counts accounting/session/flow/action instants.
    # Each additional asset needs at most one price and one converted FX cell per close.
    if engine.preflight_cell_bound + len(sessions) * len(assets) * 2 > d.MAX_HISTORICAL_CELLS:
        raise DomainError(
            ErrorCode.INPUT_BOUND_EXCEEDED, "Combined risk history capacity exceeded."
        )
    return engine, sessions, month_ends


@financial
def validate_risk_capacity(
    value: d.HistoricalInput,
    definition: RiskDefinitionContent,
    assets: tuple[RiskAssetSource, ...],
) -> int:
    """Perform the same bounded preflight at admission without calculating returns."""
    engine, sessions, _ = _prepare_risk_history(value, definition, assets)
    return engine.preflight_cell_bound + len(sessions) * len(assets) * 2


@financial
def build_risk_history(
    value: d.HistoricalInput,
    definition: RiskDefinitionContent,
    *,
    assets: tuple[RiskAssetSource, ...] = (),
) -> RiskHistory:
    engine, sessions, month_ends = _prepare_risk_history(value, definition, assets)
    # Retain canonical drawdown rather than a separately defined risk drawdown curve.
    canonical = performance(engine, h.PerformanceOptions(frequency=d.HistoricalFrequency.DAILY))
    intervals: list[RiskInterval] = []
    for start, end in pairwise(sessions):
        result = period_returns(engine, start.close_at, end.close_at, xirr=False).twr
        if result.reason_code is not None:
            engine.warnings.add(result.reason_code)
        intervals.append(
            _interval(start.close_at, end.close_at, result.value, quality=result.quality)
        )
    portfolio = _series(value, definition, "portfolio", tuple(intervals), month_ends)
    benchmark = None
    if value.benchmark_input is not None:
        if value.benchmark_input.content.return_basis is not PriceBasis.TOTAL_RETURN:
            engine.warnings.add(d.HistoricalReason.UNSUPPORTED_BASIS)
        elif sessions:
            wealth, _ = benchmark_wealth(engine, tuple(item.close_at for item in sessions))
            with arithmetic():
                benchmark_intervals: list[RiskInterval] = []
                for start, end in pairwise(sessions):
                    opening, closing = wealth[start.close_at], wealth[end.close_at]
                    change = (
                        closing / opening - ONE
                        if opening is not None and opening > 0 and closing is not None
                        else None
                    )
                    benchmark_intervals.append(_interval(start.close_at, end.close_at, change))
            benchmark = _series(
                value, definition, "benchmark", tuple(benchmark_intervals), month_ends
            )
    asset_series = tuple(
        _asset_series(engine, definition, item, sessions, month_ends)
        for item in sorted(assets, key=lambda item: item.instrument_id)
    )
    return RiskHistory(
        owner_id=value.owner_id,
        account_id=value.account_id,
        historical_input_digest=historical_input_digest(value),
        portfolio=portfolio,
        benchmark=benchmark,
        assets=asset_series,
        maximum_drawdown=canonical.summary.maximum_drawdown,
        canonical_performance_context=canonical.context,
        source_uses=tuple(sorted(engine.uses.values(), key=lambda item: item.use_key)),
        conversions=tuple(
            sorted(engine.conversions.values(), key=lambda item: item.conversion_key)
        ),
        historical_warnings=tuple(sorted(engine.warnings)),
    )
