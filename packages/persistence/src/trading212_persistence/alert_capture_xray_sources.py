"""Resolve retained X-ray dependencies to their actual normalized source timestamps."""

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from trading212_domain import alerts as d
from trading212_domain.reports import ReportSourceKind
from trading212_domain.xray import XraySourceDependency

from . import xray_catalog_models as cm
from .alert_capture_common import AlertCaptureState, AlertCaptureUnavailable
from .alert_sources import _CHILDREN, _KINDS, _PHYSICAL, PhysicalSource, authorize_alert_physical
from .base import Base
from .models import (
    CalculationRunModel,
    PortfolioSnapshotModel,
    ReconciliationDiscrepancyModel,
    ReconciliationRunModel,
    SnapshotCashModel,
    SnapshotPositionModel,
    SourceRecordModel,
)
from .report_capture_xray import _SOURCE_KINDS


def _missing() -> AlertCaptureUnavailable:
    return AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)


def _get[T: Base](state: AlertCaptureState, model: type[T], identifier: UUID) -> T:
    row = state.session.get(model, identifier)
    if row is None:
        raise _missing()
    return row


def _snapshot(state: AlertCaptureState, identifier: UUID) -> PortfolioSnapshotModel:
    row = _get(state, PortfolioSnapshotModel, identifier)
    if row.broker_account_id != state.version.account_id:
        raise _missing()
    if max(row.valuation_at, row.source_cutoff_at, row.created_at) > state.cutoff:
        raise _missing()
    return row


def _physical_parent(state: AlertCaptureState, row: PhysicalSource) -> UUID | None:
    parent: cm.FundDefinitionModel | cm.FundSourceMappingModel
    if isinstance(row, cm.FundSourceMappingModel):
        parent = _get(state, cm.FundDefinitionModel, row.fund_definition_id)
    elif isinstance(row, cm.ConstituentSnapshotModel):
        parent = _get(state, cm.FundSourceMappingModel, row.fund_mapping_id)
    else:
        return None
    if (
        parent.owner_id != state.version.owner_id
        or max(parent.effective_at, parent.first_observed_at, parent.created_at) > state.cutoff
    ):
        raise _missing()
    return parent.id


def _physical(state: AlertCaptureState, row: PhysicalSource, kind: ReportSourceKind) -> None:
    license = authorize_alert_physical(state.session, state.authorization, row, now=state.now)
    if max(row.effective_at, row.first_observed_at, row.created_at) > state.cutoff:
        raise _missing()
    parent_id = _physical_parent(state, row)
    key = f"{kind.value}.{row.id}"
    existing = state.references.get(key)
    # The pre-decode permission pass has the same header with no catalog parent.
    # Fill only its verified physical relationship before the immutable input seals.
    if existing is not None and existing.parent_id is None and parent_id is not None:
        state.references[key] = replace(existing, parent_id=parent_id)
    state.licenses[license.id] = license
    state.reference(
        kind=kind,
        identifier=row.id,
        parent_id=parent_id,
        digest=row.content_digest,
        effective_at=row.effective_at,
        known_at=max(row.first_observed_at, row.created_at),
        provider_id=row.provider_id,
        license_id=row.license_version_id,
        expires_at=row.expires_at,
    )


def _licensed(
    state: AlertCaptureState, source: XraySourceDependency, kind: ReportSourceKind
) -> bool:
    direct = _KINDS.get(kind)
    child = _CHILDREN.get(kind)
    if direct is None and child is None:
        return False
    identifier = source.reference.record_id if direct else source.reference.parent_record_id
    if identifier is None:
        raise _missing()
    if direct is not None:
        family = direct[0]
    else:
        assert child is not None
        family = child[3]
    model = _PHYSICAL[family][0]
    parent = _get(state, model, identifier)
    if (str(parent.provider_id), parent.license_version_id) != (
        source.provider_id,
        source.license_version_id,
    ):
        raise _missing()
    if source.content_digest != parent.content_digest:
        raise AlertCaptureUnavailable(d.AlertReason.COMPUTATION_FAILED)
    parent_kind = next(key for key, families in _KINDS.items() if family in families)
    _physical(state, parent, parent_kind)
    if direct:
        if source.reference.parent_record_id != _physical_parent(state, parent):
            raise _missing()
        return True
    assert child is not None
    id_column, owner_column, parent_column, _ = child
    child_model = id_column.class_
    # Only closed normalized metadata is read, after the actual parent's permission check.
    effective_column = getattr(child_model, "effective_at", None)
    columns = [parent_column, child_model.created_at]
    if effective_column is not None:
        columns.append(effective_column)
    row = state.session.execute(
        select(*columns).where(
            id_column == source.reference.record_id,
            owner_column == state.version.owner_id,
            parent_column == parent.id,
        )
    ).one_or_none()
    if row is None:
        raise _missing()
    effective_at = parent.effective_at if effective_column is None else row[2]
    state.reference(
        kind=kind,
        identifier=source.reference.record_id,
        parent_id=parent.id,
        digest=source.content_digest,
        effective_at=effective_at,
        known_at=max(row[1], parent.created_at, parent.first_observed_at),
        provider_id=parent.provider_id,
        license_id=parent.license_version_id,
        expires_at=parent.expires_at,
    )
    return True


def _ordinary(
    state: AlertCaptureState, source: XraySourceDependency, kind: ReportSourceKind
) -> tuple[datetime, datetime, UUID | None]:
    identifier = source.reference.record_id
    if kind in {ReportSourceKind.SNAPSHOT_POSITION, ReportSourceKind.SNAPSHOT_CASH}:
        child = (
            _get(state, SnapshotPositionModel, identifier)
            if kind is ReportSourceKind.SNAPSHOT_POSITION
            else _get(state, SnapshotCashModel, identifier)
        )
        if child.snapshot_id != source.snapshot_id:
            raise _missing()
        snapshot = _snapshot(state, child.snapshot_id)
        return snapshot.valuation_at, snapshot.created_at, snapshot.id
    if kind is ReportSourceKind.PORTFOLIO_SNAPSHOT:
        snapshot = _snapshot(state, identifier)
        if snapshot.id != source.snapshot_id:
            raise _missing()
        calculation = _get(state, CalculationRunModel, snapshot.calculation_run_id)
        if calculation.broker_account_id != state.version.account_id:
            raise _missing()
        return (
            snapshot.valuation_at,
            max(snapshot.created_at, calculation.created_at, calculation.calculated_at),
            calculation.id,
        )
    if kind is ReportSourceKind.CALCULATION:
        calculation = _get(state, CalculationRunModel, identifier)
        if calculation.broker_account_id != state.version.account_id:
            raise _missing()
        return (
            calculation.valuation_at,
            max(calculation.created_at, calculation.calculated_at, calculation.source_cutoff_at),
            None,
        )
    if kind is ReportSourceKind.BROKER_SOURCE_RECORD:
        record = _get(state, SourceRecordModel, identifier)
        if record.broker_account_id != state.version.account_id:
            raise _missing()
        return (
            record.source_updated_at or record.observed_at,
            max(record.created_at, record.observed_at),
            record.broker_account_id,
        )
    if kind is ReportSourceKind.RECONCILIATION:
        reconciliation = _get(state, ReconciliationRunModel, identifier)
        if reconciliation.broker_account_id != state.version.account_id:
            raise _missing()
        return reconciliation.as_of, reconciliation.created_at, None
    if kind is ReportSourceKind.RECONCILIATION_DISCREPANCY:
        discrepancy = _get(state, ReconciliationDiscrepancyModel, identifier)
        reconciliation = _get(state, ReconciliationRunModel, discrepancy.reconciliation_run_id)
        if (
            discrepancy.broker_account_id != state.version.account_id
            or reconciliation.broker_account_id != state.version.account_id
        ):
            raise _missing()
        return (
            reconciliation.as_of,
            max(discrepancy.created_at, discrepancy.first_seen_at, reconciliation.created_at),
            reconciliation.id,
        )
    if kind is ReportSourceKind.POLICY:
        policy = _get(state, cm.XrayPolicyVersionModel, identifier)
        if (policy.owner_id, policy.account_id, policy.content_digest) != (
            state.version.owner_id,
            state.version.account_id,
            source.content_digest,
        ):
            raise _missing()
        return policy.effective_at, max(policy.created_at, policy.first_observed_at), None
    raise _missing()


def capture_xray_sources(
    state: AlertCaptureState, sources: tuple[XraySourceDependency, ...], *, snapshot_id: UUID
) -> None:
    for source in sources:
        if (source.owner_id, source.account_id, source.snapshot_id) != (
            state.version.owner_id,
            state.version.account_id,
            snapshot_id,
        ):
            raise _missing()
        kind = _SOURCE_KINDS[source.reference.kind]
        if _licensed(state, source, kind):
            continue
        if source.provider_id is not None or source.license_version_id is not None:
            raise _missing()
        effective_at, known_at, parent_id = _ordinary(state, source, kind)
        if source.reference.parent_record_id != parent_id:
            raise _missing()
        state.reference(
            kind=kind,
            identifier=source.reference.record_id,
            parent_id=parent_id,
            digest=source.content_digest,
            effective_at=effective_at,
            known_at=known_at,
        )
