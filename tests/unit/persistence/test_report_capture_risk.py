"""Risk reports preserve canonical numbers, missing states and every retained trace row."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_analytics.risk import calculate_risk
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_risk_schema import RISK_PROOF_TABLES, RISK_REPORT_TABLES
from trading212_domain.report_schema import table_schema
from trading212_domain.risk import RiskMetric, RiskReason
from trading212_domain.risk_execution import RiskExecutionInput
from trading212_domain.risk_history import RiskAssetSource
from trading212_domain.risk_result import RiskCalculation
from trading212_domain.risk_serialization import risk_result_digest
from trading212_persistence.historical_base import digest
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_capture_risk import (
    RiskReportMetadata,
    project_risk,
    risk_metric_cell,
)
from trading212_persistence.report_capture_risk_proof import capture_risk_trace

from tests.unit.analytics.historical_factories import fixture as history_fixture
from tests.unit.analytics.historical_factories import with_fx
from tests.unit.analytics.source_factories import USD
from tests.unit.analytics.test_risk_history import definition
from tests.unit.analytics.test_risk_result import source_fixture
from tests.unit.domain.report_factories import selection
from tests.unit.persistence.test_report_capture_builder import Sink

pytestmark = pytest.mark.unit


def captured_input(
    *, asset: bool = False, fx: bool = False
) -> tuple[ReportBuilder, Sink, RiskCalculation, RiskExecutionInput, RiskReportMetadata]:
    assets: tuple[RiskAssetSource, ...]
    if asset:
        history, mapping = source_fixture()
        assets = (mapping,)
    elif fx:
        history = with_fx(
            history_fixture(("100",) * 4, currency=USD), (".90", ".90", ".99", ".99"), base=USD
        )
        assets = ()
    else:
        history, assets = history_fixture(("100",) * 22), ()
    policy = definition(history)
    value = calculate_risk(history, policy, assets=assets)
    window = history.selection.window
    created = window.source_cutoff_at + timedelta(days=1)
    metadata = RiskReportMetadata(
        run_id=UUID(int=101),
        result_id=UUID(int=102),
        result_digest=risk_result_digest(value),
        definition_id=UUID(int=103),
        definition_version_id=UUID(int=104),
        definition_version_number=1,
        definition_digest=digest(policy),
        portfolio_snapshot_id=UUID(int=105),
        historical_input_snapshot_id=UUID(int=106),
        benchmark_version_id=None,
        xray_run_id=None,
        xray_input_id=None,
        xray_input_digest=None,
        created_at=created,
        completed_at=created + timedelta(seconds=1),
        expires_at=created + timedelta(days=7),
    )
    original = selection()
    chosen = replace(
        original,
        account_id=UUID(history.account_id),
        snapshot_id=metadata.portfolio_snapshot_id,
        start_date=window.start_date,
        end_date=window.end_date,
        source_cutoff_at=window.source_cutoff_at,
        reporting_currency=window.reporting_currency,
        risk_run_id=metadata.run_id,
        sections=(*original.sections, r.ReportSection.RISK),
    )
    execution = RiskExecutionInput(
        historical=history,
        definition=policy,
        assets=assets,
        xray=None,
        input_digest="a" * 64,
        expires_at=created + timedelta(days=3),
    )
    sink = Sink()
    builder = ReportBuilder(
        chosen, owner_id=UUID(history.owner_id), valuation_at=window.end_at, sink=sink
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


def test_exact_observed_zero_unavailable_reason_and_structurally_absent_tail_mass() -> None:
    builder, sink, value, execution, metadata = captured_input()
    contexts = project_risk(builder, value, execution, metadata)
    builder.complete_proof_tables()
    assert set((*RISK_REPORT_TABLES, *RISK_PROOF_TABLES)) <= set(builder.descriptors)
    assert builder.descriptors[r.ReportTableKey.RISK_MATRIX_AXES_V1].row_count == 0
    assert builder.descriptors[r.ReportTableKey.RISK_MATRIX_CELLS_V1].row_count == 0
    assert builder.descriptors[r.ReportTableKey.RISK_COMPONENTS_V1].row_count == 0
    assert builder.descriptors[r.ReportTableKey.RISK_RUN_ASSETS_V1].row_count == 0
    assert builder.descriptors[r.ReportTableKey.RISK_XRAY_PATHS_V1].row_count == 0
    observed = cells(sink.chunks, r.ReportTableKey.RISK_OBSERVED_V1)[0]
    assert observed["volatility_annualized"].value == Decimal(0)
    assert observed["volatility_annualized"].state is r.CellState.AVAILABLE
    assert observed["volatility_annualized"].bound_key is not None
    assert (
        builder.bounds[observed["volatility_annualized"].bound_key].kind is r.ReportBoundKind.EXACT
    )
    assert observed["beta"].value is None
    assert observed["beta"].reason_key is not None
    assert builder.notes[observed["beta"].reason_key].code == value.observed.beta.reason
    assert observed["beta"].bound_key is not None
    assert builder.bounds[observed["beta"].bound_key].kind is r.ReportBoundKind.UNAVAILABLE
    drawdown = observed["maximum_drawdown"]
    assert drawdown.context_key == contexts.historical.key
    assert drawdown.value == value.history.maximum_drawdown.value
    assert drawdown.method_key == value.history.canonical_performance_context.method.name
    assert drawdown.origin is not None
    assert drawdown.origin.value == value.history.maximum_drawdown.origin.value
    tails = cells(sink.chunks, r.ReportTableKey.RISK_TAILS_V1)
    assert tails[0]["tail_mass"].value == value.historical_tail.tail_mass
    assert tails[1]["tail_mass"].state is r.CellState.NOT_APPLICABLE
    assert tails[1]["tail_mass"].reason_key is None
    historical_var = tails[0]["value_at_risk"]
    assert historical_var.reason_key is not None
    assert builder.notes[historical_var.reason_key].code == RiskReason.INSUFFICIENT_TAIL
    assert builder.copy_expires_at == execution.expires_at
    assert value.history.maximum_drawdown.value == drawdown.value


def test_full_series_matrix_and_source_trace_copy_without_preview_filtering() -> None:
    builder, sink, value, execution, metadata = captured_input(asset=True)
    digest_before = risk_result_digest(value)
    project_risk(builder, value, execution, metadata)
    builder.complete_proof_tables()
    matrix = cells(sink.chunks, r.ReportTableKey.RISK_MATRIX_CELLS_V1)
    assert len(matrix) == len(value.matrix.keys) ** 2
    for i, row_key in enumerate(value.matrix.keys):
        for j, column_key in enumerate(value.matrix.keys):
            row = matrix[i * len(value.matrix.keys) + j]
            assert row["row_instrument_id"].value == row_key
            assert row["column_instrument_id"].value == column_key
            assert row["covariance_periodic"].value == value.matrix.covariance_periodic[i][j].value
            assert (
                row["regularized_covariance_periodic"].value
                == value.matrix.regularized_covariance_periodic[i][j].value
            )
            assert row["correlation"].value == value.matrix.correlation[i][j].value
    retained = (value.history.portfolio, *value.history.assets)
    intervals = cells(sink.chunks, r.ReportTableKey.RISK_INTERVALS_V1)
    assert len(intervals) == sum(len(series.intervals) for series in retained)
    assert [
        (row["series_key"].value, row["simple_return"].value, row["quality"].value)
        for row in intervals
    ] == [
        (series.key, interval.simple_return, interval.quality.value)
        for series in retained
        for interval in series.intervals
    ]
    consumers = cells(sink.chunks, r.ReportTableKey.HISTORICAL_USE_CONSUMERS)
    assert [row["use_key"].value for row in consumers] == [
        use.use_key for use in value.history.source_uses
    ]
    conversions = cells(sink.chunks, r.ReportTableKey.HISTORICAL_CONVERSION_USES)
    assert [(row["conversion_key"].value, row["rate"].value) for row in conversions] == [
        (conversion.conversion_key, conversion.rate) for conversion in value.history.conversions
    ]
    assert risk_result_digest(value) == digest_before
    assert [
        (pin.role, pin.subject_id, pin.parent_id, pin.content_digest)
        for pin in builder.bindings
        if pin.family is r.ReportFamily.RISK
    ] == [
        (r.ReportInputRole.INPUT, metadata.run_id, None, execution.input_digest),
        (r.ReportInputRole.RESULT, metadata.result_id, metadata.run_id, metadata.result_digest),
        (
            r.ReportInputRole.POLICY,
            metadata.definition_version_id,
            metadata.definition_id,
            metadata.definition_digest,
        ),
    ]


@pytest.mark.parametrize("available", [False, True])
def test_partial_concentration_cell_points_to_its_exact_bound_fact(available: bool) -> None:
    builder, _, value, execution, metadata = captured_input()
    contexts = project_risk(builder, value, execution, metadata)
    metric = RiskMetric(value=Decimal(".25")) if available else value.concentration.hhi
    cell = risk_metric_cell(
        builder,
        contexts.concentration,
        key="risk.partial_hhi",
        value=metric,
        role=r.DecimalRole.SCORE,
        lower_bound=True,
    )
    assert cell.bound_key == "risk.partial_hhi"
    fact = builder.bounds[cell.bound_key]
    assert fact.kind is (
        r.ReportBoundKind.LOWER_BOUND if available else r.ReportBoundKind.UNAVAILABLE
    )
    assert fact.quantum == Decimal("1e-18") and fact.rounding == "ROUND_HALF_EVEN"


@pytest.mark.parametrize("field", ["snapshot", "owner", "cutoff", "digest", "definition"])
def test_foreign_or_changed_risk_inputs_fail_before_any_report_row(field: str) -> None:
    builder, sink, value, execution, metadata = captured_input()
    if field == "snapshot":
        metadata = replace(metadata, portfolio_snapshot_id=UUID(int=999))
    elif field == "owner":
        builder.owner_id = UUID(int=999)
    elif field == "cutoff":
        builder.selection = replace(
            builder.selection,
            source_cutoff_at=builder.selection.source_cutoff_at + timedelta(days=1),
        )
    elif field == "digest":
        metadata = replace(metadata, result_digest="f" * 64)
    else:
        metadata = replace(metadata, definition_digest="f" * 64)
    with pytest.raises(DomainError):
        project_risk(builder, value, execution, metadata)
    assert not sink.chunks and not builder.contexts


def test_broken_conversion_lineage_and_trace_bound_reject_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder, _, value, execution, metadata = captured_input(fx=True)
    contexts = project_risk(builder, value, execution, metadata)
    by_key = {use.use_key: use for use in value.history.source_uses}
    leg = next(key for conversion in value.history.conversions for key in conversion.leg_use_keys)
    broken = replace(
        value.history, source_uses=tuple(use for key, use in by_key.items() if key != leg)
    )
    second, sink, _, _, _ = captured_input()
    with pytest.raises(DomainError):
        capture_risk_trace(second, contexts.historical, broken)
    assert not sink.chunks and not second.proof_table_keys
    monkeypatch.setattr(r, "MAX_REPORT_DATASET_ROWS", len(value.history.source_uses) - 1)
    with pytest.raises(DomainError):
        capture_risk_trace(second, contexts.historical, value.history)
    assert not sink.chunks and not second.proof_table_keys


@pytest.mark.parametrize("unavailable", [False, True])
def test_xray_proof_namespaces_preserve_legacy_keys_and_allow_mixed_selected_runs(
    unavailable: bool,
) -> None:
    from trading212_analytics.xray import calculate_xray
    from trading212_persistence.report_capture_xray import _input_proof, _result_proof
    from trading212_persistence.report_capture_xray_proof import capture_xray_semantics

    from tests.unit.analytics.xray_factories import Builder, uid
    from tests.unit.persistence.test_report_canonical_capture import xray_builder

    fixture = Builder()
    fixture.position(uid(10), None if unavailable else "100")
    fixture.identity(uid(10), uid(110))
    fixture.classifications_for(uid(110))
    source = fixture.finish()
    result = calculate_xray(source)
    builder, sink, legacy = xray_builder(source)
    premium = replace(
        legacy,
        key="risk.selected.xray",
        provenance_set_key="risk.selected.xray.sources",
        coverage_set_key="risk.selected.xray.coverage",
        note_set_key="risk.selected.xray.notes",
    )
    builder.add_context(premium)
    for context in (legacy, premium):
        _input_proof(builder, context, source)
        _result_proof(builder, context, result)
        capture_xray_semantics(builder, context, source, result)
    builder.complete_proof_tables()
    legacy_rows = [
        row for chunk in sink.chunks for row in chunk.rows if row.context_key == legacy.key
    ]
    premium_rows = [
        row for chunk in sink.chunks for row in chunk.rows if row.context_key == premium.key
    ]
    assert legacy_rows and len(legacy_rows) == len(premium_rows)
    assert all(row.key.startswith("xray.") for row in legacy_rows)
    assert all(row.key.startswith("risk.selected.xray.") for row in premium_rows)
    assert {row.key for row in legacy_rows}.isdisjoint(row.key for row in premium_rows)
    assert {row.key.removeprefix("xray.") for row in legacy_rows} == {
        row.key.removeprefix("risk.selected.xray.") for row in premium_rows
    }
    relations = cells(sink.chunks, r.ReportTableKey.XRAY_PATH_RELATIONS)
    assert all(
        row["referenced_key"].value in {item.key for item in (*legacy_rows, *premium_rows)}
        for row in relations
        if row["relation_kind"].value == "fund_edge"
    )
    if unavailable:
        # Literal V1 identity is independent of the current key-building implementation.
        old = builder.notes["xray.reason.missing_fx"]
        new = builder.notes["risk.selected.xray.reason.missing_fx"]
        assert old.related_provenance_set_key == "xray.sources"
        assert new.related_provenance_set_key == "risk.selected.xray.sources"
        assert old.code == new.code == "missing_fx"


def test_selected_xray_paths_complete_the_risk_proof_after_ordinary_xray_table_is_closed() -> None:
    from trading212_analytics.xray import calculate_xray
    from trading212_domain import xray as x
    from trading212_persistence.report_capture_risk_xray import capture_risk_xray_paths
    from trading212_persistence.report_capture_xray import _result_proof, project_xray

    from tests.unit.analytics.xray_factories import Builder, uid
    from tests.unit.persistence.test_report_canonical_capture import xray_builder

    fixture = Builder()
    fixture.position(uid(10), "30")
    fixture.identity(uid(10), uid(110))
    fixture.classifications_for(uid(110))
    fixture.position(uid(20), "60")
    fixture.fund(uid(20), ((uid(10), ".5"), (uid(11), ".5")))
    fixture.cash_row("10")
    source = fixture.finish()
    result = calculate_xray(source)
    original_digest = result.content_digest
    prior, _, legacy = xray_builder(source)
    report_selection = r.ReportSelection(
        account_id=source.account_id,
        snapshot_id=source.snapshot_id,
        start_date=prior.selection.start_date,
        end_date=prior.selection.end_date,
        source_cutoff_at=source.source_cutoff_at.value,
        reporting_currency=source.reporting_currency,
        report_type=r.ReportType.PORTFOLIO_SUMMARY,
        sections=(
            r.ReportSection.OVERVIEW,
            r.ReportSection.ALLOCATION,
            r.ReportSection.QUALITY,
            r.ReportSection.XRAY,
            r.ReportSection.RISK,
        ),
        formats=(r.ReportFormat.JSON,),
        risk_run_id=uid(700),
    )
    sink = Sink()
    builder = ReportBuilder(
        report_selection,
        owner_id=source.owner_id,
        valuation_at=source.valuation_at.value,
        sink=sink,
    )
    legacy = replace(legacy, schema_version="2.0.0")
    builder.add_context(legacy)
    for reference in prior.references.values():
        builder.add_reference(reference, provenance_set_key=legacy.provenance_set_key)
    project_xray(
        builder,
        legacy,
        source,
        result,
        instrument_name=str,
        entity_name=str,
    )
    original_descriptor = builder.descriptors[r.ReportTableKey.XRAY_PATHS]
    premium = replace(
        legacy,
        key=f"risk.{uid(700)}.observed.xray",
        provenance_set_key=f"risk.{uid(700)}.observed.xray.sources",
        coverage_set_key=f"risk.{uid(700)}.observed.xray.coverage",
        note_set_key=f"risk.{uid(700)}.observed.xray.notes",
    )
    builder.add_context(premium)
    _result_proof(builder, premium, result)
    capture_risk_xray_paths(builder, premium, source, result)
    builder.complete_proof_tables()
    assert builder.descriptors[r.ReportTableKey.XRAY_PATHS] == original_descriptor
    descriptor = builder.descriptors[r.ReportTableKey.RISK_XRAY_PATHS_V1]
    assert descriptor.section is None and descriptor.row_count == len(result.terminal_paths)
    retained = cells(sink.chunks, r.ReportTableKey.RISK_XRAY_PATHS_V1)
    assert [row["key"].value for row in retained] == [path.key for path in result.terminal_paths]
    for row, path in zip(retained, result.terminal_paths, strict=True):
        for field in (
            "root_key",
            "instrument_id",
            "entity_id",
            "explicit_cash",
            "unresolved_reason",
        ):
            expected = getattr(path, field)
            if isinstance(expected, UUID):
                expected = str(expected)
            assert row[field].value == expected
        assert row["reporting_value"].value == (
            None if path.reporting_value.value is None else path.reporting_value.value.amount
        )
        for field in ("absolute_weight", "relative_weight"):
            metric, cell = getattr(path, field), row[field]
            assert cell.value == metric.value and cell.state.value == metric.availability.value
            assert (cell.quality or premium.quality) == metric.quality
            assert cell.confidence == metric.confidence
            if metric.reason is not None:
                assert cell.reason_key is not None
                assert builder.notes[cell.reason_key].code == metric.reason.value
            assert cell.bound_key is not None
        assert row["normalized_known_weight"].value == next(
            item.normalized_known_weight.value
            for item in path.dimension_weights
            if item.dimension is x.XrayDimension.COMPANY
        )
    assert any(row["explicit_cash"].value for row in retained)
    assert any(row["unresolved_reason"].value is not None for row in retained)
    path_keys = {row["key"].value for row in retained}
    for chunk in sink.chunks:
        if chunk.table is r.ReportTableKey.XRAY_PATH_RELATIONS:
            assert all(
                row.cells[0].value in path_keys
                for row in chunk.rows
                if row.context_key == premium.key
            )
    assert result.content_digest == original_digest
