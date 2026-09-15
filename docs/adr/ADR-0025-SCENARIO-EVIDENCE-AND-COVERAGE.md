# ADR-0025: Source-bound scenario evidence and conservative coverage

**Status:** Accepted implementation decision, 2026-09-15

**Authority:** The additive v1.0 freeze, Phase 3 deterministic stress methodology,
scenario service contracts, and ADR-0019. This resolves representation and coverage
details before implementation; it does not claim validation or a new provider license.

## Decision

Implement `stress_v1` version `1.0.0` with numeric profile
`premium_decimal96_q18_v1`. Calculations consume complete retained canonical
X-ray terminal values and source proof. Retain both the canonical XrayInput and
XrayCalculation through their existing codecs, without extending their frozen
schemas to accommodate scenarios. Keep original root/path identities,
classification/economic-currency evidence, explicit cash/unresolved states and
upstream partition residuals. A fund wrapper never contributes alongside its leaves.
Use the published terminal amounts without recomputing allocations or redistributing
rounding differences. Keep a declared difference between their sum and an upstream
portfolio amount separate from scenario effects.

### Sensitivity evidence

A scenario definition records user shock assumptions and immutable source/version
references. A source-backed coefficient is resolved from an owned retained typed
observation whose membership in that exact source version is proved by normalized
references and content digest. Referencing an unrelated price observation or adding
a source label to a user-entered coefficient does not establish evidence.

Retain the observation's subject identity, canonical driver identity and version,
coefficient and units, response currency/basis, validity/economic dates, first-known
time, availability/quality and provider/license lineage. Instrument/entity identity
must be canonical; symbols and names do not establish membership. The selected
source version must provide at most one applicable coefficient per component and
economic driver. Competing observations are ambiguous, not averaged or selected
by request order. Missing applicable observations leave explicit uncovered mass.

The supported response is local-value simple return. Rate shocks are absolute
decimal rate changes and their coefficients are local-value-return change per unit
rate change. Factor shocks are simple dimensionless factor returns and coefficients
are local-value-return change per unit factor return. Thus coefficient `-2` and
rate shock `0.01` give effect `-0.02`. Basis points, duration, DV01, log responses
or currency-inclusive coefficients require an explicitly evidenced typed conversion
before they qualify; no implicit conversion occurs in the calculator.

Driver equivalence follows canonical economic identity, not source revision IDs.
Different evidenced drivers may sum. The same FX/rate/direct-price exposure cannot
be counted again through a renamed factor or another provider/version. An unknown
equivalence or FX-inclusive response basis remains unsupported. A direct price
shock combined with an independent rate/factor effect carries the explicit assumption
that the price shock is an additional effect; this does not establish independence
when the source identifies equivalent exposure.

Do not add a generic source-registration API as part of this decision. The existing
typed source boundary and a bounded synthetic source fixture can exercise the
required observation/membership behavior. Production source support remains
unconfigured unless actual permitted evidence exists. Normalize sensitivity source
payload and licenses for expiry; permanently retained definition versions contain
references and owner assumptions, not provider coefficient copies that evade deletion.

### Matching and coverage

Evaluate relevant selectors as `match`, `no_match` or `unknown` using only retained
evidence. A known unequal identity is no_match. Missing/ambiguous relevant evidence
is unknown; unrelated missing dimensions do not block a known decision.

Apply exclusions first. A definite exclusion match means unchanged excluded value,
even if a sensitivity would otherwise be unsupported. An uncertain exclusion that
could affect a component's treatment cannot be treated as either a definite exclusion
or a definite permission to shock it; retain uncovered status and its reason.

Price priority is instrument, entity, sector, region. Examine configured levels in
that order. Multiple definite matches at one priority are invalid. Exact/equivalent
duplicate rules are invalid even if their sizes agree. A potentially matching unknown
at a higher priority blocks a lower-priority winner; one known match with a competing
unknown at the same priority is also uncovered. A single known match with no such
uncertainty wins; lower-priority missing classification cannot override it. If every
relevant rule is known not to match, the price channel is explicitly unshocked.

Examples: a known instrument match remains usable with an unknown sector. An entity
match with unknown instrument identity does not defeat a potentially applicable
configured instrument rule. A known instrument mismatch followed by an entity match
uses the entity rule. The result is independent of rule ordering.

Classification selectors join a terminal classification decision's assignment IDs
to the pinned input's exact assignments and taxonomy identity/version; a matching
bucket label alone is insufficient. Existing X-ray currency classification originates
from the source economic-currency dimension, not a listing-currency fallback.

FX requires evidenced economic currency. Reporting-currency identity gives FX zero
only with that evidence; listing currency is insufficient. Explicit cash currency
may establish its economic currency. For direct cash use the retained CashRoot's
original currency. For constituent cash require the exact final holding/candidate
membership and that holding's source currency; a header cash remainder without a
currency-bearing holding remains unknown. A price-rule winner does not resolve
missing FX or sensitivity evidence.

Covered, uncovered and excluded values form a mutually exclusive partition of the
canonical original amount. Covered includes explicitly unshocked values. Any strictly
positive canonical value with unsupported potentially shocked treatment prevents a
complete portfolio post-value/impact. There is no percentage materiality threshold;
the numerical tolerance is not a coverage threshold. Exact zero contributes no money
uncertainty but keeps its diagnostics. An unavailable original amount is not zero.

A component post-value is available only when every applicable channel and exclusion
decision is resolved. Known channel effects on an incomplete component may be shown
as explicitly partial facts, never added into a complete component or portfolio total.
Known-only totals remain partial estimates. The only monetary exception to unresolved
treatment is a deterministic proof that the original amount is available and every
admissible treatment, including exclusion and no-match, gives zero effect in every
applicable channel. Exact zero input shocks with the method's supported finite
coefficient bounds can establish zero effect despite unknown matching or a missing
coefficient. This proves a product/effect is zero; it never assigns zero to the missing
coefficient or invents a matched/unmatched mapping. The component remains uncovered
in the mapping/evidence diagnostics, while its separately proved unchanged money may
contribute to a complete monetary total. Exact zero original value is the analogous
case under the finite supported treatment bounds.

If any admissible treatment could have a nonzero price, factor or FX effect, or the
original amount is unavailable, this exception cannot publish a complete monetary
result. Do not rely on cancellation between unknown channels, a small-value tolerance
or a presumed missing coefficient. Current authorization, malformed-input rejection
and known equal-priority/duplicate-treatment conflicts still apply before this proof;
zero money does not bypass those checks. Keep monetary availability distinct from
mapping completeness and report the proof basis explicitly.

### Arithmetic and replay

Use ADR-0019's isolated Decimal context and one Q18 publication boundary. Price/FX
shocks are in `[-1,5]`, coefficients in `[-100,100]`, and rate/factor shocks in
`[-1,1]`. The rate/factor paragraph's total first-order effect is the sum of those
sensitivity effects, bounded to `[-1,5]`. Separately reject each negative multiplier
in the selected formula; do not clip or redistribute.

With price effect ratio p, summed sensitivity ratio f and FX ratio x:

- First-order post: `pre * (1 + p + f + x)`.
- Compounded post: `pre * (1 + p + f) * (1 + x)`.
- Original-basis channel effects: `pre*p`, `pre*f`, `pre*x`.
- Economic interaction: zero for first-order; `pre*(p+f)*x` for compounded.

Disclose any Q18 reconciliation difference separately from economic interaction.

Historical replay supplies canonical local total-return and FX changes to those
channels. In v1, a replay request does not simultaneously apply hypothetical price,
FX, rate or factor shocks; its scenario version may retain the mode and exclusions
but has no hypothetical shocks. This avoids inventing an unspecified replay/manual
shock precedence. Reject a mixed request rather than silently ignoring its definition.
First-order replay is labeled an approximation under its selected interaction policy;
neither mode represents realized owner performance. A reporting-currency return that
already contains FX must not receive FX twice: require the retained local-return/FX
decomposition or make the affected replay treatment unavailable. Out-of-bound replay
changes are explicit unsupported/failed output, never clipped.

Holding basis and market knowledge policy are separate. Current holdings reuse the
pinned current terminal partition. Historical holdings require a retained then-dated
portfolio/constituent basis at or before the replay start, with its actual valuation
time and valid historical classifications disclosed. Do not manufacture a start-date
holding set from current holdings or interpolate missing records. Retain the holdings'
own knowledge/capture cutoff as well as the independently selected market cutoff.
Point-in-time selection rejects source revisions first known after the applicable
cutoff. A then-known-at-start claim additionally requires evidence available then;
a later cutoff or retrospectively retrieved valid historical fact cannot support that
claim. Retrospective retrieval is labeled explicitly without changing holdings basis.

Comparison reads exactly two authorized retained runs. Different scenario assumptions
are expected; method/numeric/currency and declared holdings/market basis compatibility
must be established before deltas. Preserve mismatches and original values separately;
do not convert currencies, recompute runs or hide changed source/snapshot dates.

## Consequences and acceptance

Preserve the existing bounds: 128 shocks, 128 exclusions, 10,000 terminal paths,
32 MiB private input/result and 2 MiB ordinary output. Bound source memberships and
work before loading. The scenario implementation additionally has one aggregate
100,000-row sensitivity budget per run across observations, memberships, evidence
and applied-use records, alongside the complete 32 MiB proof limit. Count the combined
rows before loading or reserving expanded structures and fail on excess; do not truncate
or apply a separate 100,000-row allowance to each category. This is a root-approved
implementation admission decision, not evidence of package or owner acceptance.
Current scopes and pinned/current source permissions precede
private decoding at admission, replay, execution, publication and reads. Shared premium
capacity, fencing, source retention and report-copy deletion apply to this family.

Required vectors include 60/40 with price `-.20/+.10` and FX `-.10`: compounded
post `82.8`, price effect `-8`, FX `-10`, interaction `.8`; first-order post `82`.
Also verify equivalent fund partitions, exclusion before unsupported sensitivity,
unknown higher-priority matches, duplicate drivers, 60 covered/40 uncovered versus
40 excluded, zero/missing original values, units, negative multipliers, Q18 residuals,
future-known revisions, historical holdings and non-recomputed comparison. Run status
and financial availability stay distinct; computed partial financial coverage is not
a successful truncated execution.
