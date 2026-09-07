# Phase 1 Local Operation and Deployment

**Status:** Phase 1 operational contract
**Release:** `0.1.0`

## Independent audit correction operations

Collection traversal quotas are hard, including for an owner's first request:
64 active snapshots and 250,000 active members by default. Overflow returns
`COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED` (HTTP 429 or bounded MCP failure) with no
new cursor or partial snapshot state. Resume an existing valid traversal or retry
after expiry. Expired rows release active capacity even when bounded non-blocking
cleanup has a backlog; increasing quotas requires an explicit deployment capacity
decision, not an automatic first-request exception.

Apply migration `20260907_0008` before declaring export URL minimization complete.
It removes legacy top-level download URL fields from export source payloads only.
Do not save pre-migration URL payloads in ordinary logs or migration artifacts.
The migration cannot restore removed URLs on downgrade. New ingestion fingerprints
selected non-downloadable metadata, and the ten GET capabilities remain unchanged.

Current audit acceptance is tracked in
[Phase 1 audit corrections](../implementation/PHASE_1_AUDIT_CORRECTIONS.md).

This runbook applies to the API, worker, durable refresh-outbox dispatcher, MCP gateway, web application,
PostgreSQL system of record, and non-authoritative Redis coordination service.
It does not authorize Trading 212 Live access or public exposure of local
synthetic authentication.

Run and maintain these procedures from the synchronized `main` line. Operational examples
do not authorize a separate implementation or release workflow.

## 1. Local prerequisites

- Python `3.13.15` and `uv 0.12.7`;
- Node.js `24.20.0`, Corepack, and pnpm `10.34.5`;
- Docker with Compose (the Makefile also detects legacy `docker-compose`);
- GNU Make.

From a clean checkout:

```bash
make bootstrap
make run-local
```

`make run-local` builds and starts the repository's hardened PostgreSQL and Redis
derivatives, the one-shot migration and
synthetic seed jobs, API, worker, dispatcher, MCP, and web services. The seed is deterministic
and idempotent. It is restricted to `local`/`test` and contains no provider
credentials.

Use `make dev` when running API and web processes on the host. It starts the
dependencies, migrates, seeds, and launches both processes with loopback-only
local authentication. Stop containers without deleting the PostgreSQL volume:

```bash
make stop-local
```

Never use a volume-removing Compose command as a routine restart procedure.

## 2. Local endpoints and verification

| Surface | Address | Expected check |
|---|---|---|
| Web | `http://127.0.0.1:3000` | authenticated local portfolio shell |
| API liveness | `http://127.0.0.1:8000/health/live` | HTTP 200, bounded status |
| API readiness | `http://127.0.0.1:8000/health/ready` | HTTP 200 only after required dependencies are ready |
| Dispatcher metrics | internal `:9464/metrics` | pending/age/attempt/failure/recovery/readiness series; not host-published by default |
| MCP liveness | `http://127.0.0.1:8001/health/live` | HTTP 200, bounded status |
| MCP readiness | `http://127.0.0.1:8001/health/ready` | HTTP 200 only when an authentication mode is configured |
| PostgreSQL | `127.0.0.1:5432` | `pg_isready` through the container health check |
| Redis | `127.0.0.1:6379` | `PONG`; never authoritative financial storage |

Inspect service state and sanitized logs with the Compose implementation
available on the host:

```bash
docker compose ps
docker compose logs --since=10m api worker dispatcher mcp web
```

Do not use `docker compose config` or environment-dump commands in shared logs
when a credential bundle has been injected; interpolation can reveal secret
values.

## 3. Migrations and seed workflow

Run schema changes before compatible application processes:

```bash
make run-dependencies
make migrate
make seed-demo
```

`make migrate` upgrades to Alembic head `20260907_0008`. Re-running the upgrade and synthetic
seed is safe. Migration downgrades are not an operational rollback mechanism.
For a deployment, run the migration image as a controlled one-shot job with an
advisory deployment lock, record the previous and new Alembic revisions, and
then roll out compatible services.

The correction migrations are:

- `20260901_0004`: atomic run/outbox persistence, requested/effective refresh
  semantics, fenced leases, dispatch heartbeat, and bounded consumer attempts;
- `20260901_0005`: explicit `not_configured` credential state;
- `20260901_0006`: immutable collection-query snapshots and members;
- `20260901_0007`: active external-cash-flow revisions.
- `20260907_0008`: selective irreversible deletion of legacy export download URL fields.

## 4. Deployment configuration boundary

Use immutable images identified by commit SHA and digest. Runtime configuration
must be supplied by the deployment platform, not baked into an image.

| Concern | Local/test | Staging/production requirement |
|---|---|---|
| Authentication | explicitly enabled loopback synthetic mode | composed bearer/session verifier with issuer, audience, key references, exact origins and hosts |
| Sessions | insecure cookie permitted only on loopback local HTTP | `Secure`, `HttpOnly`, `SameSite=Strict` or approved `Lax` over TLS |
| Secrets | allowlisted environment adapter for a private Demo validation shell | external secret-manager adapter and opaque references |
| Broker | synthetic by default; opt-in Demo smoke | Demo in staging; Live is disabled and untested, outside Phase 1 acceptance, and not an additional gate |
| Database | hardened derivative of pinned PostgreSQL `18.6`, running unprivileged | managed PostgreSQL, encrypted transport/storage, monitored backups |
| Redis | hardened derivative of pinned Redis `8.10.1`, unprivileged and non-authoritative | private managed service where required; loss must not lose canonical facts/checkpoints |
| Dispatcher | required Compose service, fixed `portfolio.refresh` task, local heartbeat/metrics | independently supervised service with shared broker, bounded claims/backoff, and monitored heartbeat |
| Ingress | loopback only | TLS, exact host/origin allowlists, rate controls, no direct database/Redis exposure |
| Telemetry | local structured output | redacted logs, bounded metrics, sampled traces, configured error reporter |

Production startup is expected to fail closed until the authentication and
external secret-provider adapters are composed and a dispatcher is explicitly
configured. API readiness also fails until PostgreSQL contains a recent healthy
dispatcher cycle. Do not weaken these gates to make an image start.

Production host, identity, and secret-manager selection and the public HTTPS/OAuth MCP
deployment with ChatGPT registration remain `blocked_external`. They do not change the
complete local Phase 1 implementation state. Real-provider opening-history coverage is
`unavailable_explicit` with limitation reporting complete.

The dispatcher claims rows in bounded batches with `FOR UPDATE SKIP LOCKED`,
publishes only `portfolio.refresh`, and uses the ingestion run ID as Celery task
identity. Broker failure leaves a retryable PostgreSQL event with bounded
exponential backoff. Expired claims are recovered; exhausted publication attempts
or a queued run without a deliverable event become explicit terminal/degraded
state.

## 5. Release deployment sequence

1. Record the reviewed Git SHA, lockfile hashes, image digests, Alembic head, and
   configuration revision.
2. Pass repository validation, formatting, lint, type checks, tests, builds,
   dependency/secret/static analysis, and container scans.
3. Verify an encrypted backup and a recent isolated restore exercise.
4. Deploy the migration one-shot job; stop on any schema mismatch.
5. Deploy API, worker, dispatcher, MCP, and web images by immutable digest.
6. Require liveness and readiness checks to pass. Confirm structured logs contain
   correlation/run IDs and no headers, payloads, tokens, or credentials.
7. Run authenticated synthetic API/web/MCP smoke checks. Use Trading 212 Demo only
   through the separate opt-in procedure in
   [Credentials and Demo Validation](CREDENTIALS_AND_DEMO_VALIDATION.md).
8. Verify metrics, traces, error reporting, backup alerts, worker queue/lease
   health, dispatcher heartbeat, pending-outbox count/age and delivery failures,
   and stale-data/reconciliation alerts.
9. Record the completed deployment evidence. Do not claim ChatGPT registration
   until the external procedure actually passes.

## 6. Rollback

Roll back to a known compatible application image digest. Do not improvise an
Alembic downgrade. If a schema change is not backward compatible, stop the
rollout and follow its reviewed forward-repair or backup-restore plan. Keep
broker egress disabled during a data restore, reattach credentials only after
ownership, provenance, migration, and reconciliation validation, and record all
decisions in the incident timeline.

See also:

- [Backup and Restore](BACKUP_RESTORE.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [MCP Inspector and ChatGPT Validation](MCP_CHATGPT_VALIDATION.md)
- [Deployment, Observability, and Recovery](../engineering/DEPLOYMENT_OPERATIONS.md)
