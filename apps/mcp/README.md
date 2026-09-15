# MCP / ChatGPT integration

The Streamable HTTP service at /mcp currently exposes28 bounded tools: the original
nine portfolio reads,16 Phase2 tools and three Phase3 risk tools. The frozen
[Phase3 registry](../../docs/integrations/PHASE_3_MCP_TOOL_REGISTRY.md) defines the
remaining additions; unfinished tools are not registered. Six static resources
present snapshot, planning, performance, X-ray, report status and risk results.

All financial values come from typed canonical application services backed by
PostgreSQL. No tool accepts a broker path, method, arbitrary URL, SQL, filesystem
path or shell command. create_contribution_plan, generate_portfolio_report and
create_risk_run create bounded private application records with semantic idempotency;
their annotations correctly declare writes. Every other tool is a read. There are
no broker/provider requests in risk tools and no execution capability.

Risk creation requires portfolio:read, analytics:read and risk:write. Summary and
matrix require the first two. Current principal/account grants and retained source
licenses are checked by the service on every operation, including replay. The
risk gateway bounds inputs to64KiB and complete results to2MiB, uses the existing
RiskRunResponse/RiskMatrixResponse contracts and logs hashed identity references.
The original25 tool input/output semantics and scopes remain preserved.

## Local execution and verification

Use the existing project environment and one scoped PostgreSQL service. Migrate
and seed synthetic data first; resolve DATABASE_URL through the local secret
configuration. Synthetic authentication is disabled by default and may only be
explicitly enabled for loopback local/test work:

```bash
T212PI_ENVIRONMENT=test T212PI_LOCAL_SYNTHETIC_AUTH_ENABLED=true \
T212PI_MCP_HOST=127.0.0.1 T212PI_MCP_PORT=8001 \
uv run --package trading212-mcp python -m trading212_mcp.main
```

Health paths are /health/live and /health/ready. Without DATABASE_URL or configured
authentication the CLI fails closed. For tests use the pinned project environment:

```bash
uv run pytest tests/contract/test_mcp_contract.py tests/contract/test_phase2_mcp_registry.py tests/unit/mcp/test_risk_gateway.py
uv run pytest tests/integration/test_risk_mcp_postgres.py tests/integration/test_real_jwt_mcp_postgres.py
```

Integration fixtures create and remove temporary databases in the existing
PostgreSQL container. They use real signed tokens, SDK transport and persisted
current grants; risk execution uses the real isolated worker. They do not claim
public OAuth/ChatGPT registration or final Phase3 acceptance.

## Authentication and static resources

Deployed composition requires a shared trusted bearer authenticator, exact issuer
and resource audience, HTTPS public_base_url, explicit allowed hosts/origins and
an explicit cursor key. Credentials remain outside the repository. Existing
identity, malformed-claim and trusted-key regressions remain mandatory. Local
synthetic mode must never be exposed through a public tunnel.

All resources use text/html;profile=mcp-app, hash-based document CSP and empty
connect/resource allowlists. Risk initializes the stable MCP Apps2026-01-26 bridge,
then permits only host-mediated get_risk_summary/get_risk_matrix for the current
account/run. One read may be pending for15 seconds. Partial inputs, cancellation,
errors, account changes and teardown clear previous financial content. The
feature-detected window.openai.callTool/toolOutput fallback preserves existing
compatibility. See [widget boundaries](WIDGET_PRESENTATION.md).

mcp==2.1.1 remains pinned. Its Tool model lacks top-level securitySchemes, so the
existing _meta.securitySchemes compatibility mirror is emitted with exact scopes.
No top-level support or public deployment is claimed. Official references:

- [MCP server](https://developers.openai.com/plugins/build/mcp-server)
- [ChatGPT UI](https://developers.openai.com/plugins/build/chatgpt-ui)
- [Tool metadata](https://developers.openai.com/plugins/reference)
- [Stable MCP Apps protocol](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx)
