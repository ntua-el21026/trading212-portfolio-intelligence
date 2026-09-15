# ruff: noqa: E501
"""Exact direct allocation and cash values, with an authorized account result pin."""

from .read_widget import read_widget

ALLOCATION_WIDGET_URI = "ui://trading212-portfolio/allocation-v1.html"
ALLOCATION_WIDGET_MIME = "text/html;profile=mcp-app"
_SCRIPT = r"""
function parseInput(a){if(!record(a)||!Object.keys(a).every(k=>["account_id","top_n"].includes(k))||!opaque(a.account_id))return null;const top=a.top_n??25;return count(top,50)&&top>0?{account_id:a.account_id,top_n:top}:null;}
function metricOK(x,c){return record(x)&&x.reporting_currency===c&&(x.value===null||decimal(x.value))&&["available","partial","unavailable"].includes(x.availability)&&str(x.calculation_version,120)&&str(x.methodology,240)&&array(x.provenance,20,v=>str(v,120))&&array(x.assumptions,20,v=>str(v,240))&&(x.unavailable_reason===null||str(x.unavailable_reason,240));}
function validateResult(e,p,raw){const d=e?.data,q=e?.data_quality,c=e?.calculation,m=raw?._meta??window.openai?.toolResponseMetadata;return record(e)&&e.error===null&&record(d)&&m?.accountId===p.account_id&&currency(e.reporting_currency)&&instant(e.as_of)&&record(q)&&quality(q.state)&&instant(q.source_cutoff_at)&&array(q.warnings,20,x=>str(x,240))&&array(q.missing_inputs,20,x=>str(x,120))&&record(c)&&str(c.name,80)&&str(c.version,120)&&instant(c.calculated_at)&&array(c.assumptions,20,x=>str(x,240))&&d.methodology==="direct_provider_observed_positions_and_cash"&&d.etf_look_through===false&&d.read_only===true&&typeof d.includes_cash==="boolean"&&array(d.allocations,51,x=>record(x)&&opaque(x.id)&&str(x.label,160)&&str(x.asset_type,40)&&metricOK(x.market_value,e.reporting_currency)&&(x.weight===null||decimal(x.weight))&&["available","partial","unavailable"].includes(x.weight_availability))&&d.returned_count===d.allocations.length&&record(e.pagination)&&e.pagination.limit===p.top_n&&count(e.pagination.total)&&e.pagination.total>=d.returned_count&&typeof e.pagination.truncated==="boolean";}
function toolName(){return "get_direct_allocation";}
function toolArguments(p){return {...p};}
function nextArguments(){return null;}
function renderData(e,parent){const d=e.data;para(parent,`Account ${selection.account_id}. ${d.returned_count} returned rows of ${e.pagination.total}; truncated ${e.pagination.truncated}. Cash included ${d.includes_cash}; no ETF look-through. Ratios remain exact: 0.01 means 1%.`);para(parent,`As of ${e.as_of}; source cutoff ${e.data_quality.source_cutoff_at}; ${e.data_quality.state}. Method ${e.calculation.name} ${e.calculation.version}, calculated ${e.calculation.calculated_at}.`);
 const button=document.createElement("button"),area=document.createElement("section");button.textContent="Sort by name";let alphabetical=false;const draw=()=>{area.replaceChildren();const rows=[...d.allocations];if(alphabetical)rows.sort((a,b)=>a.label.localeCompare(b.label)||a.id.localeCompare(b.id));table(area,"Direct allocation and cash",["Holding","Exact value","Exact weight / availability","Quality / source"],rows.map(x=>[`${x.label} (${x.asset_type})`,x.market_value.value===null?`Unavailable: ${x.market_value.unavailable_reason??"No captured value"}`:`${x.market_value.value} ${x.market_value.reporting_currency}`,`${exact(x.weight)} / ${x.weight_availability}`,`${x.market_value.availability}; ${x.market_value.methodology}; ${x.market_value.provenance.join(", ")||"No references"}`]));};button.addEventListener("click",()=>{alphabetical=!alphabetical;button.textContent=alphabetical?"Restore source order":"Sort by name";draw();});parent.append(button,area);draw();const proof=disclosure(parent,"Method, quality and complete row assumptions");for(const w of e.data_quality.warnings)para(proof,w);for(const v of e.data_quality.missing_inputs)para(proof,`Missing input: ${v}`);for(const a of e.calculation.assumptions)para(proof,a);for(const x of d.allocations){para(proof,`${x.id}: calculation ${x.market_value.calculation_version}. ${x.market_value.assumptions.join("; ")||"No additional assumptions"}.`);}}
""".strip()
ALLOCATION_WIDGET_HTML = read_widget(
    title="Direct portfolio allocation",
    introduction="Observed positions and cash with exact values, source metadata and explicit missing values. This view has no broker actions.",
    name="portfolio-allocation",
    script=_SCRIPT,
)
