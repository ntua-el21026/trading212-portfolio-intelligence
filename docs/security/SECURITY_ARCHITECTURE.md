# Security Architecture and Threat Model

**Status:** Accepted normative contract

## 1. Security objectives

1. Prevent any broker mutation or trade execution.
2. Prevent credential disclosure or unauthorized portfolio access.
3. Preserve integrity and provenance of financial records/calculations.
4. Limit impact of external provider, client, model, and dependency compromise.
5. Produce actionable audit evidence without logging private secrets/data unnecessarily.
6. Fail closed under missing configuration, invalid authorization, schema drift, and uncertain broker capability.

## 2. Assets

- Trading 212 API key and secret.
- Application authentication credentials/tokens.
- Portfolio/account records and historical activity.
- Calculation and reconciliation integrity.
- Provider mapping/configuration.
- Database backups.
- Deployment and CI credentials.

## 3. Trust boundaries

```text
Browser/PWA ── Internet/TLS ── API
ChatGPT ───── Internet/TLS ── MCP
API/MCP/Worker ── private network ── PostgreSQL/Redis/storage
Worker/provider adapter ── Internet/TLS ── Trading 212
CI/CD ── deployment boundary ── runtime
```

All data crossing a boundary is validated and minimized.

## 4. Threats and controls

### Broker-write escalation

Threat: code, prompt, configuration, or compromised caller reaches a write endpoint.

Controls:

- compile-time/sealed GET-only capability registry;
- no order/Pie mutation methods or DTOs;
- no arbitrary method/path;
- dedicated read-only provider credentials;
- optional provider IP restriction;
- static forbidden-path/method tests;
- mock transport rejects any non-GET/non-allowlisted request;
- network egress allowlist where deployment supports it;
- security review for any capability change.

### Secret leakage

Threat: credentials appear in source, logs, traces, errors, browser bundles, MCP output, or backups.

Controls:

- server-side secret-provider interface;
- `.env.example` with empty values only;
- centralized structured redaction;
- no request header/body logging at provider boundary;
- secret scanning in pre-commit/CI;
- sanitized exception mapper;
- production secret manager;
- rotation/revocation runbook;
- tests containing canary secrets and asserting absence from outputs/telemetry.
- export download URLs are validated only at the provider boundary, never followed,
  and excluded from selected retained metadata and new source fingerprints. Export
  URL rotation alone does not create a source revision. The export URL canary gate
  also scans generated contracts, web bundles, and browser artifacts.

### Unauthorized portfolio access / IDOR

Controls:

- authenticated principal and explicit owner/account relationship;
- authorization in application services and routes/tools;
- opaque UUIDs are not authorization;
- negative cross-owner tests even in single-user-ready architecture;
- narrow MCP scopes;
- secure session/token settings and revocation.

### Injection

Controls:

- typed Pydantic/TypeScript schemas;
- parameterized SQL/ORM;
- allowlisted sort/filter fields;
- bounded input length/collection size;
- safe HTML/Markdown rendering;
- no shell execution from user input;
- research/prompt content treated as untrusted data;
- Content Security Policy and output encoding in web UI.

### Prompt injection / confused deputy

Controls:

- MCP tools have fixed policy independent of user/research text;
- no arbitrary HTTP/database/filesystem tool;
- untrusted text cannot define tool calls or change authorization;
- model never receives broker secrets;
- exactly nine read-only MCP tools; no refresh tool;
- tool descriptions and server enforcement both state read-only scope.

### SSRF and provider abuse

Controls:

- fixed environment base URLs;
- no user-configurable provider URL in production;
- redirects disabled/default-deny;
- strict path/query templates;
- egress restrictions;
- response-size/time limits.

### Data tampering and calculation integrity

Controls:

- immutable source/provenance/fingerprints;
- database constraints and transactional ingestion;
- atomic insertion of an ingestion run and its fixed-task outbox event;
- worker validation of dispatch/run/account/request fingerprint and schema version
  before credential resolution or economic execution;
- deterministic task identity, fenced account lease, global durable consumer
  attempt bound, and idempotent materialization for at-least-once publication;
- HMAC-authenticated, resource/owner/account/filter/sort-bound cursors with
  expiration and deterministic tie-breakers;
- calculation versions and input references;
- audit trail for mappings/config changes;
- deterministic reference/property tests;
- backups and restore validation.

### Denial of service / cost exhaustion

Controls:

- authentication, rate limits, quotas, pagination, top-N/bounded ranges;
- job queue and coalesced refreshes;
- immutable collection traversal capacity bounded per owner (default 64 active
  snapshots and 250,000 members) with explicit HTTP 429/MCP failure rather than
  silent truncation;
- no first-request quota exception: read no more than remaining member capacity
  plus one source identities under the owner lock; snapshot/member savepoint
  rollback prevents caught overflow from committing partial state or cursor state;
- outbox claims use bounded batches, `SKIP LOCKED`, expiry, publication backoff,
  and non-secret bounded-cardinality telemetry;
- provider rate coordination;
- query timeouts/indexes;
- asynchronous long tasks;
- cache with correct scope/freshness;
- bounded query snapshots and deterministic cleanup of expired traversal state.

### Supply chain

Controls:

- locked dependencies;
- minimal official base images pinned by digest for releases;
- dependency/license/static/container scanning;
- least-privilege CI permissions;
- no unreviewed install scripts;
- reproducible builds and SBOM for production releases.

## 5. Authentication modes

### Local development

A documented local-only authentication mode may create a synthetic principal. It must refuse to run when production mode is enabled and must never be enabled by default in deployed examples.

### Production

An authentication adapter validates sessions/tokens from the selected identity mechanism. Requirements:

- secure cookies/token handling;
- CSRF protection for cookie-authenticated commands;
- short-lived access and revocation/rotation appropriate to provider;
- explicit audience/issuer/signature validation;
- no anonymous portfolio endpoints;
- MCP authentication compatible with deployed ChatGPT configuration.

The final provider is an external deployment decision, not a reason to omit auth interfaces/tests.

## 6. Authorization scopes

Suggested scopes:

- `portfolio:read`
- `activity:read`
- `portfolio:refresh`
- `configuration:read`

No `trade:*` scope exists.

## 7. Data protection

- TLS for all external/internal network paths where applicable.
- Managed database/storage encryption at rest in production.
- Database backups encrypted and access-controlled.
- Minimize raw payload retention; document fields/reasons/period.
- No production data in development fixtures.
- Exports include sensitivity classification and retention metadata.

## 8. Audit events

Record at least:

- authentication success/failure and token/session revocation in privacy-preserving form;
- broker connection creation/status/credential-reference rotation (never secret value);
- refresh/ingestion/reconciliation/snapshot runs;
- refresh dispatcher publication/recovery/dead-event state with sanitized codes;
- authorization denials;
- configuration/mapping changes;
- security policy/allowlist changes;
- administrative retention/deletion actions.

Audit records are append-oriented, timestamped, correlated, and access-controlled.

## 9. Logging policy

Allow:

- correlation/request/run IDs;
- capability name, not raw arbitrary URL;
- status category, duration, counts, retry/rate observations;
- account/owner opaque IDs where required and access-controlled;
- sanitized error code.

Deny:

- authorization headers, keys, secrets, cookies/tokens;
- full upstream payloads;
- private position/activity lists by default;
- raw SQL with private values;
- stack traces returned to clients.

## 10. Security acceptance gates

Phase 1 requires:

- threat model reflected in tests;
- GET-only static/runtime proof;
- secret-canary redaction tests;
- auth/authz tests including cross-account denial;
- dependency/secret/static scanning in CI;
- production config fails closed without auth/secrets;
- TLS/deployment guidance;
- sanitized error tests;
- no critical/high unresolved security finding for phase completion.

Production readiness additionally requires the external deployment decisions and
evidence recorded by the Phase 1 acceptance documents, including a structured
security review, backup restoration, incident exercise, SBOM/container hardening,
and operational alert validation.
