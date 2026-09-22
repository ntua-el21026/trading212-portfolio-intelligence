"""Pure canonical projections; callers must supply authorized immutable metadata."""

from __future__ import annotations

from datetime import datetime

from trading212_application.source_providers import (
    FxPair,
    FxRatePage,
    FxRatesRequest,
    PriceHistoryPage,
    PriceHistoryRequest,
)
from trading212_domain import CurrencyCode
from trading212_domain.enums import QualityState
from trading212_domain.sources import (
    FxObservation,
    ObservationState,
    PriceBasis,
    PriceObservation,
    SourceCalendar,
    SourceCoverage,
    SourceGap,
    SourcePeriod,
    SourceProvenance,
    SourceReason,
    SourceSeries,
    SourceSeriesKind,
)

from .premium_acquisition_types import (
    AcquireDailyAdjusted,
    AcquireEcbReferenceFx,
    AcquisitionRejected,
    capability,
)
from .premium_acquisition_types import (
    AcquisitionFailureCode as Code,
)
from .premium_facts import (
    AcquiredSourceBatch,
    DailyAdjustedFacts,
    EcbReferenceFacts,
    premium_facts_digest,
)


def _provenance(batch: AcquiredSourceBatch, effective_at: datetime) -> SourceProvenance:
    value = batch.provenance
    return SourceProvenance(
        provider_id=str(value.provider_id),
        license_version_id=value.license.id,
        adapter_version=value.adapter_version,
        schema_version="premium-normalized-v1",
        source_revision=value.content_digest,
        revision_order=None,
        effective_at=effective_at,
        first_observed_at=value.first_known_at,
        synthetic=value.synthetic,
    )


def _coverage(expected: int, available: int, gaps: tuple[SourceGap, ...]) -> SourceCoverage:
    return SourceCoverage(
        expected_count=expected,
        available_count=available,
        gaps=gaps,
        quality=QualityState.PARTIAL if gaps else QualityState.FRESH,
        reason=SourceReason.MISSING_SESSION if gaps else None,
    )


def build_price_history_pages(
    batch: AcquiredSourceBatch, series: SourceSeries, calendar: SourceCalendar
) -> tuple[PriceHistoryRequest, tuple[PriceHistoryPage, ...]]:
    """RAW_CLOSE only: AV split+dividend adjusted close has no equivalent frozen basis.

    IDs and a supplied calendar alone are not authority. The publication service
    must load and reauthorize these exact original records and the successful
    acquisition/permit, then clamp its source lifetime to the acquisition expiry.
    """
    facts, provenance = batch.facts, batch.provenance
    if (
        type(facts) is not DailyAdjustedFacts
        or type(batch.command) is not AcquireDailyAdjusted
        or facts.period != batch.command.period
        or provenance.capability is not capability(batch.command)
        or premium_facts_digest(facts) != provenance.content_digest
        or type(series) is not SourceSeries
        or type(calendar) is not SourceCalendar
        or series.kind is not SourceSeriesKind.SECURITY_PRICE
        or series.basis is not PriceBasis.RAW_CLOSE
        or (series.owner_id, series.provider_id, series.license_version_id, series.mapping_id)
        != (
            str(provenance.owner_id),
            str(provenance.provider_id),
            provenance.license.id,
            str(provenance.canonical_market_mapping_id),
        )
        or provenance.canonical_market_mapping_id is None
        or provenance.instrument_id is None
        or series.instrument_id != str(provenance.instrument_id)
        or series.provider_key != facts.symbol
        or series.currency != facts.price_currency
        or (series.calendar_id, series.calendar_version) != (calendar.id, calendar.version)
        or calendar.period.start > facts.period.start
        or calendar.period.end < facts.period.end
    ):
        raise AcquisitionRejected(Code.UNSUPPORTED)
    sessions = tuple(
        row
        for row in calendar.sessions
        if facts.period.start <= row.session_date <= facts.period.end
    )
    if not sessions or any(row.close_at > provenance.observed_at for row in sessions):
        raise AcquisitionRejected(Code.UNSUPPORTED)
    expected = {row.session_date for row in sessions}
    values = {row.session_date: row.close for row in facts.rows}
    if len(values) != len(facts.rows) or not values.keys() <= expected:
        raise AcquisitionRejected()
    observations = tuple(
        PriceObservation(
            session_date=row.session_date,
            effective_at=row.close_at,
            value=values.get(row.session_date),
            state=ObservationState.AVAILABLE
            if row.session_date in values
            else ObservationState.MISSING,
        )
        for row in sessions
    )
    gaps = tuple(
        SourceGap(session_date=row.session_date, reason=SourceReason.MISSING_SESSION)
        for row in sessions
        if row.session_date not in values
    )
    coverage = _coverage(len(sessions), len(values), gaps)
    source = _provenance(batch, max(row.close_at for row in sessions))
    pages = tuple(
        PriceHistoryPage(
            series=series,
            provenance=source,
            period=facts.period,
            coverage=coverage,
            observations=observations[index : index + 1000],
            continuation=f"premium:{provenance.content_digest}:{index + 1000}"
            if index + 1000 < len(observations)
            else None,
        )
        for index in range(0, len(observations), 1000)
    )
    return PriceHistoryRequest(
        series=series, period=facts.period, source_cutoff_at=provenance.first_known_at
    ), pages


def build_ecb_fx_pages(
    batch: AcquiredSourceBatch,
    calendar: SourceCalendar,
    pairs: tuple[FxPair, ...],
    period: SourcePeriod,
) -> tuple[FxRatesRequest, tuple[FxRatePage, ...]]:
    """Retain original EUR-base legs only; canonical FX consumers own sourced cross-rates."""
    facts, provenance = batch.facts, batch.provenance
    if (
        type(facts) is not EcbReferenceFacts
        or type(batch.command) is not AcquireEcbReferenceFx
        or provenance.capability is not capability(batch.command)
        or premium_facts_digest(facts) != provenance.content_digest
        or type(calendar) is not SourceCalendar
        or type(period) is not SourcePeriod
        or type(pairs) is not tuple
        or not 1 <= len(pairs) <= 32
        or any(type(pair) is not FxPair or pair.base != CurrencyCode("EUR") for pair in pairs)
        or len(pairs) != len(set(pairs))
        or calendar.period.start > period.start
        or calendar.period.end < period.end
    ):
        raise AcquisitionRejected(Code.UNSUPPORTED)
    sessions = tuple(
        row for row in calendar.sessions if period.start <= row.session_date <= period.end
    )
    if not sessions or any(
        not facts.first_date <= row.session_date <= facts.last_date
        or row.close_at > provenance.observed_at
        for row in sessions
    ):
        raise AcquisitionRejected(Code.UNSUPPORTED)
    requested = {(row.session_date, pair.quote) for row in sessions for pair in pairs}
    values = {
        (row.session_date, row.quote): row
        for row in facts.rows
        if (row.session_date, row.quote) in requested
    }
    observations, gaps = [], []
    for session in sessions:
        for pair in pairs:
            found = values.get((session.session_date, pair.quote))
            key = f"ecb:{session.session_date.isoformat()}:EUR:{pair.quote}"
            observations.append(
                FxObservation(
                    base=pair.base,
                    quote=pair.quote,
                    session_date=session.session_date,
                    effective_at=session.close_at,
                    rate=None if found is None else found.rate,
                    batch_key=key,
                    state=ObservationState.MISSING if found is None else ObservationState.AVAILABLE,
                )
            )
            if found is None:
                gaps.append(
                    SourceGap(
                        session_date=session.session_date,
                        source_key=f"EUR:{pair.quote}",
                        reason=SourceReason.MISSING_SESSION,
                    )
                )
    request = FxRatesRequest(
        provider_id=str(provenance.provider_id),
        license_version_id=provenance.license.id,
        calendar_id=calendar.id,
        calendar_version=calendar.version,
        pairs=pairs,
        period=period,
        source_cutoff_at=provenance.first_known_at,
    )
    coverage = _coverage(len(requested), len(values), tuple(gaps))
    source = _provenance(batch, max(row.close_at for row in sessions))
    pages = tuple(
        FxRatePage(
            provenance=source,
            period=period,
            coverage=coverage,
            observations=tuple(observations[index : index + 1000]),
            continuation=f"premium:{provenance.content_digest}:{index + 1000}"
            if index + 1000 < len(observations)
            else None,
        )
        for index in range(0, len(observations), 1000)
    )
    return request, pages
