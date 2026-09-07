# Phase 2 Data Model

**Status:** Accepted

**Date:** 2026-09-07

**Release:** 0.2.0 design contract; implementation evidence is separate

This document extends the existing [domain model](DOMAIN_AND_DATA_MODEL.md).
It implements the current owner's Phase 2 assignment under ADRs
[0009](../adr/ADR-0009-PROVIDER-TRANSPORT-ISOLATION.md),
[0010](../adr/ADR-0010-IMMUTABLE-VIRTUAL-TARGETS.md),
[0012](../adr/ADR-0012-MARKET-SOURCE-SNAPSHOTS.md), and
[0013](../adr/ADR-0013-ECONOMIC-ENTITY-NORMALIZATION.md). Phase 1 evidence remains
anchored at `99df47b6633791c3900a52f46f56d48be922a436`; this document does not
claim that the new schema or services have been implemented.

## 1. Shared persistence rules

PostgreSQL remains authoritative. Each new table described below contains an
`owner_id` foreign key and a UUID primary key unless its row identity is an
explicit composite key. Child rows include `owner_id`, even when ownership could
be inferred from a parent. Parents expose a unique `(owner_id, id)` key; child
foreign keys include both columns. No ordinary command changes an entity's
owner. Account-associated aggregates carry `broker_account_id`; their children
must reference the same account. A database constraint trigger checks this
association through the existing account/connection/owner graph. Application
authorization performs the same check before reading or writing. Existing
global `instruments` and `listings` remain canonical identity references, while
private mappings, classifications, provider entitlements, and calculations are
owner-scoped. UUID possession is never authorization.

Money, quantity, price, FX, weight, ratios, and authoritative outputs use the
existing `NUMERIC(38,18)` representation and Decimal boundary: at most 20 integer
digits and 18 fractional digits. Reject nonfinite
values, binary-float inputs, excess input scale, and numeric overflow before
database dispatch; PostgreSQL scale rounding is not input validation. Every
monetary column has an adjacent currency or an unambiguous currency foreign key
within its immutable aggregate. Ratios are fractions, never percentage points.
Authoritative arithmetic explicitly uses local precision 80 and `ROUND_HALF_EVEN`;
it never depends on or mutates the process-global Decimal context. Declared
stored output quantum is `1e-18`. Exact target path products and their sums use
an expanded local context of 160 digits before that output boundary.
Display rounding does not modify stored results.

Instants use aware UTC `TIMESTAMPTZ` through the existing `UTCDateTime` boundary;
naive instants fail. `DATE` is reserved for economic/session dates and carries a
documented exchange-calendar or cash-flow convention. Source effective time,
first retrieval time, valuation time, source cutoff, and calculation time are
separate fields. Null values require an availability/reason field where absence
changes interpretation; zero is a valid value, never a missing-data sentinel.

`created_at`, actor principal, schema version, and provenance references are
required on user-owned aggregates and published source/results. Provenance is
normalized into source-reference joins where it determines calculation inputs.
Small warning/assumption lists and canonical manifests may use JSONB only behind
named, versioned schemas with fixed fields and bounds. Financial entities,
constraints, provider responses, and rules are not untyped JSON documents.

## 2. Virtual portfolios and immutable target versions

| Table | Required content and relational constraints |
|---|---|
| `virtual_portfolios` | `broker_account_id` nullable only for a private template; name (1..120), description (0..2000), reporting currency, optimistic `revision >= 1`; owner, account association and reporting currency are fixed at creation |
| `virtual_portfolio_events` | Portfolio FK, sequence, `created`/`metadata_updated`/`archived`, actor and time; unique portfolio/sequence; append-only lifecycle/audit record |
| `target_versions` | Portfolio FK, sequential version number, optional parent-version FK in the same portfolio, reporting currency, effective time, draft revision, schema/method versions, optional published time and content digest; unique portfolio/version number |
| `target_version_events` | Version FK, sequence, `draft_created`/`draft_updated`/`validated`/`published`/`activated`/`superseded`/`archived`, actor, time, preceding event FK and validation-result FK when published; append-only |
| `target_nodes` | Version FK, stable node key retained when cloning, parent node FK within the same version, `group`/`holding`/`cash` kind, display name, sibling order, relative weight; unique version/node key and version/parent/sibling order with NULLS NOT DISTINCT for top-level parents |
| `target_holdings` | Exactly one row per holding node; canonical instrument FK nullable only for unresolved/ambiguous state; optional `listing_id` FK selects actual-allocation scope; separate optional `preferred_listing_id` FK selects funding preference; mapping-decision FK and `resolved`/`unresolved`/`ambiguous` state; every supplied listing belongs to the mapped instrument |
| `target_mapping_decisions` | Version and holding FKs, typed requested identifier (`isin`, provider key, or MIC+ticker), selected canonical instrument/listing when resolved, method/version, confidence, actor/source and effective time; decisions referenced by publication are immutable |
| `target_constraints` | Version FK, stable constraint key, optional node FK, fixed constraint kind, exact bound/amount/weight and currency where applicable, priority coefficient; each kind has a checked field combination described below |
| `target_exclusions` | Version FK plus canonical instrument/listing or target-node FK, bounded reason; uniqueness prevents repeated exclusions; exclusion does not remove observed value from actual allocation |
| `target_validation_results` | Version FK, `input_revision`/pre-validation digest and `result_revision`/post-normalization digest, method version, normalization requested/applied flags, `valid`/`invalid` and evaluation time; publication checks the result revision/digest |
| `target_validation_issues` | Owner/validation composite FK, ordinal, stable code, severity, copied stable node/constraint keys and bounded remediation; no FK to replaceable draft nodes/constraints and no arbitrary executable expression |
| `target_normalization_adjustments` | Owner/validation composite FK, copied stable node key, original and normalized weights, original sibling sum and deterministic remainder rank; no FK to a replaceable draft node |

A virtual portfolio is the conceptual root at depth zero; it has no target-node
row and no weight. A version has at most 256 actual target nodes. Top-level nodes
have a null parent and depth one; maximum leaf depth is eight, so a path contains
at most eight weighted factors. Groups have at least one child; holding/cash
leaves have no children. Other nodes have exactly one parent in the same version;
cycles, unreachable nodes, duplicate node keys, and overlapping resolved holding
selectors fail validation. Every path must reach a top-level node.
At most one cash leaf exists, at top level, in the target version's reporting
currency. When absent, analytics includes actual cash at target zero without
inserting a node. Different listings or
share classes mapped to one economic entity produce a duplicate-exposure warning,
not a fabricated identity collapse.

A resolved holding requires an instrument. Its optional `listing_id` is an
actual-allocation selector: null aggregates every listing of that instrument;
non-null selects exactly that listing. Within one target version, an instrument
may have one instrument-wide leaf or distinct listing-specific leaves, never
both. Every actual position therefore maps to at most one leaf; instrument-wide
aggregation still retains listing/currency provenance and sourced FX. A funding
`preferred_listing_id` must belong to the instrument and, for a listing-specific
leaf, equal its selector. Without a preference, a listing-specific leaf uses its
selector; an instrument-wide leaf can resolve funding only when exactly one
eligible canonical listing exists. Otherwise planning is unavailable with
`listing_choice_required`. The finalized request pins this resolution and does
not mutate the target. Unresolved/ambiguous mappings retain requested identifiers
and evidence without inventing a canonical instrument or listing.

Each sibling set has weights in `[0,1]` and a positive sum. Publication requires
exact sum one. Explicit `normalize=true` may correct only
`abs(sum - 1) <= Decimal('1e-12')`: divide each weight by the original sum, floor
to `1e-18`, then assign remaining units by descending discarded remainder and
ascending stable node key. Retain the original weights and every adjustment.
Without explicit normalization, any nonzero residual is an error. Materially
invalid sums fail; no automatic cash node or hidden redistribution is created.
An effective leaf weight is the exact product of normalized weights on its root
path. Eight weighted factors have at most 144 fractional product digits.
Reported effective weights are quantized to `1e-18`
and carry `effective_weight_rounding_residual = 1 - sum(reported leaf weights)`.
Calculations reconstruct exact products from the immutable sibling weights;
the display/persistence residual is disclosed rather than silently redistributed.
Unclassified actual positions remain a separately named actual-allocation row
with target zero; their observed value stays in the denominator.

Constraint kinds are `minimum_funded_amount`, `amount_increment`,
`minimum_post_weight`, `maximum_post_weight`, `minimum_group_funding`,
`maximum_group_funding`, `cash_reserve`, `eligible`, `maximum_funded_lines`, and
`priority`. Amount constraints require a currency matching the target version;
weights lie in `[0,1]`, increments are positive, minima are nonnegative, and the
funded-line bound is an integer from 0 through 256. Check minimum <= maximum at
the same scope and detect contradictions between ancestor/descendant scopes.
`minimum_funded_amount` allows zero or requires its minimum once funded.
Group funding bounds apply only to groups. Post-weight bounds are absolute shares
of full post-contribution portfolio value, never relative sibling weights.
The funded-line limit counts holdings, excluding residual cash.
An exclusion takes precedence over eligibility but does not relax a minimum;
the resulting contradiction must remain explicit.

| Constraint kind | Allowed scope and checked value fields |
|---|---|
| `minimum_funded_amount` | Holding only; nonnegative amount/currency; zero allocation remains allowed |
| `amount_increment` | Holding only; positive amount/currency, exact multiple of plan monetary quantum |
| `minimum_post_weight`, `maximum_post_weight` | Holding or group; exact weight in [0,1] of full post-plan portfolio |
| `minimum_group_funding`, `maximum_group_funding` | Group only; nonnegative amount/currency of new descendant holding allocations |
| `cash_reserve` | Portfolio scope; nonnegative minimum post-plan cash amount/currency and/or weight in [0,1]; existing cash counts and the stricter bound applies |
| `eligible` | Holding only; boolean; omitted defaults true subject to mapping/exclusions |
| `maximum_funded_lines` | Portfolio scope; integer 0..256 |
| `priority` | Holding/group scope; exact coefficient in [0.000001,1000], default one |

Other value columns are null for each checked kind. Amount constraints cannot
use a foreign currency, and arbitrary extra parameters fail. Request-level
`monetary_quantum` is an optional exact power of ten no larger than the versioned
currency minor unit and with scale at most 18; the default is that minor unit.
Requests retain the quantum/currency-policy version. Contribution, amount bounds
and increments must be exact multiples of it before optimization.

Draft content changes atomically under `If-Match` and increment its draft
revision. Publication locks the portfolio and draft, validates its complete
content, seals a canonical digest, records publication, and appends lifecycle
events in one transaction. Every new validation retains both input and result
aggregate revisions and advances the latter once because latest-validation
metadata changes. Normalization additionally records any changed weights;
an exact idempotent replay does not advance the revision again.
Publication requires that result revision and its post-normalization digest to
match the current draft. Old validation rows retain stable keys and values even
if later draft replacement removes the named nodes. Published nodes, mappings, weights, constraints,
effective time, reporting currency, and digest cannot be updated or deleted by
ordinary application roles. Corrections clone a new draft/version. `active`,
`superseded`, and `archived` are lifecycle projections over append-only events,
not edits to published content. Publishing a version already effective activates
it in the publication transaction; a future-effective version is scheduled.
A bounded worker scans due scheduled versions by `(effective_at, version_number,
id)` under the same portfolio lock. An overdue candidate overtaken by an active
version published later than the candidate and at or after its effective time
is marked superseded with an audit event and no activation; it cannot undo that
newer explicit publication. Otherwise activation appends an event and supersedes
the prior active version atomically. Record logical effective time and actual
recording time separately; a delayed worker cannot backdate knowledge. Unique
version/activation identity makes restart/retry idempotent. At most one active
version exists per unarchived portfolio.

Current selection follows activation/lifecycle events; it is not a latest
unarchived-version fallback query. Archiving the active version clears selection
and leaves no active target until a newly published due version or a never-before
activated scheduled version activates. Archiving a scheduled version prevents
its activation; archiving a draft/superseded version leaves current selection
unchanged. Archived/superseded content is not reactivated; clone a new version.
Archiving the portfolio disables current selection and future activation while
preserving explicit historical version access. Every historical result keeps its
version reference. An explicit new version may have an earlier effective time,
but its publication/activation is known only at its actual recording time and
never rewrites earlier results or earlier-cutoff selection.
Unresolved mappings may be published with warnings, but affected planning or
classification remains unavailable/partial according to its material-input rule.

## 3. Contribution plans and analytical results

| Table | Required content and relational constraints |
|---|---|
| `contribution_plans` | Account and virtual-portfolio FKs, stable plan identity, creator, creation time; revision history is separate |
| `contribution_plan_requests` | Plan FK, sequential revision number, target-version and portfolio-snapshot FKs, contribution/currency, mode, restricted node references, policy/method versions, input digest, idempotency command FK; immutable |
| `contribution_plan_request_constraints` | Request FK and typed constraint overrides with stable keys; may tighten declared targets only when explicitly requested; every effective constraint is retained |
| `contribution_plan_revisions` | One finalized result per request, outcome, method/solver version, canonical digest, pre/post objectives and drift, residual cash/currency, calculation/source times and quality; immutable when finalized |
| `contribution_plan_lines` | Revision FK, deterministic ordinal and target-node/canonical listing references; current/target/post values and weights, nonnegative recommended amount/currency; unique revision/line identity |
| `contribution_plan_explanations` | Revision FK, ordinal, stable reason, related constraints, feasibility proof/bound kind and excluded/unresolved component references |
| `analytics_runs` | Account FK, fixed calculation kind, input digest, method/version, reporting currency, valuation/cutoff/calculation times, availability, quality, coverage, exact residual and canonical output digest |
| `analytics_run_sources` | Run FK and exactly one typed source reference (portfolio snapshot, target version, price/FX/benchmark/constituent snapshot or mapping revision); no arbitrary query text |
| `performance_points` | Run FK and valuation instant, portfolio value, external flow, net contribution, income, fee/tax, period/linked return and drawdown with per-metric availability; unique run/time |
| `attribution_components` | Run FK, instrument/group/cash/residual component identity, price/income/fee/tax/FX contributions with available/unsupported decomposition states |
| `income_components` | Run FK, currency and instrument/group/period identity, gross/net dividends, withholding, yield/growth/concentration when supported; no implicit cross-currency aggregation |

Planning modes are `global`, `hierarchical`, `restricted`, and `cash_only`.
Requests use a published target version and immutable portfolio snapshot in the
same authorized account. Contribution currency equals reporting currency; an
upstream explicit conversion must pin its exact FX observation before creating
the request. A subsequent calculation creates a new request/revision under the
same plan identity, leaving earlier requests and results unchanged. Outcome is
`optimal`, `feasible_nonoptimal`, `infeasible`, `unavailable`, or `failed`, distinct
from job execution state. A feasible result must prove exact
`contribution = sum(recommended amounts) + residual cash` after rounding and
must satisfy every hard constraint. No plan line is an order, executable broker
instruction, or predicted return.

Historical intelligence extends the existing analytical run and source tables.
An immutable input capture retains normalized opening positions/cash, independent
reconciliation and bridge evidence, candidate economic revisions, exact per-source
calendar/mapping/license versions and selected observation uses. Candidate broker
facts come from minimized immutable source records and occurrences; current
transaction/dividend/ledger projections may change and cannot serve as replay
inputs. An individual execution has the economic identity `(order.id, fill.id)`;
an order without a proven fill is not an execution.

Historical policy and evidence registration are fixed internal owner-authorized
operations, not public arbitrary-data commands. They retain actual receipt time
separately from economic validity. A narrow sector/asset-class evidence projection
may support historical attribution before the full entity/look-through catalog;
it carries taxonomy/version, validity, first knowledge, license and source links.
It never infers classification from an instrument name or wrapper type.

Publication seals the full capture/result bytes and normalized child rows in one
transaction. Canonical financial digests exclude generated row/run IDs and actual
capture/calculation clocks, while including input-affecting source identities,
knowledge times and policies. Repeated equivalent requests reuse that immutable
identity. Every dependent source is owner-bound and reauthorized on replay;
permitted retained hashes do not establish that deleted licensed data remains
reproducible. Composite benchmark wealth uses the explicit composite branch and
normalized component/FX/license dependencies, with no invented provider/license.

## 4. Market, FX, benchmark, and classification sources

| Table | Required content and relational constraints |
|---|---|
| `market_data_providers` | Owner, fixed adapter key/version, configuration state, opaque secret reference, server configuration revision and current license-version FK; no provider credentials or arbitrary request URL |
| `provider_license_versions` | Provider FK, effective time/version, attribution text, permitted storage/display/report/export flags, retention bounds and evidence reference; immutable; unknown permissions deny that use |
| `source_retrieval_occurrences` | Provider FK, exactly one typed price/FX/benchmark/constituent snapshot FK, retrieval time and safe receipt category; repeated identical data appends an occurrence while preserving first knowledge time |
| `market_data_instruments` | Provider FK, bounded provider instrument key, canonical instrument/listing FKs where resolved, mapping state/version, currency and asset type; unique provider/key/mapping version |
| `market_source_series` | Immutable owner-scoped catalog identity with `security_price` or `benchmark_level` kind, provider/license/mapping version, basis, currency and calendar; benchmark levels do not require a fabricated canonical instrument |
| `price_snapshots` | Provider/instrument mapping FKs, requested period, price basis (`raw_close`, `split_adjusted`, `total_return`), source currency, effective/retrieval times, source/schema/license versions, canonical digest, coverage/gap state; immutable |
| `price_observations` | Snapshot FK, exchange/session date and valuation instant, exact price/index level, currency, corporate-action revision reference, observation availability; unique snapshot/session/basis |
| `corporate_action_observations` | Provider/instrument FKs, source snapshot/digest, fixed action kind, effective date, split ratio or distribution/currency, status and correction reference; never infer an unsupported action |
| `fx_snapshots` | Provider/license FKs, period, source and retrieval times, canonical digest, method/schema version, coverage and gaps; immutable |
| `fx_observations` | Snapshot FK, base/quote currencies, effective instant, positive rate and provider sequence/revision; unique snapshot/pair/time; inverse/triangulated rates pin the original one/two observations |
| `benchmark_definitions` | Owner, stable name/key, reporting currency and optimistic revision; archive lifecycle preserves used definitions |
| `benchmark_versions` | Definition FK, sequential version, effective time, return basis, rebalancing calendar/rule and content digest; published content immutable |
| `benchmark_components` | Version FK, immutable source-series catalog FK and exact weight; weights sum exactly one under the target normalization policy |
| `benchmark_snapshots` | Closed `provider_series`/`composite` kind with mutually exclusive references: provider series requires source-series/provider/license FKs and no benchmark-version FK; composite requires a benchmark-version FK and normalized component/FX inputs. Period, effective/retrieval times, canonical input digest, methodology and coverage are immutable |
| `benchmark_observations` | Snapshot FK, session/valuation instant, exact level, native/reporting currencies, FX reference and availability; unique snapshot/time |
| `economic_entities` | Owner-scoped economic company/issuer identity, stable canonical key, display name, optional LEI and evidence references; provider IDs and tickers are not identity |
| `share_classes` | Entity FK, canonical instrument FK, class identifier and evidence/version; unique owner/instrument/effective version |
| `instrument_entity_relationships` | Instrument/listing/share-class/entity FKs as appropriate, `listing_of`, `share_class_of`, `depositary_receipt_of`, or `issuer_parent` kind, valid interval, exact receipt ratio where applicable, evidence, method/version and confidence |
| `classification_assignments` | Entity/instrument FK, one classification dimension (`sector`, `industry`, `country`, `region`, `economic_currency`), taxonomy/version, category, valid interval, source and confidence |
| `fund_definitions` | Canonical fund instrument FK, fund key/type, share-class association, provider mapping and entitlement references |
| `constituent_snapshots` | Fund/provider/license FKs, effective/source/retrieval dates, source version/digest, stated coverage, known/unresolved/cash weights and freshness; immutable |
| `constituent_holdings` | Snapshot FK, stable source constituent key, exact weight, optional canonical instrument/entity mapping FK, source currency and explicit mapping state/confidence; unique snapshot/source key |
| `xray_runs` | Account/portfolio-snapshot FKs, valuation/cutoff times, method/schema version, absolute/normalized-view mode, digest, direct/fund/classification coverage, unresolved weight and quality |
| `xray_run_sources` | X-ray FK and pinned constituent snapshot, relationship version or classification-assignment FK; one explicit source per edge used |
| `xray_exposures` | Run FK, entity/classification/unresolved bucket, exact direct/indirect/effective weights and values/currency, confidence and coverage |
| `xray_exposure_paths` | Exposure FK, source position, fund/constituent and mapping relationship references, exact path weight; distinguishes the direct position from its look-through path |
| `etf_overlap_pairs` | Run FK, canonically ordered pair of funds, exact overlap weight, common entity count, covered/unresolved weights and quality; one row per unordered pair |

The source catalog is an identity layer, not a mutable latest-snapshot pointer.
Benchmark command component `source_id` fields reference this catalog, never an
observation snapshot or another benchmark definition. This clarifies the original
abbreviated version/provider/license relationship without a circular dependency:
P2-03 serves actual provider levels through the frozen benchmark-snapshot routes;
P2-04 adds calculated composite wealth through the other explicit header variant.
Creating a definition does not fabricate observations or a composite result.

Observation revisions append a new snapshot with a new digest; an unchanged
canonical dataset reuses the same snapshot and records an additional retrieval
occurrence. Retrieval occurrences never modify the snapshot's original
knowledge time. A calculation pins exact source snapshots rather than a mutable
provider's "latest" pointer. Source selection excludes effective or retrieved
times after its declared cutoff. Currency conversion and historical constituent
selection preserve their exact selected observations and disclose gaps.
Source metadata is minimized and versioned before hashing; no credential,
signed URL, reversible URL derivative, or provider raw payload is retained.

Fund look-through replaces the fund leaf's classification path with constituent
paths; it does not add both the fund wrapper and all its constituents to company
exposure. Unknown constituent weight remains an unresolved bucket, not cash and
not a redistributed known holding. Receipt ratios describe security-unit
mapping; already valued exposure is not multiplied by that ratio again.

## 5. Reports, exports, and durable jobs

| Table | Required content and relational constraints |
|---|---|
| `report_definitions` | Owner/account scope, fixed report type, period rule, selected fixed section kinds, template version, reporting currency and revision |
| `report_jobs` | Definition/account FK, immutable requested period/sections/formats and canonical source references, request digest/idempotency FK, execution state, lease/heartbeat/attempt bound, safe failure code, requested/expiry times |
| `report_manifests` | One immutable canonical manifest per successful job; schema/method/template versions, exact pinned inputs, section hashes, license decisions, assumptions/quality/coverage and manifest SHA-256; generation time excluded from canonical digest |
| `report_artifacts` | Job/manifest FKs, format, verified MIME type, safe filename, byte length, SHA-256, `BYTEA` contents, creation/expiry times and deletion state; unique job/format |
| `export_jobs` | Owner/account, fixed export dataset kind, period and source references, CSV/JSON/XLSX format, safe field-set enum, request digest/idempotency FK and durable execution state |
| `export_manifests` | One immutable fixed-schema manifest per successful export job; dataset/column-set/schema/method versions, pinned source IDs/digests, license decisions, exact coverage and canonical digest |
| `export_artifacts` | Export-job and export-manifest FKs, format/MIME/filename, `BYTEA`, length/hash, expiry/deletion state |
| `artifact_download_grants` | Owner/account and exactly one report/export artifact FK, token hash, issue/expiry times, used/revoked state; raw token and URL are never stored |
| `report_dispatch_outbox` | Report-job FK, fixed task `reports.generate.v1`, schema version, state, bounded publication attempts and fenced claim; unique job/task version |
| `export_dispatch_outbox` | Export-job FK, fixed task `exports.generate.v1`; same bounded transactional dispatch semantics |
| `contribution_plan_jobs` | Request FK, fixed calculation version, execution state, fenced lease, attempts, heartbeat and safe failure code |
| `contribution_plan_dispatch_outbox` | Plan-job FK, fixed task `plans.calculate.v1`; unique job/task version |

Binary storage defaults to PostgreSQL `BYTEA`: at most 10 MiB per artifact,
25 MiB aggregate per report job, at most four formats, default seven-day expiry
and maximum 30-day retention. A typed storage port permits a future configured
private backend without changing authorization or returning provider URLs.
Report completion atomically seals the manifest and all requested artifacts;
partial formats cannot be exposed as a complete job. Artifact grants expire
within five minutes and require the owner session/token on every download.
Expiry first denies reads, then deletes bytes in bounded `SKIP LOCKED` batches;
keep only permitted audit/manifest digests after byte deletion.

Each fixed-purpose job has its own typed dispatch row; there is no public
generic task name, command string, URL, filesystem path, or arbitrary JSON task
payload. Job and outbox commit together. Reuse the existing pattern of fenced
claims, a maximum of eight publication attempts and four consumer attempts,
stable job UUID task identity, and append-only attempt/audit records. A recovered
consumer verifies owner/account scope and input digest before working. Redis
holds delivery coordination only. Phase 1's `portfolio.refresh` outbox contract
remains unchanged. Execution states are `queued`, `running`, `succeeded`,
`failed`, `expired`, and `cancelled` where cancellation is explicitly supported;
expired leases recover the same logical job, never a new idempotency identity.

## 6. Alert rules, events, and delivery

| Table | Required content and relational constraints |
|---|---|
| `alert_rules` | Account FK, stable name, revision and current version projection; lifecycle `draft`/`active`/`paused`/`archived` is event-derived |
| `alert_rule_versions` | Rule FK, immutable sequential version, fixed metric/rule family, scope references, comparison enum, exact threshold/currency, severity, quality policy, schedule, cooldown, source policy and digest |
| `alert_rule_events` | Rule/version FK, lifecycle transition, actor/time and sequence; append-only |
| `alert_evaluation_jobs` | Account/rule-version FK, scheduled instant, exact input snapshot/cutoff, fixed method version, durable state/lease/attempts; unique rule version/scheduled instant/input digest |
| `alert_evaluation_outbox` | Evaluation-job FK, fixed task `alerts.evaluate.v1`, bounded publication state/lease/attempts |
| `alert_evaluations` | Rule-version/job FKs, canonical input digest, method/cutoff/evaluation time, `matched`/`not_matched`/`suppressed`/`unavailable`/`failed`, exact observed threshold metric and material quality; unique rule version/input digest/method |
| `alert_events` | Rule-version/evaluation FK, episode identity/dedup digest, severity, typed safe remediation, opened/resolved times, first/last observed inputs and cooldown deadline |
| `alert_event_transitions` | Event FK, sequence, `opened`/`acknowledged`/`resolved`/`reopened`, actor/evaluation reference and time; append-only |
| `alert_acknowledgments` | Event FK, principal, timestamp, optional bounded note, idempotency command FK; duplicate retries reuse the same acknowledgment |
| `notification_destinations` | Owner/account scope, stable destination ID, current immutable version reference and lifecycle; no raw webhook URL or credential |
| `notification_destination_versions` | Destination FK, sequential version, `in_app`/`email`/`webhook`, safe label, server configuration key, opaque secret reference and verification/configuration state; delivery jobs pin this immutable version |
| `notification_delivery_jobs` | Event/destination-version FKs, fixed channel, payload digest, execution state, lease/attempt limits, retry time and safe failure category; unique event/destination/payload digest |
| `notification_delivery_outbox` | Delivery-job FK, fixed task `notifications.deliver.v1`, bounded publication state/lease/attempts |
| `notification_delivery_attempts` | Job FK, sequential attempt, start/end time, bounded status/provider category and retry decision; no response body, address, URL, or secret |

Rule families cover target/group/holding drift, concentration, effective company
concentration, ETF overlap, cash threshold, stale data, missing coverage,
reconciliation/provider/refresh failure, dividend receipt, deterministically
defined unusual activity, and report completion/failure. A fixed metric enum
and checked parameter schema implement each family; no expression interpreter,
user SQL, trading signal, predicted price, or executable remediation exists.
Input-based evaluation deduplication, event episode identity, delivery
idempotency, acknowledgment, and cooldown are distinct records and constraints.
Absent external destination configuration leaves in-app evaluation/events
functional and records external delivery as unavailable.

## 7. Shared commands, retention, and verification

`application_command_identities` stores owner, optional account, fixed command
kind, caller idempotency key, schema version, canonical request digest and typed
created aggregate references. Uniqueness is owner/account/command/key; compare
the digest before returning an existing result. Retain identities for the
aggregate's life, including safe tombstones after artifact expiry. No request
secret, arbitrary payload, or raw provider data is stored in this table.

Index collection access by owner/account plus declared sort and stable UUID.
Index pending job availability, lease expiry, artifact expiry, source effective
time/cutoff and semantic digest. Bound cleanup to 100 rows per transaction by
default with an inclusive maximum of 1,000 and `SKIP LOCKED`; expired objects
stop counting against active quotas immediately. New mutable collections share
the Phase 1 owner lock and hard default quotas of 64 active traversals and
250,000 active members, including first requests. Source and artifact retention
respects pinned license restrictions; deleting a referenced source must either
preserve an allowed reproducibility record or explicitly mark the dependent
result non-reproducible. Ordinary archive operations never cascade-delete
published history. Authorized owner deletion follows the privacy runbook.

Migrations are additive after `20260907_0008`, linear, repeatable from empty and
supported prior heads, and tested against ORM drift. Required tests cover
cross-owner composite references, account mismatch, numerical/UTC boundaries,
tree cycles and bounds, immutability at service and database boundaries,
concurrent version publication/idempotency, exact snapshot revisions, licensing,
job lease/restart/duplicate delivery, grant expiry, bounded cleanup, and seeded
API/MCP/report parity. SQL constraints supplement, rather than replace,
application validation and authorization.
