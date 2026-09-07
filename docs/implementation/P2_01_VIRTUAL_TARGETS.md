# P2-01 Virtual Portfolios and Target Versions

P2-01 is complete at `ecc75154397c8f9d7532fa2df8576846b60bae7c` with
[retained exact-SHA evidence](evidence/phase-2-p2-01-ecc7515.json).
The accepted [execution manifest](PHASE_2_EXECUTION_MANIFEST.md),
[target ADR](../adr/ADR-0010-IMMUTABLE-VIRTUAL-TARGETS.md), and
[API contracts](../architecture/PHASE_2_API_SERVICE_CONTRACTS.md) define the scope.

## Implemented capability

The authenticated `/pies` experience creates private account portfolios and
account-independent templates. Each portfolio fixes its reporting currency and
account scope, with editable name/description and an explicit archive action.
The detail route creates drafts from an empty target, a prior version, or an
authorized published template. Published content is immutable; editing it
requires a new version. Version comparison identifies deterministic changes in
both directions without altering either input.

The editor supports ordered groups, holdings and top-level reporting-currency
cash, canonical instrument/listing selection, funding-listing preferences,
explicit unresolved identifiers, exclusions, and all ten frozen constraint
kinds. Save retains invalid-but-structurally-storable drafts for correction.
Server validation reports bounded issues, exact effective weights, and explicit
normalization adjustments. Historical validation is labeled and cannot enable
publication of changed content. The editor preserves unchanged effective-time
precision, unsaved edits on command errors, and independent sibling ordering.

The target domain calculates with exact Decimal values and local precision
contexts. Validation/publication check current canonical mapping identities;
reading a published projection reconstructs its pinned content without silently
revalidating it against a changed catalog. No target is a broker Pie or an order.

## Persistence and interfaces

Migration `20260907_0009` extends the accepted `0008` schema with normalized
portfolios, versions, nodes, holdings, constraints, exclusions, mapping decisions,
validation/normalization records, audit events, command identities and collection
references. Composite ownership constraints, account guards and publication
triggers enforce scope and immutable content. Owner transaction locks serialize
commands, publication and activation. Commands require authorization, bounded
idempotency keys and optimistic preconditions; exact retries reauthorize before
returning their existing result.

Fifteen fixed target operations extend `/api/v1`. Existing Phase 1 paths and
schemas retain their contracts. The generated TypeScript client has closed Zod
schemas and fixed methods, with bounded requests/responses, safe errors,
timeouts, private caching and ETag handling. Browser server actions authenticate
each invocation and forward verified session/CSRF context to the API.

`list_virtual_pies` and `get_virtual_pie` bring the normal MCP registry to eleven
implemented tools. Both require portfolio and target read scopes, including for
templates. Hierarchy reads use one canonical transaction for portfolio,
version, validation and paginated nodes so concurrent edits cannot mix revisions.
The frozen Phase 2 registry remains planned beyond these implemented tools.

All new paginated collections use the existing owner-shared limits of 64 active
snapshots and 250,000 retained members. Cursor membership is bounded and
authorized. Navigation avoids speculative collection prefetch; instrument
selection and version activity load on explicit request.

## Local operation and recovery

Use the repository's pinned `make bootstrap`, `make run-local`, `make migrate`
and `make seed-demo` entry points. The idempotent synthetic seed adds an
account-backed portfolio and a private template with published group/holding/cash
targets. It preserves the Phase 1 economic fixture and EUR 248431.27 valuation;
seed retries retain target identities and do not overwrite user metadata edits.

The existing dispatcher activates due target versions in bounded batches on its
normal polling cycle. PostgreSQL remains authoritative; no new queue or external
scheduler is required for this lifecycle. Activation records the actual event
time with actor `system:target-scheduler`, preserves the intended effective time,
and occurs at most once per version. An older overdue schedule overtaken by a
newer explicit publication is superseded without replacing the newer active
selection. A later future schedule still activates when due.

Recover a mistaken publication by cloning the intended prior version and
publishing a new version. Archiving the active version leaves no active target;
the service does not silently reactivate a historical version. Preserve database
volumes during restart and apply migrations forward. Target scopes and published
history must not be repaired by direct SQL mutation.

## Verification boundary

Full `make validate` passed at the accepted clean SHA: 592 isolated and 103
service-backed Python tests, 86% coverage, 48 web unit tests, 32 synthetic and
12 API-backed desktop/mobile browser tests with zero retries. All three CI
workflows passed. The retained assertion map identifies 54 selectors and 100
collected Python test nodes for the package's three acceptance rows and five
scenarios, plus editor and browser assertions.

The [fresh runtime record](evidence/phase-2-p2-01-ecc7515-runtime.json) proves
repeat migration/seed, unchanged EUR 248431.27 baseline, API/MCP hierarchy parity,
one scheduled activation 0.331214 seconds after its effective time, and identical
financial/target hashes after all seven services stopped and restarted on the
same volume. Runtime logs and 45 database tables passed canary checks.
The [security record](evidence/phase-2-p2-01-ecc7515-security.json) retains full
history/source and six immutable-image scans, build bindings and scanner limits.
The earlier `6dde264` history scan failed on two verified test-code false
positives; the exact fingerprint correction and all acceptance reruns belong to
`ecc7515`. The failed gate is not presented as a pass.

The [acceptance matrix](PHASE_2_ACCEPTANCE_MATRIX.md) and
[scenario ledger](PHASE_2_SCENARIO_EVIDENCE.md) preserve pending shared predicates.
P2-02 through P2-10 remain required work; Phase 3 remains not started.
