# ruff: noqa: E501
"""Exact saved projection tables with bounded host reads and no browser persistence."""

from __future__ import annotations

import base64
import hashlib

PROJECTION_WIDGET_URI = "ui://trading212-portfolio/projection-v1.html"
PROJECTION_WIDGET_MIME = "text/html;profile=mcp-app"
_STYLE = """
:root{color-scheme:light dark;font-family:system-ui,sans-serif;font-variant-numeric:tabular-nums}
*{box-sizing:border-box}body{margin:0;padding:16px}main{max-width:1080px;margin:auto;min-width:0}h1{font-size:1.5rem}h2{font-size:1.2rem}
p,td,th,li,label{overflow-wrap:anywhere}button,select,summary{font:inherit;min-height:44px}button,select{padding:8px;margin:4px 4px 4px 0;max-width:100%}
button:disabled{cursor:not-allowed}.actions{display:flex;flex-wrap:wrap;gap:8px}.table-wrap{max-height:480px;overflow:auto;margin:12px 0}table{border-collapse:collapse;width:100%;min-width:720px;table-layout:fixed}
caption{text-align:left;font-weight:600;padding:12px 0}th,td{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid #888}:focus-visible{outline:3px solid #1879bd;outline-offset:3px}[hidden]{display:none!important}
@media(max-width:480px){body{padding:10px}th,td{padding:5px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
""".strip()
_SCRIPT = r"""
(() => {
  "use strict";
  const el=id=>document.getElementById(id), record=x=>x!==null&&typeof x==="object"&&!Array.isArray(x);
  const str=(x,max=1024)=>typeof x==="string"&&x.length>0&&x.length<=max;
  const decimal=x=>typeof x==="string"&&/^-?(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$/.test(x);
  const ratio=x=>typeof x==="string"&&/^(?:0(?:\.[0-9]{1,18})?|1(?:\.0{1,18})?)$/.test(x);
  const uuid=x=>typeof x==="string"&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(x);
  const inputUUID=x=>typeof x==="string"&&uuid(x.toLowerCase())?x.toLowerCase():null;
  const digest=x=>typeof x==="string"&&/^[0-9a-f]{64}$/.test(x),currency=x=>typeof x==="string"&&/^[A-Z]{3}$/.test(x);
  const count=(x,max=100000)=>Number.isSafeInteger(x)&&x>=0&&x<=max;
  const array=(x,max,check=record)=>Array.isArray(x)&&x.length<=max&&x.every(item=>check(item));
  const day=x=>typeof x==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(x),instant=x=>str(x,40)&&/^\d{4}-\d{2}-\d{2}T/.test(x);
  const preview=(x,check=uuid)=>record(x)&&array(x.items,64,check)&&count(x.omitted_count,250000);
  const quality=x=>["fresh","stale","partial","estimated","unreconciled","failed"].includes(x);
  const money=(x,c)=>record(x)&&decimal(x.amount)&&currency(x.currency)&&(!c||x.currency===c);
  const moneyText=x=>`${x.amount} ${x.currency}`;
  const variants=["baseline","contribution_delta","mean_log_delta"],states=["queued","running","succeeded","failed","expired","cancelled"];
  const pointMoney=["nominal","real","contributions","withdrawals_requested","withdrawals_funded","unpaid_withdrawals","investment_effect","fees","tax_drag","wealth_residual","allocation_residual","withdrawal_residual"];
  const flowMoney=["contributions","withdrawals_requested","withdrawals_funded","unpaid_withdrawals","investment_effect","fees","tax_drag"];
  const quantiles=(x,c)=>record(x)&&JSON.stringify(x.probabilities)==='["0.05","0.25","0.5","0.75","0.95"]'&&array(x.values,5,item=>money(item,c))&&x.values.length===5;
  const quantileText=x=>x.values.map((value,index)=>`${x.probabilities[index]}: ${moneyText(value)}`).join("; ");
  const set=(id,value)=>{el(id).textContent=value;};
  let selection=null,current=null,generation=0,counter=0,pending=null,partialInput=false,disposed=false,serverTools=false;
  function bridgeAvailable(){return serverTools||typeof window.openai?.callTool==="function";}
  function buttons(){
    const enabled=!disposed&&!partialInput&&selection?.run_id&&bridgeAvailable()&&!pending;
    for(const id of ["refresh","first","goal-read"])el(id).disabled=!enabled;
    el("next").disabled=!enabled||!current?.points?.next_cursor;
    set("bridge",bridgeAvailable()?"Reads use the host's authorized tools. No values are sent directly to another server.":"Widget reads are unavailable in this host. Ask the conversation to read the saved run, next point page or goal analysis.");
  }
  function clear(message){
    current=null;el("content").hidden=true;el("point-section").hidden=true;el("variant-section").hidden=true;
    for(const id of ["distribution","histogram","flows","goals","points","point-money","point-assets","sources","warnings","variant-select","point-select","assumptions","schedule"])el(id).replaceChildren();
    for(const id of ["identity","method","basis","page-count","digest","source-count","point-identity","assumption-basis"])set(id,"");
    set("status",message);buttons();
  }
  function invalidate(message){generation++;if(pending)clearTimeout(pending.timer);pending=null;selection=null;clear(message);}
  function row(id,values){const tr=document.createElement("tr");values.forEach((value,index)=>{const cell=document.createElement(index===0?"th":"td");if(index===0)cell.scope="row";cell.textContent=value;tr.append(cell);});el(id).append(tr);}
  function option(id,label){const value=document.createElement("option");value.textContent=label;el(id).append(value);}
  function contextOK(c){
    const s=c?.selection,a=c?.assumptions;
    return record(c)&&record(s)&&record(a)&&uuid(c.account_id)&&uuid(c.run_id)&&uuid(c.result_id)&&
      ["capture_digest","numerical_input_digest","saved_result_digest","assumption_version_digest"].every(k=>digest(c[k]))&&(c.goal_version_digest===null||digest(c.goal_version_digest))&&
      uuid(s.account_id)&&s.account_id===c.account_id&&uuid(s.assumption_version_id)&&(s.goal_version_id===null||uuid(s.goal_version_id))&&
      count(s.paths,4096)&&s.paths>0&&count(s.months,600)&&s.months>0&&count(s.seed,4294967295)&&array(s.retained_months,121,x=>count(x,s.months))&&s.retained_months.length>=2&&s.retained_months[0]===0&&s.retained_months.at(-1)===s.months&&s.retained_months.every((x,i)=>i===0||x>s.retained_months[i-1])&&
      record(s.initial)&&["modeled_value","observed_snapshot"].includes(s.initial.kind)&&
      (s.initial.kind==="modeled_value"?money(s.initial.modeled_value,c.reporting_currency)&&day(s.initial.modeled_anchor_date):uuid(s.initial.snapshot_id))&&
      record(s.schedule)&&money(s.schedule.base_monthly,c.reporting_currency)&&decimal(s.schedule.annual_growth)&&array(s.schedule.paused_dates,128,day)&&array(s.schedule.entries,128,e=>record(e)&&str(e.key,120)&&day(e.on)&&["lump_sum","withdrawal"].includes(e.kind)&&money(e.value,c.reporting_currency))&&
      (s.sensitivity===null||record(s.sensitivity)&&money(s.sensitivity.contribution_delta,c.reporting_currency)&&decimal(s.sensitivity.annual_mean_log_delta))&&
      day(c.anchor_date)&&day(c.terminal_date)&&instant(c.calculated_at)&&(c.source_cutoff_at===null||instant(c.source_cutoff_at))&&(c.snapshot_valuation_at===null||instant(c.snapshot_valuation_at))&&
      currency(c.reporting_currency)&&a.reporting_currency===c.reporting_currency&&quality(c.quality)&&!["fresh","stale"].includes(c.quality)&&
      array(a.assets,12,x=>record(x)&&str(x.key,120)&&decimal(x.annual_mean_log_return)&&decimal(x.annual_volatility)&&ratio(x.weight))&&a.assets.length>0&&
      array(a.correlation,12,row=>array(row,12,decimal)&&row.length===a.assets.length)&&a.correlation.length===a.assets.length&&decimal(a.annual_inflation)&&decimal(a.annual_fee)&&(a.annual_tax_drag===null||decimal(a.annual_tax_drag))&&["monthly","annual","none"].includes(a.rebalance)&&
      c.method==="projection_v1"&&c.method_version==="1.0.0"&&c.schema_version==="1.0.0"&&c.numeric_profile==="premium_decimal96_q18_v1"&&c.sampler==="sha256_counter_polar_v1"&&c.calendar_rule==="calendar_anniversary_clamped_v1"&&c.interpretation==="model_estimate_not_guaranteed_forecast"&&
      preview(c.source_evidence,x=>record(x)&&["observed_snapshot","calibration"].includes(x.role)&&uuid(x.subject_id)&&digest(x.content_digest)&&quality(x.quality)&&preview(x.source_reference_ids))&&
      preview(c.warnings,x=>str(x,120))&&array(c.numerical_zero_pivots,12,x=>count(x,11));
  }
  function estimateOK(x,c,s){return record(x)&&uuid(x.goal_version_id)&&x.goal_version_id===s.goal_version_id&&["nominal","real"].includes(x.basis)&&money(x.target,c)&&x.paths===s.paths&&count(x.successes,s.paths)&&ratio(x.probability)&&ratio(x.interval_low)&&ratio(x.interval_high)&&ratio(x.probability_objective)&&typeof x.objective_met==="boolean"&&money(x.mean_shortfall,c)&&quantiles(x.shortfalls,c)&&count(x.funding_failed_paths,s.paths)&&x.method==="goal_analysis_v1"&&x.interval_method==="wilson_95_v1"&&x.automatic_goal_acceptance===false;}
  function histogramOK(x,c,paths){return record(x)&&money(x.observed_minimum,c)&&money(x.observed_maximum,c)&&x.boundary_rule==="q18_enclosing_ceiling_v1"&&array(x.bins,20,b=>record(b)&&money(b.lower,c)&&money(b.upper,c)&&typeof b.upper_inclusive==="boolean"&&count(b.count,paths))&&x.bins.length>0&&x.bins.reduce((total,b)=>total+b.count,0)===paths;}
  function variantOK(x,c){const s=c.selection,m=c.reporting_currency,f=x?.cash_flows;return record(x)&&variants.includes(x.variant)&&
    array(x.distributions,121,d=>record(d)&&count(d.month,s.months)&&day(d.on)&&money(d.nominal_mean,m)&&money(d.real_mean,m)&&quantiles(d.nominal,m)&&quantiles(d.real,m)&&count(d.funding_failed_paths,s.paths))&&JSON.stringify(x.distributions.map(d=>d.month))===JSON.stringify(s.retained_months)&&
    histogramOK(x.nominal_histogram,m,s.paths)&&histogramOK(x.real_histogram,m,s.paths)&&record(f)&&flowMoney.every(k=>record(f[k])&&money(f[k].mean,m)&&quantiles(f[k].quantiles,m))&&count(f.funding_failed_paths,s.paths)&&count(f.unpaid_positive_below_quantum_paths,s.paths)&&
    (s.goal_version_id===null?x.goal===null:estimateOK(x.goal,m,s));}
  function pointsOK(p,c){const s=c.selection,v=s.sensitivity===null?["baseline"]:variants,pointCount=s.retained_months.length,total=v.length*s.paths*pointCount,end=p?.start_ordinal+p?.items?.length;
    return record(p)&&array(p.items,100,r=>{const point=r?.point,within=r?.ordinal%(s.paths*pointCount),variantIndex=Math.floor(r?.ordinal/(s.paths*pointCount));return record(r)&&count(r.ordinal,total-1)&&r.variant===v[variantIndex]&&r.path_index===Math.floor(within/pointCount)&&r.point_index===within%pointCount&&r.path_point_count===pointCount&&day(r.on)&&
      (r.first_unpaid_month===null||count(r.first_unpaid_month,s.months)&&r.first_unpaid_month>0)&&record(point)&&point.month===s.retained_months[r.point_index]&&pointMoney.every(k=>money(point[k],c.reporting_currency))&&
      array(point.assets,12,a=>record(a)&&str(a.key,120)&&money(a.value,c.reporting_currency))&&JSON.stringify(point.assets.map(a=>a.key))===JSON.stringify(c.assumptions.assets.map(a=>a.key))&&typeof point.funding_failed==="boolean"&&typeof point.unpaid_positive_below_quantum==="boolean"&&point.funding_failed===(r.first_unpaid_month!==null&&point.month>=r.first_unpaid_month);})&&
      p.total===total&&count(p.start_ordinal,total-1)&&count(p.point_limit,100)&&p.point_limit>0&&p.items.length>0&&p.items.length<=p.point_limit&&end<=total&&p.items.every((r,i)=>r.ordinal===p.start_ordinal+i)&&((p.next_cursor===null&&end===total)||(str(p.next_cursor,2048)&&/^[A-Za-z0-9_-]+$/.test(p.next_cursor)&&end<total));
  }
  function resultOK(d){const c=d?.context;return record(d)&&contextOK(c)&&digest(d.content_digest)&&d.view_version==="projection_points_v1"&&array(d.variants,3,v=>variantOK(v,c))&&JSON.stringify(d.variants.map(v=>v.variant))===JSON.stringify(c.selection.sensitivity===null?["baseline"]:variants)&&pointsOK(d.points,c);}
  function goalOK(d){
    if(!record(d)||!uuid(d.account_id)||!uuid(d.run_id)||!states.includes(d.state)||!["pending","available","not_loaded","expired","unavailable"].includes(d.result_availability)||!digest(d.content_digest)||d.view_version!=="goal_analysis_compact_v1"||(d.goal_version_id!==null&&!uuid(d.goal_version_id)))return false;
    if(d.availability==="unavailable")return ["no_goal_pinned","run_pending","run_failed","run_expired","run_cancelled"].includes(d.reason)&&d.context===null&&array(d.variants,0);
    const c=d.context;return d.availability==="available"&&d.reason===null&&d.state==="succeeded"&&d.result_availability==="available"&&contextOK(c)&&c.account_id===d.account_id&&c.run_id===d.run_id&&c.selection.goal_version_id===d.goal_version_id&&array(d.variants,3,v=>record(v)&&quantiles(v.terminal,c.reporting_currency)&&estimateOK(v.estimate,c.reporting_currency,c.selection))&&JSON.stringify(d.variants.map(v=>v.variant))===JSON.stringify(c.selection.sensitivity===null?["baseline"]:variants);
  }
  function sourceInfo(c){
    set("method",`Method ${c.method} ${c.method_version} · ${c.numeric_profile} · ${c.sampler} · quality ${c.quality}. Reporting currency ${c.reporting_currency}.`);
    set("basis",`${c.selection.initial.kind}; anchor ${c.anchor_date}, terminal ${c.terminal_date}, ${c.selection.paths} paths per variant, seed ${c.selection.seed}. Valuation ${c.snapshot_valuation_at??"Unavailable (modeled basis)"}; source cutoff ${c.source_cutoff_at??"Not supplied by all selected sources"}; calculated ${c.calculated_at}. Values are model estimates, not guaranteed forecasts.`);
    set("digest",`Capture ${c.capture_digest}; numerical input ${c.numerical_input_digest}; saved result ${c.saved_result_digest}.`);
    const a=c.assumptions,s=c.selection;
    set("assumption-basis",`Annual inflation ${a.annual_inflation}; fee ${a.annual_fee}; modeled tax drag ${a.annual_tax_drag??"Not modeled"}; rebalance ${a.rebalance}. Initial ${s.initial.kind==="modeled_value"?moneyText(s.initial.modeled_value)+" at "+s.initial.modeled_anchor_date:"saved snapshot "+s.initial.snapshot_id}. Base monthly contribution ${moneyText(s.schedule.base_monthly)}; annual contribution growth ${s.schedule.annual_growth}. Sensitivity ${s.sensitivity===null?"None":moneyText(s.sensitivity.contribution_delta)+" contribution delta; annual mean-log delta "+s.sensitivity.annual_mean_log_delta}. Numerical zero pivots: ${c.numerical_zero_pivots.join(", ")||"None"}.`);
    a.assets.forEach((asset,index)=>row("assumptions",[asset.key,asset.annual_mean_log_return,asset.annual_volatility,asset.weight,a.correlation[index].map((value,j)=>`${a.assets[j].key}: ${value}`).join("; ")]));
    for(const date of s.schedule.paused_dates)row("schedule",[date,"Paused contribution","No contribution at this boundary"]);
    for(const entry of s.schedule.entries)row("schedule",[`${entry.on} · ${entry.key}`,entry.kind,moneyText(entry.value)]);
    const e=c.source_evidence;set("source-count",`${e.items.length} source entries shown; ${e.omitted_count} omitted. Complete original proof remains in authorized retained storage. Warnings: ${c.warnings.items.length} shown; ${c.warnings.omitted_count} omitted.`);
    for(const item of e.items){const li=document.createElement("li");li.textContent=`${item.role} ${item.subject_id} · ${item.quality} · ${item.content_digest}. References: ${item.source_reference_ids.items.join(", ")||"None"}; ${item.source_reference_ids.omitted_count} omitted.`;el("sources").append(li);}
    for(const warning of c.warnings.items){const li=document.createElement("li");li.textContent=warning;el("warnings").append(li);}
  }
  function goalRow(name,e,terminal){row("goals",[name,`${moneyText(e.target)} (${e.basis})`,`${e.successes} / ${e.paths}; probability ${e.probability}`,`${e.interval_low} to ${e.interval_high} (${e.interval_method})`,`Objective ${e.probability_objective}; ${e.objective_met?"met in model":"not met in model"}. Automatic acceptance: false.`,`${moneyText(e.mean_shortfall)}; ${quantileText(e.shortfalls)}`,terminal?quantileText(terminal):"See terminal distribution",`${e.funding_failed_paths} funding failures`]);}
  function variantDetail(){
    for(const id of ["distribution","histogram","flows"])el(id).replaceChildren();
    if(!current?.points)return;const v=current.variants[el("variant-select").selectedIndex];if(!v)return;
    for(const d of v.distributions)row("distribution",[`${d.month} · ${d.on}`,moneyText(d.nominal_mean),quantileText(d.nominal),moneyText(d.real_mean),quantileText(d.real),`${d.funding_failed_paths} funding failures`]);
    for(const [basis,h] of [["Nominal",v.nominal_histogram],["Real",v.real_histogram]])for(const b of h.bins)row("histogram",[basis,`${moneyText(b.lower)} to ${moneyText(b.upper)} (${b.upper_inclusive?"upper inclusive":"upper exclusive"})`,String(b.count),`${moneyText(h.observed_minimum)} / ${moneyText(h.observed_maximum)}`]);
    for(const field of flowMoney)row("flows",[field,moneyText(v.cash_flows[field].mean),quantileText(v.cash_flows[field].quantiles)]);
    row("flows",["Funding failures",String(v.cash_flows.funding_failed_paths),`${v.cash_flows.unpaid_positive_below_quantum_paths} unpaid positive below q18`]);
  }
  function pointDetail(){
    for(const id of ["point-money","point-assets"])el(id).replaceChildren();
    if(!current?.points)return;const r=current.points.items[el("point-select").selectedIndex];if(!r)return;
    set("point-identity",`${r.variant}; absolute path ${r.path_index}; point ${r.point_index} of ${r.path_point_count}; month ${r.point.month} · ${r.on}; ordinal ${r.ordinal}. First unpaid month ${r.first_unpaid_month??"None"}; funding failed ${r.point.funding_failed}; unpaid positive below q18 ${r.point.unpaid_positive_below_quantum}.`);
    for(const field of pointMoney)row("point-money",[field,moneyText(r.point[field])]);
    for(const item of r.point.assets)row("point-assets",[item.key,moneyText(item.value)]);
  }
  function render(view,isGoal){
    sourceInfo(view.context);current=view;el("content").hidden=false;
    if(isGoal){for(const v of view.variants)goalRow(v.variant,v.estimate,v.terminal);return;}
    el("point-section").hidden=false;el("variant-section").hidden=false;
    view.variants.forEach(v=>{option("variant-select",v.variant);if(v.goal!==null)goalRow(v.variant,v.goal,null);});
    if(view.context.selection.goal_version_id===null)row("goals",["No goal pinned","Unavailable","Unavailable","Unavailable","No automatic goal acceptance","Unavailable","Unavailable","Unavailable"]);
    const p=view.points;set("page-count",`${p.items.length} complete points from ordinal ${p.start_ordinal}; ${p.total} total retained points; requested maximum ${p.point_limit}. ${p.next_cursor?"More points are available.":"End of retained points."} This page is not the simulated population.`);
    for(const r of p.items){row("points",[`${r.ordinal}: ${r.variant}`,`${r.path_index} / ${r.point_index}`,`${r.point.month} · ${r.on}`,moneyText(r.point.nominal),moneyText(r.point.real),`failed ${r.point.funding_failed}; first unpaid ${r.first_unpaid_month??"None"}`]);option("point-select",`${r.ordinal}: ${r.variant} / path ${r.path_index} / point ${r.point_index}`);}
    variantDetail();pointDetail();
  }
  function show(result,expected=selection){
    if(disposed||partialInput)return;clear("Reading saved projection result.");
    try{
      if(!record(result)||new TextEncoder().encode(JSON.stringify(result)).byteLength>2097152)throw new Error();
      const envelope=result.structuredContent??result.structured_content??result;
      if(record(envelope)&&record(envelope.error)&&["AUTHENTICATION_REQUIRED","ACCESS_DENIED","NOT_FOUND","PROJECTION_UNAVAILABLE","SOURCE_UNAVAILABLE","RUN_EXPIRED","CURSOR_INVALID","RATE_LIMITED","RESULT_TOO_LARGE"].includes(envelope.error.code)){clear(`Projection read unavailable: ${envelope.error.code}. Retry with current authorized inputs.`);return;}
      if(result.isError||result.is_error||!record(envelope)||envelope.execution_allowed!==false||envelope.error!==null||!record(envelope.data))throw new Error();
      const d=envelope.data,isGoal=d.view_version==="goal_analysis_compact_v1",account=d.account_id,runId=isGoal?d.run_id:d.id;
      if(!uuid(account)||!uuid(runId)||(expected&&(expected.account_id!==account||(expected.run_id&&expected.run_id!==runId))))throw new Error();
      if(expected?.assumption_version_id&&d.assumption_version_id!==expected.assumption_version_id)throw new Error();
      if(expected?.mode&&expected.mode!==(isGoal?"goal":"run"))throw new Error();
      let view=null;
      if(isGoal){if(!goalOK(d))throw new Error();view=d.availability==="available"?d:null;}
      else{
        if(!states.includes(d.state)||!["pending","available","not_loaded","expired","unavailable"].includes(d.result_availability)||((d.result!==null)!==(d.result_availability==="available"))||!digest(d.capture_digest)||!digest(d.numerical_input_digest))throw new Error();
        view=d.result;
        if(view!==null&&(d.state!=="succeeded"||!resultOK(view)||view.context.run_id!==runId||view.context.account_id!==account||view.context.capture_digest!==d.capture_digest||view.context.numerical_input_digest!==d.numerical_input_digest||view.context.selection.assumption_version_id!==d.assumption_version_id||view.context.selection.goal_version_id!==d.goal_version_id))throw new Error();
      }
      if(view!==null&&new TextEncoder().encode(JSON.stringify(view)).byteLength>1048576)throw new Error();
      if(view?.points&&((expected?.point_limit&&view.points.point_limit!==expected.point_limit)||(expected?.ordinal!==undefined&&view.points.start_ordinal!==expected.ordinal)))throw new Error();
      const saved=view?.context.saved_result_digest??null;
      if(expected?.saved&&saved&&expected.saved!==saved)throw new Error();
      selection={account_id:account,run_id:runId,point_limit:view?.points?.point_limit??expected?.point_limit??25,saved,mode:isGoal?"goal":"run"};
      set("identity",`Account ${account} · Run ${runId}`);
      if(view===null){set("status",isGoal?`Goal analysis unavailable: ${d.reason}. No financial goal estimate is displayed.`:`Projection state: ${d.state}; result: ${d.result_availability}. No financial result is available.`);buttons();return;}
      render(view,isGoal);set("status",isGoal?"Saved goal analysis. Objective attainment never accepts a goal automatically.":"Completed saved projection. Model estimates are not guaranteed forecasts.");buttons();
    }catch(_){clear("Projection result is unavailable or does not match the selected account, run and contract.");}
  }
  function finish(id,result){if(!pending||pending.id!==id||pending.generation!==generation||disposed)return;const expected=pending.expected;clearTimeout(pending.timer);pending=null;show(result,expected);}
  function read(mode){
    if(!selection||pending||disposed||partialInput||!bridgeAvailable())return;
    const goal=mode==="goal"||(mode==="refresh"&&selection.mode==="goal"),name=goal?"get_goal_analysis":"get_projection",args={account_id:selection.account_id,run_id:selection.run_id};
    const expected={...selection,mode:goal?"goal":"run"};
    if(!goal){args.point_limit=selection.point_limit;if(mode==="next"){if(!current?.points?.next_cursor)return;args.point_cursor=current.points.next_cursor;expected.ordinal=current.points.start_ordinal+current.points.items.length;}else expected.ordinal=0;}
    const id=`projection-read-${++counter}`,token=generation;clear("Loading an authorized saved projection view.");
    pending={id,generation:token,expected,timer:setTimeout(()=>finish(id,{error:true}),15000)};buttons();
    if(serverTools)window.parent.postMessage({jsonrpc:"2.0",id,method:"tools/call",params:{name,arguments:args}},"*");
    else Promise.resolve().then(()=>window.openai.callTool(name,args)).then(value=>finish(id,value),()=>finish(id,{error:true}));
  }
  function input(args,partial){
    invalidate("Waiting for the authorized projection result. Input arguments are not financial results.");partialInput=true;
    if(!partial&&record(args)&&inputUUID(args.account_id)){
      const pin={account_id:inputUUID(args.account_id),point_limit:args.point_limit??25};if(!count(pin.point_limit,100)||pin.point_limit===0)return;
      if(Object.prototype.hasOwnProperty.call(args,"run_id")){pin.run_id=inputUUID(args.run_id);if(!pin.run_id)return;}
      else{pin.assumption_version_id=inputUUID(args.assumption_version_id);if(!pin.assumption_version_id)return;}
      selection=pin;partialInput=false;
    }buttons();
  }
  function message(event){const d=event.data;if(disposed||event.source!==window.parent||d?.jsonrpc!=="2.0")return;
    if(d.id==="projection-ui-initialize"&&d.result?.protocolVersion==="2026-01-26"){serverTools=record(d.result.hostCapabilities?.serverTools);window.parent.postMessage({jsonrpc:"2.0",method:"ui/notifications/initialized",params:{}},"*");buttons();return;}
    if(d.method==="ui/resource-teardown"&&d.id!==undefined){invalidate("Projection view closed.");disposed=true;buttons();window.removeEventListener("message",message);window.removeEventListener("openai:set_globals",legacy);window.parent.postMessage({jsonrpc:"2.0",id:d.id,result:{}},"*");return;}
    if(d.id!==undefined){if(!d.method)finish(d.id,d.error?{error:true}:d.result);return;}
    if(d.method==="ui/notifications/tool-input")input(d.params?.arguments,false);
    else if(d.method==="ui/notifications/tool-input-partial")input(d.params?.arguments,true);
    else if(d.method==="ui/notifications/tool-cancelled"){invalidate("Tool execution was cancelled. No current result is displayed.");partialInput=true;}
    else if(d.method==="ui/notifications/tool-result"&&!pending)show(d.params);
  }
  function legacy(event){if(disposed||pending||partialInput||serverTools)return;const globals=event.detail?.globals;if(globals&&Object.prototype.hasOwnProperty.call(globals,"toolOutput"))show(globals.toolOutput);}
  el("refresh").addEventListener("click",()=>read("refresh"));el("first").addEventListener("click",()=>read("first"));el("next").addEventListener("click",()=>read("next"));el("goal-read").addEventListener("click",()=>read("goal"));
  el("variant-select").addEventListener("change",variantDetail);el("point-select").addEventListener("change",pointDetail);
  window.addEventListener("message",message);window.addEventListener("openai:set_globals",legacy);clear("Waiting for an authorized saved projection result.");
  window.parent.postMessage({jsonrpc:"2.0",id:"projection-ui-initialize",method:"ui/initialize",params:{protocolVersion:"2026-01-26",appInfo:{name:"portfolio-projection",version:"1.0.0"},appCapabilities:{availableDisplayModes:["inline"]}}},"*");
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
<main><h1>Portfolio projections</h1><p>Saved model estimates, not guaranteed forecasts. Exact decimal ratios are shown: 0.01 means 1%. No broker action or automatic goal acceptance is available.</p>
<p id="status" role="status" aria-live="polite"></p><p id="identity"></p>
<div class="actions"><button id="refresh" disabled>Refresh saved view</button><button id="first" disabled>Start point pages</button><button id="next" disabled>Next points</button><button id="goal-read" disabled>Read saved goal analysis</button></div><p id="bridge"></p>
<section id="content" hidden><p id="method"></p><p id="basis"></p>
<details><summary>Saved assumptions and dated schedule</summary><p id="assumption-basis"></p><div class="table-wrap" tabindex="0" role="region" aria-label="Saved assumptions"><table><caption>Exact asset assumptions and correlation axes</caption><thead><tr><th scope="col">Asset</th><th scope="col">Annual mean log return</th><th scope="col">Annual volatility</th><th scope="col">Weight</th><th scope="col">Correlation row</th></tr></thead><tbody id="assumptions"></tbody></table></div><div class="table-wrap" tabindex="0" role="region" aria-label="Dated schedule"><table><caption>All selected pauses and dated cash flows</caption><thead><tr><th scope="col">Date / key</th><th scope="col">Kind</th><th scope="col">Value / effect</th></tr></thead><tbody id="schedule"></tbody></table></div></details>
<section id="variant-section" hidden><h2>Complete retained distributions</h2><label for="variant-select">Select a saved variant</label><select id="variant-select"></select>
<div class="table-wrap" tabindex="0" role="region" aria-label="Projection distributions"><table><caption>All retained months for the selected variant</caption><thead><tr><th scope="col">Month / date</th><th scope="col">Nominal mean</th><th scope="col">Nominal quantiles</th><th scope="col">Real mean</th><th scope="col">Real quantiles</th><th scope="col">Funding</th></tr></thead><tbody id="distribution"></tbody></table></div>
<details><summary>Terminal histograms and cash-flow summaries</summary><div class="table-wrap" tabindex="0" role="region" aria-label="Terminal histograms"><table><caption>Terminal histogram bins and observed extrema</caption><thead><tr><th scope="col">Basis</th><th scope="col">Bin</th><th scope="col">Paths</th><th scope="col">Observed min / max</th></tr></thead><tbody id="histogram"></tbody></table></div>
<div class="table-wrap" tabindex="0" role="region" aria-label="Cash-flow summaries"><table><caption>Whole-population terminal cash flows</caption><thead><tr><th scope="col">Measure</th><th scope="col">Mean / count</th><th scope="col">Quantiles / detail</th></tr></thead><tbody id="flows"></tbody></table></div></details></section>
<h2>Saved goal estimates</h2><div class="table-wrap" tabindex="0" role="region" aria-label="Goal estimates"><table><caption>All saved goal variants; ratios are exact decimal strings</caption><thead><tr><th scope="col">Variant</th><th scope="col">Target</th><th scope="col">Success</th><th scope="col">Sampling interval</th><th scope="col">Objective</th><th scope="col">Shortfall</th><th scope="col">Terminal quantiles</th><th scope="col">Funding</th></tr></thead><tbody id="goals"></tbody></table></div>
<section id="point-section" hidden><h2>Complete retained point page</h2><p id="page-count"></p><div class="table-wrap" tabindex="0" role="region" aria-label="Projection point page"><table><caption>Saved dated points</caption><thead><tr><th scope="col">Ordinal / variant</th><th scope="col">Path / point index</th><th scope="col">Month / date</th><th scope="col">Nominal</th><th scope="col">Real</th><th scope="col">Funding</th></tr></thead><tbody id="points"></tbody></table></div>
<label for="point-select">Inspect every field of a point on this page</label><select id="point-select"></select><p id="point-identity"></p>
<div class="table-wrap" tabindex="0" role="region" aria-label="Complete point money"><table><caption>All selected point money and residuals</caption><thead><tr><th scope="col">Measure</th><th scope="col">Exact value</th></tr></thead><tbody id="point-money"></tbody></table></div>
<div class="table-wrap" tabindex="0" role="region" aria-label="Point asset values"><table><caption>All selected point assets</caption><thead><tr><th scope="col">Asset</th><th scope="col">Exact value</th></tr></thead><tbody id="point-assets"></tbody></table></div></section>
<details><summary>Source evidence, warnings and result identity</summary><p id="source-count"></p><p id="digest"></p><ul id="sources"></ul><ul id="warnings"></ul></details></section></main>
""".strip()
PROJECTION_WIDGET_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">'
    f"<title>Portfolio projections</title><style>{_STYLE}</style></head><body>{_BODY}"
    f"<script>{_SCRIPT}</script></body></html>"
)
