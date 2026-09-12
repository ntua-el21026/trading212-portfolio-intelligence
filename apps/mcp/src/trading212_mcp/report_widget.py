# ruff: noqa: E501
"""Static isolated presentation of authorized report state and immutable input pins."""

from __future__ import annotations

import base64
import hashlib

REPORT_WIDGET_URI = "ui://trading212-portfolio/report-status-v1.html"
REPORT_WIDGET_MIME = "text/html;profile=mcp-app"
_STYLE = """
:root{color-scheme:light dark;font-family:system-ui,sans-serif;font-variant-numeric:tabular-nums}
*{box-sizing:border-box}body{margin:0;padding:16px}main{max-width:760px;margin:auto}
h1{font-size:1.4rem}p,dd,li{overflow-wrap:anywhere}dl{display:grid;grid-template-columns:1fr 2fr;gap:8px}
dt{font-weight:600}dd{margin:0}ul{padding-left:1.5rem}details{margin-top:16px}
summary{cursor:pointer;padding:8px 0}summary:focus-visible{outline:3px solid currentColor;outline-offset:3px}
[hidden]{display:none!important}@media(max-width:480px){dl{grid-template-columns:1fr}dd{margin-bottom:8px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
""".strip()
_SCRIPT = r"""
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const records = (value, maximum) => Array.isArray(value) && value.length <= maximum && value.every(record);
  const states = new Set(["queued", "running", "succeeded", "failed", "expired", "cancelled"]);
  const text = (value, maximum = 120) => typeof value === "string" && value.length <= maximum ? value : "Unavailable";
  const identity = (value) => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value) ? value : "Unavailable";
  const digest = (value) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value) ? value : "Not available";
  const render = (envelope) => {
    byId("content").hidden = true;
    byId("pins").replaceChildren(); byId("warnings").replaceChildren();
    if (!envelope || envelope.error || !record(envelope.data) || envelope.execution_allowed !== false) {
      byId("status").textContent = "Report data is unavailable. The conversation remains usable."; return;
    }
    const job = envelope.data, context = job.context;
    if (!states.has(job.state) || (context === null ? !["expired", "cancelled"].includes(job.state) : (!context || !context.quality || !records(context.pins, 256) || !records(context.quality.warnings, 64)))) {
      byId("status").textContent = "The report response does not match its contract."; return;
    }
    byId("status").textContent = `Report state: ${job.state}.`;
    byId("job-id").textContent = identity(job.job_id);
    byId("report-id").textContent = job.report_id === null ? "No completed report" : identity(job.report_id);
    byId("type").textContent = text(job.report_type, 40);
    byId("formats").textContent = Array.isArray(job.formats) && job.formats.length <= 4 && job.formats.every((item) => ["pdf", "csv", "json", "xlsx"].includes(item)) ? job.formats.join(", ") : "Unavailable";
    byId("expiry").textContent = text(job.expires_at, 40);
    byId("failure").textContent = job.failure_code === null ? "None" : text(job.failure_code, 40);
    byId("manifest").textContent = digest(job.manifest_digest);
    if (context === null) {
      for (const id of ["snapshot", "valuation", "cutoff", "currency", "quality", "availability", "input-digest"]) byId(id).textContent = "Expired or purged source detail";
      byId("warning-note").textContent = "Source details are no longer retained. Downloads are unavailable.";
      byId("content").hidden = false; return;
    }
    byId("snapshot").textContent = identity(context.snapshot_id);
    byId("valuation").textContent = text(context.valuation_at, 40);
    byId("cutoff").textContent = text(context.source_cutoff_at, 40);
    byId("currency").textContent = text(context.reporting_currency, 3);
    byId("quality").textContent = text(context.quality.state, 30);
    byId("availability").textContent = text(context.quality.availability, 30);
    byId("input-digest").textContent = digest(context.input_digest);
    for (const pin of context.pins) {
      const item = document.createElement("li");
      item.textContent = `${text(pin.family, 40)} / ${text(pin.role, 40)}: ${identity(pin.subject_id)}; digest ${digest(pin.content_digest)}`;
      byId("pins").append(item);
    }
    for (const warning of context.quality.warnings) {
      const item = document.createElement("li"); item.textContent = text(warning.text, 4096); byId("warnings").append(item);
    }
    const omitted = context.quality.warning_omitted_count;
    byId("warning-note").textContent = Number.isSafeInteger(omitted) && omitted >= 0
      ? `${omitted} additional warning records are available in the complete authorized manifest.` : "Warning coverage unavailable.";
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
    if (message.id === "report-initialize" && !message.method && record(message.result) && !message.error) {
      window.parent.postMessage({jsonrpc: "2.0", method: "ui/notifications/initialized", params: {}}, "*");
    }
  }, {passive: true});
  if (window.openai?.toolOutput) update(window.openai.toolOutput);
  window.parent.postMessage({jsonrpc: "2.0", id: "report-initialize", method: "ui/initialize", params: {
    appInfo: {name: "trading212-report-status", version: "1.0.0"}, appCapabilities: {}, protocolVersion: "2026-01-26"
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
REPORT_WIDGET_HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{_CSP}">
<title>Private report status</title><style>{_STYLE}</style></head>
<body><main aria-labelledby="title"><h1 id="title">Private report status</h1>
<p>Saved report metadata. Open Reports in the application for an authenticated download.</p>
<p id="status" role="status">Waiting for authorized report data.</p>
<section id="content" hidden><dl>
<dt>Job</dt><dd id="job-id"></dd><dt>Report</dt><dd id="report-id"></dd>
<dt>Type</dt><dd id="type"></dd><dt>Formats</dt><dd id="formats"></dd>
<dt>Expiry</dt><dd id="expiry"></dd><dt>Failure</dt><dd id="failure"></dd>
<dt>Manifest digest</dt><dd id="manifest"></dd><dt>Snapshot</dt><dd id="snapshot"></dd>
<dt>Valuation time</dt><dd id="valuation"></dd><dt>Source cutoff</dt><dd id="cutoff"></dd>
<dt>Currency</dt><dd id="currency"></dd><dt>Quality</dt><dd id="quality"></dd>
<dt>Availability</dt><dd id="availability"></dd><dt>Input digest</dt><dd id="input-digest"></dd>
</dl><details><summary>Immutable input pins</summary><ul id="pins"></ul></details>
<details><summary>Warnings</summary><ul id="warnings"></ul><p id="warning-note"></p></details>
</section></main><script>{_SCRIPT}</script></body></html>"""
