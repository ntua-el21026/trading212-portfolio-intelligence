"""Complete canonical synthetic histories exercise all five persisted financial families."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import historical as app
from trading212_domain import build_synthetic_identity
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.values import CurrencyCode
from trading212_persistence.base import Base
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_persistence.models import PortfolioSnapshotModel
from trading212_worker.historical_seed import (
    CURSOR_KEY,
    history_principal,
    seed_historical_scenarios,
)

from tests.integration.test_historical_postgres import historical_database as historical_database

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 8, 0, tzinfo=UTC)


def counts(sessions: sessionmaker[Session]) -> dict[str, int]:
    with sessions() as session:
        return {
            table.name: session.scalar(select(func.count()).select_from(table)) or 0
            for table in Base.metadata.tables.values()
        }


@pytest.fixture(scope="module")
def seeded_history(
    historical_database: tuple[Engine, sessionmaker[Session]],
) -> tuple[sessionmaker[Session], dict[str, str]]:
    _, sessions = historical_database
    result = asyncio.run(seed_historical_scenarios(sessions, app_environment="test"))
    before = counts(sessions)
    assert asyncio.run(seed_historical_scenarios(sessions, app_environment="test")) == result
    assert counts(sessions) == before
    with sessions() as session:
        original = session.scalar(
            select(PortfolioSnapshotModel)
            .where(
                PortfolioSnapshotModel.broker_account_id == build_synthetic_identity().account.id
            )
            .order_by(PortfolioSnapshotModel.valuation_at.desc())
            .limit(1)
        )
        assert original is not None and original.portfolio_total == Decimal("248431.27")
    return sessions, result


def window(variant: str) -> d.HistoricalWindow:
    return d.HistoricalWindow(
        start_date=date(2025, 1, 1) if variant == "annual" else date(2026, 8, 2),
        end_date=date(2025, 12, 31) if variant == "annual" else date(2026, 8, 22),
        source_cutoff_at=NOW,
        reporting_currency=CurrencyCode("EUR"),
        knowledge_policy=d.KnowledgePolicy.AS_OF_CUTOFF
        if variant == "annual"
        else d.KnowledgePolicy.POINT_IN_TIME,
    )


@pytest.mark.parametrize(
    "variant, beginning, ending, gain",
    [
        ("annual", "1872.4697", "2191.280575", "218.810875"),
        ("point_in_time", "1680", "1690.019075", "10.019075"),
    ],
)
def test_seeded_performance_has_exact_conservation_and_retained_replay(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]],
    variant: str,
    beginning: str,
    ending: str,
    gain: str,
) -> None:
    sessions, ids = seeded_history
    service = PostgresHistoricalService(sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW)
    query = app.PerformanceSummaryQuery(
        window=window(variant), options=r.PerformanceOptions(frequency=d.HistoricalFrequency.DAILY)
    )
    result = asyncio.run(
        service.get_performance_summary(
            history_principal(NOW), ids[f"{variant}_account_id"], query=query
        )
    )
    for metric, amount in (
        (result.summary.beginning_value, beginning),
        (result.summary.ending_value, ending),
        (result.summary.investment_gain, gain),
    ):
        assert metric.availability is d.MetricAvailability.AVAILABLE
        assert metric.value is not None and metric.value.amount == Decimal(amount)
    assert result.summary.time_weighted_return.value is not None
    assert result.summary.modified_dietz_return.value is not None
    assert len(result.series) == (365 if variant == "annual" else 21)
    before = counts(sessions)
    later = NOW + timedelta(hours=1)
    replay = asyncio.run(
        PostgresHistoricalService(
            sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: later
        ).get_performance_summary(
            history_principal(later),
            ids[f"{variant}_account_id"],
            query=replace(query, input_snapshot_id=result.context.input_snapshot_id),
        )
    )
    assert replay.summary == result.summary and replay.series == result.series
    assert replay.context.content_digest == result.context.content_digest
    assert replay.context.calculated_at == result.context.calculated_at
    assert counts(sessions) == before


@pytest.mark.parametrize("variant", ["annual", "point_in_time"])
def test_seeded_income_uses_prior_coverage_native_currencies_and_zero_values(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]], variant: str
) -> None:
    sessions, ids = seeded_history
    service = PostgresHistoricalService(sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW)
    result = asyncio.run(
        service.get_dividend_intelligence(
            history_principal(NOW),
            ids[f"{variant}_account_id"],
            query=app.DividendIntelligenceQuery(window=window(variant)),
        )
    )
    assert result.summary.net_income.value is not None
    assert result.summary.net_income.value.amount == (
        Decimal("32.555") if variant == "annual" else Decimal(0)
    )
    assert result.summary.income_yield.value is not None
    if variant == "annual":
        assert result.summary.previous_period_income.value is not None
        assert result.summary.previous_period_income.value.amount == Decimal("20")
        assert result.summary.dividend_growth.value == Decimal("0.62775")
        assert {
            str(row.currency): row.net.value.amount
            for row in result.native_currency_totals
            if row.net.value is not None
        } == {"EUR": Decimal("28"), "USD": Decimal("5")}
    else:
        assert result.summary.income_yield.value == 0
        assert result.summary.previous_period_income.value is None


@pytest.mark.parametrize("variant", ["annual", "point_in_time"])
def test_seeded_benchmark_attribution_and_cash_flow_families_are_available(
    seeded_history: tuple[sessionmaker[Session], dict[str, str]], variant: str
) -> None:
    sessions, ids = seeded_history
    service = PostgresHistoricalService(sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: NOW)
    principal, account, period = (
        history_principal(NOW),
        ids[f"{variant}_account_id"],
        window(variant),
    )
    benchmark = asyncio.run(
        service.get_benchmark_comparison(
            principal,
            account,
            query=app.BenchmarkComparisonQuery(
                window=period, benchmark_version_id=ids[f"{variant}_benchmark_version_id"]
            ),
        )
    )
    assert benchmark.composite_snapshot is not None
    assert benchmark.summary.benchmark_return.value is not None
    assert benchmark.summary.tracking_error.value is not None
    assert benchmark.summary.paired_observation_count >= 20
    attribution = asyncio.run(
        service.get_attribution_summary(
            principal,
            account,
            query=app.AttributionQuery(
                window=period,
                options=r.AttributionOptions(grouping=d.HistoricalGrouping.GROUP),
                target_version_id=ids[f"{variant}_target_version_id"],
                grouping_policy="explicit_comparison",
                benchmark_version_id=ids[f"{variant}_benchmark_version_id"],
            ),
        )
    )
    assert attribution.summary.investment_gain.value is not None
    assert attribution.summary.residual.value is not None
    assert attribution.summary.residual.value.amount == 0
    assert attribution.summary.cash_drag.value is not None
    assert attribution.rows
    cash = asyncio.run(
        service.get_cash_flow_intelligence(
            principal, account, query=app.CashFlowIntelligenceQuery(window=period, limit=5)
        )
    )
    assert cash.summary.unresolved_count == 0
    assert cash.summary.event_count == (9 if variant == "annual" else 0)
    if variant == "annual":
        assert cash.events.next_cursor is not None
        continuation = asyncio.run(
            service.get_cash_flow_intelligence(
                principal,
                account,
                query=app.CashFlowIntelligenceQuery(
                    window=period,
                    limit=5,
                    input_snapshot_id=cash.context.input_snapshot_id,
                    cursor=cash.events.next_cursor,
                ),
            )
        )
        assert len(cash.events.items) + len(continuation.events.items) == 9
        assert set(row.event_revision_id for row in cash.events.items).isdisjoint(
            row.event_revision_id for row in continuation.events.items
        )
