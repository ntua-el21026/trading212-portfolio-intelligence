# Phase 1 Troubleshooting

**Status:** Phase 1 operational runbook

Start with the narrowest sanitized evidence: current release SHA, service state,
bounded health response, correlation/run ID, Alembic revision, and recent
structured event names/categories. Never capture environment dumps, authorization
headers, cookies, provider response bodies, broker credentials, or private
portfolio payloads.

## 1. Workspace or build failure

Run in order:

```bash
make check-workspace
make bootstrap
make format-check
make lint
make typecheck
```

Confirm `.python-version`, `.node-version`, `.uv-version`, the package-manager
field in `package.json`, and both lockfiles are unchanged. Do not bypass a pin or
regenerate a lockfile opportunistically.

## 2. Compose does not become healthy

```bash
docker compose ps
docker compose logs --since=10m postgres migrate seed api worker mcp web
```

- PostgreSQL first: require `healthy`; verify the named data volume is mounted.
- Migration/seed: require successful one-shot exits. A failed migration blocks all
  later services; do not mark it complete manually.
- Redis: require `PONG`; its loss may delay work but must not erase canonical
  records/checkpoints.
- API/MCP: liveness proves only process responsiveness. Readiness may remain 503
  for missing database/auth composition and must not be overridden.
- Web: verify its server-side API base URL targets the API service, not a browser
  bundle secret or an unreachable loopback inside the container.

If the host only provides legacy Compose, use the Make targets, which select the
available implementation.

## 3. Migration drift or database outage

```bash
DATABASE_URL=postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio \
  uv run alembic -c alembic.ini current
DATABASE_URL=postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio \
  uv run alembic -c alembic.ini heads
```

Run migration tests against a fresh isolated database. A developer database that
already applied a modified, unpublished migration may legitimately differ; do
not delete it or edit Alembic history to hide the mismatch. Preserve it, prove a
fresh database reaches the single expected head, and use a reviewed forward
migration for any released schema correction.

## 4. Refresh is queued or interrupted

Check the durable ingestion run/checkpoint first, then Celery worker availability
and Redis connectivity. The database record must exist before publication; a
lost Redis message is recoverable work, not a reason to invent a successful run.
Use the same idempotency key to resume the intended run, and confirm leases expire
or are reclaimed within the configured bound. Do not submit credentials in a job
payload or launch parallel refreshes to force progress.

## 5. Trading 212 Demo smoke fails

| Sanitized category | Action |
|---|---|
| `configuration` | Verify explicit opt-in, exact two-field JSON bundle, Demo selection, and false Live gate. Do not print the bundle. |
| `authentication` / `authorization` | Confirm the credential is a Demo credential, active and read-only; rotate/revoke through the provider rather than inspecting headers. |
| `rate_limited` | Stop retrying, preserve the sanitized rate observation, and wait for the provider window. |
| `timeout` / `transient` | Verify DNS/TLS/egress and provider status; the smoke intentionally makes one attempt. |
| `contract` | Treat as provider schema drift; preserve only an access-controlled raw response outside Git/chat, compare with the pinned official contract, and fail closed. |

The probe cannot be pointed at Live. Follow
[Credentials and Demo Validation](CREDENTIALS_AND_DEMO_VALIDATION.md); do not use
`curl` with an Authorization header as an alternative.

## 6. API/web authentication or authorization failure

- Local login requires both a local/test runtime and explicit synthetic-auth
  enablement. It must fail outside those environments.
- In staging/production, verify issuer, audience, public-key/session-key opaque
  references, secure cookie policy, and exact origins/hosts.
- A 403 for another owner/account is correct even when the identifier exists.
- Browser credentials must be the application HttpOnly session; no Trading 212
  value belongs in local/session storage or a `NEXT_PUBLIC_*` variable.
- Preserve the correlation ID and bounded error code, not the cookie/token.

## 7. MCP or widget failure

- 503 readiness with `authentication_not_configured` means fail-closed startup;
  compose an approved local loopback or OAuth bearer mode.
- 401/403: validate OAuth discovery, issuer, audience, scopes, resource URL, and
  account ownership with sanitized metadata only.
- Tool missing/schema drift: run contract tests and Inspector; exactly nine frozen
  Phase 1 tools must be present.
- Widget blank: call `get_portfolio_snapshot`, inspect the versioned resource and
  browser console, and verify empty CSP domain lists. Do not add wildcard network
  access to make rendering work.
- Public connection unavailable: local Inspector evidence is not ChatGPT evidence;
  keep the gate `blocked_external` pending HTTPS/OAuth deployment.

## 8. Security or integrity incident

Any suspected secret exposure, cross-owner access, canonical-record corruption,
or attempted broker mutation is a security incident. Disable the affected ingress
and broker egress, revoke/rotate credentials, preserve audit evidence, identify
the release/config/time window, validate against immutable source records and
reconciliation, and restore only through the isolated procedure. A broker write
attempt is critical even when Trading 212 rejects it; the application is required
to reject it before transport.
