"""Independent compatibility examples and fixed ordered orchestration boundaries."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, Inexact, localcontext
from typing import Any
from uuid import UUID

import pytest
from trading212_application import source_fallback as app
from trading212_domain import CurrencyCode, QualityState
from trading212_domain.sources import PriceBasis, SourcePeriod
from trading212_security.principals import Principal, Scope

AT = datetime(2026, 9, 15, 12, tzinfo=UTC)
OWNER, ACCOUNT, CALENDAR, INSTRUMENT = (UUID(int=x) for x in range(1, 5))
A = app.RetainedSourceCandidate(snapshot_id=UUID(int=10), content_digest="a" * 64)
B = app.RetainedSourceCandidate(snapshot_id=UUID(int=11), content_digest="b" * 64)
C = app.RetainedSourceCandidate(snapshot_id=UUID(int=12), content_digest="c" * 64)
PERIOD = SourcePeriod(start=date(2026, 9, 1), end=date(2026, 9, 14))
PRINCIPAL = Principal(
    str(OWNER),
    str(OWNER),
    "https://issuer.example",
    "opaque-subject",
    frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}),
    AT - timedelta(days=1),
    AT + timedelta(days=1),
)


def plan(**changes: Any) -> app.PriceFallbackPlan:
    return replace(
        app.PriceFallbackPlan(
            owner_id=OWNER,
            account_id=ACCOUNT,
            calendar_id=CALENDAR,
            calendar_version="v1",
            period=PERIOD,
            source_cutoff_at=AT,
            candidates=(A, B, C),
            instrument_id=INSTRUMENT,
            currency=CurrencyCode("EUR"),
            basis=PriceBasis.RAW_CLOSE,
        ),
        **changes,
    )


def facts(candidate: app.RetainedSourceCandidate = A, **changes: Any) -> app.FallbackSourceFacts:
    return replace(
        app.FallbackSourceFacts(
            family="price",
            snapshot_id=candidate.snapshot_id,
            content_digest=candidate.content_digest,
            provider_id=UUID(int=5),
            license_version_id=UUID(int=6),
            calendar_id=CALENDAR,
            calendar_version="v1",
            period=PERIOD,
            first_known_at=AT - timedelta(hours=1),
            original_expires_at=AT + timedelta(days=1),
            latest_observation_at=AT - timedelta(days=1),
            expected_count=10,
            available_count=10,
            quality=QualityState.FRESH,
            synthetic=False,
            instrument_id=INSTRUMENT,
            currency=CurrencyCode("EUR"),
            basis=PriceBasis.RAW_CLOSE,
        ),
        **changes,
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"currency": CurrencyCode("USD")}, app.SourceFallbackReason.INCOMPATIBLE_CURRENCY),
        ({"instrument_id": UUID(int=44)}, app.SourceFallbackReason.INCOMPATIBLE_SUBJECT),
        ({"calendar_version": "v2"}, app.SourceFallbackReason.INCOMPATIBLE_CALENDAR),
        (
            {"period": SourcePeriod(start=date(2026, 9, 2), end=date(2026, 9, 14))},
            app.SourceFallbackReason.INCOMPATIBLE_PERIOD,
        ),
        ({"synthetic": True}, app.SourceFallbackReason.SYNTHETIC_MISMATCH),
        (
            {"first_known_at": AT + timedelta(seconds=1)},
            app.SourceFallbackReason.SOURCE_AFTER_CUTOFF,
        ),
        ({"available_count": 9}, app.SourceFallbackReason.INSUFFICIENT_COVERAGE),
        ({"quality": QualityState.STALE}, app.SourceFallbackReason.QUALITY_NOT_ACCEPTED),
    ],
)
def test_actual_candidate_meaning_cannot_be_substituted(
    change: dict[str, Any], reason: app.SourceFallbackReason
) -> None:
    assert app.compatibility(plan(), facts(**change)) is reason


def test_coverage_threshold_uses_independent_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        assert (
            app.compatibility(
                plan(minimum_coverage=Decimal("0.999999999999999999")),
                facts(expected_count=100000, available_count=99999),
            )
            is app.SourceFallbackReason.INSUFFICIENT_COVERAGE
        )
        assert (
            app.compatibility(plan(minimum_coverage=Decimal("0.9")), facts(available_count=9))
            is None
        )


class Reader:
    def __init__(self) -> None:
        self.calls: list[UUID] = []
        self.revoke: UUID | None = None

    async def inspect_price(
        self,
        principal: Principal,
        selected: app.PriceFallbackPlan,
        candidate: app.RetainedSourceCandidate,
    ) -> app.FallbackSourceFacts:
        self.calls.append(candidate.snapshot_id)
        if self.revoke == candidate.snapshot_id and self.calls.count(candidate.snapshot_id) > 1:
            raise app.SourceFallbackError(app.SourceFallbackReason.SOURCE_UNAVAILABLE)
        return facts(candidate, available_count=8 if candidate == A else 10)

    async def inspect_fx(self, *args: object) -> app.FallbackSourceFacts:
        raise AssertionError("Cross-family dispatch")


class Acquisition:
    def __init__(self) -> None:
        self.requests: list[app.FallbackAcquisitionPin] = []

    async def acquire_price(
        self, principal: Principal, selected: app.PriceFallbackPlan
    ) -> app.RetainedSourceCandidate:
        assert selected.acquisition is not None
        self.requests.append(selected.acquisition)
        return B

    async def acquire_fx(self, *args: object) -> app.RetainedSourceCandidate:
        raise AssertionError("Cross-family dispatch")


@pytest.mark.asyncio
async def test_disabled_performs_no_source_or_acquisition_work() -> None:
    reader, acquisition = Reader(), Acquisition()
    result = await app.ExplicitSourceFallback(reader, acquisition=acquisition).select_price(
        PRINCIPAL,
        plan(
            acquisition=app.FallbackAcquisitionPin(
                request_id=UUID(int=80), mapping_version_id=UUID(int=81)
            )
        ),
    )
    assert result.selected is None and all(
        x.outcome == "unexamined" and x.reason is app.SourceFallbackReason.DISABLED
        for x in result.comparisons
    )
    assert reader.calls == [] and acquisition.requests == []


@pytest.mark.asyncio
async def test_first_compatible_preserves_rejections_and_unexamined_tail() -> None:
    reader = Reader()
    result = await app.ExplicitSourceFallback(reader).select_price(PRINCIPAL, plan(enabled=True))
    assert result.selected == facts(B)
    assert tuple(x.outcome for x in result.comparisons) == ("rejected", "selected", "unexamined")
    assert result.comparisons[0].source == facts(A, available_count=8)
    assert result.comparisons[0].reason is app.SourceFallbackReason.INSUFFICIENT_COVERAGE
    assert C.snapshot_id not in reader.calls and reader.calls == [
        A.snapshot_id,
        B.snapshot_id,
        A.snapshot_id,
        B.snapshot_id,
    ]


@pytest.mark.asyncio
async def test_final_source_revocation_redacts_the_previously_selected_facts() -> None:
    reader = Reader()
    reader.revoke = B.snapshot_id
    result = await app.ExplicitSourceFallback(reader).select_price(PRINCIPAL, plan(enabled=True))
    assert result.selected is None and result.comparisons[1].source is None
    assert result.comparisons[1].reason is app.SourceFallbackReason.SOURCE_UNAVAILABLE
    assert result.comparisons[2].outcome == "unexamined"


@pytest.mark.asyncio
async def test_optional_acquisition_keeps_original_group_and_is_after_retained_rejection() -> None:
    reader, acquisition = Reader(), Acquisition()
    pin = app.FallbackAcquisitionPin(request_id=UUID(int=80), mapping_version_id=UUID(int=81))
    result = await app.ExplicitSourceFallback(reader, acquisition=acquisition).select_price(
        PRINCIPAL, plan(enabled=True, candidates=(A,), acquisition=pin)
    )
    assert acquisition.requests == [pin] and result.selected == facts(B)
    assert result.comparisons[1].requested_id == pin.request_id


@pytest.mark.asyncio
async def test_foreign_owner_stops_before_candidate_read() -> None:
    reader = Reader()
    with pytest.raises(app.SourceFallbackError) as error:
        await app.ExplicitSourceFallback(reader).select_price(
            PRINCIPAL, plan(enabled=True, owner_id=UUID(int=99))
        )
    assert error.value.reason is app.SourceFallbackReason.ACCESS_DENIED and reader.calls == []
