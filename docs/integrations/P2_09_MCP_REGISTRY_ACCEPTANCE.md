# P2-09 MCP registry implementation and acceptance

Status: **implementation in progress; local acceptance pending**. P209 follows
accepted P208 closure `9505e2650aadedd504a0a94117c018b0b7ed153f`. The registry
retains exactly 25 bounded tool names, including the original nine reads and the
two internal durable commands. Trading 212 access remains restricted to the
frozen ten GET capabilities. GitHub Actions remains owner-deferred.

Authorities: owner attachment section 18; [frozen registry](PHASE_2_MCP_TOOL_REGISTRY.md);
[ADR-0016](../adr/ADR-0016-INTERNAL-MCP-COMMANDS.md). The acceptance oracle in
[tests/mcp_registry_cases.py](../../tests/mcp_registry_cases.py) independently names
the original nine and sixteen additions. It does not derive its expected names,
scopes or field catalogue from production registration.

## Private argument errors and compatibility

The original nine tools call `finalize_tool_contract`, which previously set only
`extra="forbid"`. The pinned MCP 2.1.1 `Tool.run` includes Pydantic validation
errors in `ToolError`; invalid values and caller-controlled unknown field names
could therefore appear before authentication or the gateway safe-error boundary.

The adapter uses a private, non-strict argument base with a safe unknown-field
validator and `hide_input_in_errors=True`. It preserves SDK JSON pre-parsing,
accepted opaque identifiers, integer/date coercion, date limits, response classes,
decimal serialization and the original nine names. The sixteen newer tools keep
their strict argument hardening. This correction changes the compatibility
adapter without changing the pinned SDK dependency or canonical services.

## Verification predicates

The following table identifies maintained assertions and their scope. Source
coverage alone does not establish a passing gate or package acceptance.

| Predicate | Existing maintained source coverage | Added acceptance source |
| --- | --- | --- |
| Exact 25 names; original nine in discovery order; exact required/optional fields; no generic input extension; every nested input object closed | `tests/contract/test_mcp_contract.py` checks the production-derived name tuple and basic descriptor shape; family unit tests check their descriptors | `test_phase2_mcp_registry.py::test_independent_exact_25_names_fields_scopes_and_annotations_after_p208` uses an independent catalogue and recurses into input definitions |
| Read/command annotations and exact OAuth scopes | Existing contract and family descriptor tests | Same independent contract checks exact scope membership without duplicates and all four annotation hints |
| Missing auth and each missing scope, including unrelated extra grants | Existing transport security, target and planning scope matrices; partial historical/report matrices | `test_phase2_mcp_registry_security.py` covers all 25; exact-scope positive controls precede every negative; new-family spies prove denied requests do not dispatch; legacy cases use the real synthetic canonical service |
| Private validation errors before auth; protected unknown names as well as values | New-family unit canaries and gateway safe errors | All 25 names receive unknown-key/value and invalid-known-value canaries; original nine expose the observed tests-first privacy defect before the adapter fix |
| Original nine compatibility | `tests/unit/mcp/test_gateway.py`; real ingestion parity in `tests/integration/test_api_mcp_postgres_parity.py` | Explicit original-nine success/schema cases, opaque snapshot alias, coerced integer, optional literal JSON pre-parsing, date window and narrower page bounds |
| Owner/account/resource authorization | Real canonical PostgreSQL target, planning, historical, X-ray, report and alert service tests; existing MCP integrations for the first four families and original nine | Original-nine cross-owner/unknown-account reads; report MCP foreign owner and revoked physical grant; alert MCP resumed cursor after physical grant revocation |
| Decimal strings, methodology, quality, warnings, assumptions, source/cutoff and account pins | Family gateway/schema tests and real API/MCP integrations; canonical report type/source/retention suites | Report command/status/list data compared with the HTTP API, retained input digest/snapshot/context preserved across retry; alert WindowPage compared with the exact canonical query |
| Command idempotency, immutable pins, one durable job/outbox, safe duplicate delivery and restart | `test_planning_postgres.py`, `test_planning_api_postgres.py`, `test_report_postgres.py`, `test_report_dispatch_postgres.py` | Real MCP report concurrent requests, fresh service/runtime retry, changed-format conflict, actual dispatch acknowledgment and worker duplicate, API same-key replay, exact job audit actions and no download grant |
| Bounded pagination and restart | Original collection, target hierarchy, planning revision, historical, X-ray and report history suites | Alert MCP two-page continuation across new service/runtime, changed-filter cursor denial and exact full-scope counts |
| No provider/broker action or generic escape hatch | `test_mcp_security.py` architecture/transport checks; planning command HTTP transport trap; exact bounded registry | Independent exact input catalogue excludes generic paths; report scenario arms an outbound HTTP trap with a blocked positive control before any command/worker/retry |
| Current source license and retention before protected payload decode | Existing historical/X-ray/report/alert PostgreSQL retention, privacy, source-revocation and current-grant tests | New transport scenarios test current grants only. They do not replace the existing physical license/retention suites or claim every resource permutation |

The scope matrix's synthetic service and spies exercise gateway boundaries.
Durable ownership, current licensing, retention and recovery remain covered by
the corresponding real PostgreSQL family scenarios.

## Canonical input and resource boundaries

P208 supplies the optional `xray_run_id` on `get_actual_vs_target`,
`get_drift_analysis` and `generate_portfolio_report`, together with their canonical
company projections and forwarding checks. P209 preserves those exact input
fields and their existing service, schema and authorization boundaries.

The MCP alert tool accepts `AlertSummaryWindowQuery` and returns
`AlertSummaryPage`; the REST summary uses `AlertSummaryTopQuery`. Their different
requests require separate canonical oracles. The MCP scenario compares the exact
WindowPage content, counts, cursor binding and current authorization with its
canonical service query.

The five widget resources retain their existing URIs and MIME type. Their
canonical-string display, local collection bounds, CSP, notification lifecycle
and keyboard behavior are described in
[Widget presentation boundaries](../../apps/mcp/WIDGET_PRESENTATION.md).
Browser presentation checks complement registry and durable-service checks;
live ChatGPT registration remains a separate external condition.

## Recorded validation and remaining acceptance

The tests-first privacy regression produced the intended RED against the original
adapter: nine failures for reflected caller-controlled names/values, 16 passes and
35 deselections (`p209-private-errors-red-01`, exit 1, 6.354 seconds). The source
was unchanged during that working-tree gate. The corrected registry gate passed 62 cases, existing MCP compatibility/security
checks passed 228, and both report/alert PostgreSQL cases passed after two retained
test-authoring failures. Static checks passed after a result-model type annotation
and removal of two redundant test casts; both preceding static failures are retained.
The corrected widget suite passed 74 desktop/mobile cases and the production web
build; ROOT reviewed the ten widget images, including two corrected planning
images. Immutable validation and source/image scans remain pending. These focused observations do not
establish package acceptance.

The regression receipt is retained as external task evidence
`gates/p209-private-errors-red-01.json` (SHA-256
`52aed964c9be94230a156f5cca1f7c55af3b08b9a9fe555c88242d9c2675bf3c`), with its
original log (SHA-256
`6d5abc32b1a670a34e2dd09cbf80a616ff4252b5a1b0233a8a1a1c9bc61752a3`).

Package acceptance still requires recorded registry/compatibility/security and
real PostgreSQL outcomes, reviewed desktop/mobile widget captures, relevant
static checks and the immutable local validation/security/runtime evidence for
the integrated source. Shared scenarios and final Phase 2 acceptance remain
incomplete. Current results belong in the [project validation record](../../VALIDATION_REPORT.md)
and [scenario ledger](../implementation/PHASE_2_SCENARIO_EVIDENCE.md).
