from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from trading212_domain import CurrencyCode, QualityState
from trading212_domain.sources import (
    FxObservation,
    FxSnapshot,
    MarketSession,
    PriceBasis,
    PriceObservation,
    PriceSnapshot,
    SourceCalendar,
    SourceCoverage,
    SourcePeriod,
    SourceProvenance,
    SourceSelectionPolicy,
    SourceSeries,
    SourceSeriesKind,
)

AT = datetime(2026, 9, 4, 16, tzinfo=UTC)
EUR = CurrencyCode("EUR")
USD = CurrencyCode("USD")
GBP = CurrencyCode("GBP")


def uid(value: int) -> str:
    return str(UUID(int=value))


def provenance(*, provider: int = 2, revision: int | None = 1) -> SourceProvenance:
    return SourceProvenance(
        provider_id=uid(provider),
        license_version_id=uid(provider + 100),
        adapter_version="1.0.0",
        schema_version="1.0.0",
        source_revision=f"revision-{revision}",
        revision_order=revision,
        effective_at=AT,
        first_observed_at=AT,
        synthetic=True,
    )


def series(*, benchmark: bool = False) -> SourceSeries:
    return SourceSeries(
        id=uid(10 if benchmark else 9),
        owner_id=uid(1),
        provider_id=uid(2),
        license_version_id=uid(102),
        kind=SourceSeriesKind.BENCHMARK_LEVEL if benchmark else SourceSeriesKind.SECURITY_PRICE,
        provider_key="synthetic-index" if benchmark else "synthetic-stock",
        mapping_version="v1",
        basis=PriceBasis.TOTAL_RETURN if benchmark else PriceBasis.RAW_CLOSE,
        currency=EUR,
        calendar_id="synthetic-utc",
        calendar_version="v1",
        mapping_id=None if benchmark else uid(5),
        instrument_id=None if benchmark else uid(6),
        listing_id=None if benchmark else uid(7),
    )


def calendar() -> SourceCalendar:
    return SourceCalendar(
        id="synthetic-utc",
        version="v1",
        timezone="UTC",
        period=SourcePeriod(start=date(2026, 9, 3), end=date(2026, 9, 7)),
        sessions=tuple(
            MarketSession(
                session_date=date(2026, 9, day), close_at=datetime(2026, 9, day, 16, tzinfo=UTC)
            )
            for day in (3, 4, 7)
        ),
    )


def policy() -> SourceSelectionPolicy:
    return SourceSelectionPolicy(
        version="source-v1",
        provider_priority=(uid(2), uid(3)),
        max_age_seconds=3 * 86400,
        allow_closed_session_carry=True,
        pivot_currency=EUR,
    )


def price(value: str = "100", *, snapshot: int = 20, revision: int | None = 1) -> PriceSnapshot:
    return PriceSnapshot(
        id=uid(snapshot),
        owner_id=uid(1),
        series=series(),
        provenance=provenance(revision=revision),
        period=SourcePeriod(start=AT.date(), end=AT.date()),
        coverage=SourceCoverage(
            expected_count=1, available_count=1, gaps=(), quality=QualityState.FRESH
        ),
        observations=(
            PriceObservation(session_date=AT.date(), effective_at=AT, value=Decimal(value)),
        ),
    )


def fx(
    *pairs: tuple[CurrencyCode, CurrencyCode, str],
    snapshot: int = 30,
    provider: int = 2,
    revision: int | None = 1,
) -> FxSnapshot:
    observations = tuple(
        FxObservation(
            base=base,
            quote=quote,
            rate=Decimal(rate),
            session_date=AT.date(),
            effective_at=AT,
            batch_key="fixing-2026-09-04",
        )
        for base, quote, rate in pairs
    )
    return FxSnapshot(
        id=uid(snapshot),
        owner_id=uid(1),
        calendar_id="synthetic-utc",
        calendar_version="v1",
        provenance=provenance(provider=provider, revision=revision),
        period=SourcePeriod(start=AT.date(), end=AT.date()),
        coverage=SourceCoverage(
            expected_count=len(observations),
            available_count=len(observations),
            gaps=(),
            quality=QualityState.FRESH,
        ),
        observations=observations,
    )


def at_observation(snapshot: PriceSnapshot, at: datetime) -> PriceSnapshot:
    return replace(
        snapshot,
        provenance=replace(snapshot.provenance, effective_at=at, first_observed_at=at),
        period=SourcePeriod(start=at.date(), end=at.date()),
        observations=tuple(
            replace(x, session_date=at.date(), effective_at=at) for x in snapshot.observations
        ),
    )
