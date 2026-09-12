# ruff: noqa: E501
"""Isolated exact X-ray presentation; all financial values come from the application."""

from __future__ import annotations

import base64
import hashlib

XRAY_WIDGET_URI = "ui://trading212-portfolio/xray-v1.html"
XRAY_WIDGET_MIME = "text/html;profile=mcp-app"
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
  const text = (value, maximum=240) => typeof value === "string" && value.length <= maximum ? value : "Unavailable";
  const count = (value) => Number.isSafeInteger(value) && value >= 0 && value <= 100000 ? String(value) : "Unavailable";
  const decimal = (value) => typeof value === "string" && /^-?(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$/.test(value) ? value : "Unavailable";
  const metric = (value) => {
    if (!value || !["available", "unavailable"].includes(value.availability) || !["exact", "lower_bound"].includes(value.bound)) return "Unavailable";
    if (value.availability === "unavailable" || value.value == null) return `Unavailable: ${text(value.reason)}; ${text(value.quality,30)}`;
    const raw = value.value;
    const display = typeof raw === "string" ? decimal(raw) : raw && typeof raw.currency === "string" && /^[A-Z]{3}$/.test(raw.currency) ? `${decimal(raw.amount)} ${raw.currency}` : "Unavailable";
    return `${display}${value.bound === "lower_bound" ? " (lower bound)" : ""}${value.positive_below_quantum === true ? " (positive below display precision)" : ""}; ${text(value.quality,30)}`;
  };
  const render = (envelope) => {
    byId("rows").replaceChildren(); byId("sources").replaceChildren(); byId("content").hidden = true;
    const data = envelope?.data;
    const overlap = data?.view === "mcp_top_pair";
    const items = overlap ? data.common_entities : data?.exposures?.items;
    if (envelope?.error || !record(data?.context) || !record(data?.summary) || !records(items, overlap ? 50 : 100) || (!overlap && data.view !== "exposures")) {
      byId("status").textContent = "X-ray data is unavailable. The conversation remains usable."; return;
    }
    const context = data.context;
    byId("status").textContent = `Quality: ${text(data.summary.total?.quality,30)}. Access: ${text(context.access?.reproducibility,30)}.`;
    byId("currency").textContent = text(context.reporting_currency,3);
    byId("valuation").textContent = text(context.valuation_at,40);
    byId("cutoff").textContent = text(context.source_cutoff_at,40);
    byId("quality-at").textContent = text(context.quality_evaluated_at,40);
    byId("method").textContent = `${text(context.method?.name)} / ${text(context.method?.version)}`;
    byId("digest").textContent = text(context.content_digest,64);
    byId("total").textContent = metric(data.summary.total);
    byId("coverage").textContent = metric(data.summary.company_known_weight);
    byId("unresolved").textContent = metric(data.summary.unresolved_weight);
    byId("duplication").textContent = metric(data.summary.duplicated_exposure);
    byId("hhi").textContent = metric(data.summary.hhi);
    const quality = data.summary.quality_coverage;
    byId("valued-roots").textContent = `${count(quality?.valued_root_count)} of ${count(quality?.root_count)}`;
    byId("direct-coverage").textContent = `${metric(quality?.direct_portfolio_value)}; ratio ${metric(quality?.direct_portfolio_weight)}`;
    byId("inferred-value").textContent = `${metric(quality?.inferred_value)}; ratio ${metric(quality?.inferred_weight)}; mapping count ${count(quality?.inferred_mapping_count)}`;
    byId("stale-value").textContent = `${metric(quality?.stale_value)}; ratio ${metric(quality?.stale_weight)}`;
    byId("pair").hidden = !overlap;
    if (overlap) {
      byId("pair-title").textContent = `${text(data.pair?.left?.name)} / ${text(data.pair?.right?.name)}`;
      byId("pair-value").textContent = metric(data.pair?.overlap);
      byId("pair-coverage").textContent = `Left: ${metric(data.pair?.left?.unit_coverage)}. Right: ${metric(data.pair?.right?.unit_coverage)}.`;
      byId("omitted-weight").textContent = metric(data.omitted_common_weight);
    }
    byId("caption").textContent = overlap ? "Returned common entities" : `Effective ${text(data.dimension_summary?.dimension,30)} exposure`;
    byId("first-heading").textContent = overlap ? "Left fund ratio" : "Direct value";
    byId("second-heading").textContent = overlap ? "Right fund ratio" : "Indirect value";
    byId("third-heading").textContent = overlap ? "Common ratio" : "Effective value";
    for (const item of items) {
      const row = document.createElement("tr");
      for (const value of [text(item.name), metric(overlap ? item.left_weight : item.direct), metric(overlap ? item.right_weight : item.indirect), metric(overlap ? item.common_weight : item.effective)]) {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      }
      byId("rows").append(row);
    }
    const selection = envelope.selection;
    byId("selection").textContent = Number.isSafeInteger(selection?.total) && selection.total >= 0 && Number.isSafeInteger(selection?.returned) && selection.returned === items.length && selection.returned <= selection.total && Number.isSafeInteger(selection?.omitted) && selection.omitted === selection.total - selection.returned
      ? `${selection.returned} returned of ${selection.total}; ${selection.omitted} not in this response.` : "Selection counts unavailable.";
    byId("warnings").textContent = records(context.warnings, 64)
      ? context.warnings.map((warning) => text(warning.code)).join("; ") || "No reported warnings." : "Warnings unavailable.";
    if (Number.isSafeInteger(context.warning_omitted_count) && context.warning_omitted_count > 0)
      byId("warnings").textContent += ` ${context.warning_omitted_count} additional warnings omitted from the preview.`;
    if (records(context.sources, 64)) {
      for (const source of context.sources) {
        const item = document.createElement("li");
        item.textContent = `${text(source.kind,40)}: ${text(source.provider_name)}; source ${text(source.source_at,40)}; confidence ${source.confidence === null ? "unknown" : decimal(source.confidence)}; ${text(source.quality,30)}`;
        byId("sources").append(item);
      }
    }
    byId("source-count").textContent = Number.isSafeInteger(context.source_count) && context.source_count >= 0 && Number.isSafeInteger(context.source_omitted_count) && context.source_omitted_count >= 0 && context.source_omitted_count <= context.source_count
      ? `${context.source_count} pinned source references; ${context.source_omitted_count} omitted from the preview.` : "Source counts unavailable.";
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
    if (event.data.id === "xray-initialize" && !event.data.method && record(event.data.result) && !event.data.error) window.parent.postMessage({jsonrpc:"2.0",method:"ui/notifications/initialized",params:{}},"*");
  }, {passive:true});
  if (window.openai?.toolOutput) update(window.openai.toolOutput);
  window.parent.postMessage({jsonrpc:"2.0",id:"xray-initialize",method:"ui/initialize",params:{
    appInfo:{name:"trading212-xray",version:"1.0.0"},appCapabilities:{},protocolVersion:"2026-01-26"
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
XRAY_WIDGET_HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{_CSP}"><title>Portfolio X-ray</title><style>{_STYLE}</style></head>
<body><main aria-labelledby="title"><h1 id="title">Portfolio X-ray</h1>
<p>Read-only observations. Ratios and values are shown exactly as returned, with cash and unresolved exposure kept separate.</p>
<p id="status" role="status">Waiting for authorized X-ray data.</p><section id="content" hidden>
<dl><dt>Portfolio value</dt><dd id="total"></dd><dt>Known company coverage ratio</dt><dd id="coverage"></dd>
<dt>Unresolved ratio</dt><dd id="unresolved"></dd><dt>Duplicated exposure ratio</dt><dd id="duplication"></dd><dt>Company HHI</dt><dd id="hhi"></dd>
<dt>Reporting currency</dt><dd id="currency"></dd><dt>Valuation</dt><dd id="valuation"></dd><dt>Source cutoff</dt><dd id="cutoff"></dd><dt>Quality assessed</dt><dd id="quality-at"></dd><dt>Method</dt><dd id="method"></dd><dt>Result digest</dt><dd id="digest"></dd></dl>
<h2>Valuation and source quality</h2><p>Quality measures overlap; do not add them to portfolio value.</p>
<dl><dt>Valued original roots</dt><dd id="valued-roots"></dd><dt>Direct valuation coverage</dt><dd id="direct-coverage"></dd>
<dt>Exposure using inferred mappings</dt><dd id="inferred-value"></dd><dt>Exposure using stale sources</dt><dd id="stale-value"></dd></dl>
<section id="pair" hidden><h2 id="pair-title"></h2><p id="pair-value"></p><p id="pair-coverage"></p><p>Omitted common weight: <span id="omitted-weight"></span></p></section>
<p>Company buckets combine listings of the same company. Totals cover the full authorized scope; a returned page or Top sample is not a new total.</p><p id="selection"></p><p id="warnings"></p><div class="table-wrap" tabindex="0" role="region" aria-label="Effective exposure rows">
<table><caption id="caption"></caption><thead><tr><th scope="col">Entity</th><th scope="col" id="first-heading"></th><th scope="col" id="second-heading"></th><th scope="col" id="third-heading"></th></tr></thead><tbody id="rows"></tbody></table></div>
<h2>Source evidence</h2><p id="source-count"></p><ul id="sources"></ul></section></main><script>{_SCRIPT}</script></body></html>"""
