from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from trading212_application.source_providers import FxPair
from trading212_domain import CurrencyCode
from trading212_domain.sources import (
    MarketSession,
    ObservationState,
    PriceBasis,
    SourceCalendar,
    SourcePeriod,
    SourceSeries,
    SourceSeriesKind,
)
from trading212_reference_data.premium_acquisition_types import (
    AcquireDailyAdjusted,
    AcquisitionRejected,
)
from trading212_reference_data.premium_acquisition_types import (
    AcquisitionCapability as Kind,
)
from trading212_reference_data.premium_facts import (
    AcquiredSourceBatch,
    AcquisitionProvenance,
    PremiumFacts,
    premium_facts_digest,
)
from trading212_reference_data.premium_parsing import parse_daily_adjusted, parse_ecb_reference_fx
from trading212_reference_data.premium_projection import (
    build_ecb_fx_pages,
    build_price_history_pages,
)

from tests.unit.reference_data.premium_fixtures import (
    ACCOUNT,
    AT,
    ENTITY,
    GRANT,
    INSTRUMENT,
    LICENSE,
    MAPPING,
    MARKET_MAPPING,
    OWNER,
    POLICY,
    PROVIDER,
    REQUEST,
    XML,
    command,
    daily,
    encoded,
    permit,
)


def batch(facts: PremiumFacts, kind: Kind = Kind.DAILY_ADJUSTED) -> AcquiredSourceBatch:
    request = command(kind)
    allowed = permit(request)
    return AcquiredSourceBatch(
        command=request,
        facts=facts,
        provenance=AcquisitionProvenance(
            owner_id=OWNER,
            account_id=ACCOUNT,
            provider_id=PROVIDER,
            capability=kind,
            instrument_id=allowed.instrument_id,
            entity_id=allowed.entity_id,
            canonical_market_mapping_id=allowed.canonical_market_mapping_id,
            mapping_version_id=MAPPING,
            mapping_digest="a" * 64,
            policy_version_id=POLICY,
            policy_digest="b" * 64,
            grant_id=GRANT,
            grant_digest="c" * 64,
            license=allowed.license,
            request_id=REQUEST,
            request_digest="d" * 64,
            attempt_id=ENTITY,
            adapter_version="premium_fixed_get_v1",
            observed_at=AT,
            first_known_at=AT,
            expires_at=AT + timedelta(days=5),
            content_digest=premium_facts_digest(facts),
        ),
    )


def calendar() -> SourceCalendar:
    return SourceCalendar(
        id="trusted-calendar",
        version="1",
        timezone="UTC",
        period=SourcePeriod(start=date(2026, 9, 14), end=date(2026, 9, 15)),
        sessions=(
            MarketSession(session_date=date(2026, 9, 14), close_at=AT - timedelta(days=1, hours=4)),
            MarketSession(session_date=date(2026, 9, 15), close_at=AT - timedelta(hours=4)),
        ),
    )


def series() -> SourceSeries:
    return SourceSeries(
        id=str(ENTITY),
        owner_id=str(OWNER),
        provider_id=str(PROVIDER),
        license_version_id=str(LICENSE),
        kind=SourceSeriesKind.SECURITY_PRICE,
        provider_key="IBM",
        mapping_version="1",
        basis=PriceBasis.RAW_CLOSE,
        currency=CurrencyCode("USD"),
        calendar_id="trusted-calendar",
        calendar_version="1",
        mapping_id=str(MARKET_MAPPING),
        instrument_id=str(INSTRUMENT),
    )


def test_price_uses_exact_registered_session_ends_and_retains_missing_sessions() -> None:
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    value = batch(parse_daily_adjusted(encoded(daily()), request, permit(request), AT))
    output, pages = build_price_history_pages(value, series(), calendar())
    assert output.source_cutoff_at == AT
    (page,) = pages
    assert (
        page.provenance.first_observed_at == AT
        and page.provenance.effective_at == AT - timedelta(hours=4)
    )
    assert (
        page.observations[0].value is None
        and page.observations[0].state is ObservationState.MISSING
    )
    assert page.observations[1].value == Decimal("105.000000000000000001")
    assert page.observations[1].effective_at == calendar().sessions[1].close_at
    assert page.coverage.expected_count == 2 and page.coverage.available_count == 1
    assert len(page.coverage.gaps) == 1 and page.continuation is None


@pytest.mark.parametrize("basis", [PriceBasis.SPLIT_ADJUSTED, PriceBasis.TOTAL_RETURN])
def test_adjusted_close_cannot_be_mislabeled_as_split_only_or_total_return(
    basis: PriceBasis,
) -> None:
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    value = batch(parse_daily_adjusted(encoded(daily()), request, permit(request), AT))
    with pytest.raises(AcquisitionRejected):
        build_price_history_pages(value, replace(series(), basis=basis), calendar())


def test_foreign_currency_calendar_or_mapping_denies_canonical_projection() -> None:
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    value = batch(parse_daily_adjusted(encoded(daily()), request, permit(request), AT))
    for changed in (
        replace(series(), currency=CurrencyCode("EUR")),
        replace(series(), calendar_version="2"),
        replace(series(), mapping_id=str(ENTITY)),
    ):
        with pytest.raises(AcquisitionRejected):
            build_price_history_pages(value, changed, calendar())


def test_ecb_retains_original_eur_legs_and_missing_quote_without_cross_rate_fabrication() -> None:
    value = batch(parse_ecb_reference_fx(XML, AT), Kind.REFERENCE_FX)
    selected = (
        FxPair(base=CurrencyCode("EUR"), quote=CurrencyCode("USD")),
        FxPair(base=CurrencyCode("EUR"), quote=CurrencyCode("GBP")),
    )
    request, pages = build_ecb_fx_pages(value, calendar(), selected, calendar().period)
    assert request.pairs == selected and request.source_cutoff_at == AT
    observations = tuple(row for page in pages for row in page.observations)
    assert len(observations) == 4
    assert [row.rate for row in observations] == [
        Decimal("1.1"),
        None,
        Decimal("1.123456789012345678"),
        Decimal("0.85"),
    ]
    assert pages[0].coverage.available_count == 3 and pages[0].coverage.expected_count == 4
    assert all(str(row.base) == "EUR" and row.batch_key.startswith("ecb:") for row in observations)
    with pytest.raises(AcquisitionRejected):
        build_ecb_fx_pages(
            value,
            calendar(),
            (FxPair(base=CurrencyCode("USD"), quote=CurrencyCode("GBP")),),
            calendar().period,
        )


def test_complete_large_selected_history_splits_pages_without_dropping_financial_rows() -> None:
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    first = AT.date() - timedelta(days=1000)
    period = SourcePeriod(start=first, end=AT.date())
    request = replace(request, period=period)
    prototype = daily()["Time Series (Daily)"]
    assert isinstance(prototype, dict)
    raw = {
        "Meta Data": {"2. Symbol": "IBM"},
        "Time Series (Daily)": {
            (first + timedelta(days=index)).isoformat(): prototype["2026-09-15"]
            for index in range(1001)
        },
    }
    facts = parse_daily_adjusted(encoded(raw), request, permit(request), AT)
    value = replace(batch(facts), command=request)
    source_calendar = replace(
        calendar(),
        period=period,
        sessions=tuple(
            MarketSession(
                session_date=first + timedelta(days=index),
                close_at=AT - timedelta(days=1000 - index, hours=4),
            )
            for index in range(1001)
        ),
    )
    _, pages = build_price_history_pages(value, series(), source_calendar)
    assert tuple(len(page.observations) for page in pages) == (1000, 1)
    assert pages[0].continuation is not None and pages[1].continuation is None
    rows = tuple(row for page in pages for row in page.observations)
    assert tuple(row.session_date for row in rows) == tuple(
        first + timedelta(days=index) for index in range(1001)
    )
    assert all(row.value == Decimal("105.000000000000000001") for row in rows)
    assert all(
        page.coverage.expected_count == page.coverage.available_count == 1001 for page in pages
    )
