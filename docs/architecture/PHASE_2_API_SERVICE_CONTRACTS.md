# Phase 2 API and Service Contracts

**Status:** Accepted

**Date:** 2026-09-07

**Release:** 0.2.0 design contract; implementation evidence is separate

This is an additive extension of the [Phase 1 contract](API_AND_SERVICE_CONTRACTS.md)
and uses the [Phase 2 data model](PHASE_2_DATA_MODEL.md). Existing routes, errors,
generated models, and nine MCP tools retain compatibility. Each operation below
has a named request/result schema and an application service. HTTP, generated web
clients, MCP, reports, and workers use those services and their canonical results.
No route accepts a broker operation, provider URL/path, arbitrary SQL, expression,
task name, or untyped provider payload.

## 1. Shared types and bounded inputs

New aggregate/reference IDs use the existing canonical UUID-string validation.
Existing account/instrument/listing IDs keep
their current canonical identity representation. All referenced resources must
belong to the principal and to the same account where required. No request body
accepts `owner_id`; the authenticated principal supplies ownership. Unknown
fields are rejected, including unknown nested fields. Request bodies are at most
64 KiB; ordinary JSON responses are at most 2 MiB. Artifact streams have the
separate size bounds below. Body, collection, hierarchy, and output limits all
apply; a maximum node count does not authorize an oversized body.

Financial numbers use exact decimal strings compatible with `NUMERIC(38,18)`:
at most 20 integer digits and 18 fractional digits;
JSON numbers, nonfinite strings, exponent notation, excess scale, and overflow
fail validation. Output uses fixed, non-exponent decimal strings, at most 18
fractional digits, and canonical zero. Money is `Money {amount, currency}`;
rates include base/quote currencies; fractions are not percentage points.
Instants serialize as RFC 3339 UTC with `Z`. Aware RFC 3339 input offsets normalize
to UTC; naive timestamps fail. Calendar dates are `YYYY-MM-DD` with the named
market or cash-flow convention. Bounded periods require `start <= end` and
`end - start <= 3660 days`; daily output contains at most 3661 points.

Names are 1..120 characters, descriptions 0..2000, normalized searches 0..80,
stable node/constraint keys 1..80, and user notes 0..1000. IDs in input sets must
be unique; target/reference arrays contain at most 256 entries. Target trees have
at most 256 nodes and leaf depth eight from the conceptual portfolio root at
depth zero. Collection limits default to 25, minimum one, maximum 100; summaries
have `top_n` from one through 50, default 25. Existing Phase 1/MCP default limits
remain unchanged. All request enums and limits appear in generated OpenAPI and
TypeScript; an unspecified filter or sort is rejected rather than interpreted.

`ResultContext` is shared metadata, not a catchall result body:

| Field | Contract |
|---|---|
| `account_id`, `reporting_currency` | Authorized calculation scope; account absent only for a private target template |
| `as_of`, `source_cutoff_at`, `calculated_at` | Distinct UTC instants; no source first observed after cutoff may be selected |
| `method {name, version}`, `schema_version` | Frozen methodology and typed result schema |
| `sources` | Bounded typed references with snapshot/version IDs and semantic digests; source metadata contains no URL, credential, or raw payload |
| `availability`, `reason_code` | `available`, `partial`, `unavailable`, or `failed`; explicit reason for nonavailable results |
| `data_quality` | Existing quality state plus coverage start/end, missing inputs, evaluated time, bounded warnings and reconciliation state |
| `coverage` | Exact covered/unresolved weights or periods with explicit basis |
| `assumptions`, `warnings` | Fixed code, severity, affected canonical IDs and bounded safe message; no executable remediation |

Individual analytical metrics use named nullable values with an explicit
availability/reason. Missing and zero are distinct. A partial response may contain
valid metrics and unavailable metrics, never plausible substituted zeroes. A
valid request lacking sufficient observations returns its typed analytical
result with `unavailable`; malformed commands or prohibited transitions return
the errors in section 10. No successful result silently truncates its body to fit
the response cap.

## 2. Authentication, scopes, commands, and concurrency

All account-backed Phase 2 operations require existing `portfolio:read` plus the
scopes below. Owner-private templates require target scopes without account
scope. New exact scopes are `targets:read`, `targets:write`, `analytics:read`,
`plans:write`, `reports:read`, `reports:write`, `alerts:read`, and `alerts:write`.
Existing `activity:read` also protects dividend/cash-flow detail and report
sections using it. Write scopes do not imply read scopes. Authorization executes
inside every service, including worker consumption, not only in HTTP middleware.
Foreign-owner opaque resources resolve as `NOT_FOUND`; a known authorized
account with an insufficient capability returns `ACCESS_DENIED`.

Cookie-authenticated POST/PATCH commands require a valid session-bound
`X-CSRF-Token`; bearer-authenticated commands require the exact scopes and do not
use CSRF tokens. Cookie mutations also enforce the configured trusted origin.
The API CORS allowlist adds PATCH, `If-Match`, and the named download-grant header
only for explicit trusted web origins. Wildcard origins with credentials remain
forbidden. No DELETE broker or generic provider route is added.

Every durable business create/action command requires `X-Idempotency-Key` (1..180
ASCII characters matching `^[A-Za-z0-9._:-]+$`). Scope it to owner, account
where present, and exact command kind. Hash the normalized, versioned request
including referenced immutable inputs. Concurrent equal requests create one
aggregate/job and audit event; retries return the same ID and current durable
state. A reused key with different semantics returns `IDEMPOTENCY_KEY_REUSED`.
Authentication and scope checks precede idempotency lookup. For an exact retry,
the committed identity is returned before rechecking a now-stale precondition;
idempotency never bypasses current authorization. Ephemeral artifact-grant
creation is the explicit exception: every authenticated retry issues a new
short-lived token, with at most ten active grants per owner/artifact and a rate
limit. A token is disclosed once and never stored reversibly for replay.
Identities survive artifact
expiry as safe tombstones. A GET never creates a plan/report/job.

Draft/metadata updates and lifecycle actions require a strong `If-Match` value
returned on reads: `"<aggregate UUID>:<revision>"`. Missing preconditions return
428; stale ones return 412. Lock, validate, update revision, and append audit in
one transaction. Published content cannot be patched even with its current ETag.
Publication requires the draft ETag and a successful validation for that exact
content digest. Internal activation is a fenced durable lifecycle transition.
Immutable result GETs use their quoted content digest as ETag and honor
`If-None-Match` with 304 only after authorization. Private responses use
`Cache-Control: private, no-store` unless an explicitly reviewed local cache
policy applies.

Target version detail includes mutable lifecycle and validation metadata even
after publication, so its full representation uses the aggregate revision ETag.
The separate `content_digest` identifies the immutable target content; it is
not a valid conditional GET validator for the complete version detail.

## 3. Virtual portfolios and targets

All paths below begin `/api/v1`. `T-R` means `targets:read`; `T-W` means
`targets:write`; both also require account `portfolio:read` when associated.
Create responds 201; other synchronous commands/read operations respond 200.

| Method and path | Canonical service | Input → result | Scope |
|---|---|---|---|
| GET `/virtual-portfolios` | `ListVirtualPortfolios` | account/state/search/sort/page → `VirtualPortfolioPage` | T-R |
| GET `/target-versions/{version_id}/nodes` | `ListTargetNodes` | version ID, optional parent node UUID, page → ordered hierarchy node page | T-R |
| POST `/virtual-portfolios` | `CreateVirtualPortfolio` | `CreateVirtualPortfolioRequest` → `VirtualPortfolioDetail` | T-W |
| GET `/virtual-portfolios/{portfolio_id}` | `GetVirtualPortfolio` | ID → `VirtualPortfolioDetail` | T-R |
| PATCH `/virtual-portfolios/{portfolio_id}` | `UpdateVirtualPortfolioMetadata` | `UpdateVirtualPortfolioRequest`, If-Match → detail | T-W |
| POST `/virtual-portfolios/{portfolio_id}/archive` | `ArchiveVirtualPortfolio` | empty typed body, If-Match → detail | T-W |
| GET `/virtual-portfolios/{portfolio_id}/target-versions` | `ListTargetVersions` | state/page → `TargetVersionPage` | T-R |
| POST `/virtual-portfolios/{portfolio_id}/target-versions` | `CreateTargetVersion` | `CreateTargetVersionRequest`, portfolio If-Match → `TargetVersionDetail` | T-W; also T-R when cloning a source |
| GET `/target-versions/{version_id}` | `GetTargetVersion` | ID → `TargetVersionDetail` | T-R |
| PATCH `/target-versions/{version_id}` | `UpdateTargetDraft` | `ReplaceTargetDraftRequest`, If-Match → detail | T-W |
| POST `/target-versions/{version_id}/validate` | `ValidateTargetVersion` | `ValidateTargetRequest`, If-Match → `TargetValidationResult` | T-W |
| POST `/target-versions/{version_id}/publish` | `PublishTargetVersion` | `PublishTargetRequest`, If-Match → detail | T-W |
| POST `/target-versions/{version_id}/archive` | `ArchiveTargetVersion` | empty typed body, If-Match → detail | T-W |
| GET `/virtual-portfolios/{portfolio_id}/target-comparison` | `CompareTargetVersions` | `left_version_id`, `right_version_id` → `TargetVersionComparison` | T-R |

Portfolio list state is `draft|active|archived|all` (default active), and sort is
`name_asc|updated_desc` (default name_asc), each tied by UUID. Draft means no
published version, active means an unarchived portfolio with a published version,
and archived reflects portfolio lifecycle; detailed target lifecycle remains
separate. Metadata responses expose their current revision and updated time.

`CreateVirtualPortfolioRequest` contains name, description, reporting currency,
and optional account ID. `UpdateVirtualPortfolioRequest` contains name and/or
description only. Account association and reporting currency are fixed at create;
an owner may explicitly create a separate account-bound portfolio from a template
by supplying a source version ID to its first draft creation. This clones the
content and validates mappings in the destination account; no ownership transfer
or shared mutable node reference is created.

`CreateTargetVersionRequest` contains optional source version ID, effective UTC
instant, and full content only when no source is supplied. Source is an authorized
published version or draft and requires `targets:read` in addition to write scope;
caller-supplied content requires only write scope. Cross-portfolio template clones are recorded as
provenance, not as a same-portfolio parent-version FK. `ReplaceTargetDraftRequest`
atomically supplies effective time, flat typed nodes, constraints, and exclusions;
no JSON Patch path interpreter is exposed. Nodes contain stable key, optional
parent key, kind, name, order, exact sibling weight, and a typed holding mapping
only for holding nodes. A resolved mapping requires `instrument_id` and has
optional `listing_id` for actual-allocation scope and separate optional
`preferred_listing_id` for funding. Null selector means all listings of that
instrument; a non-null selector means that listing only. A version may have one
instrument-wide leaf or distinct listing-specific leaves for an instrument,
never both. Every preference belongs to the instrument and must equal a non-null
selector. Without a preference, instrument-wide planning requires exactly one
eligible canonical listing; otherwise its outcome is unavailable with
`listing_choice_required`. An unresolved/ambiguous mapping may omit instrument
ID and retains a typed requested identifier plus reason instead. Raw provider URLs and
freeform identifier namespaces are prohibited. Cash uses reporting currency.

`TargetVersionDetail` includes portfolio/version IDs, version number, draft
revision, content digest when published, reporting currency, effective/published
times, lifecycle, nodes/constraints/exclusions, latest validation, and warnings.
Lifecycle is `draft`, `scheduled`, `active`, `superseded`, or `archived`;
`scheduled` denotes published content whose effective instant is in the future.
Publishing an already-effective version activates it atomically. Scheduled
activation is fenced and idempotent. Archiving the active version leaves no
active target or fallback to superseded versions; only a newly published due
version or a never-before activated scheduled version can activate next.
Archiving scheduled content prevents activation, while archiving a draft or
superseded version leaves current selection unchanged. Archived/superseded
content is corrected by cloning, never by reactivation. Portfolio archive
disables current selection and future activation; historical ID-based reads
remain available. Earlier effective dates never backdate publication knowledge.
If an outage leaves a schedule overdue and the owner subsequently publishes an
immediate replacement, the worker records the older scheduled version as
superseded without activating it when the active version was published later
than that candidate and at or after its effective time. Future effective times
after the active version's publication remain eligible for normal activation.
Each flattened node exposes depth, relative weight, exact path factors, quantized
effective weight, mapping state, and deterministic order. The detail includes
`effective_weight_rounding_residual`. Audit events have a separate bounded
`GET /target-versions/{version_id}/events` → `TargetVersionEventPage` via
`ListTargetVersionEvents` with T-R.

`ValidateTargetRequest {normalize: boolean}` defaults false. Validation stores
the exact `input_revision`/input digest and typed issues. Each new validation
atomically advances the aggregate revision once because its latest-validation
metadata changes the detail representation. An exact idempotent retry does not
advance it again. Explicit normalization additionally records original/adjusted
weights. `result_revision` is the resulting aggregate revision; the result digest
equals the input digest when content did not change. Latest validation is ordered
by result revision, including when timestamps coincide. The returned ETag
identifies that result revision; publication uses
the returned `validation_id` in `PublishTargetRequest` and requires the current
draft to match its result revision/digest. Retained issues/adjustments copy stable
node/constraint keys and values instead of retaining FKs to replaceable draft
nodes. Exact sibling sum one,
tolerance `1e-12`, deterministic scale-18 normalization, depth, cycle, ownership,
listing, constraint, and duplicate checks are defined in the data model. An
invalid tree returns a persisted `TargetValidationResult` with `valid=false` and
bounded issue rows; attempting to publish it returns `TARGET_VALIDATION_FAILED`.
Comparison aligns stable node keys, reporting added/removed/moved nodes, weight,
mapping, constraint, and effective-time changes without modifying either version.

## 4. Drift and contribution planning

`A` means `analytics:read`, `P-W` means `plans:write`; account `portfolio:read`
is always required. Analytical GETs read persisted immutable sources and do not
dispatch provider requests.

| Method and path | Canonical service | Input → result | Additional scope |
|---|---|---|---|
| GET `/accounts/{account_id}/actual-vs-target` | `GetActualVsTarget` | snapshot/version IDs, optional node ID → `ActualVsTargetResult` | A + T-R |
| GET `/accounts/{account_id}/drift` | `GetDriftAnalysis` | snapshot/version IDs, `direct`/`effective` basis → `DriftAnalysisResult` | A + T-R |
| POST `/contribution-plans` | `CreateContributionPlan` | `CreateContributionPlanRequest` → `ContributionPlanJob`, 202 | A + T-R + P-W |
| GET `/contribution-plans` | `ListContributionPlans` | account, portfolio, outcome/state/page → `ContributionPlanPage` | A |
| GET `/contribution-plans/{plan_id}` | `GetContributionPlan` | ID, optional revision → `ContributionPlanDetail` | A |
| POST `/contribution-plans/{plan_id}/revisions` | `RecalculateContributionPlan` | new typed request, If-Match → `ContributionPlanJob`, 202 | A + T-R + P-W |

Actual/target and drift rows contain node/listing identity, depth, target weight,
actual direct weight, effective weight availability, signed/absolute/relative
drift, `underweight`/`on_target`/`overweight` classification, monetary gap, and
quality. Node UUIDs and holding UUIDs are distinct: each holding row exposes both,
and actual-versus-target includes a same-input `target_identities` index of at
most 256 `{id, key, holding_id}` records for bounded selection without draining
unclassified rows. Relative drift is unavailable for target zero. Cash and unclassified
valued positions are explicit rows. Unknown valuation prevents a full-quality
denominator. Summaries retain unmapped value and the disclosed rounding residual.
The drift response has its own total, group and leaf aggregates; it is not an
alias for an allocation response.

`CreateContributionPlanRequest` contains `account_id`, `virtual_portfolio_id`,
`target_version_id`, `snapshot_id`, nonnegative contribution `Money`, mode
`global|hierarchical|restricted|cash_only`, and `coverage_policy`:
`require_complete` (default) or `allow_degraded`. Optional `eligible_holding_ids`
and `excluded_holding_ids` reference target-holding UUIDs in the pinned version;
`restricted_group_ids` references its group-node UUIDs and is nonempty in
restricted mode. `listing_preferences` contains `{holding_id, listing_id}`;
the listing must belong to that holding's canonical instrument. Each array is
unique and bounded to 256. These identities do not refer to broker positions.
`allocation_constraints` uses the checked variants in the data model. The MCP
subset `{holding_id, minimum_amount, value_increment, maximum_post_weight}` maps
respectively to a holding scope, `minimum_funded_amount`, `amount_increment`, and
`maximum_post_weight`; no minimum is silently treated as mandatory funding.
The full API also accepts this composite representation as `holding_constraints`,
bounded to 256 unique holdings, so a revision can preserve every MCP override
without lossy expansion into the separate 256 full-variant constraint limit.
Persisted requests retain both forms. Expansion occurs only inside the canonical
solver; the maximum combined effective constraint count is 1280 (256 published,
256 full overrides, and at most 768 composite expansions).
`cash_reserve` is a nonnegative reporting-currency minimum total post-plan cash
amount, including existing cash. Insufficient existing cash plus contribution
is explicit infeasibility, not an input silently clamped to contribution.
Optional `monetary_quantum` is a DecimalString power of ten no larger than the
versioned currency minor unit, scale at most 18; default is that minor unit.
Pin its exact value and policy version, and require contribution/increments/
amount bounds to be exact multiples. A zero contribution is valid when the
known valuation is positive and the zero-allocation plan satisfies constraints.
Every override is retained in the canonical request; `allow_degraded` cannot
invent missing material valuations or relax a hard constraint. No client solver
expression is accepted. Currency
must match reporting currency; any explicit preconversion references its pinned
FX observation and original amount. The normalized request pins method/version,
source cutoff and every effective constraint before the job is queued.

`ContributionPlanJob` contains plan ID, request revision, job ID, durable state,
outcome (null before a result exists), request time, and safe failure reason.
`ContributionPlanDetail` contains immutable request, result revision when ready,
method/solver version, context, objective before/after, certified lower bound,
outcome, constraints, ordered allocation lines, exclusions, unresolved inputs,
residual cash and typed explanations. Job states are
`queued|running|succeeded|failed|expired|cancelled`; result outcomes are
`optimal|feasible_nonoptimal|infeasible|unavailable|failed`. A succeeded job can
have an infeasible or unavailable analytical outcome. No feasible-looking lines
are fabricated for those outcomes. A queued/failed job cannot claim a finalized
successful plan. Repeated identical inputs produce byte-equivalent canonical
result content; job IDs and calculation clock time are outside that digest.

Plan detail includes current durable job state and a selected allocation page,
so its HTTP ETag is the SHA-256 of the complete authorized wire representation.
The immutable financial `content_digest` is separate. The detail exposes
`revision_etag`, the strong `"<plan UUID>:<request revision>"` token used by
recalculation's `If-Match`. A result digest cannot validate a changed job state
or a different page. Authorization precedes every conditional response, and
reads do not introduce a new calculation clock time.

The existing plan collection supports history through `plan_id` together with
`include_revisions=true`; these selectors must be supplied together. Its normal
view returns the latest request for each plan. Its history view returns bounded
request revisions in descending revision order, with stable cursor membership
and the same owner/account authorization and collection quotas. A finalized
revision links to detail using its `plan_revision_id`; unfinished requests do not
invent a finalized revision identity.

An explicitly selected published target may be compared with an earlier
valuation snapshot. Its publication and effective times remain separate source
metadata; when they postdate the financial cutoff or valuation, the result
discloses that deliberate comparison as an assumption. This does not claim the
target was known or active at that historical instant. The financial cutoff
continues to bound every valuation/FX observation. Automatic historical target
selection cannot use a later-known definition.

## 5. Reference sources and analytical resources

Every row requires account `portfolio:read` and A. `Activity` adds existing
`activity:read`. All series use explicit period, reporting currency, source
cutoff, and source/benchmark version where applicable. A source ID never
authorizes an arbitrary outbound request.

| GET path | Canonical service | Typed result / additional inputs or scopes |
|---|---|---|
| `/accounts/{account_id}/market-sources` | `GetMarketSourceStatus` | `MarketSourceStatus`: configured capabilities, safe state, coverage, freshness, license permissions |
| `/accounts/{account_id}/fx-sources` | `GetFxSourceStatus` | `FxSourceStatus`: available pairs, pinned revisions, gaps and age |
| `/accounts/{account_id}/benchmark-sources` | `GetBenchmarkSourceStatus` | `BenchmarkSourceStatus`: authorized definitions/versions, basis, coverage and source state |
| `/accounts/{account_id}/performance/series` | `GetPerformanceSeries` | `PerformanceSeries`: ordered valuation/flow/return/drawdown points with metric availability |
| `/accounts/{account_id}/performance/intelligence` | `GetPerformanceSummary` | `PerformanceSummary`: TWR/MWR/P&L/income/drawdown/contribution metrics and coverage |
| `/accounts/{account_id}/benchmark-comparison` | `GetBenchmarkComparison` | `BenchmarkComparison`: benchmark-version ID, portfolio/benchmark/active return, comparable aligned observations and assumptions |
| `/accounts/{account_id}/attribution` | `GetAttributionSummary` | `AttributionSummary`: `holding|group|sector|asset_class|currency` grouping, components plus explicit residual; T-R for group/target references |
| `/accounts/{account_id}/dividend-intelligence` | `GetDividendIntelligence` | `DividendIntelligence`: income amounts, concentration/growth/yields where supported; Activity |
| `/accounts/{account_id}/cash-flow-intelligence` | `GetCashFlowIntelligence` | `CashFlowIntelligence`: external flows, income, fees/taxes and internal purchases/sales separately; Activity |
| `/accounts/{account_id}/effective-exposure` | `GetEffectiveExposure` | `EffectiveExposure`: `company|sector|industry|country|region|currency` dimension, direct/indirect/unresolved values, normalized-view flag default false |
| `/accounts/{account_id}/etf-overlap` | `GetEtfOverlap` | `EtfOverlap`: two..32 unique authorized fund IDs, unordered pair metrics, common entities, constituent coverage |
| `/accounts/{account_id}/intelligence-data-quality` | `GetIntelligenceDataQuality` | `IntelligenceDataQuality`: fixed analytics-kind filter, per-source/metric freshness, reconciliation, license and missing-input state |

The new performance intelligence route leaves the existing Phase 1
`/performance/summary` response intact. Bounded source detail/observation endpoints
are `GET /price-snapshots/{id}`, `/fx-snapshots/{id}`,
`/benchmark-snapshots/{id}`, and `/constituent-snapshots/{id}`, with A and owner
authorization plus account authorization when accessed through a dependent
account result. Each returns its specific typed header and paginated observations
through a corresponding `/observations` child (constituents use `/holdings`).
License `display` permission is required. Unknown data or denied entitlements
are not exposed through these diagnostic routes.

Owner benchmark definitions use `GET/POST /benchmark-definitions`,
`GET /benchmark-definitions/{id}`, `POST /benchmark-definitions/{id}/versions`,
and `POST /benchmark-definitions/{id}/archive` via `ListBenchmarkDefinitions`,
`CreateBenchmarkDefinition`, `GetBenchmarkDefinition`, `CreateBenchmarkVersion`,
and `ArchiveBenchmarkDefinition`. Read requires A; creates/version/archive require
T-W plus A, idempotency, and If-Match on existing aggregates. Requests contain
name, reporting currency, effective time, return basis, fixed rebalance rule and
weighted component source IDs; all sources must be owner-authorized and licensed.
Versions are validated and published atomically with immutable content. No
benchmark/provider credentials or URLs can be configured through this surface.

## 6. Reports and exports

All report/export operations require account `portfolio:read`. `R-R` means
`reports:read`; `R-W` means `reports:write`. Creation also requires A and scopes
for requested data: T-R for target/plan sections; Activity for income/activity/
cash-flow sections. Permission is checked again during generation and download.

| Method and path | Canonical service | Input → result | Scope |
|---|---|---|---|
| POST `/report-jobs` | `GeneratePortfolioReport` | `GenerateReportRequest` → `ReportJobStatus`, 202 | R-W + A + section scopes |
| GET `/report-jobs/{job_id}` | `GetReportStatus` | ID → `ReportJobStatus` | R-R |
| GET `/reports` | `ListReports` | account/type/state/period/page → `ReportPage` | R-R |
| GET `/reports/{report_id}` | `GetReportManifest` | successful job/report ID → `ReportManifest` | R-R + section scopes |
| POST `/reports/{report_id}/artifacts/{artifact_id}/grants` | `CreateReportDownloadGrant` | empty typed body → `ArtifactGrant`, 201 | R-R + section scopes |
| GET `/reports/{report_id}/artifacts/{artifact_id}/content` | `DownloadReportArtifact` | `X-Artifact-Grant` plus authentication → bounded bytes | R-R + section scopes |
| POST `/exports` | `CreatePortfolioExport` | `CreateExportRequest` → `ExportJobStatus`, 202 | R-W + A + dataset scopes |
| GET `/exports` | `ListPortfolioExports` | account/dataset/state/page → `ExportPage` | R-R |
| GET `/exports/{export_id}` | `GetExportStatus` | ID → `ExportJobStatus` | R-R |
| POST `/exports/{export_id}/artifacts/{artifact_id}/grants` | `CreateExportDownloadGrant` | empty typed body → `ArtifactGrant`, 201 | R-R + dataset scopes |
| GET `/exports/{export_id}/artifacts/{artifact_id}/content` | `DownloadExportArtifact` | `X-Artifact-Grant` plus authentication → bounded bytes | R-R + dataset scopes |

`GenerateReportRequest` contains account, report type, explicit period/reporting
currency, formats, fixed sections, snapshot/target/plan/benchmark IDs as required,
source cutoff, template version and requested TTL days 1..30 (default seven).
Report types are `monthly`, `quarterly`, `annual`, `portfolio_summary`,
`target_drift`, `contribution_plan`, `performance_benchmark`, `dividend_income`,
`portfolio_xray`, and `quality_reconciliation`. Sections are `overview`,
`allocation`, `targets`, `drift`, `contribution_plan`, `performance`, `benchmark`,
`income`, `cash_flows`, `attribution`, `xray`, `quality`, and `activity`: a unique
nonempty array of at most 13 entries. There are no section aliases. Type-specific required sections
and inputs are fixed in the report methodology; irrelevant fields fail. Formats
are `pdf|csv|json|xlsx`, unique, at most four. No custom template, HTML, external
image, formula, or executable attachment is accepted.

`CreateExportRequest` selects dataset `positions|activity|dividends|targets|plans|
performance|xray|alerts`, fixed `standard|audit` column-set, source IDs, period,
currency, and one `csv|json|xlsx` format. Rows are bounded to 100,000 and columns
to 64, with at most 4096 characters per text cell; overflow fails explicitly and
creates no complete artifact. CSV/XLSX
untrusted text is rendered as text with formula-injection controls.

Job status includes job/report ID, state, requested/completed/expiry times, safe
failure code, report type/format summary, manifest digest when complete, and
bounded artifact metadata (opaque ID, format, MIME, byte length, digest, expiry).
States are `queued|running|succeeded|failed|expired|cancelled`; this release exposes
no cancellation command, so `cancelled` is reserved for audited owner-deletion
or operational termination. A report ID is the successful job's stable ID.
The manifest includes all exact source/version hashes, coverage, licenses,
assumptions and renderer/template/method versions. Artifacts are at most 10 MiB
each and 25 MiB total per report job, atomically complete across requested formats.
Status/list endpoints contain no bytes, credentials, paths, or download URLs.

`ArtifactGrant` contains only artifact ID, an opaque cryptographically random
token, and expiry at most five minutes away. This deliberately sensitive response
is never logged, included in a report, stored raw, or exposed through MCP.
Persistence stores its token hash and owner/artifact scope. Send it only in
`X-Artifact-Grant`, never a query string; every download also authenticates and
checks current owner/account, scopes, license, expiry, and digest. Responses use
fixed MIME, safe attachment filename, `nosniff`, and no-store. Expired artifacts
return `ARTIFACT_EXPIRED` even before cleanup deletes bytes. Binary content routes
are excluded from the 2 MiB JSON bound but enforce the 10 MiB artifact bound.

## 7. Alert management and history

All operations require account `portfolio:read`. Reads require `alerts:read`;
writes require `alerts:write` plus A, and T-R/Activity when the rule's inputs need
those scopes. Writes use idempotency and If-Match for an existing rule/event.

| Method and path | Canonical service | Typed input/result |
|---|---|---|
| GET/POST `/alert-rules` | `ListAlertRules` / `CreateAlertRule` | account/state/family/page → `AlertRulePage`; `CreateAlertRuleRequest` → `AlertRuleDetail`, 201 |
| GET `/alert-rules/{rule_id}` | `GetAlertRule` | `AlertRuleDetail` with current immutable version and lifecycle |
| POST `/alert-rules/{rule_id}/versions` | `CreateAlertRuleVersion` | `AlertRuleVersionRequest` → new immutable version, 201 |
| POST `/alert-rules/{rule_id}/activate` | `ActivateAlertRule` | selected version ID → detail |
| POST `/alert-rules/{rule_id}/pause` | `PauseAlertRule` | empty typed body → detail |
| POST `/alert-rules/{rule_id}/archive` | `ArchiveAlertRule` | empty typed body → detail |
| GET `/alert-events` | `ListAlertEvents` | account/rule/severity/episode-state/date/page → `AlertEventPage` |
| GET `/alert-events/{event_id}` | `GetAlertEvent` | `AlertEventDetail` with evaluation and delivery summary |
| POST `/alert-events/{event_id}/acknowledgments` | `AcknowledgeAlertEvent` | optional bounded note → `AlertAcknowledgment`, 201 |
| POST `/alert-events/{event_id}/resolve` | `ResolveAlertEvent` | optional bounded note, If-Match → `AlertEventDetail` |
| GET `/accounts/{account_id}/alert-summary` | `GetAlertSummary` | severity/state/top_n → `AlertSummary` |

An alert version contains name, a fixed rule-family/metric variant, canonical
scope IDs, comparison, exact threshold/currency, severity, quality policy,
schedule, cooldown and destination IDs. The alert methodology owns the exact
metric enum and checked fields per family. No user expression, SQL, code, cron
string, webhook URL or secret is accepted. Schedule is an interval from 300..86400
seconds or a daily UTC minute 0..1439; cooldown is 0..604800 seconds. Alert event
episode state is `open|resolved`; acknowledgment is separate, with principal and
time. Evaluation outcomes are `matched|not_matched|suppressed|unavailable|failed`.
Current lifecycle is `draft|active|paused|archived`, derived from append-only
events. Acknowledgment does not resolve or stop evaluation. Owner resolution
appends an audited transition, closes the current episode, and never deletes the
evaluation/event. It does not rearm a continuously true predicate: a later
`not_matched` evaluation must first observe recovery before a subsequent match
can open a new episode, respecting cooldown. An identical input digest cannot
reopen a resolved episode.
Notification status
never claims external delivery when configuration is absent; in-app events and
history remain fully functional.

`GET /notification-destinations` via `ListNotificationDestinations` requires
`alerts:read` and returns only opaque IDs, channel `in_app|email|webhook`, safe
label and `configured|unavailable|disabled` state. Destination provisioning and
secret/URL resolution are trusted server configuration, not a public HTTP CRUD
or test-delivery proxy. Default in-app delivery needs no external credential.

## 8. Durable collection cursors

Every new mutable collection uses the existing durable identity snapshot and
owner advisory-lock boundary, shared across API and MCP. Snapshot membership,
order and immutable analytical/source references are frozen at page one. Mutable
display metadata may reflect its current explicitly returned revision; it cannot
change membership, ordering, a pinned target version or a result's source inputs.
Collection snapshots bind owner,
account/template scope, resource version, normalized filters/sort, selected
source snapshot/cutoff, membership revision, and last ordering key. HMAC cursors
remain valid across process/container restarts with the same durable signing key.
TTL defaults to 3600 seconds, bounded by the existing 60..86400 configuration.
No caller chooses a cursor TTL or submits raw keyset SQL.

Hard quotas remain 64 active traversals and 250,000 active members per owner,
combined with Phase 1 usage. Under the owner lock, include all unexpired members,
consume at most remaining capacity plus one, and atomically roll back new header,
members, revision references, and cursor identity on overflow even if the caller
catches the error. An owner's first snapshot has no exception. Exact total is
computed from full frozen eligible membership, never a prefix. Failed capacity
requests emit neither partial data, total, nor cursor. Expired members release
capacity; cleanup is separately bounded. Immutable series use their pinned
snapshot plus signed bounded keyset cursors, and any newly materialized traversal
uses the same quota boundary.

Portfolio order is `(normalized_name ASC, id ASC)` or `(updated_at DESC, id DESC)`
as explicitly selected above. Default order is `(created_at DESC, id DESC)` for
plans/jobs/rules,
`(version_number DESC, id DESC)` for versions, `(occurred_at DESC, id DESC)` for
audit/events, and `(valuation_at ASC, id ASC)` for series. Hierarchy detail order
is depth-first by `(sibling_order, stable_node_key)` and is bounded by 256 nodes.
Other declared analytical ordering is exact descending exposure/drift followed
by stable canonical ID, with explicit residual/unresolved rows preserved.
Allowed filters are only those named above. Time filters use inclusive start,
exclusive next-day end for date-to-UTC conversion, documented before hashing.

## 9. Canonical parity and generated contracts

The [MCP registry](../integrations/PHASE_2_MCP_TOOL_REGISTRY.md) maps each tool to
the same service and typed result. MCP tool identity is not an authorization
boundary. Its conservative scope sets may be broader than HTTP's section-specific
sets: attribution always requires T-R; report generation always requires T-R and
Activity. Both also retain A and account `portfolio:read`. The two MCP commands
persist a plan/report job and return its ID/state with the same idempotency
semantics. They cannot grant artifact download access or send a notification.
MCP `idempotency_key` maps exactly to the HTTP header, and its singular report
`format` maps to a one-element `formats` list. The report section enum is shared
without aliases. MCP's two ETF IDs map to a two-element API fund-ID set, and its
attribution `holding|group|sector` enum is a declared subset of API groupings.
Paginated tool projections read the same canonical hierarchy/plan/exposure
result: totals and immutable references are unchanged by selecting a page.

Versioned canonical serializers exclude transport fields, request correlation
IDs, job IDs, and calculation clock times from economic result hashes; they
include schema/method versions, inputs, options, source cutoff, exact values,
availability, assumptions and quality. Web display formatting does not alter
the canonical value. OpenAPI schemas and the generated TypeScript client are
committed and checked for deterministic regeneration at each completed package.
No `Any`, `dict[str, Any]`, freeform JSON schema, or generic analytical response
may replace the named request/result variants in this contract.

## 10. Stable errors and verification

Use the existing `{error: {code, message, correlation_id, retryable}}` envelope.
New safe details, if needed, are a discriminated, bounded schema with fixed codes
and canonical IDs; validation messages never echo raw untrusted values.

| HTTP | Code | Meaning / retry |
|---|---|---|
| 400 | `CURSOR_INVALID` | Malformed, expired, tampered, or scope/filter/sort-mismatched cursor; restart traversal |
| 401 | `AUTHENTICATION_REQUIRED` | Missing/invalid session, bearer, or cookie CSRF; authenticate correctly |
| 403 | `ACCESS_DENIED` | Authenticated but missing required scope/entitlement |
| 404 | `NOT_FOUND` | Missing or foreign-owner resource; no ownership oracle |
| 409 | `IDEMPOTENCY_KEY_REUSED` | Same scoped key, different canonical request |
| 409 | `IMMUTABLE_VERSION` | Published content edit attempted |
| 409 | `INVALID_STATE_TRANSITION` | Action incompatible with lifecycle |
| 409 | `SOURCE_REVISION_CONFLICT` | Supplied expected source/version changed before pinning |
| 410 | `ARTIFACT_EXPIRED` | Artifact retention ended; regenerate explicitly |
| 412 | `REVISION_MISMATCH` | Supplied If-Match is stale; reread and review |
| 413 | `REQUEST_TOO_LARGE` | Body exceeds 64 KiB; no command record created |
| 422 | `VALIDATION_FAILED` | Invalid typed value, identifier, range, enum or shape |
| 422 | `TARGET_VALIDATION_FAILED` | Attempted publication of invalid content |
| 422 | `CURRENCY_MISMATCH` | Missing explicit permitted FX conversion or mismatched currency |
| 422 | `RESULT_TOO_LARGE` | Requested unpaginated result/artifact exceeds bound; narrow request |
| 428 | `REVISION_REQUIRED` | Required If-Match is absent |
| 429 | `COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED` | Shared durable traversal quota exhausted; retryable |
| 429 | `RATE_LIMITED` | Application/provider configured rate bound; retryable with safe Retry-After |
| 503 | `PROVIDER_UNAVAILABLE` | Required configured capability cannot currently supply data; retryability follows safe category |
| 503 | `JOB_DISPATCH_UNAVAILABLE` | Durable command exists but dispatch cannot proceed; same identity must be retried/recovered |
| 500 | `INTERNAL_ERROR` | Safe correlation-only failure; no stack, SQL, path or provider body |

Valid optimizer infeasibility and missing analytical coverage are typed outcomes,
not transport errors. A durable job may remain queued while its outbox retries;
never return a success state for a task that did nothing. No new route relaxes
the Trading 212 allowlist. Contract tests cover malformed/unknown inputs,
cross-owner/account references, exact scopes, CSRF, ETags, idempotency races,
quota races/rollback, immutable versions, bounded serializers, download/license
expiry, restart recovery, safe failures, generated drift, and canonical
API/web/MCP/report parity. Required checks and evidence are recorded in the
Phase 2 test strategy and acceptance matrix, not inferred from this design.
