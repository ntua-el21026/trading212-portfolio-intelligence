"""Structural report codec fixtures with independent canonical research evidence."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

from trading212_domain import report_v3 as v3
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.report_manifest import (
    encode_report_proof,
    encode_report_schema,
    report_document_digest,
)
from trading212_domain.report_research import (
    ReportResearchBinding,
    ReportResearchNoteBinding,
    ReportResearchSelection,
)
from trading212_domain.report_schema import report_tables, table_schema
from trading212_domain.research import RESEARCH_METHOD, RESEARCH_VERSION
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.serialization import canonical_json

from tests.unit.domain import research_factories as research
from tests.unit.domain.report_factories import AT, ZERO_DIGEST, document, selection, uid


def research_binding(*, notes: bool = True, review: bool = True) -> ReportResearchBinding:
    event = research.event()
    note = research.note(event)
    pin = replace(
        research.pin(),
        snapshot_id=selection().snapshot_id,
        valuation_at=AT,
        source_cutoff_at=AT - timedelta(hours=1),
    )
    item_cutoff = research.AT
    digest = sha256(
        b"t212pi.research.item.v1\0"
        + canonical_json(
            (
                event.owner_id,
                pin.account_id,
                event.revision_id,
                event.content_digest,
                pin,
                item_cutoff,
            )
        ).encode()
    ).hexdigest()
    return ReportResearchBinding(
        item_id=uid(80),
        item_selection_digest=digest,
        owner_id=event.owner_id,
        account_id=pin.account_id,
        entity_id=event.entity_id,
        event_id=event.event_id,
        event_revision_id=event.revision_id,
        event_revision_digest=event.content_digest,
        snapshot_id=pin.snapshot_id,
        snapshot_digest=ZERO_DIGEST,
        reporting_currency=pin.reporting_currency,
        source_cutoff_at=item_cutoff,
        valuation_at=pin.valuation_at,
        xray=v3.ReportXrayRunBinding(
            run_id=pin.run_id,
            input_id=uid(81),
            input_digest=pin.input_digest,
            result_digest=pin.result_digest,
        ),
        xray_pin=pin,
        note_revisions=(
            ReportResearchNoteBinding(
                note_id=note.note_id,
                revision_id=note.revision_id,
                content_digest=note.content_digest,
            ),
        )
        if notes
        else (),
        review_acknowledgment=research.acknowledgment(event) if review else None,
        created_at=research.AT,
        expires_at=research.AT + timedelta(days=7),
    )


def research_selection(pin: ReportResearchBinding) -> v3.ReportSelectionV3:
    base = selection()
    return v3.ReportSelectionV3(
        account_id=pin.account_id,
        start_date=base.start_date,
        end_date=base.end_date,
        source_cutoff_at=pin.source_cutoff_at,
        snapshot_id=pin.snapshot_id,
        reporting_currency=pin.reporting_currency,
        report_type=base.report_type,
        sections=(*base.sections, r.ReportSection.RESEARCH),
        formats=base.formats,
        premium_run=ReportResearchSelection(
            item_id=pin.item_id,
            note_revision_ids=tuple(note.revision_id for note in pin.note_revisions),
            review_acknowledgment_id=(
                pin.review_acknowledgment.acknowledgment_id if pin.review_acknowledgment else None
            ),
        ),
    )


def research_capture(*, notes: bool = True, review: bool = True) -> v3.ReportCaptureSummaryV3:
    pin = research_binding(notes=notes, review=review)
    selected = research_selection(pin)
    original = document().capture
    context = r.ReportContext(
        key="context.research",
        family=r.ReportFamily.RESEARCH,
        method_key=RESEARCH_METHOD,
        method_version=RESEARCH_VERSION,
        valuation_at=pin.valuation_at,
        source_cutoff_at=pin.source_cutoff_at,
        quality=QualityState.FRESH,
        provenance_set_key="sources.research",
        coverage_set_key="coverage.research",
        note_set_key="notes.research",
        schema_version="3.0.0",
    )
    values: list[tuple[r.ReportFamily, r.ReportInputRole, UUID, str, UUID | None]] = [
        (
            r.ReportFamily.RESEARCH,
            r.ReportInputRole.INPUT,
            pin.item_id,
            pin.item_selection_digest,
            None,
        ),
        (
            r.ReportFamily.RESEARCH,
            r.ReportInputRole.EVENT_REVISION,
            pin.event_revision_id,
            pin.event_revision_digest,
            pin.event_id,
        ),
        (
            r.ReportFamily.SNAPSHOT,
            r.ReportInputRole.SNAPSHOT,
            pin.snapshot_id,
            pin.snapshot_digest,
            None,
        ),
        (
            r.ReportFamily.XRAY,
            r.ReportInputRole.INPUT,
            pin.xray.input_id,
            pin.xray.input_digest,
            None,
        ),
        (
            r.ReportFamily.XRAY,
            r.ReportInputRole.RESULT,
            pin.xray.run_id,
            pin.xray.result_digest,
            None,
        ),
    ]
    values.extend(
        (
            r.ReportFamily.RESEARCH,
            r.ReportInputRole.SOURCE,
            note.revision_id,
            note.content_digest,
            note.note_id,
        )
        for note in pin.note_revisions
    )
    if (ack := pin.review_acknowledgment) is not None:
        values.append(
            (
                r.ReportFamily.RESEARCH,
                r.ReportInputRole.SOURCE,
                ack.acknowledgment_id,
                research_record_digest(ack),
                pin.event_revision_id,
            )
        )
    bindings = tuple(
        r.ReportBinding(
            family=family, role=role, subject_id=subject, content_digest=digest, parent_id=parent
        )
        for family, role, subject, digest, parent in values
    )
    refs = [
        r.ReportSourceReference(
            key="research.item",
            kind=r.ReportSourceKind.RESEARCH_ITEM,
            subject_id=pin.item_id,
            content_digest=pin.item_selection_digest,
        ),
        r.ReportSourceReference(
            key="research.event",
            kind=r.ReportSourceKind.RESEARCH_EVENT_REVISION,
            subject_id=pin.event_revision_id,
            content_digest=pin.event_revision_digest,
            parent_id=pin.event_id,
        ),
    ]
    refs.extend(
        r.ReportSourceReference(
            key=f"research.note.{index}",
            kind=r.ReportSourceKind.RESEARCH_NOTE_REVISION,
            subject_id=note.revision_id,
            content_digest=note.content_digest,
            parent_id=note.note_id,
        )
        for index, note in enumerate(pin.note_revisions)
    )
    if (ack := pin.review_acknowledgment) is not None:
        refs.append(
            r.ReportSourceReference(
                key="research.review",
                kind=r.ReportSourceKind.RESEARCH_REVIEW_ACKNOWLEDGMENT,
                subject_id=ack.acknowledgment_id,
                content_digest=research_record_digest(ack),
                parent_id=pin.event_revision_id,
            )
        )
    source = research.event().citations[0].source
    refs.append(
        r.ReportSourceReference(
            key="research.source",
            kind=r.ReportSourceKind.RESEARCH_SOURCE_VERSION,
            subject_id=source.version_id,
            content_digest=source.content_digest,
            parent_id=source.source_id,
        )
    )
    disabled = r.ReportNote(
        key="research.synthesis.disabled",
        kind=r.ReportNoteKind.UNAVAILABLE_REASON,
        family=r.ReportFamily.RESEARCH,
        code="optional_synthesis_disabled",
        text="Optional synthesis is disabled.",
    )
    proof = replace(
        original.proof,
        contexts=(*(replace(c, schema_version="3.0.0") for c in original.proof.contexts), context),
        source_references=(*original.proof.source_references, *refs),
        notes=(*original.proof.notes, disabled),
    )
    singleton = {
        r.ReportTableKey.RESEARCH_BASIS_V1,
        r.ReportTableKey.RESEARCH_EVENT_V1,
        r.ReportTableKey.RESEARCH_PORTFOLIO_V1,
        r.ReportTableKey.RESEARCH_XRAY_PIN_V1,
        r.ReportTableKey.RESEARCH_CITATIONS_V1,
        r.ReportTableKey.RESEARCH_SOURCES_V1,
        r.ReportTableKey.RESEARCH_SOURCE_LICENSES_V1,
        r.ReportTableKey.RESEARCH_SOURCE_GRANTS_V1,
    }
    tables = tuple(
        r.ReportTableDescriptor(
            table=table,
            schema_digest=sha256(encode_report_schema(table_schema(table))).hexdigest(),
            row_count=(
                len(pin.note_revisions)
                if table is r.ReportTableKey.RESEARCH_NOTES_V1
                else int(pin.review_acknowledgment is not None)
                if table is r.ReportTableKey.RESEARCH_REVIEW_V1
                else int(table in singleton)
            ),
            content_digest=ZERO_DIGEST,
        )
        for table in report_tables(selected)
    )
    proof_digest = sha256(encode_report_proof(proof)).hexdigest()
    header = v3.ReportDocumentHeaderV3(
        selection=selected,
        owner_id=pin.owner_id,
        valuation_at=pin.valuation_at,
        context_digest=proof_digest,
        tables=tables,
        document_digest=ZERO_DIGEST,
        premium_binding=pin,
    )
    header = replace(header, document_digest=report_document_digest(header))
    return v3.ReportCaptureSummaryV3(
        header=header,
        canonical_byte_length=0,
        chunk_count=0,
        immutable_bindings=bindings,
        proof=proof,
        proof_digest=proof_digest,
        renderer_profile=original.renderer_profile,
        copy_expires_at=pin.expires_at,
    )
