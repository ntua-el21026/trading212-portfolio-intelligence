"""Bounded duplicate-aware parsers; provider text never enters financial formulas."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from urllib.parse import urlsplit
from xml.etree import ElementTree

from trading212_domain import CurrencyCode, exact_decimal
from trading212_domain.errors import DomainError
from trading212_domain.research_sources import ResearchCompanyOverviewFacts, ResearchNewsFacts
from trading212_domain.serialization import canonical_json, to_primitive

from .premium_acquisition_types import (
    AcquireDailyAdjusted,
    AcquireNewsSentiment,
    AcquisitionPermit,
    AcquisitionRejected,
)
from .premium_acquisition_types import (
    AcquisitionFailureCode as Code,
)
from .premium_facts import (
    CompanyOverviewFacts,
    DailyAdjustedFacts,
    DailyAdjustedRow,
    EcbReferenceFacts,
    EcbReferenceRow,
    EtfHoldingFact,
    EtfProfileFacts,
    EtfSectorFact,
    NewsItemFact,
    NewsSentimentFacts,
)


@dataclass(frozen=True, slots=True)
class _Number:
    text: str


type _Json = str | _Number | bool | list[_Json] | dict[str, _Json] | None


def _constant(_: str) -> None:
    raise AcquisitionRejected()


def _object(pairs: list[tuple[str, _Json]]) -> dict[str, _Json]:
    result: dict[str, _Json] = {}
    for key, value in pairs:
        if key in result:
            raise AcquisitionRejected()
        result[key] = value
    return result


def decode_provider_json(body: bytes) -> dict[str, _Json]:
    if type(body) is not bytes or len(body) > 8 * 1024 * 1024:
        raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
    value: object = None
    failed = False
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_object,
            parse_float=_Number,
            parse_int=_Number,
            parse_constant=_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        failed = True
    if failed or not isinstance(value, dict):
        raise AcquisitionRejected()
    pending: list[tuple[object, int]] = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 100_000 or depth > 16:
            raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
        if isinstance(item, dict):
            for key, child in item.items():
                if type(key) is not str or len(key) > 120:
                    raise AcquisitionRejected()
                pending.append((child, depth + 1))
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            if len(item) > 4096:
                raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
        elif isinstance(item, _Number):
            if len(item.text) > 80:
                raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
        elif item is not None and type(item) is not bool:
            raise AcquisitionRejected()
    # JSON parsing is fully traversed before selected-field access; unknown numeric
    # sentiment metadata stays a lexical token, never a binary financial number.
    result = _dictionary(value)
    if any(key in result for key in ("Error Message", "Note", "Information")):
        if "Error Message" in result:
            raise AcquisitionRejected(Code.PERMANENT_FAILURE)
        text = str(result.get("Note", result.get("Information", ""))).lower()
        if any(word in text for word in ("rate", "frequency", "call", "limit")):
            raise AcquisitionRejected(Code.RATE_LIMITED)
        if any(word in text for word in ("apikey", "api key", "premium", "subscription")):
            raise AcquisitionRejected(Code.AUTHENTICATION_FAILED)
        raise AcquisitionRejected(Code.PERMANENT_FAILURE)
    return result


def _dictionary(value: object) -> dict[str, _Json]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise AcquisitionRejected()
    # Values originate only in the closed decoder above or its child dictionaries.
    from typing import cast

    return cast(dict[str, _Json], value)


def _list(value: _Json | None, limit: int) -> list[_Json]:
    if not isinstance(value, list):
        raise AcquisitionRejected()
    if len(value) > limit:
        raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
    return value


def _text(value: _Json | None, *, required: bool = True) -> str:
    if type(value) is not str or len(value) > 4096 or (required and not value.strip()):
        raise AcquisitionRejected()
    if any((ord(char) < 32 and char not in "\t\n\r") or 127 <= ord(char) <= 159 for char in value):
        raise AcquisitionRejected()
    return value


def _decimal(value: _Json | None, *, zero: bool = False, fraction: bool = False) -> Decimal:
    # Financial JSON numbers (including integer tokens) are rejected. Values must
    # be the provider's documented decimal strings and fit canonical NUMERIC38,18.
    if type(value) is not str or len(value) > 60:
        raise AcquisitionRejected()
    parsed: Decimal | None = None
    with contextlib.suppress(ValueError, DomainError):
        parsed = exact_decimal(value)
    if parsed is None or parsed < 0 or (not zero and parsed == 0) or (fraction and parsed > 1):
        raise AcquisitionRejected()
    return parsed


def _optional_decimal(value: _Json | None, *, fraction: bool = False) -> Decimal | None:
    if value is None or value in ("None", "N/A", "-"):
        return None
    return _decimal(value, zero=True, fraction=fraction)


def _day(value: str) -> date:
    parsed: date | None = None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        with contextlib.suppress(ValueError):
            parsed = date.fromisoformat(value)
    if parsed is None:
        raise AcquisitionRejected()
    return parsed


def parse_daily_adjusted(
    body: bytes, request: AcquireDailyAdjusted, permit: AcquisitionPermit, observed_at: datetime
) -> DailyAdjustedFacts:
    raw = decode_provider_json(body)
    metadata = _dictionary(raw.get("Meta Data"))
    if metadata.get("2. Symbol") != permit.symbol or permit.price_currency is None:
        raise AcquisitionRejected()
    if any(
        key in raw and raw[key] != str(permit.price_currency) for key in ("Currency", "currency")
    ):
        raise AcquisitionRejected()
    dates = _dictionary(raw.get("Time Series (Daily)"))
    if not dates or len(dates) > 10_000:
        raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE if dates else Code.INVALID_SCHEMA)
    rows = []
    for key, value in dates.items():
        day, fields = _day(key), _dictionary(value)
        if day > observed_at.date():
            raise AcquisitionRejected()
        opening, high, low, close, adjusted = (
            _decimal(fields.get(field))
            for field in (
                "1. open",
                "2. high",
                "3. low",
                "4. close",
                "5. adjusted close",
            )
        )
        volume = _decimal(fields.get("6. volume"), zero=True)
        dividend = _decimal(fields.get("7. dividend amount"), zero=True)
        split = _decimal(fields.get("8. split coefficient"))
        if (
            low > min(opening, close)
            or high < max(opening, close)
            or low > high
            or volume != volume.to_integral_value()
        ):
            raise AcquisitionRejected()
        if request.period.start <= day <= request.period.end:
            rows.append(
                DailyAdjustedRow(
                    session_date=day,
                    open=opening,
                    high=high,
                    low=low,
                    close=close,
                    adjusted_close=adjusted,
                    volume=int(volume),
                    dividend=dividend,
                    split_coefficient=split,
                )
            )
    if len(rows) > 3661:
        raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
    return DailyAdjustedFacts(
        symbol=_text(permit.symbol),
        price_currency=permit.price_currency,
        period=request.period,
        rows=tuple(sorted(rows, key=lambda row: row.session_date)),
        provider_rows_validated=len(dates),
    )


def parse_etf_profile(
    body: bytes, permit: AcquisitionPermit, observed_at: datetime
) -> EtfProfileFacts:
    raw = decode_provider_json(body)
    # Some versions omit a subject echo; the fixed request and trusted mapping
    # remain the provenance. A conflicting supplied echo must never be accepted.
    if any(key in raw and raw[key] != permit.symbol for key in ("symbol", "Symbol")):
        raise AcquisitionRejected()
    holdings = []
    symbols = set()
    for value in _list(raw.get("holdings"), 10_000):
        row = _dictionary(value)
        symbol = _text(row.get("symbol"))
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.:-]{0,39}", symbol) or symbol in symbols:
            raise AcquisitionRejected()
        symbols.add(symbol)
        holdings.append(
            EtfHoldingFact(
                symbol=symbol,
                description=_text(row.get("description"), required=False),
                weight=_decimal(row.get("weight"), zero=True, fraction=True),
            )
        )
    sectors, labels = [], set()
    for value in _list(raw.get("sectors"), 100):
        row = _dictionary(value)
        sector = _text(row.get("sector"))
        if sector in labels:
            raise AcquisitionRejected()
        labels.add(sector)
        sectors.append(
            EtfSectorFact(
                sector=sector, weight=_decimal(row.get("weight"), zero=True, fraction=True)
            )
        )
    with localcontext() as context:
        context.prec = 80
        total = sum((row.weight for row in holdings), Decimal(0))
        sector_total = sum((row.weight for row in sectors), Decimal(0))
        missing = Decimal(1) - total
    if total > 1 or sector_total > 1:
        raise AcquisitionRejected()
    return EtfProfileFacts(
        symbol=_text(permit.symbol),
        net_assets=_decimal(raw.get("net_assets"), zero=True),
        expense_ratio=_decimal(raw.get("net_expense_ratio"), zero=True, fraction=True),
        portfolio_turnover=_optional_decimal(raw.get("portfolio_turnover")),
        dividend_yield=_optional_decimal(raw.get("dividend_yield"), fraction=True),
        holdings=tuple(holdings),
        sectors=tuple(sectors),
        stated_holdings_weight=total,
        unreported_weight=missing,
        observed_at=observed_at,
    )


def parse_company_overview(
    body: bytes, permit: AcquisitionPermit, observed_at: datetime
) -> CompanyOverviewFacts:
    raw = decode_provider_json(body)
    if raw.get("Symbol") != permit.symbol or raw.get("Currency") != str(permit.price_currency):
        raise AcquisitionRejected()
    currency = permit.price_currency
    if currency is None:
        raise AcquisitionRejected()

    def label(name: str) -> str | None:
        value = raw.get(name)
        return None if value is None or value in ("None", "N/A", "-") else _text(value)

    return CompanyOverviewFacts(
        symbol=_text(permit.symbol),
        currency=currency,
        source=ResearchCompanyOverviewFacts(
            publisher="Alpha Vantage",
            company_name=_text(raw.get("Name")),
            description=_text(raw.get("Description"), required=False),
        ),
        sector_label=label("Sector"),
        industry_label=label("Industry"),
        country_label=label("Country"),
        observed_at=observed_at,
    )


def parse_news_sentiment(
    body: bytes, request: AcquireNewsSentiment, permit: AcquisitionPermit, observed_at: datetime
) -> NewsSentimentFacts:
    raw = decode_provider_json(body)
    entries = _list(raw.get("feed"), request.limit)
    rows, keys = [], set()
    for value in entries:
        row = _dictionary(value)
        published = _text(row.get("time_published"))
        instant: datetime | None = None
        if re.fullmatch(r"\d{8}T\d{6}", published):
            with contextlib.suppress(ValueError):
                instant = datetime.strptime(published, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        if instant is None or not request.time_from <= instant <= min(request.time_to, observed_at):
            raise AcquisitionRejected()
        tickers = tuple(
            _text(_dictionary(item).get("ticker"))
            for item in _list(row.get("ticker_sentiment"), 100)
        )
        if len(tickers) != len(set(tickers)) or permit.symbol not in tickers:
            raise AcquisitionRejected()
        facts = ResearchNewsFacts(
            publisher=_text(row.get("source")),
            title=_text(row.get("title")),
            summary=_text(row.get("summary"), required=False),
            published_at=instant,
        )
        # The provider has no stable event UUID. The URL is used only as opaque
        # source identity and immediately discarded; it is never followed, logged
        # or retained. No path/query normalization invents cross-URL equivalence.
        article = _text(row.get("url"))
        parsed_url = None
        try:
            parsed_url = urlsplit(article)
            valid_port = parsed_url.port is None or 1 <= parsed_url.port <= 65535
        except ValueError:
            valid_port = False
        if (
            parsed_url is None
            or parsed_url.scheme not in {"http", "https"}
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or not valid_port
            or any(ord(char) <= 32 or ord(char) == 127 for char in article)
        ):
            raise AcquisitionRejected()
        encoded = canonical_json(to_primitive(facts)).encode()
        if len(encoded) > 16 * 1024:
            raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
        key = hashlib.sha256(
            b"av-news-event-v1\0"
            + canonical_json(("alpha_vantage", facts.publisher, article)).encode()
        ).hexdigest()
        if key in keys:
            raise AcquisitionRejected()
        keys.add(key)
        rows.append(NewsItemFact(source_key=key, facts=facts))
    return NewsSentimentFacts(
        symbol=_text(permit.symbol),
        time_from=request.time_from,
        time_to=request.time_to,
        requested_limit=request.limit,
        items=tuple(
            sorted(rows, key=lambda row: (row.facts.published_at, row.source_key), reverse=True)
        ),
        limit_reached=len(entries) == request.limit,
    )


def parse_ecb_reference_fx(body: bytes, observed_at: datetime) -> EcbReferenceFacts:
    if type(body) is not bytes or len(body) > 1024 * 1024:
        raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
    upper = body.upper()
    if (
        b"\x00" in body
        or b"<!" in body
        or b"&" in body
        or upper.count(b"<?") > (1 if upper.lstrip().startswith(b"<?XML ") else 0)
    ):
        raise AcquisitionRejected()
    root = None
    with contextlib.suppress(ValueError, UnicodeError, ElementTree.ParseError):
        # UTF-8 only,1MiB maximum; the pre-parser rejects all declarations,
        # entities and non-XML processing instructions before parsing.
        root = ElementTree.fromstring(body.decode("utf-8"))  # noqa: S314
    gesmes = "{http://www.gesmes.org/xml/2002-08-01}"
    ecb = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"
    if root is None or root.tag != gesmes + "Envelope" or root.attrib:
        raise AcquisitionRejected()
    children = list(root)
    if [child.tag for child in children] != [gesmes + "subject", gesmes + "Sender", ecb + "Cube"]:
        raise AcquisitionRejected()
    subject, sender, cube = children
    if any(
        (node.tail or "").strip()
        or (node.tag not in {gesmes + "subject", gesmes + "name"} and (node.text or "").strip())
        for node in root.iter()
    ):
        raise AcquisitionRejected()
    if (
        subject.attrib
        or len(subject)
        or len(subject.text or "") > 120
        or sender.attrib
        or len(sender) != 1
        or sender[0].tag != gesmes + "name"
        or sender[0].attrib
        or len(sender[0])
        or cube.attrib
        or subject.text != "Reference rates"
        or sender[0].text != "European Central Bank"
    ):
        raise AcquisitionRejected()
    dates, rows = set(), []
    if not 1 <= len(cube) <= 100:
        raise AcquisitionRejected(Code.PAYLOAD_TOO_LARGE)
    for day_node in cube:
        if (
            day_node.tag != ecb + "Cube"
            or set(day_node.attrib) != {"time"}
            or not 1 <= len(day_node) <= 40
        ):
            raise AcquisitionRejected()
        day = _day(day_node.attrib["time"])
        if day in dates or day > observed_at.date():
            raise AcquisitionRejected()
        dates.add(day)
        currencies = set()
        for rate_node in day_node:
            if (
                rate_node.tag != ecb + "Cube"
                or set(rate_node.attrib) != {"currency", "rate"}
                or len(rate_node)
            ):
                raise AcquisitionRejected()
            code = rate_node.attrib["currency"]
            if not re.fullmatch(r"[A-Z]{3}", code) or code == "EUR" or code in currencies:
                raise AcquisitionRejected()
            currencies.add(code)
            rows.append(
                EcbReferenceRow(
                    session_date=day,
                    quote=CurrencyCode(code),
                    rate=_decimal(rate_node.attrib["rate"]),
                    source_key=f"ecb:{day.isoformat()}:EUR:{code}",
                )
            )
    if max(dates) - min(dates) > timedelta(days=90):
        raise AcquisitionRejected(Code.UNSUPPORTED)
    return EcbReferenceFacts(
        rows=tuple(sorted(rows, key=lambda row: (row.session_date, str(row.quote)))),
        first_date=min(dates),
        last_date=max(dates),
        date_count=len(dates),
    )
