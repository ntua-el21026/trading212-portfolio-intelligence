"""Authorized public contracts for retained reference sources and benchmark definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from trading212_domain.enums import QualityState
from trading212_domain.historical import HistoricalCoverage
from trading212_domain.historical_results import CompositeBenchmarkPoint
from trading212_domain.sources import (
    BenchmarkContent,
    BenchmarkNormalizationAdjustment,
    BenchmarkObservation,
    FxObservation,
    ObservationState,
    PriceBasis,
    PriceObservation,
    RetrievalOccurrence,
    SourceAvailability,
    SourceCoverage,
    SourceGap,
    SourceLicense,
    SourcePeriod,
    SourceProvenance,
    SourceReason,
    SourceSeriesKind,
)
from trading212_domain.values import CurrencyCode
from trading212_security.principals import Principal

from .historical import CompositeBenchmarkHeaderView, HistoricalAccessView
from .source_providers import SourceCapability
from .targets import TargetPageQuery, target_etag
from .views import Page


class SourceServiceErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    IMMUTABLE_VERSION = "IMMUTABLE_VERSION"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    SOURCE_REVISION_CONFLICT = "SOURCE_REVISION_CONFLICT"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


@dataclass(slots=True)
class SourceServiceError(Exception):
    code: SourceServiceErrorCode
    message: str

    def __str__(self) -> str:
        return self.message


class ProviderConfigurationState(StrEnum):
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"


class SourceFreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceFreshnessView:
    state: SourceFreshnessState = SourceFreshnessState.UNAVAILABLE
    policy_version: str | None = None
    reference_at: datetime | None = None
    max_age_seconds: int | None = None


class BenchmarkDefinitionState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class BenchmarkStateFilter(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    ALL = "all"


class BenchmarkSort(StrEnum):
    NAME_ASC = "name_asc"
    CREATED_DESC = "created_desc"


def _identifier(value: str) -> None:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("A canonical UUID identifier is required.")


def _search(value: str) -> str:
    if not isinstance(value, str) or len(value) > 80 or "\x00" in value:
        raise ValueError("Search must contain at most eighty characters.")
    return value.strip().casefold()


def _cutoff(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("The source cutoff must be an aware UTC instant.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceStatusQuery(TargetPageQuery):
    provider_id: str | None = None
    source_id: str | None = None
    currency: CurrencyCode | None = None
    basis: PriceBasis | None = None
    search: str = ""
    period: SourcePeriod | None = None
    source_cutoff_at: datetime | None = None
    sort: str = "source_key_asc"

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        for value in (self.provider_id, self.source_id):
            if value is not None:
                _identifier(value)
        if self.currency is not None and not isinstance(self.currency, CurrencyCode):
            raise ValueError("A typed currency is required.")
        if self.basis is not None and not isinstance(self.basis, PriceBasis):
            raise ValueError("Invalid source basis.")
        if self.period is not None and not isinstance(self.period, SourcePeriod):
            raise ValueError("A bounded source period is required.")
        if self.sort != "source_key_asc":
            raise ValueError("Unsupported source ordering.")
        object.__setattr__(self, "search", _search(self.search))
        object.__setattr__(self, "source_cutoff_at", _cutoff(self.source_cutoff_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class FxSourceStatusQuery(TargetPageQuery):
    provider_id: str | None = None
    base: CurrencyCode | None = None
    quote: CurrencyCode | None = None
    period: SourcePeriod | None = None
    source_cutoff_at: datetime | None = None
    sort: str = "pair_asc"

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        if self.provider_id is not None:
            _identifier(self.provider_id)
        if (self.base is None) != (self.quote is None):
            raise ValueError("Both FX currencies are required together.")
        for value in (self.base, self.quote):
            if value is not None and not isinstance(value, CurrencyCode):
                raise ValueError("A typed FX currency is required.")
        if self.period is not None and not isinstance(self.period, SourcePeriod):
            raise ValueError("A bounded source period is required.")
        if self.sort != "pair_asc":
            raise ValueError("Unsupported FX source ordering.")
        object.__setattr__(self, "source_cutoff_at", _cutoff(self.source_cutoff_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceObservationQuery(TargetPageQuery):
    account_id: str | None = None

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        if self.account_id is not None:
            _identifier(self.account_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class FxObservationReferenceQuery(TargetPageQuery):
    account_id: str
    base: CurrencyCode
    quote: CurrencyCode
    source_cutoff_at: datetime
    effective_at_lte: datetime | None = None

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        _identifier(self.account_id)
        if (
            self.limit > 25
            or not isinstance(self.base, CurrencyCode)
            or not isinstance(self.quote, CurrencyCode)
            or self.base == self.quote
        ):
            raise ValueError("Choose one distinct FX pair and at most 25 references.")
        cutoff = _cutoff(self.source_cutoff_at)
        effective = _cutoff(self.effective_at_lte) if self.effective_at_lte is not None else cutoff
        if cutoff is None or effective is None or effective > cutoff:
            raise ValueError("The observation effective bound cannot follow the source cutoff.")
        object.__setattr__(self, "source_cutoff_at", cutoff)
        object.__setattr__(self, "effective_at_lte", effective)


@dataclass(frozen=True, slots=True, kw_only=True)
class FxObservationReference:
    observation_id: str
    session_date: date
    effective_at: datetime
    rate: Decimal | None
    state: ObservationState


@dataclass(frozen=True, slots=True, kw_only=True)
class FxObservationReferencePage:
    account_id: str
    snapshot_id: str
    content_digest: str
    base: CurrencyCode
    quote: CurrencyCode
    source_cutoff_at: datetime
    effective_at_lte: datetime
    first_observed_at: datetime
    expires_at: datetime
    items: tuple[FxObservationReference, ...]
    next_cursor: str | None
    limit: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkDefinitionQuery(TargetPageQuery):
    state: BenchmarkStateFilter = BenchmarkStateFilter.ACTIVE
    search: str = ""
    sort: BenchmarkSort = BenchmarkSort.NAME_ASC

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        if not isinstance(self.state, BenchmarkStateFilter) or not isinstance(
            self.sort, BenchmarkSort
        ):
            raise ValueError("Unsupported benchmark filter or ordering.")
        object.__setattr__(self, "search", _search(self.search))


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkDetailQuery(TargetPageQuery):
    selected_version_id: str | None = None

    def __post_init__(self) -> None:
        TargetPageQuery.__post_init__(self)
        if self.selected_version_id is not None:
            _identifier(self.selected_version_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateBenchmarkDefinitionCommand:
    name: str
    content: BenchmarkContent
    normalize: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not 1 <= len(self.name.strip()) <= 120
            or "\x00" in self.name
        ):
            raise ValueError("A bounded benchmark name is required.")
        object.__setattr__(self, "name", self.name.strip())
        _benchmark_command(self.content, self.normalize)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateBenchmarkVersionCommand:
    content: BenchmarkContent
    normalize: bool = False

    def __post_init__(self) -> None:
        _benchmark_command(self.content, self.normalize)


def _benchmark_command(content: BenchmarkContent, normalize: bool) -> None:
    if not isinstance(content, BenchmarkContent) or not isinstance(normalize, bool):
        raise ValueError("Typed benchmark content and an explicit normalization flag are required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceSeriesView:
    id: str
    provider_id: str
    license_version_id: str
    kind: SourceSeriesKind
    provider_key: str
    mapping_version: str
    basis: PriceBasis
    currency: CurrencyCode
    calendar_id: str
    calendar_version: str
    mapping_id: str | None = None
    instrument_id: str | None = None
    listing_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderStatusView:
    id: str
    key: str
    name: str
    adapter_version: str
    configuration_state: ProviderConfigurationState
    availability: SourceAvailability
    synthetic: bool
    license: SourceLicense | None
    capabilities: tuple[SourceCapability, ...] = ()
    supported_price_bases: tuple[PriceBasis, ...] = ()
    freshness_policy_version: str | None = None
    max_age_seconds: int | None = None
    reason: SourceReason | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceSnapshotSummaryView:
    id: str
    content_digest: str
    period: SourcePeriod
    first_observed_at: datetime
    effective_at: datetime
    latest_retrieval: RetrievalOccurrence | None
    expected_count: int
    available_count: int
    quality: QualityState
    freshness: SourceFreshnessView = SourceFreshnessView()
    reason: SourceReason | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceSeriesStatusView:
    series: SourceSeriesView
    latest_snapshot: SourceSnapshotSummaryView | None
    availability: SourceAvailability
    reason: SourceReason | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FxPairStatusView:
    provider_id: str
    license_version_id: str
    base: CurrencyCode
    quote: CurrencyCode
    latest_snapshot: SourceSnapshotSummaryView | None
    availability: SourceAvailability
    reason: SourceReason | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketSourceStatusView:
    account_id: str
    providers: tuple[ProviderStatusView, ...]
    series: Page[SourceSeriesStatusView]


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkSourceStatusView:
    account_id: str
    providers: tuple[ProviderStatusView, ...]
    series: Page[SourceSeriesStatusView]


@dataclass(frozen=True, slots=True, kw_only=True)
class FxSourceStatusView:
    account_id: str
    providers: tuple[ProviderStatusView, ...]
    pairs: Page[FxPairStatusView]


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceCoverageView:
    expected_count: int
    available_count: int
    gaps: tuple[SourceGap, ...]
    gap_count: int
    gaps_truncated: bool
    quality: QualityState
    reason: SourceReason | None = None

    @classmethod
    def from_coverage(cls, value: SourceCoverage) -> SourceCoverageView:
        return cls(
            expected_count=value.expected_count,
            available_count=value.available_count,
            gaps=value.gaps[:100],
            gap_count=len(value.gaps),
            gaps_truncated=len(value.gaps) > 100,
            quality=value.quality,
            reason=value.reason,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceSnapshotHeaderView:
    id: str
    series: SourceSeriesView
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverageView
    content_digest: str
    license: SourceLicense
    latest_retrieval: RetrievalOccurrence | None
    freshness: SourceFreshnessView = SourceFreshnessView()


@dataclass(frozen=True, slots=True, kw_only=True)
class FxSnapshotHeaderView:
    calendar_id: str
    calendar_version: str
    id: str
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverageView
    content_digest: str
    license: SourceLicense
    latest_retrieval: RetrievalOccurrence | None
    freshness: SourceFreshnessView = SourceFreshnessView()


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkSnapshotHeaderView:
    id: str
    series: SourceSeriesView
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverageView
    content_digest: str
    license: SourceLicense
    latest_retrieval: RetrievalOccurrence | None
    freshness: SourceFreshnessView = SourceFreshnessView()
    kind: Literal["provider_series"] = "provider_series"
    benchmark_version_id: None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CompositeBenchmarkSnapshotHeaderView(CompositeBenchmarkHeaderView):
    coverage: HistoricalCoverage
    access: HistoricalAccessView = field(default_factory=HistoricalAccessView)


@dataclass(frozen=True, slots=True, kw_only=True)
class CompositeBenchmarkObservationPageView:
    items: tuple[CompositeBenchmarkPoint, ...]
    next_cursor: str | None
    limit: int
    total: int
    snapshot_id: str
    kind: Literal["composite"] = "composite"


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkDefinitionSummaryView:
    id: str
    name: str
    reporting_currency: CurrencyCode
    revision: int
    state: BenchmarkDefinitionState
    created_at: datetime
    updated_at: datetime
    latest_version_id: str | None
    version_count: int

    @property
    def etag(self) -> str:
        return target_etag(self.id, self.revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkVersionView:
    id: str
    definition_id: str
    version_number: int
    content: BenchmarkContent
    content_digest: str
    published_at: datetime
    normalization_adjustments: tuple[BenchmarkNormalizationAdjustment, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkDefinitionDetailView:
    definition: BenchmarkDefinitionSummaryView
    versions: Page[BenchmarkVersionView]
    selected_version: BenchmarkVersionView | None


class SourceService(Protocol):
    """Every method checks current ownership/scopes and license before disclosing data."""

    async def get_market_source_status(
        self, principal: Principal, account_id: str, *, query: SourceStatusQuery
    ) -> MarketSourceStatusView: ...
    async def get_fx_source_status(
        self, principal: Principal, account_id: str, *, query: FxSourceStatusQuery
    ) -> FxSourceStatusView: ...
    async def get_benchmark_source_status(
        self, principal: Principal, account_id: str, *, query: SourceStatusQuery
    ) -> BenchmarkSourceStatusView: ...
    async def get_price_snapshot(
        self, principal: Principal, snapshot_id: str, *, account_id: str | None = None
    ) -> PriceSnapshotHeaderView: ...
    async def get_fx_snapshot(
        self, principal: Principal, snapshot_id: str, *, account_id: str | None = None
    ) -> FxSnapshotHeaderView: ...
    async def get_benchmark_snapshot(
        self, principal: Principal, snapshot_id: str, *, account_id: str | None = None
    ) -> BenchmarkSnapshotHeaderView | CompositeBenchmarkSnapshotHeaderView: ...
    async def list_price_observations(
        self, principal: Principal, snapshot_id: str, *, query: SourceObservationQuery
    ) -> Page[PriceObservation]: ...
    async def list_fx_observations(
        self, principal: Principal, snapshot_id: str, *, query: SourceObservationQuery
    ) -> Page[FxObservation]: ...
    async def list_fx_observation_references(
        self, principal: Principal, snapshot_id: str, *, query: FxObservationReferenceQuery
    ) -> FxObservationReferencePage: ...
    async def list_benchmark_observations(
        self, principal: Principal, snapshot_id: str, *, query: SourceObservationQuery
    ) -> Page[BenchmarkObservation] | CompositeBenchmarkObservationPageView: ...
    async def list_benchmark_definitions(
        self, principal: Principal, *, query: BenchmarkDefinitionQuery
    ) -> Page[BenchmarkDefinitionSummaryView]: ...
    async def create_benchmark_definition(
        self,
        principal: Principal,
        command: CreateBenchmarkDefinitionCommand,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> BenchmarkDefinitionDetailView: ...
    async def get_benchmark_definition(
        self, principal: Principal, definition_id: str, *, query: BenchmarkDetailQuery
    ) -> BenchmarkDefinitionDetailView: ...
    async def create_benchmark_version(
        self,
        principal: Principal,
        definition_id: str,
        command: CreateBenchmarkVersionCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> BenchmarkDefinitionDetailView: ...
    async def archive_benchmark_definition(
        self,
        principal: Principal,
        definition_id: str,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> BenchmarkDefinitionDetailView: ...
