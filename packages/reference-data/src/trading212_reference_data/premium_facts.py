"""Minimized typed provider facts; original date-only semantics remain explicit."""

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from trading212_domain import CurrencyCode
from trading212_domain.research_sources import ResearchCompanyOverviewFacts, ResearchNewsFacts
from trading212_domain.serialization import canonical_json, to_primitive
from trading212_domain.sources import SourceLicense, SourcePeriod

from .premium_acquisition_types import (
    AcquisitionCapability,
    AcquisitionCommand,
    AcquisitionFailureCode,
    AcquisitionRejected,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class DailyAdjustedRow:
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    volume: int
    dividend: Decimal
    split_coefficient: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class DailyAdjustedFacts:
    symbol: str
    price_currency: CurrencyCode
    period: SourcePeriod
    rows: tuple[DailyAdjustedRow, ...]
    provider_rows_validated: int
    timing: Literal["date_only_requires_trusted_calendar"] = "date_only_requires_trusted_calendar"
    adjusted_basis: Literal["provider_split_dividend_adjusted_close"] = (
        "provider_split_dividend_adjusted_close"
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class EtfHoldingFact:
    symbol: str
    description: str
    weight: Decimal
    # The selected endpoint has no per-holding economic currency/identity contract.
    currency: None = None
    canonical_instrument_id: None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class EtfSectorFact:
    sector: str
    weight: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class EtfProfileFacts:
    symbol: str
    net_assets: Decimal
    expense_ratio: Decimal
    portfolio_turnover: Decimal | None
    dividend_yield: Decimal | None
    holdings: tuple[EtfHoldingFact, ...]
    sectors: tuple[EtfSectorFact, ...]
    stated_holdings_weight: Decimal
    unreported_weight: Decimal
    observed_at: datetime
    historical_effective_at: None = None
    metrics_currency: None = None
    cash_weight: None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanyOverviewFacts:
    symbol: str
    currency: CurrencyCode
    source: ResearchCompanyOverviewFacts
    sector_label: str | None
    industry_label: str | None
    country_label: str | None
    observed_at: datetime
    historical_effective_at: None = None
    economic_currency: None = None
    classification_confidence: None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NewsItemFact:
    source_key: str
    facts: ResearchNewsFacts


@dataclass(frozen=True, slots=True, kw_only=True)
class NewsSentimentFacts:
    symbol: str
    time_from: datetime
    time_to: datetime
    requested_limit: int
    items: tuple[NewsItemFact, ...]
    limit_reached: bool
    historical_completeness: Literal["not_asserted"] = "not_asserted"


@dataclass(frozen=True, slots=True, kw_only=True)
class EcbReferenceRow:
    session_date: date
    quote: CurrencyCode
    rate: Decimal
    source_key: str
    base: CurrencyCode = field(default_factory=lambda: CurrencyCode("EUR"))


@dataclass(frozen=True, slots=True, kw_only=True)
class EcbReferenceFacts:
    rows: tuple[EcbReferenceRow, ...]
    first_date: date
    last_date: date
    date_count: int
    timing: Literal["date_only_first_known_at_retrieval"] = "date_only_first_known_at_retrieval"
    series_kind: Literal["reference_rate"] = "reference_rate"


type PremiumFacts = (
    DailyAdjustedFacts
    | EtfProfileFacts
    | CompanyOverviewFacts
    | NewsSentimentFacts
    | EcbReferenceFacts
)


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionProvenance:
    owner_id: UUID
    account_id: UUID
    instrument_id: UUID | None
    canonical_market_mapping_id: UUID | None
    entity_id: UUID | None
    provider_id: UUID
    capability: AcquisitionCapability
    mapping_version_id: UUID
    mapping_digest: str
    policy_version_id: UUID
    policy_digest: str
    grant_id: UUID
    grant_digest: str
    license: SourceLicense
    request_id: UUID
    request_digest: str
    attempt_id: UUID
    adapter_version: str
    observed_at: datetime
    first_known_at: datetime
    expires_at: datetime
    content_digest: str
    synthetic: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquiredSourceBatch:
    command: AcquisitionCommand
    provenance: AcquisitionProvenance
    facts: PremiumFacts


def premium_facts_digest(facts: PremiumFacts) -> str:
    if type(facts) not in {
        DailyAdjustedFacts,
        EtfProfileFacts,
        CompanyOverviewFacts,
        NewsSentimentFacts,
        EcbReferenceFacts,
    }:
        raise AcquisitionRejected()
    encoded = canonical_json(to_primitive(facts)).encode()
    if len(encoded) > 8 * 1024 * 1024:
        raise AcquisitionRejected(AcquisitionFailureCode.PAYLOAD_TOO_LARGE)
    return hashlib.sha256(b"premium-normalized-facts-v1\0" + encoded).hexdigest()
