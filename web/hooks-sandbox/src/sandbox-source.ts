/**
 * The code that runs inside the sandbox, as strings (runtime-design.md §7a "Where it runs").
 *
 *   host page ──(iframe sandbox="allow-scripts", srcdoc, CSP default-src 'none')──▶ FRAME_SCRIPT
 *   FRAME_SCRIPT ──(blob: dedicated worker)──▶ WORKER_BOOTSTRAP + researcher source
 *   host ◀──── one transferred MessagePort, JSON strings only ────▶ worker
 *
 * Nothing in here is trusted by the host: the host validates every message. The bootstrap
 * is convenience plus defence in depth (deterministic time and randomness, egress APIs
 * removed); the CSP and the iframe sandbox are what block egress, and the host's deadlines
 * are what bound CPU and memory.
 */

import { sha256, utf8 } from '@osp/engine';
import { HOOK_EVENTS } from './manifest.ts';

/**
 * The iframe's only script. It accepts one init message from its parent carrying exactly one
 * MessagePort and the worker source, starts the worker from a blob, hands it the port, and
 * then ignores everything else (including anything the worker posts to it).
 */
export const FRAME_SCRIPT = `(function(){"use strict";var done=false;addEventListener("message",function(e){if(done||e.source!==parent)return;var d=e.data,p=e.ports;if(!d||d.osp!=="hooks-init"||typeof d.workerSource!=="string"||!p||p.length!==1)return;done=true;var u=URL.createObjectURL(new Blob([d.workerSource],{type:"text/javascript"}));var w=new Worker(u);setTimeout(function(){URL.revokeObjectURL(u)},5000);w.onmessage=null;w.onmessageerror=null;w.onerror=function(ev){ev.preventDefault()};w.postMessage({port:p[0]},[p[0]])})})();`;

function base64(bytes: Uint8Array): string {
	const abc = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
	let out = '';
	for (let i = 0; i < bytes.length; i += 3) {
		const a = bytes[i]!;
		const b = bytes[i + 1];
		const c = bytes[i + 2];
		out += abc[a >> 2]! + abc[((a & 3) << 4) | ((b ?? 0) >> 4)]!;
		out += b === undefined ? '=' : abc[((b & 15) << 2) | ((c ?? 0) >> 6)]!;
		out += c === undefined ? '=' : abc[c & 63]!;
	}
	return out;
}

/**
 * CSP source for FRAME_SCRIPT. A srcdoc iframe inherits the host page's CSP as well, so the
 * runtime's own CSP must allow this hash in `script-src` and `blob:` in `worker-src`.
 */
export const FRAME_SCRIPT_HASH = `'sha256-${base64(sha256(utf8(FRAME_SCRIPT)))}'`;

/** The iframe's CSP: nothing but the frame script and one blob worker. */
export const FRAME_CSP = `default-src 'none'; script-src ${FRAME_SCRIPT_HASH}; worker-src blob:; base-uri 'none'; form-action 'none'`;

export const FRAME_SRCDOC = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${FRAME_CSP}"><meta name="referrer" content="no-referrer"></head><body><script>${FRAME_SCRIPT}</script></body></html>`;

/** Globals removed from the worker before researcher code runs (defence in depth). */
export const LOCKED_GLOBALS = [
	'fetch',
	'XMLHttpRequest',
	'WebSocket',
	'WebSocketStream',
	'EventSource',
	'WebTransport',
	'importScripts',
	'Worker',
	'SharedWorker',
	'BroadcastChannel',
	'indexedDB',
	'caches',
	'Request',
	'Response',
	'Headers',
	'Notification',
	'WebAssembly',
	'RTCPeerConnection',
	'RTCDataChannel',
	'FileSystemHandle',
	'StorageManager'
];

/**
 * Worker bootstrap, run before the researcher's source in the same script. Exposes
 * `osp.on(event, handler)`; a handler is called as `handler(ctx, data, act)`, where `act`
 * has the five actions and `ctx.random()`/`ctx.now()` are the seeded/injected ones that
 * `Math.random`, `Date` and `performance.now` also use.
 */
function bootstrap(lockdown: boolean): string {
	return `(function(G){"use strict";
var LOCK=${lockdown ? 'true' : 'false'},EVENTS=${JSON.stringify(HOOK_EVENTS)},LOCKED=${JSON.stringify(LOCKED_GLOBALS)};
var stringify=JSON.stringify,parse=JSON.parse,freeze=Object.freeze,keys=Object.keys,RealDate=Date,MP=G.MessagePort;
var seed=1,nowValue=0,handlers=Object.create(null),port=null;
function rnd(){seed=(seed+0x6D2B79F5)|0;var t=seed;t=Math.imul(t^(t>>>15),t|1);t^=t+Math.imul(t^(t>>>7),t|61);return((t^(t>>>14))>>>0)/4294967296;}
function now(){return nowValue;}
var D=function Date(){if(!new.target)return new RealDate(nowValue).toString();var a=Array.prototype.slice.call(arguments);return a.length?new (Function.prototype.bind.apply(RealDate,[null].concat(a)))():new RealDate(nowValue);};
D.prototype=RealDate.prototype;D.now=now;D.parse=RealDate.parse;D.UTC=RealDate.UTC;
function def(o,k,v){try{Object.defineProperty(o,k,{value:v,writable:false,configurable:false,enumerable:false});}catch(e){try{o[k]=v;}catch(_){}}}
def(G,"Date",D);def(Math,"random",rnd);
if(G.performance){def(G.performance,"now",function(){return 0;});}
if(G.crypto&&G.crypto.getRandomValues){def(G.crypto,"getRandomValues",function(a){for(var i=0;i<a.length;i++)a[i]=Math.floor(rnd()*256);return a;});}
if(G.Intl&&Intl.DateTimeFormat){var F=Intl.DateTimeFormat.prototype,f0=F.format,f1=F.formatToParts;
 def(F,"format",function(d){return f0.call(this,d===undefined?nowValue:d);});
 def(F,"formatToParts",function(d){return f1.call(this,d===undefined?nowValue:d);});}
if(LOCK){for(var i=0;i<LOCKED.length;i++){var n=LOCKED[i];for(var o=G;o&&o!==Object.prototype;o=Object.getPrototypeOf(o)){try{if(Object.prototype.hasOwnProperty.call(o,n))delete o[n];}catch(e){}}def(G,n,undefined);}}
function deepFreeze(x){if(x&&typeof x==="object"&&!Object.isFrozen(x)){var k=keys(x);for(var i=0;i<k.length;i++)deepFreeze(x[k[i]]);freeze(x);}return x;}
def(G,"osp",freeze({on:function(name,fn){if(EVENTS.indexOf(name)>=0&&typeof fn==="function")handlers[name]=fn;}}));
function send(o){var s;try{s=stringify(o);}catch(e){s=stringify({t:"result",id:o.id,ok:false,actions:[],error:"unserialisable"});}port.postMessage(s);}
function run(m){
 seed=(m.seed|0)||1;nowValue=+m.now||0;
 var actions=[],open=true;
 function add(a){if(open)actions.push(a);}
 var act=freeze({
  setVariable:function(id,value){add({type:"setVariable",id:id,value:value});},
  addParadata:function(key,value){add({type:"addParadata",key:key,value:value});},
  rejectPage:function(o){o=o||{};add({type:"rejectPage",itemId:o.itemId===undefined?null:o.itemId,message:o.message});},
  setEndRedirect:function(templateId,params){add({type:"setEndRedirect",templateId:templateId,params:params});},
  postToParent:function(type,payload){add({type:"postToParent",messageType:type,payload:payload});}
 });
 var ctx=m.ctx||{};ctx.random=rnd;ctx.now=now;deepFreeze(ctx);deepFreeze(m.data);
 function done(ok,err){if(!open)return;open=false;var out;try{out=parse(stringify(actions));}catch(e){ok=false;err="unserialisable";out=[];}send({t:"result",id:m.id,ok:ok,actions:ok?out:[],error:ok?undefined:String(err&&err.name||err||"error").slice(0,80)});}
 var h=handlers[m.event];
 if(!h){done(false,"no-handler");return;}
 try{var r=h(ctx,m.data,act);if(r&&typeof r.then==="function"){r.then(function(){done(true);},function(e){done(false,e);});}else done(true);}catch(e){done(false,e);}
}
G.addEventListener("message",function(e){if(port)return;var p=e.data&&e.data.port;if(!(p instanceof MP))return;port=p;port.onmessage=function(ev){var m;if(typeof ev.data!=="string")return;try{m=parse(ev.data);}catch(_){return;}if(m&&m.t==="invoke")run(m);};send({t:"ready"});});
})(self);
`;
}

/** The worker script: bootstrap, then the researcher's source in its own block. */
export function workerSource(source: string, opts: { lockdown?: boolean } = {}): string {
	return `${bootstrap(opts.lockdown !== false)}\n;{\n${source}\n}\n`;
}
