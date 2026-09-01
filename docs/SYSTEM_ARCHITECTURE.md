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
              ┌──────────────┴──────────────┐
              │                             │
     ┌────────┴─────────┐  fixed task   ┌─────────┴────────┐
     │ Worker/scheduler │◀────────────│ Outbox dispatcher │
     │ ingest/reconcile │              │ claim/publish/retry│
     └──────────────────┘              └──────────────────┘
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
- persist each requested refresh run and its dispatch event atomically;
- preserve requested semantics separately from promoted/effective execution semantics.

### 3.3 Canonical domain

Owns:

- accounts and owners;
- instruments/listings/identifiers;
- money, quantity, price, FX rate, percentage, and time-range value objects;
- positions and position lots/derived acquisition state where supported;
- transactions, cash flows, dividends, and order observations;
- snapshots and valuation records;
- provenance, coverage, quality, warning, and reconciliation models;

Provider-specific field names must not leak into application/API contracts.

### 3.4 Persistence

PostgreSQL stores:

- normalized canonical entities;
- ingestion runs and checkpoints;
- fixed-task refresh-dispatch outbox rows and dispatcher heartbeats;
- immutable collection-query snapshots and ordered member identities;
- source payload metadata/fingerprints;
- historical snapshots;
- calculation runs/results or reproducible inputs, depending on metric class;
- audit/security events;

Requirements:

- migrations are ordered, immutable after application, and tested from empty and previous schema states;
- uniqueness constraints enforce idempotency;
- transactions protect atomic ingestion units;
- repositories return domain objects, not unbounded ORM entities to interfaces;
- sensitive payload fields are minimized and protected.
- the Phase 1 migration head is `20260901_0007`; migrations `0004` through `0007`
  add durable dispatch/idempotency state, explicit unconfigured credential state,
  immutable collection traversal snapshots, and active external-cash-flow revisions.

### 3.5 Analytics

Analytics are pure/deterministic where practical and accept explicit inputs, valuation timestamps, reporting currency, method options, and data-quality context.

No analytics function calls Trading 212 directly. Provider refresh is an application use case preceding calculation.

### 3.6 Application services

Application services implement use cases such as:

- refresh account data;
- get account summary;
- list owner-scoped broker connections without revealing credential references;
- list/search positions and canonical instrument/listing metadata;
- get canonical portfolio snapshot;
- compare recorded snapshots;
- list transactions/dividends/order observations;
- calculate direct allocation and core accounting;
- calculate coverage-gated XIRR, TWR, and Modified Dietz summaries;
- expose reconciliation/data-quality state;

They enforce authorization, pagination, bounded response sizes, and consistent error mapping.

Collection queries are typed. Positions, activity, dividends, and instruments use
short-lived immutable result-membership snapshots with exact filtered totals.
Orders, portfolio snapshots, and reconciliation discrepancies use signed
read-cutoff keysets. All cursors are versioned, HMAC-protected, resource-bound,
owner/account-bound, filter/sort-bound, and use deterministic tie-breakers.

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
- idempotency, leases/locks, heartbeats, retries, dead-letter/failure recording.

### Outbox dispatcher process

- independently polls PostgreSQL; API correctness never depends on a broker call;
- claims `pending` rows and expired `publishing` claims with
  `FOR UPDATE SKIP LOCKED`;
- publishes only `portfolio.refresh`, with task ID equal to the durable run ID;
- applies bounded publication attempts and exponential backoff;
- records sanitized errors and a heartbeat consumed by API readiness;
- recovers expired claims and cleans expired collection-query snapshots in bounded batches.

### MCP process

- remote Streamable HTTP-compatible MCP endpoint according to current official SDK capability;
- authenticated and rate-limited;
- explicit tool registry;
- no arbitrary query/path tools;
- exactly nine read-only tools; no MCP refresh tool;
- output-size bounds, server-side filtering, cursor pagination, and full-period
  dividend aggregation with a bounded recent sample;
- data timestamp and quality metadata in every financial response.

### Web process

- Next.js server/client boundaries chosen to keep secrets server-side;
- typed generated API client;
- accessible responsive financial UI;
- route-specific server loaders and URL cursor state for holdings, activity,
  dividends, snapshots, quality, synchronization, and connections;
- bounded overview previews that display returned and exact total counts;
- no direct broker access.

## 5. Data flow

### Ingestion

```text
authorized refresh command
  → canonicalize owner/account/mode/capabilities/snapshot behavior/schema version
  → lock account and compare account-scoped idempotency fingerprint
  → commit queued ingestion run + fixed-task outbox event atomically
  → dispatcher claims event under a renewable timeout
  → publish portfolio.refresh with deterministic run-derived task ID
  → worker validates task metadata against run and outbox
  → acquire fenced account-scoped lease and durable consumer attempt
  → check rate budget
  → call exact GET capability
  → validate provider DTO
  → record source metadata/fingerprint
  → map to canonical records
  → upsert idempotently in transaction
  → advance checkpoint only after durable success
  → reconcile affected account
  → optionally create snapshot
  → confirm terminal consumer delivery and publish run metrics/status
```

### Query

```text
web or MCP request
  → authenticate
  → authorize account/scope
  → application service
  → SQL filtering/sorting/aggregation and immutable traversal state
  → canonical repository and deterministic analytics
  → response schema with timestamps, method, quality, warnings
```

### Explicit refresh

A user-requested refresh invokes a bounded refresh use case, never allows arbitrary
endpoint selection, and reports pending/rate-limited/failed state. Once the
PostgreSQL transaction succeeds, the API returns the durable queued run even when
the broker is unavailable; the outbox remains retryable. A repeated matching
idempotency key returns the same run. Reusing the key for different requested
semantics returns `IDEMPOTENCY_KEY_REUSED` without another event. Correlation IDs
are operational metadata and are not part of semantic identity.

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
- `IDEMPOTENCY_KEY_REUSED`
- `CURSOR_INVALID`
- `COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED`
- `INTERNAL_ERROR`

Raw provider responses, stack traces, secrets, and internal SQL are not returned to clients. Correlation IDs link sanitized client errors to internal telemetry.

## 7. Caching

- PostgreSQL canonical data is authoritative.
- In-process/Redis caches may accelerate reference data and repeated summaries.
- Cache entries include account/scope, schema/calculation version, valuation/source timestamps, and invalidation semantics.
- Stale cache must not be mislabeled fresh.
- Provider responses containing secrets are never cached in client-visible stores.

## 8. Deployment baseline

Local Phase 1 uses Docker Compose for PostgreSQL, non-authoritative Redis,
API, worker, dispatcher, MCP, and web processes. Production uses independently
deployable containers, managed PostgreSQL, a shared task broker, TLS, secret
management, monitoring, and backups. Deployed configuration must explicitly
enable a dispatcher, and API readiness requires a recent healthy dispatcher cycle.

## 9. Architectural acceptance

The architecture is realized when dependency tests prove provider code cannot be
imported by domain analytics, the broker client cannot dispatch writes or unknown
paths, interfaces share canonical services, run/outbox persistence is atomic,
duplicate delivery remains economically idempotent, collection traversal is
stable, migrations and ingestion are repeatable, and all financial responses
expose methodology/provenance/quality metadata.
