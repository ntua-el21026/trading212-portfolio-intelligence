"""Atomically publish supported canonical sources with their original receipt clocks."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.source_providers import (
    FxRatePage,
    FxRatesRequest,
    PriceHistoryPage,
    PriceHistoryRequest,
)
from trading212_domain.research_sources import ResearchEventRevision
from trading212_domain.sources import (
    FxSnapshot,
    PriceSnapshot,
    SourceCalendar,
    SourceSeries,
    SourceUse,
    source_snapshot_digest,
)
from trading212_security.principals import Principal

from .acquisition_authority import resolve_acquisition
from .acquisition_models import (
    ProviderAcquisitionAttemptModel as Attempt,
)
from .acquisition_models import (
    ProviderAcquisitionMarketResultModel as MarketResult,
)
from .acquisition_models import (
    ProviderAcquisitionPublicationModel as Publication,
)
from .acquisition_models import (
    ProviderAcquisitionRequestModel as Request,
)
from .acquisition_records import (
    AcquisitionAttemptReceipt,
    AcquisitionAuthorityBasis,
    AcquisitionCapability,
    AcquisitionPublicationClock,
    AcquisitionSelection,
    AcquisitionStorageDenied,
)
from .acquisition_research_authority import PostgresResearchCapabilityAuthority
from .acquisition_store import PostgresAcquisitionStore, acquisition_lock, attempt_receipt
from .report_authorization import ReportAuthorization
from .research_service import PostgresResearchService
from .source_ingestion import SourceIngestion
from .source_models import FxSnapshotModel, PriceSnapshotModel, SourceSnapshotFields


@dataclass(frozen=True, slots=True)
class AcquisitionMarketMetadata:
    calendar: SourceCalendar
    series: SourceSeries | None


class PostgresAcquisitionPublisher(PostgresAcquisitionStore):
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        principal: Principal,
        cursor_signing_key: bytes,
        enabled: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(sessions=sessions, principal=principal, enabled=enabled, clock=clock)
        self._sources = SourceIngestion(
            sessions=self._sessions, cursor_signing_key=cursor_signing_key, clock=self._clock
        )
        self._research = PostgresResearchService(
            self._sessions,
            cursor_signing_key=cursor_signing_key,
            clock=self._clock,
            capability_authority=PostgresResearchCapabilityAuthority(),
        )

    def _publication_authority(
        self,
        session: Session,
        selection: AcquisitionSelection,
        basis: AcquisitionAuthorityBasis,
        receipt: AcquisitionAttemptReceipt,
        clock: AcquisitionPublicationClock,
    ) -> ReportAuthorization:
        if not self._enabled:
            raise AcquisitionStorageDenied()
        now = self._now()
        auth, current = resolve_acquisition(
            session, self._principal, selection, now=now, pinned=basis
        )
        attempt = session.scalar(
            select(Attempt)
            .where(Attempt.owner_id == auth.owner_id, Attempt.id == receipt.id)
            .with_for_update(read=True)
        )
        request = session.scalar(
            select(Request)
            .where(Request.owner_id == auth.owner_id, Request.id == selection.request_id)
            .with_for_update(read=True)
        )
        current_license = self._sources._current_license(session, auth.owner_id, basis.provider_id)
        if (
            attempt is None
            or request is None
            or attempt_receipt(attempt) != receipt
            or attempt.outcome is not None
            or attempt.finished_at is None
            or request.state != "succeeded"
            or request.principal_id != auth.principal_id
            or receipt.request_id != selection.request_id
            or receipt.request_digest != request.request_digest
            or not receipt.reserved_at
            <= clock.acquired_at
            <= attempt.finished_at
            < receipt.deadline
            or clock.expires_at <= now
            or clock.expires_at > current.expires_at
            or current_license is None
            or current_license.retention_days is None
            or basis.license.retention_days is None
            or clock.expires_at
            > clock.acquired_at
            + timedelta(days=min(30, current_license.retention_days, basis.license.retention_days))
            or (
                request.mapping_version_id,
                request.mapping_digest,
                request.policy_version_id,
                request.policy_digest,
                request.grant_id,
                request.grant_digest,
            )
            != (
                basis.mapping_version_id,
                basis.mapping_digest,
                basis.policy_version_id,
                basis.policy_digest,
                basis.grant_id,
                basis.grant_digest,
            )
        ):
            raise AcquisitionStorageDenied()
        return auth

    async def market_metadata(
        self, selection: AcquisitionSelection, basis: AcquisitionAuthorityBasis
    ) -> AcquisitionMarketMetadata:
        if not self._enabled:
            raise AcquisitionStorageDenied()

        def operation(session: Session) -> AcquisitionMarketMetadata:
            acquisition_lock(session, selection.owner_id, basis.provider_id)
            auth, current = resolve_acquisition(
                session, self._principal, selection, now=self._now(), pinned=basis
            )
            if current.calendar_id is None:
                raise AcquisitionStorageDenied()
            calendar = self._sources._calendar(session, auth.owner_id, current.calendar_id)
            series = (
                None
                if current.source_series_id is None
                else self._sources._series(session, auth.owner_id, current.source_series_id)
            )
            auth.check(session, now=self._now())
            return AcquisitionMarketMetadata(calendar, series)

        return await self._execute(operation)

    def _record_publication(
        self,
        session: Session,
        receipt: AcquisitionAttemptReceipt,
        clock: AcquisitionPublicationClock,
        kind: str,
        source_id: UUID,
        content_digest: str,
    ) -> None:
        existing = session.scalar(
            select(Publication).where(
                Publication.owner_id == receipt.owner_id,
                Publication.source_kind == kind,
                Publication.source_id == source_id,
            )
        )
        if existing is not None:
            if (
                existing.attempt_id,
                existing.content_digest,
                existing.acquisition_digest,
                existing.acquired_at,
                existing.first_known_at,
                existing.expires_at,
            ) != (
                receipt.id,
                content_digest,
                clock.content_digest,
                clock.acquired_at,
                clock.first_known_at,
                clock.expires_at,
            ):
                raise AcquisitionStorageDenied()
            return
        session.add(
            Publication(
                id=uuid4(),
                owner_id=receipt.owner_id,
                attempt_id=receipt.id,
                source_kind=kind,
                source_id=source_id,
                content_digest=content_digest,
                acquisition_digest=clock.content_digest,
                acquired_at=clock.acquired_at,
                first_known_at=clock.first_known_at,
                expires_at=clock.expires_at,
                published_at=self._now(),
                created_at=self._now(),
            )
        )
        session.flush()

    def _record_market_result(
        self,
        session: Session,
        receipt: AcquisitionAttemptReceipt,
        clock: AcquisitionPublicationClock,
        kind: str,
        row: SourceSnapshotFields,
    ) -> None:
        # The original publication alone owns source clocks and grant authority.
        # A newly charged request may only point to it after exact semantic reuse.
        publication = session.scalar(
            select(Publication).where(
                Publication.owner_id == receipt.owner_id,
                Publication.source_kind == kind,
                Publication.source_id == row.id,
            )
        )
        if (
            publication is None
            or publication.content_digest != row.content_digest
            or publication.acquisition_digest != clock.content_digest
        ):
            raise AcquisitionStorageDenied()
        prior = session.scalar(
            select(MarketResult).where(
                MarketResult.owner_id == receipt.owner_id,
                MarketResult.attempt_id == receipt.id,
            )
        )
        if prior is not None:
            if (prior.publication_id, prior.observed_at) != (publication.id, clock.acquired_at):
                raise AcquisitionStorageDenied()
            return
        session.add(
            MarketResult(
                id=uuid4(),
                owner_id=receipt.owner_id,
                attempt_id=receipt.id,
                publication_id=publication.id,
                observed_at=clock.acquired_at,
                created_at=self._now(),
            )
        )
        session.flush()

    async def publish_market(
        self,
        selection: AcquisitionSelection,
        basis: AcquisitionAuthorityBasis,
        receipt: AcquisitionAttemptReceipt,
        clock: AcquisitionPublicationClock,
        request: PriceHistoryRequest | FxRatesRequest,
        pages: tuple[PriceHistoryPage, ...] | tuple[FxRatePage, ...],
    ) -> PriceSnapshot | FxSnapshot:
        def operation(session: Session) -> PriceSnapshot | FxSnapshot:
            acquisition_lock(session, selection.owner_id, basis.provider_id)
            auth = self._publication_authority(session, selection, basis, receipt, clock)
            if (
                type(request) is PriceHistoryRequest
                and selection.capability is not AcquisitionCapability.DAILY_ADJUSTED
            ) or (
                type(request) is FxRatesRequest
                and selection.capability is not AcquisitionCapability.REFERENCE_FX
            ):
                raise AcquisitionStorageDenied()
            if type(request) is PriceHistoryRequest:
                if (
                    str(basis.source_series_id) != request.series.id
                    or request.series.basis.value != "raw_close"
                ):
                    raise AcquisitionStorageDenied()
            elif type(request) is FxRatesRequest:
                if basis.calendar_id is None or any(
                    pair.base.value != "EUR" for pair in request.pairs
                ):
                    raise AcquisitionStorageDenied()
                calendar = self._sources._calendar(session, auth.owner_id, basis.calendar_id)
                if (request.calendar_id, request.calendar_version) != (
                    calendar.id,
                    calendar.version,
                ):
                    raise AcquisitionStorageDenied()
            else:
                raise AcquisitionStorageDenied()
            snapshot = self._sources._assemble(
                session, auth.owner_id, request, pages, original_clock=clock
            )
            if not isinstance(snapshot, (PriceSnapshot, FxSnapshot)):
                raise AcquisitionStorageDenied()
            kind = "price" if isinstance(snapshot, PriceSnapshot) else "fx"
            model = PriceSnapshotModel if kind == "price" else FxSnapshotModel
            semantic = source_snapshot_digest(snapshot)
            prior = session.scalar(
                select(Publication).where(
                    Publication.owner_id == auth.owner_id,
                    Publication.attempt_id == receipt.id,
                    Publication.source_kind == kind,
                )
            )
            row: SourceSnapshotFields
            if prior is not None:
                found = session.scalar(
                    select(model).where(
                        model.owner_id == auth.owner_id, model.id == prior.source_id
                    )
                )
                if found is None or prior.content_digest != semantic:
                    raise AcquisitionStorageDenied()
                row = found
                self._sources._snapshot_permit(session, row, SourceUse.STORE)
            else:
                existing = session.scalar(
                    select(model).where(
                        model.owner_id == auth.owner_id, model.content_digest == semantic
                    )
                )
                if existing is not None:
                    # An identical economic source remains the original retained copy.
                    # Reacquisition cannot renew its knowledge clock or expiry.
                    row = existing
                    self._sources._snapshot_permit(session, row, SourceUse.STORE)
                else:
                    row = self._sources._persist_snapshot(session, snapshot, original_clock=clock)
                    self._record_publication(
                        session, receipt, clock, kind, row.id, row.content_digest
                    )
            self._publication_authority(session, selection, basis, receipt, clock)
            self._sources._snapshot_permit(session, row, SourceUse.STORE)
            self._sources._snapshot_permit(session, row, SourceUse.DISPLAY)
            self._record_market_result(session, receipt, clock, kind, row)
            result = self._sources._load_snapshot(session, row)
            if not isinstance(result, (PriceSnapshot, FxSnapshot)):
                raise AcquisitionStorageDenied()
            self._publication_authority(session, selection, basis, receipt, clock)
            self._sources._snapshot_permit(session, row, SourceUse.STORE)
            self._sources._snapshot_permit(session, row, SourceUse.DISPLAY)
            return result

        return await self._execute(operation)

    async def publish_research(
        self,
        selection: AcquisitionSelection,
        basis: AcquisitionAuthorityBasis,
        receipt: AcquisitionAttemptReceipt,
        clock: AcquisitionPublicationClock,
        events: tuple[ResearchEventRevision, ...],
    ) -> tuple[ResearchEventRevision, ...]:
        if (
            type(events) is not tuple
            or len(events) > 100
            or any(type(x) is not ResearchEventRevision for x in events)
            or selection.capability
            not in {AcquisitionCapability.NEWS_SENTIMENT, AcquisitionCapability.COMPANY_OVERVIEW}
        ):
            raise AcquisitionStorageDenied()

        def operation(session: Session) -> tuple[ResearchEventRevision, ...]:
            acquisition_lock(session, selection.owner_id, basis.provider_id)
            auth = self._publication_authority(session, selection, basis, receipt, clock)
            output = []
            for incoming in events:
                if (
                    incoming.owner_id != auth.owner_id
                    or incoming.entity_id != basis.entity_id
                    or incoming.provider_id != basis.provider_id
                    or len(incoming.citations) != 1
                ):
                    raise AcquisitionStorageDenied()
                citation = incoming.citations[0]
                source = citation.source
                if (
                    source.license != basis.license
                    or source.request_digest != receipt.request_digest
                    or source.observed_at != clock.acquired_at
                    or source.first_known_at != clock.first_known_at
                    or source.retained_at != clock.acquired_at
                    or source.source_cutoff_at != clock.first_known_at
                    or source.expires_at != clock.expires_at
                    or source.adapter_version != "premium_fixed_get_v1"
                ):
                    raise AcquisitionStorageDenied()
                selected = self._research.publish_event(session, auth, incoming)
                self._record_publication(
                    session, receipt, clock, "research", source.version_id, source.content_digest
                )
                output.append(selected)
            self._publication_authority(session, selection, basis, receipt, clock)
            return tuple(output)

        return await self._execute(operation)
