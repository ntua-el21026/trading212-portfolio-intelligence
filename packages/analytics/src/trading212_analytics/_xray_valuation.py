"""Bounded sourced FX and reconciliation at the saved reporting-money boundary."""

from __future__ import annotations

from uuid import UUID

from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.values import CurrencyCode, Money
from trading212_domain.xray import (
    XrayAvailability,
    XrayBound,
    XrayCash,
    XrayFxLeg,
    XrayInput,
    XrayLicensedFx,
    XrayMoneyMetric,
    XrayPosition,
    XrayReason,
    XrayReconciliation,
)
from trading212_domain.xray_validation import bound, invalid, validate_record

from trading212_analytics._xray_decimal import ZERO, S, arithmetic, coefficient18, q18
from trading212_analytics._xray_sources import confidence, quality


def convert_xray_money(
    value: XrayMoneyMetric, reporting_currency: CurrencyCode, *, legs: tuple[XrayFxLeg, ...] = ()
) -> XrayMoneyMetric:
    """Apply <=2 actual direct/inverse quotes, with one exact final Q18 boundary.

    Starting with amount_coefficient/S, each multiply contributes rate_coefficient/S
    and each inverse contributes S/rate_coefficient. With two legs, the largest
    numerator is below 1e114 and denominator below 1e94; q18's Decimal256 envelope
    safely contains both, without forming a rounded reciprocal or intermediate money.
    """
    if type(value) is not XrayMoneyMetric or type(reporting_currency) is not CurrencyCode:
        invalid("conversion.type")
    validate_record(value)
    if type(legs) is not tuple or any(type(item) is not XrayFxLeg for item in legs):
        invalid("conversion.legs")
    bound(len(legs) <= 2, "conversion.legs")
    for leg in legs:
        validate_record(leg)
    if value.value is None:
        if legs:
            invalid("conversion.unavailable_input")
        return value
    if value.value.currency == reporting_currency:
        if legs:
            invalid("conversion.identity_legs")
        return value
    # The same closed record validation is also applied at immutable input admission.
    XrayLicensedFx("portfolio_total", value, reporting_currency, legs)
    references = tuple(
        sorted(
            set(value.source_reference_ids + tuple(item.source_reference_id for item in legs)),
            key=str,
        )
    )
    if not legs or any(leg.rate is None or leg.quality is QualityState.FAILED for leg in legs):
        return XrayMoneyMetric(
            None,
            XrayReason.MISSING_FX,
            quality((value.quality, QualityState.PARTIAL, *(leg.quality for leg in legs))),
            ValueOrigin.UNAVAILABLE,
            XrayBound.EXACT,
            XrayAvailability.UNAVAILABLE,
            confidence((value.confidence, *(leg.confidence for leg in legs))),
            references,
        )
    if value.bound is not XrayBound.EXACT:
        invalid("conversion.unusable_basis")
    with arithmetic():
        numerator, denominator = coefficient18(value.value.amount), S
        for leg in legs:
            assert leg.rate is not None
            rate = coefficient18(leg.rate)
            if leg.operation == "multiply":
                numerator *= rate
                denominator *= S
            else:
                numerator *= S
                denominator *= rate
        amount = q18(numerator, denominator)
    return XrayMoneyMetric(
        Money(amount, reporting_currency),
        None,
        quality((value.quality, *(leg.quality for leg in legs))),
        ValueOrigin.DERIVED_DETERMINISTIC,
        XrayBound.EXACT,
        XrayAvailability.AVAILABLE,
        confidence((value.confidence, *(leg.confidence for leg in legs))),
        references,
    )


def verify_licensed_fx(value: XrayInput) -> None:
    rows: tuple[XrayPosition | XrayCash, ...] = (*value.positions, *value.cash)
    roots = {item.root.key: item for item in rows}
    for conversion in value.licensed_fx:
        expected = convert_xray_money(
            conversion.input_value, conversion.output_currency, legs=conversion.legs
        )
        actual = (
            value.portfolio_total
            if conversion.consumer_key == "portfolio_total"
            else roots[conversion.consumer_key].reporting_value
        )
        if actual != expected:
            invalid("licensed_fx.reporting_value")


def build_xray_reconciliation(
    positions: tuple[XrayPosition, ...],
    cash: tuple[XrayCash, ...],
    portfolio_total: XrayMoneyMetric,
    *,
    source_reference_ids: tuple[UUID, ...] = (),
) -> XrayReconciliation:
    """Keep declared, complete-root and difference availability independently honest."""
    if type(positions) is not tuple or any(type(item) is not XrayPosition for item in positions):
        invalid("reconciliation.positions")
    if type(cash) is not tuple or any(type(item) is not XrayCash for item in cash):
        invalid("reconciliation.cash")
    if type(portfolio_total) is not XrayMoneyMetric or type(source_reference_ids) is not tuple:
        invalid("reconciliation.type")
    if any(type(item) is not UUID for item in source_reference_ids) or len(
        set(source_reference_ids)
    ) != len(source_reference_ids):
        invalid("reconciliation.references")
    roots: tuple[XrayPosition | XrayCash, ...] = (*positions, *cash)
    bound(len(roots) <= 10_000 and len(source_reference_ids) <= 100_000, "reconciliation.bounds")
    if len({item.root.key for item in roots}) != len(roots):
        invalid("reconciliation.roots")
    for item in (*roots, portfolio_total):
        validate_record(item)
    metrics = tuple(item.reporting_value for item in roots)
    currencies = {
        item.value.currency for item in (*metrics, portfolio_total) if item.value is not None
    }
    if len(currencies) > 1:
        invalid("reconciliation.currency")
    if any(
        item.value is not None and (item.bound is not XrayBound.EXACT or item.value.amount < ZERO)
        for item in metrics
    ):
        invalid("reconciliation.root_basis")
    currency = next(iter(currencies), None)
    complete = all(item.value is not None for item in metrics) and currency is not None
    references = tuple(
        sorted({reference for item in metrics for reference in item.source_reference_ids}, key=str)
    )
    state = quality(tuple(item.quality for item in metrics))
    certainty = confidence(tuple(item.confidence for item in metrics))
    with arithmetic():
        coefficient = (
            sum(
                (coefficient18(item.value.amount) for item in metrics if item.value is not None),
                ZERO,
            )
            if complete
            else None
        )
        root_value = (
            None
            if coefficient is None or currency is None
            else Money(q18(coefficient, S), currency)
        )
        root_total = XrayMoneyMetric(
            root_value,
            None if complete else XrayReason.INCOMPLETE_VALUATION,
            state if complete else quality((state, QualityState.PARTIAL)),
            ValueOrigin.DERIVED_DETERMINISTIC if complete else ValueOrigin.UNAVAILABLE,
            XrayBound.EXACT,
            XrayAvailability.AVAILABLE if complete else XrayAvailability.UNAVAILABLE,
            certainty,
            references,
        )
        known = root_value is not None and portfolio_total.value is not None
        difference = None
        if known:
            assert (
                portfolio_total.value is not None
                and coefficient is not None
                and currency is not None
            )
            difference = Money(
                q18(coefficient18(portfolio_total.value.amount) - coefficient, S), currency
            )
    difference_refs = tuple(
        sorted(
            set(references + portfolio_total.source_reference_ids + source_reference_ids), key=str
        )
    )
    difference_metric = XrayMoneyMetric(
        difference,
        None if known else XrayReason.INCOMPLETE_VALUATION,
        quality(
            (state, portfolio_total.quality, QualityState.FRESH if known else QualityState.PARTIAL)
        ),
        ValueOrigin.DERIVED_DETERMINISTIC if known else ValueOrigin.UNAVAILABLE,
        XrayBound.EXACT,
        XrayAvailability.AVAILABLE if known else XrayAvailability.UNAVAILABLE,
        confidence((certainty, portfolio_total.confidence)),
        difference_refs,
    )
    return XrayReconciliation(
        portfolio_total, root_total, difference_metric, tuple(sorted(source_reference_ids, key=str))
    )
