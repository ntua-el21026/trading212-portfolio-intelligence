# ADR-0027: Canonical projection paths and bounded representation

**Status:** Accepted implementation decision, 2026-09-15

**Authority:** The additive v1.0 freeze, Phase 3 projection/goal methods and
ADR-0019. This fixes representations before dependent implementation; it does not
claim executable validation, package acceptance or production readiness.

Implement the frozen projection_v1/goal_analysis_v1 methods with ADR-0019's unchanged
Decimal96 profile and counter/polar sampler. This decision fixes representations and
supported input conventions needed by the numerical kernel; capture authorization,
calendar mapping, durable storage and worker fencing remain separate implementation.

Require run allocation to agree exactly with the immutable assumption weights.
These weights allocate initial value and every contribution. Apply a contribution
sensitivity delta to the recurring base before annual growth and pauses. Apply the
mean-log-return sensitivity delta uniformly to every asset's annual mean log return.
Validate all three resulting variants before work and charge all their asset-month-path
products to the shared one-million ceiling. They share the original seed and absolute
path/asset/month identities; variant names never enter random counters.

Canonical asset order is ascending key, with the correlation axes permuted identically.
Paths/assets/attempts are zero-based; simulated months are one-based. Month 0 is initial
wealth and has no random draw, flow, fee or return. The polar sampler uses all required
independent coordinates, even one corresponding to a zero-volatility asset, because
another correlated asset can depend on it. An all-zero-volatility model may omit draws.
Evaluate each midpoint coordinate with the exact integer PRNG numerator
`(2*k + 1 - 2**128) / 2**128`, converting the numerator and denominator to Decimal
for division. This is exactly the frozen `2*((k+.5)/2**128)-1` map, with no change
to hash encoding or sampled distribution, and avoids subtractive cancellation near
the midpoint that would discard about 39 digits before the polar transform. Integer
work here is limited to PRNG counter/encoding conversion, not financial evolution.

The kernel accepts resolved integer month indices. The future capture boundary validates
actual calendar dates, goal horizon/date and the immutable goal schedule against those
indices; it may not silently invent an anchor date or reinterpret outside-horizon entries.
Scheduled entry IDs are unique. Pauses suppress recurring contributions only; lumps
still apply. Bound the combined explicit pause and lump/withdrawal entries to 128.
Growth -1 has multiplier 1 during the first year and 0 thereafter, with no Decimal 0**0.

At month start, add recurring and lump contributions at target weights, then fund all
scheduled withdrawals pro-rata from the resulting nonnegative holdings. Aggregate
same-month withdrawals before funding; unpaid amounts remain a separate cumulative
liability and are never discharged by future contributions. Apply asset returns, then
fee, then tax on post-fee values, then the selected month-end rebalance. Full funding
that exactly depletes wealth is not itself an unpaid obligation.

Path evolution remains Decimal96. Check Q18/public bounds without feeding rounded values
back into evolution. Retained point values are published once to Q18. All summaries,
quantiles, histograms and goal comparisons use those retained canonical Q18 values so
they can be reproduced from saved projection paths. Preserve a separate ever-unpaid
funding flag from strictly positive pre-rounding unpaid amounts, including an amount
that rounds to Q18 zero. An unavailable or hidden liability must not become a successful
funding outcome. Goal success requires threshold attainment and no unpaid event.

Publish signed wealth and asset-allocation reconciliation residuals. Keep original
initial value, cumulative contributions, requested/funded/unpaid withdrawals, investment
gain/loss, fees and tax separate. Do not redistribute a residual or clear an unpaid flag
to force agreement. Real values divide nominal values by the declared compounded inflation
factor at that month; the scenario is modeled, including optional tax drag, not tax advice.

Nearest-rank quantiles use canonical value then absolute path index ordering; p0 selects
the minimum. Fixed summary percentiles are .05/.25/.50/.75/.95. Histograms start with
min(20,path_count) bins. Compute equal width by Decimal ceiling quantization of
`(observed_max-observed_min)/bin_count` to Q18. Begin at observed_min and end at
`observed_min+bin_count*width`, enclosing the observed range; the final edge may exceed
the observed maximum by the disclosed boundary rounding. Retain observed_min/max
separately and name this rule `q18_enclosing_ceiling_v1`. Reduce bin count only when
the unrounded width is below one quantum or the enclosing upper edge exceeds the
supported public bound. A nondivisible broad span must not collapse merely because
its Q18 coefficient lacks a small divisor. Equal values have one bin. All limits and
membership calculations use Decimal, not binary floats or integer financial arithmetic.
Bins are lower inclusive/upper exclusive except the final upper-inclusive bin. Check
every published edge for overflow; no clipped edge or successful truncation. No
interpolated quantile.

Path checkpoints are bounded chunks of at most 32 absolute path indices. Recompute a
requested path from its initial state; rounded checkpoints are not simulation restart
states. Finalization requires every requested absolute path exactly once for every
variant, matching input digest, canonical retained months and source basis. Duplicate,
missing or foreign chunks fail; a prefix cannot become a complete result. Bound actual
serialized private input/result bytes at 32 MiB; the public 2 MiB response boundary remains
the later service adapter's obligation. No successful truncation or reduced path count.

Retain Wilson 95% intervals using the frozen z constant, including all/none-success
samples. They describe sampling uncertainty conditional on the model. Report objective,
probability, shortfalls and unpaid funding separately; meeting a modeled objective does
not mark a goal accepted. Independent reference, hostile-context, seed/counter, cash-flow,
fee/real, chunk identity, unpaid-subquantum and all/none goal tests must pass before use.

## Calendar capture: discrete monthly date convention

This representation is accepted for implementation on 2026-09-15. Executable
verification and package acceptance remain separate.

Every capture retains an actual initial date anchor and all month boundaries.
For an observed snapshot, derive the anchor from its canonical valuation timestamp
in UTC and retain that complete timestamp and immutable snapshot pin. A modeled
initial value supplies its anchor date explicitly. Never choose the worker clock,
move an observed valuation to a month boundary or infer the anchor from a goal.

Define boundary 0 as the anchor date. Boundary m advances by m calendar months
from the original anchor year, month and day, clamping that original day to the
destination month's final valid day. Compute each boundary independently, not
by repeatedly adding a month to an already clamped date. Thus 2025-01-31 gives
2025-02-28 and 2025-03-31; 2024-01-31 gives 2024-02-29 and 2024-03-31.
An anchor on February's final day does not imply an end-of-month policy for all
later months: 2024-02-29 advances to 2024-03-29. Reject date overflow.

The retained month-0 wealth is before any flow. Month m starts at boundary m-1,
applies its modeled start-of-month flows, and ends at boundary m. Monthly
recurrence begins at the anchor. Pause dates, lump sums and withdrawal dates must
be exact start boundaries for months 1 through M. A mid-period date is unsupported,
not silently shifted or front-loaded. A flow on terminal boundary M is outside
the modeled horizon because no subsequent monthly step is requested.

Goal target date must equal terminal boundary M exactly, in addition to exact
month horizon, immutable assumption version, reporting currency and complete
schedule agreement. Preserve schedule identities and original dates; reordering
does not change content, but relabeling, merging, splitting or moving entries is
not equality to an immutable goal schedule. Pauses suppress recurring amounts
only; same-date lump sums remain active. The source capture and numerical input
must retain matching mapped month identities without recalculating finance.

Use a named `calendar_anniversary_clamped_v1` mapping rule with actionable typed
validation errors for unsupported dates, mismatched goal dates and outside-horizon
entries. These date rules are an explicit discrete monthly modeling convention,
not a claim to simulate daily cash-flow timing. Calendar validation does not grant
ownership, scopes or source entitlements; those must be checked before loading
private source/version content by the eventual application service.
