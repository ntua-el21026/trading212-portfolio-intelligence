"""Pinned reconciliation and complete typed quality relations for private reports."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.report_schema import report_tables

from .models import PortfolioSnapshotModel, ReconciliationDiscrepancyModel, ReconciliationRunModel
from .planning_inputs import digest
from .report_builder import ReportBuilder
from .report_capture_common import capture_note, capture_row, capture_stored_warnings, capture_table


def capture_quality(
    builder: ReportBuilder,
    session: Session,
    snapshot: PortfolioSnapshotModel,
) -> None:
    selected = report_tables(builder.selection)
    if r.ReportTableKey.RECONCILIATION not in selected:
        return
    cutoff = builder.selection.source_cutoff_at
    run = session.scalar(
        select(ReconciliationRunModel)
        .where(
            ReconciliationRunModel.broker_account_id == snapshot.broker_account_id,
            ReconciliationRunModel.created_at <= cutoff,
            ReconciliationRunModel.as_of <= cutoff,
            ReconciliationRunModel.coverage_start_at <= snapshot.valuation_at,
            ReconciliationRunModel.coverage_end_at >= snapshot.valuation_at,
        )
        .order_by(ReconciliationRunModel.as_of.desc(), ReconciliationRunModel.id.desc())
        .limit(1)
    )
    context = r.ReportContext(
        key="context.reconciliation",
        family=r.ReportFamily.RECONCILIATION,
        method_key="snapshot_reconciliation" if run is None else run.algorithm_version,
        method_version="1.0.0" if run is None else run.tolerance_version,
        valuation_at=snapshot.valuation_at,
        source_cutoff_at=cutoff,
        source_at=None if run is None else run.as_of,
        quality=QualityState.PARTIAL if run is None else QualityState(run.quality_state),
        provenance_set_key="sources.reconciliation",
        coverage_set_key="coverage.reconciliation",
        note_set_key="notes.reconciliation",
        reconciliation_key="reconciliation.snapshot",
    )
    builder.add_context(context)
    if run is None:
        builder.add_reconciliation(
            r.ReportReconciliationBinding(
                key="reconciliation.snapshot",
                absent=True,
            )
        )
        capture_note(
            builder,
            context,
            key="reconciliation.absent",
            text="No reconciliation observed by the cutoff covers this snapshot valuation.",
            kind=r.ReportNoteKind.RECONCILIATION,
            code="not_evaluated",
        )
    else:
        fingerprint = digest(
            (
                run.id,
                run.as_of,
                run.algorithm_version,
                run.tolerance_version,
                run.input_fingerprint,
                run.status,
                run.quality_state,
                run.coverage_start_at,
                run.coverage_end_at,
                run.coverage_complete,
                run.coverage_gaps,
                run.discrepancy_count,
                run.warnings,
                run.provenance,
            )
        )
        builder.add_reconciliation(
            r.ReportReconciliationBinding(
                key="reconciliation.snapshot",
                absent=False,
                run_id=run.id,
                content_digest=fingerprint,
            )
        )
        builder.add_binding(
            r.ReportBinding(
                family=context.family,
                role=r.ReportInputRole.RECONCILIATION,
                subject_id=run.id,
                content_digest=fingerprint,
            )
        )
        builder.add_reference(
            r.ReportSourceReference(
                key=f"reconciliation.{run.id}",
                kind=r.ReportSourceKind.RECONCILIATION,
                subject_id=run.id,
                content_digest=fingerprint,
                source_at=run.as_of,
                first_observed_at=run.created_at,
            ),
            provenance_set_key=context.provenance_set_key,
        )
        builder.add_coverage(
            r.ReportCoverageFact(
                set_key=context.coverage_set_key,
                family=context.family,
                metric_key="complete",
                value=r.ReportCell(
                    kind=r.CellKind.BOOLEAN, value=run.coverage_complete, context_key=context.key
                ),
            )
        )
        for ordinal, gap in enumerate(run.coverage_gaps):
            capture_note(builder, context, key=f"reconciliation.gap.{ordinal}", text=gap)
        capture_stored_warnings(builder, context, run.warnings, key="reconciliation.warning")
    # Family identity includes the actual reconciliation or explicit absence.
    snapshot_context = builder.contexts["context.snapshot"]
    builder.contexts[snapshot_context.key] = replace(
        snapshot_context,
        reconciliation_key=context.reconciliation_key,
    )
    row = capture_row(
        builder,
        context,
        r.ReportTableKey.RECONCILIATION,
        key="reconciliation.summary",
        values={
            "reconciliation_run_id": None if run is None else run.id,
            "status": "not_evaluated" if run is None else run.status,
            "evaluated_at": None if run is None else run.as_of,
            "algorithm_version": None if run is None else run.algorithm_version,
            "tolerance_version": None if run is None else run.tolerance_version,
            "discrepancy_count": 0 if run is None else run.discrepancy_count,
            "absent": run is None,
        },
    )
    capture_table(builder, r.ReportTableKey.RECONCILIATION, (row,))

    def issues() -> Iterator[r.ReportRow]:
        if run is None:
            return
        query = (
            select(ReconciliationDiscrepancyModel)
            .where(
                ReconciliationDiscrepancyModel.reconciliation_run_id == run.id,
                ReconciliationDiscrepancyModel.broker_account_id == snapshot.broker_account_id,
                ReconciliationDiscrepancyModel.created_at <= cutoff,
            )
            .order_by(ReconciliationDiscrepancyModel.id)
            .limit(r.MAX_REPORT_DATASET_ROWS + 1)
        )
        for index, issue in enumerate(session.scalars(query).yield_per(256)):
            r.report_limit(index < r.MAX_REPORT_DATASET_ROWS, "reconciliation_issues")
            unavailable = issue.last_seen_at > cutoff or (
                issue.resolved_at is not None and issue.resolved_at > cutoff
            )
            reason = (
                "This mutable discrepancy changed after the selected cutoff; "
                "its earlier values are unavailable."
            )
            yield capture_row(
                builder,
                context,
                r.ReportTableKey.RECONCILIATION_ISSUES,
                key=f"reconciliation.issue.{issue.id}",
                values={
                    "issue_id": issue.id,
                    "type": issue.discrepancy_type,
                    "severity": None if unavailable else issue.severity,
                    "status": None if unavailable else issue.resolution_state,
                    "summary": None if unavailable else issue.downstream_effect,
                    "expected": None if unavailable else issue.expected_value,
                    "observed": None if unavailable else issue.observed_value,
                    "residual": None if unavailable else issue.residual,
                    "tolerance": None if unavailable else issue.tolerance,
                    "currency": None if unavailable else issue.currency,
                },
                reasons={
                    name: reason
                    for name in (
                        "severity",
                        "status",
                        "summary",
                        "expected",
                        "observed",
                        "residual",
                        "tolerance",
                        "currency",
                    )
                }
                if unavailable
                else None,
            )

    capture_table(builder, r.ReportTableKey.RECONCILIATION_ISSUES, issues())


def capture_quality_tables(builder: ReportBuilder) -> None:
    """Render shared proof only after all families have contributed their facts."""
    if r.ReportTableKey.COVERAGE not in report_tables(builder.selection):
        return
    context = builder.contexts["context.snapshot"]
    rows = (
        capture_row(
            builder,
            context,
            r.ReportTableKey.COVERAGE,
            key=f"coverage.{fact.set_key}.{fact.metric_key}",
            values={"family": fact.family, "coverage_key": fact.metric_key, "metric": fact.value},
        )
        for fact in sorted(
            builder.coverage, key=lambda fact: (fact.family.value, fact.set_key, fact.metric_key)
        )
        if fact.value.kind in {r.CellKind.DECIMAL, r.CellKind.INTEGER, r.CellKind.BOOLEAN}
    )
    capture_table(builder, r.ReportTableKey.COVERAGE, rows)
    note_rows = (
        capture_row(
            builder,
            context,
            r.ReportTableKey.NOTES,
            key=note.key,
            values={
                "note_key": note.key,
                "kind": note.kind,
                "family": note.family,
                "code": note.code,
                "text": note.text,
                "related_provenance_set_key": note.related_provenance_set_key,
            },
        )
        for note in sorted(builder.notes.values(), key=lambda note: (note.family.value, note.key))
    )
    capture_table(builder, r.ReportTableKey.NOTES, note_rows)
