# ruff: noqa: E501
"""Static isolated presentation of canonical historical performance and comparison results."""

from __future__ import annotations

import base64
import hashlib

HISTORICAL_WIDGET_URI = "ui://trading212-portfolio/performance-comparison-v1.html"
HISTORICAL_WIDGET_MIME = "text/html;profile=mcp-app"
_STYLE = """
:root{color-scheme:light dark;font-family:system-ui,sans-serif;font-variant-numeric:tabular-nums}
*{box-sizing:border-box}body{margin:0;padding:16px}main{max-width:900px;margin:auto}h1{font-size:1.4rem}
p,dd,td{overflow-wrap:anywhere}dl{display:grid;grid-template-columns:1fr 2fr;gap:8px}dt{font-weight:600}dd{margin:0}
.table-wrap{max-height:480px;overflow:auto}table{border-collapse:collapse;width:100%;table-layout:fixed}
caption{text-align:left;font-weight:600;margin:12px 0}th,td{text-align:left;padding:8px;border-bottom:1px solid #888}
:focus-visible{outline:3px solid #1879bd;outline-offset:3px}[hidden]{display:none!important}
@media(max-width:480px){dl{grid-template-columns:1fr}dd{margin-bottom:8px}th,td{padding:6px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
""".strip()
_SCRIPT = r"""
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const records = (value, maximum) => Array.isArray(value) && value.length <= maximum && value.every(record);
  const text = (value, maximum=120) => typeof value === "string" && value.length <= maximum ? value : "Unavailable";
  const decimal = (value) => typeof value === "string" && /^-?(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$/.test(value) ? value : "Unavailable";
  const metric = (value) => {
    if (!value || !["available", "partial", "unavailable"].includes(value.availability)) return "Unavailable";
    if (value.availability === "unavailable" || value.value == null) return `Unavailable: ${text(value.reason_code)}; quality ${text(value.quality,30)}`;
    const raw = value.value;
    const display = typeof raw === "string" ? decimal(raw) : raw && typeof raw.currency === "string" && /^[A-Z]{3}$/.test(raw.currency) ? `${decimal(raw.amount)} ${raw.currency}` : "Unavailable";
    return (value.availability === "partial" ? `${display} (partial: ${text(value.reason_code)})` : display) + `; quality ${text(value.quality,30)}`;
  };
  const render = (envelope) => {
    byId("rows").replaceChildren(); byId("content").hidden = true;
    const data = envelope?.data;
    if (envelope?.error || !record(data?.context) || !records(data.series, 3661) || !record(data.summary)) {
      byId("status").textContent = "Historical data is unavailable. The conversation remains usable."; return;
    }
    const context = data.context;
    byId("status").textContent = `Availability: ${text(context.availability,30)}. Quality: ${text(context.quality,30)}.`;
    byId("window").textContent = `${text(context.window?.start_date,10)} to ${text(context.window?.end_date,10)}`;
    byId("cutoff").textContent = text(context.window?.source_cutoff_at,40);
    byId("method").textContent = `${text(context.method?.name)} / ${text(context.method?.version)}`;
    byId("currency").textContent = text(context.window?.reporting_currency,3);
    byId("calculated").textContent = text(context.calculated_at,40);
    byId("assumptions").textContent = Array.isArray(context.assumptions) && context.assumptions.length <= 16
      ? context.assumptions.map((item) => text(item,80)).join("; ") || "No reported assumptions."
      : "Assumptions unavailable.";
    byId("reconstruction").textContent = text(context.reconstruction,30);
    byId("access").textContent = text(context.access?.reproducibility,30);
    byId("digest").textContent = text(context.content_digest,64);
    byId("source-note").textContent = Number.isSafeInteger(context.source_count) && context.source_count >= 0 && context.source_count <= 8192 && Number.isSafeInteger(context.source_omitted_count) && context.source_omitted_count >= 0 && context.source_omitted_count <= context.source_count
      ? `${context.source_count} pinned source references; ${context.source_omitted_count} omitted from the bounded preview.` : "Source counts unavailable.";
    byId("warning-note").textContent = records(context.warnings, 64)
      ? context.warnings.map((warning) => text(warning.reason_code)).join("; ") || "No reported warnings." : "Warnings unavailable.";
    if (Number.isSafeInteger(context.warning_omitted_count) && context.warning_omitted_count > 0 && context.warning_omitted_count <= 8192)
      byId("warning-note").textContent += ` ${context.warning_omitted_count} additional warnings omitted from the bounded preview.`;
    byId("coverage-note").textContent = records(context.coverage?.measures, 10)
      ? context.coverage.measures.map((measure) => Number.isSafeInteger(measure.available_count) && Number.isSafeInteger(measure.expected_count) && measure.available_count >= 0 && measure.available_count <= measure.expected_count && measure.expected_count <= 400000 && (!measure.complete || measure.available_count === measure.expected_count)
        ? `${text(measure.key,40)}: ${measure.available_count}/${measure.expected_count} (${measure.complete === true ? "complete" : "incomplete"})` : "Coverage unavailable.").join("; ")
      : "Coverage unavailable.";
    const comparison = Object.hasOwn(data.summary,"benchmark_return");
    byId("primary-label").textContent = comparison ? "Portfolio return ratio" : "Ending portfolio value";
    byId("secondary-label").textContent = comparison ? "Benchmark return ratio" : "Investment gain";
    byId("primary").textContent = metric(comparison ? data.summary.portfolio_return : data.summary.ending_value);
    byId("secondary").textContent = metric(comparison ? data.summary.benchmark_return : data.summary.investment_gain);
    byId("first-heading").textContent = comparison ? "Portfolio wealth index (ratio)" : "Portfolio value";
    byId("second-heading").textContent = comparison ? "Benchmark wealth index (ratio)" : "Cumulative return ratio";
    for (const point of data.series) {
      const row = document.createElement("tr");
      for (const value of [text(point.date,10), metric(comparison ? point.portfolio_wealth : point.portfolio_value), metric(comparison ? point.benchmark_wealth : point.cumulative_return)]) {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      }
      byId("rows").append(row);
    }
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
    if (event.source !== window.parent || event.data?.jsonrpc !== "2.0") return;
    if (event.data.id === undefined && ["ui/notifications/tool-input", "ui/notifications/tool-input-partial"].includes(event.data.method)) pending();
    if (event.data.id === undefined && event.data.method === "ui/notifications/tool-cancelled") pending(true);
    if (event.data.id === undefined && event.data.method === "ui/notifications/tool-result") update(event.data.params);
    if (event.data.id === "historical-initialize" && !event.data.method && record(event.data.result) && !event.data.error) window.parent.postMessage({jsonrpc:"2.0",method:"ui/notifications/initialized",params:{}},"*");
  }, {passive:true});
  if (window.openai?.toolOutput) update(window.openai.toolOutput);
  window.parent.postMessage({jsonrpc:"2.0",id:"historical-initialize",method:"ui/initialize",params:{
    appInfo:{name:"trading212-historical-comparison",version:"1.0.0"},appCapabilities:{},protocolVersion:"2026-01-26"
  }},"*");
})();
""".strip()


def _hash(value: str) -> str:
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode("ascii")


_CSP = (
    "default-src 'none'; connect-src 'none'; img-src 'none'; font-src 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; "
    f"script-src 'sha256-{_hash(_SCRIPT)}'; style-src 'sha256-{_hash(_STYLE)}'"
)
HISTORICAL_WIDGET_HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{_CSP}"><title>Historical performance comparison</title><style>{_STYLE}</style></head>
<body><main aria-labelledby="title"><h1 id="title">Historical performance comparison</h1>
<p>Read-only canonical observations. Ratios are shown exactly as returned; this card calculates no financial values.</p>
<p id="status" role="status">Waiting for authorized historical data.</p><section id="content" hidden>
<dl><dt id="primary-label"></dt><dd id="primary"></dd><dt id="secondary-label"></dt><dd id="secondary"></dd>
<dt>Window</dt><dd id="window"></dd><dt>Source cutoff</dt><dd id="cutoff"></dd><dt>Method</dt><dd id="method"></dd>
<dt>Reporting currency</dt><dd id="currency"></dd><dt>Calculated</dt><dd id="calculated"></dd><dt>Reconstruction</dt><dd id="reconstruction"></dd><dt>Reproducibility access</dt><dd id="access"></dd><dt>Financial result digest</dt><dd id="digest"></dd></dl>
<p id="assumptions"></p><p id="coverage-note"></p><p id="source-note"></p><p id="warning-note"></p><div class="table-wrap" tabindex="0" role="region" aria-label="Historical observations">
<table><caption>Complete returned historical series</caption><thead><tr><th scope="col">Date</th><th scope="col" id="first-heading"></th><th scope="col" id="second-heading"></th></tr></thead><tbody id="rows"></tbody></table></div></section>
</main><script>{_SCRIPT}</script></body></html>"""
