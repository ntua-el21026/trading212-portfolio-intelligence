# P2-06 Reports and Exports

**Specification:** implementation contract. **Implementation:** scoped local acceptance at `9e39767b408b38203d88d6e5b41bf0bc1265adfb`; GitHub Actions is explicitly deferred by the owner, not passed. P205 historical evidence remains separate. See the [P206 exact-source local assertion map](evidence/phase-2-p2-06-9e39767.json) and the acceptance scope below.

This contract implements the owner's continuing Phase 2 assignment under the
[design authority order](../DESIGN_INDEX.md), [ADR-0014](../adr/ADR-0014-PRIVATE-REPRODUCIBLE-REPORTS.md),
[report methods §7](../analytics/PHASE_2_METHODS.md#7-private-reports-and-exports),
[API contracts §6](../architecture/PHASE_2_API_SERVICE_CONTRACTS.md#6-reports-and-exports),
[closed MCP registry](../integrations/PHASE_2_MCP_TOOL_REGISTRY.md),
[data model §5](../architecture/PHASE_2_DATA_MODEL.md#5-reports-exports-and-durable-jobs),
and [execution manifest](PHASE_2_EXECUTION_MANIFEST.md). It fixes implementation
choices left open by those authorities without relaxing their limits or broker boundary.
All analytical data comes from the same canonical application/analytics families used
by API and MCP. Trading 212 retains exactly its ten approved GET capabilities.

Scope is an implemented vertical for ten report types, four report formats, seven currently
backed standalone datasets, two field sets and three standalone formats, including
private generation/status/manifest/download through API, web and MCP where authorized.
The fixed eighth export dataset, `alerts`, is assigned to the real P2-07 producer below;
that release obligation is not claimed complete by a P2-06 placeholder. P2-08/P2-09 do
not defer functioning P2-06 interfaces, and P2-10 owns the final release-wide restart gate.

## Scoped local acceptance and CI deferral

P2-06 has scoped local acceptance at `9e39767b408b38203d88d6e5b41bf0bc1265adfb`. GitHub Actions is deferred by explicit owner instruction; no CI pass is claimed. The complete required local gates, exact source bindings and deferred startup observations are retained in the P206 acceptance evidence. Remaining Phase 2 implementation continues under that recorded deferral until the owner resumes CI verification.

The [finalized artifact](evidence/phase-2-p2-06-9e39767.json) closes P2-RPT-001/002/003 and S24–27 only. Ten report types across four formats, seven backed standalone datasets and the tested field-set/format matrix retain their actual assertion and execution scope. Prior development observations below remain historical. No all-page visual review, PDF/UA certification or operational PDF byte identity is inferred.

## 1. Ownership and smallest implementation surface

Domain ownership:

- `packages/domain/src/trading212_domain/reports.py`: closed enums, immutable selections,
  document/cell/context/reference records, type/period/reference rules and hard bounds.
- `packages/domain/src/trading212_domain/report_schema.py`: fixed section/table/column
  registry and standard/audit projections. No runtime schema registration.
- `packages/domain/src/trading212_domain/report_manifest.py`: explicit typed codec,
  canonical record/chunk/section/manifest encodings and hashes; no reflection over
  arbitrary application objects and no financial calculator.

Application ownership:

- `packages/application/src/trading212_application/reports.py`: commands, public result
  records, capture/read/render ports and narrow canonical-family capture protocols.
- `packages/application/src/trading212_application/report_jobs.py`: distinct report and
  export task messages/claims, durable store/publisher ports and fixed retry constants.

The domain/application owner implements these contracts and focused pure tests. Root
owns the package specification, public schemas/adapters, generated contracts and UI.
Persistence owns transactional capture, physical references/authorization, models,
migrations, source-copy retention, worker/dispatcher composition and durable jobs.
Renderer implementation lives in `apps/worker/src/trading212_worker/report_renderers/`
and consumes this document contract. It must not import persistence or implement
another analytical calculation. The worker owns private buffers and temporary files.

Keep existing public historical/X-ray helpers and their DISPLAY defaults unchanged.
Add internal, narrowly typed REPORT/EXPORT-aware capture entry points. Reuse existing
family calculators/stores and canonical published values; reports never recalculate
returns, drift, allocations, overlap, FX, totals, rounding residuals or quality weights.

## 2. Closed enums and commands

All enum values below are exact lowercase wire values. Requests reject extra fields.

```python
ReportType = Literal[
    "monthly",
    "quarterly",
    "annual",
    "portfolio_summary",
    "target_drift",
    "contribution_plan",
    "performance_benchmark",
    "dividend_income",
    "portfolio_xray",
    "quality_reconciliation",
]
ReportFormat = Literal["pdf", "csv", "json", "xlsx"]
ExportFormat = Literal["csv", "json", "xlsx"]
ReportSection = Literal[
    "overview",
    "allocation",
    "targets",
    "drift",
    "contribution_plan",
    "performance",
    "benchmark",
    "income",
    "cash_flows",
    "attribution",
    "xray",
    "quality",
    "activity",
]
ExportDataset = Literal[
    "positions",
    "activity",
    "dividends",
    "targets",
    "plans",
    "performance",
    "xray",
    "alerts",
]
ExportFieldSet = Literal["standard", "audit"]
ReportJobState = Literal["queued", "running", "succeeded", "failed", "expired", "cancelled"]
ReportSourceUse = Literal["report", "export"]  # adapter maps to existing SourceUse
```

Use actual StrEnum classes in implementation. `cancelled` has no public command and is
reserved for audited owner deletion/operational termination. Alerts remains in the
release enum; P2-06 rejects it before any job/outbox/capture until P2-07 supplies the
real canonical producer. Root must record that cross-package obligation explicitly.
Do not return an empty successful alerts export as a placeholder.

Normalized application commands (all immutable keyword-only dataclasses):

```python
class ReportSelection:
    account_id: UUID
    start_date: date
    end_date: date
    source_cutoff_at: datetime  # aware UTC
    snapshot_id: UUID
    reporting_currency: CurrencyCode
    report_type: ReportType
    sections: tuple[ReportSection, ...]  # unique, nonempty, <=13
    formats: tuple[ReportFormat, ...]  # unique, nonempty, <=4
    target_version_id: UUID | None = None
    plan_revision_id: UUID | None = None
    benchmark_version_id: UUID | None = None
    constituent_snapshot_id: UUID | None = None
    template_version: str = FIXED_REPORT_TEMPLATE_VERSION


class GenerateReportCommand:
    selection: ReportSelection
    idempotency_key: str
    ttl_days: int = 7  # 1..30, reject bool


class ExportSelection:
    account_id: UUID
    start_date: date
    end_date: date
    source_cutoff_at: datetime
    snapshot_id: UUID
    reporting_currency: CurrencyCode
    dataset: ExportDataset
    field_set: ExportFieldSet
    format: ExportFormat
    target_version_id: UUID | None = None
    plan_revision_id: UUID | None = None
    benchmark_version_id: UUID | None = None
    constituent_snapshot_id: UUID | None = None


class CreateExportCommand:
    selection: ExportSelection
    idempotency_key: str
    ttl_days: int = 7
```

These are the internal normalized shapes. HTTP request bodies flatten selection fields;
idempotency remains the existing `X-Idempotency-Key` command header, while MCP carries
its exact `idempotency_key` field. No additional MCP field is admitted. `template_version` selects a known bundled
profile, never user template content. No public run-ID/input-ID escape hatch is needed:
server-side resolution pins the actual immutable family input/result and fixed options.
Plan selection always uses the immutable revision, never the stable mutable plan ID.

The MCP `generate_portfolio_report` input must remain exactly:

- Required: `account_id`, `idempotency_key`, `start_date`, `end_date`,
  `source_cutoff_at`, `snapshot_id`, `reporting_currency`, `report_type`, `format`,
  `sections`.
- Optional only: `target_version_id`, `plan_revision_id`, `benchmark_version_id`,
  `constituent_snapshot_id`.
- `additionalProperties: false`. No `formats`, `ttl_days`, `template_version`,
  renderer/policy/method/normalization fields, run/input IDs, destinations or content.
- Adapt singular `format` to a one-element `formats`; use server profile and TTL seven.
- Idempotency key is 1..180 ASCII characters matching `^[A-Za-z0-9._:-]+$`.
- Advertise/enforce all P,N,RW,A,T scopes; `reports:read` is separate retrieval authority.

Dates satisfy start<=end and a difference <=3660 days. Calendar report requests match
one complete named month, quarter or year. Every source/reference input array obeys
the existing 256 bound. Validate referenced account/period/source cutoff/currency and
required scope union before publication; irrelevant references fail, even if authorized.

Required selections, copied from method §7.1:

| Type | Required sections | Additional canonical pins |
|---|---|---|
| monthly/quarterly/annual | overview, allocation, performance, income, cash_flows, quality | complete calendar period; both boundaries and period sources |
| portfolio_summary | overview, allocation, quality | valuation snapshot |
| target_drift | overview, targets, drift, quality | published target and snapshot |
| contribution_plan | overview, targets, contribution_plan, quality | finalized plan revision and its target/snapshot |
| performance_benchmark | overview, performance, benchmark, quality | period valuation/flow sources and benchmark version/snapshot |
| dividend_income | overview, income, cash_flows, quality | period canonical activity snapshot |
| portfolio_xray | overview, xray, quality | X-ray run/input and exact constituent/mapping dependencies |
| quality_reconciliation | overview, quality, activity | valuation/activity snapshot; applicable reconciliation or explicit absence |

Additional targets/drift, plan, benchmark and X-ray sections introduce their respective
pins. Other analytical sections resolve their fixed historical family/options profile.
A required reference cannot be replaced by an unavailable section. A valid pinned
canonical result whose metric/section is unavailable keeps its real reason and state.

## 3. One immutable document/cell model

Use a fixed schema registry plus immutable typed row tuples, not one nested arbitrary
JSON object, per-format DTO copies, user-defined columns, or a general query language.
The registry owns table identity, columns, cell kinds, applicability and stable ordering.
All listed records are frozen, slotted, keyword-only dataclasses; code blocks below
specify fields/signatures rather than supplying executable implementations. UUID fields
use native UUID internally and canonical UUID strings on HTTP/MCP/JSON boundaries.
`Sha256` means exactly 64 lowercase hexadecimal characters. No caller supplies owner ID.
No user/provider text becomes a table key, column key, expression, path or markup.

```python
CellKind = Literal["text", "identifier", "enum", "decimal", "integer", "boolean", "date", "instant"]
CellState = Literal["available", "partial", "unavailable", "failed", "not_applicable"]
DecimalRole = Literal["money", "quantity", "price", "fx", "ratio", "score", "residual"]


class ReportCell:
    kind: CellKind
    value: str | Decimal | int | bool | date | datetime | None
    state: CellState = "available"
    decimal_role: DecimalRole | None = None
    currency: CurrencyCode | None = None
    context_key: str | None = None
    reason_key: str | None = None  # typed note registry reference
    bound_key: str | None = None  # captured canonical bound descriptor
    quality: QualityState | None = None
    origin: ReportMetricOrigin | None = None  # exact closed canonical origin vocabulary
    coverage_key: str | None = None
    confidence: Decimal | None = None  # finite Q18 ratio in [0, 1]
    method_key: str | None = None
    method_version: str | None = None  # present exactly with method_key
    provenance_set_key: str | None = None
    note_set_key: str | None = None


class ReportColumn:
    key: ReportColumnKey  # str; exact membership/order in fixed table registry
    kind: CellKind | None  # None only for fixed metric-union columns
    decimal_role: DecimalRole | None
    optional: bool  # schema applicability, never missing=zero


class ReportTableSchema:
    key: ReportTableKey  # finite registry listed in §4
    schema_version: Literal["1.0.0"]
    columns: tuple[ReportColumn, ...]  # exactly registered order, <=64
    order: ReportRowOrder  # fixed for this table, not caller supplied


class ReportRow:
    key: str  # actual source identity or stable semantic key
    context_key: str
    cells: tuple[ReportCell, ...]  # exactly one cell per registered column


class ReportTableDescriptor:
    table: ReportTableKey
    section: ReportSection | None  # none only for standalone export/common proof
    dataset: ExportDataset | None
    schema_digest: Sha256
    state: Literal["available", "partial", "unavailable", "failed"]
    reason_key: str | None
    row_count: int
    content_digest: Sha256


class ReportDocumentHeader:
    document_schema_version: Literal["1.0.0"]
    selection: ReportSelection | ExportSelection
    owner_id: UUID  # captured authorized scope, not caller input
    valuation_at: datetime
    context_digest: Sha256
    tables: tuple[ReportTableDescriptor, ...]
    document_digest: Sha256
```

Runtime validation is exact-type-aware: reject bool as int, all binary floats, NaN,
infinity, naive timestamps, unexpected enum strings and mismatched cell/column kinds.
Money/price require currency; ratios/quantities do not invent one. FX records retain
explicit base/quote in their fixed table columns. `not_applicable` represents a genuinely
inapplicable optional scalar (for example a cash row's instrument ID), never an analytical
availability substitute. Null metric values require `unavailable` or `failed` plus a reason;
available zero remains the exact decimal zero. Partial numeric metrics retain value,
reason/coverage and the original quality. Canonical bound descriptors preserve exact,
lower-bound and unavailable conclusions without inference by the renderer.

Use existing public role-validated decimal values from canonical results. Do not apply
NUMERIC(38,18) input validation blindly to every already-valid result, and do not expose
private Decimal256 coefficient fields. Serialize a finite Decimal using its validated
public quantum/role without another quantization or float conversion. A stable decimal
string encoding normalizes signed zero and redundant trailing zeros only; exact value,
method quantum and explicitly reported residual/bound metadata remain available.

Common typed context/proof records (domain records, not JSON payloads):

- `ReportContext(key, family, method_key, method_version, schema_version,
  valuation_at, source_cutoff_at, source_at, quality, provenance_set_key,
  coverage_set_key, note_set_key, reconciliation_key)`. `family` is a closed
  `snapshot|activity|target|planning|performance|benchmark|income|cash_flows|
  attribution|xray|reconciliation` enum. Reuse existing QualityState unchanged.
- `ReportSourceReference(key, kind, subject_id, parent_id, content_digest,
  source_at, first_observed_at, provider_id, license_version_id, mapping_version_id)`.
  Kind is a closed union of the actual existing family reference kinds, qualified by
  family. Source gaps retain actual gap identity; no fabricated observation ID.
- `ReportSourceMembership(provenance_set_key, source_key)` and
  `ReportNoteMembership(note_set_key, note_key)` are sorted normalized relations.
- `ReportLicenseReference(version_id, provider_id, license_digest, attribution,
  pinned_store, pinned_display, pinned_report, pinned_export, valid_from,
  expires_at)` uses the existing permission-state enum (including unknown), not bool
  coercion. Preserve the actual licensed decision/version; no invented legal terms.
- `ReportNote(key, kind, family, code, text, related_provenance_set_key)`; kind is
  `warning|assumption|limitation|unavailable_reason|reconciliation`. Codes are validated
  against the supplying canonical family's existing enums/versioned fixed codes.
- `ReportCoverageFact(set_key, family, metric_key, value: ReportCell)` and
  `ReportBoundFact(key, family, kind, quantum, rounding, positive_below_quantum)`.
  Keys/kinds come from the actual family registry. Copy canonical facts; do not derive
  new coverage, count residuals as economic partitions, or collapse inferred/stale.

The two fixed columns coverage.metric and coverage_facts.value have column kind=None:
they accept only typed decimal/integer/boolean ReportCell variants, retaining actual
role/currency/state. They are not arbitrary text/JSON columns. All other columns retain
one exact kind/role.

All optional IDs are typed absence; textual notes are capped at 4096 Unicode characters.
Full selected source/license/context/proof relations are captured with the document, deduplicated
by actual immutable identity/digest, and resolved by keys. They must remain available
in every artifact through explicit records or the independently retrievable manifest.
Do not discard a reference because it fell beyond a public preview's first 64 entries.
The public manifest retains every selected source/version hash, license, context,
coverage measure, warning, assumption, and source membership within its 2 MiB bound.
Bulk typed proof relations are streamed as ordinary fixed-schema chunk tables: the
manifest binds their exact schemas, row counts and complete row-stream digests. All
four artifact formats include every row. This is lossless partitioning of the canonical
document, not a public preview or omitted proof. Manifest or document overflow fails
explicitly before publication.

## 4. Fixed section/table schemas

Notation: `id` identifier, `text` untrusted text, `enum` fixed canonical enum, `date`,
`utc` aware instant, `int`, `bool`, `M` monetary metric, `R` ratio metric, `Q` quantity,
`D` other role-validated decimal. Every row has the key/context above. Every metric cell
retains state/currency/reason/bound/context; those are not re-expanded into dozens of
ad-hoc financial columns. Common proof tables apply to every section and both field sets.
Column order below is the fixed v1 registry order. Scalar metadata not applicable to
a row remains explicitly not_applicable. Nested collections become fixed relation tables.

| Section / table | Fixed columns and original canonical source |
|---|---|
| overview / snapshot_totals | snapshot_id:id, valuation_at:utc, source_cutoff_at:utc, total:M, cash:M, invested:M, net_contributions:M, dividends_received:M, realized_profit_loss:M, unrealized_profit_loss:M; immutable SnapshotDetail and pinned calculation fingerprint |
| allocation / positions | position_id:id, instrument_id:id?, listing_id:id?, ticker:text, name:text, instrument_type:enum, quantity:Q, trading_currency:enum, current_price:D(price), market_value:M, provider_cost_basis:M, provider_unrealized_profit_loss:M, direct_weight:R; actual snapshot positions, never current AccountSummary |
| allocation / allocation_buckets | dimension:enum, bucket_key:id, name:text, value:M, weight:R, position_count:int; complete canonical direct allocation buckets including explicit cash/unclassified |
| targets / target_nodes | target_version_id:id, node_id:id, parent_node_id:id?, node_key:id, node_kind:enum, name:text, ordinal:int, instrument_id:id?, listing_id:id?, target_weight:R; exact published target version |
| targets / target_holdings | node_key:id, state:enum, instrument_id:id?, listing_id:id?, preferred_listing_id:id?, identifier_kind:enum?, identifier_value:text?, identifier_provider:text?, reason:text?; exact TargetHoldingMapping/TargetIdentifier, preserving unresolved identity |
| targets / target_constraints | target_version_id:id, key:id, kind:enum, node_key:id?, amount:D(money)?, currency:enum?, weight:R?, enabled:bool?, count:int?, coefficient:D(score)?; all actual TargetConstraint fields, never arbitrary expression text |
| drift / drift_rows | key:id, node_id:id?, holding_id:id?, kind:enum, parent_key:id?, name:text, depth:int, listing_id:id?, instrument_id:id?, target_weight:R, actual_value:M, actual_direct_weight:R, effective_weight:R, effective_weight_reason:enum, signed_drift:R, absolute_drift:R, relative_drift:R, relative_drift_reason:enum?, classification:enum?, monetary_gap:M; all DriftCalculation.rows |
| drift / drift_totals | value:M, cash:M, unclassified:M, l1_drift:R, weighted_squared_drift:D(score), effective_weight_rounding_residual:D(residual), group_count:int, holding_count:int, unclassified_count:int; exact DriftTotals, frontier keys in relation table |
| contribution_plan / plan_summary | plan_revision_id:id, outcome:enum, mode:enum, contribution:M, monetary_quantum:D?, currency_policy_version:id, residual_cash:M, current_cash:M, post_cash:M, post_total:M, bound_kind:enum?, examined_moves:int, attempted_assignments:int, exhaustive:bool, execution_allowed:bool(false); exact finalized summary |
| contribution_plan / plan_lines | ordinal:int, node_id:id, holding_id:id, node_key:id, instrument_id:id?, listing_id:id?, current_value:M, target_weight:R, current_weight:R, recommended_amount:M, post_value:M, post_weight:R, minimum_funded_amount:M, value_increment:M, excluded:bool; exact ContributionPlanLine |
| contribution_plan / plan_objectives | stage:enum(before/after/lower_bound/gap), ordinal:int, score:D(score), quantum:D(score), rounding:enum, rounding_error_bound:enum; ordered existing PlanObjective scores, no optimization here |
| contribution_plan / plan_relations | relation_kind:enum(binding_constraint/excluded_node/unresolved_node/frontier), parent_key:id, ordinal:int, member_key:id; exact retained keys; explanations use common notes |
| performance / performance_summary | the 17 PerformanceMetrics fields, in its declared order: beginning_value, ending_value, deposits, withdrawals, net_contributions, investment_gain, income, fees, withholding_taxes, realized_profit_loss, unrealized_profit_loss:M; time_weighted_return, money_weighted_return, modified_dietz_return, annualized_time_weighted_return, annualized_modified_dietz_return, maximum_drawdown:R |
| performance / performance_points | ordinal:int, date:date, valuation_at:utc, portfolio_value:M, invested_value:M, cash_value:M, external_flow:M, deposits:M, withdrawals:M, net_contributions:M, income:M, fees:M, withholding_taxes:M, interval_return:R, cumulative_return:R, twr_wealth:R, drawdown:R, flow_count:int; all canonical PerformancePoint rows |
| performance / performance_periods | kind:enum, period_start_at:utc, period_end_at:utc, method:enum, value:R, annualized_value:R; exact HistoricalPeriodReturn, never derives calendar/rolling returns |
| benchmark / benchmark_summary | portfolio_return:R, benchmark_return:R, excess_return:R, tracking_difference:R, relative_wealth_return:R, annualized_portfolio_return:R, annualized_benchmark_return:R, annualized_tracking_difference:R, tracking_error:R, paired_observation_count:int, comparable_total_return_basis:bool |
| benchmark / benchmark_points | ordinal:int, date:date, valuation_at:utc, portfolio_return:R, benchmark_return:R, excess_return:R, portfolio_wealth:R, benchmark_wealth:R, relative_wealth:R; all canonical points |
| benchmark / benchmark_periods | kind:enum, period_start_at:utc, period_end_at:utc, portfolio_return:R, benchmark_return:R, excess_return:R, relative_wealth_return:R, annualized_portfolio_return:R, annualized_benchmark_return:R; exact HistoricalBenchmarkPeriodReturn, no recomputation |
| income / income_summary | net_income:M, gross_income:M, withholding:M, positive_income:M, negative_corrections:M, mean_invested_value:M, income_yield:R, previous_period_income:M, dividend_growth:R, event_count:int |
| income / income_components | grouping:enum(instrument/group), key:id, label:text, instrument_id:id?, group_key:id?, currency:enum, net:M, gross:M, withholding:M, positive_income:M, negative_corrections:M, concentration:R, event_count:int, unresolved:bool; full instrument and group rows |
| income / income_totals | basis:enum(native/reporting), currency:enum, net:M, gross:M, withholding:M, positive_income:M, negative_corrections:M, event_count:int, positive_event_count:int, correction_count:int; exact CurrencyIncomeTotals |
| income / income_periods | start_date:date, end_date:date, currency:enum, net:M, gross:M, withholding:M, positive_income:M, negative_corrections:M, event_count:int, positive_event_count:int, correction_count:int; actual native CurrencyIncomeTotals for each IncomePeriod |
| income / income_reporting_periods | start_date:date, end_date:date, reporting_net:M; exact IncomePeriod.reporting_net, without fabricating unsupplied reporting metrics |
| cash_flows / cash_flow_summary | event_count:int, filtered_count:int, external_count:int, internal_count:int, unresolved_count:int |
| cash_flows / cash_flow_totals | basis:enum(native/reporting), currency:enum, external_net:M, deposits:M, withdrawals:M, internal_net:M, income:M, fees:M, taxes:M, purchases:M, sales:M, unresolved_amount:M, external_count:int, internal_count:int, unresolved_count:int |
| cash_flows / cash_flow_periods | start_date:date, end_date:date, plus the cash_flow_totals columns; supplied canonical period totals |
| cash_flows / cash_flow_events | ordinal:int, event_revision_id:id, economic_key:id, economic_at:utc, kind:enum, classification:enum(external/internal/unresolved), native_amount:M, reporting_amount:M, instrument_id:id?, listing_id:id?, group_key:id?, correction_of:id?; full canonical events |
| attribution / attribution_summary | investment_gain:M, attributed_amount:M, residual:M, uncovered_residual:M, quantization_residual:M, portfolio_return:R, attributed_return:R, residual_return:R, dietz_denominator:M, cash_drag:R, brinson_allocation:R, brinson_selection:R |
| attribution / attribution_components | key:id, label:text, instrument_id:id?, listing_id:id?, group_key:id?, currency:enum?, amount:M, return_contribution:R, unresolved:bool; all canonical rows |
| attribution / attribution_effects | parent_key:id(portfolio or component), kind:enum(price/income/fees/taxes/fx/interaction/cash_fx), amount:M, return_contribution:R |
| xray / xray_summary | total:M, company_known_weight:R, cash_weight:R, unresolved_weight:R, duplicated_exposure:R, hhi:R; exact XrayPortfolioSummary |
| xray / xray_quality | root_count:int, valued_root_count:int, direct_portfolio_value:M, direct_portfolio_weight:R, inferred_mapping_count:int, inferred_value:M, inferred_weight:R, stale_value:M, stale_weight:R; overlapping XrayQualityCoverage measures, never sum as a partition |
| xray / xray_dimensions | dimension:enum, known:M, cash:M, unresolved:M, known_weight:R, cash_weight:R, unresolved_weight:R, complete:bool, positive_unresolved_below_quantum:bool |
| xray / xray_exposures | dimension:enum, bucket_key:id, name:text, direct:M, indirect:M, effective:M, direct_weight:R, indirect_weight:R, absolute_weight:R, normalized_known_weight:R?, path_count:int, confidence:R?, quality:enum; complete exposures of the pinned selection |
| xray / xray_paths | key:id, root_key:id, root_kind:enum(position/cash), position_id:id?, instrument_id:id?, entity_id:id?, name:text, explicit_cash:bool, unresolved_reason:enum?, reporting_value:M, absolute_weight:R, relative_weight:R, normalized_known_weight:R?, quality:enum, confidence:R?; exact retained paths, relations below |
| xray / xray_held_funds | instrument_id:id, name:text, position_count:int, composition_root_key:id, constituent_snapshot_id:id?, source_at:utc?, unit_coverage:R, cash_weight:R, unresolved_weight:R, complete:bool, quality:enum, confidence:R? |
| xray / xray_overlap_pairs | pair_key:id, left_instrument_id:id, right_instrument_id:id, overlap:R, common_entity_count:int; actual bounded canonical pair result |
| xray / xray_overlap_entities | pair_key:id, entity_id:id, name:text, left_weight:R, right_weight:R, common_weight:R; all retained common entities for each selected pair |
| xray / xray_concentrations | count:int, weight:R; canonical combined concentration for that count, not each member's individual weight |
| xray / xray_concentration_members | count:int, ordinal:int, entity_id:id; exact canonical entity membership/order, no re-ranking arithmetic |
| xray / xray_thresholds | metric:enum, breached:bool?, reason:enum?, bound:enum; preserve lower-bound semantics |
| xray / xray_residuals | key:id, consumer_key:id, kind:enum, value:D(residual), currency:enum?, child_count:int, parent_separately_rounded:bool; exact public residual, no private coefficient |
| xray / xray_path_relations | path_key:id, relation_kind:enum(fund_edge/identity_decision/source/classification), ordinal:int, referenced_key:id; referenced typed proof in fixed family tables |
| quality / reconciliation | reconciliation_run_id:id?, status:enum, evaluated_at:utc?, algorithm_version:id?, tolerance_version:id?, discrepancy_count:int, absent:bool; explicit actual absence, not fake run |
| quality / reconciliation_issues | issue_id:id, type:enum, severity:enum, status:enum, summary:text, expected:D?, observed:D?, residual:D(residual)?, tolerance:D?, currency:enum? |
| quality / coverage | family:enum, coverage_key:enum, metric:ReportCell; existing family coverage measures only |
| quality / notes | note_key:id, kind:enum, family:enum, code:enum, text:text, related_provenance_set_key:id?; all selected warnings/assumptions/limitations/reasons |
| activity / activity | record_id:id, revision_id:id, occurred_at:utc, type:enum, direction:enum, amount:M, ticker:text?, quantity:Q?, description:text, status:enum, correction_of:id?; canonical dated events/revisions, no tax inference |

Implement the registry with explicit names, not a run-time field wildcard. The period
and constraint rows above were checked against actual immutable records. Resolve target
node/holding physical IDs through actual published rows while preserving TargetNode.key,
parent_key, kind, name, order, weight and TargetHoldingMapping; do not manufacture IDs.
Sections may share one captured table where semantics/digest are identical; references
must not create duplicate economic totals.

Standalone dataset schemas are fixed bundles of those same table schemas:

| Dataset | standard bundle | audit additions |
|---|---|---|
| positions | positions, snapshot_totals | actual position revision/source binding, broker valuation basis and sourced FX evidence; no second conversion |
| activity | activity | immutable revisions/economic identity/source membership and reconciliation links |
| dividends | dividends: record_id:id, revision_id:id, paid_on:date, ticker:text, net:M, gross:M, tax:M, quantity:Q? | actual event/economic/revision/source bindings, correction links, existing income conversion evidence |
| targets | target_nodes, target_holdings, target_constraints | publication/version content digest, parent identity and existing constraint/explanation provenance |
| plans | plan_summary, plan_lines, plan_objectives, plan_relations | immutable revision/input/result digests, before/after drift tables and existing constraint/explanation evidence |
| performance | performance_summary, performance_points, performance_periods | full event-source memberships, actual observation/evidence uses and conversion-use records |
| xray | xray_summary, xray_quality, xray_dimensions, xray_exposures, xray_paths, xray_held_funds, xray_overlap_pairs, xray_overlap_entities, xray_concentrations, xray_concentration_members, xray_thresholds, xray_residuals | full selected path/identity/classification/fund-edge/source relations and policy/run/input bindings |
| alerts | reserved until real P2-07 canonical events | reserved with explicit P2-07 positive/parity/security obligations |

Both field sets always include manifest provenance, availability, quality, warnings,
source/license versions and method/currency/valuation. Audit adds explanatory record
relations; standard never hides a material state or turns unavailable into zero.
Fixed proof tables have typed columns for actual existing variants, particularly
HistoricalObservationUse, HistoricalEvidenceUse, HistoricalConversionUse, XrayFundEdge
and X-ray identity/classification decisions. Use one row per closed variant with explicit
schema columns and relation keys; no JSON-in-a-cell escape hatch or raw provider payload.


The common proof registry is finite too. Its following schemas make the full adapters
implementable without a payload escape hatch (actual record order/keys are preserved):

| Proof table | Fixed columns |
|---|---|
| target_exclusions | key:id, node_key:id?, instrument_id:id?, listing_id:id?, reason:text; actual target exclusions |
| historical_anchor_reconciliation | anchor_id:id, policy_version:id, outcome:enum; actual canonical anchor reconciliation |
| historical_reconciliation_lines | anchor_id:id, ordinal:int, kind:enum, identity:id, currency:enum?, expected:D?, observed:D?, residual:D(residual)?, tolerance:D, state:enum; exact supplied comparison, no recomputation |
| historical_reconciliation_anchors | anchor_id:id, ordinal:int, reference_id:id; actual supporting anchor references |
| xray_reconciliation | declared_total:M, root_total:M, difference:M; exact canonical reconciliation metrics |
| xray_warning_paths | note_key:id, ordinal:int, path_key:id; complete canonical warning memberships |
| historical_source_details | source_key:id, kind:enum, semantic_digest:id?, derived_projection_digest:id?, original_fingerprint:id?, version:id?; preserve all supplied fingerprint roles, with the report reference hash binding this canonical metadata |
| historical_source_parents | source_key:id, ordinal:int, parent_id:id; all actual parent identifiers |
| historical_event_identities | revision_id:id, economic_key:id, source_record_id:id, source_occurrence_id:id?, economic_at:utc, first_observed_at:utc, revision_sequence:int?, supersedes_revision_id:id?, record_state:enum, quality:enum, kind:enum, event_digest:id, correction_of:id?; actual captured dated event revisions |
| xray_valuation_roots | root_key:id, root_kind:enum, position_id:id?, snapshot_cash_id:id?, instrument_id:id?, listing_id:id?, original_value:M, reporting_value:M; preserve supplied original and reporting money separately |
| xray_broker_fx | root_key:id, source_reference_id:id, calculation_reference_id:id, source_record_id:id, calculation_run_id:id, listing_id:id, base_currency:enum, quote_currency:enum, rate:D(fx), observed_at:utc, source_observed_at:utc, source:text, quality:enum, confidence:R?, operation:enum; exact retained broker conversion evidence |
| xray_licensed_fx | consumer_key:id, input_value:M, output_currency:enum, leg_count:int; actual saved-value operand, including unavailable conversions with no legs |
| xray_fx_legs | consumer_key:id, ordinal:int, source_reference_id:id, snapshot_id:id, observation_id:id?, coverage_gap_id:id?, base_currency:enum, quote_currency:enum, rate:D(fx), observed_at:utc, first_known_at:utc, operation:enum, quality:enum, confidence:R?, state:enum; exact actual observation or coverage-gap identity |
| xray_dependency_identities | source_key:id, dependency_id:id, kind:enum, subject_kind:enum, subject_id:id, physical_kind:enum, physical_record_id:id, physical_parent_id:id?; preserve semantic and physical dependency roles separately |
| historical_use_consumers | use_key:id, kind:enum, listing_id:id?, instrument_id:id?, event_revision_id:id?, group_key:id?, component_source_id:id? |
| historical_observation_uses | use_key:id, role:enum, use_at:utc, knowledge_cutoff_at:utc, source_kind:enum, snapshot_id:id, observation_index:int, conversion_key:id?, leg_ordinal:int?, direction:enum?, base:enum?, quote:enum? |
| historical_evidence_uses | use_key:id, role:enum, use_at:utc, knowledge_cutoff_at:utc, reference_kind:enum, reference_id:id |
| historical_missing_uses | use_key:id, role:enum, use_at:utc, knowledge_cutoff_at:utc, expected_kind:enum(series/fx_pair), series_id:id?, base:enum?, quote:enum?, calendar_id:id, calendar_version:id, expected_session:date?, reason:enum |
| historical_use_candidates | use_key:id, ordinal:int, candidate_snapshot_id:id |
| historical_conversion_uses | conversion_key:id, use_at:utc, base:enum, quote:enum, operation:enum, rate:D(fx); exact HistoricalConversionUse fields, not a new conversion |
| historical_conversion_legs | conversion_key:id, ordinal:int, leg_use_key:id |
| historical_event_memberships | parent_key:id, ordinal:int, event_revision_id:id |
| xray_selections | key:id, kind:enum, subject_id:id, reason:enum? |
| xray_selection_evidence | selection_key:id, role:enum(candidate/selected), ordinal:int, evidence_id:id |
| xray_source_uses | consumer_key:id, kind:enum, source_reference_id:id, evidence_id:id?, subject_id:id |
| xray_fund_edges | path_key:id, ordinal:int, fund_instrument_id:id, mapping_id:id, candidate_id:id, holding_id:id?, weight:R, origin:enum(holding/header_cash/header_unresolved/remainder) |
| xray_path_classifications | path_key:id, dimension:enum, bucket_key:id?, decision_key:id?, reason:enum?, confidence:R? |
| xray_classification_decisions | key:id, entity_id:id, dimension:enum, bucket_key:id?, reason:enum?, confidence:R? |
| xray_classification_memberships | decision_key:id, role:enum(assignment/evidence/source), ordinal:int, reference_id:id |

`ReportProofRelation` is the explicit closed union of these typed proof-row variants plus
their family-bound counterparts; it is not `dict[str, Any]`. Method/domain names here
must be mapped directly to actual canonical fields. In particular no reporting adapter
may invent a historical observation ID: the real snapshot+observation_index identity is
retained, and missing-use candidates are physical source IDs. A new report-level use of
a source is separate from its original canonical role/use_at/knowledge_cutoff_at.

The complete validated planning operands use these additional fixed proof tables.
The exact `eligible_holding_ids is None` distinction is preserved by
`eligibility_explicit`; empty membership tables preserve an explicitly empty selection.
All option memberships, valuation missing-input keys, source memberships, target content,
node/catalog identities and exact FX operands are included. No report projection derives
new values or replaces an unavailable valuation with zero.

| Table | Fixed ordered columns |
| --- | --- |
| plan_input_header | request_id:id, input_digest:id, virtual_portfolio_id:id, target_version_id:id, target_content_digest:id, target_effective_at:utc, target_published_at:utc, method_version:id, schema_version:id, currency_policy_version:id |
| plan_valuation | snapshot_id:id, account_id:id, reporting_currency:enum, valuation_at:utc, source_cutoff_at:utc, content_digest:id, portfolio_total:M, quality:enum, coverage_complete:bool, reconciled:bool |
| plan_valuation_positions | ordinal:int, listing_id:id, instrument_id:id?, value:M, quality:enum, fx_key:id? |
| plan_valuation_cash | ordinal:int, value:M, quality:enum, fx_key:id? |
| plan_fx | key:id, source_kind:enum, source_id:id, base:enum, quote:enum, rate:D(fx) |
| plan_options | contribution:M, mode:enum, coverage_policy:enum, eligibility_explicit:bool, cash_reserve:M?, monetary_quantum:M? |
| plan_input_members | relation_kind:enum, ordinal:int, member_key:id |
| plan_listing_preferences | holding_id:id, listing_id:id |
| plan_holding_constraints | holding_id:id, minimum_amount:M, value_increment:M, maximum_post_weight:R? |
| plan_allocation_constraints | key:id, kind:enum, node_id:id?, amount:M?, currency:enum?, weight:R?, enabled:bool?, count:int?, coefficient:D? |
| plan_node_identities | id:id, key:id, holding_id:id? |
| plan_catalog_instruments | instrument_id:id, economic_entity_id:id? |
| plan_catalog_listings | listing_id:id, instrument_id:id, eligible:bool |
| plan_source_details | context_key:id, kind:enum, id:id, version:text, content_digest:id, effective_at:utc, first_observed_at:utc |
| plan_effective_constraints | target_version_id:id, key:id, kind:enum, node_key:id?, amount:D(money)?, currency:enum?, weight:R?, enabled:bool?, count:int?, coefficient:D(score)? |

The following final proof tables preserve public canonical fields and configured
benchmark/X-ray policy operands. Private Decimal256 coefficients and unselected raw
provider batches remain outside the report schema; immutable result/source hashes
bind them. Source-use snapshot/index relationships and every public metric/residual
remain complete. `xray_members` is a closed relation table for direct positions,
valuation roots, fund/composition/entity paths, exposure buckets, reconciliation, and
provider order; it cannot introduce arbitrary application records.

| Table | Fixed ordered columns |
| --- | --- |
| benchmark_composite | benchmark_version_id:id, definition_id:id?, definition_digest:id?, published_at:utc?, reporting_currency:enum, return_basis:enum, calendar_id:id, calendar_version:id, rebalance_rule:enum, start_date:date, end_date:date, source_cutoff_at:utc, input_digest:id, method_key:id, method_version:id, component_count:int, observation_count:int |
| benchmark_components | source_id:id, weight:R, calendar_id:id, calendar_version:id |
| benchmark_component_members | source_id:id, role:enum, ordinal:int, reference_id:id |
| historical_options | family:enum, frequency:enum?, return_method:enum?, rolling_window:enum?, calendar_period:enum?, grouping:enum?, cash_flow_kind:enum?, coverage_policy:enum, knowledge_policy:enum, reporting_calendar_id:id?, reporting_calendar_version:id?, input_schema_version:id, input_method_version:id, result_schema_version:id |
| historical_warning_coverage | note_key:id, coverage_key:enum? |
| xray_direct_positions | root_key:id, position_id:id, instrument_id:id, listing_id:id?, reporting_value:M, absolute_weight:R, is_fund:bool |
| xray_fund_entities | fund_instrument_id:id, entity_id:id, weight:R |
| xray_path_weights | path_key:id, dimension:enum, normalized_known_weight:R |
| xray_members | parent_kind:enum, parent_key:id, role:enum, ordinal:int, reference_key:id |
| xray_policy | id:id, version:id, method_key:id, method_version:id, numeric_policy:id, schema_version:id, quality_evaluated_at:utc, valuation_complete:bool, threshold_state:enum |
| xray_policy_components | kind:enum, id:id, version:id, content_digest:id, rule:enum?, secondary_rule:enum?, stale_after_seconds:int?, evaluation_basis:enum? |
| xray_policy_limits | key:enum, value:int |
| xray_taxonomies | dimension:enum, taxonomy_id:id, version:id, key:id |
| xray_threshold_policy | metric:enum, limit:R, comparison:enum, policy_id:id, policy_version:id, source_reference_id:id |

Per-metric quality, origin, coverage, confidence, method and provenance remain on the
typed ReportCell rather than duplicated proof rows. ReportMetricOrigin is the closed
union `observed_provider`, `normalized_provider`, `derived_deterministic`, `estimated`,
`unavailable`, `provider`, `derived`; adapters copy the originating family vocabulary.
The eight optional metadata fields above and the original optional `decimal_role`,
`currency`, `context_key`, `reason_key`, and `bound_key` fields are omitted from
canonical JSON only when None. Required `kind`, `value`, and `state` retain their
defined representation. Decode permits those exact omissions, rejects unknown fields
and explicit noncanonical null fields, and verifies canonical re-encoding. Populated
metadata and explicit unavailable financial values are always retained.

The cell context defaults to its row's required `context_key`. Decimal-cell quality,
coverage set, method name/version, provenance set and note set default to that named
context when omitted. Capture removes an explicit value only when it exactly equals
the referenced context; method name and version are compared and omitted together.
Metric-specific coverage keys and all differing metadata remain explicit. Origin and
confidence have no context default. Nondecimal cells do not inherit metric metadata.

Snapshot position and cash numeric cells combine their stored intrinsic quality with
the snapshot's existing effective quality at the requested source cutoff. Use the
established severity ordering, including for prices and allocation weights whose
denominator is the snapshot total. A stored fresh row cannot override an aged snapshot;
a stronger intrinsic degradation remains visible. This corrects metadata propagation
without changing amounts, availability, origins, freshness thresholds or method versions.
Previously sealed captures remain immutable. Independent historical, planning, X-ray
and reconciliation families retain their own pinned quality.

Before sealing, both streamed rows and inline proof/coverage cells resolve every
row/cell context, unavailable reason, bound, and explicit provenance/note set against
the captured proof. Context-declared sets remain valid when empty; shared references
may cross presentation families. Coverage references name a declared set, an actual
coverage fact, or a historical measure base with its complete expected-count,
available-count and completeness triplet in one set. Unknown links fail the whole
capture. Explicit empty X-ray metric source sets have an empty declaration and never
inherit unrelated root sources.
Notes with source references resolve their declared provenance set; a warning with
no source references retains an absent note link, which has no context inheritance.
Context reconciliation links resolve an actual captured binding, including explicit
absence bindings. Duplicate license-version or reconciliation identities are rejected.
CSV, XLSX and PDF resolve this declared inheritance for presentation; canonical JSON
retains the compact cells and complete named contexts, allowing exact reconstruction.
PDF labels the row context as the default and prints any differing explicit cell
context beside its value, including nondecimal values and inline proof rows. The
coverage appendix prints each fact's explicit cell context. This source-context
resolution is independent of decimal-only metric metadata inheritance.

## 5. Complete family adapters and honest overlap scope

Application-only capture inputs should be narrowly typed views of existing persisted
results, with declared completeness and actual input/result/options digests:

```python
class CanonicalFamilyBinding:
    family: ReportFamily
    input_id: UUID
    input_digest: Sha256
    result_id: UUID
    result_digest: Sha256
    options_digest: Sha256
    method_key: str
    method_version: str


class ReportCapturePort(Protocol):
    def capture_report(
        self, selection: ReportSelection, *, sink: ReportCaptureSink
    ) -> ReportCaptureSummary: ...
    def capture_export(
        self, selection: ExportSelection, *, sink: ReportCaptureSink
    ) -> ReportCaptureSummary: ...
```

The implementing object is bound to the creation transaction, authorized current
principal/account and exact SourceUse. Neither method opens its own transaction or
accepts caller-supplied SQL, raw JSON, a URL or a broad Principal replacement. The ReportService creation transaction checks owner idempotency semantics and preserves
old pins on replay before invoking capture. The adapter never queries idempotency. It
appends chunks and returns ReportCaptureSummary including typed proof/profile. After the
adapter returns, the service reauthorizes and calls sink.finish(summary) exactly once;
only then may job/input/outbox creation commit. The adapter never calls sink.finish. Snapshot/activity/target bindings use their
actual physical identity and actual fingerprint/version fields; they do not fabricate
`input_id`/`result_id` where the family has none. Represent them with separate typed
binding variants, rather than forcing analytical run fields onto a family that has no such run.

Historical adapter: load the retained family calculation (PerformanceCalculation,
BenchmarkCalculation, IncomeCalculation, CashFlowCalculation,
AttributionCalculation) with its original input and exact options, under requested
REPORT/EXPORT + STORE/current required permissions. Capture every selected public
summary, series point, period, component and event, including complete memberships
beyond public transport previews. Resolve full event/source memberships from retained
canonical input/source-use records when result rows contain omitted-reference counters.
Never use HistoricalRunContext's source/warning previews, top_n income/attribution,
or the current Page limit as full report content. A source-preview omission is not an
analytical missing-input state and must not be copied as such.

Detailed historical provenance follows the fixed `report_source_projection_v1` rule.
Retain source uses at the requested window's start/end, every reported public point's
valuation instant, all reported rolling/calendar/income/cash-flow period boundaries,
and the economic instants of actual consumed event revisions. The latter includes
prior-period income events underpinning previous-income and growth metrics. Keep
each distinct actual corporate-action snapshot/index/knowledge-cutoff observation,
using an existing canonical use if its selected-instant uses do not already cover it.
Retain conversions at those instants or referenced by retained observation uses, and
close their full actual FX leg relationships. Missing and zero states remain distinct
on these retained uses and on every public metric.

The source/header/license/hash sets, input/result/policy bindings, anchor proofs,
coverage, warnings and assumptions are complete and unfiltered. Intermediate daily
reconstruction checks stay in the immutable canonical run bound by those hashes;
they are not another selected report dataset. The manifest records this projection
rule explicitly. This rule has no preview, top-N or arbitrary sampling limit and
never changes the selected public series frequency or drops a public result row.
Composite benchmarks retain their complete public header/count, configured weights,
source/calendar/license memberships and all comparison points. The private daily
composite-observation array is not copied as an additional report table.
When an authorized canonical comparison has a persisted composite snapshot, its
actual public-header ID, content digest and method are retained as a
`family=benchmark, role=snapshot` binding, with the comparison run as `parent_id`.
An absent composite produces no fabricated snapshot pin. Calculation execution time
does not enter the deterministic manifest.

X-ray adapter: use retained canonical XrayCalculation plus actual input/run/policy and complete
physical dependencies. Preserve explicit identity ambiguity/GAP, selected classification
GAP, actual FX coverage gap, zero/missing distinction, BROKER_FX original/saved-currency
basis, direct/inferred/stale coverage overlap and all display residuals/bounds. Translate
only published financial values into cells; retain full explanatory relations separately.
Use actual stored/calculated overlap pairs and their common rows; never recompute
intersections in persistence or the renderer and never use public Top(...).items as the
full source. Existing canonical calculators remain the only calculation authority.

The fixed X-ray report profile selects whole-account held-fund overlap, with
explicit complete/partial/unavailable pair metrics from the canonical analytics. The
existing `calculate_common_entities(result, CanonicalFundPair)` returns both the actual
pair metric and every common entity for that pair; use it once per ordered pair in a
narrow application-level canonical adapter and capture those outputs. It accepts one
pair, so this does not raise `calculate_overlap_pairs`'s existing 2..32 subset bound.
Iterate held-fund IDs in stable UUID order; generate each pair exactly once, stream its
rows, and stop on the frozen dataset or additional byte bounds. The loop enumerates
identities; all financial arithmetic remains inside the existing analytics function.
Bind each pair result to the retained X-ray run/input/content digest and exact fund IDs.

For 40 held funds, this allows all 780 actual pair calculations without treating one
32-fund public collection as complete. It does not widen any kernel graph/root/proof
bound, invent an aggregate, or recalculate a pair twice to obtain its common rows.
Before work, use bounded identity-count arithmetic to reject a known pair-row overflow;
while streaming, detect the first excess common-entity/document row or byte. That count
is control metadata, not a new authoritative financial calculation. This full-scope profile is fixed by this specification. A future explicitly selected
summary profile would be different content and cannot silently replace it. No public Top-N source,
cursor collection or arbitrary caller-controlled subset is required for the default.

Current source-use guards require a narrow internal use-aware seam: DISPLAY helpers
cannot be reused for REPORT/EXPORT by assuming those rights imply each other. Capture,
decode, renderer input load, post-render/final seal and download recheck the actual
pinned/current selected use, STORE and applicable DISPLAY independently. These access
overlays do not rewrite the captured semantic content or its pinned historical quality.

## 6. Canonical streaming, manifest and limits

Frozen bounds: request 64 KiB; ordinary JSON response 2 MiB; each selected dataset
100,000 rows, 64 columns, 4096 characters/text cell; artifact 10 MiB; complete job 25 MiB;
at most four formats; TTL default seven/request 1..30 days. Read at most limit+one to
prove row overflow. None of these implies allocating the theoretical full row/cell
cross-product. Require explicit empty canonical data vs failed/missing capture.

Additional fixed implementation bounds, checked independently of the frozen limits:

- Total canonical bytes <=32 MiB before compression: sum of exact encoded chunk bytes
  plus candidate manifest bytes, counting header/proof/bindings/profile once.
- Each immutable chunk <=1 MiB canonical UTF-8 bytes, with whole records; one oversized
  record fails before allocation/publication. Count all typed metadata/proof bytes too.
- Table identities come from the finite registry. Every context/proof record and table
  descriptor is counted toward the same aggregate bound; no hidden unbounded metadata
  side channel or public source-proof truncation.
- Bounded renderer workspace and process working memory are separate budgets; root
  uses the renderer policy below. A bounded output sink alone does not prove
  bounded PDF/XLSX internal memory or temporary files. No extra service/container.

All simultaneous limits apply. A request that meets the row limit can still fail a byte
limit honestly. A chunk's stored representation must be small enough for the existing
shared source-purge budget to make progress; do not create one unbounded capture blob.
Use sequential immutable chunks, not one tuple of all rows or an unbounded BytesIO.
`ReportBuilder.add_proof` maintains bounded per-table hash/count/identity state and an
aggregate pending row buffer below one chunk. It flushes interleaved table chunks with
independent contiguous ordinals; `complete_proof_tables()` closes their descriptors.
The facade requires exactly the requested data tables plus these registered proof
tables. `finish()` closes any remaining proof writers and never seals the service sink.

```python
class ReportChunk:
    table: ReportTableKey
    ordinal: int
    rows: tuple[ReportRow, ...]
    canonical_bytes: bytes  # <=1 MiB; codec-verified exact match
    digest: Sha256


class ReportCaptureSink(Protocol):
    def append(self, chunk: ReportChunk) -> None: ...
    def finish(self, summary: ReportCaptureSummary) -> None: ...


class ReportCaptureSummary:
    header: ReportDocumentHeader
    canonical_byte_length: int
    chunk_count: int
    immutable_bindings: tuple[ReportBinding, ...]  # closed family-specific union
    proof: ReportProof
    proof_digest: Sha256
    renderer_profile: ReportRendererProfile


class ReportManifest:
    method: Literal["report_manifest_v1"]
    method_version: Literal["1.0.0"]
    document: ReportDocumentHeader
    renderer_profile: ReportRendererProfile
    bindings: tuple[ReportBinding, ...]
    contexts: tuple[ReportContext, ...]
    source_references: tuple[ReportSourceReference, ...]
    source_memberships: tuple[ReportSourceMembership, ...]
    note_memberships: tuple[ReportNoteMembership, ...]
    license_references: tuple[ReportLicenseReference, ...]
    coverage: tuple[ReportCoverageFact, ...]
    bounds: tuple[ReportBoundFact, ...]
    notes: tuple[ReportNote, ...]
    proof_relations: tuple[
        ReportProofRelation, ...
    ]  # supports small inline fixtures; production streams these registered rows as chunk tables
    reconciliation: tuple[ReportReconciliationBinding, ...]
    escaping_version: str


class ReportRendererProfile:
    profile_version: str
    template_version: str
    locale: str
    timezone: Literal["UTC"]
    renderer_versions: tuple[ReportRendererVersion, ...]  # one per selected format
    fonts: tuple[ReportFontReference, ...]  # version/hash/license ref
    chart_order_version: str
    accessibility_profile_version: str


def encode_report_manifest(value: ReportManifest) -> bytes: ...
def decode_report_manifest(payload: bytes) -> ReportManifest: ...
def build_report_manifest(
    capture: ReportCaptureSummary, *, proof: ReportProof, profile: ReportRendererProfile
) -> ReportManifest: ...
def report_manifest_digest(value: ReportManifest) -> Sha256: ...
```

`ReportProof` is the immutable typed aggregate of the manifest's context/source/license/
coverage/bounds/note/reconciliation records and normalized memberships, not arbitrary
JSON. Every referenced key must resolve exactly; duplicates with conflicting content
fail. The normalized membership relations are included explicitly, not merely their set keys. References are sorted by stable family/identity; row and table
order follows the fixed schema. Sections/formats normalize as sets into fixed enum order.
No chunk boundary, generated capture/job/definition ID, execution/generated/calculated-
by-report timestamp, expiry, grant or storage address enters semantic bytes. Actual
underlying canonical run IDs and original analytical timestamps remain provenance.
Capture IDs/ordinals may be operational storage locators only.

Hash semantic row records with an unambiguous length-prefixed stream or the exact fixed
JSON framing; use the version fixed below. Table hash is independent of chunking.
Section hash binds table identity/order/schema, full rows/context/proof; document hash
binds normalized semantic selection plus all section/proof digests. Avoid self-hash:
header/document hash inputs exclude their own digest field; manifest hash is SHA-256 of
encoded manifest bytes and is stored outside that payload. Public JSON under 2 MiB is
checked after exact encoding, before publishing any success. Artifact hashes bind their
actual bytes separately. Canonical JSON uses UTF-8, fixed key/order/escaping rules,
validated decimal strings and aware-UTC strings; no float, locale-dependent collation,
clock reads or unordered set/dict iteration. Decoding/re-encoding must be byte-identical.

Owner/account scope and actual underlying identities stay in the manifest. Operational
TTL stays in the request/idempotency digest because it changes the command, but is not
part of the semantic manifest or document selection. The normalized selection in the
header therefore contains no idempotency key or TTL. A generated definition identity
cannot replace its immutable content/version digest in the semantic selection.

## 7. Render/read ports and format behavior

```python
class ReportDocumentReader(Protocol):
    @property
    def header(self) -> ReportDocumentHeader: ...
    @property
    def manifest(self) -> ReportManifest: ...
    def iter_chunks(self, table: ReportTableKey) -> Iterator[ReportChunk]: ...


class BoundedArtifactSink(Protocol):
    def write(self, chunk: bytes) -> int: ...  # reject before crossing 10 MiB
    @property
    def byte_length(self) -> int: ...


class RenderedArtifact:
    format: ReportFormat
    mime_type: ReportMimeType  # fixed format-to-MIME registry
    content: bytes  # <=10 MiB; no path/URL
    byte_length: int
    content_digest: Sha256


class ReportRenderReceipt:
    format: ReportFormat
    mime_type: ReportMimeType


class BoundedArtifactBuffer(BoundedArtifactSink, Protocol):
    def finish(self, receipt: ReportRenderReceipt) -> RenderedArtifact: ...


class ReportRendererPort(Protocol):
    def render(
        self,
        document: ReportDocumentReader,
        *,
        format: ReportFormat,
        profile: ReportRendererProfile,
        sink: BoundedArtifactSink,
        guard: ReportRenderGuard,
    ) -> ReportRenderReceipt: ...


class ReportRenderGuard(Protocol):
    def check(self) -> None: ...  # cancellation/lease/access/time/budget
```

`open_report_document(claim)` is a synchronous context manager opened, consumed and
closed entirely in the renderer thread. It loads a sealed typed capture under fresh
short database authorization checks between bounded reads, and releases its connection/
cursor on every path. No database transaction or row lock spans rendering. Its reader
verifies canonical hashes and decodes at most one bounded chunk at a time. It never
selects latest sources. The deterministic candidate manifest comes from the captured
proof plus the exact renderer profile pinned at creation; no successful manifest row is
required before rendering. Manifest rows are inserted only on atomic successful seal.
Reject unsupported profile/version at load. Heartbeat and guard checks operate
independently; final DB fencing and fresh authorization remain decisive.

The renderer receives only `BoundedArtifactSink` and returns `ReportRenderReceipt`.
The worker owns `BoundedArtifactBuffer.finish(receipt)`, which finalizes the exact bytes,
measures length and computes SHA-256 itself before constructing `RenderedArtifact`.
A renderer cannot claim a hash for bytes it has not emitted or read unrestricted buffer
contents through the sink protocol. Length/MIME/digest are reverified at final storage.

The renderer has a fixed approved template/profile and no user URL/HTML/code interface.
The worker owns a private bounded temporary context and removes it on every path. Keep
at most one active renderer and account all completed buffers toward the 25 MiB job cap;
all requested formats remain private until atomic completion. `RenderedArtifact.content`
is the finalized bounded payload extracted by the sink owner, not a second unrestricted
copy. Use a private bounded buffer view internally to avoid duplicate finalized copies;
materialize bytes only at the bounded storage boundary. There is no arbitrary path port.

- JSON emits the typed document and independent manifest with decimal strings and full
  states; it retains safe original strings, not CSV-prefixed mutations.
- CSV reports with multiple tables use one fixed normalized cell-record schema:
  `section,table,row_key,column_key,cell_kind,value,decimal_role,currency,state,
  reason_key,bound_key,context_key,quality,origin,coverage_key,confidence,method_key,
  method_version,provenance_set_key,note_set_key`. Context/proof records use fixed registered table
  keys in the same representation. This is a declared CSV schema, not a sequence of
  incompatible ad-hoc headers. Dataset CSV may use its fixed wide table schema only
  where there is one table; multi-table datasets use the same explicit normalized form.
  Analytical dataset row limits apply before this mechanical cell expansion; emitted
  bytes remain bounded by 10 MiB and no records are silently dropped.
- XLSX uses fixed worksheets/table schemas and explicit string cells for all exact
  decimals, quantities, IDs, UTC timestamps and untrusted strings; no formulas, macros,
  links, or implicit numeric coercion. Check library return codes and temporary growth.
- PDF presents selected sections plus complete method/source/quality/coverage notes and
  limitations; charts have table equivalents and consume supplied exact series. Float
  geometry cannot feed a semantic cell or hash. Pin fonts and fail explicitly on text
  that cannot be represented, never silently substitute/drop glyphs. State actual
  selectable-text/accessibility capability without an untested PDF/UA claim.
  Its readable appendix includes context, warnings, reconciliation, sources and
  licenses. The exact canonical manifest appears once as the inert embedded UTF-8
  `report-manifest.json` attachment; its digest is displayed for independent checking.
  The PDF does not print raw manifest JSON as debug pages. Selected analytical values
  and retained material proof rows remain readable. Attachment objects use fixed
  names and MIME types, with no external-file references, launch actions or JavaScript.

CSV uses UTF-8/RFC4180 quoting/doubled quotes and the frozen formula-prefix policy:
ordinary/full-width =,+,-,@ after leading whitespace/control/BOM, or initial tab/CR/LF,
gets an apostrophe prefix. This applies only to untrusted text cells, never validated
numeric decimal cells. Escape PDF markup rather than interpreting it. Fixed attachment
filenames/MIME/Content-Disposition belong to the download adapter, not document input.

## 8. Durable interfaces and public result shapes

Reuse planning's lifecycle mechanics with distinct report/export models, messages,
fixed tasks and outboxes. Existing planning UUID leases alone do not satisfy method7:
report/export claims additionally require a monotonically increasing integer fence.

```python
REPORT_TASK_NAME = "reports.generate.v1"
EXPORT_TASK_NAME = "exports.generate.v1"


class ReportTaskMessage:
    job_id: UUID
    owner_id: UUID
    account_id: UUID
    capture_id: UUID
    input_digest: Sha256


class ExportTaskMessage:  # distinct class, same strict fields
    job_id: UUID
    owner_id: UUID
    account_id: UUID
    capture_id: UUID
    input_digest: Sha256


class ReportJobClaim:
    message: ReportTaskMessage
    lease_id: UUID
    fence: int  # positive, monotonic on each claim
    lease_expires_at: datetime
    consumer_attempt: int  # 1..4


class ReportJobStore(Protocol):
    async def claim_report_job(
        self, message: ReportTaskMessage, *, consumer_id: str
    ) -> ReportJobClaim | None: ...
    async def heartbeat_report_job(self, claim: ReportJobClaim) -> bool: ...
    def open_report_document(
        self, claim: ReportJobClaim
    ) -> ContextManager[ReportDocumentReader]: ...
    async def complete_report_job(
        self,
        claim: ReportJobClaim,
        *,
        manifest: ReportManifest,
        artifacts: tuple[RenderedArtifact, ...],
    ) -> bool: ...
    async def fail_report_job(
        self, claim: ReportJobClaim, *, failure: ReportFailureCode, retryable: bool
    ) -> bool: ...
```

Public and durable store methods are async, following existing application conventions.
Creation-session capture and renderer iteration are synchronous and confined to their
transaction/thread. Do not perform synchronous DB I/O on the event loop. Export has its own matching typed methods
and claims rather than a generic caller-controlled task name. Dispatcher claims reuse
planning's bounded message/claim/ack/defer structure, but with separate fixed report and
export publishers. Store validates the complete message against real relational IDs;
Celery only receives opaque IDs/digest and rejects unknown fields before business logic.

Creation pins capture+job+owner idempotency+outbox in one transaction under fresh scope
and license authorization. Same key/same semantic command returns the same job/pins
under current authorization; changed command conflicts. Use lease60s, heartbeat15s,
max4 consumer attempts with1/2/4s deterministic delays; max8 publication attempts
independently. Current integer fence, lease validity, owner/principal/account, source
permissions and source expiry guard one atomic manifest+all-artifact completion.
Unique job/format seals reject duplicates. Permanent validation/license failures do
not retry. Never record success for one format while another is missing/failed.

Internal sanitized `ReportFailureCode` closed values:
`invalid_input`, `input_unavailable`, `input_changed`, `access_denied`,
`source_restricted`, `limit_exceeded`, `render_failed`, `storage_unavailable`,
`publication_unavailable`, `lease_expired`, `attempts_exhausted`.
Map these through the existing public service error envelope; no unrelated shared
ErrorCode is added. Domain validation uses VALIDATION_FAILED, authorized input overflow
uses INPUT_BOUND_EXCEEDED, unknown/foreign objects use NOT_FOUND, changed idempotency
uses CONFLICT, and missing capability uses ACCESS_DENIED at the public boundary. No exception content/raw
provider strings/tokens/bytes in these failures. Expired download behavior remains the
frozen public `ARTIFACT_EXPIRED` contract independently of internal code naming.

```python
class ReportArtifactMetadata:
    artifact_id: UUID
    format: ReportFormat
    mime_type: ReportMimeType
    byte_length: int
    content_digest: Sha256
    expires_at: datetime


class ReportJobStatus:
    account_id: UUID
    context: ReportPinnedContext | None  # only expired/cancelled after lawful purge
    job_id: UUID
    report_id: UUID | None  # same job ID only after success
    state: ReportJobState
    requested_at: datetime
    completed_at: datetime | None
    expires_at: datetime
    failure_code: ReportFailureCode | None
    report_type: ReportType
    formats: tuple[ReportFormat, ...]
    manifest_digest: Sha256 | None
    artifacts: tuple[ReportArtifactMetadata, ...]


class ExportJobStatus:
    account_id: UUID
    context: ReportPinnedContext | None  # only expired/cancelled after lawful purge
    export_id: UUID  # stable job identity
    state: ReportJobState
    requested_at: datetime
    completed_at: datetime | None
    expires_at: datetime
    failure_code: ReportFailureCode | None
    dataset: ExportDataset
    field_set: ExportFieldSet
    format: ExportFormat
    manifest_digest: Sha256 | None
    artifacts: tuple[ReportArtifactMetadata, ...]  # zero pending/failed; exactly one success


class ArtifactGrant:
    artifact_id: UUID
    token: str  # sensitive response only; never MCP/log
    expires_at: datetime
```

Public statuses/lists carry no artifact bytes, URLs, storage paths or raw credentials.
Current read scopes do not follow merely from successful creation. Exactly the eleven
HTTP operations and three MCP operations in the frozen registry are exposed; no generic
artifact/task/cancel/upload/redaction/custom-template endpoint is introduced here.
Grant creation has an empty typed body, at most ten active owner/artifact grants, and
new ephemeral random tokens on retries rather than idempotent raw-token replay. Only
the digest persists. Grant validity <=5min and <=artifact expiry, plus current principal,
owner/account, section/dataset source permissions and actual digest before BYTEA read.

Persistence owns the joint lock/capture-consistency review. Existing proven partial
orders are source before historical/X-ray family access, the shared `targets:{owner}`
namespace for target/planning operations, and collection capacity last where used.
This contract does not assert an already-proven total source→family→targets order; new
report capture/completion/cleanup paths must fit one reviewed order without reversals. Current principal/grant/account
checks occur again at final seal; do not fabricate blanket worker scopes or keep an
expired request session as permanent permission. The durable principal protocol below fixes that resolution independently of request-session lifetime.

Expiry/cleanup is one bounded transaction over <=100 artifacts in stable expiry/key
order with SKIP LOCKED, atomically clearing bytes/grants. Report capture/proof/manifest
and artifacts are source copies in the existing shared4096-row/64MiB source-purge budget.
Do not reset that budget by family or leave copied input alive after declaring cleanup
complete. Retain only permitted tombstone/audit data; physical cleanup delay never grants
continued access. The source/fence invariant is rechecked after rendering even when a
revocation or source expiry activated during work.

The corresponding export lifecycle is a distinct ExportJobStore with
`async claim_export_job(ExportTaskMessage, *, consumer_id: str) -> ExportJobClaim | None`,
`async heartbeat_export_job(ExportJobClaim) -> bool`, synchronous
`open_export_document(ExportJobClaim) -> ContextManager[ReportDocumentReader]`,
`async complete_export_job(ExportJobClaim, *, manifest: ReportManifest,
artifacts: tuple[RenderedArtifact, ...]) -> bool`, and
`async fail_export_job(ExportJobClaim, *, failure: ReportFailureCode, retryable: bool) -> bool`.
ExportJobClaim has the same lease_id/fence/lease_expires_at/consumer_attempt fields with
an ExportTaskMessage. Service create_report/create_export is owned by ReportService,
not by these worker store ports or the capture adapter.

Each store also exposes async `claim_report_dispatches`/`claim_export_dispatches`
with keyword dispatcher_id:str and limit:int=20 (1..100), returning a tuple of the
corresponding ReportDispatchClaim/ExportDispatchClaim. Each dispatch claim contains its
typed message, claim_token:UUID, claim_expires_at:datetime and publication_attempt:int
(1..8). Async `acknowledge_report_dispatch(claim)`/`acknowledge_export_dispatch(claim)`
return bool; async `defer_report_dispatch(claim, *, failure: ReportFailureCode)` and its
export counterpart return bool. Dispatch claim duration is30seconds, matching the
existing bounded planning pattern. All claim/ack/defer methods verify exact identity.
Acknowledgment and deferred-publication callbacks also require a queued or running
job. A callback arriving after completion returns false before changing the outbox,
attempts, artifacts or audit history, including an ambiguous eighth publication
failure. Historical outbox claims on terminal jobs remain excluded from dispatch;
worker completion does not fabricate a publication acknowledgment.

`ReportJobInputError(code: ReportFailureCode, retryable: bool = False)` and
`ReportRenderError(code: ReportFailureCode, retryable: bool = False)` are safe application
exceptions; their string messages are fixed, never exception/provider payloads. Contract
validation uses existing DomainError; byte/row/column/text resource rejection maps to
INPUT_BOUND_EXCEEDED or internal LIMIT_EXCEEDED as appropriate to the operation.

## 9. Fixed profiles, canonical byte encoding and principal delegation

The fixed versions are `report_manifest_v1`/`1.0.0`, document/column schema `1.0.0`,
`report_sections_v1`, `report_template_v1`, `report_render_v1`,
`report_csv_text_v1`, `report_chart_order_v1`, locale `en-GB`, timezone `UTC` and
`report_visual_accessibility_v1`. There is no custom renderer/profile input. Record exact
installed renderer versions and exact bundled font hashes in ReportRendererProfile.
Changing a profile produces a new version and changes the semantic manifest.

Historical capture uses `AS_OF_CUTOFF` and `REQUIRE_COMPLETE`, with the existing fixed
performance TWR/monthly/no rolling/no extra calendar breakdown; benchmark monthly/no
rolling/no extra calendar breakdown; income holding grouping; attribution holding/TWR;
cash flows monthly/all kinds. Their persisted analytics-run kind is `cash_flow`,
while the public report family remains `cash_flows`. Calendar reports retain their complete requested calendar
window; internal support windows include the canonical prior-period income inputs.
The requested historical period, snapshot valuation time and source knowledge cutoff
are independent pins. A snapshot must be valued no later than the requested cutoff,
which must not be in the future; it need not fall inside the historical period. Data
first received after that period may participate under `AS_OF_CUTOFF` when its actual
first-known time satisfies the cutoff. Keep the immutable observation, receipt and
snapshot timestamps unchanged. When the snapshot lies outside the requested period,
retain `snapshot_outside_period` as a manifest warning and disclose the snapshot date
prominently in the PDF. Its overview/allocation describes that actual snapshot, not a
fabricated period-end valuation. Historical tables still require their own complete
period boundaries and canonical source evidence.
The saved source policy/calendar/accounting/input/family/options digests are pinned before
dispatch. Reuse existing policy ordering and tied-version conflict rejection rather than
selecting the latest completed result by creation time. Unavailable canonical metrics
remain unavailable with their original reasons.

X-ray captures the existing XrayRunRequest from snapshot/cutoff/currency and resolves
policy with the existing capture rules: authorized account, observed by cutoff,
effective by snapshot valuation, effective_at DESC/first_observed_at DESC/policy ID DESC.
Reuse/publish the canonical calculation under the actual input digest, not a latest-run
query. Select dimensions company/sector/industry/country/region/currency in that order;
absolute exposures, `normalized_known_only=false`; full-scope pair algorithm is §5.
Optional constituent_snapshot_id is a dependency expectation: it must be an authorized,
time-valid, actually selected constituent snapshot in that result. It cannot override
source selection or stand in for all nested/held-fund/mapping/FX evidence.

A supplied plan revision resolves its actual target/virtual-portfolio/snapshot parents.
A published target resolves its actual parent/account. Explicit references must agree.
Selected benchmark content requires its version and the existing capture resolves its
exact snapshots. These internal pins add no field to the closed MCP input.

Canonical byte encoding is `report_canonical_json_v1`: UTF-8, no BOM, no insignificant
whitespace, fixed object-key order defined by the records in this specification, JSON
escaping of controls with original Unicode otherwise retained, exact non-exponent
canonical decimal strings, lowercase UUID/SHA strings, ISO dates, and UTC instants with
`Z` and canonical optional fractional seconds. Reject unknown keys and noncanonical
re-encoding. Stable table order follows this registry, rows follow its keys/ordinals;
context/reference relations sort by their typed family/identity keys. Every record is
encoded separately. Stream hash input is an unsigned 8-byte big-endian byte length then
record bytes, preceded by fixed schema/table identity; no ambiguous delimiter framing.
Integer framing/row counts are control metadata only, not financial calculation.

Section hash binds its table schemas/row-stream digests plus referenced context/proof
digests. Document digest binds normalized selection, ordered section/table digests and
full proof digest. Operational capture IDs/chunk boundaries do not enter those inputs.
The manifest includes the document digest and has no self-digest field; SHA-256 of its
exact encoded bytes is the independent manifest digest. Source-reference membership,
notes, coverage and actual license attribution are complete or explicitly fail the
2 MiB encoded manifest limit before successful publication.

Durable authorization is `report_delegation_v1`. A typed trusted provisioning adapter
maintains current `(owner_id, principal_id, scope, granted_at, expires_at?, revoked_at?)`
rows linked to the real canonical principal. Local synthetic seeding may provision
reviewed fixed grants. Public report requests, their section selections, and first-seen
bearer claims never manufacture entitlements. Missing durable grants fail closed.

Creation stores initiating principal ID, owner/account, delegation policy version and
only the exact required generation scope union, with the sealed command/job. It stores
no bearer/session/CSRF token and creates no blanket-scope worker Principal. Job expiry
bounds the delegation. At claim/load/heartbeat/final seal, reload active principal,
current grants, current owner/account relationship and bounded delegation lifetime.
Current grant/status mutation and final publication serialize through the same reviewed
owner authorization lock and fresh row predicates; no ORM-cached authorization passes
for a fresh check. A permanently failed job never resurrects on later regrant.

Ordinary initiating credential expiry/logout does not silently cancel this separate
bounded job delegation. Disabling that principal or revoking a required durable grant
denies generation on its next boundary and must defeat final publication. Every read
uses a freshly authenticated requester, which may be another currently authorized
principal of the same owner. Creation requires portfolio:read/reports:write/analytics:read
plus selected target/activity scopes; retrieval requires portfolio:read/reports:read
plus selected data scopes where specified. MCP creation keeps its conservative five-scope
contract. Write permission never implies read permission.

## 10. Public context, complete services and binary ownership

Queued creation already resolves/pins input, so its returned context must expose the
same safe bounded pins and quality required by MCP; it must not wait for a manifest.

```python
class ReportInputPin:
    family: ReportFamily
    role: ReportInputRole  # fixed family-specific registry
    subject_id: UUID
    content_digest: Sha256
    parent_id: UUID | None
    method_key: str | None
    method_version: str | None


class ReportQualitySummary:
    state: QualityState
    availability: SourceAvailability  # available/partial/unavailable/failed
    evaluated_at: datetime
    warnings: tuple[ReportNote, ...]  # <=64 safe preview records
    warning_count: int
    warning_omitted_count: int


class ReportPinnedContext:
    snapshot_id: UUID
    valuation_at: datetime
    source_cutoff_at: datetime
    reporting_currency: CurrencyCode
    input_digest: Sha256
    document_digest: Sha256
    profile_version: Literal["report_sections_v1"]
    schema_version: Literal["1.0.0"]
    pins: tuple[ReportInputPin, ...]  # <=256 actual input/run/policy/version pins
    quality: ReportQualitySummary
```

The context pin array contains the actual finite top-level calculation/input/policy
identities, not every path source; complete proof is in the manifest. Pin overflow fails
before creation; it is not a preview. Warning preview carries exact total/omitted counts.
It does not replace complete manifest warnings or trigger fresh financial calculations.
Statuses/lists use the same context schema under the ordinary 2 MiB JSON ceiling.

```python
class ReportListQuery:
    limit: int = 25  # 1..100
    cursor: str | None = None
    state: ReportJobState | None = None
    report_type: ReportType | None = None
    start_date: date | None = None
    end_date: date | None = None
    sort: Literal["created_desc"] = "created_desc"


class ExportListQuery:
    limit: int = 25
    cursor: str | None = None
    state: ReportJobState | None = None
    dataset: ExportDataset | None = None
    sort: Literal["created_desc"] = "created_desc"


class ReportService(Protocol):
    async def generate_report(
        self, principal: Principal, command: GenerateReportCommand
    ) -> ReportJobStatus: ...
    async def get_report_status(
        self, principal: Principal, account_id: UUID, job_id: UUID
    ) -> ReportJobStatus: ...
    async def list_reports(
        self, principal: Principal, account_id: UUID, *, query: ReportListQuery
    ) -> Page[ReportJobStatus]: ...
    async def get_report_manifest(
        self, principal: Principal, account_id: UUID, report_id: UUID
    ) -> ReportManifest: ...
    async def create_report_download_grant(
        self, principal: Principal, account_id: UUID, report_id: UUID, artifact_id: UUID
    ) -> ArtifactGrant: ...
    async def download_report_artifact(
        self,
        principal: Principal,
        account_id: UUID,
        report_id: UUID,
        artifact_id: UUID,
        *,
        grant_token: str,
    ) -> ReportArtifactDownload: ...
    async def create_export(
        self, principal: Principal, command: CreateExportCommand
    ) -> ExportJobStatus: ...
    async def get_export_status(
        self, principal: Principal, account_id: UUID, export_id: UUID
    ) -> ExportJobStatus: ...
    async def list_exports(
        self, principal: Principal, account_id: UUID, *, query: ExportListQuery
    ) -> Page[ExportJobStatus]: ...
    async def create_export_download_grant(
        self, principal: Principal, account_id: UUID, export_id: UUID, artifact_id: UUID
    ) -> ArtifactGrant: ...
    async def download_export_artifact(
        self,
        principal: Principal,
        account_id: UUID,
        export_id: UUID,
        artifact_id: UUID,
        *,
        grant_token: str,
    ) -> ReportArtifactDownload: ...


class ReportArtifactDownload:
    metadata: ReportArtifactMetadata
    filename: str  # fixed server profile, never caller input
    content: bytes  # <=10 MiB, digest/length/MIME verified
```

Status methods map directly to the eleven named frozen HTTP operations; there is no
additional export-manifest URL or cancellation endpoint. MCP uses only get_report_status,
list_reports and generate_portfolio_report, returning bounded pins/quality, never grant
bytes or content URLs. HTTP report/export path IDs still resolve owner/account authority
inside the service; account selection cannot weaken that lookup.

The general JSON client retains its 2 MiB cap. A separate fixed content adapter accepts
only these artifact IDs plus the ephemeral header, verifies MIME/length/hash with a
10 MiB byte ceiling and rejects redirects/alternate locations. Grant bodies are empty,
require ordinary command CSRF/origin safeguards for cookies and do not use idempotent
raw-token replay. Grants are reusable until expiry/revocation, at most ten active grants
per owner/artifact, with at most five-minute lifetime. Grant creation retries mint a new
token. Download records usage/audit without logging header bytes. This is short-lived
supplemental access, never token-only authorization.

Job/artifact effective expiry is min(requested creation-time TTL, every selected source's
actual retention/license deadline). Capture rejects already-expired sources. An otherwise
permitted shorter future deadline is returned explicitly as effective expires_at; it
does not extend licensing to satisfy requested TTL. Source-use revocation can deny access
earlier than that timestamp. Tombstone retention follows existing configured policy and
never retains source detail prohibited by the current license.

The shared audit stream records report/export job creation, completion, failure and
expiry in the transaction that wins the guarded state transition. Physical input
purge appends one completion event with its fixed `ttl`, `source` or `owner` reason.
Idempotent command, worker and cleanup retries do not duplicate these events. Audit
metadata contains only a typed failure code or retention reason; canonical payloads,
command bodies, artifact contents and access tokens are excluded. Download and grant
events retain their separate existing records.

## 11. Renderer resource profile and schema ownership

Use ReportLab `5.0.1` and XlsxWriter `3.2.9` as the initial locked renderer implementation,
with stdlib CSV/JSON. Dependency addition remains an implementation change subject to
installed API/license/security/build verification, not a passing claim in this spec.
Bundle only DejaVu Sans Book and Bold `2.37`, exact files/hashes/notices in the installed
worker package and profile. No runtime font/image download or arbitrary external link.
Initial supported glyphs are those actually present in the pinned faces; test Latin,
Greek/polytonic, Cyrillic, euro and relevant currency symbols. Unsupported glyphs fail
explicitly before artifact success. PDF/UA compliance is not claimed.

The renderer runs one artifact at a time, in one private worker-owned temporary context.
Fix total canonical input32 MiB, decoded chunk1 MiB, artifact10 MiB, buffered requested
artifacts25 MiB, uncompressed private scratch192 MiB, PDF1000 pages, and worker renderer
child address-space budget512 MiB. Check serialized and scratch byte budgets during
writes; apply the memory limit to the isolated rendering child, not the whole shared
worker. Child cancellation/lease loss stops generation and triggers finally cleanup;
crash recovery removes only inspected task-owned orphan workspaces. Child-process
startup/platform support is verified in native Linux/CI/worker image before acceptance.
The process remains internal to the existing worker; there is no additional container.
No assertion of bounded renderer memory follows solely from an output sink limit.

ReportLab uses safe fixed templates and supported selectable Unicode fonts. Layout
geometry may use floats; no layout result feeds an authoritative metric or semantic
hash. XLSX uses explicit write_string, disables strings_to_numbers/formulas/urls, checks
write return codes and writes rows in order with bounded scratch/constant-memory policy.
Read-only format verification checks PDF text/metadata and all expanded XLSX parts;
no formulas, macros, external relationships or secret/signed-URL material may survive.

The pinned XLSX implementation reserves a 1 MiB scratch base plus, for each emitted
normalized row, `2 * (sum(7 * UTF8_bytes(cell) + 96 for cell in row) + 128)` bytes.
The sevenfold allowance covers the writer's control-character XML escaping; fixed cell
and row markup allowances cover the registered styles and bounded row indices. The
factor of two covers streamed rows and assembled worksheet XML existing together.
Both this reservation and actual private-directory sizes enforce the unchanged
192 MiB cap. XlsxWriter `3.2.9` recognizes literal `<r>...</r>` as rich XML even through
`write_string` in constant-memory mode. The fixed text worksheet overrides only that
internal branch to use the ordinary escaped inline-string writer. Three retained
regressions verify literal text survives and produces no formulas.

An earlier synthetic renderer check, before the public-output trace projection, used a
complete 365-interval historical window,
3,676 canonical rows and a 17,159-byte manifest. Its PDF was 1,042,772 bytes across
532 pages; CSV was 6,702,310 bytes; JSON was 3,655,809 bytes; XLSX was 1,939,757 bytes.
All four outputs passed the format-specific checks within the unchanged caps. This is
a renderer stress observation, not evidence of a persisted annual report job or the
report-type acceptance matrix or the final representation; those require their separate real capture, worker,
authorization and download checks.

CSV and XLSX keep the 20-column normalized cell header for selected analytical tables.
Proof-table descriptors have neither section nor dataset. Their lossless records use
`section=proof`, the actual table and row/context keys, `cell_kind=text`,
`state=available`, and `value=json:` followed by at most 4,000 Unicode characters.
The reserved `column_key` grammar is `schema.NNNNNN` for the canonical table schema
and `row.RRRRRR.NNNNNN` for each canonical row, with zero-based six-digit row and
fragment ordinals. Schema fragments precede row fragments; each group and row sequence
is contiguous with no repeated or skipped ordinal. Remove only the literal `json:`
prefix and join each group's fragments to recover the exact `encode_report_schema`
or `encode_report_row` bytes. Validate the fixed schema, row count and expanded
table digest against the manifest. This is a fixed transport representation of the
typed proof records, never an arbitrary provider payload or free-form JSON cell.

The cell/table registry is the single schema authority for every renderer and both field
sets. Do not implement free-form tables or JSON-in-a-cell to shortcut a source adapter.
A schema change updates its version, manifest/codec fixtures, generated public metadata
where exposed and all parser/parity tests together. Source actor names and complete safe
license attribution may appear as bounded escaped text; URLs or credentials from raw
provider material never enter the captured document.

## 12. Delivery sequence and evidence obligations

Implement the fixed records, exact MCP normalization and codecs first; then transaction-
bound capture/durable storage/worker plus renderers; then complete HTTP/MCP/web download
surfaces. Preserve current behavior and the read-only broker boundary. Every new artifact
format is real, parser-valid and private; no TODO producer or successful empty placeholder.
All ten report types support all four formats through the same durable path. Each of the
seven backed standalone datasets supports standard/audit and CSV/JSON/XLSX. Legitimate
empty data is an authorized successful dataset with zero actual rows and complete state/
provenance. Missing producers or prohibited sources are explicit failures.

The full-release alerts dataset remains in its fixed enum. P2-06 rejects it before
capture/job/outbox with VALIDATION_FAILED and a fixed sanitized producer-unavailable
message. P2-07 must connect actual canonical alert events and prove positive/legitimate-
zero results, both field sets/three formats, source and account authorization, parity,
idempotency, expiry/cleanup and restart through these same ports. P2-06 completion may
close its report requirements and seven producer-backed datasets only; the explicit
P2-07 obligation remains pending and the final eight-dataset contract is unchanged.

Required proof maps to [acceptance](PHASE_2_ACCEPTANCE_MATRIX.md) P2-RPT-001/002/003
and [scenarios](PHASE_2_SCENARIO_EVIDENCE.md) P2-S24..27; P2-S31/32/34 are shared
partial obligations and P2-S40 remains the release-wide P2-10 gate. Do not mark a shared
scenario complete from reporting-only tests.

- Pure/domain: exact ten-type section/ref/calendar matrices and immutable request
  encoding; extra MCP fields and unknown schema kinds denied; zero/missing/failed/
  stale/partial/inferred/unreconciled distinctions; no float/exponent/overflow;
  row100000/100001, columns64/65, text4096/4097, multibyte byte limits and one oversized
  record; canonical document/hash independent of chunk boundaries and operational IDs.
- Canonical adapters: complete selected historical rows/periods/events and the defined
  public-instant/event/FX provenance projection with complete source hashes;
  same selected snapshot/run/options/method/currency values across API/MCP/report;
  X-ray missing FX/classification/identity evidence, original broker FX basis,
  overlapping quality measures, exact residual/bound semantics; all780 pairs for40
  held funds when within document limits, with every common entity and no repeated
  pair calculation. No public preview or Top omission copied as complete data.
- PostgreSQL: migrations/schema guards, owner/account/principal composite links,
  creation/capture/idempotency/outbox atomicity; identical command replay under current
  grants, changed-command conflict; fresh license/STORE/use checks before decode and
  final seal, time-activated denial during rendering, all-format atomicity, duplicate
  delivery, stale integer fences/lease recovery/heartbeat and four/eight exhaustion.
- Formats/security: real PDF parse/text order/Unicode/accessibility limitation; JSON
  exact decimal/state/manifest replay; CSV import/injection cases and XLSX archive cell
  types, full-width/whitespace/BOM/multiline/separator canaries; manifest/all-format/log/
  trace secret and provider/export-URL component canaries; artifact/job/scratch/memory/
  page overflow leaves no downloadable partial output.
- Access/retention: cross-owner/account/scope failures for all eleven operations;
  independent current read principal; expired/revoked grants and digest mismatch before
  bytes; ten-grant cap, CSRF/origin, no URL/token logging; actual source deadline clamps,
  expiry before physical cleanup, <=100 SKIP LOCKED cleanup and shared4096-row/64MiB
  source-purge progress including captured input/manifest/artifacts/grants.
- Product/runtime: desktop/mobile generation, status, manifest, authenticated download
  and unavailable/failed/expired states; original job/input/manifest/artifact identity
  across worker/dispatcher restart without duplicate finalized work. Run meaningful
  focused checks, full required local gates and scans/runtime at the final source; actual CI is temporarily deferred under the explicit owner decision above.

Verification remains serial on the laptop. Reuse one task Compose project and start
only required services, using one container when sufficient. Remove inspected task-
owned disposable containers, volumes, networks, workspaces and obsolete build metadata
at verification boundaries. Preserve source/dependencies/accepted evidence and unrelated
user data; no global prune. Record observed results separately and keep status honest.

The September 9 development run `p206-working-remainder-04` passed with its working
source unchanged in 2,828.665 seconds: 1,914 isolated and 277 service/migration coverage
tests, 88% combined statement/branch coverage, 86 serial browser checks and the remaining
documentation/security/build/image stages. It follows the separately recorded dispatch
interruption, migration-test inventory correction and source-canary fixture correction;
those failed records remain preserved. This run precedes the final navigation correction
and is not clean exact-SHA acceptance. The PostgreSQL CI budget is 90 minutes, informed
by measured local coverage and an estimated 69.18-minute CI job using prior accepted
phase ratios; no tests or coverage were removed. At that historical development boundary, final-source validation, CI/scans, fresh runtime/cleanup and screenshot/PDF review were still pending. Current local acceptance and the distinct CI deferral are recorded above.

The later default-restoration/coalesced-history correction passed 45 focused unit
cases and all 301 web unit tests. Four real desktop browser journeys passed after
the sticky sidebar received vertical scrolling; four mobile journeys passed before
that sole CSS change to the hidden desktop sidebar. Final web lint, typecheck and
production build passed. Failed regression/selector/sidebar observations are retained
with their corrections. Root reviewed eight working screenshots, including the
supplemental control viewports, with a documented full-page mobile capture limitation.
These are working-source results; final-source acceptance and visual review remain
separate requirements.
