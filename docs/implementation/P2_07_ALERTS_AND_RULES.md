# P2-07 Alerts and Rules

P2-07 has scoped local acceptance at `03c3c5b0b8182aadaaf48ec29131ab7fe83095a7`: versioned alert rules, immutable scheduled evaluation, event deduplication/cooldown, authorized lifecycle/history, bounded delivery and canonical alerts exports. Phase 2 is in progress: 7/10 packages (70%), 19/29 local rows and 30/40 scenarios complete. S31 includes both report/alert durable recovery and actual Redis-loss republication of the same pending alert input. Shared API/DATA/SEC/OPS and S32/S34/S38 predicates remain partial; P2-08 through P2-10 and Phase 3 remain `not_started`. GitHub Actions is owner-deferred and unverified; no CI pass or final Phase 2 release is claimed.

[Accepted local evidence](evidence/phase-2-p2-07-03c3c5b.json). Actual completed gate summaries record 2352 isolated and 338 service-backed Python tests, 88% combined Python coverage with branch measurement, 345 web unit tests and 100 local browser checks. The full gate took 5416.926 seconds; fresh runtime took 256.28724 seconds. All six immutable images and the exact source/history scans passed; all seven runtime services restarted and scoped cleanup verified absence.

The implementation began from P206 closure `2cdb409`. Earlier working/no-acceptance observations, rejected `0d7aa9b` security evidence and rejected `0df988c` browser evidence remain historical at their original sources; P206 acceptance and evidence bytes are unchanged.

This implementation applies [ADR-0015](../adr/ADR-0015-VERSIONED-ALERT-EVALUATION.md),
[methods section 8](../analytics/PHASE_2_METHODS.md#8-versioned-alerts-and-deterministic-evaluation),
the [fixed API operations](../architecture/PHASE_2_API_SERVICE_CONTRACTS.md#7-alert-management-and-history)
and [security/privacy contract](../security/PHASE_2_SECURITY_PRIVACY.md).
It adds no broker capabilities: Trading 212 retains its ten typed GET operations.

## Implementation ownership and bounded contracts

Domain owns immutable rule versions, predicates, captured inputs, evaluation
results and canonical codecs. Analytics owns exact comparisons, concentration,
schedule arithmetic and condition/event reduction. Application ports expose
only named alert operations and fixed evaluation/delivery job types.
PostgreSQL owns account authorization, immutable capture, lifecycle, due cursors,
outboxes, leases, independent acknowledgment/resolution and bounded retention.
Existing dispatcher and worker processes run the engine; no additional service
or dedicated scheduler container is introduced.

All 15 families and 27 metrics in methods section 8.1 are required. Predicate
variants reject irrelevant fields. Fixed source families are `valuation`,
`history`, `price`, `fx`, `constituent`, and `classification`; source references
identify the relevant immutable evidence, and missing-session rules additionally
pin a calendar version. Activity filters reuse the canonical historical cash-flow
kind registry. Refresh capability filters reuse the existing exact ingestion
capability enum, with its existing application import retained.

`history` identifies a retained `HistoricalRunModel` and uses its canonical
coverage cells. Valuation coverage counts the original positions and cash only
when the saved calculation proves the complete inventory; an unknown denominator
stays unknown. Constituent weight coverage supports a missing fraction without
inventing a missing row count. Classification coverage uses the actual pinned
instrument/taxonomy request. Calendar children must also be known by the slot.

Canonical input and result bytes are each limited to 2 MiB. Each evaluation may create at most 10,000 total prospective in-app and external delivery jobs; the complete fanout is counted before any event or delivery write, and overflow fails atomically with `INPUT_BOUND_EXCEEDED`. Complete event batches
are limited to 10,000 candidates with explicit overflow detection; exceeding a
bound is an inspectable unavailable result, never a truncated exact metric.
These are implementation bounds, not claims about measured throughput.
Captured payload retention ends at the earlier of 90 days and every applicable
source's lawful expiry. Current revocation denies use immediately. Safe identity,
digest and lifecycle tombstones remain until authorized owner deletion; archive
does not delete history or extend any source license.

## Cutoffs, lifecycle and event semantics

The scheduled slot is the immutable source cutoff. Economic/effective time and
trusted first knowledge/publication must both qualify. A late-created result with
an old valuation date cannot supply an older slot. Retrying a job never recaptures
newer input. Threshold comparison uses the canonical exact basis, including
private Decimal256 X-ray coefficients where applicable, with Q18 presentation
kept separate. A known lower bound proves only the conclusions mathematically
supported by that bound; missing input never becomes zero or false.

Ordinary cash, direct concentration, drift, and FX retain the established
Decimal80/Q18 calculation boundary; Decimal256 is confined to exact X-ray ratios.
Portfolio L1 drift is half the absolute drift sum at a declared frontier depth
from 1 through 8. Alert freshness overlays never mutate an existing planning
input's quality while retaining its old digest. Known cash keeps its own material
quality even when an unrelated position lacks a price.
Failed material financial input produces an inspectable failed evaluation under
both quality policies; a retained scalar cannot trigger or clear an episode.
Health and terminal-outcome rules may observe the failure they are designed to
report. Direct broker FX conversions retain the actual source record, rate,
observation time and direction without inventing a market-provider identity.

Activation starts at the first schedule-aligned slot at or after the actual
activation instant. A compact durable cursor retains unadmitted eligible work;
indexed append-only lifecycle events explain inactive intervals. Admission uses
one slot per transaction and a cycle limit of at most 100. Admission reserves a
durable sequence order before owner/source locks, so denied or busy rules
retain their original due slots without starving other rules, even across clock
ties, concurrent dispatchers and process restarts. The database enforces
strict unique `(rule_version_id, scheduled_for)`, as required by ADR-0015 and
methods, over the weaker three-column example in the data-model overview.
Claims pin lifecycle sequence as well as lease/fence; pause/resume cannot revive
a claim from before the pause. Chronological predecessor checks at dispatch,
claim and completion prevent later effects from overtaking earlier work.

Explicit backfill is a separate internal command for one exact historical,
eligible missing slot. It uses the same immutable capture and unique job identity,
with an immutable observation-only execution intent. It evaluates real historical
input and retains all five truthful outcomes, but cannot alter live condition
state or deliver notifications. It cannot take outstanding work away from live
admission or overwrite an existing evaluation.

Threshold episodes retain their true latch across unavailable, suppressed or
failed observations. Acknowledgment is independent of resolution. Manual
resolution does not rearm a continuing true condition; a later false observation
is required. Supersession closes an old episode as `rule_superseded` without
claiming recovery. Event rules deduplicate economic/run/job identity plus active
revision and retain explicit correction links. Cooldown limits external attempts
while every distinct event remains visible in-app.

`absolute_external_flow_amount` compares the absolute amount of each canonical
external-flow event, not a net or gross window aggregate. `activity_count` is the
complete window aggregate. Purchases/sales are internal flows; source currencies
are never relabeled, and conversion requires a sourced, pinned FX observation.

Explicit immutable activity revision evidence references two actual account
source records with the same canonical economic identity. Both owner attestation
and an inert reference to reviewed provider evidence require an authorized owner
registration; neither invents broker sequence numbers or verifies external
evidence automatically. The server records first knowledge, prevents cycles, and
retains the proof alongside the selected revision. Without proof, conflicting
revisions remain ambiguous. Historical and alert selection use this shared rule.
Order/fill registration uses the owned, cutoff-visible mapping inventory and
requires a canonical execution; an unmatched order cannot receive an unusable
revision identity. Historical period capture retains the complete economic group
when any candidate precedes the period end, including a correction moved beyond
that end. An unproved conflicting date remains ambiguous; a proved later date
supersedes the old payment before period filtering. Unrelated later groups stay
excluded, and prior-cutoff immutable captures retain their original bytes.
Alert capture applies its window and known instrument/kind scope to complete
economic revision groups: if any member can qualify, all members participate in
canonical revision selection. Explicit same-instant linked cash-effect parents
remain available for canonical deduplication. An unrelated old or known
out-of-scope conflict does not invalidate the selected window; a relevant conflict
still fails closed. Raw source observation times and canonical event bytes remain
unchanged when a proof is recorded. Typed proof references retain both ordered
source parents, digest and actual proof knowledge time. Point-in-time selection
applies an edge only when that proof is known, so a later capture still exposes
the ambiguity that existed at an earlier valuation cutoff.

Alert eligibility follows the validated ancestry needed to establish the winner.
A late bridge can therefore make an older revision newly eligible even when its
direct proof falls outside the current window. Unrelated proof branches do not
advance that winner's eligibility. Proved corrections resolve before economic
date filtering: a correction moved into the future suppresses its superseded
payment now and becomes eligible when its own payment date arrives, without
another ingestion. Complete known proof parents are retained when a mistaken
future date is corrected backward. Their actual source arrival and payload
fingerprint are pinned; the normalized event digest binds the original economic
timestamp. Future payments are not emitted early. Native and proof-free timing
retain their established behavior. Selected winners are filtered before material quality or FX
conversion, so an unrelated currency or degraded event cannot poison the result.
The separate `activity_window` coverage fact retains its complete-ledger meaning
across orders, dividends and transactions for unusual-activity rules; dividend
rules retain dividend-only coverage. Scope filtering does not invent completeness.

## Actual provider observations and delivery

Provider-health rules reference an owner-owned configured market-data provider.
Reference-provider invocations are owner/provider scoped; assigning them to a
broker account would invent attribution. Broker failures belong to the separate
account-bound failed-refresh family.

Wrappers around the seven existing typed methods record actual completed calls
using an invocation UUID, capability, adapter version, start/completion/first-known
UTC instants, safe outcome and fixed failure category. A database sequence breaks
equal-time ties. There is no response, request, destination, credential or raw
exception payload. Re-recording one observation is idempotent; another physical
attempt gets another identity. Adapter success is distinct from downstream
ingestion or Redis publication success. No network await occurs in a database
transaction. Current owner/provider/capability and principal grants are checked
before invocation and recording. Recording failure propagates explicitly.

Local `not_configured`, `unsupported` and `license_denied` outcomes are unavailable,
and do not claim network failure or a successful reset. No observations is
unavailable. A real failure/failure/success/failure sequence has one consecutive
failure. Capture uses a complete bounded eligible prefix; exceeding its source
bound cannot yield a truncated exact count.

The in-app feed is complete without external configuration. Optional external
payloads contain only delivery, event, rule, and immutable rule-version UUIDs, with no financial
source details, free-form user text or artifact tokens. Destinations are trusted
server configuration; public operations expose only opaque IDs and safe state.
The dedicated webhook adapter must satisfy ADR-0009's manifest, fixed origin,
DNS/connection pinning, TLS, timeout/body/retry and isolation requirements before
being enabled. No real recipient delivery is authorized by local validation.
An ambiguous delivery timeout records `publication_unavailable` and retries the
same delivery identity and payload. The fourth consumer attempt reaches the
terminal attempt bound; worker outcomes distinguish this failure from a deferred
retry. Worker and persistence share the permanent-failure classification.

The packaged `alert-webhook.json` manifest initially has no origins. It fixes
`POST /v1/alerts`, the notification credential namespace, 5-second connection/read
and 15-second total deadlines, 64 KiB request/response and 8 KiB header limits,
and four consumer attempts. Each attempt resolves and validates every address,
then connects to a checked numeric address with the configured TLS hostname.
Redirects, environment proxies, scoped/IPv4-mapped/transition addresses and
nonpublic destinations are rejected. Responses and secrets are not retained.
The broker transport validator's exception names only this adapter; sibling
files and aliased outbound stream imports remain denied.

## Public interfaces and verification

Implement exactly the 13 accepted HTTP operations and one additional MCP tool,
`get_alert_summary`. Rule detail includes a bounded evaluation page (default 25,
maximum 100) so suppressed, unavailable and no-match results remain inspectable
without fabricated events or an extra route. Strong aggregate ETags serve action
preconditions; mutable composite detail does not return conditional 304 responses.
Reads require portfolio/alerts read; writes require portfolio read, alerts write,
analytics read and the predicate's material target/activity scopes. Write grants
do not imply read grants. Current and pinned source permissions remain mandatory.
Idempotent lifecycle replay rechecks current grants against the original command's
immutable version, resolved through its recorded lifecycle event. A later active
or latest version neither removes nor adds material requirements to that replay.

The web editor must cover all typed predicates, immutable version creation and
explicit activation, lifecycle actions, stale preconditions, evaluation history,
independent acknowledgment/resolution and stable URL/filter/cursor navigation.
All saved immutable versions have their own bounded page, including drafts
that were never activated; version and evaluation cursors remain independent.
The existing alerts export dataset becomes available only with its actual
canonical producer and licensed standard/audit JSON/CSV/XLSX coverage.
An alert export's copied payload expires no later than the selected alert
input/result deadlines, as well as its report and licensed-source deadlines.

Required proof includes exact boundaries and lower bounds, all metric producers,
health exceptions, the six-slot two-episode example, correction/dedup/cooldown,
pause/resume/supersession, reversed dispatch, leases/restart/dead letters, real
backfill, current authorization, license expiry and physical copy purge, actual
provider observations, in-app-only operation, webhook SSRF/redirect rejection,
API/MCP parity and complete desktop/mobile journeys. Heavy checks run serially,
reusing one task Compose project and only its needed services. Disposable task
resources and generated files are inspected and removed at verification boundaries.
