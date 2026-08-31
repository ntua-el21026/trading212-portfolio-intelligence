# Changelog

All notable project changes are recorded here. The project follows semantic versioning once implementation releases begin.

## [Unreleased]

### Added

- Architecture Design Freeze v0.1.
- Product, scope, architecture, domain/data, API/service, ingestion, integration, calculation, reconciliation, security, testing, deployment, and operations contracts.
- Accepted ADRs for read-only safety, stack, persistence, deterministic finance, provider boundaries, shared backend, direct-main workflow, and three-phase delivery.
- Complete three-phase implementation roadmap.
- Detailed Phase 1 work packages P1-01 through P1-12 and global acceptance checklist.
- Master Phase 1 Codex implementation prompt.
- Human- and machine-readable project status/progress.

### Security

- Trading 212 integration frozen as exact GET-only/default-deny.
- Broker order/Pie mutation, generic proxy, autonomous trading, and credential exposure explicitly prohibited.

## Planned releases

### [0.1.0] — Phase 1: Trusted Foundation

Monorepo, provider ingestion, canonical history, reconciliation, snapshots, core accounting/allocation, API, web foundation, MCP tools, and operational baseline.

### [0.2.0] — Phase 2: Portfolio Intelligence

Virtual Pies/targets, contribution optimization, full performance/benchmarks, X-ray, reports, alerts, and premium analytical interfaces.

### [1.0.0] — Phase 3: Premium Intelligence and Productization

Advanced risk/scenarios/goals, research cockpit, rich ChatGPT UI, PWA polish, premium providers, and production hardening.
