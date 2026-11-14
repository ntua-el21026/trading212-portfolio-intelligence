"""Exact retained research report capture with REPORT authority before private bytes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from trading212_application import reports as app
from trading212_application import research as research_app
from trading212_application.sources import SourceServiceError
from trading212_application.xray import XrayServiceError
from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.report_research import (
    ReportResearchBinding,
    ReportResearchNoteBinding,
    ReportResearchSelection,
)
from trading212_domain.report_v3 import ReportSelectionV3, ReportXrayRunBinding
from trading212_domain.research import ResearchEventKind
from trading212_domain.research_facts import ResearchXrayPin, copy_research_portfolio_facts
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.sources import SourceLicense, SourceUse
from trading212_domain.xray import XrayReferenceKind
from trading212_domain.xray_result import XrayCalculation

from .acquisition_research_authority import PostgresResearchCapabilityAuthority
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_builder import ReportBuilder
from .report_capture_research import ResearchReportWriter, project_research
from .report_capture_xray import _SOURCE_KINDS, _source_key, _source_parents
from .report_research_sources import ResearchReportAuthority, authorize_research_report_metadata
from .research_item_store import ResearchItemStore
from .research_permissions import require_research_capability
from .research_source_store import ResearchAuthorizedSource, research_error, research_owner_lock
from .research_xray_read import ResearchXrayRead, finish_research_xray, read_research_xray
from .source_store import digest, license_view
from .xray_service import PostgresXrayService


class ResearchReportStore(ResearchItemStore):
    """Reuse the existing typed retained readers with stronger copy permission."""

    _research_xray: PostgresXrayService

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime],
        cursor_signing_key: bytes,
    ) -> None:
        super().__init__(
            sessions=sessions,
            clock=clock,
            cursor_signing_key=cursor_signing_key,
            required_copy_use=SourceUse.REPORT,
            research_capability_authority=PostgresResearchCapabilityAuthority(),
        )
        self._research_xray = PostgresXrayService(
            sessions=sessions,
            clock=clock,
            cursor_signing_key=cursor_signing_key,
            required_copy_use=SourceUse.REPORT,
        )
        # The optimized summary reader has a combined private-read bound. Reports
        # retain their original separate input/result/reference bounds, so keep
        # an unoverridden reader for that size-only compatibility path. Its own
        # metadata calls cannot recurse into this optimized subclass.
        self._original_reader = ResearchItemStore(
            sessions=sessions,
            clock=clock,
            cursor_signing_key=cursor_signing_key,
            required_copy_use=SourceUse.REPORT,
            research_capability_authority=PostgresResearchCapabilityAuthority(),
        )
        self._original_reader._research_xray = self._research_xray
        self._original_runs: set[UUID] = set()
        self._retained_reads: dict[UUID, ResearchXrayRead] = {}

    def retained_xray(
        self, session: Session, auth: ReportAuthorization, run_id: UUID
    ) -> tuple[ResearchXrayPin, XrayCalculation, UUID, datetime | None]:
        self.research_authority(session, auth)
        try:
            basis = read_research_xray(
                session, auth, run_id, now=self._now(), required_copy_use=SourceUse.REPORT
            )
            finish_research_xray(
                session, auth, basis, now=self._now(), required_copy_use=SourceUse.REPORT
            )
        except research_app.ResearchServiceError as error:
            if error.code is not research_app.ResearchErrorCode.INPUT_BOUND_EXCEEDED:
                raise
            result = self._original_reader.retained_xray(session, auth, run_id)
            self._original_runs.add(run_id)
            self._retained_reads.pop(run_id, None)
            return result
        self._retained_reads[run_id] = basis
        return basis.pin, basis.result, basis.input_id, basis.deadline

    def xray_metadata(
        self, session: Session, auth: ReportAuthorization, run_id: UUID
    ) -> tuple[UUID, str, str, UUID, datetime | None]:
        self.research_authority(session, auth)
        if run_id not in self._retained_reads and run_id not in self._original_runs:
            self.retained_xray(session, auth, run_id)
        if run_id in self._original_runs:
            # Capture's complete initial/final REPORT metadata preflights remain
            # in force, including acquired-source rights and physical lifetimes.
            # Repeat the original reader's current license/expiry gate here too.
            return self._original_reader.xray_metadata(session, auth, run_id)
        basis = self._retained_reads[run_id]
        # Reuse only immutable decoded proof within this locked capture. Current
        # rights, expiry and exact physical membership are queried again here.
        finish_research_xray(
            session, auth, basis, now=self._now(), required_copy_use=SourceUse.REPORT
        )
        return (
            basis.input_id,
            basis.pin.result_digest,
            basis.pin.input_digest,
            basis.pin.snapshot_id,
            basis.deadline,
        )

    def authorize_source(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> ResearchAuthorizedSource:
        permitted = super().authorize_source(session, auth, identifier)
        row = permitted.header
        grant = require_research_capability(
            self._research_capabilities,
            session,
            owner_id=auth.owner_id,
            provider_id=row.provider_id,
            entity_id=row.entity_id,
            capability=ResearchEventKind(row.capability),
            license_version_id=row.license_version_id,
            grant_id=row.capability_grant_id,
            grant_digest=row.capability_grant_digest,
            now=self._now(),
        )
        if SourceUse.REPORT not in grant.uses:
            raise research_error()
        return permitted


def _source_proof(writer: ResearchReportWriter, authority: ResearchReportAuthority) -> None:
    """Only authorized normalized source/license/grant metadata; no extra provider facts."""
    builder, context = writer.builder, writer.context
    source_rows, license_rows, grant_rows = [], {}, []
    for allowed in authority.sources:
        row, origin, grant = allowed.header, allowed.origin, allowed.grant
        builder.add_reference(
            r.ReportSourceReference(
                key=f"research.source.{row.id}",
                kind=r.ReportSourceKind.RESEARCH_SOURCE_VERSION,
                subject_id=row.id,
                parent_id=row.source_id,
                content_digest=row.content_digest,
                source_at=row.source_cutoff_at,
                first_observed_at=row.first_known_at,
                provider_id=row.provider_id,
                license_version_id=row.license_version_id,
            ),
            provenance_set_key=context.provenance_set_key,
        )
        source_rows.append(
            writer.row(
                r.ReportTableKey.RESEARCH_SOURCES_V1,
                str(row.id),
                row,
                extra={
                    "version_id": row.id,
                    "provider": "alpha_vantage",
                    "schema_version": "1.0.0",
                    "original_retained_at": origin.original_retained_at,
                    "origin_expires_at": origin.expires_at,
                },
            )
        )
        for role, stored in (
            ("pinned", allowed.pinned_license),
            ("current", allowed.current_license),
        ):
            license = license_view(stored)
            key = (role, stored.id)
            license_rows[key] = writer.row(
                r.ReportTableKey.RESEARCH_SOURCE_LICENSES_V1,
                f"{role}.{stored.id}",
                license,
                extra={"role": role, "content_digest": digest(license)},
            )
            if role == "pinned":
                builder.add_license(
                    r.ReportLicenseReference(
                        version_id=stored.id,
                        provider_id=stored.provider_id,
                        license_digest=digest(license),
                        attribution=license.attribution,
                        pinned_store=license.store,
                        pinned_display=license.display,
                        pinned_report=license.report,
                        pinned_export=license.export,
                        valid_from=license.effective_at,
                    )
                )
        grant_rows.append(
            writer.row(
                r.ReportTableKey.RESEARCH_SOURCE_GRANTS_V1,
                str(row.id),
                grant,
                extra={
                    "source_version_id": row.id,
                    "store_allowed": SourceUse.STORE in grant.uses,
                    "display_allowed": SourceUse.DISPLAY in grant.uses,
                    "report_allowed": SourceUse.REPORT in grant.uses,
                    "export_allowed": SourceUse.EXPORT in grant.uses,
                },
            )
        )
    writer.table(r.ReportTableKey.RESEARCH_SOURCES_V1, source_rows)
    writer.table(
        r.ReportTableKey.RESEARCH_SOURCE_LICENSES_V1,
        (license_rows[key] for key in sorted(license_rows, key=lambda x: (x[0], str(x[1])))),
    )
    writer.table(r.ReportTableKey.RESEARCH_SOURCE_GRANTS_V1, grant_rows)


def _xray_sources(
    writer: ResearchReportWriter,
    store: ResearchReportStore,
    session: Session,
    result: XrayCalculation,
) -> None:
    """Original X-ray dependency identities use established physical-copy guards."""
    builder, context, service = writer.builder, writer.context, store._research_xray
    licenses: dict[UUID, SourceLicense] = {}
    source_times: dict[
        tuple[XrayReferenceKind, UUID, str | None], tuple[datetime | None, datetime | None]
    ] = {}
    for dependency in result.source_dependencies:
        if dependency.license_version_id is not None:
            license = licenses.get(dependency.license_version_id)
            if license is None:
                license = service._permit(
                    session, builder.owner_id, dependency.license_version_id, SourceUse.REPORT
                )
                licenses[dependency.license_version_id] = license
            builder.add_license(
                r.ReportLicenseReference(
                    version_id=dependency.license_version_id,
                    provider_id=UUID(license.provider_id),
                    license_digest=digest(license),
                    attribution=license.attribution,
                    pinned_store=license.store,
                    pinned_display=license.display,
                    pinned_report=license.report,
                    pinned_export=license.export,
                    valid_from=license.effective_at,
                )
            )
        physical = dependency.reference
        parent_times = physical.kind in {
            XrayReferenceKind.ENTITY_EVIDENCE_REFERENCE,
            XrayReferenceKind.RELATIONSHIP,
            XrayReferenceKind.FX_OBSERVATION,
            XrayReferenceKind.FX_COVERAGE_GAP,
        }
        identifier = physical.parent_record_id if parent_times else physical.record_id
        if identifier is None:
            fail_validation("A captured source child requires its actual parent.", field="source")
        key = (physical.kind, identifier, dependency.provider_id)
        if key not in source_times:
            view = service._source_view(session, builder.owner_id, dependency)
            source_times[key] = (view.source_at, view.first_observed_at)
        source_at, known_at = source_times[key]
        builder.add_reference(
            r.ReportSourceReference(
                key=_source_key(dependency.id),
                kind=_SOURCE_KINDS[dependency.reference.kind],
                subject_id=dependency.reference.record_id,
                parent_id=dependency.reference.parent_record_id,
                content_digest=dependency.content_digest,
                source_at=source_at,
                first_observed_at=known_at,
                provider_id=None
                if dependency.provider_id is None
                else UUID(dependency.provider_id),
                license_version_id=dependency.license_version_id,
            ),
            provenance_set_key=context.provenance_set_key,
        )
    _source_parents(builder, context, session, service, result, SourceUse.REPORT)


def capture_research(
    builder: ReportBuilder,
    session: Session,
    authorization: ReportAuthorization,
    *,
    sessions: sessionmaker[Session],
    clock: Callable[[], datetime],
    cursor_signing_key: bytes,
) -> ReportResearchBinding:
    selection = builder.selection
    if not isinstance(selection, ReportSelectionV3) or not isinstance(
        selection.premium_run, ReportResearchSelection
    ):
        fail_validation("An explicit research selection is required.", field="premium_run")
    research_owner_lock(session, authorization.owner_id)
    pin = selection.premium_run
    authority = authorize_research_report_metadata(session, authorization, pin, now=clock())
    item = authority.item
    if (
        item.snapshot_id != selection.snapshot_id
        or item.source_cutoff_at != selection.source_cutoff_at
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    store = ResearchReportStore(sessions, clock=clock, cursor_signing_key=cursor_signing_key)
    try:
        # Exact selected IDs only. Never call item_view(), current_review() or a note-head query.
        event = store.read_event(session, authorization, item.revision_id)
        notes = tuple(
            store.read_note_revision(session, authorization, identifier)
            for identifier in pin.note_revision_ids
        )
        review = None if authority.review is None else store._review_view(authority.review)
        xray_pin, xray, input_id, xray_deadline = store.retained_xray(
            session, authorization, item.xray_run_id
        )
        facts = copy_research_portfolio_facts(xray_pin, xray, item.entity_id)
        if (
            input_id,
            xray_pin.input_digest,
            xray_pin.result_digest,
            research_record_digest(xray_pin),
        ) != (
            item.xray_input_id,
            item.xray_input_digest,
            item.xray_result_digest,
            item.xray_pin_digest,
        ) or (xray_pin.snapshot_id, xray_pin.reporting_currency, xray_pin.valuation_at) != (
            selection.snapshot_id,
            selection.reporting_currency,
            builder.valuation_at,
        ):
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        snapshots = tuple(
            binding
            for binding in builder.bindings
            if binding.family is r.ReportFamily.SNAPSHOT
            and binding.role is r.ReportInputRole.SNAPSHOT
            and binding.subject_id == item.snapshot_id
        )
        if len(snapshots) != 1:
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        deadline = min(authority.expires_at, xray_deadline or authority.expires_at)
        binding = ReportResearchBinding(
            item_id=item.id,
            item_selection_digest=item.selection_digest,
            owner_id=authorization.owner_id,
            account_id=authorization.account_id,
            entity_id=item.entity_id,
            event_id=event.event_id,
            event_revision_id=event.revision_id,
            event_revision_digest=event.content_digest,
            snapshot_id=item.snapshot_id,
            snapshot_digest=snapshots[0].content_digest,
            reporting_currency=selection.reporting_currency,
            source_cutoff_at=item.source_cutoff_at,
            valuation_at=xray_pin.valuation_at,
            xray=ReportXrayRunBinding(
                run_id=item.xray_run_id,
                input_id=input_id,
                input_digest=xray_pin.input_digest,
                result_digest=xray_pin.result_digest,
            ),
            xray_pin=xray_pin,
            note_revisions=tuple(
                ReportResearchNoteBinding(
                    note_id=note.note_id,
                    revision_id=note.revision_id,
                    content_digest=note.content_digest,
                )
                for note in notes
            ),
            created_at=item.created_at,
            expires_at=deadline,
            review_acknowledgment=review,
        )
        writer = project_research(builder, binding, event, facts, notes)
        _source_proof(writer, authority)
        _xray_sources(writer, store, session, xray)
        witnesses = [
            (
                r.ReportFamily.RESEARCH,
                r.ReportInputRole.INPUT,
                item.id,
                item.selection_digest,
                None,
            ),
            (
                r.ReportFamily.RESEARCH,
                r.ReportInputRole.EVENT_REVISION,
                event.revision_id,
                event.content_digest,
                event.event_id,
            ),
            (r.ReportFamily.XRAY, r.ReportInputRole.INPUT, input_id, xray_pin.input_digest, None),
            (
                r.ReportFamily.XRAY,
                r.ReportInputRole.RESULT,
                item.xray_run_id,
                xray_pin.result_digest,
                None,
            ),
        ]
        witnesses.extend(
            (
                r.ReportFamily.RESEARCH,
                r.ReportInputRole.SOURCE,
                note.revision_id,
                note.content_digest,
                note.note_id,
            )
            for note in notes
        )
        if review is not None:
            witnesses.append(
                (
                    r.ReportFamily.RESEARCH,
                    r.ReportInputRole.SOURCE,
                    review.acknowledgment_id,
                    research_record_digest(review),
                    event.revision_id,
                )
            )
        for family, role, identifier, content_digest, parent in witnesses:
            builder.add_binding(
                r.ReportBinding(
                    family=family,
                    role=role,
                    subject_id=identifier,
                    content_digest=content_digest,
                    parent_id=parent,
                    method_key=writer.context.method_key,
                    method_version=writer.context.method_version,
                )
            )
            if family is r.ReportFamily.RESEARCH:
                kind = (
                    r.ReportSourceKind.RESEARCH_ITEM
                    if role is r.ReportInputRole.INPUT
                    else r.ReportSourceKind.RESEARCH_EVENT_REVISION
                    if role is r.ReportInputRole.EVENT_REVISION
                    else r.ReportSourceKind.RESEARCH_REVIEW_ACKNOWLEDGMENT
                    if review is not None and identifier == review.acknowledgment_id
                    else r.ReportSourceKind.RESEARCH_NOTE_REVISION
                )
                builder.add_reference(
                    r.ReportSourceReference(
                        key=f"research.selected.{kind.value}.{identifier}",
                        kind=kind,
                        subject_id=identifier,
                        content_digest=content_digest,
                        parent_id=parent,
                    ),
                    provenance_set_key=writer.context.provenance_set_key,
                )
        final = authorize_research_report_metadata(session, authorization, pin, now=clock())
        store.xray_metadata(session, authorization, item.xray_run_id)
        builder.limit_copy_expiry(min(deadline, final.expires_at))
        return binding
    except (research_app.ResearchServiceError, SourceServiceError, XrayServiceError):
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE) from None
