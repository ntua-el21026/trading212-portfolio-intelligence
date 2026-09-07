"""Small hand-calculable canonical historical inputs, independent of the engine."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from trading212_domain import CurrencyCode, Money, QualityState
from trading212_domain import historical as d
from trading212_domain.source_details import CorporateActionSnapshot
from trading212_domain.sources import (
    MarketSession,
    PriceObservation,
    PriceSnapshot,
    SourceCalendar,
    SourceCoverage,
    SourcePeriod,
    source_snapshot_digest,
)

from .source_factories import EUR, provenance, series, uid

START = datetime(2025, 1, 1, tzinfo=UTC)


def coverage() -> d.HistoricalCoverage:
    return d.HistoricalCoverage(
        measures=tuple(
            d.HistoricalCoverageMeasure(
                key=kind, expected_count=1, available_count=1, complete=True
            )
            for kind in d.HistoricalCoverageKey
        )
    )


def metric(
    value: str | None,
    currency: CurrencyCode = EUR,
    key: d.HistoricalCoverageKey = d.HistoricalCoverageKey.VALUATIONS,
) -> d.HistoricalMoneyMetric:
    return d.HistoricalMoneyMetric(
        value=Money(Decimal(value), currency) if value is not None else None,
        availability=d.MetricAvailability.AVAILABLE
        if value is not None
        else d.MetricAvailability.UNAVAILABLE,
        reason_code=None if value is not None else d.HistoricalReason.COST_COVERAGE,
        quality=QualityState.FRESH if value is not None else QualityState.PARTIAL,
        coverage_key=key,
    )


def source_ref(
    identity: int, *, at: datetime = START - timedelta(days=1), kind: str = "broker_source_record"
) -> d.HistoricalSourceReference:
    # Call sites choose closed domain kinds, not arbitrary provider data.
    if kind == "historical_evidence":
        return d.HistoricalSourceReference(
            kind="historical_evidence", id=uid(identity), effective_at=at, first_observed_at=at
        )
    return d.HistoricalSourceReference(
        kind="broker_source_record", id=uid(identity), effective_at=at, first_observed_at=at
    )


def fixture(
    prices: tuple[str, ...] = ("100", "100", "110", "120"),
    *,
    cash: str = "0",
    quantity: str = "1",
    currency: CurrencyCode = EUR,
) -> d.HistoricalInput:
    dates = tuple(START - timedelta(days=1) + timedelta(days=i) for i in range(len(prices)))
    period = SourcePeriod(start=dates[0].date(), end=dates[-1].date())
    calendar = SourceCalendar(
        id="synthetic-utc",
        version="v1",
        timezone="UTC",
        period=period,
        sessions=tuple(
            MarketSession(session_date=at.date(), close_at=at.replace(hour=16)) for at in dates
        ),
    )
    metadata = replace(series(), currency=currency)
    snapshot = PriceSnapshot(
        id=uid(20),
        owner_id=uid(1),
        series=metadata,
        provenance=replace(
            provenance(),
            effective_at=dates[-1].replace(hour=16),
            first_observed_at=dates[-1].replace(hour=17),
        ),
        period=period,
        coverage=SourceCoverage(
            expected_count=len(prices),
            available_count=len(prices),
            gaps=(),
            quality=QualityState.FRESH,
        ),
        observations=tuple(
            PriceObservation(
                session_date=at.date(), effective_at=at.replace(hour=16), value=Decimal(price)
            )
            for at, price in zip(dates, prices, strict=True)
        ),
    )
    actions = CorporateActionSnapshot(
        id=uid(21),
        owner_id=snapshot.owner_id,
        series=snapshot.series,
        provenance=snapshot.provenance,
        period=snapshot.period,
        coverage=SourceCoverage(
            expected_count=0, available_count=0, gaps=(), quality=QualityState.FRESH
        ),
        observations=(),
    )
    quantity_value = Decimal(quantity)
    anchor = d.HistoricalValuationAnchor(
        id=uid(50),
        at=dates[0].replace(hour=16),
        timing="after_events",
        positions=(
            d.HistoricalAnchorPosition(
                listing_id=uid(7),
                instrument_id=uid(6),
                quantity=quantity_value,
                market_value=metric(str(quantity_value * Decimal(prices[0])), currency),
                acquisition_cost=metric(
                    str(quantity_value * Decimal(prices[0])), currency, d.HistoricalCoverageKey.COST
                ),
            ),
        ),
        cash=(Money(Decimal(cash), EUR),),
        origin=d.HistoricalOrigin.PROVIDER,
        source_refs=(uid(51),),
        coverage=coverage(),
        reconciliation=d.HistoricalReconciliationProof(
            policy_version="exact-v1",
            anchor_refs=(uid(51),),
            lines=(
                d.HistoricalReconciliationLine(
                    kind="quantity",
                    identity=uid(7),
                    currency=None,
                    expected=quantity_value,
                    observed=quantity_value,
                    residual=Decimal(0),
                    tolerance=Decimal(0),
                    state="reconciled",
                ),
            ),
            outcome="reconciled",
        ),
    )
    from trading212_domain.sources import SourceSelectionPolicy

    selection = d.HistoricalSelectionRequest(
        window=d.HistoricalWindow(
            start_date=START.date(),
            end_date=dates[-1].date(),
            source_cutoff_at=dates[-1] + timedelta(days=2),
            reporting_currency=EUR,
        ),
        accounting_policy=d.HistoricalAccountingPolicy(),
        source_policy=SourceSelectionPolicy(
            version="historical-source-v1",
            provider_priority=(uid(2),),
            max_age_seconds=3 * 86400,
            allow_closed_session_carry=True,
        ),
        reporting_calendar_ref=d.CalendarRef(id=calendar.id, version=calendar.version),
    )
    refs: tuple[d.HistoricalSourceReference, ...] = (
        source_ref(51, kind="historical_evidence"),
        source_ref(5),
        d.HistoricalSourceReference(
            kind="price_snapshot",
            id=snapshot.id,
            effective_at=snapshot.provenance.effective_at,
            first_observed_at=snapshot.provenance.first_observed_at,
            semantic_digest=source_snapshot_digest(snapshot),
        ),
    )
    capabilities: tuple[
        Literal["historical_orders", "historical_transactions", "historical_dividends"], ...
    ] = ("historical_orders", "historical_transactions", "historical_dividends")
    activity = tuple(
        d.HistoricalActivityCoverage(
            id=uid(300 + i),
            capability=capability,
            start_at=dates[0],
            end_at=selection.window.end_at,
            first_observed_at=selection.window.source_cutoff_at,
            ingestion_run_id=uid(310 + i),
            coverage_complete=True,
        )
        for i, capability in enumerate(capabilities)
    )
    refs = (
        *refs,
        d.HistoricalSourceReference(
            kind="corporate_action_snapshot",
            id=actions.id,
            effective_at=actions.provenance.effective_at,
            first_observed_at=actions.provenance.first_observed_at,
            semantic_digest=source_snapshot_digest(actions),
        ),
        *(
            d.HistoricalSourceReference(
                kind="ingestion_run",
                id=chunk.ingestion_run_id,
                effective_at=chunk.end_at,
                first_observed_at=chunk.first_observed_at,
            )
            for chunk in activity
        ),
    )
    return d.HistoricalInput(
        owner_id=uid(1),
        account_id=uid(90),
        selection=selection,
        opening=d.ObservedHistoricalOpening(anchor=anchor, bridge_coverage=coverage()),
        instruments=(
            d.HistoricalInstrument(
                listing_id=uid(7),
                instrument_id=uid(6),
                native_currency=currency,
                source_series_ids=(uid(9),),
            ),
        ),
        event_candidates=(),
        valuation_anchors=(),
        price_snapshots=(snapshot,),
        fx_snapshots=(),
        action_snapshots=(actions,),
        calendars=(calendar,),
        mapping_evidence=(
            d.HistoricalMappingEvidence(
                id=uid(5),
                source_ref=uid(5),
                instrument_id=uid(6),
                listing_id=uid(7),
                native_currency=currency,
                asset_type="equity",
                valid_from=dates[0],
                valid_to=None,
                first_observed_at=dates[0],
                state="resolved",
            ),
        ),
        classification_evidence=(),
        sources=refs,
        coverage=coverage(),
        activity_coverage=activity,
    )


def identity(number: int, at: datetime) -> d.HistoricalEventIdentity:
    return d.HistoricalEventIdentity(
        economic_key=f"event-{number}",
        revision_id=uid(number),
        source_record_id=uid(number),
        source_occurrence_id=None,
        economic_at=at,
        first_observed_at=at,
        revision_sequence=1,
    )


def with_events(value: d.HistoricalInput, *events: d.HistoricalEvent) -> d.HistoricalInput:
    return replace(
        value,
        event_candidates=tuple(events),
        sources=(
            *value.sources,
            *(
                source_ref(
                    int(item.identity.source_record_id.replace("-", ""), 16),
                    at=item.identity.first_observed_at,
                )
                for item in events
            ),
        ),
    )


def with_fx(
    value: d.HistoricalInput, rates: tuple[str, ...], *, base: CurrencyCode
) -> d.HistoricalInput:
    from trading212_domain.sources import FxObservation, FxSnapshot

    price = value.price_snapshots[0]
    fx = FxSnapshot(
        id=uid(30),
        owner_id=value.owner_id,
        calendar_id=price.series.calendar_id,
        calendar_version=price.series.calendar_version,
        provenance=price.provenance,
        period=price.period,
        coverage=price.coverage,
        observations=tuple(
            FxObservation(
                base=base,
                quote=EUR,
                rate=Decimal(rate),
                session_date=item.session_date,
                effective_at=item.effective_at,
                batch_key=f"fx-{index}",
            )
            for index, (item, rate) in enumerate(zip(price.observations, rates, strict=True))
        ),
    )
    return replace(
        value,
        fx_snapshots=(fx,),
        sources=(
            *value.sources,
            d.HistoricalSourceReference(
                kind="fx_snapshot",
                id=fx.id,
                effective_at=fx.provenance.effective_at,
                first_observed_at=fx.provenance.first_observed_at,
                semantic_digest=source_snapshot_digest(fx),
            ),
        ),
    )


def with_benchmark(
    value: d.HistoricalInput, a: tuple[str, ...], b: tuple[str, ...], *, daily: bool = False
) -> d.HistoricalInput:
    from trading212_domain.sources import (
        BenchmarkComponent,
        BenchmarkContent,
        BenchmarkObservation,
        BenchmarkRebalanceRule,
        BenchmarkSnapshot,
        PriceBasis,
    )

    price = value.price_snapshots[0]
    snapshots = []
    for number, levels in ((60, a), (61, b)):
        benchmark_series = replace(
            series(benchmark=True), id=uid(number), provider_key=f"benchmark-{number}"
        )
        snapshots.append(
            BenchmarkSnapshot(
                id=uid(number + 10),
                owner_id=value.owner_id,
                series=benchmark_series,
                provenance=price.provenance,
                period=price.period,
                coverage=price.coverage,
                observations=tuple(
                    BenchmarkObservation(
                        session_date=item.session_date,
                        effective_at=item.effective_at,
                        level=Decimal(level),
                    )
                    for item, level in zip(price.observations, levels, strict=True)
                ),
            )
        )
    content = BenchmarkContent(
        reporting_currency=EUR,
        effective_at=START,
        return_basis=PriceBasis.TOTAL_RETURN,
        calendar_id=price.series.calendar_id,
        calendar_version=price.series.calendar_version,
        rebalance_rule=BenchmarkRebalanceRule.DAILY_REBALANCED
        if daily
        else BenchmarkRebalanceRule.BUY_AND_HOLD,
        components=(
            BenchmarkComponent(source_id=uid(60), weight=Decimal(".6")),
            BenchmarkComponent(source_id=uid(61), weight=Decimal(".4")),
        ),
    )
    return replace(
        value,
        selection=replace(value.selection, benchmark_version_id=uid(80)),
        benchmark_input=d.CompositeBenchmarkInput(
            benchmark_version_id=uid(80),
            definition_id=uid(81),
            content_digest="a" * 64,
            content=content,
            published_at=START,
            benchmark_snapshots=tuple(snapshots),
        ),
    )


def point_in_time(value: d.HistoricalInput) -> d.HistoricalInput:
    original = value.price_snapshots[0]
    snapshots = tuple(
        replace(
            original,
            id=uid(400 + index),
            provenance=replace(
                original.provenance,
                effective_at=observation.effective_at,
                first_observed_at=observation.effective_at,
            ),
            period=SourcePeriod(start=observation.session_date, end=observation.session_date),
            observations=(observation,),
            coverage=SourceCoverage(
                expected_count=1, available_count=1, gaps=(), quality=QualityState.FRESH
            ),
        )
        for index, observation in enumerate(original.observations)
    )
    chunks = []
    capabilities: tuple[
        Literal["historical_orders", "historical_transactions", "historical_dividends"], ...
    ] = ("historical_orders", "historical_transactions", "historical_dividends")
    for index, observation in enumerate(original.observations):
        for j, capability in enumerate(capabilities):
            at = observation.effective_at.replace(hour=0) + timedelta(days=1)
            chunks.append(
                d.HistoricalActivityCoverage(
                    id=uid(500 + index * 3 + j),
                    capability=capability,
                    start_at=value.calendars[0].sessions[0].close_at,
                    end_at=at,
                    first_observed_at=at,
                    ingestion_run_id=uid(600 + index * 3 + j),
                    coverage_complete=True,
                )
            )
    actions = tuple(
        replace(
            value.action_snapshots[0],
            id=uid(3000 + index),
            provenance=snapshot.provenance,
            period=snapshot.period,
        )
        for index, snapshot in enumerate(snapshots)
    )
    refs = tuple(
        item
        for item in value.sources
        if item.kind not in ("price_snapshot", "ingestion_run", "corporate_action_snapshot")
    )
    refs = (
        *refs,
        *(
            d.HistoricalSourceReference(
                kind="price_snapshot",
                id=item.id,
                effective_at=item.provenance.effective_at,
                first_observed_at=item.provenance.first_observed_at,
                semantic_digest=source_snapshot_digest(item),
            )
            for item in snapshots
        ),
        *(
            d.HistoricalSourceReference(
                kind="ingestion_run",
                id=chunk.ingestion_run_id,
                effective_at=chunk.end_at,
                first_observed_at=chunk.first_observed_at,
            )
            for chunk in chunks
        ),
    )
    refs = (
        *refs,
        *(
            d.HistoricalSourceReference(
                kind="corporate_action_snapshot",
                id=item.id,
                effective_at=item.provenance.effective_at,
                first_observed_at=item.provenance.first_observed_at,
                semantic_digest=source_snapshot_digest(item),
            )
            for item in actions
        ),
    )
    return replace(
        value,
        selection=replace(
            value.selection,
            window=replace(
                value.selection.window, knowledge_policy=d.KnowledgePolicy.POINT_IN_TIME
            ),
        ),
        price_snapshots=snapshots,
        action_snapshots=actions,
        activity_coverage=tuple(chunks),
        sources=refs,
    )
