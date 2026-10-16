/* No imports: the e2e vite config loads this file directly to hash it. */

/**
 * The iframe's only script. It accepts one init message from its parent carrying exactly one
 * MessagePort and the worker source, starts the worker from a blob, hands it the port, and
 * then ignores everything else (including anything the worker posts to it).
 */
export const FRAME_SCRIPT = `(function(){"use strict";var done=false;addEventListener("message",function(e){if(done||e.source!==parent)return;var d=e.data,p=e.ports;if(!d||d.osp!=="hooks-init"||typeof d.workerSource!=="string"||!p||p.length!==1)return;done=true;var u=URL.createObjectURL(new Blob([d.workerSource],{type:"text/javascript"}));var w=new Worker(u);setTimeout(function(){URL.revokeObjectURL(u)},5000);w.onmessage=null;w.onmessageerror=null;w.onerror=function(ev){ev.preventDefault()};w.postMessage({port:p[0]},[p[0]])})})();`;

/** The iframe's CSP: nothing but the frame script (by hash) and one blob worker. */
export function frameCsp(scriptHash: string): string {
	return `default-src 'none'; script-src ${scriptHash}; worker-src blob:; base-uri 'none'; form-action 'none'`;
}

/**
 * The sandbox document: used as the iframe's `srcdoc`, or served as a static file from a
 * separate sandbox origin (`HookHostOptions.frameUrl`).
 */
export function frameDocument(scriptHash: string): string {
	return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${frameCsp(scriptHash)}"><meta name="referrer" content="no-referrer"></head><body><script>${FRAME_SCRIPT}</script></body></html>`;
}
