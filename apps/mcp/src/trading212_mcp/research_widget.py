# ruff: noqa: E501
"""Inert research source text, exact portfolio evidence and owner revisions."""

from .read_widget import read_widget

RESEARCH_WIDGET_URI = "ui://trading212-portfolio/research-v1.html"
RESEARCH_WIDGET_MIME = "text/html;profile=mcp-app"
_SCRIPT = r"""
const noteFields=["title","note","thesis","risks","catalysts","break_conditions"];
function parseInput(a){
 if(!record(a)||!inputUUID(a.account_id))return null;
 const p={account_id:inputUUID(a.account_id)};
 if(Object.prototype.hasOwnProperty.call(a,"item_id"))return Object.keys(a).every(k=>["account_id","item_id"].includes(k))&&inputUUID(a.item_id)?{...p,item_id:inputUUID(a.item_id)}:null;
 if(!Object.keys(a).every(k=>["account_id","xray_run_id","source_cutoff_at","entity_id","event_kind","review_state","limit","cursor"].includes(k))||!inputUUID(a.xray_run_id)||!instant(a.source_cutoff_at))return null;
 Object.assign(p,{xray_run_id:inputUUID(a.xray_run_id),source_cutoff_at:a.source_cutoff_at,entity_id:a.entity_id??null,event_kind:a.event_kind??null,review_state:a.review_state??"all",limit:a.limit??25,cursor:a.cursor??null});
 if(p.entity_id!==null){p.entity_id=inputUUID(p.entity_id);if(!p.entity_id)return null;}
 return (p.event_kind===null||["news","company_overview"].includes(p.event_kind))&&["all","reviewed","unreviewed"].includes(p.review_state)&&count(p.limit,100)&&p.limit>0&&(p.cursor===null||typeof p.cursor==="string"&&/^[A-Za-z0-9_-]{1,2048}$/.test(p.cursor))?p:null;
}
function pinOK(p){return record(p)&&["owner_id","account_id","run_id","snapshot_id","policy_id"].every(k=>uuid(p[k]))&&digest(p.input_digest)&&digest(p.result_digest)&&currency(p.reporting_currency)&&["valuation_at","source_cutoff_at","quality_evaluated_at"].every(k=>instant(p[k]))&&p.method==="xray_v1"&&p.method_version==="1.1.0"&&p.numerical_profile==="xray_decimal256_exact_q18_v1"&&p.schema_version==="1"&&str(p.policy_version);}
function citationOK(c,s){const v=c?.source,l=v?.license;return record(c)&&uuid(c.citation_id)&&digest(c.content_digest)&&c.entity_id===s.entity_id&&record(v)&&["source_id","version_id","provider_id","license_version_id"].every(k=>uuid(v[k]))&&v.owner_id===s.owner_id&&v.entity_id===s.entity_id&&v.facts_digest===c.facts_digest&&digest(v.facts_digest)&&digest(v.content_digest)&&digest(v.request_digest)&&v.capability===s.facts.kind&&v.provider==="alpha_vantage"&&typeof v.synthetic==="boolean"&&str(v.adapter_version,128)&&["observed_at","first_known_at","source_cutoff_at","retained_at","expires_at"].every(k=>instant(v[k]))&&record(l)&&l.id===v.license_version_id&&l.provider_id===v.provider_id&&l.store==="allowed"&&l.display==="allowed"&&str(l.attribution)&&str(c.provider_event_key,128)&&(c.published_at===null||instant(c.published_at));}
function itemOK(x){
 const s=x?.source,p=x?.portfolio,b=p?.pin,f=s?.facts;
 return record(x)&&uuid(x.item_id)&&instant(x.source_cutoff_at)&&record(s)&&record(p)&&pinOK(b)&&s.owner_id===b.owner_id&&s.entity_id===p.entity_id&&uuid(s.entity_id)&&uuid(s.event_id)&&uuid(s.revision_id)&&count(s.revision,512)&&s.revision>0&&digest(s.content_digest)&&instant(s.created_at)&&instant(s.expires_at)&&record(f)&&f.content_type==="source_facts"&&str(f.publisher)&&
 (f.kind==="news"?str(f.title)&&str(f.summary)&&instant(f.published_at):f.kind==="company_overview"&&str(f.company_name)&&str(f.description)&&f.published_at===null&&f.publication_reason==="provider_publication_unavailable")&&
 array(s.citations,64,c=>citationOK(c,s))&&s.citations.length>0&&
 p.content_type==="portfolio_facts"&&p.view_schema==="research_portfolio_preview_v1"&&digest(p.canonical_facts_digest)&&quality(p.quality)&&str(p.origin,64)&&["exact","lower_bound"].includes(p.bound)&&
 (p.effective_exposure===null?p.availability==="unavailable"&&["captured_value_unavailable","entity_absent_from_capture"].includes(p.reason):p.availability==="available"&&p.reason===null&&money(p.effective_exposure)&&p.effective_exposure.currency===b.reporting_currency)&&
 (p.confidence===null||decimal(p.confidence))&&typeof p.company_coverage_complete==="boolean"&&typeof p.positive_unresolved_below_quantum==="boolean"&&
 ["source_reference_ids","metric_source_reference_ids"].every(k=>array(p[k],64,uuid))&&array(p.path_keys,64,v=>str(v,1024))&&array(p.warnings,64,w=>record(w)&&str(w.code,120)&&array(w.source_reference_ids,64,uuid)&&array(w.path_keys,64,v=>str(v,1024))&&count(w.source_references_omitted)&&count(w.paths_omitted))&&
 ["warnings_omitted","source_references_omitted","metric_sources_omitted","paths_omitted"].every(k=>count(p[k]))&&count(x.owner_revisions_omitted)&&
 array(x.owner_revisions,64,n=>record(n)&&uuid(n.note_id)&&uuid(n.revision_id)&&n.owner_id===b.owner_id&&n.account_id===b.account_id&&n.entity_id===p.entity_id&&count(n.revision,512)&&n.revision>0&&digest(n.content_digest)&&instant(n.created_at)&&record(n.content)&&n.content.content_type==="owner_revision"&&noteFields.every(k=>str(n.content[k]))&&array(n.content.citations,64,c=>record(c)&&uuid(c.citation_id)&&uuid(c.source_version_id)&&digest(c.source_version_digest)&&digest(c.citation_digest)))&&
 (x.review===null||record(x.review)&&x.review.owner_id===b.owner_id&&x.review.account_id===b.account_id&&x.review.event_id===s.event_id&&x.review.revision_id===s.revision_id&&x.review.revision_digest===s.content_digest&&instant(x.review.reviewed_at))&&record(x.synthesis)&&x.synthesis.availability==="unavailable"&&x.synthesis.content_type==="optional_synthesis"&&["disabled","not_configured","source_unavailable"].includes(x.synthesis.reason);
}
function validateResult(e,p){if(!record(e)||e.error!==null||e.execution_allowed!==false||!record(e.data))return false;const d=e.data;if(p.item_id)return itemOK(d)&&d.item_id===p.item_id&&d.portfolio.pin.account_id===p.account_id;
 return pinOK(d.pin)&&d.pin.account_id===p.account_id&&d.pin.run_id===p.xray_run_id&&sameInstant(d.source_cutoff_at,p.source_cutoff_at)&&d.limit===p.limit&&d.method==="research_summary_v1"&&d.method_version==="1.0.0"&&d.schema_version==="1.0.0"&&count(d.total)&&count(d.unknown_exposure_total,d.total)&&array(d.items,p.limit,x=>itemOK(x)&&x.portfolio.pin.account_id===p.account_id&&x.portfolio.pin.run_id===p.xray_run_id&&x.portfolio.pin.result_digest===d.pin.result_digest&&sameInstant(x.source_cutoff_at,p.source_cutoff_at)&&(p.entity_id===null||x.portfolio.entity_id===p.entity_id)&&(p.event_kind===null||x.source.facts.kind===p.event_kind)&&(p.review_state==="all"||p.review_state==="reviewed"&&x.review!==null||p.review_state==="unreviewed"&&x.review===null))&&d.total>=d.items.length&&(d.next_cursor===null||typeof d.next_cursor==="string"&&/^[A-Za-z0-9_-]{1,2048}$/.test(d.next_cursor));}
function toolName(p){return p.item_id?"get_research_item":"get_research_summary";}
function toolArguments(p){return {...p};}
function nextArguments(e,p){return !p?.item_id&&e?.data?.next_cursor?{...p,cursor:e.data.next_cursor}:null;}
function itemDetail(x,parent){
 const s=x.source,p=x.portfolio,b=p.pin,f=s.facts;
 para(parent,`Saved item ${x.item_id}; entity ${p.entity_id}; immutable event ${s.event_id}, revision ${s.revision}. ${x.review?"This exact revision is reviewed":"This revision is unreviewed"}.`);
 para(parent,`Source facts · ${f.publisher}. ${f.published_at===null?"Publication unavailable (provider overview)":`Published ${f.published_at}`}. Source cutoff ${x.source_cutoff_at}; retained revision expires ${s.expires_at}.`);
 para(parent,f.kind==="news"?f.title:f.company_name);para(parent,f.kind==="news"?f.summary:f.description);
 table(parent,"Deterministic portfolio facts",["Measure","Exact saved value"],[
 ["Effective exposure",moneyText(p.effective_exposure)],["Availability / reason",`${p.availability} / ${p.reason??"None"}; upstream ${p.upstream_reason??"None"}`],["Quality / origin / bound",`${p.quality} / ${p.origin} / ${p.bound}`],["Confidence",exact(p.confidence)],["Coverage",`Company complete ${p.company_coverage_complete}; unresolved positive below quantum ${p.positive_unresolved_below_quantum}`],["Method",`${b.method} ${b.method_version}; ${b.numerical_profile}`],["Valuation / source cutoff",`${b.valuation_at} / ${b.source_cutoff_at}`],["Saved X-ray",`${b.run_id}; snapshot ${b.snapshot_id}; input ${b.input_digest}; result ${b.result_digest}`],["Canonical fact digest",p.canonical_facts_digest]]);
 const proof=disclosure(parent,"Source citations, original clocks and retained proof");
 table(proof,"Every returned source citation",["Citation / source version","Provider event / digest","Original clocks","License / attribution"],s.citations.map(c=>[`${c.citation_id}; ${c.source.version_id}`,`${c.source.provider} / ${c.provider_event_key}; source ${c.source.content_digest}; citation ${c.content_digest}; facts ${c.facts_digest}`,`Observed ${c.source.observed_at}; first known ${c.source.first_known_at}; cutoff ${c.source.source_cutoff_at}; retained ${c.source.retained_at}; expires ${c.source.expires_at}`,`${c.source.license_version_id}; ${c.source.license.attribution}; synthetic ${c.source.synthetic}`]));
 para(proof,`Event digest ${s.content_digest}. Sources: ${p.source_reference_ids.join(", ")||"None"}; omitted ${p.source_references_omitted}. Metric sources: ${p.metric_source_reference_ids.join(", ")||"None"}; omitted ${p.metric_sources_omitted}. Paths: ${p.path_keys.join(", ")||"None"}; omitted ${p.paths_omitted}. Warnings omitted ${p.warnings_omitted}.`);
 for(const w of p.warnings)para(proof,`${w.code}; reason ${w.reason??"None"}; source references ${w.source_reference_ids.join(", ")||"None"} (${w.source_references_omitted} omitted); paths ${w.path_keys.join(", ")||"None"} (${w.paths_omitted} omitted).`);
 const notes=disclosure(parent,`Owner revisions (${x.owner_revisions.length} shown; ${x.owner_revisions_omitted} omitted)`);
 for(const n of x.owner_revisions){para(notes,`Owner note ${n.note_id}, revision ${n.revision} (${n.revision_id}), ${n.created_at}; digest ${n.content_digest}.`);for(const key of noteFields)para(notes,`${key}: ${n.content[key]}`);for(const c of n.content.citations)para(notes,`Citation ${c.citation_id}; source ${c.source_version_id}; source digest ${c.source_version_digest}; citation digest ${c.citation_digest}.`);}
 para(parent,`Optional synthesis unavailable: ${x.synthesis.reason}. Source text and notes are untrusted content and do not change portfolio facts.`);
}
function renderData(e,parent){const d=e.data;if(selection.item_id){itemDetail(d,parent);return;}
 para(parent,`${d.items.length} of ${d.total} authorized items; ${d.unknown_exposure_total} have unknown exposure. Ranking keeps known lower bounds explicit. ${d.next_cursor?"More items available.":"End of this selection."}`);
 table(parent,"Research page",["Source item","Exact exposure / bound","Review / publication"],d.items.map(x=>[x.source.facts.kind==="news"?x.source.facts.title:x.source.facts.company_name,`${moneyText(x.portfolio.effective_exposure)} / ${x.portfolio.bound}`,`${x.review?"Reviewed":"Unreviewed"}; ${x.source.facts.published_at??"Publication unavailable"}`]));
 if(d.items.length===0)return;const label=document.createElement("label"),select=document.createElement("select"),detail=document.createElement("section");label.htmlFor="research-item-select";label.textContent="Inspect a complete item on this page";select.id="research-item-select";d.items.forEach((x,i)=>{const o=document.createElement("option");o.value=String(i);o.textContent=x.source.facts.kind==="news"?x.source.facts.title:x.source.facts.company_name;select.append(o);});parent.append(label,select,detail);const change=()=>{detail.replaceChildren();itemDetail(d.items[select.selectedIndex],detail);};select.addEventListener("change",change);change();
}
""".strip()
RESEARCH_WIDGET_HTML = read_widget(
    title="Portfolio research",
    introduction="Source facts, deterministic portfolio exposure and your revisions stay separate. Research text is displayed as inert content. Exact ratios remain decimal strings.",
    name="portfolio-research",
    script=_SCRIPT,
)
