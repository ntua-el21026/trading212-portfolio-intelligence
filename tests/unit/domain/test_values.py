from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from trading212_domain import (
    CurrencyCode,
    DomainError,
    FxRate,
    Instant,
    Money,
    Percentage,
    Price,
    Quantity,
    Ratio,
    canonical_json,
    decimal_string,
    exact_decimal,
    quantize_boundary,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "value",
    [
        1.1,
        float("inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        " 1.0",
        "+1",
        "01",
        "1e3",
        "1,000",
        "",
        True,
        object(),
    ],
)
def test_exact_decimal_rejects_binary_nonfinite_and_ambiguous_values(value: object) -> None:
    with pytest.raises(DomainError):
        exact_decimal(value)  # type: ignore[arg-type]


def test_exact_decimal_enforces_database_precision_and_scale() -> None:
    assert exact_decimal("99999999999999999999.123456789012345678") == Decimal(
        "99999999999999999999.123456789012345678"
    )
    with pytest.raises(DomainError, match="NUMERIC"):
        exact_decimal("0.1234567890123456789")
    with pytest.raises(DomainError, match="NUMERIC"):
        exact_decimal("999999999999999999999999999999999999999")


def test_decimal_serialization_is_canonical_and_never_uses_exponents() -> None:
    assert decimal_string(Decimal("1.230000")) == "1.23"
    assert decimal_string(Decimal("-0.000")) == "0"
    assert decimal_string(Decimal("0.000000000000000001")) == "0.000000000000000001"


def test_money_requires_explicit_matching_currency() -> None:
    eur = Money.parse("10.10", "EUR")
    assert eur + Money.parse("2.20", "EUR") == Money.parse("12.30", "EUR")
    assert eur - Money.parse("0.10", "EUR") == Money.parse("10", "EUR")
    assert eur.scale("2.5") == Money.parse("25.25", "EUR")
    with pytest.raises(DomainError, match="currency mismatch"):
        _ = eur + Money.parse("1", "USD")


def test_fx_conversion_is_explicit_directional_and_auditable() -> None:
    observed_at = Instant.parse("2026-01-02T03:04:05Z")
    fx = FxRate(CurrencyCode("USD"), CurrencyCode("EUR"), Decimal("0.8"), observed_at, "fixture")
    assert fx.convert(Money.parse("10", "USD")) == Money.parse("8", "EUR")
    assert fx.inverse().convert(Money.parse("8", "EUR")) == Money.parse("10", "USD")
    with pytest.raises(DomainError, match="does not match"):
        fx.convert(Money.parse("10", "GBP"))


def test_same_currency_fx_rate_must_be_one() -> None:
    with pytest.raises(DomainError, match="must equal one"):
        FxRate(
            CurrencyCode("EUR"),
            CurrencyCode("EUR"),
            Decimal("1.01"),
            Instant.parse("2026-01-01T00:00:00Z"),
            "invalid-fixture",
        )


def test_aware_time_is_normalized_to_utc_and_naive_time_is_rejected() -> None:
    local = datetime(2026, 3, 29, 4, 30, tzinfo=timezone(timedelta(hours=3)))
    instant = Instant(local)
    assert instant.value == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    assert canonical_json(instant) == '"2026-03-29T01:30:00Z"'
    with pytest.raises(DomainError, match="timezone-aware"):
        Instant(datetime(2026, 1, 1))


def test_value_objects_are_immutable() -> None:
    money = Money.parse("1", "EUR")
    with pytest.raises(FrozenInstanceError):
        money.amount = Decimal("2")  # type: ignore[misc]


def test_ratio_percentage_price_and_quantity_never_accept_float() -> None:
    assert Percentage.parse("12.5").as_ratio() == Ratio.parse("0.125")
    assert Price.parse("123.456", "EUR").value == Decimal("123.456")
    assert Quantity.parse("0.000001").value == Decimal("0.000001")
    for constructor in (
        lambda: Percentage.parse(1.2),  # type: ignore[arg-type]
        lambda: Ratio.parse(1.2),  # type: ignore[arg-type]
        lambda: Price.parse(1.2, "EUR"),  # type: ignore[arg-type]
        lambda: Quantity.parse(1.2),  # type: ignore[arg-type]
    ):
        with pytest.raises(DomainError):
            constructor()


def test_rounding_is_half_even_only_at_explicit_boundary() -> None:
    assert quantize_boundary(Decimal("2.345"), Decimal("0.01")) == Decimal("2.34")
    assert quantize_boundary(Decimal("2.355"), Decimal("0.01")) == Decimal("2.36")
    high_scale_fx_intermediate = Decimal("123.45") * Decimal("0.876543210987654321")
    assert quantize_boundary(
        high_scale_fx_intermediate, Decimal("0.000000000000000001")
    ) == Decimal("108.209259396425925927")
    with pytest.raises(DomainError, match="finite Decimal intermediate"):
        quantize_boundary(Decimal("NaN"), Decimal("0.01"))
    with pytest.raises(DomainError, match="binary float"):
        quantize_boundary(1.25, Decimal("0.01"))  # type: ignore[arg-type]
