# Portfolio X-Ray

**Status:** Accepted Phase 2 design; not Phase 1 implementation scope

The executable release 0.2.0 contract is the
[Phase 2 methodology](PHASE_2_METHODS.md), with immutable source selection under
[ADR-0012](../adr/ADR-0012-MARKET-SOURCE-SNAPSHOTS.md) and economic identity under
[ADR-0013](../adr/ADR-0013-ECONOMIC-ENTITY-NORMALIZATION.md).

## Objective

Calculate true direct and indirect economic exposure by combining direct positions with ETF constituent data and normalized instrument/entity mappings while making coverage, date, source, and mapping confidence visible.

## Exposure graph

```text
Portfolio
  → account positions
  → listing
  → canonical instrument
  → fund constituent snapshot (when instrument is a fund)
  → constituent instrument/entity
  → issuer/parent/share-class normalization
  → classifications: sector, industry, country, region, currency
```

Every edge stores source, effective date, weight, and confidence.

## Core calculations

For direct portfolio weight \(w_f\) in fund \(f\), and constituent weight \(c_{f,j}\):

\[
w^{indirect}_{j} = \sum_f w_f c_{f,j}
\]

Effective exposure combines direct and indirect exposure after entity normalization:

\[
w^{effective}_{j} = w^{direct}_{j} + w^{indirect}_{j}
\]

Uncovered fund weight remains an explicit `unresolved_fund_exposure` component. It is not redistributed across known constituents unless a separately labeled normalized view is requested.

## Required capabilities

- direct versus indirect company exposure;
- ETF overlap matrix and duplicated exposure;
- issuer/parent, share-class, ADR, and listing normalization;
- effective sector/industry/country/region/currency exposure;
- top underlying entities;
- coverage by portfolio value and constituent weight;
- constituent snapshot dates and provider versions;
- mapping-confidence distribution;
- unsupported/opaque instruments;
- comparison against configured concentration thresholds.

## Identifier strategy

Preference order depends on asset class but may use provider instrument ID, ISIN, exchange MIC+ticker, LEI/entity mappings, issuer references, and manually reviewed overrides. Ticker-only mapping is not accepted as high confidence.

Manual mapping overrides are versioned, attributed, reviewable, and never mutate raw provider data.

## Data-quality policy

A result includes:

- direct-portfolio coverage;
- fund look-through coverage;
- constituent-weight coverage;
- stale constituent snapshots;
- unmapped listings/entities;
- classification coverage;
- inferred mapping count/value;
- total unresolved exposure.

`100% exposure` may be claimed only when weights and mappings reconcile within documented tolerance.

## Caching and history

ETF constituent snapshots are immutable by provider/fund/effective date/version.
Historical portfolio X-ray uses a snapshot effective for the valuation date and
known by the explicit source cutoff. Release 0.2.0 does not use future
constituents to fill earlier history; missing eligible inputs remain unavailable
or partial. An older eligible snapshot may be stale, with its age and quality
disclosed under the versioned method.

## Safety/licensing

Provider license and redistribution restrictions control persistence, export, UI detail, and report behavior. No constituent data is scraped or redistributed contrary to terms.

## Acceptance tests

- overlapping ETFs plus a direct holding;
- multiple listings/share classes normalized to one entity;
- stale/missing constituent data;
- constituent weights below/above unity with cash/other bucket;
- unmapped and low-confidence mappings;
- no redistribution of unresolved weight in absolute view;
- deterministic aggregation and exact residual;
- portfolio-value coverage and API/MCP/report parity.
