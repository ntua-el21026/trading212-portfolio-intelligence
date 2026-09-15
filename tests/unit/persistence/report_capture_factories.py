"""Full historical renderer fixtures built from the existing exact synthetic kernel input."""

from dataclasses import replace
from datetime import date, datetime
from uuid import UUID

from trading212_analytics.historical import calculate_performance
from trading212_domain import historical_results as h
from trading212_domain import reports as r
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_capture_historical import _context, project_historical

from tests.unit.analytics.historical_factories import fixture as historical_fixture
from tests.unit.domain.report_factories import ReportFixture, document


class _CaptureSink:
    def __init__(self) -> None:
        self.chunks: list[r.ReportChunk] = []

    def append(self, chunk: r.ReportChunk) -> None:
        self.chunks.append(chunk)

    def finish(self, summary: r.ReportCaptureSummary) -> None:
        raise AssertionError("The renderer fixture does not own the service seal")


def annual_performance_document(
    formats: tuple[r.ReportFormat, ...] = tuple(r.ReportFormat),
) -> ReportFixture:
    """Calculate 365 intervals and report the fixed monthly public series/provenance.

    This exercises renderer size and provenance preservation. It is a synthetic
    portfolio-summary report with a full historical window, not a persisted annual job.
    """
    value = historical_fixture(("100",) * 366)
    result = calculate_performance(value, options=h.PerformanceOptions())
    window = value.selection.window
    base = document(formats)
    base_selection = base.header.selection
    assert isinstance(base_selection, r.ReportSelection)
    selection = replace(
        base_selection,
        account_id=UUID(value.account_id),
        start_date=window.start_date,
        end_date=window.end_date,
        source_cutoff_at=window.source_cutoff_at,
        sections=(*base_selection.sections, r.ReportSection.PERFORMANCE),
    )
    sink = _CaptureSink()
    builder = ReportBuilder(
        selection, owner_id=UUID(value.owner_id), valuation_at=window.end_at, sink=sink
    )
    for context in base.capture.proof.contexts:
        builder.add_context(
            replace(
                context,
                valuation_at=window.end_at,
                source_cutoff_at=window.source_cutoff_at,
            )
        )
    sources = {item.key: item for item in base.capture.proof.source_references}
    for membership in base.capture.proof.source_memberships:
        builder.add_reference(
            sources[membership.source_key], provenance_set_key=membership.provenance_set_key
        )
    notes = {item.key: item for item in base.capture.proof.notes}
    for note_membership in base.capture.proof.note_memberships:
        builder.add_note(notes[note_membership.note_key], note_set_key=note_membership.note_set_key)
    for binding in base.capture.immutable_bindings:
        builder.add_binding(binding)
    for descriptor in base.header.tables:
        rows = (
            replace(
                row,
                cells=tuple(
                    replace(cell, value=window.end_at)
                    if type(cell.value) is datetime
                    else replace(cell, value=window.end_date)
                    if type(cell.value) is date
                    else cell
                    for cell in row.cells
                ),
            )
            for chunk in base.iter_chunks(descriptor.table)
            for row in chunk.rows
        )
        builder.add_table(descriptor.table, rows, section=descriptor.section)
    context = _context(builder, result)
    project_historical(builder, context, value, result)
    capture = builder.finish()
    assert isinstance(capture, r.ReportCaptureSummary)
    return ReportFixture(capture, tuple(sink.chunks))
