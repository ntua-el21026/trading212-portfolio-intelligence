# System Architecture

**Status:** Accepted for Design Freeze v0.1

## 1. Context

Trading 212 Portfolio Intelligence ingests read-only brokerage data, converts it into a canonical auditable portfolio model, performs deterministic calculations, and serves the same results to a web/PWA client and a ChatGPT MCP application.

```text
                         ┌──────────────────────────┐
                         │ ChatGPT / Apps SDK UI    │
                         └────────────┬─────────────┘
                                      │ MCP over HTTPS
┌──────────────────────────┐          │
│ Next.js Web / PWA        │──────────┼──────────────┐
└────────────┬─────────────┘          │              │
             │ HTTPS                  ▼              ▼
             │             ┌────────────────┐  ┌────────────────┐
             └────────────▶│ API application│  │ MCP application│
                           └────────┬───────┘  └───────┬────────┘
                                    │                  │
                                    └────────┬─────────┘
                                             ▼
                                 ┌──────────────────────┐
                                 │ Application services │
                                 │ + authorization      │
                                 └──────────┬───────────┘
                                            │
              ┌─────────────────────────────┼─────────────────────────────┐
              ▼                             ▼                             ▼
    ┌───────────────────┐       ┌──────────────────────┐      ┌────────────────────┐
    │ Canonical domain  │       │ Deterministic       │      │ Provider adapters  │
    │ + repositories    │       │ analytics engine    │      │ Trading212 first   │
    └─────────┬─────────┘       └──────────┬───────────┘      └─────────┬──────────┘
              │                            │                            │ GET allowlist
              └──────────────┬─────────────┴──────────────┬─────────────┘
                             ▼                            ▼
                    ┌────────────────┐          ┌────────────────────┐
                    │ PostgreSQL     │          │ Trading 212 API    │
                    │ system record  │          │ Demo / Live        │
                    └────────────────┘          └────────────────────┘
                             ▲
                             │
                    ┌────────┴─────────┐
                    │ Worker/scheduler │
                    │ ingest/reconcile │
                    └──────────────────┘
```

## 2. Repository topology

```text
apps/
  api/                 FastAPI HTTP application
  worker/              scheduled/background execution
  mcp/                 remote MCP server and ChatGPT resources
  web/                 Next.js/React web and PWA
packages/
  domain/              canonical entities, value objects, invariants
  application/         use cases, orchestration, authorization
  persistence/         SQLAlchemy repositories, migrations support
  trading212/          provider DTOs, client, allowlist, mapping
  analytics/           deterministic calculations
  observability/       structured logging, metrics, tracing
  security/            auth, redaction, secret interfaces
  api-contracts/       OpenAPI/schema generation and clients
  ui/                  shared UI/design-system components
infrastructure/
  docker/              container definitions
  deployment/          provider-neutral deployment manifests/examples
  monitoring/          dashboards/alerts as introduced
tests/
  fixtures/
  unit/
  property/
  contract/
  integration/
  e2e/
  security/
docs/
config/
scripts/
```

Python packages may live under a single Python workspace and TypeScript packages under a pnpm workspace; the conceptual boundaries above are mandatory even if exact physical names are refined during P1-01.

## 3. Architectural layers

### 3.1 Provider layer

Responsibilities:

- authentication header construction from a secret-provider interface;
- exact allowlisted path/method dispatch;
- timeout, bounded retry, rate-limit, and pagination handling;
- provider DTO validation;
- source metadata capture;
- no domain calculations;
- no write methods.

The adapter must be replaceable by a fixture/mock provider implementing the same port.

### 3.2 Ingestion and normalization

Responsibilities:

- coordinate full and incremental reads;
- maintain checkpoints/cursors/watermarks;
- fingerprint/deduplicate provider records;
- retain sufficient raw/source representation for audit and replay;
- map provider DTOs into canonical records;
- execute atomically/idempotently;
- record run status, counts, warnings, latency, and source coverage.

### 3.3 Canonical domain

Owns:

- accounts and owners;
- instruments/listings/identifiers;
- money, quantity, price, FX rate, percentage, and time-range value objects;
- positions and position lots/derived acquisition state where supported;
- transactions, cash flows, dividends, and order observations;
- snapshots and valuation records;
- provenance, coverage, quality, warning, and reconciliation models;
- later virtual Pies, targets, constraints, scenarios, goals, and research records.

Provider-specific field names must not leak into application/API contracts.

### 3.4 Persistence

PostgreSQL stores:

- normalized canonical entities;
- ingestion runs and checkpoints;
- source payload metadata/fingerprints;
- historical snapshots;
- calculation runs/results or reproducible inputs, depending on metric class;
- audit/security events;
- later targets, reports, alerts, scenarios, and research data.

Requirements:

- migrations are ordered, immutable after application, and tested from empty and previous schema states;
- uniqueness constraints enforce idempotency;
- transactions protect atomic ingestion units;
- repositories return domain objects, not unbounded ORM entities to interfaces;
- sensitive payload fields are minimized and protected.

### 3.5 Analytics

Analytics are pure/deterministic where practical and accept explicit inputs, valuation timestamps, reporting currency, method options, and data-quality context.

No analytics function calls Trading 212 directly. Provider refresh is an application use case preceding calculation.

### 3.6 Application services

Application services implement use cases such as:

- refresh account data;
- get account summary;
- list/search positions and instruments;
- get canonical portfolio snapshot;
- compare recorded snapshots;
- list transactions/dividends/order observations;
- calculate direct allocation and core accounting;
- expose reconciliation/data-quality state;
- later manage targets, optimize contributions, generate reports, and run analyses.

They enforce authorization, pagination, bounded response sizes, and consistent error mapping.

### 3.7 Interfaces

The API, web, worker, and MCP applications are composition roots. They may format/transport data but must not duplicate business calculations.

The MCP application invokes application services through typed ports. Tool output schemas are stable and versioned. Rich UI resources are optional views over the same structured tool results.

## 4. Runtime processes

### API process

- serves authenticated `/api/v1` endpoints;
- exposes liveness/readiness without leaking secrets;
- performs short application requests;
- schedules long work rather than blocking where needed.

### Worker process

- scheduled/full/incremental ingestion;
- reconciliation and snapshot jobs;
- later report/alert/analytics jobs;
- idempotency, leases/locks, heartbeats, retries, dead-letter/failure recording.

### MCP process

- remote Streamable HTTP-compatible MCP endpoint according to current official SDK capability;
- authenticated and rate-limited;
- explicit tool registry;
- no arbitrary query/path tools;
- output-size bounds and pagination/aggregation;
- data timestamp and quality metadata in every financial response.

### Web process

- Next.js server/client boundaries chosen to keep secrets server-side;
- typed generated API client;
- accessible responsive financial UI;
- no direct broker access.

## 5. Data flow

### Ingestion

```text
schedule/manual refresh
  → acquire account-scoped lease
  → check rate budget
  → call exact GET capability
  → validate provider DTO
  → record source metadata/fingerprint
  → map to canonical records
  → upsert idempotently in transaction
  → advance checkpoint only after durable success
  → reconcile affected account
  → optionally create snapshot
  → publish run metrics/status
```

### Query

```text
web or MCP request
  → authenticate
  → authorize account/scope
  → application service
  → canonical repository and analytics
  → response schema with timestamps, method, quality, warnings
```

### Explicit refresh

A user-requested refresh invokes a bounded refresh use case, never allows arbitrary endpoint selection, and reports pending/rate-limited/failed state. Interfaces should normally query persisted canonical data for reliability and speed.

## 6. Failure model

Errors use stable categories:

- `AUTHENTICATION_REQUIRED`
- `AUTHORIZATION_DENIED`
- `PROVIDER_AUTHENTICATION_FAILED`
- `PROVIDER_RATE_LIMITED`
- `PROVIDER_TIMEOUT`
- `PROVIDER_UNAVAILABLE`
- `PROVIDER_SCHEMA_INCOMPATIBLE`
- `DATA_PARTIAL`
- `DATA_UNRECONCILED`
- `CALCULATION_UNAVAILABLE`
- `INVALID_REQUEST`
- `CONFLICT`
- `INTERNAL_ERROR`

Raw provider responses, stack traces, secrets, and internal SQL are not returned to clients. Correlation IDs link sanitized client errors to internal telemetry.

## 7. Caching

- PostgreSQL canonical data is authoritative.
- In-process/Redis caches may accelerate reference data and repeated summaries.
- Cache entries include account/scope, schema/calculation version, valuation/source timestamps, and invalidation semantics.
- Stale cache must not be mislabeled fresh.
- Provider responses containing secrets are never cached in client-visible stores.

## 8. Extension strategy

External providers implement explicit ports:

- broker account data;
- market price history;
- FX/reference data;
- ETF constituents;
- research/document sources.

A new broker maps into the same canonical domain and cannot alter calculation semantics. Broker-specific capabilities are isolated and declared; unsupported concepts yield explicit coverage state.

## 9. Deployment baseline

Local Phase 1 uses Docker Compose for PostgreSQL and optional Redis, with applications runnable through documented make targets. Production uses independently deployable containers, managed PostgreSQL, TLS, secret management, private storage, monitoring, and backups. Deployment configuration remains provider-neutral until an external hosting decision is recorded.

## 10. Architectural acceptance

The architecture is realized when dependency tests prove provider code cannot be imported by domain analytics, the broker client cannot dispatch writes or unknown paths, interfaces share canonical services, migrations and ingestion are idempotent, and all financial responses expose methodology/provenance/quality metadata.
