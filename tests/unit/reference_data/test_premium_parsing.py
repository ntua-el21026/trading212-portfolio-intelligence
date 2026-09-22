import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from trading212_domain.sources import SourcePeriod
from trading212_reference_data.premium_acquisition_types import (
    AcquireDailyAdjusted,
    AcquireNewsSentiment,
    AcquisitionRejected,
)
from trading212_reference_data.premium_acquisition_types import (
    AcquisitionCapability as Kind,
)
from trading212_reference_data.premium_acquisition_types import (
    AcquisitionFailureCode as Code,
)
from trading212_reference_data.premium_parsing import (
    decode_provider_json,
    parse_company_overview,
    parse_daily_adjusted,
    parse_ecb_reference_fx,
    parse_etf_profile,
    parse_news_sentiment,
)

from tests.unit.reference_data.premium_fixtures import (
    AT,
    XML,
    command,
    daily,
    encoded,
    etf,
    news,
    overview,
    permit,
)


def test_daily_preserves_raw_adjusted_action_precision_without_reconstruction() -> None:
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    facts = parse_daily_adjusted(encoded(daily()), request, permit(request), AT)
    (row,) = facts.rows
    assert row.close == Decimal("105.000000000000000001")
    assert row.adjusted_close == Decimal("52.25")
    assert row.dividend == Decimal("0.75") and row.split_coefficient == Decimal("2")
    assert str(facts.price_currency) == "USD" and row.volume == 123456
    assert facts.timing == "date_only_requires_trusted_calendar"


def test_wrong_subject_and_out_of_period_malformed_row_reject() -> None:
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    raw = daily()
    raw["Meta Data"] = {"2. Symbol": "OTHER"}
    with pytest.raises(AcquisitionRejected):
        parse_daily_adjusted(encoded(raw), request, permit(request), AT)
    # A declared period selects output; it does not excuse bad provider rows elsewhere.
    request = replace(request, period=SourcePeriod(start=date(2026, 9, 14), end=date(2026, 9, 14)))
    raw = daily()
    raw["Time Series (Daily)"] = {"2026-09-15": {"4. close": "1"}}
    with pytest.raises(AcquisitionRejected):
        parse_daily_adjusted(encoded(raw), request, permit(request), AT)


@pytest.mark.parametrize(
    "body",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b"[]",
        b'{"x":' + b"[" * 18 + b"0" + b"]" * 18 + b"}",
    ],
)
def test_bounded_duplicate_and_nonfinite_json_rejects(body: bytes) -> None:
    with pytest.raises(AcquisitionRejected):
        decode_provider_json(body)


@pytest.mark.parametrize(
    "value", [1.5, 10, "1e5", "NaN", "-1", "1.0000000000000000001", "100000000000000000000"]
)
def test_financial_number_and_precision_negative_oracles(value: object) -> None:
    raw = json.loads(encoded(daily()))
    raw["Time Series (Daily)"]["2026-09-15"]["4. close"] = value
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    with pytest.raises(AcquisitionRejected):
        parse_daily_adjusted(encoded(raw), request, permit(request), AT)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"Note": "API call frequency exceeded"}, Code.RATE_LIMITED),
        (
            {"Information": "This premium endpoint requires a subscription"},
            Code.AUTHENTICATION_FAILED,
        ),
        ({"Error Message": "Invalid request"}, Code.PERMANENT_FAILURE),
    ],
)
def test_error_envelopes_never_become_empty_success(payload: object, code: Code) -> None:
    with pytest.raises(AcquisitionRejected) as failure:
        decode_provider_json(encoded(payload))
    assert failure.value.code is code


def test_etf_observed_holdings_unknown_currency_and_unreported_weight_are_explicit() -> None:
    request = command(Kind.ETF_PROFILE)
    facts = parse_etf_profile(encoded(etf()), permit(request), AT)
    assert facts.stated_holdings_weight == Decimal("0.8") and facts.unreported_weight == Decimal(
        "0.2"
    )
    assert facts.historical_effective_at is None and facts.observed_at == AT
    assert (
        facts.cash_weight is None
        and facts.metrics_currency is None
        and facts.dividend_yield is None
    )
    assert all(
        row.currency is None and row.canonical_instrument_id is None for row in facts.holdings
    )
    raw = etf()
    raw["holdings"] = [
        {"symbol": "AAA", "description": "A", "weight": "0.9"},
        {"symbol": "BBB", "description": "B", "weight": "0.2"},
    ]
    with pytest.raises(AcquisitionRejected):
        parse_etf_profile(encoded(raw), permit(request), AT)


def test_overview_never_invents_publication_economic_currency_or_confidence() -> None:
    request = command(Kind.COMPANY_OVERVIEW)
    facts = parse_company_overview(encoded(overview()), permit(request), AT)
    assert (
        facts.source.published_at is None
        and facts.economic_currency is None
        and facts.classification_confidence is None
    )
    assert facts.country_label == "USA" and str(facts.currency) == "USD"
    raw = overview()
    raw["Currency"] = "EUR"
    with pytest.raises(AcquisitionRejected):
        parse_company_overview(encoded(raw), permit(request), AT)


def test_news_numeric_sentiment_is_discarded_but_exact_identity_survives_correction() -> None:
    request = command(Kind.NEWS_SENTIMENT)
    assert isinstance(request, AcquireNewsSentiment)
    first = parse_news_sentiment(encoded(news()), request, permit(request), AT)
    raw = news()
    feed = raw["feed"]
    assert isinstance(feed, list)
    feed[0]["summary"] = "Corrected source statement"
    changed = parse_news_sentiment(encoded(raw), request, permit(request), AT)
    assert first.items[0].source_key == changed.items[0].source_key
    assert first.items[0].facts != changed.items[0].facts
    assert (
        "http" not in repr(first)
        and "sentiment_score" not in repr(first)
        and "banner" not in repr(first)
    )
    raw["feed"] = []
    empty = parse_news_sentiment(encoded(raw), request, permit(request), AT)
    assert empty.items == () and empty.historical_completeness == "not_asserted"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "//publisher.example/a",
        "https://user:secret@publisher.example/a",
        "https://publisher.example/a\nnext",
        "https://publisher.example:99999/a",
    ],
)
def test_news_urls_are_only_validated_opaque_identity_never_network_targets(url: str) -> None:
    request = command(Kind.NEWS_SENTIMENT)
    assert isinstance(request, AcquireNewsSentiment)
    raw = news()
    feed = raw["feed"]
    assert isinstance(feed, list)
    feed[0]["url"] = url
    with pytest.raises(AcquisitionRejected):
        parse_news_sentiment(encoded(raw), request, permit(request), AT)


def test_news_wrong_ticker_future_publication_and_excess_items_reject() -> None:
    request = command(Kind.NEWS_SENTIMENT)
    assert isinstance(request, AcquireNewsSentiment)
    for name, value in (
        ("ticker_sentiment", [{"ticker": "OTHER"}]),
        ("time_published", "20260916T120000"),
    ):
        raw = news()
        feed = raw["feed"]
        assert isinstance(feed, list)
        feed[0][name] = value
        with pytest.raises(AcquisitionRejected):
            parse_news_sentiment(encoded(raw), request, permit(request), AT)
    raw = news()
    feed = raw["feed"]
    assert isinstance(feed, list)
    raw["feed"] = feed * 101
    with pytest.raises(AcquisitionRejected) as failure:
        parse_news_sentiment(encoded(raw), request, permit(request), AT)
    assert failure.value.code is Code.PAYLOAD_TOO_LARGE


def test_ecb_original_legs_and_dates_keep_exact_rates_without_weekend_fill() -> None:
    facts = parse_ecb_reference_fx(XML, AT)
    assert facts.date_count == 2 and len(facts.rows) == 3
    assert all(str(row.base) == "EUR" for row in facts.rows)
    assert next(
        row.rate
        for row in facts.rows
        if str(row.quote) == "USD" and row.session_date == date(2026, 9, 15)
    ) == Decimal("1.123456789012345678")
    assert facts.timing == "date_only_first_known_at_retrieval"


@pytest.mark.parametrize(
    "body",
    [
        XML.replace(b'<Cube currency="GBP"', b'<Cube currency="USD"'),
        XML.replace(b"2026-09-14", b"2026-09-15"),
        XML.replace(b'rate="0.85"', b'rate="0"'),
        XML.replace(b"http://www.ecb.int/", b"http://untrusted.example/"),
        b'<!DOCTYPE x [<!ENTITY xx SYSTEM "file:///etc/passwd">]>' + XML,
        XML.replace(b"Reference rates", b"&xx;"),
        XML.replace(b"2026-09-15", b"2026-09-16"),
        XML.decode().encode("utf-16"),
    ],
)
def test_ecb_closed_xml_and_external_entity_negative_oracles(body: bytes) -> None:
    with pytest.raises(AcquisitionRejected):
        parse_ecb_reference_fx(body, AT)
