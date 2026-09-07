"""Typed owner-authorized source registration and ingestion; no transport interface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from trading212_domain.source_details import (
    InstrumentCandidate,
    SourceIdentifier,
    SourceMappingState,
)
from trading212_domain.sources import (
    PriceBasis,
    SourceCalendar,
    SourceLicense,
    SourceSeries,
    source_id,
    source_key,
    source_tuple,
)
from trading212_domain.values import CurrencyCode, require_bounded_text, require_utc
from trading212_security.principals import Principal

from .source_providers import SourceCapability
from .sources import ProviderConfigurationState

if TYPE_CHECKING:
    from trading212_domain.source_details import CorporateActionSnapshot
    from trading212_domain.sources import BenchmarkSnapshot, FxSnapshot, PriceSnapshot

    from .source_providers import (
        BenchmarkSeriesPage,
        BenchmarkSeriesRequest,
        CorporateActionPage,
        CorporateActionsRequest,
        FxRatePage,
        FxRatesRequest,
        PriceHistoryPage,
        PriceHistoryRequest,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceProviderRegistration:
    id: str
    key: str
    name: str
    adapter_version: str
    configuration_state: ProviderConfigurationState
    synthetic: bool
    freshness_policy_version: str | None = None
    max_age_seconds: int | None = None
    capabilities: tuple[SourceCapability, ...] = ()
    supported_price_bases: tuple[PriceBasis, ...] = ()

    def __post_init__(self) -> None:
        if (self.freshness_policy_version is None) != (self.max_age_seconds is None):
            raise ValueError("Freshness policy and bound are required together.")
        if self.freshness_policy_version is not None:
            source_key(self.freshness_policy_version, "freshness_policy_version")
            if type(self.max_age_seconds) is not int or not 0 <= self.max_age_seconds <= 315360000:
                raise ValueError("An exact bounded freshness interval is required.")
        source_tuple(self.capabilities, SourceCapability, "capabilities", 7)
        source_tuple(self.supported_price_bases, PriceBasis, "supported_price_bases", 3)
        if len(set(self.capabilities)) != len(self.capabilities) or len(
            set(self.supported_price_bases)
        ) != len(self.supported_price_bases):
            raise ValueError("Provider capabilities and bases must be unique.")
        source_id(self.id)
        source_key(self.key)
        source_key(self.adapter_version, "adapter_version")
        require_bounded_text(self.name, field="name", maximum=120)
        if (
            not isinstance(self.configuration_state, ProviderConfigurationState)
            or type(self.synthetic) is not bool
        ):
            raise ValueError("Typed provider configuration is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceProvider:
    registration: SourceProviderRegistration
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceInstrumentMapping:
    id: str
    provider_id: str
    provider_key: str
    version: str
    state: SourceMappingState
    identifier: SourceIdentifier
    currency: CurrencyCode
    asset_type: str
    evidence_key: str
    valid_from: datetime
    valid_to: datetime | None = None
    instrument_id: str | None = None
    listing_id: str | None = None
    candidates: tuple[InstrumentCandidate, ...] = ()

    def __post_init__(self) -> None:
        for field in ("id", "provider_id", "instrument_id", "listing_id"):
            if getattr(self, field) is not None:
                source_id(getattr(self, field), field)
        for field in ("provider_key", "version", "asset_type", "evidence_key"):
            source_key(getattr(self, field), field)
        if (
            not isinstance(self.state, SourceMappingState)
            or not isinstance(self.identifier, SourceIdentifier)
            or not isinstance(self.currency, CurrencyCode)
        ):
            raise ValueError("Typed source mapping fields are required.")
        source_tuple(self.candidates, InstrumentCandidate, "candidates", 20)
        object.__setattr__(self, "valid_from", require_utc(self.valid_from))
        if self.valid_to is not None:
            object.__setattr__(self, "valid_to", require_utc(self.valid_to))
            if self.valid_to <= self.valid_from:
                raise ValueError("A nonempty mapping validity interval is required.")
        if self.state is SourceMappingState.RESOLVED:
            if self.instrument_id is None:
                raise ValueError("A resolved mapping requires a canonical instrument.")
        elif self.instrument_id is not None or self.listing_id is not None:
            raise ValueError("Unresolved mappings cannot invent canonical identities.")
        if self.listing_id is not None and self.instrument_id is None:
            raise ValueError("A listing requires its canonical instrument.")


class SourceIngestionService(Protocol):
    async def configure_source_provider(
        self,
        principal: Principal,
        command: SourceProviderRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> SourceProvider: ...
    async def register_source_license(
        self,
        principal: Principal,
        license: SourceLicense,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> SourceLicense: ...
    async def register_source_mapping(
        self,
        principal: Principal,
        mapping: SourceInstrumentMapping,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> SourceInstrumentMapping: ...
    async def register_source_calendar(
        self,
        principal: Principal,
        calendar: SourceCalendar,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> SourceCalendar: ...
    async def register_source_series(
        self,
        principal: Principal,
        series: SourceSeries,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> SourceSeries: ...
    async def ingest_price_history(
        self,
        principal: Principal,
        request: PriceHistoryRequest,
        pages: tuple[PriceHistoryPage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> PriceSnapshot: ...
    async def ingest_fx_rates(
        self,
        principal: Principal,
        request: FxRatesRequest,
        pages: tuple[FxRatePage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> FxSnapshot: ...
    async def ingest_benchmark_series(
        self,
        principal: Principal,
        request: BenchmarkSeriesRequest,
        pages: tuple[BenchmarkSeriesPage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> BenchmarkSnapshot: ...
    async def ingest_corporate_actions(
        self,
        principal: Principal,
        request: CorporateActionsRequest,
        pages: tuple[CorporateActionPage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> CorporateActionSnapshot: ...
    async def expire_source_snapshots(self, *, limit: int = 100) -> int: ...
