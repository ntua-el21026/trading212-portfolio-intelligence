# Changelog

All notable project changes are recorded here. The project follows semantic versioning once implementation releases begin.

## [Unreleased]

### Changed

- Fast-forwarded the existing Phase 1 implementation into the authoritative `main`
  history, retired the unaccepted alternate delivery policy, and added executable
  validation that rejects non-`main` repository workflow instructions.

### Added

- Phase 1 mixed Python/TypeScript monorepo with pinned runtimes, locked dependencies, unified Make targets, CI, and generated-contract drift checks.
- Canonical exact-decimal financial domain, PostgreSQL migrations/repositories, durable ingestion, immutable provenance, ledger, reconciliation, snapshots, and Phase 1 accounting/allocation.
- Strict GET-only Trading 212 adapter with an exact ten-capability allowlist, fail-before-transport method rejection, typed provider schemas, pagination, bounded retry, redaction, and rate coordination.
- Authenticated `/api/v1`, generated TypeScript client, responsive Phase 1 web application, and explicit freshness/data-quality/unavailable states.
- Authenticated Streamable HTTP MCP gateway with nine frozen read-only tools and a versioned portfolio-overview widget.
- Non-root application containers, local Compose orchestration, deterministic synthetic seed, observability hooks, external Demo smoke tool, and operations runbooks.
- Phase 1 implementation, acceptance, and validation evidence ledgers.
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
- Verified the working-tree secret canary is absent from API/worker/MCP/web logs and
  application image filesystems; final-SHA Semgrep, dependency, secret, Trivy filesystem,
  and hardened-image results remain pending.
- Verified hardened PostgreSQL/Redis disposable-volume startup as their unprivileged
  users and non-root application runtime probes after package-manager removal. The API
  worker, MCP, web, hardened PostgreSQL, and hardened Redis images all passed working-tree
  Trivy `0.74.0` high/critical vulnerability and secret scans with no findings.
- Verified working-tree Trivy filesystem vulnerability/secret/misconfiguration/license
  scanning, a clean pre-evidence Gitleaks history scan, and deterministic Semgrep over
  142 targets with zero findings. All workflow actions and external Docker base images
  are immutable SHA/digest pinned; the immutable `main`-SHA CI rerun remains pending.
- Trading 212 integration frozen as exact GET-only/default-deny.
- Broker order/Pie mutation, generic proxy, autonomous trading, and credential exposure explicitly prohibited.

## Planned releases

### [0.1.0] — Phase 1: Trusted Foundation

Monorepo, provider ingestion, canonical history, reconciliation, snapshots, core accounting/allocation, API, web foundation, MCP tools, and operational baseline.

Implementation and isolated local runtime/restart evidence are present on `main`. All
fourteen mandatory synthetic scenarios have
complete working-tree evidence; scenario 8's synthetic fixture does not claim real
Trading 212 opening-history coverage. Final release-SHA validation, pushed-SHA security
jobs, and owner review remain pending. Real Trading 212 Demo and deployed ChatGPT
validation remain explicitly external.

### [0.2.0] — Phase 2: Portfolio Intelligence

Virtual Pies/targets, contribution optimization, full performance/benchmarks, X-ray, reports, alerts, and premium analytical interfaces.

### [1.0.0] — Phase 3: Premium Intelligence and Productization

Advanced risk/scenarios/goals, research cockpit, rich ChatGPT UI, PWA polish, premium providers, and production hardening.
