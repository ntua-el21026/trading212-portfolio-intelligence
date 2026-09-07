"""Closed reference-source and benchmark contracts without provider transport input."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from .targets import (
    AwareInstant,
    CurrencyString,
    Cursor,
    DecimalString,
    Description,
    Digest,
    Name,
    UUIDString,
    WeightString,
)


def _calendar_date(value: object) -> object:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("A calendar date is required.")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise ValueError("A calendar date is required.") from None
    return value


def _positive(value: str) -> str:
    if Decimal(value) <= 0:
        raise ValueError("An available source value must be positive.")
    return value


def _revision_order(value: str) -> str:
    if int(value) > 2**63 - 1:
        raise ValueError("The source revision order exceeds its retained integer bound.")
    return value


SourceRevisionOrder = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:0|[1-9][0-9]{0,18})$"),
    AfterValidator(_revision_order),
]
CalendarDate = Annotated[date, BeforeValidator(_calendar_date)]
SourceKey = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
]
SourceSearch = Annotated[str, StringConstraints(strict=True, max_length=80, pattern=r"^[^\x00]*$")]
SourcePositiveDecimal = Annotated[DecimalString, AfterValidator(_positive)]
SourcePriceBasis = Literal["raw_close", "split_adjusted", "total_return"]
SourceAvailability = Literal["available", "partial", "unavailable", "failed"]
SourceObservationState = Literal["available", "missing", "unsupported", "disputed"]
SourceLicensePermission = Literal["allowed", "denied", "unknown"]
SourceCapability = Literal[
    "price_history",
    "corporate_actions",
    "fx_rates",
    "benchmark_series",
    "resolve_instrument",
    "classifications",
    "constituents",
]
SourceQuality = Literal["fresh", "stale", "partial", "estimated", "unreconciled", "failed"]
SourceReason = Literal[
    "no_observations",
    "missing_session",
    "outside_calendar",
    "before_first_observation",
    "future_observation",
    "after_cutoff",
    "stale",
    "unsupported",
    "disputed",
    "ambiguous_revision",
    "missing_fx_pair",
    "incompatible_fixing",
    "numeric_unrepresentable",
    "license_denied",
    "expired",
    "not_configured",
    "unresolved",
    "ambiguous",
    "retention_removed",
]


class SourceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def no_unknown_field_reflection(cls, value: object) -> object:
        if isinstance(value, dict) and any(key not in cls.model_fields for key in value):
            raise ValueError("The bounded source object contains unexpected fields.")
        return value


class SourceFreshness(SourceSchema):
    state: Literal["fresh", "stale", "unavailable"]
    policy_version: SourceKey | None
    reference_at: AwareInstant | None
    max_age_seconds: Annotated[StrictInt, Field(ge=0, le=315360000)] | None

    @model_validator(mode="after")
    def explicit_freshness_inputs(self) -> Self:
        if (self.policy_version is None) != (self.max_age_seconds is None):
            raise ValueError("Freshness policy and maximum age must be explicit together.")
        if self.state != "unavailable" and (
            self.policy_version is None or self.reference_at is None
        ):
            raise ValueError("Known freshness requires a versioned policy and source time.")
        return self


class SourcePeriod(SourceSchema):
    start: CalendarDate
    end: CalendarDate

    @model_validator(mode="after")
    def bounded_period(self) -> Self:
        if not 0 <= (self.end - self.start).days <= 3660:
            raise ValueError("The source period exceeds its inclusive date bounds.")
        return self


class SourcePageQuery(SourceSchema):
    cursor: Cursor | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 25


class SourceStatusQuery(SourcePageQuery):
    provider_id: UUIDString | None = None
    source_id: UUIDString | None = None
    currency: CurrencyString | None = None
    basis: SourcePriceBasis | None = None
    search: SourceSearch = ""
    start: CalendarDate | None = None
    end: CalendarDate | None = None
    source_cutoff_at: AwareInstant | None = None
    sort: Literal["source_key_asc"] = "source_key_asc"

    @model_validator(mode="after")
    def paired_period(self) -> Self:
        _period(self.start, self.end)
        return self


class FxSourceStatusQuery(SourcePageQuery):
    provider_id: UUIDString | None = None
    base: CurrencyString | None = None
    quote: CurrencyString | None = None
    start: CalendarDate | None = None
    end: CalendarDate | None = None
    source_cutoff_at: AwareInstant | None = None
    sort: Literal["pair_asc"] = "pair_asc"

    @model_validator(mode="after")
    def paired_filters(self) -> Self:
        _period(self.start, self.end)
        if (self.base is None) != (self.quote is None):
            raise ValueError("Both FX currencies are required together.")
        return self


def _period(start: date | None, end: date | None) -> None:
    if (start is None) != (end is None):
        raise ValueError("Both period dates are required together.")
    if start is not None and end is not None and not 0 <= (end - start).days <= 3660:
        raise ValueError("The source period exceeds its inclusive date bounds.")


class SourceDetailQuery(SourceSchema):
    account_id: UUIDString | None = None


class SourceObservationQuery(SourcePageQuery):
    account_id: UUIDString | None = None


class BenchmarkDefinitionQuery(SourcePageQuery):
    state: Literal["active", "archived", "all"] = "active"
    search: SourceSearch = ""
    sort: Literal["name_asc", "created_desc"] = "name_asc"


class BenchmarkDetailQuery(SourcePageQuery):
    selected_version_id: UUIDString | None = None


class SourcePage[ItemT](SourceSchema):
    items: Annotated[list[ItemT], Field(max_length=100)]
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def consistent_page(self) -> Self:
        if len(self.items) > self.limit or len(self.items) > self.total:
            raise ValueError("The source page violates its bounds.")
        return self


class SourceLicense(SourceSchema):
    id: UUIDString
    provider_id: UUIDString
    version: SourceKey
    effective_at: AwareInstant
    store: SourceLicensePermission
    display: SourceLicensePermission
    report: SourceLicensePermission
    export: SourceLicensePermission
    retention_days: Annotated[StrictInt, Field(ge=1, le=36500)] | None
    attribution: Description
    evidence_key: SourceKey

    @model_validator(mode="after")
    def bounded_retention(self) -> Self:
        if self.store == "allowed" and self.retention_days is None:
            raise ValueError("Permitted storage requires a retention bound.")
        return self


class SourceSeries(SourceSchema):
    id: UUIDString
    provider_id: UUIDString
    license_version_id: UUIDString
    kind: Literal["security_price", "benchmark_level"]
    provider_key: SourceKey
    mapping_version: SourceKey
    basis: SourcePriceBasis
    currency: CurrencyString
    calendar_id: SourceKey
    calendar_version: SourceKey
    mapping_id: UUIDString | None = None
    instrument_id: UUIDString | None = None
    listing_id: UUIDString | None = None

    @model_validator(mode="after")
    def mapping_shape(self) -> Self:
        if self.kind == "security_price" and (
            self.mapping_id is None or self.instrument_id is None
        ):
            raise ValueError("Security sources require retained canonical mapping provenance.")
        if self.kind == "benchmark_level" and any(
            value is not None for value in (self.mapping_id, self.instrument_id, self.listing_id)
        ):
            raise ValueError("Benchmark levels cannot fabricate security mappings.")
        return self


class SourceProvenance(SourceSchema):
    provider_id: UUIDString
    license_version_id: UUIDString
    adapter_version: SourceKey
    schema_version: SourceKey
    source_revision: SourceKey
    revision_order: SourceRevisionOrder | None
    effective_at: AwareInstant
    first_observed_at: AwareInstant
    synthetic: StrictBool


class SourceRetrievalOccurrence(SourceSchema):
    id: UUIDString
    snapshot_id: UUIDString
    retrieved_at: AwareInstant


class SourceGap(SourceSchema):
    session_date: CalendarDate
    reason: SourceReason
    source_key: SourceKey | None = None


class SourceCoverage(SourceSchema):
    expected_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    available_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    gaps: Annotated[list[SourceGap], Field(max_length=100)]
    gap_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    gaps_truncated: StrictBool
    quality: SourceQuality
    reason: SourceReason | None = None

    @model_validator(mode="after")
    def coverage_shape(self) -> Self:
        if (
            self.available_count + self.gap_count > self.expected_count
            or len(self.gaps) != min(self.gap_count, 100)
            or self.gaps_truncated != (self.gap_count > len(self.gaps))
            or (
                self.quality == "fresh"
                and (self.gap_count or self.available_count != self.expected_count)
            )
        ):
            raise ValueError("Source coverage is inconsistent.")
        return self


class ProviderStatus(SourceSchema):
    id: UUIDString
    key: SourceKey
    name: Name
    adapter_version: SourceKey
    configuration_state: Literal["configured", "not_configured", "disabled"]
    availability: SourceAvailability
    synthetic: StrictBool
    license: SourceLicense | None
    capabilities: Annotated[list[SourceCapability], Field(max_length=7)] = Field(
        default_factory=list
    )
    supported_price_bases: Annotated[list[SourcePriceBasis], Field(max_length=3)] = Field(
        default_factory=list
    )
    freshness_policy_version: SourceKey | None = None
    max_age_seconds: Annotated[StrictInt, Field(ge=0, le=315360000)] | None = None
    reason: SourceReason | None = None

    @model_validator(mode="after")
    def explicit_capabilities_and_policy(self) -> Self:
        if (
            len(self.capabilities) != len(set(self.capabilities))
            or len(self.supported_price_bases) != len(set(self.supported_price_bases))
            or (self.freshness_policy_version is None) != (self.max_age_seconds is None)
        ):
            raise ValueError("Provider capabilities and freshness policy are inconsistent.")
        return self


class SourceSnapshotSummary(SourceSchema):
    id: UUIDString
    content_digest: Digest
    period: SourcePeriod
    first_observed_at: AwareInstant
    effective_at: AwareInstant
    latest_retrieval: SourceRetrievalOccurrence | None
    expected_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    available_count: Annotated[StrictInt, Field(ge=0, le=100000)]
    quality: SourceQuality
    freshness: SourceFreshness
    reason: SourceReason | None = None


class SourceSeriesStatus(SourceSchema):
    series: SourceSeries
    latest_snapshot: SourceSnapshotSummary | None
    availability: SourceAvailability
    reason: SourceReason | None = None


class FxPairStatus(SourceSchema):
    provider_id: UUIDString
    license_version_id: UUIDString
    base: CurrencyString
    quote: CurrencyString
    latest_snapshot: SourceSnapshotSummary | None
    availability: SourceAvailability
    reason: SourceReason | None = None


class MarketSourceStatus(SourceSchema):
    account_id: UUIDString
    providers: Annotated[list[ProviderStatus], Field(max_length=100)]
    series: SourcePage[SourceSeriesStatus]


class BenchmarkSourceStatus(SourceSchema):
    account_id: UUIDString
    providers: Annotated[list[ProviderStatus], Field(max_length=100)]
    series: SourcePage[SourceSeriesStatus]


class FxSourceStatus(SourceSchema):
    account_id: UUIDString
    providers: Annotated[list[ProviderStatus], Field(max_length=100)]
    pairs: SourcePage[FxPairStatus]


class PriceSnapshotHeader(SourceSchema):
    id: UUIDString
    series: SourceSeries
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    content_digest: Digest
    license: SourceLicense
    latest_retrieval: SourceRetrievalOccurrence | None
    freshness: SourceFreshness

    @model_validator(mode="after")
    def price_series_kind(self) -> Self:
        if self.series.kind != "security_price":
            raise ValueError("A price snapshot requires a security price series.")
        return self


class FxSnapshotHeader(SourceSchema):
    calendar_id: SourceKey
    calendar_version: SourceKey
    id: UUIDString
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    content_digest: Digest
    license: SourceLicense
    latest_retrieval: SourceRetrievalOccurrence | None
    freshness: SourceFreshness


class BenchmarkSnapshotHeader(SourceSchema):
    id: UUIDString
    kind: Literal["provider_series"] = "provider_series"
    benchmark_version_id: None = None
    series: SourceSeries
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    content_digest: Digest
    license: SourceLicense
    latest_retrieval: SourceRetrievalOccurrence | None
    freshness: SourceFreshness

    @model_validator(mode="after")
    def benchmark_series_kind(self) -> Self:
        if self.series.kind != "benchmark_level":
            raise ValueError("A raw benchmark snapshot requires a benchmark level series.")
        return self


class PriceObservation(SourceSchema):
    session_date: CalendarDate
    effective_at: AwareInstant
    value: SourcePositiveDecimal | None
    state: SourceObservationState = "available"
    corporate_action_revision: SourceKey | None = None

    @model_validator(mode="after")
    def value_state(self) -> Self:
        _observation(self.state, self.value)
        return self


class FxObservation(SourceSchema):
    base: CurrencyString
    quote: CurrencyString
    session_date: CalendarDate
    effective_at: AwareInstant
    rate: SourcePositiveDecimal | None
    batch_key: SourceKey
    state: SourceObservationState = "available"

    @model_validator(mode="after")
    def value_state(self) -> Self:
        _observation(self.state, self.rate)
        if self.base == self.quote:
            raise ValueError("Provider FX requires distinct currencies.")
        return self


class BenchmarkObservation(SourceSchema):
    session_date: CalendarDate
    effective_at: AwareInstant
    level: SourcePositiveDecimal | None
    state: SourceObservationState = "available"

    @model_validator(mode="after")
    def value_state(self) -> Self:
        _observation(self.state, self.level)
        return self


def _observation(state: str, value: str | None) -> None:
    if (state == "available") != (value is not None):
        raise ValueError("Observation state and value must agree.")


class BenchmarkComponent(SourceSchema):
    source_id: UUIDString
    weight: WeightString


class BenchmarkContent(SourceSchema):
    reporting_currency: CurrencyString
    effective_at: AwareInstant
    return_basis: SourcePriceBasis
    calendar_id: SourceKey
    calendar_version: SourceKey
    rebalance_rule: Literal["buy_and_hold", "daily_rebalanced"]
    components: Annotated[list[BenchmarkComponent], Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def distinct_sources(self) -> Self:
        if len({item.source_id for item in self.components}) != len(self.components):
            raise ValueError("Benchmark components must identify distinct source series.")
        return self


class CreateBenchmarkDefinitionRequest(SourceSchema):
    name: Name
    content: BenchmarkContent
    normalize: StrictBool = False


class CreateBenchmarkVersionRequest(SourceSchema):
    content: BenchmarkContent
    normalize: StrictBool = False


class EmptySourceRequest(SourceSchema):
    pass


class BenchmarkDefinitionSummary(SourceSchema):
    id: UUIDString
    name: Name
    reporting_currency: CurrencyString
    revision: Annotated[StrictInt, Field(ge=1)]
    revision_etag: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)]
    state: Literal["active", "archived"]
    created_at: AwareInstant
    updated_at: AwareInstant
    latest_version_id: UUIDString | None
    version_count: Annotated[StrictInt, Field(ge=0)]


class BenchmarkNormalizationAdjustment(SourceSchema):
    source_id: UUIDString
    original_weight: WeightString
    normalized_weight: WeightString


class BenchmarkVersion(SourceSchema):
    id: UUIDString
    definition_id: UUIDString
    version_number: Annotated[StrictInt, Field(ge=1)]
    content: BenchmarkContent
    content_digest: Digest
    published_at: AwareInstant
    normalization_adjustments: Annotated[
        list[BenchmarkNormalizationAdjustment], Field(max_length=256)
    ]


class BenchmarkDefinitionDetail(SourceSchema):
    definition: BenchmarkDefinitionSummary
    versions: SourcePage[BenchmarkVersion]
    selected_version: BenchmarkVersion | None
