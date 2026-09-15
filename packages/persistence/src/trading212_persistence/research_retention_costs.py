"""Closed conservative research SQL cleanup work, including trigger fanout."""

from .projection_retention_costs import ProjectionMutationCost

# Metadata reads outside SQL triggers are additionally reserved by the scanner.
RESEARCH_CURSOR_RESERVE = 16
RESEARCH_MARKER_RESERVE = 8
RESEARCH_OWNER_MARKER_RESERVE = 8
# Event delete: target1 + owner marker1 + <=64*(member/citation/marker)3
# + <=64*(member UPDATE + guarded payload-absence probe)2 + counter UPDATE2.
# Reserve384 >=324, including repeated exact probes and FK/constraint allowance.
# No single mutation may exceed the shared512-row batch bound. Header flags are
# immutable provenance metadata, not retained provider/financial payload bytes.
RESEARCH_EVENT_MUTATION_ROWS = 384


def research_mutation_cost(table: str, *, delete_rows: bool) -> ProjectionMutationCost | None:
    if table not in {
        "research_source_payloads",
        "research_event_payloads",
        "research_note_payloads",
    }:
        return None
    if not delete_rows:
        raise ValueError("Research payloads can only be removed as complete immutable records.")
    return ProjectionMutationCost(
        scope_rows=0,
        mutation_rows=RESEARCH_EVENT_MUTATION_ROWS if table == "research_event_payloads" else 8,
        # Size-only metadata and the SQL charge trigger both read exact copied
        # columns; quota refunds use the same bytes only after the actual DELETE.
        payload_inspections=2,
    )
