"""Provider-neutral, bounded reference-data ports; transport stays in adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Protocol

from trading212_domain import CurrencyCode, exact_decimal, require_utc
from trading212_domain.errors import fail_validation
from trading212_domain.source_details import (
    ClassificationObservation,
    ConstituentHolding,
    CorporateActionObservation,
    InstrumentCandidate,
    SourceIdentifier,
    SourceMappingState,
)
from trading212_domain.sources import (
    MAX_SOURCE_PAGE_ROWS,
    BenchmarkObservation,
    FxObservation,
    PriceObservation,
    SourceCoverage,
    SourcePeriod,
    SourceProvenance,
    SourceReason,
    SourceSeries,
    SourceSeriesKind,
    source_id,
    source_integer,
    source_key,
    source_tuple,
)


class SourceCapability(StrEnum):
    PRICE_HISTORY = "price_history"
    CORPORATE_ACTIONS = "corporate_actions"
    FX_RATES = "fx_rates"
    BENCHMARK_SERIES = "benchmark_series"
    RESOLVE_INSTRUMENT = "resolve_instrument"
    CLASSIFICATIONS = "classifications"
    CONSTITUENTS = "constituents"


class SourceProviderError(StrEnum):
    NOT_CONFIGURED = "not_configured"
    UNSUPPORTED = "unsupported"
    NOT_FOUND = "not_found"
    AUTHENTICATION_FAILED = "authentication_failed"
    ACCESS_DENIED = "access_denied"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    TRANSIENT_FAILURE = "transient_failure"
    INVALID_SCHEMA = "invalid_schema"
    PAGINATION_INVALID = "pagination_invalid"
    LICENSE_DENIED = "license_denied"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    PERMANENT_FAILURE = "permanent_failure"


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceFailure:
    code: SourceProviderError
    capability: SourceCapability
    provider_key: str
    retryable: bool = False
    retry_after_seconds: int | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, SourceProviderError) or not isinstance(
            self.capability, SourceCapability
        ):
            fail_validation("A closed provider failure category is required.", field="failure")
        source_key(self.provider_key, "provider_key")
        if type(self.retryable) is not bool:
            fail_validation("Retryability must be explicit.", field="retryable")
        retryable_codes = {
            SourceProviderError.RATE_LIMITED,
            SourceProviderError.TIMEOUT,
            SourceProviderError.TRANSIENT_FAILURE,
        }
        if self.retryable and self.code not in retryable_codes:
            fail_validation("This failure category cannot be retried.", field="retryable")
        if self.retry_after_seconds is not None:
            source_integer(self.retry_after_seconds, "retry_after_seconds", 0, 60)
        if self.correlation_id is not None:
            source_key(self.correlation_id, "correlation_id")


def _continuation(value: str | None) -> None:
    if value is not None and (
        not isinstance(value, str)
        or not 1 <= len(value) <= 1024
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.:"
            for c in value
        )
    ):
        fail_validation("A bounded opaque provider continuation is required.", field="continuation")


def _request(
    value: PriceHistoryRequest | CorporateActionsRequest | FxRatesRequest | BenchmarkSeriesRequest,
) -> None:
    if not isinstance(value.period, SourcePeriod):
        fail_validation("A typed bounded source period is required.", field="period")
    object.__setattr__(value, "source_cutoff_at", require_utc(value.source_cutoff_at))
    _continuation(value.continuation)


def _series_request(
    value: PriceHistoryRequest | CorporateActionsRequest | BenchmarkSeriesRequest,
    kind: SourceSeriesKind,
) -> None:
    _request(value)
    series = value.series
    if not isinstance(series, SourceSeries) or series.kind is not kind:
        fail_validation(
            "The requested immutable source series has an incompatible kind.", field="series"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceHistoryRequest:
    series: SourceSeries
    period: SourcePeriod
    source_cutoff_at: datetime
    continuation: str | None = None

    def __post_init__(self) -> None:
        _series_request(self, SourceSeriesKind.SECURITY_PRICE)


@dataclass(frozen=True, slots=True, kw_only=True)
class CorporateActionsRequest:
    series: SourceSeries
    period: SourcePeriod
    source_cutoff_at: datetime
    continuation: str | None = None

    def __post_init__(self) -> None:
        _series_request(self, SourceSeriesKind.SECURITY_PRICE)


@dataclass(frozen=True, slots=True, kw_only=True)
class FxPair:
    base: CurrencyCode
    quote: CurrencyCode

    def __post_init__(self) -> None:
        if (
            not isinstance(self.base, CurrencyCode)
            or not isinstance(self.quote, CurrencyCode)
            or self.base == self.quote
        ):
            fail_validation("An FX pair requires distinct typed currencies.", field="pair")


@dataclass(frozen=True, slots=True, kw_only=True)
class FxRatesRequest:
    provider_id: str
    license_version_id: str
    calendar_id: str
    calendar_version: str
    pairs: tuple[FxPair, ...]
    period: SourcePeriod
    source_cutoff_at: datetime
    continuation: str | None = None

    def __post_init__(self) -> None:
        _request(self)
        source_id(self.provider_id, "provider_id")
        source_id(self.license_version_id, "license_version_id")
        source_key(self.calendar_id, "calendar_id")
        source_key(self.calendar_version, "calendar_version")
        source_tuple(self.pairs, FxPair, "pairs", 32)
        if not self.pairs or len(set(self.pairs)) != len(self.pairs):
            fail_validation("The FX request requires 1..32 unique pairs.", field="pairs")


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkSeriesRequest:
    series: SourceSeries
    period: SourcePeriod
    source_cutoff_at: datetime
    continuation: str | None = None

    def __post_init__(self) -> None:
        _series_request(self, SourceSeriesKind.BENCHMARK_LEVEL)


def _page(
    value: PriceHistoryPage
    | CorporateActionPage
    | FxRatePage
    | BenchmarkSeriesPage
    | ClassificationPage,
    observation_type: type[object],
) -> None:
    if not isinstance(value.provenance, SourceProvenance):
        fail_validation("A minimized canonical provenance record is required.", field="provenance")
    source_tuple(value.observations, observation_type, "observations", MAX_SOURCE_PAGE_ROWS)
    _continuation(value.continuation)
    if hasattr(value, "period") and not isinstance(value.period, SourcePeriod):
        fail_validation("A bounded source period is required.", field="period")
    if hasattr(value, "coverage") and not isinstance(value.coverage, SourceCoverage):
        fail_validation("Whole-request source coverage is required.", field="coverage")
    if isinstance(value, (PriceHistoryPage, CorporateActionPage, BenchmarkSeriesPage)):
        kind = (
            SourceSeriesKind.BENCHMARK_LEVEL
            if isinstance(value, BenchmarkSeriesPage)
            else SourceSeriesKind.SECURITY_PRICE
        )
        if (
            not isinstance(value.series, SourceSeries)
            or value.series.kind is not kind
            or value.series.provider_id != value.provenance.provider_id
            or value.series.license_version_id != value.provenance.license_version_id
        ):
            fail_validation("Provider page and immutable series scope must agree.", field="series")
    if not isinstance(value, ClassificationPage):
        for observation in value.observations:
            if not value.period.start <= observation.session_date <= value.period.end:
                fail_validation(
                    "A page observation falls outside its requested period.", field="observations"
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceHistoryPage:
    series: SourceSeries
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    observations: tuple[PriceObservation, ...]
    continuation: str | None = None

    def __post_init__(self) -> None:
        _page(self, PriceObservation)


@dataclass(frozen=True, slots=True, kw_only=True)
class CorporateActionPage:
    series: SourceSeries
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    observations: tuple[CorporateActionObservation, ...]
    continuation: str | None = None

    def __post_init__(self) -> None:
        _page(self, CorporateActionObservation)


@dataclass(frozen=True, slots=True, kw_only=True)
class FxRatePage:
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    observations: tuple[FxObservation, ...]
    continuation: str | None = None

    def __post_init__(self) -> None:
        _page(self, FxObservation)


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkSeriesPage:
    series: SourceSeries
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    observations: tuple[BenchmarkObservation, ...]
    continuation: str | None = None

    def __post_init__(self) -> None:
        _page(self, BenchmarkObservation)


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentResolutionRequest:
    identifier: SourceIdentifier
    source_cutoff_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, SourceIdentifier):
            fail_validation("A typed instrument identifier is required.", field="identifier")
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentResolutionResult:
    state: SourceMappingState
    candidates: tuple[InstrumentCandidate, ...]
    reason: SourceReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, SourceMappingState):
            fail_validation("A typed mapping state is required.", field="state")
        source_tuple(self.candidates, InstrumentCandidate, "candidates", 20)
        if (
            (self.state is SourceMappingState.RESOLVED and len(self.candidates) != 1)
            or (self.state is SourceMappingState.UNRESOLVED and self.candidates)
            or (self.state is SourceMappingState.AMBIGUOUS and len(self.candidates) < 2)
        ):
            fail_validation("Mapping state and candidate count disagree.", field="candidates")
        if self.reason is not None and not isinstance(self.reason, SourceReason):
            fail_validation("A typed resolution reason is required.", field="reason")


@dataclass(frozen=True, slots=True, kw_only=True)
class ClassificationRequest:
    instrument_ids: tuple[str, ...]
    taxonomy: str
    taxonomy_version: str
    source_cutoff_at: datetime
    continuation: str | None = None

    def __post_init__(self) -> None:
        source_tuple(self.instrument_ids, str, "instrument_ids", 100)
        if not self.instrument_ids or len(set(self.instrument_ids)) != len(self.instrument_ids):
            fail_validation(
                "Classification requests need 1..100 unique identities.", field="instrument_ids"
            )
        for item in self.instrument_ids:
            source_id(item, "instrument_ids")
        source_key(self.taxonomy, "taxonomy")
        source_key(self.taxonomy_version, "taxonomy_version")
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
        _continuation(self.continuation)


@dataclass(frozen=True, slots=True, kw_only=True)
class ClassificationPage:
    request: ClassificationRequest
    provenance: SourceProvenance
    observations: tuple[ClassificationObservation, ...]
    continuation: str | None = None

    def __post_init__(self) -> None:
        _page(self, ClassificationObservation)
        if not isinstance(self.request, ClassificationRequest):
            fail_validation("The complete classification request is required.", field="request")
        subjects = set(self.request.instrument_ids)
        if any(
            row.instrument_id not in subjects
            or row.taxonomy != self.request.taxonomy
            or row.taxonomy_version != self.request.taxonomy_version
            for row in self.observations
        ):
            fail_validation(
                "Classification subjects and taxonomy must match the request.", field="observations"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstituentRequest:
    fund_series_id: str
    effective_at: datetime
    source_cutoff_at: datetime
    continuation: str | None = None

    def __post_init__(self) -> None:
        source_id(self.fund_series_id, "fund_series_id")
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))
        if self.effective_at > self.source_cutoff_at:
            fail_validation(
                "Constituents cannot use a post-cutoff effective date.", field="effective_at"
            )
        _continuation(self.continuation)


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstituentPage:
    request: ConstituentRequest
    provenance: SourceProvenance
    effective_at: datetime
    holdings: tuple[ConstituentHolding, ...]
    stated_coverage: Decimal
    unresolved_weight: Decimal
    cash_weight: Decimal
    continuation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, SourceProvenance):
            fail_validation("Canonical provenance is required.", field="provenance")
        if not isinstance(self.request, ConstituentRequest):
            fail_validation("The complete constituent request is required.", field="request")
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        if self.effective_at > self.request.effective_at:
            fail_validation(
                "Constituents cannot follow the requested effective date.", field="effective_at"
            )
        source_tuple(self.holdings, ConstituentHolding, "holdings", MAX_SOURCE_PAGE_ROWS)
        for field in ("stated_coverage", "unresolved_weight", "cash_weight"):
            value = exact_decimal(getattr(self, field), field=field)
            if not 0 <= value <= 1:
                fail_validation("Constituent coverage must be a fraction.", field=field)
            object.__setattr__(self, field, value)
        with localcontext() as context:
            context.prec = 80
            if self.stated_coverage + self.unresolved_weight + self.cash_weight > 1:
                fail_validation("Constituent coverage exceeds one.", field="coverage")
        _continuation(self.continuation)


class MarketPriceHistoryProvider(Protocol):
    async def get_price_history(
        self, request: PriceHistoryRequest
    ) -> PriceHistoryPage | SourceFailure: ...
    async def get_corporate_actions(
        self, request: CorporateActionsRequest
    ) -> CorporateActionPage | SourceFailure: ...


class FxReferenceProvider(Protocol):
    async def get_rates(self, request: FxRatesRequest) -> FxRatePage | SourceFailure: ...


class BenchmarkProvider(Protocol):
    async def get_series(
        self, request: BenchmarkSeriesRequest
    ) -> BenchmarkSeriesPage | SourceFailure: ...


class ClassificationProvider(Protocol):
    async def get_classifications(
        self, request: ClassificationRequest
    ) -> ClassificationPage | SourceFailure: ...


class InstrumentEnrichmentProvider(ClassificationProvider, Protocol):
    async def resolve_instrument(
        self, request: InstrumentResolutionRequest
    ) -> InstrumentResolutionResult | SourceFailure: ...


class ETFConstituentProvider(Protocol):
    async def get_constituents(
        self, request: ConstituentRequest
    ) -> ConstituentPage | SourceFailure: ...
