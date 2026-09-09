"""Typed synthetic adapter fixtures; financial evidence belongs to calculator tests."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from trading212_application import xray as app
from trading212_application.views import Page
from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.values import CurrencyCode, Money
from trading212_domain.xray import (
    XrayAvailability,
    XrayBound,
    XrayDimension,
    XrayMoneyMetric,
    XrayRatioMetric,
)
from trading212_domain.xray_result import (
    XrayDimensionSummary,
    XrayPortfolioSummary,
    XrayQualityCoverage,
)

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
ACCOUNT = str(UUID(int=1))
SNAPSHOT = str(UUID(int=2))
RUN = str(UUID(int=3))
QUERY = {
    "snapshot_id": SNAPSHOT,
    "source_cutoff_at": "2026-09-07T12:00:00Z",
    "reporting_currency": "EUR",
}


def ratio(value: str = "0", *, refs: tuple[UUID, ...] = ()) -> XrayRatioMetric:
    return XrayRatioMetric(
        value=Decimal(value),
        reason=None,
        quality=QualityState.FRESH,
        bound=XrayBound.EXACT,
        availability=XrayAvailability.AVAILABLE,
        confidence=None,
        source_reference_ids=refs,
    )


def money(value: str = "0", *, refs: tuple[UUID, ...] = ()) -> XrayMoneyMetric:
    return XrayMoneyMetric(
        value=Money.parse(value, "EUR"),
        reason=None,
        quality=QualityState.FRESH,
        origin=ValueOrigin.DERIVED_DETERMINISTIC,
        bound=XrayBound.EXACT,
        availability=XrayAvailability.AVAILABLE,
        confidence=None,
        source_reference_ids=refs,
    )


def context() -> app.XrayContext:
    return app.XrayContext(
        account_id=ACCOUNT,
        snapshot_id=SNAPSHOT,
        run_id=RUN,
        input_snapshot_id=str(UUID(int=4)),
        input_digest="a" * 64,
        content_digest="b" * 64,
        valuation_at=NOW,
        source_cutoff_at=NOW,
        reporting_currency=CurrencyCode("EUR"),
        calculated_at=NOW,
        quality_evaluated_at=NOW,
        method=app.XrayMethodView(),
        policies=(),
        sources=(),
        source_count=0,
        source_omitted_count=0,
        warnings=(),
        warning_count=0,
        warning_omitted_count=0,
        residuals=(),
        residual_count=0,
        residual_omitted_count=0,
    )


def summary() -> XrayPortfolioSummary:
    return XrayPortfolioSummary(
        total=money("100"),
        company_known_weight=ratio("1"),
        cash_weight=ratio(),
        unresolved_weight=ratio(),
        duplicated_exposure=ratio(),
        top_concentrations=(),
        hhi=ratio("1"),
        thresholds=(),
        quality_coverage=XrayQualityCoverage(
            root_count=1,
            valued_root_count=1,
            direct_portfolio_value=money("100"),
            direct_portfolio_weight=ratio("1"),
            inferred_mapping_count=0,
            inferred_value=money(),
            inferred_weight=ratio(),
            stale_value=money(),
            stale_weight=ratio(),
        ),
    )


def exposures() -> app.ExposuresView:
    return app.ExposuresView(
        context=context(),
        summary=summary(),
        dimension_summary=XrayDimensionSummary(
            dimension=XrayDimension.COMPANY,
            known=money("100"),
            cash=money(),
            unresolved=money(),
            known_weight=ratio("1"),
            cash_weight=ratio(),
            unresolved_weight=ratio(),
            complete=True,
            positive_unresolved_below_quantum=False,
        ),
        dimension_residuals=(),
        normalized_known_only=False,
        exposures=Page(items=(), next_cursor=None, limit=25, total=0),
    )


def pairs() -> app.OverlapPairsView:
    return app.OverlapPairsView(
        context=context(),
        summary=summary(),
        selected_fund_ids=(str(UUID(int=5)), str(UUID(int=6))),
        pairs=Page(items=(), next_cursor=None, limit=25, total=0),
    )
