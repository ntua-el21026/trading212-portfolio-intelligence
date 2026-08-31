# ADR-0004 — Deterministic Decimal Financial Engine

**Status:** Accepted  
**Date:** 2026-08-31

## Context

Portfolio values, cash flows, returns, weights, and optimizer outputs must be reproducible and cannot depend on language-model arithmetic or binary floating-point artifacts.

## Decision

Authoritative financial calculations are deterministic versioned code. Money, quantity, price, FX, ratios, and weights use exact Decimal/NUMERIC representations with explicit currency, valuation time, method, provenance, quality, assumptions, and warnings. The language model selects and explains tools but does not calculate authoritative values.

## Consequences

- JSON financial decimals serialize as strings.
- Cross-currency operations require explicit FX records.
- Rounding occurs only at declared boundaries.
- Reference and property tests are mandatory.
- Semantic calculation changes increment a calculation version and preserve historical attribution.
