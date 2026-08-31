# Test Strategy and Quality Gates

**Status:** Accepted

## 1. Testing objectives

Tests must demonstrate financial correctness, read-only security, data integrity, contract compatibility, failure behavior, and cross-interface consistency—not merely execute lines.

## 2. Test layers

### Unit tests

Pure value objects, mapping helpers, calculations, policy decisions, error mapping, pagination state, and authorization rules.

### Property-based tests

Use Hypothesis or equivalent for:

- money/currency operation invariants;
- allocation weights and conservation;
- cash-flow/accounting identities;
- idempotent deduplication;
- rounding/contribution conservation;
- timestamp/order boundaries;
- reconciliation tolerance behavior.

### Contract tests

- Trading 212 exact method/path/query/DTO fixtures;
- provider error and rate-limit mapping;
- OpenAPI schemas/examples and generated client;
- MCP tool input/output schemas;
- database repository contracts;
- mock-provider parity.

### Integration tests

Run against real PostgreSQL and, where used, Redis/object storage substitutes. Cover migrations, transactions, concurrency/locks, ingestion, repositories, API and worker composition.

### End-to-end tests

- synthetic user/account setup;
- mock broker ingestion through dashboard/MCP result;
- refresh/reconciliation/data-quality flow;
- web navigation and responsive/accessibility behavior;
- deployed-container smoke path.

### Security/architecture tests

- only exact GET capabilities in broker registry;
- forbidden order/Pie mutation strings/interfaces absent;
- unknown path/method rejected before transport;
- provider transport inaccessible from domain/interfaces;
- secrets/canary strings absent from logs/errors/API/MCP/client bundles;
- auth/authz and cross-account denial;
- SSRF/open redirect/input limits;
- production configuration fails closed.

### Migration tests

- upgrade empty database to head;
- upgrade from previous release fixture;
- downgrade only where supported/declared;
- data-preservation assertions;
- schema model and migration consistency.

### Performance tests

Introduced with corresponding paths:

- dashboard/API query p95 and query count;
- ingestion throughput/rate coordination;
- large history pagination;
- report/risk/projection workloads;
- web bundle/runtime performance.

## 3. Fixture policy

- Synthetic only in source control.
- Stable, human-reviewable fixtures with semantic names.
- Include exact expected decimals and quality states.
- Provider recordings must be sanitized, minimized, scanned, and documented.
- Clocks and random seeds controlled.
- Avoid brittle full-response snapshots for dynamic metadata; assert contracts and important values.

## 4. Required Phase 1 fixture portfolios

1. Empty EUR account.
2. Simple single-currency buy-and-hold.
3. Fractional multi-position portfolio.
4. Multi-currency positions with FX.
5. Deposits/withdrawals plus buys/sells.
6. Dividends, fees, and withholding.
7. Partial historical coverage.
8. Duplicate and updated provider events.
9. Unmapped instrument.
10. Unsupported/unknown activity.
11. Reconciliation mismatch.
12. Stale sources.
13. Provider rate limit/transient outage/schema drift.
14. Cross-owner authorization attempt.

## 5. Quality gates

Repository commands must converge on:

```bash
make bootstrap
make format
make format-check
make lint
make typecheck
make test-unit
make test-property
make test-contract
make test-integration
make test-e2e
make test-security
make test-migrations
make docs-check
make security-check
make build
make test
```

`make test` runs all locally executable required suites or clearly documents intentionally separate expensive/credentialed markers.

## 6. CI stages

Recommended pipeline:

1. repository/docs/secret validation;
2. Python format/lint/type/unit/property;
3. TypeScript format/lint/type/unit/build;
4. PostgreSQL migration/integration;
5. provider/API/MCP contracts and security negatives;
6. web end-to-end/accessibility smoke;
7. dependency/static/container scans;
8. package/container build.

GitHub Actions runs on pushes to `main`. Direct-main policy increases the importance of local full gates and small commits; CI failure must be corrected immediately on `main` without history rewriting.

## 7. Coverage

Coverage is a diagnostic, not the sole gate. Establish sensible thresholds during P1-01, with stricter expectations for domain, calculations, broker allowlist, auth, and reconciliation. Any excluded path must be justified.

Mutation testing may be added for critical calculations/security policy when the baseline is stable.

## 8. External tests

Marked separately and never run with secrets on untrusted contexts:

- Trading 212 Demo smoke/contract tests;
- deployed remote MCP registration/invocation;
- production backup restoration;
- paid market/ETF provider tests.

A missing credential skips only the explicit external marker and remains a recorded acceptance gate. It does not skip mock/contract/security coverage.

## 9. Phase 1 release evidence

Phase completion records:

- exact commit SHA;
- toolchain/lockfile versions;
- passing command summary;
- migration head;
- OpenAPI/MCP contract versions;
- broker allowlist test evidence;
- reference calculation fixture results;
- secret/security scan results;
- container/local smoke evidence;
- Demo/deployment gates pass or explicitly remain external;
- known limitations and quality coverage.
