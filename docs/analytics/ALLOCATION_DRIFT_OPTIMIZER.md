# Allocation, Drift, and Contribution Optimization

**Status:** Accepted  
**Phase 1:** Direct observed allocation only  
**Phase 2:** Targets, drift, and optimizer

The accepted [Phase 2 methods](PHASE_2_METHODS.md) and
[optimizer ADR](../adr/ADR-0011-DETERMINISTIC-CONTRIBUTION-OPTIMIZER.md) select the
exact objective, bounded search and status rules for release 0.2.0. They refine
the general formulations below; alternative objectives are not release options.

## 1. Direct allocation

For portfolio value \(V > 0\), direct component weight is:

\[
w_i = \frac{V_i}{V}
\]

where components include positions and cash according to the selected view. Requirements:

- all components converted to the reporting currency at explicit rates;
- weights use unrounded authoritative values;
- displayed weights may not sum exactly because of formatting and show residual where material;
- negative cash/margin is not expected for supported Invest scope but must not be silently clamped;
- zero-value portfolio returns an explicit unavailable/empty allocation state, not division by zero;
- unmapped positions remain visible as `unclassified` rather than excluded.

## 2. Canonical target model — Phase 2

A target version is immutable after publication and contains:

- effective timestamp;
- hierarchy of groups/virtual Pies;
- target weights at each sibling level summing to exactly one after any explicit,
  bounded normalization under [ADR-0010](../adr/ADR-0010-IMMUTABLE-VIRTUAL-TARGETS.md);
- listing/instrument mapping;
- optional cash target;
- maximum/minimum weights;
- contribution eligibility/exclusions;
- minimum contribution/order amount and increment;
- priority coefficient;
- notes and strategy version.

Changing targets creates a new version, preserving history.

## 3. Drift metrics

The platform supports documented measures:

### Signed absolute drift

\[
d_i = w_i - w_i^*
\]

### Absolute percentage-point drift

\[
|d_i|
\]

### Relative drift

\[
r_i = \frac{w_i-w_i^*}{w_i^*}
\]

only when target weight is nonzero.

### Portfolio L1 drift

\[
D_1 = \frac{1}{2}\sum_i |w_i-w_i^*|
\]

The half factor represents minimum mass that would need reallocation in an unconstrained frictionless model.

### Weighted squared drift

\[
D_2 = \sum_i \alpha_i(w_i-w_i^*)^2
\]

used by the contribution optimizer when selected.

Metrics state hierarchy level, component universe, cash treatment, and target version.

## 4. Contribution-only optimization

Given current component values \(V_i\), contribution allocations \(x_i\), total current value \(V\), contribution \(C\), and targets \(w_i^*\):

\[
\min_{x} \sum_i \alpha_i\left(\frac{V_i+x_i}{V+C}-w_i^*\right)^2
\]

subject to:

\[
x_i \ge 0,\quad \sum_i x_i + x_{cash}=C
\]

plus configured eligibility, minimum/increment, cash, and maximum-weight constraints.

Alternative documented objectives may minimize L1 drift or lexicographically prioritize underweights. The selected objective and solver version are part of the result.

## 5. Hierarchical planning

For nested Pies, modes include:

1. **Global optimization:** flatten eligible leaves while enforcing group constraints.
2. **Two-stage:** allocate contribution across top-level groups, then optimize within funded groups.
3. **Restricted scope:** optimize only one selected group/Pie.

The mode is explicit. Hierarchical targets must not be multiplied/flattened incorrectly; effective leaf target equals the product of normalized weights along its path where the model defines relative child targets.

## 6. Constraints

Supported Phase 2 constraints:

- no sales (mandatory default);
- contribution amount fixed, with unspent amounts retained as residual cash;
- preserve/add target cash reserve;
- component eligible/ineligible;
- minimum amount when funded;
- amount increment/rounding;
- maximum post-contribution weight;
- group minimum/maximum funding;
- maximum number of funded lines;
- priority/penalty coefficients;
- preferred listing policy without falsely equating listing currency to economic exposure.

Constraints are validated before solve and assigned stable IDs for explanation.

## 7. Discrete rounding

The continuous solution is not the final plan when amount increments/minimums apply.

The general continuous-relaxation approach is:

1. Solve continuous problem.
2. Generate feasible rounded candidate.
3. Allocate residual deterministically to the line(s) that improve the objective most while satisfying constraints.
4. Recalculate post-plan weights and drift using rounded amounts.
5. Return unallocated residual to cash when no feasible improvement exists.
6. Verify exact contribution conservation in monetary minor/increment units.

No floating-point rounding heuristics may violate conservation.
The accepted Phase 2 solver may use exact bounded enumeration or its documented
deterministic discrete search instead; every returned result still verifies all
hard constraints, recomputes the objective, and discloses residual cash and
whether global optimality was established.

## 8. Infeasibility

The optimizer returns:

- `optimal`;
- `feasible_nonoptimal` with solver bound/reason when applicable;
- `infeasible` with conflicting constraints;
- `unavailable` due to data quality/mapping;
- `failed` for internal error.

It does not silently drop constraints. It may offer a separately labeled relaxation analysis without altering the requested plan.

## 9. Result schema

A plan includes:

- plan ID and calculation/solver version;
- target version and portfolio snapshot;
- contribution/reporting currency;
- objective and constraints;
- current, target, and post-plan values/weights;
- recommended amount per group/holding;
- residual cash;
- pre/post drift metrics;
- binding constraints;
- excluded/unmapped components;
- feasibility/status;
- data quality, assumptions, and warnings;
- explicit statement that it is a manual plan and no trades were placed.

## 10. Safety

- The plan is never translated into broker order requests.
- No MCP/API route exposes execution.
- Output cannot include credential or hidden broker parameter.
- Stale/unreconciled valuations above configured severity block or visibly degrade optimization.
- Missing target mappings are not assigned zero target silently.

## 11. Tests

Property/reference tests cover:

- contribution conservation;
- nonnegative allocations;
- target normalization;
- deterministic output;
- no-sale invariant;
- maximum weight and cash reserve;
- minimum/increment rounding;
- infeasible combinations;
- zero portfolio and zero contribution;
- overweight components receiving zero in the unconstrained optimum where appropriate;
- hierarchical target flattening;
- post-rounding objective recomputation;
- mapping/FX/data-quality failures;
- parity across API, web, MCP, and report outputs.
