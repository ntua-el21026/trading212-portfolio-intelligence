# ruff: noqa: E501
"""Offline presentation helpers used only by the three closed Phase 3 read widgets."""

import base64
import hashlib
from html import escape

_STYLE = """
:root{color-scheme:light dark;font:16px system-ui,sans-serif;font-variant-numeric:tabular-nums}*{box-sizing:border-box}body{margin:0;padding:16px}main{max-width:1080px;margin:auto;min-width:0}h1{font-size:1.5rem}h2{font-size:1.2rem}p,li,td,th,summary{overflow-wrap:anywhere}p.prose{white-space:pre-wrap}button,select,summary{font:inherit;min-height:44px}button,select{padding:8px;max-width:100%}.actions{display:flex;gap:8px;flex-wrap:wrap}.table-wrap{width:100%;overflow:auto;max-height:480px;margin:12px 0}table{border-collapse:collapse;width:100%;min-width:680px;table-layout:fixed}th,td{padding:9px;text-align:left;vertical-align:top;border-bottom:1px solid #888}caption{text-align:left;font-weight:600;padding:12px 0}:focus-visible{outline:3px solid #1879bd;outline-offset:3px}[hidden]{display:none!important}@media(max-width:480px){body{padding:10px}td,th{padding:6px}}@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
""".strip()
_HELPERS = r"""
const el=id=>document.getElementById(id),record=x=>x!==null&&typeof x==="object"&&!Array.isArray(x);
const str=(x,max=4096)=>typeof x==="string"&&x.length<=max;
const uuid=x=>typeof x==="string"&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(x);
const inputUUID=x=>typeof x==="string"&&uuid(x.toLowerCase())?x.toLowerCase():null;
const opaque=x=>typeof x==="string"&&/^[A-Za-z0-9._:-]{1,255}$/.test(x);
const digest=x=>typeof x==="string"&&/^[0-9a-f]{64}$/.test(x);
const decimal=x=>typeof x==="string"&&x.length<=1024&&/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(x);
const currency=x=>typeof x==="string"&&/^[A-Z]{3}$/.test(x);
function normalizeInstant(x){
 if(typeof x!=="string")return null;
 const m=/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|([+-])(\d{2}):(\d{2}))$/.exec(x);
 if(!m||Number(m[1].slice(0,4))<1)return null;
 const local=Date.parse(m[1]+"Z");
 if(!Number.isFinite(local)||new Date(local).toISOString().slice(0,19)!==m[1])return null;
 const hours=Number(m[5]??0),minutes=Number(m[6]??0);
 if(hours>23||minutes>59)return null;
 const offset=(hours*60+minutes)*60000*(m[4]==="-"?-1:1);
 const utc=new Date(local-offset).toISOString().slice(0,19);
 if(!/^\d{4}-/.test(utc)||Number(utc.slice(0,4))<1)return null;
 const fraction=(m[2]??"").replace(/0+$/,"");
 return utc+(fraction?"."+fraction:"")+"Z";
}
const instant=x=>normalizeInstant(x)!==null;
const sameInstant=(a,b)=>{const normalized=normalizeInstant(a);return normalized!==null&&normalized===normalizeInstant(b);};
const count=(x,max=2147483647)=>Number.isSafeInteger(x)&&x>=0&&x<=max;
const array=(x,max,check=record)=>Array.isArray(x)&&x.length<=max&&x.every(y=>check(y));
const money=x=>record(x)&&decimal(x.amount)&&currency(x.currency);
const moneyText=x=>x===null?"Unavailable":`${x.amount} ${x.currency}`;
const exact=x=>x===null?"Unavailable":x;
const quality=x=>["fresh","stale","partial","estimated","unreconciled","failed"].includes(x);
const set=(id,value)=>{el(id).textContent=value;};
function para(parent,text){const p=document.createElement("p");p.className="prose";p.textContent=text;parent.append(p);return p;}
function table(parent,title,headers,rows){const wrap=document.createElement("div");wrap.className="table-wrap";wrap.tabIndex=0;wrap.setAttribute("role","region");wrap.setAttribute("aria-label",title);const t=document.createElement("table"),caption=document.createElement("caption"),head=document.createElement("thead"),body=document.createElement("tbody"),tr=document.createElement("tr");caption.textContent=title;t.append(caption);for(const label of headers){const th=document.createElement("th");th.scope="col";th.textContent=label;tr.append(th);}head.append(tr);t.append(head);for(const values of rows){const r=document.createElement("tr");values.forEach((value,i)=>{const c=document.createElement(i===0?"th":"td");if(i===0)c.scope="row";c.textContent=value;r.append(c);});body.append(r);}t.append(body);wrap.append(t);parent.append(wrap);}
function disclosure(parent,title){const d=document.createElement("details"),s=document.createElement("summary");s.textContent=title;d.append(s);parent.append(d);return d;}
let selection=null,current=null,generation=0,counter=0,pending=null,blocked=true,disposed=false,serverTools=false;
function available(){return serverTools||typeof window.openai?.callTool==="function";}
function buttons(){el("refresh").disabled=disposed||blocked||!selection||!!pending||!available();el("next").disabled=el("refresh").disabled||!nextArguments(current,selection);set("bridge",available()?"Reads use the host's authorized tools. Local controls do not save account data.":"Ask the conversation to read this view or its next page; widget tool calls are unavailable in this host.");}
function clear(message){current=null;el("content").replaceChildren();el("content").hidden=true;set("status",message);buttons();}
function invalidate(message){generation++;if(pending)clearTimeout(pending.timer);pending=null;selection=null;blocked=true;clear(message);}
function input(args,partial){invalidate("Waiting for an authorized result. Input arguments are not financial values.");if(!partial){selection=parseInput(args);blocked=selection===null;}buttons();}
function show(result,expected=selection){
 if(disposed||blocked||!expected)return;
 clear("Reading the authorized result.");
 try{if(!record(result)||new TextEncoder().encode(JSON.stringify(result)).byteLength>2097152)throw Error();const e=result.structuredContent??result.structured_content??result;
 if(record(e)&&record(e.error)&&e.data===null){set("status","This authorized read is unavailable. Retry or restart the selection in the conversation.");buttons();return;}
 if(!validateResult(e,expected,result))throw Error();current=e;selection=expected;renderData(e,el("content"));el("content").hidden=false;set("status","Authorized result loaded. Exact values and source distinctions are preserved.");buttons();
 }catch(_){clear("Result unavailable or inconsistent with the selected account, source and contract.");}}
function finish(id,result){if(!pending||pending.id!==id||pending.generation!==generation||disposed)return;const expected=pending.expected;clearTimeout(pending.timer);pending=null;show(result,expected);}
function read(next=false){if(blocked||!selection||pending||disposed||!available())return;const args=next?nextArguments(current,selection):selection;if(!args)return;const expected={...args},id=`${WIDGET_NAME}-read-${++counter}`;clear("Loading an authorized read.");pending={id,generation,expected,timer:setTimeout(()=>finish(id,{error:true}),15000)};buttons();const name=toolName(args),argumentsValue=toolArguments(args);if(serverTools)window.parent.postMessage({jsonrpc:"2.0",id,method:"tools/call",params:{name,arguments:argumentsValue}},"*");else Promise.resolve().then(()=>window.openai.callTool(name,argumentsValue)).then(value=>finish(id,value),()=>finish(id,{error:true}));}
function message(event){const d=event.data;if(disposed||event.source!==window.parent||!record(d)||d.jsonrpc!=="2.0")return;
 if(d.id===`${WIDGET_NAME}-initialize`&&d.result?.protocolVersion==="2026-01-26"){serverTools=record(d.result.hostCapabilities?.serverTools);window.parent.postMessage({jsonrpc:"2.0",method:"ui/notifications/initialized",params:{}},"*");buttons();return;}
 if(d.method==="ui/resource-teardown"&&d.id!==undefined){invalidate("View closed.");disposed=true;buttons();window.removeEventListener("message",message);window.removeEventListener("openai:set_globals",legacy);window.parent.postMessage({jsonrpc:"2.0",id:d.id,result:{}},"*");return;}
 if(d.id!==undefined){if(!d.method)finish(d.id,d.error?{error:true}:d.result);return;}
 if(d.method==="ui/notifications/tool-input")input(d.params?.arguments,false);
 else if(d.method==="ui/notifications/tool-input-partial")input(d.params?.arguments,true);
 else if(d.method==="ui/notifications/tool-cancelled")invalidate("Read cancelled; no financial content is displayed.");
 else if(d.method==="ui/notifications/tool-result"&&!pending)show(d.params);
}
function legacy(event){if(disposed||serverTools)return;const g=event.detail?.globals;if(!record(g))return;if(Object.prototype.hasOwnProperty.call(g,"toolInput"))input(g.toolInput,false);if(!pending&&Object.prototype.hasOwnProperty.call(g,"toolOutput"))show(g.toolOutput);}
el("refresh").addEventListener("click",()=>read());el("next").addEventListener("click",()=>read(true));window.addEventListener("message",message);window.addEventListener("openai:set_globals",legacy);clear("Waiting for an authorized result.");window.parent.postMessage({jsonrpc:"2.0",id:`${WIDGET_NAME}-initialize`,method:"ui/initialize",params:{protocolVersion:"2026-01-26",appInfo:{name:WIDGET_NAME,version:"1.0.0"},appCapabilities:{availableDisplayModes:["inline"]}}},"*");if(window.openai&&Object.prototype.hasOwnProperty.call(window.openai,"toolInput"))input(window.openai.toolInput,false);if(window.openai?.toolOutput)show(window.openai.toolOutput);
""".strip()


def read_widget(*, title: str, introduction: str, name: str, script: str) -> str:
    # Arguments are compile-time strings from three fixed internal callers.
    js = (
        '(() => {"use strict";const WIDGET_NAME="'
        + name
        + '";\n'
        + script
        + "\n"
        + _HELPERS
        + "\n})();"
    )

    def token(value: str) -> str:
        return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode()

    csp = f"default-src 'none'; script-src 'sha256-{token(js)}'; style-src 'sha256-{token(_STYLE)}'; img-src 'none'; connect-src 'none'; font-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    body = f'<main><h1>{escape(title)}</h1><p>{escape(introduction)}</p><p id="status" role="status" aria-live="polite"></p><div class="actions"><button id="refresh" disabled>Refresh authorized view</button><button id="next" disabled>Next page</button></div><p id="bridge"></p><section id="content" hidden></section></main>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        + f'<meta http-equiv="Content-Security-Policy" content="{csp}"><title>{escape(title)}</title><style>{_STYLE}</style></head><body>{body}<script>{js}</script></body></html>'
    )
