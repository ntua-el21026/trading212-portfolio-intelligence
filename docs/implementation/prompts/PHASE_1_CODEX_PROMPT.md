# Master Codex Prompt — Phase 1: Trusted Foundation

**Status:** Historical execution prompt retained for reproducibility
**Validated implementation SHA:** `e13916eca34d8e3be1ed130248d6c3d1ed7e3869`
**Current authority:** `main`; Phase 2 and Phase 3 are `not_started`

Phase 1 has completed all locally executable acceptance at the validated implementation
SHA. Do not replay this prompt as a new implementation request or use it to begin a later
phase. The four remaining external conditions are recorded in the current status and
acceptance evidence.

The original execution prompt is retained below for auditability and reproducibility.

```text
We are implementing Phase 1 of the private repository:

ntua-el21026/trading212-portfolio-intelligence

Act as the principal/staff engineer responsible for architecture, backend, data engineering, financial correctness, security, frontend foundations, MCP integration, testing, operations, documentation, and direct commits.

============================================================
0. EXECUTION MODE
============================================================

This is a complete implementation task, not a planning-only, audit-only, or scaffolding-only task.

Inspect current `main` first, record its starting SHA, and implement the entire Phase 1 Trusted Foundation. Continue autonomously through every locally resolvable work package. Build, test, document, and commit coherent increments directly to `main`.

Repository workflow is main-only:

- work directly on `main`;
- do not create a branch or pull request;
- do not use a detached worktree for final changes;
- do not treat task-local examples, historical records, or release labels as workflow
  exceptions;
- do not force-push, reset shared history, rebase published commits, amend published commits, or rewrite history;
- synchronize/re-read latest `main` before starting and immediately before every commit;
- use small coherent fast-forward commits with precise Conventional Commit messages;
- run every relevant real quality gate before each commit;
- if another commit appears on `main`, inspect and integrate it safely before proceeding.

Do not stop after a plan, scaffolding, one vertical slice, or partial implementation. Continue until every locally executable Phase 1 criterion is satisfied or a genuine external/safety blocker remains that cannot be represented by a secure port, deterministic mock, fixture, feature gate, or explicit external validation state.

Do not ask routine implementation, naming, formatting, dependency, schema, test, or UX questions. Resolve them from repository authority and sound engineering judgment. Ask only when a required external credential/domain/provider decision or an irreconcilable higher-authority conflict genuinely blocks safe progress.

============================================================
1. SOURCE OF TRUTH — READ BEFORE CODING
============================================================

Treat current `main` as the source of truth. Read and inspect, in order:

1. `AGENTS.md`
2. `README.md`
3. `docs/DESIGN_INDEX.md`
4. `docs/DESIGN_FREEZE_V0_1.md`
5. `docs/DOCUMENT_GOVERNANCE.md`
6. `docs/PRODUCT_REQUIREMENTS.md`
7. `docs/SCOPE_AND_NON_GOALS.md`
8. `docs/SYSTEM_ARCHITECTURE.md`
9. `docs/architecture/DOMAIN_AND_DATA_MODEL.md`
10. `docs/architecture/API_AND_SERVICE_CONTRACTS.md`
11. `docs/architecture/BACKGROUND_JOBS_AND_INGESTION.md`
12. `docs/integrations/TRADING212_API_CONTRACT.md`
13. `config/contracts/trading212-read-allowlist.yaml`
14. `docs/integrations/CHATGPT_MCP_APP.md`
15. `docs/integrations/PROVIDER_ADAPTERS.md`
16. `docs/analytics/FINANCIAL_CALCULATION_POLICY.md`
17. `docs/analytics/PERFORMANCE_ACCOUNTING.md`
18. `docs/analytics/DATA_QUALITY_AND_RECONCILIATION.md`
19. `docs/security/SECURITY_ARCHITECTURE.md`
20. `docs/security/PRIVACY_RETENTION_AUDIT.md`
21. `docs/engineering/ENGINEERING_STANDARDS.md`
22. `docs/engineering/TEST_STRATEGY.md`
23. `docs/engineering/DEPLOYMENT_OPERATIONS.md`
24. `docs/implementation/MASTER_IMPLEMENTATION_PLAN.md`
25. `docs/implementation/PHASE_1_TECHNICAL_BASELINE.md`
26. `docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md`
27. `docs/implementation/PHASE_1_EXECUTION_MANIFEST.md`
28. `docs/implementation/PHASE_1_ACCEPTANCE_MATRIX.md`
29. `docs/implementation/PHASE_1_READINESS_REVIEW.md`
30. every accepted ADR under `docs/adr/`
31. `PROJECT_STATUS.md`
32. `PROJECT_STATUS.json`
33. `PROJECT_PROGRESS.json`
34. `VALIDATION_REPORT.md`

Then inspect the entire current tree, recent history, workflows, configuration, generated artifacts, tests, and any code already present. Do not assume the repository still contains only documentation.

Use the precedence in `docs/DESIGN_INDEX.md`. `PHASE_1_TECHNICAL_BASELINE.md` is authoritative for runtime/toolchain versions. The human Trading 212 contract and machine allowlist must agree exactly. Correct lower-authority drift in the same coherent commit; do not silently violate higher authority.

Before coding, run:

python scripts/validate_repository.py

If it fails, repair the documentation/contract baseline first and commit that repair before implementation.

============================================================
2. NON-NEGOTIABLE INVARIANTS
============================================================

These are hard constraints:

1. Trading 212 is strictly read-only, fixed-allowlist, and default-deny.
2. Implement exactly these ten GET capabilities and no others:
   - GET `/equity/account/summary`
   - GET `/equity/metadata/instruments`
   - GET `/equity/metadata/exchanges`
   - GET `/equity/positions`
   - GET `/equity/orders`
   - GET `/equity/orders/{order_id}`
   - GET `/equity/history/orders`
   - GET `/equity/history/transactions`
   - GET `/equity/history/dividends`
   - GET `/equity/history/exports`
3. The GET exports capability observes existing metadata/status only. Do not implement export creation.
4. Do not implement any broker `POST`, `PUT`, `PATCH`, or `DELETE`; market/limit/stop/stop-limit orders; cancellation/amendment; Pie mutation; transfers/payments; CFDs; or any broker write.
5. Do not expose a generic HTTP request, arbitrary URL/path, SQL, filesystem, shell, or broker proxy through API, MCP, web, configuration, or application services.
6. Unknown capability/method/path/query parameter must fail before transport invocation. Do not probe alternate endpoints.
7. Demo is the default Trading 212 environment. Live is explicit and remains read-only.
8. Broker/auth secrets are server-side only. Never commit, print, log, trace, serialize, return, render, snapshot, or include them in errors/reports/artifacts.
9. Authoritative money, quantity, price, FX, weights, ratios, and calculations use exact Decimal/NUMERIC representations. Never construct Decimal from float.
10. Every monetary value has a currency; cross-currency calculation requires explicit sourced FX.
11. Every internal instant is timezone-aware UTC; reject naive datetimes at boundaries.
12. Missing, zero, partial, stale, estimated, unreconciled, unavailable, and failed are distinct states.
13. Provider DTOs remain isolated from canonical domain/application/interface contracts.
14. Ingestion, pagination, replay, checkpoints, durable refresh dispatch, jobs,
    migrations, and retries are idempotent and crash-safe. No committed refresh may
    depend on an in-request best-effort broker publication.
15. Every material result includes method/version, valuation/source times, reporting currency, provenance/coverage, assumptions, quality, and warnings.
16. Deterministic code performs authoritative financial calculations. The model invokes/explains typed tools only.
17. API, web, MCP, workers, and reports use the same canonical application services and calculation engine.
18. No Phase 2/3 feature is presented as implemented in Phase 1. Only typed extension ports, schemas, and disabled/inert hooks explicitly required by Phase 1 are allowed.
19. No autonomous or assisted live trade execution exists anywhere.

Add architecture, static, contract, runtime-negative, authorization, and secret-canary tests that prove these invariants.

============================================================
3. PHASE 1 OBJECTIVE
============================================================

Deliver release-quality Phase 1 (`0.1.0`): a secure, deterministic, runnable monorepo that uses a synthetic provider by default and can, when the user later supplies read-only Demo credentials, ingest Trading 212 observations; persist canonical auditable history; reconcile positions/cash/activity; create immutable historical snapshots; calculate trustworthy core accounting, direct allocation, and coverage-gated performance; and expose consistent results through a versioned API, responsive premium web foundation, authenticated remote MCP server, and operational workers.

Implement all P1-01 through P1-12 in `PHASE_1_TRUSTED_FOUNDATION.md`. Do not reduce or reinterpret their scope. Stop after Phase 1; do not begin Phase 2.

============================================================
4. AUTHORITATIVE TECHNOLOGY BASELINE
============================================================

Use:

- Python `3.13.x`
- `uv` workspace and committed `uv.lock`
- FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3, async `httpx`
- Celery 5.6 for background execution with application-level idempotency/checkpoints
- official MCP Python SDK/current supported FastMCP primitives and Streamable HTTP-compatible remote transport
- PostgreSQL `18.x` as system of record
- optional Redis `8.x` for local job/lock/cache/rate coordination, never authoritative financial storage
- Node.js `24.x LTS`
- pnpm `10.x` workspace and committed lockfile
- current compatible stable Next.js and React, strict TypeScript
- generated TypeScript API client/contracts
- pytest, pytest-asyncio, Hypothesis, Ruff, strict mypy
- Vitest, Testing Library, Playwright
- Docker Compose and GitHub Actions on pushes to `main`

During P1-01 verify primary official compatibility, lock exact supported versions, pin runtime/tool versions, avoid floating `latest` release images, and record consequential deviations in an accepted ADR before depending on them.

============================================================
5. REQUIRED IMPLEMENTATION SEQUENCE
============================================================

P1-01 — Repository, workspace, toolchains, local stack, and CI
P1-02 — Shared contracts, value objects, domain invariants, and quality/provenance types
P1-03 — PostgreSQL schema, repositories, constraints, and migrations
P1-04 — Trading 212 exact GET-only adapter, DTOs, mapping, retry/rate/error policy
P1-05 — Full/incremental ingestion, pagination, checkpoints, leases, rate coordination
P1-06 — Ledger/activity model, reconciliation, discrepancy records, immutable snapshots
P1-07 — Core accounting, P/L coverage, direct allocation, and coverage-gated performance
P1-08 — Authentication, authorization, secret interfaces, redaction, audit/security controls
P1-09 — Versioned API, OpenAPI, generated TypeScript client, stable errors/pagination
P1-10 — Responsive accessible premium Phase 1 web application foundation
P1-11 — Authenticated bounded MCP gateway and core ChatGPT tools
P1-12 — Deployment, observability, scans, synthetic E2E, acceptance evidence, release prep

After each work package:

- run every relevant format/lint/type/unit/property/contract/integration/migration/security/build/E2E gate;
- update docs when implementation resolves a detail;
- update `PROJECT_PROGRESS.json` accurately;
- update `PROJECT_STATUS.md` and `PROJECT_STATUS.json` when state materially changes;
- commit directly to `main` with a coherent Conventional Commit message;
- verify the pushed head and CI before continuing.

Do not mark a package complete without its acceptance evidence.

============================================================
6. REPOSITORY AND DEVELOPER EXPERIENCE
============================================================

Create the documented monorepo boundaries. Provide working root commands—never no-op success placeholders—including functional equivalents of:

make bootstrap
make format
make format-check
make lint
make typecheck
make test-unit
make test-property
make test-contract
make test-integration
make test-migrations
make test-security
make test-e2e
make docs-check
make security-check
make build
make test
make dev

A clean clone must bootstrap from lockfiles, start PostgreSQL/optional Redis, migrate, seed a deterministic synthetic portfolio, and run API, worker, MCP, and web through documented commands. Commit migrations and generated contracts. Never commit secrets, real account data, caches, virtual environments, node_modules, local databases, private reports, or build output.

============================================================
7. DOMAIN, PERSISTENCE, AND INGESTION
============================================================

Implement canonical types/entities for principals/owners, broker connections/accounts using opaque secret references, instruments/listings/identifiers, Money/Currency/Quantity/Price/FxRate/ratios/time ranges, provenance/source records/fingerprints, ingestion runs/checkpoints/coverage/quality/warnings, canonical transactions/cash flows/dividends/order observations/current positions, immutable snapshots/components, reconciliation runs/discrepancies, calculation metadata/registry, and audit events.

Preserve provider-reported versus derived values. PostgreSQL is authoritative. Use constraints and transactions to enforce idempotency and ownership boundaries.

Implement full/incremental ingestion with exact typed capabilities, capability-specific pagination, safe overlap, deterministic deduplication, durable checkpoints after atomic success, leases/heartbeats/coalescing, bounded retries/backoff/jitter, account/environment rate coordination, partial aggregate quality, repeated-page/loop/max-bound detection, crash/restart/replay safety, strict schema-drift handling, and a deterministic synthetic/replay provider.

Persist every refresh run and exactly one bounded, non-secret, fixed
`portfolio.refresh` outbox event in the same PostgreSQL transaction. The API returns the
durable queued run after commit and does not call Celery for correctness. Add an
independently scheduled dispatcher that claims with `FOR UPDATE SKIP LOCKED`, leased
claims and expiry, publishes with a deterministic run-derived task ID, retries with
bounded backoff and sanitized errors, recovers expired ambiguous claims, and never
publishes an arbitrary task/payload. The worker must validate event/run/account/request
metadata before execution. At-least-once delivery, including a crash after broker
acceptance but before outbox acknowledgement, must retain one logical run and idempotent
source/canonical/economic/snapshot state. Deployed readiness requires a live dispatcher;
expose pending count, oldest pending age, attempts/failures, recovered claims, and queued
runs without a deliverable event.

Bind each account-scoped idempotency key to a canonical requested fingerprint containing
owner/account, requested mode, normalized requested capabilities, create-snapshot
behavior, and request-schema version; exclude correlation ID. Store requested semantics
separately from promoted effective semantics. An identical retry in any lifecycle state
returns the same run. Different requested semantics on the same account/key fail with
sanitized `IDEMPOTENCY_KEY_REUSED` and HTTP `409`, publish nothing, and reveal no prior
request detail. Enforce PostgreSQL/synthetic and concurrent-request parity.

The correction migration sequence is linear through `20260901_0007`: transactional
outbox/request identity (`0004`), explicit unconfigured credential state (`0005`),
immutable collection-query snapshots (`0006`), and active external-cash-flow revisions
(`0007`). Verify empty-to-head, repeated migration, downgrade policy, and ORM drift.

Use synthetic source-controlled fixtures only.

============================================================
8. FINANCIAL, RECONCILIATION, AND QUALITY REQUIREMENTS
============================================================

Implement and validate:

- position and portfolio market value;
- cash, invested, and total value;
- net external deposits/withdrawals over covered history;
- dividend/income summary;
- provider-reported versus internally derived acquisition/P&L fields kept distinct;
- direct position and cash allocation;
- immutable snapshot comparison;
- quantity and cash reconciliation using versioned tolerances;
- explicit residuals/discrepancies;
- coverage-gated XIRR/MWR, TWR, and/or Modified Dietz exactly as methodology permits;
- explicit unavailable/partial behavior when history, FX, fees, cost basis, valuations, or corporate actions are insufficient.

Deposits must never be counted as investment gain. Buys/sells are internal flows. Missing is never zero. Unmapped positions remain in total value as unclassified where possible. A result cannot have higher quality than material inputs.

Use hand-calculated reference fixtures and property-based tests.

============================================================
9. API, WEB, AND MCP
============================================================

API:

- implement documented `/api/v1` resources/use cases;
- implement typed authorized `ListBrokerConnections`, `SearchInstruments`,
  `GetInstrument`, `GetPortfolioSnapshot`, `GetCorePerformanceSummary`,
  `ListReconciliationDiscrepancies`, and `GetDataQualitySummary` use cases plus typed
  collection queries in both PostgreSQL and deterministic synthetic services;
- enforce authorization in routes and application services;
- serialize decimals as exact strings and datetimes as RFC 3339 UTC;
- use bounded versioned integrity-protected cursors bound to resource, authorized scope,
  deterministic sort, filter fingerprint, immutable result membership/read cutoff,
  last key/tie-breaker, and schema version; reject invalid/mismatched/tampered/expired
  cursors with stable sanitized 400-class errors;
- apply search/date/type predicates and deterministic ordering in PostgreSQL before
  `limit + 1` pagination over the complete eligible dataset; remove offset pagination,
  pre-pagination collection caps, in-memory collect-then-filter behavior, and confidently
  incorrect totals;
- high-level refresh accepts closed enums only and cannot inject provider paths;
- generate, validate, and compile the TypeScript client from OpenAPI/contracts.

Positions bind to one immutable portfolio snapshot and support market-value, direct-
weight, and ticker sorts plus bounded ticker/name search. Activity uses
`(occurred_at DESC, id DESC)` with bound date/type filters and immutable result
membership/read-cutoff behavior. Dividends use `(paid_on DESC, id DESC)` and full-period
database aggregation. Orders return latest observations at the bound cutoff. Snapshots
use `(valuation_at DESC, id DESC)`. Instruments search canonical metadata, include unheld
listings, and disambiguate canonical instrument from provider/environment listing.

Web:

- build an authenticated responsive accessible premium Phase 1 shell;
- implement overview, positions, activity/transactions, dividends, snapshots/history, reconciliation, and data-quality views;
- show basic direct allocation and portfolio-value/deposit history only when supported;
- render loading, empty, stale, partial, estimated, unreconciled, unavailable, and failed states;
- display source timestamp, calculation method/version, reporting currency, quality, and warnings;
- perform no authoritative financial arithmetic in the browser;
- use route-specific typed server loaders for overview, holdings, activity, dividends,
  snapshots, quality/reconciliation, synchronization, and settings/connections;
- preserve cursor/filter state in safe URL query state and expose accessible page/load-
  more navigation for holdings, activity, dividends, snapshots, and discrepancies so
  browser back/forward works;
- label overview collections as bounded previews with returned/full counts and links to
  complete views; request largest holdings using market-value/direct-weight sorting;
- do not add Phase 2 optimizer/Pie/X-ray or Phase 3 risk/research UI.

MCP/ChatGPT:

- use the current official remote MCP approach verified from primary docs;
- require authentication outside local test mode;
- expose exactly the nine-tool Phase 1 registry documented in the repository;
- invoke canonical application services and return bounded structured outputs with common metadata;
- perform position search/sort, transaction date/type filtering, dividend full-period
  aggregation, direct snapshot-by-ID lookup, and data-quality evaluation in dedicated
  application services before bounding the returned tool payload;
- mark an incomplete aggregate `partial`; a warning cannot leave it `fresh`;
- add schema, auth, authorization, negative, bounds, and API-parity tests;
- expose no arbitrary query/HTTP/SQL/filesystem/shell/broker-path tool;
- do not add a refresh tool to the fixed nine-tool Phase 1 registry;
- provide a minimal accessible Apps SDK summary resource only if it does not compromise core completion.

Remote ChatGPT registration/domain may remain an explicit external gate. Local MCP server, schemas, inspector/contract tests, and synthetic end-to-end flow must be complete.

============================================================
10. SECURITY, PRIVACY, OBSERVABILITY, AND OPERATIONS
============================================================

Implement local-only synthetic auth that cannot run in production; a fail-closed production auth adapter boundary; owner/account authorization and cross-account denial tests; secret-provider interface; centralized redaction; canary-secret tests; suitable CSRF/CORS/host/session/token protections; API/MCP request bounds and rate limits; structured logs/metrics/tracing hooks; liveness/readiness including independent refresh-dispatcher readiness; bounded outbox backlog/age/attempt/failure/recovery/orphan telemetry; job/provider/reconciliation telemetry without high-cardinality private labels; Dockerfiles/Compose; provider-neutral deployment examples; migration deployment process; backup/restore, incident, and credential-rotation runbooks; dependency/secret/static/container scans; least-privilege workflows; and non-root/minimal containers where practical.

Never claim compliance, privacy validation, Demo/Live connectivity, remote deployment, backup restoration, or security completion without exact evidence.

============================================================
11. MANDATORY TEST AND E2E EVIDENCE
============================================================

The final local/CI state must pass:

- Python format/lint/strict typing;
- TypeScript format/lint/strict typing/build;
- unit tests;
- property-based domain/financial tests;
- exact Trading 212 contract and pre-transport negative tests;
- ingestion restart/pagination/rate-limit/duplicate/partial/schema-drift tests;
- API commit-before-publication outbox restart, ambiguous broker-accepted duplicate
  delivery, expired-claim, concurrent dispatcher, bounded publication/consumer failure,
  semantic idempotency equality/conflict/concurrency, and dispatcher-readiness tests;
- PostgreSQL repository/integration/migration tests;
- ledger/reconciliation/snapshot/reference-calculation tests;
- API/OpenAPI/generated-client/auth/pagination/error tests;
- more-than-50, more-than-100, and more-than-10,000-row collection reachability; exact
  filtered totals; cursor scope/filter/sort/tamper/expiry; mutation-stability; unheld
  instrument; full-period MCP aggregation tests;
- MCP schema/auth/security/API-parity tests;
- web component/Playwright/accessibility/responsive tests;
- desktop/mobile URL cursor, page/load-more, browser-back, inserted-row stability,
  preview-count/largest-ordering, and horizontal-overflow tests;
- secret/dependency/static/container scans;
- documentation/link/JSON/allowlist/progress validation;
- clean build/container smoke;
- all 14 mandatory synthetic scenarios in `PHASE_1_EXECUTION_MANIFEST.md`.

A test command must not report success when it is a placeholder. The only conditions
that may remain external are:

- owner-run Trading 212 read-only Demo smoke requiring user credentials;
- production host, identity, and secret-manager selection;
- public HTTPS/OAuth MCP deployment and ChatGPT registration;
- real-provider opening-history limitations, reported explicitly rather than inferred
  from synthetic fixtures.

Record every external skip exactly. Everything else must run locally or in CI.

============================================================
12. DOCUMENTATION, STATUS, AND RELEASE EVIDENCE
============================================================

Keep docs, migrations, generated schemas/clients, code, tests, and status synchronized. Add an ADR before consequential architectural deviation. Update README/setup/run/test/deployment instructions. Keep `PROJECT_PROGRESS.json` machine-valid and evidence-based.

At P1-12 produce a final Phase 1 acceptance report containing:

- starting and final `main` SHAs;
- ordered commits and work packages;
- exact commands and results;
- CI links/status at final SHA;
- runtime/dependency versions and lockfiles;
- migration head `20260901_0007`, repeat/upgrade/downgrade-policy/ORM-drift evidence;
- OpenAPI/generated client/MCP schemas;
- exact ten-capability GET-only/default-deny proof;
- reference/property financial test results;
- API/web/MCP synthetic E2E and parity results;
- separate scenario 14 evidence for API commit-before-publication recovery, worker restart
  after confirmed publication, and full-stack retained state;
- security/redaction/scan results;
- known limitations and data coverage;
- explicit external-gate state;
- changelog/release notes for `0.1.0`.

Do not tag or claim `0.1.0` complete unless every locally executable acceptance row is complete and only documented external gates remain.

============================================================
13. STOPPING CONDITIONS
============================================================

Continue without seeking approval for ordinary decisions. Stop only for a genuine irreconcilable higher-authority conflict, a required external credential/domain decision, a safety violation, or a required unavailable tool after documented alternatives are exhausted.

When blocked:

- finish and commit all coherent safe work;
- leave `main` green and truthful;
- mark the exact package/acceptance row and status;
- provide evidence, attempted alternatives, and the smallest required user action;
- never fabricate data, credentials, tests, deployment, or completion.

When Phase 1 is complete, stop. Do not implement Phase 2.

============================================================
14. FINAL RESPONSE
============================================================

Return:

1. concise implementation summary by P1 package;
2. starting and final SHAs;
3. ordered commits;
4. exact test/build/scan/validation commands and outcomes;
5. architecture/security/financial invariants proven;
6. migration/API/client/MCP/web/E2E evidence;
7. external gates and known limitations;
8. confirmation that all changes were fast-forward commits directly to `main` and no Phase 2 work began.

Begin by inspecting current `main` and running the documentation validator. Then implement the full Phase 1.
```
