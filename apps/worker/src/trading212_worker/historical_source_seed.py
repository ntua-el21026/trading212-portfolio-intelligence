"""Exact licensed synthetic history through the existing source-ingestion port."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from trading212_application import source_providers as ports
from trading212_application import sources as app
from trading212_application.source_ingestion import (
    SourceInstrumentMapping,
    SourceProviderRegistration,
)
from trading212_domain import build_synthetic_identity
from trading212_domain.enums import QualityState
from trading212_domain.source_details import (
    SourceIdentifier,
    SourceIdentifierKind,
    SourceMappingState,
)
from trading212_domain.sources import (
    BenchmarkComponent,
    BenchmarkContent,
    BenchmarkObservation,
    BenchmarkRebalanceRule,
    FxObservation,
    LicensePermission,
    MarketSession,
    PriceBasis,
    PriceObservation,
    SourceCalendar,
    SourceCoverage,
    SourceLicense,
    SourcePeriod,
    SourceProvenance,
    SourceSeries,
    SourceSeriesKind,
)
from trading212_domain.values import CurrencyCode
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import Principal

from .historical_fixture import SyntheticHistoryScenario, close_at, history_id


def historical_calendar(scenario: SyntheticHistoryScenario) -> SourceCalendar:
    return SourceCalendar(
        id=f"synthetic-history-{scenario.variant}",
        version="daily-v1",
        timezone="UTC",
        period=SourcePeriod(start=scenario.start, end=scenario.end),
        sessions=tuple(
            MarketSession(session_date=day, close_at=close_at(day)) for day in scenario.sessions
        ),
    )


async def register_historical_sources(
    service: PostgresSourceService,
    principal: Principal,
    scenario: SyntheticHistoryScenario,
) -> tuple[tuple[SourceSeries, ...], str]:
    prefix = f"history-{scenario.variant}-v1"
    provider_id = history_id(f"{scenario.variant}/provider")
    license_id = history_id(f"{scenario.variant}/license")
    calendar = historical_calendar(scenario)
    await service.configure_source_provider(
        principal,
        SourceProviderRegistration(
            id=provider_id,
            key=prefix,
            name=f"Synthetic {scenario.variant} historical evidence",
            adapter_version="history-fixture-1",
            configuration_state=app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            freshness_policy_version="history-daily-close-1",
            max_age_seconds=86400,
            capabilities=(
                ports.SourceCapability.PRICE_HISTORY,
                ports.SourceCapability.FX_RATES,
                ports.SourceCapability.BENCHMARK_SERIES,
                ports.SourceCapability.CORPORATE_ACTIONS,
            ),
            supported_price_bases=(PriceBasis.RAW_CLOSE, PriceBasis.TOTAL_RETURN),
        ),
        idempotency_key=f"{prefix}:provider",
        correlation_id=prefix,
    )
    await service.register_source_license(
        principal,
        SourceLicense(
            id=license_id,
            provider_id=provider_id,
            version="history-synthetic-license-1",
            effective_at=scenario.opening_at - timedelta(days=1),
            store=LicensePermission.ALLOWED,
            display=LicensePermission.ALLOWED,
            report=LicensePermission.ALLOWED,
            export=LicensePermission.ALLOWED,
            retention_days=3650,
            attribution="Declared synthetic historical observations; no external market provider.",
            evidence_key=f"{prefix}-license",
        ),
        idempotency_key=f"{prefix}:license",
        correlation_id=prefix,
    )
    await service.register_source_calendar(
        principal,
        calendar,
        idempotency_key=f"{prefix}:calendar",
        correlation_id=prefix,
    )
    series = []
    for item in scenario.instruments:
        currency = item.listing.trading_currency
        mapping_id = history_id(f"{scenario.variant}/{currency}/mapping")
        await service.register_source_mapping(
            principal,
            SourceInstrumentMapping(
                id=mapping_id,
                provider_id=provider_id,
                provider_key=item.listing.provider_instrument_id,
                version="history-mapping-1",
                state=SourceMappingState.RESOLVED,
                identifier=SourceIdentifier(
                    kind=SourceIdentifierKind.ISIN, value=item.instrument.isin or ""
                ),
                currency=currency,
                asset_type="equity",
                evidence_key=f"{prefix}-{currency}-identity",
                valid_from=scenario.opening_at,
                instrument_id=str(item.instrument.id),
                listing_id=str(item.listing.id),
            ),
            idempotency_key=f"{prefix}:mapping:{currency}",
            correlation_id=prefix,
        )
        for kind in SourceSeriesKind:
            security = kind is SourceSeriesKind.SECURITY_PRICE
            value = SourceSeries(
                id=history_id(f"{scenario.variant}/{currency}/{kind.value}"),
                owner_id=str(build_synthetic_identity().owner.id),
                provider_id=provider_id,
                license_version_id=license_id,
                kind=kind,
                provider_key=item.listing.provider_instrument_id
                if security
                else f"HISTORY_INDEX_{currency}",
                mapping_version="history-mapping-1",
                basis=PriceBasis.RAW_CLOSE if security else PriceBasis.TOTAL_RETURN,
                currency=currency,
                calendar_id=calendar.id,
                calendar_version=calendar.version,
                mapping_id=mapping_id if security else None,
                instrument_id=str(item.instrument.id) if security else None,
                listing_id=str(item.listing.id) if security else None,
            )
            await service.register_source_series(
                principal,
                value,
                idempotency_key=f"{prefix}:series:{currency}:{kind.value}",
                correlation_id=prefix,
            )
            series.append(value)
    label = "annual" if scenario.variant == "annual" else "timely"
    benchmark = await service.create_benchmark_definition(
        principal,
        app.CreateBenchmarkDefinitionCommand(
            name=f"Synthetic {label} 60/40 benchmark",
            content=BenchmarkContent(
                reporting_currency=CurrencyCode("EUR"),
                effective_at=scenario.opening_at,
                return_basis=PriceBasis.TOTAL_RETURN,
                rebalance_rule=BenchmarkRebalanceRule.BUY_AND_HOLD,
                calendar_id=calendar.id,
                calendar_version=calendar.version,
                components=tuple(
                    BenchmarkComponent(
                        source_id=value.id,
                        weight=Decimal("0.6") if str(value.currency) == "EUR" else Decimal("0.4"),
                    )
                    for value in series
                    if value.kind is SourceSeriesKind.BENCHMARK_LEVEL
                ),
            ),
        ),
        idempotency_key=f"{prefix}:benchmark",
        correlation_id=prefix,
    )
    if benchmark.selected_version is None:
        raise RuntimeError("Historical synthetic benchmark was not published")
    return tuple(series), benchmark.selected_version.id


async def ingest_historical_reference_batch(
    service: PostgresSourceService,
    principal: Principal,
    scenario: SyntheticHistoryScenario,
    series: tuple[SourceSeries, ...],
    *,
    period: SourcePeriod,
    at: datetime,
) -> dict[str, str]:
    prefix = f"history-{scenario.variant}-v1:{period.start}:{period.end}"
    days = tuple(day for day in scenario.sessions if period.start <= day <= period.end)
    if not days or len(days) > 1000 or close_at(days[-1]) > at:
        raise ValueError("Historical replay batch must be covered, bounded and already observed")
    coverage = SourceCoverage(
        expected_count=len(days), available_count=len(days), gaps=(), quality=QualityState.FRESH
    )
    provenance = SourceProvenance(
        provider_id=history_id(f"{scenario.variant}/provider"),
        license_version_id=history_id(f"{scenario.variant}/license"),
        adapter_version="history-fixture-1",
        schema_version="history-source-1",
        source_revision=f"history-{period.start}-{period.end}",
        revision_order=1,
        effective_at=close_at(days[-1]),
        first_observed_at=at,
        synthetic=True,
    )
    result = {}
    for value in series:
        currency = str(value.currency)
        if value.kind is SourceSeriesKind.SECURITY_PRICE:
            request = ports.PriceHistoryRequest(series=value, period=period, source_cutoff_at=at)
            page = ports.PriceHistoryPage(
                series=value,
                provenance=provenance,
                period=period,
                coverage=coverage,
                observations=tuple(
                    PriceObservation(
                        session_date=day,
                        effective_at=close_at(day),
                        value=scenario.price(currency, day),
                    )
                    for day in days
                ),
            )
            snapshot = await service.ingest_price_history(
                principal,
                request,
                (page,),
                idempotency_key=f"{prefix}:price:{currency}",
                correlation_id="synthetic-historical-reference",
            )
            result[f"price_{currency}"] = snapshot.id
            actions = await service.ingest_corporate_actions(
                principal,
                ports.CorporateActionsRequest(series=value, period=period, source_cutoff_at=at),
                (
                    ports.CorporateActionPage(
                        series=value,
                        provenance=provenance,
                        period=period,
                        coverage=SourceCoverage(
                            expected_count=0, available_count=0, gaps=(), quality=QualityState.FRESH
                        ),
                        observations=(),
                    ),
                ),
                idempotency_key=f"{prefix}:actions:{currency}",
                correlation_id="synthetic-historical-reference",
            )
            result[f"actions_{currency}"] = actions.id
        else:
            benchmark = await service.ingest_benchmark_series(
                principal,
                ports.BenchmarkSeriesRequest(series=value, period=period, source_cutoff_at=at),
                (
                    ports.BenchmarkSeriesPage(
                        series=value,
                        provenance=provenance,
                        period=period,
                        coverage=coverage,
                        observations=tuple(
                            BenchmarkObservation(
                                session_date=day,
                                effective_at=close_at(day),
                                level=scenario.benchmark(currency, day),
                            )
                            for day in days
                        ),
                    ),
                ),
                idempotency_key=f"{prefix}:benchmark:{currency}",
                correlation_id="synthetic-historical-reference",
            )
            result[f"benchmark_{currency}"] = benchmark.id
    calendar = historical_calendar(scenario)
    fx = await service.ingest_fx_rates(
        principal,
        ports.FxRatesRequest(
            provider_id=provenance.provider_id,
            license_version_id=provenance.license_version_id,
            calendar_id=calendar.id,
            calendar_version=calendar.version,
            pairs=(ports.FxPair(base=CurrencyCode("USD"), quote=CurrencyCode("EUR")),),
            period=period,
            source_cutoff_at=at,
        ),
        (
            ports.FxRatePage(
                provenance=provenance,
                period=period,
                coverage=coverage,
                observations=tuple(
                    FxObservation(
                        base=CurrencyCode("USD"),
                        quote=CurrencyCode("EUR"),
                        session_date=day,
                        effective_at=close_at(day),
                        rate=scenario.fx(day),
                        batch_key=f"history-{day}",
                    )
                    for day in days
                ),
            ),
        ),
        idempotency_key=f"{prefix}:fx",
        correlation_id="synthetic-historical-reference",
    )
    result["fx"] = fx.id
    return result
