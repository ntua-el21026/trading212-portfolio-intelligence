"""Small complete retained calculation plus a collecting shared-cell report sink."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from trading212_domain import reports as r
from trading212_domain.report_manifest import encode_report_schema, report_table_digest
from trading212_domain.report_schema import table_schema, validate_report_row
from trading212_domain.report_v4 import (
    ReportCaptureSummaryV4,
    ReportContextSnapshotBinding,
    ReportContextV4,
    ReportProjectionRunSelection,
    ReportProjectionVersionBinding,
    ReportSelectionV4,
    report_tables_v4,
)
from trading212_domain.sources import SourceAvailability
from trading212_persistence.projection_input_store import CapturedProjectionInputs
from trading212_persistence.projection_result_store import StoredProjectionResult
from trading212_persistence.projection_retained_codec import pack_projection_input
from trading212_persistence.projection_source_store import ProjectionSourceBundle
from trading212_persistence.report_capture_projection import ProjectionReportMetadata

from tests.unit.application.projection_presentation_factories import retained

OWNER = UUID(int=901)
REPORT_AT = datetime(2025, 2, 28, 20, 12, 3, 999999, tzinfo=UTC)


class CollectingBuilder:
    def __init__(self, selection: ReportSelectionV4) -> None:
        self.selection = selection
        self.owner_id = OWNER
        self.valuation_at = REPORT_AT
        self.bindings = [
            r.ReportBinding(
                family=r.ReportFamily.SNAPSHOT,
                role=r.ReportInputRole.SNAPSHOT,
                subject_id=selection.snapshot_id,
                content_digest="e" * 64,
                method_key="portfolio_snapshot_v1",
                method_version="1.0.0",
            )
        ]
        self.references: dict[str, r.ReportSourceReference] = {}
        self.contexts: dict[str, ReportContextV4] = {}
        self.notes: dict[str, r.ReportNote] = {}
        self.note_memberships: list[r.ReportNoteMembership] = []
        self.source_memberships: list[r.ReportSourceMembership] = []
        self.licenses: list[r.ReportLicenseReference] = []
        self.rows: dict[r.ReportTableKey, tuple[r.ReportRow, ...]] = {}
        self.sections: dict[r.ReportTableKey, r.ReportSection | None] = {}
        self.deadline: datetime | None = None

    def add_context(self, context: ReportContextV4) -> None:
        assert self.contexts.get(context.key, context) == context
        self.contexts[context.key] = context

    def add_binding(self, binding: r.ReportBinding) -> None:
        self.bindings.append(binding)

    def add_reference(self, reference: r.ReportSourceReference, *, provenance_set_key: str) -> None:
        self.references[reference.key] = reference
        self.source_memberships.append(
            r.ReportSourceMembership(
                provenance_set_key=provenance_set_key,
                source_key=reference.key,
            )
        )

    def add_license(self, license: r.ReportLicenseReference) -> None:
        self.licenses.append(license)

    def add_note(self, note: r.ReportNote, *, note_set_key: str) -> None:
        self.notes[note.key] = note
        self.note_memberships.append(
            r.ReportNoteMembership(note_set_key=note_set_key, note_key=note.key)
        )

    def limit_copy_expiry(self, deadline: datetime) -> None:
        self.deadline = deadline if self.deadline is None else min(deadline, self.deadline)

    def add_table(
        self,
        table: r.ReportTableKey,
        rows: Iterable[r.ReportRow],
        *,
        section: r.ReportSection | None = None,
        dataset: r.ExportDataset | None = None,
        state: SourceAvailability = SourceAvailability.AVAILABLE,
        reason_key: str | None = None,
    ) -> None:
        assert table not in self.rows and dataset is None
        assert state is SourceAvailability.AVAILABLE and reason_key is None
        actual = tuple(rows)
        for row in actual:
            validate_report_row(table, row)
            assert row.context_key in self.contexts
        self.rows[table] = actual
        self.sections[table] = section

    def descriptors(self) -> tuple[r.ReportTableDescriptor, ...]:
        # Ordinary sections belong to parent integration; placeholders have no rows.
        return tuple(
            r.ReportTableDescriptor(
                table=table,
                schema_digest=sha256(encode_report_schema(table_schema(table))).hexdigest(),
                row_count=len(self.rows.get(table, ())),
                content_digest=report_table_digest(table, self.rows.get(table, ())),
                section=self.sections.get(table),
            )
            for table in report_tables_v4(self.selection)
        )


@dataclass(frozen=True)
class ReportCase:
    builder: CollectingBuilder
    captured: CapturedProjectionInputs
    saved: StoredProjectionResult
    metadata: ProjectionReportMetadata


def case(*, goal: bool = True, sensitive: bool = True, goal_section: bool = True) -> ReportCase:
    original = retained(goal=goal, sensitive=sensitive, source_count=0, observed=False)
    plan = original.capture
    created = original.calculated_at - timedelta(seconds=1)
    deadline = created + timedelta(days=30)
    selection = ReportSelectionV4(
        account_id=plan.selection.account_id,
        snapshot_id=UUID(int=903),
        start_date=REPORT_AT.date().replace(day=1),
        end_date=REPORT_AT.date(),
        source_cutoff_at=REPORT_AT + timedelta(hours=2),
        reporting_currency=plan.inputs.assumptions.reporting_currency,
        report_type=r.ReportType.PORTFOLIO_SUMMARY,
        sections=(
            r.ReportSection.OVERVIEW,
            r.ReportSection.ALLOCATION,
            r.ReportSection.QUALITY,
            r.ReportSection.PROJECTION,
            *((r.ReportSection.GOAL,) if goal and goal_section else ()),
        ),
        formats=tuple(r.ReportFormat),
        premium_run=ReportProjectionRunSelection(run_id=original.run_id),
    )

    def version(identifier: UUID, digest: str, aggregate: int) -> ReportProjectionVersionBinding:
        return ReportProjectionVersionBinding(
            aggregate_id=UUID(int=aggregate),
            version_id=identifier,
            version_number=1,
            predecessor_id=None,
            name="Synthetic immutable model",
            description="Exact retained source fixture",
            content_digest=digest,
            created_at=created - timedelta(days=2),
        )

    metadata = ProjectionReportMetadata(
        run_id=original.run_id,
        input_id=UUID(int=902),
        assumption=version(
            plan.assumption_version.version_id, plan.assumption_version.content_digest, 910
        ),
        goal=None
        if plan.goal_version is None
        else version(plan.goal_version.version_id, plan.goal_version.content_digest, 911),
        created_at=created,
        completed_at=original.calculated_at + timedelta(seconds=1),
        expires_at=deadline,
        report_context=ReportContextSnapshotBinding(
            snapshot_id=selection.snapshot_id,
            snapshot_digest="e" * 64,
            valuation_at=REPORT_AT,
            source_cutoff_at=selection.source_cutoff_at,
        ),
    )
    return ReportCase(
        builder=CollectingBuilder(selection),
        captured=CapturedProjectionInputs(
            plan=plan,
            sources=ProjectionSourceBundle(
                snapshot=None,
                sources=(),
                expires_at=deadline,
                license_version_ids=(),
            ),
            stored=pack_projection_input(plan),
        ),
        saved=StoredProjectionResult(
            id=original.result_id,
            run_id=original.run_id,
            content_digest=original.saved_result_digest,
            created_at=original.calculated_at,
            calculation=original.calculation,
            quality=original.quality,
        ),
        metadata=metadata,
    )


def values(table: r.ReportTableKey, row: r.ReportRow) -> dict[str, r.ReportCell]:
    return {
        column.key: cell
        for column, cell in zip(table_schema(table).columns, row.cells, strict=True)
    }


def capture_v4() -> ReportCaptureSummaryV4:
    """Real chunk builder over saved synthetic projection values; ordinary tables are empty."""
    from unittest.mock import Mock

    from trading212_domain.report_v4 import ReportCaptureSummaryV4
    from trading212_persistence.report_builder import ReportBuilder
    from trading212_persistence.report_capture_projection import project_projection

    value = case()
    sink = Mock()
    builder = ReportBuilder(
        value.builder.selection,
        owner_id=value.builder.owner_id,
        valuation_at=value.builder.valuation_at,
        sink=sink,
    )
    for binding in value.builder.bindings:
        builder.add_binding(binding)
    builder.premium_binding = project_projection(
        builder, value.captured, value.saved, value.metadata
    )
    for table in report_tables_v4(value.builder.selection):
        if table not in builder.descriptors:
            builder.add_table(table, ())
    capture = builder.finish()
    assert isinstance(capture, ReportCaptureSummaryV4)
    assert capture.chunk_count == sink.append.call_count
    assert any(context.valuation_at is None for context in capture.proof.contexts)
    return capture
