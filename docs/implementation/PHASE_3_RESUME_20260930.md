# Phase 3 checkpoint — 2026-09-30

This is an owner-requested save point for later continuation, not a completed
feature or release. Parent delivery is
`c59b754b368025d728547ce66a26fa95ae584ab2` (saved layouts and provider acquisition).
Phase 3 implementation/local acceptance/independent review remain pending;
GitHub Actions remains owner-deferred and unverified. No deployment is authorized.

## Preserved implementation

- Account aggregation domain, exact calculation, normalized persistence,
  migration 0030, source authorization/retention, six typed REST operations and
  generated client.
- Aggregation web workspace, explicit saved FX observation picker and one bounded
  FX reference API read; synthetic custody ingestion and opt-in browser fixtures.
- Focused unit/contract/PostgreSQL/browser test sources and the accepted ADR-0034
  design. Authored tests are not evidence that their runtime paths pass.
- Current generated inventory: 136 REST paths/161 operations/578 schemas;
  ORM inventory: 364 tables. Original ten broker GETs remain sealed.

## Exact outstanding failure

The last actual PostgreSQL diagnostic, on 2026-09-22, failed at:

```text
tests/integration/test_aggregation_core_guards_postgres.py::test_live_run_future_expiry_marker_rejected_by_unmodified_database_clock
```

The failure occurs at `store.create_run(...)`, before the test reaches its marker
assertions. PostgreSQL reports `aggregate native component proof differs` in
`aggregate_child_guard()` at PL/pgSQL line 76. The relevant trigger is defined in
`migrations/versions/20260915_0030_account_aggregation.py`; publication is in
`packages/persistence/src/trading212_persistence/aggregation_publication.py`.
Investigate the mismatching native proof predicate and publication ordering;
missing membership flush is an unverified hypothesis. Preserve the database guard.
The diagnostic plugin is external to the repository and must not enter production.

Existing gate receipts below are historical working-source observations. Their
source manifests identify the exact tested files; they do not establish acceptance
of this later checkpoint:

| Receipt | Observed result |
| --- | --- |
| `aggregation-focused-05` | Passed: 51 Python tests, 58 web tests, Ruff, mypy, TypeScript, ESLint, generated contracts, architecture and broker boundary; 33.246s. |
| `aggregation-postgres-02` | Failed overall; migration, synthetic custody and browser fixture cases passed before an FX query-plan assertion failed. |
| `aggregation-postgres-04` | Failed overall; five FX reference cases passed before aggregation publication failed; 55.368s. |
| `aggregation-diagnostic-02` | Failed; exact SQL error above, source unchanged; 11.412s. |

There is no passing aggregation runtime/browser gate or full candidate gate.
The FX plan case constrains planner choices for its tiny fixture; it does not
prove default-planner production latency.

## Resume locally

Use the existing checkout at
`/home/peppasmich/projects/trading212-portfolio-intelligence` and private environment
`/home/peppasmich/.local/state/t212pi/20260908-resume/env.sh`.
Evidence and external stages are retained under
`/home/peppasmich/.local/state/t212pi/20260908-resume/phase3-20260914` (called `E`
below). These local files are not included in the Git checkpoint. Preserve them
until their source and evidence have been deliberately integrated or archived.

1. Fetch current main and inspect this checkpoint before editing. Reuse Docker
   Desktop with WSL integration and the single task PostgreSQL container when
   available; do not install another daemon or create parallel stacks.
2. Reproduce and fix the exact failing selector, then the remaining aggregate
   guard/retention cases. Run checks with fresh evidence names via
   `E/run_gate_v3.py`; never edit source while a gate fingerprints it.
3. Build the production web application and run the real aggregation browser
   journey at all three widths. Its fixtures require `T212PI_E2E_AGGREGATION=1`.
4. Review and integrate the external stages below using their saved bases,
   patches and file maps. Preserve root's current typing, transport timeout and
   migration SQL corrections. Generate contracts from the composed source.
5. Complete the remaining gates in `E/phase3-remaining-gates-audit.md`, including
   actual performance/RSS/latency, recovery, backup restoration, source/image
   security, provenance and final immutable-source acceptance evidence.

| External work, not integrated in this commit | Local continuation material under `E` |
| --- | --- |
| Research report profile 5, then alert retention (migrations 0031/0032) | `research-alert-preview-01`, `research-alert-composition-01.json`; original `staging-research-report-v5` and `staging-alert-retention`. The composed preview includes the V5 status mapper fix. |
| Aggregate report profile 6 core (migration 0033) | `aggregate-report-v6-handoff.md`, `aggregate-report-v6-filemap.json`, `staging-aggregate-report-v6`. |
| Report profile 6 API, web and browser | `aggregate-report-v6-api-filemap.json`, `aggregate-report-web-handoff.md`, `aggregate-report-web-filemap.json`, `aggregate-report-browser-handoff.md`, `aggregate-report-browser-filemap.json`. |
| Browser performance fixtures/collector | `browser-performance-handoff.md`, `browser-performance-filemap.json`, `browser-performance-preview-01`, `browser-performance-composition-01.json`. |
| Local SBOM/provenance/signature machinery | `local-supply-chain-handoff.md`, `staging-local-supply-chain`; independent review/freeze and execution remain pending. |

The metrics/alert expansion and clean PostgreSQL restore harness were assigned
before interruption; no completed frozen handoff or runtime result is claimed.
Whole-worker RSS and maximum-load/API latency work also remains incomplete.
Inspect any partial local artifacts before continuing instead of assuming the
earlier agent messages establish completion.

The existing Trivy vulnerability database was already stale on 2026-09-22;
refresh and record its actual metadata for the eventual security gate. SBOM
generation alone does not establish a vulnerability-scan pass.

## Checkpoint environment

On 2026-09-30, no task test/application process was found before verification.
The WSL `docker` command was unavailable and the Windows CLI initially could not
connect to `dockerDesktopLinuxEngine`. A normal Docker Desktop start succeeded
for the owner's subsequent cleanup request. No PostgreSQL or application
container was started and no database test rerun is claimed.

The cleanup removed 62 ignored/generated cache roots, totaling 1,688,853,330
logical bytes (1,698,889,728 allocated bytes): inactive Next output, Python/type/
test caches, TypeScript build metadata, generated client output and the stale
Trivy cache. Source/staging contents, dependencies, installed tools, Hypothesis
examples and accepted evidence were preserved. The next web/client use must
rebuild generated output; the next vulnerability scan must refresh its database.
`E/checkpoint-local-cleanup-20260930.json` records paths, sizes, content digests,
prior scanner metadata and the unchanged Git state.

Docker cleanup removed the stopped task PostgreSQL container, its task network,
six task image tags and 49 completed build-history records verified against this
repository's VCS metadata. Their inspected metadata is retained locally. Both
database volumes were preserved, along with scanner/base images and one build
record whose ownership was not verified. No global pruning was performed.
Runtime resumption must rebuild the task images and recreate its single Compose
service against the retained volume when needed.


Two exact-ID build-cache passes reported reclaiming 5.766GB and 2.135GB,
respectively. The first used repository Dockerfile/parent-chain evidence; the
second removed explicitly traced descendants of its saved web package-copy
roots. Together with local caches this removes approximately 9.59GB of cached
data, apart from the six removed task images. The final Docker inventory had
zero containers, two retained volumes and 126 cache records (6.631GB) whose
shared/generic/unverified ownership did not justify deletion. No blanket prune
was used. Receipts are `E/checkpoint-build-cache-cleanup-20260930.json` and
`E/checkpoint-web-cache-descendant-cleanup-20260930.json`.


## Save-point verification

`aggregation-checkpoint-20260930-01` passed in 52.984s with an unchanged working
source: 51 focused Python tests, 58 web tests, Ruff lint/format, mypy, workspace
TypeScript/ESLint, generated-contract equality, architecture, the ten-GET broker
boundary, repository/workspace validation, the high-confidence secret scan,
Prettier and `git diff --check`. Its command, raw log, JUnit output and source
manifest are retained under `E` with that receipt name. It runs no PostgreSQL,
production browser, image, full-suite or final acceptance gate. No GitHub Actions
status was queried.

Only documentation changed after that gate, with executable content/type/mode
checked against its source manifest before commit. The known database failure
and unfinished local stages remain as described above.
