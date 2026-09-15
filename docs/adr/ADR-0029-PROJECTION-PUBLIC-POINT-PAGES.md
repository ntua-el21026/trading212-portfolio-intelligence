# ADR-0029: Bounded saved projection checkpoint pages

- Status: Accepted design for implementation; runtime validation pending
- Date: 2026-09-15
- Scope: P3-03 application, REST, MCP and report projection boundaries
- Authority: Phase 3 service contracts and methods; ADR0019 and ADR0027

## Context

The canonical projection contains every selected variant, absolute path and retained
checkpoint. Private input/result storage remains bounded at 32 MiB, while ordinary
public transport is limited to 2 MiB. No reduction in simulated paths, horizon,
retained months or sensitivity cases can turn an over-bound result into success.
A 600-month horizon retains at most 121 checkpoints, not 601: ADR0027's existing
121-point maximum remains unchanged.

A conservative JSON upper bound for the proposed complete point is 5 KiB: twelve
asset entries with 120-character ASCII keys and explicit Money, twelve other Money
values, month/funding fields and row identity. A complete 121-checkpoint path can
therefore occupy about 605 KiB before common context. A hypothetical 601-row path
would exceed 2.9 MiB under this bound, but that representation is not authorized.
The full three-variant distribution/histogram/goal summaries and bounded source
proof can combine with a whole retained path to exceed the 1 MiB financial-page
budget. These are conservative representation bounds, not measured serialization
or runtime benchmark results; no executable measurement was run for this stage.

## Decision

Preserve all 17 frozen operations and MCP tools 33–36. Add optional `point_limit`
(default 25, range 1..100) and `point_cursor` (maximum 2048 characters) only to
GetProjectionRun and the corresponding get_projection tool. The new resource remains
projection-v1.html. This is a bounded representation of an existing read, not a
new path-query endpoint. GetGoalAnalysis keeps its current operation and returns
all saved goal sensitivity variants or a typed unavailable reason.

Name the distinct public result `projection_points_v1`. Every page contains the
complete common context and every variant's retained monthly distributions,
nominal/real terminal histograms and observed extrema, terminal cash-flow summaries,
funding counts and optional goal estimates. All financial values carry currency;
all ratios remain exact decimal strings. Context contains at least estimated quality,
never better than full retained source quality, and explicitly states that the result
is a model estimate rather than a guaranteed forecast. Source/warning preview arrays
contain at most 16 entries (within the shared maximum of 64) with exact omitted counts. Omission from a preview is not
a missing or unavailable financial observation. Full proof remains private and in
complete authorized reports.

Traverse complete ProjectionPoint rows in canonical variant order (baseline,
contribution_delta, mean_log_delta), then absolute path index, then retained point
ordinal. A row includes absolute page ordinal, variant, path index, retained point
index, path point count, first unpaid month, mapped calendar date and every original
point financial/asset/residual/funding field. No point can be split or stripped of
financial fields to fit. A page may end within one path; its identities and cursor
state that continuation honestly. All retained paths and points remain accessible;
no selected path is described as the whole population. The flattened total is
variant_count * path_count * retained_point_count. Page size is a maximum; byte
limits may end it earlier after a whole row.

Use a hard 1 MiB UTF-8 canonical financial page budget including common context,
summary, rows and view metadata. Reject when common context alone cannot fit or the
next single row cannot fit an otherwise empty page. Do not drop common variants,
reduce the requested point limit, truncate arrays or return an empty prefix with
success. The REST/MCP transport must separately measure its entire final envelope
against 2 MiB. Public page/content digests are distinct from canonical saved result,
numerical input and complete dated capture digests.

Terminal cash-flow means and nearest-rank quantiles use the complete saved Q18
terminal vectors for contributions, requested/funded/unpaid withdrawals, investment
effect, fees and optional modeled tax drag. Reuse Decimal96/Q18 and the frozen
five nearest-rank probabilities. Preserve funding failures and positive unpaid
amounts below Q18 separately. The current canonical result already retains all
those vectors; the application projection implementation must derive these summaries
from them without rerunning sampled paths or changing saved values. This new public
summary contract is not a claim that the aggregation adapter already exists.

A goal analysis retains its job state separately from result availability. A
succeeded job whose retained result expired remains distinguishable from a failed
job. No pinned goal produces explicit `no_goal_pinned` without fabricated finance.
An available analysis returns exact terminal quantiles in the pinned nominal/real
basis, saved target, success count/probability/Wilson sampling interval, shortfalls,
funding counts and all separate common-random-number sensitivity estimates. A
modeled `objective_met` result never changes goal lifecycle state or auto-accepts it.

Retain version names and descriptions as immutable metadata alongside numerical
content. Command idempotency binds both metadata and content; numerical
`projection_definition_digest(content)` and the existing capture types are unchanged.
Changing labels is not new calibration evidence. Full source selection and dated
calendar intent remain bound by the complete capture digest, not only the numerical
digest. Neither IDs nor source labels authorize private access.

Current token scopes, durable grants, owned account/version/snapshot relationships,
normalized calibration memberships and pinned/current source license rights precede
private content decoding, cursor parsing, conditional responses and idempotent replay.
Reauthorize immediately before financial return/publication. A cursor binds stable
issuer+subject, account, run, complete capture digest, numerical input digest,
canonical result digest, public view version, point limit, resource name and absolute
ordinal; expiry is no later than the run or any required source. Changing any binding
fails before exposing financial rows. A caller-supplied expected account pin for MCP
must be checked before private data or cursor processing. Tokens or token hashes are
not cursor identities.

## Validation and integration

Add tests for financial-string/bool/unknown-field rejection; canonical asset axes,
exact weights and PSD; dated schedule and goal agreement; all-variant work limits;
whole-row continuation and totals; variant/path/point identity; full source quality;
funding flags/residuals; complete histograms/goals; explicit no-goal/expired states;
UTF-8 financial-page and complete envelope byte bounds; source/account authorization
before bytes/cursors/conditional reads; and immutable saved-value parity across API,
MCP and reports. Parent service/storage/worker integration owns execution evidence.
The bounded public representation is accepted before its dependent registration.
Implementation and local execution evidence remain separately tracked; this decision
does not certify completion, independent acceptance or production readiness.
