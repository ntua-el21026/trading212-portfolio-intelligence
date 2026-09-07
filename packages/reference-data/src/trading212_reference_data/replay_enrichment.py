"""Typed corporate-action, resolution, classification and ETF replay capabilities."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from trading212_application import source_providers as ports
from trading212_domain.enums import QualityState
from trading212_domain.source_details import (
    ClassificationObservation,
    ConstituentHolding,
    ConstituentState,
    InstrumentCandidate,
    SourceMappingState,
)
from trading212_domain.sources import ObservationState, SourceCoverage, SourceGap, SourceReason
from trading212_domain.values import CurrencyCode

from .replay import ReplayContext, ReplayVariant
from .synthetic import FIXTURE_KNOWN_AT, SyntheticData


async def corporate_actions(
    context: ReplayContext, request: ports.CorporateActionsRequest
) -> ports.CorporateActionPage | ports.SourceFailure:
    capability = ports.SourceCapability.CORPORATE_ACTIONS
    failure = context.check(
        capability, request.source_cutoff_at, series=request.series, period=request.period
    )
    if isinstance(failure, ports.SourceFailure):
        return failure
    assert isinstance(context.data, SyntheticData)
    observations = tuple(
        row
        for row in context.data.actions
        if request.period.start <= row.session_date <= request.period.end
    )
    if context.variant is ReplayVariant.EMPTY:
        # An empty event stream is successful only for this explicit synthetic scenario.
        observations = ()
    elif context.variant is ReplayVariant.GAP:
        observations = tuple(
            replace(
                row,
                state=ObservationState.UNSUPPORTED,
                ratio=None,
                amount=None,
                currency=None,
                target_instrument_id=None,
            )
            if index == 0
            else row
            for index, row in enumerate(observations)
        )
    elif context.variant is ReplayVariant.CORRECTION:
        observations = tuple(
            replace(
                row,
                source_key=row.source_key + "-corrected",
                correction_source_key=row.source_key,
                source_revision=(row.source_revision.removesuffix("-1") + "-2")
                if row.source_revision is not None
                else None,
                ratio=Decimal("3") if row.ratio is not None else None,
                amount=Decimal("0.75") if row.amount is not None else None,
            )
            for row in observations
        )
    window = await context.page_window(capability, request, len(observations), request.continuation)
    if isinstance(window, ports.SourceFailure):
        return window
    return ports.CorporateActionPage(
        series=request.series,
        provenance=context.provenance(
            first_observed_at=failure,
            effective_at=max(
                (row.effective_at for row in observations),
                default=datetime.combine(request.period.end, datetime.min.time(), UTC),
            ),
        ),
        period=request.period,
        coverage=SourceCoverage(
            expected_count=len(observations),
            available_count=sum(row.state is ObservationState.AVAILABLE for row in observations),
            gaps=tuple(
                SourceGap(
                    session_date=row.session_date,
                    source_key=row.source_key,
                    reason=SourceReason.UNSUPPORTED,
                )
                for row in observations
                if row.state is not ObservationState.AVAILABLE
            ),
            quality=QualityState.FRESH
            if all(row.state is ObservationState.AVAILABLE for row in observations)
            else QualityState.PARTIAL,
            reason=None
            if all(row.state is ObservationState.AVAILABLE for row in observations)
            else SourceReason.UNSUPPORTED,
        ),
        observations=observations[window.start : window.stop],
        continuation=window.continuation,
    )


class ReplayInstrumentEnrichmentProvider:
    def __init__(self, context: ReplayContext) -> None:
        self.context = context

    async def resolve_instrument(
        self, request: ports.InstrumentResolutionRequest
    ) -> ports.InstrumentResolutionResult | ports.SourceFailure:
        context = self.context
        capability = ports.SourceCapability.RESOLVE_INSTRUMENT
        failure = context.check(capability, request.source_cutoff_at)
        if isinstance(failure, ports.SourceFailure):
            return failure
        window = await context.page_window(capability, request, 1, None)
        if isinstance(window, ports.SourceFailure):
            return window
        identifier = request.identifier
        assert isinstance(context.data, SyntheticData)
        matches = identifier in context.data.identifiers
        candidates = tuple(
            InstrumentCandidate(
                instrument_id=instrument_id,
                listing_id=listing_id,
                evidence_key="synthetic-mapping-v1",
                valid_from=FIXTURE_KNOWN_AT,
                valid_to=None,
                confidence=Decimal("1"),
            )
            for instrument_id, listing_id in sorted(
                {
                    (series.instrument_id, series.listing_id)
                    for series in context.series
                    if matches and series.instrument_id is not None
                },
                key=lambda pair: (pair[0], pair[1] or ""),
            )
        )
        if context.variant is ReplayVariant.EMPTY:
            candidates = ()
        state = (
            SourceMappingState.UNRESOLVED
            if not candidates
            else (
                SourceMappingState.RESOLVED
                if len(candidates) == 1
                else SourceMappingState.AMBIGUOUS
            )
        )
        return ports.InstrumentResolutionResult(
            state=state,
            candidates=candidates,
            reason=SourceReason.UNRESOLVED
            if not candidates
            else SourceReason.AMBIGUOUS
            if len(candidates) > 1
            else None,
        )

    async def get_classifications(
        self, request: ports.ClassificationRequest
    ) -> ports.ClassificationPage | ports.SourceFailure:
        context = self.context
        capability = ports.SourceCapability.CLASSIFICATIONS
        failure = context.check(capability, request.source_cutoff_at)
        if isinstance(failure, ports.SourceFailure):
            return failure
        assert isinstance(context.data, SyntheticData)
        known = {series.instrument_id for series in context.series}
        if (
            request.taxonomy != "synthetic-taxonomy"
            or request.taxonomy_version != "1"
            or not set(request.instrument_ids).issubset(known)
        ):
            return context.failure(capability, ports.SourceProviderError.UNSUPPORTED)
        observations = tuple(
            ClassificationObservation(
                instrument_id=instrument,
                dimension=dimension,
                taxonomy=request.taxonomy,
                taxonomy_version=request.taxonomy_version,
                category=category,
                evidence_key="synthetic-classifications-v1",
                valid_from=FIXTURE_KNOWN_AT,
                valid_to=None,
                confidence=Decimal("1"),
            )
            for instrument in sorted(request.instrument_ids)
            for dimension, category in context.data.classifications
        )
        if context.variant is ReplayVariant.EMPTY or not observations:
            return context.failure(capability, ports.SourceProviderError.NOT_FOUND)
        window = await context.page_window(
            capability, request, len(observations), request.continuation
        )
        if isinstance(window, ports.SourceFailure):
            return window
        return ports.ClassificationPage(
            provenance=context.provenance(effective_at=FIXTURE_KNOWN_AT, first_observed_at=failure),
            observations=observations[window.start : window.stop],
            continuation=window.continuation,
        )


class ReplayETFConstituentProvider:
    def __init__(self, context: ReplayContext) -> None:
        self.context = context

    async def get_constituents(
        self, request: ports.ConstituentRequest
    ) -> ports.ConstituentPage | ports.SourceFailure:
        context = self.context
        capability = ports.SourceCapability.CONSTITUENTS
        failure = context.check(capability, request.source_cutoff_at)
        if isinstance(failure, ports.SourceFailure):
            return failure
        mapping = context.fund_mapping
        if mapping is None or request.fund_series_id != mapping.fund_series_id:
            return context.failure(capability, ports.SourceProviderError.NOT_FOUND)
        if request.effective_at < FIXTURE_KNOWN_AT:
            return context.failure(capability, ports.SourceProviderError.NOT_FOUND)
        if context.variant is ReplayVariant.EMPTY:
            return context.failure(capability, ports.SourceProviderError.NOT_FOUND)
        assert isinstance(context.data, SyntheticData)
        if not context.data.constituents:
            return context.failure(capability, ports.SourceProviderError.NOT_FOUND)
        holdings = tuple(
            ConstituentHolding(
                source_key=row.source_key,
                weight=row.weight,
                state=row.state,
                currency=CurrencyCode("EUR"),
                instrument_id=mapping.constituent_instrument_id
                if row.state is ConstituentState.RESOLVED
                else None,
                evidence_key="synthetic-constituents-v1"
                if row.state is ConstituentState.RESOLVED
                else None,
            )
            for row in context.data.constituents
        )
        window = await context.page_window(capability, request, len(holdings), request.continuation)
        if isinstance(window, ports.SourceFailure):
            return window
        with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
            totals = {
                state: sum((row.weight for row in holdings if row.state is state), Decimal(0))
                for state in ConstituentState
            }
        return ports.ConstituentPage(
            provenance=context.provenance(effective_at=FIXTURE_KNOWN_AT, first_observed_at=failure),
            effective_at=FIXTURE_KNOWN_AT,
            holdings=holdings[window.start : window.stop],
            stated_coverage=totals[ConstituentState.RESOLVED],
            unresolved_weight=totals[ConstituentState.UNRESOLVED],
            cash_weight=totals[ConstituentState.CASH],
            continuation=window.continuation,
        )
