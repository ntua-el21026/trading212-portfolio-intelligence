# Performance Accounting

**Status:** Accepted  
**Phase 1:** Core accounting and coverage-gated summary  
**Phase 2:** Full performance series, benchmark comparison, attribution

## 1. Objective

Separate capital contributed by the user from investment gain and provide reproducible return metrics only over periods with adequate data.

At a high level:

```text
Ending portfolio value
= beginning portfolio value
+ net external cash flows
+ investment result
```

The residual must be reported; it is not silently assigned to performance.

## 2. External versus internal flows

External flows change capital supplied to the portfolio:

- deposits/contributions;
- withdrawals;
- account-level transfers crossing the portfolio boundary when identifiable.

Internal flows do not count as contributions:

- security purchases/sales;
- dividends retained in the account;
- fees/taxes;
- FX conversion inside the account;
- cash-to-security reallocation.

Ambiguous activity is classified `unknown` and degrades relevant metrics.

## 3. Core accounting fields

Where coverage permits, snapshots expose:

- beginning value;
- ending value;
- gross deposits;
- gross withdrawals;
- net external contributions;
- dividends/income;
- fees and taxes;
- realized P/L;
- unrealized P/L;
- FX effect where independently supported;
- investment gain;
- reconciliation residual;
- coverage start/end and quality.

The identity used for a specific report is versioned and tested. Components that overlap in provider semantics are not double-counted.

## 4. Money-weighted return

XIRR solves for \(r\) such that:

\[
\sum_{i=0}^{n} \frac{C_i}{(1+r)^{(t_i-t_0)/365}} = 0
\]

under a declared investor/portfolio cash-flow sign convention, including the terminal portfolio value as the closing flow.

Requirements:

- irregular dates supported;
- root selection policy documented;
- non-convergence and multiple-root ambiguity reported;
- no annualization for invalid/too-short periods without explicit policy;
- external flows only;
- input cash flows and terminal value reproducibly linked;
- numerical tolerance and iteration bounds fixed/tested.

Phase 1 may expose MWR only when external-flow coverage begins no later than the period start and terminal valuation is reliable.

## 5. Time-weighted return

TWR geometrically links subperiod returns split by external cash flows:

\[
R_{TWR} = \prod_{k=1}^{m}(1+r_k)-1
\]

The exact timing convention depends on available valuations:

- preferred: valuation immediately before/after material external flows;
- fallback: daily Modified Dietz/subperiod method only when explicitly labeled;
- missing valuations cause partial/unavailable status, not invented interpolation.

Phase 1 implements a conservative coverage-gated method based on recorded snapshots. Phase 2 expands historical price/valuation support.

## 6. Modified Dietz

For bounded reporting periods where intra-period flows exist and full subperiod valuation is unavailable:

\[
R_{MD} = \frac{V_E - V_B - \sum_i C_i}{V_B + \sum_i w_i C_i}
\]

where \(w_i\) reflects the fraction of the period remaining after flow \(i\). The day-count and start/end-of-day timing convention are explicit.

It is not labeled TWR and is not used when the denominator is invalid or economically unstable.

## 7. Annualization

For a cumulative return \(R\) over \(d\) days:

\[
R_{ann} = (1+R)^{365/d}-1
\]

only when:

- \(1+R > 0\);
- period meets configured minimum duration;
- metric type permits annualization;
- data coverage/quality supports it.

Reports always show period dates and cumulative return alongside annualized values.

## 8. Cost basis and P/L

Provider-reported cost basis/P&L is retained distinctly from internally reconstructed values.

Internal reconstruction requires an accepted lot/accounting policy and adequate transaction/corporate-action history. Until then:

- Phase 1 may calculate weighted average acquisition for supported straightforward buys/sells using documented rules;
- unsupported transfers/corporate actions make cost-basis coverage partial/unreconciled;
- realized P/L is unavailable rather than guessed when disposal basis is not trustworthy;
- currency conversion and fees/taxes are explicit components.

Any jurisdictional tax-basis calculation is outside scope; the application metric is investment accounting, not tax advice.

## 9. Reporting currency and FX

Two distinct effects may be reported:

- local/trading-currency asset return;
- reporting-currency return including FX.

FX attribution requires aligned rates and a documented decomposition. Without sufficient data, the total reporting-currency return may remain calculable while FX attribution is unavailable.

## 10. Benchmark comparison — Phase 2

Benchmark comparison requires:

- explicit benchmark/listing/total-return definition;
- aligned dates and reporting currency;
- dividend treatment compatibility;
- benchmark data source and timestamp;
- handling for user cash flows (typically TWR comparison);
- tracking/excess-return method;
- no comparison over unsupported gaps.

## 11. Attribution — Phase 2

Attribution must reconcile to portfolio return within a disclosed residual/tolerance. It may include:

- position/group contribution;
- income;
- fees/taxes;
- cash drag;
- FX effect;
- allocation/selection effects only when methodology and data support them.

An unexplained residual is displayed.

## 12. Phase 1 acceptance fixtures

At minimum:

1. No-flow single-position gain.
2. Deposit mid-period.
3. Withdrawal mid-period.
4. Dividend retained as cash.
5. Buy/sell internal cash exchange.
6. Fee and withholding.
7. Multi-currency position with explicit FX.
8. Missing FX.
9. Partial transaction history.
10. Zero/negative denominator and XIRR non-convergence.
11. Same economic activity delivered twice.
12. Reconciliation mismatch.

Each fixture includes expected decimals, period, method, quality state, and warnings.
