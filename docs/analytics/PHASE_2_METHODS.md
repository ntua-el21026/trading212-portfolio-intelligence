# Phase 2 Analytical Methods

**Status:** Accepted design contract

**Decision date:** 2026-09-07

**Release:** 0.2.0; implementation and validation evidence remain separate

This specification makes the accepted [financial policy](FINANCIAL_CALCULATION_POLICY.md),
[allocation policy](ALLOCATION_DRIFT_OPTIMIZER.md),
[performance accounting](PERFORMANCE_ACCOUNTING.md), and [X-ray policy](PORTFOLIO_XRAY.md)
executable. Its decisions are recorded in ADRs
[0011](../adr/ADR-0011-DETERMINISTIC-CONTRIBUTION-OPTIMIZER.md),
[0014](../adr/ADR-0014-PRIVATE-REPRODUCIBLE-REPORTS.md), and
[0015](../adr/ADR-0015-VERSIONED-ALERT-EVALUATION.md). It describes required behavior,
not evidence that that behavior has already shipped. API, web, MCP, alerts, and
reports consume the same persisted application-service calculations.

## 1. Common numerical and reproducibility contract

Financial wire inputs are finite decimal strings, never JSON numbers or binary
floats. Exact integers are allowed internally for integer-valued domain data.
Money, quantity, price, FX, weights, ratios, and public/normalized results retain
`NUMERIC(38,18)`. X-ray private exact-state coefficients are the narrowly bounded
retention exception in [ADR-0017](../adr/ADR-0017-DECIMAL256-EXACT-XRAY.md);
they are not public financial values or a global numeric-decoder relaxation. Reject excess input scale, more than 20 integer digits,
and overflow before persistence.
Every amount has a currency. Use a fixed local Decimal context of precision 80
with `ROUND_HALF_EVEN`, and a versioned output quantum of `1e-18`, denoted `Q`.
Sorting, accumulation order, rounding boundaries, and iteration limits below are
part of the method. The closed X-ray coefficient algebra uses the fully specified
local Decimal256 context in ADR-0017; ordinary precision 80 and target precision 160 stay unchanged.
Ambient Decimal context and wall-clock execution duration
must not alter results. Presentation rounding never feeds a calculation.

The method identifiers are `drift_v1`, `contribution_weighted_drift_v1`,
`performance_v2`, `benchmark_comparison_v1`, `income_v1`,
`attribution_bridge_v1`, `cash_flow_intelligence_v1`, `xray_v1`, `report_manifest_v1`, and
`alert_evaluation_v1`. Except `xray_v1` at `1.1.0` with numeric policy
`xray_decimal256_exact_q18_v1`, each remains registered at semantic version
`1.0.0`. Old immutable results retain their actual versions; do not relabel them. Existing Phase 1 XIRR, Modified Dietz, and snapshot-subperiod TWR
primitives retain their existing identifiers and version `1.0.0`; an enclosing
Phase 2 calculation records both its own method and the primitives used.
Changing a formula, bound, ordering, quality gate, or rounding rule creates a
new method version and new immutable result.

`cash_flow_intelligence_v1` is the additive P2-04 method identifier for the
separate dated external/internal cash-flow classification and currency totals
specified in this document. It does not change a performance primitive. Enclosing
calculations record the exact Phase 1 primitive identifiers they actually invoke:
`xirr`, `modified_dietz`, and `snapshot_subperiod_twr`, all at version `1.0.0`.

Every result records the authorized owner/account scope; immutable input IDs
and content digests; valuation instant; source cutoff; requested period;
reporting currency; method, policy, schema, source, mapping, and license
versions; coverage denominators; availability; quality; warnings; assumptions;
and calculation time. Replays pin those references, rather than selecting
current `latest` records. Generated result IDs and execution timestamps are
outside the deterministic result document. Its canonical JSON uses UTF-8,
sorted object keys, schema-defined array ordering, decimal strings at the
declared scale, UTC `Z` instants, and no NaN or infinity. SHA-256 of those bytes
is the semantic result digest. Source selection and source cutoff belong
inside that document; a different cutoff is a different request.

Availability and quality are separate: unavailable/unsupported/failed are not
zero; fresh/stale/partial/estimated/unreconciled are not interchangeable.
Quality is evaluated per metric from its actual dependencies. Where exposed by
the closed request, `coverage_policy` is `require_complete` by default or explicitly
`allow_degraded`; the latter cannot invent a material missing value. A complete cash
series does not make an incomplete price series complete. Default financial
decisions require complete material valuation, mapping, currency, flow, and
reconciliation inputs. An explicitly permitted degraded calculation records
the policy and affected values, and cannot claim fresh/full coverage.

## 2. Targets, actual allocation, and drift

The virtual portfolio is a conceptual root at depth zero without its own row or
weight. At most 256 actual nodes exist; top-level nodes are depth one and maximum
leaf depth is eight. Groups have children; holdings and cash are leaves. There
is at most one explicit cash leaf in the reporting currency, at depth one.
Cash cannot be nested in a group. Without an explicit cash leaf,
cash remains a synthetic component with target zero outside the target tree.
Actual holdings map to at most one disjoint target selector. For each instrument,
a version permits either one instrument-wide leaf (`listing_id` absent), or
distinct listing-specific leaves, never both. The instrument-wide leaf aggregates
all current listings with pinned FX; listing-specific leaves match only their
selected listing. Other observed holdings remain `unclassified` with their full
known value and explicit target zero.
Different listings of one entity remain separate direct holdings and produce
an economic-duplication warning; X-ray consolidates their value separately.

Sibling weights are fractions in `[0,1]` and must have positive sum `s`.
Publication requires `s = 1` exactly. Explicit `normalize=true` is allowed only
when `abs(s - 1) <= Decimal('1e-12')`. Compute each `w/s` at precision 80, floor
to `1e-18`, and distribute the remaining units to descending discarded
remainders, then ascending stable node keys. Retain original weights, `s`,
adjustments, and ordering. This produces exact sum one without inventing cash.
Larger residuals fail; normalization never silently changes a published version.

Effective leaf target `t_i` is the product of the immutable normalized sibling
weights on its path. Compute products and their sums in a local precision-160
context: eight scale-18 factors require at most 144 fractional digits. Retain
these exact intermediate products during hierarchy construction; ordinary
ratios/objectives then use the declared precision-80 context. Report `Q(t_i)`
and `effective_weight_rounding_residual = 1 - sum(Q(t_i))`. Calculations
reconstruct the source products, rather than renormalizing the reported leaves.

Convert every actual value with pinned FX before aggregating. For total
`V > 0`, component actual weight is `w_i = V_i / V`. A group's actual value and
effective target are sums over its descendant leaves. Its displayed local
child weight may additionally use the group denominator, but its portfolio
drift uses the full portfolio denominator. Signed drift is `w_i - t_i`,
absolute drift is `abs(w_i - t_i)`, relative drift is `(w_i - t_i)/t_i`
only for `t_i > 0`, and monetary gap is `t_i * V - V_i` in reporting currency.
Positive signed drift is overweight, negative is underweight, and zero is on
target. Classification uses authoritative values before display rounding.

For a non-overlapping frontier that partitions the selected portfolio, including
cash and unclassified exposure, portfolio L1 drift is
`sum(abs(w_i - t_i))/2`; weighted squared drift is
`sum(alpha_i * (w_i - t_i)^2)`. Never add parent and child weights in one
partition. Report the frontier/universe explicitly. Zero portfolio value gives
unavailable weight/drift with `zero_valuation_denominator`, while known zero
values remain visible. Negative unsupported Invest values are an explicit
quality failure, never clamped. Effective company drift is available only with
an explicitly mapped effective-exposure target and sufficient X-ray coverage;
listing targets alone do not define company targets.

## 3. Deterministic contribution optimizer

### 3.1 Inputs, objective, and modes

Pin the published target version, canonical valuation snapshot, mappings, FX,
effective constraints, reporting currency, cutoff, and quality policy. The
nonnegative contribution `C` is already in reporting currency. A different
currency requires a separate explicit conversion with pinned FX before plan
creation. `V` includes holdings, existing cash, and all known unclassified
value; `D = V + C` is fixed throughout the solve. Existing cash is not spent by
this contribution-only method. Holding recommendations `x_i >= 0` and new cash
`x_cash >= 0` obey exact `sum(x_i) + x_cash = C`. Cash is a component in the
objective and all post-plan totals, including when its target is zero.

`objective_before` evaluates the no-purchase baseline with all of the new
contribution retained as cash, using the same `D` as `objective_after`.
`before_drift` separately describes the actual pre-contribution snapshot with
denominator `V`; `after_drift` describes the proposed portfolio with denominator
`D`. The interface distinguishes these baselines rather than comparing scores
whose denominators differ.

The financial source cutoff belongs to the pinned valuation and FX observations.
An explicitly chosen target definition is a configuration reference: retain its
actual publication/effective times even when comparing it with an earlier
valuation, and disclose that comparison when the target postdates the cutoff or
valuation. Do not imply that it was the target known or active then. Automatic
historical target selection still excludes later-known definitions; this
explicit comparison never admits later financial observations.

The global objective is the versioned discrete score
`Q(sum(alpha_i * ((V_i + x_i)/D - t_i)^2))`, over holding leaves, cash,
and unclassified actual exposure in ascending stable component-key order.
Priorities `alpha_i` are in `[0.000001,1000]`, default one. Unclassified value
has allocation zero, target zero, and priority one. Quantization here is part
of the objective definition; equal quantized scores are deliberate ties.
Compare candidates by ascending `(score, residual_cash, allocation_vector)`,
where the holding allocation vector follows ascending canonical node keys.
This fully specifies ties, including which equally good line receives a unit.
The result reports the quantized score, quantum, `ROUND_HALF_EVEN` policy, and
rounding error-bound label `half_quantum`. The precision-80 intermediate score
is neither persisted nor serialized through the scale-18 financial contract.
Do not round a sub-quantum residual to zero and claim exact objective equality.

Modes have these exact meanings:

| Mode | Allocation domain and objective |
|---|---|
| `global` | All eligible mapped target holdings; minimize the global score while enforcing every ancestor/group constraint |
| `hierarchical` | Same feasible domain; minimize a lexicographic score vector for tree frontiers at depths 1 through 8, followed by the leaf score; each frontier replaces a group with children only at the next depth and carries already terminal leaves, cash, and unclassified value |
| `restricted` | Expand the selected node IDs into a union of descendant holding leaves; fix all other holding allocations to zero; retain full `V+C` denominator and global score |
| `cash_only` | Evaluate only `x_i=0, x_cash=C`, honoring all hard constraints and input gates; explicitly requested/manual cash-retention outcome |

Hierarchical mode gives top-level allocation precedence, then within-group
allocation, while solving joint discrete feasibility. It does not round an
independent group budget and silently violate child constraints. A group's
priority applies to its frontier component; carried leaves retain their own.
Synthetic cash and unclassified components use priority one at every frontier.

`C=0, V>0` permits the unique zero-allocation plan if constraints hold.
`V=0, C>0` is a valid initial funding plan. `D=0` makes the drift objective
unavailable. Cash-only fallback requires an explicit mode request; it cannot
convert a missing valuation, missing FX, or unknown denominator into a
full-quality result.

### 3.2 Hard constraints and discrete domain

The planning monetary quantum `q` is the reporting currency's versioned minor
unit, or an explicitly selected power-of-ten quantum no larger than that minor
unit, with at most 18 decimal places. Pin both the quantum and currency policy.
`C`, increments, and amount bounds must be exact multiples of `q`; reject
incompatible requests rather than rounding contribution inputs. A holding
increment is a positive integer multiple of `q`, default `q`. Its allocation
is zero or a multiple of that increment. A funded minimum requires either
zero or an allocation at least `minimum_funded_amount`; the first admissible
positive amount is the smallest increment multiple satisfying that bound.
This is a definition of the allowed domain, not an alteration of the minimum.

Group minimum/maximum funding, eligibility, exclusions, restricted scope,
and holding/group minimum/maximum post-weight
are hard constraints. A funded minimum does not mean unconditional funding.
For a group, funding is the sum of descendant new holding allocations. Cash is
outside all groups. Post-weight bounds are
absolute portfolio fractions: test `lower * D <= V_g + x_g <= upper * D`
directly, without comparing rounded displayed weights. Minimum group funding
is unconditional; exclusions never erase a conflicting lower bound.
`C` is the fixed contribution added to the portfolio, and any part that is
not allocated to holdings remains cash; there is no endogenous budget or
denominator adjustment.

A cash reserve is a minimum post-plan cash amount and/or full-portfolio cash
weight; enforce the greater required reserve, accounting for existing cash.
Maximum funded lines is an integer 0..256 and counts positive holding lines,
not groups or cash. Eligibility and listing preferences resolve to an exact
canonical funding listing before solving. The optional funding preference is
distinct from the actual-position selector: it must belong to the instrument,
and for a listing-specific leaf it must equal that selector. Without a preference,
use the explicit listing selector, or the sole eligible listing of an
instrument-wide leaf. Multiple eligible listings without a preference make
planning `unavailable/listing_choice_required`. A preference does not perform
an implicit instrument substitution or currency conversion. Multiple restrictions all
apply; no priority coefficient relaxes a hard constraint.

Every effective constraint has a stable key and is included in the plan input
digest. Negative values, contradictory same-scope bounds, unresolved material
mappings, unsupported valuations, or missing FX fail before search with typed
reasons. Proven mathematical contradictions are `infeasible`; input quality
and unavailable mappings are `unavailable`. Explicitly excluded unresolved
holdings may remain an unchanged known-valued component, with a warning, only
when the denominator itself is complete.

### 3.3 Bounded deterministic solve

Use this fixed procedure for method version `1.0.0`:

1. Build finite integer-quantum domains, retaining zero when allowed. Derive
   conservative box lower/upper bounds from the hard constraints. Check
   directly provable contradictions, including sum-of-minima versus budget,
   already breached unavoidable post-weight bounds, and zero eligible capacity.
2. Solve a continuous box relaxation as a guide. With `a_i=t_i*D-V_i`, its
   allocation has form `clip(a_i - lambda/(2*alpha_i), L_i, U_i)` including
   cash. Bracket `lambda` using the finite box endpoint derivatives and perform
   exactly 128 bisections, in fixed order, choosing the side by whether the
   sum exceeds `C`. Ignore activation/cardinality and group coupling only in
   this explicitly labeled relaxation; it is not a final feasible plan.
3. Floor the relaxed holding allocations to their increments; remove a
   positive allocation below its funded minimum. Allocate the remaining
   contribution to cash. Accept this seed only if an independent validator
   confirms every hard constraint. From a feasible seed, consider a single
   increment or minimum activation block from cash to each eligible line;
   choose the move giving the best strictly improved candidate tuple. Repeat
   until none improves or 10,000 moves have been examined. Every retained
   candidate is independently feasible. An invalid seed is discarded.
4. Search discrete candidates by depth-first enumeration of holding leaves in
   ascending stable key order. Generate each leaf's allowed amounts lazily in
   ascending `(distance from continuous guide, amount)` order. At a complete
   holding vector, set residual cash to `C-sum(x_i)` and run the independent
   hard-constraint validator. Retain the best candidate tuple. Prune only on
   proved necessary remaining-budget, remaining-capacity, group-bound, or
   funded-line violations; a heuristic score is not proof of infeasibility.
   Count every attempted assignment, including immediately pruned assignments,
   toward a fixed 100,000-node limit. No wall-clock cutoff affects the result.
5. Recompute amounts, weights, frontier scores, binding constraints, and drift
   from the selected discrete amounts. Independently verify exact conservation,
   all constraints, nonnegative recommendations, and stable serialization.
   Failure of this final validator is an internal `failed` outcome and returns
   no apparently valid recommendations.

For a singleton domain, including `cash_only`, exhaustive verification can
finish without the general search. The guide and residual-improvement stages
are bounded aids; completeness and optimality depend on the discrete domain
search, not on those aids. Group lower bounds may make the rounded seed
invalid while the search still finds a feasible plan.

| Outcome | Evidence required |
|---|---|
| `optimal` | Entire finite domain searched, including a directly verified singleton; applies to this versioned quantized objective and requested mode |
| `feasible_nonoptimal` | Valid incumbent with search limit reached; report `search_budget_exhausted`, node count, bound kind, and objective gap |
| `infeasible` | Exhaustive search found no feasible candidate, or explicit necessary constraints prove contradiction; include related constraint keys |
| `unavailable` | Material data/mapping gate failed, zero denominator, or search budget exhausted without a feasible candidate; the latter never proves infeasibility |
| `failed` | Sanitized internal arithmetic/validation/storage failure, with a correlation ID and no raw provider content |

The default safe lower bound is zero for each nonnegative squared score;
report its kind as `nonnegative_objective_bound`. For a scalar score the
absolute gap is `score - 0`; for hierarchical scores report componentwise
bounds and gaps, without claiming a scalar global optimality gap. Do not label
the bounded procedure a globally optimal continuous or mixed-integer solver.
Results are immutable; recalculation appends a new revision. None of these
values are broker orders, expected returns, or execution instructions.

### 3.4 Hand-calculable optimizer references

Unless stated otherwise, currency is EUR, `q=0.01`, holding increments are
explicitly `1`, priorities are one, and cash target is zero. The quantum follows
the currency-minor-unit rule in section 3.2; the larger holding increments keep
these reference domains hand-calculable. Values below are exact before final
`Q` output.

| Input | Required result or invariant |
|---|---|
| A=60, B=40, targets 1/2 each, C=20 | B receives 20, A receives zero, cash zero; post values 60/60 and score zero |
| Same values, C=15, B funded minimum 20, A excluded | All 15 remains cash if reserve/group constraints permit; B cannot receive 15 |
| A=60, B=40, C=20, B maximum post-weight 0.4, A excluded | B may receive at most 8; residual cash at least 12; full denominator is 120 |
| A=0, B=0, targets 1/2 each, C=1, increments 1, A key before B | A=0/B=1 beats A=1/B=0 on the final ascending allocation-vector tie; score 0.5, cash zero |
| Group G has target 0.6; its children have weights 0.25/0.75 | Effective child targets are 0.15/0.45; they are never treated as 0.25/0.75 of the whole portfolio |
| G minimum funding 11, C=10 | Proven `infeasible`, with G constraint and contribution bound identified |
| Sum of sibling inputs differs from 1 by 1e-13 | Reject without normalization; explicit normalization preserves exact sum one and records adjustments |
| Missing FX for a nonzero holding | `unavailable`; no zero-value substitution or full-quality cash fallback |
| Deliberately huge discrete domain with valid incumbent | At the fixed node limit return `feasible_nonoptimal`; repeated requests have identical canonical data |

## 4. Market, FX, and benchmark sources

All source adapters are typed and provider-specific. Source snapshots contain
only validated minimized canonical observations and metadata. A matching
canonical content digest is idempotent; a correction appends an immutable
revision. Never retain credentials, provider signed URLs, or URL-derived
fingerprints. Local synthetic/replay adapters exercise the same observation,
licensing, revision, coverage, and failure contracts without paid credentials.

Selection pins a source policy/version with a deterministic ordered provider
priority. Within a provider choose the newest applicable effective observation
whose first retrieval is no later than the source cutoff, then its declared
provider revision and stable snapshot key. Ambiguous conflicting revisions
without an ordering contract are unavailable. Economic observation time must
not exceed the valuation instant. Historical point-in-time calculations use
the historical knowledge cutoff; a later-cutoff historical reconstruction is
explicitly labeled restated. New retrieval occurrences do not backdate first
knowledge time. Persist the exact selected IDs, not just a query recipe.

Price basis is exactly `raw_close`, `split_adjusted`, or `total_return`.
Valuation multiplies actual quantities by prices in the matching quantity and
corporate-action basis. Raw prices plus actual dividend cash flows must not
also include dividend-adjusted returns. Splits change quantity/price basis,
not external contributions. Missing or disputed corporate-action coverage
blocks affected historical valuation/returns. Index levels and security
prices remain different source types even when their percentage changes match.

Use a versioned exchange/session calendar. A closed-session date may carry the
last applicable close only under that calendar policy, preserving original
source time and age; it is not a new observation. Missing an expected open
session is a gap. Never interpolate, insert zero, or extend a series before
its first valid observation. Freshness policies state maximum elapsed age and
expected sessions missed. A displayed stale latest value does not establish a
complete historical return series. Requested periods are bounded to 3,660 days
and provider pages to 1,000 observations, with independent page, response-byte,
and total-row bounds in the provider contract.

FX rates state base, quote, effective instant, source, first retrieval, and
revision. `rate(base,quote)` means quote units for one base unit; convert by
multiplication. Same-currency conversion is explicitly the identity operation,
not a missing-rate default. The source policy tries a direct pair, then an
allowed reciprocal, then at most one configured pivot. Reciprocal and pivot
operations require positive rates, preserve their source legs and formula,
and follow the same cutoff/age gate. Triangulation requires one provider,
compatible fixing/session dates, and a declared common snapshot/batch policy;
it never opportunistically mixes providers or dates. Missing legs make the
conversion unavailable. EUR/USD=1.20 and GBP/EUR=1.10 from one compatible
fixing yield GBP/USD=1.32; that value is derived, not provider-reported.

A benchmark definition version freezes series/component references, weights,
return basis, reporting currency, calendar, and rebalancing convention. Weights
sum exactly one under the explicit sibling-normalization policy. Default
buy-and-hold composite wealth is `B(t)=sum(w_i*L_i(t)/L_i(t0))` with base one.
If explicitly selected, daily rebalanced wealth is the product of
`1 + sum(w_i*r_i,k)` over common valid sessions. Never substitute one convention
for another. Convert component levels using pinned FX before forming returns.
Prefer licensed total-return series; price-only comparison is labeled as such
and is not represented as a like-for-like total-return comparison. A missing
component, period boundary, or expected session makes the composite unavailable;
weights are not silently redistributed among available series.

## 5. Performance, income, and residual-aware attribution

### 5.1 Series and returns

Reconstruct historical quantities and cash from canonical active ledger
revisions, with reconciled opening history and corporate actions, then value
them using the pinned source observations. Do not invent historical snapshots
from today's holdings. Report beginning/ending values, contribution and
withdrawal timelines, cumulative net contributions, dividends, fees, and
withholding separately. Deposits/withdrawals are signed external portfolio
flows `F`; buys, sells, internal cash transfers, dividends, fees, and taxes
are internal investment/cash effects. For account aggregation, a documented
transfer between included accounts is internal; a transfer across the selected
scope boundary is external. Unresolved transfer classification is a coverage
gate. Investment result is `G = V_end - V_start - sum(F)`.

Time-weighted return splits at each external cash flow with known pre/post
flow valuations. For a subperiod with a flow at its end,
`r_k=(V_end,k-F_end,k)/V_start,k - 1`; linked TWR is
`product(1+r_k)-1`. A flow's timestamp and valuation convention are explicit.
Missing valuations around an intraperiod flow cannot be labeled exact TWR.
Modified Dietz instead uses
`(V_end-V_start-sum(F))/(V_start+sum(a_i*F_i))`, where
`a_i=(end-flow_time_i)/(end-start)` using exact elapsed UTC seconds.
A nonpositive denominator is unavailable. Preserve the Phase 1 primitive's
validation and convention; the wrapper adds complete-history and quality gates.
The distinction between flow-time valuations and estimated Dietz weighting
follows the primary [GIPS calculation methodology](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/),
reviewed 2026-09-07; this product does not assert GIPS compliance.

MWR/XIRR uses investor signs: initial `-V_start`, each external portfolio flow
negated, terminal `+V_end`. Group exact timestamps and drop zero net flows
before sign-pattern validation. Reuse the Phase 1 conventional unique-root
policy; ambiguous/nonconventional roots are unavailable rather than choosing
a convenient solution. ACT/365 uses 31,536,000 seconds per year. Its versioned
root domain is greater than -1 with lower bracket `-0.999999999999` and upper
search limit `1000000`; maximum iterations 256, interval tolerance `1e-24`,
and relative NPV tolerance `1e-28`. The high bracket starts at one and expands
by a factor of ten up to its bound. NPV tolerance is
`max(1e-24, sum(abs(investor_flows))*1e-28)`; either that NPV tolerance or the
interval tolerance terminates bisection. Solver failure retains its typed reason.

Calendar periods use explicit reporting-calendar boundaries and UTC instants;
rolling windows declare their day/session length. Every requested boundary
and required session must be covered. Cumulative return `R` can be annualized
only for elapsed duration at least 365 days and `1+R>0`, using
`(1+R)^(365/days)-1`, with `days=elapsed_UTC_seconds/86400`, in the fixed
Decimal context. XIRR is intrinsically annual
and is labeled with its elapsed period and solver method. Do not relabel a
short-period cumulative return as annualized performance.

Drawdown uses a flow-neutral TWR wealth index `W`, peak
`P_t=max(W_s for s<=t)`, and `DD_t=W_t/P_t-1`; report the running and maximum
negative drawdown. Positive peak and complete linked-return coverage are
required. A separate raw-value drawdown, if requested, explicitly discloses
its dependence on contributions and withdrawals.

Benchmark and portfolio start/end instants, reporting currency, and eligible
sessions must align exactly. Cumulative excess return/tracking difference is
`R_portfolio-R_benchmark`. Optional relative wealth return is separately named
`(1+R_portfolio)/(1+R_benchmark)-1` and requires positive benchmark wealth.
Annualized tracking difference compares individually eligible annualized
returns, not annualized arithmetic subtraction. Tracking error uses sample
standard deviation of aligned daily active returns, multiplied by the square
root of the versioned calendar's annual session factor (default 252). Require
at least 20 paired observations and no hidden gaps; otherwise it is unavailable.
All square roots and powers use Decimal, never a binary-float financial path.
The active-return standard-deviation definition is supported by
[CFA Institute's Evaluating ETFs chapter, page 43](https://rpc.cfainstitute.org/sites/default/files/-/media/documents/book/rf-publication/2015/rf-v2015-n3-1-pdf.pdf),
reviewed 2026-09-07; the minimum observation count and session factor are
explicit product policies, not a claim of universal statistical sufficiency.

### 5.2 Income and P/L

Income uses active canonical dividend revisions and their economic payment
dates. Report gross, withholding, and net only when their fields reconcile;
unknown gross or tax is null with a reason, not inferred zero. Negative
corrections remain visible and do not create a new positive-dividend event.
Aggregate by currency without FX, and additionally by reporting currency only
with pinned payment-date FX. Instrument/group assignment pins the selected
target/mapping version and states whether historical or comparison grouping
was requested. Fees and withholding remain individually inspectable.

Period income yield is covered net income divided by the time-weighted mean
invested value over that period, excluding cash and requiring a complete
valuation series with positive denominator. The mean is
`sum(invested_value_at_start_k * elapsed_seconds_k)/total_elapsed_seconds`,
over the declared session-close partitions, with the prior valid value held
only through permitted closed-session intervals. It is a realized period measure,
not a forecast yield. Portfolio dividend growth compares net income against
the immediately preceding equal calendar period in the same currency, with a
positive denominator and full coverage. Disclose changes in holdings and FX;
this is not issuer dividend-per-share growth. Income concentration uses each
positive income component divided by total positive income, with negative
corrections reported separately. Zero positive income makes concentration
unavailable. Realized/unrealized P/L uses the existing cost-basis/lot policy
only where opening lots and corporate actions are sufficiently covered;
unsupported basis does not become a zero P/L.

### 5.3 Attribution and cash drag

Reconcile every attribution view to `G`. Instrument and group contribution
are alternative partitions of the same result; price/income/fee/tax/FX are a
different decomposition, and are never summed across those views. Each effect
is classified once, with active ledger/source revisions pinned.

For a constant-quantity segment with quantity `q`, raw native prices `p0,p1`,
and reporting-currency FX `f0,f1`, use:

- price effect: `q*(p1-p0)*f0`;
- FX effect: `q*p0*(f1-f0)`;
- price/FX interaction: `q*(p1-p0)*(f1-f0)`.

Their sum is exactly `q*(p1*f1-p0*f0)` before output quantization. Split at
supported trades/corporate actions, using execution valuations and FX where
available; add actual dividend cash, signed fees/taxes, and separately
identified cash FX. Missing transaction-time inputs make the affected
decomposition unavailable; they do not justify guessing an allocation.
Dividend-adjusted prices cannot be combined with dividend cash a second time.

Always show `residual = G - sum(available attributed amounts)` with reasons,
including uncovered effects and output rounding separately. A known residual
is not automatically a fee or FX effect. Return attribution for Modified Dietz
divides component amounts and residual by the same valid Dietz denominator.
For flow-split TWR, subperiod component returns `c_j,k` are linked by
`sum_k(c_j,k * product_l>k(1+r_l))`, including an explicit residual component,
so their sum equals linked TWR. Do not combine incompatible attribution bases.

Cash drag is an explicitly labeled benchmark-relative counterfactual:
per aligned subperiod, `cash_weight_start*(cash_return-benchmark_return)`.
Link periods with the declared return-attribution convention. It is available
only with sourced cash income/return, aligned benchmark returns, and relevant
cash timing; otherwise return `unavailable_cash_counterfactual_inputs`.
Brinson allocation/selection effects are unavailable without benchmark
constituent weights and returns. Unsupported decomposition is never fabricated.

Reference: `q=2, p0=10, p1=12, f0=1, f1=1.1` gives price 4, FX 2, interaction
0.4, and total valuation change 6.4. Adding known dividend income 3, tax -0.5,
and fee -0.2 gives 8.7 before any external flow. A reported total gain 9 then
requires explicit residual 0.3, not a silently adjusted component.

## 6. ETF look-through and Portfolio X-ray

Use explicit versioned listing/security/share-class/ADR/entity relationships,
with provenance, validity dates, and confidence. Listing is not company;
ticker alone is not a high-confidence identity. An ADR ratio describes units
and is not applied again to an already valued position. Share classes and
ordinary/ADR holdings consolidate only when an applicable relationship
supports that economic identity. Keep the original paths for drill-down.

For fund portfolio weight `w_f` and constituent weight `c_f,e`, its entity
contribution is `w_f*c_f,e`. Sum direct entity weights plus all applicable fund
paths to obtain effective exposure. The direct view retains fund wrappers;
the effective view replaces the wrapper with constituent/unresolved paths,
rather than counting both. Known fund cash stays cash. Missing constituent
weight is unresolved, never assumed cash or redistributed among known entities.

Select constituent snapshots with effective time no later than valuation and
first retrieval no later than source cutoff. A later-cutoff historical
restatement is labeled; a future-effective constituent set cannot become a
historical fact. Source-date mismatches and stale sets stay explicit. A
snapshot with summed weight below one retains `1-sum(weights)` unresolved;
negative weights or sum above one are invalid for this long-only method.
A separately requested normalized known-only comparison view must disclose
its discarded mass and cannot replace the default absolute-exposure view.

Nested funds recurse for at most four fund edges and 10,000 visited exposure
paths across the complete snapshot, including position/cash roots and zero-valued
funds. Detect cycles on the current ancestry path; repeated diamond paths remain
independent. Reserve every pending branch before expansion; reject an initial
root inventory that cannot fit, rather than selecting a favorable prefix. At a bound, cycle, missing fund snapshot,
or unsupported instrument, preserve the entire unexpanded path weight in an
unresolved bucket with its reason. The result is partial, not falsely complete.
Aggregate paths in stable source/entity-key order; quantities of unlike
securities are never added to infer economic exposure.

Sector, industry, country, region, and economic-currency breakdowns use sourced
classification assignments with taxonomy/version/confidence. Listing currency
is a separate direct attribute, not economic-currency exposure. Each dimension
has its own known/unresolved mass, so complete country classification does not
imply complete sector coverage. Report direct portfolio-value coverage, fund
constituent coverage, entity mapping confidence, inferred value, stale value,
classification coverage, and unresolved weight. Known+unresolved+explicit cash
must reconcile to the original portfolio mass, with output rounding disclosed.

Pairwise ETF overlap is `O_ab=sum_e(min(c_a,e,c_b,e))` after economic-entity
consolidation, over absolute known weights. Incomplete mapping/constituents
make that a known-overlap lower bound, not evidence of no overlap. Pairs are
sorted by canonical fund keys. Portfolio duplicated exposure is
`sum_e(total_source_weight_e-max_source_weight_e)`, where each source is one
direct holding or top-level fund position with its paths consolidated per
entity. It measures exposure shared across sources and is not added to total
portfolio exposure. Within-fund duplicate listings consolidate before this
calculation.

Top-N concentration and HHI use absolute effective entity weights, with
`HHI=sum_e(weight_e^2)`. State whether cash is included; company concentration
excludes it without renormalizing the remaining portfolio denominator.
Unresolved exposure gives known-only lower bounds and an explicit unknown mass;
threshold alerts requiring a complete concentration result are suppressed or
explicitly degraded. Do not publish a falsely exact portfolio HHI with missing
constituents.

Reference: direct A=0.20; fund F1=0.50 with A/B/unresolved=0.60/0.30/0.10;
fund F2=0.30 with A/B=0.20/0.80. Effective A=0.56, B=0.39, unresolved=0.05.
F1/F2 known overlap is 0.50. Portfolio duplicated exposure is
`(0.56-0.30)+(0.39-0.24)=0.41`. An ADR and ordinary holding mapped to A join
that same entity; their source paths remain inspectable. Marking F1 stale
does not change these arithmetic values, but makes the result stale/partial
according to its pinned quality policy. It cannot be advertised as current.

### 6.1 Exact coefficients, bases and metric states

[ADR-0017](../adr/ADR-0017-DECIMAL256-EXACT-XRAY.md) supplies the complete closed
precision proof, input/zero/role bounds, trap policy, exact Decimal divmod HALF_EVEN,
post-round NUMERIC overflow and residual inequalities. At k<=4 fund edges use
M=amount*10^18, a=weight*10^18, R=product(a)*10^(72-18k), N=M*R. Relative composition
has denominator 10^72; money has denominator 10^90. R exists independently of M.
Missing reporting valuation/FX is absent money, never M=0. Both child-unit and
available-money conservation are mandatory before rounding, including M=0 roots.

Let D be the complete root reporting-value numerator, and K the known noncash
numerator for the selected dimension. Absolute weights divide by D; D<=0 or an
unavailable complete basis makes the dependent ratio unavailable. Known-normalized
comparisons divide by that dimension's K; K=0 is unavailable. Keep absolute cash,
unknown and discarded mass visible. Company concentration excludes cash numerators
without renormalizing D. Consolidate entity N before H=sum(N_e*N_e); HHI=H/(D*D).
Fixed top1/5/10/25/50 sums rank exact N with stable entity-key ties. Duplication
consolidates each original position per entity before sum-minus-cross-position-max.
Do not aggregate unlike quantities or apply saved FX/receipt ratios twice.

Threshold policies pin ID/version/source, configured/unconfigured state, top1/top5/
HHI limits in [0,1] and each strict `gt` or inclusive `ge` operator. Compare exact
N*10^18 to T*B, never rounded displays. A partial lower bound may prove a breach;
an inconclusive partial comparison is unavailable, not false. An unavailable
threshold result does not erase a computable overlap lower-bound value. Positive
sub-Q18 unknown mass remains unknown; independent signed display residuals never
repair or redistribute mass. No default concentration limit or P2-07 alert is added.

### 6.2 One run, representative funds and closed interfaces

Calculate once over complete immutable inputs. Dimension, normalized presentation,
selected fund set, Page, Top and view are projections, not new calculation inputs.
Select each exact held canonical fund's lowest tagged real snapshot-position UUID
key, including zero-valued roots, before considering coverage or value. Retain that
occurrence's unit composition from the same global traversal. No best-root fallback,
second traversal, cross-root union or multiplication into another monetary root.
Real snapshot-cash rows retain their own tagged identities. The versioned traversal
policy `xray_position_then_cash_uuid_v1` orders positions before cash, then lowercase
real row UUIDs lexically within each kind; do not use ASCII tag or input order.

For two valid unit bases, consolidate entities then sum min(R_a,e,R_b,e)/10^72.
An incomplete legitimate basis yields a known-overlap lower bound, including zero
with unknown actual overlap; fully supported disjoint funds can yield exact zero.
Missing monetary FX alone does not remove an independent authorized unit basis.
An unestablishable/expired basis is unavailable; license/owner/nonheld-ID denial
preserves the normal error, never a successful zero fallback. Q18 can round a lower
bound upward by Q/2, so it is a displayed approximation; exact comparisons use R.

X-ray pins its completeness/degraded metric gates in the immutable quality policy;
no undeclared public coverage-policy argument is introduced.

The closed shared domain records are `XrayPolicyVersion`, `XrayInput`,
`XrayPosition`, `XrayCash`, tagged `RootRef`, `XrayCalculation`, `FundComposition`,
`XrayExactState`, `XrayMoneyMetric` and `XrayRatioMetric`. Pin complete snapshot/
owner/account/currency/cutoff, typed dependencies, provider/identity/classification/
freshness/quality/threshold/traversal policy versions and method/schema identity.
Current access/generated envelopes do not enter semantic bytes. `content_digest`
is derived from the complete canonical result excluding itself.

```text
calculate_xray(value: XrayInput) -> XrayCalculation
verify_xray_result(value: XrayInput, result: XrayCalculation) -> None
calculate_overlap_pairs(result: XrayCalculation,
                        fund_ids: tuple[UUID, ...]) -> tuple[CanonicalOverlapPair, ...]
calculate_common_entities(result: XrayCalculation,
                          pair: CanonicalFundPair) -> CanonicalCommonEntities
company_exposure_basis(result: XrayCalculation) -> CompanyExposureBasis
encode_xray_input(value: XrayInput) -> bytes
decode_xray_input(payload: bytes) -> XrayInput
encode_xray_result(value: XrayCalculation) -> bytes
decode_xray_result(payload: bytes) -> XrayCalculation
```

These are required implementation seams, not existing implemented exports. Pair
helpers use retained compositions only; neither source selection nor traversal is
repeated. Same-run A/B values/evidence survive adding C or changing presentation.
Changed actual snapshots need not select the same representative. Public row/run
UUIDs and calculation time belong to the stored envelope; path identities and
exact-state/provenance are semantic. Closed codecs validate role bounds and typed
states; independent verification checks both normalized and retained exact truth.

## 7. Private reports and exports

### 7.1 Canonical content and formats

Report types are `monthly`, `quarterly`, `annual`, `portfolio_summary`,
`target_drift`, `contribution_plan`, `performance_benchmark`, `dividend_income`,
`portfolio_xray`, and `quality_reconciliation`. Monthly/quarterly/annual types
derive explicit calendar boundaries; an on-demand summary pins its requested
valuation instant. Formats are PDF, CSV, JSON, and XLSX. The fixed section enum
is `overview`, `allocation`, `targets`, `drift`, `contribution_plan`,
`performance`, `benchmark`, `income`, `cash_flows`, `attribution`, `xray`,
`quality`, and `activity`; selections contain at most these 13 unique values.
All nontrivial requests use the durable report job path, including local mode.

| Report type | Required selected sections | Additional required references |
|---|---|---|
| `monthly`, `quarterly`, `annual` | overview, allocation, performance, income, cash_flows, quality | Complete named calendar period and boundary snapshot/source references |
| `portfolio_summary` | overview, allocation, quality | Valuation snapshot |
| `target_drift` | overview, targets, drift, quality | Published target version and valuation snapshot |
| `contribution_plan` | overview, targets, contribution_plan, quality | Finalized immutable plan revision and its target/snapshot |
| `performance_benchmark` | overview, performance, benchmark, quality | Period valuation/flow sources and benchmark version/snapshot |
| `dividend_income` | overview, income, cash_flows, quality | Period canonical activity snapshot |
| `portfolio_xray` | overview, xray, quality | Valuation snapshot and X-ray run with exact constituent/mapping sources |
| `quality_reconciliation` | overview, quality, activity | Valuation/activity snapshot and latest applicable reconciliation run, or its explicit absence |

Optional selected sections add their own dependencies: targets/drift require
the published target, contribution_plan the immutable plan, benchmark its
version/snapshot, and xray its run. Reject missing required section selections
or irrelevant request references. A section whose canonical result is
unavailable may render that result and reason; it cannot silently disappear or
be presented as a complete calculation. Standalone dataset exports use the
same authorization, manifest, limits, licensing, escaping, storage, and expiry
policy, with their own typed `exports.generate.v1` job/outbox.

A report selects persisted canonical service results, without recomputing
financial arithmetic in templates or the browser. Its independent
`report_manifest_v1` document records scope, period, valuation and source cutoff,
reporting currency, selected sections/formats, schema/renderer/locale versions,
target/plan/snapshot/calculation IDs and digests, source/mapping/license versions,
coverage, quality, assumptions, reconciliation, and warnings. It excludes
generated job IDs, execution time, expiry, access grants, and storage addresses.
Identical canonical inputs/options produce identical manifest bytes and hash.
Each artifact additionally records the hash of its actual bytes. PDF generation
metadata may contain execution time; byte-identical PDFs are not claimed unless
tests establish that separately. Fonts, ordering, chart series, and renderer
version are pinned. Authoritative chart/table values match API and MCP output.

PDF structure includes scope/currency/valuation, totals, selected analytical
sections, source and methodology notes, quality/coverage/reconciliation appendix,
assumptions, and limitations. Include headings, logical reading order,
selectable text, contrast, and tabular chart equivalents; state renderer
accessibility capabilities honestly. CSV/JSON/XLSX include the same provenance
and unavailable states through explicit columns or companion manifest sections.
The activity worksheet groups canonical dated events and identifiers for
accounting review, without asserting tax classification or tax advice.

CSV uses UTF-8, quoted fields, doubled embedded quotes, and RFC-4180 escaping.
Treat all provider/user strings as text:
if the first character after leading whitespace/control/BOM is `=`, `+`, `-`,
or `@` (including their full-width Unicode variants), or the value begins with
tab/CR/LF, prefix an apostrophe in the export
cell. Preserve original safe values in the canonical JSON; the manifest records
the export escaping method. Validated numeric decimal fields have a distinct
schema and are not user-provided formula expressions. XLSX writes exact money,
quantity, IDs, UTC timestamps, and all untrusted strings as explicit text cells;
it has no formulas, macros, external links, or implicit float conversion.
Safe HTML/PDF templates escape markup. Filenames are generated from fixed report
type/date/opaque identifier, not arbitrary user names or paths. MIME and
Content-Disposition are fixed by format; downloads use `nosniff`.
The [OWASP CSV injection guidance](https://owasp.org/www-community/attacks/CSV_Injection),
reviewed 2026-09-07, cautions that spreadsheet save/reopen behavior can remove
CSV escaping. This format policy protects generated cells under the tested
import behavior, not arbitrary downstream transformations; explicit-text XLSX
and canonical JSON preserve stronger type semantics. Regression fixtures cover
separators, quotes, whitespace, full-width initiators, and multiline text.

Bound a selected dataset to 100,000 rows, 64 columns, and 4,096 characters per
text cell; bound each artifact to 10 MiB and the complete job to 25 MiB across
at most four formats. Read at most the row limit plus one to detect overflow,
and enforce byte bounds during generation. Exceeding any bound yields a typed
limit failure with no silently truncated artifact or false success. An
explicit summary with an `other` bucket is a different report selection and
states its aggregation. License permissions are checked at selection and
download time; unknown or denied storage/display/export rights deny that use.
An omitted restricted section requires an explicitly requested redacted report,
whose manifest records the omission, rather than a successful incomplete export.

### 7.2 Storage, execution, access, and retention

The default private artifact store is PostgreSQL BYTEA with owner/account
foreign keys, content length/type/hash, manifest digest, and expiry. Completion
of all requested artifacts and the immutable manifest is one transaction,
guarded by the current fenced job lease. Temporary generation is bounded and
does not persist raw source data or public URLs. An optional typed external
object-store port must provide equivalent private authorization, content hash,
expiry, and orphan-cleanup guarantees; it is not required for local completion.

Creation authenticates/authorizes the exact scope, validates all options,
pins immutable inputs in one transaction, and inserts a typed
`reports.generate.v1` outbox record. Owner-scoped idempotency keys return the
existing job for identical semantic inputs and conflict for different inputs.
Retries reuse the original input manifest. PostgreSQL is authoritative for
queued/running/succeeded/failed/expired states; Redis is transport/cache only.
Workers claim due jobs with row locking, a 60-second lease, 15-second heartbeat,
and monotonically increasing fence token. Only the current fence can commit.
Crash/restart allows reclaim after lease expiry. At most four execution
attempts use deterministic delays 1, 2, and 4 seconds between attempts;
permanent validation/license failures do not retry. Exhaustion records a
sanitized terminal failure/dead-letter reason. Unique job/format keys and
transactional completion prevent duplicate finalized artifacts. Outbox dispatch
and consumption remain idempotent under duplicate Redis deliveries. Publication
has at most eight attempts under the existing fenced outbox policy, independently
of the four consumer execution attempts; exhaustion has an explicit dead-letter
state and cannot falsely mark a job successful.

Expiry is seven days by default, configurable per authorized request from one
to 30 days. It is checked during every download, independently of physical cleanup.
Downloads require current owner/account authorization. Any short-lived access
grant is a cryptographically random opaque token with only its digest stored,
bound to that owner/artifact, valid at most five minutes and never beyond
artifact expiry. It supplements authentication; UUID/token possession does not
replace ownership. Grant bytes and download URLs are excluded from ordinary
logs, manifests, MCP results, and source snapshots. Streaming rechecks the
authorized object before reading bytes; cache headers are private/no-store.

An idempotent PostgreSQL cleanup job processes at most 100 expired artifacts
per transaction in stable expiry/key order with row locking. It clears bytes
and grants atomically, retaining only the permitted manifest/audit tombstone
and byte digest under the configured audit-retention policy. Owner deletion
revokes access and applies the same retention policy. Record creation,
completion/failure, authorized download, expiry, and deletion audit events
without tokens, byte content, raw provider payloads, or credential material.

## 8. Versioned alerts and deterministic evaluation

### 8.1 Rule families and quality gates

Rules are owner/account-scoped with immutable versions, typed family-specific
fields, severity, schedule, cooldown, quality policy, and safe remediation text.
The stable identity has draft/active/paused/archived lifecycle; modifying an
active rule creates a new version. There is no user expression language,
generic task payload, arbitrary URL, or trading execution capability.
Comparison operators are the bounded enum `gt`, `gte`, `lt`, `lte`, `eq` with
metric-compatible typed Decimal/integer/state thresholds. No binary floats
or textual `eval` path is permitted.

| Family | Supported metric/predicate and material-input rule |
|---|---|
| Target drift | Portfolio L1 drift on a named target version/frontier; requires complete valuation, target, mapping, and FX |
| Group drift | Absolute full-portfolio drift for one group node; same gates, not a sibling-relative threshold |
| Holding drift | Absolute drift for one canonical target holding; same gates, unchanged observed denominator |
| Concentration | Direct holding maximum weight, top-N weight, or HHI with explicit cash treatment; complete selected direct universe |
| Effective company concentration | One entity's effective weight, top-N effective weight, or effective HHI; requires material entity/constituent coverage, otherwise unavailable/degraded |
| ETF overlap | Named pair's known overlap or portfolio duplicated-exposure metric; incomplete coverage is a lower-bound state, not exact zero |
| Cash threshold | Cash amount with currency or cash/full-portfolio weight; amount needs known cash, ratio also needs complete valuation/FX |
| Stale data | Age in elapsed seconds and/or expected sessions missed for a named source family; evaluates stale state deliberately |
| Missing coverage | Missing count or `1-covered_fraction` for a named valuation/history/price/FX/constituent/classification domain; unknown denominator is unavailable |
| Reconciliation failure | Failed reconciliation state or typed discrepancy count/severity from a completed reconciliation run |
| Provider failure | Last completed typed provider failure or consecutive failed requests/runs within a bounded window; no credential/error-body matching |
| Failed refresh | New terminal failed canonical refresh run, keyed by run ID; incomplete/running refresh is not failed |
| Dividend received | New positive net canonical dividend payment, keyed by economic event and active revision; duplicate replay is ignored and corrections are identified |
| Unusual activity | Explicit absolute cash-flow amount, typed activity count in a bounded window, or new unclassified activity; fixed thresholds and sourced currencies, with no statistical/predictive trading signal |
| Report completion/failure | New terminal report job outcome and report type, keyed by job ID; no artifact content or private download token in the event |

The exact family and metric wire identifiers, with their additional typed scope
fields, are fixed below. Reject irrelevant fields and incompatible threshold
types. `top_n` is 1..50 (default 25); observation windows are integer seconds
from 300 through 2,678,400 (31 days), and retain their UTC start/end instants.
Each referenced target, group, holding, entity, fund pair, source, or report
belongs to the rule's authorized owner/account context.

| Family identifier | Metric identifiers | Additional checked fields |
|---|---|---|
| `target_drift` | `portfolio_l1_drift` | target_version_id, frontier_depth |
| `group_drift` | `group_absolute_drift` | target_version_id, group_node_id |
| `holding_drift` | `holding_absolute_drift` | target_version_id, holding_id |
| `concentration` | `direct_max_weight`, `direct_top_n_weight`, `direct_hhi` | include_cash; top_n only for top-N |
| `effective_company_concentration` | `effective_entity_weight`, `effective_top_n_weight`, `effective_hhi` | entity_id only for entity weight; top_n only for top-N |
| `etf_overlap` | `etf_pair_overlap`, `portfolio_duplicated_exposure` | two distinct canonically ordered fund IDs only for pair overlap |
| `cash_threshold` | `cash_amount`, `cash_weight` | reporting currency for amount threshold |
| `stale_data` | `source_age_seconds`, `source_missing_sessions` | fixed source_family and applicable source ID; calendar version for sessions |
| `missing_coverage` | `missing_count`, `missing_fraction` | domain enum valuation/history/price/FX/constituent/classification and applicable source ID |
| `reconciliation_failure` | `reconciliation_failed`, `reconciliation_discrepancy_count` | optional fixed discrepancy severity filter |
| `provider_failure` | `provider_failed`, `provider_consecutive_failures` | configured provider ID, bounded observation window |
| `failed_refresh` | `refresh_failed` | optional refresh capability-family filter from the fixed registry |
| `dividend_received` | `positive_dividend` | optional canonical instrument ID; optional positive minimum net amount/currency |
| `unusual_activity` | `absolute_external_flow_amount`, `activity_count`, `unclassified_activity` | bounded window, fixed activity-kind filter, currency only for amount |
| `report_outcome` | `report_terminal` | report_type filter and outcome succeeded/failed/either |

Weights/drift/HHI/amounts use DecimalString thresholds. Counts, ages, and session
counts use nonnegative integer thresholds. Boolean failure states permit only
`eq` with a boolean threshold. Event predicates refresh_failed, positive_dividend,
unclassified_activity, and report_terminal have their fixed qualifying condition
and no comparison expression; their relevant optional filter fields above do
not broaden them into arbitrary expressions. Event-like unusual activity also
pins the qualifying canonical activity revision. Source age is scheduled cutoff
minus the latest eligible source effective instant, never worker wall time.
Provider consecutive failure counts reset on a recorded success in the selected
window; no observations is unavailable, not a fabricated success or failure.

All requested families are supported under their mathematical/data preconditions.
Unavailable metrics return a stable reason and no fabricated boolean. A default
financial threshold suppresses stale/partial/estimated/unreconciled material
inputs. An explicitly allowed degraded policy can emit an event labeled with
the exact quality and affected coverage. Health rules for stale data, missing
coverage, reconciliation, or provider failure deliberately evaluate those
states; they must not suppress the condition they are designed to observe.
Missing FX, unsupported P/L/attribution, unknown entity identity, or incomplete
history cannot be substituted with zero to trigger or clear a financial rule.
Suppressions and unavailable evaluations are persisted and inspectable.

### 8.2 Scheduling, episodes, cooldown, and lifecycle

Schedules pin either a UTC anchor with integer interval from 300 to 86,400
seconds (default 300), or a daily UTC minute from 0 to 1,439. Interval slot `n`
has cutoff `anchor+n*interval`; a daily slot is midnight UTC plus its selected
minute. There is no locale/DST-dependent schedule. Cooldown is an integer from
0 to 604,800 seconds. Use slot time, not worker start time. At each due slot,
a transaction records the rule version,
exact eligible input snapshot manifest, evaluation job, and typed outbox event.
Unique `(rule_version, scheduled_for)` prevents duplicate slots. Process at
most 100 due slots per scheduler transaction, in stable slot/rule order;
deferred slots remain due and are not silently dropped. Retries use the same
pinned manifest/cutoff. Explicit backfill is a bounded separate request and
does not overwrite earlier evaluations.

Threshold rules create an episode on false-to-true transition. Continued true
evaluations update evidence/history without duplicate events; true-to-false
resolves the episode with `condition_cleared`. An unavailable evaluation neither
clears nor creates an episode and records the gap. Acknowledgment records who
has seen the event independently of condition resolution. Manual resolution
does not rearm a continuously true predicate; rearming requires a later false
evaluation. A new rule version closes old open episodes as `rule_superseded`,
without claiming the observed condition recovered. The first eligible true
evaluation of an active new version may create its own episode.

Event-based families deduplicate by rule version, family, stable economic/run/
job identity, and active revision. Corrections have explicit correction links;
the same economic revision arriving twice is not two dividends or failures.
Database unique keys enforce both event and episode identities. Cooldown limits
notification attempts after the last eligible notification time; it does not
erase distinct events or evaluation history. An event during cooldown remains
in the in-app feed with `suppressed_cooldown` notification state. Continued
true thresholds do not retrigger just because cooldown elapsed.

### 8.3 Durable delivery and optional destinations

Evaluation jobs, fixed typed outboxes, leases, fence tokens, bounded retry,
and dead-letter handling use the report-job durability policy in section 7.2.
Final evaluation, condition state, event, in-app notification, and delivery
outbox are committed transactionally. Unique event/owner notification keys
make in-app delivery idempotent. The in-app feed is complete without external
credentials or destinations. API/web acknowledgment and resolution require
owner/account authorization, concurrency checks, and audit; MCP may expose
bounded summaries under its accepted tool policy.

Optional email/webhook destinations reference a separately configured and
versioned server-side destination plus opaque credential reference. Missing
configuration reports `external_delivery_unavailable`; it does not block
evaluation or in-app events. Delivery attempts reuse a stable delivery ID and
bounded payload. External transport is at-least-once: a receiver may deduplicate
that ID, but an ambiguous timeout cannot establish exactly-once external
delivery. Retry four attempts with the same bounded delay policy; retain
sanitized terminal failure and dead-letter status. Recheck owner/destination
authorization before delivery, and never send artifact tokens or secrets.

The optional webhook adapter is dedicated to this purpose. It permits configured
HTTPS origins on port 443 outside isolated tests, verifies TLS, disables
environment proxies and redirects, and rejects credentials in URLs. Validate
every DNS answer and every retry against loopback, private, link-local,
metadata, multicast, reserved, and IPv4-mapped IPv6 forbidden destinations.
Pin the actual connection to a validated public address while preserving TLS
hostname/SNI; re-resolution without connection pinning is insufficient against
DNS rebinding. Reject a host if any returned address violates the policy.
Use bounded connect/read/total timeouts and at most 64 KiB request/response
bodies. No public tool accepts a per-call URL or destination credentials.
These controls apply the allowlist and DNS-rebinding concerns described by
[OWASP's SSRF prevention guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html),
reviewed 2026-09-07, with this product's stricter fixed-destination contract.

Reference: a drift rule observes false/true/true/unavailable/false/true over six
slots. It creates two episodes, retains the unavailable evaluation, and closes
the first only on the fifth slot. Replaying any slot or Redis delivery creates
no additional event. A new dividend during cooldown is still visible in-app,
with suppressed external notification. An absent webhook does not affect these
results; a private-address or redirecting destination fails before dispatch.
