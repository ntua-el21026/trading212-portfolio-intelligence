# Changelog

All notable project changes are recorded here. The project follows semantic versioning once implementation releases begin.

## [Unreleased]

### Phase 2 historical intelligence

- Add immutable historical captures, dated activity/opening evidence and five
  exact calculation families for performance, benchmarks, attribution, income
  and cash flows, with restated and point-in-time source selection.
- Expose six additive HTTP reads, four bounded MCP reads and connected performance
  and income pages with capture replay, filters, charts and accessible tables.
- Add separate annual and timely synthetic histories, normalized calculation
  provenance, composite benchmark views and bounded licensed-payload cleanup.
  P2-04 acceptance remains pending its exact-source validation and runtime gates.

### Phase 2 reference sources

- Add isolated typed synthetic reference adapters for raw, split-adjusted and
  total-return prices, FX, benchmark levels, corporate actions and metadata.
- Retain immutable owner-scoped source catalogs, calendars, licenses, observations,
  revisions, retrieval occurrences and exact benchmark command history in PostgreSQL.
- Expose fourteen bounded source/benchmark API operations, generated clients,
  provenance and observation pages, and an immutable benchmark version editor.
- Enforce cutoff, calendar-gap, revision-ambiguity, freshness and separate
  storage/display/report/export permission policies. External providers remain
  explicitly unconfigured. Accept P2-03 at
  `e258f54bb03a958f7847b310ee882b7f4a54686f` with full local/CI validation, eight
  source/history/image scans and fresh retained-volume restart evidence.
- Preserve the first runtime harness failure: regenerated cursor issue timestamps
  changed signed bytes. A second attempt exhausted the unchanged 64-view quota.
  Correct cursor comparisons and scope repeated planning regression to one durable
  global plan with actual Redis-loss recovery; every new source check remains.
  Three packages, eight local rows and twelve scenarios are now complete.

### Phase 2 contribution planning

- Add exact direct drift and four contribution planning modes over pinned
  snapshots and published targets, with explicit quality, constraints and bounds.
- Store durable internal planning requests, fenced delivery/consumer attempts and
  immutable result revisions through migration `20260907_0010`.
- Add six bounded API operations, four MCP tools and authenticated drift/planner
  pages with preserved edits, revision history and canonical server results.
- Accept P2-02 at `f78c9d2917c3ce8c93f9ae5631390c59616abc82` after full local/CI
  gates, eight source/history/image scans, all four planning modes and a fresh
  seven-service restart with immutable revision and lost-message recovery proof.
  Phase 2 has two complete packages, six local rows and eleven scenarios; later
  packages and shared release predicates remain required.
- Isolate each browser fixture launch in its own disposable PostgreSQL database,
  including when CI supplies a database URL, so independent desktop/mobile runs
  retain the production owner quota without sharing earlier test reservations.

### Phase 2 virtual targets

- Accept P2-01 at `ecc75154397c8f9d7532fa2df8576846b60bae7c` with full local/CI
  gates, exact test mappings, fresh activation/restart evidence and eight
  source/history/image security scans. Three local rows and five scenarios are
  complete; the full Phase 2 release remains in progress.

- Add owner-scoped portfolios/templates and normalized hierarchical target versions
  with exact validation, explicit normalization, mappings, constraints and audit.
- Enforce immutable published content, optimistic/idempotent commands, scheduled
  activation and deterministic version comparison in PostgreSQL.
- Add fifteen typed API operations, generated strict TypeScript methods, the
  authenticated `/pies` editor and two atomic/scoped MCP target read tools.
- Preserve shared collection limits and Phase 1 economics; add adversarial,
  concurrent, migration, editor and browser regressions. Immutable P2-01
  acceptance is recorded separately; the complete Phase 2 release remains pending.

### Phase 2 design closure

- Accept the v0.2 design delta and eight ADRs for targets, provider isolation,
  deterministic optimization, source snapshots, entity normalization, reports,
  alert scheduling and internal MCP commands.
- Freeze the normalized data/API/provider/method/security/web/operations contracts,
  25-tool MCP registry, 29 local acceptance rows and 40 mandatory scenarios.
- Begin Phase 2 implementation with no completed packages; retain corrected
  Phase 1 evidence and Phase 3 `not_started`.

### Independent Phase 1 audit corrections

- Enforce hard collection membership quotas from the first traversal, bound source
  consumption to remaining capacity plus one, and roll back failed materialization
  through a savepoint without cursor or partial state.
- Select non-downloadable historical export metadata before fingerprinting and
  retention; ignore URL-only rotation and remove legacy top-level URL keys with
  migration `20260907_0008`.
- Add quota, concurrency, rollback, export-URL canary and migration regressions,
  with explicit post-generation contract/web/browser artifact scans in CI.
- Remove remaining Debian and bundled Node package-manager tooling from all six
  runtime images while retaining package inventory for vulnerability/license scans;
  add an executable image probe to local builds and the security image matrix.
- Close both audit findings at `99df47b6633791c3900a52f46f56d48be922a436` after all local/CI,
  security, browser, and Compose restart gates pass; preserve the exact evidence in
  [the audit correction record](docs/implementation/PHASE_1_AUDIT_CORRECTIONS.md).

### Changed

- Fast-forwarded the existing Phase 1 implementation into the authoritative `main`
  history, retired the unaccepted alternate delivery policy, and added executable
  validation that rejects non-`main` repository workflow instructions.
- Corrected refresh dispatch with atomic ingestion-run/outbox persistence, leased
  at-least-once publication, deterministic task identity, bounded retry/backoff,
  crash recovery, dispatcher readiness, and outbox telemetry.
- Corrected refresh idempotency so a key is bound to canonical requested semantics;
  identical retries coalesce while mismatched mode or scope returns the stable
  `IDEMPOTENCY_KEY_REUSED` conflict without another publication.
- Replaced mutable offset/capped collection behavior with filter-bound opaque keyset or
  immutable-query cursors, complete SQL filtering/counts, dedicated service queries,
  nine-tool MCP parity, and route-specific URL pagination in the web application.
- Completed owner-scoped broker connection, canonical instrument/listing, authorized
  snapshot, core performance, reconciliation, and data-quality application contracts.
- Hardened Phase 1 evidence validation so acceptance-row states, external-gate states,
  machine-readable readiness, counts, and remaining conditions are bound fail-closed;
  adversarial governance regressions cover relabeling and false readiness promotion.

### Added

- Phase 1 mixed Python/TypeScript monorepo with pinned runtimes, locked dependencies, unified Make targets, CI, and generated-contract drift checks.
- Canonical exact-decimal financial domain, PostgreSQL migrations/repositories, durable ingestion, immutable provenance, ledger, reconciliation, snapshots, and Phase 1 accounting/allocation.
- Strict GET-only Trading 212 adapter with an exact ten-capability allowlist, fail-before-transport method rejection, typed provider schemas, pagination, bounded retry, redaction, and rate coordination.
- Authenticated `/api/v1`, generated TypeScript client, responsive Phase 1 web application, and explicit freshness/data-quality/unavailable states.
- Authenticated Streamable HTTP MCP gateway with nine frozen read-only tools and a versioned portfolio-overview widget.
- Non-root application containers, local Compose orchestration, deterministic synthetic seed, observability hooks, external Demo smoke tool, and operations runbooks.
- Phase 1 implementation, acceptance, and validation evidence ledgers.
- Alembic revisions `20260901_0004` through `20260901_0007` for the durable refresh
  outbox/request semantics, safe credential state, immutable collection-query snapshots,
  and active external-cash-flow revisions.
- Mode-aware transaction incrementals with a persisted high-water mark, seven-day
  overlap, stable cursor/filter validation, monotonic empty-page behavior, and safe
  full-replay/deduplication fallback for history contracts without a time filter.
- Provenance-bearing explicit FX materialization with fail-closed missing-FX behavior.
- Isolated API-backed Compose acceptance evidence covering authenticated desktop/mobile
  web rendering, exact API/MCP parity, durable queued-run recovery, full-stack restart,
  canonical-state retention, and local latency smoke measurements.
- Retained synthetic immutable quantity/cash mismatch acceptance fixture propagated
  through PostgreSQL, REST, MCP, and the actual API-backed desktop/mobile web quality view.
- Architecture Design Freeze v0.1.
- Product, scope, architecture, domain/data, API/service, ingestion, integration, calculation, reconciliation, security, testing, deployment, and operations contracts.
- Accepted ADRs for read-only safety, stack, persistence, deterministic finance, provider boundaries, shared backend, direct-main workflow, and three-phase delivery.
- Complete three-phase implementation roadmap.
- Detailed Phase 1 work packages P1-01 through P1-12 and global acceptance checklist.
- Master Phase 1 Codex implementation prompt.
- Human- and machine-readable project status/progress.

### Security

- Added repository-wide Trading 212 boundary enforcement, credential canary/redaction
  tests, authorization negatives, dependency/secret scans, deterministic pinned Semgrep
  CE rules without external uploads, and Trivy filesystem/container scanning workflows.
- Added hardened PostgreSQL `18.6` and Redis `8.10.1` images with patched OpenSSL
  packages, unprivileged runtime users, removal of unused `gosu`/snake-oil key material,
  and minimized application runtimes without package installers.
- Verified at immutable evidence SHA `e13916eca34d8e3be1ed130248d6c3d1ed7e3869`
  that the secret canary is absent from API/worker/MCP/web logs and application image
  filesystems and that the pinned Semgrep, dependency, secret, Trivy filesystem, and
  hardened-image gates pass.
- Verified hardened PostgreSQL/Redis disposable-volume startup as their unprivileged
  users and non-root application runtime probes after package-manager removal. The API,
  worker, MCP, web, hardened PostgreSQL, and hardened Redis images passed Trivy `0.74.0`
  high/critical vulnerability and secret scans with no findings.
- Verified Trivy filesystem vulnerability/secret/misconfiguration/license scanning, a
  clean complete-history Gitleaks scan, and deterministic repository-local Semgrep with
  zero findings. All workflow actions and external Docker base images are immutable
  SHA/digest pinned.
- Corrected the time-bounded LGPL policy entry to Trivy `0.74.0`'s nested
  `license.ignored` schema, then reran the fresh-checkout filesystem/config/license gate.
- Trading 212 integration frozen as exact GET-only/default-deny.
- Broker order/Pie mutation, generic proxy, autonomous trading, and credential exposure explicitly prohibited.

## Planned releases

### [0.1.0] — Phase 1: Trusted Foundation

Monorepo, provider ingestion, canonical history, reconciliation, snapshots, core accounting/allocation, API, web foundation, MCP tools, and operational baseline.

Implementation is complete on `main`, all 24 locally executable acceptance rows passed,
and all fourteen mandatory synthetic scenarios have evidence at immutable commit
`99df47b6633791c3900a52f46f56d48be922a436`. The final evidence includes 85% Python
coverage, 371 isolated Python tests, 73 migration/integration tests, 22 web unit tests,
32 synthetic Playwright tests, 6 API-backed Playwright tests, Alembic head
`20260907_0008`, and exactly nine MCP tools. Release readiness remains
`blocked_external` for the Demo smoke, production host/identity/secret-manager selection,
and public HTTPS/OAuth MCP plus ChatGPT registration. Real-provider opening-history
coverage remains `unavailable_explicit` with limitation reporting complete. Trading 212
Live is disabled and untested, not another Phase 1 gate.

### [0.2.0] — Phase 2: Portfolio Intelligence

Virtual Pies/targets, contribution optimization, full performance/benchmarks, X-ray, reports, alerts, and premium analytical interfaces.

Status: `in_progress`; P2-01 through P2-03 complete (3/10 packages).

### [1.0.0] — Phase 3: Premium Intelligence and Productization

Advanced risk/scenarios/goals, research cockpit, rich ChatGPT UI, PWA polish, premium providers, and production hardening.

Status: `not_started`.
