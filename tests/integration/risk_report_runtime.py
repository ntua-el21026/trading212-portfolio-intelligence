"""Fresh licensed history copies preserve the annual fixture's economic observations."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from trading212_application import historical as historical_app
from trading212_application import source_providers as ports
from trading212_application import sources as source_app
from trading212_application.historical_evidence import HistoricalPolicyRegistration
from trading212_application.source_ingestion import (
    SourceInstrumentMapping,
    SourceProviderRegistration,
)
from trading212_domain.enums import QualityState
from trading212_domain.historical import HistoricalFrequency
from trading212_domain.historical_results import PerformanceOptions
from trading212_domain.source_details import (
    CorporateActionSnapshot,
    SourceIdentifier,
    SourceIdentifierKind,
    SourceMappingState,
)
from trading212_domain.sources import (
    FxObservation,
    FxSnapshot,
    LicensePermission,
    PriceBasis,
    PriceObservation,
    PriceSnapshot,
    SourceCoverage,
    SourceLicense,
    SourcePeriod,
    SourceProvenance,
    SourceSeries,
    SourceSeriesKind,
)
from trading212_domain.values import CurrencyCode
from trading212_persistence.historical_capture import HistoricalCaptureStore
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_persistence.historical_store import PostgresHistoricalStore
from trading212_persistence.source_service import PostgresSourceService
from trading212_worker.historical_fixture import build_history_scenario, close_at
from trading212_worker.historical_seed import CURSOR_KEY
from trading212_worker.historical_source_seed import historical_calendar

from tests.integration.test_risk_runs_postgres import RunCase


async def fresh_report_history(
    case: RunCase, original: historical_app.PerformanceIntelligenceView
) -> historical_app.PerformanceIntelligenceView:
    """Use new source identities and a current knowledge cutoff, never renew old rows."""
    at = datetime.now(UTC)
    case.principal = replace(
        case.principal,
        authenticated_at=at - timedelta(minutes=1),
        expires_at=at + timedelta(hours=2),
    )

    def clock() -> datetime:
        return at

    history = PostgresHistoricalService(case.sessions, cursor_signing_key=CURSOR_KEY, clock=clock)
    captures = HistoricalCaptureStore(case.sessions, cursor_signing_key=CURSOR_KEY, clock=clock)
    saved = await captures.load(case.principal, original.context.input_snapshot_id)
    scenario = build_history_scenario("annual")
    window = case.command.window
    assert case.command.benchmark_version_id is None
    original_sources: tuple[PriceSnapshot | FxSnapshot | CorporateActionSnapshot, ...] = (
        *saved.input.price_snapshots,
        *saved.input.fx_snapshots,
        *saved.input.action_snapshots,
    )
    periods = {value.period for value in original_sources}
    assert len(periods) == 1
    period: SourcePeriod = periods.pop()
    assert period.start <= window.start_date <= window.end_date <= period.end
    days = tuple(day for day in scenario.sessions if period.start <= day <= period.end)
    assert 20 < len(days) <= 1000
    provider, license_id = str(uuid4()), str(uuid4())
    source = PostgresSourceService(
        sessions=case.sessions, cursor_signing_key=CURSOR_KEY, clock=clock
    )
    await source.configure_source_provider(
        case.principal,
        SourceProviderRegistration(
            id=provider,
            key="risk-report-runtime",
            name="Synthetic runtime copies of declared annual observations",
            adapter_version="history-fixture-1",
            configuration_state=source_app.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(
                ports.SourceCapability.PRICE_HISTORY,
                ports.SourceCapability.FX_RATES,
                ports.SourceCapability.CORPORATE_ACTIONS,
            ),
            supported_price_bases=(PriceBasis.RAW_CLOSE,),
        ),
        idempotency_key="risk-report-runtime:provider",
        correlation_id="risk-report-runtime",
    )
    await source.register_source_license(
        case.principal,
        SourceLicense(
            id=license_id,
            provider_id=provider,
            version="1",
            effective_at=scenario.opening_at - timedelta(days=1),
            store=LicensePermission.ALLOWED,
            display=LicensePermission.ALLOWED,
            report=LicensePermission.ALLOWED,
            export=LicensePermission.ALLOWED,
            retention_days=3650,
            attribution="Declared synthetic annual observations; fresh runtime copy only.",
            evidence_key="risk-report-runtime",
        ),
        idempotency_key="risk-report-runtime:license",
        correlation_id="risk-report-runtime",
    )
    calendar = historical_calendar(scenario)
    provenance = SourceProvenance(
        provider_id=provider,
        license_version_id=license_id,
        adapter_version="history-fixture-1",
        schema_version="history-source-1",
        source_revision="runtime-1",
        revision_order=1,
        effective_at=close_at(days[-1]),
        first_observed_at=at,
        synthetic=True,
    )
    coverage = SourceCoverage(
        expected_count=len(days), available_count=len(days), gaps=(), quality=QualityState.FRESH
    )
    series_ids: list[str] = []
    snapshot_ids: set[str] = set()
    for item in scenario.instruments:
        currency = item.listing.trading_currency
        mapping = str(uuid4())
        await source.register_source_mapping(
            case.principal,
            SourceInstrumentMapping(
                id=mapping,
                provider_id=provider,
                provider_key=item.listing.provider_instrument_id,
                version="runtime-1",
                state=SourceMappingState.RESOLVED,
                identifier=SourceIdentifier(
                    kind=SourceIdentifierKind.ISIN, value=item.instrument.isin or ""
                ),
                currency=currency,
                asset_type="equity",
                evidence_key="risk-report-runtime",
                valid_from=scenario.opening_at,
                instrument_id=str(item.instrument.id),
                listing_id=str(item.listing.id),
            ),
            idempotency_key=f"risk-report-runtime:mapping:{currency}",
            correlation_id="risk-report-runtime",
        )
        series = SourceSeries(
            id=str(uuid4()),
            owner_id=case.principal.owner_id,
            provider_id=provider,
            license_version_id=license_id,
            kind=SourceSeriesKind.SECURITY_PRICE,
            provider_key=item.listing.provider_instrument_id,
            mapping_version="runtime-1",
            basis=PriceBasis.RAW_CLOSE,
            currency=currency,
            calendar_id=calendar.id,
            calendar_version=calendar.version,
            mapping_id=mapping,
            instrument_id=str(item.instrument.id),
            listing_id=str(item.listing.id),
        )
        await source.register_source_series(
            case.principal,
            series,
            idempotency_key=f"risk-report-runtime:series:{currency}",
            correlation_id="risk-report-runtime",
        )
        series_ids.append(series.id)
        price = await source.ingest_price_history(
            case.principal,
            ports.PriceHistoryRequest(series=series, period=period, source_cutoff_at=at),
            (
                ports.PriceHistoryPage(
                    series=series,
                    provenance=provenance,
                    period=period,
                    coverage=coverage,
                    observations=tuple(
                        PriceObservation(
                            session_date=day,
                            effective_at=close_at(day),
                            value=scenario.price(str(currency), day),
                        )
                        for day in days
                    ),
                ),
            ),
            idempotency_key=f"risk-report-runtime:price:{currency}",
            correlation_id="risk-report-runtime",
        )
        actions = await source.ingest_corporate_actions(
            case.principal,
            ports.CorporateActionsRequest(series=series, period=period, source_cutoff_at=at),
            (
                ports.CorporateActionPage(
                    series=series,
                    provenance=provenance,
                    period=period,
                    coverage=SourceCoverage(
                        expected_count=0, available_count=0, gaps=(), quality=QualityState.FRESH
                    ),
                    observations=(),
                ),
            ),
            idempotency_key=f"risk-report-runtime:actions:{currency}",
            correlation_id="risk-report-runtime",
        )
        snapshot_ids.update((price.id, actions.id))
    fx = await source.ingest_fx_rates(
        case.principal,
        ports.FxRatesRequest(
            provider_id=provider,
            license_version_id=license_id,
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
        idempotency_key="risk-report-runtime:fx",
        correlation_id="risk-report-runtime",
    )
    snapshot_ids.add(fx.id)
    assert saved.input.selection.reporting_calendar_ref is not None
    assert saved.input.selection.source_policy is not None
    policy = HistoricalPolicyRegistration(
        id=str(uuid4()),
        key="risk-report-runtime",
        effective_at=at,
        accounting_policy=saved.input.selection.accounting_policy,
        source_policy=replace(
            saved.input.selection.source_policy,
            version="risk-report-runtime-1",
            provider_priority=(provider,),
        ),
        reporting_calendar_ref=saved.input.selection.reporting_calendar_ref,
        price_series_ids=tuple(series_ids),
        action_series_ids=tuple(series_ids),
    )
    await PostgresHistoricalStore(
        case.sessions, cursor_signing_key=CURSOR_KEY, clock=clock
    ).register_historical_policy(
        case.principal,
        str(case.command.account_id),
        policy,
        idempotency_key="risk-report-runtime:policy",
        correlation_id="risk-report-runtime",
    )
    old = await history.get_performance_summary(
        case.principal,
        str(case.command.account_id),
        query=historical_app.PerformanceSummaryQuery(
            window=window, options=PerformanceOptions(frequency=HistoricalFrequency.DAILY)
        ),
    )
    old_copy = await captures.load(case.principal, old.context.input_snapshot_id)
    assert old_copy.input == saved.input
    old_sources: tuple[PriceSnapshot | FxSnapshot | CorporateActionSnapshot, ...] = (
        *old_copy.input.price_snapshots,
        *old_copy.input.fx_snapshots,
        *old_copy.input.action_snapshots,
    )
    assert snapshot_ids.isdisjoint(value.id for value in old_sources)
    current = await history.get_performance_summary(
        case.principal,
        str(case.command.account_id),
        query=historical_app.PerformanceSummaryQuery(
            window=replace(window, source_cutoff_at=at),
            options=PerformanceOptions(frequency=HistoricalFrequency.DAILY),
        ),
    )
    new_copy = await captures.load(case.principal, current.context.input_snapshot_id)
    new_sources: tuple[PriceSnapshot | FxSnapshot | CorporateActionSnapshot, ...] = (
        *new_copy.input.price_snapshots,
        *new_copy.input.fx_snapshots,
        *new_copy.input.action_snapshots,
    )
    assert {value.id for value in new_sources} == snapshot_ids
    assert all(
        value.provenance.provider_id == provider and value.provenance.first_observed_at == at
        for value in new_sources
    )
    assert current.summary == old.summary == original.summary
    assert current.series == old.series == original.series
    assert {
        (value.series.currency, value.period, value.coverage, value.observations)
        for value in new_copy.input.price_snapshots
    } == {
        (value.series.currency, value.period, value.coverage, value.observations)
        for value in saved.input.price_snapshots
    }
    assert {
        (value.period, value.coverage, value.observations) for value in new_copy.input.fx_snapshots
    } == {(value.period, value.coverage, value.observations) for value in saved.input.fx_snapshots}
    assert {
        (value.series.currency, value.period, value.coverage, value.observations)
        for value in new_copy.input.action_snapshots
    } == {
        (value.series.currency, value.period, value.coverage, value.observations)
        for value in saved.input.action_snapshots
    }
    for field in (
        "method",
        "primitive_methods",
        "accounting_policy_version",
        "coverage",
        "quality",
        "availability",
        "reconstruction",
        "warnings",
        "assumptions",
        "schema_version",
        "warning_count",
        "warning_omitted_count",
    ):
        assert (
            getattr(current.context, field)
            == getattr(old.context, field)
            == getattr(original.context, field)
        ), field
    assert (await captures.load(case.principal, saved.id)).input == saved.input
    case.command = replace(
        case.command,
        window=replace(window, source_cutoff_at=at),
        historical_input_snapshot_id=UUID(current.context.input_snapshot_id),
    )
    return current
