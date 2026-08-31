"""Versioned quantity, cash, and value reconciliation bridges."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trading212_domain import (
    BrokerAccountId,
    CurrencyCode,
    DiscrepancySeverity,
    DiscrepancyType,
    DomainError,
    DomainWarning,
    ErrorCode,
    ListingId,
    Money,
    QualityState,
    Quantity,
    ReconciliationStatus,
    exact_decimal,
)

from ._decimal import persisted_decimal, subtract, total
from .quality import combine_quality, degrade_quality

RECONCILIATION_METHOD_ID = "quantity_cash_value_bridges"
RECONCILIATION_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class TolerancePolicy:
    """Absolute comparison tolerances; source identity remains exact elsewhere."""

    version: str
    quantity_absolute: Decimal
    money_absolute: Decimal
    value_absolute: Decimal

    def __post_init__(self) -> None:
        for field_name in ("quantity_absolute", "money_absolute", "value_absolute"):
            value = exact_decimal(getattr(self, field_name), field=field_name)
            if value < 0:
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    f"{field_name} must not be negative",
                    field_name,
                )
            object.__setattr__(self, field_name, value)
        if not self.version:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "tolerance version is required",
                "version",
            )


TOLERANCE_POLICY_V1 = TolerancePolicy(
    version="v1",
    quantity_absolute=Decimal("0.00000001"),
    money_absolute=Decimal("0.01"),
    value_absolute=Decimal("0.01"),
)


@dataclass(frozen=True, slots=True)
class QuantityBridgeInput:
    account_id: BrokerAccountId
    listing_id: ListingId
    opening_quantity: Quantity
    closing_quantity: Quantity | None
    buys: tuple[Quantity, ...] = ()
    sells: tuple[Quantity, ...] = ()
    transfers_in: tuple[Quantity, ...] = ()
    transfers_out: tuple[Quantity, ...] = ()
    corporate_additions: tuple[Quantity, ...] = ()
    corporate_removals: tuple[Quantity, ...] = ()
    coverage_complete: bool = True
    unsupported_activity: bool = False
    quality_state: QualityState = QualityState.FRESH

    def __post_init__(self) -> None:
        values = (
            self.opening_quantity,
            *(self.buys),
            *(self.sells),
            *(self.transfers_in),
            *(self.transfers_out),
            *(self.corporate_additions),
            *(self.corporate_removals),
        )
        if any(item.value < 0 for item in values):
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "quantity bridge movement magnitudes must not be negative",
                "quantity",
            )
        if self.closing_quantity is not None and self.closing_quantity.value < 0:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "observed closing quantity must not be negative",
                "closing_quantity",
            )


@dataclass(frozen=True, slots=True)
class CashBridgeInput:
    account_id: BrokerAccountId
    opening_cash: Money
    closing_cash: Money | None
    deposits: tuple[Money, ...] = ()
    withdrawals: tuple[Money, ...] = ()
    buy_outflows: tuple[Money, ...] = ()
    sell_inflows: tuple[Money, ...] = ()
    dividends: tuple[Money, ...] = ()
    interest: tuple[Money, ...] = ()
    fees: tuple[Money, ...] = ()
    taxes: tuple[Money, ...] = ()
    signed_adjustments: tuple[Money, ...] = ()
    coverage_complete: bool = True
    unsupported_activity: bool = False
    quality_state: QualityState = QualityState.FRESH

    def __post_init__(self) -> None:
        unsigned_groups = (
            self.deposits,
            self.withdrawals,
            self.buy_outflows,
            self.sell_inflows,
            self.dividends,
            self.interest,
            self.fees,
            self.taxes,
        )
        all_values = tuple(item for group in unsigned_groups for item in group) + tuple(
            self.signed_adjustments
        )
        if self.closing_cash is not None:
            all_values += (self.closing_cash,)
        if any(item.currency != self.opening_cash.currency for item in all_values):
            raise DomainError(
                ErrorCode.CURRENCY_MISMATCH,
                "cash bridge values must use one currency",
                "currency",
            )
        if any(item.amount < 0 for group in unsigned_groups for item in group):
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "cash bridge movement magnitudes must not be negative",
                "amount",
            )


@dataclass(frozen=True, slots=True)
class ValueBridgeInput:
    account_id: BrokerAccountId
    canonical_total: Money
    provider_total: Money | None
    quality_state: QualityState = QualityState.FRESH
    comparable_valuation: bool = True

    def __post_init__(self) -> None:
        if (
            self.provider_total is not None
            and self.provider_total.currency != self.canonical_total.currency
        ):
            raise DomainError(
                ErrorCode.CURRENCY_MISMATCH,
                "value bridge totals must use one currency",
                "currency",
            )


@dataclass(frozen=True, slots=True)
class ReconciliationCheck:
    discrepancy_type: DiscrepancyType
    scope: str
    expected: Decimal
    observed: Decimal | None
    residual: Decimal | None
    tolerance: Decimal
    within_tolerance: bool | None
    currency: CurrencyCode | None = None
    listing_id: ListingId | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationIssue:
    discrepancy_type: DiscrepancyType
    severity: DiscrepancySeverity
    scope: str
    expected: Decimal | None
    observed: Decimal | None
    residual: Decimal | None
    tolerance: Decimal | None
    downstream_effect: str
    currency: CurrencyCode | None = None
    listing_id: ListingId | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    method_id: str
    version: str
    tolerance_version: str
    account_id: BrokerAccountId
    coverage_complete: bool
    status: ReconciliationStatus
    quality_state: QualityState
    checks: tuple[ReconciliationCheck, ...]
    discrepancies: tuple[ReconciliationIssue, ...]
    warnings: tuple[DomainWarning, ...]


def _sum_quantities(values: tuple[Quantity, ...]) -> Decimal:
    return total(item.value for item in values)


def _sum_money(values: tuple[Money, ...]) -> Decimal:
    return total(item.amount for item in values)


def _quantity_check(
    bridge: QuantityBridgeInput,
    policy: TolerancePolicy,
) -> tuple[ReconciliationCheck, tuple[ReconciliationIssue, ...], tuple[DomainWarning, ...]]:
    expected_raw = total(
        (
            bridge.opening_quantity.value,
            _sum_quantities(bridge.buys),
            _sum_quantities(bridge.transfers_in),
            _sum_quantities(bridge.corporate_additions),
            -_sum_quantities(bridge.sells),
            -_sum_quantities(bridge.transfers_out),
            -_sum_quantities(bridge.corporate_removals),
        )
    )
    expected = persisted_decimal(expected_raw)
    observed = bridge.closing_quantity.value if bridge.closing_quantity is not None else None
    residual = persisted_decimal(subtract(observed, expected)) if observed is not None else None
    within = abs(residual) <= policy.quantity_absolute if residual is not None else None
    scope = f"listing:{bridge.listing_id}"
    check = ReconciliationCheck(
        discrepancy_type=DiscrepancyType.QUANTITY_MISMATCH,
        scope=scope,
        expected=expected,
        observed=observed,
        residual=residual,
        tolerance=policy.quantity_absolute,
        within_tolerance=within,
        listing_id=bridge.listing_id,
    )
    issues: list[ReconciliationIssue] = []
    warnings: list[DomainWarning] = []
    if within is False:
        issues.append(
            ReconciliationIssue(
                discrepancy_type=DiscrepancyType.QUANTITY_MISMATCH,
                severity=DiscrepancySeverity.ERROR,
                scope=scope,
                expected=expected,
                observed=observed,
                residual=residual,
                tolerance=policy.quantity_absolute,
                downstream_effect=(
                    "Position accounting and dependent portfolio metrics are unreconciled."
                ),
                listing_id=bridge.listing_id,
            )
        )
    if observed is None or not bridge.coverage_complete:
        issues.append(
            ReconciliationIssue(
                discrepancy_type=DiscrepancyType.PROVIDER_HISTORY_COVERAGE_GAP,
                severity=DiscrepancySeverity.WARNING,
                scope=scope,
                expected=expected,
                observed=observed,
                residual=residual,
                tolerance=policy.quantity_absolute,
                downstream_effect=(
                    "The quantity bridge is partial and cannot establish full coverage."
                ),
                listing_id=bridge.listing_id,
            )
        )
        warnings.append(
            DomainWarning(
                "quantity_coverage_gap",
                "Quantity history or closing observation is incomplete.",
                (str(bridge.listing_id),),
            )
        )
    if bridge.unsupported_activity:
        issues.append(
            ReconciliationIssue(
                discrepancy_type=DiscrepancyType.UNSUPPORTED_CORPORATE_ACTION,
                severity=DiscrepancySeverity.ERROR,
                scope=scope,
                expected=expected,
                observed=observed,
                residual=residual,
                tolerance=policy.quantity_absolute,
                downstream_effect="Unsupported activity prevents a trustworthy quantity bridge.",
                listing_id=bridge.listing_id,
            )
        )
        warnings.append(
            DomainWarning(
                "unsupported_quantity_activity",
                "Unsupported activity prevents a trustworthy quantity bridge.",
                (str(bridge.listing_id),),
            )
        )
    return check, tuple(issues), tuple(warnings)


def _cash_check(
    bridge: CashBridgeInput,
    policy: TolerancePolicy,
) -> tuple[ReconciliationCheck, tuple[ReconciliationIssue, ...], tuple[DomainWarning, ...]]:
    expected_raw = total(
        (
            bridge.opening_cash.amount,
            _sum_money(bridge.deposits),
            -_sum_money(bridge.withdrawals),
            -_sum_money(bridge.buy_outflows),
            _sum_money(bridge.sell_inflows),
            _sum_money(bridge.dividends),
            _sum_money(bridge.interest),
            -_sum_money(bridge.fees),
            -_sum_money(bridge.taxes),
            _sum_money(bridge.signed_adjustments),
        )
    )
    expected = persisted_decimal(expected_raw)
    observed = bridge.closing_cash.amount if bridge.closing_cash is not None else None
    residual = persisted_decimal(subtract(observed, expected)) if observed is not None else None
    within = abs(residual) <= policy.money_absolute if residual is not None else None
    currency = bridge.opening_cash.currency
    scope = f"cash:{currency}"
    check = ReconciliationCheck(
        discrepancy_type=DiscrepancyType.CASH_MISMATCH,
        scope=scope,
        expected=expected,
        observed=observed,
        residual=residual,
        tolerance=policy.money_absolute,
        within_tolerance=within,
        currency=currency,
    )
    issues: list[ReconciliationIssue] = []
    warnings: list[DomainWarning] = []
    if within is False:
        issues.append(
            ReconciliationIssue(
                discrepancy_type=DiscrepancyType.CASH_MISMATCH,
                severity=DiscrepancySeverity.ERROR,
                scope=scope,
                expected=expected,
                observed=observed,
                residual=residual,
                tolerance=policy.money_absolute,
                downstream_effect=(
                    "Cash accounting and dependent performance metrics are unreconciled."
                ),
                currency=currency,
            )
        )
    if observed is None or not bridge.coverage_complete:
        issues.append(
            ReconciliationIssue(
                discrepancy_type=DiscrepancyType.PROVIDER_HISTORY_COVERAGE_GAP,
                severity=DiscrepancySeverity.WARNING,
                scope=scope,
                expected=expected,
                observed=observed,
                residual=residual,
                tolerance=policy.money_absolute,
                downstream_effect="The cash bridge is partial and cannot establish full coverage.",
                currency=currency,
            )
        )
        warnings.append(
            DomainWarning(
                "cash_coverage_gap",
                "Cash history or closing observation is incomplete.",
                (str(currency),),
            )
        )
    if bridge.unsupported_activity:
        issues.append(
            ReconciliationIssue(
                discrepancy_type=DiscrepancyType.MISSING_SOURCE_ACTIVITY,
                severity=DiscrepancySeverity.ERROR,
                scope=scope,
                expected=expected,
                observed=observed,
                residual=residual,
                tolerance=policy.money_absolute,
                downstream_effect="Unsupported activity prevents a trustworthy currency ledger.",
                currency=currency,
            )
        )
        warnings.append(
            DomainWarning(
                "unsupported_cash_activity",
                "Unsupported activity prevents a trustworthy cash bridge.",
                (str(currency),),
            )
        )
    return check, tuple(issues), tuple(warnings)


def _value_check(
    bridge: ValueBridgeInput,
    policy: TolerancePolicy,
) -> tuple[ReconciliationCheck, tuple[ReconciliationIssue, ...], tuple[DomainWarning, ...]]:
    expected = bridge.canonical_total.amount
    observed = bridge.provider_total.amount if bridge.provider_total is not None else None
    residual = persisted_decimal(subtract(observed, expected)) if observed is not None else None
    within = abs(residual) <= policy.value_absolute if residual is not None else None
    currency = bridge.canonical_total.currency
    scope = f"portfolio_value:{currency}"
    check = ReconciliationCheck(
        discrepancy_type=DiscrepancyType.TIMING_SETTLEMENT_DIFFERENCE,
        scope=scope,
        expected=expected,
        observed=observed,
        residual=residual,
        tolerance=policy.value_absolute,
        within_tolerance=within,
        currency=currency,
    )
    issues: list[ReconciliationIssue] = []
    warnings: list[DomainWarning] = []
    if within is False:
        issues.append(
            ReconciliationIssue(
                discrepancy_type=DiscrepancyType.TIMING_SETTLEMENT_DIFFERENCE,
                severity=DiscrepancySeverity.ERROR,
                scope=scope,
                expected=expected,
                observed=observed,
                residual=residual,
                tolerance=policy.value_absolute,
                downstream_effect="Canonical and provider portfolio totals disagree.",
                currency=currency,
            )
        )
    if observed is None or not bridge.comparable_valuation:
        issues.append(
            ReconciliationIssue(
                discrepancy_type=(
                    DiscrepancyType.TIMING_SETTLEMENT_DIFFERENCE
                    if observed is not None
                    else DiscrepancyType.MISSING_SOURCE_ACTIVITY
                ),
                severity=DiscrepancySeverity.WARNING,
                scope=scope,
                expected=expected,
                observed=observed,
                residual=residual,
                tolerance=policy.value_absolute,
                downstream_effect="A comparable provider portfolio total is unavailable.",
                currency=currency,
            )
        )
        warnings.append(
            DomainWarning(
                "value_comparison_unavailable",
                "Provider and canonical valuation timing or coverage is not comparable.",
                (str(currency),),
            )
        )
    return check, tuple(issues), tuple(warnings)


def reconcile_portfolio(
    *,
    account_id: BrokerAccountId,
    quantity_bridges: tuple[QuantityBridgeInput, ...] = (),
    cash_bridges: tuple[CashBridgeInput, ...] = (),
    value_bridges: tuple[ValueBridgeInput, ...] = (),
    policy: TolerancePolicy = TOLERANCE_POLICY_V1,
) -> ReconciliationResult:
    """Run deterministic bridges for exactly one broker account."""

    if (
        any(item.account_id != account_id for item in quantity_bridges)
        or any(item.account_id != account_id for item in cash_bridges)
        or any(item.account_id != account_id for item in value_bridges)
    ):
        raise ValueError("reconciliation input contains a different broker account")

    checks: list[ReconciliationCheck] = []
    issues: list[ReconciliationIssue] = []
    warnings: list[DomainWarning] = []
    input_states: list[QualityState] = []
    incomplete = False
    unsupported = False

    for quantity_bridge in sorted(quantity_bridges, key=lambda item: str(item.listing_id)):
        check, bridge_issues, bridge_warnings = _quantity_check(quantity_bridge, policy)
        checks.append(check)
        issues.extend(bridge_issues)
        warnings.extend(bridge_warnings)
        input_states.append(quantity_bridge.quality_state)
        incomplete = (
            incomplete
            or not quantity_bridge.coverage_complete
            or quantity_bridge.closing_quantity is None
        )
        unsupported = unsupported or quantity_bridge.unsupported_activity
    for cash_bridge in sorted(cash_bridges, key=lambda item: str(item.opening_cash.currency)):
        check, bridge_issues, bridge_warnings = _cash_check(cash_bridge, policy)
        checks.append(check)
        issues.extend(bridge_issues)
        warnings.extend(bridge_warnings)
        input_states.append(cash_bridge.quality_state)
        incomplete = (
            incomplete or not cash_bridge.coverage_complete or cash_bridge.closing_cash is None
        )
        unsupported = unsupported or cash_bridge.unsupported_activity
    for value_bridge in sorted(value_bridges, key=lambda item: str(item.canonical_total.currency)):
        check, bridge_issues, bridge_warnings = _value_check(value_bridge, policy)
        checks.append(check)
        issues.extend(bridge_issues)
        warnings.extend(bridge_warnings)
        input_states.append(value_bridge.quality_state)
        incomplete = (
            incomplete
            or value_bridge.provider_total is None
            or not value_bridge.comparable_valuation
        )

    quality = combine_quality(input_states)
    mismatched = any(check.within_tolerance is False for check in checks)
    if mismatched or unsupported:
        quality = degrade_quality(quality, QualityState.UNRECONCILED)
    elif incomplete:
        quality = degrade_quality(quality, QualityState.PARTIAL)

    if quality is QualityState.FAILED:
        status = ReconciliationStatus.FAILED
    elif mismatched or unsupported or quality is QualityState.UNRECONCILED:
        status = ReconciliationStatus.UNRECONCILED
    elif incomplete or quality is QualityState.PARTIAL:
        status = ReconciliationStatus.PARTIAL
    else:
        status = ReconciliationStatus.RECONCILED

    return ReconciliationResult(
        method_id=RECONCILIATION_METHOD_ID,
        version=RECONCILIATION_VERSION,
        tolerance_version=policy.version,
        account_id=account_id,
        coverage_complete=not incomplete,
        status=status,
        quality_state=quality,
        checks=tuple(checks),
        discrepancies=tuple(issues),
        warnings=tuple(warnings),
    )
