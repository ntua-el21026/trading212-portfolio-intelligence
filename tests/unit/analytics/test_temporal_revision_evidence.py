"""Raw knowledge, proof knowledge and alert eligibility have separate temporal roles."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from trading212_analytics._historical_core import (
    HistoricalEngine,
    revision_first_eligible_at,
    selected_event_revisions,
)
from trading212_domain import Money
from trading212_domain import historical as h
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.historical_serialization import historical_value_from_json
from trading212_domain.serialization import canonical_json

from tests.unit.analytics.historical_factories import START, fixture, identity, metric, source_ref
from tests.unit.analytics.source_factories import EUR, uid

pytestmark = pytest.mark.unit


def event(number: int, amount: str = "1", *, known_days: int = 0) -> h.HistoricalDividend:
    return h.HistoricalDividend(
        identity=replace(
            identity(number, START),
            first_observed_at=START + timedelta(days=known_days),
            revision_sequence=None,
        ),
        dividend_key="same-payment",
        instrument_id=None,
        listing_id=None,
        net=Money(Decimal(amount), EUR),
        gross=metric(amount),
        withholding=metric("0"),
        payment_convention="exact_provider_instant",
    )


def proof(
    new: h.HistoricalDividend, previous: h.HistoricalDividend, day: int
) -> h.HistoricalSourceReference:
    at = START + timedelta(days=day)
    return h.HistoricalSourceReference(
        kind="activity_revision_evidence",
        id=new.identity.source_record_id,
        effective_at=at,
        first_observed_at=at,
        semantic_digest="a" * 64,
        parent_ids=(new.identity.source_record_id, previous.identity.source_record_id),
    )


def test_one_later_pit_input_preserves_preproof_conflict_and_raw_bytes() -> None:
    old, new = event(100, "2"), event(101, "3", known_days=1)
    edge = proof(new, old, 3)
    base = fixture()
    value = replace(
        base,
        selection=replace(
            base.selection,
            window=replace(
                base.selection.window,
                source_cutoff_at=START + timedelta(days=4),
                knowledge_policy=h.KnowledgePolicy.POINT_IN_TIME,
            ),
        ),
        event_candidates=(old, new),
        sources=(*base.sources, source_ref(100), source_ref(101), edge),
    )
    before = canonical_json(value)
    decoded = historical_value_from_json(before, h.HistoricalInput)
    assert decoded == value and canonical_json(decoded) == before
    engine = HistoricalEngine(decoded)
    assert engine.events(START + timedelta(hours=12)) == ((old,), False)
    assert engine.events(START + timedelta(days=2)) == ((), True)
    assert engine.events(edge.first_observed_at - timedelta(microseconds=1)) == ((), True)
    selected, ambiguous = engine.events(edge.first_observed_at)
    assert not ambiguous and len(selected) == 1
    assert isinstance(selected[0], h.HistoricalDividend)
    assert selected[0].net == new.net
    assert selected[0].identity.first_observed_at == new.identity.first_observed_at
    assert selected[0].correction_of == old.identity.source_record_id
    assert value.event_candidates == (old, new) and canonical_json(value) == before


def test_late_bridge_eligibility_follows_only_the_winning_validated_chain() -> None:
    old, middle, new = event(100, "2"), event(101, "3"), event(102, "4")
    tail, bridge = proof(new, middle, 1), proof(middle, old, 3)
    # A separate branch of this same economic group cannot contaminate C's ancestry.
    other_old, other_new = event(103, "5"), event(104, "6")
    unrelated = proof(other_new, other_old, 4)
    events = (old, middle, new, other_old, other_new)
    assert selected_event_revisions(
        (old, middle, new), START + timedelta(days=2), revision_sources=(tail, bridge)
    ) == ((), True)
    early = revision_first_eligible_at(events, (tail, bridge, unrelated), cutoff=START)
    assert set(early.values()) == {START}
    eligible = revision_first_eligible_at(
        events, (unrelated, bridge, tail), cutoff=START + timedelta(days=4)
    )
    assert eligible[new.identity.source_record_id] == bridge.first_observed_at
    assert eligible[other_new.identity.source_record_id] == unrelated.first_observed_at
    assert eligible == revision_first_eligible_at(
        tuple(reversed(events)), (tail, bridge, unrelated), cutoff=START + timedelta(days=4)
    )
    selected, ambiguous = selected_event_revisions(
        (old, middle, new), bridge.first_observed_at, revision_sources=(tail, bridge)
    )
    assert not ambiguous and len(selected) == 1
    assert selected[0].identity.revision_id == new.identity.revision_id
    assert selected[0].identity.first_observed_at == START


@pytest.mark.parametrize(
    "invalid",
    (
        "missing_old",
        "missing_new",
        "duplicate_edge",
        "cycle",
        "mixed_cycle",
        "economic",
        "digest",
        "parent_shape",
        "native_conflict",
        "correction_conflict",
        "duplicate_source",
        "duplicate_revision",
        "duplicate_proof_id",
    ),
)
def test_invalid_explicit_proof_graphs_fail_closed(invalid: str) -> None:
    old, new = event(100), event(101, "2")
    edge = proof(new, old, 1)
    events: tuple[h.HistoricalEvent, ...] = (old, new)
    sources: tuple[h.HistoricalSourceReference, ...] = (edge,)
    if invalid == "missing_old":
        events = (new,)
    elif invalid == "missing_new":
        events = (old,)
    elif invalid == "duplicate_edge":
        sources = (edge, replace(edge, id=uid(999)))
    elif invalid == "cycle":
        sources = (edge, proof(old, new, 1))
    elif invalid == "mixed_cycle":
        events = (
            replace(
                old,
                identity=replace(
                    old.identity,
                    supersedes_revision_id=new.identity.revision_id,
                ),
            ),
            new,
        )
    elif invalid == "economic":
        events = (old, replace(new, dividend_key="different"))
    elif invalid == "digest":
        sources = (replace(edge, semantic_digest=None),)
    elif invalid == "parent_shape":
        sources = (replace(edge, parent_ids=(new.identity.source_record_id,)),)
    elif invalid == "native_conflict":
        events = (
            old,
            replace(new, identity=replace(new.identity, supersedes_revision_id=uid(999))),
        )
    elif invalid == "correction_conflict":
        events = (old, replace(new, correction_of=uid(999)))
    elif invalid == "duplicate_source":
        events = (old, new, replace(old, identity=replace(old.identity, revision_id=uid(999))))
    elif invalid == "duplicate_revision":
        events = (
            old,
            replace(new, identity=replace(new.identity, revision_id=old.identity.revision_id)),
        )
    else:
        third = event(102, "3")
        events = (old, new, third)
        sources = (edge, replace(proof(third, new, 2), id=edge.id))
    with pytest.raises(DomainError):
        revision_first_eligible_at(events, sources, cutoff=START + timedelta(days=2))
    with pytest.raises(DomainError):
        selected_event_revisions(events, START, revision_sources=sources)


def test_long_chain_is_iterative_bounded_and_order_independent() -> None:
    events = tuple(event(1000 + index) for index in range(2000))
    sources = tuple(
        proof(events[index], events[index - 1], 1 if index != 1 else 3)
        for index in range(1, len(events))
    )
    eligible = revision_first_eligible_at(
        tuple(reversed(events)), sources, cutoff=START + timedelta(days=3)
    )
    assert len(eligible) == len(events)
    assert eligible[events[-1].identity.source_record_id] == START + timedelta(days=3)
    assert eligible == revision_first_eligible_at(
        events, tuple(reversed(sources)), cutoff=START + timedelta(days=3)
    )


def test_attested_future_date_resolves_before_economic_filter_without_changing_native_path() -> (
    None
):
    old, new = event(100, "2"), event(101, "3")
    new = replace(new, identity=replace(new.identity, economic_at=START + timedelta(days=4)))
    edge = proof(new, old, 1)
    cutoff = START + timedelta(days=2)
    assert selected_event_revisions((old, new), cutoff) == ((old,), False)
    assert selected_event_revisions(
        (old, new),
        START,
        revision_sources=(edge,),
    ) == ((old,), False)
    assert selected_event_revisions((old, new), cutoff, revision_sources=(edge,)) == ((), False)
    selected, ambiguous = selected_event_revisions(
        (old, new),
        new.identity.economic_at,
        revision_sources=(edge,),
    )
    assert (
        not ambiguous
        and len(selected) == 1
        and selected[0].identity.revision_id == new.identity.revision_id
    )
    native = replace(
        new, identity=replace(new.identity, supersedes_revision_id=old.identity.revision_id)
    )
    assert selected_event_revisions((old, native), cutoff) == ((old,), False)
    assert selected_event_revisions((old, native), cutoff, revision_sources=(edge,)) == (
        (old,),
        False,
    )


@pytest.mark.parametrize("bound", ("events", "sources"))
def test_bounds_reject_the_entire_input_before_graph_work(bound: str) -> None:
    old, new = event(100), event(101)
    events: tuple[h.HistoricalEvent, ...] = (old, new)
    sources: tuple[h.HistoricalSourceReference, ...] = (proof(new, old, 1),)
    if bound == "events":
        events = (old,) * (h.MAX_HISTORICAL_EVENTS + 1)
    else:
        sources = sources * (h.MAX_HISTORICAL_SOURCES + 1)
    with pytest.raises(DomainError) as caught:
        revision_first_eligible_at(events, sources, cutoff=START)
    assert caught.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    with pytest.raises(DomainError) as caught:
        selected_event_revisions(events, START, revision_sources=sources)
    assert caught.value.code is ErrorCode.INPUT_BOUND_EXCEEDED


def test_attested_future_winner_becomes_eligible_when_its_economic_time_arrives() -> None:
    old, new = event(100, "2"), event(101, "3")
    new = replace(new, identity=replace(new.identity, economic_at=START + timedelta(days=4)))
    edge = proof(new, old, 1)
    assert (
        revision_first_eligible_at(
            (old, new),
            (edge,),
            cutoff=START + timedelta(days=2),
        )[new.identity.source_record_id]
        == new.identity.economic_at
    )


def test_native_supersession_and_sequence_keep_original_knowledge_and_bytes() -> None:
    old, new = event(100, "2", known_days=2), event(101, "3", known_days=1)
    old = replace(old, identity=replace(old.identity, revision_id=uid(1100)))
    new = replace(
        new,
        identity=replace(
            new.identity,
            revision_id=uid(1101),
            supersedes_revision_id=uid(1100),
        ),
    )
    cutoff = START + timedelta(days=2)
    encoded = canonical_json((old, new))
    assert selected_event_revisions((old, new), cutoff) == ((new,), False)
    redundant = proof(new, old, 3)
    assert selected_event_revisions((old, new), cutoff, revision_sources=(redundant,)) == (
        (new,),
        False,
    )
    assert (
        revision_first_eligible_at((old, new), (redundant,), cutoff=START + timedelta(days=4))[
            new.identity.source_record_id
        ]
        == new.identity.first_observed_at
    )
    assert canonical_json((old, new)) == encoded
    sequenced = replace(
        new,
        identity=replace(
            new.identity,
            supersedes_revision_id=None,
            revision_sequence=2,
        ),
    )
    first = replace(old, identity=replace(old.identity, revision_sequence=1))
    assert selected_event_revisions((first, sequenced), cutoff) == ((sequenced,), False)


def test_proof_projects_distinct_parent_revision_and_source_ids() -> None:
    old, new = event(100, "2"), event(101, "3", known_days=2)
    old = replace(old, identity=replace(old.identity, revision_id=uid(1100)))
    edge = proof(new, old, 1)
    assert selected_event_revisions(
        (old, new), edge.first_observed_at, revision_sources=(edge,)
    ) == ((old,), False)
    selected, ambiguous = selected_event_revisions(
        (old, new), START + timedelta(days=2), revision_sources=(edge,)
    )
    assert not ambiguous and len(selected) == 1
    winner = selected[0]
    assert isinstance(winner, h.HistoricalDividend)
    assert winner.identity.supersedes_revision_id == old.identity.revision_id
    assert winner.correction_of == old.identity.source_record_id
    assert new.identity.supersedes_revision_id is None and new.correction_of is None
    assert (
        revision_first_eligible_at((old, new), (edge,), cutoff=START + timedelta(days=2))[
            new.identity.source_record_id
        ]
        == new.identity.first_observed_at
    )


def test_no_proof_and_legacy_projected_inputs_remain_codec_compatible() -> None:
    value = fixture()
    before = canonical_json(value)
    restored = historical_value_from_json(before, h.HistoricalInput)
    assert restored == value and canonical_json(restored) == before
    assert HistoricalEngine(restored).events(START) == HistoricalEngine(value).events(START)
    assert canonical_json(value) == before
    old, new = event(100, "2"), event(101, "3", known_days=3)
    legacy = replace(
        new,
        identity=replace(
            new.identity,
            supersedes_revision_id=old.identity.revision_id,
        ),
        correction_of=old.identity.source_record_id,
    )
    legacy_bytes = canonical_json(legacy)
    assert historical_value_from_json(legacy_bytes, h.HistoricalDividend) == legacy
    assert selected_event_revisions(
        (old, legacy), START + timedelta(days=4), revision_sources=(proof(new, old, 3),)
    ) == ((legacy,), False)
