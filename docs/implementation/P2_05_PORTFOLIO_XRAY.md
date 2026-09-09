# P2-05 Portfolio X-ray

P2-05 is **in progress** from accepted authority SHA
`0ebbfa29253f418084835335eb2ee66f1b898679`. P2-04 remains accepted at
`2a7c89a9b8c37d97006dafbbe97a44eec37b3fe0`. The implementation below has working-tree
verification; exact committed-source, CI, security/image and fresh-runtime
acceptance has not yet been recorded. P2-06 through P2-10 and Phase 3 remain not_started.

## Authority and calculation

The [execution manifest](PHASE_2_EXECUTION_MANIFEST.md),
[ADR-0017](../adr/ADR-0017-DECIMAL256-EXACT-XRAY.md),
[methods](../analytics/PHASE_2_METHODS.md),
[data model](../architecture/PHASE_2_DATA_MODEL.md), and
[API contracts](../architecture/PHASE_2_API_SERVICE_CONTRACTS.md) govern this
increment. `xray_v1` 1.1.0 uses `xray_decimal256_exact_q18_v1` within its closed
Decimal256 arithmetic boundary. Ordinary portfolio and target arithmetic retain
their existing contexts. Public amounts and weights remain explicit Q18 decimals;
private exact coefficients retain bounded calculation state and conservation
proofs without routing through the ordinary numeric decoder.

Real positions and cash retain their independent monetary roots. The global
10,000-path budget includes zero-valued roots; traversal reserves pending root
mass and follows at most four fund edges. A fund's unit composition uses its
lowest real held position UUID, including a zero-valued position. It does not
combine different roots or substitute a more complete root. Unknown mass remains
unresolved. Direct inventory, inferred identity and stale-path coverage are
separate quality measures and are not added to portfolio value.

Economic consolidation requires dated sourced identity evidence. Ambiguous or
failed mappings remain unresolved, including when a constituent supplies a
candidate entity. Classification uses entity evidence first, then compatible
instrument evidence; explicit classification coverage gaps block older fallback.
Reporting conversion preserves the saved broker valuation basis and requires
eligible sourced FX. An actual newer FX coverage gap blocks older quotes. A
two-leg route requires a common immutable source snapshot and fixing instant.

Known noncash normalization is specific to the selected dimension and retains its
denominator. Absolute weights govern concentration, overlap and threshold
decisions. Incomplete fund unit bases expose lower bounds; an unavailable basis
is distinct from a known disjoint zero. Canonical replay includes policy metadata
in stable order as well as financial values, warnings and provenance.

## Persistence and retention

Migration `20260909_0013` adds the X-ray catalog, policy, immutable captures,
canonical runs, projections and collection bindings. Deferred sealing guards
protect complete publication. Capture selects the bounded reachable catalog
closure and preserves competing relevant evidence without admitting unrelated
expired sources. Provider pages retain typed request echoes and trusted receipts.

Canonical runs retain fund compositions. Requested pair and common-entity rows
belong to their immutable collection; the service does not persist all pairs for
the account. Discovery supports more than 32 held funds, while one selected
request accepts 2–32 funds and at most 496 pairs. Separate selections retain
separate copies under the existing shared owner quota and TTL. Reuse does not
extend expiry, and empty collections still reserve capacity.

Current owner, scope, license and expiry checks precede decoding, replay, cursor
continuation and conditional responses. Every new run, financial projection, and
collection membership/binding requires pinned and current storage permission.
Checks at publication boundaries also reject permissions or source expiry that
activate during calculation. Existing retained collections and transient Top
reads require display permission without creating another stored copy.
Bounded cleanup charges rows and bytes
across retained source, capture, run and collection copies. Cleanup commits its
bounded progress independently of a later collection-capacity rejection, so a
large expired collection can eventually release its charged binding. Licensed
financial payloads and identifying exposure buckets are physically cleared;
nonfinancial retention evidence remains.

## Public surfaces and synthetic fixture

Four authenticated GET operations expose effective exposure, ETF overlap,
constituent snapshot headers and holdings. Effective exposure has bounded
exposure, path and held-fund views; overlap has pair and common-entity views.
The implemented inventory becomes 70 HTTP operations and 21 MCP tools. The two
new MCP reads use the same service and an isolated accessible X-ray resource.
Trading 212 retains its exact ten GET-only capabilities.

The `/xray` page preserves account, immutable snapshot/run, cutoff, currency,
dimension, view and fund selection in explicit query state. It presents exact
values, quality coverage, normalization denominators, bounded path proofs and
source links. Common-entity detail includes each fund's unit-basis coverage,
cash, unresolved weight, source time and representative root. The source page
distinguishes freshness from the currently authorized license state.

The complete synthetic seed adds a fourth account with direct share classes,
an ADR, two funds, unresolved constituents and dated stale evidence. Its exact
EUR 1,000 value comprises Alpha 560, Beta 390 and unresolved 50; known company
coverage is 0.95, duplicate exposure 0.41, HHI 0.4657 and pair overlap 0.5 as a
lower bound. The broker's USD 62.50 ADR basis remains the saved EUR 50 value.
The original EUR 248,431.27 portfolio is preserved. These are synthetic inputs,
not evidence of live provider access or licensing.

## Development verification and remaining acceptance

The initial working-tree `make validate` passed formatting, lint, strict typing,
1,394 Python unit tests, 223 web unit tests, 34 property tests, 114 contract tests
and 210 integration tests. Its migration inventory assertion omitted the new
revision from the downgrade table total. Adding that revision to the existing
inventory fixed the test; all 12 migration tests then passed. No migration or
schema behavior was changed by this correction.

The remaining working-tree gate,
`make test-security test-coverage test-e2e docs-check security-check build container-build`,
passed in 1,519.445 seconds with unchanged source. It recorded 100 security tests,
1,642 isolated and 225 service/migration tests (1,867 unique Python tests), 88%
combined statement/branch coverage, and all 76 browser tests with no retries.
Documentation, security checks, native/web builds and all six container builds
passed. These observations are development verification, not immutable commit
acceptance. The earlier failed gate is retained separately.

Focused evidence additionally exercises all 161 calculator/domain/decimal/property
cases, real discovery of 40 held funds and separately retained 496-pair selections,
actual-source FX coverage gaps, independent cleanup progress, and deferred input
and run sealing failures. Overlapping focused batches are not added to the unique
coverage count. Screenshot review found two X-ray form buttons using absent style
classes; they now use the existing shared Button component. After this correction,
focused lint and TypeScript checks, 20 X-ray web unit tests, all six X-ray desktop/
mobile browser tests, and the web production build passed. The updated desktop
screenshot confirms both buttons have the shared component styling.

Final review found and corrected a split-permission gap: display-authorized
retained runs could create new collections after storage permission was withdrawn.
The broad working-tree gate above predates this correction. Nine real PostgreSQL
regression cases passed in 75.80 seconds, covering denied/unknown storage permission,
new financial/membership/empty bindings, permitted existing reads and transient Top,
and permissions or expiry activated during publication. Failed writes retain no new
durable rows. The first attempt failed only a test comparison of reissued cursor
timestamps; the correction checks stable content and resumes the original cursor.
The complete X-ray integration rerun then passed all 54 cases in 447.68 seconds;
strict mypy passed all 389 Python files. A subsequent unchanged-source affected
gate passed 279 selected unit/property/contract tests, all 100 security tests, all
six X-ray desktop/mobile browser checks, formatting, lint, typing, documentation,
native/web builds, Semgrep and all six container builds. Its recorded duration was
247.142 seconds. Committed-source acceptance remains required.

Full acceptance must bind final source to the complete repository checks,
security/image scans, all CI workflows and a fresh runtime with immutable database
comparison across restart. No package or shared scenario is marked complete by
these development observations.

The documented P2-08 multi-account global header/default Compose configuration
and full-product mobile presentation follow-ups remain outstanding. Report
parity belongs to P2-06. Local verification reuses one task Compose project,
starts only required services and removes disposable task outputs at boundaries.

## Initial candidate security finding

Implementation `b9b75ec54fe94fdcec627d8e31ca94700ccb08ad` remains unaccepted.
Security CI `34340985984` flagged the synthetic policy label as a generic API key.
Source tracing and an independent review confirmed it is a policy identifier,
not a credential. A single commit/file/rule/line exception is documented in
`.gitleaksignore`; the corrected scan passed all 86 reachable commits. CI now
prints redacted finding details. The in-progress exact local gate was deliberately
interrupted after 176 integration passes to avoid repeating its remaining work
before correction. No full-gate acceptance is claimed for that attempt. See the
[retained finding and correction](evidence/phase-2-p2-05-b9b75ec-failed-security.json).
The corrected commit still requires all exact-source gates and fresh runtime
acceptance.

## CI database fixture correction

Candidate `b2b0466cc150ac14cd3893fd823a7b84b084d7d9` passed documentation,
security and browser CI. Its database coverage job passed 1,642 isolated tests
and 180 service tests, then reported 54 X-ray fixture setup errors. The fixture
retained CI's bare `postgresql://` URL, causing Alembic to select the uninstalled
psycopg2 driver. It now normalizes the disposable URL to `postgresql+psycopg`,
as the existing historical fixture does. No application or dependency changed.
The real migration/seed/read regression passed separately with both URL forms.
The database CI job now allows 40 minutes for the expanded coverage workload.
Its failed run spent 317.19 seconds on isolated tests and 595.18 seconds on the
service stage while all 54 X-ray cases failed during setup. Those stages alone
leave less than five minutes of the former 20-minute budget for the X-ray cases.
Test commands and the coverage threshold are unchanged.

The local exact gate was deliberately interrupted after diagnosis. It completed
219 integration, 12 migration, 100 security and 1,642 isolated coverage tests,
then 188 service coverage cases before interruption. It has no full-gate pass.
The [retained failure](evidence/phase-2-p2-05-b2b0466-failed-quality.json) keeps
the actual CI and partial local outcomes. Full corrected-source acceptance is
still required before closing P2-05.

## Serial browser CI budget

Candidate `c84ecee2278a1f32d41c2e9640692001fae6fcf8` passed documentation,
security and complete Python CI coverage: 1,642 isolated cases, 234 service cases
and 88% combined statement/branch coverage. Browser CI completed 73 checks, then
the 20-minute job limit cancelled the final three mobile X-ray cases. GitHub's
timeout annotation and the incomplete transcript are retained in the
[candidate record](evidence/phase-2-p2-05-c84ecee-incomplete-browser.json).

The browser job now allows 40 minutes for serial execution. Test selection,
per-test timeouts, retry policy and worker count are unchanged. The local full
gate was deliberately interrupted after 224 service coverage passes to avoid
remaining work on the superseded candidate. Its completed layers are retained,
without claiming a full-gate pass. The corrected commit still requires complete
immutable-source acceptance.
