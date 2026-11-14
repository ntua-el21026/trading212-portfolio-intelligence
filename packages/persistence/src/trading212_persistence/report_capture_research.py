"""Fixed-schema research copies of retained facts and explicitly selected owner revisions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import fields
from decimal import Decimal
from uuid import UUID

from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.report_research import ReportResearchBinding, ReportResearchSelection
from trading212_domain.report_research_schema import RESEARCH_REPORT_TABLES
from trading212_domain.report_schema import table_schema
from trading212_domain.report_v3 import ReportSelectionV3
from trading212_domain.research import RESEARCH_METHOD, RESEARCH_VERSION
from trading212_domain.research_facts import ResearchPortfolioFacts
from trading212_domain.research_notes import ResearchNoteRevision
from trading212_domain.research_serialization import research_record_digest
from trading212_domain.research_sources import ResearchEventRevision
from trading212_domain.values import CurrencyCode

from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_note, capture_row


class ResearchReportWriter:
    def __init__(self, builder: ReportBuilder, context: r.ReportContext) -> None:
        self.builder, self.context = builder, context

    def row(
        self,
        table: r.ReportTableKey,
        ordinal: str | int,
        source: object | None = None,
        *,
        extra: Mapping[str, ReportValue] | None = None,
    ) -> r.ReportRow:
        overrides = extra or {}
        values: dict[str, ReportValue] = {}
        for column in table_schema(table).columns:
            if column.key in overrides:
                values[column.key] = overrides[column.key]
            elif source is not None and hasattr(source, column.key):
                values[column.key] = getattr(source, column.key)
            else:
                fail_validation("Research fixed-table projection is incomplete.", field=column.key)
            scalar = values[column.key]
            if isinstance(scalar, CurrencyCode):
                values[column.key] = scalar.value
        return capture_row(
            self.builder,
            self.context,
            table,
            key=f"research.{table.value}.{ordinal}",
            values=values,
            currency=self.builder.selection.reporting_currency,
        )

    def table(self, table: r.ReportTableKey, rows: Iterable[r.ReportRow]) -> None:
        self.builder.add_table(
            table,
            rows,
            section=r.ReportSection.RESEARCH if table in RESEARCH_REPORT_TABLES else None,
        )


def research_report_context(
    binding: ReportResearchBinding, facts: ResearchPortfolioFacts
) -> r.ReportContext:
    return r.ReportContext(
        key="research",
        family=r.ReportFamily.RESEARCH,
        method_key=RESEARCH_METHOD,
        method_version=RESEARCH_VERSION,
        valuation_at=binding.valuation_at,
        source_cutoff_at=binding.source_cutoff_at,
        source_at=binding.created_at,
        quality=facts.quality,
        provenance_set_key="research.sources",
        coverage_set_key="research.coverage",
        note_set_key="research.notes",
        schema_version="3.0.0",
    )


def _exposure_cell(writer: ResearchReportWriter, facts: ResearchPortfolioFacts) -> r.ReportCell:
    builder, context = writer.builder, writer.context
    missing = facts.effective_exposure is None
    reason = None
    if facts.reason is not None:
        reason = capture_note(
            builder,
            context,
            key="research.exposure.reason",
            text=facts.reason.value,
            code=facts.reason.value,
        )
    bound_key = "research.exposure.bound"
    builder.add_bound(
        r.ReportBoundFact(
            key=bound_key,
            family=r.ReportFamily.RESEARCH,
            kind=r.ReportBoundKind.UNAVAILABLE if missing else r.ReportBoundKind(facts.bound.value),
            quantum=Decimal("1e-18"),
            rounding="ROUND_HALF_EVEN",
            positive_below_quantum=facts.positive_unresolved_below_quantum,
        )
    )
    builder.add_coverage(
        r.ReportCoverageFact(
            set_key=context.coverage_set_key,
            family=r.ReportFamily.RESEARCH,
            metric_key="company_coverage_complete",
            value=r.ReportCell(
                kind=r.CellKind.BOOLEAN,
                state=r.CellState.AVAILABLE,
                value=facts.company_coverage_complete,
                context_key=context.key,
            ),
        )
    )
    return r.ReportCell(
        kind=r.CellKind.DECIMAL,
        value=None if facts.effective_exposure is None else facts.effective_exposure.amount,
        state=r.CellState.UNAVAILABLE if missing else r.CellState.AVAILABLE,
        decimal_role=r.DecimalRole.MONEY,
        currency=builder.selection.reporting_currency,
        context_key=context.key,
        reason_key=reason,
        bound_key=bound_key,
        quality=facts.quality,
        confidence=facts.confidence,
        origin=r.ReportMetricOrigin(facts.origin.value),
        coverage_key=context.coverage_set_key,
        method_key=facts.pin.method,
        method_version=facts.pin.method_version,
        provenance_set_key=context.provenance_set_key,
        note_set_key=context.note_set_key,
    )


def project_research(
    builder: ReportBuilder,
    binding: ReportResearchBinding,
    event: ResearchEventRevision,
    facts: ResearchPortfolioFacts,
    notes: tuple[ResearchNoteRevision, ...],
) -> ResearchReportWriter:
    """Copy retained canonical data; no financial calculation or head resolution."""
    selected = builder.selection
    actual_notes = tuple(
        sorted(
            ((note.note_id, note.revision_id, note.content_digest) for note in notes),
            key=lambda note: str(note[1]),
        )
    )
    if (
        not isinstance(selected, ReportSelectionV3)
        or not isinstance(selected.premium_run, ReportResearchSelection)
        or selected.premium_run.item_id != binding.item_id
        or selected.premium_run.note_revision_ids != tuple(note[1] for note in actual_notes)
        or (
            builder.owner_id,
            selected.account_id,
            selected.snapshot_id,
            selected.reporting_currency,
            selected.source_cutoff_at,
            builder.valuation_at,
        )
        != (
            binding.owner_id,
            binding.account_id,
            binding.snapshot_id,
            binding.reporting_currency,
            binding.source_cutoff_at,
            binding.valuation_at,
        )
        or (
            event.owner_id,
            event.entity_id,
            event.event_id,
            event.revision_id,
            event.content_digest,
        )
        != (
            binding.owner_id,
            binding.entity_id,
            binding.event_id,
            binding.event_revision_id,
            binding.event_revision_digest,
        )
        or facts.entity_id != binding.entity_id
        or facts.pin != binding.xray_pin
        or actual_notes
        != tuple(
            (note.note_id, note.revision_id, note.content_digest) for note in binding.note_revisions
        )
        or any(
            (note.owner_id, note.account_id, note.entity_id)
            != (binding.owner_id, binding.account_id, binding.entity_id)
            for note in notes
        )
    ):
        fail_validation(
            "Research projection differs from its retained binding.", field="research_binding"
        )
    context = research_report_context(binding, facts)
    builder.add_context(context)
    writer = ResearchReportWriter(builder, context)
    capture_note(
        builder,
        context,
        key="research.optional_synthesis.disabled",
        text="Optional synthesis is unavailable because it is disabled.",
        code="optional_synthesis_disabled",
    )
    capture_note(
        builder,
        context,
        key="research.explicit_selection",
        text="Only explicitly selected immutable note revisions and review evidence are included.",
        kind=r.ReportNoteKind.ASSUMPTION,
        code="exact_revision_selection",
    )
    writer.table(
        r.ReportTableKey.RESEARCH_BASIS_V1,
        (
            writer.row(
                r.ReportTableKey.RESEARCH_BASIS_V1,
                0,
                binding,
                extra={
                    "selected_note_count": len(notes),
                    "review_selected": binding.review_acknowledgment is not None,
                    "xray_pin_digest": research_record_digest(binding.xray_pin),
                },
            ),
        ),
    )
    writer.table(
        r.ReportTableKey.RESEARCH_EVENT_V1,
        (
            writer.row(
                r.ReportTableKey.RESEARCH_EVENT_V1,
                0,
                event,
                extra={
                    "kind": event.facts.kind,
                    "publisher": event.facts.publisher,
                    "title": getattr(event.facts, "title", None),
                    "summary": getattr(event.facts, "summary", None),
                    "published_at": event.facts.published_at,
                    "company_name": getattr(event.facts, "company_name", None),
                    "description": getattr(event.facts, "description", None),
                    "publication_reason": getattr(event.facts, "publication_reason", None),
                    "content_type": event.facts.content_type,
                    "facts_digest": research_record_digest(event.facts),
                },
            ),
        ),
    )
    writer.table(
        r.ReportTableKey.RESEARCH_CITATIONS_V1,
        (
            writer.row(
                r.ReportTableKey.RESEARCH_CITATIONS_V1,
                ordinal,
                citation,
                extra={
                    "ordinal": ordinal,
                    "source_id": citation.source.source_id,
                    "source_version_id": citation.source.version_id,
                    "source_version_digest": citation.source.content_digest,
                    "citation_digest": citation.content_digest,
                },
            )
            for ordinal, citation in enumerate(event.citations)
        ),
    )
    writer.table(
        r.ReportTableKey.RESEARCH_PORTFOLIO_V1,
        (
            writer.row(
                r.ReportTableKey.RESEARCH_PORTFOLIO_V1,
                0,
                facts,
                extra={
                    "canonical_facts_digest": research_record_digest(facts),
                    "effective_exposure": _exposure_cell(writer, facts),
                },
            ),
        ),
    )

    def member_rows(
        kind: str, key: str, field: str, values: Iterable[str | UUID]
    ) -> Iterable[r.ReportRow]:
        for ordinal, value in enumerate(values):
            yield writer.row(
                r.ReportTableKey.RESEARCH_PORTFOLIO_MEMBERS_V1,
                f"{kind}.{key}.{field}.{ordinal}",
                extra={
                    "owner_kind": kind,
                    "owner_key": key,
                    "field": field,
                    "ordinal": ordinal,
                    "member_id": value,
                },
            )

    def portfolio_members() -> Iterable[r.ReportRow]:
        for name in ("source_reference_ids", "metric_source_reference_ids", "path_keys"):
            yield from member_rows("portfolio", str(facts.entity_id), name, getattr(facts, name))
        for ordinal, warning in enumerate(facts.warnings):
            for name in ("source_reference_ids", "path_keys"):
                yield from member_rows("warning", str(ordinal), name, getattr(warning, name))

    writer.table(r.ReportTableKey.RESEARCH_PORTFOLIO_MEMBERS_V1, portfolio_members())
    writer.table(
        r.ReportTableKey.RESEARCH_WARNINGS_V1,
        (
            writer.row(
                r.ReportTableKey.RESEARCH_WARNINGS_V1, ordinal, warning, extra={"ordinal": ordinal}
            )
            for ordinal, warning in enumerate(facts.warnings)
        ),
    )
    writer.table(
        r.ReportTableKey.RESEARCH_NOTES_V1,
        (
            writer.row(
                r.ReportTableKey.RESEARCH_NOTES_V1,
                str(note.revision_id),
                note,
                extra={
                    field.name: getattr(note.content, field.name)
                    for field in fields(note.content)
                    if field.name != "citations"
                },
            )
            for note in notes
        ),
    )
    writer.table(
        r.ReportTableKey.RESEARCH_NOTE_CITATIONS_V1,
        (
            writer.row(
                r.ReportTableKey.RESEARCH_NOTE_CITATIONS_V1,
                f"{note.revision_id}.{ordinal}",
                citation,
                extra={"note_revision_id": note.revision_id, "ordinal": ordinal},
            )
            for note in notes
            for ordinal, citation in enumerate(note.content.citations)
        ),
    )
    review = binding.review_acknowledgment
    writer.table(
        r.ReportTableKey.RESEARCH_REVIEW_V1,
        () if review is None else (writer.row(r.ReportTableKey.RESEARCH_REVIEW_V1, 0, review),),
    )
    writer.table(
        r.ReportTableKey.RESEARCH_XRAY_PIN_V1,
        (
            writer.row(
                r.ReportTableKey.RESEARCH_XRAY_PIN_V1,
                0,
                binding.xray_pin,
                extra={"input_id": binding.xray.input_id},
            ),
        ),
    )
    return writer
