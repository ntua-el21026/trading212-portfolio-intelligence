# Risk, Stress Testing, and Projections

**Status:** Accepted Phase 3 design; not Phase 1 implementation scope

## 1. Principles

- Observed historical statistics, deterministic scenarios, and probabilistic projections are separate result types.
- All results are reproducible from versioned inputs and assumptions.
- Market history, benchmark definitions, FX treatment, frequency, missing-data policy, and estimation window are explicit.
- Risk metrics are descriptive estimates, not guarantees.
- The language model explains results but does not calculate or alter assumptions invisibly.

## 2. Risk metrics

Planned metrics include:

- annualized volatility and downside deviation;
- rolling return/volatility;
- current and maximum drawdown;
- beta/alpha where method and benchmark support them;
- covariance/correlation;
- historical/parametric VaR and Expected Shortfall with confidence/horizon/method;
- Herfindahl concentration and effective number of holdings;
- diversification ratio;
- marginal/component contribution to risk;
- exposure-based concentration after X-ray.

Return construction, resampling, annualization factors, stale prices, non-overlapping histories, and FX are specified per model.

## 3. Stress scenarios

### Deterministic shocks

A versioned scenario maps shocks to instruments, entities, sectors, regions, currencies, rates, or factors with precedence rules. Example:

```yaml
name: Technology and USD correction
shocks:
  us_technology: -0.35
  broad_us_equity: -0.18
  semiconductors: -0.45
  usd_vs_eur: -0.12
```

The engine reports exposure mapped/unmapped, first-order loss by component, interaction/override policy, reporting-currency effect, and quality.

### Historical replay

Reprices the current portfolio using an explicitly selected historical window and mapping. Survivorship, missing history, and current-versus-historical constituent assumptions are disclosed.

## 4. Risk contribution

For covariance matrix \(\Sigma\), weights \(w\), and portfolio volatility \(\sigma_p=\sqrt{w^T\Sigma w}\), marginal/component contribution may be calculated as:

\[
MRC_i=\frac{(\Sigma w)_i}{\sigma_p}, \qquad CRC_i=w_i MRC_i
\]

The implementation must reconcile component contributions to total volatility within tolerance and flag unstable/singular estimates.

## 5. Monte Carlo projections

A projection run stores:

- assumption-set version;
- start portfolio value/allocation;
- contribution schedule and growth;
- horizon/frequency;
- nominal return, volatility, correlation, inflation, FX, fees/taxes assumptions as applicable;
- distribution/model family;
- rebalance policy;
- random seed and simulation count;
- software/calculation version;
- percentile outputs and target probabilities.

No run uses historical CAGR as an undisclosed deterministic forecast.

## 6. Goal planning

Goals specify target amount, nominal/real basis, target date/horizon, currency, contribution schedule, withdrawals, probability objective, and assumption set. Results include probability, percentile paths, shortfall distribution, contribution sensitivity, and assumption sensitivity.

## 7. Data/quality gates

- minimum aligned history per metric;
- stale/missing price policy;
- minimum observation count;
- outlier/corporate-action handling;
- benchmark/FX source alignment;
- covariance regularization method;
- constituent/mapping coverage;
- quality and confidence warnings.

## 8. Tests

- independent reference calculations;
- covariance/risk-contribution conservation;
- constant/zero-volatility series;
- perfect positive/negative correlation;
- missing/non-overlapping histories;
- drawdown edge cases;
- VaR/ES ordering and confidence/horizon semantics;
- deterministic scenario precedence and residual exposure;
- seeded Monte Carlo reproducibility;
- contribution/inflation/withdrawal timing;
- monotonic sensitivity checks where mathematically expected;
- cross-interface parity and assumption disclosure.
