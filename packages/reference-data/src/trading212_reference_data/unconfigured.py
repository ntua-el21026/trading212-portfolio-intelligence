"""Explicit unavailable external configuration; never substitutes replay or empty data."""

from trading212_application import source_providers as ports


def _unconfigured(capability: ports.SourceCapability) -> ports.SourceFailure:
    return ports.SourceFailure(
        code=ports.SourceProviderError.NOT_CONFIGURED,
        capability=capability,
        provider_key="external-unconfigured",
        retryable=False,
    )


class UnconfiguredReferenceProviders:
    """The closed seven operations remain unavailable until a real adapter is selected."""

    async def get_price_history(self, request: ports.PriceHistoryRequest) -> ports.SourceFailure:
        return _unconfigured(ports.SourceCapability.PRICE_HISTORY)

    async def get_corporate_actions(
        self, request: ports.CorporateActionsRequest
    ) -> ports.SourceFailure:
        return _unconfigured(ports.SourceCapability.CORPORATE_ACTIONS)

    async def get_rates(self, request: ports.FxRatesRequest) -> ports.SourceFailure:
        return _unconfigured(ports.SourceCapability.FX_RATES)

    async def get_series(self, request: ports.BenchmarkSeriesRequest) -> ports.SourceFailure:
        return _unconfigured(ports.SourceCapability.BENCHMARK_SERIES)

    async def resolve_instrument(
        self, request: ports.InstrumentResolutionRequest
    ) -> ports.SourceFailure:
        return _unconfigured(ports.SourceCapability.RESOLVE_INSTRUMENT)

    async def get_classifications(
        self, request: ports.ClassificationRequest
    ) -> ports.SourceFailure:
        return _unconfigured(ports.SourceCapability.CLASSIFICATIONS)

    async def get_constituents(self, request: ports.ConstituentRequest) -> ports.SourceFailure:
        return _unconfigured(ports.SourceCapability.CONSTITUENTS)
