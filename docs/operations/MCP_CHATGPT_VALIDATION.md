# MCP Inspector and ChatGPT Developer Mode Validation

**Status:** Phase 1 operational procedure
**External gate:** public HTTPS/OAuth deployment and ChatGPT connection remain
`blocked_external` until the owner supplies that environment and runs this
procedure.

## 1. Local MCP Inspector validation

Local synthetic authentication is only for loopback `local`/`test` validation.
Never expose it through a tunnel. Start the MCP service from one terminal:

```bash
T212PI_ENVIRONMENT=test \
T212PI_LOCAL_SYNTHETIC_AUTH_ENABLED=true \
T212PI_MCP_HOST=127.0.0.1 \
T212PI_MCP_PORT=8001 \
uv run --package trading212-mcp python -m trading212_mcp.main
```

Obtain the deterministic synthetic account identifier without copying an ID from
source:

```bash
uv run python -c 'from trading212_application import SyntheticPortfolioService; print(SyntheticPortfolioService.ACCOUNT_ID)'
```

In a second terminal, start the official MCP Inspector:

```bash
npx @modelcontextprotocol/inspector@latest
```

Select **Streamable HTTP**, enter `http://127.0.0.1:8001/mcp`, and initialize.
Capture the Inspector package version used in the validation record. Verify:

1. exactly these nine tools are discovered: `get_account_summary`,
   `get_portfolio_snapshot`, `list_positions`, `list_recent_transactions`,
   `get_dividend_summary`, `get_direct_allocation`,
   `compare_portfolio_snapshots`, `get_reconciliation_status`, and
   `get_data_quality_summary`;
2. every descriptor is read-only, non-destructive, idempotent, closed-world, and
   has a bounded input/output schema plus the documented authentication metadata;
3. repeated identical calls return equivalent canonical values;
4. invalid/extra input keys, malformed cursors, excessive limits, unknown IDs,
   and cross-account access fail with bounded sanitized errors;
5. empty, stale, partial, unavailable, and provider-failure states remain explicit;
6. `get_portfolio_snapshot` attaches the versioned
   `ui://trading212-portfolio/snapshot-v1.html` resource and the widget renders;
7. widget CSP connect/resource domain allowlists are empty and no credential,
   raw provider payload, or private error detail appears.

Local inspection does not prove Internet reachability, OAuth, or ChatGPT
registration.

## 2. Authenticated public staging prerequisite

ChatGPT requires a public HTTPS Streamable HTTP endpoint. Deploy staging with a
trusted certificate and compose the shared bearer authenticator, OAuth 2.1
issuer/resource metadata, exact allowed host/origin lists, and
`T212PI_MCP_PUBLIC_BASE_URL=https://<reviewed-host>`. The endpoint is
`https://<reviewed-host>/mcp`.

Do not tunnel the local synthetic server. Use an authenticated staging instance
containing only approved synthetic or Demo read-only data. Before ChatGPT:

- validate OAuth discovery/token audience and `/mcp` with Inspector;
- prove unauthenticated, invalid-token, wrong-audience, missing-scope, and
  cross-owner calls are denied;
- confirm TLS, host/origin protections, CSP, redaction, bounded schemas, and all
  nine tool annotations;
- verify `/health/live` and `/health/ready` disclose no dependency or secret
  details.

## 3. ChatGPT Developer Mode connection

Follow the current official OpenAI connection documentation because UI labels may
change. At this release:

1. In ChatGPT, open **Settings → Security and login** and enable
   **Developer mode**. Availability can depend on account/workspace policy.
2. Open **ChatGPT Plugins**, select the plus button, and enter the reviewed
   user-facing name and description.
3. Under **Connection**, select the public endpoint method and enter the complete
   `https://<reviewed-host>/mcp` URL. A workspace-associated Secure MCP Tunnel is
   the documented private-development alternative.
4. Create the connection, complete OAuth, and review the discovered tools and
   metadata before using it in a new conversation.

Do not paste a Trading 212 credential into ChatGPT; ChatGPT authenticates to this
application's MCP resource server only. Phase 1 validation does not require
public directory submission.

After discovery, review all nine schemas and annotations before enabling the
connection. Test direct requests, indirect discovery, follow-up conversation,
repeated calls, the snapshot widget, empty/stale/partial/unavailable states,
provider failure, and unsupported/mutating requests. Confirm ChatGPT preserves
as-of time, reporting currency, methodology, quality, coverage, and warnings and
does not imply trade execution or financial advice.

Refresh metadata after any descriptor, schema, widget URI, CSP, or OAuth change.
Record the staging URL, release SHA/image digest, OAuth issuer/audience (not
tokens), Inspector version/results, ChatGPT connection time, nine-tool inventory,
widget evidence, negative tests, and any browser/console errors.

Official references:

- <https://developers.openai.com/plugins/deploy/connect-chatgpt>
- <https://developers.openai.com/plugins/build/mcp-server>
- <https://developers.openai.com/plugins/build/chatgpt-ui>
- <https://modelcontextprotocol.io/docs/tools/inspector>

See [`apps/mcp/README.md`](../../apps/mcp/README.md) for the implementation-level
tool, widget, authentication, and SDK compatibility notes.
