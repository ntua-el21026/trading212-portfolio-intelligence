# ChatGPT MCP and Apps SDK Contract

**Status:** Accepted  
**Phase 1 scope:** Remote authenticated read/fetch MCP service with core portfolio tools  
**Phase 2/3 scope:** Expanded analytical tools and rich interactive resources

## 1. Purpose

Enable the user to query the canonical portfolio naturally from a normal ChatGPT conversation while preserving the same values, authorization, data quality, provenance, and read-only safety as the standalone web application.

## 2. Architecture

```text
ChatGPT
  → authenticated HTTPS MCP transport
  → MCP composition root
  → application-service ports
  → canonical repositories + deterministic analytics
```

The MCP application does not access Trading 212 transport, SQLAlchemy sessions, or calculation internals directly. It uses application services with the same authorization policy as HTTP.

## 3. Transport and SDK rule

Phase 1 shall use the current official MCP Python SDK primitives and a remote transport supported by ChatGPT at implementation time. Codex must verify the official SDK/transport API during P1-11 and lock compatible versions. The architecture is independent of a specific convenience wrapper.

No unauthenticated Internet-accessible MCP endpoint is permitted.

## 4. Tool design principles

- Explicit and narrow; no generic query, SQL, HTTP, URL, or filesystem tool.
- Read-only in broker and application semantics, except an optional high-level `refresh_portfolio_data` command that only schedules allowlisted broker reads.
- Clear descriptions state that values are portfolio observations/analytics and no trades are placed.
- Small typed inputs with enums, bounds, and defaults.
- Structured typed outputs, not prose-only strings.
- Bounded results with pagination, top-N, or summarized mode.
- Stable error categories and actionable safe messages.
- Every financial output includes valuation/source timestamps, reporting currency, method/version, quality state, and warnings.
- Tool names are durable contracts; breaking changes require versioning/migration.

## 5. Phase 1 tool registry

### `get_account_summary`

Returns account currency, cash/account totals, source timestamp, freshness, and reconciliation summary.

### `get_portfolio_snapshot`

Returns canonical total value, cash, invested value, net-contribution coverage, realized/unrealized/dividend fields where reliable, and top-level metadata.

### `list_positions`

Inputs: account selector when needed, page/cursor, bounded limit, sort enum, optional search.  
Returns canonical position rows with IDs, listing identifiers, quantity, valuation, P/L coverage, weight, timestamps, and quality.

### `list_recent_transactions`

Inputs: bounded date range, type filter enum, cursor/limit.  
Returns canonical activity; unknown/unsupported types remain explicit.

### `get_dividend_summary`

Returns covered period, totals by currency/reporting currency where available, recent dividend rows, and data coverage warnings.

### `get_direct_allocation`

Returns direct position weights and cash allocation; no ETF look-through claim in Phase 1.

### `compare_portfolio_snapshots`

Inputs: two snapshot IDs or bounded date selectors.  
Returns value/cash/position changes, with effects limited to available Phase 1 data and no fabricated attribution.

### `get_reconciliation_status`

Returns last reconciliation state, coverage, discrepancy counts/categories, residuals where safe, and remediation guidance.

### `get_data_quality_summary`

Returns freshness and quality state by capability/dataset, source cutoffs, warnings, and failed/partial runs.

### `refresh_portfolio_data` — optional configuration

Schedules a high-level read-only refresh scope. It accepts only an enum (`summary`, `positions`, `activity`, `all`) and optional idempotency key; it cannot accept provider paths. It returns a refresh-run ID and status. Deployments may disable it and expose only fetch tools.

## 6. Output envelope

Semantic structure:

```json
{
  "data": {},
  "as_of": "2026-08-31T12:00:00Z",
  "reporting_currency": "EUR",
  "data_quality": {
    "state": "fresh",
    "warnings": [],
    "source_cutoff_at": "2026-08-31T11:59:30Z"
  },
  "calculation": {
    "name": "direct_allocation",
    "version": "1.0.0",
    "calculated_at": "2026-08-31T12:00:01Z",
    "assumptions": []
  },
  "pagination": null
}
```

Exact schemas live with source code and generated contract artifacts.

## 7. Authentication and authorization

- Remote MCP authentication is provided by an adapter compatible with the selected deployment/ChatGPT configuration.
- Tokens/credentials are validated server-side and mapped to an application principal.
- Account ownership is enforced in application services.
- Tool-level scopes distinguish portfolio reads, activity reads, and optional refresh command.
- Authentication errors reveal no account existence or provider detail.
- Sessions/tokens are logged only by opaque hashed/correlation identifiers.

## 8. Privacy and prompt-injection boundary

Broker data is private user data. The server returns only data required by the invoked tool. It must not embed secrets or hidden configuration in tool output/resources.

Research/web content introduced in Phase 3 is untrusted data and cannot alter tool policy, authorization, system instructions, provider allowlists, or execution behavior. Portfolio notes/source text must be clearly separated from executable/tool metadata.

## 9. Apps SDK resources

Phase 1 may provide a minimal summary resource/card, but tool correctness must not depend on rich UI.

Later resources can include:

- portfolio summary card;
- allocation/drift visualization;
- contribution-plan table;
- data-quality panel;
- performance/benchmark chart;
- X-ray exposure explorer;
- risk/scenario result card.

Resources consume structured result data and implement accessible text alternatives, keyboard interaction, responsive layout, and reduced motion.

## 10. Consistency requirement

For a fixed account, source cutoff, calculation version, reporting currency, and parameters:

```text
HTTP API value = Web-displayed canonical value = MCP structured value = Report value
```

Formatting may differ; authoritative decimals and methods may not.

Parity tests must invoke the underlying application service and each interface adapter against the same fixtures.

## 11. Failure behavior

Tools return stable safe errors such as:

- authentication required;
- authorization denied;
- data refresh pending;
- provider rate limited/unavailable;
- partial/stale/unreconciled data;
- calculation unavailable due to coverage;
- invalid bounded input.

The language model receives enough metadata to explain limitations but not raw upstream errors, stack traces, or internal paths.

## 12. Phase 1 acceptance

- Remote MCP server starts from documented commands/configuration.
- Tool schemas validate and appear in MCP inspection tests.
- Authentication is required outside local test mode.
- Every tool is mapped to a typed application use case.
- All outputs are bounded and include common metadata.
- API/MCP parity tests pass.
- Unknown tools/inputs and oversized requests fail closed.
- Broker write capability is unreachable from MCP by design and negative tests.
- A mock-data end-to-end ChatGPT-compatible flow is demonstrated.
- Live ChatGPT registration remains an explicit external deployment gate if domain/auth configuration is unavailable.
