"""Idempotent local/test histories using canonical ingestion and typed registration."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, localcontext
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.historical_evidence import (
    HistoricalActivityCoverageRegistration,
    HistoricalEvidenceRegistration,
    HistoricalPolicyRegistration,
)
from trading212_application.ingestion import (
    IngestionCapability,
    IngestionCoordinator,
    RunMode,
    RunStatus,
)
from trading212_domain import build_synthetic_identity
from trading212_domain import historical as d
from trading212_domain.enums import QualityState
from trading212_domain.sources import SourcePeriod, SourceSelectionPolicy, SourceSeriesKind
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.historical_store import PostgresHistoricalStore
from trading212_persistence.mappers import account_to_model, instrument_to_model, listing_to_model
from trading212_persistence.models import (
    BrokerAccountModel,
    InstrumentModel,
    ListingModel,
    SourceRecordModel,
    SourceRecordOccurrenceModel,
)
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import Principal, Scope

from .historical_fixture import (
    HISTORY_CONTEXT,
    HISTORY_RECEIPT,
    SyntheticHistoryScenario,
    build_history_scenario,
    close_at,
    history_id,
)
from .historical_provider import SyntheticHistoricalProvider
from .historical_source_seed import (
    historical_calendar,
    ingest_historical_reference_batch,
    register_historical_sources,
)
from .historical_target_seed import seed_historical_target
from .materializer import PostgresCanonicalMaterializer
from .postgres_store import PostgresIngestionStore

CURSOR_KEY = hashlib.sha256(b"synthetic-historical-seed-cursors-v1").digest()


def fixed_clock(at: datetime) -> Callable[[], datetime]:
    return lambda: at


def history_principal(at: datetime) -> Principal:
    identity = build_synthetic_identity()
    return Principal(
        principal_id=str(identity.principal.id),
        owner_id=str(identity.owner.id),
        issuer="local.synthetic",
        subject="synthetic-owner",
        scopes=frozenset(Scope),
        authenticated_at=at - timedelta(minutes=1),
        expires_at=at + timedelta(hours=2),
    )


def _seed_identity(sessions: sessionmaker[Session], scenario: SyntheticHistoryScenario) -> None:
    models: list[BrokerAccountModel | InstrumentModel | ListingModel] = [
        account_to_model(scenario.account)
    ]
    for item in scenario.instruments:
        models.extend(
            (
                instrument_to_model(item.instrument, observed_at=item.listing.valid_from),
                listing_to_model(item.listing),
            )
        )
    with sessions.begin() as session:
        for model in models:
            values = {
                column.name: getattr(model, column.name)
                for column in model.__table__.columns
                if getattr(model, column.name) is not None or column.server_default is None
            }
            session.execute(insert(type(model)).values(**values).on_conflict_do_nothing())


async def _observe(
    sessions: sessionmaker[Session],
    scenario: SyntheticHistoryScenario,
    *,
    economic_at: datetime,
    received_at: datetime,
    label: str,
    include_equal: bool = True,
) -> tuple[str, ...]:
    key = f"history-{scenario.variant}-v1:{label}"
    run = await IngestionCoordinator(
        provider=SyntheticHistoricalProvider(
            scenario,
            economic_at=economic_at,
            clock=lambda: received_at,
            include_equal=include_equal,
        ),
        store=PostgresIngestionStore(
            sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
        ),
        clock=lambda: received_at,
    ).refresh(
        owner_id=str(build_synthetic_identity().owner.id),
        account_id=str(scenario.account.id),
        mode=RunMode.FULL,
        idempotency_key=key,
        correlation_id=key,
    )
    if run.status is not RunStatus.SUCCEEDED:
        raise RuntimeError(
            f"synthetic historical ingestion did not complete: {scenario.variant}/{label}"
        )
    if include_equal:
        capabilities: tuple[
            Literal["historical_orders", "historical_transactions", "historical_dividends"], ...
        ] = ("historical_orders", "historical_transactions", "historical_dividends")
        coverage = HistoricalEvidenceRegistration(
            id=history_id(f"{scenario.variant}/activity-coverage/{label}"),
            key=f"history-{scenario.variant}-{label}-activity",
            activity_coverage=tuple(
                HistoricalActivityCoverageRegistration(
                    id=history_id(f"{scenario.variant}/activity-coverage/{label}/{capability}"),
                    ingestion_run_id=run.id,
                    capability=capability,
                    start_at=scenario.opening_at,
                    end_at=economic_at,
                    coverage_complete=True,
                )
                for capability in capabilities
            ),
        )
        await PostgresHistoricalStore(
            sessions, cursor_signing_key=CURSOR_KEY, clock=fixed_clock(received_at)
        ).register_historical_evidence(
            history_principal(received_at),
            str(scenario.account.id),
            coverage,
            idempotency_key=f"{key}:coverage",
            correlation_id="synthetic-historical-coverage",
        )
    with sessions() as session:
        references = session.scalars(
            select(SourceRecordModel.id)
            .join(
                SourceRecordOccurrenceModel,
                SourceRecordOccurrenceModel.source_record_id == SourceRecordModel.id,
            )
            .where(
                SourceRecordOccurrenceModel.ingestion_run_id == UUID(run.id),
                SourceRecordModel.broker_account_id == scenario.account.id,
                SourceRecordModel.capability.in_(
                    (IngestionCapability.ACCOUNT.value, IngestionCapability.POSITIONS.value)
                ),
            )
            .order_by(SourceRecordModel.id)
        ).all()
    if len(references) != 3:
        raise RuntimeError(
            "Synthetic anchor requires exactly two position records and its account record"
        )
    return tuple(str(value) for value in references)


def _coverage(values: tuple[tuple[d.HistoricalCoverageKey, int], ...]) -> d.HistoricalCoverage:
    return d.HistoricalCoverage(
        measures=tuple(
            d.HistoricalCoverageMeasure(
                key=key, expected_count=count, available_count=count, complete=True
            )
            for key, count in values
        )
    )


def history_anchor(
    scenario: SyntheticHistoryScenario,
    *,
    at: datetime,
    timing: Literal["before_events", "after_events"],
    refs: tuple[str, ...],
    label: str,
) -> d.HistoricalValuationAnchor:
    state = scenario.state(at, include_equal=timing == "after_events")
    quantities, costs = dict(state.quantities), dict(state.acquisition_costs)

    def money(
        amount: Decimal, currency: CurrencyCode, key: d.HistoricalCoverageKey
    ) -> d.HistoricalMoneyMetric:
        return d.HistoricalMoneyMetric(
            value=Money(amount, currency),
            availability=d.MetricAvailability.AVAILABLE,
            reason_code=None,
            quality=QualityState.FRESH,
            coverage_key=key,
            origin=d.HistoricalOrigin.PROVIDER,
        )

    with localcontext(HISTORY_CONTEXT):
        positions = tuple(
            d.HistoricalAnchorPosition(
                listing_id=str(item.listing.id),
                instrument_id=str(item.instrument.id),
                quantity=quantities[str(item.listing.trading_currency)],
                market_value=money(
                    quantities[str(item.listing.trading_currency)]
                    * scenario.price(str(item.listing.trading_currency), at.date()),
                    item.listing.trading_currency,
                    d.HistoricalCoverageKey.VALUATIONS,
                ),
                acquisition_cost=money(
                    costs[str(item.listing.trading_currency)],
                    item.listing.trading_currency,
                    d.HistoricalCoverageKey.COST,
                ),
            )
            for item in scenario.instruments
        )
    cash = tuple(
        Money(amount, CurrencyCode(currency)) for currency, amount in state.cash if amount != 0
    )
    measures: list[
        tuple[Literal["quantity", "cash", "cost"], str, CurrencyCode | None, Decimal]
    ] = [("quantity", row.listing_id, None, row.quantity) for row in positions]
    measures.extend(
        (
            "cost",
            row.listing_id,
            row.acquisition_cost.value.currency,
            row.acquisition_cost.value.amount,
        )
        for row in positions
        if row.acquisition_cost.value is not None
    )
    measures.extend(("cash", row.currency.value, row.currency, row.amount) for row in cash)
    lines = tuple(
        d.HistoricalReconciliationLine(
            kind=kind,
            identity=identity,
            currency=currency,
            expected=amount,
            observed=amount,
            residual=Decimal(0),
            tolerance=Decimal(0),
            state="reconciled",
        )
        for kind, identity, currency, amount in measures
    )
    coverage = _coverage(
        (
            (d.HistoricalCoverageKey.OPENING, 1),
            (d.HistoricalCoverageKey.QUANTITY, len(positions)),
            (d.HistoricalCoverageKey.CASH, len(cash)),
            (d.HistoricalCoverageKey.COST, len(positions)),
            (d.HistoricalCoverageKey.VALUATIONS, len(positions)),
        )
    )
    return d.HistoricalValuationAnchor(
        id=history_id(f"{scenario.variant}/anchor/{label}"),
        at=at,
        timing=timing,
        positions=positions,
        cash=cash,
        origin=d.HistoricalOrigin.PROVIDER,
        source_refs=refs,
        coverage=coverage,
        reconciliation=d.HistoricalReconciliationProof(
            policy_version="synthetic-source-conservation-1",
            anchor_refs=refs,
            lines=lines,
            outcome="reconciled",
        ),
    )


async def _register_evidence(
    sessions: sessionmaker[Session],
    scenario: SyntheticHistoryScenario,
    *,
    at: datetime,
    opening: d.HistoricalValuationAnchor,
    anchors: tuple[d.HistoricalValuationAnchor, ...],
) -> None:
    store = PostgresHistoricalStore(sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: at)
    classifications = tuple(
        d.HistoricalClassificationEvidence(
            id=history_id(
                f"{scenario.variant}/{item.listing.trading_currency}/{dimension}/classification"
            ),
            instrument_id=str(item.instrument.id),
            dimension="sector" if dimension == "sector" else "asset_class",
            taxonomy="synthetic-direct-classification",
            taxonomy_version="1",
            category=category,
            valid_from=scenario.opening_at,
            valid_to=None,
            first_observed_at=at,
            source_refs=(
                history_id(f"{scenario.variant}/{item.listing.trading_currency}/mapping"),
            ),
            license_version_id=history_id(f"{scenario.variant}/license"),
        )
        for item in scenario.instruments
        for dimension, category in (
            ("asset_class", "equity"),
            (
                "sector",
                "technology" if str(item.listing.trading_currency) == "EUR" else "industrials",
            ),
        )
    )
    evidence = HistoricalEvidenceRegistration(
        id=history_id(f"{scenario.variant}/evidence"),
        key=f"synthetic-history-{scenario.variant}-1",
        opening=d.ObservedHistoricalOpening(
            anchor=opening,
            bridge_coverage=_coverage(
                (
                    (d.HistoricalCoverageKey.OPENING, 1),
                    (d.HistoricalCoverageKey.QUANTITY, 2),
                    (d.HistoricalCoverageKey.CASH, 1),
                    (d.HistoricalCoverageKey.COST, 2),
                    (d.HistoricalCoverageKey.EVENTS, 0),
                )
            ),
        ),
        valuation_anchors=anchors,
        classifications=classifications,
    )
    await store.register_historical_evidence(
        history_principal(at),
        str(scenario.account.id),
        evidence,
        idempotency_key=f"history-{scenario.variant}:evidence-v1",
        correlation_id="synthetic-historical-evidence",
    )


async def seed_historical_scenarios(
    sessions: sessionmaker[Session], *, app_environment: str
) -> dict[str, str]:
    if app_environment not in {"local", "test"}:
        raise RuntimeError("synthetic historical seed is restricted to local/test environments")
    result = {}
    for variant in ("annual", "point_in_time"):
        scenario = build_history_scenario(variant)
        _seed_identity(sessions, scenario)
        configured_at = HISTORY_RECEIPT if variant == "annual" else scenario.opening_at
        sources = PostgresSourceService(
            sessions=sessions, cursor_signing_key=CURSOR_KEY, clock=fixed_clock(configured_at)
        )
        series, benchmark_id = await register_historical_sources(
            sources, history_principal(configured_at), scenario
        )
        target_id = await seed_historical_target(
            sessions, history_principal(configured_at), scenario, configured_at
        )
        calendar = historical_calendar(scenario)
        policy = HistoricalPolicyRegistration(
            id=history_id(f"{variant}/policy"),
            key=f"synthetic-history-{variant}-1",
            effective_at=scenario.opening_at,
            accounting_policy=d.HistoricalAccountingPolicy(annual_session_factor=365),
            source_policy=SourceSelectionPolicy(
                version="history-prior-complete-close-1",
                provider_priority=(history_id(f"{variant}/provider"),),
                max_age_seconds=86400,
                allow_closed_session_carry=True,
            ),
            reporting_calendar_ref=d.CalendarRef(id=calendar.id, version=calendar.version),
            price_series_ids=tuple(
                value.id for value in series if value.kind is SourceSeriesKind.SECURITY_PRICE
            ),
            action_series_ids=tuple(
                value.id for value in series if value.kind is SourceSeriesKind.SECURITY_PRICE
            ),
        )
        await PostgresHistoricalStore(
            sessions, cursor_signing_key=CURSOR_KEY, clock=fixed_clock(configured_at)
        ).register_historical_policy(
            history_principal(configured_at),
            str(scenario.account.id),
            policy,
            idempotency_key=f"history-{variant}:policy-v1",
            correlation_id="synthetic-historical-policy",
        )
        received_at = configured_at + (
            timedelta(seconds=1) if variant == "annual" else timedelta(0)
        )
        opening_refs = await _observe(
            sessions,
            scenario,
            economic_at=scenario.opening_at,
            received_at=received_at,
            label="opening",
        )
        opening = history_anchor(
            scenario,
            at=scenario.opening_at,
            timing="after_events",
            refs=opening_refs,
            label="opening",
        )
        anchors = []
        if variant == "annual":
            for event in scenario.activities:
                if event.kind not in ("deposit", "withdrawal"):
                    continue
                for timing in ("before_events", "after_events"):
                    received_at += timedelta(minutes=1)
                    label = f"{event.key}-{timing}"
                    refs = await _observe(
                        sessions,
                        scenario,
                        economic_at=event.at,
                        received_at=received_at,
                        include_equal=timing == "after_events",
                        label=label,
                    )
                    anchors.append(
                        history_anchor(scenario, at=event.at, timing=timing, refs=refs, label=label)
                    )
            received_at += timedelta(minutes=1)
            await _observe(
                sessions,
                scenario,
                economic_at=datetime.combine(
                    scenario.end + timedelta(days=1), time.min, tzinfo=UTC
                ),
                received_at=received_at,
                label="closing",
            )
            await _register_evidence(
                sessions,
                scenario,
                at=received_at + timedelta(seconds=1),
                opening=opening,
                anchors=tuple(anchors),
            )
            source_at = received_at + timedelta(minutes=1)
            await ingest_historical_reference_batch(
                PostgresSourceService(
                    sessions=sessions, cursor_signing_key=CURSOR_KEY, clock=fixed_clock(source_at)
                ),
                history_principal(source_at),
                scenario,
                series,
                period=SourcePeriod(start=scenario.start, end=scenario.end),
                at=source_at,
            )
        else:
            await _register_evidence(
                sessions,
                scenario,
                at=received_at,
                opening=opening,
                anchors=(),
            )
            for day in scenario.sessions:
                source_at = close_at(day)
                if day != scenario.start:
                    await _observe(
                        sessions,
                        scenario,
                        economic_at=close_at(day),
                        received_at=source_at,
                        label=f"day-{day}",
                    )
                await ingest_historical_reference_batch(
                    PostgresSourceService(
                        sessions=sessions,
                        cursor_signing_key=CURSOR_KEY,
                        clock=fixed_clock(source_at),
                    ),
                    history_principal(source_at),
                    scenario,
                    series,
                    period=SourcePeriod(start=day, end=day),
                    at=source_at,
                )
                boundary = datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC)
                await _observe(
                    sessions,
                    scenario,
                    economic_at=boundary,
                    received_at=boundary,
                    label=f"boundary-{day}",
                )
        result[f"{variant}_account_id"] = str(scenario.account.id)
        result[f"{variant}_benchmark_version_id"] = benchmark_id
        result[f"{variant}_target_version_id"] = target_id
    return result
