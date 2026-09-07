"""Typed corporate actions, enrichment and constituent provider records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from .errors import fail_validation
from .sources import (
    ObservationState,
    SourceCoverage,
    SourcePeriod,
    SourceProvenance,
    SourceSeries,
    SourceSeriesKind,
    _date,
    _series_snapshot,
    _snapshot,
    _typed,
    source_id,
    source_key,
)
from .values import CurrencyCode, exact_decimal, require_utc


class CorporateActionKind(StrEnum):
    SPLIT = "split"
    CASH_DISTRIBUTION = "cash_distribution"
    MERGER = "merger"
    SPINOFF = "spinoff"


@dataclass(frozen=True, slots=True, kw_only=True)
class CorporateActionObservation:
    source_key: str
    session_date: date
    effective_at: datetime
    kind: CorporateActionKind
    state: ObservationState
    ratio: Decimal | None = None
    amount: Decimal | None = None
    currency: CurrencyCode | None = None
    target_instrument_id: str | None = None
    correction_source_key: str | None = None
    source_revision: str | None = None

    def __post_init__(self) -> None:
        source_key(self.source_key)
        _date(self.session_date, "session_date")
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        _typed(self.kind, CorporateActionKind, "kind")
        _typed(self.state, ObservationState, "state")
        if self.source_revision is not None:
            source_key(self.source_revision, "source_revision")
        if self.correction_source_key is not None:
            source_key(self.correction_source_key, "correction_source_key")
            if self.correction_source_key == self.source_key:
                fail_validation("An action cannot correct itself.", field="correction_source_key")
        if self.target_instrument_id is not None:
            source_id(self.target_instrument_id, "target_instrument_id")
        for field in ("ratio", "amount"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, exact_decimal(value, field=field))
        if self.currency is not None:
            _typed(self.currency, CurrencyCode, "currency")
        if self.state is not ObservationState.AVAILABLE:
            if any(
                x is not None
                for x in (self.ratio, self.amount, self.currency, self.target_instrument_id)
            ):
                fail_validation("Unsupported action fields cannot be fabricated.", field="state")
        elif self.kind is CorporateActionKind.CASH_DISTRIBUTION:
            if (
                self.amount is None
                or self.amount < 0
                or self.currency is None
                or self.ratio is not None
                or self.target_instrument_id is not None
            ):
                fail_validation(
                    "A cash distribution requires only exact amount and currency.", field="amount"
                )
        elif (
            self.ratio is None
            or self.ratio <= 0
            or self.amount is not None
            or self.currency is not None
        ):
            fail_validation(
                "An available security action requires a positive ratio.", field="ratio"
            )
        elif (self.target_instrument_id is not None) != (
            self.kind in {CorporateActionKind.MERGER, CorporateActionKind.SPINOFF}
        ):
            fail_validation(
                "A security action has incompatible target identity.", field="target_instrument_id"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class CorporateActionSnapshot:
    id: str
    owner_id: str
    series: SourceSeries
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    observations: tuple[CorporateActionObservation, ...]

    def __post_init__(self) -> None:
        _snapshot(self, CorporateActionObservation)
        _series_snapshot(self, SourceSeriesKind.SECURITY_PRICE)


class SourceIdentifierKind(StrEnum):
    ISIN = "isin"
    PROVIDER_KEY = "provider_key"
    MIC_TICKER = "mic_ticker"


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceIdentifier:
    kind: SourceIdentifierKind
    value: str
    mic: str | None = None

    def __post_init__(self) -> None:
        _typed(self.kind, SourceIdentifierKind, "identifier.kind")
        source_key(self.value, "identifier.value")
        if self.kind is SourceIdentifierKind.ISIN and not re.fullmatch(
            r"[A-Z]{2}[A-Z0-9]{9}[0-9]", self.value
        ):
            fail_validation("A typed ISIN is required.", field="identifier")
        if self.kind is SourceIdentifierKind.MIC_TICKER:
            if not isinstance(self.mic, str) or not re.fullmatch(r"[A-Z0-9]{4}", self.mic):
                fail_validation("A MIC and ticker are required together.", field="identifier")
        elif self.mic is not None:
            fail_validation("This identifier kind does not take a MIC.", field="identifier")


class SourceMappingState(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


def _evidence(value: InstrumentCandidate | ClassificationObservation) -> None:
    source_key(value.evidence_key, "evidence_key")
    object.__setattr__(value, "valid_from", require_utc(value.valid_from, field="valid_from"))
    if value.valid_to is not None:
        object.__setattr__(value, "valid_to", require_utc(value.valid_to, field="valid_to"))
    if value.valid_to is not None and value.valid_to <= value.valid_from:
        fail_validation("Evidence validity must be a nonempty interval.", field="valid_to")
    confidence = exact_decimal(value.confidence, field="confidence")
    if not 0 <= confidence <= 1:
        fail_validation("Confidence must be a fraction.", field="confidence")
    object.__setattr__(value, "confidence", confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentCandidate:
    instrument_id: str
    listing_id: str | None
    evidence_key: str
    valid_from: datetime
    valid_to: datetime | None
    confidence: Decimal

    def __post_init__(self) -> None:
        source_id(self.instrument_id, "instrument_id")
        if self.listing_id is not None:
            source_id(self.listing_id, "listing_id")
        _evidence(self)


class ClassificationDimension(StrEnum):
    SECTOR = "sector"
    INDUSTRY = "industry"
    COUNTRY = "country"
    REGION = "region"
    ECONOMIC_CURRENCY = "economic_currency"


@dataclass(frozen=True, slots=True, kw_only=True)
class ClassificationObservation:
    instrument_id: str
    dimension: ClassificationDimension
    taxonomy: str
    taxonomy_version: str
    category: str
    evidence_key: str
    valid_from: datetime
    valid_to: datetime | None
    confidence: Decimal

    def __post_init__(self) -> None:
        source_id(self.instrument_id, "instrument_id")
        _typed(self.dimension, ClassificationDimension, "dimension")
        for field in ("taxonomy", "taxonomy_version", "category"):
            source_key(getattr(self, field), field)
        _evidence(self)


class ConstituentState(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CASH = "cash"


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstituentHolding:
    source_key: str
    weight: Decimal
    state: ConstituentState
    currency: CurrencyCode
    instrument_id: str | None = None
    entity_id: str | None = None
    evidence_key: str | None = None

    def __post_init__(self) -> None:
        source_key(self.source_key)
        _typed(self.state, ConstituentState, "state")
        _typed(self.currency, CurrencyCode, "currency")
        object.__setattr__(self, "weight", exact_decimal(self.weight, field="weight"))
        if not 0 <= self.weight <= 1:
            fail_validation("A constituent weight must be a fraction.", field="weight")
        for field in ("instrument_id", "entity_id"):
            if getattr(self, field) is not None:
                source_id(getattr(self, field), field)
        if self.evidence_key is not None:
            source_key(self.evidence_key, "evidence_key")
        if self.state is ConstituentState.RESOLVED:
            if (self.instrument_id is None and self.entity_id is None) or self.evidence_key is None:
                fail_validation("Resolved constituents require canonical evidence.", field="state")
        elif self.instrument_id is not None or self.entity_id is not None:
            fail_validation(
                "Unknown or cash constituents cannot invent an identity.", field="state"
            )
