"""Actual provider wrappers distinguish attempts, safe failures and recording errors."""

from dataclasses import dataclass, field, replace
from uuid import UUID, uuid4

import pytest
from trading212_application import source_providers as p
from trading212_application.provider_observations import (
    ObservedBenchmarkProvider,
    ObservedETFConstituentProvider,
    ObservedFxReferenceProvider,
    ObservedInstrumentEnrichmentProvider,
    ObservedMarketPriceHistoryProvider,
    ProviderInvocation,
    ProviderInvocationFailed,
    ProviderObservationUnavailable,
)
from trading212_domain import CurrencyCode, build_synthetic_identity
from trading212_domain.source_details import SourceIdentifier, SourceIdentifierKind
from trading212_domain.sources import PriceBasis, SourceSeriesKind
from trading212_reference_data.replay import (
    ReplayBenchmarkProvider,
    ReplayFxReferenceProvider,
    ReplayMarketPriceHistoryProvider,
)
from trading212_reference_data.replay_enrichment import (
    ReplayETFConstituentProvider,
    ReplayInstrumentEnrichmentProvider,
)
from trading212_reference_data.synthetic import (
    ADAPTER_VERSION,
    CALENDAR_ID,
    CALENDAR_VERSION,
    FIXTURE_KNOWN_AT,
    FIXTURE_PERIOD,
    FUND_SERIES_ID,
    LICENSE_ID,
    PROVIDER_ID,
    PROVIDER_KEY,
)
from trading212_reference_data.unconfigured import UnconfiguredReferenceProviders

from tests.unit.test_reference_replay import context, price_request

pytestmark = pytest.mark.unit


@dataclass
class Observer:
    provider_key: str = PROVIDER_KEY
    invocations: list[ProviderInvocation] = field(default_factory=list)
    outcomes: list[tuple[ProviderInvocation, p.SourceProviderError | None]] = field(
        default_factory=list
    )
    recording_available: bool = True

    async def begin(self, capability: p.SourceCapability) -> ProviderInvocation:
        result = ProviderInvocation(
            id=uuid4(),
            owner_id=build_synthetic_identity().owner.id,
            provider_id=UUID(PROVIDER_ID),
            provider_key=self.provider_key,
            adapter_version=ADAPTER_VERSION,
            capability=capability,
            started_at=FIXTURE_KNOWN_AT,
        )
        self.invocations.append(result)
        return result

    async def complete(
        self, invocation: ProviderInvocation, *, failure: p.SourceProviderError | None
    ) -> None:
        if not self.recording_available:
            raise ProviderObservationUnavailable("Provider observation storage is unavailable.")
        self.outcomes.append((invocation, failure))


async def test_all_seven_real_typed_operations_record_successful_physical_attempts() -> None:
    ctx, observer = context(), Observer()
    price = ObservedMarketPriceHistoryProvider(ReplayMarketPriceHistoryProvider(ctx), observer)
    request = price_request(ctx)
    assert isinstance(await price.get_price_history(request), p.PriceHistoryPage)
    assert isinstance(
        await price.get_corporate_actions(
            p.CorporateActionsRequest(
                series=request.series,
                period=request.period,
                source_cutoff_at=request.source_cutoff_at,
            )
        ),
        p.CorporateActionPage,
    )
    fx = ObservedFxReferenceProvider(ReplayFxReferenceProvider(ctx), observer)
    assert isinstance(
        await fx.get_rates(
            p.FxRatesRequest(
                provider_id=PROVIDER_ID,
                license_version_id=LICENSE_ID,
                calendar_id=CALENDAR_ID,
                calendar_version=CALENDAR_VERSION,
                pairs=(p.FxPair(base=CurrencyCode("EUR"), quote=CurrencyCode("USD")),),
                period=FIXTURE_PERIOD,
                source_cutoff_at=FIXTURE_KNOWN_AT,
            )
        ),
        p.FxRatePage,
    )
    benchmark = ObservedBenchmarkProvider(ReplayBenchmarkProvider(ctx), observer)
    assert isinstance(
        await benchmark.get_series(
            p.BenchmarkSeriesRequest(
                series=next(
                    row
                    for row in ctx.series
                    if row.kind is SourceSeriesKind.BENCHMARK_LEVEL
                    and row.basis is PriceBasis.TOTAL_RETURN
                ),
                period=FIXTURE_PERIOD,
                source_cutoff_at=FIXTURE_KNOWN_AT,
            )
        ),
        p.BenchmarkSeriesPage,
    )
    enrichment = ObservedInstrumentEnrichmentProvider(
        ReplayInstrumentEnrichmentProvider(ctx), observer
    )
    assert isinstance(
        await enrichment.resolve_instrument(
            p.InstrumentResolutionRequest(
                identifier=SourceIdentifier(kind=SourceIdentifierKind.ISIN, value="XS0000000001"),
                source_cutoff_at=FIXTURE_KNOWN_AT,
            )
        ),
        p.InstrumentResolutionResult,
    )
    assert isinstance(
        await enrichment.get_classifications(
            p.ClassificationRequest(
                instrument_ids=(str(build_synthetic_identity().instrument.id),),
                taxonomy="synthetic-taxonomy",
                taxonomy_version="1",
                source_cutoff_at=FIXTURE_KNOWN_AT,
            )
        ),
        p.ClassificationPage,
    )
    constituents = ObservedETFConstituentProvider(ReplayETFConstituentProvider(ctx), observer)
    assert isinstance(
        await constituents.get_constituents(
            p.ConstituentRequest(
                fund_series_id=FUND_SERIES_ID,
                effective_at=FIXTURE_KNOWN_AT,
                source_cutoff_at=FIXTURE_KNOWN_AT,
            )
        ),
        p.ConstituentPage,
    )
    assert {call.capability for call in observer.invocations} == set(p.SourceCapability)
    assert len({call.id for call in observer.invocations}) == 7
    assert all(failure is None for _, failure in observer.outcomes)
    await price.get_price_history(request)
    assert len({call.id for call in observer.invocations}) == 8


async def test_unconfigured_result_is_preserved_and_not_fabricated_success() -> None:
    observer = Observer(provider_key="external-unconfigured")
    provider = ObservedMarketPriceHistoryProvider(UnconfiguredReferenceProviders(), observer)
    result = await provider.get_price_history(price_request(context()))
    assert (
        isinstance(result, p.SourceFailure) and result.code is p.SourceProviderError.NOT_CONFIGURED
    )
    assert observer.outcomes[0][1] is p.SourceProviderError.NOT_CONFIGURED


@pytest.mark.parametrize("fault", ["provider", "capability", "provenance", "version", "schema"])
async def test_wrong_response_binding_records_safe_schema_failure(fault: str) -> None:
    ctx, observer = context(), Observer()
    response = await ReplayMarketPriceHistoryProvider(ctx).get_price_history(price_request(ctx))
    assert isinstance(response, p.PriceHistoryPage)
    page: p.PriceHistoryPage = response

    class Provider:
        async def get_price_history(
            self, request: p.PriceHistoryRequest
        ) -> p.PriceHistoryPage | p.SourceFailure:
            if fault in {"provider", "capability"}:
                return p.SourceFailure(
                    code=p.SourceProviderError.TIMEOUT,
                    capability=p.SourceCapability.FX_RATES
                    if fault == "capability"
                    else p.SourceCapability.PRICE_HISTORY,
                    provider_key="other-provider" if fault == "provider" else PROVIDER_KEY,
                )
            if fault == "schema":
                return object()  # type: ignore[return-value]
            provider_id = str(uuid4()) if fault == "provenance" else PROVIDER_ID
            return replace(
                page,
                series=replace(page.series, provider_id=provider_id),
                provenance=replace(
                    page.provenance,
                    provider_id=provider_id,
                    adapter_version="other-adapter" if fault == "version" else ADAPTER_VERSION,
                ),
            )

        async def get_corporate_actions(
            self, request: p.CorporateActionsRequest
        ) -> p.SourceFailure:
            raise AssertionError("Unrequested capability")

    result = await ObservedMarketPriceHistoryProvider(Provider(), observer).get_price_history(
        price_request(ctx)
    )
    assert (
        isinstance(result, p.SourceFailure) and result.code is p.SourceProviderError.INVALID_SCHEMA
    )
    assert observer.outcomes[0][1] is p.SourceProviderError.INVALID_SCHEMA


async def test_unexpected_exception_discards_secret_cause_and_context() -> None:
    observer = Observer()

    class Provider:
        async def get_rates(self, request: p.FxRatesRequest) -> p.SourceFailure:
            raise RuntimeError("synthetic-private-provider-canary")

    request = p.FxRatesRequest(
        provider_id=PROVIDER_ID,
        license_version_id=LICENSE_ID,
        calendar_id=CALENDAR_ID,
        calendar_version=CALENDAR_VERSION,
        pairs=(p.FxPair(base=CurrencyCode("EUR"), quote=CurrencyCode("USD")),),
        period=FIXTURE_PERIOD,
        source_cutoff_at=FIXTURE_KNOWN_AT,
    )
    with pytest.raises(ProviderInvocationFailed) as caught:
        await ObservedFxReferenceProvider(Provider(), observer).get_rates(request)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "synthetic-private-provider-canary" not in repr(caught.value)
    assert observer.outcomes[0][1] is p.SourceProviderError.PERMANENT_FAILURE


async def test_recording_failure_cannot_return_an_observed_success() -> None:
    ctx, observer = context(), Observer(recording_available=False)
    with pytest.raises(ProviderObservationUnavailable):
        await ObservedMarketPriceHistoryProvider(
            ReplayMarketPriceHistoryProvider(ctx), observer
        ).get_price_history(price_request(ctx))
    assert len(observer.invocations) == 1 and observer.outcomes == []
