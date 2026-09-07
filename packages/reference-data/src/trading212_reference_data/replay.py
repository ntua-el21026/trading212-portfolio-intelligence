"""Concrete fixed-family replay adapters over versioned synthetic source fixtures."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from trading212_application import source_providers as ports
from trading212_domain.enums import QualityState
from trading212_domain.serialization import canonical_json, to_primitive
from trading212_domain.sources import (
    ObservationState,
    SourceCoverage,
    SourceGap,
    SourceLicense,
    SourcePeriod,
    SourceProvenance,
    SourceReason,
    SourceSeries,
    SourceSeriesKind,
    SourceUse,
)
from trading212_domain.values import CurrencyCode, require_utc

from .bounded_json import DecodeFailure
from .replay_runtime import ReplayFault, ReplayRuntime, ReplayWindow
from .synthetic import (
    ADAPTER_VERSION,
    CALENDAR_ID,
    CALENDAR_VERSION,
    FIXTURE_KNOWN_AT,
    FIXTURE_PERIOD,
    PROVIDER_ID,
    PROVIDER_KEY,
    SyntheticData,
    SyntheticFundMapping,
    decode_synthetic_data,
    replay_coverage,
    synthetic_series,
)


class ReplayVariant(StrEnum):
    STANDARD = "standard"
    GAP = "gap"
    EMPTY = "empty"
    CORRECTION = "correction"


class ReplayContext:
    """Trusted adapter dependencies; no caller-selected paths, credentials or origins."""

    def __init__(
        self,
        *,
        license: SourceLicense,
        series: tuple[SourceSeries, ...],
        clock: Callable[[], datetime],
        runtime: ReplayRuntime | None = None,
        variant: ReplayVariant = ReplayVariant.STANDARD,
        fixture_payload: bytes | None = None,
        fund_mapping: SyntheticFundMapping | None = None,
    ) -> None:
        if not isinstance(variant, ReplayVariant):
            raise ValueError("invalid replay scenario")
        if (
            not isinstance(license, SourceLicense)
            or not isinstance(series, tuple)
            or not 1 <= len(series) <= 6
            or any(not isinstance(item, SourceSeries) for item in series)
            or license.provider_id != PROVIDER_ID
            or any(
                item.provider_id != PROVIDER_ID or item.license_version_id != license.id
                for item in series
            )
            or len({item.owner_id for item in series}) != 1
        ):
            raise ValueError("replay source configuration is incompatible")
        # These six fixed fixtures must never be relabeled as another mapping,
        # currency, calendar, series key or return basis by adapter construction.
        security = tuple(item for item in series if item.kind is SourceSeriesKind.SECURITY_PRICE)
        mappings = {(item.instrument_id, item.listing_id) for item in security}
        if len(mappings) > 1 or any(listing is None for _, listing in mappings):
            raise ValueError("replay source mapping is incompatible")
        representative = security[0] if security else series[0]
        expected = synthetic_series(
            owner_id=representative.owner_id,
            instrument_id=representative.instrument_id or PROVIDER_ID,
            listing_id=representative.listing_id or PROVIDER_ID,
        )
        if len({item.id for item in series}) != len(series) or any(
            item not in expected for item in series
        ):
            raise ValueError("replay source configuration is incompatible")
        if fund_mapping is not None and (
            not isinstance(fund_mapping, SyntheticFundMapping)
            or fund_mapping.owner_id != representative.owner_id
            or fund_mapping.constituent_instrument_id not in {s.instrument_id for s in security}
        ):
            raise ValueError("replay fund mapping is incompatible")
        self.license = license
        self.series = series
        self.clock = clock
        self.runtime = runtime or ReplayRuntime(
            cursor_key=hashlib.sha256(b"synthetic-reference-continuations-v1").digest()
        )
        self.variant = variant
        self.fund_mapping = fund_mapping
        self.data = decode_synthetic_data(fixture_payload)
        self._data_digest = hashlib.sha256(
            canonical_json(to_primitive(self.data)).encode()
        ).hexdigest()

    @property
    def revision(self) -> str:
        order = "2" if self.variant is ReplayVariant.CORRECTION else "1"
        return f"synthetic-{self.variant.value}-{order}"

    def failure(
        self,
        capability: ports.SourceCapability,
        code: ports.SourceProviderError | ReplayFault | DecodeFailure,
    ) -> ports.SourceFailure:
        category = ports.SourceProviderError(code.value)
        return ports.SourceFailure(
            code=category,
            capability=capability,
            provider_key=PROVIDER_KEY,
            retryable=category
            in {
                ports.SourceProviderError.TIMEOUT,
                ports.SourceProviderError.RATE_LIMITED,
                ports.SourceProviderError.TRANSIENT_FAILURE,
            },
            correlation_id="synthetic-reference-v1",
        )

    def check(
        self,
        capability: ports.SourceCapability,
        cutoff: datetime,
        *,
        series: SourceSeries | None = None,
        period: SourcePeriod | None = None,
    ) -> ports.SourceFailure | datetime:
        at = require_utc(self.clock())
        if isinstance(self.data, DecodeFailure):
            return self.failure(capability, self.data)
        if not self.license.permits(SourceUse.STORE) or at < self.license.effective_at:
            return self.failure(capability, ports.SourceProviderError.LICENSE_DENIED)
        if cutoff < max(FIXTURE_KNOWN_AT, at) or at < FIXTURE_KNOWN_AT:
            return self.failure(capability, ports.SourceProviderError.NOT_FOUND)
        if series is not None and series not in self.series:
            return self.failure(capability, ports.SourceProviderError.ACCESS_DENIED)
        if period is not None and (
            period.start < FIXTURE_PERIOD.start or period.end > FIXTURE_PERIOD.end
        ):
            return self.failure(capability, ports.SourceProviderError.UNSUPPORTED)
        return at

    def provenance(
        self, *, effective_at: datetime, first_observed_at: datetime
    ) -> SourceProvenance:
        return SourceProvenance(
            provider_id=PROVIDER_ID,
            license_version_id=self.license.id,
            adapter_version=ADAPTER_VERSION,
            schema_version="reference-replay-v1",
            source_revision=self.revision,
            revision_order=2 if self.variant is ReplayVariant.CORRECTION else 1,
            effective_at=effective_at,
            first_observed_at=first_observed_at,
            synthetic=True,
        )

    async def page_window(
        self,
        capability: ports.SourceCapability,
        request: object,
        count: int,
        continuation: str | None,
    ) -> ReplayWindow | ports.SourceFailure:
        minimized = to_primitive(request)
        assert isinstance(minimized, dict)
        minimized.pop("continuation", None)
        scope = canonical_json(
            {
                "capability": capability.value,
                "request": minimized,
                "revision": self.revision,
                "fixture_digest": self._data_digest,
                "rows": count,
            }
        )
        window = self.runtime.window(scope=scope, count=count, continuation=continuation)
        if isinstance(window, ReplayFault):
            return self.failure(capability, window)
        fault = await self.runtime.run_attempts(deadline=window.deadline)
        return self.failure(capability, fault) if fault is not ReplayFault.NONE else window

    def dates(self, period: SourcePeriod) -> tuple[date, ...]:
        assert isinstance(self.data, SyntheticData)
        return tuple(
            s.session_date
            for s in self.data.calendar.sessions
            if period.start <= s.session_date <= period.end
        )


class ReplayMarketPriceHistoryProvider:
    def __init__(self, context: ReplayContext) -> None:
        self.context = context

    async def get_price_history(
        self, request: ports.PriceHistoryRequest
    ) -> ports.PriceHistoryPage | ports.SourceFailure:
        context = self.context
        capability = ports.SourceCapability.PRICE_HISTORY
        failure = context.check(
            capability, request.source_cutoff_at, series=request.series, period=request.period
        )
        if isinstance(failure, ports.SourceFailure):
            return failure
        assert isinstance(context.data, SyntheticData)
        observations = tuple(
            row
            for basis, rows in context.data.prices
            if basis is request.series.basis
            for row in rows
            if request.period.start <= row.session_date <= request.period.end
        )
        if context.variant is ReplayVariant.EMPTY:
            observations = ()
        elif context.variant is ReplayVariant.GAP:
            observations = tuple(
                replace(row, value=None, state=ObservationState.MISSING)
                if row.session_date == date(2026, 8, 12)
                else row
                for row in observations
            )
        elif context.variant is ReplayVariant.CORRECTION:
            observations = tuple(
                replace(
                    row,
                    value=Decimal("222") if row.session_date == date(2026, 8, 28) else row.value,
                    corporate_action_revision=(
                        row.corporate_action_revision.removesuffix("-1") + "-2"
                        if row.corporate_action_revision is not None
                        else None
                    ),
                )
                for row in observations
            )
        window = await context.page_window(
            capability, request, len(observations), request.continuation
        )
        if isinstance(window, ports.SourceFailure):
            return window
        coverage = replay_coverage(
            expected_dates=context.dates(request.period),
            available_dates=tuple(
                row.session_date for row in observations if row.state is ObservationState.AVAILABLE
            ),
        )
        return ports.PriceHistoryPage(
            series=request.series,
            provenance=context.provenance(
                first_observed_at=failure,
                effective_at=max(
                    (row.effective_at for row in observations),
                    default=datetime.combine(request.period.end, datetime.min.time(), UTC),
                ),
            ),
            period=request.period,
            coverage=coverage,
            observations=observations[window.start : window.stop],
            continuation=window.continuation,
        )

    async def get_corporate_actions(
        self, request: ports.CorporateActionsRequest
    ) -> ports.CorporateActionPage | ports.SourceFailure:
        from .replay_enrichment import corporate_actions

        return await corporate_actions(self.context, request)


class ReplayFxReferenceProvider:
    def __init__(self, context: ReplayContext) -> None:
        self.context = context

    async def get_rates(
        self, request: ports.FxRatesRequest
    ) -> ports.FxRatePage | ports.SourceFailure:
        context = self.context
        capability = ports.SourceCapability.FX_RATES
        failure = context.check(capability, request.source_cutoff_at, period=request.period)
        if isinstance(failure, ports.SourceFailure):
            return failure
        if request.provider_id != PROVIDER_ID or request.license_version_id != context.license.id:
            return context.failure(capability, ports.SourceProviderError.ACCESS_DENIED)
        if (request.calendar_id, request.calendar_version) != (CALENDAR_ID, CALENDAR_VERSION):
            return context.failure(capability, ports.SourceProviderError.UNSUPPORTED)
        assert isinstance(context.data, SyntheticData)
        pairs = {(pair.base, pair.quote) for pair in request.pairs}
        if not pairs.issubset({(row.base, row.quote) for row in context.data.fx}):
            return context.failure(capability, ports.SourceProviderError.UNSUPPORTED)
        observations = tuple(
            row
            for row in context.data.fx
            if (row.base, row.quote) in pairs
            and request.period.start <= row.session_date <= request.period.end
        )
        if context.variant is ReplayVariant.EMPTY:
            observations = ()
        elif context.variant is ReplayVariant.GAP:
            observations = tuple(
                replace(row, rate=None, state=ObservationState.MISSING)
                if row.session_date == date(2026, 8, 12)
                else row
                for row in observations
            )
        elif context.variant is ReplayVariant.CORRECTION:
            observations = tuple(
                replace(row, rate=Decimal("1.25"))
                if row.base == CurrencyCode("EUR") and row.session_date == date(2026, 8, 28)
                else row
                for row in observations
            )
        window = await context.page_window(
            capability, request, len(observations), request.continuation
        )
        if isinstance(window, ports.SourceFailure):
            return window
        expected = {
            (day, base, quote) for day in context.dates(request.period) for base, quote in pairs
        }
        available = {
            (row.session_date, row.base, row.quote)
            for row in observations
            if row.state is ObservationState.AVAILABLE
        }
        missing = expected - available
        coverage = SourceCoverage(
            expected_count=len(expected),
            available_count=len(available),
            gaps=tuple(
                SourceGap(
                    session_date=day,
                    source_key=f"{base}:{quote}",
                    reason=SourceReason.MISSING_SESSION,
                )
                for day, base, quote in sorted(missing)
            ),
            quality=QualityState.PARTIAL if missing else QualityState.FRESH,
            reason=SourceReason.MISSING_SESSION if missing else None,
        )
        return ports.FxRatePage(
            provenance=context.provenance(
                first_observed_at=failure,
                effective_at=max(
                    (row.effective_at for row in observations),
                    default=datetime.combine(request.period.end, datetime.min.time(), UTC),
                ),
            ),
            period=request.period,
            coverage=coverage,
            observations=observations[window.start : window.stop],
            continuation=window.continuation,
        )


class ReplayBenchmarkProvider:
    def __init__(self, context: ReplayContext) -> None:
        self.context = context

    async def get_series(
        self, request: ports.BenchmarkSeriesRequest
    ) -> ports.BenchmarkSeriesPage | ports.SourceFailure:
        context = self.context
        capability = ports.SourceCapability.BENCHMARK_SERIES
        failure = context.check(
            capability, request.source_cutoff_at, series=request.series, period=request.period
        )
        if isinstance(failure, ports.SourceFailure):
            return failure
        assert isinstance(context.data, SyntheticData)
        observations = tuple(
            row
            for basis, rows in context.data.benchmark
            if basis is request.series.basis
            for row in rows
            if request.period.start <= row.session_date <= request.period.end
        )
        if context.variant is ReplayVariant.EMPTY:
            observations = ()
        elif context.variant is ReplayVariant.GAP:
            observations = tuple(
                replace(row, level=None, state=ObservationState.MISSING)
                if row.session_date == date(2026, 8, 12)
                else row
                for row in observations
            )
        elif context.variant is ReplayVariant.CORRECTION:
            observations = tuple(
                replace(row, level=Decimal("1040"))
                if row.session_date == date(2026, 8, 28)
                else row
                for row in observations
            )
        window = await context.page_window(
            capability, request, len(observations), request.continuation
        )
        if isinstance(window, ports.SourceFailure):
            return window
        return ports.BenchmarkSeriesPage(
            series=request.series,
            provenance=context.provenance(
                first_observed_at=failure,
                effective_at=max(
                    (row.effective_at for row in observations),
                    default=datetime.combine(request.period.end, datetime.min.time(), UTC),
                ),
            ),
            period=request.period,
            coverage=replay_coverage(
                expected_dates=context.dates(request.period),
                available_dates=tuple(
                    row.session_date
                    for row in observations
                    if row.state is ObservationState.AVAILABLE
                ),
            ),
            observations=observations[window.start : window.stop],
            continuation=window.continuation,
        )
