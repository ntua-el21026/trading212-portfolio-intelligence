# ADR-0018 — Explicit Owner-Authorized Phase Transition

**Status:** Accepted  
**Date:** 2026-09-14  
**Authority:** Owner's Complete Phase 3 assignment

## Decision and scope

The owner accepted corrected Phase 2 implementation
`f88b0199b2d8691ff89101b7991e9bb0fea1d1ca`, tree
`5ac0dba52e369a30a32a2d7d5b41409e12fc0911`, delivered at
`d2ebdaf96d1b61aacea5c6492824946540f88803`, for progression to all ten Phase 3
packages. Preserve the [owner decision](../implementation/evidence/phase-3-owner-authorization-20260914.json)
and the [prior selector observations](../implementation/evidence/phase-3-start-d2ebdaf.json).
The decision quotes the current assignment; its digest identifies that input.
The validator checks declared consistency against this reviewed authority record.
It does not independently authenticate a human decision or attest execution.

Status schema 2 supports this specific Phase 2 to Phase 3 transition. It retains
schema 1 validation for historical contracts. Authority, decision, scope, accepted
source/tree/delivery and evidence reference are closed fields. An arbitrary
rehashed agent approval, unsupported transition or copied validation result
cannot authorize progression. A later owner decision requires a corresponding
explicit policy change and new immutable evidence; never modify this record.

The existing 3998426 ledger and corrected f88b019 artifact retain their original
bytes, counts and claims. The prior active selector values remain in the start
record and under explicitly historical compatibility scopes. Phase 2's owner
acceptance is separate from that historical ledger and from the new candidate.

The reported independent review covered R-01/R-02 code corrections and found no
new blocker in its inspected scope. Full local archives were not independently
inspected and all gates were not independently rerun. Do not turn this report
into independent full-release verification.

Phase 3 targets 1.0.0 with its own implementation, source/tree, local evidence and
pending independent review. The Phase 2 owner decision grants no Phase 3
acceptance. GitHub Actions remains deferred_by_owner and unverified. Production
readiness is not_authorized; public deployment/release/tag, paid providers and
Trading 212 Live remain outside this authorization.

## Verification obligations

Preserve existing status and historical Phase 2 design mutation contracts.
Exercise the legitimate transition plus wrong source/tree/delivery, wrong owner,
wrong scope, unsupported phase, altered/rehashed approval, missing corrected
local evidence, one-sided status changes, inherited acceptance and false
CI/production claims. A completed package still requires its own inspectable
source-bound evidence. Governance scripts are executable code and require
formatting, lint, typing and tests before direct-main delivery.
