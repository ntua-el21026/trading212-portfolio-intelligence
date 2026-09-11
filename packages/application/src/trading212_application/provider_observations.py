"""Content-free observations of actual fixed-purpose provider invocations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from trading212_domain.sources import SourceProvenance, source_key
from trading212_domain.values import require_utc

from . import source_providers as p


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderInvocation:
    id: UUID
    owner_id: UUID
    provider_id: UUID
    provider_key: str
    adapter_version: str
    capability: p.SourceCapability
    started_at: datetime

    def __post_init__(self) -> None:
        for value in (self.id, self.owner_id, self.provider_id):
            if not isinstance(value, UUID):
                raise ValueError("Canonical provider invocation identities are required.")
        source_key(self.provider_key, "provider_key")
        source_key(self.adapter_version, "adapter_version")
        if not isinstance(self.capability, p.SourceCapability):
            raise ValueError("A fixed provider capability is required.")
        object.__setattr__(self, "started_at", require_utc(self.started_at))


class ProviderOutcomeObserver(Protocol):
    async def begin(self, capability: p.SourceCapability) -> ProviderInvocation: ...

    async def complete(
        self, invocation: ProviderInvocation, *, failure: p.SourceProviderError | None
    ) -> None: ...


class ProviderInvocationFailed(RuntimeError):
    """An actual invocation raised an exception; its unsafe payload is discarded."""


class ProviderObservationUnavailable(RuntimeError):
    """The invocation cannot be durably observed; no response is accepted as observed."""


class _Observed:
    def __init__(self, observer: ProviderOutcomeObserver) -> None:
        self._observer = observer

    async def _invoke[T](
        self,
        capability: p.SourceCapability,
        invoke: Callable[[], Awaitable[T | p.SourceFailure]],
        expected: type[T],
    ) -> T | p.SourceFailure:
        invocation = await self._observer.begin(capability)
        raised = False
        try:
            result = await invoke()
        except Exception:
            raised = True
        if raised:
            # Recording failure itself propagates: no unobserved success claim.
            await self._observer.complete(
                invocation, failure=p.SourceProviderError.PERMANENT_FAILURE
            )
            # Raise outside the except suite so raw provider error context is absent.
            raise ProviderInvocationFailed("The provider invocation failed.") from None
        failure = None
        if isinstance(result, p.SourceFailure):
            if result.capability is capability and result.provider_key == invocation.provider_key:
                failure = result.code
            else:
                failure = p.SourceProviderError.INVALID_SCHEMA
        elif not isinstance(result, expected):
            failure = p.SourceProviderError.INVALID_SCHEMA
        elif not isinstance(result, p.InstrumentResolutionResult):
            provenance = getattr(result, "provenance", None)
            if (
                not isinstance(provenance, SourceProvenance)
                or provenance.provider_id != str(invocation.provider_id)
                or provenance.adapter_version != invocation.adapter_version
            ):
                failure = p.SourceProviderError.INVALID_SCHEMA
        await self._observer.complete(invocation, failure=failure)
        if failure is p.SourceProviderError.INVALID_SCHEMA:
            return p.SourceFailure(
                code=failure, capability=capability, provider_key=invocation.provider_key
            )
        return result


class ObservedMarketPriceHistoryProvider(_Observed):
    def __init__(
        self, provider: p.MarketPriceHistoryProvider, observer: ProviderOutcomeObserver
    ) -> None:
        super().__init__(observer)
        self._provider = provider

    async def get_price_history(
        self, request: p.PriceHistoryRequest
    ) -> p.PriceHistoryPage | p.SourceFailure:
        return await self._invoke(
            p.SourceCapability.PRICE_HISTORY,
            lambda: self._provider.get_price_history(request),
            p.PriceHistoryPage,
        )

    async def get_corporate_actions(
        self, request: p.CorporateActionsRequest
    ) -> p.CorporateActionPage | p.SourceFailure:
        return await self._invoke(
            p.SourceCapability.CORPORATE_ACTIONS,
            lambda: self._provider.get_corporate_actions(request),
            p.CorporateActionPage,
        )


class ObservedFxReferenceProvider(_Observed):
    def __init__(self, provider: p.FxReferenceProvider, observer: ProviderOutcomeObserver) -> None:
        super().__init__(observer)
        self._provider = provider

    async def get_rates(self, request: p.FxRatesRequest) -> p.FxRatePage | p.SourceFailure:
        return await self._invoke(
            p.SourceCapability.FX_RATES, lambda: self._provider.get_rates(request), p.FxRatePage
        )


class ObservedBenchmarkProvider(_Observed):
    def __init__(self, provider: p.BenchmarkProvider, observer: ProviderOutcomeObserver) -> None:
        super().__init__(observer)
        self._provider = provider

    async def get_series(
        self, request: p.BenchmarkSeriesRequest
    ) -> p.BenchmarkSeriesPage | p.SourceFailure:
        return await self._invoke(
            p.SourceCapability.BENCHMARK_SERIES,
            lambda: self._provider.get_series(request),
            p.BenchmarkSeriesPage,
        )


class ObservedClassificationProvider(_Observed):
    def __init__(
        self, provider: p.ClassificationProvider, observer: ProviderOutcomeObserver
    ) -> None:
        super().__init__(observer)
        self._provider = provider

    async def get_classifications(
        self, request: p.ClassificationRequest
    ) -> p.ClassificationPage | p.SourceFailure:
        return await self._invoke(
            p.SourceCapability.CLASSIFICATIONS,
            lambda: self._provider.get_classifications(request),
            p.ClassificationPage,
        )


class ObservedInstrumentEnrichmentProvider(ObservedClassificationProvider):
    def __init__(
        self, provider: p.InstrumentEnrichmentProvider, observer: ProviderOutcomeObserver
    ) -> None:
        super().__init__(provider, observer)
        self._enrichment = provider

    async def resolve_instrument(
        self, request: p.InstrumentResolutionRequest
    ) -> p.InstrumentResolutionResult | p.SourceFailure:
        return await self._invoke(
            p.SourceCapability.RESOLVE_INSTRUMENT,
            lambda: self._enrichment.resolve_instrument(request),
            p.InstrumentResolutionResult,
        )


class ObservedETFConstituentProvider(_Observed):
    def __init__(
        self, provider: p.ETFConstituentProvider, observer: ProviderOutcomeObserver
    ) -> None:
        super().__init__(observer)
        self._provider = provider

    async def get_constituents(
        self, request: p.ConstituentRequest
    ) -> p.ConstituentPage | p.SourceFailure:
        return await self._invoke(
            p.SourceCapability.CONSTITUENTS,
            lambda: self._provider.get_constituents(request),
            p.ConstituentPage,
        )
