"""Exact research item/revision report bindings; no synthesized research run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from . import reports as r
from .errors import fail_validation
from .research import RESEARCH_METHOD, RESEARCH_VERSION
from .research_facts import ResearchXrayPin
from .research_notes import ResearchReviewAcknowledgment
from .research_serialization import research_record_digest
from .serialization import canonical_json
from .values import CurrencyCode


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportResearchSelection(r.ReportRecord):
    item_id: UUID
    note_revision_ids: tuple[UUID, ...]
    review_acknowledgment_id: UUID | None = None
    family: r.ReportFamily = r.ReportFamily.RESEARCH

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if self.family is not r.ReportFamily.RESEARCH:
            fail_validation("Research selection family differs.", field="family")
        r.report_limit(len(self.note_revision_ids) <= 64, "note_revision_ids")
        if len(set(self.note_revision_ids)) != len(self.note_revision_ids):
            fail_validation("Research note revisions are duplicated.", field="note_revision_ids")
        object.__setattr__(
            self, "note_revision_ids", tuple(sorted(self.note_revision_ids, key=str))
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportResearchNoteBinding(r.ReportRecord):
    note_id: UUID
    revision_id: UUID
    content_digest: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportResearchBinding(r.ReportRecord):
    item_id: UUID
    item_selection_digest: str
    owner_id: UUID
    account_id: UUID
    entity_id: UUID
    event_id: UUID
    event_revision_id: UUID
    event_revision_digest: str
    snapshot_id: UUID
    snapshot_digest: str
    reporting_currency: CurrencyCode
    source_cutoff_at: datetime
    valuation_at: datetime
    xray: v3.ReportXrayRunBinding
    xray_pin: ResearchXrayPin
    note_revisions: tuple[ReportResearchNoteBinding, ...]
    created_at: datetime
    expires_at: datetime
    review_acknowledgment: ResearchReviewAcknowledgment | None = None
    family: r.ReportFamily = r.ReportFamily.RESEARCH

    def __post_init__(self) -> None:
        r.ReportRecord.__post_init__(self)
        if self.family is not r.ReportFamily.RESEARCH or self.created_at >= self.expires_at:
            fail_validation("A retained research item is required.", field="premium_binding")
        if self.item_selection_digest != research_item_selection_digest(self):
            fail_validation(
                "Research item selection digest differs.", field="item_selection_digest"
            )
        pin = self.xray_pin
        if (
            self.owner_id,
            self.account_id,
            self.snapshot_id,
            self.reporting_currency,
            self.valuation_at,
            self.xray.run_id,
            self.xray.input_digest,
            self.xray.result_digest,
        ) != (
            pin.owner_id,
            pin.account_id,
            pin.snapshot_id,
            pin.reporting_currency,
            pin.valuation_at,
            pin.run_id,
            pin.input_digest,
            pin.result_digest,
        ):
            fail_validation("Research X-ray evidence differs.", field="xray_pin")
        # Item/event visibility and the saved X-ray financial cutoff are distinct.
        r.report_limit(len(self.note_revisions) <= 64, "note_revisions")
        if len({note.revision_id for note in self.note_revisions}) != len(self.note_revisions):
            fail_validation("Research note bindings are duplicated.", field="note_revisions")
        object.__setattr__(
            self,
            "note_revisions",
            tuple(sorted(self.note_revisions, key=lambda n: str(n.revision_id))),
        )
        review = self.review_acknowledgment
        if review is not None and (
            review.owner_id,
            review.account_id,
            review.event_id,
            review.revision_id,
            review.revision_digest,
        ) != (
            self.owner_id,
            self.account_id,
            self.event_id,
            self.event_revision_id,
            self.event_revision_digest,
        ):
            fail_validation("Research review binding differs.", field="review_acknowledgment")


def research_item_selection_digest(pin: ReportResearchBinding) -> str:
    """The existing item identity framing, independent of report JSON field order."""
    return sha256(
        b"t212pi.research.item.v1\0"
        + canonical_json(
            (
                pin.owner_id,
                pin.account_id,
                pin.event_revision_id,
                pin.event_revision_digest,
                pin.xray_pin,
                pin.source_cutoff_at,
            )
        ).encode()
    ).hexdigest()


def research_required_bindings(
    pin: ReportResearchBinding,
) -> frozenset[tuple[r.ReportFamily, r.ReportInputRole, UUID, str, UUID | None]]:
    values: set[tuple[r.ReportFamily, r.ReportInputRole, UUID, str, UUID | None]] = {
        (pin.family, r.ReportInputRole.INPUT, pin.item_id, pin.item_selection_digest, None),
        (
            pin.family,
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
    }
    values.update(
        (pin.family, r.ReportInputRole.SOURCE, note.revision_id, note.content_digest, note.note_id)
        for note in pin.note_revisions
    )
    if (review := pin.review_acknowledgment) is not None:
        values.add(
            (
                pin.family,
                r.ReportInputRole.SOURCE,
                review.acknowledgment_id,
                research_record_digest(review),
                pin.event_revision_id,
            )
        )
    return frozenset(values)


def validate_research_header(header: v3.ReportDocumentHeaderV3) -> None:
    from .report_projection_schema import PROJECTION_TABLE_COLUMNS
    from .report_research_schema import RESEARCH_PROOF_TABLES, RESEARCH_REPORT_TABLES
    from .report_risk_schema import RISK_PROOF_TABLES, RISK_REPORT_TABLES
    from .report_scenario_schema import SCENARIO_PROOF_TABLES, SCENARIO_REPORT_TABLES

    selection, pin = header.selection, header.premium_binding
    if not isinstance(pin, ReportResearchBinding) or not isinstance(
        selection.premium_run, ReportResearchSelection
    ):
        fail_validation("An exact research selection and binding are required.", field="research")
    chosen = selection.premium_run
    review_id = (
        pin.review_acknowledgment.acknowledgment_id
        if pin.review_acknowledgment is not None
        else None
    )
    if (
        chosen.item_id != pin.item_id
        or chosen.note_revision_ids != tuple(note.revision_id for note in pin.note_revisions)
        or chosen.review_acknowledgment_id != review_id
        or selection.account_id != pin.account_id
        or header.owner_id != pin.owner_id
        or selection.snapshot_id != pin.snapshot_id
        or selection.reporting_currency != pin.reporting_currency
        or selection.source_cutoff_at != pin.source_cutoff_at
        or header.valuation_at != pin.valuation_at
        or (selection.xray_run_id is not None and selection.xray_run_id != pin.xray.run_id)
    ):
        fail_validation("Research selected identities or basis differ.", field="premium_binding")
    supplied = {table.table for table in header.tables}
    required = set((*RESEARCH_REPORT_TABLES, *RESEARCH_PROOF_TABLES))
    forbidden = set(
        (
            *RISK_REPORT_TABLES,
            *RISK_PROOF_TABLES,
            *SCENARIO_REPORT_TABLES,
            *SCENARIO_PROOF_TABLES,
            *PROJECTION_TABLE_COLUMNS,
        )
    )
    r.report_limit(len(header.tables) <= 128, "tables")
    if len(supplied) != len(header.tables) or not required <= supplied or supplied & forbidden:
        fail_validation("Research fixed table inventory differs.", field="tables")
    if any(
        table.dataset is not None
        or (table.section is not None and table.section not in selection.sections)
        for table in header.tables
    ):
        fail_validation("Research table sections differ.", field="tables")
    counts = {table.table: table.row_count for table in header.tables}
    for table in (
        r.ReportTableKey.RESEARCH_BASIS_V1,
        r.ReportTableKey.RESEARCH_EVENT_V1,
        r.ReportTableKey.RESEARCH_PORTFOLIO_V1,
        r.ReportTableKey.RESEARCH_XRAY_PIN_V1,
    ):
        if counts[table] != 1:
            fail_validation("Research canonical basis is incomplete.", field="tables")
    if (
        counts[r.ReportTableKey.RESEARCH_NOTES_V1] != len(pin.note_revisions)
        or counts[r.ReportTableKey.RESEARCH_REVIEW_V1] != int(review_id is not None)
        or any(
            counts[table] == 0
            for table in (
                r.ReportTableKey.RESEARCH_CITATIONS_V1,
                r.ReportTableKey.RESEARCH_SOURCES_V1,
                r.ReportTableKey.RESEARCH_SOURCE_LICENSES_V1,
                r.ReportTableKey.RESEARCH_SOURCE_GRANTS_V1,
            )
        )
    ):
        fail_validation("Research selected evidence is incomplete.", field="tables")


def validate_research_profile(
    header: v3.ReportDocumentHeaderV3,
    proof: r.ReportProof,
    bindings: tuple[r.ReportBinding, ...],
) -> None:
    validate_research_header(header)
    pin = header.premium_binding
    if not isinstance(pin, ReportResearchBinding):
        fail_validation("Research binding is required.", field="premium_binding")
    forbidden = {
        r.ReportFamily.RISK,
        r.ReportFamily.SCENARIO,
        r.ReportFamily.PROJECTION,
        r.ReportFamily.GOAL,
    }
    if any(
        item.family in forbidden
        for group in (proof.contexts, proof.coverage, proof.bounds, proof.notes, bindings)
        for item in group
    ) or any(context.schema_version != "3.0.0" for context in proof.contexts):
        fail_validation("Research proof family or version differs.", field="proof")
    contexts = [context for context in proof.contexts if context.family is pin.family]
    if not contexts or any(
        (context.valuation_at, context.source_cutoff_at, context.method_key, context.method_version)
        != (pin.valuation_at, pin.source_cutoff_at, RESEARCH_METHOD, RESEARCH_VERSION)
        for context in contexts
    ):
        fail_validation("Research canonical context is absent or inconsistent.", field="contexts")
    if not any(
        note.family is pin.family
        and note.kind is r.ReportNoteKind.UNAVAILABLE_REASON
        and note.code == "optional_synthesis_disabled"
        for note in proof.notes
    ):
        fail_validation("Disabled research synthesis must be explicit.", field="notes")
    if any(source.kind in r.SCENARIO_REPORT_SOURCE_KINDS for source in proof.source_references):
        fail_validation("Research cannot contain scenario source proof.", field="source_references")
    actual = {(b.family, b.role, b.subject_id, b.content_digest, b.parent_id) for b in bindings}
    required = research_required_bindings(pin)
    if not required <= actual or {b for b in actual if b[0] is pin.family} != {
        b for b in required if b[0] is pin.family
    }:
        fail_validation(
            "Research immutable proof differs from selected identities.", field="bindings"
        )
    references = {
        (s.kind, s.subject_id, s.content_digest, s.parent_id) for s in proof.source_references
    }
    selected = {
        (r.ReportSourceKind.RESEARCH_ITEM, pin.item_id, pin.item_selection_digest, None),
        (
            r.ReportSourceKind.RESEARCH_EVENT_REVISION,
            pin.event_revision_id,
            pin.event_revision_digest,
            pin.event_id,
        ),
    }
    selected.update(
        (
            r.ReportSourceKind.RESEARCH_NOTE_REVISION,
            note.revision_id,
            note.content_digest,
            note.note_id,
        )
        for note in pin.note_revisions
    )
    if (review := pin.review_acknowledgment) is not None:
        selected.add(
            (
                r.ReportSourceKind.RESEARCH_REVIEW_ACKNOWLEDGMENT,
                review.acknowledgment_id,
                research_record_digest(review),
                pin.event_revision_id,
            )
        )
    selected_kinds = {
        r.ReportSourceKind.RESEARCH_ITEM,
        r.ReportSourceKind.RESEARCH_EVENT_REVISION,
        r.ReportSourceKind.RESEARCH_NOTE_REVISION,
        r.ReportSourceKind.RESEARCH_REVIEW_ACKNOWLEDGMENT,
    }
    if selected != {source for source in references if source[0] in selected_kinds} or not any(
        source.kind is r.ReportSourceKind.RESEARCH_SOURCE_VERSION
        for source in proof.source_references
    ):
        fail_validation("Research original source proof is incomplete.", field="source_references")


# Define this closed variant before loading its legacy X-ray binding module.
# Both direct research imports and profile-three re-exports then resolve safely.
from . import report_v3 as v3  # noqa: E402
