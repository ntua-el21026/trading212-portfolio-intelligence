# ruff: noqa: E501
"""Canonical risk presentation with the standard MCP Apps bridge and no remote resources."""

from __future__ import annotations

import base64
import hashlib

RISK_WIDGET_URI = "ui://trading212-portfolio/risk-v1.html"
RISK_WIDGET_MIME = "text/html;profile=mcp-app"
_STYLE = """
:root{color-scheme:light dark;font-family:system-ui,sans-serif;font-variant-numeric:tabular-nums}
*{box-sizing:border-box}body{margin:0;padding:16px}main{max-width:1000px;margin:auto;min-width:0}h1{font-size:1.5rem}h2{font-size:1.2rem}
p,dd,td,th{overflow-wrap:anywhere}dl{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2fr);gap:8px}dt{font-weight:600}dd{margin:0}
button,select,summary{font:inherit;min-height:44px}button,select{padding:8px;margin:4px 4px 4px 0}button:disabled{cursor:not-allowed}
.table-wrap{max-height:460px;overflow:auto;margin:12px 0}table{border-collapse:collapse;width:100%;table-layout:fixed}#matrix-table{table-layout:auto}
caption{text-align:left;font-weight:600;padding:12px 0}th,td{text-align:left;padding:8px;border-bottom:1px solid #888}#matrix-table td{min-width:140px}
:focus-visible{outline:3px solid #1879bd;outline-offset:3px}[hidden]{display:none!important}.actions{display:flex;flex-wrap:wrap;gap:8px}
@media(max-width:480px){dl{grid-template-columns:1fr}dd{margin-bottom:8px}th,td{padding:6px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
""".strip()
_SCRIPT = r"""
(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const record = x => x !== null && typeof x === "object" && !Array.isArray(x);
  const text = (x, max=240) => typeof x === "string" && x.length <= max ? x : "Unavailable";
  const decimal = x => typeof x === "string" && /^-?(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$/.test(x);
  const uuid = x => typeof x === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(x);
  const inputUUID = x => typeof x === "string" && uuid(x.toLowerCase()) ? x.toLowerCase() : null;
  const count = (x, max=3660) => Number.isSafeInteger(x) && x >= 0 && x <= max;
  const array = (x, max, check=record) => Array.isArray(x) && x.length <= max && x.every(check);
  const metricOK = x => record(x) && ((decimal(x.value) && x.reason === null) || (x.value === null && typeof x.reason === "string" && x.reason.length <= 80));
  const metric = x => metricOK(x) ? (x.value === null ? `Unavailable: ${text(x.reason,80)}` : x.value) : "Unavailable";
  const set = (id, value) => { el(id).textContent = value; };
  let generation = 0, selection = null, current = null, rollingPage = 0;
  let partialInput = false, serverTools = false, disposed = false, counter = 0, pending = null;
  function bridgeAvailable() { return serverTools || typeof window.openai?.callTool === "function"; }
  function buttons() {
    for (const id of ["refresh", "load-matrix"]) el(id).disabled = disposed || !selection?.run_id || !bridgeAvailable() || pending !== null;
    set("bridge", bridgeAvailable() ? "Refresh uses the host's authorized tools. No direct network access." : "This host does not expose tool refresh. Ask the conversation to read the run again.");
  }
  function clear(message) {
    current = null; rollingPage = 0; el("content").hidden = true; el("summary").hidden = true;
    for (const id of ["observed", "tails", "contributions", "rolling", "matrix-head", "matrix-rows", "sources", "warnings"]) el(id).replaceChildren();
    for (const id of ["identity", "quality", "assumptions", "source-count", "digest", "modeled", "concentration", "rolling-count"]) set(id, "");
    set("status", message); buttons();
  }
  function invalidate(message) {
    generation++; if (pending) clearTimeout(pending.timer); pending = null; selection = null;
    clear(message);
  }
  function matrixOK(m) {
    return record(m) && array(m.keys,32,uuid) && new Set(m.keys).size === m.keys.length &&
      count(m.requested_intervals) && count(m.used_intervals) && count(m.omitted_intervals) &&
      m.used_intervals + m.omitted_intervals === m.requested_intervals &&
      ["correlation","covariance_periodic","regularized_covariance_periodic"].every(key =>
        array(m[key],32,row => array(row,32,metricOK) && row.length === m.keys.length) && m[key].length === m.keys.length);
  }
  function resultOK(r) {
    const c = r?.historical_context, d = r?.definition;
    return record(r) && record(c) && uuid(c.account_id) && record(c.window) && record(d) &&
      typeof d.name === "string" && d.name.length <= 120 &&
      ["daily","monthly"].includes(d.frequency) && ["simple","log"].includes(d.return_kind) &&
      [d.annual_risk_free,d.annual_minimum_acceptable_return,d.confidence,d.shrinkage].every(decimal) &&
      ["fresh","stale","partial","estimated","unreconciled","failed"].includes(c.quality) &&
      array(c.sources,64) && array(c.warnings,64) && count(r.omitted_sources,8192) && count(r.omitted_warnings,8192) &&
      typeof r.content_digest === "string" && /^[0-9a-f]{64}$/.test(r.content_digest) &&
      r.numerical_profile === "premium_decimal96_q18_v1" && matrixOK(r.matrix);
  }
  function fullOK(r) {
    const o=r.observed, m=r.modeled, c=r.concentration;
    return record(o) && record(m) && record(c) &&
      ["volatility_annualized","volatility_periodic","downside_annualized","mean_periodic_return","beta","alpha_annualized"].every(k=>metricOK(o[k])) &&
      [o.used_observations,o.requested_observations,o.omitted_observations,o.outlier_observations,o.benchmark_pairs].every(x=>count(x)) &&
      array(o.rolling,3660,x=>metricOK(x.volatility) && count(x.observations,252) && typeof x.end_at === "string") &&
      [r.historical_tail,r.parametric_tail].every(t=>record(t) && decimal(t.confidence) && metricOK(t.value_at_risk) && metricOK(t.expected_shortfall) && count(t.horizon,20)) &&
      array(m.components,32,x=>uuid(x.instrument_id) && [x.weight,x.marginal_annualized,x.component_annualized].every(metricOK)) &&
      [m.coverage,m.volatility_annualized,m.diversification_ratio,m.component_sum,m.component_display_residual,m.weight_display_residual,c.hhi,c.effective_holdings,c.company_known_weight,c.cash_weight,c.unresolved_weight].every(metricOK);
  }
  function row(id, values, heading=false) {
    const tr=document.createElement("tr"); values.forEach((value,index)=>{
      const cell=document.createElement(heading || index===0 ? "th" : "td");
      if (heading) cell.scope="col"; else if (index===0) cell.scope="row";
      cell.textContent=value; tr.append(cell);
    }); el(id).append(tr);
  }
  function renderMatrix() {
    const m=current?.matrix; el("matrix-head").replaceChildren(); el("matrix-rows").replaceChildren();
    if (!m) return;
    const kind=el("measure").value;
    if (!["correlation","covariance_periodic","regularized_covariance_periodic"].includes(kind)) return;
    row("matrix-head", ["Asset",...m.keys], true);
    m.keys.forEach((key,index)=>row("matrix-rows",[key,...m[kind][index].map(metric)]));
    set("matrix-count", m.keys.length ? `${m.used_intervals} used, ${m.omitted_intervals} omitted of ${m.requested_intervals} intervals. No gaps are filled.` : "No asset universe selected. Observed portfolio estimates remain separate.");
  }
  function renderRolling() {
    const points=current?.observed?.rolling ?? []; el("rolling").replaceChildren();
    for (const point of points.slice(rollingPage*50,(rollingPage+1)*50)) row("rolling",[text(point.end_at,40),String(point.observations),metric(point.volatility)]);
    set("rolling-count", `${points.slice(rollingPage*50,(rollingPage+1)*50).length} of ${points.length} retained estimates; page ${rollingPage+1}.`);
    el("previous").disabled=rollingPage===0; el("next").disabled=(rollingPage+1)*50>=points.length;
  }
  function show(result, expected=selection) {
    if (disposed || partialInput) return;
    clear("Reading canonical risk result.");
    try {
      if (!record(result) || new TextEncoder().encode(JSON.stringify(result)).byteLength > 2097152 || result.isError || result.is_error) throw new Error();
      const envelope=result.structuredContent ?? result.structured_content ?? result;
      if (!record(envelope) || envelope.execution_allowed !== false || envelope.error !== null || !record(envelope.data)) throw new Error();
      const data=envelope.data, run=data.id ?? data.run_id;
      if (!uuid(data.account_id) || !uuid(run) || (expected && (expected.account_id !== data.account_id || (expected.run_id && expected.run_id !== run)))) throw new Error();
      if (expected?.definition_version_id && ["definition_version_id","portfolio_snapshot_id","historical_input_snapshot_id"].some(k=>expected[k]!==data[k])) throw new Error();
      if (expected?.definition_version_id && expected.xray_run_id !== data.xray_run_id) throw new Error();
      const isRun=uuid(data.id), risk=isRun ? data.result : data;
      if (isRun && (!["queued","running","succeeded","failed","expired","cancelled"].includes(data.state) || !["pending","available","not_loaded","expired","unavailable"].includes(data.result_availability))) throw new Error();
      if (risk !== null && (!resultOK(risk) || risk.historical_context.account_id !== data.account_id || (isRun && (data.state !== "succeeded" || data.result_availability !== "available" || !fullOK(risk))))) throw new Error();
      if (isRun && risk === null && data.result_availability === "available") throw new Error();
      selection={account_id:data.account_id,run_id:run};
      set("identity", `Account ${data.account_id} · Run ${run}`);
      if (risk === null) { set("status", `Risk state: ${data.state}; result: ${data.result_availability}. No financial result is available.`); buttons(); return; }
      current=risk; const context=risk.historical_context, d=risk.definition;
      set("status", isRun ? "Completed canonical risk estimates." : "Canonical risk matrix.");
      set("quality", `Quality: ${context.quality}; availability: ${text(context.availability,30)}. Cutoff: ${text(context.window.source_cutoff_at,40)}. Currency: ${text(context.window.reporting_currency,3)}.`);
      set("assumptions", `${d.name} · ${d.frequency} ${d.return_kind} returns. Calendar ${text(d.calendar_id,120)} / ${text(d.calendar_version,120)}. Annual risk-free ${d.annual_risk_free}; minimum acceptable return ${d.annual_minimum_acceptable_return}. Regularization ${text(d.regularization,40)} / ${d.shrinkage}. Numerical profile ${risk.numerical_profile}.`);
      set("digest", risk.content_digest);
      set("source-count", `${context.sources.length} source references shown; ${risk.omitted_sources} omitted. ${context.warnings.length} warnings shown; ${risk.omitted_warnings} omitted.`);
      for (const source of context.sources) { const li=document.createElement("li"); li.textContent=`${text(source.kind,80)} · ${text(source.id,120)} · ${text(source.effective_at,40)}`; el("sources").append(li); }
      for (const warning of context.warnings) { const li=document.createElement("li"); li.textContent=text(warning.reason_code,80); el("warnings").append(li); }
      if (isRun) {
        const o=risk.observed;
        for (const [label,key] of [["Annualized volatility","volatility_annualized"],["Periodic volatility","volatility_periodic"],["Downside deviation","downside_annualized"],["Periodic mean return","mean_periodic_return"],["Benchmark beta","beta"],["Annualized alpha","alpha_annualized"]]) row("observed",[label,metric(o[key])]);
        row("observed",["Maximum drawdown",decimal(risk.maximum_drawdown?.value) ? risk.maximum_drawdown.value : "Unavailable"]);
        set("sample", `${o.used_observations} used of ${o.requested_observations}; ${o.omitted_observations} omitted; ${o.outlier_observations} outliers retained. Benchmark pairs ${o.benchmark_pairs}.`);
        for (const t of [risk.historical_tail,risk.parametric_tail]) row("tails",[text(t.method,60),`${t.confidence} / ${t.horizon}`,metric(t.value_at_risk),metric(t.expected_shortfall),`${text(t.quantile,80)}; ${text(t.horizon_policy,80)}`]);
        const m=risk.modeled,c=risk.concentration;
        set("modeled", `Coverage ${metric(m.coverage)}; annualized volatility ${metric(m.volatility_annualized)}; diversification ${metric(m.diversification_ratio)}. Component sum ${metric(m.component_sum)}; display residual ${metric(m.component_display_residual)}; weight residual ${metric(m.weight_display_residual)}. ${m.complete_universe === true ? "Complete modeled universe." : "Incomplete universe; missing exposure is not assigned zero risk or renormalized."}`);
        for (const item of m.components) row("contributions",[item.instrument_id,metric(item.weight),metric(item.marginal_annualized),metric(item.component_annualized)]);
        set("concentration", `Economic issuer HHI ${metric(c.hhi)}; effective holdings ${metric(c.effective_holdings)}; known company ratio ${metric(c.company_known_weight)}; cash ratio ${metric(c.cash_weight)}; unresolved ratio ${metric(c.unresolved_weight)}. Quality ${text(c.quality,30)}. ${c.lower_bound === true && c.hhi.value !== null ? "Known issuer HHI is a lower bound." : "Availability follows the canonical X-ray partition."} Wrappers and constituents are not counted twice.`);
        el("summary").hidden=false; renderRolling();
      }
      renderMatrix(); el("content").hidden=false; buttons();
    } catch (_) { clear("Risk result is unavailable or does not match the selected account and contract."); }
  }
  function finish(id, result) {
    if (!pending || pending.id !== id || pending.generation !== generation || disposed) return;
    const request=pending; clearTimeout(request.timer); pending=null;
    if (result?.error) clear("The host could not complete the authorized read. Retry is available.");
    else show(result, request.selection);
    buttons();
  }
  function read(name) {
    if (disposed || pending || !selection?.run_id || !bridgeAvailable() || !["get_risk_summary","get_risk_matrix"].includes(name)) return;
    const id=`risk-read-${++counter}`, pin={account_id:selection.account_id,run_id:selection.run_id};
    const timer=setTimeout(()=>finish(id,{error:true}),15000);
    pending={id,generation,selection:pin,timer}; clear("Loading the authorized risk result…");
    if (serverTools) window.parent.postMessage({jsonrpc:"2.0",id,method:"tools/call",params:{name,arguments:pin}},"*");
    else Promise.resolve().then(()=>window.openai.callTool(name,pin)).then(value=>finish(id,value),()=>finish(id,{error:true}));
  }
  function input(args, partial) {
    invalidate("Waiting for the authorized risk result. Input arguments are not financial results."); partialInput=true;
    if (!partial && record(args) && inputUUID(args.account_id)) {
      const pin={account_id:inputUUID(args.account_id),run_id:null};
      if (Object.prototype.hasOwnProperty.call(args,"run_id")) {
        pin.run_id=inputUUID(args.run_id); if (!pin.run_id) return;
      } else {
        for (const key of ["definition_version_id","portfolio_snapshot_id","historical_input_snapshot_id"]) {
          pin[key]=inputUUID(args[key]); if (!pin[key]) return;
        }
        pin.xray_run_id=args.xray_run_id == null ? null : inputUUID(args.xray_run_id);
        if (args.xray_run_id != null && !pin.xray_run_id) return;
      }
      selection=pin; partialInput=false;
    }
    buttons();
  }
  function message(event) {
    const data=event.data;
    if (disposed || event.source !== window.parent || data?.jsonrpc !== "2.0") return;
    if (data.id === "risk-ui-initialize" && data.result?.protocolVersion === "2026-01-26") {
      serverTools=record(data.result.hostCapabilities?.serverTools);
      window.parent.postMessage({jsonrpc:"2.0",method:"ui/notifications/initialized",params:{}},"*"); buttons(); return;
    }
    if (data.method === "ui/resource-teardown" && data.id !== undefined) {
      invalidate("Risk view closed."); disposed=true; buttons(); window.removeEventListener("message",message);
      window.removeEventListener("openai:set_globals",legacy);
      window.parent.postMessage({jsonrpc:"2.0",id:data.id,result:{}},"*"); return;
    }
    if (data.id !== undefined) { if (!data.method) finish(data.id,data.error ? {error:true} : data.result); return; }
    if (data.method === "ui/notifications/tool-input") input(data.params?.arguments,false);
    else if (data.method === "ui/notifications/tool-input-partial") input(data.params?.arguments,true);
    else if (data.method === "ui/notifications/tool-cancelled") { invalidate("Tool execution was cancelled. No current result is displayed."); partialInput=true; }
    else if (data.method === "ui/notifications/tool-result") show(data.params);
  }
  function legacy(event) {
    if (disposed || pending || partialInput || serverTools) return;
    const globals=event.detail?.globals;
    if (globals && Object.prototype.hasOwnProperty.call(globals,"toolOutput")) show(globals.toolOutput);
  }
  el("refresh").addEventListener("click",()=>read("get_risk_summary"));
  el("load-matrix").addEventListener("click",()=>read("get_risk_matrix"));
  el("measure").addEventListener("change",renderMatrix);
  el("previous").addEventListener("click",()=>{ if (rollingPage>0) { rollingPage--; renderRolling(); } });
  el("next").addEventListener("click",()=>{ if (current?.observed && (rollingPage+1)*50<current.observed.rolling.length) { rollingPage++; renderRolling(); } });
  window.addEventListener("message",message); window.addEventListener("openai:set_globals",legacy);
  clear("Waiting for an authorized canonical risk result.");
  window.parent.postMessage({jsonrpc:"2.0",id:"risk-ui-initialize",method:"ui/initialize",params:{protocolVersion:"2026-01-26",appInfo:{name:"portfolio-risk",version:"1.0.0"},appCapabilities:{availableDisplayModes:["inline"]}}},"*");
  if (window.openai?.toolOutput) show(window.openai.toolOutput);
})();
""".strip()


def _hash(value: str) -> str:
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode()


_CSP = (
    "default-src 'none'; connect-src 'none'; img-src 'none'; font-src 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; "
    f"script-src 'sha256-{_hash(_SCRIPT)}'; style-src 'sha256-{_hash(_STYLE)}'"
)
_BODY = """
<main><h1>Portfolio risk</h1><p>Historical estimates and current-weight modeling. Exact decimal ratios are shown: 0.01 means 1%. These are finite-precision estimates, not forecasts or trade instructions.</p>
<p id="status" role="status" aria-live="polite"></p><p id="identity"></p>
<div class="actions"><button id="refresh" disabled>Refresh risk summary</button><button id="load-matrix" disabled>Read risk matrix</button></div><p id="bridge"></p>
<section id="content" hidden><p id="quality"></p><p id="assumptions"></p>
<section id="summary" hidden><h2>Observed historical risk</h2><p id="sample"></p>
<div class="table-wrap" tabindex="0" role="region" aria-label="Observed estimates"><table><caption>Canonical observed estimates</caption><thead><tr><th scope="col">Measure</th><th scope="col">Value / reason</th></tr></thead><tbody id="observed"></tbody></table></div>
<h2>Rolling volatility</h2><p id="rolling-count"></p><div class="table-wrap" tabindex="0" role="region" aria-label="Rolling estimates"><table><caption>Canonical rolling annualized volatility</caption><thead><tr><th scope="col">Window end</th><th scope="col">Observations</th><th scope="col">Value / reason</th></tr></thead><tbody id="rolling"></tbody></table></div>
<div class="actions"><button id="previous">Previous estimates</button><button id="next">Next estimates</button></div>
<h2>Tail loss estimates</h2><p>Positive values mean loss; negative values mean gain. Historical tails compound overlapping windows; the parametric model assumes independent log returns.</p>
<div class="table-wrap" tabindex="0" role="region" aria-label="Tail estimates"><table><caption>Historical and parametric tail estimates</caption><thead><tr><th scope="col">Method</th><th scope="col">Confidence / periods</th><th scope="col">VaR</th><th scope="col">Expected Shortfall</th><th scope="col">Convention</th></tr></thead><tbody id="tails"></tbody></table></div>
<h2>Modeled risk at current weights</h2><p id="modeled"></p><div class="table-wrap" tabindex="0" role="region" aria-label="Risk contributions"><table><caption>Current-weight risk contributions</caption><thead><tr><th scope="col">Asset</th><th scope="col">Weight</th><th scope="col">Marginal</th><th scope="col">Component</th></tr></thead><tbody id="contributions"></tbody></table></div>
<h2>Economic issuer concentration</h2><p id="concentration"></p></section>
<h2>Asset matrix</h2><label for="measure">Matrix measure</label><select id="measure"><option value="correlation">Correlation</option><option value="covariance_periodic">Periodic covariance</option><option value="regularized_covariance_periodic">Explicitly regularized covariance</option></select><p id="matrix-count"></p>
<div class="table-wrap" tabindex="0" role="region" aria-label="Risk matrix"><table id="matrix-table"><caption>Canonical asset matrix</caption><thead id="matrix-head"></thead><tbody id="matrix-rows"></tbody></table></div>
<details><summary>Source evidence and result identity</summary><p id="source-count"></p><p>Result digest: <span id="digest"></span></p><ul id="sources"></ul><ul id="warnings"></ul></details></section></main>
""".strip()
RISK_WIDGET_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">'
    f"<title>Portfolio risk</title><style>{_STYLE}</style></head><body>{_BODY}"
    f"<script>{_SCRIPT}</script></body></html>"
)
