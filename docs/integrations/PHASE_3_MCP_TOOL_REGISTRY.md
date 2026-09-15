# Phase 3 MCP Tool Registry

**Status:** Accepted design; registration follows completed vertical implementations

Preserve all 25 frozen Phase 2 names, input/output semantics and scopes. Add exactly
these thirteen in order, final total 38. Unfinished tools are absent, never success stubs.
P=portfolio:read, N=analytics:read. Every row needs P+N and current account grants/owner;
additional scopes below are required too. Strict bounded API DTOs reject unknown fields,
financial floats, malformed IDs and foreign references. No caller owner/scopes/URLs.
Run/item reads require account_id and exact retained ID; Page is signed and bounded.

| # | Name | Service | Additional scope | Kind | Input/result |
| --- | --- | --- | --- | --- | --- |
| 26 | create_risk_run | CreateRiskRun | risk:write | COMMAND | CreateRiskRunRequest + idempotency_key; RiskRunView |
| 27 | get_risk_summary | GetRiskRun | none | READ | account_id, run_id; RiskRunView |
| 28 | get_risk_matrix | GetRiskMatrix | none | READ | account_id, run_id; matrix/coverage |
| 29 | list_scenarios | ListScenarios | none | READ | account_id, Page; scenario summaries |
| 30 | create_scenario_run | CreateScenarioRun | scenarios:write | COMMAND | CreateScenarioRunRequest + idempotency_key; ScenarioRunView |
| 31 | get_scenario_result | GetScenarioRun | none | READ | account_id, run_id; ScenarioRunView |
| 32 | compare_scenarios | CompareScenarios | none | READ | account_id, two distinct run IDs; comparison |
| 33 | create_projection_run | CreateProjectionRun | projections:write | COMMAND | ProjectionRequest + idempotency_key; ProjectionRunView |
| 34 | get_projection | GetProjectionRun | none | READ | account_id, run_id; ProjectionRunView |
| 35 | list_goals | ListGoals | none | READ | account_id, Page; goal summaries |
| 36 | get_goal_analysis | GetGoalAnalysis | none | READ | account_id, run_id; GoalAnalysis |
| 37 | get_research_summary | GetResearchSummary | research:read | READ | account_id, pinned xray reference, cutoff, filters/Page; ResearchSummary |
| 38 | get_research_item | GetResearchItem | research:read | READ | account_id, item_id; ResearchItemView |

| Kind | readOnlyHint | destructiveHint | idempotentHint | openWorldHint |
| --- | --- | --- | --- | --- |
| READ | true | false | true | false |
| COMMAND | false | false | true | false |

Commands create private records using retained inputs, never broker/provider calls.
Recheck grants/licenses on reads, execution and replay. Failures/expiry/cancellation
have safe reasons and no result before atomic publication. Result<=2 MiB, bounded
previews/exact omissions, declared outputSchema. Annotations never replace auth.

## Resources

Preserve five Phase 2 URIs. Add under ui://trading212-portfolio/:
allocation-v1.html, drift-v1.html, risk-v1.html, scenario-v1.html,
projection-v1.html, research-v1.html. Existing get_direct_allocation and
get_drift_analysis attach allocation/drift without changing financial semantics.
Risk tools attach risk; scenario run/read/compare attach scenario; projection/run/goal
analysis attach projection; research attaches research. Lists remain useful as text.

MIME text/html;profile=mcp-app. Descriptor _meta.ui.resourceUri and visibility
model/app with existing outputTemplate/widgetAccessible aliases. Resource _meta.ui
has csp.connectDomains=[], resourceDomains=[], prefersBorder and trusted optional
domain; mirror existing OpenAI aliases, no frames. No remote font/image/script/fetch,
eval, forms or raw-content HTML. Hash-based document CSP remains restrictive.

Validate ui/initialize and tool-result notifications; explicit reads use tools/call
with feature-detected compatibility fallback. Sort/selection/table expansion are
local presentation state only, no persisted account finance. Discard late foreign-
account results. textContent and canonical decimal strings, method/source/quality,
loading/errors/retry, accessible tables, focus/reduced motion are required.

Local signed-JWT/browser tests cover exact38 descriptors, strict schema/annotations,
scopes/CSP, command conflict/concurrent replay, bounded outputs and zero broker/provider
dispatch. Public ChatGPT registration remains separately unverified.


## Current implementation checkpoint

Risk tools26-28 and risk-v1.html are implemented. The executable registry currently
contains28 tools and6 resources; the original25 remain in order with their exact
inputs, scopes and outputs. The remaining ten premium tools and five new resources
are unregistered until their service implementations exist. This is not final P3-05
acceptance or public ChatGPT registration. Risk result envelopes wrap the same
RiskRunResponse/RiskMatrixResponse used by REST, with a closed safe error alternative.
Risk widget reads use tools/call after host capability negotiation, with the existing
window.openai.callTool compatibility fallback when available. Refresh is limited to
summary/matrix for the displayed owned account/run, one pending read and15 seconds.
Partial inputs, cancellation, errors and teardown clear financial content; late
responses cannot replace a new account/run selection. No broker command is available.
