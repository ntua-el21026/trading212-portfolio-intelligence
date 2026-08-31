# Master Codex Prompt — Phase 1: Trusted Foundation

Copy the complete prompt below into Codex with the repository `ntua-el21026/trading212-portfolio-intelligence` selected.

```text
We are implementing Phase 1 of the private repository:

ntua-el21026/trading212-portfolio-intelligence

You have repository access. Work as the lead staff engineer responsible for architecture, backend, data engineering, financial correctness, security, frontend foundations, MCP integration, testing, documentation, and direct commits.

============================================================
0. EXECUTION MODE
============================================================

This is an implementation task, not a planning-only or review-only task.

Inspect the current `main` branch first, then implement the complete Phase 1 Trusted Foundation. Continue autonomously through all locally resolvable work packages. Build, test, document, and commit coherent increments directly to `main`.

Repository workflow is intentionally:

- work directly on `main`;
- do not create a branch;
- do not open a pull request;
- do not use a detached worktree for the final changes;
- do not force-push, reset, rebase, amend shared commits, or rewrite history;
- pull/re-read the latest `main` before starting and before every commit;
- make small coherent fast-forward commits;
- run the relevant complete quality gates before each commit;
- if another commit appears on `main`, inspect and integrate it safely before continuing.

Do not stop after scaffolding, a partial vertical slice, or a written plan. Continue until every locally executable Phase 1 acceptance criterion is satisfied, or until a genuine external blocker remains that cannot be represented by a safe interface, mock, fixture, or explicit validation gate.

Do not ask me routine implementation, naming, formatting, library, or UX questions. Resolve them from the repository's accepted documentation and sound engineering judgment. Ask only when an external credential, deployment domain, or incompatible requirement genuinely prevents further safe work.

============================================================
1. SOURCE OF TRUTH — READ BEFORE CODING
============================================================

Treat current `main` as the source of truth. Before changing code, inspect the complete repository and read, in this order:

1. `AGENTS.md`
2. `docs/DESIGN_INDEX.md`
3. `docs/DESIGN_FREEZE_V0_1.md`
4. `docs/DOCUMENT_GOVERNANCE.md`
5. `docs/PRODUCT_REQUIREMENTS.md`
6. `docs/SCOPE_AND_NON_GOALS.md`
7. `docs/SYSTEM_ARCHITECTURE.md`
8. `docs/architecture/DOMAIN_AND_DATA_MODEL.md`
9. `docs/architecture/API_AND_SERVICE_CONTRACTS.md`
10. `docs/architecture/BACKGROUND_JOBS_AND_INGESTION.md`
11. `docs/integrations/TRADING212_API_CONTRACT.md`
12. `docs/integrations/CHATGPT_MCP_APP.md`
13. `docs/integrations/PROVIDER_ADAPTERS.md`
14. `docs/analytics/FINANCIAL_CALCULATION_POLICY.md`
15. `docs/analytics/PERFORMANCE_ACCOUNTING.md`
16. `docs/analytics/DATA_QUALITY_AND_RECONCILIATION.md`
17. `docs/security/SECURITY_ARCHITECTURE.md`
18. `docs/security/PRIVACY_RETENTION_AUDIT.md`
19. `docs/engineering/ENGINEERING_STANDARDS.md`
20. `docs/engineering/TEST_STRATEGY.md`
21. `docs/engineering/DEPLOYMENT_OPERATIONS.md`
22. `docs/implementation/MASTER_IMPLEMENTATION_PLAN.md`
23. `docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md`
24. every accepted ADR under `docs/adr/`
25. `PROJECT_STATUS.md`
26. `PROJECT_PROGRESS.json`

Then inspect the current repository tree, Git history, configuration, workflows, tests, generated artifacts, and any code already present. Do not assume the repository still contains documentation only.

Document precedence is defined in `docs/DESIGN_INDEX.md`. When a lower-authority document or this prompt conflicts with the design freeze, accepted ADR, security/broker contract, or Phase 1 specification, follow the higher-authority repository document and correct the lower-authority text in the same coherent commit.

============================================================
2. NON-NEGOTIABLE SAFETY AND FINANCIAL INVARIANTS
============================================================

These are hard constraints, not suggestions:

1. Trading 212 is strictly read-only and default-deny.
2. Implement only the exact GET capabilities in `docs/integrations/TRADING212_API_CONTRACT.md`.
3. Do not implement market/limit/stop/stop-limit orders, cancellation, amendment, Pie mutation, transfers, exports requiring mutation, CFD operations, or any broker write.
4. Do not expose a generic HTTP request, arbitrary URL/path, SQL, filesystem, shell, or broker proxy through API, MCP, web, configuration, or internal application services.
5. Unknown method/path/query capability must be rejected before network transport is invoked.
6. Demo is the default Trading 212 environment. Live requires explicit configuration and remains read-only.
7. Broker/auth secrets are server-side only. Never commit, print, log, trace, return, serialize, render, snapshot, or include them in errors/reports/test artifacts.
8. Authoritative money, quantity, price, FX, weights, ratios, and calculations use exact Decimal/NUMERIC representations. Never use binary floating point as the source of truth and never create Decimal from float.
9. Every monetary value has an explicit currency. Cross-currency calculation requires an explicit sourced FX rate.
10. Every internal instant is timezone-aware UTC. Reject naive datetimes at boundaries.
11. Missing, unknown, zero, partial, estimated, stale, unreconciled, and failed are distinct states.
12. Provider DTOs remain isolated from canonical domain/application/interface contracts.
13. Ingestion, pagination, replay, checkpoints, jobs, and migrations must be idempotent and safe under retries/restarts/duplicates/partial failure.
14. Every authoritative calculation includes method/version, valuation/source timestamps, reporting currency, provenance/coverage, assumptions, quality state, and warnings.
15. Deterministic code performs all financial calculations. The language model only invokes and explains structured tools.
16. API, web, MCP, workers, and reports use the same canonical application services and calculation engine.
17. No Phase 2 or Phase 3 feature may be presented as implemented during Phase 1. Only documented extension interfaces and disabled/inert hooks are allowed.
18. No autonomous or assisted live trade execution exists anywhere.

Add automated architecture, static, contract, runtime-negative, and secret-canary tests that prove these constraints.

============================================================
3. PHASE 1 OBJECTIVE
============================================================

Deliver release-quality Phase 1 (`0.1.0`):

A secure, deterministic, runnable monorepo that can use a synthetic/mock provider and, when the user later supplies read-only Demo credentials, ingest Trading 212 account data; persist canonical auditable history; reconcile positions/cash/activity; create historical portfolio snapshots; calculate trustworthy core accounting, direct allocation, and coverage-gated performance; and expose consistent results through a versioned API, responsive web foundation, and authenticated remote MCP server.

The exact work packages and acceptance criteria are in:

`docs/implementation/PHASE_1_TRUSTED_FOUNDATION.md`

Implement all P1-01 through P1-12. Do not reduce or reinterpret their scope.

============================================================
4. REQUIRED IMPLEMENTATION SEQUENCE
============================================================

Use the dependency order below. You may refine commit grouping, but do not skip acceptance evidence.

P1-01 — Repository, workspace, toolchains, and CI
P1-02 — Shared contracts and domain values
P1-03 — PostgreSQL schema and migrations
P1-04 — Trading 212 strict read-only adapter
P1-05 — Ingestion, pagination, and rate-limit coordination
P1-06 — Ledger, reconciliation, and snapshots
P1-07 — Core accounting, P/L coverage, direct allocation, and performance summary
P1-08 — Authentication, authorization, secrets, and redaction
P1-09 — Versioned API and generated TypeScript client
P1-10 — Responsive accessible web application foundation
P1-11 — Authenticated MCP gateway and core ChatGPT tools
P1-12 — Deployment, observability, security hardening, E2E validation, and acceptance evidence

After each package:

- run all relevant format/lint/type/unit/property/contract/integration/security/migration/build checks;
- update documentation where implementation resolved a detail;
- update `PROJECT_PROGRESS.json` accurately;
- update `PROJECT_STATUS.md` when state materially changes;
- commit directly to `main` with a precise conventional commit message;
- re-read the new `main` state before continuing.

Do not mark a package complete before its acceptance criteria and tests pass.

============================================================
5. TECHNOLOGY BASELINE
============================================================

Follow the frozen architecture unless an accepted ADR is required:

- Python 3.13
- `uv` workspace and committed lockfile
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- asynchronous `httpx` provider I/O
- PostgreSQL 17
- optional Redis 7 for locks/cache/rate/job coordination, never the system of record
- current official MCP Python SDK / compatible FastMCP primitives and a ChatGPT-supported remote transport verified during implementation
- Node.js 22 LTS
- pnpm workspace and committed lockfile
- Next.js, React, strict TypeScript
- generated TypeScript API client/contracts
- pytest, pytest-asyncio where needed, Hypothesis, Ruff, strict mypy
- Vitest and Playwright
- Docker Compose for local dependencies
- GitHub Actions on every push to `main`

Verify current official compatibility and lock exact versions. Do not browse random tutorials or adopt unmaintained wrappers when primary documentation or the repository contract is available. Record any consequential implementation choice in an ADR before depending on it.

============================================================
6. REQUIRED REPOSITORY/DEVELOPER EXPERIENCE
============================================================

Create a coherent monorepo matching the documented boundaries. Exact physical names may be refined only if all documents are updated consistently.

Provide working root commands, not no-op placeholders, including functional equivalents of:

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
make dev

A clean clone must be able to bootstrap, start local PostgreSQL/optional Redis, migrate, seed a deterministic synthetic portfolio, and run API, worker, MCP, and web through documented commands.

Examples contain no credential values. Commit lockfiles and migrations. Do not commit caches, virtual environments, node modules, build output, local databases, secrets, or private reports.

============================================================
7. DOMAIN, DATA, AND INGESTION REQUIREMENTS
============================================================

Implement the canonical domain and persistence contracts, including:

- principals/owners;
- broker connections and accounts using opaque credential references;
- instruments and listings with stable provider identity and ISIN where available;
- Money/Currency/Quantity/Price/FxRate/ratio/time value objects;
- provenance, source records/fingerprints, ingestion runs, checkpoints, coverage, quality, warnings;
- canonical transactions, cash flows, dividends, read-only order observations, current positions;
- portfolio snapshots/components;
- reconciliation runs/discrepancies;
- calculation metadata/registry;
- audit events.

Preserve provider-reported and internally derived values distinctly.

Implement full/incremental read ingestion with:

- exact typed capabilities;
- capability-specific pagination;
- safe overlap and deduplication;
- durable checkpoint only after atomic commit;
- leases/heartbeats/coalescing;
- bounded retries/backoff/jitter;
- rate-limit coordination;
- partial capability results and aggregate quality;
- repeated-page/loop and max-bound detection;
- restart/crash/replay safety;
- strict schema drift behavior;
- deterministic synthetic mock/replay provider.

Do not use real user/account data in source-controlled fixtures.

============================================================
8. CORE FINANCIAL AND QUALITY REQUIREMENTS
============================================================

Implement and validate:

- position and portfolio market values;
- cash, invested, and total value;
- net external deposits/withdrawals over covered history;
- dividend/income summary;
- provider-reported versus internally derived acquisition/P&L fields kept distinct;
- direct position and cash allocation;
- portfolio snapshot comparison;
- quantity and cash reconciliation with versioned tolerances;
- reconciliation residuals/discrepancies;
- coverage-gated XIRR/MWR, TWR, and/or Modified Dietz exactly as the performance specification permits;
- explicit unavailable/partial behavior when history, FX, cost basis, fees, valuations, or corporate actions are insufficient.

Deposits must never be counted as investment gain. Buys/sells are internal flows. Missing is never zero. Unmapped positions remain in total value as unclassified where possible. No metric may be higher quality than its material inputs.

Use hand-calculated reference fixtures plus property-based tests. Cover every mandatory fixture and E2E scenario in the Phase 1 and test-strategy documents.

============================================================
9. API, WEB, AND MCP REQUIREMENTS
============================================================

API:

- implement the versioned resources/use cases in `docs/architecture/API_AND_SERVICE_CONTRACTS.md`;
- enforce authorization in application services and routes;
- exact decimal-string and RFC 3339 UTC serialization;
- cursor pagination, bounded filters, stable safe errors, correlation IDs;
- high-level refresh accepts only supported enums and cannot inject provider paths;
- generate/validate OpenAPI and a compiling TypeScript client.

Web:

- create a responsive, accessible, premium-quality foundation using only Phase 1 capabilities;
- authenticated shell and navigation;
- portfolio overview, positions, transactions/activity, dividends, snapshots/history, reconciliation, and data-quality views;
- basic direct allocation and portfolio-value/deposit history visualization only when supported;
- explicit loading, empty, stale, partial, estimated, unreconciled, and failed states;
- show source timestamp, calculation method/version, reporting currency, warnings;
- no duplicate authoritative financial arithmetic in the browser;
- no Phase 2 optimizer/Pie/X-ray or Phase 3 risk/research UI.

MCP/ChatGPT:

- use the current official supported remote MCP approach and verify it against primary documentation;
- require authentication outside local test mode;
- expose only the Phase 1 tool registry in `docs/integrations/CHATGPT_MCP_APP.md`;
- invoke canonical application services;
- return bounded structured results with common metadata;
- add schema, authorization, negative, and API-parity tests;
- no generic query/HTTP/SQL/filesystem tool;
- optional read-refresh tool accepts only a high-level enum and can be disabled;
- provide a minimal accessible Apps SDK summary resource only if it can be done cleanly without delaying core correctness.

A deployed ChatGPT registration/domain may remain an explicit external gate. The local MCP server, schemas, inspector/contract tests, and mock-data end-to-end flow must still be complete.

============================================================
10. SECURITY, PRIVACY, AND OPERATIONS
============================================================

Implement:

- local-only synthetic auth that cannot run in production;
- production authentication adapter boundary that fails closed when unconfigured;
- principal/owner/account authorization including cross-account denial tests;
- secret-provider interface, centralized redaction, canary-secret tests;
- CSRF/CORS/host/session/token protections appropriate to the selected auth mode;
- API/MCP request bounds and rate limits;
- structured logs, metrics, tracing hooks, health/readiness, job/provider/reconciliation telemetry;
- no high-cardinality/private metric labels;
- Dockerfiles/Compose and production-neutral deployment examples;
- migration deployment process;
- backup/restore, incident, and credential-rotation runbooks;
- dependency, secret, static-analysis, and container scanning;
- least-privilege GitHub Actions permissions;
- non-root/minimal containers where practical.

Never make a compliance, privacy, Demo, Live, deployment, backup, or security-validation claim without evidence.

============================================================
11. REQUIRED TEST AND VALIDATION EVIDENCE
============================================================

At minimum, the final `main` state must pass all locally executable equivalents of:

- Python format/lint/strict type checks;
- TypeScript format/lint/strict type/build checks;
- unit tests;
- property-based financial/domain tests;
- Trading 212 exact-contract and runtime-negative security tests;
- ingestion restart/pagination/rate-limit/duplicate/partial/schema-drift tests;
- PostgreSQL repository/integration/migration tests;
- ledger/reconciliation/snapshot/reference calculation tests;
- API/OpenAPI/generated-client/auth/pagination/error tests;
- MCP schema/auth/security/API-parity tests;
- web component/Playwright/accessibility/responsive smoke tests;
- end-to-end synthetic account flow;
- secret/dependency/static/container scans;
- documentation/link/JSON/YAML/progress validation;
- clean build and container smoke.

A test command must not report success if it is a placeholder or skipped without an explicit recognized external marker.

External markers may cover only:

- Trading 212 Demo smoke requiring user credentials;
- deployed remote ChatGPT registration/domain/auth;
- production backup/hosting checks not available locally.

Record exact skipped external gates. Everything else must run locally or in CI.

============================================================
12. DOCUMENTATION AND STATUS REQUIREMENTS
============================================================

Keep the repository self-documenting. During implementation:

- update authoritative docs when implementation resolves details;
- add ADRs before consequential architectural deviations;
- update README/local setup/run/test/deployment instructions;
- add API/MCP tool reference and runbooks;
- maintain CHANGELOG;
- update `PROJECT_PROGRESS.json` after every work package;
- update `PROJECT_STATUS.md` truthfully;
- create a Phase 1 acceptance/validation report at completion containing exact SHA, commands/results, migrations, contracts, quality/security evidence, limitations, and external gates.

Do not leave TODO/TBD placeholders for decisions you can safely resolve. Put genuinely external unresolved items in `docs/OPEN_QUESTIONS.md` with safe default and resolution evidence.

============================================================
13. COMMIT PLAN
============================================================

Use multiple coherent commits directly to `main`, broadly aligned to the work packages. Do not create one giant unreviewable commit and do not create dozens of meaningless micro-commits.

Before every commit:

1. inspect `git status` and diff;
2. fetch/pull/re-read current `main` and integrate any new commit safely;
3. run all relevant gates for the changed surface;
4. scan the diff for secrets/private data/generated noise;
5. update docs/progress;
6. commit with a precise conventional message;
7. verify the new commit and CI state when available.

Never force-push. If CI fails after a direct-main commit, immediately diagnose and correct it in a new coherent commit before continuing.

============================================================
14. STOPPING AND FINAL RESPONSE
============================================================

Continue until the Phase 1 global exit checklist is satisfied.

You may stop early only for a genuine blocker defined in the phase specification. Before stopping:

- commit all coherent passing work directly to `main`;
- leave main runnable and tests green;
- update progress/status truthfully;
- document the blocker, evidence, safe state, and exact required external action;
- do not claim Phase 1 complete.

When finished, return a precise implementation report containing:

1. final `main` commit SHA;
2. ordered commits created and their purpose;
3. repository architecture implemented;
4. Phase 1 work-package status P1-01 through P1-12;
5. exact validation commands and results;
6. database migration head;
7. API/OpenAPI and MCP tool contract summary;
8. proof of Trading 212 GET-only/default-deny boundary;
9. financial reference/property test summary;
10. web/MCP end-to-end status;
11. security/secret/redaction/scan status;
12. known limitations and data-quality coverage;
13. exact remaining external gates, if any;
14. whether Phase 1 is fully accepted and ready for Phase 2.

Begin now by inspecting the complete current `main` branch and documentation. Then implement Phase 1—not another plan.
```
