"""Frozen ISO 4217 SIX numeric minor units; unavailable codes are not inferred."""

from decimal import Decimal
from types import MappingProxyType

from .errors import fail_validation
from .values import CurrencyCode, exact_decimal

CURRENCY_POLICY_VERSION = "iso4217-six-2026-01-01-v1"
CURRENCY_SOURCE_URL = "https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml"
CURRENCY_SOURCE_SHA256 = "838dfb991648cf36df939edd5fe3811737962b75a32252847d239cedd1e291c9"
CURRENCY_SOURCE_PUBLISHED = "2026-01-01"
CURRENCY_SOURCE_REVIEWED = "2026-09-07"
# Complete numeric entries in the pinned edition. N.A. and absent codes have no default.
CURRENCY_MINOR_DIGITS = MappingProxyType(
    {
        **dict.fromkeys(
            [
                "BIF",
                "CLP",
                "DJF",
                "GNF",
                "ISK",
                "JPY",
                "KMF",
                "KRW",
                "PYG",
                "RWF",
                "UGX",
                "UYI",
                "VND",
                "VUV",
                "XAF",
                "XOF",
                "XPF",
            ],
            0,
        ),
        **dict.fromkeys(
            [
                "AED",
                "AFN",
                "ALL",
                "AMD",
                "AOA",
                "ARS",
                "AUD",
                "AWG",
                "AZN",
                "BAM",
                "BBD",
                "BDT",
                "BMD",
                "BND",
                "BOB",
                "BOV",
                "BRL",
                "BSD",
                "BTN",
                "BWP",
                "BYN",
                "BZD",
                "CAD",
                "CDF",
                "CHE",
                "CHF",
                "CHW",
                "CNY",
                "COP",
                "COU",
                "CRC",
                "CUP",
                "CVE",
                "CZK",
                "DKK",
                "DOP",
                "DZD",
                "EGP",
                "ERN",
                "ETB",
                "EUR",
                "FJD",
                "FKP",
                "GBP",
                "GEL",
                "GHS",
                "GIP",
                "GMD",
                "GTQ",
                "GYD",
                "HKD",
                "HNL",
                "HTG",
                "HUF",
                "IDR",
                "ILS",
                "INR",
                "IRR",
                "JMD",
                "KES",
                "KGS",
                "KHR",
                "KPW",
                "KYD",
                "KZT",
                "LAK",
                "LBP",
                "LKR",
                "LRD",
                "LSL",
                "MAD",
                "MDL",
                "MGA",
                "MKD",
                "MMK",
                "MNT",
                "MOP",
                "MRU",
                "MUR",
                "MVR",
                "MWK",
                "MXN",
                "MXV",
                "MYR",
                "MZN",
                "NAD",
                "NGN",
                "NIO",
                "NOK",
                "NPR",
                "NZD",
                "PAB",
                "PEN",
                "PGK",
                "PHP",
                "PKR",
                "PLN",
                "QAR",
                "RON",
                "RSD",
                "RUB",
                "SAR",
                "SBD",
                "SCR",
                "SDG",
                "SEK",
                "SGD",
                "SHP",
                "SLE",
                "SOS",
                "SRD",
                "SSP",
                "STN",
                "SVC",
                "SYP",
                "SZL",
                "THB",
                "TJS",
                "TMT",
                "TOP",
                "TRY",
                "TTD",
                "TWD",
                "TZS",
                "UAH",
                "USD",
                "USN",
                "UYU",
                "UZS",
                "VED",
                "VES",
                "WST",
                "XAD",
                "XCD",
                "XCG",
                "YER",
                "ZAR",
                "ZMW",
                "ZWG",
            ],
            2,
        ),
        **dict.fromkeys(["BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"], 3),
        **dict.fromkeys(["CLF", "UYW"], 4),
    }
)


def monetary_quantum(currency: CurrencyCode, requested: Decimal | None = None) -> Decimal | None:
    if not isinstance(currency, CurrencyCode):
        fail_validation("A typed reporting currency is required.", field="currency")
    digits = CURRENCY_MINOR_DIGITS.get(currency.value)
    if digits is None:
        return None
    default = Decimal("1" if digits == 0 else "0." + "0" * (digits - 1) + "1")
    if requested is None:
        return default
    value = exact_decimal(requested, field="monetary_quantum")
    if value <= 0 or value > default:
        fail_validation(
            "Monetary quantum must not exceed the currency minor unit.", field="monetary_quantum"
        )
    # Compare exact values instead of normalize(), which uses ambient precision.
    if value not in tuple(
        Decimal("1" if scale == 0 else "0." + "0" * (scale - 1) + "1") for scale in range(19)
    ):
        fail_validation("Monetary quantum must be an exact power of ten.", field="monetary_quantum")
    return value
