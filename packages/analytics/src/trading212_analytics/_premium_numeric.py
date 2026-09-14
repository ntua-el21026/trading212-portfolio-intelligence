"""Isolated finite-precision numerical primitives from ADR-0019.

Values here are internal estimates, not wire values. Publish exactly once via q18.
No function inherits the caller's precision, rounding, flags or traps.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)

from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.values import exact_decimal

PROFILE = "premium_decimal96_q18_v1"
ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")
Q18 = Decimal("1e-18")
TOLERANCE = Decimal("1e-60")
PI = Decimal(
    "3.1415926535897932384626433832795028841971693993751058209749445923078164062862089986280348253421170679"
)
CONFIDENCES = (Decimal("0.90"), Decimal("0.95"), Decimal("0.99"))
type Matrix = tuple[tuple[Decimal, ...], ...]


def invalid(field: str) -> None:
    raise DomainError(ErrorCode.VALIDATION_FAILED, "Invalid premium numerical input.", field)


@contextmanager
def arithmetic() -> Iterator[Context]:
    # Construct all context options; localcontext() alone would inherit hostile traps.
    context = Context(
        prec=96,
        rounding=ROUND_HALF_EVEN,
        Emin=-999,
        Emax=999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, FloatOperation],
    )
    try:
        with localcontext(context) as active:
            yield active
    except DecimalException:
        raise DomainError(
            ErrorCode.DATA_UNAVAILABLE,
            "Premium numerical computation exceeds its supported bounds.",
            "premium.numeric",
        ) from None


def finite(value: Decimal, field: str = "premium.numeric") -> Decimal:
    """Bound internal Decimal encodings before work; request values have stricter Q18 rules."""
    if not isinstance(value, Decimal) or not value.is_finite():
        invalid(field)
    parts = value.as_tuple()
    if (
        not isinstance(parts.exponent, int)
        or not -999 <= parts.exponent <= 999
        or len(parts.digits) > 96
    ):
        invalid(field)
    return value


def q18(value: Decimal) -> Decimal:
    finite(value)
    with arithmetic():
        rounded = value.quantize(Q18)
        return exact_decimal(rounded.copy_abs() if rounded.is_zero() else rounded)


def _matrix(value: Matrix) -> int:
    if not isinstance(value, tuple) or not 1 <= len(value) <= 32:
        invalid("premium.matrix")
    for row in value:
        if not isinstance(row, tuple) or len(row) != len(value):
            invalid("premium.matrix.shape")
        for cell in row:
            finite(cell, "premium.matrix.cell")
    return len(value)


@dataclass(frozen=True, slots=True)
class SemidefiniteFactor:
    lower: Matrix
    numerical_zero_pivots: tuple[int, ...]


def semidefinite_factor(matrix: Matrix) -> SemidefiniteFactor:
    """Ordered Cholesky supports singular PSD matrices without an inverse or repair."""
    size = _matrix(matrix)
    with arithmetic():
        scale = max(ONE, *(value.copy_abs() for row in matrix for value in row))
        tolerance = TOLERANCE * scale
        lower = [[ZERO for _ in range(size)] for _ in range(size)]
        zero_pivots: list[int] = []
        for row in range(size):
            for column in range(row + 1):
                if matrix[row][column] != matrix[column][row]:
                    invalid("premium.matrix.symmetry")
                residual = matrix[row][column] - sum(
                    (lower[row][k] * lower[column][k] for k in range(column)), ZERO
                )
                if row == column:
                    if residual < -tolerance:
                        invalid("premium.matrix.psd")
                    if residual.copy_abs() <= tolerance:
                        zero_pivots.append(row)
                    else:
                        lower[row][column] = residual.sqrt()
                elif lower[column][column] == ZERO:
                    if residual.copy_abs() > tolerance:
                        invalid("premium.matrix.psd")
                else:
                    lower[row][column] = residual / lower[column][column]
        return SemidefiniteFactor(tuple(tuple(row) for row in lower), tuple(zero_pivots))


def sample_covariance(series: tuple[tuple[Decimal, ...], ...]) -> Matrix:
    """Complete aligned series only; metadata/alignment are owned by the risk engine."""
    if not isinstance(series, tuple) or not 1 <= len(series) <= 32:
        invalid("premium.series")
    if not isinstance(series[0], tuple) or not 20 <= len(series[0]) <= 3661:
        invalid("premium.series.samples")
    count = len(series[0])
    if count * len(series) > 100000:
        invalid("premium.series.cells")
    for row in series:
        if not isinstance(row, tuple) or len(row) != count:
            invalid("premium.series.alignment")
        for value in row:
            finite(value, "premium.series.value")
    with arithmetic():
        means = tuple(sum(row, ZERO) / count for row in series)
        centered = tuple(
            tuple(value - mean for value in row) for row, mean in zip(series, means, strict=True)
        )
        covariance = [[ZERO for _ in series] for _ in series]
        for i, row in enumerate(centered):
            for j in range(i + 1):
                value = sum((a * b for a, b in zip(row, centered[j], strict=True)), ZERO) / (
                    count - 1
                )
                covariance[i][j] = covariance[j][i] = value
        result = tuple(tuple(row) for row in covariance)
        semidefinite_factor(result)
        return result


def shrink_covariance(matrix: Matrix, shrinkage: Decimal) -> Matrix:
    size = _matrix(matrix)
    finite(shrinkage)
    if not ZERO <= shrinkage <= ONE:
        invalid("premium.matrix.shrinkage")
    # Validate the original too: shrinkage cannot launder an invalid covariance.
    semidefinite_factor(matrix)
    with arithmetic():
        return tuple(
            tuple(matrix[i][j] if i == j else (ONE - shrinkage) * matrix[i][j] for j in range(size))
            for i in range(size)
        )


def correlations(matrix: Matrix) -> tuple[tuple[Decimal | None, ...], ...]:
    size = _matrix(matrix)
    semidefinite_factor(matrix)
    with arithmetic():
        result: list[tuple[Decimal | None, ...]] = []
        for i in range(size):
            row: list[Decimal | None] = []
            for j in range(size):
                if matrix[i][i] <= ZERO or matrix[j][j] <= ZERO:
                    row.append(None)
                else:
                    value = matrix[i][j] / (matrix[i][i] * matrix[j][j]).sqrt()
                    if value.copy_abs() > ONE + TOLERANCE:
                        invalid("premium.matrix.correlation")
                    row.append(max(-ONE, min(ONE, value)))
            result.append(tuple(row))
        return tuple(result)


@dataclass(frozen=True, slots=True)
class ModeledRisk:
    volatility: Decimal
    marginal: tuple[Decimal, ...] | None
    components: tuple[Decimal, ...] | None
    diversification: Decimal | None
    residual: Decimal | None
    numerical_zero_pivots: tuple[int, ...]


def modeled_risk(matrix: Matrix, weights: tuple[Decimal, ...], annual_factor: int) -> ModeledRisk:
    size = _matrix(matrix)
    if (
        not isinstance(weights, tuple)
        or len(weights) != size
        or type(annual_factor) is not int
        or annual_factor not in (12, 252)
    ):
        invalid("premium.model.shape")
    for weight in weights:
        if finite(weight) < ZERO:
            invalid("premium.model.weights")
    with arithmetic():
        if sum(weights, ZERO) != ONE:
            invalid("premium.model.weights")
    return modeled_risk_from_values(matrix, weights, annual_factor)


def modeled_risk_from_values(
    matrix: Matrix, values: tuple[Decimal, ...], annual_factor: int
) -> ModeledRisk:
    """Use v/sum(v) algebraically without allocating a rounded weight residual.

    The caller must prove that values are the complete material portfolio. This
    normalization alone cannot establish economic coverage.
    """
    size = _matrix(matrix)
    if (
        not isinstance(values, tuple)
        or len(values) != size
        or type(annual_factor) is not int
        or annual_factor not in (12, 252)
    ):
        invalid("premium.model.shape")
    for value in values:
        if finite(value) < ZERO:
            invalid("premium.model.values")
    factor = semidefinite_factor(matrix)
    with arithmetic():
        total = sum(values, ZERO)
        if total <= ZERO:
            invalid("premium.model.values")
        product = tuple(
            sum((row[j] * values[j] for j in range(size)), ZERO) * annual_factor / total
            for row in matrix
        )
        variance = sum((values[i] * product[i] for i in range(size)), ZERO) / total
        tolerance = TOLERANCE * max(ONE, *(v.copy_abs() for v in product))
        if variance < -tolerance:
            invalid("premium.model.variance")
        if variance <= ZERO:
            return ModeledRisk(ZERO, None, None, None, None, factor.numerical_zero_pivots)
        volatility = variance.sqrt()
        marginal = tuple(value / volatility for value in product)
        components = tuple(value * marginal[i] / total for i, value in enumerate(values))
        residual = volatility - sum(components, ZERO)
        if residual.copy_abs() > TOLERANCE * max(ONE, volatility):
            invalid("premium.model.reconciliation")
        standalone = (
            sum(
                (values[i] * max(ZERO, matrix[i][i] * annual_factor).sqrt() for i in range(size)),
                ZERO,
            )
            / total
        )
        return ModeledRisk(
            volatility,
            marginal,
            components,
            standalone / volatility,
            residual,
            factor.numerical_zero_pivots,
        )


def normal_cdf(value: Decimal) -> Decimal:
    finite(value)
    if value.copy_abs() > Decimal("8"):
        invalid("premium.normal.domain")
    with arithmetic():
        if value.copy_abs() < Decimal("1e-86"):
            return Decimal("0.5")
        x = value / TWO.sqrt()
        square = x * x
        term = total = x
        for n in range(1, 512):
            if term.copy_abs() < Decimal("1e-86"):
                return Decimal("0.5") + total / PI.sqrt()
            term *= -square * (2 * n - 1) / (n * (2 * n + 1))
            total += term
    raise DomainError(ErrorCode.DATA_UNAVAILABLE, "Normal CDF did not converge.", "premium.normal")


def normal_quantile(confidence: Decimal) -> Decimal:
    finite(confidence)
    if confidence not in CONFIDENCES:
        invalid("premium.normal.confidence")
    with arithmetic():
        low, high = ZERO, Decimal("4")
        for _ in range(256):
            middle = (low + high) / TWO
            if normal_cdf(middle) < confidence:
                low = middle
            else:
                high = middle
        return (low + high) / TWO
