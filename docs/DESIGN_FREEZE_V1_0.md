# Design Freeze v1.0 — Premium Intelligence and Productization

**Status:** Accepted implementation design; runtime acceptance pending

**Date:** 2026-09-14

**Target:** 1.0.0; local candidate only

## Authority and baseline

The owner's Complete Phase 3 assignment authorizes P3-01 through P3-10 after
owner acceptance of corrected Phase 2 for progression. [ADR-0018](adr/ADR-0018-OWNER-AUTHORIZED-PHASE-TRANSITION.md)
records the authority and its limits. Actual clean starting main was
`d2ebdaf96d1b61aacea5c6492824946540f88803`. Governance delivery `30fe2ed` precedes
this additive freeze. It does not implement a premium package.

Keep v0.1, v0.2 and accepted ADRs except where this explicit delta supersedes a
named later-phase exclusion. Historical validation, independent review, owner
acceptance, current local evidence and production readiness remain separate.
Phase 3 does not inherit Phase 2 acceptance. GitHub Actions remains
`deferred_by_owner`, unverified. No Phase 4 is introduced.

## Permanent boundaries

Trading 212 remains precisely the ten sealed GET capabilities. No new broker
operation, arbitrary transport/path/query, redirect, signed-export following,
execution object, Pie write, transfer or payment is permitted. Default demo and
disabled Live remain unchanged. Internal writes never create broker commands.

PostgreSQL is authoritative. Typed domain/application services own canonical
values; web, MCP and reports project those values. Existing Decimal80,
Decimal160 target and Decimal256 exact-Xray profiles retain their semantics.
New approximate statistics and projections use the separately versioned
[ADR-0019](adr/ADR-0019-PREMIUM-NUMERICAL-METHODS.md) profile. Every financial
wire value remains a bounded exact decimal string, with currency, UTC source
cutoff, method/schema version, coverage, quality and provenance. Approximate
statistics do not become exact facts merely by using Decimal.

Observed historical statistics, deterministic shocks and probabilistic
projections are distinct result families. Missing inputs never become zero,
FX never defaults to one, listing currency never establishes economic currency,
and current knowledge never silently rewrites a pinned historical result.

## Required vertical capabilities

| Package | Required behavior |
| --- | --- |
| P3-01 | Canonical aligned simple/log returns, observed and modeled risk, volatility/downside/drawdown/beta/alpha, covariance/correlation, historical and parametric VaR/ES, concentration and reconciled risk contributions. |
| P3-02 | Immutable scenarios and source-bound runs, precedence/overlap/FX/sensitivity rules, historical replay, explicit coverage, editing/history/comparison and canonical report views. |
| P3-03 | Versioned assumptions/goals, bounded reproducible correlated simulations, timed cash flows/fees/inflation/rebalancing, uncertainty, probabilities/shortfalls/sensitivity and durable restart. |
| P3-04 | Exposure-ranked research, cited versioned events, owner notes/theses/catalysts/break conditions and review state; source facts and synthesis remain distinct. |
| P3-05 | Preserve all 25 MCP contracts; add only frozen premium reads and three bounded internal run commands, with accessible canonical widgets. |
| P3-06 | Installable responsive PWA, static offline shell, command palette, owned saved views, URL navigation and measured accessibility/performance. |
| P3-07 | Explicitly licensed typed market/FX/ETF/reference/research adapters with synthetic contracts, safe unconfigured states and observable authorized failover. |
| P3-08 | A second synthetic read-only broker, authorized multi-account consolidation, explicit FX and evidence-based internal transfer matching. |
| P3-09 | Internal adversarial tests, bounded jobs/queries, source/image/SBOM/provenance/signing machinery, resilience, physical retention and clean synthetic backup restoration. |
| P3-10 | Linear install/upgrade from 0016, exact-source local gates and parity, portable evidence, 1.0.0-target notes and independent-review/external-gate boundaries. |

## Ownership, immutable inputs and work

Every definition/version/run/source/goal/note/preference and selected account
belongs to an authorized owner. Composite references, immutable publication,
exact numeric columns, UTC times, uniqueness and audit supplement service checks.
Published changes append a version. Current grants and source entitlements are
rechecked on admission, execution, reads, downloads and replay, including after
revocation while work is queued. A source cutoff never grants access.

Reuse PostgreSQL transactional outboxes, fenced leases, bounded dispatch/consumer
attempts and idempotent publication. Redis loss may delay work, never erase the
logical job or duplicate its financial result. Only fixed typed task families
exist; no generic expression, model-selected tool, URL or executable payload.
Bound assets, points, iterations, attempts, rows, bytes and per-owner capacity
before execution, and preserve accounting across chunks/restarts. A partial
calculation cannot be published as a successful complete result.

## Privacy and product behavior

Fetched research is untrusted content, not policy or an authorization channel.
External models are disabled without explicit configuration and minimized
inputs; private portfolio data is not sent by default. Credentials resolve
through designated secret ports. Provider text cannot select destinations,
invoke tools or construct financial values in a canonical result.

The PWA caches only an explicit public static shell/asset allowlist. Authenticated
HTML, account APIs, reports and tokens are never cached for offline use. Account
switching, logout and browser navigation preserve authorization and isolation.
Charts have server-value tables, visible quality/gaps, keyboard focus, reduced
motion and responsive layouts. Unsupported notifications remain visibly unavailable.

## Completion and resource discipline

Design acceptance is permission to implement, not evidence of implementation.
Each package has separate implementation, local validation and external gates.
One final immutable implementation source/tree must pass the complete applicable
local gates; later documentation requires non-documentation content/type/mode
equivalence. Governance scripts count as executable code. Retain actual original
logs, node IDs, coverage, captures, scan scope, resource and recovery receipts in
a portable sanitized pack; a checksum alone does not prove execution.

Use the existing task Compose project and serial laptop verification, reusing
necessary services. Remove only inspected obsolete task resources; preserve
source, dependencies, current images, evidence and unrelated data. No global prune.
Paid services, public deployment/release/tag, ChatGPT registration, production
restore and Live activation require separate external authorization/evidence.
