from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from trading212_analytics import _historical_core as core
from trading212_analytics._selection_index import CalendarIndex, CalendarSelectionIndex
from trading212_analytics.historical import calculate_performance, verify_historical_result
from trading212_analytics.source_policy import _calendar_selection
from trading212_domain import DomainError, QualityState
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.historical_serialization import historical_canonical_bytes
from trading212_domain.sources import (
    BenchmarkObservation,
    BenchmarkSnapshot,
    MarketSession,
    ObservationState,
    PriceObservation,
    PriceSnapshot,
    SourceCalendar,
    SourceCoverage,
    SourceGap,
    SourcePeriod,
    SourceReason,
    SourceSelectionPolicy,
)

from .historical_factories import fixture, with_fx
from .source_factories import AT, USD, calendar, policy, price, series, uid

pytestmark = pytest.mark.unit


def assert_selection_parity(
    snapshots: tuple[PriceSnapshot | BenchmarkSnapshot, ...],
    *,
    selected_policy: SourceSelectionPolicy | None = None,
    cutoff: datetime = AT,
    selected_calendar: SourceCalendar | None = None,
) -> CalendarSelectionIndex:
    selected_calendar = selected_calendar or calendar()
    selected_series = snapshots[0].series
    assert selected_series is not None
    selected_policy = selected_policy or policy()
    prepared = CalendarSelectionIndex.prepare(
        snapshots,
        series_id=selected_series.id,
        calendar=CalendarIndex(selected_calendar),
        policy=selected_policy,
        cutoff=cutoff,
        budget=1000,
    )
    assert prepared is not None
    instants = {
        cutoff,
        cutoff - timedelta(microseconds=1),
        cutoff + timedelta(microseconds=1),
        *(AT + timedelta(days=days) for days in range(-3, 6)),
        *(
            session.close_at + timedelta(microseconds=delta)
            for session in selected_calendar.sessions
            for delta in (-1, 0, 1)
        ),
    }
    for at in sorted(instants):
        expected = _calendar_selection(
            snapshots,
            series_id=selected_series.id,
            calendar=selected_calendar,
            at=at,
            source_cutoff_at=cutoff,
            policy=selected_policy,
        )
        actual = prepared.select(at)
        assert actual == expected
        if actual[1] is not None and expected[1] is not None:
            assert actual[1].snapshot is expected[1].snapshot
            assert actual[1].observation is expected[1].observation
            assert actual[1].reference() == expected[1].reference()
    return prepared


@pytest.mark.parametrize("orders", [(1, 2), (2, 2), (None, 2), (None, None)])
@pytest.mark.parametrize("amount", ["100", "105"])
@pytest.mark.parametrize("knowledge", [-1, 0, 1])
def test_revision_and_knowledge_boundaries(
    orders: tuple[int | None, int | None],
    amount: str,
    knowledge: int,
) -> None:
    original = price(revision=orders[0])
    revision = price(amount, snapshot=21, revision=orders[1])
    revision = replace(
        revision,
        provenance=replace(
            revision.provenance,
            first_observed_at=AT + timedelta(microseconds=knowledge),
        ),
    )
    assert_selection_parity((revision, original))
    assert_selection_parity((original, revision))


@pytest.mark.parametrize(
    "reason", [SourceReason.MISSING_SESSION, SourceReason.DISPUTED, SourceReason.UNSUPPORTED]
)
@pytest.mark.parametrize("real_row", [False, True])
def test_gap_revisions_and_real_observation_suppression(
    reason: SourceReason, real_row: bool
) -> None:
    original = price()
    corrected = replace(
        price(snapshot=21, revision=2),
        observations=original.observations if real_row else (),
        coverage=SourceCoverage(
            expected_count=3,
            available_count=int(real_row),
            quality=QualityState.PARTIAL,
            gaps=(
                SourceGap(session_date=AT.date(), reason=reason, source_key="one"),
                SourceGap(
                    session_date=AT.date(), reason=SourceReason.MISSING_SESSION, source_key="two"
                ),
            ),
        ),
    )
    prepared = assert_selection_parity((corrected, original))
    assert prepared.count == (2 if real_row else 3)
    candidate, actual_reason = prepared.select(AT)[1:]
    if real_row:
        assert candidate is not None and candidate.snapshot is corrected
    else:
        assert candidate is None
        assert actual_reason is (
            SourceReason.MISSING_SESSION
            if reason is SourceReason.MISSING_SESSION
            else SourceReason.AMBIGUOUS_REVISION
        )


@pytest.mark.parametrize("future_source", [False, True])
@pytest.mark.parametrize("missing_provider", [False, True])
def test_empty_eligibility_reason_uses_all_providers_and_future_provenance(
    future_source: bool,
    missing_provider: bool,
) -> None:
    snapshot = replace(
        price(),
        observations=(replace(price().observations[0], effective_at=AT + timedelta(seconds=1)),),
    )
    if future_source:
        snapshot = replace(
            snapshot,
            provenance=replace(snapshot.provenance, effective_at=AT + timedelta(seconds=1)),
        )
    selected_policy = (
        replace(policy(), provider_priority=(uid(3),)) if missing_provider else policy()
    )
    prepared = assert_selection_parity((snapshot,), selected_policy=selected_policy)
    assert prepared.select(AT)[2] is (
        SourceReason.AFTER_CUTOFF if future_source else SourceReason.BEFORE_FIRST_OBSERVATION
    )
    eligible = assert_selection_parity((price(),), selected_policy=selected_policy)
    assert eligible.select(AT)[2] is (SourceReason.NO_OBSERVATIONS if missing_provider else None)


@pytest.mark.parametrize("carry", [False, True])
@pytest.mark.parametrize("age", [86399, 86400, 86401])
def test_strict_age_closed_session_and_calendar_edges(carry: bool, age: int) -> None:
    assert_selection_parity(
        (price(),),
        selected_policy=replace(policy(), allow_closed_session_carry=carry, max_age_seconds=age),
    )


def test_benchmark_and_original_observation_indices() -> None:
    sessions = calendar().sessions
    observations = tuple(
        BenchmarkObservation(
            session_date=s.session_date, effective_at=s.close_at, level=Decimal(i + 1)
        )
        for i, s in enumerate(sessions)
    )
    snapshot = BenchmarkSnapshot(
        id=uid(25),
        owner_id=uid(1),
        series=series(benchmark=True),
        provenance=price().provenance,
        period=calendar().period,
        coverage=SourceCoverage(
            expected_count=3, available_count=3, gaps=(), quality=QualityState.FRESH
        ),
        observations=tuple(reversed(observations)),
    )
    # Domain canonicalization fixes row order before either selector sees it.
    prepared = assert_selection_parity((snapshot,), cutoff=AT + timedelta(days=4))
    selected = prepared.select(sessions[-1].close_at)[1]
    assert selected is not None and selected.index == 2


@pytest.mark.parametrize("zone", ["UTC", "Europe/Athens", "America/New_York"])
def test_calendar_search_matches_original_across_dst_and_terminal_edges(zone: str) -> None:
    sessions = tuple(
        MarketSession(
            session_date=datetime(2026, 10, day).date(),
            close_at=datetime(2026, 10, day, 16, tzinfo=ZoneInfo(zone)).astimezone(UTC),
        )
        for day in (24, 25, 26)
    )
    source_calendar = SourceCalendar(
        id="dst",
        version="v1",
        timezone=zone,
        period=SourcePeriod(start=sessions[0].session_date, end=sessions[-1].session_date),
        sessions=sessions,
    )
    prepared = CalendarIndex(source_calendar)
    for session in sessions:
        for delta in (-1, 0, 1, 86400):
            at = session.close_at + timedelta(seconds=delta)
            matches = [s for s in sessions if s.close_at <= at]
            assert prepared.latest(at) == (matches[-1] if matches else None)


def test_gap_budget_falls_back_whole_descriptor_and_validates_first() -> None:
    snapshot = replace(
        price(),
        observations=(),
        coverage=SourceCoverage(
            expected_count=3,
            available_count=0,
            quality=QualityState.PARTIAL,
            gaps=tuple(
                SourceGap(
                    session_date=AT.date(),
                    reason=SourceReason.MISSING_SESSION,
                    source_key=f"gap-{i}",
                )
                for i in range(3)
            ),
        ),
    )
    assert (
        CalendarSelectionIndex.prepare(
            (snapshot,),
            series_id=snapshot.series.id,
            calendar=CalendarIndex(calendar()),
            policy=policy(),
            cutoff=AT,
            budget=2,
        )
        is None
    )
    prepared = CalendarSelectionIndex.prepare(
        (snapshot,),
        series_id=snapshot.series.id,
        calendar=CalendarIndex(calendar()),
        policy=policy(),
        cutoff=AT,
        budget=3,
    )
    assert prepared is not None and prepared.count == 3
    assert prepared.select(AT)[1] is None
    with pytest.raises(DomainError):
        CalendarSelectionIndex.prepare(
            (snapshot, snapshot),
            series_id=snapshot.series.id,
            calendar=CalendarIndex(calendar()),
            policy=policy(),
            cutoff=AT,
            budget=0,
        )
    with pytest.raises(DomainError):
        CalendarSelectionIndex.prepare(
            (snapshot,),
            series_id=uid(999),
            calendar=CalendarIndex(calendar()),
            policy=policy(),
            cutoff=AT,
            budget=0,
        )


@pytest.mark.parametrize("point_in_time", [False, True])
def test_engine_fallback_is_complete_and_not_rebuilt(point_in_time: bool) -> None:
    value = fixture()
    if point_in_time:
        value = replace(
            value,
            selection=replace(
                value.selection,
                window=replace(
                    value.selection.window,
                    knowledge_policy=d.KnowledgePolicy.POINT_IN_TIME,
                ),
            ),
        )
    with patch.object(core, "MAX_INDEX_CANDIDATES", 0):
        engine = core.HistoricalEngine(value)
    with patch.object(
        CalendarSelectionIndex, "prepare", wraps=CalendarSelectionIndex.prepare
    ) as prepare:
        for _ in range(2):
            engine.price(
                value.price_snapshots[0].series.id,
                value.selection.window.start_at,
                r.HistoricalUseConsumer(kind="portfolio"),
            )
            engine.price(
                value.price_snapshots[0].series.id,
                value.selection.window.end_at,
                r.HistoricalUseConsumer(kind="portfolio"),
            )
        assert prepare.call_count == (0 if point_in_time else 1)
        assert all(index is None for index in engine.selection_indexes.values())


@pytest.mark.parametrize("knowledge", list(d.KnowledgePolicy))
def test_full_result_evidence_parity_with_legacy_fallback(knowledge: d.KnowledgePolicy) -> None:
    value = with_fx(fixture(currency=USD), (".9",) * 4, base=USD)
    value = replace(
        value,
        selection=replace(
            value.selection, window=replace(value.selection.window, knowledge_policy=knowledge)
        ),
    )
    indexed = calculate_performance(
        value, options=r.PerformanceOptions(frequency=d.HistoricalFrequency.DAILY)
    )
    with patch.object(core, "MAX_INDEX_CANDIDATES", 0):
        legacy = calculate_performance(
            value, options=r.PerformanceOptions(frequency=d.HistoricalFrequency.DAILY)
        )
    verify_historical_result(value, indexed)
    assert historical_canonical_bytes(indexed) == historical_canonical_bytes(legacy)


def test_independent_descriptors_bind_objects_policy_and_cutoff() -> None:
    original, revised = price("100"), price("105")
    first = assert_selection_parity((original,))
    second = assert_selection_parity((revised,))
    assert first.snapshots[0] is original and second.snapshots[0] is revised
    assert first.select(AT)[1] != second.select(AT)[1]
    assert_selection_parity((original,), cutoff=AT - timedelta(microseconds=1))
    changed = replace(original, id=uid(21), series=replace(original.series, currency=USD))
    with pytest.raises(DomainError):
        CalendarSelectionIndex.prepare(
            (original, changed),
            series_id=original.series.id,
            calendar=CalendarIndex(calendar()),
            policy=policy(),
            cutoff=AT,
            budget=1000,
        )


def test_shared_selection_preserves_distinct_consumer_evidence() -> None:
    value = fixture()
    series_id = value.price_snapshots[0].series.id
    at = value.selection.window.start_at.replace(hour=16)
    consumers = (
        r.HistoricalUseConsumer(kind="portfolio"),
        r.HistoricalUseConsumer(kind="holding", listing_id=value.instruments[0].listing_id),
    )
    indexed = core.HistoricalEngine(value)
    with patch.object(core, "MAX_INDEX_CANDIDATES", 0):
        legacy = core.HistoricalEngine(value)
    for consumer in consumers:
        assert indexed.price(series_id, at, consumer) == legacy.price(series_id, at, consumer)
    assert len(indexed.selection_indexes) == 1
    assert len(indexed.uses) == 2
    assert indexed.uses == legacy.uses
    assert {use.consumer for use in indexed.uses.values()} == set(consumers)


def test_nonmonotonic_closes_preserve_last_original_session() -> None:
    # St John's rolled 00:01 back into the preceding date in 2009. These are
    # valid ordered session dates whose UTC closes are in reverse order.
    zone = ZoneInfo("America/St_Johns")
    local = (
        datetime(2009, 10, 31, 23, 59, tzinfo=zone, fold=1),
        datetime(2009, 11, 1, 0, 0, tzinfo=zone, fold=0),
    )
    sessions = tuple(
        MarketSession(session_date=t.date(), close_at=t.astimezone(UTC)) for t in local
    )
    captured_calendar = SourceCalendar(
        id="synthetic-utc",
        version="v1",
        timezone=zone.key,
        period=SourcePeriod(start=sessions[0].session_date, end=sessions[-1].session_date),
        sessions=sessions,
    )
    assert sessions[0].close_at > sessions[1].close_at
    prepared_calendar = CalendarIndex(captured_calendar)
    assert prepared_calendar.latest(sessions[0].close_at) is sessions[1]
    base = price()
    snapshot = replace(
        base,
        period=captured_calendar.period,
        provenance=replace(
            base.provenance,
            effective_at=sessions[1].close_at,
            first_observed_at=sessions[1].close_at,
        ),
        observations=tuple(
            PriceObservation(
                session_date=s.session_date, effective_at=s.close_at, value=Decimal(100 + i)
            )
            for i, s in enumerate(sessions)
        ),
        coverage=SourceCoverage(
            expected_count=2, available_count=2, gaps=(), quality=QualityState.FRESH
        ),
    )
    assert_selection_parity(
        (snapshot,),
        selected_calendar=captured_calendar,
        cutoff=sessions[0].close_at + timedelta(days=1),
    )


@pytest.mark.parametrize("missing", [False, True])
def test_preferred_provider_does_not_substitute_another_immutable_series(missing: bool) -> None:
    from trading212_analytics.source_policy import _Candidate, _choose

    preferred = price()
    if missing:
        preferred = replace(
            preferred,
            observations=(
                replace(preferred.observations[0], value=None, state=ObservationState.MISSING),
            ),
            coverage=SourceCoverage(
                expected_count=1, available_count=0, gaps=(), quality=QualityState.PARTIAL
            ),
        )
    lower = replace(
        price("105", snapshot=21),
        series=replace(series(), id=uid(99), provider_id=uid(3), license_version_id=uid(103)),
        provenance=replace(price().provenance, provider_id=uid(3), license_version_id=uid(103)),
        observations=(
            replace(price("105").observations[0], effective_at=AT + timedelta(seconds=1)),
        ),
    )
    winner, reason = _choose(
        (
            _Candidate(lower, 0, lower.observations[0]),
            _Candidate(preferred, 0, preferred.observations[0]),
        ),
        policy(),
    )
    assert winner is not None and winner.snapshot is preferred and reason is None
    prepared = assert_selection_parity(
        (preferred, lower),
        selected_policy=replace(policy(), max_age_seconds=0),
        cutoff=AT + timedelta(seconds=1),
    )
    assert prepared.select(AT + timedelta(seconds=1))[2] is (
        SourceReason.MISSING_SESSION if missing else SourceReason.STALE
    )
    conflicting_identity = replace(lower, series=replace(lower.series, id=preferred.series.id))
    # Provider and license belong to immutable series metadata. Both entry paths
    # must reject a provider change under the same series ID before selection.
    with pytest.raises(DomainError):
        _calendar_selection(
            (preferred, conflicting_identity),
            series_id=preferred.series.id,
            at=AT,
            source_cutoff_at=AT,
            policy=policy(),
            calendar=calendar(),
        )
    with pytest.raises(DomainError):
        CalendarSelectionIndex.prepare(
            (preferred, conflicting_identity),
            series_id=preferred.series.id,
            cutoff=AT,
            policy=policy(),
            calendar=CalendarIndex(calendar()),
            budget=1000,
        )
