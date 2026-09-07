from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal, Inexact, Rounded, localcontext

import pytest
from trading212_analytics.source_policy import (
    assess_fx_coverage,
    assess_source_coverage,
    license_use_reason,
    select_benchmark,
    select_fx,
    select_price,
)
from trading212_domain import CurrencyCode, DomainError, QualityState
from trading212_domain.sources import (
    BenchmarkObservation,
    BenchmarkSnapshot,
    FxOperation,
    FxSnapshot,
    LicensePermission,
    MarketSession,
    ObservationState,
    PriceSelection,
    SourceAvailability,
    SourceCalendar,
    SourceCoverage,
    SourceGap,
    SourceLicense,
    SourcePeriod,
    SourceReason,
    SourceUse,
    source_snapshot_digest,
)

from .source_factories import (
    AT,
    EUR,
    GBP,
    USD,
    at_observation,
    calendar,
    fx,
    policy,
    price,
    series,
    uid,
)

pytestmark = pytest.mark.unit


def test_correction_is_unavailable_before_actual_first_knowledge() -> None:
    original = price("100")
    correction = replace(
        price("105", snapshot=21, revision=2),
        provenance=replace(
            price().provenance,
            source_revision="revision-2",
            revision_order=2,
            first_observed_at=AT + timedelta(days=2),
        ),
    )

    def selected(cutoff: datetime) -> Decimal | None:
        return select_price(
            (correction, original),
            series_id=original.series.id,
            at=AT,
            source_cutoff_at=cutoff,
            policy=policy(),
            calendar=calendar(),
        ).value

    assert selected(AT) == Decimal(100)
    assert selected(AT + timedelta(days=2)) == Decimal(105)
    assert source_snapshot_digest(original) != source_snapshot_digest(correction)


def test_unchanged_retrieval_keeps_semantic_digest_but_preserves_knowledge_reference() -> None:
    original = price()
    later = replace(
        original,
        id=uid(22),
        provenance=replace(original.provenance, first_observed_at=AT + timedelta(days=1)),
    )
    assert source_snapshot_digest(original) == source_snapshot_digest(later)
    result = select_price(
        (later,),
        series_id=later.series.id,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert result.value is None and result.reason is SourceReason.AFTER_CUTOFF


@pytest.mark.parametrize("revision", [None, 1])
def test_conflicting_unordered_or_tied_revisions_are_not_silently_selected(
    revision: int | None,
) -> None:
    a = price("100", revision=revision)
    b = price("105", snapshot=21, revision=revision)
    output = select_price(
        (b, a),
        series_id=a.series.id,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert output.availability is SourceAvailability.UNAVAILABLE
    assert output.reason is SourceReason.AMBIGUOUS_REVISION


def test_closed_calendar_carry_does_not_fill_a_missing_open_session() -> None:
    snapshot = price()

    def read(at: datetime, carry: bool = True) -> PriceSelection:
        return select_price(
            (snapshot,),
            series_id=snapshot.series.id,
            at=at,
            source_cutoff_at=at,
            policy=replace(policy(), allow_closed_session_carry=carry),
            calendar=calendar(),
        )

    saturday = AT + timedelta(days=1)
    carried = read(saturday)
    assert carried.value == Decimal(100)
    assert carried.selected is not None and carried.selected.effective_at == AT
    assert read(saturday, False).value is None
    assert read(AT + timedelta(days=3)).reason is SourceReason.MISSING_SESSION
    stale = select_price(
        (snapshot,),
        series_id=snapshot.series.id,
        at=saturday,
        source_cutoff_at=saturday,
        policy=replace(policy(), max_age_seconds=86399),
        calendar=calendar(),
    )
    assert stale.value == Decimal(100) and stale.reason is SourceReason.STALE
    assert stale.availability is SourceAvailability.PARTIAL


def test_missing_disputed_and_future_observations_do_not_become_zero_or_old_values() -> None:
    original = price()
    missing = replace(
        original,
        observations=(
            replace(original.observations[0], value=None, state=ObservationState.DISPUTED),
        ),
        coverage=SourceCoverage(
            expected_count=1,
            available_count=0,
            gaps=(SourceGap(session_date=AT.date(), reason=SourceReason.DISPUTED),),
            quality=QualityState.PARTIAL,
            reason=SourceReason.DISPUTED,
        ),
    )
    result = select_price(
        (missing,),
        series_id=original.series.id,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert result.value is None and result.reason is SourceReason.DISPUTED
    previous = at_observation(price(snapshot=21), AT - timedelta(days=1))
    result = select_price(
        (original, previous),
        series_id=original.series.id,
        at=AT - timedelta(days=1),
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert result.selected is not None and result.selected.snapshot_id == previous.id
    assert result.selected.effective_at == AT - timedelta(days=1)


def test_calendar_gaps_and_dst_use_explicit_session_instants() -> None:
    ny = SourceCalendar(
        id="synthetic-ny",
        version="dst-test",
        timezone="America/New_York",
        period=SourcePeriod(start=date(2026, 3, 6), end=date(2026, 3, 9)),
        sessions=(
            MarketSession(
                session_date=date(2026, 3, 6), close_at=datetime(2026, 3, 6, 21, tzinfo=UTC)
            ),
            MarketSession(
                session_date=date(2026, 3, 9), close_at=datetime(2026, 3, 9, 20, tzinfo=UTC)
            ),
        ),
    )
    observation = replace(
        price().observations[0],
        session_date=date(2026, 3, 6),
        effective_at=datetime(2026, 3, 6, 21, tzinfo=UTC),
    )
    coverage = assess_source_coverage(ny, ny.period, (observation,))
    assert (coverage.expected_count, coverage.available_count) == (2, 1)
    assert coverage.gaps == (
        SourceGap(session_date=date(2026, 3, 9), reason=SourceReason.MISSING_SESSION),
    )
    with pytest.raises(DomainError):
        assess_source_coverage(
            ny,
            ny.period,
            (replace(observation, effective_at=observation.effective_at + timedelta(hours=1)),),
        )


def test_raw_benchmark_level_selection_preserves_source_kind_and_basis() -> None:
    original = price()
    snapshot = BenchmarkSnapshot(
        id=uid(44),
        owner_id=original.owner_id,
        series=series(benchmark=True),
        provenance=original.provenance,
        period=original.period,
        coverage=original.coverage,
        observations=(
            BenchmarkObservation(session_date=AT.date(), effective_at=AT, level=Decimal("125.125")),
        ),
    )
    assert snapshot.series is not None
    result = select_benchmark(
        (snapshot,),
        series_id=snapshot.series.id,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert result.level == Decimal("125.125")
    assert result.selected is not None and result.selected.snapshot_id == snapshot.id


def test_fx_direct_precedes_reciprocal_then_one_provider_priority() -> None:
    a = fx((USD, EUR, "0.8"), provider=2)
    b = fx((EUR, USD, "1.2"), provider=3, snapshot=31)
    result = select_fx(
        (a, b),
        base=EUR,
        quote=USD,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert result.operation is FxOperation.DIRECT and result.rate == Decimal("1.2")
    assert result.sources[0].provider_id == uid(3)
    result = select_fx(
        (a,), base=EUR, quote=USD, at=AT, source_cutoff_at=AT, policy=policy(), calendar=calendar()
    )
    assert result.operation is FxOperation.RECIPROCAL and result.rate == Decimal("1.25")
    direct = fx((EUR, USD, "1.3"), snapshot=32)
    result = select_fx(
        (b, direct),
        base=EUR,
        quote=USD,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert result.rate == Decimal("1.3") and result.sources[0].provider_id == uid(2)


def test_fx_single_pivot_hand_reference_is_exact_and_preserves_both_legs() -> None:
    snapshot = fx((GBP, EUR, "1.1"), (EUR, USD, "1.2"))
    result = select_fx(
        (snapshot,),
        base=GBP,
        quote=USD,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert result.operation is FxOperation.TRIANGULATED and result.rate == Decimal("1.32")
    assert len(result.sources) == 2 and {x.snapshot_id for x in result.sources} == {snapshot.id}
    assert len({x.observation_index for x in result.sources}) == 2
    assert all(x.content_digest == source_snapshot_digest(snapshot) for x in result.sources)


@pytest.mark.parametrize("change", ["provider", "snapshot", "batch", "session"])
def test_fx_never_combines_incompatible_pivot_legs(change: str) -> None:
    snapshot = fx((GBP, EUR, "1.1"), (EUR, USD, "1.2"))
    snapshots: tuple[FxSnapshot, ...]
    if change in {"provider", "snapshot"}:
        snapshots = (
            fx((GBP, EUR, "1.1")),
            fx((EUR, USD, "1.2"), snapshot=31, provider=3 if change == "provider" else 2),
        )
    else:
        observations = list(snapshot.observations)
        observations[0] = (
            replace(observations[0], batch_key="other-fixing")
            if change == "batch"
            else replace(
                observations[0],
                session_date=(AT - timedelta(days=1)).date(),
                effective_at=AT - timedelta(days=1),
            )
        )
        snapshots = (
            replace(
                snapshot,
                period=SourcePeriod(start=(AT - timedelta(days=1)).date(), end=AT.date()),
                observations=tuple(observations),
            ),
        )
    result = select_fx(
        snapshots,
        base=GBP,
        quote=USD,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert result.rate is None and result.reason is SourceReason.INCOMPATIBLE_FIXING


def test_fx_identity_missing_stale_and_rounding_overflow_are_distinct() -> None:
    identity = select_fx(
        (), base=EUR, quote=EUR, at=AT, source_cutoff_at=AT, policy=policy(), calendar=calendar()
    )
    assert (
        identity.rate == 1 and identity.operation is FxOperation.IDENTITY and identity.sources == ()
    )
    missing = select_fx(
        (), base=EUR, quote=USD, at=AT, source_cutoff_at=AT, policy=policy(), calendar=calendar()
    )
    assert missing.rate is None and missing.reason is SourceReason.MISSING_FX_PAIR
    snapshot = fx((EUR, USD, "1.2"))
    stale = select_fx(
        (snapshot,),
        base=EUR,
        quote=USD,
        at=AT + timedelta(seconds=2),
        source_cutoff_at=AT,
        policy=replace(policy(), max_age_seconds=1, pivot_currency=None),
        calendar=calendar(),
    )
    assert stale.reason is SourceReason.STALE and stale.rate is None
    overflow = select_fx(
        (fx((GBP, EUR, "99999999999999999999"), (EUR, USD, "99999999999999999999")),),
        base=GBP,
        quote=USD,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert overflow.rate is None and overflow.reason is SourceReason.NUMERIC_UNREPRESENTABLE


def test_fx_ignores_future_corrections_and_ambient_decimal_context() -> None:
    original = fx((USD, EUR, "3"))
    future = replace(
        fx((USD, EUR, "4"), snapshot=31, revision=2),
        provenance=replace(
            original.provenance,
            source_revision="revision-2",
            revision_order=2,
            first_observed_at=AT + timedelta(seconds=1),
        ),
    )
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        result = select_fx(
            (future, original),
            base=EUR,
            quote=USD,
            at=AT,
            source_cutoff_at=AT,
            policy=policy(),
            calendar=calendar(),
        )
    assert result.rate == Decimal("0.333333333333333333")
    assert result.sources[0].snapshot_id == original.id


def test_cross_owner_source_set_rejects_before_selection() -> None:
    with pytest.raises(DomainError):
        select_fx(
            (fx((EUR, USD, "1.2")), replace(fx((EUR, USD, "1.3"), snapshot=31), owner_id=uid(99))),
            base=EUR,
            quote=USD,
            at=AT,
            source_cutoff_at=AT,
            policy=policy(),
            calendar=calendar(),
        )


def test_corrected_missing_price_does_not_resurrect_old_observation() -> None:
    original = price()
    missing = replace(
        original,
        id=uid(21),
        observations=(),
        coverage=SourceCoverage(
            expected_count=1,
            available_count=0,
            gaps=(SourceGap(session_date=AT.date(), reason=SourceReason.MISSING_SESSION),),
            quality=QualityState.PARTIAL,
            reason=SourceReason.MISSING_SESSION,
        ),
        provenance=replace(
            original.provenance,
            source_revision="revision-2",
            revision_order=2,
            first_observed_at=AT + timedelta(seconds=1),
        ),
    )
    before = select_price(
        (original, missing),
        series_id=original.series.id,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert before.value == 100
    after = select_price(
        (original, missing),
        series_id=original.series.id,
        at=AT,
        source_cutoff_at=AT + timedelta(seconds=1),
        policy=policy(),
        calendar=calendar(),
    )
    assert after.value is None and after.reason is SourceReason.MISSING_SESSION


def test_corrected_missing_fx_pair_is_not_replaced_by_old_rate() -> None:
    original = fx((EUR, USD, "1.2"))
    missing = replace(
        original,
        id=uid(31),
        observations=(),
        coverage=SourceCoverage(
            expected_count=1,
            available_count=0,
            gaps=(
                SourceGap(
                    session_date=AT.date(),
                    reason=SourceReason.MISSING_SESSION,
                    source_key="EUR:USD",
                ),
            ),
            quality=QualityState.PARTIAL,
            reason=SourceReason.MISSING_SESSION,
        ),
        provenance=replace(
            original.provenance,
            source_revision="revision-2",
            revision_order=2,
            first_observed_at=AT + timedelta(seconds=1),
        ),
    )
    before = select_fx(
        (original, missing),
        base=EUR,
        quote=USD,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=calendar(),
    )
    assert before.rate == Decimal("1.2")
    after = select_fx(
        (original, missing),
        base=EUR,
        quote=USD,
        at=AT,
        source_cutoff_at=AT + timedelta(seconds=1),
        policy=policy(),
        calendar=calendar(),
    )
    assert after.rate is None and after.reason is SourceReason.MISSING_SESSION


def test_fx_coverage_counts_every_pair_and_fixing_without_silent_omission() -> None:
    snapshot = fx((GBP, EUR, "1.1"), (EUR, USD, "1.2"))
    value = assess_fx_coverage(
        calendar(), calendar().period, snapshot.observations, pairs=((GBP, EUR), (EUR, USD))
    )
    assert (value.expected_count, value.available_count, len(value.gaps)) == (6, 2, 4)
    assert {x.source_key for x in value.gaps} == {"GBP:EUR", "EUR:USD"}
    assert {x.session_date for x in value.gaps} == {date(2026, 9, 3), date(2026, 9, 7)}
    assert value.quality is QualityState.PARTIAL


def test_license_use_rejects_unknown_retention_boundary_and_removed_replay() -> None:
    license = SourceLicense(
        id=uid(102),
        provider_id=uid(2),
        version="v1",
        effective_at=AT,
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.UNKNOWN,
        export=LicensePermission.DENIED,
        retention_days=30,
        attribution="Synthetic source",
        evidence_key="fixture-license",
    )
    expires = AT + timedelta(days=30)
    assert (
        license_use_reason(
            license,
            use=SourceUse.DISPLAY,
            at=expires - timedelta(microseconds=1),
            first_observed_at=AT,
        )
        is None
    )
    assert (
        license_use_reason(license, use=SourceUse.DISPLAY, at=expires, first_observed_at=AT)
        is SourceReason.EXPIRED
    )
    assert (
        license_use_reason(license, use=SourceUse.REPORT, at=AT, first_observed_at=AT)
        is SourceReason.LICENSE_DENIED
    )
    assert (
        license_use_reason(
            license, use=SourceUse.DISPLAY, at=AT, first_observed_at=AT, deleted=True
        )
        is SourceReason.RETENTION_REMOVED
    )


@pytest.mark.parametrize(
    "base,pairs,expected",
    [
        (EUR, ((EUR, USD, "1.2"),), Decimal("1.2")),
        (GBP, ((GBP, EUR, "1.1"), (EUR, USD, "1.2")), Decimal("1.32")),
    ],
)
def test_fx_calendar_allows_declared_closed_carry_but_never_misses_open_fixing(
    base: CurrencyCode,
    pairs: tuple[tuple[CurrencyCode, CurrencyCode, str], ...],
    expected: Decimal,
) -> None:
    snapshot = fx(*pairs)
    weekend = AT + timedelta(days=1)
    carried = select_fx(
        (snapshot,),
        base=base,
        quote=USD,
        at=weekend,
        source_cutoff_at=weekend,
        policy=policy(),
        calendar=calendar(),
    )
    assert carried.rate == expected
    assert all(source.effective_at == AT for source in carried.sources)
    prohibited = select_fx(
        (snapshot,),
        base=base,
        quote=USD,
        at=weekend,
        source_cutoff_at=weekend,
        policy=replace(policy(), allow_closed_session_carry=False),
        calendar=calendar(),
    )
    assert prohibited.rate is None and prohibited.reason is SourceReason.MISSING_SESSION
    next_open = AT + timedelta(days=3)
    missing = select_fx(
        (snapshot,),
        base=base,
        quote=USD,
        at=next_open,
        source_cutoff_at=next_open,
        policy=policy(),
        calendar=calendar(),
    )
    assert missing.rate is None and missing.reason is SourceReason.MISSING_SESSION


def test_fx_calendar_identity_cannot_be_replaced_by_another_registered_version() -> None:
    with pytest.raises(DomainError):
        select_fx(
            (fx((EUR, USD, "1.2")),),
            base=EUR,
            quote=USD,
            at=AT,
            source_cutoff_at=AT,
            policy=policy(),
            calendar=replace(calendar(), version="v2"),
        )


def test_fx_correction_uses_fixing_calendar_date_even_when_utc_date_differs() -> None:
    local_date = date(2026, 9, 5)
    local_calendar = SourceCalendar(
        id="synthetic-sydney",
        version="1",
        timezone="Australia/Sydney",
        period=SourcePeriod(start=local_date, end=local_date),
        sessions=(MarketSession(session_date=local_date, close_at=AT),),
    )
    source = fx((EUR, USD, "1.2"))
    original = replace(
        source,
        calendar_id=local_calendar.id,
        calendar_version=local_calendar.version,
        period=local_calendar.period,
        observations=tuple(replace(row, session_date=local_date) for row in source.observations),
    )
    correction = replace(
        original,
        id=uid(31),
        observations=(),
        provenance=replace(original.provenance, source_revision="2", revision_order=2),
        coverage=SourceCoverage(
            expected_count=1,
            available_count=0,
            gaps=(
                SourceGap(
                    session_date=local_date,
                    reason=SourceReason.MISSING_SESSION,
                    source_key="EUR:USD",
                ),
            ),
            quality=QualityState.PARTIAL,
            reason=SourceReason.MISSING_SESSION,
        ),
    )
    value = select_fx(
        (original, correction),
        base=EUR,
        quote=USD,
        at=AT,
        source_cutoff_at=AT,
        policy=policy(),
        calendar=local_calendar,
    )
    assert value.rate is None and value.reason is SourceReason.MISSING_SESSION
