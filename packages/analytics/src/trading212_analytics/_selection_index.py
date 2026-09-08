"""Bounded immutable calendar/series preparation owned by one historical engine."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from trading212_domain import CurrencyCode, require_utc
from trading212_domain.sources import (
    BenchmarkSnapshot,
    MarketSession,
    PriceSnapshot,
    SourceCalendar,
    SourceReason,
    SourceSelectionPolicy,
)

from .source_policy import (
    _calendar_candidates,
    _calendar_sources,
    _Candidate,
    _choose,
    _eligible,
    _inputs,
    _state_reason,
)

MAX_INDEX_CANDIDATES = 100_000
MAX_INDEX_SERIES = 256


class CalendarIndex:
    def __init__(self, calendar: SourceCalendar) -> None:
        self.calendar = calendar
        self.zone = ZoneInfo(calendar.timezone)
        self.sessions = {session.session_date: session for session in calendar.sessions}
        ordered = sorted(
            (session.close_at, index) for index, session in enumerate(calendar.sessions)
        )
        self.closes = tuple(close for close, _ in ordered)
        latest, prefixes = -1, []
        for _, index in ordered:
            latest = max(latest, index)
            prefixes.append(calendar.sessions[latest])
        # Preserve the last original eligible session, without a monotonic-close assumption.
        self.completed = tuple(prefixes)

    def latest(self, at: datetime) -> MarketSession | None:
        index = bisect_right(self.closes, at) - 1
        return self.completed[index] if index >= 0 else None


@dataclass(frozen=True, slots=True)
class _Timeline:
    times: tuple[datetime, ...]
    decisions: tuple[tuple[_Candidate | None, SourceReason | None], ...]


@dataclass(frozen=True, slots=True)
class CalendarSelectionIndex:
    # Strong references bind the exact captured objects, policy and cutoff; this
    # descriptor is never stored outside its owning engine or keyed by a digest.
    snapshots: tuple[PriceSnapshot | BenchmarkSnapshot, ...]
    calendar: CalendarIndex
    policy: SourceSelectionPolicy
    cutoff: datetime
    currency: CurrencyCode
    count: int
    future_provenance: bool
    first_eligible: datetime | None
    timelines: tuple[_Timeline, ...]

    @classmethod
    def prepare(
        cls,
        snapshots: tuple[PriceSnapshot | BenchmarkSnapshot, ...],
        *,
        series_id: str,
        calendar: CalendarIndex,
        policy: SourceSelectionPolicy,
        cutoff: datetime,
        budget: int,
    ) -> CalendarSelectionIndex | None:
        # Validation is mandatory even when preparation falls back for capacity.
        _inputs(snapshots, cutoff, cutoff, policy)
        sources = _calendar_sources(snapshots, series_id, calendar.calendar)
        series = sources[0].series
        assert series is not None
        candidates: list[_Candidate] = []
        for candidate in _calendar_candidates(sources, calendar.sessions):
            if len(candidates) >= budget:
                return None  # Discard the entire partial descriptor, never publish a prefix.
            candidates.append(candidate)
        buckets: dict[str, dict[datetime, list[_Candidate]]] = {}
        first_eligible: datetime | None = None
        future = False
        for candidate in candidates:
            provenance = candidate.snapshot.provenance
            future |= provenance.first_observed_at > cutoff or provenance.effective_at > cutoff
            if not _eligible(candidate, cutoff, cutoff):
                continue
            effective = candidate.observation.effective_at
            first_eligible = effective if first_eligible is None else min(first_eligible, effective)
            if provenance.provider_id in policy.provider_priority:
                buckets.setdefault(provenance.provider_id, {}).setdefault(effective, []).append(
                    candidate
                )
        timelines = []
        for provider in policy.provider_priority:
            times = tuple(sorted(buckets.get(provider, {})))
            timelines.append(
                _Timeline(
                    times, tuple(_choose(tuple(buckets[provider][at]), policy) for at in times)
                )
            )
        return cls(
            snapshots,
            calendar,
            policy,
            cutoff,
            series.currency,
            len(candidates),
            future,
            first_eligible,
            tuple(timelines),
        )

    def select(self, at: datetime) -> tuple[CurrencyCode, _Candidate | None, SourceReason | None]:
        at = require_utc(at, field="at")
        calendar, policy = self.calendar, self.policy
        day = at.astimezone(calendar.zone).date()
        if not calendar.calendar.period.start <= day <= calendar.calendar.period.end:
            return self.currency, None, SourceReason.OUTSIDE_CALENDAR
        expected = calendar.latest(at)
        if expected is None:
            return self.currency, None, SourceReason.BEFORE_FIRST_OBSERVATION
        if day != expected.session_date and (
            not policy.allow_closed_session_carry or day in calendar.sessions
        ):
            return self.currency, None, SourceReason.MISSING_SESSION
        candidate: _Candidate | None = None
        reason: SourceReason | None = SourceReason.NO_OBSERVATIONS
        for timeline in self.timelines:
            index = bisect_right(timeline.times, at) - 1
            if index >= 0:
                candidate, reason = timeline.decisions[index]
                break
        if candidate is None:
            if (
                reason is SourceReason.NO_OBSERVATIONS
                and self.count
                and (self.first_eligible is None or at < self.first_eligible)
            ):
                reason = (
                    SourceReason.AFTER_CUTOFF
                    if self.future_provenance
                    else SourceReason.BEFORE_FIRST_OBSERVATION
                )
            return self.currency, None, reason
        if (
            candidate.observation.session_date != expected.session_date
            or candidate.observation.effective_at != expected.close_at
        ):
            return self.currency, None, SourceReason.MISSING_SESSION
        state_reason = _state_reason(candidate)
        if state_reason is not None:
            return self.currency, None, state_reason
        reason = (
            SourceReason.STALE
            if at - candidate.observation.effective_at > timedelta(seconds=policy.max_age_seconds)
            else None
        )
        return self.currency, candidate, reason
