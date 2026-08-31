# Deployment, Observability, and Recovery

**Status:** Accepted baseline

## 1. Environments

- `local`: synthetic/mock provider by default; optional Demo credentials.
- `test`: ephemeral CI services and synthetic fixtures.
- `staging`: production-like deployment using Demo/read-only data where available.
- `production`: private Live read-only connection after all gates.

Environment selection is explicit. Production fails closed when authentication, secret storage, TLS, database, or broker configuration is incomplete.

## 2. Local topology

Docker Compose provides:

- PostgreSQL 18;
- optional Redis 8, strictly non-authoritative coordination/cache/job infrastructure;
- optional local object-storage substitute when reports are introduced.

Applications run through documented make targets or containers. A single command should bootstrap dependencies, migrate the database, seed a synthetic portfolio, and start API/worker/MCP/web for development.

## 3. Production topology

Provider-neutral containers:

- web;
- API;
- MCP;
- worker/scheduler;
- managed PostgreSQL;
- optional managed Redis;
- private object storage;
- TLS ingress/reverse proxy;
- secret manager;
- logs, metrics, traces, alerts;
- encrypted backups.

API/MCP/worker may share a code image with separate commands, but scale/failure domains remain explicit.

## 4. Configuration

Typed settings validate at startup:

- environment and service role;
- database/Redis/storage URLs through secret references where sensitive;
- authentication mode/provider;
- Trading 212 environment and credential reference;
- provider timeouts/retries/rate limits;
- freshness/retention policy;
- allowed origins/hosts;
- logging/telemetry endpoints;
- feature flags;
- worker schedules/concurrency.

Unknown or unsafe production configuration fails startup. `.env.example` contains names/descriptions and blank synthetic placeholders only.

## 5. Health

### Liveness

Process event loop/runtime is responsive. No dependency details or secrets.

### Readiness

Required configuration valid, database reachable/migrated, and service can safely serve its role. Broker availability is reported as a component/degraded state and should not necessarily make cached read APIs unready.

### Dependency status

Authenticated operational view includes sanitized database, worker, provider, checkpoint, freshness, and queue state.

## 6. Observability

### Logs

Structured JSON in deployed environments with correlation/request/run IDs, service/version, event, duration/count/status, and sanitized error category.

### Metrics

- HTTP/MCP latency, status, active requests;
- job queue/lease/attempt/duration/results;
- provider capability calls, latency, errors, retries, rate observations;
- ingestion records/pages/checkpoint lag;
- dataset freshness/quality and reconciliation discrepancies;
- database pool/query/migration health;
- cache hit/staleness;
- report/analytics job duration;
- security/auth denials and redaction-test health where appropriate.

Labels remain bounded; instrument IDs/tickers are not high-cardinality metric labels.

### Traces

Trace service and database/provider spans without sensitive payload/header values. Sampling and retention are configurable.

## 7. Alerts

Initial operational alerts:

- service unready/restart loop;
- database unavailable or migration mismatch;
- repeated ingestion failure/schema incompatibility;
- stale account beyond threshold;
- provider authentication failure/rate exhaustion;
- worker lease/queue backlog;
- reconciliation discrepancy escalation;
- backup failure;
- elevated auth denials/error rate/latency;
- storage capacity/retention failure.

Alerts include run/correlation references and safe remediation links.

## 8. Migrations and deployment

- Build immutable versioned images.
- Run migration validation before deployment.
- Apply migrations as a controlled one-shot job with advisory lock.
- Deploy backward-compatible application changes before destructive cleanup.
- Verify health, smoke tests, and schema version.
- Roll back application image when compatible; database rollback follows explicit migration plan, never ad hoc.
- Record deployed commit, image digest, migration head, and config version.

## 9. Backups and disaster recovery

Before production readiness:

- automated encrypted PostgreSQL backups with monitored success;
- object/report storage versioning/retention as appropriate;
- documented RPO/RTO targets selected for the private deployment;
- periodic restore into isolated environment;
- restore validation of migrations, ownership, snapshots, provenance, and audit data;
- outbound broker access disabled during restore until credentials deliberately reattached;
- credential rotation after suspected compromise.

## 10. Incident response

Severity is based on credential exposure, unauthorized access, data integrity, broker-boundary violation, prolonged outage, or privacy loss.

Immediate actions may include:

1. revoke/rotate Trading 212 and application credentials;
2. disable broker egress and MCP/web ingress selectively;
3. preserve logs/audit evidence;
4. identify affected commit/config/time window;
5. validate portfolio data against source/reconciliation;
6. restore or rebuild canonical data from source records/backups;
7. document root cause and prevention tests;
8. communicate factually without concealing uncertainty.

Any indication of a broker write request is critical even if rejected upstream; the application should reject it before transport and alert.

## 11. Deployment gates

- all local/CI gates pass;
- images scan without unresolved critical/high findings;
- authentication/TLS/secrets configured;
- database migrated and backed up;
- provider credential read-only and revocable;
- logs/traces verified redacted;
- allowlist negative test in deployed environment;
- smoke tests for API, worker, MCP, and web;
- rollback/restore procedures documented;
- monitoring/alerts receiving expected signals.

## 12. Phase 1 implementation runbooks

- [Local operation and deployment](../operations/LOCAL_AND_DEPLOYMENT.md)
- [PostgreSQL backup and restore](../operations/BACKUP_RESTORE.md)
- [Credentials and Trading 212 Demo validation](../operations/CREDENTIALS_AND_DEMO_VALIDATION.md)
- [MCP Inspector and ChatGPT Developer Mode](../operations/MCP_CHATGPT_VALIDATION.md)
- [Troubleshooting](../operations/TROUBLESHOOTING.md)
