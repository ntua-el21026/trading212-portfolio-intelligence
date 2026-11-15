"""Unconfigured historical coverage remains explicit in report-only projections."""

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

import pytest
from trading212_analytics.historical import calculate_cash_flows
from trading212_domain import historical as h
from trading212_domain import historical_results as hr
from trading212_domain import reports as r
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.historical_serialization import historical_canonical_bytes
from trading212_domain.report_manifest import validate_report_references
from trading212_domain.values import Money
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_capture_historical import _context, project_historical

from tests.unit.analytics.historical_factories import START, fixture, identity, with_events
from tests.unit.domain.report_factories import selection
from tests.unit.persistence.test_report_canonical_capture import CaptureSink, decoded_rows

pytestmark = pytest.mark.unit


def _capture(*, configured: bool) -> tuple[ReportBuilder, CaptureSink, hr.CashFlowCalculation]:
    value = fixture()
    if not configured:
        # Match the real persistence capture without an approved opening or
        # activity coverage. Unknown event completeness has no numeric count.
        value = replace(
            value,
            opening=h.UnavailableHistoricalOpening(reasons=(h.HistoricalReason.OPENING_MISSING,)),
            activity_coverage=(),
            coverage=h.HistoricalCoverage(
                measures=(
                    h.HistoricalCoverageMeasure(
                        key=h.HistoricalCoverageKey.OPENING,
                        expected_count=1,
                        available_count=0,
                        complete=False,
                        reasons=(h.HistoricalReason.OPENING_MISSING,),
                    ),
                )
            ),
        )
    currency = value.selection.window.reporting_currency
    value = with_events(
        value,
        h.HistoricalExternalFlow(
            identity=identity(100, START),
            kind="deposit",
            signed_amount=Money(Decimal("1"), currency),
            scope_proof="account_boundary",
        ),
    )
    result = calculate_cash_flows(value, options=hr.CashFlowOptions())
    original = historical_canonical_bytes(result)
    window = value.selection.window
    chosen = replace(
        selection(formats=(r.ReportFormat.JSON,)),
        account_id=UUID(value.account_id),
        start_date=window.start_date,
        end_date=window.end_date,
        source_cutoff_at=window.source_cutoff_at,
        report_type=r.ReportType.QUALITY_RECONCILIATION,
        sections=(r.ReportSection.OVERVIEW, r.ReportSection.QUALITY, r.ReportSection.ACTIVITY),
    )
    sink = CaptureSink()
    builder = ReportBuilder(
        chosen, owner_id=UUID(value.owner_id), valuation_at=window.end_at, sink=sink
    )
    context = _context(builder, result)
    project_historical(builder, context, value, result)
    assert historical_canonical_bytes(result) == original
    return builder, sink, result


def _coverage_keys(sink: CaptureSink) -> set[str]:
    return {
        cell.coverage_key
        for chunk in sink.chunks
        for row in chunk.rows
        for cell in row.cells
        if cell.coverage_key is not None
    }


def test_missing_referenced_event_measure_has_unavailable_proof_without_invented_counts(
    record_property: Callable[[str, object], None],
) -> None:
    builder, sink, result = _capture(configured=False)
    original = historical_canonical_bytes(result)
    record_property("canonical_result_sha256", sha256(original).hexdigest())
    assert result.context.availability is h.HistoricalAvailability.PARTIAL
    assert not any(
        measure.key is h.HistoricalCoverageKey.EVENTS
        for measure in result.context.coverage.measures
    )
    capture = builder.finish()
    # This is the same unchanged resolution gate used by the PostgreSQL sink.
    validate_report_references(capture.proof, coverage_keys=_coverage_keys(sink))
    context = next(
        item for item in capture.proof.contexts if item.family is r.ReportFamily.CASH_FLOWS
    )
    facts = [
        fact
        for fact in capture.proof.coverage
        if fact.set_key == context.coverage_set_key and fact.metric_key == "events"
    ]
    assert len(facts) == 1
    missing = facts[0].value
    assert missing.kind is r.CellKind.BOOLEAN
    assert missing.value is None and missing.state is r.CellState.UNAVAILABLE
    assert missing.context_key == context.key
    assert missing.reason_key is not None
    reason = next(note for note in capture.proof.notes if note.key == missing.reason_key)
    assert reason.kind is r.ReportNoteKind.UNAVAILABLE_REASON
    assert reason.code == "canonical_coverage_measure_missing"
    # Preserve every provided canonical measure exactly; missing EVENTS has no
    # fabricated expected/available counters or complete=False stand-in.
    for measure in result.context.coverage.measures:
        actual = {
            fact.metric_key: fact.value.value
            for fact in capture.proof.coverage
            if fact.set_key == context.coverage_set_key
            and fact.metric_key.startswith(f"{measure.key.value}.")
        }
        assert actual == {
            f"{measure.key.value}.expected_count": measure.expected_count,
            f"{measure.key.value}.available_count": measure.available_count,
            f"{measure.key.value}.complete": measure.complete,
        }
    assert not any(fact.metric_key.startswith("events.") for fact in capture.proof.coverage)
    amount = decoded_rows(sink, r.ReportTableKey.ACTIVITY)[0]["amount"]
    assert amount.value == Decimal("1") and amount.currency is not None
    assert amount.currency.value == "EUR" and amount.state is r.CellState.AVAILABLE
    assert amount.coverage_key == "events"
    assert historical_canonical_bytes(result) == original


def test_provided_event_measure_retains_original_facts_without_missing_marker() -> None:
    builder, sink, result = _capture(configured=True)
    capture = builder.finish()
    validate_report_references(capture.proof, coverage_keys=_coverage_keys(sink))
    original = next(
        measure
        for measure in result.context.coverage.measures
        if measure.key is h.HistoricalCoverageKey.EVENTS
    )
    facts = {
        fact.metric_key: fact.value.value
        for fact in capture.proof.coverage
        if fact.metric_key.startswith("events.")
    }
    assert facts == {
        "events.expected_count": original.expected_count,
        "events.available_count": original.available_count,
        "events.complete": original.complete,
    }
    assert not any(fact.metric_key == "events" for fact in capture.proof.coverage)
    assert not any(
        note.code == "canonical_coverage_measure_missing" for note in capture.proof.notes
    )


@pytest.mark.parametrize("unresolved", ["unknown_coverage", "cash"])
def test_unreferenced_missing_or_unknown_measure_is_still_rejected(unresolved: str) -> None:
    builder, sink, _ = _capture(configured=False)
    capture = builder.finish()
    with pytest.raises(DomainError) as rejected:
        validate_report_references(capture.proof, coverage_keys=_coverage_keys(sink) | {unresolved})
    assert rejected.value.code is ErrorCode.VALIDATION_FAILED
    assert rejected.value.field == "coverage_key"
