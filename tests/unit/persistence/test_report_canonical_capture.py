"""Pure capture projections against actual canonical kernels, without a database."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_analytics.historical import calculate_income, calculate_performance
from trading212_analytics.xray import calculate_xray
from trading212_domain import historical as h
from trading212_domain import historical_results as hr
from trading212_domain import reports as r
from trading212_domain import xray as x
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import (
    build_report_manifest,
    decode_report_manifest,
    encode_report_manifest,
    report_table_digest,
    validate_report_references,
)
from trading212_domain.report_schema import table_schema
from trading212_domain.sources import LicensePermission
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_capture_common import capture_row
from trading212_persistence.report_capture_historical import (
    HistoricalEventLabels,
    _context,
    project_historical,
)
from trading212_persistence.report_capture_xray import (
    _SOURCE_KINDS,
    _metric,
    _source_key,
    project_xray,
)

from tests.unit.analytics.historical_factories import fixture as historical_fixture
from tests.unit.analytics.historical_factories import with_events
from tests.unit.analytics.xray_factories import Builder, uid

pytestmark = pytest.mark.unit


class CaptureSink:
    def __init__(self) -> None:
        self.chunks: list[r.ReportChunk] = []

    def append(self, chunk: r.ReportChunk) -> None:
        self.chunks.append(chunk)

    def finish(self, summary: r.ReportCaptureSummary) -> None:
        raise AssertionError("A canonical adapter must not seal the service-owned sink")


def decoded_rows(sink: CaptureSink, table: r.ReportTableKey) -> list[dict[str, r.ReportCell]]:
    keys = tuple(item.key for item in table_schema(table).columns)
    return [
        dict(zip(keys, row.cells, strict=True))
        for chunk in sink.chunks
        if chunk.table is table
        for row in chunk.rows
    ]


def xray_builder(value: x.XrayInput) -> tuple[ReportBuilder, CaptureSink, r.ReportContext]:
    sink = CaptureSink()
    selection = r.ExportSelection(
        account_id=value.account_id,
        snapshot_id=value.snapshot_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        source_cutoff_at=value.source_cutoff_at.value,
        reporting_currency=value.reporting_currency,
        dataset=r.ExportDataset.XRAY,
        field_set=r.ExportFieldSet.AUDIT,
        format=r.ExportFormat.JSON,
    )
    builder = ReportBuilder(
        selection, owner_id=value.owner_id, valuation_at=value.valuation_at.value, sink=sink
    )
    context = r.ReportContext(
        key="xray",
        family=r.ReportFamily.XRAY,
        method_key=value.policy.method_name,
        method_version=value.policy.method_version,
        valuation_at=value.valuation_at.value,
        source_cutoff_at=value.source_cutoff_at.value,
        quality=QualityState.FRESH,
        provenance_set_key="xray.sources",
        coverage_set_key="xray.coverage",
        note_set_key="xray.notes",
    )
    builder.add_context(context)
    for item in value.source_dependencies:
        if item.license_version_id is not None:
            builder.add_license(
                r.ReportLicenseReference(
                    version_id=item.license_version_id,
                    provider_id=UUID(item.provider_id or ""),
                    license_digest="a" * 64,
                    attribution="Synthetic canonical calculator fixture",
                    pinned_store=LicensePermission.ALLOWED,
                    pinned_display=LicensePermission.ALLOWED,
                    pinned_report=LicensePermission.ALLOWED,
                    pinned_export=LicensePermission.ALLOWED,
                    valid_from=value.valuation_at.value,
                )
            )
        builder.add_reference(
            r.ReportSourceReference(
                key=_source_key(item.id),
                kind=_SOURCE_KINDS[item.reference.kind],
                subject_id=item.reference.record_id,
                parent_id=item.reference.parent_record_id,
                content_digest=item.content_digest,
                provider_id=None if item.provider_id is None else UUID(item.provider_id),
                license_version_id=item.license_version_id,
            ),
            provenance_set_key=context.provenance_set_key,
        )
    return builder, sink, context


def test_xray_capture_includes_every_pair_beyond_public_subset_and_fits_manifest(
    record_property: Callable[[str, object], None],
) -> None:
    source = Builder()
    source.identity(uid(10), uid(110))
    source.classifications_for(uid(110), key="alpha")
    for index in range(40):
        instrument = uid(2000 + index)
        source.position(instrument, "1")
        source.fund(instrument, ((uid(10), "1"),))
    value = source.finish()
    result = calculate_xray(value)
    builder, sink, context = xray_builder(value)
    project_xray(
        builder,
        context,
        value,
        result,
        instrument_name=lambda identifier: f"Fund {identifier}",
        entity_name=lambda identifier: f"Entity {identifier}",
    )
    pairs = decoded_rows(sink, r.ReportTableKey.XRAY_OVERLAP_PAIRS)
    common = decoded_rows(sink, r.ReportTableKey.XRAY_OVERLAP_ENTITIES)
    assert len(pairs) == len(common) == 780
    assert len({row["pair_key"].value for row in pairs}) == 780
    assert all(row["overlap"].value == Decimal("1") for row in pairs)
    assert all(row["common_weight"].value == Decimal("1") for row in common)
    capture = builder.finish()
    manifest = encode_report_manifest(build_report_manifest(capture))
    record_property("manifest_bytes", len(manifest))
    record_property("document_bytes", capture.canonical_byte_length)
    record_property("table_rows", sum(item.row_count for item in capture.header.tables))
    record_property("pair_rows", len(pairs))
    record_property("source_memberships", len(capture.proof.source_memberships))
    assert len(manifest) <= r.MAX_REPORT_MANIFEST_BYTES
    assert capture.canonical_byte_length == len(manifest) + sum(
        len(item.canonical_bytes) for item in sink.chunks
    )
    assert decode_report_manifest(manifest) == build_report_manifest(capture)


def test_xray_capture_keeps_original_broker_currency_and_saved_operand_without_conversion() -> None:
    source = Builder()
    broker = source.broker_position()
    source.identity(uid(10), uid(110))
    source.classifications_for(uid(110))
    value = source.finish()
    result = calculate_xray(value)
    builder, sink, context = xray_builder(value)
    project_xray(
        builder,
        context,
        value,
        result,
        instrument_name=lambda identifier: str(identifier),
        entity_name=lambda identifier: str(identifier),
    )
    builder.complete_proof_tables()
    root = decoded_rows(sink, r.ReportTableKey.XRAY_VALUATION_ROOTS)[0]
    assert root["original_value"].value == Decimal("62.50")
    assert (
        root["original_value"].currency is not None
        and root["original_value"].currency.value == "USD"
    )
    assert root["reporting_value"].value == Decimal("50")
    assert decoded_rows(sink, r.ReportTableKey.XRAY_SUMMARY)[0]["total"].value == Decimal("50")
    values = decoded_rows(sink, r.ReportTableKey.XRAY_BROKER_FX)[0]
    assert values["rate"].value == broker.rate == Decimal("0.8")
    assert values["source_record_id"].value == str(broker.source_record_id)


def test_xray_empty_metric_provenance_is_declared_without_inheriting_root_sources() -> None:
    source = Builder()
    source.broker_position()
    value = source.finish()
    builder, _, context = xray_builder(value)
    original = replace(value.positions[0].reporting_value, source_reference_ids=())
    cell = _metric(builder, context, "empty.sources", original)
    assert cell.provenance_set_key != context.provenance_set_key
    assert any(
        item.provenance_set_key == cell.provenance_set_key for item in builder.contexts.values()
    )
    assert not any(
        item.provenance_set_key == cell.provenance_set_key for item in builder.source_memberships
    )
    proof = r.ReportProof(
        contexts=tuple(_legacy_context(item) for item in builder.contexts.values()),
        bounds=tuple(builder.bounds.values()),
        coverage=(
            r.ReportCoverageFact(
                set_key=context.coverage_set_key,
                family=r.ReportFamily.XRAY,
                metric_key="empty.sources",
                value=cell,
            ),
        ),
    )
    validate_report_references(proof)
    assert cell.value == original.value.amount if original.value is not None else cell.value is None


@pytest.mark.parametrize("referenced", [False, True])
def test_historical_warning_source_absence_has_no_inherited_or_unresolved_set(
    referenced: bool,
) -> None:
    from tests.unit.domain.report_factories import selection

    value = historical_fixture()
    result = calculate_performance(value, options=hr.PerformanceOptions())
    warning = h.HistoricalIssue(
        reason_code=h.HistoricalReason.VALUATION_MISSING,
        reference_ids=(str(uid(991)),) if referenced else (),
    )
    result = replace(result, context=replace(result.context, warnings=(warning,)))
    builder = ReportBuilder(
        selection(), owner_id=uid(3), valuation_at=result.context.window.end_at, sink=CaptureSink()
    )
    context = _context(builder, result)
    note = builder.notes[f"{context.key}.warning.0"]
    if referenced:
        assert note.related_provenance_set_key == f"{context.key}.warning.0.sources"
    else:
        assert note.related_provenance_set_key is None
        validate_report_references(
            r.ReportProof(
                contexts=tuple(_legacy_context(item) for item in builder.contexts.values()),
                notes=tuple(builder.notes.values()),
            )
        )


@pytest.mark.parametrize("configured", [False, True])
def test_composite_snapshot_binding_preserves_actual_header_or_explicit_absence(
    configured: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.orm import Session
    from trading212_analytics.historical import calculate_benchmark_comparison
    from trading212_application.sources import CompositeBenchmarkSnapshotHeaderView
    from trading212_persistence import report_capture_historical as capture_module
    from trading212_persistence.historical_models import HistoricalRunModel
    from trading212_persistence.historical_publication import composite_snapshot_header
    from trading212_persistence.source_models import BenchmarkSnapshotModel

    from tests.unit.analytics.historical_factories import with_benchmark
    from tests.unit.domain.report_factories import selection

    value = with_benchmark(
        historical_fixture(("100", "100", "100")), ("100", "110", "99"), ("100", "90", "108")
    )
    if not configured:
        value = replace(
            value,
            selection=replace(value.selection, source_policy=None, reporting_calendar_ref=None),
        )
    result = calculate_benchmark_comparison(value, options=hr.ComparisonOptions())
    owner = UUID(value.owner_id)
    run = HistoricalRunModel(id=uid(995), owner_id=owner)
    builder = ReportBuilder(
        selection(), owner_id=owner, valuation_at=value.selection.window.end_at, sink=CaptureSink()
    )
    calls = 0

    def header(
        session: Session,
        actual_owner: UUID,
        actual_run: HistoricalRunModel,
        actual: hr.BenchmarkCalculation,
    ) -> CompositeBenchmarkSnapshotHeaderView:
        nonlocal calls
        calls += 1
        assert actual_owner == owner and actual_run is run and actual is result
        assert actual.composite is not None
        return composite_snapshot_header(
            BenchmarkSnapshotModel(id=uid(996), created_at=value.selection.window.end_at),
            actual.composite,
        )

    monkeypatch.setattr(capture_module, "composite_header", header)
    with Session() as session:
        capture_module._capture_composite_binding(builder, session, owner, run, result)
    if not configured:
        assert result.composite is None and calls == 0 and builder.bindings == []
    else:
        assert result.composite is not None and calls == 1
        assert len(builder.bindings) == 1
        binding = builder.bindings[0]
        assert (binding.family, binding.role, binding.subject_id, binding.parent_id) == (
            r.ReportFamily.BENCHMARK,
            r.ReportInputRole.SNAPSHOT,
            uid(996),
            run.id,
        )
        from trading212_persistence.historical_base import digest

        assert binding.content_digest == digest(result.composite)
        assert (binding.method_key, binding.method_version) == (
            result.composite.method.name,
            result.composite.method.version,
        )


@pytest.mark.parametrize("days,expected_points", [(31, 1), (365, 12)])
def test_monthly_and_annual_public_performance_and_provenance_are_complete_and_bounded(
    days: int,
    expected_points: int,
    record_property: Callable[[str, object], None],
) -> None:
    value = historical_fixture(("100",) * (days + 1))
    result = calculate_performance(value, options=hr.PerformanceOptions())
    sink = CaptureSink()
    window = value.selection.window
    selection = r.ExportSelection(
        account_id=UUID(value.account_id),
        snapshot_id=uid(3),
        start_date=window.start_date,
        end_date=window.end_date,
        source_cutoff_at=window.source_cutoff_at,
        reporting_currency=window.reporting_currency,
        dataset=r.ExportDataset.PERFORMANCE,
        field_set=r.ExportFieldSet.AUDIT,
        format=r.ExportFormat.JSON,
    )
    builder = ReportBuilder(
        selection, owner_id=UUID(value.owner_id), valuation_at=window.end_at, sink=sink
    )
    context = _context(builder, result)
    project_historical(builder, context, value, result)
    assert len(decoded_rows(sink, r.ReportTableKey.PERFORMANCE_POINTS)) == expected_points
    assert decoded_rows(sink, r.ReportTableKey.PERFORMANCE_SUMMARY)[0][
        "time_weighted_return"
    ].value == Decimal("0")
    builder.complete_proof_tables()
    use_tables = (
        r.ReportTableKey.HISTORICAL_OBSERVATION_USES,
        r.ReportTableKey.HISTORICAL_EVIDENCE_USES,
        r.ReportTableKey.HISTORICAL_MISSING_USES,
    )
    # The fixed service profile reports monthly points. Daily reconstruction
    # traces remain in the immutable run; every reported instant and both
    # period boundaries retain their exact source uses, including unavailable.
    instants = {window.start_at, window.end_at, *(point.valuation_at for point in result.points)}
    expected_uses = tuple(use for use in result.source_uses if use.use_at in instants)
    captured_uses = [row for table in use_tables for row in decoded_rows(sink, table)]
    assert {row["use_key"].value for row in captured_uses} == {use.use_key for use in expected_uses}
    assert len(captured_uses) == len(expected_uses) < len(result.source_uses)
    assert {row["use_at"].value for row in captured_uses} == instants
    capture = builder.finish()
    payload = encode_report_manifest(build_report_manifest(capture))
    record_property("days", days)
    record_property("manifest_bytes", len(payload))
    record_property("document_bytes", capture.canonical_byte_length)
    record_property("table_rows", sum(item.row_count for item in capture.header.tables))
    record_property("retained_source_uses", len(expected_uses))
    record_property("canonical_private_source_uses", len(result.source_uses))
    assert len(payload) <= r.MAX_REPORT_MANIFEST_BYTES
    assert capture.canonical_byte_length <= r.MAX_REPORT_DOCUMENT_BYTES
    for descriptor in capture.header.tables:
        assert descriptor.content_digest == report_table_digest(
            descriptor.table,
            (row for chunk in sink.chunks if chunk.table is descriptor.table for row in chunk.rows),
        )


@pytest.mark.parametrize("currency", ["EUR", "USD"])
def test_dividend_capture_keeps_zero_missing_gross_correction_and_exact_source_identity(
    currency: str,
) -> None:
    value = historical_fixture()
    identity = h.HistoricalEventIdentity(
        economic_key="dividend-correction",
        revision_id=str(uid(701)),
        source_record_id=str(uid(702)),
        source_occurrence_id=None,
        economic_at=value.selection.window.start_at,
        first_observed_at=value.selection.window.start_at,
    )
    missing = h.HistoricalMoneyMetric(
        value=None,
        availability=h.MetricAvailability.UNAVAILABLE,
        reason_code=h.HistoricalReason.GROSS_UNKNOWN,
        quality=QualityState.PARTIAL,
        coverage_key=h.HistoricalCoverageKey.PRIOR_INCOME,
    )
    dividend = h.HistoricalDividend(
        identity=identity,
        dividend_key="corrected-payment",
        instrument_id=str(uid(6)),
        listing_id=str(uid(7)),
        net=Money(Decimal("0"), CurrencyCode(currency)),
        gross=missing,
        withholding=replace(missing, reason_code=h.HistoricalReason.WITHHOLDING_UNKNOWN),
        payment_convention="exact_provider_instant",
        correction_of=str(uid(700)),
    )
    value = with_events(value, dividend)
    result = calculate_income(value, options=hr.IncomeOptions())
    sink = CaptureSink()
    window = value.selection.window
    selection = r.ExportSelection(
        account_id=UUID(value.account_id),
        snapshot_id=uid(3),
        start_date=window.start_date,
        end_date=window.end_date,
        source_cutoff_at=window.source_cutoff_at,
        reporting_currency=window.reporting_currency,
        dataset=r.ExportDataset.DIVIDENDS,
        field_set=r.ExportFieldSet.AUDIT,
        format=r.ExportFormat.JSON,
    )
    builder = ReportBuilder(
        selection, owner_id=UUID(value.owner_id), valuation_at=window.end_at, sink=sink
    )
    context = _context(builder, result)
    project_historical(
        builder,
        context,
        value,
        result,
        labels={
            identity.source_record_id: HistoricalEventLabels(
                "SYNTH", "Provider dividend", Decimal("2")
            )
        },
    )
    row = decoded_rows(sink, r.ReportTableKey.DIVIDENDS)[0]
    assert row["net"].value == Decimal("0") and row["net"].state is r.CellState.AVAILABLE
    assert row["gross"].value is None and row["gross"].state is r.CellState.UNAVAILABLE
    assert row["net"].currency == row["gross"].currency == CurrencyCode(currency)
    assert row["gross"].reason_key is not None
    assert (row["gross"].quality or context.quality) is QualityState.PARTIAL
    assert row["record_id"].value == identity.source_record_id
    assert row["revision_id"].value == identity.revision_id
    assert row["quantity"].value == Decimal("2")
    capture = builder.finish()
    fields = decoded_rows(sink, r.ReportTableKey.CASH_FLOW_EVENTS)[0]
    assert fields["correction_of"].value == str(uid(700))
    manifest = build_report_manifest(capture)
    assert decode_report_manifest(encode_report_manifest(manifest)) == manifest


def test_interleaved_proof_rows_stream_with_bounded_buffer_and_complete_hashes() -> None:
    source = Builder()
    source.position(uid(10), "1")
    value = source.finish()
    builder, sink, context = xray_builder(value)
    for ordinal in range(300):
        for table, values in (
            (
                r.ReportTableKey.TARGET_EXCLUSIONS,
                {
                    "key": f"exclusion.{ordinal}",
                    "node_key": None,
                    "instrument_id": str(uid(10)),
                    "listing_id": None,
                    "reason": "x" * 4096,
                },
            ),
            (
                r.ReportTableKey.HISTORICAL_SOURCE_DETAILS,
                {
                    "source_key": f"source.{ordinal}",
                    "kind": "price_snapshot",
                    "semantic_digest": "a" * 64,
                    "derived_projection_digest": None,
                    "original_fingerprint": None,
                    "version": "1.0.0",
                },
            ),
        ):
            row = capture_row(
                builder, context, table, key=f"{table.value}.{ordinal}", values=values
            )
            builder.add_proof(r.ReportProofRelation(table=table, row=row))
            assert builder._pending_proof_bytes < r.MAX_REPORT_CHUNK_BYTES
    assert sink.chunks  # payloads have already left the bounded writer before finish
    capture = builder.finish()
    assert not capture.proof.proof_relations
    for descriptor in capture.header.tables:
        rows = tuple(
            row for chunk in sink.chunks if chunk.table is descriptor.table for row in chunk.rows
        )
        assert len(rows) == descriptor.row_count == 300
        assert descriptor.content_digest == report_table_digest(descriptor.table, rows)
        chunks = [chunk for chunk in sink.chunks if chunk.table is descriptor.table]
        assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
        assert all(len(chunk.canonical_bytes) <= r.MAX_REPORT_CHUNK_BYTES for chunk in chunks)
    assert not builder._pending_proof_bytes
    with pytest.raises(DomainError):
        builder.add_proof(r.ReportProofRelation(table=table, row=row))


@pytest.mark.parametrize("daily,expected", [(False, ".026"), (True, ".0404")])
def test_benchmark_capture_retains_configured_weights_and_public_composite_header(
    daily: bool,
    expected: str,
) -> None:
    from trading212_analytics.historical import calculate_benchmark_comparison

    from tests.unit.analytics.historical_factories import with_benchmark
    from tests.unit.domain.report_factories import selection as base_selection

    value = with_benchmark(
        historical_fixture(("100", "100", "100")),
        ("100", "110", "99"),
        ("100", "90", "108"),
        daily=daily,
    )
    result = calculate_benchmark_comparison(value, options=hr.ComparisonOptions())
    window = value.selection.window
    base = base_selection()
    chosen = replace(
        base,
        account_id=UUID(value.account_id),
        start_date=window.start_date,
        end_date=window.end_date,
        source_cutoff_at=window.source_cutoff_at,
        sections=(*base.sections, r.ReportSection.BENCHMARK),
        benchmark_version_id=UUID(value.selection.benchmark_version_id or ""),
    )
    sink = CaptureSink()
    builder = ReportBuilder(
        chosen, owner_id=UUID(value.owner_id), valuation_at=window.end_at, sink=sink
    )
    context = _context(builder, result)
    project_historical(builder, context, value, result)
    capture = builder.finish()
    assert decoded_rows(sink, r.ReportTableKey.BENCHMARK_SUMMARY)[0][
        "benchmark_return"
    ].value == Decimal(expected)
    components = decoded_rows(sink, r.ReportTableKey.BENCHMARK_COMPONENTS)
    assert [row["weight"].value for row in components] == [Decimal(".6"), Decimal(".4")]
    assert result.composite is not None
    assert {row["source_id"].value for row in components} == {
        item.source_id for item in result.composite.inputs
    }
    assert not decoded_rows(sink, r.ReportTableKey.BENCHMARK_OBSERVATIONS)
    points = decoded_rows(sink, r.ReportTableKey.BENCHMARK_POINTS)
    assert len(points) == len(result.points)
    assert [row["benchmark_wealth"].value for row in points] == [
        item.benchmark_wealth.value for item in result.points
    ]
    members = decoded_rows(sink, r.ReportTableKey.BENCHMARK_COMPONENT_MEMBERS)
    assert {(row["role"].value, row["reference_id"].value) for row in members} == {
        (role, identifier)
        for item in result.composite.inputs
        for role, identifiers in (
            ("snapshot", item.snapshot_ids),
            ("license", item.license_version_ids),
        )
        for identifier in identifiers
    }
    header = decoded_rows(sink, r.ReportTableKey.BENCHMARK_COMPOSITE)[0]
    assert header["observation_count"].value == len(result.composite.observations)
    assert header["rebalance_rule"].value == result.composite.rebalance_rule.value
    assert decode_report_manifest(
        encode_report_manifest(build_report_manifest(capture))
    ) == build_report_manifest(capture)


def test_cash_flow_capture_preserves_external_signs_whole_window_totals_and_event_ids() -> None:
    from trading212_analytics.historical import calculate_cash_flows

    from tests.unit.analytics.historical_factories import START, identity
    from tests.unit.domain.report_factories import selection as base_selection

    value = historical_fixture()
    currency = value.selection.window.reporting_currency
    events = (
        h.HistoricalExternalFlow(
            identity=identity(100, START),
            kind="deposit",
            signed_amount=Money(Decimal("50"), currency),
            scope_proof="account_boundary",
        ),
        h.HistoricalExternalFlow(
            identity=identity(101, START),
            kind="withdrawal",
            signed_amount=Money(Decimal("-20"), currency),
            scope_proof="account_boundary",
        ),
    )
    value = with_events(value, *events)
    result = calculate_cash_flows(value, options=hr.CashFlowOptions())
    window = value.selection.window
    base = base_selection()
    chosen = replace(
        base,
        account_id=UUID(value.account_id),
        start_date=window.start_date,
        end_date=window.end_date,
        source_cutoff_at=window.source_cutoff_at,
        sections=(*base.sections, r.ReportSection.CASH_FLOWS, r.ReportSection.ACTIVITY),
    )
    sink = CaptureSink()
    builder = ReportBuilder(
        chosen, owner_id=UUID(value.owner_id), valuation_at=window.end_at, sink=sink
    )
    context = _context(builder, result)
    project_historical(builder, context, value, result)
    builder.finish()
    rows = decoded_rows(sink, r.ReportTableKey.ACTIVITY)
    assert {(row["revision_id"].value, row["amount"].value) for row in rows} == {
        (events[0].identity.revision_id, Decimal("50")),
        (events[1].identity.revision_id, Decimal("-20")),
    }
    proof = decoded_rows(sink, r.ReportTableKey.CASH_FLOW_EVENTS)
    assert len(proof) == 2
    totals = decoded_rows(sink, r.ReportTableKey.CASH_FLOW_TOTALS)
    assert next(
        row["external_net"].value for row in totals if row["basis"].value == "reporting"
    ) == Decimal("30")
    assert {row["classification"].value for row in proof} == {"external"}
    options = decoded_rows(sink, r.ReportTableKey.HISTORICAL_OPTIONS)[0]
    assert options["cash_flow_kind"].state is r.CellState.NOT_APPLICABLE
    assert options["knowledge_policy"].value == window.knowledge_policy.value


def test_attribution_capture_retains_exact_effects_and_full_selected_options() -> None:
    from trading212_analytics.historical import calculate_attribution

    from tests.unit.analytics.historical_factories import with_fx
    from tests.unit.analytics.source_factories import USD
    from tests.unit.domain.report_factories import selection as base_selection

    value = with_fx(
        historical_fixture(("10", "12"), quantity="2", currency=USD), ("1", "1.1"), base=USD
    )
    result = calculate_attribution(
        value, options=hr.AttributionOptions(method=h.AttributionMethod.MODIFIED_DIETZ)
    )
    window = value.selection.window
    base = base_selection()
    chosen = replace(
        base,
        account_id=UUID(value.account_id),
        start_date=window.start_date,
        end_date=window.end_date,
        source_cutoff_at=window.source_cutoff_at,
        sections=(*base.sections, r.ReportSection.ATTRIBUTION),
    )
    sink = CaptureSink()
    builder = ReportBuilder(
        chosen, owner_id=UUID(value.owner_id), valuation_at=window.end_at, sink=sink
    )
    context = _context(builder, result)
    project_historical(builder, context, value, result)
    builder.finish()
    summary = decoded_rows(sink, r.ReportTableKey.ATTRIBUTION_SUMMARY)[0]
    assert summary["investment_gain"].value == Decimal("6.4")
    effects = {
        row["kind"].value: row["amount"].value
        for row in decoded_rows(sink, r.ReportTableKey.ATTRIBUTION_EFFECTS)
        if row["parent_key"].value == "portfolio"
    }
    assert effects["price"] == Decimal("4")
    assert effects["fx"] == Decimal("2")
    assert effects["interaction"] == Decimal(".4")
    assert (
        decoded_rows(sink, r.ReportTableKey.HISTORICAL_OPTIONS)[0]["return_method"].value
        == "modified_dietz"
    )


def test_single_fund_capture_keeps_entity_aggregates_path_dimensions_and_actual_policy() -> None:
    source = Builder()
    source.identity(uid(10), uid(110))
    source.classifications_for(uid(110))
    source.position(uid(2000), "1")
    source.fund(uid(2000), ((uid(10), "1"),))
    value = source.finish()
    threshold_id, reference_id = uid(777), uid(778)
    threshold = x.ConcentrationThresholdPolicy(
        threshold_id,
        "1",
        reference_id,
        Decimal(".5"),
        Decimal(".8"),
        Decimal(".4"),
        x.XrayComparison.GE,
        x.XrayComparison.GT,
        x.XrayComparison.GE,
    )
    dependency = x.XraySourceDependency(
        reference_id,
        value.owner_id,
        value.account_id,
        value.snapshot_id,
        x.XrayDependencyKind.THRESHOLD,
        x.XraySubjectKind.POLICY,
        threshold_id,
        None,
        None,
        "b" * 64,
        x.XrayPhysicalReference(x.XrayReferenceKind.OWNER_POLICY, threshold_id, None),
    )
    value = replace(
        value,
        policy=replace(value.policy, thresholds=threshold),
        source_dependencies=(*value.source_dependencies, dependency),
    )
    result = calculate_xray(value)
    builder, sink, context = xray_builder(value)
    project_xray(builder, context, value, result, instrument_name=str, entity_name=str)
    capture = builder.finish()
    assert not decoded_rows(sink, r.ReportTableKey.XRAY_OVERLAP_PAIRS)
    entities = decoded_rows(sink, r.ReportTableKey.XRAY_FUND_ENTITIES)
    assert len(entities) == 1 and entities[0]["weight"].value == Decimal("1")
    weights = decoded_rows(sink, r.ReportTableKey.XRAY_PATH_WEIGHTS)
    assert len(weights) == sum(len(item.dimension_weights) for item in result.terminal_paths)
    assert {row["dimension"].value for row in weights} == {item.value for item in x.XrayDimension}
    policy = decoded_rows(sink, r.ReportTableKey.XRAY_POLICY)[0]
    assert policy["method_key"].value == context.method_key == "xray_v1"
    assert policy["method_version"].value == context.method_version == "1.1.0"
    assert policy["numeric_policy"].value == "xray_decimal256_exact_q18_v1"
    assert policy["quality_evaluated_at"].value == result.quality_evaluated_at.value
    assert {
        row["id"].value for row in decoded_rows(sink, r.ReportTableKey.XRAY_POLICY_COMPONENTS)
    } == {
        str(item.id)
        for item in (
            value.policy.provider_selection_policy,
            value.policy.identity_policy,
            value.policy.classification_policy,
            value.policy.freshness_policy,
            value.policy.quality_policy,
            value.policy.traversal_policy,
        )
    }
    assert any(note.text == value.policy.numeric_policy for note in capture.proof.notes)

    limits = decoded_rows(sink, r.ReportTableKey.XRAY_THRESHOLD_POLICY)
    assert [
        (row["metric"].value, row["limit"].value, row["comparison"].value) for row in limits
    ] == [
        ("top1", Decimal(".5"), "ge"),
        ("top5", Decimal(".8"), "gt"),
        ("hhi", Decimal(".4"), "ge"),
    ]
    assert all(row["source_reference_id"].value == str(reference_id) for row in limits)


def test_unavailable_original_cash_retains_its_known_native_currency() -> None:
    from tests.unit.analytics.xray_factories import metric

    source = Builder()
    source.cash_row("1")
    row = source.cash[0]
    source.cash[0] = replace(
        row,
        root=replace(row.root, original_currency=CurrencyCode("USD")),
        original_value=metric(None, row.valuation_refs),
        reporting_value=metric(None, row.valuation_refs),
    )
    value = source.finish()
    result = calculate_xray(value)
    builder, sink, context = xray_builder(value)
    project_xray(builder, context, value, result, instrument_name=str, entity_name=str)
    builder.finish()
    root = decoded_rows(sink, r.ReportTableKey.XRAY_VALUATION_ROOTS)[0]
    assert root["original_value"].value is None
    assert root["original_value"].state is r.CellState.UNAVAILABLE
    assert root["original_value"].currency == CurrencyCode("USD")
    assert root["reporting_value"].value is None
    assert root["reporting_value"].currency == CurrencyCode("EUR")


def test_public_trace_keeps_event_fx_and_boundary_legs_without_mutating_daily_run() -> None:
    from trading212_domain.historical_serialization import historical_input_digest
    from trading212_persistence.report_capture_historical_proof import retained_historical_trace

    from tests.unit.analytics.historical_factories import START, identity, with_fx
    from tests.unit.analytics.source_factories import USD

    value = with_fx(historical_fixture(("100",) * 32, currency=USD), (".8",) * 32, base=USD)
    event = h.HistoricalExternalFlow(
        identity=identity(999, START + timedelta(days=10)),
        kind="deposit",
        signed_amount=Money(Decimal("5"), USD),
        scope_proof="account_boundary",
    )
    value = with_events(value, event)
    input_digest = historical_input_digest(value)
    source_fingerprints = tuple((source.id, source.semantic_digest) for source in value.sources)
    result = calculate_performance(value, options=hr.PerformanceOptions())
    complete_uses, complete_conversions = result.source_uses, result.conversions
    uses, conversions = retained_historical_trace(value, result)
    expected_instants = {
        value.selection.window.start_at,
        value.selection.window.end_at,
        event.identity.economic_at,
        *(point.valuation_at for point in result.points),
    }
    assert {use.use_key for use in uses} == {
        use.use_key for use in complete_uses if use.use_at in expected_instants
    }
    assert 0 < len(uses) < len(complete_uses)
    by_key = {use.use_key: use for use in uses}
    actual_conversions = {item.conversion_key: item for item in complete_conversions}
    for conversion in conversions:
        assert conversion == actual_conversions[conversion.conversion_key]
        for key in conversion.leg_use_keys:
            leg = by_key[key]
            assert isinstance(leg, hr.HistoricalObservationUse)
            assert leg.conversion_leg is not None
            assert leg.conversion_leg.conversion_key == conversion.conversion_key
            assert leg.snapshot_id == value.fx_snapshots[0].id
    event_fx = [
        use
        for use in uses
        if isinstance(use, hr.HistoricalObservationUse)
        and use.source_kind == "fx"
        and use.consumer.event_revision_id == event.identity.revision_id
    ]
    assert event_fx and all(use.use_at == event.identity.economic_at for use in event_fx)
    assert any(item.rate == Decimal(".8") and item.leg_use_keys for item in conversions)
    assert result.source_uses is complete_uses and result.conversions is complete_conversions
    assert historical_input_digest(value) == input_digest
    assert (
        tuple((source.id, source.semantic_digest) for source in value.sources)
        == source_fingerprints
    )


def _legacy_context(value: object) -> r.ReportContext:
    assert isinstance(value, r.ReportContext)
    return value
