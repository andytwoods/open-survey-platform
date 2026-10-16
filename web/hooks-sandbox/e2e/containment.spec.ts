/**
 * Forged port messages, floods, infinite loops and huge allocations: each is detected by the
 * host from outside, the sandbox is killed and respawned, the page stays responsive, and
 * nothing the attacker sent is applied.
 */

import { expect, test } from '@playwright/test';
import { egressLog, openRuntime, resetEgress, responsive } from './util.ts';

test.beforeEach(async ({ request }) => resetEgress(request));
test.afterEach(async ({ request }) => {
	expect(await egressLog(request)).toEqual([]);
});

/** A benign handler on onBack proves the sandbox works again after a kill. */
const HEALTHY = `osp.on('onBack', function (ctx, data, act) { act.addParadata('alive', true); });`;

test('forged port messages: stolen port, guessed ids, non-string and wrong-shape messages are refused', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async (healthy) => {
		// The hook steals the port at top level and forges a result for a guessed invocation.
		const src = `
			var stolen = null;
			self.addEventListener('message', function (e) { if (e.data && e.data.port) stolen = e.data.port; });
			osp.on('onPageShown', function (ctx, data, act) {
				stolen.postMessage(JSON.stringify({ t: 'result', id: 'onPageNext@99', ok: true, actions: [{ type: 'setVariable', id: 'hv_score', value: 99 }] }));
			});
			osp.on('onPageInit', function (ctx, data, act) { stolen.postMessage({ t: 'result', id: 'x', ok: true, actions: [] }); });
			osp.on('onStart', function (ctx, data, act) { stolen.postMessage('{"t":"result","id":"onStart@1","ok":true,"actions":"nope"}'); });
			${healthy}`;
		const { runner, host } = window.H.make(src, {
			manifest: {
				handlers: {
					onStart: { reads: [], writes: ['hv_note'] },
					onPageInit: { reads: [], writes: [] },
					onPageShown: { reads: [], writes: [] },
					onBack: { reads: [], writes: [] }
				}
			}
		});
		const start = await runner.begin(); // three forged replies, three violations
		// A forged message from the page side: window messages are never read by the host.
		window.postMessage({ t: 'result', id: 'onBack@0', ok: true, actions: [{ type: 'setVariable', id: 'hv_score', value: 99 }] }, '*');
		host.iframe?.contentWindow?.postMessage({ osp: 'hooks-init', workerSource: 'fetch("http://127.0.0.1:4418/reinit")' }, '*');
		await runner.answer('q1', 1);
		await runner.next();
		const back = await runner.back();
		return {
			start,
			back,
			violations: host.stats.violations,
			kills: host.stats.kills,
			vars: runner.state.data.hooks?.vars ?? {},
			paradata: runner.state.data.hooks?.paradata ?? [],
			failed: window.H.hookEvents(runner.state).map((e) => [e.effect.event, (e.value as { error?: string } | null)?.error ?? null])
		};
	}, HEALTHY);
	expect(r.violations).toEqual(expect.arrayContaining(['unexpected-message', 'not-a-string', 'bad-result']));
	expect(r.kills).toBeGreaterThanOrEqual(3);
	expect(r.vars).toEqual({}); // hv_score never set by the forged result
	expect(r.failed).toEqual(
		expect.arrayContaining([
			['onStart', 'violation:bad-result'],
			['onPageShown', 'violation:unexpected-message']
		])
	);
	expect(r.back).toMatchObject({ outcome: 'ok' });
	expect(r.paradata).toEqual([{ key: 'alive', value: true, event: 'onBack' }]);
});

test('flooding the port kills the sandbox; the page stays responsive and the next hook works', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async (healthy) => {
		const src = `
			var stolen = null;
			self.addEventListener('message', function (e) { if (e.data && e.data.port) stolen = e.data.port; });
			osp.on('onPageShown', function () { for (var i = 0; i < 200000; i++) stolen.postMessage('{"t":"noise"}'); });
			osp.on('onAnswer', function (ctx, data, act) { for (var i = 0; i < 100000; i++) act.addParadata('k' + i, i); });
			${healthy}`;
		const { runner, host } = window.H.make(src, {
			manifest: { handlers: { onPageShown: { reads: [], writes: [] }, onAnswer: { reads: ['q1'], writes: [] }, onBack: { reads: [], writes: [] } } }
		});
		const flood = await runner.begin();
		const manyActions = await runner.answer('q1', 1);
		await runner.next();
		const back = await runner.back();
		return { flood, manyActions, back, violations: host.stats.violations, paradata: runner.state.data.hooks?.paradata.length ?? 0 };
	}, HEALTHY);
	expect(r.violations[0]).toMatch(/flood|unexpected-message/);
	expect(r.flood).toMatchObject({ outcome: 'failed-open' });
	// 100k actions: refused as a whole (or the message is too large / a flood), never applied.
	expect(r.manyActions).toMatchObject({ outcome: 'failed-open' });
	expect(r.back).toMatchObject({ outcome: 'ok' });
	expect(r.paradata).toBe(1);
	expect(await responsive(frame)).toBeLessThan(1000);
});

test('infinite loops: killed at the deadline from outside, the page never blocks, then respawned', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async (healthy) => {
		const src = `osp.on('onPageShown', function () { while (true) {} });\n${healthy}`;
		const { runner, host } = window.H.make(src, {
			manifest: { handlers: { onPageShown: { reads: [], writes: [], timeoutMs: 500 }, onBack: { reads: [], writes: [] } } }
		});
		// Count main-thread ticks while the worker spins.
		let ticks = 0;
		const iv = setInterval(() => ticks++, 20);
		const t0 = performance.now();
		const loop = await runner.begin();
		const took = performance.now() - t0;
		clearInterval(iv);
		await runner.answer('q1', 1);
		await runner.next();
		const back = await runner.back();
		return { loop, took, ticks, kills: host.stats.kills, spawns: host.stats.spawns, back };
	}, HEALTHY);
	expect(r.loop).toEqual({ outcome: 'failed-open', error: 'timeout:timeout' });
	expect(r.took).toBeGreaterThanOrEqual(450);
	expect(r.took).toBeLessThan(3000);
	expect(r.ticks).toBeGreaterThan(10); // the host page kept running
	expect(r.kills).toBeGreaterThanOrEqual(1);
	expect(r.spawns).toBeGreaterThanOrEqual(2);
	expect(r.back).toMatchObject({ outcome: 'ok' });
});

test('an infinite loop at top level never becomes ready; a flow-critical hook then ends hook-failed', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async () => {
		const src = `while (true) {}\nosp.on('onPageInit', function () {});`;
		const { runner, host } = window.H.make(src, { host: { spawnTimeoutMs: 400, maxSpawns: 3 } });
		const first = await runner.begin();
		const retried = await runner.retry();
		return { first, retried, end: runner.state.data.ended?.outcome ?? null, stats: host.stats };
	});
	expect(r.first).toMatchObject({ outcome: 'retry', event: 'onPageInit' });
	expect(r.retried).toMatchObject({ outcome: 'hook-failed' });
	expect(r.end).toBe('hook-failed');
	expect(r.stats.spawns).toBeLessThanOrEqual(3);
});

test('huge allocations: heap exhaustion, giant buffers and oversized replies are contained', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async (healthy) => {
		const src = `
			osp.on('onPageShown', function () { var a = []; while (true) a.push(new Array(1e6).fill(Math.random())); });
			osp.on('onPageInit', function () { new ArrayBuffer(Math.pow(2, 45)); });
			osp.on('onAnswer', function (ctx, data, act) { act.setVariable('hv_note', 'x'.repeat(5e7)); });
			${healthy}`;
		const { runner, host } = window.H.make(src, {
			manifest: {
				handlers: {
					onPageInit: { reads: [], writes: [] },
					onPageShown: { reads: [], writes: [], timeoutMs: 1500 },
					onAnswer: { reads: ['q1'], writes: ['hv_note'], timeoutMs: 3000 },
					onBack: { reads: [], writes: [] }
				}
			}
		});
		const out: unknown[] = [];
		out.push(await runner.fire('onPageInit', {}));
		out.push(await runner.fire('onPageShown', {}));
		out.push(await runner.answer('q1', 1));
		await runner.next();
		const back = await runner.back();
		return { out, back, stats: host.stats, note: runner.state.data.hooks?.vars.hv_note ?? null };
	}, HEALTHY);
	expect(r.out[0]).toMatchObject({ outcome: 'failed-open', error: expect.stringMatching(/^error:RangeError/) });
	expect(r.out[1]).toMatchObject({ outcome: 'failed-open' }); // timeout (or crash → timeout)
	expect(r.out[2]).toMatchObject({ outcome: 'failed-open' }); // too-large reply, or the worker died
	expect(r.note).toBeNull();
	expect(r.back).toMatchObject({ outcome: 'ok' });
	expect(await responsive(frame)).toBeLessThan(1000);
});
