# Widget presentation boundaries

Current Phase3 implementation exposes 36 tools and 8 resources. The five Phase2
resources retain their accepted contracts; risk, scenario and projection are
additive resources. Final Phase3 acceptance remains separate from implementation.

## Historical Phase2 evidence

The five MCP resources have scoped local P209 acceptance at `d70ab445de38aee255275880c5ef7a105ebbb939`, with actual widget cases and reviewed captures retained in [P209 scoped evidence](../../docs/implementation/evidence/phase-2-p2-09-d70ab44.json). Rendering bounds and compatibility remain as described below. Final shared local scenarios and the actual P210 runtime/teardown are separately bound by [final P210 local evidence](../../docs/implementation/evidence/phase-2-p2-10-3998426.json) at 3998426aa7e7614e421518efd01b08188e194100. Live ChatGPT registration remains an external condition. Postacceptance housekeeping is recorded in the separate post-delivery receipt.

P2-09 and its assigned S33 authorization scenario are complete at `bd47329cca5c1409486fff40d48e92163ab4a8af` in the [S33 supplement](../../docs/implementation/evidence/phase-2-p2-09-s33-bd47329.json). This adds authorization and relevant build/security evidence; it does not create new widget/browser/visual observations. Phase 2 is locally complete at 3998426aa7e7614e421518efd01b08188e194100: 10/10 packages (100%), 29/29 local rows and 40/40 scenarios. P2-10 and the shared local predicates are complete under the final same-source acceptance. At that historical checkpoint Phase3 was not_started. GitHub Actions remains owner-deferred and unverified, with no CI pass claim. The final Phase 2 release evidence SHA is 3998426aa7e7614e421518efd01b08188e194100. See [final P210 local evidence](../../docs/implementation/evidence/phase-2-p2-10-3998426.json).

The five static resources keep their existing URI, MIME, and Python export names:

| Resource | Export | Presentation |
| --- | --- | --- |
| `ui://trading212-portfolio/snapshot-v1.html` | `SNAPSHOT_WIDGET_HTML` | Original snapshot |
| `ui://trading212-portfolio/contribution-plan-v1.html` | `PLAN_WIDGET_HTML` | Manual contribution plan |
| `ui://trading212-portfolio/performance-comparison-v1.html` | `HISTORICAL_WIDGET_HTML` | Performance and comparison |
| `ui://trading212-portfolio/xray-v1.html` | `XRAY_WIDGET_HTML` | Effective exposure and overlap |
| `ui://trading212-portfolio/report-status-v1.html` | `REPORT_WIDGET_HTML` | Private report job status |

All five remain `text/html;profile=mcp-app`. Their registry metadata and25 tools,
including the original nine input/output contracts, belong to the server layer.

Rendering uses canonical returned strings and explicit units. No widget converts
financial values through Number, computes totals, normalizes ratios, substitutes
missing values with zero, fetches data, executes trades, or requests internal
commands. Snapshot preserves the Phase 1 decimal syntax, including values beyond
Phase 2 q18; values longer than 512 characters get an explicit display-limit
message pointing to the unchanged structured result. Values are never truncated
or rounded. Historical metrics show their own quality, independent of run
quality. X-ray retains lower bounds, positive-below-quantum disclosure, full-scope
summaries, and explicit omitted sample weights.

All documents use hashes of their exact static script/style bytes and disable
external connections/resources, nested frames, objects, base changes, and forms.
Tool text enters textContent only. Fixed initialization messages use the existing
parent postMessage channel. Document CSP supplements host sandbox/resource CSP;
it does not replace the server's resource metadata or host sandbox.

Only parent-sourced JSON-RPC tool notifications update the view. Partial/complete
input notifications clear the previous result and show a neutral pending state;
their arguments are never treated as authorized output or displayed. Cancellation
clears the view without claiming durable job cancellation. Error CallToolResults
also clear it, even if conflicting structured success data is attached.
The standard structuredContent and existing structured_content/direct-envelope
forms remain supported. The original initial window.openai.toolOutput fallback
remains, but a late initialize error cannot replay it after tool notifications.
No additional host API or host-specific update event is assumed.

Display work has local bounds: plan pages 100 rows; historical series 3661 points;
exposure pages 100 rows; overlap Top 50 entities; report 256 pins / 64 warnings.
Nested entries must be objects before iteration. Plan explanations/warnings show
up to 16 of the returned records with exact returned/omitted preview counts
(server bounds remain 1280 warnings/explanations and 256 assumptions). Other
existing string and source-preview limits remain. Malformed displayed
collections fail safely or show an explicit unavailable disclosure and a later
valid result can recover. These display guards do not replicate full server DTO
validation or change transport byte limits.

The plan table now follows the existing focusable scrolling-region pattern.
Historical and X-ray tables retain their semantic labels and keyboard regions;
report details retain native summary controls. Snapshot full values wrap at
narrow widths. Browser tests cover these behaviors on the existing desktop/mobile
projects. Rendered heading bounds also prevent text painting across table columns;
this document does not claim an accessibility audit or live ChatGPT acceptance.

Protocol reference: [MCP Apps stable 2026-01-26 specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx),
Host-to-View notifications and lifecycle sections. The installed mcp/mcp_types
2.1.1 source supplies the CallToolResult structured_content/is_error Python names.

## Additive risk resource

ui://trading212-portfolio/risk-v1.html uses the same MIME and CSP rules. Its three
attached tools return canonical risk run/matrix DTOs. The widget does not create
runs; it exposes explicit authorized reads through tools/call after ui/initialize
negotiates host serverTools support. The compatibility callTool fallback is used
only when available. No external asset, provider, download or arbitrary tool is
accessible. Error text and untrusted source/definition text enter textContent.

Only one read is pending, with a15-second timeout. Request IDs and a selection
generation bind responses to the current account/run; partial input notifications,
account changes, cancellation and teardown discard old responses. No financial
state is persisted. Canonical strings are displayed without float conversion;
matrices are at most32 square, rolling tables show50 of at most3660 points, and
source/warning previews show exact omissions. The full UTF-8 result bound is2MiB.

Local iframe tests cover the standard lifecycle, fallback, keyboard, reduced motion,
360/768/1440-pixel layouts, exact/unavailable states, malformed numeric input,
untrusted markup, wrong senders, late replies and read timeout. Source-bound logs
and reviewed synthetic captures are retained as component evidence. This is not a
live ChatGPT test or final premium accessibility/performance acceptance.


## Additive projection resource

`ui://trading212-portfolio/projection-v1.html` is attached to tools 33, 34 and 36:
`create_projection_run`, `get_projection` and `get_goal_analysis`. Tool 35,
`list_goals`, remains a structured text collection. The first 32 tool contracts
and seven resource documents are preserved. This section describes implementation
boundaries; it does not assert executed validation or live ChatGPT acceptance.

The widget reads only `get_projection` and `get_goal_analysis` through the
negotiated host bridge. It does not create a run or a goal, cancel a job, resample
paths, obtain credentials, call a provider, or submit a broker action. The sole
new MCP command creates a private application run under current account grants,
portfolio/analytics read scopes and projections write scope. Signed principal
resolution and source authorization remain server responsibilities; widget inputs
and source IDs do not grant authority. No cookie-authenticated browser mutation
is introduced, so no additional CSRF mechanism is added to this bearer transport.

Saved assumptions, dated schedules, every variant's retained distributions and
terminal histograms, cash-flow summaries, goal targets and Wilson intervals are
available as semantic tables. A point page contains at most 100 complete rows;
explicit continuation preserves account/run, signed cursor, requested page size,
next ordinal and saved result digest. Inspecting a point reveals all 12 monetary
fields, all asset values, funding flags and residuals. Financial strings retain
the exact returned decimal representation and currency; model estimates and
unavailable states stay explicit. Source and warning previews disclose their
omitted counts, and unavailable original source clocks stay unavailable.

The bounded public view is at most 1 MiB and the complete MCP result, including
text and metadata, is at most 2 MiB of UTF-8 JSON. The host bridge supports one
pending read with a 15-second deadline. Account/run changes, partial arguments,
cancellation and teardown discard prior results and late replies. A host without
tool-read capability can still render the canonical tables. The existing
feature-detected `window.openai.callTool` compatibility path remains available;
standard MCP Apps initialization and `tools/call` are preferred. The resource
uses the same MIME, script/style hashes and empty network/asset CSP allowlists as
the existing resources. There is no browser persistence or financial arithmetic.
