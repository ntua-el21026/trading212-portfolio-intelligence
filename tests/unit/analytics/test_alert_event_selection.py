from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from trading212_analytics._historical_core import selected_event_revisions, selected_events
from trading212_domain import Money
from trading212_domain import historical as d

from .historical_factories import START, fixture, identity, with_events
from .source_factories import EUR, uid

pytestmark = pytest.mark.unit


def event(number: int, amount: str) -> d.HistoricalExternalFlow:
    return d.HistoricalExternalFlow(
        identity=identity(number, START),
        signed_amount=Money(Decimal(amount), EUR),
        kind="deposit",
        scope_proof="account_boundary",
    )


def test_standalone_selection_keeps_revision_order_knowledge_and_full_input_parity() -> None:
    first = event(100, "2")
    revised = replace(
        event(101, "3"),
        identity=replace(
            first.identity,
            revision_id=uid(101),
            source_record_id=uid(101),
            revision_sequence=2,
            first_observed_at=START + timedelta(seconds=1),
            supersedes_revision_id=uid(100),
        ),
    )
    candidates = (revised, first)
    assert selected_event_revisions(candidates, START) == ((first,), False)
    expected = ((revised,), False)
    assert selected_event_revisions(candidates, START + timedelta(seconds=1)) == expected
    assert (
        selected_events(with_events(fixture(), *candidates), START + timedelta(seconds=1))
        == expected
    )
    assert (
        selected_event_revisions(tuple(reversed(candidates)), START + timedelta(seconds=1))
        == expected
    )


def test_supersession_cycle_and_conflicting_equal_sequence_are_ambiguous_not_empty_max() -> None:
    first = event(100, "2")
    second = replace(
        event(101, "3"),
        identity=replace(first.identity, revision_id=uid(101), source_record_id=uid(101)),
    )
    assert selected_event_revisions((first, second), START) == ((), True)
    cycle = (
        replace(first, identity=replace(first.identity, supersedes_revision_id=uid(101))),
        replace(second, identity=replace(second.identity, supersedes_revision_id=uid(100))),
    )
    assert selected_event_revisions(cycle, START) == ((), True)
    assert selected_event_revisions((), START) == ((), False)
