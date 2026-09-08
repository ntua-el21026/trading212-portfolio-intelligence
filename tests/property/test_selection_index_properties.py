from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from trading212_domain import QualityState
from trading212_domain.sources import (
    ObservationState,
    PriceObservation,
    SourceCoverage,
    SourceGap,
    SourceReason,
)

from tests.unit.analytics.source_factories import AT, calendar, policy, price, uid
from tests.unit.analytics.test_selection_index import assert_selection_parity

pytestmark = pytest.mark.property


@settings(max_examples=140, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.lists(st.integers(0, 5), min_size=3, max_size=3),
            st.one_of(st.none(), st.integers(1, 3)),
            st.integers(-2, 2),
            st.integers(-1, 1),
            st.integers(1, 4),
        ),
        min_size=1,
        max_size=4,
    ),
    st.integers(-2, 4),
    st.booleans(),
    st.booleans(),
    st.integers(0, 4 * 86400),
)
def test_prepared_selection_matches_scan_for_revision_gap_and_cutoff_combinations(
    rows: list[tuple[list[int], int | None, int, int, int]],
    cutoff_day: int,
    include_provider: bool,
    carry: bool,
    age: int,
) -> None:
    source_calendar = calendar()
    states = (
        ObservationState.AVAILABLE,
        ObservationState.MISSING,
        ObservationState.DISPUTED,
        ObservationState.UNSUPPORTED,
    )
    snapshots = []
    for number, (codes, revision, knowledge_day, effective_delta, amount) in enumerate(rows):
        observations = tuple(
            PriceObservation(
                session_date=session.session_date,
                effective_at=session.close_at + timedelta(microseconds=effective_delta),
                value=Decimal(amount) if code == 0 else None,
                state=states[code],
            )
            for code, session in zip(codes, source_calendar.sessions, strict=True)
            if code < 4
        )
        gaps = tuple(
            SourceGap(session_date=session.session_date, reason=SourceReason.MISSING_SESSION)
            for code, session in zip(codes, source_calendar.sessions, strict=True)
            if code == 4
        )
        base = price(snapshot=20 + number, revision=revision)
        snapshots.append(
            replace(
                base,
                period=source_calendar.period,
                observations=tuple(reversed(observations)),
                provenance=replace(
                    base.provenance, first_observed_at=AT + timedelta(days=knowledge_day)
                ),
                coverage=SourceCoverage(
                    expected_count=len(observations) + len(gaps),
                    available_count=codes.count(0),
                    quality=QualityState.PARTIAL,
                    gaps=gaps,
                ),
            )
        )
    assert_selection_parity(
        tuple(snapshots),
        cutoff=AT + timedelta(days=cutoff_day),
        selected_policy=replace(
            policy(),
            provider_priority=(uid(3), uid(2)) if include_provider else (uid(3),),
            max_age_seconds=age,
            allow_closed_session_carry=carry,
        ),
    )
