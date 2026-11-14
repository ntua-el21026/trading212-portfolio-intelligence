"""Independent retained research scalars keep their quality, bounds and exact pins."""

from dataclasses import replace
from decimal import Decimal

import pytest
from trading212_domain import reports as r
from trading212_domain.errors import DomainError
from trading212_domain.report_schema import table_schema
from trading212_domain.research_notes import ResearchNoteRevision
from trading212_domain.xray import XrayBound
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_capture_research import project_research

from tests.unit.domain import research_factories as research
from tests.unit.domain.report_factories import uid
from tests.unit.domain.report_research_factories import research_binding, research_selection

pytestmark = pytest.mark.unit


class Sink:
    def __init__(self) -> None:
        self.chunks: list[r.ReportChunk] = []

    def append(self, chunk: r.ReportChunk) -> None:
        self.chunks.append(chunk)


@pytest.mark.parametrize("changed", ["event", "entity", "notes"])
def test_projection_rejects_mismatched_retained_evidence(changed: str) -> None:
    binding = research_binding()
    event = research.event()
    notes: tuple[ResearchNoteRevision, ...] = (research.note(event),)
    facts = replace(research.portfolio(event), pin=binding.xray_pin)
    if changed == "event":
        event = replace(event, event_id=uid(999))
    elif changed == "entity":
        facts = replace(facts, entity_id=uid(999))
    else:
        notes = ()
    sink = Sink()
    builder = ReportBuilder(
        research_selection(binding),
        owner_id=binding.owner_id,
        valuation_at=binding.valuation_at,
        sink=sink,
    )
    with pytest.raises(DomainError) as rejected:
        project_research(builder, binding, event, facts, notes)
    assert rejected.value.field == "research_binding"
    assert sink.chunks == []


@pytest.mark.parametrize(
    "amount,bound",
    [("100", XrayBound.EXACT), ("100", XrayBound.LOWER_BOUND), (None, XrayBound.EXACT)],
)
def test_projection_preserves_decimal_quality_unavailability_and_bound(
    amount: str | None,
    bound: XrayBound,
) -> None:
    binding, event = research_binding(), research.event()
    facts = replace(research.portfolio(event, amount, bound=bound), pin=binding.xray_pin)
    sink = Sink()
    builder = ReportBuilder(
        research_selection(binding),
        owner_id=binding.owner_id,
        valuation_at=binding.valuation_at,
        sink=sink,
    )
    project_research(builder, binding, event, facts, (research.note(event),))
    table = r.ReportTableKey.RESEARCH_PORTFOLIO_V1
    row = next(chunk.rows[0] for chunk in sink.chunks if chunk.table is table)
    cells = dict(
        zip((column.key for column in table_schema(table).columns), row.cells, strict=True)
    )
    metric = cells["effective_exposure"]
    assert metric.value == (None if amount is None else Decimal(amount))
    assert metric.state is (r.CellState.UNAVAILABLE if amount is None else r.CellState.AVAILABLE)
    assert metric.currency == binding.reporting_currency
    context = builder.contexts[row.context_key]
    assert (metric.quality or context.quality) == facts.quality
    assert metric.confidence == facts.confidence
    assert metric.origin is not None and metric.origin.value == facts.origin.value
    assert metric.bound_key is not None
    assert builder.bounds[metric.bound_key].kind is (
        r.ReportBoundKind.UNAVAILABLE if amount is None else r.ReportBoundKind(bound.value)
    )
    if amount is None:
        assert metric.reason_key is not None
        assert facts.reason is not None
        assert builder.notes[metric.reason_key].code == facts.reason.value
