"""Bounded canonical capture and typed scalar projection without a database."""

from dataclasses import replace
from decimal import Decimal
from typing import cast

import pytest
from trading212_application.views import Availability, MetricView
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.report_manifest import build_report_manifest, encode_report_manifest
from trading212_domain.values import CurrencyCode
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_capture_common import (
    ReportValue,
    capture_row,
    capture_stored_warnings,
)

from tests.unit.domain.report_factories import document

pytestmark = pytest.mark.unit


class Sink:
    def __init__(self) -> None:
        self.chunks: list[r.ReportChunk] = []
        self.finished = False

    def append(self, chunk: r.ReportChunk) -> None:
        self.chunks.append(chunk)

    def finish(self, summary: r.ReportCaptureSummary) -> None:
        self.finished = True


def builder() -> tuple[ReportBuilder, Sink]:
    fixture, sink = document(), Sink()
    result = ReportBuilder(
        fixture.header.selection,
        owner_id=fixture.header.owner_id,
        valuation_at=fixture.header.valuation_at,
        sink=sink,
    )
    return result, sink


def test_stream_capture_matches_fixed_manifest_and_leaves_seal_to_service() -> None:
    fixture = document()
    target, sink = builder()
    for context in fixture.capture.proof.contexts:
        target.add_context(context)
    for reference in fixture.capture.proof.source_references:
        target.add_reference(reference, provenance_set_key="sources.snapshot")
    for note in fixture.capture.proof.notes:
        target.add_note(note, note_set_key="notes.snapshot")
    for binding in fixture.capture.immutable_bindings:
        target.add_binding(binding)
    for table in fixture.header.tables:
        target.add_table(
            table.table,
            (row for chunk in fixture.iter_chunks(table.table) for row in chunk.rows),
            section=table.section,
            dataset=table.dataset,
        )
    captured = target.finish()
    assert encode_report_manifest(build_report_manifest(captured)) == encode_report_manifest(
        fixture.manifest
    )
    assert captured.canonical_byte_length == sum(
        len(chunk.canonical_bytes) for chunk in sink.chunks
    ) + len(encode_report_manifest(fixture.manifest))
    assert not sink.finished


def test_proof_growth_is_rejected_before_unbounded_notes_are_retained() -> None:
    target, _ = builder()
    note = document().capture.proof.notes[0]
    with pytest.raises(DomainError):
        for index in range(10_000):
            target.add_note(
                replace(note, key=f"note.{index}", text="x" * 4096), note_set_key="notes.snapshot"
            )
    assert len(target.notes) < 512


def test_duplicate_rows_reject_instead_of_double_counting_canonical_values() -> None:
    target, sink = builder()
    chunk = document().chunks[0]
    with pytest.raises(DomainError):
        target.add_table(chunk.table, (*chunk.rows, *chunk.rows))
    assert not sink.finished


def test_scalar_projection_preserves_money_and_refuses_implicit_binary_float() -> None:
    target, _ = builder()
    context = document().capture.proof.contexts[0]
    target.add_context(context)
    metric = MetricView(
        Decimal("-12.123456789012345678"),
        "USD",
        Availability.AVAILABLE,
        "1.0.0",
        "provider-reported amount",
        ("synthetic_source",),
    )
    values: dict[str, ReportValue] = {
        "dimension": "direct",
        "bucket_key": "cash",
        "name": "Cash",
        "value": metric,
        "weight": None,
        "position_count": 0,
    }
    row = capture_row(
        target,
        context,
        r.ReportTableKey.ALLOCATION_BUCKETS,
        key="allocation.cash",
        values=values,
        currency=CurrencyCode("EUR"),
    )
    assert row.cells[3].value == metric.value
    assert row.cells[3].currency == CurrencyCode("USD")
    assert row.cells[4].state is r.CellState.UNAVAILABLE
    assert row.cells[5].value == 0
    with pytest.raises(DomainError):
        capture_row(
            target,
            context,
            r.ReportTableKey.ALLOCATION_BUCKETS,
            key="allocation.invalid",
            values={**values, "weight": cast(ReportValue, 0.1)},
            currency=CurrencyCode("EUR"),
        )


def test_report_retains_every_warning_code_message_and_affected_field() -> None:
    target, _ = builder()
    context = document().capture.proof.contexts[0]
    target.add_context(context)
    warnings = [
        {
            "code": f"source_{index}",
            "message": f"Warning {index}: " + "x" * 470,
            "affected_fields": ["market_value", "quantity"],
        }
        for index in range(25)
    ]
    capture_stored_warnings(target, context, warnings, key="snapshot.warning")
    assert len(target.notes) == 75
    for index, warning in enumerate(warnings):
        note = target.notes[f"snapshot.warning.{index}"]
        assert (note.code, note.text) == (warning["code"], warning["message"])
        assert target.notes[f"snapshot.warning.{index}.field.1"].text == "Affected field: quantity"


def test_unknown_warning_payload_fails_instead_of_silently_omitting_it() -> None:
    target, _ = builder()
    context = document().capture.proof.contexts[0]
    target.add_context(context)
    with pytest.raises(DomainError):
        capture_stored_warnings(target, context, [{"unknown_payload": "untrusted"}], key="warning")


def test_cells_inherit_only_equal_context_metadata_and_keep_metric_overrides() -> None:
    target, _ = builder()
    context = document().capture.proof.contexts[0]
    target.add_context(context)
    row = capture_row(
        target,
        context,
        r.ReportTableKey.ALLOCATION_BUCKETS,
        key="allocation.typed",
        currency=CurrencyCode("EUR"),
        values={
            "dimension": "direct",
            "bucket_key": "cash",
            "name": "Cash",
            "value": Decimal("12.5"),
            "weight": r.ReportCell(
                kind=r.CellKind.DECIMAL,
                decimal_role=r.DecimalRole.RATIO,
                value=Decimal("0.125"),
                context_key=context.key,
                quality=QualityState.ESTIMATED,
                origin=r.ReportMetricOrigin.DERIVED_DETERMINISTIC,
                confidence=Decimal("0.75"),
                coverage_key="exact.metric.coverage",
                method_key=context.method_key,
                method_version="2.0.0",
                provenance_set_key=context.provenance_set_key,
                note_set_key=context.note_set_key,
            ),
            "position_count": 1,
        },
    )
    assert row.context_key == context.key
    assert all(cell.context_key is None for cell in row.cells)
    value, weight = row.cells[3:5]
    assert value.value == Decimal("12.5") and value.currency == CurrencyCode("EUR")
    assert value.quality is value.method_key is value.method_version is None
    assert value.coverage_key is value.provenance_set_key is value.note_set_key is None
    assert weight.quality is QualityState.ESTIMATED
    assert weight.confidence == Decimal("0.75")
    assert weight.origin is r.ReportMetricOrigin.DERIVED_DETERMINISTIC
    assert weight.coverage_key == "exact.metric.coverage"
    assert (weight.method_key, weight.method_version) == (context.method_key, "2.0.0")
