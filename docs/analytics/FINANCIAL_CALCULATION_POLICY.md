# Financial Calculation Policy

**Status:** Accepted normative contract

## 1. Purpose

Define the non-negotiable numerical, temporal, currency, provenance, quality, and reproducibility rules for every authoritative portfolio calculation.

## 2. Determinism

For identical canonical inputs, valuation timestamp, reporting currency, calculation version, and options, a calculation must produce identical authoritative decimal results and warnings.

The language model never performs authoritative portfolio arithmetic. It may select a calculation tool and explain returned structured results.

## 3. Numeric representation

- Python `Decimal` or database exact `NUMERIC` is mandatory for money, quantity, price, FX, weights, ratios, and authoritative derived values.
- JavaScript `number` must not be the source of truth for authoritative financial values; clients parse/store decimal strings using a decimal-safe library or format server-provided display values.
- Inputs must be finite and validated for declared scale/range.
- No implicit conversion from float to Decimal.
- Aggregation uses full retained precision, then rounds only at declared output/accounting boundaries.

The narrow [ADR-0017](../adr/ADR-0017-DECIMAL256-EXACT-XRAY.md) policy registers
`xray_v1` 1.1.0 / `xray_decimal256_exact_q18_v1`. Its closed financial coefficient
operations are Decimal-only in a fresh fully specified local precision-256 context.
Private exact state uses role-bounded integral Decimal strings, separate from Q18
public/normalized NUMERIC fields. Ordinary precision 80 and target precision 160 stay unchanged;
Python integer/Fraction financial arithmetic is test-oracle-only. Reject oversized
zero representations before arithmetic and canonicalize admitted zero positively.

## 4. Currency

Every monetary value includes an ISO-4217 currency. Operations obey:

- addition/subtraction: same currency only;
- comparison: same currency or explicit conversion;
- conversion: explicit FX rate, direction, source, observation timestamp, and policy;
- reporting-currency totals: component conversion details or reproducible FX references retained;
- unavailable FX: metric becomes partial/unavailable, not silently treated as 1:1;
- instrument trading currency is not automatically equivalent to underlying economic currency exposure.

## 5. Rounding

Default calculation rounding mode is `ROUND_HALF_EVEN` unless a provider/accounting contract requires another explicit mode.

- Do not round intermediate portfolio sums merely for display precision.
- Display precision is separate from stored/calculated precision.
- Allocation residual caused by displayed rounding is reported where material.
- Optimizer order amounts obey broker/minimum-increment constraints only in Phase 2 output rounding and then recompute post-rounding drift.
- Currency minor units are presentation/accounting metadata, not a license to discard fractional internal values prematurely.

X-ray rounds once through exact Decimal divmod and doubled-remainder/quotient-parity
HALF_EVEN. Reject a rounded coefficient >=10^38 after carry, including negative
outputs. Exact coefficients drive conservation, ranking and thresholds; disclosed
signed residuals and rounded lower bounds do not replace that proof or invent mass.

## 6. Time and valuation

- All instants are UTC internally.
- A result uses one explicit `valuation_at` and `source_cutoff_at` model.
- Inputs observed after the source cutoff are excluded from that result.
- Date-based cash flows use documented timing convention for TWR/MWR.
- Market-close versus intraday valuations are never mixed without warning/method.
- Snapshot comparison uses comparable reporting currency and calculation version or states the transformation.

## 7. Sign conventions

Canonical external cash-flow convention from the portfolio's perspective:

- deposit/contribution into portfolio: positive external flow;
- withdrawal from portfolio: negative external flow;
- buys/sells: internal portfolio exchanges, not external contributions;
- dividend received: internal investment income, not an external contribution;
- fees/taxes: negative economic effects;
- transaction `net_cash_amount` sign is normalized and tested independently of provider sign conventions.

API schemas name direction explicitly and avoid undocumented negative-value conventions.

## 8. Observed versus derived values

Every field/metric is classified as:

- `observed_provider`;
- `normalized_provider`;
- `derived_deterministic`;
- `estimated`;
- `unavailable`.

Provider-reported P/L and internally derived P/L may coexist with distinct names/provenance; the system does not overwrite one with the other.

## 9. Calculation result metadata

Every authoritative result carries:

- calculation name and semantic version;
- calculated timestamp;
- valuation timestamp;
- source cutoff;
- reporting currency;
- input snapshot/source identifiers or reproducible query key;
- method/options;
- assumptions;
- coverage period;
- data-quality state;
- warnings and missing inputs;
- residual/reconciliation value when applicable.

## 10. Quality propagation

A calculation cannot be higher quality than its material inputs.

Illustrative precedence (most severe wins subject to metric-specific rules):

```text
FAILED > UNRECONCILED > PARTIAL > ESTIMATED > STALE > FRESH
```

This is not blindly ordinal: a stale non-material reference record need not degrade an unrelated metric. Each calculation documents material dependencies and quality propagation.

## 11. Missing data

- Missing is never zero.
- Unknown cost basis does not imply zero cost.
- Missing fees/taxes make net-return decomposition partial.
- Incomplete broker history constrains net-contribution and realized-performance coverage.
- Unmapped instruments remain included in total value where observed, but classification/X-ray becomes partial.
- Unsupported corporate actions produce reconciliation discrepancies.

## 12. Tolerances

Reconciliation/comparison tolerances are explicit, versioned, currency/quantity aware, and justified. Tolerance may classify immaterial rounding difference; it must not alter stored source values or hide systematic residuals.

## 13. Calculation registry

Implementation maintains a registry containing:

- stable calculation ID;
- current semantic version;
- input schema/version;
- output schema/version;
- method summary;
- quality policy;
- reference fixtures;
- compatibility/migration notes.

A semantic change increments calculation version. Historical results remain attributable to their original version.

## 14. Required Phase 1 calculations

- position market value;
- account/portfolio total aggregation;
- cash/invested split;
- direct position and cash weights;
- net external contributions over covered history;
- provider and internally derived realized/unrealized/dividend fields only at documented coverage;
- snapshot change;
- core MWR/TWR summary only when prerequisites are satisfied;
- reconciliation residuals and quality summary.

## 15. Validation

Required evidence:

- hand-calculated reference portfolios;
- property-based tests for conservation, weights, currency constraints, and cash-flow invariants;
- high-precision/rounding edge cases;
- negative values, fractional quantities, zero-value portfolio, missing FX, and partial history;
- timezone/DST/date-boundary cases;
- cross-interface parity;
- independently implemented verification for critical return algorithms where practical.
