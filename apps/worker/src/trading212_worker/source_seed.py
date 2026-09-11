"""Idempotent reference-source replay through the authorized persistence boundary."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from trading212_application import source_providers as ports
from trading212_application import sources as app
from trading212_application.provider_observations import (
    ObservedBenchmarkProvider,
    ObservedFxReferenceProvider,
    ObservedInstrumentEnrichmentProvider,
    ObservedMarketPriceHistoryProvider,
)
from trading212_application.source_ingestion import (
    SourceInstrumentMapping,
    SourceProviderRegistration,
)
from trading212_domain import build_synthetic_identity
from trading212_domain.fixtures import fixture_uuid
from trading212_domain.source_details import (
    SourceIdentifier,
    SourceIdentifierKind,
    SourceMappingState,
)
from trading212_domain.sources import (
    BenchmarkComponent,
    BenchmarkContent,
    BenchmarkRebalanceRule,
    PriceBasis,
    SourceSeriesKind,
)
from trading212_domain.values import CurrencyCode
from trading212_persistence.provider_observation_store import PostgresProviderOutcomeObserver
from trading212_reference_data.replay import (
    ReplayBenchmarkProvider,
    ReplayContext,
    ReplayFxReferenceProvider,
    ReplayMarketPriceHistoryProvider,
    ReplayVariant,
)
from trading212_reference_data.replay_enrichment import ReplayInstrumentEnrichmentProvider
from trading212_reference_data.synthetic import (
    ADAPTER_VERSION,
    CALENDAR_ID,
    CALENDAR_VERSION,
    FIXTURE_PERIOD,
    LICENSE_ID,
    MAPPING_ID,
    PROVIDER_ID,
    PROVIDER_KEY,
    SyntheticData,
    synthetic_license,
    synthetic_series,
)
from trading212_security.principals import Principal, Scope

from .synthetic_grants import seed_synthetic_grants


async def collect_source_pages[T](
    fetch: Callable[[str | None], Awaitable[T | ports.SourceFailure]],
    *,
    page_type: type[T],
    next_cursor: Callable[[T], str | None],
    row_count: Callable[[T], int],
) -> tuple[T, ...]:
    """Retain only a complete bounded chain; failure never commits a valid-looking prefix."""
    pages = []
    seen: set[str] = set()
    cursor = None
    total = 0
    for _ in range(100):
        page = await fetch(cursor)
        if isinstance(page, ports.SourceFailure):
            raise RuntimeError(f"synthetic reference retrieval failed: {page.code.value}")
        if not isinstance(page, page_type):
            raise RuntimeError("synthetic reference retrieval returned an incompatible page")
        total += row_count(page)
        if total > 100_000 or row_count(page) > 1000:
            raise RuntimeError("synthetic reference retrieval exceeded its row bound")
        pages.append(page)
        cursor = next_cursor(page)
        if cursor is None:
            return tuple(pages)
        if cursor in seen:
            raise RuntimeError("synthetic reference retrieval repeated a page cursor")
        seen.add(cursor)
    raise RuntimeError("synthetic reference retrieval exceeded its page bound")


async def seed_source_scenarios(
    sessions: sessionmaker[Session], *, app_environment: str, at: datetime
) -> dict[str, str]:
    if app_environment not in {"local", "test"}:
        raise RuntimeError("synthetic reference seed is restricted to local/test environments")
    from trading212_persistence.source_service import PostgresSourceService

    identity = build_synthetic_identity()
    principal = Principal(
        principal_id=str(identity.principal.id),
        owner_id=str(identity.owner.id),
        issuer="local.synthetic",
        subject="synthetic-owner",
        scopes=frozenset({Scope.ANALYTICS_READ, Scope.TARGETS_WRITE, Scope.PORTFOLIO_READ}),
        authenticated_at=at - timedelta(minutes=1),
        expires_at=at + timedelta(hours=1),
    )
    seed_synthetic_grants(
        sessions,
        app_environment=app_environment,
        at=at,
        scopes=principal.scopes,
    )
    service = PostgresSourceService(
        sessions=sessions,
        cursor_signing_key=hashlib.sha256(b"synthetic-source-seed-cursors-v1").digest(),
        clock=lambda: at,
    )
    prefix = "synthetic-source-seed-v1"
    await service.configure_source_provider(
        principal,
        SourceProviderRegistration(
            id=PROVIDER_ID,
            key=PROVIDER_KEY,
            name="Synthetic reference replay",
            adapter_version=ADAPTER_VERSION,
            configuration_state=app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=tuple(ports.SourceCapability),
            supported_price_bases=tuple(PriceBasis),
            freshness_policy_version="synthetic-reference-freshness-1",
            max_age_seconds=604800,
        ),
        idempotency_key=f"{prefix}:provider",
        correlation_id=prefix,
    )
    await service.configure_source_provider(
        principal,
        SourceProviderRegistration(
            id=str(fixture_uuid("reference-external/unconfigured/v1")),
            key="external-unconfigured",
            name="External reference provider",
            adapter_version="not-configured-v1",
            configuration_state=app.ProviderConfigurationState.NOT_CONFIGURED,
            synthetic=False,
        ),
        idempotency_key=f"{prefix}:external",
        correlation_id=prefix,
    )
    license = synthetic_license()
    await service.register_source_license(
        principal, license, idempotency_key=f"{prefix}:license", correlation_id=prefix
    )
    series = synthetic_series(
        owner_id=str(identity.owner.id),
        instrument_id=str(identity.instrument.id),
        listing_id=str(identity.listing.id),
    )
    context = ReplayContext(license=license, series=series, clock=lambda: at)
    observer = PostgresProviderOutcomeObserver(
        sessions=sessions, principal=principal, provider_id=UUID(PROVIDER_ID), clock=lambda: at
    )
    if not isinstance(context.data, SyntheticData):
        raise RuntimeError("synthetic reference fixture did not decode")
    await service.register_source_calendar(
        principal,
        context.data.calendar,
        idempotency_key=f"{prefix}:calendar",
        correlation_id=prefix,
    )
    identifier = SourceIdentifier(kind=SourceIdentifierKind.ISIN, value="XS0000000001")
    enrichment = ObservedInstrumentEnrichmentProvider(
        ReplayInstrumentEnrichmentProvider(context), observer
    )
    resolution = await enrichment.resolve_instrument(
        ports.InstrumentResolutionRequest(identifier=identifier, source_cutoff_at=at)
    )
    if (
        not isinstance(resolution, ports.InstrumentResolutionResult)
        or resolution.state is not SourceMappingState.RESOLVED
    ):
        raise RuntimeError("synthetic reference mapping did not resolve")
    resolved_candidate = resolution.candidates[0]
    await service.register_source_mapping(
        principal,
        SourceInstrumentMapping(
            id=MAPPING_ID,
            provider_id=PROVIDER_ID,
            provider_key="SYNTHETIC_EQ_1",
            version="synthetic-mapping-1",
            state=SourceMappingState.RESOLVED,
            identifier=identifier,
            currency=CurrencyCode("EUR"),
            asset_type="equity",
            evidence_key=resolved_candidate.evidence_key,
            valid_from=resolved_candidate.valid_from,
            valid_to=resolved_candidate.valid_to,
            instrument_id=str(identity.instrument.id),
            listing_id=str(identity.listing.id),
            candidates=resolution.candidates,
        ),
        idempotency_key=f"{prefix}:mapping",
        correlation_id=prefix,
    )
    results = {}
    for item in series:
        await service.register_source_series(
            principal, item, idempotency_key=f"{prefix}:series:{item.id}", correlation_id=prefix
        )
        item_context = ReplayContext(
            license=license,
            series=series,
            clock=lambda: at,
            variant=ReplayVariant.GAP
            if item.kind is SourceSeriesKind.SECURITY_PRICE and item.basis is PriceBasis.RAW_CLOSE
            else ReplayVariant.STANDARD,
        )
        if item.kind is SourceSeriesKind.SECURITY_PRICE:
            price_request = ports.PriceHistoryRequest(
                series=item, period=FIXTURE_PERIOD, source_cutoff_at=at
            )
            price_provider = ObservedMarketPriceHistoryProvider(
                ReplayMarketPriceHistoryProvider(item_context), observer
            )

            async def fetch_price(
                cursor: str | None,
                provider: ObservedMarketPriceHistoryProvider = price_provider,
                request: ports.PriceHistoryRequest = price_request,
            ) -> ports.PriceHistoryPage | ports.SourceFailure:
                return await provider.get_price_history(replace(request, continuation=cursor))

            price_pages = await collect_source_pages(
                fetch_price,
                page_type=ports.PriceHistoryPage,
                next_cursor=lambda p: p.continuation,
                row_count=lambda p: len(p.observations),
            )
            price = await service.ingest_price_history(
                principal,
                price_request,
                price_pages,
                idempotency_key=f"{prefix}:price:{item.id}",
                correlation_id=prefix,
            )
            results[f"price_{item.basis.value}_snapshot_id"] = price.id
        else:
            benchmark_request = ports.BenchmarkSeriesRequest(
                series=item, period=FIXTURE_PERIOD, source_cutoff_at=at
            )
            benchmark_provider = ObservedBenchmarkProvider(
                ReplayBenchmarkProvider(item_context), observer
            )

            async def fetch_benchmark(
                cursor: str | None,
                provider: ObservedBenchmarkProvider = benchmark_provider,
                request: ports.BenchmarkSeriesRequest = benchmark_request,
            ) -> ports.BenchmarkSeriesPage | ports.SourceFailure:
                return await provider.get_series(replace(request, continuation=cursor))

            benchmark_pages = await collect_source_pages(
                fetch_benchmark,
                page_type=ports.BenchmarkSeriesPage,
                next_cursor=lambda p: p.continuation,
                row_count=lambda p: len(p.observations),
            )
            benchmark = await service.ingest_benchmark_series(
                principal,
                benchmark_request,
                benchmark_pages,
                idempotency_key=f"{prefix}:benchmark:{item.id}",
                correlation_id=prefix,
            )
            results[f"benchmark_{item.basis.value}_snapshot_id"] = benchmark.id
    fx_request = ports.FxRatesRequest(
        provider_id=PROVIDER_ID,
        license_version_id=LICENSE_ID,
        calendar_id=CALENDAR_ID,
        calendar_version=CALENDAR_VERSION,
        pairs=(
            ports.FxPair(base=CurrencyCode("EUR"), quote=CurrencyCode("USD")),
            ports.FxPair(base=CurrencyCode("GBP"), quote=CurrencyCode("EUR")),
        ),
        period=FIXTURE_PERIOD,
        source_cutoff_at=at,
    )
    fx_provider = ObservedFxReferenceProvider(ReplayFxReferenceProvider(context), observer)
    fx_pages = await collect_source_pages(
        lambda cursor: fx_provider.get_rates(replace(fx_request, continuation=cursor)),
        page_type=ports.FxRatePage,
        next_cursor=lambda p: p.continuation,
        row_count=lambda p: len(p.observations),
    )
    fx = await service.ingest_fx_rates(
        principal, fx_request, fx_pages, idempotency_key=f"{prefix}:fx", correlation_id=prefix
    )
    results["fx_snapshot_id"] = fx.id
    action_request = ports.CorporateActionsRequest(
        series=series[0], period=FIXTURE_PERIOD, source_cutoff_at=at
    )
    price_provider = ObservedMarketPriceHistoryProvider(
        ReplayMarketPriceHistoryProvider(context), observer
    )
    action_pages = await collect_source_pages(
        lambda cursor: price_provider.get_corporate_actions(
            replace(action_request, continuation=cursor)
        ),
        page_type=ports.CorporateActionPage,
        next_cursor=lambda p: p.continuation,
        row_count=lambda p: len(p.observations),
    )
    actions = await service.ingest_corporate_actions(
        principal,
        action_request,
        action_pages,
        idempotency_key=f"{prefix}:actions",
        correlation_id=prefix,
    )
    results["corporate_action_snapshot_id"] = actions.id
    benchmark_source = next(
        item
        for item in series
        if item.kind is SourceSeriesKind.BENCHMARK_LEVEL and item.basis is PriceBasis.TOTAL_RETURN
    )
    definition = await service.create_benchmark_definition(
        principal,
        app.CreateBenchmarkDefinitionCommand(
            name="Synthetic total-return benchmark",
            content=BenchmarkContent(
                reporting_currency=CurrencyCode("EUR"),
                effective_at=at,
                return_basis=PriceBasis.TOTAL_RETURN,
                calendar_id=CALENDAR_ID,
                calendar_version=CALENDAR_VERSION,
                rebalance_rule=BenchmarkRebalanceRule.BUY_AND_HOLD,
                components=(
                    BenchmarkComponent(source_id=benchmark_source.id, weight=Decimal("1")),
                ),
            ),
        ),
        idempotency_key=f"{prefix}:definition",
        correlation_id=prefix,
    )
    results["benchmark_definition_id"] = definition.definition.id
    if definition.selected_version is None:
        raise RuntimeError("synthetic benchmark definition did not publish its first version")
    results["benchmark_version_id"] = definition.selected_version.id
    return results
