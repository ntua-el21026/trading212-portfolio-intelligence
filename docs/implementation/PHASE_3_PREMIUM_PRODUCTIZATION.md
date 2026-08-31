# Phase 3 — Premium Intelligence and Productization

**Status:** Accepted roadmap; implementation begins only after Phase 2 acceptance  
**Target release:** `1.0.0`

## Objective

Complete the premium product with advanced risk/scenario/projection/goal capabilities, portfolio-aware research, rich ChatGPT UI, installable PWA polish, premium provider support, extension readiness, and production-grade security, reliability, performance, and operations.

## Work packages

### P3-01 — Advanced risk analytics

- aligned return-series engine;
- volatility/downside deviation/rolling metrics;
- drawdowns;
- beta/covariance/correlation;
- VaR and Expected Shortfall with explicit model/horizon/confidence;
- concentration/diversification;
- marginal/component risk contribution;
- robust missing-history/regularization/quality behavior;
- independent reference validation.

### P3-02 — Stress and scenario engine

- immutable versioned scenario definitions;
- entity/sector/region/currency/factor shock mapping and precedence;
- deterministic first-order scenario results;
- historical replay with explicit assumptions;
- coverage/unresolved exposure/residual;
- scenario editor, comparison, API/MCP/report integration.

### P3-03 — Monte Carlo and goal planning

- versioned assumption sets;
- reproducible seeded simulation engine;
- contributions, contribution growth/pauses, lump sums, withdrawals, inflation, fees, rebalancing;
- nominal/real outputs, percentiles, shortfall and target probabilities;
- goal definitions and sensitivity analysis;
- strict distinction between observed history and assumptions;
- resource/performance limits and asynchronous jobs.

### P3-04 — Research cockpit

- portfolio-ranked companies/events by effective exposure;
- saved notes, thesis, risks, catalysts, thesis-break conditions;
- cited source records and dates;
- material-change review workflow;
- explicit separation of source facts, deterministic portfolio facts, and model synthesis;
- prompt-injection-safe ingestion and no execution linkage;
- privacy/retention/source-license controls.

### P3-05 — Rich ChatGPT UI

- accessible Apps SDK portfolio card;
- allocation/target/drift and contribution-plan views;
- performance/benchmark chart;
- X-ray explorer;
- risk/scenario/projection/goal resources;
- research summary resources;
- responsive/reduced-motion/text alternatives;
- tool/resource contract, visual, and interaction tests.

### P3-06 — PWA and premium product polish

- installable responsive PWA;
- polished information architecture and command palette/search;
- saved dashboard layouts/views;
- offline-safe shell and explicit stale-data behavior;
- notification UX where configured;
- complete design system, accessibility audit, visual regression;
- performance/bundle/core-web-vitals optimization.

### P3-07 — Premium data providers

- production market/FX/ETF/reference/research adapters selected by evidence and licensing;
- provider failover/coverage comparison/cost controls;
- immutable snapshots and provenance;
- entitlement/license-aware export;
- adapter contract suites and operational dashboards.

### P3-08 — Multi-account and multi-broker readiness

- prove canonical domain can host another broker adapter without calculation rewrites;
- account aggregation and ownership boundaries where enabled;
- capability/coverage matrix;
- no dilution of read-only safety for Trading 212;
- migration/performance/security review.

This package may stop at verified readiness/second mock adapter if adding a real broker is not justified.

### P3-09 — Security, performance, and resilience hardening

- structured threat-model review/penetration test;
- SBOM, image signing/provenance, hardened least-privilege runtime;
- dependency/license/container/infrastructure gates;
- load/performance budgets and query/job optimization;
- chaos/failure tests for providers/workers/database/cache;
- backup restore and incident exercises;
- privacy deletion/retention/export hardening;
- SLOs and operational dashboards.

### P3-10 — Release candidate and final acceptance

- clean production-like installation and migration;
- exact release evidence and runbooks;
- end-to-end web/MCP/report parity;
- external provider/account/deployment validation;
- accessibility/security/performance/recovery acceptance;
- known-limitations statement;
- `1.0.0` release notes and status.

## Exit criteria

- Advanced analytics independently validate and expose assumptions/quality.
- Scenario and projection runs are versioned/reproducible.
- Research content cannot change policy, authorize tools, or trigger execution.
- Rich ChatGPT UI remains a presentation over canonical tools.
- PWA meets accessibility/performance targets on key devices.
- Premium-provider data use respects entitlement and failure behavior.
- Restore and incident exercises pass.
- No unresolved critical/high security issue.
- Production monitoring/SLOs and operational ownership are defined.
- The exact `1.0.0` SHA is reproducibly buildable and documented.
