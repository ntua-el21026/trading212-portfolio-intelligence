# ruff: noqa: E501
"""Saved scenario tables with bounded MCP Apps reads and no private browser cache."""

from __future__ import annotations

import base64
import hashlib

SCENARIO_WIDGET_URI = "ui://trading212-portfolio/scenario-v1.html"
SCENARIO_WIDGET_MIME = "text/html;profile=mcp-app"
_STYLE = """
:root{color-scheme:light dark;font-family:system-ui,sans-serif;font-variant-numeric:tabular-nums}
*{box-sizing:border-box}body{margin:0;padding:16px}main{max-width:1080px;margin:auto;min-width:0}h1{font-size:1.5rem}h2{font-size:1.2rem}
p,td,th,li,label{overflow-wrap:anywhere}button,input,select,summary{font:inherit;min-height:44px}button,input,select{padding:8px;margin:4px 4px 4px 0;max-width:100%}input{width:26rem}
button:disabled{cursor:not-allowed}.actions{display:flex;flex-wrap:wrap;gap:8px}.table-wrap{max-height:480px;overflow:auto;margin:12px 0}table{border-collapse:collapse;width:100%;min-width:720px;table-layout:fixed}
caption{text-align:left;font-weight:600;padding:12px 0}th,td{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid #888}:focus-visible{outline:3px solid #1879bd;outline-offset:3px}[hidden]{display:none!important}
@media(max-width:480px){body{padding:10px}th,td{padding:5px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
""".strip()
_SCRIPT = r"""
(() => {
  "use strict";
  const el=id=>document.getElementById(id), record=x=>x!==null&&typeof x==="object"&&!Array.isArray(x);
  const str=(x,max=1024)=>typeof x==="string"&&x.length>0&&x.length<=max;
  const text=(x,max=1024)=>str(x,max)?x:"Unavailable";
  const decimal=x=>typeof x==="string"&&/^-?(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$/.test(x);
  const uuid=x=>typeof x==="string"&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(x);
  const inputUUID=x=>typeof x==="string"&&uuid(x.toLowerCase())?x.toLowerCase():null;
  const digest=x=>typeof x==="string"&&/^[0-9a-f]{64}$/.test(x);
  const currency=x=>typeof x==="string"&&/^[A-Z]{3}$/.test(x);
  const count=(x,max=100000)=>Number.isSafeInteger(x)&&x>=0&&x<=max;
  const array=(x,max,check=record)=>Array.isArray(x)&&x.length<=max&&x.every(item=>check(item));
  const quality=x=>["fresh","stale","partial","estimated","unreconciled","failed"].includes(x);
  const preview=(x,check=uuid)=>record(x)&&array(x.items,16,check)&&count(x.omitted_count);
  const confidence=x=>x===null||(typeof x==="string"&&/^(?:0(?:\.[0-9]{1,18})?|1(?:\.0{1,18})?)$/.test(x));
  const ratio=x=>record(x)&&quality(x.quality)&&((decimal(x.value)&&x.reason===null)||(x.value===null&&str(x.reason,80)));
  const money=(x,c)=>record(x)&&quality(x.quality)&&confidence(x.confidence)&&preview(x.source_reference_ids)&&((record(x.value)&&decimal(x.value.amount)&&currency(x.value.currency)&&(!c||x.value.currency===c)&&x.reason===null)||(x.value===null&&str(x.reason,80)));
  const moneyText=x=>x.value===null?`Unavailable: ${text(x.reason,80)} · ${x.quality}`:`${x.value.amount} ${x.value.currency} · ${x.quality}${x.confidence===null?"":` · confidence ${x.confidence}`}`;
  const ratioText=x=>x.value===null?`Unavailable: ${text(x.reason,80)} · ${x.quality}`:`${x.value} · ${x.quality}`;
  const set=(id,value)=>{el(id).textContent=value;};
  const states=["queued","running","succeeded","failed","expired","cancelled"];
  const summaryMoney=["terminal_pre_value","covered_pre_value","uncovered_pre_value","excluded_pre_value","covered_post_value","excluded_post_value","provably_unchanged_uncovered_value","post_value","impact","rounding_residual","component_sum_residual"];
  const effects=(x,c)=>record(x)&&["price_ratio","factor_ratio","fx_ratio"].every(k=>ratio(x[k]))&&["price","factor","fx","interaction"].every(k=>money(x[k],c));
  let selection=null,current=null,generation=0,counter=0,pending=null,partialInput=false,disposed=false,serverTools=false;
  function bridgeAvailable(){return serverTools||typeof window.openai?.callTool==="function";}
  function buttons(){
    const enabled=!disposed&&!partialInput&&selection&&(selection.run_id||selection.run_ids)&&bridgeAvailable()&&!pending;
    for(const id of ["refresh","first"])el(id).disabled=!enabled;
    el("next").disabled=!enabled||!current?.components.next_cursor;
    el("compare").disabled=!enabled||!selection?.run_id||!inputUUID(el("other-run").value)||inputUUID(el("other-run").value)===selection.run_id;
    set("bridge",bridgeAvailable()?"Reads use the host's authorized tools. Values are never sent directly to another server.":"This host does not support widget reads. Ask the conversation to read the run or its next component page.");
  }
  function clear(message){
    current=null;el("content").hidden=true;el("details").hidden=true;
    for(const id of ["summary","components","sensitivities","sources","warnings","component-select"])el(id).replaceChildren();
    for(const id of ["identity","method","basis","coverage","page-count","digest","source-count","component-detail","effects"])set(id,"");
    set("status",message);buttons();
  }
  function invalidate(message){generation++;if(pending)clearTimeout(pending.timer);pending=null;selection=null;el("other-run").value="";clear(message);}
  function replayOK(x){const s=x?.selection;return x===null||(record(x)&&record(s)&&["current_holdings","historical_holdings"].includes(s.holdings_basis)&&["point_in_time","retrospective"].includes(s.knowledge_basis)&&str(s.start_date,10)&&str(s.end_date,10)&&str(s.market_knowledge_cutoff_at,40)&&quality(x.quality));}
  function replayText(c){const r=c.replay,s=r?.selection;return r===null?"Current retained terminal holdings.":`Counterfactual replay: ${s.holdings_basis}; ${s.knowledge_basis} knowledge; window ${s.start_date} through ${s.end_date}; market knowledge cutoff ${s.market_knowledge_cutoff_at}; quality ${r.quality}.`;}
  function contextOK(c){
    const p=c?.pins,s=c?.summary,d=c?.definition;
    return record(c)&&record(p)&&record(s)&&record(d)&&uuid(c.run_id)&&uuid(c.result_id)&&uuid(p.account_id)&&currency(p.reporting_currency)&&
      ["scenario_version_id","portfolio_snapshot_id","xray_run_id"].every(k=>uuid(p[k]))&&digest(c.saved_result_digest)&&digest(c.input_digest)&&
      ["first_order","compounded"].includes(d.mode)&&str(d.name,120)&&str(c.valuation_at,40)&&str(p.source_cutoff_at,40)&&
      c.method_version==="1.0.0"&&c.schema_version==="1.0.0"&&c.numerical_profile==="premium_decimal96_q18_v1"&&
      summaryMoney.every(k=>money(s[k],p.reporting_currency))&&effects(s.effects,p.reporting_currency)&&
      ["covered_count","uncovered_count","excluded_count","missing_pre_value_count","uncertain_money_count"].every(k=>count(s[k],10000))&&
      preview(c.diagnostics,x=>record(x)&&str(x.reason,80))&&array(c.assumptions,16,x=>str(x,80))&&replayOK(c.replay);
  }
  function sensitivityOK(x){return record(x)&&uuid(x.version_id)&&uuid(x.driver_id)&&str(x.rule_key)&&preview(x.candidate_observation_ids)&&
    (x.observation_id===null||uuid(x.observation_id)&&x.candidate_observation_ids.items.includes(x.observation_id))&&
    (x.coefficient===null||decimal(x.coefficient))&&decimal(x.shock_size)&&ratio(x.effect_ratio)&&preview(x.driver_evidence_reference_ids);}
  function componentOK(x,c){const e=x?.exposure;return record(x)&&record(e)&&str(e.root_key)&&str(e.path_key)&&money(e.pre_value,c)&&
    ["covered","uncovered","excluded"].includes(x.partition)&&["post_value","impact","rounding_residual"].every(k=>money(x[k],c))&&effects(x.effects,c)&&
    ["instrument","entity","sector","region","economic_currency"].every(k=>record(e[k]))&&preview(e.source_reference_ids)&&
    array(x.sensitivity_uses,128,sensitivityOK)&&array(x.matching_exclusion_keys,128,str)&&array(x.uncertain_rule_keys,128,str)&&preview(x.diagnostic_keys,str);}
  function pageOK(p,check){const end=p?.start_ordinal+p?.items?.length;return record(p)&&array(p.items,100,check)&&count(p.total,10000)&&
    count(p.start_ordinal,10000)&&count(p.component_limit,100)&&p.component_limit>0&&p.items.length<=p.component_limit&&end<=p.total&&
    (p.items.length>0||p.total===0)&&((p.next_cursor===null&&end===p.total)||(str(p.next_cursor,2048)&&end<p.total));}
  function deltaOK(x,b,a,compatible){return record(x)&&money(x.before,b)&&money(x.after,a)&&money(x.difference,compatible?b:null)&&(compatible||x.difference.value===null);}
  function compareOK(d){const b=d.before?.pins.reporting_currency,a=d.after?.pins.reporting_currency;return contextOK(d.before)&&contextOK(d.after)&&
    d.before.run_id!==d.after.run_id&&d.before.pins.account_id===d.after.pins.account_id&&typeof d.compatible==="boolean"&&array(d.mismatches,8,x=>record(x)&&str(x.field,80)&&str(x.left)&&str(x.right))&&
    d.compatible===(d.mismatches.length===0)&&["post_value","impact"].every(k=>deltaOK(d[k],b,a,d.compatible))&&
    pageOK(d.components,x=>record(x)&&str(x.root_key)&&str(x.path_key)&&(x.before!==null||x.after!==null)&&
      (x.before===null||componentOK(x.before,b))&&(x.after===null||componentOK(x.after,a))&&
      ["post_value","impact"].every(k=>deltaOK(x[k],b,a,d.compatible)));}
  function row(id,values){const tr=document.createElement("tr");values.forEach((value,index)=>{const cell=document.createElement(index===0?"th":"td");if(index===0)cell.scope="row";cell.textContent=value;tr.append(cell);});el(id).append(tr);}
  function evidence(c,label){const refs=c.summary.terminal_pre_value.source_reference_ids;
    const li=document.createElement("li");li.textContent=`${label}: ${refs.items.length} source references shown; ${refs.omitted_count} omitted. ${refs.items.join(", ")}`;el("sources").append(li);
    for(const diagnostic of c.diagnostics.items){const item=document.createElement("li");item.textContent=`${label}: ${text(diagnostic.reason,80)}`;el("warnings").append(item);}
    const item=document.createElement("li");item.textContent=`${label}: ${c.diagnostics.omitted_count} additional diagnostics omitted.`;el("warnings").append(item);
  }
  function detail(){
    el("sensitivities").replaceChildren();set("component-detail","");set("effects","");el("details").hidden=true;
    if(!current)return;const index=Number(el("component-select").value);if(!Number.isSafeInteger(index)||index<0||index>=current.components.items.length)return;
    const value=current.components.items[index],sides=current.compare?[["Before",value.before],["After",value.after]]:[["Scenario",value]];
    const descriptions=[],channels=[];
    for(const [label,item] of sides){if(item===null){descriptions.push(`${label}: component absent from retained partition.`);continue;}
      const e=item.exposure;descriptions.push(`${label}: ${e.root_key} / ${e.path_key}; instrument ${text(e.instrument.subject_id,36)} (${text(e.instrument.state,40)}); entity ${text(e.entity.subject_id,36)} (${text(e.entity.state,40)}). Sector ${text(e.sector.bucket_key)}; region ${text(e.region.bucket_key)}; economic currency ${text(e.economic_currency.currency,3)} (${text(e.economic_currency.state,40)}). Winning rule ${text(item.winning_price_rule_key)}. Exclusions: ${item.matching_exclusion_keys.join(", ")||"none"}. Uncertain rules: ${item.uncertain_rule_keys.join(", ")||"none"}. Source references: ${e.source_reference_ids.items.length} shown, ${e.source_reference_ids.omitted_count} omitted. Diagnostics: ${item.diagnostic_keys.items.length} shown, ${item.diagnostic_keys.omitted_count} omitted.`);
      channels.push(`${label}: price ${ratioText(item.effects.price_ratio)}, factor ${ratioText(item.effects.factor_ratio)}, FX ${ratioText(item.effects.fx_ratio)}. Money effects: price ${moneyText(item.effects.price)}, factor ${moneyText(item.effects.factor)}, FX ${moneyText(item.effects.fx)}, interaction ${moneyText(item.effects.interaction)}. Rounding residual ${moneyText(item.rounding_residual)}.`);
      for(const s of item.sensitivity_uses)row("sensitivities",[`${label} · ${s.rule_key}`,`${s.driver_id} / ${s.version_id}`,s.observation_id??"Unavailable",s.coefficient??"Unavailable",s.shock_size,ratioText(s.effect_ratio),`${s.reason??"resolved"}; ${s.candidate_observation_ids.omitted_count} candidate observations omitted; ${s.driver_evidence_reference_ids.omitted_count} driver references omitted`]);
    }
    set("component-detail",descriptions.join(" "));set("effects",channels.join(" "));el("details").hidden=false;
  }
  function render(d,isComparison){
    const before=isComparison?d.before:d.context,after=isComparison?d.after:null,s=before.summary;
    set("method",`${before.definition.name} · ${before.definition.mode} · method ${before.method_version} · ${before.numerical_profile}. Valuation ${before.valuation_at}; cutoff ${before.pins.source_cutoff_at}; reporting currency ${before.pins.reporting_currency}.${after?` After: ${after.definition.name} · ${after.definition.mode}; valuation ${after.valuation_at}; cutoff ${after.pins.source_cutoff_at}; currency ${after.pins.reporting_currency}.`:""}`);
    set("basis",isComparison?(d.compatible?"Compatible retained bases. Differences are after minus before.":`Incompatible retained bases. Both sides remain visible; differences are unavailable. ${d.mismatches.map(x=>`${x.field}: ${x.left} / ${x.right}`).join("; ")}`):`Assumptions: ${before.assumptions.join(", ")}. ${replayText(before)}`);
    if(after)set("basis",el("basis").textContent+` Before: ${replayText(before)} After: ${replayText(after)}`);
    set("coverage",`Before/scenario partition: ${s.covered_count} covered, ${s.uncovered_count} uncovered, ${s.excluded_count} excluded; ${s.missing_pre_value_count} missing pre-values, ${s.uncertain_money_count} uncertain money rows.${after?` After partition: ${after.summary.covered_count} covered, ${after.summary.uncovered_count} uncovered, ${after.summary.excluded_count} excluded.`:""} Known-only subtotals do not replace unavailable full totals.`);
    const labels=[["Terminal pre-value","terminal_pre_value"],["Covered pre-value","covered_pre_value"],["Uncovered pre-value","uncovered_pre_value"],["Excluded pre-value","excluded_pre_value"],["Post-value","post_value"],["Impact","impact"],["Rounding residual","rounding_residual"],["Component-sum residual","component_sum_residual"]];
    for(const [label,key] of labels)row("summary",[label,moneyText(s[key]),after?moneyText(after.summary[key]):"—",after&&["post_value","impact"].includes(key)?moneyText(d[key].difference):"—"]);
    const p=d.components;set("page-count",`${p.items.length} whole components shown from ordinal ${p.start_ordinal}; ${p.total} total; requested maximum ${p.component_limit}. ${p.next_cursor?"More components are available.":"End of retained components."}`);
    p.items.forEach((item,index)=>{const b=isComparison?item.before:item,a=isComparison?item.after:null,e=b?.exposure??a.exposure;
      row("components",[`${e.root_key} / ${e.path_key}`,b?`${b.partition}: ${moneyText(b.exposure.pre_value)}`:"Absent",b?moneyText(b.post_value):"Absent",a?`${a.partition}: ${moneyText(a.post_value)}`:"—",isComparison?moneyText(item.post_value.difference):moneyText(item.impact)]);
      const option=document.createElement("option");option.value=String(index);option.textContent=`${p.start_ordinal+index+1}: ${e.root_key} / ${e.path_key}`;el("component-select").append(option);
    });
    set("digest",`Public page ${d.content_digest}; saved ${before.saved_result_digest}${after?` / ${after.saved_result_digest}`:""}. Public view ${d.view_version}.`);
    evidence(before,isComparison?"Before":"Scenario");if(after)evidence(after,"After");
    set("source-count","Source/proof lists are bounded previews with explicit omissions. Complete proof remains in authorized canonical storage.");
    current={...d,compare:isComparison};el("content").hidden=false;detail();
  }
  function show(result,expected=selection){
    if(disposed||partialInput)return;clear("Reading saved scenario result.");
    try{
      if(!record(result)||new TextEncoder().encode(JSON.stringify(result)).byteLength>2097152)throw new Error();
      const envelope=result.structuredContent??result.structured_content??result;
      if(record(envelope)&&record(envelope.error)&&["AUTHENTICATION_REQUIRED","ACCESS_DENIED","NOT_FOUND","SCENARIO_UNAVAILABLE","SOURCE_UNAVAILABLE","RUN_EXPIRED","CURSOR_INVALID","RATE_LIMITED"].includes(envelope.error.code)){clear(`Scenario read unavailable: ${envelope.error.code}. Retry with current authorized inputs.`);return;}
      if(result.isError||result.is_error||!record(envelope)||envelope.execution_allowed!==false||envelope.error!==null||!record(envelope.data))throw new Error();
      const d=envelope.data,isComparison=record(d.before)&&record(d.after),account=isComparison?d.before.pins?.account_id:d.account_id;
      const ids=isComparison?[d.before.run_id,d.after.run_id]:[d.id];
      if(!uuid(account)||!ids.every(uuid)||(expected&&(expected.account_id!==account||(expected.run_id&&expected.run_id!==ids[0])||(expected.run_ids&&JSON.stringify(expected.run_ids)!==JSON.stringify(ids)))))throw new Error();
      if(expected?.scenario_version_id&&["scenario_version_id","portfolio_snapshot_id","xray_run_id"].some(k=>expected[k]!==d[k]))throw new Error();
      let view=d;
      if(isComparison){if(!compareOK(d))throw new Error();}
      else{
        if(!states.includes(d.state)||!["pending","available","not_loaded","expired","unavailable"].includes(d.result_availability)||((d.result!==null)!==(d.result_availability==="available")))throw new Error();
        view=d.result;
        if(view!==null){const c=view.context;
          if(d.state!=="succeeded"||!contextOK(c)||c.run_id!==d.id||c.pins.account_id!==account||c.input_digest!==d.input_digest||["scenario_version_id","portfolio_snapshot_id","xray_run_id"].some(k=>c.pins[k]!==d[k])||!pageOK(view.components,x=>componentOK(x,c.pins.reporting_currency))||view.components.total!==c.summary.covered_count+c.summary.uncovered_count+c.summary.excluded_count)throw new Error();
        }
      }
      if(view!==null&&(!digest(view.content_digest)||view.view_version!=="scenario_compact_v1"||(expected?.component_limit&&view.components.component_limit!==expected.component_limit)||(expected?.ordinal!==undefined&&view.components.start_ordinal!==expected.ordinal)))throw new Error();
      const saved=view===null?null:(isComparison?[d.before.saved_result_digest,d.after.saved_result_digest]:[view.context.saved_result_digest]);
      if(expected?.saved&&saved&&JSON.stringify(expected.saved)!==JSON.stringify(saved))throw new Error();
      selection={account_id:account,...(isComparison?{run_ids:ids}:{run_id:ids[0]}),component_limit:view?.components.component_limit??expected?.component_limit??25,saved};
      set("identity",`Account ${account} · ${isComparison?"Before / after runs":"Run"} ${ids.join(" / ")}`);
      if(view===null){set("status",`Scenario state: ${d.state}; result: ${d.result_availability}. No financial result is available.`);buttons();return;}
      render(view,isComparison);set("status",isComparison?"Saved scenario comparison.":"Completed saved scenario analysis.");buttons();
    }catch(_){clear("Scenario result is unavailable or does not match the selected account, run and contract.");}
  }
  function finish(id,result){if(!pending||pending.id!==id||pending.generation!==generation||disposed)return;const expected=pending.expected;clearTimeout(pending.timer);pending=null;show(result,expected);}
  function read(mode){
    if(!selection||pending||disposed||partialInput||!bridgeAvailable())return;
    const expected={...selection};let name="get_scenario_result",args={account_id:selection.account_id,component_limit:selection.component_limit};
    if(mode==="compare"){const other=inputUUID(el("other-run").value);if(!selection.run_id||!other||other===selection.run_id)return;expected.run_ids=[selection.run_id,other];delete expected.run_id;delete expected.saved;}
    if(expected.run_ids){name="compare_scenarios";args.run_ids=[...expected.run_ids];}else if(expected.run_id)args.run_id=expected.run_id;else return;
    if(mode==="next"){if(!current?.components.next_cursor)return;args.component_cursor=current.components.next_cursor;expected.ordinal=current.components.start_ordinal+current.components.items.length;}else expected.ordinal=0;
    const id=`scenario-read-${++counter}`,token=generation;clear("Loading an authorized saved scenario page.");
    pending={id,generation:token,expected,timer:setTimeout(()=>finish(id,{error:true}),15000)};buttons();
    if(serverTools)window.parent.postMessage({jsonrpc:"2.0",id,method:"tools/call",params:{name,arguments:args}},"*");
    else Promise.resolve().then(()=>window.openai.callTool(name,args)).then(value=>finish(id,value),()=>finish(id,{error:true}));
  }
  function input(args,partial){
    invalidate("Waiting for the authorized scenario result. Input arguments are not financial results.");partialInput=true;
    if(!partial&&record(args)&&inputUUID(args.account_id)){
      const pin={account_id:inputUUID(args.account_id),component_limit:args.component_limit??25};if(!count(pin.component_limit,100)||pin.component_limit===0)return;
      if(Object.prototype.hasOwnProperty.call(args,"run_ids")){if(!array(args.run_ids,2,x=>inputUUID(x)!==null)||args.run_ids.length!==2)return;pin.run_ids=args.run_ids.map(inputUUID);if(pin.run_ids[0]===pin.run_ids[1])return;}
      else if(Object.prototype.hasOwnProperty.call(args,"run_id")){pin.run_id=inputUUID(args.run_id);if(!pin.run_id)return;}
      else{for(const k of ["scenario_version_id","portfolio_snapshot_id","xray_run_id"]){pin[k]=inputUUID(args[k]);if(!pin[k])return;}}
      selection=pin;partialInput=false;
    }buttons();
  }
  function message(event){const d=event.data;if(disposed||event.source!==window.parent||d?.jsonrpc!=="2.0")return;
    if(d.id==="scenario-ui-initialize"&&d.result?.protocolVersion==="2026-01-26"){serverTools=record(d.result.hostCapabilities?.serverTools);window.parent.postMessage({jsonrpc:"2.0",method:"ui/notifications/initialized",params:{}},"*");buttons();return;}
    if(d.method==="ui/resource-teardown"&&d.id!==undefined){invalidate("Scenario view closed.");disposed=true;buttons();window.removeEventListener("message",message);window.removeEventListener("openai:set_globals",legacy);window.parent.postMessage({jsonrpc:"2.0",id:d.id,result:{}},"*");return;}
    if(d.id!==undefined){if(!d.method)finish(d.id,d.error?{error:true}:d.result);return;}
    if(d.method==="ui/notifications/tool-input")input(d.params?.arguments,false);
    else if(d.method==="ui/notifications/tool-input-partial")input(d.params?.arguments,true);
    else if(d.method==="ui/notifications/tool-cancelled"){invalidate("Tool execution was cancelled. No current result is displayed.");partialInput=true;}
    else if(d.method==="ui/notifications/tool-result"&&!pending)show(d.params);
  }
  function legacy(event){if(disposed||pending||partialInput||serverTools)return;const globals=event.detail?.globals;if(globals&&Object.prototype.hasOwnProperty.call(globals,"toolOutput"))show(globals.toolOutput);}
  el("refresh").addEventListener("click",()=>read("first"));el("first").addEventListener("click",()=>read("first"));el("next").addEventListener("click",()=>read("next"));
  el("compare").addEventListener("click",()=>read("compare"));el("other-run").addEventListener("input",buttons);el("component-select").addEventListener("change",detail);
  window.addEventListener("message",message);window.addEventListener("openai:set_globals",legacy);clear("Waiting for an authorized saved scenario result.");
  window.parent.postMessage({jsonrpc:"2.0",id:"scenario-ui-initialize",method:"ui/initialize",params:{protocolVersion:"2026-01-26",appInfo:{name:"portfolio-scenario",version:"1.0.0"},appCapabilities:{availableDisplayModes:["inline"]}}},"*");
  if(window.openai?.toolInput)input(window.openai.toolInput,false);if(window.openai?.toolOutput)show(window.openai.toolOutput);
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
<main><h1>Portfolio scenarios</h1><p>Saved stress estimates from explicit assumptions. Exact decimal ratios are shown: 0.01 means 1%. Missing values retain their reasons. No broker action is available.</p>
<p id="status" role="status" aria-live="polite"></p><p id="identity"></p>
<div class="actions"><button id="refresh" disabled>Refresh saved result</button><button id="first" disabled>Start components</button><button id="next" disabled>Next components</button></div>
<label for="other-run">Compare with another saved run ID</label><input id="other-run" type="text" maxlength="36" autocomplete="off" spellcheck="false"><button id="compare" disabled>Compare saved runs</button><p id="bridge"></p>
<section id="content" hidden><p id="method"></p><p id="basis"></p><p id="coverage"></p>
<div class="table-wrap" tabindex="0" role="region" aria-label="Scenario summaries"><table><caption>Retained financial summaries</caption><thead><tr><th scope="col">Measure</th><th scope="col">Scenario / before</th><th scope="col">After</th><th scope="col">Difference</th></tr></thead><tbody id="summary"></tbody></table></div>
<h2>Financial components</h2><p id="page-count"></p><div class="table-wrap" tabindex="0" role="region" aria-label="Scenario component page"><table><caption>Whole retained component paths</caption><thead><tr><th scope="col">Root / path</th><th scope="col">Partition / pre-value</th><th scope="col">Scenario / before post-value</th><th scope="col">After post-value</th><th scope="col">Impact / post-value difference</th></tr></thead><tbody id="components"></tbody></table></div>
<label for="component-select">Inspect a component on this page</label><select id="component-select"></select>
<section id="details" hidden><h2>Selected component evidence</h2><p id="component-detail"></p><p id="effects"></p><div class="table-wrap" tabindex="0" role="region" aria-label="Selected component sensitivities"><table><caption>All retained sensitivity uses for the selected component</caption><thead><tr><th scope="col">Side / rule</th><th scope="col">Driver / version</th><th scope="col">Observation</th><th scope="col">Coefficient</th><th scope="col">Shock</th><th scope="col">Effect ratio / quality</th><th scope="col">Reason / omissions</th></tr></thead><tbody id="sensitivities"></tbody></table></div></section>
<details><summary>Source evidence and result identity</summary><p id="source-count"></p><p id="digest"></p><ul id="sources"></ul><ul id="warnings"></ul></details></section></main>
""".strip()
SCENARIO_WIDGET_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">'
    f"<title>Portfolio scenarios</title><style>{_STYLE}</style></head><body>{_BODY}"
    f"<script>{_SCRIPT}</script></body></html>"
)
