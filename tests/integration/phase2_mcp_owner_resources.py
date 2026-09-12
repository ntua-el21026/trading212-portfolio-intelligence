"""Canonical targets, durable plans and private benchmark definitions for two owners."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from trading212_analytics.planning import calculate_contribution_plan
from trading212_application import planning as pa
from trading212_application import sources as sa
from trading212_application import targets as ta
from trading212_application.planning_jobs import PlanTaskMessage
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.source_providers import SourceCapability
from trading212_domain import build_synthetic_identity
from trading212_domain import planning as pd
from trading212_domain import sources as sd
from trading212_domain import targets as td
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence import PostgresPlanningService, PostgresTargetService
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_persistence.models import InstrumentModel, ListingModel
from trading212_persistence.source_service import PostgresSourceService

from tests.integration.phase2_authorization_cases import KEY, AccountPin, Actor, OwnerGrid


@dataclass(frozen=True)
class TargetPin:
    portfolio: ta.VirtualPortfolioView
    version: ta.TargetVersionView


@dataclass(frozen=True)
class PlanningPin:
    pin: AccountPin
    target: TargetPin
    job: pa.ContributionPlanJobView


@dataclass(frozen=True)
class IntelligenceOwners:
    grid: OwnerGrid
    targets: PostgresTargetService
    planning: PostgresPlanningService
    history: PostgresHistoricalService
    plans: dict[UUID, PlanningPin]
    templates: dict[str, tuple[TargetPin, TargetPin]]
    benchmarks: dict[str, str]


async def publish_target(
    grid: OwnerGrid,
    service: PostgresTargetService,
    actor: Actor,
    account: UUID | None,
) -> TargetPin:
    identity = build_synthetic_identity()
    additional_instrument_id, additional_listing_id = uuid4(), uuid4()
    # Two resolved holdings give limit=1 a real second allocation line to page.
    with grid.sessions() as session, session.begin():
        session.add(
            InstrumentModel(
                id=additional_instrument_id,
                canonical_name="Synthetic additional holding",
                instrument_type="equity",
            )
        )
        session.flush()
        session.add(
            ListingModel(
                id=additional_listing_id,
                instrument_id=additional_instrument_id,
                provider="synthetic",
                environment="synthetic",
                provider_instrument_id=str(additional_listing_id),
                ticker="SYNADD",
                trading_currency="EUR",
                status="active",
                valid_from=grid.at - timedelta(days=1),
            )
        )
    portfolio = await service.create_virtual_portfolio(
        actor.principal,
        ta.CreateVirtualPortfolioCommand(
            "Private owner target " + uuid4().hex[:8],
            CurrencyCode("EUR"),
            None if account is None else str(account),
        ),
        idempotency_key=uuid4().hex,
        correlation_id="p210-mcp-owner",
    )
    content = td.TargetContent(
        (
            td.TargetNode("group", None, td.TargetNodeKind.GROUP, "Equities", 0, Decimal("0.8")),
            td.TargetNode(
                "holding",
                "group",
                td.TargetNodeKind.HOLDING,
                "Synthetic holding",
                0,
                Decimal("0.5"),
                td.TargetHoldingMapping(
                    td.TargetMappingState.RESOLVED,
                    identity.instrument.id,
                    identity.listing.id,
                ),
            ),
            td.TargetNode(
                "additional-holding",
                "group",
                td.TargetNodeKind.HOLDING,
                "Synthetic additional holding",
                1,
                Decimal("0.5"),
                td.TargetHoldingMapping(
                    td.TargetMappingState.RESOLVED,
                    additional_instrument_id,
                    additional_listing_id,
                ),
            ),
            td.TargetNode("cash", None, td.TargetNodeKind.CASH, "Cash", 1, Decimal("0.2")),
        )
    )
    version = await service.create_target_version(
        actor.principal,
        portfolio.id,
        ta.CreateTargetVersionCommand(grid.at - timedelta(days=1), content=content),
        if_match=portfolio.etag,
        idempotency_key=uuid4().hex,
        correlation_id="p210-mcp-owner",
    )
    validation = await service.validate_target_version(
        actor.principal,
        version.id,
        ta.ValidateTargetCommand(),
        if_match=version.etag,
        idempotency_key=uuid4().hex,
        correlation_id="p210-mcp-owner",
    )
    assert validation.valid
    published = await service.publish_target_version(
        actor.principal,
        version.id,
        ta.PublishTargetCommand(validation.id),
        if_match=validation.etag,
        idempotency_key=uuid4().hex,
        correlation_id="p210-mcp-owner",
    )
    return TargetPin(portfolio, published)


async def benchmark(
    grid: OwnerGrid,
    source: PostgresSourceService,
    actor: Actor,
) -> str:
    provider, license_id, series_id = (str(uuid4()) for _ in range(3))
    await source.configure_source_provider(
        actor.principal,
        SourceProviderRegistration(
            id=provider,
            key="p210-owner-benchmark",
            name="Synthetic private benchmark",
            adapter_version="p210-replay-v1",
            configuration_state=sa.ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(SourceCapability.BENCHMARK_SERIES,),
            supported_price_bases=(sd.PriceBasis.TOTAL_RETURN,),
        ),
        idempotency_key=uuid4().hex,
        correlation_id="p210-mcp-owner",
    )
    license = sd.SourceLicense(
        id=license_id,
        provider_id=provider,
        version="v1",
        effective_at=grid.at - timedelta(days=1),
        store=sd.LicensePermission.ALLOWED,
        display=sd.LicensePermission.ALLOWED,
        report=sd.LicensePermission.ALLOWED,
        export=sd.LicensePermission.ALLOWED,
        retention_days=365,
        attribution="Synthetic private benchmark only.",
        evidence_key="p210-synthetic-license",
    )
    await source.register_source_license(
        actor.principal,
        license,
        idempotency_key=uuid4().hex,
        correlation_id="p210-mcp-owner",
    )
    calendar = sd.SourceCalendar(
        id="p210-owner-calendar",
        version="v1",
        timezone="UTC",
        period=sd.SourcePeriod(start=grid.at.date(), end=grid.at.date()),
        sessions=(sd.MarketSession(session_date=grid.at.date(), close_at=grid.at),),
    )
    await source.register_source_calendar(
        actor.principal,
        calendar,
        idempotency_key=uuid4().hex,
        correlation_id="p210-mcp-owner",
    )
    await source.register_source_series(
        actor.principal,
        sd.SourceSeries(
            id=series_id,
            owner_id=actor.principal.owner_id,
            provider_id=provider,
            license_version_id=license.id,
            kind=sd.SourceSeriesKind.BENCHMARK_LEVEL,
            provider_key="p210-owner-benchmark",
            mapping_version="v1",
            basis=sd.PriceBasis.TOTAL_RETURN,
            currency=CurrencyCode("EUR"),
            calendar_id=calendar.id,
            calendar_version=calendar.version,
        ),
        idempotency_key=uuid4().hex,
        correlation_id="p210-mcp-owner",
    )
    created = await source.create_benchmark_definition(
        actor.principal,
        sa.CreateBenchmarkDefinitionCommand(
            name="Private benchmark " + uuid4().hex[:8],
            content=sd.BenchmarkContent(
                reporting_currency=CurrencyCode("EUR"),
                effective_at=grid.at,
                return_basis=sd.PriceBasis.TOTAL_RETURN,
                calendar_id=calendar.id,
                calendar_version=calendar.version,
                rebalance_rule=sd.BenchmarkRebalanceRule.BUY_AND_HOLD,
                components=(sd.BenchmarkComponent(source_id=series_id, weight=Decimal("1")),),
            ),
        ),
        idempotency_key=uuid4().hex,
        correlation_id="p210-mcp-owner",
    )
    assert created.selected_version is not None
    return created.selected_version.id


@pytest.fixture(scope="module")
def intelligence_owners(owner_grid: OwnerGrid) -> IntelligenceOwners:
    grid = owner_grid
    targets = PostgresTargetService(
        sessions=grid.sessions, cursor_signing_key=KEY, clock=lambda: grid.at
    )
    planning = PostgresPlanningService(
        sessions=grid.sessions,
        cursor_signing_key=KEY,
        clock=lambda: grid.at,
    )
    source = PostgresSourceService(
        sessions=grid.sessions, cursor_signing_key=KEY, clock=lambda: grid.at
    )
    history = PostgresHistoricalService(
        grid.sessions, cursor_signing_key=KEY, clock=lambda: grid.at
    )

    async def prepare() -> IntelligenceOwners:
        plans: dict[UUID, PlanningPin] = {}
        templates: dict[str, tuple[TargetPin, TargetPin]] = {}
        benchmarks: dict[str, str] = {}
        for actor in grid.actors:
            templates[actor.principal.owner_id] = (
                await publish_target(grid, targets, actor, None),
                await publish_target(grid, targets, actor, None),
            )
            benchmarks[actor.principal.owner_id] = await benchmark(grid, source, actor)
            for pin in actor.accounts:
                target = await publish_target(grid, targets, actor, pin.account_id)
                job = await planning.create_contribution_plan(
                    actor.principal,
                    pa.CreateContributionPlanCommand(
                        account_id=str(pin.account_id),
                        snapshot_id=str(pin.snapshot_id),
                        virtual_portfolio_id=target.portfolio.id,
                        target_version_id=target.version.id,
                        options=pd.PlanningOptions(
                            Money(Decimal("20"), CurrencyCode("EUR")),
                            pd.PlanningMode.GLOBAL,
                            pd.CoveragePolicy.ALLOW_DEGRADED,
                        ),
                    ),
                    idempotency_key=uuid4().hex,
                    correlation_id="p210-mcp-owner",
                )
                message = PlanTaskMessage(
                    job.job_id,
                    job.request_id,
                    actor.principal.owner_id,
                    job.account_id,
                    job.input_digest,
                )
                claim = await planning.claim_plan_job(message, consumer_id="p210-owner-fixture")
                assert claim is not None
                value = await planning.load_plan_job_input(claim)
                calculated = calculate_contribution_plan(value)
                assert len(calculated.lines) == 2
                assert await planning.complete_plan_job(claim, calculated)
                plans[pin.account_id] = PlanningPin(pin, target, job)
        return IntelligenceOwners(grid, targets, planning, history, plans, templates, benchmarks)

    return asyncio.run(prepare())
