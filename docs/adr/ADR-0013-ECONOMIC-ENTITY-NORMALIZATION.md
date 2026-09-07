# ADR-0013 — Economic Entity, Share-Class and Listing Normalization

**Status:** Accepted

**Date:** 2026-09-07

**Authority:** Current owner's Phase 2 design assignment

## Context

A company may have multiple share classes, exchange listings or depositary
receipts. Funds may hold these securities directly or through other funds.
Ticker grouping can both miss common exposure and merge unrelated securities.
Adding a fund wrapper to all its constituents double-counts economic exposure.

## Decision

Retain canonical instruments and listings and add owner-scoped economic entities,
share classes, explicit listing/share-class/receipt/issuer relationships,
classification assignments, fund definitions and immutable constituent snapshots.
Every mapping has evidence/source/version, effective interval and confidence.
Canonical identity, provider key, ticker, MIC, ISIN and issuer are separate typed
fields. No high-confidence entity resolution is inferred from ticker alone.
Ambiguous/unresolved mappings remain explicit and retain their valued exposure.
Mapping corrections append new versions; published calculations pin old versions.

Receipt relationships include an exact security-unit conversion ratio with
evidence. Ratios reconcile units when that conversion is required; do not
multiply a position's already converted monetary exposure by the ratio again.
Different classes/listings can map to a common economic entity for exposure
aggregation while retaining distinct securities for prices, currency, targets
and contribution allocation. A parent/issuer relationship does not automatically
mean identical equity economics; only the selected methodology's explicit
aggregation policy may traverse it.

Company look-through replaces the fund wrapper's company-classification path
with weighted constituent paths. Direct holdings and every indirect fund path
retain separate provenance and then aggregate by resolved economic identity.
This includes common exposure through different fund share classes without
double counting a wrapper. Missing constituent coverage, stale snapshots,
unresolved security mappings and unsupported nested funds remain explicit
unresolved buckets. Never relabel them cash or redistribute their weight to
known constituents. A user-selected normalized covered-only view is a separate
clearly labeled result and preserves absolute coverage alongside it.

ETF overlap aggregates entity weights within each fund first, then sums the
minimum common entity weight for each unordered pair. Pair identity is sorted
stably, and result coverage/confidence accompanies the value. Sector, industry,
country, region and economic-currency exposure use versioned classification
taxonomies; trading currency alone cannot establish company economic currency.
Snapshot and mapping selection obey the known-at-cutoff policy in
[ADR-0012](ADR-0012-MARKET-SOURCE-SNAPSHOTS.md).

## Consequences

Targets and pricing preserve security identity while X-ray can aggregate real
shared economic exposure. Explainable paths show where each effective weight
came from. Incomplete mapping reduces coverage rather than producing misleading
precision. Relational provenance and nested-fund checks add work but allow
deterministic corrections and safe reporting.

## Rejected alternatives

- Ticker-only grouping or all-listings collapse: creates false identity matches
  and loses security/currency distinctions.
- Counting wrappers and constituents together: overstates effective exposure.
- Renormalizing unknown weight into known holdings by default: hides missing
  coverage and can inflate concentration/overlap claims.
- Applying receipt ratios to already valued weights: counts the same conversion
  twice.
- Updating mapping rows used by finalized results: makes historical X-ray change
  without a new calculation/source version.

## Verification obligation

Test multiple listings/share classes, receipts, overlapping ETFs, nested funds,
same ticker/different entity, ambiguous evidence, stale/future snapshots,
classification revisions, incomplete coverage, weight conservation, deterministic
pair ordering, direct-plus-indirect deduplication and canonical report/API/MCP
parity with fully synthetic licensed fixtures.
