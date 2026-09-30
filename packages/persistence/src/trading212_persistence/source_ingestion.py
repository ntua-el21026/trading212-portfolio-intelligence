"""Atomic licensed ingestion of already-fetched typed pages; no network dispatch."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import TypedDict, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_application import sources as app
from trading212_application.source_ingestion import (
    SourceInstrumentMapping,
    SourceProvider,
    SourceProviderRegistration,
)
from trading212_application.source_providers import (
    BenchmarkSeriesPage,
    BenchmarkSeriesRequest,
    CorporateActionPage,
    CorporateActionsRequest,
    FxRatePage,
    FxRatesRequest,
    PriceHistoryPage,
    PriceHistoryRequest,
    SourceCapability,
)
from trading212_domain.serialization import canonical_json
from trading212_domain.source_details import (
    CorporateActionKind,
    CorporateActionObservation,
    CorporateActionSnapshot,
    SourceMappingState,
)
from trading212_domain.sources import (
    BenchmarkObservation,
    BenchmarkSnapshot,
    FxObservation,
    FxSnapshot,
    ObservationState,
    PriceObservation,
    PriceSnapshot,
    SourceCalendar,
    SourceCoverage,
    SourceLicense,
    SourcePeriod,
    SourceProvenance,
    SourceSeries,
    SourceUse,
    source_snapshot_digest,
)
from trading212_security.principals import Principal

from .acquisition_records import AcquisitionPublicationClock
from .models import InstrumentModel, ListingModel
from .source_models import (
    BenchmarkObservationModel,
    BenchmarkSnapshotModel,
    CorporateActionObservationModel,
    CorporateActionSnapshotModel,
    FxObservationModel,
    FxSnapshotModel,
    MarketDataInstrumentModel,
    MarketDataProviderModel,
    MarketSourceSeriesModel,
    PriceObservationModel,
    PriceSnapshotModel,
    ProviderLicenseVersionModel,
    SourceCalendarModel,
    SourceCalendarSessionModel,
    SourceCoverageGapModel,
    SourceMappingCandidateModel,
    SourceRetrievalOccurrenceModel,
    SourceSnapshotFields,
)
from .source_store import SourceStore, digest, error

type Snapshot = PriceSnapshot | FxSnapshot | BenchmarkSnapshot | CorporateActionSnapshot
type Request = (
    PriceHistoryRequest | FxRatesRequest | BenchmarkSeriesRequest | CorporateActionsRequest
)
type SourcePage = PriceHistoryPage | FxRatePage | BenchmarkSeriesPage | CorporateActionPage


class SnapshotHeader(TypedDict):
    id: str
    owner_id: str
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage


class SourceIngestion(SourceStore):
    async def configure_source_provider(
        self,
        principal: Principal,
        command: SourceProviderRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> SourceProvider:
        def operation(session: Session, owner: UUID) -> SourceProvider:
            replay, fingerprint = self._replay(
                session, owner, "provider.configure", idempotency_key, command
            )
            row = session.scalar(
                select(MarketDataProviderModel).where(
                    MarketDataProviderModel.id == UUID(command.id)
                )
            )
            if row is not None and row.owner_id != owner:
                raise error(app.SourceServiceErrorCode.NOT_FOUND)
            if replay is not None:
                assert row is not None and replay.result_revision is not None
                return SourceProvider(
                    registration=command,
                    revision=replay.result_revision,
                    created_at=row.created_at,
                    updated_at=replay.created_at,
                )
            if row is None:
                row = MarketDataProviderModel(
                    id=UUID(command.id),
                    owner_id=owner,
                    key=command.key,
                    name=command.name,
                    adapter_version=command.adapter_version,
                    configuration_state=command.configuration_state.value,
                    synthetic=command.synthetic,
                    freshness_policy_version=command.freshness_policy_version,
                    max_age_seconds=command.max_age_seconds,
                    capabilities=[x.value for x in command.capabilities],
                    supported_price_bases=[x.value for x in command.supported_price_bases],
                    revision=1,
                    created_at=self._now(),
                    updated_at=self._now(),
                )
                session.add(row)
            else:
                if row.key != command.key or row.synthetic != command.synthetic:
                    raise error(app.SourceServiceErrorCode.SOURCE_REVISION_CONFLICT)
                row.name, row.adapter_version = command.name, command.adapter_version
                row.configuration_state = command.configuration_state.value
                row.capabilities = [x.value for x in command.capabilities]
                row.supported_price_bases = [x.value for x in command.supported_price_bases]
                row.freshness_policy_version = command.freshness_policy_version
                row.max_age_seconds = command.max_age_seconds
                row.revision += 1
                row.updated_at = self._now()
            session.flush()
            self._record(
                session,
                principal,
                "provider.configure",
                idempotency_key,
                fingerprint,
                row.id,
                correlation_id,
                row.revision,
            )
            return self._provider_view(row)

        return await self._run(principal, operation, write=True)

    async def register_source_license(
        self,
        principal: Principal,
        license: SourceLicense,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> SourceLicense:
        def operation(session: Session, owner: UUID) -> SourceLicense:
            self._owned(session, owner, MarketDataProviderModel, license.provider_id)
            replay, fingerprint = self._replay(
                session, owner, "license.register", idempotency_key, license
            )
            if replay is not None:
                return self._license(session, owner, replay.result_id)
            row = session.scalar(
                select(ProviderLicenseVersionModel).where(
                    ProviderLicenseVersionModel.id == UUID(license.id)
                )
            )
            if row is not None:
                if row.owner_id != owner:
                    raise error(app.SourceServiceErrorCode.NOT_FOUND)
                if self._license(session, owner, row.id) != license:
                    raise error(app.SourceServiceErrorCode.SOURCE_REVISION_CONFLICT)
            else:
                session.add(
                    ProviderLicenseVersionModel(
                        id=UUID(license.id),
                        owner_id=owner,
                        provider_id=UUID(license.provider_id),
                        version=license.version,
                        version_number=int(
                            session.scalar(
                                select(
                                    func.coalesce(
                                        func.max(ProviderLicenseVersionModel.version_number), 0
                                    )
                                ).where(
                                    ProviderLicenseVersionModel.provider_id
                                    == UUID(license.provider_id)
                                )
                            )
                            or 0
                        )
                        + 1,
                        effective_at=license.effective_at,
                        store_permission=license.store.value,
                        display_permission=license.display.value,
                        report_permission=license.report.value,
                        export_permission=license.export.value,
                        retention_days=license.retention_days,
                        attribution=license.attribution,
                        evidence_key=license.evidence_key,
                        created_at=self._now(),
                    )
                )
                session.flush()
            self._record(
                session,
                principal,
                "license.register",
                idempotency_key,
                fingerprint,
                UUID(license.id),
                correlation_id,
            )
            return license

        return await self._run(principal, operation, write=True)

    async def register_source_calendar(
        self,
        principal: Principal,
        calendar: SourceCalendar,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> SourceCalendar:
        def operation(session: Session, owner: UUID) -> SourceCalendar:
            replay, fingerprint = self._replay(
                session, owner, "calendar.register", idempotency_key, calendar
            )
            if replay is not None:
                return self._calendar(session, owner, replay.result_id)
            row = session.scalar(
                select(SourceCalendarModel).where(
                    SourceCalendarModel.owner_id == owner,
                    SourceCalendarModel.key == calendar.id,
                    SourceCalendarModel.version == calendar.version,
                )
            )
            if row is not None and row.content_digest != digest(calendar):
                raise error(app.SourceServiceErrorCode.SOURCE_REVISION_CONFLICT)
            if row is None:
                row = SourceCalendarModel(
                    id=uuid4(),
                    owner_id=owner,
                    key=calendar.id,
                    version=calendar.version,
                    timezone=calendar.timezone,
                    period_start=calendar.period.start,
                    period_end=calendar.period.end,
                    content_digest=digest(calendar),
                    created_at=self._now(),
                )
                session.add(row)
                session.flush()
                session.add_all(
                    SourceCalendarSessionModel(
                        owner_id=owner,
                        calendar_id=row.id,
                        session_date=x.session_date,
                        close_at=x.close_at,
                        created_at=self._now(),
                    )
                    for x in calendar.sessions
                )
                session.flush()
            self._record(
                session,
                principal,
                "calendar.register",
                idempotency_key,
                fingerprint,
                row.id,
                correlation_id,
            )
            return calendar

        return await self._run(principal, operation, write=True)

    def _canonical_mapping(
        self, session: Session, instrument: str | None, listing: str | None
    ) -> None:
        if instrument is not None and session.get(InstrumentModel, UUID(instrument)) is None:
            raise error(app.SourceServiceErrorCode.NOT_FOUND)
        if listing is not None:
            row = session.get(ListingModel, UUID(listing))
            if row is None or row.instrument_id != UUID(str(instrument)):
                raise error(app.SourceServiceErrorCode.NOT_FOUND)

    async def register_source_mapping(
        self,
        principal: Principal,
        mapping: SourceInstrumentMapping,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> SourceInstrumentMapping:
        def operation(session: Session, owner: UUID) -> SourceInstrumentMapping:
            self._owned(session, owner, MarketDataProviderModel, mapping.provider_id)
            self._canonical_mapping(session, mapping.instrument_id, mapping.listing_id)
            for candidate in mapping.candidates:
                self._canonical_mapping(session, candidate.instrument_id, candidate.listing_id)
            replay, fingerprint = self._replay(
                session, owner, "mapping.register", idempotency_key, mapping
            )
            if replay is not None:
                return mapping
            row = session.scalar(
                select(MarketDataInstrumentModel).where(
                    MarketDataInstrumentModel.id == UUID(mapping.id)
                )
            )
            if row is not None:
                if row.owner_id != owner:
                    raise error(app.SourceServiceErrorCode.NOT_FOUND)
                if row.content_digest != digest(mapping):
                    raise error(app.SourceServiceErrorCode.SOURCE_REVISION_CONFLICT)
            else:
                row = MarketDataInstrumentModel(
                    id=UUID(mapping.id),
                    owner_id=owner,
                    provider_id=UUID(mapping.provider_id),
                    provider_key=mapping.provider_key,
                    version=mapping.version,
                    state=mapping.state.value,
                    instrument_id=None
                    if mapping.instrument_id is None
                    else UUID(mapping.instrument_id),
                    listing_id=None if mapping.listing_id is None else UUID(mapping.listing_id),
                    identifier_kind=mapping.identifier.kind.value,
                    identifier_value=mapping.identifier.value,
                    identifier_mic=mapping.identifier.mic,
                    currency=mapping.currency.value,
                    asset_type=mapping.asset_type,
                    evidence_key=mapping.evidence_key,
                    valid_from=mapping.valid_from,
                    valid_to=mapping.valid_to,
                    content_digest=digest(mapping),
                    created_at=self._now(),
                )
                session.add(row)
                session.flush()
                session.add_all(
                    SourceMappingCandidateModel(
                        owner_id=owner,
                        mapping_id=row.id,
                        ordinal=i,
                        instrument_id=UUID(x.instrument_id),
                        listing_id=None if x.listing_id is None else UUID(x.listing_id),
                        evidence_key=x.evidence_key,
                        valid_from=x.valid_from,
                        valid_to=x.valid_to,
                        confidence=x.confidence,
                        created_at=self._now(),
                    )
                    for i, x in enumerate(mapping.candidates)
                )
                session.flush()
            self._record(
                session,
                principal,
                "mapping.register",
                idempotency_key,
                fingerprint,
                row.id,
                correlation_id,
            )
            return mapping

        return await self._run(principal, operation, write=True)

    async def register_source_series(
        self,
        principal: Principal,
        series: SourceSeries,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> SourceSeries:
        def operation(session: Session, owner: UUID) -> SourceSeries:
            if series.owner_id != str(owner):
                raise error(app.SourceServiceErrorCode.NOT_FOUND)
            license = self._permit(session, owner, UUID(series.license_version_id), SourceUse.STORE)
            if license.provider_id != series.provider_id:
                raise error(app.SourceServiceErrorCode.NOT_FOUND)
            calendar = session.scalar(
                select(SourceCalendarModel).where(
                    SourceCalendarModel.owner_id == owner,
                    SourceCalendarModel.key == series.calendar_id,
                    SourceCalendarModel.version == series.calendar_version,
                )
            )
            if calendar is None:
                raise error(app.SourceServiceErrorCode.NOT_FOUND)
            if series.mapping_id is not None:
                mapping = self._owned(session, owner, MarketDataInstrumentModel, series.mapping_id)
                if (
                    mapping.provider_key != series.provider_key
                    or mapping.provider_id != UUID(series.provider_id)
                    or mapping.state != SourceMappingState.RESOLVED.value
                    or mapping.version != series.mapping_version
                    or mapping.instrument_id != UUID(str(series.instrument_id))
                    or mapping.listing_id
                    != (None if series.listing_id is None else UUID(series.listing_id))
                    or mapping.currency != series.currency.value
                ):
                    raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
            replay, fingerprint = self._replay(
                session, owner, "series.register", idempotency_key, series
            )
            if replay is not None:
                return self._series(session, owner, replay.result_id)
            row = session.scalar(
                select(MarketSourceSeriesModel).where(MarketSourceSeriesModel.id == UUID(series.id))
            )
            if row is not None:
                if row.owner_id != owner:
                    raise error(app.SourceServiceErrorCode.NOT_FOUND)
                if row.content_digest != digest(series):
                    raise error(app.SourceServiceErrorCode.SOURCE_REVISION_CONFLICT)
            else:
                session.add(
                    MarketSourceSeriesModel(
                        id=UUID(series.id),
                        owner_id=owner,
                        provider_id=UUID(series.provider_id),
                        license_version_id=UUID(series.license_version_id),
                        calendar_id=calendar.id,
                        mapping_id=None if series.mapping_id is None else UUID(series.mapping_id),
                        kind=series.kind.value,
                        provider_key=series.provider_key,
                        mapping_version=series.mapping_version,
                        instrument_id=None
                        if series.instrument_id is None
                        else UUID(series.instrument_id),
                        listing_id=None if series.listing_id is None else UUID(series.listing_id),
                        basis=series.basis.value,
                        currency=series.currency.value,
                        content_digest=digest(series),
                        created_at=self._now(),
                    )
                )
                session.flush()
            self._record(
                session,
                principal,
                "series.register",
                idempotency_key,
                fingerprint,
                UUID(series.id),
                correlation_id,
            )
            return series

        return await self._run(principal, operation, write=True)

    def _assemble(
        self,
        session: Session,
        owner: UUID,
        request: Request,
        pages: tuple[SourcePage, ...],
        *,
        original_clock: AcquisitionPublicationClock | None = None,
    ) -> Snapshot:
        page_type = {
            PriceHistoryRequest: PriceHistoryPage,
            FxRatesRequest: FxRatePage,
            BenchmarkSeriesRequest: BenchmarkSeriesPage,
            CorporateActionsRequest: CorporateActionPage,
        }[type(request)]
        if (
            request.continuation is not None
            or not isinstance(pages, tuple)
            or not 1 <= len(pages) <= 100
            or any(type(x) is not page_type for x in pages)
        ):
            raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
        first = pages[0]
        provenance = replace(first.provenance, first_observed_at=self._now())
        if original_clock is not None:
            if (
                type(original_clock) is not AcquisitionPublicationClock
                or type(request) not in (PriceHistoryRequest, FxRatesRequest)
                or original_clock.acquired_at > self._now()
                or original_clock.expires_at <= self._now()
                or any(
                    page.provenance.first_observed_at != original_clock.first_known_at
                    or page.provenance.source_revision != original_clock.content_digest
                    for page in pages
                )
            ):
                raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
            provenance = replace(first.provenance, first_observed_at=original_clock.first_known_at)
        provider = self._owned(session, owner, MarketDataProviderModel, provenance.provider_id)
        if (
            provider.configuration_state != "configured"
            or provider.adapter_version != provenance.adapter_version
            or provider.synthetic != provenance.synthetic
        ):
            raise error(app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE)
        required_capability = {
            PriceHistoryRequest: SourceCapability.PRICE_HISTORY,
            FxRatesRequest: SourceCapability.FX_RATES,
            BenchmarkSeriesRequest: SourceCapability.BENCHMARK_SERIES,
            CorporateActionsRequest: SourceCapability.CORPORATE_ACTIONS,
        }[type(request)]
        if required_capability.value not in provider.capabilities:
            raise error(app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE)
        if (
            isinstance(request, (PriceHistoryRequest, BenchmarkSeriesRequest))
            and request.series.basis.value not in provider.supported_price_bases
        ):
            raise error(app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE)
        license = self._permit(session, owner, UUID(provenance.license_version_id), SourceUse.STORE)
        if license.provider_id != str(provider.id):
            raise error(app.SourceServiceErrorCode.NOT_FOUND)
        if isinstance(request, FxRatesRequest):
            if (
                request.provider_id != provenance.provider_id
                or request.license_version_id != provenance.license_version_id
            ):
                raise error(app.SourceServiceErrorCode.NOT_FOUND)
        else:
            if self._series(session, owner, UUID(request.series.id)) != request.series:
                raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
        continuations: set[str] = set()
        count = 0
        for i, page in enumerate(pages):
            if (
                page.period != request.period
                or page.coverage != first.coverage
                or replace(page.provenance, first_observed_at=provenance.first_observed_at)
                != provenance
                or (
                    not isinstance(request, FxRatesRequest)
                    and getattr(page, "series", None) != request.series
                )
                or (i == len(pages) - 1) != (page.continuation is None)
            ):
                raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
            if page.continuation is not None:
                if page.continuation in continuations:
                    raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
                continuations.add(page.continuation)
            count += len(page.observations)
            if count > 100000 or len(canonical_json(page).encode()) > 8 * 1024 * 1024:
                raise error(app.SourceServiceErrorCode.RESULT_TOO_LARGE)
            if any(
                x.effective_at > request.source_cutoff_at or x.effective_at > self._now()
                for x in page.observations
            ):
                raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
        if (
            provenance.effective_at > request.source_cutoff_at
            or provenance.effective_at > self._now()
        ):
            raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
        if isinstance(request, FxRatesRequest):
            fx = tuple(x for p in pages if isinstance(p, FxRatePage) for x in p.observations)
            pairs = {(x.base, x.quote) for x in request.pairs}
            if any((x.base, x.quote) not in pairs for x in fx):
                raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
            snapshot: Snapshot = FxSnapshot(
                calendar_id=request.calendar_id,
                calendar_version=request.calendar_version,
                id=str(uuid4()),
                owner_id=str(owner),
                provenance=provenance,
                period=request.period,
                coverage=first.coverage,
                observations=fx,
            )
        elif isinstance(request, PriceHistoryRequest):
            snapshot = PriceSnapshot(
                id=str(uuid4()),
                owner_id=str(owner),
                series=request.series,
                provenance=provenance,
                period=request.period,
                coverage=first.coverage,
                observations=tuple(
                    x for p in pages if isinstance(p, PriceHistoryPage) for x in p.observations
                ),
            )
        elif isinstance(request, BenchmarkSeriesRequest):
            snapshot = BenchmarkSnapshot(
                id=str(uuid4()),
                owner_id=str(owner),
                series=request.series,
                provenance=provenance,
                period=request.period,
                coverage=first.coverage,
                observations=tuple(
                    x for p in pages if isinstance(p, BenchmarkSeriesPage) for x in p.observations
                ),
            )
        else:
            snapshot = CorporateActionSnapshot(
                id=str(uuid4()),
                owner_id=str(owner),
                series=request.series,
                provenance=provenance,
                period=request.period,
                coverage=first.coverage,
                observations=tuple(
                    x for p in pages if isinstance(p, CorporateActionPage) for x in p.observations
                ),
            )
        observations = snapshot.observations
        if (
            sum(x.state is ObservationState.AVAILABLE for x in observations)
            != first.coverage.available_count
        ):
            raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
        if isinstance(snapshot, FxSnapshot):
            from trading212_analytics.source_policy import assess_fx_coverage

            assert isinstance(request, FxRatesRequest)
            calendar_row = session.scalar(
                select(SourceCalendarModel).where(
                    SourceCalendarModel.owner_id == owner,
                    SourceCalendarModel.key == request.calendar_id,
                    SourceCalendarModel.version == request.calendar_version,
                )
            )
            if calendar_row is None:
                raise error(app.SourceServiceErrorCode.NOT_FOUND)
            fx_coverage = assess_fx_coverage(
                self._calendar(session, owner, calendar_row.id),
                request.period,
                snapshot.observations,
                pairs=tuple((x.base, x.quote) for x in request.pairs),
            )
            if fx_coverage != snapshot.coverage:
                raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
        if isinstance(snapshot, (PriceSnapshot, BenchmarkSnapshot)):
            from trading212_analytics.source_policy import assess_source_coverage

            assert snapshot.series is not None
            row = self._owned(session, owner, MarketSourceSeriesModel, snapshot.series.id)
            calendar = self._calendar(session, owner, row.calendar_id)
            coverage = assess_source_coverage(calendar, request.period, snapshot.observations)
            if coverage != snapshot.coverage:
                raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
        return snapshot

    def _load_snapshot(self, session: Session, row: SourceSnapshotFields) -> Snapshot:
        kwargs = SnapshotHeader(
            id=str(row.id),
            owner_id=str(row.owner_id),
            provenance=self._provenance(row),
            period=SourcePeriod(start=row.period_start, end=row.period_end),
            coverage=self._coverage(session, row),
        )
        if isinstance(row, PriceSnapshotModel):
            return PriceSnapshot(
                **kwargs,
                series=self._series(session, row.owner_id, row.series_id),
                observations=tuple(
                    self._price_observation(x)
                    for x in session.scalars(
                        select(PriceObservationModel)
                        .where(PriceObservationModel.snapshot_id == row.id)
                        .order_by(PriceObservationModel.ordinal)
                    )
                ),
            )
        if isinstance(row, FxSnapshotModel):
            calendar = self._calendar(session, row.owner_id, row.calendar_id)
            return FxSnapshot(
                **kwargs,
                calendar_id=calendar.id,
                calendar_version=calendar.version,
                observations=tuple(
                    self._fx_observation(x)
                    for x in session.scalars(
                        select(FxObservationModel)
                        .where(FxObservationModel.snapshot_id == row.id)
                        .order_by(FxObservationModel.ordinal)
                    )
                ),
            )
        if isinstance(row, BenchmarkSnapshotModel):
            assert row.series_id is not None
            return BenchmarkSnapshot(
                **kwargs,
                series=self._series(session, row.owner_id, row.series_id),
                observations=tuple(
                    self._benchmark_observation(x)
                    for x in session.scalars(
                        select(BenchmarkObservationModel)
                        .where(BenchmarkObservationModel.snapshot_id == row.id)
                        .order_by(BenchmarkObservationModel.ordinal)
                    )
                ),
            )
        assert isinstance(row, CorporateActionSnapshotModel)
        from trading212_domain.values import CurrencyCode

        return CorporateActionSnapshot(
            **kwargs,
            series=self._series(session, row.owner_id, row.series_id),
            observations=tuple(
                CorporateActionObservation(
                    source_key=x.source_key,
                    source_revision=x.source_revision,
                    session_date=x.session_date,
                    effective_at=x.effective_at,
                    kind=CorporateActionKind(x.kind),
                    state=ObservationState(x.state),
                    ratio=x.ratio,
                    amount=x.amount,
                    currency=None if x.currency is None else CurrencyCode(x.currency),
                    target_instrument_id=None
                    if x.target_instrument_id is None
                    else str(x.target_instrument_id),
                    correction_source_key=x.correction_source_key,
                )
                for x in session.scalars(
                    select(CorporateActionObservationModel)
                    .where(CorporateActionObservationModel.snapshot_id == row.id)
                    .order_by(CorporateActionObservationModel.ordinal)
                )
            ),
        )

    def _persist_snapshot(
        self,
        session: Session,
        snapshot: Snapshot,
        *,
        original_clock: AcquisitionPublicationClock | None = None,
    ) -> SourceSnapshotFields:
        model = {
            PriceSnapshot: PriceSnapshotModel,
            FxSnapshot: FxSnapshotModel,
            BenchmarkSnapshot: BenchmarkSnapshotModel,
            CorporateActionSnapshot: CorporateActionSnapshotModel,
        }[type(snapshot)]
        p = snapshot.provenance
        license = self._license(session, UUID(snapshot.owner_id), UUID(p.license_version_id))
        assert license.retention_days is not None
        expiry = p.first_observed_at + timedelta(days=license.retention_days)
        if original_clock is not None:
            if (
                type(original_clock) is not AcquisitionPublicationClock
                or type(snapshot) not in (PriceSnapshot, FxSnapshot)
                or p.first_observed_at != original_clock.first_known_at
                or p.source_revision != original_clock.content_digest
                or original_clock.expires_at > expiry
                or original_clock.expires_at <= self._now()
            ):
                raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
            expiry = original_clock.expires_at
        kwargs = dict(
            id=UUID(snapshot.id),
            owner_id=UUID(snapshot.owner_id),
            provider_id=UUID(p.provider_id),
            license_version_id=UUID(p.license_version_id),
            adapter_version=p.adapter_version,
            schema_version=p.schema_version,
            source_revision=p.source_revision,
            revision_order=p.revision_order,
            effective_at=p.effective_at,
            first_observed_at=p.first_observed_at,
            expires_at=expiry,
            synthetic=p.synthetic,
            period_start=snapshot.period.start,
            period_end=snapshot.period.end,
            expected_count=snapshot.coverage.expected_count,
            available_count=snapshot.coverage.available_count,
            quality=snapshot.coverage.quality.value,
            reason=None if snapshot.coverage.reason is None else snapshot.coverage.reason.value,
            economic_digest=digest(
                (
                    snapshot.period,
                    snapshot.coverage,
                    tuple(sorted(snapshot.observations, key=canonical_json)),
                )
            ),
            content_digest=source_snapshot_digest(snapshot),
            created_at=self._now(),
        )
        if isinstance(snapshot, FxSnapshot):
            calendar = session.scalar(
                select(SourceCalendarModel).where(
                    SourceCalendarModel.owner_id == UUID(snapshot.owner_id),
                    SourceCalendarModel.key == snapshot.calendar_id,
                    SourceCalendarModel.version == snapshot.calendar_version,
                )
            )
            if calendar is None:
                raise error(app.SourceServiceErrorCode.NOT_FOUND)
            kwargs["calendar_id"] = calendar.id
        if not isinstance(snapshot, FxSnapshot):
            assert snapshot.series is not None
            kwargs["series_id"] = UUID(snapshot.series.id)
        if isinstance(snapshot, BenchmarkSnapshot):
            kwargs["snapshot_kind"] = "provider_series"
        row = model(**kwargs)
        session.add(row)
        session.flush()
        typed_observations = cast(
            tuple[
                PriceObservation
                | FxObservation
                | BenchmarkObservation
                | CorporateActionObservation,
                ...,
            ],
            snapshot.observations,
        )
        for i, observation in enumerate(typed_observations):
            child: (
                PriceObservationModel
                | FxObservationModel
                | BenchmarkObservationModel
                | CorporateActionObservationModel
            )
            common = dict(
                owner_id=row.owner_id,
                snapshot_id=row.id,
                ordinal=i,
                session_date=observation.session_date,
                effective_at=observation.effective_at,
                state=observation.state.value,
                created_at=self._now(),
            )
            if isinstance(observation, PriceObservation):
                child = PriceObservationModel(
                    **common,
                    value=observation.value,
                    corporate_action_revision=observation.corporate_action_revision,
                )
            elif isinstance(observation, FxObservation):
                child = FxObservationModel(
                    **common,
                    base=observation.base.value,
                    quote=observation.quote.value,
                    rate=observation.rate,
                    batch_key=observation.batch_key,
                )
            elif isinstance(observation, BenchmarkObservation):
                child = BenchmarkObservationModel(**common, level=observation.level)
            else:
                self._canonical_mapping(session, observation.target_instrument_id, None)
                child = CorporateActionObservationModel(
                    **common,
                    source_key=observation.source_key,
                    source_revision=observation.source_revision,
                    kind=observation.kind.value,
                    ratio=observation.ratio,
                    amount=observation.amount,
                    currency=None if observation.currency is None else observation.currency.value,
                    target_instrument_id=None
                    if observation.target_instrument_id is None
                    else UUID(observation.target_instrument_id),
                    correction_source_key=observation.correction_source_key,
                )
            session.add(child)
        for i, gap in enumerate(snapshot.coverage.gaps):
            session.add(
                SourceCoverageGapModel(
                    owner_id=row.owner_id,
                    **{self._snapshot_reference(row): row.id},
                    ordinal=i,
                    session_date=gap.session_date,
                    reason=gap.reason.value,
                    source_key=gap.source_key,
                    created_at=self._now(),
                )
            )
        session.flush()
        return row

    async def _ingest(
        self,
        principal: Principal,
        request: Request,
        pages: tuple[SourcePage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> Snapshot:
        kinds = {
            PriceHistoryRequest: ("price.ingest", PriceSnapshotModel),
            FxRatesRequest: ("fx.ingest", FxSnapshotModel),
            BenchmarkSeriesRequest: ("benchmark.ingest", BenchmarkSnapshotModel),
            CorporateActionsRequest: ("actions.ingest", CorporateActionSnapshotModel),
        }

        def operation(session: Session, owner: UUID) -> Snapshot:
            snapshot = self._assemble(session, owner, request, pages)
            kind, model = kinds[type(request)]
            semantic = source_snapshot_digest(snapshot)
            replay, fingerprint = self._replay(
                session, owner, kind, idempotency_key, (request, semantic)
            )
            if replay is not None:
                replay_row = self._owned(session, owner, model, replay.result_id)
                self._snapshot_permit(session, replay_row, SourceUse.STORE)
                return self._load_snapshot(session, replay_row)
            row = session.scalar(
                select(model).where(model.owner_id == owner, model.content_digest == semantic)
            )
            if row is None:
                row = self._persist_snapshot(session, snapshot)
            else:
                self._snapshot_permit(session, row, SourceUse.STORE)
            session.add(
                SourceRetrievalOccurrenceModel(
                    owner_id=owner,
                    **{self._snapshot_reference(row): row.id},
                    retrieved_at=self._now(),
                    created_at=self._now(),
                )
            )
            session.flush()
            self._record(
                session, principal, kind, idempotency_key, fingerprint, row.id, correlation_id
            )
            return self._load_snapshot(session, row)

        return await self._run(principal, operation, write=True)

    async def ingest_price_history(
        self,
        principal: Principal,
        request: PriceHistoryRequest,
        pages: tuple[PriceHistoryPage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> PriceSnapshot:
        result = await self._ingest(
            principal,
            request,
            pages,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        assert isinstance(result, PriceSnapshot)
        return result

    async def ingest_fx_rates(
        self,
        principal: Principal,
        request: FxRatesRequest,
        pages: tuple[FxRatePage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> FxSnapshot:
        result = await self._ingest(
            principal,
            request,
            pages,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        assert isinstance(result, FxSnapshot)
        return result

    async def ingest_benchmark_series(
        self,
        principal: Principal,
        request: BenchmarkSeriesRequest,
        pages: tuple[BenchmarkSeriesPage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> BenchmarkSnapshot:
        result = await self._ingest(
            principal,
            request,
            pages,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        assert isinstance(result, BenchmarkSnapshot)
        return result

    async def ingest_corporate_actions(
        self,
        principal: Principal,
        request: CorporateActionsRequest,
        pages: tuple[CorporateActionPage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> CorporateActionSnapshot:
        result = await self._ingest(
            principal,
            request,
            pages,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        assert isinstance(result, CorporateActionSnapshot)
        return result

    async def expire_source_snapshots(self, *, limit: int = 100) -> int:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("A bounded source expiry batch is required.")

        def expire() -> int:
            from .source_retention import SourcePurgeBudget
            from .source_retention_service import expire_source_payloads

            with self._sessions() as session, session.begin():
                from .xray_enrichment_retention import expire_enrichment_payloads

                at = self._now()
                budget = SourcePurgeBudget()
                from .aggregation_retention import expire_aggregate_payloads
                from .phase2_retention_runtime import rotation
                from .projection_retention import expire_projection_payloads
                from .research_retention import expire_research_payloads
                from .risk_retention import expire_risk_payloads
                from .scenario_retention import expire_scenario_payloads
                from .scenario_source_retention import expire_scenario_sensitivity_payloads

                completed = 0
                for family in rotation(session, "dispatch", 8, budget):
                    if family == 0:
                        expire_risk_payloads(session, at=at, budget=budget)
                    elif family == 1:
                        expire_scenario_payloads(session, at=at, budget=budget)
                    elif family == 2:
                        expire_projection_payloads(session, at=at, budget=budget)
                    elif family == 3:
                        expire_scenario_sensitivity_payloads(session, at=at, budget=budget)
                    elif family == 4:
                        expire_research_payloads(
                            session,
                            at=at,
                            budget=budget,
                            capability_authority=self._research_capabilities,
                        )
                    elif completed < limit and family == 5:
                        completed += expire_source_payloads(
                            session, at=at, limit=limit - completed, budget=budget
                        )
                    elif completed < limit and family == 6:
                        completed += expire_enrichment_payloads(
                            session, at=at, limit=limit - completed, budget=budget
                        )
                    elif family == 7:
                        expire_aggregate_payloads(session, at=at, budget=budget)
                return completed

        return await asyncio.to_thread(expire)
