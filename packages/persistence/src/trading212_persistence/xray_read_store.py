"""Authorized normalized X-ray projection helpers; no financial calculation here."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import xray as app
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_domain.errors import DomainError
from trading212_domain.xray import XrayDimension
from trading212_domain.xray_codec import XrayComponent, decode_xray_component
from trading212_domain.xray_result import (
    FundComposition,
    XrayDimensionSummary,
    XrayDisplayResidual,
    XrayHeldFund,
    XrayTerminalPath,
)
from trading212_security.principals import Principal

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    _acquire_owner_capacity_lock,
)
from .models import InstrumentModel
from .source_retention import SourcePurgeBudget
from .source_store import digest
from .xray_base import xray_error
from .xray_catalog_models import ConstituentSnapshotModel, EntityEvidenceReferenceModel
from .xray_retention import cleanup_expired_xray_collections
from .xray_run_models import (
    XrayDimensionModel,
    XrayExposurePathModel,
    XrayFundCompositionModel,
    XrayHeldFundModel,
    XrayInputDependencyModel,
    XrayResidualModel,
    XrayRunSourceModel,
)
from .xray_run_store import XrayRunStore
from .xray_store_contract import XrayRunHandle
from .xray_views import held_fund_view


def component[T: XrayComponent](payload: bytes, kind: type[T]) -> T:
    try:
        return decode_xray_component(payload, kind)
    except DomainError:
        raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE) from None


def run_definition(
    owner: UUID,
    account: UUID,
    request: app.XrayRunRequest,
    options: app.Exposures | app.Paths | app.HeldFunds | app.Pairs | app.CommonEntities,
    resource: CollectionSnapshotResource,
) -> CollectionSnapshotDefinition:
    currency = (
        request.currency.reporting_currency.value
        if isinstance(request.currency, app.ExplicitCurrency)
        else "snapshot_currency"
    )
    return CollectionSnapshotDefinition(
        resource=resource,
        owner_id=owner,
        broker_account_id=account,
        filter_fingerprint=digest(
            (request.snapshot_id, request.source_cutoff_at, currency, options)
        ),
    )


class XrayReadStore(XrayRunStore):
    async def _read_xray[T](
        self, principal: Principal, operation: Callable[[Session, UUID], T]
    ) -> T:
        def cleanup(session: Session, owner: UUID) -> None:
            _acquire_owner_capacity_lock(session, owner)
            cleanup_expired_xray_collections(session, owner, SourcePurgeBudget(), at=self._now())

        # A rejected read must not roll back partial physical cleanup. Otherwise
        # an expired collection larger than one budget can occupy a full owner's
        # capacity forever. The read reacquires locks and reauthorizes afterwards.
        await self._xrun(principal, cleanup)
        try:
            return await self._xrun(principal, operation)
        except CollectionSnapshotCapacityError:
            raise xray_error(app.XrayServiceErrorCode.RESULT_TOO_LARGE) from None
        except CursorValidationError:
            raise xray_error(app.XrayServiceErrorCode.VALIDATION_FAILED) from None

    def _xray_account(self, session: Session, principal: Principal, account: str) -> UUID:
        identifier = self._account(session, principal, account)
        if identifier is None:
            raise xray_error(app.XrayServiceErrorCode.NOT_FOUND)
        return identifier

    def _instrument_name(self, session: Session, identifier: UUID) -> str:
        name = session.scalar(
            select(InstrumentModel.canonical_name).where(InstrumentModel.id == identifier)
        )
        if name is None:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        return name

    def _entity_name(
        self, session: Session, owner: UUID, handle: XrayRunHandle, identifier: UUID
    ) -> str:
        # Read only names from evidence actually used by this retained run.
        # Conflicting display labels never become an economic identity decision.
        names = tuple(
            session.scalars(
                select(EntityEvidenceReferenceModel.display_name)
                .join(
                    XrayInputDependencyModel,
                    XrayInputDependencyModel.entity_evidence_version_id
                    == EntityEvidenceReferenceModel.evidence_version_id,
                )
                .join(
                    XrayRunSourceModel,
                    XrayRunSourceModel.dependency_id == XrayInputDependencyModel.id,
                )
                .where(
                    XrayRunSourceModel.run_id == handle.run_id,
                    XrayRunSourceModel.owner_id == owner,
                    XrayInputDependencyModel.input_id == handle.input_id,
                    XrayInputDependencyModel.owner_id == owner,
                    EntityEvidenceReferenceModel.owner_id == owner,
                    EntityEvidenceReferenceModel.entity_id == identifier,
                    EntityEvidenceReferenceModel.kind == "entity",
                    EntityEvidenceReferenceModel.display_name.is_not(None),
                )
                .distinct()
                .limit(2)
            )
        )
        return names[0] if len(names) == 1 and names[0] is not None else f"Entity {identifier}"

    def _dimension(
        self, session: Session, owner: UUID, handle: XrayRunHandle, dimension: XrayDimension
    ) -> XrayDimensionSummary:
        payloads = tuple(
            session.scalars(
                select(XrayDimensionModel.canonical_payload)
                .where(
                    XrayDimensionModel.owner_id == owner,
                    XrayDimensionModel.run_id == handle.run_id,
                )
                .order_by(XrayDimensionModel.ordinal)
                .limit(7)
            )
        )
        if len(payloads) != 6:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        values = tuple(component(payload, XrayDimensionSummary) for payload in payloads)
        if len({value.dimension for value in values}) != 6:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        return next(value for value in values if value.dimension is dimension)

    def _residuals(
        self, session: Session, owner: UUID, run: UUID, consumer: str, *, maximum: int = 8
    ) -> tuple[XrayDisplayResidual, ...]:
        rows = tuple(
            session.scalars(
                select(XrayResidualModel.canonical_payload)
                .where(
                    XrayResidualModel.owner_id == owner,
                    XrayResidualModel.run_id == run,
                    XrayResidualModel.consumer_key == consumer,
                )
                .order_by(XrayResidualModel.ordinal)
                .limit(maximum + 1)
            )
        )
        if len(rows) > maximum:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        values = tuple(component(payload, XrayDisplayResidual) for payload in rows)
        if any(value.consumer_key != consumer for value in values):
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        return values

    def _held_view(
        self, session: Session, owner: UUID, handle: XrayRunHandle, instrument: UUID
    ) -> app.XrayHeldFundView:
        held = session.scalar(
            select(XrayHeldFundModel).where(
                XrayHeldFundModel.owner_id == owner,
                XrayHeldFundModel.run_id == handle.run_id,
                XrayHeldFundModel.instrument_id == instrument,
            )
        )
        row = session.scalar(
            select(XrayFundCompositionModel).where(
                XrayFundCompositionModel.owner_id == owner,
                XrayFundCompositionModel.run_id == handle.run_id,
                XrayFundCompositionModel.instrument_id == instrument,
            )
        )
        if held is None or row is None:
            raise xray_error(app.XrayServiceErrorCode.VALIDATION_FAILED)
        value = component(row.canonical_payload, FundComposition)
        selected = component(held.canonical_payload, XrayHeldFund)
        if value.fund_instrument_id != instrument or selected.instrument_id != instrument:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        path_row = session.scalar(
            select(XrayExposurePathModel)
            .where(
                XrayExposurePathModel.owner_id == owner,
                XrayExposurePathModel.run_id == handle.run_id,
                XrayExposurePathModel.root_key == value.composition_root_key,
            )
            .order_by(XrayExposurePathModel.ordinal)
            .limit(1)
        )
        if path_row is None:
            raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
        path = component(path_row.canonical_payload, XrayTerminalPath)
        candidate = path.fund_edges[0].candidate_id if path.fund_edges else None
        source = (
            None
            if candidate is None
            else self._owned(session, owner, ConstituentSnapshotModel, candidate)
        )
        return held_fund_view(
            value,
            held=selected,
            name=self._instrument_name(session, instrument),
            constituent_snapshot_id=candidate,
            source_at=None if source is None else source.effective_at,
        )
