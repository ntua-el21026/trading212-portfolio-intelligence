"""Safe, deterministic adapters from canonical application views to MCP schemas."""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal

from trading212_application.views import (
    AccountView,
    ActivityView,
    AllocationView,
    DividendView,
    MetricView,
    PositionView,
    QualityView,
    ReconciliationIssueView,
    SnapshotComparisonView,
    SnapshotView,
)
from trading212_domain.values import decimal_string

from .schemas import (
    Account,
    ActivityRow,
    AllocationRow,
    DataQuality,
    DividendRow,
    Metric,
    PositionRow,
    ReconciliationIssue,
    SnapshotComparisonData,
    SnapshotCore,
)

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def safe_text(value: object, *, maximum: int) -> str:
    """Bound provider-derived text and remove non-printing control characters."""
    return _CONTROL_CHARACTERS.sub("", str(value)).strip()[:maximum]


def safe_strings(values: Iterable[object], *, maximum: int, count: int = 20) -> list[str]:
    return [safe_text(value, maximum=maximum) for value in list(values)[:count]]


def quality(value: QualityView, *, extra_warnings: Iterable[str] = ()) -> DataQuality:
    warnings = [*value.warnings, *extra_warnings]
    return DataQuality(
        state=value.state.value,
        warnings=safe_strings(warnings, maximum=240),
        missing_inputs=safe_strings(value.missing_inputs, maximum=120),
        source_cutoff_at=value.source_timestamp,
        freshness_threshold_seconds=value.freshness_threshold_seconds,
    )


def metric(value: MetricView) -> Metric:
    return Metric(
        value=decimal_string(value.value) if value.value is not None else None,
        reporting_currency=value.currency,
        availability=value.availability.value,
        calculation_version=safe_text(value.calculation_version, maximum=120),
        methodology=safe_text(value.methodology, maximum=240),
        provenance=safe_strings(value.provenance, maximum=120),
        assumptions=safe_strings(value.assumptions, maximum=240),
        unavailable_reason=(
            safe_text(value.unavailable_reason, maximum=240)
            if value.unavailable_reason is not None
            else None
        ),
    )


def account(value: AccountView) -> Account:
    return Account(
        id=safe_text(value.id, maximum=255),
        display_name=safe_text(value.display_name, maximum=120),
        provider=safe_text(value.provider, maximum=40),
        environment=safe_text(value.environment, maximum=40),
        account_type=safe_text(value.account_type, maximum=40),
        reporting_currency=value.reporting_currency,
        connection_state=safe_text(value.connection_state, maximum=80),
        last_refresh_at=value.last_refresh_at,
    )


def position(value: PositionView) -> PositionRow:
    return PositionRow(
        id=safe_text(value.id, maximum=255),
        ticker=safe_text(value.ticker, maximum=40),
        name=safe_text(value.name, maximum=160),
        instrument_type=safe_text(value.instrument_type, maximum=40),
        quantity=decimal_string(value.quantity) if value.quantity is not None else None,
        trading_currency=value.trading_currency,
        current_price=(
            decimal_string(value.current_price) if value.current_price is not None else None
        ),
        market_value=metric(value.market_value),
        provider_cost_basis=metric(value.provider_cost_basis),
        provider_unrealized_profit_loss=metric(value.provider_unrealized_profit_loss),
        direct_weight=(
            decimal_string(value.direct_weight) if value.direct_weight is not None else None
        ),
        data_quality=quality(value.quality),
    )


def activity(value: ActivityView) -> ActivityRow:
    return ActivityRow(
        id=safe_text(value.id, maximum=255),
        occurred_at=value.occurred_at,
        activity_type=safe_text(value.activity_type, maximum=80),
        direction=safe_text(value.direction, maximum=80),
        amount=metric(value.amount),
        ticker=safe_text(value.ticker, maximum=40) if value.ticker is not None else None,
        quantity=decimal_string(value.quantity) if value.quantity is not None else None,
        description=safe_text(value.description, maximum=240),
        data_quality=quality(value.quality),
    )


def dividend(value: DividendView) -> DividendRow:
    return DividendRow(
        id=safe_text(value.id, maximum=255),
        paid_on=value.paid_on,
        ticker=safe_text(value.ticker, maximum=40),
        net_amount=metric(value.net_amount),
        gross_amount=metric(value.gross_amount),
        withholding_tax=metric(value.withholding_tax),
        quantity=decimal_string(value.quantity) if value.quantity is not None else None,
        data_quality=quality(value.quality),
    )


def allocation(value: AllocationView) -> AllocationRow:
    return AllocationRow(
        id=safe_text(value.id, maximum=255),
        label=safe_text(value.label, maximum=160),
        asset_type=safe_text(value.asset_type, maximum=40),
        market_value=metric(value.market_value),
        weight=decimal_string(value.weight) if value.weight is not None else None,
        weight_availability=value.weight_availability.value,
    )


def snapshot(value: SnapshotView) -> SnapshotCore:
    return SnapshotCore(
        id=safe_text(value.id, maximum=255),
        valuation_at=value.valuation_at,
        source_cutoff_at=value.source_cutoff_at,
        reporting_currency=value.reporting_currency,
        total_value=metric(value.total_value),
        cash_value=metric(value.cash_value),
        invested_value=metric(value.invested_value),
        net_contributions=metric(value.net_contributions),
        data_quality=quality(value.quality),
    )


def snapshot_comparison(value: SnapshotComparisonView) -> SnapshotComparisonData:
    return SnapshotComparisonData(
        start=snapshot(value.start),
        end=snapshot(value.end),
        value_change=metric(value.value_change),
        net_external_flows=metric(value.net_external_flows),
        investment_result=metric(value.investment_result),
        reconciliation_residual=metric(value.reconciliation_residual),
    )


def reconciliation_issue(value: ReconciliationIssueView) -> ReconciliationIssue:
    return ReconciliationIssue(
        id=safe_text(value.id, maximum=255),
        issue_type=safe_text(value.issue_type, maximum=80),
        severity=safe_text(value.severity, maximum=40),
        status=safe_text(value.status, maximum=40),
        summary=safe_text(value.summary, maximum=240),
        expected_value=_decimal(value.expected_value),
        observed_value=_decimal(value.observed_value),
        residual=_decimal(value.residual),
        tolerance=_decimal(value.tolerance),
        currency=value.currency,
    )


def _decimal(value: Decimal | None) -> str | None:
    return decimal_string(value) if value is not None else None
