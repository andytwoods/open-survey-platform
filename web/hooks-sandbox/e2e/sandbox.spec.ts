/**
 * The sandbox itself: iframe flags and CSP, the port-only channel, determinism inside the
 * worker, and a normal session running through real hooks.
 */

import { expect, test } from '@playwright/test';
import { egressLog, openRuntime, resetEgress } from './util.ts';

test.beforeEach(async ({ request }) => resetEgress(request));
test.afterEach(async ({ request }) => {
	expect(await egressLog(request)).toEqual([]);
});

test('iframe is sandboxed allow-scripts only, opaque, with a default-src none CSP', async ({ page }) => {
	const frame = await openRuntime(page);
	const info = await frame.evaluate(async () => {
		const { host, runner } = window.H.make('osp.on("onStart", function(){});');
		await runner.begin();
		const f = host.iframe!;
		let docAccess: string;
		try {
			docAccess = f.contentDocument === null ? 'null' : 'accessible';
		} catch (e) {
			docAccess = `threw ${(e as Error).name}`;
		}
		return {
			sandbox: f.getAttribute('sandbox'),
			srcdoc: f.srcdoc,
			src: f.getAttribute('src'),
			docAccess,
			spawns: host.stats.spawns
		};
	});
	expect(info.sandbox).toBe('allow-scripts');
	expect(info.src).toBeNull();
	expect(info.srcdoc).toContain(`content="default-src 'none'; script-src 'sha256-`);
	expect(info.srcdoc).not.toContain('allow-same-origin');
	expect(info.docAccess).toBe('null');
	expect(info.spawns).toBe(1);
});

test('a session runs through real hooks: variables drive show-if and branches', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async () => {
		const src = `
			osp.on('onPageInit', function (ctx, data, act) { if (data.page === 'p2') act.setVariable('hv_flag', true); });
			osp.on('onPageNext', function (ctx, data, act) {
				if (data.page === 'p2') act.setVariable('hv_score', (ctx.results.q1 && ctx.results.q1.value || 0) * 3);
			});`;
		const { runner } = window.H.make(src);
		await runner.begin();
		await runner.answer('q1', 5);
		const a = await runner.next();
		const p2 = window.H.engine.view(runner.state).items.map((i) => i.id);
		const b = await runner.next();
		const page = window.H.engine.view(runner.state).page;
		const replayed = window.H.engine.replay(runner.plan, runner.state.data.events);
		return {
			a,
			p2,
			b,
			page,
			replayOk: window.H.engine.isState(replayed) && window.H.engine.canonicalJson(replayed.data) === window.H.engine.canonicalJson(runner.state.data)
		};
	});
	expect(r).toEqual({ a: { outcome: 'advanced' }, p2: ['n2', 'q5'], b: { outcome: 'advanced' }, page: 'p3', replayOk: true });
});

test('Math.random, Date and performance.now inside the worker are ctx.random/ctx.now, seeded and recorded', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async () => {
		const src = `
			osp.on('onPageShown', function (ctx, data, act) {
				var a = Math.random(), b = Math.random();
				act.addParadata('r1', a); act.addParadata('r2', b);
				act.addParadata('now', Date.now()); act.addParadata('newDate', new Date().getTime());
				act.addParadata('ctxNow', ctx.now()); act.addParadata('perf', performance.now());
				act.addParadata('dateStr', typeof Date());
				var buf = new Uint8Array(4); crypto.getRandomValues(buf); act.addParadata('crypto', buf.join(','));
			});`;
		const one = window.H.make(src);
		await one.runner.begin();
		const two = window.H.make(src);
		await two.runner.begin();
		const pd = (x: typeof one) => Object.fromEntries(x.runner.state.data.hooks!.paradata.map((p) => [p.key, p.value]));
		const ev = window.H.hookEvents(one.runner.state).find((e) => e.effect.event === 'onPageShown')!;
		return { a: pd(one), b: pd(two), recorded: ev.value as { seed: number; now: number } };
	});
	expect(r.a).toEqual(r.b); // same session seed + invocation id → same values in a fresh sandbox
	expect(r.a.r1).not.toBe(r.a.r2);
	expect(r.a.now).toBe(r.recorded.now);
	expect(r.a.newDate).toBe(r.recorded.now);
	expect(r.a.ctxNow).toBe(r.recorded.now);
	expect(r.a.perf).toBe(0);
	expect(r.a.dateStr).toBe('string');
	expect(typeof r.recorded.seed).toBe('number');
});
