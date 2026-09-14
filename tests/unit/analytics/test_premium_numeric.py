"""Independent analytical references for the ADR-0019 finite-precision profile."""

from __future__ import annotations

from decimal import ROUND_DOWN, Context, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction
from typing import Any

import pytest
from trading212_analytics._premium_numeric import (
    arithmetic,
    correlations,
    modeled_risk,
    normal_cdf,
    normal_quantile,
    q18,
    sample_covariance,
    semidefinite_factor,
    shrink_covariance,
)
from trading212_analytics._premium_tails import historical_tail, parametric_tail
from trading212_domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.unit


def _reference_cdf(value: Decimal) -> Decimal:
    """Independent positive-series integral and Machin pi at 200 digits.

    CDF(x)-1/2 = exp(-x*x/2)/sqrt(2*pi) * sum x**(2k+1)/(2k+1)!!.
    Unlike production erf's alternating series this has no cancellation for x>0.
    """
    with localcontext(Context(prec=200)):

        def atan_inverse(inverse: int) -> Decimal:
            x = D(1) / inverse
            term, total = x, x
            for n in range(1, 1000):
                term *= -(x * x)
                step = term / (2 * n + 1)
                total += step
                if abs(step) < D("1e-190"):
                    return total
            raise AssertionError("oracle arctan convergence")

        pi = 16 * atan_inverse(5) - 4 * atan_inverse(239)
        x = value.copy_abs()
        term = total = x
        for n in range(1, 1000):
            term *= x * x / (2 * n + 1)
            total += term
            if abs(term) < D("1e-170"):
                area = (-x * x / 2).exp() * total / (2 * pi).sqrt()
                return D(".5") + (area if value >= 0 else -area)
        raise AssertionError("oracle integral convergence")


@pytest.mark.parametrize(
    "value", ["-8", "-7", "-4", "-2", "-1", "-.1", "0", ".1", "1", "2", "4", "7", "8"]
)
def test_cdf_against_independent_high_precision_series(value: str) -> None:
    x = D(value)
    assert abs(normal_cdf(x) - _reference_cdf(x)) < D("1e-70")


@pytest.mark.parametrize("confidence", [".90", ".95", ".99"])
def test_inverse_normal_against_independent_integral(confidence: str) -> None:
    value = normal_quantile(D(confidence))
    assert abs(_reference_cdf(value) - D(confidence)) < D("1e-70")


def test_rational_covariance_beta_and_euler_components() -> None:
    a = (D("-.01"), D(0), D(".01")) * 10
    b = tuple(2 * value for value in a)
    covariance = sample_covariance((a, b))
    with localcontext(Context(prec=180)):
        rational = Fraction(2, 1000) / 29
        variance = D(rational.numerator) / D(rational.denominator)
        sigma = (252 * variance).sqrt()
        assert abs(covariance[0][0] - variance) < D("1e-90")
        assert abs(covariance[0][1] / covariance[0][0] - 2) < D("1e-90")
        result = modeled_risk(covariance, (D(".5"), D(".5")), 252)
        assert result.components is not None
        assert abs(result.volatility - D("1.5") * sigma) < D("1e-90")
        assert abs(result.components[0] - D(".5") * sigma) < D("1e-90")
        assert abs(result.components[1] - sigma) < D("1e-90")
        assert abs(sum(result.components) - result.volatility) < D("1e-90")
        assert correlations(covariance) == ((D(1), D(1)), (D(1), D(1)))
        assert result.numerical_zero_pivots == (1,)


def test_singular_anticorrelation_and_zero_variance_are_supported() -> None:
    matrix = ((D(1), D(-1)), (D(-1), D(1)))
    assert semidefinite_factor(matrix).numerical_zero_pivots == (1,)
    result = modeled_risk(matrix, (D(".5"), D(".5")), 252)
    assert result.volatility == 0
    assert result.components is None and result.marginal is None and result.diversification is None
    assert correlations(((D(0),),)) == ((None,),)
    assert sample_covariance(((D(0),) * 30,)) == ((D(0),),)


@pytest.mark.parametrize(
    "matrix",
    [
        ((D(1), D(2)), (D(2), D(1))),
        ((D(0), D(1)), (D(1), D(1))),
        ((D(1), D(0)), (D(1), D(1))),
        ((D(-1),),),
    ],
)
def test_indefinite_asymmetric_or_nonzero_null_column_fails(matrix: Any) -> None:
    with pytest.raises(DomainError):
        semidefinite_factor(matrix)
    with pytest.raises(DomainError):
        shrink_covariance(matrix, D(1))


def test_explicit_shrinkage_and_weight_validation() -> None:
    matrix = ((D(1), D(1)), (D(1), D(1)))
    assert shrink_covariance(matrix, D(".25")) == ((D(1), D(".75")), (D(".75"), D(1)))
    with pytest.raises(DomainError):
        modeled_risk(matrix, (D(".4"), D(".5")), 252)
    with pytest.raises(DomainError):
        modeled_risk(matrix, (D("-.5"), D("1.5")), 252)
    with pytest.raises(DomainError):
        shrink_covariance(matrix, D("1.1"))


def test_context_isolation_restoration_rounding_and_failure() -> None:
    expected = normal_cdf(D(1))
    with localcontext(Context(prec=6, rounding=ROUND_DOWN, Emin=-9, Emax=9)) as hostile:
        hostile.traps[Inexact] = hostile.traps[Rounded] = True
        before = hostile.copy()
        assert normal_cdf(D(1)) == expected
        assert q18(D("1.0000000000000000005")) == D(1)
        assert q18(D("1.0000000000000000015")) == D("1.000000000000000002")
        assert q18(D("-0.0000000000000000001")).is_signed() is False
        with pytest.raises(DomainError), arithmetic():
            D(1000) ** 1000
        assert hostile.prec == before.prec and hostile.rounding == before.rounding
        assert hostile.Emin == before.Emin and hostile.Emax == before.Emax
        assert hostile.flags == before.flags and hostile.traps == before.traps
    with pytest.raises(DomainError):
        q18(D("99999999999999999999.9999999999999999999"))


@pytest.mark.parametrize(
    "value", [1.0, True, "1", D("NaN"), D("Infinity"), D("1e1000"), D("1e-1000")]
)
def test_invalid_numeric_encodings_fail_before_work(value: Any) -> None:
    with pytest.raises(DomainError):
        normal_cdf(value)
    with pytest.raises(DomainError):
        semidefinite_factor(((value,),))


def test_sample_and_matrix_work_bounds() -> None:
    for series in (
        (),
        ((D(0),) * 19,),
        ((D(0),) * 20, (D(0),) * 21),
        ((D(0),) * 3662,),
        ((D(0),) * 3230,) * 31,
    ):
        with pytest.raises(DomainError):
            sample_covariance(series)
    with pytest.raises(DomainError):
        semidefinite_factor(((D(1),),) * 33)


def test_historical_tail_reference_fractional_mass_and_sign() -> None:
    returns = tuple(-D(i) / 10000 for i in range(100))
    result = historical_tail(returns, D(".95"), 1, "daily")
    assert result.value_at_risk == D(".0094") and result.expected_shortfall == D(".0097")
    fractional = historical_tail((*returns, D("-.01")), D(".95"), 1, "daily")
    assert fractional.expected_shortfall is not None
    with localcontext(Context(prec=180)):
        assert abs(fractional.expected_shortfall - (D(".049") + D(".000475")) / D("5.05")) < D(
            "1e-90"
        )
    assert historical_tail(returns, D(".99"), 1, "daily").reason == "insufficient_tail"
    gain = historical_tail((D(".01"),) * 102, D(".95"), 2, "daily")
    assert gain.value_at_risk == gain.expected_shortfall == D("-.0201")
    gap = historical_tail((D(0),) * 50 + (None,) + (D(0),) * 50, D(".9"), 2, "daily")
    assert gap.observations == 98


def test_parametric_lognormal_loss_reference_and_unavailability() -> None:
    returns = (D("-.01"), D(0), D(".01")) * 10
    result = parametric_tail(returns, D(".95"), 2, "daily")
    assert result.reason is None
    assert result.value_at_risk is not None and result.expected_shortfall is not None
    with localcontext(Context(prec=180)):
        # Independently invert the reference integral; no production CDF in the oracle.
        lo, hi = D(0), D(4)
        for _ in range(260):
            mid = (lo + hi) / 2
            if _reference_cdf(mid) < D(".95"):
                lo = mid
            else:
                hi = mid
        z = (lo + hi) / 2
        s = (D(2) * D(".002") / 29).sqrt()
        expected_var = 1 - (-s * z).exp()
        expected_es = 1 - (s * s / 2).exp() * _reference_cdf(-z - s) / D(".05")
        assert abs(result.value_at_risk - expected_var) < D("1e-70")
        assert abs(result.expected_shortfall - expected_es) < D("1e-70")
    constant = parametric_tail((D(".01"),) * 30, D(".95"), 2, "daily")
    assert constant.value_at_risk is not None
    with localcontext(Context(prec=180)):
        assert abs(constant.value_at_risk - (1 - D(".02").exp())) < D("1e-90")
    assert constant.value_at_risk == constant.expected_shortfall
    assert parametric_tail((D(2),) * 30, D(".95"), 1, "daily").reason == "unsupported_parametric"
    assert parametric_tail((D(0),) * 19, D(".95"), 1, "daily").reason == "insufficient_history"


def test_tiny_normal_argument_uses_declared_error_budget_without_underflow() -> None:
    assert normal_cdf(D("1e-999")) == D(".5")
    assert normal_cdf(D("-1e-999")) == D(".5")
