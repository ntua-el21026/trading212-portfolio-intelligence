# Research report selection — accepted owner decision

**Status:** Accepted for implementation by explicit owner decision on
14 November 2026. Runtime verification and Phase 3 acceptance remain pending.

**Scope:** Consolidated Implementation Batch 1, P3-S24/P3-S26 and
P3-RESEARCH-001/P3-RESEARCH-003.

## Existing authority

[ADR-0026](../adr/ADR-0026-PREMIUM-REPORT-PROFILES.md) permits a typed research
family on the existing six premium `/api/v2` report routes and explicit
`report_sections_v3` document profile. Research must bind retained X-ray,
source-event and note-revision evidence without inventing a research run.
[ADR-0031](../adr/ADR-0031-RESEARCH-ITEMS-AND-RETENTION.md) makes an item identity
bind an account, immutable event revision, saved X-ray pin and cutoff. The current
item view additionally resolves current owner-note heads and current review state.

Selecting only `item_id` therefore leaves two materially different report-content
and semantic-retry policies. This proposal settles that choice before code depends
on it; it does not change financial calculations or licensing rights.

## Recommended decision: exact revision selection

One research report selects:

- One existing `item_id`, whose exact event revision, account, X-ray input/result
  identities/digests and cutoff are retained in the report binding.
- An explicit ordered-canonical set of zero to 64 exact `note_revision_ids`.
  Each revision must belong to the same authorized owner/account/entity. There
  is no implicit latest-note lookup or substitution. An empty set means no owner
  notes were selected, rather than claiming the owner has no notes.
- An optional exact `review_acknowledgment_id` for the selected event revision
  and account. Omission means review evidence was not selected, rather than
  claiming the event is unreviewed.

The research selector is a new closed profile3 binding variant; it is not a
`run_id`. Selected revision identities participate in new research request
semantics. Exact retries return the original admitted capture; changed selected
identities with the same semantic key conflict. Later note/review changes never
silently replace captured content. Foreign, erased, missing or unavailable pins
fail safely, with permission checks before private decoding.

Use the existing PDF, CSV, XLSX and JSON report artifacts, renderers, worker,
download grants and limits. Reuse the premium REST routes and report workspace.
This does not add a separate generic dataset-export API, extra provider operation,
MCP tool/resource, optional synthesis or service. Original V1/profile2 and earlier
profile3 bytes, request identities, schemas' existing meanings and the original
25 MCP descriptors remain preserved. The MCP inventory remains 38 tools and
11 resources.

Capture complete selected source facts, canonical portfolio evidence, selected
owner revisions and optional review proof in fixed versioned tables, preserving
content kinds, dates, quality, provenance and explicit unavailable states. Keep
the existing 32 MiB document, 2 MiB manifest, 256-license, table/format/artifact
bounds. Over-bound complete evidence is rejected rather than truncated.

Pinned and current STORE/DISPLAY/REPORT permissions, research capability grants,
current account grants and transitive X-ray rights must hold before decoding and
at final capture/read/download boundaries. EXPORT remains an additional use only
for an actual export contract, as ADR-0026 specifies. A format does not grant a
license use. Provider and owner-note erasure remove dependent forbidden report
copies within the existing shared physical cleanup budgets; denial is immediate.
Original semantic-source lifetimes, current/pinned licenses, retained X-ray
deadlines and report TTL clamp every derived copy. No retrieval/copy renews time.

## Alternative: snapshot current heads at first admission

One `item_id` would resolve all current eligible note heads and review state at
the first admission transaction. It would need a separately specified complete
selection rule, bound/overflow behavior, captured-head set and retry semantics.
Later retries would retain the first capture, even if current notes changed.
This is feasible but gives the same item selection a broader implicit meaning.

## Owner decision and required verification

The owner approved exact revision selection above. The current-head alternative
is retained as decision context and is not an implicit fallback. This approval
authorizes the bounded implementation; it does not certify runtime evidence,
acceptance rows/scenarios, licensing rights or production readiness.

Implementation after approval requires original failure evidence and focused
domain/codec, real PostgreSQL, REST/generated-client, report-workspace and four-format
tests. Verify cross-owner/current-grant/source-use denial before decoding; exact
replay/conflict; all-source/selected-note provenance; original deadlines; erasure
and bounded physical closure; artifact safety and legacy profile compatibility.
All Phase 3 acceptance rows/scenarios remain pending until independent review
and explicit owner acceptance.
