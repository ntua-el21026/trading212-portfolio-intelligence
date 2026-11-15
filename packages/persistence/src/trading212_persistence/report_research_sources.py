"""Exact research report metadata and current REPORT rights before private bytes."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, union
from sqlalchemy.orm import Session, load_only
from trading212_application import reports as app
from trading212_application.research import RESEARCH_READ_SCOPES, ResearchServiceError
from trading212_domain.report_research import (
    ReportResearchBinding,
    ReportResearchNoteBinding,
    ReportResearchSelection,
)
from trading212_domain.report_v3 import ReportCaptureSummaryV3, ReportSelectionV3
from trading212_domain.reports import MAX_REPORT_DATASET_ROWS, ReportSourceKind, ReportSourceUse
from trading212_domain.research import ResearchEventKind
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.sources import SourceUse
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError

from .acquisition_research_authority import PostgresResearchCapabilityAuthority
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_models import ReportInputSnapshotModel, ReportRetentionWorkModel
from .report_research_models import (
    ReportInputResearchDependencyModel,
    ReportInputResearchNoteModel,
    ReportInputResearchSourceModel,
)
from .research_models import (
    ResearchEventCitationModel,
    ResearchEventPayloadModel,
    ResearchEventRevisionModel,
    ResearchItemModel,
    ResearchNoteCitationModel,
    ResearchNotePayloadModel,
    ResearchNoteRevisionModel,
    ResearchOwnerErasureModel,
    ResearchRetentionModel,
    ResearchReviewModel,
    ResearchSourceOriginModel,
    ResearchSourceVersionModel,
)
from .research_permissions import (
    ResearchCapabilityGrant,
    ResearchCapabilityRequest,
    require_research_capabilities,
)
from .source_models import FxSnapshotModel, ProviderLicenseVersionModel
from .source_store import digest as source_digest
from .source_store import license_view
from .xray_run_models import (
    XrayInputDependencyModel,
    XrayInputSnapshotModel,
    XrayRetentionEventModel,
    XrayRunModel,
)


@dataclass(frozen=True)
class ResearchReportSourceAuthority:
    header: ResearchSourceVersionModel
    origin: ResearchSourceOriginModel
    grant: ResearchCapabilityGrant
    pinned_license: ProviderLicenseVersionModel
    current_license: ProviderLicenseVersionModel
    deadline: datetime


@dataclass(frozen=True)
class ResearchReportAuthority:
    item: ResearchItemModel
    event: ResearchEventRevisionModel
    notes: tuple[ResearchNoteRevisionModel, ...]
    review: ResearchReviewModel | None
    sources: tuple[ResearchReportSourceAuthority, ...]
    expires_at: datetime


def _deny() -> AuthorizationError:
    return AuthorizationError("access denied")


def _owner(session: Session, auth: ReportAuthorization, now: datetime) -> ReportAuthorization:
    current = replace(auth, required_scopes=auth.required_scopes | RESEARCH_READ_SCOPES)
    current.check(session, now=now)
    if (
        session.scalar(
            select(ResearchOwnerErasureModel.owner_id).where(
                ResearchOwnerErasureModel.owner_id == auth.owner_id
            )
        )
        is not None
    ):
        raise _deny()
    return current


def _sources(
    session: Session, auth: ReportAuthorization, identifiers: tuple[UUID, ...], now: datetime
) -> tuple[ResearchReportSourceAuthority, ...]:
    from .report_sources import _license

    if not identifiers or len(identifiers) > 4160:
        raise _deny()
    rows = tuple(
        session.execute(
            select(ResearchSourceVersionModel, ResearchSourceOriginModel)
            .join(
                ResearchSourceOriginModel,
                (
                    (ResearchSourceOriginModel.owner_id == ResearchSourceVersionModel.owner_id)
                    & (ResearchSourceOriginModel.id == ResearchSourceVersionModel.origin_id)
                ),
            )
            .where(
                ResearchSourceVersionModel.owner_id == auth.owner_id,
                ResearchSourceVersionModel.id.in_(identifiers),
            )
            .order_by(ResearchSourceVersionModel.id)
            .execution_options(populate_existing=True)
        )
    )
    if len(rows) != len(identifiers):
        raise _deny()
    if (
        session.scalar(
            select(ResearchRetentionModel.id)
            .where(
                ResearchRetentionModel.owner_id == auth.owner_id,
                ResearchRetentionModel.source_version_id.in_(identifiers),
            )
            .limit(1)
        )
        is not None
    ):
        raise _deny()
    requests = tuple(
        ResearchCapabilityRequest(
            source_version_id=header.id,
            owner_id=header.owner_id,
            provider_id=header.provider_id,
            entity_id=header.entity_id,
            capability=ResearchEventKind(header.capability),
            license_version_id=header.license_version_id,
            grant_id=header.capability_grant_id,
            grant_digest=header.capability_grant_digest,
            retained_at=header.retained_at,
            original_retained_at=origin.original_retained_at,
            effective_expires_at=header.effective_expires_at,
        )
        for header, origin in rows
    )
    try:
        grants = require_research_capabilities(
            PostgresResearchCapabilityAuthority(), session, requests=requests, now=now
        )
    except ResearchServiceError:
        raise _deny() from None
    licensed: dict[
        tuple[UUID, UUID], tuple[ProviderLicenseVersionModel, ProviderLicenseVersionModel]
    ] = {}
    result = []
    for (header, origin), grant in zip(rows, grants, strict=True):
        if SourceUse.REPORT not in grant.uses or not header.sealed:
            raise _deny()
        key = (header.provider_id, header.license_version_id)
        if key not in licensed:
            if len(licensed) >= 256:
                raise _deny()
            licensed[key] = _license(
                session,
                owner_id=auth.owner_id,
                provider_id=header.provider_id,
                license_id=header.license_version_id,
                digest=None,
                source_use=ReportSourceUse.REPORT,
                now=now,
            )
        pinned, current = licensed[key]
        if pinned.retention_days is None or current.retention_days is None:
            raise _deny()
        deadline = min(
            header.expires_at,
            header.effective_expires_at,
            origin.expires_at,
            grant.expires_at,
            origin.original_retained_at
            + timedelta(days=min(30, pinned.retention_days, current.retention_days)),
        )
        if (
            now >= deadline
            or header.effective_expires_at > deadline
            or origin.original_retained_at > header.retained_at
            or (origin.entity_id, origin.capability, origin.facts_digest)
            != (header.entity_id, header.capability, header.facts_digest)
        ):
            raise _deny()
        result.append(
            ResearchReportSourceAuthority(header, origin, grant, pinned, current, deadline)
        )
    return tuple(result)


def _xray_report_sources(
    session: Session,
    auth: ReportAuthorization,
    input_id: UUID,
    *,
    now: datetime,
    licensed: dict[
        tuple[UUID, UUID], tuple[ProviderLicenseVersionModel, ProviderLicenseVersionModel]
    ],
) -> datetime | None:
    """Authorize the complete licensed parent inventory before any private copy.

    Read only exact owned dependency keys and scalar physical headers. Reuse the
    report authority for pinned/current STORE/DISPLAY/REPORT uses and acquired FX
    grants; the later canonical X-ray reader still verifies every original pin.
    No financial value or canonical reference is selected by this preflight.
    """
    from .report_sources import _PHYSICAL, _license, _physical_permit_many

    dependency = XrayInputDependencyModel
    deadline = None
    total = 0
    for family in (
        "fx",
        "constituent",
        "classification",
        "entity_evidence",
        "fund_definition",
        "fund_mapping",
    ):
        model, column = _PHYSICAL[family]
        target = getattr(dependency, column)
        extra = (FxSnapshotModel.adapter_version,) if family == "fx" else ()
        rows = session.execute(
            select(model, dependency.provider_id, dependency.license_version_id)
            .select_from(dependency)
            .outerjoin(model, (model.owner_id == dependency.owner_id) & (model.id == target))
            .where(
                dependency.owner_id == auth.owner_id,
                dependency.input_id == input_id,
                target.is_not(None),
            )
            .options(
                load_only(
                    model.id,
                    model.owner_id,
                    model.provider_id,
                    model.license_version_id,
                    model.created_at,
                    model.expires_at,
                    *extra,
                    raiseload=True,
                )
            )
            .distinct()
            .limit(MAX_REPORT_DATASET_ROWS - total + 1)
            .execution_options(populate_existing=True)
        ).all()
        total += len(rows)
        if total > MAX_REPORT_DATASET_ROWS:
            raise _deny()
        identifiers: list[UUID] = []
        for source, provider_id, license_id in rows:
            if source is None or (source.provider_id, source.license_version_id) != (
                provider_id,
                license_id,
            ):
                raise _deny()
            key = (source.provider_id, source.license_version_id)
            if key not in licensed:
                if len(licensed) >= 256:
                    raise _deny()
                licensed[key] = _license(
                    session,
                    owner_id=auth.owner_id,
                    provider_id=source.provider_id,
                    license_id=source.license_version_id,
                    digest=None,
                    source_use=ReportSourceUse.REPORT,
                    now=now,
                )
            pinned, current = licensed[key]
            if (
                pinned.retention_days is None
                or current.retention_days is None
                or source.created_at > now
            ):
                raise _deny()
            original_deadline = min(
                source.expires_at,
                source.created_at
                + timedelta(days=min(30, pinned.retention_days, current.retention_days)),
            )
            # This is the derived report-copy deadline. A licensed physical
            # source may validly outlive it; copying never renews either clock.
            if now >= original_deadline:
                raise _deny()
            identifiers.append(source.id)
            deadline = min(deadline or original_deadline, original_deadline)
        _physical_permit_many(
            session,
            owner_id=auth.owner_id,
            family=family,
            source_ids=tuple(identifiers),
            source_use=ReportSourceUse.REPORT,
            now=now,
        )
    return deadline


def authorize_research_report_metadata(
    session: Session,
    authorization: ReportAuthorization,
    selection: ReportResearchSelection,
    *,
    now: datetime,
) -> ResearchReportAuthority:
    """Read only scalar headers/memberships; never select a private payload column."""
    now = require_utc(now)
    auth = _owner(session, authorization, now)
    item = session.scalar(
        select(ResearchItemModel)
        .where(
            ResearchItemModel.owner_id == auth.owner_id,
            ResearchItemModel.account_id == auth.account_id,
            ResearchItemModel.id == selection.item_id,
        )
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
    event = session.scalar(
        select(ResearchEventRevisionModel)
        .where(
            ResearchEventRevisionModel.owner_id == auth.owner_id,
            ResearchEventRevisionModel.account_id == auth.account_id,
            ResearchEventRevisionModel.id == item.revision_id,
        )
        .execution_options(populate_existing=True)
    )
    if (
        event is None
        or not event.sealed
        or event.content_digest != item.revision_digest
        or event.entity_id != item.entity_id
        or event.visible_at > item.source_cutoff_at
        or item.created_at > now
        or min(item.expires_at, event.expires_at) <= now
    ):
        raise _deny()
    if (
        session.scalar(
            select(ResearchEventPayloadModel.id).where(
                ResearchEventPayloadModel.owner_id == auth.owner_id,
                ResearchEventPayloadModel.revision_id == event.id,
            )
        )
        is None
    ):
        raise _deny()
    xray = session.execute(
        select(
            XrayInputSnapshotModel.id,
            XrayInputSnapshotModel.account_id,
            XrayInputSnapshotModel.snapshot_id,
            XrayInputSnapshotModel.input_digest,
            XrayInputSnapshotModel.sealed_at,
            XrayRunModel.input_id,
            XrayRunModel.content_digest,
            XrayRunModel.sealed_at,
        )
        .join(
            XrayRunModel,
            (XrayRunModel.input_id == XrayInputSnapshotModel.id)
            & (XrayRunModel.owner_id == XrayInputSnapshotModel.owner_id),
        )
        .where(
            XrayInputSnapshotModel.owner_id == auth.owner_id,
            XrayInputSnapshotModel.id == item.xray_input_id,
            XrayRunModel.id == item.xray_run_id,
        )
    ).first()
    if (
        xray is None
        or tuple(xray[:4])
        != (item.xray_input_id, auth.account_id, item.snapshot_id, item.xray_input_digest)
        or xray[4] is None
        or xray[5] != item.xray_input_id
        or xray[6] != item.xray_result_digest
        or xray[7] is None
        or session.scalar(
            select(XrayRetentionEventModel.id)
            .where(
                XrayRetentionEventModel.owner_id == auth.owner_id,
                XrayRetentionEventModel.input_id == item.xray_input_id,
            )
            .limit(1)
        )
        is not None
    ):
        raise _deny()
    notes = tuple(
        session.scalars(
            select(ResearchNoteRevisionModel)
            .where(
                ResearchNoteRevisionModel.owner_id == auth.owner_id,
                ResearchNoteRevisionModel.account_id == auth.account_id,
                ResearchNoteRevisionModel.id.in_(selection.note_revision_ids),
            )
            .order_by(ResearchNoteRevisionModel.id)
        )
    )
    if len(notes) != len(selection.note_revision_ids) or any(
        not note.sealed or note.entity_id != item.entity_id or note.created_at > now
        for note in notes
    ):
        raise _deny()
    if notes and session.scalar(
        select(func.count())
        .select_from(ResearchNotePayloadModel)
        .where(
            ResearchNotePayloadModel.owner_id == auth.owner_id,
            ResearchNotePayloadModel.revision_id.in_(selection.note_revision_ids),
        )
    ) != len(notes):
        raise _deny()
    review = None
    if selection.review_acknowledgment_id is not None:
        review = session.scalar(
            select(ResearchReviewModel).where(
                ResearchReviewModel.owner_id == auth.owner_id,
                ResearchReviewModel.account_id == auth.account_id,
                ResearchReviewModel.id == selection.review_acknowledgment_id,
            )
        )
        if (
            review is None
            or review.event_id != event.event_id
            or review.revision_id != event.id
            or review.revision_digest != event.content_digest
            or review.reviewed_at > now
        ):
            raise _deny()
    source_ids = tuple(
        session.scalars(
            union(
                select(ResearchEventCitationModel.source_version_id).where(
                    ResearchEventCitationModel.owner_id == auth.owner_id,
                    ResearchEventCitationModel.revision_id == event.id,
                ),
                select(ResearchNoteCitationModel.source_version_id).where(
                    ResearchNoteCitationModel.owner_id == auth.owner_id,
                    ResearchNoteCitationModel.revision_id.in_(selection.note_revision_ids),
                ),
            )
            .order_by("source_version_id")
            .limit(4161)
        )
    )
    sources = _sources(session, auth, source_ids, now)
    licensed = {
        (source.header.provider_id, source.header.license_version_id): (
            source.pinned_license,
            source.current_license,
        )
        for source in sources
    }
    xray_deadline = _xray_report_sources(
        session, auth, item.xray_input_id, now=now, licensed=licensed
    )
    _owner(session, auth, now)
    return ResearchReportAuthority(
        item,
        event,
        notes,
        review,
        sources,
        min(
            item.expires_at,
            event.expires_at,
            *(s.deadline for s in sources),
            *(() if xray_deadline is None else (xray_deadline,)),
        ),
    )


def bind_report_research_dependency(
    session: Session,
    authorization: ReportAuthorization,
    capture: ReportInputSnapshotModel,
    selection: ReportSelectionV3,
    summary: ReportCaptureSummaryV3,
    *,
    now: datetime,
) -> datetime:
    selected, binding = selection.premium_run, summary.header.premium_binding
    if not isinstance(selected, ReportResearchSelection) or not isinstance(
        binding, ReportResearchBinding
    ):
        raise _deny()
    authority = authorize_research_report_metadata(session, authorization, selected, now=now)
    item, event = authority.item, authority.event
    expected_notes = tuple(
        ReportResearchNoteBinding(
            note_id=n.note_id, revision_id=n.id, content_digest=n.content_digest
        )
        for n in authority.notes
    )
    if (
        capture.contract_version != 3
        or capture.kind != "report"
        or (
            binding.item_id,
            binding.item_selection_digest,
            binding.owner_id,
            binding.account_id,
            binding.entity_id,
            binding.event_id,
            binding.event_revision_id,
            binding.event_revision_digest,
            binding.source_cutoff_at,
            binding.created_at,
        )
        != (
            item.id,
            item.selection_digest,
            item.owner_id,
            item.account_id,
            item.entity_id,
            event.event_id,
            event.id,
            event.content_digest,
            item.source_cutoff_at,
            item.created_at,
        )
        or binding.note_revisions != expected_notes
        or binding.expires_at > authority.expires_at
        or binding.expires_at <= now
        or research_record_digest(binding.xray_pin) != item.xray_pin_digest
        or (
            binding.xray.run_id,
            binding.xray.input_id,
            binding.xray.input_digest,
            binding.xray.result_digest,
        )
        != (item.xray_run_id, item.xray_input_id, item.xray_input_digest, item.xray_result_digest)
        or ((binding.review_acknowledgment is None) != (authority.review is None))
        or (
            binding.review_acknowledgment is not None
            and authority.review is not None
            and research_record_digest(binding.review_acknowledgment)
            != authority.review.content_digest
        )
    ):
        raise _deny()
    # Closed research references must cover precisely the selected originals.
    expected = {
        (ReportSourceKind.RESEARCH_ITEM, item.id, item.selection_digest, None),
        (ReportSourceKind.RESEARCH_EVENT_REVISION, event.id, event.content_digest, event.event_id),
        *(
            (ReportSourceKind.RESEARCH_NOTE_REVISION, n.id, n.content_digest, n.note_id)
            for n in authority.notes
        ),
        *(
            (
                ReportSourceKind.RESEARCH_SOURCE_VERSION,
                s.header.id,
                s.header.content_digest,
                s.header.source_id,
            )
            for s in authority.sources
        ),
    }
    if authority.review is not None:
        expected.add(
            (
                ReportSourceKind.RESEARCH_REVIEW_ACKNOWLEDGMENT,
                authority.review.id,
                authority.review.content_digest,
                event.id,
            )
        )
    kinds = {kind for kind, *_ in expected}
    # An unselected review/note is rejected too, including an empty selection.
    kinds |= {
        ReportSourceKind.RESEARCH_NOTE_REVISION,
        ReportSourceKind.RESEARCH_REVIEW_ACKNOWLEDGMENT,
    }
    references = summary.proof.source_references
    if {
        (s.kind, s.subject_id, s.content_digest, s.parent_id) for s in references if s.kind in kinds
    } != expected:
        raise _deny()
    headers = {s.header.id: s.header for s in authority.sources}
    if any(
        (s.provider_id, s.license_version_id, s.source_at, s.first_observed_at)
        != (
            headers[s.subject_id].provider_id,
            headers[s.subject_id].license_version_id,
            headers[s.subject_id].source_cutoff_at,
            headers[s.subject_id].first_known_at,
        )
        for s in references
        if s.kind is ReportSourceKind.RESEARCH_SOURCE_VERSION
    ):
        raise _deny()
    root = ReportInputResearchDependencyModel(
        id=uuid4(),
        owner_id=item.owner_id,
        account_id=item.account_id,
        input_id=capture.id,
        created_at=now,
        item_id=item.id,
        item_selection_digest=item.selection_digest,
        entity_id=item.entity_id,
        event_id=event.event_id,
        event_revision_id=event.id,
        event_revision_digest=event.content_digest,
        xray_run_id=item.xray_run_id,
        xray_input_id=item.xray_input_id,
        xray_input_digest=item.xray_input_digest,
        xray_result_digest=item.xray_result_digest,
        xray_pin_digest=item.xray_pin_digest,
        source_cutoff_at=item.source_cutoff_at,
        source_count=len(authority.sources),
        note_count=len(authority.notes),
        review_acknowledgment_id=selected.review_acknowledgment_id,
        expires_at=binding.expires_at,
        copy_pending=True,
        payload_pending=True,
    )
    session.add(root)
    session.flush()
    for source in authority.sources:
        h, o = source.header, source.origin
        session.add(
            ReportInputResearchSourceModel(
                id=uuid4(),
                owner_id=item.owner_id,
                account_id=item.account_id,
                input_id=capture.id,
                created_at=now,
                source_version_id=h.id,
                source_version_digest=h.content_digest,
                origin_id=o.id,
                provider_id=h.provider_id,
                entity_id=h.entity_id,
                capability=h.capability,
                license_version_id=h.license_version_id,
                license_digest=source_digest(license_view(source.pinned_license)),
                capability_grant_id=h.capability_grant_id,
                capability_grant_digest=h.capability_grant_digest,
                original_retained_at=o.original_retained_at,
                original_expires_at=o.expires_at,
                retained_at=h.retained_at,
                effective_expires_at=h.effective_expires_at,
                copy_pending=True,
            )
        )
    for ordinal, note in enumerate(authority.notes):
        session.add(
            ReportInputResearchNoteModel(
                id=uuid4(),
                owner_id=item.owner_id,
                account_id=item.account_id,
                input_id=capture.id,
                created_at=now,
                ordinal=ordinal,
                note_id=note.note_id,
                revision_id=note.id,
                content_digest=note.content_digest,
                copy_pending=True,
            )
        )
    session.flush()
    return min(binding.expires_at, authority.expires_at)


def authorize_report_research_sources(
    session: Session, authorization: ReportAuthorization, *, input_id: UUID, now: datetime
) -> bool:
    """Return false only for an ordinary report; a research dependency must validate."""
    root = session.scalar(
        select(ReportInputResearchDependencyModel).where(
            ReportInputResearchDependencyModel.owner_id == authorization.owner_id,
            ReportInputResearchDependencyModel.account_id == authorization.account_id,
            ReportInputResearchDependencyModel.input_id == input_id,
        )
    )
    if root is None:
        return False
    if (
        root.expires_at <= now
        or session.scalar(
            select(ReportRetentionWorkModel.id).where(
                ReportRetentionWorkModel.owner_id == authorization.owner_id,
                ReportRetentionWorkModel.input_id == input_id,
            )
        )
        is not None
    ):
        raise _deny()
    notes = tuple(
        session.scalars(
            select(ReportInputResearchNoteModel)
            .where(
                ReportInputResearchNoteModel.owner_id == authorization.owner_id,
                ReportInputResearchNoteModel.input_id == input_id,
            )
            .order_by(ReportInputResearchNoteModel.ordinal)
            .limit(65)
        )
    )
    if len(notes) != root.note_count:
        raise _deny()
    selected = ReportResearchSelection(
        item_id=root.item_id,
        note_revision_ids=tuple(n.revision_id for n in notes),
        review_acknowledgment_id=root.review_acknowledgment_id,
    )
    authority = authorize_research_report_metadata(session, authorization, selected, now=now)
    item, event = authority.item, authority.event
    if (
        (
            root.item_selection_digest,
            root.entity_id,
            root.event_id,
            root.event_revision_id,
            root.event_revision_digest,
            root.xray_run_id,
            root.xray_input_id,
            root.xray_input_digest,
            root.xray_result_digest,
            root.xray_pin_digest,
            root.source_cutoff_at,
        )
        != (
            item.selection_digest,
            item.entity_id,
            event.event_id,
            event.id,
            event.content_digest,
            item.xray_run_id,
            item.xray_input_id,
            item.xray_input_digest,
            item.xray_result_digest,
            item.xray_pin_digest,
            item.source_cutoff_at,
        )
        or not root.copy_pending
        or not root.payload_pending
        or root.expires_at > authority.expires_at
    ):
        raise _deny()
    if any(
        (
            member.ordinal,
            member.note_id,
            member.revision_id,
            member.content_digest,
            member.copy_pending,
        )
        != (ordinal, note.note_id, note.id, note.content_digest, True)
        for ordinal, (member, note) in enumerate(zip(notes, authority.notes, strict=True))
    ):
        raise _deny()
    members = tuple(
        session.scalars(
            select(ReportInputResearchSourceModel)
            .where(
                ReportInputResearchSourceModel.owner_id == authorization.owner_id,
                ReportInputResearchSourceModel.input_id == input_id,
            )
            .order_by(ReportInputResearchSourceModel.source_version_id)
            .limit(4161)
        )
    )
    if len(members) != root.source_count or len(members) != len(authority.sources):
        raise _deny()
    for member, source in zip(members, authority.sources, strict=True):
        if (
            member.source_version_id,
            member.source_version_digest,
            member.origin_id,
            member.provider_id,
            member.entity_id,
            member.capability,
            member.copy_pending,
            member.capability_grant_id,
            member.capability_grant_digest,
            member.license_version_id,
            member.license_digest,
            member.original_retained_at,
            member.original_expires_at,
            member.retained_at,
            member.effective_expires_at,
        ) != (
            source.header.id,
            source.header.content_digest,
            source.origin.id,
            source.header.provider_id,
            source.header.entity_id,
            source.header.capability,
            True,
            source.header.capability_grant_id,
            source.header.capability_grant_digest,
            source.header.license_version_id,
            source_digest(license_view(source.pinned_license)),
            source.origin.original_retained_at,
            source.origin.expires_at,
            source.header.retained_at,
            source.header.effective_expires_at,
        ):
            raise _deny()
    return True
