# ADR-0016 — Bounded Internal MCP Plan and Report Commands

**Status:** Accepted

**Date:** 2026-09-07

**Decision authority:** Owner's current two-stage assignment, Phase 2 section 18

**Implementation status:** Pending; this ADR accepts a contract, not runtime evidence

## Context

Phase 1 exposes exactly nine observational portfolio tools. Phase 2 requires
fourteen additional reads and two explicitly authorized internal side effects:
creating a manual contribution plan and generating a private portfolio report.
An annotation that calls these writes read-only would mislead clients. Allowing
a generic command, refresh, target/rule editor, broker request or external
notification tool would exceed the owner's exact registry and security boundary.

ADR-0001 permanently seals Trading 212 behind its ten fixed GET capabilities.
ADR-0006 requires canonical application services across interfaces. The owner
assignment permits internal target/plan/report/rule records while preserving
broker read-only behavior. These requirements are compatible; an internal plan
or report record is not a broker operation.

## Decision

Freeze the [Phase 2 MCP registry](../integrations/PHASE_2_MCP_TOOL_REGISTRY.md)
at exactly 25 names: the nine existing tools, fourteen new reads and only
`create_contribution_plan` and `generate_portfolio_report` as commands.
Preserve the existing nine wire contracts. The Phase 1 contract's prohibition on
MCP application mutation is superseded only for these two named Phase 2 commands;
all broker prohibitions and other Phase 1 safety requirements remain normative.

Both commands have `readOnlyHint=false`, `destructiveHint=false`,
`idempotentHint=true` and `openWorldHint=false`. All 23 reads use
`readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true` and
`openWorldHint=false`. These descriptors report implemented semantics; they are
not permission grants and never replace service authorization.

A command validates a bounded strict input object and authenticated principal,
checks all tool scopes and owner/account/input-reference authorization, pins
immutable canonical inputs, and atomically stores a durable application record,
idempotency identity and safe audit event. Any asynchronous execution intent is
committed through the transactional outbox in the same database transaction.
No record is acknowledged before commit; a publication failure cannot lose the
job. Consumers reauthorize the persisted scope/account and validate immutable
input references before execution. Operational retries cannot change financial
inputs or elevate their quality.

`create_contribution_plan` requires `portfolio:read`, `targets:read`,
`analytics:read` and `plans:write`; it calls `CreateContributionPlan` and returns
the created plan/request/job IDs and current state, with a finalized revision ID
only once that immutable result exists. Execution state
`queued|running|succeeded|failed|expired|cancelled` is separate from the eventual
plan outcome `optimal|feasible_nonoptimal|infeasible|unavailable|failed`; a queued
response has null outcome and no fabricated plan data. It computes/persists non-negative
manual value allocations and residual cash using the frozen optimizer. It does
not produce broker order objects or translate values into order instructions.
A finalized plan cannot be edited in place. Infeasibility is a structured outcome
with reasons, not a fabricated feasible allocation.

`generate_portfolio_report` requires `portfolio:read`, `analytics:read`,
`reports:write`, `activity:read` and `targets:read` conservatively across the
allowed sections. It calls `GeneratePortfolioReport` and returns the report job
ID and state, with report ID/manifest hash only when available. Report reads and
downloads independently require `reports:read` and current owner/account
permission. Generation never implies a grant to fetch another owner's artifact.
It uses existing canonical inputs and the configured private artifact store;
the accepted default is bounded PostgreSQL `BYTEA` storage (10 MiB/artifact,
25 MiB/job, seven-day default and thirty-day maximum retention). Optional private
object storage preserves the same authorization and expiry contract. Generation
does not create/fetch a broker export, ingest providers, email recipients,
configure webhook destinations or publish a public artifact.

## Idempotency and safe retry

The required key is a bounded non-secret ASCII token. Durable uniqueness covers
owner, account, operation and key; the stored canonical input digest includes
all financial parameters, version/cutoff/currency/source references and relevant
constraints/sections. A repeated identical request returns the original logical
plan/report job. A reused key with different canonical inputs returns the stable
idempotency conflict before new work is inserted. Different owners/accounts
cannot use a collision to discover or reuse each other's record.

Concurrent requests, delayed publication and duplicate worker delivery produce
one logical record and one logical artifact/event, using database uniqueness,
transactional claims and consumer idempotency. Retry attempts and transport
correlation IDs are operational metadata, not new plan revisions. An explicit
recalculation/new report request uses a new key and preserves prior immutable
results. An expired report remains expired on an identical retry; creating a
new authorized generation requires a new key. Command replay never silently
extends retention or resurrects deleted artifacts.

## Bounded disclosure and resources

Strict schemas reject unknown nested fields, arbitrary URLs/paths/SQL/shell,
provider payloads, user-supplied owners and executable templates. Exact money,
quantity, FX, ratios and weights travel as validated decimal strings. Output
includes applicable reporting currency, immutable input references, calculation
and source times, method/version, coverage, quality, assumptions and warnings.
A queued job uses an explicit pending state rather than invented financial data.

Resource IDs are opaque references authorized on every lookup. Tool results
contain no provider signed URLs, storage keys, credentials, public artifact URLs
or generic filesystem access. The fixed versioned widgets in the registry only
render canonical structured results under strict CSP; they add no network or
command capability. Authenticated report downloading remains in the application.

Bearer authentication remains mandatory outside restricted local/test mode;
cookie-authenticated application counterparts additionally enforce CSRF.
Missing scopes, revoked access, cross-owner/account references and invalid
idempotency keys fail before persistence/provider dispatch. Audits contain safe
operation/outcome/opaque correlation metadata, never raw request bodies or
secrets. Model/provider text is untrusted data and cannot change scope or method.

## Delivery and acceptance

A vertical package may expose its exact tool after its underlying capability is
complete and verified. Unimplemented tools remain absent. P2-09 alone accepts
the complete 25-tool registry after descriptor/schema, scope/owner negatives,
API/MCP/report parity, concurrent retry/crash-window, CSP/accessibility and broker
transport-spy tests pass. No successful no-op tool satisfies this ADR.

The forty-scenario ledger and P2-10 exact-SHA gates provide release evidence.
Public HTTPS/OAuth ChatGPT registration and actual external delivery remain
separate explicit external gates; they do not prevent local protocol tests.

## Consequences and rejected alternatives

The host can accurately distinguish observations from internal writes while
both retain the permanent no-execution boundary. The exact registry limits
product scope and makes descriptor drift directly testable. Durable records and
idempotency add persistence and concurrency obligations; they prevent retry
amplification and lost work.

Rejected alternatives are annotating internal writes as read-only, using an
unbounded generic command, returning unsigned/public storage access, accepting
model-generated provider URLs, registering placeholder tools, or adding broker
execution/target editing/notification delivery to MCP. None is needed for the
owner's specified Phase 2 use cases.
