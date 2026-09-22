"""Private fixed provider fallback composition; no public acquisition endpoint."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import source_fallback as app
from trading212_domain.sources import (
    FxSnapshot,
    PriceBasis,
    PriceSnapshot,
    SourceUse,
    source_snapshot_digest,
)
from trading212_persistence.acquisition_authority import resolve_acquisition
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionAttemptModel as Attempt,
)
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionMarketResultModel as MarketResult,
)
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionPublicationModel as Publication,
)
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionRequestModel as Request,
)
from trading212_persistence.acquisition_records import (
    AcquisitionAuthorityBasis,
    AcquisitionSelection,
    AcquisitionStorageDenied,
)
from trading212_persistence.acquisition_store import acquisition_lock
from trading212_persistence.source_fallback import PostgresCompatibleSourceReader
from trading212_persistence.source_models import FxSnapshotModel, PriceSnapshotModel
from trading212_reference_data.premium_acquisition import acquisition_request_digest
from trading212_reference_data.premium_acquisition_types import (
    AcquireDailyAdjusted,
    AcquireEcbReferenceFx,
    AcquisitionCommand,
    AcquisitionCredentialPort,
    AcquisitionFailure,
)
from trading212_security.principals import Principal

from .premium_acquisition_runtime import PostgresPremiumAcquisitionRuntime, _permit, _selection


class ConfiguredCompatibleSourceAcquisition:
    """At most one matching command using the plan's original immutable request id."""

    def __init__(self, runtime: PostgresPremiumAcquisitionRuntime) -> None:
        self._runtime = runtime

    async def _prepare(
        self, principal: Principal, plan: app.SourceFallbackPlan, command: AcquisitionCommand
    ) -> tuple[AcquisitionSelection, AcquisitionAuthorityBasis]:
        if not plan.enabled or plan.synthetic or plan.acquisition is None:
            raise app.SourceFallbackError(app.SourceFallbackReason.ACQUISITION_UNAVAILABLE)
        store = self._runtime._store
        if principal != store._principal:
            raise app.SourceFallbackError(app.SourceFallbackReason.ACCESS_DENIED)
        selection = _selection(command)
        basis = await store.resolve(selection)
        if basis is None:
            raise app.SourceFallbackError(app.SourceFallbackReason.ACQUISITION_UNAVAILABLE)
        metadata = await store.market_metadata(selection, basis)
        if (
            basis.calendar_id != plan.calendar_id
            or metadata.calendar.version != plan.calendar_version
        ):
            raise app.SourceFallbackError(app.SourceFallbackReason.INCOMPATIBLE_CALENDAR)
        if (
            not metadata.calendar.period.start
            <= plan.period.start
            <= plan.period.end
            <= metadata.calendar.period.end
        ):
            raise app.SourceFallbackError(app.SourceFallbackReason.INCOMPATIBLE_PERIOD)
        if isinstance(plan, app.PriceFallbackPlan):
            if basis.instrument_id != plan.instrument_id:
                raise app.SourceFallbackError(app.SourceFallbackReason.INCOMPATIBLE_SUBJECT)
            if basis.price_currency != plan.currency:
                raise app.SourceFallbackError(app.SourceFallbackReason.INCOMPATIBLE_CURRENCY)
            if (
                plan.basis is not PriceBasis.RAW_CLOSE
                or metadata.series is None
                or metadata.series.basis is not plan.basis
            ):
                raise app.SourceFallbackError(app.SourceFallbackReason.INCOMPATIBLE_BASIS)
        elif any(pair.base.value != "EUR" for pair in plan.pairs):
            raise app.SourceFallbackError(app.SourceFallbackReason.INCOMPATIBLE_PAIRS)
        return selection, basis

    async def _published(
        self,
        command: AcquisitionCommand,
        selection: AcquisitionSelection,
        basis: AcquisitionAuthorityBasis,
        kind: str,
    ) -> app.RetainedSourceCandidate | None:
        store = self._runtime._store
        expected = acquisition_request_digest(command, _permit(basis))

        def operation(session: Session) -> app.RetainedSourceCandidate | None:
            acquisition_lock(session, selection.owner_id, basis.provider_id)
            auth, current = resolve_acquisition(
                session, store._principal, selection, now=store._now(), pinned=basis
            )
            request = session.scalar(
                select(Request).where(
                    Request.id == selection.request_id, Request.owner_id == auth.owner_id
                )
            )
            if request is None:
                return None
            if (
                request.account_id,
                request.principal_id,
                request.mapping_version_id,
                request.mapping_digest,
                request.policy_version_id,
                request.policy_digest,
                request.grant_id,
                request.grant_digest,
                request.request_digest,
            ) != (
                auth.account_id,
                auth.principal_id,
                current.mapping_version_id,
                current.mapping_digest,
                current.policy_version_id,
                current.policy_digest,
                current.grant_id,
                current.grant_digest,
                expected,
            ):
                raise AcquisitionStorageDenied()
            if request.state != "succeeded":
                return None
            values = session.execute(
                select(Publication.source_id, Publication.content_digest)
                .join(
                    MarketResult,
                    (MarketResult.owner_id == Publication.owner_id)
                    & (MarketResult.publication_id == Publication.id),
                )
                .join(
                    Attempt,
                    (Attempt.owner_id == MarketResult.owner_id)
                    & (Attempt.id == MarketResult.attempt_id),
                )
                .where(
                    Publication.owner_id == auth.owner_id,
                    Publication.source_kind == kind,
                    Attempt.request_id == request.id,
                    Attempt.finished_at.is_not(None),
                    Attempt.outcome.is_(None),
                )
                .limit(2)
            ).all()
            if len(values) != 1:
                raise AcquisitionStorageDenied()
            resolve_acquisition(
                session, store._principal, selection, now=store._now(), pinned=basis
            )
            model = PriceSnapshotModel if kind == "price" else FxSnapshotModel
            source = session.scalar(
                select(model).where(model.owner_id == auth.owner_id, model.id == values[0][0])
            )
            if source is None or source.content_digest != values[0][1]:
                raise AcquisitionStorageDenied()
            store._sources._snapshot_permit(session, source, SourceUse.STORE)
            store._sources._snapshot_permit(session, source, SourceUse.DISPLAY)
            auth.check(session, now=store._now())
            # Reuse never replaces the original publication's grant or expiry.
            return app.RetainedSourceCandidate(
                snapshot_id=values[0][0], content_digest=values[0][1]
            )

        return await store._execute(operation)

    async def acquire_price(
        self, principal: Principal, plan: app.PriceFallbackPlan
    ) -> app.RetainedSourceCandidate:
        if type(plan) is not app.PriceFallbackPlan or plan.acquisition is None:
            raise app.SourceFallbackError(app.SourceFallbackReason.ACQUISITION_UNAVAILABLE)
        command = AcquireDailyAdjusted(
            owner_id=plan.owner_id,
            account_id=plan.account_id,
            request_id=plan.acquisition.request_id,
            mapping_version_id=plan.acquisition.mapping_version_id,
            period=plan.period,
        )
        try:
            selection, basis = await self._prepare(principal, plan, command)
            existing = await self._published(command, selection, basis, "price")
            if existing is not None:
                return existing
            batch = await self._runtime.acquisition.acquire_daily_adjusted(command)
            if isinstance(batch, AcquisitionFailure):
                raise app.SourceFallbackError(app.SourceFallbackReason.ACQUISITION_UNAVAILABLE)
            value = await self._runtime.publish(batch)
            if type(value) is not PriceSnapshot:
                raise AcquisitionStorageDenied()
            return app.RetainedSourceCandidate(
                snapshot_id=UUID(value.id), content_digest=source_snapshot_digest(value)
            )
        except AcquisitionStorageDenied:
            raise app.SourceFallbackError(
                app.SourceFallbackReason.ACQUISITION_UNAVAILABLE
            ) from None

    async def acquire_fx(
        self, principal: Principal, plan: app.FxFallbackPlan
    ) -> app.RetainedSourceCandidate:
        if type(plan) is not app.FxFallbackPlan or plan.acquisition is None:
            raise app.SourceFallbackError(app.SourceFallbackReason.ACQUISITION_UNAVAILABLE)
        command = AcquireEcbReferenceFx(
            owner_id=plan.owner_id,
            account_id=plan.account_id,
            request_id=plan.acquisition.request_id,
            mapping_version_id=plan.acquisition.mapping_version_id,
        )
        try:
            selection, basis = await self._prepare(principal, plan, command)
            existing = await self._published(command, selection, basis, "fx")
            if existing is not None:
                return existing
            batch = await self._runtime.acquisition.acquire_ecb_reference_fx(command)
            if isinstance(batch, AcquisitionFailure):
                raise app.SourceFallbackError(app.SourceFallbackReason.ACQUISITION_UNAVAILABLE)
            value = await self._runtime.publish(batch)
            if type(value) is not FxSnapshot:
                raise AcquisitionStorageDenied()
            return app.RetainedSourceCandidate(
                snapshot_id=UUID(value.id), content_digest=source_snapshot_digest(value)
            )
        except AcquisitionStorageDenied:
            raise app.SourceFallbackError(
                app.SourceFallbackReason.ACQUISITION_UNAVAILABLE
            ) from None


def postgres_source_fallback(
    *,
    sessions: sessionmaker[Session],
    principal: Principal,
    cursor_signing_key: bytes,
    enabled: bool = False,
    credentials: AcquisitionCredentialPort | None = None,
    clock: Callable[[], datetime] | None = None,
) -> app.ExplicitSourceFallback:
    reader = PostgresCompatibleSourceReader(
        sessions=sessions, cursor_signing_key=cursor_signing_key, clock=clock
    )
    runtime = PostgresPremiumAcquisitionRuntime(
        sessions=sessions,
        principal=principal,
        cursor_signing_key=cursor_signing_key,
        enabled=enabled,
        credentials=credentials,
        clock=clock,
    )
    return app.ExplicitSourceFallback(
        reader, acquisition=ConfiguredCompatibleSourceAcquisition(runtime)
    )
