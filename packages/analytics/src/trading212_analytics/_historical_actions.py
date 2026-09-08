"""Cutoff-selected reference actions and explicit completed-session absence evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from trading212_domain import QualityState
from trading212_domain import historical as d
from trading212_domain.serialization import canonical_json
from trading212_domain.source_details import CorporateActionSnapshot


@dataclass(frozen=True, slots=True)
class SelectedActions:
    observations: tuple[tuple[CorporateActionSnapshot, int], ...]
    coverage_snapshots: tuple[CorporateActionSnapshot, ...]
    complete: bool


def _choose(
    snapshots: tuple[CorporateActionSnapshot, ...], day: date
) -> CorporateActionSnapshot | None:
    # An original singleton needs only the inclusive period check; revision
    # filtering cannot change which snapshot wins.
    if len(snapshots) == 1:
        snapshot = snapshots[0]
        return snapshot if snapshot.period.start <= day <= snapshot.period.end else None
    candidates = tuple(item for item in snapshots if item.period.start <= day <= item.period.end)
    if not candidates:
        return None
    if all(item.provenance.revision_order is not None for item in candidates):
        latest = max(item.provenance.revision_order or 0 for item in candidates)
        candidates = tuple(item for item in candidates if item.provenance.revision_order == latest)
    # A single validated candidate cannot conflict with another snapshot. Avoid
    # serializing its session proof again for every subsequent valuation date.
    if len(candidates) == 1:
        return candidates[0]
    # Receipt recency is never a revision order. Equal per-session economics may
    # occur in overlapping full/partial retrieval windows without being revisions.
    signatures = {
        canonical_json(
            (
                tuple(row for row in item.observations if row.session_date == day),
                tuple(gap for gap in item.coverage.gaps if gap.session_date == day),
                item.coverage.quality,
                item.coverage.available_count == item.coverage.expected_count,
            )
        )
        for item in candidates
    }
    if len(signatures) != 1:
        return None
    return min(candidates, key=lambda item: (item.provenance.first_observed_at, item.id))


def select_actions(
    value: d.HistoricalInput,
    *,
    listing_ids: frozenset[str],
    start: datetime,
    through: datetime,
    cutoff: datetime,
) -> SelectedActions:
    policy = value.selection.source_policy
    if not listing_ids:
        return SelectedActions((), (), True)
    if policy is None:
        return SelectedActions((), (), False)
    calendars = {(item.id, item.version): item for item in value.calendars}
    selected: dict[tuple[str, int], tuple[CorporateActionSnapshot, int]] = {}
    coverage: dict[str, CorporateActionSnapshot] = {}
    complete = True
    for listing in sorted(listing_ids):
        available = tuple(
            item
            for item in value.action_snapshots
            if item.series.listing_id == listing
            and item.provenance.provider_id in policy.provider_priority
            and item.provenance.first_observed_at <= cutoff
            and item.provenance.effective_at <= cutoff
        )
        if not available:
            complete = False
            continue
        series_id = min(
            available,
            key=lambda item: (
                policy.provider_priority.index(item.provenance.provider_id),
                item.series.id,
            ),
        ).series.id
        snapshots = tuple(item for item in available if item.series.id == series_id)
        series = snapshots[0].series
        calendar = calendars[(series.calendar_id, series.calendar_version)]
        sessions = tuple(
            session for session in calendar.sessions if start <= session.close_at <= through
        )
        if not sessions:
            # No newly completed session does not waive the opening session proof.
            previous = tuple(session for session in calendar.sessions if session.close_at <= start)
            sessions = previous[-1:]
        if not sessions or (
            through > calendar.sessions[-1].close_at and not policy.allow_closed_session_carry
        ):
            complete = False
        days = {session.session_date for session in sessions}
        days.update(
            observation.session_date
            for snapshot in snapshots
            for observation in snapshot.observations
            if start <= observation.effective_at <= through
        )
        for day in sorted(days):
            snapshot = _choose(snapshots, day)
            if snapshot is None:
                complete = False
                continue
            coverage[snapshot.id] = snapshot
            if snapshot.coverage.quality is not QualityState.FRESH:
                complete = False
            for index, observation in enumerate(snapshot.observations):
                if observation.session_date == day and observation.effective_at <= through:
                    selected[(snapshot.id, index)] = (snapshot, index)
    observations = tuple(
        sorted(
            selected.values(),
            key=lambda pair: (
                pair[0].observations[pair[1]].effective_at,
                pair[0].series.id,
                pair[0].observations[pair[1]].source_key,
                pair[0].id,
            ),
        )
    )
    # Corrections explicitly identify the older provider action; they do not add
    # another split. Replacing an unavailable fact remains a coverage decision.
    corrected = {
        (snapshot.series.id, snapshot.observations[index].correction_source_key)
        for snapshot, index in observations
        if snapshot.observations[index].correction_source_key is not None
    }
    observations = tuple(
        (snapshot, index)
        for snapshot, index in observations
        if (snapshot.series.id, snapshot.observations[index].source_key) not in corrected
    )
    return SelectedActions(observations, tuple(coverage[key] for key in sorted(coverage)), complete)
