# Phase 2 MCP Tool Registry

**Status:** Accepted design contract, 2026-09-07

**Target:** `0.2.0`; exact final registry size **25**

**Implementation acceptance:** Pending; the validated Phase 1 runtime has nine tools

This contract extends [the Phase 1 MCP contract](CHATGPT_MCP_APP.md) under
[ADR-0016](../adr/ADR-0016-INTERNAL-MCP-COMMANDS.md). It preserves all nine existing
names, arguments, scopes and response semantics and adds exactly fourteen reads
and two internal commands. No aliases, optional broker tools or generic query
capabilities are registered. The product name “virtual Pie” maps to the canonical
`virtual_portfolios` resource; it never refers to a mutable Trading 212 Pie.

## Exposure and compatibility

A complete vertical capability may register its specified tools after its real
service/schema/auth/negative/parity tests pass. An unimplemented tool is absent,
not a successful placeholder. Contract tests at each increment assert the exact
implemented name set; P2-09 requires the complete 25-name set. The original nine
tools remain present throughout. P2-09 acceptance is not inferred from a subset.

The remote transport remains authenticated and fail-closed. Every tool invokes
one canonical application use case, never an HTTP route, database session,
provider transport or separate analytics implementation. API, workers, reports,
web and MCP share the same use cases and immutable input references.

## Shared wire and authorization rules

All new input/output objects forbid unknown fields at every nesting level.
Inputs are strict: UUID strings for resource IDs, RFC 3339 timezone-aware UTC
instants, ISO dates, three-uppercase-letter currencies and finite base-ten
decimal strings. Binary JSON numbers are rejected for financial values; strings
are validated against exact `NUMERIC(38,18)` domain precision/range (at most
20 integer digits and at most 18 fractional digits; no exponent/NaN/infinity). No caller-supplied
owner/principal/scope field is accepted. IDs never substitute for authorization.

`P` means `portfolio:read`, `A` means `activity:read`, `T` means `targets:read`,
`N` means `analytics:read`, `PW` means `plans:write`, `RR` means `reports:read`,
`RW` means `reports:write`, and `AR` means `alerts:read`. These abbreviations are
for the table only; descriptors advertise the complete exact scope strings.
`targets:write` and `alerts:write` belong to authorized API/web management and do
not authorize extra MCP tools. `plans:write` does not authorize target edits.

Every scope in a tool's row is required. The principal owner must own the account
and every referenced portfolio, version, source snapshot, plan, report, rule or
benchmark selection. Cross-resource account/version mismatches fail before data
is returned or a command is persisted. List predicates include owner/account in
the query. The two virtual-portfolio reads permit `account_id=null` solely for
owner-private templates; their conservative `P,T` scope requirement remains.
No template operation grants access to a different account. A virtual portfolio
has at most 256 target nodes; its conceptual root is depth zero and is not a
weighted stored node, with top-level depth one and maximum leaf depth eight.

New bounded profiles:

| Profile | Contract |
|---|---|
| `Page` | `cursor: string|null` up to 2048 characters; `limit: integer` 1–100, default 25. Signed stable continuation binds owner/account/resource, immutable snapshot/version, filters and sort. Hard owner capacity applies on first and later traversals. |
| `Window` | Explicit inclusive `start_date`, `end_date`, with `0 <= end-start <= 3660 days`; explicit `source_cutoff_at` UTC. Reject inverted, naive or look-ahead selectors. Daily output is at most 3661 observations; requests beyond the bound require another bounded window. |
| `Top` | `top_n: integer` 1–50, default 25. Full eligible-set aggregates precede a bounded sample; disclose omitted counts/weight and never label truncated detail complete. |
| `Snapshot` | Required authorized `account_id`, `snapshot_id`; the snapshot is immutable and determines valuation time. Cross-source calculations additionally pin authorized source snapshots or a resolved immutable source bundle. |
| `Target` | Required `virtual_portfolio_id`, `target_version_id`, owned together; published immutable version and account association must match the snapshot. |
| `Idempotency` | Required `idempotency_key`, 1–180 ASCII characters matching `^[A-Za-z0-9._:-]+$`; no secrets. Same owner/account/operation/key and canonical input returns the same durable record; a changed payload conflicts. |

New tool input size is at most 64 KiB and serialized output at most 2 MiB. Bounded
arrays and text fields are checked before dispatch/serialization; oversized
results return a safe capacity error and no partial JSON. Per-table page and
summary bounds apply within this envelope. Existing nine tool limits and date
policies remain unchanged. No arbitrary sort key, expression, SQL, path, URL,
regex query, freeform prompt, renderer code or provider configuration is accepted.

## Annotation profiles

The emitted MCP wire annotations are explicit on every descriptor:

| Profile | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` |
|---|---|---|---|---|
| `READ` | `true` | `false` | `true` | `false` |
| `COMMAND` | `false` | `false` | `true` | `false` |

`READ` denotes observational application behavior; bounded cache/audit/collection
bookkeeping does not modify the user's targets/plans/reports or call a broker.
`COMMAND` creates only a new internal immutable plan or report job. Neither
command deletes/replaces user work, contacts providers, sends notifications or
publishes an artifact externally. Reports use stored authorized inputs and a
configured private artifact port. Client annotations describe behavior; server
authorization and application invariants enforce it. The protocol also requires
structured results to match a declared output schema when one is provided.
See the [official MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

## Exact registry

The arguments column lists required fields first and optional defaults afterward.
Every new account-backed tool requires `account_id`; all read detail IDs are
authorized directly, without searching a truncated list.

| # | Exact tool | Canonical application service / existing gateway | Required scopes | Profile | Input and bounded result |
|---:|---|---|---|---|---|
| 1 | `get_account_summary` | Existing account-summary use case | P | READ | Existing `account_id`; canonical account totals/quality. |
| 2 | `get_portfolio_snapshot` | Existing snapshot detail use case | P | READ | Existing `account_id`, optional `snapshot_id`; one authorized immutable snapshot. |
| 3 | `list_positions` | Existing collection-query use case | P | READ | Existing signed cursor, limit 1–50/default 25, sort enum and search <=80; immutable bounded page. |
| 4 | `list_recent_transactions` | Existing activity-query use case | P,A | READ | Existing required bounded dates, activity enum, cursor and limit 1–50/default 25. |
| 5 | `get_dividend_summary` | Existing dividend-summary use case | P,A | READ | Existing date bounds and recent limit 1–25/default 10; full-period currency aggregates. |
| 6 | `get_direct_allocation` | Existing direct-allocation use case | P | READ | Existing top_n 1–50/default 25; direct weights and cash only. |
| 7 | `compare_portfolio_snapshots` | Existing snapshot-comparison use case | P | READ | Existing account and start/end snapshot IDs; original covered comparison semantics. |
| 8 | `get_reconciliation_status` | Existing reconciliation use case | P | READ | Existing issue_limit 1–50/default 25; bounded discrepancies. |
| 9 | `get_data_quality_summary` | Existing data-quality use case | P,A | READ | Existing account input and bounded dataset/run output; no refresh. |
| 10 | `list_virtual_pies` | `ListVirtualPortfolios` | P,T | READ | `account_id` UUID or explicit null; `Page`; state `draft/active/archived/all` default `active`, search <=80, sort `name_asc/updated_desc` default `name_asc`; portfolio summaries, current version IDs and exact scoped total. |
| 11 | `get_virtual_pie` | `GetVirtualPortfolio` | P,T | READ | `account_id` UUID or null, `virtual_portfolio_id`; optional `target_version_id` (default resolved effective version), parent node UUID, `Page`; portfolio/version metadata and paginated ordered hierarchy, explicit unresolved mapping and aggregate validation. |
| 12 | `get_actual_vs_target` | `GetActualVsTarget` | P,T,N | READ | `Snapshot`, `Target`, reporting currency; optional group UUID and `Page`; exact target/direct actual/gap metrics, cash/unmapped rows and full-scope totals. |
| 13 | `get_drift_analysis` | `GetDriftAnalysis` | P,T,N | READ | `Snapshot`, `Target`, reporting currency, basis `direct/effective` default `direct`, `Top`; ranked holding/group/cash drift, source bundle and effective-exposure coverage. |
| 14 | `get_contribution_plan` | `GetContributionPlan` | P,N | READ | `account_id`, `plan_id`, optional immutable `plan_revision_id`, `Page`; persisted plan state, constraints, solver/input IDs, totals/residual and bounded allocation lines. |
| 15 | `get_performance_summary` | `GetPerformanceSummary` | P,N | READ | `account_id`, `Window`, reporting currency, method `twr/mwr/modified_dietz` default `twr`, frequency `daily/monthly` default `monthly`; bounded series, external-flow treatment, root/coverage limitations and method/version. |
| 16 | `get_benchmark_comparison` | `GetBenchmarkComparison` | P,N | READ | Performance window/currency, `benchmark_version_id`, frequency `daily/monthly` default `monthly`; aligned portfolio/benchmark/excess series, calendar/FX/total-return basis and coverage. |
| 17 | `get_dividend_intelligence` | `GetDividendIntelligence` | P,A,N | READ | `account_id`, `Window`, reporting currency, `Top`; per-currency income/fees/tax totals, sourced conversion and bounded issuer/period breakdown without implicit FX. |
| 18 | `get_attribution_summary` | `GetAttributionSummary` | P,N,T | READ | `account_id`, `Window`, reporting currency, grouping `holding/group/sector` default `holding`, optional `target_version_id`, `Top`; reconciled components and residual/coverage, group requires owned target version. |
| 19 | `get_effective_exposure` | `GetEffectiveExposure` | P,N | READ | `Snapshot`, `source_cutoff_at`, reporting currency, dimension `company/sector/industry/country/region/currency` default `company`, `Page`; direct/indirect/effective rows, constituent/source IDs, confidence and unresolved weight. |
| 20 | `get_etf_overlap` | `GetEtfOverlap` | P,N | READ | `Snapshot`, `source_cutoff_at`, two distinct canonical ETF instrument UUIDs; `Top` common exposures, overlap denominator/coverage and unresolved weights; both instruments must belong to the authorized snapshot. |
| 21 | `get_report_status` | `GetReportStatus` | P,RR | READ | `account_id`, `report_job_id`; durable job state, safe failure/quality, manifest hash, opaque `report_id` if available and expiry. No download/provider/storage URL. |
| 22 | `list_reports` | `ListReports` | P,RR | READ | `account_id`, `Page`, job state or `all`, report-type enum or `all`, sort `created_desc` only; bounded authorized report/job summaries and expiry. |
| 23 | `get_alert_summary` | `GetAlertSummary` | P,AR | READ | `account_id`, `Window`, state `open/acknowledged/resolved/all` default `open`, severity `info/warning/critical/all` default `all`, `Page`; full-filter counts and bounded events/rule-version/quality context. No destination configuration. |
| 24 | `create_contribution_plan` | `CreateContributionPlan` | P,T,N,PW | COMMAND | Strict creation DTO below; returns durable `plan_id`, request/job ID, nullable finalized `plan_revision_id` and current state, input references and planning-only disclosure. |
| 25 | `generate_portfolio_report` | `GeneratePortfolioReport` | P,N,RW,A,T | COMMAND | Strict report DTO below; returns durable `report_job_id`, current state, pinned inputs and manifest identity when available. |

`get_contribution_plan` cannot use `plans:write` as a read bypass. Saved analytics
results are scoped by `portfolio:read,analytics:read`; plan creation additionally
requires target read and plan write. Report generation does not grant report
reading/download permission; the user must also have `reports:read` to retrieve
artifacts. The attribution tool requires P,N,T conservatively for every grouping choice,
including owner-authorized target-group attribution.

## P2-05 X-ray projection clarification

Rows 19/20 keep exactly their frozen capabilities, P,N scopes and READ annotations.
Both use the shared `XrayService` and `ui://trading212-portfolio/xray-v1.html`.
Row 19 selects absolute exposures with its dimension and signed Page; no view,
normalization, run replay, provider or mapping argument is added. Row 20 takes two
distinct held canonical fund UUIDs and Top, with no currency argument. Resolve its
currency from the immutable authorized snapshot inside the service, then call the
same explicit-currency calculation; no preliminary gateway/account-default lookup.

Return `xray_v1` 1.1.0 and `xray_decimal256_exact_q18_v1` plus actual representative
root/source/cutoff/unit coverage. Full pair summaries agree with HTTP common-entity
pages; Top has exact total/returned/omitted counts and omitted common weight, never
a recomputed Top-only total. Unit composition remains independent of monetary zero
or missing FX. A valid incomplete basis returns a known-overlap lower bound,
including zero with unknown actual overlap; denied/expired/unestablishable bases
remain errors/unavailable. Threshold-state unavailability is separate from a bound
value. No client arithmetic or exposure of private exact-state coefficients.

Read existing canonical compositions without fetch/reselection/retraversal. MCP Top
may be transient and creates no permanent pair cache. Any durable member/binding
uses shared collection capacity and original TTL; current owner/account/license
and exact dependency checks precede decode, reuse, cursor and 304. Safe source
previews disclose exact omissions and preserve access to authorized full path detail.

## Contribution command DTO

`create_contribution_plan` requires `Snapshot`, `Target`, `Idempotency`,
`contribution: {amount: nonnegative DecimalString, currency: CurrencyCode}` and
`mode: global|hierarchical|restricted|cash_only`. Optional fields are:

- `restricted_group_ids`: unique UUIDs, at most 256; nonempty for restricted mode;
- `eligible_holding_ids` and `excluded_holding_ids`: unique UUID arrays, at most
  256 each; only holdings in the pinned target version, with contradictions rejected;
- `listing_preferences`: at most 256 strict `{holding_id, listing_id}` records;
- `allocation_constraints`: at most 256 strict records containing `holding_id`,
  non-negative `minimum_amount`, positive `value_increment` and optional
  `maximum_post_weight` in [0,1], all in the contribution currency;
- `cash_reserve`: non-negative DecimalString in contribution currency;
- `monetary_quantum`: positive DecimalString power of ten, at most 18 fractional
  digits and no larger than the versioned currency minor unit; defaults to that
  minor unit, with the resolved quantum/policy pinned in the request;
- `coverage_policy`: `require_complete` (default) or `allow_degraded`; the latter
  does not invent missing financial inputs or relax any hard constraint.

All optional overrides enter the canonical request/hash and must satisfy the
published target's hard constraints. Cash reserve means minimum total post-plan
cash, including existing cash; a reserve above existing cash plus contribution
is an infeasible constraint. Zero contribution permits a zero-allocation result
when valuation and constraints permit it.
Contribution currency must equal the canonical reporting currency. Any upstream
explicit conversion pins a sourced cutoff-safe FX observation before creation;
the MCP command performs no implicit currency conversion. Solver/method
versions are server-selected and pinned in the durable request; clients cannot
choose executable solver code. A finalized plan is immutable; explicit
recalculation creates a new revision with a new command key. Infeasibility returns
a persisted structured state and reasons, never a supposedly valid allocation.
The result includes `execution_allowed=false`; no order side/type/venue/endpoint
or broker-ready instruction object exists.

## Report command DTO

`generate_portfolio_report` requires `account_id`, `Idempotency`, `Window`,
`snapshot_id`, reporting currency, `report_type`, `format` and `sections`.
`report_type` is exactly `monthly|quarterly|annual|portfolio_summary|target_drift|
contribution_plan|performance_benchmark|dividend_income|portfolio_xray|quality_reconciliation`.
`format` is `pdf|csv|json|xlsx`; `sections` is a unique nonempty array, at most thirteen,
from `overview|allocation|targets|drift|contribution_plan|performance|benchmark|
income|cash_flows|attribution|xray|quality|activity`, with no aliases.
Optional `target_version_id`, `plan_revision_id`,
`benchmark_version_id` and `constituent_snapshot_id` must match the selected
sections and account; every other field is rejected. Calendar report types must
match the complete requested month/quarter/year. All input snapshots, section
methods, source permissions and renderer versions are resolved and pinned
before durable dispatch.

Income/activity sections use `activity:read`; drift/target and plan sections use
`targets:read`. The MCP tool conservatively requires and advertises all of
P,N,RW,A,T for every invocation. The shared service additionally enforces
section-level permissions before job creation; an API adapter may use its own
explicit section-dependent scope contract without weakening the MCP boundary. Report types/formats may
reject unsupported combinations explicitly; release acceptance requires every
owner-required report type and export format to have a supported path. No raw
HTML, template, arbitrary filename, storage key, URL or email/webhook destination
is an input. Format/license/expiry failures create no downloadable partial file. The default
private store is bounded PostgreSQL `BYTEA`: 10 MiB per artifact, 25 MiB per job,
default seven-day and maximum thirty-day retention. Optional external object
storage does not change authorization, expiry or URL-disclosure rules.

## Output and failure envelopes

The shared job-state enum is `queued|running|succeeded|failed|expired|cancelled`;
`cancelled` is an internal lifecycle state and grants no MCP cancellation tool.
A plan outcome is separately `optimal|feasible_nonoptimal|infeasible|unavailable|
failed`. Initial creation returns job state `queued`, a durable plan/request/job ID and
null outcome/finalized revision ID; computed plan data is absent until available. Job success never implies mathematical
optimality or sufficient coverage. Report filters use this exact job-state enum.

New results use strict structured success/error schemas. Financial success data
contains exact decimal strings and explicit currencies, valuation/source cutoff,
calculation time, method/version, input revision IDs, coverage, quality,
assumptions and warnings. Operational command/status outputs carry pinned input
references and explicit pending/not-yet-calculated metadata, never invented
analytics. Every returned metric distinguishes fresh, stale, partial, estimated,
unavailable, unsupported, unreconciled and failed where applicable; null is not
zero. Collections carry exact eligible totals, cursor and truncation/omission
metadata. Provenance is a bounded safe source identifier, never a provider URL.

Stable sanitized error categories include authentication/access denial,
validation, not-found, version-precondition conflict, idempotency conflict,
capacity/cursor errors, insufficient coverage, calculation unavailable,
source-license restriction, report expiry and internal failure. Errors carry
bounded correlation/remediation fields and retryability without request payloads,
private identifiers, stack traces or provider bodies. A retry preserves the
idempotency key. Business infeasibility is a typed plan outcome, not an invented
successful plan. MCP `isError` agrees with the declared error envelope.

## Versioned accessible resources

Preserve `ui://trading212-portfolio/snapshot-v1.html`. Add only these fixed
presentation resources when their services are complete:

| Resource URI | Attached tools |
|---|---|
| `ui://trading212-portfolio/contribution-plan-v1.html` | `get_contribution_plan`, `create_contribution_plan` |
| `ui://trading212-portfolio/performance-comparison-v1.html` | `get_performance_summary`, `get_benchmark_comparison` |
| `ui://trading212-portfolio/xray-v1.html` | `get_effective_exposure`, `get_etf_overlap` |
| `ui://trading212-portfolio/report-status-v1.html` | `get_report_status`, `generate_portfolio_report` |

Resources are static server-owned HTML over validated structured tool results.
Use the repository's tested SDK metadata mapping for standard `ui.resourceUri`,
Apps SDK output template and widget CSP aliases; schema/descriptor tests must
check the actual emitted protocol. Both `ui.csp` and `openai/widgetCSP` declare
empty connect/resource domain lists and no frame domains. Any widget origin is
trusted deployment configuration. No remote images/fonts/scripts/iframes,
arbitrary fetching, dynamic evaluation or raw HTML from tool/provider content
is allowed. Fixed scripts/styles use a restrictive hash-based document CSP;
external connections, forms, object/embed and nested frames are disabled.

Widgets render labels with `textContent`, expose semantic text/table alternatives,
keyboard/focus/reduced-motion support and bounded responsive layouts. They make
no authoritative calculations or hidden tool calls. A report status widget shows
state/expiry and opaque IDs; authenticated artifact access occurs through the
application's authorized download flow, never a public or signed storage URL in
a tool result. Tool correctness and accessible textual results are independent
of widget rendering or live ChatGPT registration.

## Required verification

P2-09 must assert exactly these 25 descriptors, strict nested schemas, scope
mapping, annotations and resource metadata. Test all missing/cross-owner/account
references, unknown fields/tools, output caps, expired/tampered cursors,
idempotency replay/conflict/concurrency, worker recovery and no provider/broker
calls from either command. Match API/MCP/report canonical values at identical
inputs. Browser/resource tests cover CSP, injection, secrets, quality states and
accessibility. The [scenario ledger](../implementation/PHASE_2_SCENARIO_EVIDENCE.md)
records evidence; this contract itself proves no implemented tool.
