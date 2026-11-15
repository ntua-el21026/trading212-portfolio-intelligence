"""Scalar source authorization before any retained report payload is decoded."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from sqlalchemy import Boolean, case, false, func, select, text
from sqlalchemy.orm import InstrumentedAttribute, Session
from trading212_domain.report_v4 import ReportProofV4
from trading212_domain.reports import (
    MAX_REPORT_DATASET_ROWS,
    ReportProof,
    ReportSourceKind,
    ReportSourceUse,
)
from trading212_domain.sources import LicensePermission
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError

from . import source_models as sm
from . import xray_catalog_models as xm
from .report_models import (
    ReportInputDependencyModel,
    ReportInputLicenseModel,
    ReportInputSnapshotModel,
)
from .source_store import digest as source_digest
from .source_store import license_view
from .xray_lifecycle_models import EnrichmentExpiryEventModel, EnrichmentRetentionWorkModel

if TYPE_CHECKING:
    from .report_authorization import ReportAuthorization

type PhysicalSource = sm.SourceSnapshotFields | xm.XrayEvidenceFields

# Closed source families only. No caller supplies a SQL name, URL or provider path.
_PHYSICAL: dict[str, tuple[type[PhysicalSource], str]] = {
    "price": (sm.PriceSnapshotModel, "price_snapshot_id"),
    "fx": (sm.FxSnapshotModel, "fx_snapshot_id"),
    "benchmark": (sm.BenchmarkSnapshotModel, "benchmark_snapshot_id"),
    "corporate_action": (sm.CorporateActionSnapshotModel, "corporate_action_snapshot_id"),
    "classification": (xm.ClassificationSnapshotModel, "classification_snapshot_id"),
    "constituent": (xm.ConstituentSnapshotModel, "constituent_snapshot_id"),
    "entity_evidence": (xm.EntityEvidenceVersionModel, "entity_evidence_version_id"),
    "fund_definition": (xm.FundDefinitionModel, "fund_definition_id"),
    "fund_mapping": (xm.FundSourceMappingModel, "fund_mapping_id"),
}
_KINDS = {
    ReportSourceKind.PRICE_SNAPSHOT: ("price",),
    ReportSourceKind.FX_SNAPSHOT: ("fx",),
    ReportSourceKind.BENCHMARK: ("benchmark",),
    ReportSourceKind.CORPORATE_ACTION: ("corporate_action",),
    ReportSourceKind.CLASSIFICATION_SNAPSHOT: ("classification",),
    ReportSourceKind.CONSTITUENT_SNAPSHOT: ("constituent",),
    ReportSourceKind.ENTITY_EVIDENCE_VERSION: ("entity_evidence",),
    ReportSourceKind.FUND_DEFINITION: ("fund_definition",),
    ReportSourceKind.FUND_MAPPING: ("fund_mapping",),
}

type ChildColumns = tuple[
    InstrumentedAttribute[UUID],
    InstrumentedAttribute[UUID],
    InstrumentedAttribute[UUID] | InstrumentedAttribute[UUID | None],
    str,
]
_CHILDREN: dict[ReportSourceKind, ChildColumns] = {
    ReportSourceKind.PRICE_OBSERVATION: (
        sm.PriceObservationModel.id,
        sm.PriceObservationModel.owner_id,
        sm.PriceObservationModel.snapshot_id,
        "price",
    ),
    ReportSourceKind.FX_OBSERVATION: (
        sm.FxObservationModel.id,
        sm.FxObservationModel.owner_id,
        sm.FxObservationModel.snapshot_id,
        "fx",
    ),
    ReportSourceKind.FX_COVERAGE_GAP: (
        sm.SourceCoverageGapModel.id,
        sm.SourceCoverageGapModel.owner_id,
        sm.SourceCoverageGapModel.fx_snapshot_id,
        "fx",
    ),
    ReportSourceKind.ENTITY_EVIDENCE_REFERENCE: (
        xm.EntityEvidenceReferenceModel.id,
        xm.EntityEvidenceReferenceModel.owner_id,
        xm.EntityEvidenceReferenceModel.evidence_version_id,
        "entity_evidence",
    ),
    ReportSourceKind.RELATIONSHIP: (
        xm.InstrumentEntityRelationshipModel.id,
        xm.InstrumentEntityRelationshipModel.owner_id,
        xm.InstrumentEntityRelationshipModel.evidence_version_id,
        "entity_evidence",
    ),
    ReportSourceKind.CLASSIFICATION_ASSIGNMENT: (
        xm.ClassificationAssignmentModel.id,
        xm.ClassificationAssignmentModel.owner_id,
        xm.ClassificationAssignmentModel.snapshot_id,
        "classification",
    ),
    ReportSourceKind.CONSTITUENT_HOLDING: (
        xm.ConstituentHoldingModel.id,
        xm.ConstituentHoldingModel.owner_id,
        xm.ConstituentHoldingModel.snapshot_id,
        "constituent",
    ),
}


def _deny() -> AuthorizationError:
    return AuthorizationError("access denied")


def _lock(session: Session, authorization: ReportAuthorization, now: datetime) -> None:
    authorization.check(session, now=now)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"sources:{authorization.owner_id}"},
    )


def _license(
    session: Session,
    *,
    owner_id: UUID,
    provider_id: UUID,
    license_id: UUID,
    digest: str | None,
    source_use: ReportSourceUse,
    now: datetime,
) -> tuple[sm.ProviderLicenseVersionModel, sm.ProviderLicenseVersionModel]:
    if not isinstance(source_use, ReportSourceUse):
        raise _deny()
    pinned = session.scalar(
        select(sm.ProviderLicenseVersionModel)
        .where(
            sm.ProviderLicenseVersionModel.id == license_id,
            sm.ProviderLicenseVersionModel.owner_id == owner_id,
            sm.ProviderLicenseVersionModel.provider_id == provider_id,
        )
        .execution_options(populate_existing=True)
    )
    current = session.scalar(
        select(sm.ProviderLicenseVersionModel)
        .where(
            sm.ProviderLicenseVersionModel.owner_id == owner_id,
            sm.ProviderLicenseVersionModel.provider_id == provider_id,
            sm.ProviderLicenseVersionModel.effective_at <= now,
        )
        .order_by(
            sm.ProviderLicenseVersionModel.effective_at.desc(),
            sm.ProviderLicenseVersionModel.version_number.desc(),
            sm.ProviderLicenseVersionModel.id.desc(),
        )
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if pinned is None or current is None or pinned.effective_at > now:
        raise _deny()
    if digest is not None and source_digest(license_view(pinned)) != digest:
        raise _deny()
    for row in (pinned, current):
        requested = (
            row.report_permission if source_use is ReportSourceUse.REPORT else row.export_permission
        )
        if any(
            value != LicensePermission.ALLOWED.value
            for value in (
                row.store_permission,
                row.display_permission,
                requested,
            )
        ):
            raise _deny()
    return pinned, current


def original_report_copy_deadline(
    session: Session,
    authorization: ReportAuthorization,
    *,
    dependencies: tuple[ReportInputDependencyModel, ...],
    now: datetime,
) -> datetime | None:
    """Recheck original physical copy bounds without changing stored source proof."""
    now = require_utc(now)
    _lock(session, authorization, now)
    if len(dependencies) > MAX_REPORT_DATASET_ROWS:
        raise _deny()
    licenses: dict[tuple[UUID, UUID], int] = {}
    deadline = None
    for dependency in dependencies:
        entry = _PHYSICAL.get(dependency.kind)
        if entry is None or dependency.owner_id != authorization.owner_id:
            raise _deny()
        model, column = entry
        header = session.execute(
            select(
                model.id,
                model.provider_id,
                model.license_version_id,
                model.content_digest,
                model.created_at,
                model.expires_at,
            ).where(model.owner_id == authorization.owner_id, model.id == dependency.source_id)
        ).first()
        if (
            header is None
            or (
                header.id,
                header.provider_id,
                header.license_version_id,
                header.content_digest,
                header.expires_at,
            )
            != (
                getattr(dependency, column),
                dependency.provider_id,
                dependency.license_version_id,
                dependency.content_digest,
                dependency.expires_at,
            )
            or header.created_at > now
        ):
            raise _deny()
        key = (header.provider_id, header.license_version_id)
        if key not in licenses:
            if len(licenses) >= 256:
                raise _deny()
            pinned, current = _license(
                session,
                owner_id=authorization.owner_id,
                provider_id=header.provider_id,
                license_id=header.license_version_id,
                digest=None,
                source_use=ReportSourceUse.REPORT,
                now=now,
            )
            pinned_days, current_days = pinned.retention_days, current.retention_days
            if (
                pinned_days is None
                or current_days is None
                or not 1 <= pinned_days <= 36500
                or not 1 <= current_days <= 36500
            ):
                raise _deny()
            licenses[key] = min(30, pinned_days, current_days)
        original_deadline = min(
            header.expires_at, header.created_at + timedelta(days=licenses[key])
        )
        if original_deadline <= now:
            raise _deny()
        deadline = min(deadline or original_deadline, original_deadline)
    return deadline


def _physical_permit(
    session: Session,
    row: PhysicalSource,
    family: str,
    *,
    source_use: ReportSourceUse,
    now: datetime,
) -> None:
    if (
        family in {"price", "fx"}
        and isinstance(row, (sm.PriceSnapshotModel, sm.FxSnapshotModel))
        and row.adapter_version == "premium_fixed_get_v1"
        and session.scalar(
            text("SELECT acquisition_source_restricted(:owner, :kind, :source, :at, :use)"),
            {
                "owner": row.owner_id,
                "kind": family,
                "source": row.id,
                "at": now,
                "use": source_use.value,
            },
        )
        is not False
    ):
        raise _deny()
    if row.expires_at <= now:
        raise _deny()
    reference = _PHYSICAL[family][1]
    events = (
        (sm.SourceExpiryEventModel, sm.SourceRetentionWorkModel)
        if family in {"price", "fx", "benchmark", "corporate_action", "constituent"}
        else (EnrichmentExpiryEventModel, EnrichmentRetentionWorkModel)
    )
    if any(
        session.scalar(
            select(model.id)
            .where(
                model.owner_id == row.owner_id,
                getattr(model, reference) == row.id,
            )
            .limit(1)
        )
        is not None
        for model in events
    ):
        raise _deny()


def _physical_permit_many(
    session: Session,
    *,
    owner_id: UUID,
    family: str,
    source_ids: tuple[UUID, ...],
    source_use: ReportSourceUse,
    now: datetime,
) -> None:
    """Fresh bounded physical metadata gates after each family's license checks.

    The scalar gate remains the authority for other callers. These fixed-table
    windows select only identities, original expiry and restriction flags; no
    permission or result survives this invocation or transaction boundary.
    """
    if (
        type(owner_id) is not UUID
        or type(family) is not str
        or family not in _PHYSICAL
        or not isinstance(source_use, ReportSourceUse)
        or type(source_ids) is not tuple
        or len(source_ids) > MAX_REPORT_DATASET_ROWS
        or any(type(identifier) is not UUID for identifier in source_ids)
        or len(set(source_ids)) != len(source_ids)
    ):
        raise _deny()
    now = require_utc(now)
    model, reference = _PHYSICAL[family]
    events = (
        (sm.SourceExpiryEventModel, sm.SourceRetentionWorkModel)
        if family in {"price", "fx", "benchmark", "corporate_action", "constituent"}
        else (EnrichmentExpiryEventModel, EnrichmentRetentionWorkModel)
    )
    acquisition = (
        case(
            (
                model.adapter_version == "premium_fixed_get_v1",
                func.acquisition_source_restricted(
                    owner_id, family, model.id, now, source_use.value, type_=Boolean
                ),
            ),
            else_=False,
        )
        if family in {"price", "fx"}
        and issubclass(model, (sm.PriceSnapshotModel, sm.FxSnapshotModel))
        else false()
    )
    flags = tuple(
        select(event.id)
        .where(event.owner_id == owner_id, getattr(event, reference) == model.id)
        .correlate(model)
        .exists()
        for event in events
    )
    for offset in range(0, len(source_ids), 512):
        window = source_ids[offset : offset + 512]
        rows = session.execute(
            select(
                model.id,
                model.expires_at,
                flags[0].label("expiry_pending"),
                flags[1].label("retention_pending"),
                acquisition.label("acquisition_restricted"),
            ).where(model.owner_id == owner_id, model.id.in_(window))
        ).all()
        if len(rows) != len(window) or {row.id for row in rows} != set(window):
            raise _deny()
        if any(
            row.expires_at <= now
            or row.expiry_pending is not False
            or row.retention_pending is not False
            or row.acquisition_restricted is not False
            for row in rows
        ):
            raise _deny()


def authorize_report_sources(
    session: Session,
    authorization: ReportAuthorization,
    *,
    input_id: UUID,
    source_use: ReportSourceUse,
    now: datetime,
) -> None:
    """Check current permission/expiry using normalized metadata before BYTEA/JSON."""
    now = require_utc(now)
    _lock(session, authorization, now)
    from .report_premium_sources import authorize_report_premium_sources

    authorize_report_premium_sources(session, authorization, input_id=input_id, now=now)
    licenses = session.scalars(
        select(ReportInputLicenseModel)
        .where(
            ReportInputLicenseModel.owner_id == authorization.owner_id,
            ReportInputLicenseModel.input_id == input_id,
        )
        .order_by(ReportInputLicenseModel.license_version_id)
        .limit(257)
    )
    allowed: set[UUID] = set()
    for reference in licenses:
        if len(allowed) >= 256:
            raise _deny()
        _license(
            session,
            owner_id=authorization.owner_id,
            provider_id=reference.provider_id,
            license_id=reference.license_version_id,
            digest=reference.content_digest,
            source_use=source_use,
            now=now,
        )
        allowed.add(reference.license_version_id)
    dependencies = session.scalars(
        select(ReportInputDependencyModel)
        .where(
            ReportInputDependencyModel.owner_id == authorization.owner_id,
            ReportInputDependencyModel.input_id == input_id,
        )
        .order_by(ReportInputDependencyModel.id)
        .limit(MAX_REPORT_DATASET_ROWS + 1)
    )
    for index, dependency in enumerate(dependencies):
        if index >= MAX_REPORT_DATASET_ROWS or dependency.license_version_id not in allowed:
            raise _deny()
        entry = _PHYSICAL.get(dependency.kind)
        if entry is None:
            raise _deny()
        model, column = entry
        row = cast(
            PhysicalSource | None,
            session.scalar(
                select(model)
                .where(
                    model.id == dependency.source_id,
                    model.owner_id == authorization.owner_id,
                )
                .execution_options(populate_existing=True)
            ),
        )
        if row is None or (
            row.id,
            row.provider_id,
            row.license_version_id,
            row.content_digest,
            row.expires_at,
        ) != (
            getattr(dependency, column),
            dependency.provider_id,
            dependency.license_version_id,
            dependency.content_digest,
            dependency.expires_at,
        ):
            raise _deny()
        _physical_permit(session, row, dependency.kind, source_use=source_use, now=now)


def project_report_dependencies(
    session: Session,
    authorization: ReportAuthorization,
    *,
    input_id: UUID,
    proof: ReportProof | ReportProofV4,
    source_use: ReportSourceUse,
    now: datetime,
) -> tuple[ReportInputDependencyModel, ...]:
    """Bind full canonical source parents; observations never invent physical parents."""
    now = require_utc(now)
    _lock(session, authorization, now)
    if (
        len(proof.source_references) > MAX_REPORT_DATASET_ROWS
        or len(proof.license_references) > 256
    ):
        raise _deny()
    licenses = {reference.version_id: reference for reference in proof.license_references}
    if len(licenses) != len(proof.license_references):
        raise _deny()
    for licensed_version in licenses.values():
        _license(
            session,
            owner_id=authorization.owner_id,
            provider_id=licensed_version.provider_id,
            license_id=licensed_version.version_id,
            digest=licensed_version.license_digest,
            source_use=source_use,
            now=now,
        )
    result: list[ReportInputDependencyModel] = []
    parents: dict[UUID, tuple[str, UUID, UUID]] = {}
    children: list[tuple[UUID, str, UUID, UUID]] = []
    research_kinds = {
        ReportSourceKind.RESEARCH_ITEM,
        ReportSourceKind.RESEARCH_EVENT_REVISION,
        ReportSourceKind.RESEARCH_NOTE_REVISION,
        ReportSourceKind.RESEARCH_REVIEW_ACKNOWLEDGMENT,
        ReportSourceKind.RESEARCH_SOURCE_VERSION,
    }
    if any(reference.kind in research_kinds for reference in proof.source_references) and (
        source_use is not ReportSourceUse.REPORT
        or session.scalar(
            select(ReportInputSnapshotModel.contract_version).where(
                ReportInputSnapshotModel.owner_id == authorization.owner_id,
                ReportInputSnapshotModel.account_id == authorization.account_id,
                ReportInputSnapshotModel.id == input_id,
            )
        )
        != 3
    ):
        raise _deny()
    for reference in sorted(proof.source_references, key=lambda value: value.key):
        if reference.kind in research_kinds:
            # The research binder checks the complete exact selected identity set
            # and current REPORT capabilities before sealing. Its separate scoped
            # normalized memberships also own subsequent reads/physical erasure.
            # Research source versions are not fabricated market snapshots.
            continue
        if reference.license_version_id is None:
            if (
                reference.kind in _CHILDREN
                or reference.kind in _KINDS
                or reference.kind
                in {
                    ReportSourceKind.HISTORICAL_CLASSIFICATION,
                }
            ):
                raise _deny()
            continue
        license = licenses.get(reference.license_version_id)
        if license is None or reference.provider_id != license.provider_id:
            raise _deny()
        candidates: list[tuple[str, PhysicalSource]] = []
        for family in _KINDS.get(reference.kind, ()):
            model, _ = _PHYSICAL[family]
            row = cast(
                PhysicalSource | None,
                session.scalar(
                    select(model).where(
                        model.id == reference.subject_id,
                        model.owner_id == authorization.owner_id,
                    )
                ),
            )
            if row is not None:
                candidates.append((family, row))
        if len(candidates) > 1:
            raise _deny()
        if not candidates:
            if reference.kind in _CHILDREN:
                if reference.parent_id is None:
                    raise _deny()
                identity, owner, parent, family = _CHILDREN[reference.kind]
                actual_parent = session.scalar(
                    select(parent).where(
                        identity == reference.subject_id,
                        owner == authorization.owner_id,
                    )
                )
                if actual_parent is None or actual_parent != reference.parent_id:
                    raise _deny()
                children.append((actual_parent, family, license.provider_id, license.version_id))
            elif reference.kind in _KINDS:
                raise _deny()
            # Non-expiring metadata/evidence is protected by its explicit license
            # row and typed canonical pin; it is not a fabricated snapshot copy.
            continue
        family, row = candidates[0]
        if (row.provider_id, row.license_version_id, row.content_digest) != (
            reference.provider_id,
            reference.license_version_id,
            reference.content_digest,
        ):
            raise _deny()
        _physical_permit(session, row, family, source_use=source_use, now=now)
        if row.id in parents:
            continue
        parents[row.id] = (family, row.provider_id, row.license_version_id)
        result.append(
            ReportInputDependencyModel(
                id=uuid4(),
                owner_id=authorization.owner_id,
                created_at=now,
                input_id=input_id,
                source_key=reference.key,
                kind=family,
                source_id=row.id,
                parent_id=reference.parent_id,
                content_digest=row.content_digest,
                provider_id=row.provider_id,
                license_version_id=row.license_version_id,
                expires_at=row.expires_at,
                **{_PHYSICAL[family][1]: row.id},
            )
        )
    if any(
        parents.get(parent) != (family, provider, license)
        for parent, family, provider, license in children
    ):
        raise _deny()
    return tuple(result)
