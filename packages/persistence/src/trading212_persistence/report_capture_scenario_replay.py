"""Scenario replay pins, complete mappings, coverage and unfiltered canonical source use."""

from collections.abc import Iterable

from trading212_domain import reports as r
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import ScenarioCalculation

from .report_capture_common import capture_note
from .report_capture_scenario_cells import ScenarioReportWriter
from .report_capture_scenario_trace import capture_scenario_trace

_REPLAY_TABLES = (
    r.ReportTableKey.SCENARIO_REPLAY_BASIS_V1,
    r.ReportTableKey.SCENARIO_REPLAY_BINDINGS_V1,
    r.ReportTableKey.SCENARIO_REPLAY_METHODS_V1,
    r.ReportTableKey.SCENARIO_REPLAY_COVERAGE_V1,
    r.ReportTableKey.SCENARIO_REPLAY_WARNINGS_V1,
)


def capture_scenario_replay(
    writer: ScenarioReportWriter, value: ScenarioCalculation, execution: ScenarioExecutionInput
) -> None:
    saved, replay = execution.replay, value.replay
    if saved is None or replay is None:
        for table in (*_REPLAY_TABLES, r.ReportTableKey.SCENARIO_REPLAY_CHANGES_V1):
            writer.table(table, (), analytical=table is r.ReportTableKey.SCENARIO_REPLAY_CHANGES_V1)
        return
    context, window, selected = replay.context, replay.context.window, replay.selection
    writer.table(
        r.ReportTableKey.SCENARIO_REPLAY_BASIS_V1,
        (
            writer.row(
                r.ReportTableKey.SCENARIO_REPLAY_BASIS_V1,
                extra={
                    "historical_input_snapshot_id": selected.historical_input_snapshot_id,
                    "historical_input_digest": saved.historical_input_digest,
                    "start_date": selected.start_date,
                    "end_date": selected.end_date,
                    "market_knowledge_cutoff_at": selected.market_knowledge_cutoff_at,
                    "holdings_basis": selected.holdings_basis,
                    "knowledge_basis": selected.knowledge_basis,
                    "holdings_evidence_at": replay.holdings_evidence_at,
                    "holdings_knowledge_cutoff_at": replay.holdings_knowledge_cutoff_at,
                    "context_input_digest": context.input_digest,
                    "account_id": context.account_id,
                    "reporting_currency": window.reporting_currency.value,
                    "coverage_policy": window.coverage_policy,
                    "knowledge_policy": window.knowledge_policy,
                    "method_name": context.method.name,
                    "method_version": context.method.version,
                    "source_policy_version": context.source_policy_version,
                    "accounting_policy_version": context.accounting_policy_version,
                    "quality": context.quality,
                    "availability": context.availability,
                    "reconstruction": context.reconstruction,
                    "schema_version": context.schema_version,
                },
            ),
        ),
    )

    def bindings() -> Iterable[r.ReportRow]:
        for ordinal, item in enumerate(saved.market_bindings):
            row = writer.row(
                r.ReportTableKey.SCENARIO_REPLAY_BINDINGS_V1,
                ordinal,
                item,
                extra={
                    "ordinal": ordinal,
                    "local_currency": None
                    if item.local_currency is None
                    else item.local_currency.value,
                },
            )
            writer.members(
                "replay_binding", row.key, "source_reference_ids", item.source_reference_ids
            )
            yield row

    writer.table(r.ReportTableKey.SCENARIO_REPLAY_BINDINGS_V1, bindings())
    writer.table(
        r.ReportTableKey.SCENARIO_REPLAY_METHODS_V1,
        (
            writer.row(
                r.ReportTableKey.SCENARIO_REPLAY_METHODS_V1,
                ordinal,
                extra={"ordinal": ordinal, "name": method.name, "version": method.version},
            )
            for ordinal, method in enumerate(context.primitive_methods)
        ),
    )

    def coverage() -> Iterable[r.ReportRow]:
        for ordinal, item in enumerate(context.coverage.measures):
            row = writer.row(
                r.ReportTableKey.SCENARIO_REPLAY_COVERAGE_V1,
                ordinal,
                extra={
                    "ordinal": ordinal,
                    "coverage_key": item.key,
                    "expected_count": item.expected_count,
                    "available_count": item.available_count,
                    "complete": item.complete,
                },
            )
            writer.members("replay_coverage", row.key, "reasons", item.reasons)
            yield row

    writer.table(r.ReportTableKey.SCENARIO_REPLAY_COVERAGE_V1, coverage())

    def warnings() -> Iterable[r.ReportRow]:
        for ordinal, warning in enumerate(context.warnings):
            row = writer.row(
                r.ReportTableKey.SCENARIO_REPLAY_WARNINGS_V1,
                ordinal,
                extra={
                    "ordinal": ordinal,
                    "reason_code": warning.reason_code,
                    "coverage_key": warning.coverage_key,
                },
            )
            writer.members("replay_warning", row.key, "reference_ids", warning.reference_ids)
            yield row

    writer.table(r.ReportTableKey.SCENARIO_REPLAY_WARNINGS_V1, warnings())

    def changes() -> Iterable[r.ReportRow]:
        for ordinal, change in enumerate(replay.changes):
            row = writer.row(
                r.ReportTableKey.SCENARIO_REPLAY_CHANGES_V1,
                ordinal,
                change,
                extra={"ordinal": ordinal},
            )
            writer.members("replay_change", row.key, "source_use_keys", change.source_use_keys)
            writer.members("replay_change", row.key, "conversion_keys", change.conversion_keys)
            yield row

    writer.table(r.ReportTableKey.SCENARIO_REPLAY_CHANGES_V1, changes(), analytical=True)
    writer.members(
        "replay_context",
        writer.key(r.ReportTableKey.SCENARIO_REPLAY_BASIS_V1),
        "assumptions",
        context.assumptions,
    )
    writer.members(
        "replay_context",
        writer.key(r.ReportTableKey.SCENARIO_REPLAY_BASIS_V1),
        "source_reference_ids",
        (f"historical.source.{source.kind}.{source.id}" for source in context.sources),
    )
    history_key = f"{writer.context.key}.history"
    history = r.ReportContext(
        key=history_key,
        family=r.ReportFamily.PERFORMANCE,
        method_key=context.method.name,
        method_version=context.method.version,
        valuation_at=window.end_at,
        source_cutoff_at=window.source_cutoff_at,
        quality=context.quality,
        provenance_set_key=f"{history_key}.sources",
        coverage_set_key=f"{history_key}.coverage",
        note_set_key=f"{history_key}.notes",
        schema_version="3.0.0",
    )
    writer.builder.add_context(history)
    for ordinal, assumption in enumerate(context.assumptions):
        capture_note(
            writer.builder,
            history,
            key=f"{history_key}.assumption.{ordinal}",
            text=assumption,
            code="canonical_method_assumption",
            kind=r.ReportNoteKind.ASSUMPTION,
        )
    writer.builder.add_binding(
        r.ReportBinding(
            family=r.ReportFamily.PERFORMANCE,
            role=r.ReportInputRole.INPUT,
            subject_id=selected.historical_input_snapshot_id,
            content_digest=saved.historical_input_digest,
            method_key=context.method.name,
            method_version=context.method.version,
        )
    )
    capture_scenario_trace(writer.builder, history, replay)
