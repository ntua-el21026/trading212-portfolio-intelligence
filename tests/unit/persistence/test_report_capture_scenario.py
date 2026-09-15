"""Scenario report financial parity and complete proof, independent of the public DTO."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_analytics.scenario import calculate_scenario
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.report_scenario_schema import SCENARIO_PROOF_TABLES, SCENARIO_REPORT_TABLES
from trading212_domain.report_schema import table_schema
from trading212_domain.report_v3 import ReportScenarioRunSelection, ReportSelectionV3
from trading212_domain.scenario import ScenarioReason
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_domain.scenario_result import ScenarioCalculation, ScenarioMoneyMetric
from trading212_domain.scenario_serialization import scenario_result_digest
from trading212_domain.sources import ObservationState
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_capture_scenario import (
    ScenarioReportMetadata,
    project_scenario,
    scenario_report_binding,
    scenario_report_context,
)
from trading212_persistence.report_capture_scenario_cells import ScenarioReportWriter
from trading212_persistence.report_capture_scenario_proof import (
    ScenarioSourceHeader,
    capture_scenario_source_headers,
)
from trading212_persistence.report_capture_scenario_sources import capture_scenario_xray_paths
from trading212_persistence.report_capture_scenario_trace import capture_scenario_trace
from trading212_persistence.report_capture_xray import _SOURCE_KINDS

from tests.unit.analytics.scenario_factories import (
    content,
    input_for,
    portfolio,
    price,
    rate,
    with_observation,
)
from tests.unit.analytics.test_scenario_replay import _execution as replay_execution
from tests.unit.analytics.xray_factories import uid
from tests.unit.domain.scenario_factories import sensitivity_capture

pytestmark = pytest.mark.unit


class Sink:
    def __init__(self) -> None:
        self.chunks: list[r.ReportChunk] = []

    def append(self, chunk: r.ReportChunk) -> None:
        self.chunks.append(chunk)

    def finish(self, summary: object) -> None:
        pass


def prepared(
    execution: ScenarioExecutionInput | None = None,
) -> tuple[
    ReportBuilder, Sink, ScenarioCalculation, ScenarioExecutionInput, ScenarioReportMetadata
]:
    execution = (
        input_for(portfolio(), content(price(10, "-.2"), price(11, ".1")))
        if execution is None
        else execution
    )
    value = calculate_scenario(execution)
    metadata = ScenarioReportMetadata(
        run_id=uid(8101),
        result_id=uid(8102),
        result_digest=scenario_result_digest(value),
        scenario_version_number=1,
        created_at=execution.pins.source_cutoff_at,
        completed_at=execution.pins.source_cutoff_at + timedelta(seconds=1),
        expires_at=execution.expires_at,
    )
    selection = ReportSelectionV3(
        account_id=execution.pins.account_id,
        snapshot_id=execution.pins.portfolio_snapshot_id,
        source_cutoff_at=execution.pins.source_cutoff_at,
        reporting_currency=execution.pins.reporting_currency,
        start_date=execution.replay.selection.start_date
        if execution.replay
        else value.valuation_at.date(),
        end_date=execution.replay.selection.end_date
        if execution.replay
        else value.valuation_at.date(),
        report_type=r.ReportType.PORTFOLIO_SUMMARY,
        sections=(
            r.ReportSection.OVERVIEW,
            r.ReportSection.ALLOCATION,
            r.ReportSection.QUALITY,
            r.ReportSection.SCENARIO,
        ),
        formats=tuple(r.ReportFormat),
        premium_run=ReportScenarioRunSelection(run_id=metadata.run_id),
    )
    sink = Sink()
    builder = ReportBuilder(
        selection, owner_id=execution.pins.owner_id, valuation_at=value.valuation_at, sink=sink
    )
    # The pure projection requires the already authorized immutable source graph.
    # These headers correspond to the deterministic X-ray fixture dependencies.
    context = scenario_report_context(value, metadata)
    builder.add_context(context)
    for dependency in execution.xray_input.source_dependencies:
        builder.add_reference(
            r.ReportSourceReference(
                key=f"xray.source.{dependency.id}",
                kind=_SOURCE_KINDS[dependency.reference.kind],
                subject_id=dependency.reference.record_id,
                parent_id=dependency.reference.parent_record_id,
                content_digest=dependency.content_digest,
                source_at=value.valuation_at,
                first_observed_at=value.valuation_at,
                provider_id=None
                if dependency.provider_id is None
                else UUID(dependency.provider_id),
                license_version_id=dependency.license_version_id,
            ),
            provenance_set_key=context.provenance_set_key,
        )
    return builder, sink, value, execution, metadata


def cells(
    chunks: Iterable[r.ReportChunk], table: r.ReportTableKey
) -> list[dict[str, r.ReportCell]]:
    columns = table_schema(table).columns
    return [
        dict(zip((column.key for column in columns), row.cells, strict=True))
        for chunk in chunks
        if chunk.table is table
        for row in chunk.rows
    ]


def complete_owned_tables(
    builder: ReportBuilder,
    value: ScenarioCalculation,
    execution: ScenarioExecutionInput,
    metadata: ScenarioReportMetadata,
) -> None:
    context = project_scenario(builder, value, execution, metadata)
    headers = tuple(
        ScenarioSourceHeader(
            source_kind=kind,
            subject_id=getattr(item, field),
            content_digest=item.content_digest,
            created_at=metadata.created_at - timedelta(days=1),
            expires_at=metadata.expires_at if kind == "scenario_sensitivity_version" else None,
        )
        for kind, items, field in (
            ("scenario_sensitivity_version", execution.sensitivities.versions, "version_id"),
            (
                "scenario_sensitivity_observation",
                execution.sensitivities.observations,
                "observation_id",
            ),
            ("scenario_sensitivity_evidence", execution.sensitivities.evidence, "id"),
        )
        for item in items
    )
    capture_scenario_source_headers(
        ScenarioReportWriter(builder, context), execution.sensitivities, headers
    )
    child = replace(
        context,
        key=f"{context.key}.xray",
        family=r.ReportFamily.XRAY,
        method_key=execution.xray_input.policy.method_name,
        method_version=execution.xray_input.policy.method_version,
    )
    builder.add_context(child)
    capture_scenario_xray_paths(builder, child, execution)
    builder.complete_proof_tables()


def test_all_fixed_tables_exact_money_channels_and_saved_parents_without_risk_pin() -> None:
    builder, sink, value, execution, metadata = prepared()
    before = scenario_result_digest(value)
    complete_owned_tables(builder, value, execution, metadata)
    assert set((*SCENARIO_REPORT_TABLES, *SCENARIO_PROOF_TABLES)) <= set(builder.descriptors)
    actual = cells(sink.chunks, r.ReportTableKey.SCENARIO_SUMMARY_V1)[0]
    assert actual["post_value"].value == Decimal("92")
    assert actual["impact"].value == Decimal("-8")
    assert actual["terminal_pre_value"].value == Decimal("100")
    assert actual["component_sum_residual"].value == Decimal("0")
    for row, component in zip(
        cells(sink.chunks, r.ReportTableKey.SCENARIO_COMPONENTS_V1), value.components, strict=True
    ):
        assert component.post_value.value is not None
        assert row["post_value"].value == component.post_value.value.amount
        assert row["post_value"].currency == execution.pins.reporting_currency
        assert row["post_value"].confidence == component.post_value.confidence
        assert row["path_key"].value == component.exposure.path_key
    channels = cells(sink.chunks, r.ReportTableKey.SCENARIO_CHANNELS_V1)
    assert len(channels) == (len(value.components) + 1) * 4
    assert next(
        row
        for row in channels
        if row["scope"].value == "summary" and row["channel"].value == "price"
    )["effect"].value == Decimal("-8")
    assert all(
        row["ratio"].state is r.CellState.NOT_APPLICABLE
        for row in channels
        if row["channel"].value == "interaction"
    )
    assert builder.descriptors[r.ReportTableKey.SCENARIO_REPLAY_CHANGES_V1].row_count == 0
    assert builder.descriptors[r.ReportTableKey.SCENARIO_SENSITIVITY_OBSERVATIONS_V1].row_count == 0
    assert not any(binding.family is r.ReportFamily.RISK for binding in builder.bindings)
    binding = scenario_report_binding(value, execution, metadata)
    assert binding.run_id == metadata.run_id
    assert binding.xray.input_id == execution.pins.xray_input_id
    assert binding.historical is None
    assert scenario_result_digest(value) == before


def test_missing_coefficient_and_known_zero_effect_keep_distinct_states_and_original_evidence() -> (
    None
):
    source = sensitivity_capture()
    source = with_observation(
        source,
        replace(
            source.observations[0],
            coefficient=None,
            state=ObservationState.MISSING,
            reason=ScenarioReason.MISSING_SENSITIVITY,
            quality=QualityState.PARTIAL,
        ),
    )
    builder, sink, value, execution, metadata = prepared(
        input_for(portfolio(), content(rate(source, "0")), source)
    )
    complete_owned_tables(builder, value, execution, metadata)
    observation = cells(sink.chunks, r.ReportTableKey.SCENARIO_SENSITIVITY_OBSERVATIONS_V1)[0]
    assert observation["coefficient"].value is None
    assert observation["coefficient"].state is r.CellState.UNAVAILABLE
    assert observation["reason"].value == "missing_sensitivity"
    uses = cells(sink.chunks, r.ReportTableKey.SCENARIO_APPLIED_SENSITIVITIES_V1)
    assert uses and all(row["effect_ratio"].value == 0 for row in uses)
    assert all(row["coefficient"].value is None for row in uses)
    members = cells(sink.chunks, r.ReportTableKey.SCENARIO_MEMBERS_V1)
    candidates = [
        row["reference_id"].value
        for row in members
        if row["field"].value == "candidate_observation_ids"
    ]
    assert str(source.observations[0].observation_id) in candidates
    assert builder.descriptors[r.ReportTableKey.SCENARIO_SENSITIVITY_EVIDENCE_V1].row_count == len(
        source.evidence
    )
    assert builder.descriptors[r.ReportTableKey.SCENARIO_SOURCE_HEADERS_V1].row_count == len(
        source.versions
    ) + len(source.observations) + len(source.evidence)


def test_full_replay_trace_preserves_local_and_fx_channels_and_all_use_legs() -> None:
    builder, sink, value, execution, metadata = prepared(replay_execution())
    assert value.replay is not None
    complete_owned_tables(builder, value, execution, metadata)
    changes = cells(sink.chunks, r.ReportTableKey.SCENARIO_REPLAY_CHANGES_V1)
    assert changes[0]["local_return"].value == Decimal("0.2")
    assert changes[0]["fx_return"].value == Decimal("-0.1")
    assert changes[0]["reporting_return"].value == Decimal("0.08")
    assert builder.descriptors[r.ReportTableKey.HISTORICAL_USE_CONSUMERS].row_count == len(
        value.replay.source_uses
    )
    assert builder.descriptors[r.ReportTableKey.HISTORICAL_CONVERSION_USES].row_count == len(
        value.replay.conversions
    )
    assert builder.descriptors[r.ReportTableKey.HISTORICAL_CONVERSION_LEGS].row_count == sum(
        len(item.leg_use_keys) for item in value.replay.conversions
    )
    assert scenario_report_binding(value, execution, metadata).historical is not None


@pytest.mark.parametrize("changed", ["account", "snapshot", "currency", "run", "digest"])
def test_mismatched_selection_fails_before_writing_any_table(changed: str) -> None:
    builder, sink, value, execution, metadata = prepared()
    if changed == "account":
        builder.selection = replace(builder.selection, account_id=uid(9200))
    elif changed == "snapshot":
        builder.selection = replace(builder.selection, snapshot_id=uid(9200))
    elif changed == "currency":
        builder.selection = replace(builder.selection, reporting_currency=CurrencyCode("USD"))
    elif changed == "run":
        metadata = replace(metadata, run_id=uid(9200))
    else:
        metadata = replace(metadata, result_digest="0" * 64)
    with pytest.raises(DomainError):
        project_scenario(builder, value, execution, metadata)
    assert not builder.descriptors and not sink.chunks


def test_metric_missing_and_tiny_values_keep_currency_confidence_and_precise_state() -> None:
    builder, _, value, _, metadata = prepared()
    writer = ScenarioReportWriter(builder, scenario_report_context(value, metadata))
    missing = writer.metric(
        "scenario.test.missing",
        ScenarioMoneyMetric(
            value=None,
            quality=QualityState.PARTIAL,
            reason=ScenarioReason.UNCERTAIN_MONEY,
            confidence=None,
        ),
    )
    assert missing.state is r.CellState.UNAVAILABLE and missing.currency == CurrencyCode("EUR")
    assert (
        missing.reason_key is not None
        and builder.notes[missing.reason_key].code == "uncertain_money"
    )
    tiny = writer.metric(
        "scenario.test.tiny",
        ScenarioMoneyMetric(
            value=Money(Decimal("-0.000000000000000001"), CurrencyCode("EUR")),
            quality=QualityState.ESTIMATED,
            reason=None,
            confidence=Decimal("0.75"),
        ),
    )
    assert tiny.value == Decimal("-0.000000000000000001") and tiny.confidence == Decimal("0.75")
    assert tiny.state is r.CellState.AVAILABLE


def test_whole_document_bound_fails_instead_of_truncating_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder, _, value, execution, metadata = prepared()
    monkeypatch.setattr(r, "MAX_REPORT_DOCUMENT_BYTES", 512)
    with pytest.raises(DomainError) as error:
        project_scenario(builder, value, execution, metadata)
    assert error.value.code is ErrorCode.INPUT_BOUND_EXCEEDED


def test_missing_money_witness_fails_instead_of_inventing_source_membership() -> None:
    builder, _, value, execution, metadata = prepared()
    builder.references.clear()
    with pytest.raises(DomainError, match="source witness"):
        project_scenario(builder, value, execution, metadata)


def test_original_source_header_inventory_rejects_omission() -> None:
    source = sensitivity_capture()
    builder, _, value, execution, metadata = prepared(
        input_for(portfolio(), content(rate(source, ".01")), source)
    )
    writer = ScenarioReportWriter(builder, scenario_report_context(value, metadata))
    with pytest.raises(DomainError, match="header inventory"):
        capture_scenario_source_headers(writer, execution.sensitivities, ())


def test_broken_replay_conversion_leg_rejects_without_public_projection_fallback() -> None:
    builder, _, value, _, metadata = prepared(replay_execution())
    assert value.replay is not None
    proof = value.replay
    # Dataclass validation permits a conversion's own unknown leg keys; the complete
    # capture must still reconcile those against every original observation use.
    broken = replace(
        proof,
        conversions=(
            replace(proof.conversions[0], leg_use_keys=("absent",)),
            *proof.conversions[1:],
        ),
    )
    with pytest.raises(DomainError, match="lineage"):
        capture_scenario_trace(builder, scenario_report_context(value, metadata), broken)


def test_trace_row_bound_rejects_before_emitting_a_partial_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder, sink, value, _, metadata = prepared(replay_execution())
    assert value.replay is not None and value.replay.source_uses
    monkeypatch.setattr(r, "MAX_REPORT_DATASET_ROWS", len(value.replay.source_uses) - 1)
    with pytest.raises(DomainError) as error:
        capture_scenario_trace(builder, scenario_report_context(value, metadata), value.replay)
    assert error.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert not sink.chunks and not builder.proof_table_keys


def test_derived_money_cannot_silently_change_the_reporting_currency() -> None:
    builder, _, value, _, metadata = prepared()
    writer = ScenarioReportWriter(builder, scenario_report_context(value, metadata))
    with pytest.raises(DomainError, match="currency differs"):
        writer.metric(
            "scenario.test.foreign",
            ScenarioMoneyMetric(
                value=Money(Decimal("1"), CurrencyCode("USD")),
                quality=QualityState.FRESH,
                reason=None,
                confidence=None,
            ),
        )


def test_retained_source_count_must_match_the_complete_execution() -> None:
    builder, sink, value, execution, metadata = prepared()
    altered = replace(value, sensitivity_source_row_count=value.sensitivity_source_row_count + 1)
    metadata = replace(metadata, result_digest=scenario_result_digest(altered))
    with pytest.raises(DomainError, match="retained run"):
        project_scenario(builder, altered, execution, metadata)
    assert not sink.chunks and not builder.descriptors
