# ADR-0012 — Immutable Market, FX and Benchmark Source Snapshots

**Status:** Accepted

**Date:** 2026-09-07

**Authority:** Current owner's Phase 2 design assignment

## Context

Prices, FX, benchmark levels and fund constituents can be revised, arrive late,
use different calendars or have different license permissions. A mutable latest
series cannot establish what a calculation knew at its cutoff. Price basis and
currency errors can also create apparently plausible but incomparable returns.

## Decision

Persist normalized owner-scoped immutable source headers and observations with
exact Decimal/currency, provider/adapter/schema/license versions, effective time,
first-known retrieval time, coverage, basis and canonical semantic digest.
Definitions and versions for benchmarks are separate from provider observations.
Distinct raw-close, split-adjusted and total-return bases cannot substitute for
one another. FX explicitly identifies base and quote; inverse/triangulated
conversions pin their underlying observations and method. No cross-currency
calculation proceeds without sourced conversion or an explicit unavailable state.

Every calculation pins specific source IDs and versions plus source cutoff. A
source must be effective and first known no later than that cutoff; choose the
latest eligible declared revision with stable source identity tie-breaks.
Historical replay never selects a revision learned in the future. Corrections
append a new snapshot with its later knowledge time. Identical minimized content
reuses identity and appends retrieval occurrences, preserving original knowledge
time. Digests include semantic observations, basis, currency, source revision,
license/mapping version and schema; transport timing and arbitrary raw metadata
do not create economic revisions. Reproducibility records pin the retrieval
occurrence used to assess freshness separately from the semantic input digest.

Bounded daily periods, calendar alignment, return/FX conventions and gap policies
are versioned methods. Do not extrapolate missing history or use future
constituents to fill an earlier period. Stale/partial/estimated/unavailable states
remain explicit. Reference inputs never mutate a canonical broker snapshot or
turn a provider-reported figure into an internally calculated one without a
separate labeled result.

Storage/display/report/export permissions are immutable license-version inputs;
unknown permission denies the use. Enforce retention and attribution. If legal
deletion removes replay inputs, retain only permitted audit/digests and mark
dependent results non-reproducible. Semantic minimization precedes hashing:
credentials, signed URLs, raw bodies and their derivatives are never provenance.
The [provider contract](../integrations/PHASE_2_PROVIDER_CONTRACTS.md) requires
working replay adapters and safe unconfigured real-provider states.

## Consequences

Earlier results can be reproduced against exact known-at-cutoff inputs, and
provider corrections are visible rather than retroactively changing history.
Storage and join cost increases, bounded by retention and snapshot deduplication.
Availability may be lower than an unconstrained latest-data lookup; that is a
truthful quality result. Entitlements can prevent replay/export even when an
earlier summary remains legitimately retained.

## Rejected alternatives

- Upserting a latest price/FX/constituent row: destroys revision and knowledge
  history needed for reproduction and avoids neither licensing nor gap handling.
- Pinning provider names and dates only: cannot identify a revised dataset.
- Hashing raw HTTP responses: retains secret/URL derivatives and makes transient
  transport details change economic identity.
- Filling history from future observations: introduces look-ahead bias.
- Assuming one permission authorizes all uses: violates explicit license scope.

## Verification obligation

Test corrected-versus-identical source retrievals, late arrivals and cutoff
selection, timezone/calendar alignment, FX direction and missing pairs, basis
compatibility, gaps, staleness, semantic hash canaries, licensing at every use,
safe expiry and deterministic synthetic seeded reproduction.
