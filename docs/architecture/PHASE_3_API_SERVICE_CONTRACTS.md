# Phase 3 API and Service Contracts

**Status:** Accepted implementation design; implementation/validation pending

All routes below are additive under /api/v1. Preserve the existing 87 paths and95
operations and their generated contracts. Authentication, exact issuer/audience,
strict internal IDs, current grants, CSRF/trusted-origin behavior and sanitized
errors remain the existing service boundary. No body accepts owner_id or an
arbitrary transport/query/expression. No public schema uses Any or an untyped map.

## Shared request and result rules

Use canonical IDs, exact Money/currency, existing fixed decimal wire grammar,
UTC instants, 64 KiB bodies, 2 MiB ordinary results and bounded page/cursor contracts.
Page default 25/max100; source/warning preview max64 with exact omitted counts.
Dates and IDs are versioned input references, never implicit instructions to fetch.
Reauthorize before cursor/304/idempotent replay as well as ordinary reads.

The existing application command identity is scoped by owner, fixed command version
and idempotency key; its digest also binds the account and material input.

Every create/run command requires X-Idempotency-Key; modifications to an existing
aggregate require If-Match. Same semantics returns the original logical identity,
changed semantics conflicts. Published definitions change only by creating a new
version. Referenced records must have the correct owner/account and current source
permissions. Write scopes never imply read scopes. Commands append safe audit
in the transaction and never return a successful no-op.

P=portfolio:read, A=analytics:read. Premium scopes are risk:write,
scenarios:write, projections:write, goals:write, research:read, research:write,
preferences:read, preferences:write, aggregate:read and aggregate:write. Account-backed analytics
requires P+A. Research also requires research:read; research mutation adds
research:write. Preferences are owner-scoped, with P for any referenced account.
Aggregation requires P+A+aggregate:read for every member, independently checked.
Selection/run creation additionally requires aggregate:write.
Activity details/transfer disclosure additionally require existing activity:read.

ResultContext retains authorized scope, reporting currency, valuation/source
cutoff/calculation time, input snapshot/digest, method/schema/numeric versions,
availability/reason, quality, coverage, assumptions and bounded provenance.
Individual unavailable metrics are null with a reason, never zero. Historical
statistics, deterministic stress and probabilistic projections use named result
variants. Financial digests exclude operational envelopes, not material assumptions.

Run status is separate from result availability. RiskRunView, ScenarioRunView and
ProjectionRunView contain typed request/job/run references and durable execution
state; result is null until atomic publication. Failed/expired/cancelled work has
safe categories and no fabricated financial result. Published views contain the
same named RiskResult, ScenarioResult or ProjectionResult across API/MCP/reports.

## Risk contracts

Risk MCP preserves accepted correlation IDs up to128 characters in response
metadata. Audit storage retains IDs up to120 characters unchanged; longer accepted
IDs use `sha256:` followed by the full SHA-256 hex digest of the UTF-8 identity.
This reference never truncates the ID or changes semantic idempotency. Stored
command/audit fields remain bounded to120. HTTP retains its existing120-character
correlation acceptance rule and replaces invalid supplied IDs with a generated UUID.

RiskDefinitionContent contains name, description, return_kind=simple|log,
frequency=daily|monthly, calendar reference, annual risk-free and minimum acceptable
return assumptions, rolling window count, confidence=.90|.95|.99, horizon,
regularization=none|diagonal_shrinkage and explicit lambda. Definitions record
missing/outlier/basis policy versions. Validate minimum 20 samples, daily rolling
20..252/monthly rolling 20..120, horizons20/12 maximum and all numeric bounds.

CreateRiskRunRequest pins definition_version_id, portfolio_snapshot_id,
historical_input_snapshot_id, window/currency/cutoff, optional benchmark_version_id
and up to 32 unique canonical asset source mappings. An optional explicit xray_run_id
pins the same owned snapshot/cutoff for concentration and current-weight risk; omission
leaves those projections unavailable and never silently selects a newer X-ray run. It never accepts caller-supplied
return arrays or uses current holding-value changes as asset returns. Missing
material history becomes explicit metric availability; unknown fields fail.

| Method/path | Service / required scope |
| --- | --- |
| GET/POST /accounts/{account_id}/risk-definitions | ListRiskDefinitions / CreateRiskDefinition; P+A, POST adds risk:write |
| GET /risk-definitions/{definition_id} | GetRiskDefinition; P+A |
| GET/POST /risk-definitions/{definition_id}/versions | ListRiskVersions / CreateRiskVersion; POST adds risk:write and If-Match |
| GET /risk-definition-versions/{version_id} | GetRiskVersion; P+A |
| GET/POST /accounts/{account_id}/risk-runs | ListRiskRuns / CreateRiskRun; POST adds risk:write |
| GET /risk-runs/{run_id} | GetRiskRun; P+A |
| GET /risk-runs/{run_id}/matrix | GetRiskMatrix; P+A, same immutable run |
| POST /risk-runs/{run_id}/cancel | CancelRiskRun; P+A+risk:write |

RiskResult separates observed portfolio estimates from current-weight modeled
risk. It includes aligned/omitted counts, period/annualized and rolling volatility,
downside, canonical drawdown, beta/alpha, covariance/correlation with per-cell
availability, historical/parametric tail definitions and values, concentration,
effective holdings, diversification, marginal/component risk and residuals.
Never infer complete modeled portfolio risk from an incomplete selected universe.

RiskMatrixView includes the run/account/definition-version identity, immutable
definition assumptions, historical context with bounded source/warning omissions,
canonical result digest, numeric profile and matrix coverage. Expired matrix inputs
return410; ordinary run status can still show typed expired availability without a
financial result. A definition ETag is its owned id/revision; financial-read ETags
hash the validated public representation after current authorization.

## Scenario contracts

ScenarioVersionContent contains name, description, first_order|compounded mode,
up to 128 shocks and128 exclusions. A shock selects instrument/entity/sector/region/
currency or an explicitly evidenced rate/factor sensitivity with canonical reference,
finite Decimal size and source/version. Equal-priority competing matches are invalid.
Rules preserve the instrument>entity>sector>region hierarchy, explicit exclusions
and separately disclosed currency/factor interactions. No executable expression.

CreateScenarioRunRequest pins scenario_version_id, portfolio_snapshot_id,
xray_input/run reference, reporting currency/cutoff and optional historical replay
window/market knowledge cutoff/holding basis. Published runs retain the actual
inputs, not latest sources. ScenarioComparisonQuery has exactly two distinct owned
run IDs and never recomputes their values or hides method/currency differences.

| Method/path | Service / required scope |
| --- | --- |
| GET/POST /accounts/{account_id}/scenarios | ListScenarios / CreateScenario; P+A, POST adds scenarios:write |
| GET /scenarios/{scenario_id} | GetScenario; P+A |
| GET/POST /scenarios/{scenario_id}/versions | ListScenarioVersions / CreateScenarioVersion; POST adds scenarios:write and If-Match |
| GET /scenario-versions/{version_id} | GetScenarioVersion; P+A |
| GET/POST /accounts/{account_id}/scenario-runs | ListScenarioRuns / CreateScenarioRun; POST adds scenarios:write |
| GET /scenario-runs/{run_id} | GetScenarioRun; P+A |
| GET /accounts/{account_id}/scenario-comparison | CompareScenarios; P+A |
| POST /scenario-runs/{run_id}/cancel | CancelScenarioRun; P+A+scenarios:write |

[ADR-0025](../adr/ADR-0025-SCENARIO-EVIDENCE-AND-COVERAGE.md) concretizes the
X-ray pin as an owned succeeded saved run; the service resolves its complete original
input/result and verifies the exact snapshot/currency/cutoff. Rate/factor definitions
retain source/version/driver pins, never caller coefficient arrays. Historical replay
pins an owned retained historical input and separate holdings/market knowledge bases;
it rejects simultaneous hypothetical shock entries. Source membership and current
rights precede coefficient decoding, and the complete sensitivity expansion shares
one 100,000-row/32 MiB admission bound.

ScenarioResult contains original root/terminal exposure, winning/excluded mappings,
covered/uncovered mass, pre/post/impact components, interaction residual, source
dates and assumptions. A fund wrapper is replaced by its terminal partition;
never count both. Unsupported sensitivities remain unavailable, and total post
value cannot silently assume an unknown shocked component was unaffected.

## Assumptions, projections and goals

AssumptionVersionContent contains ordered canonical asset-class keys, annual mean
log returns/volatilities, exact weights summing1, PSD correlation matrix, reporting
currency, inflation/fee and explicitly modeled tax-drag assumptions, and
monthly|annual|none internal rebalance policy. Annual mean log return is in[-.5,.5],
volatility in[0,1], inflation in[-.1,.5], fee/tax drag in[0,.2]. Tax drag is optional
user-specified modeling, not jurisdictional tax calculation. Definitions identify
assumed values separately from any explicitly pinned calibration evidence.

ProjectionRequest pins assumption_version_id, optional goal_version_id and explicit
initial_basis: observed_snapshot (owned snapshot_id; canonical server-derived value)
or modeled_value (explicit modeled Money and anchor date). It also specifies allocation, seed uint32,1..600 monthly steps,1..4096 paths, up to 121 requested
retained month indices including 0 and the terminal month, and up to 128 schedule
entries. The asset-month-path work product, including sensitivity variants, must
fit 1,000,000 before admission. Negative money, duplicate schedule identity,
invalid weights and inconsistent currencies fail validation.

Contribution schedule contains a base monthly amount, annual growth in[-1,1],
explicit paused months, dated monthly lump sums and withdrawals. All money is in
the declared reporting currency. Sensitivity is optional and contains one monthly
contribution delta and one annual mean-log-return delta. It requests baseline plus
two separate variants with common random numbers and counts all three toward
admission. No silent reduction in paths/horizon/points or different random seed.

The ADR-0027 `calendar_anniversary_clamped_v1` convention derives an observed
anchor from the actual snapshot valuation timestamp in UTC, retaining its full
instant. It computes anniversaries from the original day with destination-month
clamping. Dated flows and pauses must match exact starts; mid-period and
outside-horizon entries fail with typed errors. Target date equals the terminal
boundary. Retain the original dated request and a distinct complete capture digest;
the numerical digest alone does not identify calendar/source intent.

GoalVersionContent pins currency, target amount/date/month horizon, nominal|real
basis, probability objective in[0,1], assumption version and schedule. GoalAnalysis
uses the exact saved projection, with terminal percentile/shortfall distribution,
probability, sampling uncertainty and sensitivity variants. No goal is automatically
accepted merely because modeled success exceeds its chosen objective.

| Method/path | Service / required scope |
| --- | --- |
| GET/POST /accounts/{account_id}/assumption-sets | ListAssumptionSets / CreateAssumptionSet; P+A, POST adds projections:write |
| GET /assumption-sets/{set_id} | GetAssumptionSet; P+A |
| GET/POST /assumption-sets/{set_id}/versions | ListAssumptionVersions / CreateAssumptionVersion; POST adds projections:write and If-Match |
| GET /assumption-versions/{version_id} | GetAssumptionVersion; P+A |
| GET/POST /accounts/{account_id}/goals | ListGoals / CreateGoal; P+A, POST adds goals:write |
| GET /goals/{goal_id} | GetGoal; P+A |
| GET/POST /goals/{goal_id}/versions | ListGoalVersions / CreateGoalVersion; POST adds goals:write and If-Match |
| GET /goal-versions/{version_id} | GetGoalVersion; P+A |
| GET/POST /accounts/{account_id}/projection-runs | ListProjectionRuns / CreateProjectionRun; POST adds projections:write |
| GET /projection-runs/{run_id} | GetProjectionRun; P+A |
| GET /projection-runs/{run_id}/goal-analysis | GetGoalAnalysis; P+A; explicit unavailable when no goal was pinned |
| POST /projection-runs/{run_id}/cancel | CancelProjectionRun; P+A+projections:write |

ProjectionResult returns nominal/real percentile paths, terminal histogram and
quantiles, simulated-path count, actual assumption/seed/model identity, cash-flow
and insolvency summaries, sampling limitations and sensitivity. Results are
estimates under the model, not forecasts guaranteed by the historical portfolio.

## Research, preferences, providers and aggregation

ResearchSummaryQuery selects account, pinned X-ray run, cutoff, entity/event kind,
review state and bounded pagination. ResearchItemView contains retained citation
identity, source publication/observation times, license/retention, source facts,
portfolio facts, owner revisions and explicitly unavailable optional synthesis.
It never returns raw provider metadata or a server-fetchable URL.
Owner note/thesis fields are bounded text with separate risks/catalysts/break
conditions and cited source IDs. Acknowledgment records actor/time and source
revision; a later material source revision remains unreviewed until acknowledged.

| Method/path | Service / required scope |
| --- | --- |
| GET /accounts/{account_id}/research | GetResearchSummary; P+A+research:read |
| GET /research/items/{item_id} | GetResearchItem; P+A+research:read |
| GET/POST /accounts/{account_id}/research/notes | ListResearchNotes / CreateResearchNote; POST adds research:write |
| GET /research/notes/{note_id} | GetResearchNote; P+A+research:read |
| GET/POST /research/notes/{note_id}/versions | ListResearchNoteVersions / CreateResearchNoteVersion; POST adds research:write and If-Match |
| POST /research/events/{event_id}/review | ReviewResearchEvent; P+A+research:read+research:write |
| GET/POST /preferences/layouts | ListOwnerLayouts / CreateOwnerLayout; preferences:read, POST adds preferences:write |
| GET/PATCH /preferences/layouts/{layout_id} | GetOwnerLayout / UpdateOwnerLayout; PATCH adds preferences:write and If-Match |
| POST /preferences/layouts/{layout_id}/archive | ArchiveOwnerLayout; preferences:read+preferences:write, If-Match |
| GET /accounts/{account_id}/premium-providers | GetPremiumProviderStatus; P+A, only currently authorized source metadata |
| GET/POST /aggregate-selections | ListAggregateSelections / CreateAggregateSelection; P+A+aggregate:read for every member |
| GET /aggregate-selections/{selection_id} | GetAggregateSelection; same member authorization |
| GET/POST /aggregate-selections/{selection_id}/runs | ListAggregateRuns / CreateAggregateRun; same member authorization |
| GET /aggregate-runs/{run_id} | GetAggregateRun; same current member authorization; activity:read for transfers |

Provider configuration/credentials/license provisioning is a trusted operational
boundary, not a generic public source-create route. Live unavailable status never
substitutes synthetic data. Acquisition only uses approved typed worker ports.

AggregateSelection contains1..8 unique authorized account/snapshot pairs, reporting
currency, cutoff and explicit economic-identity policy. Maximum10,000 total holding
rows and32 currencies. Repeated ingestion records do not duplicate economics;
genuine holdings in distinct accounts add and retain account provenance. Only
actual counterpart transfer evidence marks flows internal; same date/amount alone
is insufficient. Missing FX or unmatched/ambiguous transfer evidence is disclosed.

## Canonical consumers, reports and errors

Generate clients from authoritative typed OpenAPI. Preserve all old method/path/
operation schemas, and add named premium client families. User-facing pages,
widgets, comparisons and reports use persisted canonical result variants and
source cutoffs, never independently calculated copies. Extend fixed report
sections with risk, scenario, projection, goal and research content and the required
current use permissions; existing reports remain compatible. Report renderer
availability does not override source expiry or permit arbitrary templates.

Retain the existing safe error envelope and established status codes. Invalid
schema/bounds are422; body excess413; absent/current denied scopes403; foreign IDs404;
idempotency conflicts409; revision mismatch412/missing428; capacity429; transient
unavailability503. Analytical missingness is a typed result, not a fake successful
numeric zero. Errors never echo tokens, provider bodies, SQL, user notes or URLs.

## Versioned premium reports

[ADR-0024](../adr/ADR-0024-VERSIONED-PREMIUM-REPORTS.md) preserves the existing
V1 report API and original MCP descriptors. Premium reports use a distinct V2
collection and `report_sections_v2` / `2.0.0` document/context contract over the
shared report engine. V1 never serializes V2 pins through its closed legacy types.
V2 mirrors the six report-only `/api/v1` route shapes under `/api/v2`, with separate
operation IDs/cursor identity. Risk creation pins a succeeded immutable run and
retains complete canonical proof; no arbitrary columns, calculations or URLs.
Seventeen fixed risk tables include six proof tables. The distinct
`risk_xray_paths_v1` proof table retains every selected terminal path's root,
issuer, cash/unresolved state and exact exposure metrics. Its empty descriptor
records an absent risk X-ray pin; it coexists with ordinary X-ray analytical tables.
Existing report scopes, CSRF/idempotency, download grants and byte bounds apply.
The risk-only profile is implemented with local component evidence; full Phase3
acceptance remains pending.

[ADR-0026](../adr/ADR-0026-PREMIUM-REPORT-PROFILES.md) accepts one additive
`report_sections_v3` / `3.0.0` outer format on the same six premium routes. An explicit
closed profile selector negotiates it; omission preserves the current profile2
risk-only request, collection, cursor, canonical bytes and semantic command framing.
Profile3 has closed family literals, actual typed canonical input bindings and an
explicit versioned table-key registry extended only with implemented schemas. New
registry members truthfully extend generated premium unions, preserving previously
emitted documents and existing table meanings; original V1/MCP descriptors stay exact.
Unsupported sections fail before work, never create placeholder success. SQL lists,
counts, cursors, direct IDs, grants and retention all remain profile-scoped. This
profile3 evolution is an accepted design decision, not implemented runtime support.
