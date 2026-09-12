# Widget presentation boundaries

The five MCP resources have scoped local P209 acceptance at `d70ab445de38aee255275880c5ef7a105ebbb939`, with actual widget cases and reviewed captures retained in [P209 scoped evidence](../../docs/implementation/evidence/phase-2-p2-09-d70ab44.json). Rendering bounds and compatibility remain as described below. Final shared scenarios and live ChatGPT registration remain incomplete; no new full Compose runtime or cleanup is claimed.

P2-09 and its assigned S33 authorization scenario are complete at `bd47329cca5c1409486fff40d48e92163ab4a8af` in the [S33 supplement](../../docs/implementation/evidence/phase-2-p2-09-s33-bd47329.json). This adds authorization and relevant build/security evidence; it does not create new widget/browser/visual observations. Phase 2 remains in progress at 9/10 packages (90%), 23/29 local rows and 31/40 scenarios, with P2-10 in_progress and implemented_unverified, Phase 3 not_started, owner-deferred CI and a null final release SHA.

The five static resources keep their existing URI, MIME, and Python export names:

| Resource | Export | Presentation |
| --- | --- | --- |
| `ui://trading212-portfolio/snapshot-v1.html` | `SNAPSHOT_WIDGET_HTML` | Original snapshot |
| `ui://trading212-portfolio/contribution-plan-v1.html` | `PLAN_WIDGET_HTML` | Manual contribution plan |
| `ui://trading212-portfolio/performance-comparison-v1.html` | `HISTORICAL_WIDGET_HTML` | Performance and comparison |
| `ui://trading212-portfolio/xray-v1.html` | `XRAY_WIDGET_HTML` | Effective exposure and overlap |
| `ui://trading212-portfolio/report-status-v1.html` | `REPORT_WIDGET_HTML` | Private report job status |

All remain `text/html;profile=mcp-app`. Registry metadata and the exact 25 tools,
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

## Historical P209 implementation status

The five MCP resources present canonical results within local display bounds.
P209 implementation is in progress. Focused desktop/mobile browser and image
review checks passed on the corrected working source; immutable acceptance remains
pending. Registry and service
acceptance are tracked in the
[P209 implementation record](../../docs/integrations/P2_09_MCP_REGISTRY_ACCEPTANCE.md).
