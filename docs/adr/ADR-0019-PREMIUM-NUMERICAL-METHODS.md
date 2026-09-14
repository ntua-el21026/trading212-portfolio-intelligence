# ADR-0019 — Finite-Precision Risk and Reproducible Projections

**Status:** Accepted implementation design; verification pending

**Date:** 2026-09-14

**Authority:** Owner's Complete Phase 3 assignment and additive v1.0 freeze

## Numerical boundary

Register `premium_decimal96_q18_v1` for new risk, stress and projection methods
only. Use a fresh Decimal context with precision 96, HALF_EVEN, Emin=-999,
Emax=999, clamp=0 and explicit InvalidOperation, DivisionByZero, Overflow,
Underflow and FloatOperation traps. Inexact/Rounded are permitted for approximate
statistics, never claimed to prove mathematical exactness. Restore the caller's
context on every exit. Existing profiles remain unchanged.

Validate finite bounded Decimal inputs before arithmetic; no production float
conversion. Persist/output once through the existing NUMERIC(38,18) boundary,
reject carry/overflow and canonicalize zero. Keep intermediate values in this
profile. Disclose signed output residuals; do not redistribute them. Internal
relative numerical tolerance is `1e-60 * max(1, scale)`; public reconciliation
allows only the declared Q18 rounding envelope plus that computational tolerance.
A failed bound, convergence or numerical condition produces typed unavailable/
failed output, never a substituted value. Version any algorithm or tolerance change.

## Risk estimation and matrix algebra

Use canonical total-return evidence, explicit calendar/currency/FX and cutoffs.
Portfolio observed TWR excludes external flows using the existing historical
accounting. Asset returns cannot be inferred from changes in holding values when
quantities change. Simple return is end/start-1; log return is ln(1+simple), which
requires simple>-1. Missing tuples remain missing; no zero/forward filling.
Observed portfolio risk and current-weight modeled asset risk are distinct.

Compute means then centered sample covariance with divisor n-1; public estimates
require at least 20 aligned observations. Annualization factors are 252 for the
pinned daily session calendar and 12 for monthly intervals. Volatility multiplies
period standard deviation by sqrt(A). Downside deviation is sqrt of the mean
squared negative deviations below the declared periodic minimum acceptable return,
using all n observations, then sqrt(A). Rolling windows apply the same minimum
and alignment rules. Drawdown reuses canonical flow-neutral TWR wealth.

For benchmark variance>0, beta=cov(portfolio,benchmark)/var(benchmark).
Alpha is A times the mean periodic excess portfolio return minus beta times
mean periodic excess benchmark return. The annual risk-free assumption is explicit;
convert to periodic simple or log basis consistently. Missing/constant benchmark
makes beta/alpha unavailable. Zero-variance correlations are unavailable, including
the corresponding diagonal. Zero observed volatility itself is a valid zero.

Check symmetry and PSD with a stable ordered semidefinite Cholesky decomposition.
A zero pivot requires a zero residual column within the numerical tolerance;
negative pivots outside that tolerance reject the matrix. Numerical-zero
classification is disclosed and not a claim of positive definiteness. Singular
PSD matrices remain usable for w' Sigma w; no inverse is needed. Optional
`diagonal_shrinkage_v1` is explicit: (1-lambda)Sigma+lambda*diag(Sigma), with lambda
pinned in the request. Default lambda=0; never silently repair a matrix.

For portfolio sigma>0, marginal risk is Sigma*w/sigma and component risk is
w_i*marginal_i. Reconcile their sum to sigma before Q18 and disclose the rounded
residual. Diversification is weighted standalone volatility / portfolio volatility.
Zero denominator is unavailable. Complete portfolio modeled risk requires complete
material weights/series; never renormalize uncovered exposure into known assets.
Concentration aggregates economic identity before squaring; preserve X-ray's
known lower bounds, direct/indirect partition and unresolved mass.

## Loss quantiles and expected shortfall

Positive loss means a decline; negative VaR/ES may represent a gain and is not
clamped. Confidence is one of .90, .95 or .99. Daily horizons are 1..20 sessions,
monthly horizons 1..12 intervals. Historical h-period losses equal one minus the
product of h consecutive simple gross returns. Use all eligible overlapping
windows and disclose their dependence. Sort losses ascending; VaR is the nearest
rank ceil(c*n). ES averages exactly the worst (1-c)*n empirical mass, including a
fractional boundary observation. Require tail mass at least five. Do not apply
square-root scaling to historical losses or silently shrink the horizon.

The parametric model is Gaussian log returns and lognormal terminal wealth,
explicitly separate from historical tail estimates. Let m=h*mean(log returns),
s=sqrt(h)*sd(log returns), z=Phi_inverse(c). Then:

- VaR = 1-exp(m-s*z).
- ES = 1-exp(m+s*s/2)*Phi(-z-s)/(1-c).
- For s=0 both equal 1-exp(m), without division by zero.

The supported parametric domain requires abs(period log mean)<=1 and period
log standard deviation<=1, and all CDF arguments within [-8,8]. Other valid
historical data remains available with this model explicitly unsupported.
Do not use an unstable overflow/underflow product as a tail estimate.

Implement Phi using the Decimal error-function power series with recursive terms,
maximum 512 terms and absolute term threshold 1e-86, with a retained 100-digit pi
constant. Compute inverse Phi by 256 bisections on [0,4] for the three supported
confidences. The reviewed domain and precision allow a conservative absolute CDF
error target 1e-70; test it independently rather than inferring it from the type.
The final Q18 boundary remains separate from numerical and sampling uncertainty.

## Simulation family and random identity

Use monthly correlated Gaussian log increments. Assumptions explicitly specify
annual mean log return and annual log volatility; historical CAGR is never an
implicit expected return. Increment is mu/12 + sigma/sqrt(12) times the correlated
standard-normal innovation. Canonical asset ordering and the assumption version
are pinned. Correlation uses the same PSD policy, with diagonal one and entries
in [-1,1]. Zero-volatility assets have deterministic increments.

`sha256_counter_polar_v1` gives each path/month/asset/attempt its own immutable
random identity. Hash the fixed domain `t212pi.projection.v1` followed by a NUL,
seed as four unsigned big-endian bytes, path index as four, month index as two,
asset ordinal as one, attempt ordinal as one. Split the 32-byte digest into two
128-bit unsigned integers. Convert each to a Decimal midpoint uniform
(k+0.5)/2^128, then u=2*uniform-1. For q=u*u+v*v in (0,1), return
u*sqrt(-2*ln(q)/q). Try at most 32 attempts; exhaustion is a typed deterministic
failure. Integer arithmetic is restricted to PRNG state/counters/encoding.

This finite generator approximates Gaussian sampling; it is not a guarantee of
true randomness or future returns. No Python random state, binary-float normal
transform, process seed, chunk position or worker identity influences the result.
Fixed absolute path indices reproduce across serial/chunked/restarted execution.
Sensitivity runs may explicitly reuse the same seed for common random numbers.

Cash-flow, fee/inflation/rebalancing timing, insolvency, quotas and publication
are part of the versioned projection contract, not implementation discretion.
Canonical output excludes operational job IDs/clocks and includes all financial
inputs, model/numeric version, seed, source identities and quality assumptions.
Timeout/cancellation cannot publish a partial set as a complete simulation.

## Independent verification and limits

Use analytically justified rational covariance/beta/concentration fixtures and
separately implemented higher-precision reference calculations. Verify covariance
symmetry/PSD, perfect correlation/anticorrelation, zero variance, singularity,
component conservation, hostile ambient contexts and Q18 ties/overflow.
Cross-check normal quantiles with an independent implementation under its declared
accuracy, plus independent high-precision analytical risk references.

Projection zero-volatility paths must match deterministic cash-flow references.
Check repeated/chunked/restarted financial identity independently of job metadata;
separate those assertions from statistical moment/tail tolerances. Goal confidence
intervals measure Monte Carlo sampling uncertainty under the assumed model, not
uncertainty about whether that model describes markets. Historical estimates,
shocks and probabilistic projections never share an unlabeled result type.
