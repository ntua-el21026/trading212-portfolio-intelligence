"""Private source projections, authorization, commands and bounded retained collections."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from .research_permissions import ResearchCapabilityAuthority

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import sources as app
from trading212_application.queries import CursorCodec, CursorValidationError
from trading212_application.source_ingestion import SourceProvider, SourceProviderRegistration
from trading212_application.source_providers import SourceCapability
from trading212_application.targets import validate_target_idempotency_key
from trading212_domain import CurrencyCode, QualityState, require_utc
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import (
    BenchmarkObservation,
    FxObservation,
    LicensePermission,
    MarketSession,
    ObservationState,
    PriceBasis,
    PriceObservation,
    RetrievalOccurrence,
    SourceCalendar,
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
from trading212_security.principals import Authorizer, Principal, Scope

from .collection_snapshots import (
    CollectionSnapshot,
    CollectionSnapshotDefinition,
    CollectionSnapshotPage,
    CollectionSnapshotStore,
)
from .models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CollectionQuerySnapshotMemberModel,
    CollectionQuerySnapshotModel,
)
from .source_models import (
    BenchmarkObservationModel,
    FxObservationModel,
    MarketDataProviderModel,
    MarketSourceSeriesModel,
    PriceObservationModel,
    ProviderLicenseVersionModel,
    SourceAuditEventModel,
    SourceCalendarModel,
    SourceCalendarSessionModel,
    SourceCollectionBindingModel,
    SourceCommandIdentityModel,
    SourceCommandVersionModel,
    SourceCoverageGapModel,
    SourceExpiryEventModel,
    SourceOwned,
    SourceRetentionWorkModel,
    SourceRetrievalOccurrenceModel,
    SourceSnapshotFields,
)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def license_view(row: ProviderLicenseVersionModel) -> SourceLicense:
    """Canonical immutable license fields shared by capture and access checks."""
    return SourceLicense(
        id=str(row.id),
        provider_id=str(row.provider_id),
        version=row.version,
        effective_at=row.effective_at,
        store=LicensePermission(row.store_permission),
        display=LicensePermission(row.display_permission),
        report=LicensePermission(row.report_permission),
        export=LicensePermission(row.export_permission),
        retention_days=row.retention_days,
        attribution=row.attribution,
        evidence_key=row.evidence_key,
    )


def error(code: app.SourceServiceErrorCode) -> app.SourceServiceError:
    return app.SourceServiceError(
        code,
        {
            app.SourceServiceErrorCode.NOT_FOUND: "The requested source was not found.",
            app.SourceServiceErrorCode.ACCESS_DENIED: "Source use is not permitted.",
            app.SourceServiceErrorCode.IDEMPOTENCY_KEY_REUSED: "Idempotency request mismatch.",
            app.SourceServiceErrorCode.REVISION_REQUIRED: "A revision is required.",
            app.SourceServiceErrorCode.REVISION_MISMATCH: "The revision does not match.",
            app.SourceServiceErrorCode.SOURCE_REVISION_CONFLICT: "Source revision conflict.",
            app.SourceServiceErrorCode.RESULT_TOO_LARGE: "Source limit exceeded.",
        }.get(code, "The source request cannot be completed."),
    )


class SourceStore:
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        cursor_ttl_seconds: int = 3600,
        max_active_collection_snapshots_per_owner: int = 64,
        max_active_collection_members_per_owner: int = 250_000,
        required_copy_use: SourceUse | None = None,
        research_capability_authority: ResearchCapabilityAuthority | None = None,
    ) -> None:
        if required_copy_use is not None and (
            not isinstance(required_copy_use, SourceUse)
            or required_copy_use
            not in {
                SourceUse.REPORT,
                SourceUse.EXPORT,
            }
        ):
            raise ValueError("Only fixed report/export copy uses are supported.")
        self._required_copy_use = required_copy_use
        self._research_capabilities = research_capability_authority
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._authorizer = Authorizer()
        self._cursors = CursorCodec(
            cursor_signing_key, clock=self._clock, ttl_seconds=cursor_ttl_seconds
        )
        self._ttl = cursor_ttl_seconds
        self._snapshot_quota = max_active_collection_snapshots_per_owner
        self._member_quota = max_active_collection_members_per_owner

    def _now(self) -> datetime:
        return require_utc(self._clock())

    async def _run[T](
        self, principal: Principal, operation: Callable[[Session, UUID], T], *, write: bool = False
    ) -> T:
        self._authorizer.require_scope(principal, Scope.ANALYTICS_READ, now=self._now())
        if write:
            self._authorizer.require_scope(principal, Scope.TARGETS_WRITE, now=self._now())
        owner = UUID(principal.owner_id)

        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                        {"key": f"sources:{owner}"},
                    )
                    return operation(session, owner)
            except IntegrityError:
                rejection = app.SourceServiceErrorCode.VALIDATION_FAILED
            except SQLAlchemyError:
                rejection = app.SourceServiceErrorCode.PROVIDER_UNAVAILABLE
            raise error(rejection)

        return await asyncio.to_thread(execute)

    def _account(self, session: Session, principal: Principal, account: str | None) -> UUID | None:
        if account is None:
            return None
        self._authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=self._now())
        identifier = UUID(account)
        owner = session.scalar(
            select(BrokerConnectionModel.owner_id)
            .join(BrokerAccountModel)
            .where(BrokerAccountModel.id == identifier)
        )
        if owner != UUID(principal.owner_id):
            raise error(app.SourceServiceErrorCode.NOT_FOUND)
        return identifier

    def _owned[T: SourceOwned](
        self, session: Session, owner: UUID, model: type[T], identifier: str | UUID
    ) -> T:
        row = session.scalar(
            select(model).where(model.owner_id == owner, model.id == UUID(str(identifier)))
        )
        if row is None:
            raise error(app.SourceServiceErrorCode.NOT_FOUND)
        return row

    def _license(self, session: Session, owner: UUID, identifier: UUID) -> SourceLicense:
        row = self._owned(session, owner, ProviderLicenseVersionModel, identifier)
        return license_view(row)

    def _current_license(
        self, session: Session, owner: UUID, provider: UUID
    ) -> SourceLicense | None:
        row = session.scalar(
            select(ProviderLicenseVersionModel)
            .where(
                ProviderLicenseVersionModel.owner_id == owner,
                ProviderLicenseVersionModel.provider_id == provider,
                ProviderLicenseVersionModel.effective_at <= self._now(),
            )
            .order_by(
                ProviderLicenseVersionModel.effective_at.desc(),
                ProviderLicenseVersionModel.version_number.desc(),
                ProviderLicenseVersionModel.id.desc(),
            )
            .limit(1)
        )
        return None if row is None else self._license(session, owner, row.id)

    def _permit(
        self, session: Session, owner: UUID, license_id: UUID, use: SourceUse
    ) -> SourceLicense:
        license = self._license(session, owner, license_id)
        current = self._current_license(session, owner, UUID(license.provider_id))
        # A report uses the same canonical readers, but display permission alone
        # cannot authorize copying licensed values into a private artifact.
        uses = (
            (use,)
            if self._required_copy_use is None
            else (use, SourceUse.DISPLAY, SourceUse.STORE, self._required_copy_use)
        )
        if (
            any(not license.permits(item) for item in uses)
            or license.effective_at > self._now()
            or current is None
            or any(not current.permits(item) for item in uses)
        ):
            raise error(app.SourceServiceErrorCode.ACCESS_DENIED)
        return license

    def _freshness(self, session: Session, row: SourceSnapshotFields) -> app.SourceFreshnessView:
        provider = self._owned(session, row.owner_id, MarketDataProviderModel, row.provider_id)
        if provider.freshness_policy_version is None or provider.max_age_seconds is None:
            return app.SourceFreshnessView()
        state = (
            app.SourceFreshnessState.STALE
            if self._now() >= row.effective_at + timedelta(seconds=provider.max_age_seconds)
            else app.SourceFreshnessState.FRESH
        )
        return app.SourceFreshnessView(
            state=state,
            policy_version=provider.freshness_policy_version,
            reference_at=row.effective_at,
            max_age_seconds=provider.max_age_seconds,
        )

    def _snapshot_permit(
        self, session: Session, row: SourceSnapshotFields, use: SourceUse = SourceUse.DISPLAY
    ) -> SourceLicense:
        license = self._permit(session, row.owner_id, row.license_version_id, use)
        if row.adapter_version == "premium_fixed_get_v1":
            if (
                session.scalar(
                    select(SourceRetentionWorkModel.id)
                    .where(
                        SourceRetentionWorkModel.owner_id == row.owner_id,
                        getattr(SourceRetentionWorkModel, self._snapshot_reference(row)) == row.id,
                    )
                    .limit(1)
                )
                is not None
            ):
                raise error(app.SourceServiceErrorCode.ACCESS_DENIED)
            kind = {"price_snapshots": "price", "fx_snapshots": "fx"}.get(str(row.__tablename__))
            if (
                kind is None
                or session.scalar(
                    text("SELECT acquisition_source_restricted(:owner,:kind,:source,:at,:use)"),
                    {
                        "owner": row.owner_id,
                        "kind": kind,
                        "source": row.id,
                        "at": self._now(),
                        "use": (self._required_copy_use or use).value,
                    },
                )
                is not False
            ):
                raise error(app.SourceServiceErrorCode.ACCESS_DENIED)
        if row.expires_at <= self._now() or session.scalar(
            select(SourceExpiryEventModel.id)
            .where(getattr(SourceExpiryEventModel, self._snapshot_reference(row)) == row.id)
            .limit(1)
        ):
            raise error(app.SourceServiceErrorCode.ACCESS_DENIED)
        return license

    @staticmethod
    def _snapshot_reference(row: SourceSnapshotFields) -> str:
        return str(row.__tablename__).removesuffix("s") + "_id"

    def _calendar(self, session: Session, owner: UUID, identifier: UUID) -> SourceCalendar:
        row = self._owned(session, owner, SourceCalendarModel, identifier)
        sessions = tuple(
            MarketSession(session_date=x.session_date, close_at=x.close_at)
            for x in session.scalars(
                select(SourceCalendarSessionModel)
                .where(SourceCalendarSessionModel.calendar_id == row.id)
                .order_by(SourceCalendarSessionModel.session_date)
            )
        )
        return SourceCalendar(
            id=row.key,
            version=row.version,
            timezone=row.timezone,
            period=SourcePeriod(start=row.period_start, end=row.period_end),
            sessions=sessions,
        )

    def _series(self, session: Session, owner: UUID, identifier: UUID) -> SourceSeries:
        row = self._owned(session, owner, MarketSourceSeriesModel, identifier)
        calendar = self._owned(session, owner, SourceCalendarModel, row.calendar_id)
        return SourceSeries(
            id=str(row.id),
            owner_id=str(owner),
            provider_id=str(row.provider_id),
            license_version_id=str(row.license_version_id),
            kind=SourceSeriesKind(row.kind),
            provider_key=row.provider_key,
            mapping_version=row.mapping_version,
            basis=PriceBasis(row.basis),
            currency=CurrencyCode(row.currency),
            calendar_id=calendar.key,
            calendar_version=calendar.version,
            mapping_id=None if row.mapping_id is None else str(row.mapping_id),
            instrument_id=None if row.instrument_id is None else str(row.instrument_id),
            listing_id=None if row.listing_id is None else str(row.listing_id),
        )

    def _series_view(self, session: Session, owner: UUID, identifier: UUID) -> app.SourceSeriesView:
        series = self._series(session, owner, identifier)
        return app.SourceSeriesView(
            id=series.id,
            provider_id=series.provider_id,
            license_version_id=series.license_version_id,
            kind=series.kind,
            provider_key=series.provider_key,
            mapping_version=series.mapping_version,
            basis=series.basis,
            currency=series.currency,
            calendar_id=series.calendar_id,
            calendar_version=series.calendar_version,
            mapping_id=series.mapping_id,
            instrument_id=series.instrument_id,
            listing_id=series.listing_id,
        )

    @staticmethod
    def _provenance(row: SourceSnapshotFields) -> SourceProvenance:
        return SourceProvenance(
            provider_id=str(row.provider_id),
            license_version_id=str(row.license_version_id),
            adapter_version=row.adapter_version,
            schema_version=row.schema_version,
            source_revision=row.source_revision,
            revision_order=row.revision_order,
            effective_at=row.effective_at,
            first_observed_at=row.first_observed_at,
            synthetic=row.synthetic,
        )

    def _coverage(self, session: Session, row: SourceSnapshotFields) -> SourceCoverage:
        gaps = tuple(
            SourceGap(
                session_date=x.session_date, reason=SourceReason(x.reason), source_key=x.source_key
            )
            for x in session.scalars(
                select(SourceCoverageGapModel)
                .where(getattr(SourceCoverageGapModel, self._snapshot_reference(row)) == row.id)
                .order_by(SourceCoverageGapModel.ordinal)
            )
        )
        return SourceCoverage(
            expected_count=row.expected_count,
            available_count=row.available_count,
            gaps=gaps,
            quality=QualityState(row.quality),
            reason=None if row.reason is None else SourceReason(row.reason),
        )

    def _retrieval(
        self,
        session: Session,
        row: SourceSnapshotFields,
        *,
        identifier: UUID | None = None,
        cutoff: datetime | None = None,
    ) -> RetrievalOccurrence | None:
        query = select(SourceRetrievalOccurrenceModel).where(
            getattr(SourceRetrievalOccurrenceModel, self._snapshot_reference(row)) == row.id
        )
        if identifier is not None:
            query = query.where(SourceRetrievalOccurrenceModel.id == identifier)
        if cutoff is not None:
            query = query.where(SourceRetrievalOccurrenceModel.retrieved_at <= cutoff)
        occurrence = session.scalar(
            query.order_by(
                SourceRetrievalOccurrenceModel.retrieved_at.desc(),
                SourceRetrievalOccurrenceModel.id.desc(),
            ).limit(1)
        )
        return (
            None
            if occurrence is None
            else RetrievalOccurrence(
                id=str(occurrence.id), snapshot_id=str(row.id), retrieved_at=occurrence.retrieved_at
            )
        )

    @staticmethod
    def _price_observation(row: PriceObservationModel) -> PriceObservation:
        return PriceObservation(
            session_date=row.session_date,
            effective_at=row.effective_at,
            value=row.value,
            state=ObservationState(row.state),
            corporate_action_revision=row.corporate_action_revision,
        )

    @staticmethod
    def _fx_observation(row: FxObservationModel) -> FxObservation:
        return FxObservation(
            session_date=row.session_date,
            effective_at=row.effective_at,
            base=CurrencyCode(row.base),
            quote=CurrencyCode(row.quote),
            rate=row.rate,
            batch_key=row.batch_key,
            state=ObservationState(row.state),
        )

    @staticmethod
    def _benchmark_observation(row: BenchmarkObservationModel) -> BenchmarkObservation:
        return BenchmarkObservation(
            session_date=row.session_date,
            effective_at=row.effective_at,
            level=row.level,
            state=ObservationState(row.state),
        )

    @staticmethod
    def _provider_view(row: MarketDataProviderModel) -> SourceProvider:
        return SourceProvider(
            registration=SourceProviderRegistration(
                id=str(row.id),
                key=row.key,
                name=row.name,
                adapter_version=row.adapter_version,
                configuration_state=app.ProviderConfigurationState(row.configuration_state),
                synthetic=row.synthetic,
                freshness_policy_version=row.freshness_policy_version,
                max_age_seconds=row.max_age_seconds,
                capabilities=tuple(SourceCapability(x) for x in row.capabilities),
                supported_price_bases=tuple(PriceBasis(x) for x in row.supported_price_bases),
            ),
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _replay(
        self, session: Session, owner: UUID, kind: str, key: str, payload: object
    ) -> tuple[SourceCommandIdentityModel | None, str]:
        validate_target_idempotency_key(key)
        fingerprint = digest(payload)
        row = session.scalar(
            select(SourceCommandIdentityModel).where(
                SourceCommandIdentityModel.owner_id == owner,
                SourceCommandIdentityModel.idempotency_key == key,
            )
        )
        if row is not None and (row.kind != kind or row.request_digest != fingerprint):
            raise error(app.SourceServiceErrorCode.IDEMPOTENCY_KEY_REUSED)
        return row, fingerprint

    def _record(
        self,
        session: Session,
        principal: Principal,
        kind: str,
        key: str,
        fingerprint: str,
        result_id: UUID,
        correlation: str,
        revision: int | None = None,
        response: app.BenchmarkDefinitionDetailView | None = None,
    ) -> SourceCommandIdentityModel:
        if (
            not isinstance(correlation, str)
            or not 1 <= len(correlation) <= 100
            or "\x00" in correlation
        ):
            raise error(app.SourceServiceErrorCode.VALIDATION_FAILED)
        row = SourceCommandIdentityModel(
            id=uuid4(),
            owner_id=UUID(principal.owner_id),
            kind=kind,
            idempotency_key=key,
            request_digest=fingerprint,
            result_id=result_id,
            result_revision=revision,
            response_total=None if response is None else response.versions.total,
            response_next_cursor=None if response is None else response.versions.next_cursor,
            response_updated_at=None if response is None else response.definition.updated_at,
            response_archived=None
            if response is None
            else response.definition.state is app.BenchmarkDefinitionState.ARCHIVED,
            response_selected_version_id=None
            if response is None or response.selected_version is None
            else UUID(response.selected_version.id),
            actor_principal_id=principal.principal_id,
            correlation_id=correlation,
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        if response is not None:
            session.add_all(
                SourceCommandVersionModel(
                    owner_id=row.owner_id,
                    command_id=row.id,
                    version_id=UUID(x.id),
                    ordinal=i,
                    created_at=self._now(),
                )
                for i, x in enumerate(response.versions.items)
            )
        session.add(
            SourceAuditEventModel(
                owner_id=row.owner_id,
                command_id=row.id,
                actor_principal_id=principal.principal_id,
                correlation_id=correlation,
                kind=kind,
                resource_id=result_id,
                created_at=self._now(),
            )
        )
        session.flush()
        return row

    def _store(self, session: Session) -> CollectionSnapshotStore:
        return CollectionSnapshotStore(
            session,
            self._cursors,
            ttl_seconds=self._ttl,
            max_active_snapshots_per_owner=self._snapshot_quota,
            max_active_members_per_owner=self._member_quota,
        )

    def _page(
        self,
        session: Session,
        definition: CollectionSnapshotDefinition,
        ids: tuple[UUID, ...],
        *,
        cursor: str | None,
        limit: int,
    ) -> CollectionSnapshotPage:
        store = self._store(session)
        if cursor is not None:
            return store.resume(definition, cursor, limit=limit)
        key = digest(
            (
                definition.owner_id,
                definition.broker_account_id,
                definition.resource,
                definition.filter_fingerprint,
                ids,
            )
        )
        retained = session.scalar(
            select(CollectionQuerySnapshotModel)
            .join(
                SourceCollectionBindingModel,
                SourceCollectionBindingModel.collection_snapshot_id
                == CollectionQuerySnapshotModel.id,
            )
            .where(
                SourceCollectionBindingModel.owner_id == definition.owner_id,
                SourceCollectionBindingModel.cache_key == key,
                CollectionQuerySnapshotModel.owner_id == definition.owner_id,
                CollectionQuerySnapshotModel.broker_account_id == definition.broker_account_id,
                CollectionQuerySnapshotModel.resource == definition.resource.value,
                CollectionQuerySnapshotModel.filter_fingerprint == definition.filter_fingerprint,
                CollectionQuerySnapshotModel.expires_at > func.now(),
            )
            .order_by(
                CollectionQuerySnapshotModel.created_at.desc(),
                CollectionQuerySnapshotModel.id.desc(),
            )
            .limit(1)
            .with_for_update(read=True)
        )
        if retained is not None:
            members = tuple(
                session.scalars(
                    select(CollectionQuerySnapshotMemberModel.record_id)
                    .where(CollectionQuerySnapshotMemberModel.snapshot_id == retained.id)
                    .order_by(CollectionQuerySnapshotMemberModel.ordinal)
                    .limit(len(ids) + 1)
                )
            )
            if retained.exact_total != len(ids) or members != ids:
                raise CursorValidationError("The retained source membership is invalid.")
            return store._read_page(
                CollectionSnapshot(
                    retained.id,
                    definition,
                    retained.exact_total,
                    retained.created_at,
                    retained.expires_at,
                ),
                after_ordinal=0,
                limit=limit,
            )
        page = store.materialize(definition, ids, limit=limit)
        session.add(
            SourceCollectionBindingModel(
                owner_id=definition.owner_id, collection_snapshot_id=page.snapshot_id, cache_key=key
            )
        )
        session.flush()
        return page
