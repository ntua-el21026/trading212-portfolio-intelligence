# ADR-0010 — Immutable Hierarchical Virtual Targets

**Status:** Accepted

**Date:** 2026-09-07

**Authority:** Current owner's Phase 2 design assignment

## Context

Virtual Pies require nested groups, cash and canonical holdings while preserving
the exact target used by earlier drift, plans and reports. Editing published
weights or flattening the hierarchy into a mutable document would make those
results irreproducible. Broker Pies remain outside the write boundary.

## Decision

Use owner-scoped normalized virtual portfolios, target versions, nodes, holdings,
mapping decisions, typed constraints, exclusions, validations and audit events in
the [Phase 2 data model](../architecture/PHASE_2_DATA_MODEL.md). A private template
may omit account association; analytical use pins an authorized account-bound
portfolio and immutable published target version. Canonical instrument identity
and optional listing preference are separate. Unresolved mappings are explicit;
their dependent outputs cannot claim complete coverage.

The portfolio is a conceptual root at depth zero without a node row or weight.
There are at most 256 actual target nodes. Top-level nodes have depth one and
maximum leaf depth is eight: at most eight relative sibling-weight factors.
Groups have children; holdings/cash do not. Parent links stay in the same version;
cycles, unreachable nodes, invalid sibling order and overlapping holding selectors
fail validation. A holding selects one canonical instrument and optionally one
listing; per instrument allow one instrument-wide leaf or distinct listing
leaves, never both. Funding preference is separate and must satisfy this selector.
Unresolved/ambiguous mappings may have no canonical instrument; resolved ones
must have one. At most one explicit cash leaf exists at top level in
reporting currency. When absent, analytics still includes observed cash with target zero;
the service does not insert or modify a target node.

Weights are Decimal fractions stored as `NUMERIC(38,18)`. Every sibling set has
positive sum and must sum exactly to one to publish. Only explicit
`normalize=true` permits a residual with absolute magnitude at most `1e-12`.
Divide by the original sum, floor to `1e-18`, and distribute remaining units by
descending discarded remainder with ascending stable node-key ties. Persist
original weights, sums, adjustments and validation method. Other residuals fail;
there is no silent normalization or implicit cash balancing.

Authoritative arithmetic retains explicit local precision 80 with half-even
rounding; it never depends on or mutates process-global Decimal context. Exact
path products/sums temporarily use precision 160: eight scale-18 factors require
at most 144 fractional digits. Output effective leaf weights round to `1e-18`
and disclose `effective_weight_rounding_residual = 1 - sum(reported weights)`.
Authoritative algorithms reconstruct exact path products from the immutable
sibling weights. They do not normalize rounded leaf weights or hide residuals.

Draft changes require optimistic revision/If-Match and append audit in the same
transaction. Publication locks portfolio/draft, checks its exact validated digest,
seals all content and appends lifecycle events atomically. Validation retains
input/result revisions and digests, and publication checks the result revision.
Issue/normalization history retains stable node/constraint keys and copied values,
not foreign keys to replaceable draft nodes. Published nodes,
weights, mappings, constraints, reporting currency and effective time are
immutable to application roles. Corrections clone a new version. Scheduled,
active, superseded and archived states are projections of append-only lifecycle
events, not content updates. Publishing an already-effective version activates it;
a future version activates once through bounded scheduled processing. Activation
and supersession select one active version with actual knowledge time recorded.
Archiving the active version clears current selection without falling back to a
superseded version; a new activation is required. Archiving scheduled content
prevents activation. Superseded/archived content cannot reactivate; clone a new
version. Portfolio archive disables current selection and scheduled activation.
Historical ID-based access and prior results retain their selected version;
earlier effective times cannot backdate publication knowledge.

## Consequences

Plan/report reproduction can identify exact target content. Relational ownership,
tree and identity constraints are testable independently of request validation.
Draft editing remains convenient through bounded atomic content replacement;
published changes require a new version and explicit comparison. Lifecycle
projections can be rebuilt from events without rewriting financial history.

## Rejected alternatives

- Mutable published weights or JSON trees: invalidate prior results and weaken
  ownership/reference constraints.
- Silent sibling/leaf renormalization: hides user errors and changes targets.
- A weighted root at depth zero plus eight child levels: creates nine weighted
  factors and contradicts the frozen depth/precision bound.
- Multiple unexplained cash leaves: cannot assign observed account cash to
  separate groups without inventing allocation ownership.
- Mirroring edits to broker Pies: violates the strictly read-only product boundary.

## Verification obligation

Test owner/account composite references, cycles/depth/node bounds, exact/tolerance
boundary sums, deterministic normalization, context/rounding residual, concurrent
publication, If-Match retries, database-level published immutability, scheduled
activation, unresolved mappings, version comparison and canonical API/MCP parity.
