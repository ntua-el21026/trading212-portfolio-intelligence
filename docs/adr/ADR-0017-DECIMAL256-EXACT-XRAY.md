# ADR-0017 — Decimal256 exact X-ray coefficients and representative fund compositions

**Status:** Accepted design decision; implementation evidence remains separate

**Date:** 2026-09-09

**Decision authority:** Owner-authorized Decimal-only numerical policy and the settled representative-root/lifecycle closure.

**Scope:** P2-05 design only. P2-05 implementation is not_started; Phase 3 remains not_started.

This narrowly amends the common precision and X-ray version declarations in the
[v0.2 delta](../DESIGN_FREEZE_V0_2.md), [methods](../analytics/PHASE_2_METHODS.md),
[technical baseline](../implementation/PHASE_2_TECHNICAL_BASELINE.md) and
[data model](../architecture/PHASE_2_DATA_MODEL.md). It preserves the accepted text of
[ADR-0004](ADR-0004-DETERMINISTIC-DECIMAL-FINANCIAL-ENGINE.md),
[ADR-0011](ADR-0011-DETERMINISTIC-CONTRIBUTION-OPTIMIZER.md) and
[ADR-0013](ADR-0013-ECONOMIC-ENTITY-NORMALIZATION.md). The representative policy was
selected by the coordinating assistant within the owner's authorization; it is
not attributed to an earlier explicit owner selection or to the original ADRs.

## Context

The frozen X-ray method requires four nested fund edges, one global 10,000-visited-path bound, replacement of wrappers by their economic paths, complete mass accounting, entity consolidation, pairwise sum-min overlap, original-position duplication, and absolute company concentration. Money and source weights can have 18 fractional digits. Exact path values followed by cumulative sums and HHI squaring need more retained precision than the ordinary 80-digit context.

A valid source-derived entity amount can be `10^18 + 5*10^-19 + 10^-90`: one direct amount, one minimum-quantum amount weighted by 0.5, and another minimum-quantum amount weighted by four minimum-quantum edges. Its Q18 value is `1000000000000000000.000000000000000001`. Precision-80 aggregation can discard the last positive term and round the changed exact-half case to `1000000000000000000.000000000000000000`. Exact products alone do not prevent this loss at aggregation.

The recovered Python-integer coefficient proposal is unsuitable because the owner requires Decimal for production financial arithmetic, including private intermediates. A finite Decimal coefficient algebra provides the needed exactness without a general rational-expression engine.

Multiple original held positions can refer to the same canonical fund instrument. The single global traversal budget may truncate those occurrences differently. Pair output is keyed by fund instrument and therefore needs a deterministic choice of one retained relative composition. That choice must preserve every original position's independent monetary paths and duplication source.

## Decision

### 1. Scope, identity and supersession

Adopt `xray_v1` version **`1.1.0`**, with numeric policy **`xray_decimal256_exact_q18_v1`**. Pin method/version, numeric policy, representative-root/traversal policy, threshold policy identity, complete snapshot, source cutoff and selected evidence in immutable inputs and result identity. This ADR and the synchronized method amendment must precede code depending on this exception.

This decision narrowly supersedes the ordinary precision-80 intermediate requirement for the closed X-ray operations listed below, and the frozen `xray_v1` version-1.0.0 declaration. It also documents the bounded private coefficient representation needed for exact replay. It preserves ordinary financial precision 80, the existing target-hierarchy precision-160 exception, public/normalized financial NUMERIC(38,18) fields and Q18 HALF_EVEN boundaries. It does not change other method/release versions, historical result attribution or source identity rules.

ADR-0004's Decimal/versioned-calculation principles and ADR-0013's economic identity, receipt and monetary-path rules remain controlling and compatible. ADR-0004, ADR-0011 and ADR-0013 retain their original accepted text. This ADR narrows the common precision requirement only for X-ray; ADR-0011 contribution arithmetic and the existing target hierarchy exception are unchanged. Earlier results retain their actual method/version; do not relabel or migrate a 1.0.0 digest as 1.1.0.

### 2. Bounded Decimal inputs, zero and retained representation

Money inputs used by the monetary kernel are finite validated Decimal reporting amounts with absolute magnitude below 10^20, scale at most 18, at most 38 stored coefficient digits and bounded canonical exponent [-18,20]. Roots and source weights are nonnegative under this long-only method; each weight is at most one. Reject unsupported shape/range before scaling, including for zero. Exact bounded input-codec canonicalization may resolve equivalent encodings; rounding into compliance is forbidden.

Use Decimal for every financial operand and operation, including coefficients, min/max, sums, comparisons, rounding parity and residual bounds. Python integers may represent loop counts, indexing, exponent metadata and Context configuration. Convert a count to Decimal before using it in a financial error-bound expression. Fraction and integer financial arithmetic are allowed only in independent test oracles and test construction. No float path is introduced.

Let `S=Decimal("1e18")`, `Q=Decimal("1e-18")`. Construct `coefficient18(x)` by exact Decimal scaleb by Decimal("18"), then quantize to Decimal("1") in the exact context. The input exponent bound makes the shifted exponent nonnegative, so that quantization only appends zeros. Canonical source coefficients have exponent zero. Clear the sign of zero.

**Correction from independent review:** an integral-value magnitude check alone does not bound zero's exponent. `Decimal("0E+1000")` is numerically zero but scaling it can signal Clamped in a context with Emax=999. Therefore coefficient ingress must check representation bounds even for zero, then rebind every admitted zero to `Decimal("0")` before the first context arithmetic operation. For the private closed kernel, require finite Decimal, nonnegative integer exponent no greater than 249, no more than 250 stored coefficient digits, and the narrower role-specific magnitude bound below. A large-exponent zero fails typed shape validation; ordinary bounded zero encodings canonicalize exactly. Denominator zero remains invalid after canonicalization. Context-generated bounded zero exponents are normalized at coefficient/serialization boundaries; no arbitrary-exponent zero is admitted on the strength of magnitude alone.

Retain exact coefficients in a bounded private `exact_state`, using role-validated integral decimal strings with at most 250 digits, decoded directly to Decimal. Canonical zero serializes as `"0"`; no sign/exponent variants. Private coefficient storage must not coerce these values through NUMERIC(38,18) or reconstruct them from rounded public weights. Public and normalized financial fields remain bounded Q18 values with typed currency/quality. This creates no generic coefficient/formula API and does not change licensed-data retention requirements.

Use a fresh local Context specifying every field: precision 256, ROUND_HALF_EVEN, Emin=-999, Emax=999, capitals=1, clamp=0, initially empty flags and traps for Inexact, Rounded, InvalidOperation, DivisionByZero, Overflow, Underflow, Subnormal, Clamped and FloatOperation. Do not inherit mutable ambient/DefaultContext settings. A violated bound or signal yields the normal unpublished typed failure, with no lower-precision fallback, automatic precision escalation or global context mutation.

### 3. One complete traversal and exact path coefficients

For a terminal path with k fund edges, 0 <= k <= 4:

```text
M = coefficient18(reporting_amount)
a_j = coefficient18(source_weight_j)
padding[k] = (10^72, 10^54, 10^36, 10^18, 1)[k]
R = product(a_j) * padding[k]
N = M * R
relative path composition = R / 10^72
reporting path amount = N / 10^90
```

All numerical symbols are Decimal; the empty product is Decimal("1"). Ratios above remain separate exact numerator/denominator coefficients until the declared Q18 boundary. Keep R independent of M. If monetary valuation/FX is unavailable, do not fabricate M=0; an independently established authorized unit composition can remain computable.

Perform one stable traversal over the complete immutable snapshot, independent of requested dimension, normalization, selected pair/fund subset, Top, page or view. All roots, including explicit cash and zero-valued held funds, count toward the global 10,000 visited paths. If the initial root inventory cannot fit, reject the complete calculation rather than dropping cash or a favorable prefix. The separate input ceilings remain 10,000 positions, 32 currencies, 256 candidate constituent snapshots, 100,000 constituent rows across candidates, 100,000 combined identity/classification evidence rows and, separately, 100,000 selected uses, 32 MiB canonical input/result and 2 MiB public envelope; the traversal cap can be tighter than these capture ceilings.

Source sibling coefficients must sum to at most S exactly; the remainder S minus that sum is unresolved. Expansion replaces a parent. Reserve space for every pending branch before expansion; otherwise preserve the whole parent as unresolved. Detect cycles on the current ancestry path, not with a global visited-fund set that removes legitimate repeated paths. Missing/depth/cycle/path-bound branches retain their entire relative and monetary mass. No source/license validation or complete provider page-chain requirement is relaxed.

Assert both invariants before rounding: every expanded node's child R equals parent R, and its child N equals parent N when money is available. A root fund's known entity + explicit cash + unresolved relative coefficients equal 10^72, even at M=0. Whole-portfolio known + unresolved + explicit cash money equals its complete declared reporting basis, with any separately recorded valuation reconciliation supported by retained evidence. Monetary conservation at zero is insufficient to prove unit conservation.

Existing reporting-currency money and saved FX provenance remain authoritative. Listing currency does not cause a second conversion; ADR ratios do not multiply an already valued position again. Do not add quantities of unlike securities or infer economic currency from trading currency.

### 4. Closed formulas and denominators

Let D be the complete portfolio reporting-value numerator at denominator 10^90. D must derive from the complete root basis and reconcile with terminal partitions. Nonpositive or unavailable D makes portfolio ratios unavailable. K is the known noncash numerator for the requested classification dimension; K=0 makes normalized comparison unavailable. Keep absolute cash, unknown/discarded mass and the denominator visible in normalized views.

| Metric | Exact numerator | Denominator/rule |
|---|---|---|
| Total/root/path/direct/indirect/effective money | Corresponding sum of N | 10^90 |
| Absolute entity/classification/cash/unresolved/covered weight | Corresponding sum of N | D |
| Explicit known-normalized comparison | Selected known noncash numerator | That dimension's K |
| Pairwise known overlap | Sum over entities of min(R_a,e, R_b,e), after per-representative entity consolidation | 10^72 |
| Portfolio duplicated exposure | Sum_e(sum_original_roots N_root,e - max_original_roots N_root,e) | D |
| Company top-N | Sum of the largest consolidated N_e, exact descending order and stable entity-key ties | D |
| Company HHI | H = sum_e(N_e * N_e), consolidated before squaring | D * D |

Company concentration excludes cash from numerators without renormalizing D. Classification dimensions independently partition the same mass; do not sum their totals together. Overlapping quality indicators are not economic mass. Keep each original position as a duplication source; consolidate its paths/listings per entity before the cross-source maximum. No variance, higher power, variable-expression formula or new alert feature is covered by this exception.

### 5. Precision proof

The proof uses the complete root/terminal count bound, integral coefficients, nonnegative sums and the closed formulas. For a nonzero integral coefficient with nonnegative exponent, magnitude below 10^b implies at most b coefficient digits. Equality to 10^b needs b+1 digits. Zero is bounded and canonicalized explicitly as above.

| Value or operation | Bound | Maximum decimal digits |
|---|---:|---:|
| M | <10^38 | 38 |
| a_j | <=10^18 | 19 |
| R | <=10^72 | 73 |
| One path N | <10^110 | 110 |
| Sum of root M, at most 10,000 total roots | <10^42 | 42 |
| D, economic bucket, K, top-N or duplication numerator | <10^114 | 114 |
| Ordinary numerator scaled by S | <10^132 | 132 |
| Consolidated entity square | <10^228 | 228 |
| Loose sum H of at most 10,000 entity squares | <10^232 | 232 |
| H*S | <10^250 | 250 |
| D*D | <10^228 | 228 |
| Conserving fund entity coefficient or pair overlap numerator | <=10^72 | 73 |
| Loose sum of 10,000 relative coefficients before conservation | <=10^76 | 77 |
| Twice a q18 remainder | <2*10^228 <10^229 | 229 |
| Sum of 10,000 published Q18 integer coefficients | <10^42 | 42 |
| Difference of two such displayed sums | magnitude <2*10^42 <10^43 | 43 |

Even summing 100,000 invalid maximum source-weight coefficients before rejecting an oversum is at most 10^23 (24 digits). Nonnegative partial sums stay inside their whole-sum bounds. Conservation/residual subtractions remain bounded. At most 10,000 terminal paths imply at most 10,000 consolidated company entities; dimensions do not multiply the HHI inventory.

For conserving inputs H <= D squared gives the tighter H*S <10^246. The loose 250-digit envelope deliberately remains safe before the final conservation assertion; it does not authorize HHI >1 or a publishable total >=10^20. Precision 256 covers the largest coefficient with six spare digits; explicit exponent bounds lie comfortably within [-999,999]. This proof does not apply to arbitrary Decimal expressions or additional formulas.

### 6. One exact divmod HALF_EVEN boundary and overflow

For q18(N,B), first validate/canonicalize the bounded integral Decimal coefficients: abs(N)<10^232 and 0<B<10^228. Under the explicit context:

```text
A = abs(N) * S
q, r = Decimal context.divmod(A, B)
assert A == q*B + r and 0 <= r < B
increment q exactly when 2*r > B, or when 2*r == B and q remainder Decimal("2") == Decimal("1")
require q < 10^38 AFTER the increment
apply the original numerator sign, canonicalizing zero positive
scaleb the signed integer coefficient by Decimal("-18")
require output exponent -18 and no arithmetic signals
```

All arithmetic in this procedure is Decimal. No rounded division approximates the midpoint. Nonnegative divmod operands provide an integral quotient and nonnegative remainder. A<10^250, q<=A, q*B<=A and reconstruction stays <=A. Doubling r requires at most 229 digits; the parity operation's quotient is bounded by A. For B=1 there is no remainder/increment; for integral B>=2, q<=A/2, so the increment cannot exceed the envelope. Decimal's finite-precision quotient guard is therefore satisfied.

The post-increment test is essential. NUMERIC(38,18)'s maximum magnitude is 10^20-10^-18. With L=10^38, the exact amount `(2L-1)/(2S) = 10^20 - 0.5*10^-18` lies at a tie whose lower coefficient L-1 is odd, so HALF_EVEN produces L and must reject. A just-below-tie value may round to L-1 and pass; apply the same rule for negative values. Every published financial field and the complete-root total must fit before publication. Individually valid roots do not establish that their sum fits. Private proof stress totals are not publishable financial totals.

### 7. Representative fund composition and lower-bound meaning

For each canonical fund instrument held as an original top-level position, select the lowest canonical held position root key before considering monetary size, source quality, traversal success or requested outputs. Include zero-valued positions. Input iteration order, generated run IDs, ticker, another share class sharing an economic entity and nested occurrences do not substitute for the canonical root key of that exact fund instrument.

Use only the chosen occurrence's unit-relative coefficients retained during the existing global traversal. Do not retraverse, reorder roots to favor overlap, choose a later better-covered occurrence, union in extra paths from another occurrence or add a per-fund/unit traversal budget. If the representative is truncated while another occurrence is complete, that limitation remains visible. Never multiply the representative vector into other positions to backfill monetary exposure, and never collapse positions for duplication.

Pin the representative policy/version and `composition_root_key`, exact fund instrument, selected paths, source/mapping evidence, unit cash/unresolved mass, dates and quality to the immutable run. A wholly unexpanded root retains unit unresolved=1 even when its monetary unresolved amount is zero. Per-fund/pair coverage is measured on this unit composition; portfolio monetary coverage cannot replace it. Retain per-fund compositions and derive bounded requested pairs from them, without materializing an all-held-fund Cartesian array or selecting sources again.

| Situation | Required interpretation |
|---|---|
| Two valid reconciled unit compositions with complete supported entity/cash coverage | Exact overlap for the pinned source model, with independent source freshness/confidence disclosures |
| Some branches unresolved, bounded, cyclic or missing, but valid authorized unit bases and retained known buckets exist | Compute O_known and return a partial known-overlap lower bound with each side's unresolved mass |
| Empty known intersection, including an entirely unresolved representative with a legitimate unit basis | Zero known-overlap lower bound; actual overlap remains unknown. This is not proof of disjoint funds or an invented successful source |
| Zero monetary fund/portfolio value, or unavailable reporting FX alone | Unit-relative overlap remains computable if its independent basis/evidence is valid; monetary ratios keep their own gates |
| Pair/basis cannot be established, required retained state cannot be decoded/replayed, or validation fails | Typed unavailable/unsupported/failure as applicable; no fabricated numeric value |
| Unauthorized/nonheld pair, denied display, revoked license or forbidden expired payload | Preserve rejection/access/replay failure semantics before cache/cursor/304; do not replace them with successful zero/partial data |

A provider source may be unavailable while a legitimate canonical composition records its entire unit as unresolved. These are separate facts. Conversely, do not invent a canonical unit basis when its required authorization/state cannot be established.

Nonnegative unresolved entity mass can only increase known entity coefficients in an admissible completion. Min and sum are monotone, proving the unrounded O_known is a lower bound for completions of the pinned source model. This is not a guarantee about current real holdings when evidence is stale or inferred. Q18 can round a lower bound upward by up to Q/2: the displayed number is the declared rounded approximation to the bound, not an exact inequality certificate. Preserve the exact coefficients for comparisons.

### 8. Exact thresholds, quality and display residuals

For a registered threshold theta in [0,1], T=coefficient18(theta). Compare N*S with T*B using the immutable policy's strict > or inclusive >= operator. Ordinary products are below 10^132; HHI's left product is below 10^250 and right below 10^246; conserving pair products are at most 10^90. Configuration identity, configured/unconfigured state and top1/top5/HHI comparison operators are retained inputs. No P2-07 alert implementation is introduced.

A partial lower bound can establish a breach only through the exact comparison, with bound/quality disclosed. Otherwise the threshold conclusion is unavailable, not “not breached.” This does not make a computable overlap lower-bound value unavailable. A value displayed as 0.5 may still be exactly below 0.5; a positive unknown/common amount displayed as zero remains positive for coverage and proof decisions.

Require exact coefficient conservation before computing separate display residuals: authoritative Q18 total minus independently rounded amounts; one minus rounded absolute partition weights; rounded parent minus rounded children; and rounded effective minus the sum of rounded direct and rounded indirect. Residuals remain labeled signed values, never cash/unresolved backfill or redistributed balancing entries. For n children and an exact Q18 total, abs(residual)<=n*Q/2; with a separately rounded parent, <=(n+1)*Q/2. Compare twice the absolute residual coefficient against the Decimal child count (or count+Decimal("1")); validate the persisted residual field bound. Retain a positive-below-quantum indication, reasons and affected paths for exact positive unresolved mass rounded to zero.

## Consequences and rejected alternatives

This decision makes this bounded X-ray algebra exact through its single output boundary, independent of ambient context and execution duration. It requires a small private exact-state codec, strict construction/boundary validation, method identity changes and independently checked conservation. Keeping one representative may intentionally yield less pair coverage than another occurrence, but preserves fixed traversal budgets and query-independent semantics.

Reject precision-80/160 aggregation without a sufficient proof; private Python-int/Fraction production coefficients; rounded display values as ranking/conservation/threshold inputs; all-roots/best-root overlap composition; retraversal outside the shared budget; cash substitution/renormalization of unknown mass; and successful numeric fallbacks after permission or replay denial. No global licensed-data cache or owner policy override is authorized.

## Genuine invariants and later verification obligations

These are future implementation requirements, not tests executed by this draft.

1. Independently reconstruct coefficients and graph partitions from synthetic source inputs with a Fraction/integer test oracle. Check exact node/whole-portfolio monetary conservation and independent unit conservation, nonnegativity, role bounds and all final NUMERIC fields. Compare the raw retained coefficients and Q18 outputs, not merely production-computed sums against each other.
2. Cover the precision-80 counterexample; positive/negative exact ties with odd/even quotients; values immediately either side of a tie; recurring ratios; canonical positive zero; role maxima; huge-exponent zero rejected before arithmetic; equivalent permitted bounded zero/trailing-zero encodings; carry-induced overflow at both signs; and unsupported scale/nonfinite/negative/oversummed inputs. Exercise every explicit trap and outer-context restoration on success and failure.
3. Use hostile ambient and mutable DefaultContext settings through the complete entry point, source-coefficient construction, aggregation, q18, thresholds and exception exits. Enforce maximum source/traversal/byte budgets before expensive materialization. The conservative maximum-root arithmetic stress must be rejected as a publishable total, even when its internal operations are exact.
4. Preserve the reference fixture A=.56/B=.39/unknown=.05, overlap=.50, duplication=.41, top1=.56, top2=.95 and HHI=.4657. Consolidate repeated entity paths before squaring/min/max; preserve distinct original monetary sources and do not reapply receipt/FX conversions.
5. Select the lowest held root even if it is zero-valued or less complete than a later occurrence. Test shared subtrees, independent diamond paths, true ancestry cycles, depth four/five, global capacity and initial-root overflow. Every pending branch and each representative unit remains represented; no best-root switch, path union, monetary backfill or hidden second traversal occurs.
6. Distinguish supported disjoint exact zero; empty-intersection zero lower bound with unresolved mass; sub-Q18 positive common/unknown mass; zero monetary basis with valid pair composition; unknown/missing FX; and unestablishable or unauthorized bases. Do not turn an unavailable threshold conclusion into a null computable overlap bound or vice versa.
7. Check exact thresholds at 0/1, equality, just-below/above limits and rounded-equal displays; both comparison operators; partial proved breach, partial inconclusive and unconfigured states. Dimension-specific K=0 is unavailable; known-only presentation never changes absolute company HHI/top-N, cash or unknown mass. Check residual inequalities independently without distributing the residual.
8. For the same immutable run and pinned policies, requesting A/B alone or with C, changing Top/page/view/dimension/normalization and repeated authorized reads preserve representative keys, pair totals, coverage and selected evidence. A changed actual snapshot/root inventory may legitimately choose another representative. Equivalent input permutations preserve economic values and root selection under stable canonical ordering; equal full hashes are required only where the canonical input identity/provenance is actually the same. Differently paginated envelopes need not have identical bytes.
9. Verify same-run service/API/web/MCP/report canonical value and provenance parity, exact coefficient decode/replay and method/policy digest binding. Generated run IDs, calculated_at and pagination envelopes are not financial arithmetic inputs. Preserve method/version distinctions across historical results.
10. Exercise owner/nonheld-ID rejection, source mapping conflicts, effective/first-knowledge cutoffs, complete page-chain validation, stale/inferred quality and revoked/expired licenses before decode/replay/cache/cursor/304 reuse. Numeric exactness never upgrades evidence or legal eligibility. No source revocation or source-date change is claimed to leave availability invariant.

## Typed retained roles and canonical identity

The proof envelope is not a generic coefficient admission rule. Retained fields
use closed role validators: root M <10^38; source/threshold coefficient <=10^18;
relative path/fund/entity/pair coefficient <=10^72; terminal N <10^110; complete
root-M sum <10^42; portfolio/bucket/entity/K/top-N/duplication coefficient <10^114;
entity square and D squared <10^228; H <10^232 with H<=D squared for a conserving
complete basis; signed display residual magnitude <10^43. Economic coefficients
are nonnegative. Zero D/K is a retained state, not a division denominator. Missing
money has no coefficient. The loose source sum, relative sum and scaled numerator
bounds in the proof are temporary bounds, not permissions to retain invalid mass.

`PositionRoot` refers to the real `snapshot_positions.id` and exact instrument/
listing; `CashRoot` refers to `snapshot_cash.id` and original currency. Use tagged
canonical lowercase UUID keys, with lexical position UUID order for the same fund's
representative. The traversal policy `xray_position_then_cash_uuid_v1` orders position roots before
cash roots (explicit kind rank 0 then 1), then lowercase canonical real row UUIDs
lexically within each kind. Tagged keys are `position:<uuid>` and `cash:<uuid>`;
ASCII tag order, generated replacement IDs and query iteration order are forbidden.

Use named `XrayMoneyMetric` and `XrayRatioMetric` states with typed value/null,
closed availability/reason, quality and dependencies, and exact/lower-bound
semantics independent of freshness. Reuse `Money`, `CurrencyCode`, UTC instants,
UUID, `QualityState` and `ValueOrigin`. Pinned quality-evaluation time belongs to
input policy, not execution time. Paths own their R/N; aggregate exact state is
keyed to the semantic rows and verified against paths, not an independently
editable duplicate path store. Exact coefficients never use the ordinary Q18
`exact_decimal`/`decimal_string` boundary or ordinary Money arithmetic internally.

`content_digest` is derived SHA-256 of the canonical semantic result bytes and
is excluded from the bytes it hashes. Include exact state, input digest, versions,
source cutoff and every material source decision; exclude generated result/run
IDs, calculation time, current access and transport envelopes. Fixed private
codecs reject unknown/duplicate fields, invalid union states and role/shape/bound
violations. Current authorization precedes decoding; codec validity grants no access.

## Bounded projections and licensed-copy lifecycle

The canonical run retains fund compositions, not a complete pair Cartesian array.
At most 32 selected funds produce 496 pairs per request; discovery may contain more
held funds. Pair/common projections use retained compositions only. Every durable
pair/common payload is owned or referenced by an active collection binding and
charged to existing shared owner limits: 64 active collections and 250,000 members.
A common-entity collection also owns a bounded reference to its pair summary.
A pair header cannot accumulate uncharged arbitrary per-run bindings. Empty/first
requests reserve capacity and exact membership reuse preserves original TTL.
MCP Top can be transient with no permanent cache. Expiry removes unreferenced
projection payloads; deterministic identities and values can be regenerated from
retained canonical composition without retraversal. No lifetime 496-pair cap, new
economic fund-count restriction, all-held Cartesian cache or quota reset is implied.

Source expiry/revocation denies access immediately, including active cursors and
304. Physical cleanup inventories every canonical input/result/exact-state copy,
normalized/evidence/path row and pair/common/binding payload. Share the existing
100-capture and 100-run invocation budgets across families; additionally pin and
charge bounded physical rows and payload bytes visited/removed. Use indexed bounded
batches, never an unbounded cascading delete. Keep indexed pending work and the
source pending until forbidden copies are physically gone; retain only legally
permitted tombstones/digests/audit. Collection TTL never extends source retention.
The following reviewed limits are part of the policy and must precede dependent
implementation. They are fixed resource bounds, not measured throughput claims.

### Operational bounds

Each existing source-expiry invocation shares separate ceilings of 4,096 physical
rows inspected, 4,096 physical rows removed, 64 MiB logical copied-payload bytes
inspected and 64 MiB removed across all source families and dependent copies.
Keep the existing 100-capture and 100-run ceilings. A cleared payload counts as
removed even when its permitted tombstone row remains. Include each canonical
input/result/exact-state copy, normalized financial/evidence/path payload and
pair/common/collection binding; repeated inspection consumes budget again.
Use indexed batches of at most 512 rows, reduced by remaining row and byte budgets.
Read bounded size metadata before loading payloads; never load a complete batch
and only then discover its byte cost. Do not reset counters per source or family.
A largest legal 32 MiB document can progress in a fresh invocation. Exhaustion
leaves indexed pending work and immediate access denial, with no premature
purge-complete marker or unbounded cascading delete.

A terminal path contains at most 256 identity decision IDs and 256 source reference
IDs, its at-most-four complete fund edges, and one scalar classification assignment
per projected dimension. These are closed categories, not an extensible map of
unbounded proof arrays. Reject a capture that cannot preserve its material proof;
never truncate proof references. A maximal legal singleton path must fit the 2 MiB
public envelope. Larger pages may return RESULT_TOO_LARGE; a smaller requested
page retains identical membership, run identity and reachability.

## Implementation and comparability boundary

This is an authority decision, not implementation or acceptance evidence. Saved
scratch scalar-oracle observations do not fulfill the graph, codec, persistence,
license, API/MCP, restart or output-state obligations above. No numerical workload
is claimed to have been executed for this authority synchronization. Method 1.1.0
and its numeric/traversal identities apply to new X-ray results only; historical
methods, primitive inventories and previously accepted immutable results remain
at their actual versions. Other Phase 2 methods remain 1.0.0 and release 0.2.0 is
unchanged. P2-06 owns reports, P2-07 owns alerts, P2-08 owns intelligence-data-quality
and actual company-effective-weight enrichment; company drift additionally needs
an explicitly pinned entity-target basis. Phase 3 remains not_started.
