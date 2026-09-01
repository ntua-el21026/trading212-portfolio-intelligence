# Phase 1 MCP / ChatGPT integration

This service exposes the nine frozen read-only portfolio tools from
`docs/integrations/CHATGPT_MCP_APP.md` over Streamable HTTP at `/mcp`. It uses the
same `PortfolioService`, `Principal`, scopes, and account-ownership policy as the
HTTP API. It contains no Trading 212 transport, SQL, generic HTTP/URL,
filesystem, broker-path, or refresh tool.

All nine tools invoke typed application-service queries. Position search/sort,
transaction date/type filters, and cursor pagination are applied before rows reach
the gateway. Dividend totals cover the full filtered period while the recent
sample remains bounded. Explicit snapshot IDs use direct owner/account-scoped
lookup. The gateway never collects a fixed prefix and presents it as complete.

Collection cursors are opaque signed tokens bound to resource, owner/account,
filter/sort, immutable result membership or read cutoff, and last ordering key.
Invalid, expired, tampered, or mismatched cursors fail safely. Tool cursor inputs
permit the bounded token size required by this contract; callers must treat them
as opaque.

## Local seeded inspection

The unauthenticated local mode is deliberately disabled by default. Migrate and seed
the local PostgreSQL database first, then enable local/test synthetic authentication
explicitly:

```bash
T212PI_ENVIRONMENT=test \
T212PI_LOCAL_SYNTHETIC_AUTH_ENABLED=true \
DATABASE_URL=postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio \
T212PI_MCP_HOST=127.0.0.1 \
T212PI_MCP_PORT=8001 \
uv run --package trading212-mcp python -m trading212_mcp.main
```

In another terminal:

```bash
uv run python -c \
  "from trading212_application.services import SyntheticPortfolioService as S; print(S.ACCOUNT_ID)"
npx @modelcontextprotocol/inspector@latest
```

Select **Streamable HTTP**, enter `http://127.0.0.1:8001/mcp`, initialize, and
verify that exactly nine tools are listed. Exercise each tool with the opaque
seeded account ID printed above, including invalid cursors, limits, identifiers,
date ranges, extra input keys, and repeated identical calls. Health endpoints are
`GET /health/live` and `GET /health/ready`.

Use more than one page when inspecting positions or transactions and verify that
the returned exact total remains stable. `get_dividend_summary` returns a bounded
recent sample plus full-period database totals; it is not a substitute collection
listing.

### Containerized local synthetic mode

Containerized local development may need the process to listen on all container
interfaces while Docker publishes it only on host loopback. That exception is
local-only and must be explicit:

```text
T212PI_MCP_HOST=0.0.0.0
T212PI_MCP_ALLOW_NON_LOOPBACK_LOCAL_SYNTHETIC_BIND=true
```

Use it only with a loopback host-port mapping such as
`127.0.0.1:8001:8001`; never use this synthetic mode on an
Internet-reachable listener.

## Deployed authentication composition

Production must construct `create_runtime(...)` with:

- `DATABASE_URL` for the shared canonical PostgreSQL service, or an explicitly
  injected `PortfolioService` in a deployment composition root;
- a shared `BearerAuthenticator` (normally `JwtAuthenticator` resolved through the
  deployment secret-provider boundary);
- `SecuritySettings.issuer` for OAuth discovery;
- `McpSettings.public_base_url` for the HTTPS resource server URL;
- explicit allowed hosts and origins.

The MCP SDK then protects `/mcp`, publishes OAuth protected-resource metadata, and
maps the validated token to the shared `Principal`. Application services enforce
the exact `portfolio:read` and `activity:read` scopes plus account ownership.
`get_data_quality_summary` requires both scopes because it reports portfolio and
activity coverage.
Starting the CLI without `DATABASE_URL`, or without either deployment bearer
authentication or explicit local/test synthetic authentication, fails closed.

## ChatGPT Developer Mode

Use a public HTTPS development tunnel or Secure MCP Tunnel; never expose the local
synthetic mode on an Internet-reachable endpoint. For an authenticated deployment:

1. Verify the public `https://<host>/mcp` URL and OAuth discovery with MCP Inspector.
2. In ChatGPT, open **Settings → Security and login** and enable **Developer mode**.
3. Open ChatGPT Plugins, select the plus button, and add the complete HTTPS `/mcp`
   URL (or select the configured Secure MCP Tunnel).
4. Review the nine discovered schemas/annotations, authenticate, then test direct,
   indirect, follow-up, empty, stale, partial, provider-failure, and unsupported
   requests. Refresh metadata after descriptor or widget changes.

Live registration is an external deployment gate until a public domain and OAuth
configuration are supplied; local tests do not claim that gate passed.

## Apps resource and CSP

Only `get_portfolio_snapshot` attaches
`ui://trading212-portfolio/snapshot-v1.html`. The dependency-free card consumes
`ui/notifications/tool-result` through the MCP Apps bridge first, feature-detects
`window.openai.toolOutput` only as a compatibility fallback, and renders untrusted
data via `textContent`. It performs no network requests or subframing, so both CSP
domain allowlists are exactly empty. Change the resource URI when HTML, CSS, or
JavaScript changes incompatibly.

## Pinned SDK compatibility gate

`mcp==2.1.1` is pinned. Its `mcp.types.Tool` wire model does not contain the
top-level `securitySchemes` extension documented by OpenAI, so serializing such a
field through the supported Python model is impossible. Every descriptor emits the
official `_meta.securitySchemes` compatibility mirror with its exact OAuth scopes;
`tests/contract/test_mcp_contract.py` locks this behavior and records the absent
top-level field as an upstream SDK gate. Do not fabricate top-level support or
silently remove authentication metadata.

Official references used for this implementation:

- <https://developers.openai.com/plugins/build/mcp-server>
- <https://developers.openai.com/plugins/build/chatgpt-ui>
- <https://developers.openai.com/plugins/plan/tools>
- <https://developers.openai.com/plugins/reference>
- <https://developers.openai.com/plugins/deploy/connect-chatgpt>
