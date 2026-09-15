# Phase 3 Calculation Methods

**Status:** Accepted implementation design; executable validation pending

Methods risk_v1, stress_v1, projection_v1, goal_analysis_v1, research_summary_v1
and account_aggregation_v1 start at 1.0.0. [ADR-0019](../adr/ADR-0019-PREMIUM-NUMERICAL-METHODS.md)
defines premium_decimal96_q18_v1. Existing methods retain their numerical profiles.
Finite computation is not mathematical exactness or economic/model certainty.

## Risk input construction

Each interval pins session boundaries, calendar/version, reporting currency, source
IDs, knowledge cutoff, price/action basis and quality. Sort dates and asset IDs;
conflicting duplicate boundaries fail. Daily intervals join consecutive sessions.
Monthly intervals join successive last sessions of calendar months and require every
intervening daily boundary. Missing sessions break intervals: no bridging gaps or
forward-fill. Holidays are distinct from missing expected observations.

Observed portfolio simple returns reuse Phase 2 canonical TWR interval returns and
exact external-flow anchors/action/reconciliation policy. Never difference account
value or subtract aggregate deposits without timing evidence. Log returns=ln(1+r).
r=-1 permits simple loss statistics but makes log metrics unavailable. Nonpositive
wealth bases remain unavailable. Drawdown reuses canonical TWR wealth/peak conventions.

Asset series use pinned canonical Phase 2 benchmark/market observations, never changing
position market values. Total-return observations already include their reinvestment
basis: do not add dividends/splits twice. Raw-price series require the canonical action
bridge, split factors and distribution evidence before being labeled total return.
Price-only may be displayed separately but cannot enter a total-return covariance
universe. Unknown adjustment semantics/incomplete actions makes total return unavailable.
Revision first-known time must be <=cutoff; backfilled data is not then-known evidence.

Convert each boundary with explicit sourced reporting FX under the existing selection
policy. Flat local price and FX .90 to .99 gives reporting return .10. Same-currency
identity is explicit, never a missing-FX fallback. Stale/estimated observations retain
quality and are excluded from observed risk estimates in v1. No winsorization;
nonfinite/impossible simple returns <-1 fail, |simple return|>1 is retained with an
outlier disclosure. Log values outside parametric bounds disable only that model.

Align a single complete-case intersection for each declared metric universe. Report
requested/usable/omitted intervals and reasons. Every matrix cell uses the same dates.
Portfolio-only, portfolio/benchmark and modeled-asset universes are separately labeled.
Minimum 20 valid observations per estimate/window. Horizon losses require consecutive
valid intervals and never compound across gaps.

## Risk estimates

Annualization A=252 daily or 12 monthly. Sample covariance uses n-1 centered products;
annual volatility=sqrt(A*variance). Rolling estimates repeat the trailing estimator;
early unavailable windows remain gaps. Downside=sqrt(A*sum(min(r-MAR,0)^2)/n).
Annual risk-free/MAR assumptions are >-1 and <=1. Periodic simple rate=(1+annual)^(1/A)-1;
periodic log rate=ln(1+annual)/A. Beta/alpha, PSD, correlation and Euler contributions
follow ADR-0019. Zero observed variance gives zero volatility; zero denominators make
beta/correlation/diversification/contributions unavailable, not fabricated zeros.

Current-weight modeled risk requires complete selected economic coverage and weights
summing one. Cash needs an explicit modeled return series; incomplete universes never
renormalize. Keep original and explicitly regularized covariance separate. Report
contribution sum and residual without distributing it to manufacture reconciliation.

Concentration reuses canonical X-ray terminal partitions: combine economic entities
across direct/indirect paths, exclude wrappers, preserve cash/unresolved mass.
HHI=sum(w_i^2) uses absolute total-portfolio weights. Unknown mass means known HHI is
a lower bound; 1/HHI is exact effective holdings only with complete coverage. Zero
HHI denominator is unavailable. No covered-only normalization.

Historical VaR/ES always use compounded simple horizon returns, including when log
statistics are selected. Disclose overlapping dependence, sample count, confidence,
horizon, positive-loss sign, nearest-rank quantile and fractional tail mass. Require
five expected tail observations. Parametric lognormal formulas and IID horizon policy
are in ADR-0019; no square-root scaling for historical VaR or maximum-loss guarantee.

## Deterministic stress

Start from canonical nonnegative X-ray terminal values. Preserve each root/entity/
classification/economic-currency/source and mass. Exclusions apply first and mean
explicitly unchanged. Winning price rule specificity: instrument > entity > sector >
region; equal-priority conflicts are invalid, never resolved by list order. A fully
classified unmatched row is explicitly unshocked. Missing classification which could
match a rule means uncovered, not zero effect.

Price/currency shocks in [-1,5]. FX shocks require evidenced economic currency;
listing currency is insufficient. Reporting-currency identity has zero FX shock.
Rate/factor effects require sourced sensitivities. Coefficients in [-100,100], shocks
in [-1,1], total first-order effect in [-1,5]; rate changes are absolute decimal rates.
Different evidenced factor effects sum. Reject duplicated equivalent FX/rate/price
exposure treatment and unsupported sensitivities remain uncovered.

first_order: post=pre*(1+price+factor+FX).
compounded: post=pre*(1+price+factor)*(1+FX).
Negative multipliers fail, never clip. Show price/factor/FX effects plus interaction
residual. Original value=covered+uncovered+excluded; post-pre=sum(effects)+interaction
within Q18 output tolerance. If material potentially shocked mass is unsupported,
full post-value is unavailable and covered totals are explicitly partial estimates.

Historical replay pins market window/cutoff independently of holding basis.
current_holdings reprices a current pinned terminal partition; historical_holdings
requires retained then-dated portfolio/constituents. Neither claims actually realized
owner performance. Reuse canonical total-return/FX changes; disclose unmapped/delisted
survivors and unresolved constituents. point_in_time rejects later-known revisions;
retrospective permits explicitly disclosed later retrieval without a then-known claim.
Comparison reads two retained runs and computes differences only for compatible
currency/dimensions/basis; otherwise preserve separate values and mismatch reasons.

[ADR-0025](../adr/ADR-0025-SCENARIO-EVIDENCE-AND-COVERAGE.md) fixes sensitivity
membership/units/economic-driver equivalence, tri-state selector priority and a
conservative money-coverage predicate. Any positive potentially shocked unsupported
amount blocks complete totals, except a separately proved unchanged treatment whose
every admissible channel is zero; unknown mapping diagnostics remain. The rate/factor
effect bound applies to their summed ratio, and each selected formula checks its
actual multiplier. Replay uses canonical market channels with mode/exclusions but
no simultaneous hypothetical shocks. Historical holdings and their own knowledge
cutoff remain separate from market knowledge. All complete source proof is bounded.

## Projections and goals

Use ADR-0019 correlated monthly lognormal model/stateless sampler. Sort assets by
canonical key before factorization/sampling. Expected annual mean log return is an
explicit modeled parameter, never an inferred CAGR. Initial basis is observed_snapshot
with authorized canonical converted value, or modeled_value with explicit Money.
Model weights allocate initial wealth. No simulated rebalance is a broker command.

At start of month m, add base*(1+growth)^floor((m-1)/12) unless paused; lump sums still
apply. Allocate contributions at target weights. Fund scheduled withdrawals pro-rata
to current nonnegative asset values. Record unpaid amounts; never create negative
wealth. Future contributions do not silently discharge recorded unpaid liabilities.
Any unpaid withdrawal makes the path's funding condition unsuccessful.

Apply asset exp(mu/12+sigma*z/sqrt(12)), then monthly retention (1-fee)^(1/12) and
optional modeled (1-tax_drag)^(1/12). Record fee/tax amounts. Rebalance at month end:
monthly, annual when m%12=0, or never. Preserve total wealth without implied transaction
costs beyond explicit fees. Real wealth=nominal/(1+inflation)^(m/12).

Retain requested path months only with cash conservation and unpaid/insolvency state.
Any numerical/public bound violation produces a typed failure, never truncated success.
Quantile nearest rank=ceil(p*n); p=0 selects minimum. Fixed percentiles .05,.25,.50,.75,.95.
Sort equal values by absolute path index. Terminal histogram <=20 equal-width bins,
last inclusive; equal terminals one bin. Counts integer, limits Decimal.

Goal success: terminal nominal/real value>=target AND no unpaid withdrawal.
Probability=successes/paths; shortfall=max(target-value,0), separately from unpaid
flows. Report mean/quantiles and objective without accepting a goal. Sampling interval
uses 95% Wilson score, z=1.9599639845400542355245944305205515279555500778695.
All/none success retain Wilson intervals; these describe sampling, not model uncertainty.

Sensitivity cases are baseline, one contribution delta and one annual mean-log-return
delta, with common seed/path indices. Validate all variants and charge all toward work
quota. Report each separately. Assert monotonicity only where the assumptions justify
it, not under arbitrary withdrawals/rebalancing/heterogeneous stochastic changes.

## Research and aggregation

Research ranking: descending absolute canonical effective exposure, unreviewed material
revision, descending publication time, stable entity/event IDs. Unknown exposure is
separate, never zero. Source facts, portfolio facts, owner revisions and optional
synthesis are distinct variants. Deduplicate provider/event identity and sanitized
semantic digest; correction appends revision. Material change means fact/citation
changes, not retrieval-time drift. Review acknowledges exact revision. Synthesis stays
disabled until configured, requires authorized retained citations and cannot mint finance.

Aggregate 1..8 distinct authorized account/snapshot pairs with disclosed valuation and
cutoff. Deduplicate ingestion by broker/account/external_record_id within an account;
equal holdings across accounts are distinct genuine assets. Group canonical economic
identities after sourced individual FX conversions. Missing FX preserves partial rows
and makes full total unavailable. Internal transfer needs a unique evidenced linked
counterparty/reference and opposite principal in the same currency between included
accounts; cross-currency transfers additionally need evidenced FX/fees. Equal date/value
alone is insufficient. Ambiguous/unmatched legs degrade aggregate flow/performance
coverage; valid current holdings totals remain independently available.
