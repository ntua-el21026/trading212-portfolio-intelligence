"""Private source-bound risk history, assembled only from authorized canonical captures."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import fail_validation
from .historical import HistoricalRatioMetric, HistoricalReason, historical_digest
from .historical_results import (
    HistoricalConversionUse,
    HistoricalResultContext,
    HistoricalSourceUse,
)
from .risk import RiskSeries
from .sources import source_id, source_tuple


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskAssetSource:
    instrument_id: str
    series_id: str

    def __post_init__(self) -> None:
        source_id(self.instrument_id, "instrument_id")
        source_id(self.series_id, "series_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskHistory:
    owner_id: str
    account_id: str
    historical_input_digest: str
    portfolio: RiskSeries
    benchmark: RiskSeries | None
    assets: tuple[RiskSeries, ...]
    canonical_performance_context: HistoricalResultContext
    maximum_drawdown: HistoricalRatioMetric
    source_uses: tuple[HistoricalSourceUse, ...]
    conversions: tuple[HistoricalConversionUse, ...]
    historical_warnings: tuple[HistoricalReason, ...]

    def __post_init__(self) -> None:
        source_id(self.owner_id, "owner_id")
        source_id(self.account_id, "account_id")
        historical_digest(self.historical_input_digest, "historical_input_digest")
        source_tuple(self.assets, RiskSeries, "assets", 32)
        source_tuple(self.conversions, HistoricalConversionUse, "conversions", 100000)
        source_tuple(self.historical_warnings, HistoricalReason, "historical_warnings", 128)
        # Detailed historical union/reference validation is performed by the canonical
        # capture/result pipeline; this envelope never invents a source selector.
        if not isinstance(self.portfolio, RiskSeries) or (
            self.benchmark is not None and not isinstance(self.benchmark, RiskSeries)
        ):
            fail_validation("Canonical risk history series are required.", field="history")
        if not isinstance(self.maximum_drawdown, HistoricalRatioMetric):
            fail_validation("Canonical historical drawdown is required.", field="drawdown")
        if (
            not isinstance(self.source_uses, tuple)
            or len(self.source_uses) > 400000
            or any(not isinstance(item, HistoricalSourceUse) for item in self.source_uses)
        ):
            fail_validation("Historical source-use capacity exceeded.", field="source_uses")
        context = self.canonical_performance_context
        if not isinstance(context, HistoricalResultContext) or (
            context.account_id != self.account_id
            or context.input_digest != self.historical_input_digest
            or context.window.reporting_currency != self.portfolio.reporting_currency
            or context.window.source_cutoff_at != self.portfolio.source_cutoff_at
        ):
            fail_validation("Historical context differs from risk history.", field="context")
        rows = (self.portfolio, *self.assets, *((self.benchmark,) if self.benchmark else ()))
        if self.portfolio.key != "portfolio" or (
            self.benchmark and self.benchmark.key != "benchmark"
        ):
            fail_validation("Risk history roles disagree.", field="series")
        if len({row.key for row in rows}) != len(rows):
            fail_validation("Risk history identities must be unique.", field="series")

        def basis(row: RiskSeries) -> tuple[object, ...]:
            return (
                row.reporting_currency,
                row.calendar_id,
                row.calendar_version,
                row.frequency,
                row.source_cutoff_at,
                row.basis,
            )

        if any(basis(row) != basis(self.portfolio) for row in rows):
            fail_validation("Risk history contains incompatible series.", field="series")
        if sum(len(row.intervals) for row in rows) > 100000:
            fail_validation("Combined risk interval capacity exceeded.", field="intervals")
        for row in rows:
            if any(
                item.start_at < context.window.start_at or item.end_at > context.window.end_at
                for item in row.intervals
            ):
                fail_validation("Risk interval lies outside captured window.", field="intervals")
        for row in self.assets:
            source_id(row.key, "asset.instrument_id")
        if len({item.use_key for item in self.source_uses}) != len(self.source_uses) or len(
            {item.conversion_key for item in self.conversions}
        ) != len(self.conversions):
            fail_validation("Risk historical evidence identities conflict.", field="source_uses")
