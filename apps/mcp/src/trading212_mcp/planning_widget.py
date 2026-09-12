# ruff: noqa: E501
"""Static, network-isolated presentation of validated manual planning tool output."""

from __future__ import annotations

import base64
import hashlib

PLAN_WIDGET_URI = "ui://trading212-portfolio/contribution-plan-v1.html"
PLAN_WIDGET_MIME = "text/html;profile=mcp-app"
_STYLE = """
:root{color-scheme:light dark;font-family:system-ui,sans-serif;font-variant-numeric:tabular-nums}
*{box-sizing:border-box}body{margin:0;padding:16px}main{max-width:760px;margin:auto}
h1{font-size:1.4rem}p,dd,th,td{overflow-wrap:anywhere}dl{display:grid;grid-template-columns:1fr 2fr;gap:8px}
dt{font-weight:600}dd{margin:0}.table-wrap{max-height:480px;overflow:auto}
:focus-visible{outline:3px solid #1879bd;outline-offset:3px}table{border-collapse:collapse;width:100%;table-layout:fixed}
caption{text-align:left;font-weight:600;margin:12px 0}th,td{text-align:left;padding:8px;border-bottom:1px solid #888}
[hidden]{display:none!important}@media(max-width:480px){dl{grid-template-columns:1fr}dd{margin-bottom:8px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
""".strip()
_SCRIPT = r"""
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const records = (value, maximum) => Array.isArray(value) && value.length <= maximum && value.every(record);
  const money = (value) => value && typeof value.amount === "string" &&
    /^-?(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$/.test(value.amount) &&
    typeof value.currency === "string" && /^[A-Z]{3}$/.test(value.currency)
      ? `${value.amount} ${value.currency}` : "Unavailable";
  const text = (value, maximum = 120) => typeof value === "string" && value.length <= maximum ? value : "Unavailable";
  const states = new Set(["queued", "running", "succeeded", "failed", "expired", "cancelled"]);
  const outcomes = new Set(["optimal", "feasible_nonoptimal", "infeasible", "unavailable", "failed"]);
  const render = (envelope) => {
    byId("rows").replaceChildren();
    byId("content").hidden = true;
    if (!envelope || envelope.error || !record(envelope.data) || envelope.execution_allowed !== false) {
      byId("status").textContent = "Planning data is unavailable. The conversation remains usable.";
      return;
    }
    const data = envelope.data;
    const job = data.job || data;
    if (!record(job) || !states.has(job.state) || job.execution_allowed !== false) {
      byId("status").textContent = "The planning response does not match its contract.";
      return;
    }
    byId("status").textContent = `Job state: ${job.state}. Execution is disabled.`;
    byId("plan-id").textContent = text(job.plan_id, 36);
    byId("request-id").textContent = text(job.request_id, 36);
    const result = data.result;
    const finalized = job.state === "succeeded" && record(result) && outcomes.has(result.outcome) && result.execution_allowed === false;
    if ((result != null && !finalized) || (data.lines != null && !records(data.lines.items, 100))) {
      byId("status").textContent = "The planning response does not match its contract."; return;
    }
    byId("outcome").textContent = finalized ? result.outcome : "Not calculated";
    byId("contribution").textContent = finalized ? money(result.contribution) : "Not calculated";
    byId("residual").textContent = finalized ? money(result.residual_cash) : "Not calculated";
    byId("quality").textContent = finalized ? text(result.context?.data_quality?.state, 30) : "Not evaluated";
    byId("method").textContent = finalized ? `${text(result.context?.method?.name, 80)} / ${text(result.context?.method?.version, 30)}` : "Pending calculation";
    byId("digest").textContent = finalized ? text(data.content_digest, 64) : "No finalized result";
    byId("coverage").textContent = finalized ? text(result.context?.availability, 30) : "No analytical coverage claimed";
    const context = finalized ? result.context : null;
    for (const [id, value] of [["valuation", context?.as_of], ["cutoff", context?.source_cutoff_at], ["calculated", context?.calculated_at]]) {
      byId(id).textContent = context ? text(value, 40) : "Not calculated";
    }
    const coverage = context?.coverage;
    byId("coverage-detail").textContent = coverage
      ? `Valued: ${money(coverage.valued_total)}; matched: ${money(coverage.matched_total)}; unclassified: ${money(coverage.unclassified_total)}; ${coverage.complete === true ? "complete" : "incomplete"}.`
      : "Coverage details unavailable.";
    byId("bound").textContent = finalized ? text(result.bound_kind, 80) : "Not calculated";
    const preview = (items, maximum) => records(items, maximum)
      ? items.slice(0, 16).map((item) => `${text(item.code, 80)}: ${text(item.message, 240)}`).join("; ") + ` (${items.length} records; ${Math.max(0, items.length - 16)} omitted from this preview.)`
      : "Unavailable";
    byId("warnings").textContent = context ? preview(context.warnings, 1280) : "Not evaluated";
    byId("assumptions").textContent = context ? preview(context.assumptions, 256) : "Not evaluated";
    byId("explanations").textContent = finalized ? preview(result.explanations, 1280) : "Not calculated";
    const rows = finalized && data.lines ? data.lines.items : [];
    for (const line of rows) {
      const row = document.createElement("tr");
      for (const value of [text(line.node_key, 80), money(line.recommended_amount), money(line.post_value)]) {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      }
      byId("rows").append(row);
    }
    byId("page-note").textContent = envelope.pagination?.truncated === true
      ? "Only a bounded page is shown. Totals describe the complete saved plan."
      : "The returned page is shown; no values are calculated in this card.";
    byId("content").hidden = false;
  };
  const update = (result) => {
    // Host notifications are untrusted presentation input, even with a valid sender.
    try {
      render(result?.isError || result?.is_error ? null : result?.structuredContent ?? result?.structured_content ?? result);
    } catch (_) {
      render(null);
    }
  };
  const pending = (cancelled = false) => {
    render(null);
    byId("status").textContent = cancelled
      ? "Tool execution was cancelled. No current result is displayed."
      : "Waiting for the authorized tool result. Input arguments are not results.";
  };
  window.addEventListener("message", (event) => {
    if (event.source !== window.parent || !event.data || event.data.jsonrpc !== "2.0") return;
    const message = event.data;
    if (message.id === undefined && ["ui/notifications/tool-input", "ui/notifications/tool-input-partial"].includes(message.method)) pending();
    if (message.id === undefined && message.method === "ui/notifications/tool-cancelled") pending(true);
    if (message.id === undefined && message.method === "ui/notifications/tool-result") update(message.params);
    if (message.id === "planning-initialize" && !message.method && record(message.result) && !message.error) {
      window.parent.postMessage({jsonrpc: "2.0", method: "ui/notifications/initialized", params: {}}, "*");
    }
  }, {passive: true});
  if (window.openai?.toolOutput) update(window.openai.toolOutput);
  window.parent.postMessage({jsonrpc: "2.0", id: "planning-initialize", method: "ui/initialize", params: {
    appInfo: {name: "trading212-contribution-plan", version: "1.0.0"}, appCapabilities: {}, protocolVersion: "2026-01-26"
  }}, "*");
})();
""".strip()


def _hash(value: str) -> str:
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode("ascii")


_CSP = (
    "default-src 'none'; connect-src 'none'; img-src 'none'; font-src 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; "
    f"script-src 'sha256-{_hash(_SCRIPT)}'; style-src 'sha256-{_hash(_STYLE)}'"
)
PLAN_WIDGET_HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{_CSP}">
<title>Manual contribution plan</title><style>{_STYLE}</style></head>
<body><main aria-labelledby="title"><h1 id="title">Manual contribution plan</h1>
<p>Read-only presentation. Execution is disabled. Manual proposals only.</p>
<p id="status" role="status">Waiting for authorized planning data.</p>
<section id="content" hidden><dl>
<dt>Plan</dt><dd id="plan-id"></dd><dt>Request</dt><dd id="request-id"></dd>
<dt>Outcome</dt><dd id="outcome"></dd><dt>Contribution</dt><dd id="contribution"></dd>
<dt>Residual cash</dt><dd id="residual"></dd><dt>Quality</dt><dd id="quality"></dd>
<dt>Coverage</dt><dd id="coverage"></dd><dt>Method</dt><dd id="method"></dd>
<dt>Result digest</dt><dd id="digest"></dd><dt>Valuation</dt><dd id="valuation"></dd>
<dt>Source cutoff</dt><dd id="cutoff"></dd><dt>Calculated</dt><dd id="calculated"></dd>
<dt>Coverage detail</dt><dd id="coverage-detail"></dd><dt>Solver bound kind</dt><dd id="bound"></dd></dl>
<p>Warnings: <span id="warnings"></span></p><p>Assumptions: <span id="assumptions"></span></p><p>Outcome explanations: <span id="explanations"></span></p>
<div class="table-wrap" tabindex="0" role="region" aria-label="Saved allocation page"><table><caption>Saved allocation page</caption><thead><tr>
<th scope="col">Target</th><th scope="col">Recommended value</th><th scope="col">Post-plan value</th>
</tr></thead><tbody id="rows"></tbody></table></div><p id="page-note"></p></section>
</main><script>{_SCRIPT}</script></body></html>"""
