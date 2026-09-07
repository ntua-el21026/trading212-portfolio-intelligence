# ADR-0011: Deterministic Contribution Optimizer

**Status:** Accepted

**Date:** 2026-09-07

**Decision authority:** Current owner's Phase 2 design-closure assignment

## Context

Manual contribution planning must respect immutable hierarchical targets,
observed holdings/cash, minimums, value increments, eligibility, reserve,
post-weight bounds, group funding constraints, and a maximum funded-line count.
It must preserve exact contribution conservation and return the same canonical
plan for identical inputs. Discrete increments and interacting group constraints
make a continuous solution insufficient. Bounded search cannot promise a global
optimum or prove infeasibility merely because it runs out of work.

## Decision

Adopt `contribution_weighted_drift_v1` version `1.0.0` as fully specified in
[Phase 2 methods, section 3](../analytics/PHASE_2_METHODS.md#3-deterministic-contribution-optimizer).
Pin the authorized account, immutable target/valuation/mapping/FX references,
source cutoff, reporting currency, quantum, effective constraints, quality
policy, and method version. Contribution currency equals reporting currency;
any upstream explicit conversion retains its sourced FX before request creation.

Let `D=V+C`, including current cash and unclassified known value. Recommend only
nonnegative holding amounts and residual cash, with exact
`C=sum(holding allocations)+residual cash`. Existing cash is not spent. The
global objective is the scale-18 quantized weighted squared post-contribution
drift over the full non-overlapping leaf/cash/unclassified universe. Compare
equal scores by residual cash and then the allocation vector in ascending
stable canonical node-key order. Hierarchical mode lexicographically prioritizes
successive tree frontiers before leaf drift; restricted mode fixes other
holding allocations to zero without shrinking the portfolio denominator.
Explicit cash-only mode validates its singleton domain against every constraint.

Use precision-80 Decimal with `ROUND_HALF_EVEN`; reuse `NUMERIC(38,18)` and
reject financial floats, excess input scale, and more than 20 integer digits.
Exact products of at most eight scale-18 sibling weights use a temporary
precision-160 context. Reported target weights have a disclosed aggregate
rounding residual; never silently renormalize the derived leaf weights.
Reported objective precision is scale 18 with an explicit half-quantum rounding
bound, not an unpersistable high-precision score or false zero residual.

The solver builds a continuous box-relaxation guide using exactly 128 Decimal
bisections, constructs and independently checks a rounded seed, and attempts
at most 10,000 deterministic residual-improvement moves. It then explores the
finite holding domains lazily in stable order, with a fixed 100,000 attempted
assignment limit and only proven feasibility pruning. Every retained/final
plan passes an independent hard-constraint validator. This is a bounded
deterministic procedure; the complete algorithm, domains, tie ordering, and
reference cases are normative in the methods document.

`optimal` requires exhaustive finite-domain search, including directly checked
singleton domains, for the requested versioned objective/mode. A feasible incumbent
at the limit is `feasible_nonoptimal` with reason, node count, and valid bound;
the default bound is the nonnegative objective's zero lower bound. Exhaustion
without an incumbent is `unavailable/search_budget_exhausted`, not `infeasible`.
Infeasible requires a constraint proof or exhausted finite domain. Missing
material inputs are unavailable; internal validation/arithmetic errors fail
without returning recommendations. Every final result is immutable, and a
recalculation appends a revision with a new input/result digest.

## Consequences

Plans are reproducible, inspectable manual proposals, with no trade prediction,
order translation, or broker dispatch. Strong feasibility is independent of
search quality. Hard cases can return a valid but nonoptimal plan, or an honest
bounded-search unavailable result. Any larger bounds or solver replacement
requires a new method version; wall-clock limits cannot silently change outputs.
Precision and target rules remain compatible with the established financial
boundary, while exact hierarchy products need a narrowly scoped larger context.

API, web, reports, alerts, and MCP read the same canonical service output.
Tests must cover hand-calculated minima/increments/max-weight/reserve cases,
all modes, target normalization, zero values, mapping/FX failures, conflict
proofs, bounded-search outcomes, stable ties, byte-equivalent canonical replay,
and exact conservation after every discrete operation. Acceptance evidence is
recorded separately from this accepted design.

## Rejected alternatives

- Binary-float optimization or client-side authoritative calculation: violates
  exact monetary boundaries and reproducible service parity.
- Rounded continuous output without independent validation: can violate funded
  minimums, group constraints, max weight, or contribution conservation.
- Claiming every greedy/bounded result optimal or every timeout infeasible:
  overstates what the computation proves.
- Unbounded enumeration or elapsed-time stopping: either unbounded resource use
  or machine-dependent canonical results.
- Automatically selling overweight holdings, spending existing cash, or
  relaxing exclusions: changes the authorized contribution-only problem.
