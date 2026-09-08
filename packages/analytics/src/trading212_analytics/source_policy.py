"""Deterministic point-in-time reference selection and explicit FX derivation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, localcontext
from zoneinfo import ZoneInfo

from trading212_domain import CurrencyCode, DomainError, QualityState, exact_decimal, require_utc
from trading212_domain.errors import fail_validation
from trading212_domain.sources import (
    MAX_SOURCE_ROWS,
    SOURCE_QUANTUM,
    BenchmarkObservation,
    BenchmarkSelection,
    BenchmarkSnapshot,
    FxConversion,
    FxObservation,
    FxOperation,
    FxSnapshot,
    MarketSession,
    ObservationState,
    PriceObservation,
    PriceSelection,
    PriceSnapshot,
    SelectedSource,
    SourceAvailability,
    SourceCalendar,
    SourceCoverage,
    SourceGap,
    SourceLicense,
    SourcePeriod,
    SourceReason,
    SourceSelectionPolicy,
    SourceSnapshot,
    SourceUse,
    source_id,
    source_snapshot_digest,
    source_tuple,
)

# Historical reconstruction selects many observations from the same immutable
# snapshot. Keep its independently computed digest only for one calculation;
# never retain licensed payloads in a process-global memoization cache.
_DIGEST_SCOPE: ContextVar[dict[int, tuple[SourceSnapshot, str]] | None] = ContextVar(
    "source_selection_digest_scope", default=None
)


@contextmanager
def _source_digest_scope() -> Iterator[None]:
    if _DIGEST_SCOPE.get() is not None:
        yield
        return
    token = _DIGEST_SCOPE.set({})
    try:
        yield
    finally:
        _DIGEST_SCOPE.reset(token)


def _snapshot_digest(snapshot: SourceSnapshot) -> str:
    cache = _DIGEST_SCOPE.get()
    if cache is None:
        return source_snapshot_digest(snapshot)
    cached = cache.get(id(snapshot))
    if cached is not None and cached[0] is snapshot:
        return cached[1]
    result = source_snapshot_digest(snapshot)
    if len(cache) < 256:
        cache[id(snapshot)] = (snapshot, result)
    return result


@dataclass(frozen=True, slots=True)
class _Candidate:
    snapshot: SourceSnapshot
    index: int
    observation: PriceObservation | FxObservation | BenchmarkObservation

    @property
    def amount(self) -> Decimal | None:
        if isinstance(self.observation, PriceObservation):
            return self.observation.value
        if isinstance(self.observation, FxObservation):
            return self.observation.rate
        return self.observation.level

    def reference(self) -> SelectedSource:
        return SelectedSource(
            snapshot_id=self.snapshot.id,
            content_digest=_snapshot_digest(self.snapshot),
            provider_id=self.snapshot.provenance.provider_id,
            license_version_id=self.snapshot.provenance.license_version_id,
            observation_index=self.index,
            effective_at=self.observation.effective_at,
            first_observed_at=self.snapshot.provenance.first_observed_at,
        )


def _inputs(
    snapshots: tuple[SourceSnapshot, ...],
    at: datetime,
    cutoff: datetime,
    policy: SourceSelectionPolicy,
) -> tuple[datetime, datetime]:
    source_tuple(snapshots, (PriceSnapshot, FxSnapshot, BenchmarkSnapshot), "snapshots", 256)
    if len({x.owner_id for x in snapshots}) > 1 or len({x.id for x in snapshots}) != len(snapshots):
        fail_validation(
            "Source selection requires one owner and unique snapshots.", field="snapshots"
        )
    if sum(len(x.observations) for x in snapshots) > MAX_SOURCE_ROWS:
        fail_validation("Source selection exceeds its bounded row budget.", field="snapshots")
    if not isinstance(policy, SourceSelectionPolicy):
        fail_validation("A versioned source policy is required.", field="policy")
    return require_utc(at, field="at"), require_utc(cutoff, field="source_cutoff_at")


def _eligible(candidate: _Candidate, at: datetime, cutoff: datetime) -> bool:
    source = candidate.snapshot.provenance
    return (
        source.first_observed_at <= cutoff
        and source.effective_at <= cutoff
        and candidate.observation.effective_at <= at
        and candidate.observation.effective_at <= cutoff
    )


def _choose(
    candidates: tuple[_Candidate, ...], policy: SourceSelectionPolicy
) -> tuple[_Candidate | None, SourceReason | None]:
    for provider in policy.provider_priority:
        available = [x for x in candidates if x.snapshot.provenance.provider_id == provider]
        if not available:
            continue
        effective = max(x.observation.effective_at for x in available)
        latest = [x for x in available if x.observation.effective_at == effective]
        orders = [x.snapshot.provenance.revision_order for x in latest]
        if all(x is not None for x in orders):
            highest = max(x for x in orders if x is not None)
            latest = [x for x in latest if x.snapshot.provenance.revision_order == highest]
        economic_values = {(x.observation.state, x.amount) for x in latest}
        if len(economic_values) != 1:
            return None, SourceReason.AMBIGUOUS_REVISION
        return min(latest, key=lambda x: (x.snapshot.id, x.index)), None
    return None, SourceReason.NO_OBSERVATIONS


def _state_reason(candidate: _Candidate) -> SourceReason | None:
    return {
        ObservationState.AVAILABLE: None,
        ObservationState.MISSING: SourceReason.MISSING_SESSION,
        ObservationState.UNSUPPORTED: SourceReason.UNSUPPORTED,
        ObservationState.DISPUTED: SourceReason.DISPUTED,
    }[candidate.observation.state]


def _calendar_sources(
    snapshots: tuple[PriceSnapshot | BenchmarkSnapshot, ...],
    series_id: str,
    calendar: SourceCalendar,
) -> tuple[PriceSnapshot | BenchmarkSnapshot, ...]:
    source_id(series_id, "series_id")
    sources = tuple(x for x in snapshots if x.series is not None and x.series.id == series_id)
    if not sources:
        fail_validation(
            "The selected series is absent from the pinned source input.", field="series_id"
        )
    series = sources[0].series
    assert series is not None
    if any(x.series != series for x in sources):
        fail_validation("An immutable series identity cannot change its metadata.", field="series")
    if not isinstance(calendar, SourceCalendar) or (
        series.calendar_id,
        series.calendar_version,
    ) != (calendar.id, calendar.version):
        fail_validation("The source and versioned calendar must agree.", field="calendar")
    return sources


def _calendar_candidates(
    sources: tuple[PriceSnapshot | BenchmarkSnapshot, ...],
    calendar_sessions: dict[date, MarketSession],
) -> Iterator[_Candidate]:
    for source in sources:
        dates = set()
        for i, observation in enumerate(source.observations):
            assert isinstance(observation, (PriceObservation, BenchmarkObservation))
            yield _Candidate(source, i, observation)
            dates.add(observation.session_date)
        # A corrected dataset may remove an earlier observation. Its declared gap
        # remains a revision candidate, preventing fallback to superseded data.
        for gap in source.coverage.gaps:
            session = calendar_sessions.get(gap.session_date)
            if gap.session_date not in dates and session is not None:
                state = (
                    ObservationState.DISPUTED
                    if gap.reason is SourceReason.DISPUTED
                    else ObservationState.UNSUPPORTED
                    if gap.reason is SourceReason.UNSUPPORTED
                    else ObservationState.MISSING
                )
                missing = (
                    PriceObservation(
                        session_date=gap.session_date,
                        effective_at=session.close_at,
                        value=None,
                        state=state,
                    )
                    if isinstance(source, PriceSnapshot)
                    else BenchmarkObservation(
                        session_date=gap.session_date,
                        effective_at=session.close_at,
                        level=None,
                        state=state,
                    )
                )
                yield _Candidate(source, -1, missing)


def _calendar_selection(
    snapshots: tuple[PriceSnapshot | BenchmarkSnapshot, ...],
    *,
    series_id: str,
    at: datetime,
    source_cutoff_at: datetime,
    policy: SourceSelectionPolicy,
    calendar: SourceCalendar,
) -> tuple[CurrencyCode, _Candidate | None, SourceReason | None]:
    source_id(series_id, "series_id")
    at, cutoff = _inputs(snapshots, at, source_cutoff_at, policy)
    sources = _calendar_sources(snapshots, series_id, calendar)
    series = sources[0].series
    assert series is not None
    as_date = at.astimezone(ZoneInfo(calendar.timezone)).date()
    if not calendar.period.start <= as_date <= calendar.period.end:
        return series.currency, None, SourceReason.OUTSIDE_CALENDAR
    sessions = [x for x in calendar.sessions if x.close_at <= at]
    if not sessions:
        return series.currency, None, SourceReason.BEFORE_FIRST_OBSERVATION
    expected = sessions[-1]
    if as_date != expected.session_date and (
        not policy.allow_closed_session_carry
        or any(x.session_date == as_date for x in calendar.sessions)
    ):
        return series.currency, None, SourceReason.MISSING_SESSION
    all_candidates = tuple(
        _calendar_candidates(sources, {x.session_date: x for x in calendar.sessions})
    )
    candidates = tuple(x for x in all_candidates if _eligible(x, at, cutoff))
    candidate, reason = _choose(candidates, policy)
    if candidate is None:
        if reason is SourceReason.NO_OBSERVATIONS and all_candidates and not candidates:
            reason = (
                SourceReason.AFTER_CUTOFF
                if any(
                    x.snapshot.provenance.first_observed_at > cutoff
                    or x.snapshot.provenance.effective_at > cutoff
                    for x in all_candidates
                )
                else SourceReason.BEFORE_FIRST_OBSERVATION
            )
        return series.currency, None, reason
    if (
        candidate.observation.session_date != expected.session_date
        or candidate.observation.effective_at != expected.close_at
    ):
        return series.currency, None, SourceReason.MISSING_SESSION
    reason = _state_reason(candidate)
    if reason is not None:
        return series.currency, None, reason
    if at - candidate.observation.effective_at > timedelta(seconds=policy.max_age_seconds):
        return series.currency, candidate, SourceReason.STALE
    return series.currency, candidate, None


def select_price(
    snapshots: tuple[PriceSnapshot, ...],
    *,
    series_id: str,
    at: datetime,
    source_cutoff_at: datetime,
    policy: SourceSelectionPolicy,
    calendar: SourceCalendar,
) -> PriceSelection:
    source_tuple(snapshots, PriceSnapshot, "snapshots", 256)
    currency, candidate, reason = _calendar_selection(
        snapshots,
        series_id=series_id,
        at=at,
        source_cutoff_at=source_cutoff_at,
        policy=policy,
        calendar=calendar,
    )
    return PriceSelection(
        value=candidate.amount if candidate else None,
        currency=currency,
        availability=SourceAvailability.AVAILABLE
        if reason is None
        else SourceAvailability.PARTIAL
        if candidate
        else SourceAvailability.UNAVAILABLE,
        reason=reason,
        selected=candidate.reference() if candidate else None,
    )


def select_benchmark(
    snapshots: tuple[BenchmarkSnapshot, ...],
    *,
    series_id: str,
    at: datetime,
    source_cutoff_at: datetime,
    policy: SourceSelectionPolicy,
    calendar: SourceCalendar,
) -> BenchmarkSelection:
    source_tuple(snapshots, BenchmarkSnapshot, "snapshots", 256)
    currency, candidate, reason = _calendar_selection(
        snapshots,
        series_id=series_id,
        at=at,
        source_cutoff_at=source_cutoff_at,
        policy=policy,
        calendar=calendar,
    )
    return BenchmarkSelection(
        level=candidate.amount if candidate else None,
        currency=currency,
        availability=SourceAvailability.AVAILABLE
        if reason is None
        else SourceAvailability.PARTIAL
        if candidate
        else SourceAvailability.UNAVAILABLE,
        reason=reason,
        selected=candidate.reference() if candidate else None,
    )


def assess_source_coverage(
    calendar: SourceCalendar,
    period: SourcePeriod,
    observations: tuple[PriceObservation | BenchmarkObservation, ...],
) -> SourceCoverage:
    if not isinstance(calendar, SourceCalendar) or not isinstance(period, SourcePeriod):
        fail_validation("A typed calendar and source period are required.", field="calendar")
    if period.start < calendar.period.start or period.end > calendar.period.end:
        fail_validation("The calendar must cover the whole requested period.", field="period")
    source_tuple(
        observations, (PriceObservation, BenchmarkObservation), "observations", MAX_SOURCE_ROWS
    )
    expected = {
        x.session_date: x for x in calendar.sessions if period.start <= x.session_date <= period.end
    }
    observed = {x.session_date: x for x in observations}
    if len(observed) != len(observations) or any(x not in expected for x in observed):
        fail_validation(
            "Observation sessions are repeated or outside the calendar.", field="observations"
        )
    gaps = []
    for day, session in expected.items():
        observation = observed.get(day)
        if observation is None:
            gaps.append(SourceGap(session_date=day, reason=SourceReason.MISSING_SESSION))
        elif observation.effective_at != session.close_at:
            fail_validation(
                "Observation close must match the pinned session.", field="effective_at"
            )
        elif observation.state is not ObservationState.AVAILABLE:
            gaps.append(
                SourceGap(
                    session_date=day,
                    reason={
                        ObservationState.MISSING: SourceReason.MISSING_SESSION,
                        ObservationState.UNSUPPORTED: SourceReason.UNSUPPORTED,
                        ObservationState.DISPUTED: SourceReason.DISPUTED,
                    }[observation.state],
                )
            )
    return SourceCoverage(
        expected_count=len(expected),
        available_count=len(expected) - len(gaps),
        gaps=tuple(gaps),
        quality=QualityState.PARTIAL if gaps else QualityState.FRESH,
        reason=SourceReason.MISSING_SESSION if gaps else None,
    )


def assess_fx_coverage(
    calendar: SourceCalendar,
    period: SourcePeriod,
    observations: tuple[FxObservation, ...],
    *,
    pairs: tuple[tuple[CurrencyCode, CurrencyCode], ...],
) -> SourceCoverage:
    """Count every requested pair/fixing cell; missing pairs are not silently omitted."""
    if not isinstance(calendar, SourceCalendar) or not isinstance(period, SourcePeriod):
        fail_validation("A typed FX calendar and period are required.", field="calendar")
    if period.start < calendar.period.start or period.end > calendar.period.end:
        fail_validation("The calendar must cover the complete requested FX period.", field="period")
    if (
        not isinstance(pairs, tuple)
        or not 1 <= len(pairs) <= 32
        or any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or any(not isinstance(currency, CurrencyCode) for currency in pair)
            or pair[0] == pair[1]
            for pair in pairs
        )
        or len(set(pairs)) != len(pairs)
    ):
        fail_validation("FX coverage requires 1..32 distinct typed pairs.", field="pairs")
    source_tuple(observations, FxObservation, "observations", MAX_SOURCE_ROWS)
    sessions = {
        x.session_date: x for x in calendar.sessions if period.start <= x.session_date <= period.end
    }
    expected_count = len(sessions) * len(pairs)
    if expected_count > MAX_SOURCE_ROWS:
        fail_validation(
            "The FX request requires explicitly split bounded snapshots.", field="period"
        )
    observed = {(x.session_date, x.base, x.quote): x for x in observations}
    if len(observed) != len(observations) or any(
        day not in sessions or (base, quote) not in pairs for day, base, quote in observed
    ):
        fail_validation(
            "FX observations exceed the fixed pair/session scope.", field="observations"
        )
    gaps = []
    for day, session in sessions.items():
        for base, quote in sorted(pairs):
            observation = observed.get((day, base, quote))
            reason: SourceReason | None
            if observation is None:
                reason = SourceReason.MISSING_SESSION
            elif observation.effective_at != session.close_at:
                fail_validation(
                    "FX observation instant must match its declared fixing calendar.",
                    field="effective_at",
                )
            else:
                reason = {
                    ObservationState.AVAILABLE: None,
                    ObservationState.MISSING: SourceReason.MISSING_SESSION,
                    ObservationState.UNSUPPORTED: SourceReason.UNSUPPORTED,
                    ObservationState.DISPUTED: SourceReason.DISPUTED,
                }[observation.state]
            if reason is not None:
                gaps.append(
                    SourceGap(
                        session_date=day, reason=reason, source_key=f"{base.value}:{quote.value}"
                    )
                )
    return SourceCoverage(
        expected_count=expected_count,
        available_count=expected_count - len(gaps),
        gaps=tuple(gaps),
        quality=QualityState.PARTIAL if gaps else QualityState.FRESH,
        reason=SourceReason.MISSING_SESSION if gaps else None,
    )


def license_use_reason(
    license: SourceLicense,
    *,
    use: SourceUse,
    at: datetime,
    first_observed_at: datetime | None = None,
    deleted: bool = False,
) -> SourceReason | None:
    """Check immutable permitted use and expiry without exposing removed source content."""
    if (
        not isinstance(license, SourceLicense)
        or not isinstance(use, SourceUse)
        or type(deleted) is not bool
    ):
        fail_validation("A typed license and use are required.", field="license")
    at = require_utc(at, field="at")
    if first_observed_at is not None:
        first_observed_at = require_utc(first_observed_at, field="first_observed_at")
    if deleted:
        return SourceReason.RETENTION_REMOVED
    if license.effective_at > at or not license.permits(use):
        return SourceReason.LICENSE_DENIED
    if first_observed_at is not None:
        if first_observed_at > at:
            return SourceReason.AFTER_CUTOFF
        if license.retention_days is not None and at - first_observed_at >= timedelta(
            days=license.retention_days
        ):
            return SourceReason.EXPIRED
    return None


def select_fx(
    snapshots: tuple[FxSnapshot, ...],
    *,
    base: CurrencyCode,
    quote: CurrencyCode,
    at: datetime,
    source_cutoff_at: datetime,
    policy: SourceSelectionPolicy,
    calendar: SourceCalendar,
) -> FxConversion:
    source_tuple(snapshots, FxSnapshot, "snapshots", 256)
    at, cutoff = _inputs(snapshots, at, source_cutoff_at, policy)
    if not isinstance(base, CurrencyCode) or not isinstance(quote, CurrencyCode):
        fail_validation("FX selection requires explicit typed currencies.", field="currency")
    if base == quote:
        return FxConversion(
            base=base,
            quote=quote,
            rate=Decimal(1),
            operation=FxOperation.IDENTITY,
            availability=SourceAvailability.AVAILABLE,
            reason=None,
            sources=(),
        )
    if not isinstance(calendar, SourceCalendar) or any(
        (snapshot.calendar_id, snapshot.calendar_version) != (calendar.id, calendar.version)
        for snapshot in snapshots
    ):
        fail_validation("FX sources and the pinned fixing calendar must agree.", field="calendar")
    as_date = at.astimezone(ZoneInfo(calendar.timezone)).date()
    if not calendar.period.start <= as_date <= calendar.period.end:
        return _unavailable_fx(base, quote, SourceReason.OUTSIDE_CALENDAR)
    sessions = tuple(session for session in calendar.sessions if session.close_at <= at)
    if not sessions:
        return _unavailable_fx(base, quote, SourceReason.BEFORE_FIRST_OBSERVATION)
    expected = sessions[-1]
    if as_date != expected.session_date and (
        not policy.allow_closed_session_carry
        or any(session.session_date == as_date for session in calendar.sessions)
    ):
        return _unavailable_fx(base, quote, SourceReason.MISSING_SESSION)
    eligible = tuple(
        _Candidate(snapshot, i, item)
        for snapshot in snapshots
        for i, item in enumerate(snapshot.observations)
        if _eligible(_Candidate(snapshot, i, item), at, cutoff)
    )
    fresh = tuple(
        x
        for x in eligible
        if at - x.observation.effective_at <= timedelta(seconds=policy.max_age_seconds)
        and x.observation.session_date == expected.session_date
        and x.observation.effective_at == expected.close_at
    )
    if not fresh and eligible:
        freshness_reason = (
            SourceReason.STALE
            if any(x.observation.effective_at == expected.close_at for x in eligible)
            else SourceReason.MISSING_SESSION
        )
        return _unavailable_fx(base, quote, freshness_reason)
    last_reason = SourceReason.MISSING_FX_PAIR
    for operation, start, end in [
        (FxOperation.DIRECT, base, quote),
        *([(FxOperation.RECIPROCAL, quote, base)] if policy.allow_inverse_fx else []),
    ]:
        matching = tuple(
            x
            for x in fresh
            if isinstance(x.observation, FxObservation)
            and (x.observation.base, x.observation.quote) == (start, end)
        )
        chosen, reason = _choose(matching, policy)
        if reason is SourceReason.AMBIGUOUS_REVISION:
            return _unavailable_fx(base, quote, reason)
        if chosen is not None:
            gap_reason = _fx_gap_reason(chosen, snapshots, start, end, cutoff)
            if gap_reason is not None:
                return _unavailable_fx(base, quote, gap_reason)
            last_reason = _state_reason(chosen) or SourceReason.MISSING_FX_PAIR
            if chosen.amount is not None:
                with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
                    rate = (
                        chosen.amount
                        if operation is FxOperation.DIRECT
                        else Decimal(1) / chosen.amount
                    )
                return _fx_result(base, quote, operation, rate, (chosen,))
    pivot = policy.pivot_currency
    if pivot is not None and pivot not in {base, quote}:
        result = _pivot(fresh, base, quote, pivot, policy, snapshots, cutoff)
        if result is not None:
            return result
        if fresh:
            last_reason = SourceReason.INCOMPATIBLE_FIXING
    elif not fresh and eligible:
        last_reason = SourceReason.STALE
    return _unavailable_fx(base, quote, last_reason)


def _fx_gap_reason(
    chosen: _Candidate,
    snapshots: tuple[FxSnapshot, ...],
    base: CurrencyCode,
    quote: CurrencyCode,
    cutoff: datetime,
) -> SourceReason | None:
    for snapshot in snapshots:
        provenance = snapshot.provenance
        if (
            provenance.provider_id != chosen.snapshot.provenance.provider_id
            or provenance.first_observed_at > cutoff
            or provenance.effective_at > cutoff
        ):
            continue
        for gap in snapshot.coverage.gaps:
            if (
                gap.source_key not in {None, f"{base.value}:{quote.value}"}
                or gap.session_date != chosen.observation.session_date
            ):
                continue
            if gap.session_date == chosen.observation.session_date:
                old = chosen.snapshot.provenance.revision_order
                new = provenance.revision_order
                if old is None or new is None:
                    return SourceReason.AMBIGUOUS_REVISION
                if new < old:
                    continue
            return SourceReason.MISSING_SESSION
    return None


def _unavailable_fx(base: CurrencyCode, quote: CurrencyCode, reason: SourceReason) -> FxConversion:
    return FxConversion(
        base=base,
        quote=quote,
        rate=None,
        operation=FxOperation.UNAVAILABLE,
        availability=SourceAvailability.UNAVAILABLE,
        reason=reason,
        sources=(),
    )


def _fx_result(
    base: CurrencyCode,
    quote: CurrencyCode,
    operation: FxOperation,
    rate: Decimal,
    chosen: tuple[_Candidate, ...],
) -> FxConversion:
    try:
        with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
            rounded = exact_decimal(rate.quantize(SOURCE_QUANTUM))
        if rounded <= 0:
            return _unavailable_fx(base, quote, SourceReason.NUMERIC_UNREPRESENTABLE)
    except (DecimalException, DomainError):
        return _unavailable_fx(base, quote, SourceReason.NUMERIC_UNREPRESENTABLE)
    return FxConversion(
        base=base,
        quote=quote,
        rate=rounded,
        operation=operation,
        availability=SourceAvailability.AVAILABLE,
        reason=None,
        sources=tuple(x.reference() for x in chosen),
    )


def _pivot(
    candidates: tuple[_Candidate, ...],
    base: CurrencyCode,
    quote: CurrencyCode,
    pivot: CurrencyCode,
    policy: SourceSelectionPolicy,
    snapshots: tuple[FxSnapshot, ...],
    cutoff: datetime,
) -> FxConversion | None:
    # The v1 common-fixing policy requires the same immutable snapshot, batch and date.
    for provider in policy.provider_priority:
        groups: dict[tuple[str, str, date, datetime], list[_Candidate]] = {}
        relevant = {(base, pivot), (pivot, quote)}
        if policy.allow_inverse_fx:
            relevant.update({(pivot, base), (quote, pivot)})
        for item in candidates:
            observation = item.observation
            assert isinstance(observation, FxObservation)
            if (
                item.snapshot.provenance.provider_id == provider
                and (observation.base, observation.quote) in relevant
            ):
                groups.setdefault(
                    (
                        item.snapshot.id,
                        observation.batch_key,
                        observation.session_date,
                        observation.effective_at,
                    ),
                    [],
                ).append(item)
        alternatives: list[tuple[_Candidate, _Candidate, Decimal]] = []
        for batch_candidates in groups.values():
            # Snapshot uniqueness bounds each group to at most four relevant pairs.
            for first in batch_candidates:
                for second in batch_candidates:
                    a = _oriented(first, base, pivot, policy.allow_inverse_fx)
                    b = _oriented(second, pivot, quote, policy.allow_inverse_fx)
                    if a is not None and b is not None:
                        with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
                            alternatives.append((first, second, a * b))
        if not alternatives:
            continue
        instant = max(x[0].observation.effective_at for x in alternatives)
        alternatives = [x for x in alternatives if x[0].observation.effective_at == instant]
        orders = [x[0].snapshot.provenance.revision_order for x in alternatives]
        if all(x is not None for x in orders):
            order = max(x for x in orders if x is not None)
            alternatives = [
                x for x in alternatives if x[0].snapshot.provenance.revision_order == order
            ]
        if len({x[2] for x in alternatives}) != 1:
            return _unavailable_fx(base, quote, SourceReason.AMBIGUOUS_REVISION)
        first, second, rate = min(
            alternatives, key=lambda x: (x[0].snapshot.id, x[0].index, x[1].index)
        )
        for candidate in (first, second):
            observation = candidate.observation
            assert isinstance(observation, FxObservation)
            reason = _fx_gap_reason(
                candidate, snapshots, observation.base, observation.quote, cutoff
            )
            if reason is not None:
                return _unavailable_fx(base, quote, reason)
        return _fx_result(base, quote, FxOperation.TRIANGULATED, rate, (first, second))
    return None


def _oriented(
    candidate: _Candidate, base: CurrencyCode, quote: CurrencyCode, inverse: bool
) -> Decimal | None:
    observation = candidate.observation
    assert isinstance(observation, FxObservation)
    if observation.rate is None:
        return None
    if (observation.base, observation.quote) == (base, quote):
        return observation.rate
    if inverse and (observation.base, observation.quote) == (quote, base):
        with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
            return Decimal(1) / observation.rate
    return None
