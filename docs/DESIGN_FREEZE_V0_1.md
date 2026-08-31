# Architecture Design Freeze v0.1

**Status:** Accepted  
**Effective date:** 2026-08-31  
**Delivery:** Direct fast-forward commits to `main`

## 1. Product definition

Trading 212 Portfolio Intelligence is a private, premium portfolio intelligence platform. It ingests read-only brokerage observations, persists an auditable provider-independent portfolio history, performs deterministic financial calculations, and exposes the same canonical results through a web/PWA application, an HTTP API, workers, reports, and a ChatGPT MCP app.

It is not a broker, execution system, investment adviser, autonomous agent, or generic data proxy.

## 2. Permanent invariants

1. Trading 212 access is strictly read-only, fixed-allowlist, and default-deny.
2. No broker request other than an allowlisted `GET` can reach transport.
3. No order placement, cancellation, amendment, Pie mutation, transfer, CFD operation, or automated trade execution exists.
4. Demo is the default environment; Live requires explicit read-only configuration.
5. Broker credentials remain server-side and are never exposed to web or model contexts.
6. PostgreSQL is the system of record; caches/queues are not authoritative financial storage.
7. The canonical domain is provider-independent.
8. Provider DTOs do not leak into application/API/MCP contracts.
9. Financial calculations are deterministic and use exact decimal values.
10. Every monetary value has an explicit currency; cross-currency calculation requires sourced FX.
11. All internal instants are timezone-aware UTC.
12. Missing, zero, partial, stale, estimated, unreconciled, unavailable, and failed are distinct.
13. Ingestion, jobs, checkpoints, migrations, and replay are idempotent.
14. Calculation outputs include version, timestamps, provenance, coverage, quality, assumptions, and warnings.
15. API, web, MCP, workers, and reports share canonical application services and calculation code.
16. The language model invokes and explains typed tools; it does not perform authoritative financial arithmetic.
17. Direct commits to `main` are fast-forward only; history rewriting is prohibited.
18. Later-phase features cannot be presented as complete during Phase 1.

## 3. Architecture

The accepted topology is a mixed Python/TypeScript monorepo:

```text
apps/
  api/        FastAPI HTTP application
  worker/     durable ingestion/reconciliation/snapshot jobs
  mcp/        authenticated remote MCP server
  web/        Next.js/React responsive PWA
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
tests/
config/
scripts/
docs/
```

Python owns canonical financial/domain/application/persistence/provider logic. TypeScript owns the web client and shared UI. Generated contracts connect the two without duplicating financial logic.

## 4. Data model

PostgreSQL stores principals/owners, broker connections/accounts, instruments/listings, source records/fingerprints, ingestion runs/checkpoints, transactions/cash flows/dividends/order observations, position observations, reconciliation runs/discrepancies, immutable portfolio snapshots/components, calculation metadata, and audit events. Later phases add targets, virtual Pies, reports, alerts, scenarios, goals, and research records.

Secret values are not stored in canonical tables; only opaque secret references and non-sensitive status metadata are permitted.

## 5. Provider boundary

The exact Phase 1 Trading 212 capabilities are defined twice and must agree:

- `docs/integrations/TRADING212_API_CONTRACT.md`
- `config/contracts/trading212-read-allowlist.yaml`

The allowlist contains ten current official GET capabilities. Any beta API change fails closed until the contract, allowlist, DTOs, fixtures, and tests are deliberately updated from primary documentation.

## 6. Financial policy

- Use `Decimal`/database `NUMERIC` for authoritative money, quantities, prices, FX, and ratios.
- Never infer a missing input as zero.
- Separate external contributions from internal security transactions.
- Separate provider-reported fields from internally derived values.
- Refuse or downgrade metrics when material history, valuations, FX, fees, cost basis, or corporate actions are incomplete.
- Preserve reproducibility using calculation versions and explicit source cutoffs.

## 7. Phase boundaries

### Phase 1 — Trusted Foundation (`0.1.0`)

Monorepo, domain/persistence, GET-only broker adapter, ingestion, ledger, reconciliation, snapshots, core accounting/allocation/coverage-gated performance, authentication, API, bounded premium web foundation, MCP tools, CI, operations, and acceptance evidence.

### Phase 2 — Portfolio Intelligence (`0.2.0`)

Virtual Pies/targets, contribution-only optimization, market/benchmark performance, attribution, ETF look-through/X-ray, reports, exports, rules/alerts, and premium analytical interfaces.

### Phase 3 — Premium Intelligence and Productization (`1.0.0`)

Advanced risk/scenarios/projections/goals, research cockpit, rich ChatGPT UI, PWA polish, premium provider adapters, multi-broker readiness, and production hardening.

## 8. Runtime authority

`docs/implementation/PHASE_1_TECHNICAL_BASELINE.md` is authoritative for Phase 1 toolchain/runtime versions and may supersede older examples without changing architectural semantics.

## 9. Change control

A frozen invariant changes only through an accepted superseding ADR plus synchronized contracts, tests, documentation, and status. A provider beta correction that does not alter product semantics may be handled as a contract correction, but must still be verified from primary sources and committed with exact/negative tests.
