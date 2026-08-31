# Phase 1 — Trusted Foundation

**Status:** Approved for implementation  
**Target release:** `0.1.0`  
**Execution branch:** `main` only  
**Primary objective:** Build a secure, deterministic, runnable foundation that ingests read-only Trading 212 data into an auditable canonical portfolio model and exposes consistent core results through API, web, and MCP interfaces.

## 1. Scope

Phase 1 includes:

- monorepo/toolchain/CI bootstrap;
- canonical domain contracts and exact financial value objects;
- PostgreSQL schema/migrations/repositories;
- strict Trading 212 GET-only adapter;
- mock provider and synthetic fixtures;
- full/incremental ingestion with pagination, rate limits, checkpoints, and idempotency;
- transaction/cash-flow ledger, reconciliation, and historical snapshots;
- core accounting, P/L coverage, direct allocation, snapshot comparison, and conservative performance summary;
- authentication/authorization/secrets/redaction;
- versioned HTTP API and generated TypeScript client;
- premium-quality but intentionally bounded web foundation;
- remote MCP server with core portfolio tools and optional minimal resource;
- Docker/local environment, observability, CI/security checks, and phase acceptance evidence.

Phase 1 does not implement virtual Pies/targets, contribution optimization, ETF look-through, external market/benchmark analytics, full reports/alerts, advanced risk, scenarios, Monte Carlo, goals, research cockpit, or live trade execution.

## 2. Mandatory invariants

Every work package must preserve:

1. Trading 212 is strictly read-only and default-deny.
2. Only the ten exact GET capabilities in the broker contract may dispatch.
3. No order/Pie mutation or generic provider proxy exists.
4. Demo is default; Live requires explicit read-only configuration.
5. Secrets never reach source control, browser, MCP output, logs, traces, reports, or errors.
6. Money and authoritative ratios use exact decimal arithmetic; timestamps are UTC.
7. Provider DTOs do not leak into domain/application/interface contracts.
8. Ingestion and migrations are idempotent.
9. Missing/partial/stale/unreconciled data is explicit.
10. API, web, and MCP share canonical application services/calculations.
11. Work is committed directly and incrementally to `main` without force-push.
12. Phase status is not overstated when an external credential/deployment gate remains.

## 3. Target repository structure

Codex may refine names during P1-01 while preserving boundaries and updating architecture docs:

```text
apps/
  api/
  worker/
  mcp/
  web/
packages/
  domain/
  application/
  persistence/
  trading212/
  analytics/
  security/
  observability/
  api-contracts/
  ui/
infrastructure/
  docker/
  deployment/
  monitoring/
tests/
  fixtures/
  unit/
  property/
  contract/
  integration/
  e2e/
  security/
config/
scripts/
docs/
```

## 4. P1-01 — Repository, workspace, toolchains, and CI

### Deliverables

- Python 3.13 `uv` workspace and lockfile.
- Node.js 24/pnpm 10 workspace and lockfile.
- Application/package skeletons matching architecture boundaries.
- Root `Makefile` with discoverable commands.
- `.editorconfig`, `.gitignore`, `.dockerignore`, environment examples, lint/type/test configuration.
- Docker Compose for PostgreSQL 18 and optional Redis 8.
- Pre-commit or equivalent local checks without making them the only enforcement.
- GitHub Actions on every push to `main`.
- Documentation/link/JSON/YAML/secret validation.
- Baseline README/local development instructions.
- Architecture dependency test foundation.

### Required commands

At minimum establish functional equivalents of:

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
make test-security
make test-migrations
make docs-check
make security-check
make build
make test
make dev
```

Commands may become progressively complete as packages are added, but may not falsely return success while doing nothing. Placeholder commands must be explicit and eliminated before phase acceptance.

### Acceptance

- Clean bootstrap from documented prerequisites.
- Lockfiles committed and reproducible.
- Python/TypeScript hello-health components build/test.
- PostgreSQL starts and migrations command is wired.
- CI runs on direct pushes to `main` with least-privilege permissions.
- Secret scanning and docs validation active.
- No production credential values in examples.
- `PROJECT_PROGRESS.json` marks P1-01 complete with evidence.

### Suggested commits

1. `chore: bootstrap monorepo and toolchains`
2. `ci: add direct-main quality and security pipeline`
3. `docs: document reproducible local development`

## 5. P1-02 — Shared contracts and domain values

### Deliverables

- Typed `CurrencyCode`, `Money`, `Quantity`, `Price`, `FxRate`, ratio/percentage, UTC instant/date-range value objects.
- Canonical IDs and owner/broker connection/account/instrument/listing models.
- Provenance, calculation metadata, quality state, coverage, warning, and stable error taxonomy.
- Canonical transaction/dividend/order-observation/position/snapshot/reconciliation models.
- Serialization schemas and decimal/timezone policy.
- Calculation registry skeleton.
- Synthetic fixture builders.

### Acceptance

- No implicit float-to-money path.
- Cross-currency operations require explicit FX.
- Naive timestamps rejected.
- Missing/null is distinct from zero.
- Value objects immutable where appropriate.
- Domain package has no FastAPI, SQLAlchemy, Trading 212 transport, web, or MCP dependency.
- Unit/property tests cover precision, arithmetic, serialization, currencies, signs, and timezone boundaries.
- Architecture/import tests enforce dependency direction.

### Suggested commits

1. `feat(domain): add exact financial value objects`
2. `feat(domain): add canonical portfolio and provenance contracts`
3. `test(domain): add financial and temporal property tests`

## 6. P1-03 — PostgreSQL schema and migrations

### Deliverables

- SQLAlchemy 2 persistence models/mappers and repositories.
- Alembic baseline and documented migration workflow.
- Tables for owners/principals, broker connections/accounts, instruments/listings, ingestion runs/checkpoints/source records, canonical transactions/cash flows/dividends/order observations/current observations, snapshots/components, reconciliation runs/discrepancies, calculation metadata, and audit events.
- Exact numeric/UTC/ownership/idempotency constraints.
- Repository transaction/unit-of-work boundaries.
- Test database fixtures and migration tests.

### Required design details

- Secret values are not stored; only opaque credential references/status metadata.
- Provider/environment/account/listing identities have explicit unique constraints.
- Source record provider IDs/fingerprints enforce deduplication.
- Completed snapshots and completed run metadata are append-oriented/immutable by service policy.
- Indexes support account/date/cursor/activity and latest-snapshot queries.
- JSON fields are bounded to metadata where relational fields are semantically important.

### Acceptance

- Empty-to-head migration passes repeatedly.
- Schema matches ORM metadata under the chosen consistency check.
- Repositories enforce owner/account scope.
- Duplicate source/canonical ingestion is idempotent.
- Atomic rollback tests leave no partial checkpoint advancement.
- Decimal/timezone round trips preserve values.
- No secrets/private fixture data committed.

### Suggested commits

1. `feat(persistence): add baseline PostgreSQL schema`
2. `feat(persistence): add typed repositories and unit of work`
3. `test(persistence): add migration idempotency and ownership tests`

## 7. P1-04 — Trading 212 strict read-only adapter

### Deliverables

- Typed client implementing exactly the capability table in `docs/integrations/TRADING212_API_CONTRACT.md`.
- Fixed Demo/Live base environment enum.
- Server-side auth/secret interface and centralized redaction.
- Private sealed GET-only dispatcher.
- DTO schemas and canonical mappers for all Phase 1 capabilities.
- Typed query/path parameters, timeouts, bounded retry, error mapping.
- Mock transport and official-contract/sanitized synthetic fixtures.
- Current official API/OpenAPI verification recorded in the contract and tests.

### Mandatory negative design

The production adapter must not contain:

- public/generic `request(method, path)`;
- any non-GET dispatch;
- order placement/cancel/amend DTO/method/path;
- Pie mutation or generic Pie API abstraction;
- arbitrary base URL in production settings;
- response/header/body logging containing secrets/private payloads.

### Acceptance

- Static test asserts exact capability count, GET method, and path templates.
- Unknown capability/path/query rejected before mock network receives a request.
- Forbidden order/Pie mutation path strings/methods absent from production adapter or explicitly present only in negative-test fixtures/docs.
- Canary API secret absent from all captured logs, errors, traces, API/MCP-compatible schemas.
- DTO mapping handles valid, additive unknown, missing, malformed decimal/currency/ID/time fields correctly.
- Retry/rate-limit/error mapping tests pass.
- Demo smoke test marker exists and safely skips only when credentials are absent.

### Suggested commits

1. `feat(trading212): add sealed GET-only capability client`
2. `feat(trading212): add strict DTOs and canonical mappers`
3. `test(security): prove broker writes and unknown paths are unreachable`

## 8. P1-05 — Ingestion, pagination, and rate-limit coordination

### Deliverables

- Full and incremental ingestion orchestration per capability.
- Capability-specific paginators/checkpoints/overlap.
- Central provider/account rate coordinator.
- Leases/locks, heartbeats, job/run records, coalescing.
- Bounded retry and partial-failure behavior.
- Source fingerprint/deduplication and canonical upsert transactions.
- Reference-data refresh strategy.
- Mock failure, pagination loop, late update, duplicate, restart/replay tests.
- Worker commands/schedules and manual high-level refresh use case.

### Acceptance

- Re-running full/incremental fixtures produces identical canonical state.
- Crash before/after page commit recovers without loss/duplication/checkpoint corruption.
- Concurrent identical refresh coalesces or serializes safely.
- Checkpoint advances only after durable atomic success.
- Pagination loops/max bounds fail visibly.
- Partial endpoint failure produces correct run and aggregate quality states.
- Rate-limit responses postpone work without uncontrolled retries.
- Refresh caller cannot select provider paths.

### Suggested commits

1. `feat(ingestion): add durable runs checkpoints and leases`
2. `feat(ingestion): add idempotent capability pipelines`
3. `test(ingestion): add restart pagination and rate-limit scenarios`

## 9. P1-06 — Ledger, reconciliation, and snapshots

### Deliverables

- Canonical cash-flow classification and ledger projection.
- External versus internal flow classification.
- Position quantity and cash reconciliation algorithms with versioned tolerance policy.
- Reconciliation run/discrepancy persistence and resolution metadata.
- Portfolio snapshot calculator/persistence using explicit source cutoff/valuation time.
- Daily/post-refresh/manual snapshot scheduling.
- Snapshot deduplication/version semantics.
- Data-quality aggregation by dependency.

### Acceptance

- Reference fixtures bridge quantity/cash exactly or generate expected discrepancy.
- Deposits/withdrawals are external; buys/sells/dividends are classified correctly.
- Unknown/unsupported activity remains explicit and degrades affected metrics.
- Unmapped instruments remain in observed value totals where possible.
- Reconciliation reruns are deterministic and preserve prior run history.
- Equivalent snapshot key does not duplicate; revised calculation version is traceable.
- Source cutoff, quality, warnings, coverage, and calculation version persist.

### Suggested commits

1. `feat(ledger): normalize portfolio cash flows`
2. `feat(reconciliation): add quantity and cash bridges`
3. `feat(snapshot): add immutable canonical portfolio snapshots`

## 10. P1-07 — Core accounting, P/L, and direct allocation

### Deliverables

- Position/portfolio market-value aggregation.
- Cash/invested/total values.
- Net external contributions over covered history.
- Dividend/income summary.
- Provider-reported versus internally derived acquisition/P&L fields kept distinct.
- Direct position/cash allocation and residual.
- Snapshot comparison.
- Conservative coverage-gated MWR/TWR/Modified Dietz summary as specified; unavailable rather than guessed.
- Calculation registry/version/provenance/quality metadata.
- Reference and property tests.

### Acceptance

- All authoritative values use Decimal and explicit currency/FX.
- Portfolio component sum reconciles or exposes residual.
- Weight sum/residual behavior correct for zero, negative, partial, and multi-currency fixtures.
- Deposits are not reported as investment performance.
- Missing cost basis/fees/FX/history prevents unsupported P/L/return claims.
- XIRR convergence/multiple-root/invalid cases handled safely.
- Results deterministic and parity-ready for interfaces.
- At least the fourteen Phase 1 fixture scenarios in the test strategy are covered.

### Suggested commits

1. `feat(analytics): add core portfolio accounting`
2. `feat(analytics): add direct allocation and snapshot comparison`
3. `feat(analytics): add coverage-gated return summary`

## 11. P1-08 — Authentication, authorization, and secrets

### Deliverables

- Principal/owner/account authorization service.
- Local synthetic auth mode that cannot run in production.
- Production auth adapter boundary and fail-closed configuration.
- Session/token middleware appropriate to selected baseline without locking deployment provider prematurely.
- MCP scope/auth adapter boundary.
- CSRF/CORS/host policy as applicable.
- Secret-provider implementations for environment/local development and production interface.
- Redaction filter and security audit events.
- Rate limiting/input bounds.

### Acceptance

- Every account-scoped application service rejects cross-owner access.
- Production startup fails without valid auth and secret configuration.
- Local bypass fails when environment is not local/test.
- Secret canaries absent from logs/errors/traces/client bundles/test artifacts.
- Auth errors do not reveal account existence/provider details.
- Refresh scope permission distinct from read permission.
- No `trade:*` authorization concept exists.

### Suggested commits

1. `feat(security): add principals authorization and local auth`
2. `feat(security): add secret providers and centralized redaction`
3. `test(security): add fail-closed and cross-account tests`

## 12. P1-09 — Versioned internal API and generated client

### Deliverables

- FastAPI composition root and `/api/v1` resources from API contract.
- Typed settings/dependency wiring.
- Stable error envelope/correlation IDs.
- Cursor pagination/filtering/limits.
- Refresh command and status.
- OpenAPI export/validation.
- Generated TypeScript client/types consumed by web.
- Health/live/readiness endpoints.
- API contract/integration/security tests.

### Acceptance

- Routes invoke application services; no direct provider/repository/calculation duplication.
- Decimal/time/date/null serialization conforms to contract.
- OpenAPI validates and generated client compiles.
- Auth/authz, validation, pagination, error sanitization, and request bounds tested.
- API data includes timestamps, currency, calculation/quality/warnings.
- Refresh accepts enums only and cannot inject path/query names.
- Health endpoints leak no secret/configuration detail.

### Suggested commits

1. `feat(api): add versioned portfolio and activity endpoints`
2. `feat(api): add refresh status and quality endpoints`
3. `build(api): generate and verify TypeScript client`

## 13. P1-10 — Web application foundation

### Deliverables

- Next.js/React/TypeScript app using generated API client.
- Authenticated shell, responsive navigation, accessible design tokens/components.
- Portfolio overview with synthetic/real canonical data.
- Positions, activity/transactions, dividends, snapshots/history, reconciliation/data-quality pages.
- Loading, empty, stale, partial, unreconciled, and failed states.
- Source timestamp/methodology/quality details.
- Basic portfolio value/deposit history and direct allocation visualization using only Phase 1 data.
- Light/dark and reduced-motion/accessibility foundations.
- Unit/component/Playwright/accessibility/visual smoke tests.

### Non-goals

No virtual Pie editor, contribution optimizer, X-ray, benchmark attribution, advanced risk, research cockpit, or execution controls.

### Acceptance

- No financial arithmetic duplicated in UI beyond presentation formatting.
- No broker/auth secrets in browser/server bundle.
- Responsive desktop/mobile key flows.
- Keyboard and semantic accessibility for core pages.
- Stale/partial/unreconciled states visually and textually explicit.
- API errors safely actionable.
- Synthetic end-to-end flow passes.
- Visual design is coherent/premium without compromising information clarity.

### Suggested commits

1. `feat(web): add authenticated responsive application shell`
2. `feat(web): add portfolio positions and activity views`
3. `feat(web): add quality reconciliation and history views`

## 14. P1-11 — MCP gateway and core ChatGPT tools

### Deliverables

- Remote MCP server using current official supported SDK/transport.
- Auth adapter and application-service composition.
- Exact Phase 1 tool registry from `CHATGPT_MCP_APP.md`.
- Common result metadata and bounded/paginated schemas.
- Optional minimal accessible portfolio-summary resource/card.
- MCP inspector/contract tests and API parity tests.
- Docker/deployment command and ChatGPT setup documentation.

### Acceptance

- Tool schemas validate and are discoverable.
- Every tool invokes a typed application use case.
- Authentication required outside local test mode.
- Unknown/oversized inputs fail closed.
- Outputs include valuation/source time, currency, calculation version, quality, warnings.
- API/MCP fixture values match exactly.
- No generic query/HTTP/SQL/filesystem/broker path tool.
- No broker mutation reachable.
- Mock-data end-to-end invocation works.
- Live ChatGPT registration is passed or recorded as external deployment gate, not fabricated.

### Suggested commits

1. `feat(mcp): add authenticated remote MCP gateway`
2. `feat(mcp): expose bounded Phase 1 portfolio tools`
3. `test(mcp): add schema security and API parity tests`

## 15. P1-12 — Operations, deployment, and phase acceptance

### Deliverables

- Complete Dockerfiles/Compose and production-neutral deployment examples.
- Database migration startup/deploy job.
- Structured logs, metrics, traces hooks, health, worker telemetry.
- Backup/restore and incident/credential rotation runbooks.
- Dependency/secret/static/container scans.
- Performance smoke benchmarks.
- End-to-end synthetic demo.
- Demo credential smoke test when supplied.
- Phase acceptance report, validation report, changelog, status/progress update.

### Acceptance

- Clean clone → bootstrap → migrate → seed synthetic data → run API/worker/MCP/web documented and verified.
- `make test`, `make build`, `make docs-check`, and `make security-check` pass.
- Containers run as non-root where practical, expose only needed ports, and contain no secrets.
- Logs/traces verified redacted.
- Migration/restart/idempotent refresh smoke passes.
- Baseline performance targets measured/documented.
- No unresolved critical/high security issue.
- Exact `main` SHA and test evidence recorded.
- External Demo/deployed ChatGPT gates clearly passed or remaining; no other hidden incomplete Phase 1 criteria.

### Suggested commits

1. `ops: add production-neutral containers and observability`
2. `test(e2e): add complete synthetic portfolio workflow`
3. `docs: record Phase 1 acceptance and release 0.1.0`

## 16. Mandatory Phase 1 end-to-end scenarios

1. Fresh synthetic account ingestion and snapshot.
2. Repeated identical refresh with no duplicate economic records.
3. Incremental update adds one transaction/dividend/position change.
4. Transient provider failure retries and recovers.
5. Rate limit pauses and resumes safely.
6. One capability fails; portfolio state becomes appropriately partial.
7. Schema incompatibility fails atomic unit without checkpoint advance.
8. Quantity/cash mismatch becomes unreconciled and visible in web/API/MCP.
9. Multi-currency valuation with explicit FX and missing-FX degradation.
10. Unauthorized cross-account API/MCP access denied.
11. Canary secret cannot be found in telemetry or client results.
12. Attempted non-GET/unknown broker path rejected before transport.
13. Snapshot comparison and direct allocation consistent across API/web/MCP.
14. Container restart preserves canonical state and resumes jobs safely.

## 17. Global Phase 1 exit checklist

Phase 1 is complete only when all are true:

- [ ] P1-01 through P1-12 are marked complete with evidence.
- [ ] Repository builds from a clean checkout.
- [ ] All required local commands pass at the exact final SHA.
- [ ] Database migrations are reproducible and tested.
- [ ] Broker registry contains exactly documented GET capabilities.
- [ ] Negative write/path tests prove default denial before network dispatch.
- [ ] Mock provider and synthetic portfolio demonstrate all mandatory scenarios.
- [ ] Canonical ledger/reconciliation/snapshot/accounting/allocation are deterministic.
- [ ] Data-quality states and source/calculation metadata appear in every relevant interface.
- [ ] API/OpenAPI and generated web client are synchronized.
- [ ] Core web pages are responsive and accessible.
- [ ] MCP tools are authenticated, bounded, schema-valid, and API-parity tested.
- [ ] Secret/auth/security scans and canary redaction tests pass.
- [ ] Observability and operational runbooks exist.
- [ ] `PROJECT_STATUS.md`, `PROJECT_PROGRESS.json`, changelog, and validation evidence are accurate.
- [ ] Trading 212 Demo smoke has passed with user credentials, or it is the only explicitly external broker verification gate.
- [ ] Remote ChatGPT registration has passed, or domain/auth registration is the only explicitly external MCP verification gate.
- [ ] No Phase 2/3 feature is falsely claimed or partially exposed as production-ready.

## 18. Codex stopping conditions

Codex should continue autonomously through locally resolvable work. It may stop and report a blocker only when:

- current documentation contains a genuine incompatible requirement that cannot be safely resolved by precedence/ADR;
- an external credential/domain/provider decision is required for the next external validation gate;
- a required dependency/tool cannot run in the available environment after documented alternatives are exhausted;
- proceeding would violate the read-only/security freeze.

When stopping, leave `main` passing, commit completed coherent work, update status/progress honestly, and provide exact blocker/evidence/next action. Do not ask for nonessential aesthetic or implementation preferences.
