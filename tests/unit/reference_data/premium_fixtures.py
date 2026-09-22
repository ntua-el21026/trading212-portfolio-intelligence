"""Synthetic documented-shape fixtures; no provider calls or production grants."""

import json
from datetime import UTC, date, datetime, timedelta
from typing import TypedDict
from uuid import UUID

from trading212_domain import CurrencyCode
from trading212_domain.sources import LicensePermission, SourceLicense, SourcePeriod
from trading212_reference_data.premium_acquisition_types import (
    AcquireCompanyOverview,
    AcquireDailyAdjusted,
    AcquireEcbReferenceFx,
    AcquireEtfProfile,
    AcquireNewsSentiment,
    AcquisitionCapability,
    AcquisitionCommand,
    AcquisitionPermit,
    capability,
)

AT = datetime(2026, 9, 15, 20, tzinfo=UTC)
OWNER, ACCOUNT, REQUEST, MAPPING, PROVIDER, POLICY, GRANT, LICENSE, ENTITY, INSTRUMENT = tuple(
    UUID(int=index) for index in range(1, 11)
)
MARKET_MAPPING = UUID(int=11)
SECRET = "private-test-canary-not-a-real-key"


class _Ids(TypedDict):
    owner_id: UUID
    account_id: UUID
    request_id: UUID
    mapping_version_id: UUID


def command(
    kind: AcquisitionCapability = AcquisitionCapability.DAILY_ADJUSTED,
) -> AcquisitionCommand:
    fields: _Ids = dict(
        owner_id=OWNER, account_id=ACCOUNT, request_id=REQUEST, mapping_version_id=MAPPING
    )
    if kind is AcquisitionCapability.DAILY_ADJUSTED:
        return AcquireDailyAdjusted(
            **fields, period=SourcePeriod(start=date(2026, 9, 14), end=date(2026, 9, 15))
        )
    if kind is AcquisitionCapability.ETF_PROFILE:
        return AcquireEtfProfile(**fields)
    if kind is AcquisitionCapability.COMPANY_OVERVIEW:
        return AcquireCompanyOverview(**fields)
    if kind is AcquisitionCapability.NEWS_SENTIMENT:
        return AcquireNewsSentiment(
            **fields, time_from=AT - timedelta(days=1), time_to=AT, limit=100
        )
    return AcquireEcbReferenceFx(**fields)


def permit(value: AcquisitionCommand) -> AcquisitionPermit:
    kind = capability(value)
    return AcquisitionPermit(
        owner_id=OWNER,
        account_id=ACCOUNT,
        mapping_version_id=MAPPING,
        mapping_digest="a" * 64,
        provider_id=PROVIDER,
        capability=kind,
        policy_version_id=POLICY,
        policy_digest="b" * 64,
        grant_id=GRANT,
        grant_digest="c" * 64,
        license=SourceLicense(
            id=str(LICENSE),
            provider_id=str(PROVIDER),
            version="explicit-synthetic-grant",
            effective_at=AT - timedelta(days=10),
            store=LicensePermission.ALLOWED,
            display=LicensePermission.ALLOWED,
            report=LicensePermission.DENIED,
            export=LicensePermission.DENIED,
            retention_days=7,
            attribution="Synthetic provider fixture",
            evidence_key="synthetic-fixture",
        ),
        effective_at=AT - timedelta(days=1),
        expires_at=AT + timedelta(days=5),
        symbol=None if kind is AcquisitionCapability.REFERENCE_FX else "IBM",
        price_currency=CurrencyCode("USD")
        if kind in {AcquisitionCapability.DAILY_ADJUSTED, AcquisitionCapability.COMPANY_OVERVIEW}
        else None,
        instrument_id=INSTRUMENT
        if kind in {AcquisitionCapability.DAILY_ADJUSTED, AcquisitionCapability.COMPANY_OVERVIEW}
        else None,
        canonical_market_mapping_id=MARKET_MAPPING
        if kind is AcquisitionCapability.DAILY_ADJUSTED
        else None,
        entity_id=ENTITY
        if kind in {AcquisitionCapability.COMPANY_OVERVIEW, AcquisitionCapability.NEWS_SENTIMENT}
        else None,
        credential_reference=None
        if kind is AcquisitionCapability.REFERENCE_FX
        else f"reference-data/alpha-vantage/{OWNER}/{PROVIDER}",
    )


def daily() -> dict[str, object]:
    row = {
        "1. open": "101.125",
        "2. high": "106",
        "3. low": "100",
        "4. close": "105.000000000000000001",
        "5. adjusted close": "52.25",
        "6. volume": "123456",
        "7. dividend amount": "0.75",
        "8. split coefficient": "2",
    }
    return {
        "Meta Data": {"2. Symbol": "IBM", "5. Time Zone": "US/Eastern"},
        "Time Series (Daily)": {"2026-09-15": row},
    }


def news() -> dict[str, object]:
    return {
        "items": "1",
        "sentiment_score_definition": "ignored",
        "feed": [
            {
                "title": "Synthetic issuer statement",
                "url": "https://publisher.example/article?id=first&view=full",
                "time_published": "20260915T120000",
                "summary": "Source prose <script>inert</script>",
                "source": "Synthetic publisher",
                "banner_image": "https://ignored.example/banner.png",
                "overall_sentiment_score": 0.5,
                "ticker_sentiment": [{"ticker": "IBM", "relevance_score": "0.9"}],
            }
        ],
    }


def etf() -> dict[str, object]:
    return {
        "net_assets": "100000000",
        "net_expense_ratio": "0.0020",
        "portfolio_turnover": "0.035",
        "dividend_yield": "None",
        "holdings": [
            {"symbol": "AAA", "description": "Synthetic A", "weight": "0.4"},
            {"symbol": "BBB", "description": "Synthetic B", "weight": "0.4"},
        ],
        "sectors": [{"sector": "Technology", "weight": "0.8"}],
    }


def overview() -> dict[str, object]:
    return {
        "Symbol": "IBM",
        "Currency": "USD",
        "Name": "Synthetic issuer",
        "Description": "Source-authored overview.",
        "Sector": "TECHNOLOGY",
        "Industry": "COMPUTER HARDWARE",
        "Country": "USA",
        "MarketCapitalization": "9999999",
    }


def encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n<gesmes:Envelope'
    b' xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xm'
    b'lns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref'
    b'">\n<gesmes:subject>Reference rates</gesmes:subject><ges'
    b"mes:Sender><gesmes:name>European Central Bank</gesmes:n"
    b'ame></gesmes:Sender>\n<Cube><Cube time="2026-09-15"><Cub'
    b'e currency="USD" rate="1.123456789012345678"/><Cube cur'
    b'rency="GBP" rate="0.85"/></Cube>\n<Cube time="2026-09-14'
    b'"><Cube currency="USD" rate="1.1"/></Cube></Cube></gesm'
    b"es:Envelope>"
)
