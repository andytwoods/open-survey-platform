/**
 * Ordered effects through the real sandbox: stale results, a refresh during a hook, and a
 * duplicate onBeforeSubmit.
 */

import { expect, test } from '@playwright/test';
import { egressLog, openRuntime, resetEgress } from './util.ts';

test.beforeEach(async ({ request }) => resetEgress(request));
test.afterEach(async ({ request }) => {
	expect(await egressLog(request)).toEqual([]);
});

test('a result that arrives after the state moved on is stale: refused, logged, never applied', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async () => {
		const src = `osp.on('onAnswer', function (ctx, data, act) {
			return new Promise(function (res) { setTimeout(function () { act.setVariable('hv_note', 'late ' + data.value); res(); }, 300); });
		});`;
		const { runner } = window.H.make(src);
		await runner.begin();
		const slow = runner.answer('q1', 1);
		await window.H.sleep(50);
		// The participant keeps typing while the hook runs.
		runner.setState(window.H.engine.answer(runner.state, 'q2', 'typing'));
		const outcome = await slow;
		const last = window.H.hookEvents(runner.state).at(-1)!;
		return { outcome, rejected: last.rejected ?? null, note: runner.state.data.hooks?.vars.hv_note ?? null };
	});
	expect(r).toEqual({ outcome: { outcome: 'stale' }, rejected: 'stale', note: null });
});

test('refresh during a hook: the lost call is re-run once on resume, nothing is duplicated', async ({ page }) => {
	const src = `
		osp.on('onPageInit', function (ctx, data, act) {
			if (data.page !== 'p2') return;
			return new Promise(function (res) { setTimeout(function () { act.setVariable('hv_flag', true); res(); }, 1500); });
		});
		osp.on('onResume', function (ctx, data, act) { act.addParadata('resumed', true); });`;
	let frame = await openRuntime(page);
	const before = await frame.evaluate(async (src) => {
		window.H.clearSnapshot();
		const { runner } = window.H.make(src, { persist: true });
		await runner.begin();
		await runner.answer('q1', 5);
		void runner.next(); // reaches p2, then its slow onPageInit starts
		while (window.H.engine.view(runner.state).page !== 'p2' || !window.H.inflight()) await window.H.sleep(10);
		return { page: window.H.engine.view(runner.state).page, inflight: window.H.inflight() };
	}, src);
	expect(before.page).toBe('p2');
	expect(before.inflight).toMatchObject({ event: 'onPageInit' });

	await page.reload(); // mid-hook
	frame = await openRuntime(page);
	const after = await frame.evaluate(async (src) => {
		const marker = window.H.inflight(); // cleared by pagehide: a clean unload, not a crash
		const { runner } = window.H.make(src, { persist: true, restore: true });
		const resumed = await runner.resume();
		const evs = window.H.hookEvents(runner.state).filter((e) => e.rejected === undefined);
		const replayed = window.H.engine.replay(runner.plan, runner.state.data.events);
		return {
			marker,
			resumed,
			page: window.H.engine.view(runner.state).page,
			items: window.H.engine.view(runner.state).items.map((i) => i.id),
			initsOnP2: evs.filter((e) => e.effect.event === 'onPageInit').length,
			resumes: evs.filter((e) => e.effect.event === 'onResume').length,
			replayOk: window.H.engine.isState(replayed) && window.H.engine.canonicalJson(replayed.data) === window.H.engine.canonicalJson(runner.state.data)
		};
	}, src);
	expect(after.marker).toBeNull();
	expect(after.resumed).toMatchObject({ outcome: 'skipped' }); // onPageShown is not declared here
	expect(after.page).toBe('p2');
	expect(after.items).toEqual(['n2', 'q5']); // the re-run hook set hv_flag
	expect(after.initsOnP2).toBe(2); // p1's and p2's: exactly one each
	expect(after.resumes).toBe(1);
	expect(after.replayOk).toBe(true);
});

test('duplicate onBeforeSubmit (double-clicked Next, repeated submit) runs and records once', async ({ page }) => {
	const frame = await openRuntime(page);
	const r = await frame.evaluate(async () => {
		const src = `osp.on('onBeforeSubmit', function (ctx, data, act) {
			return new Promise(function (res) { setTimeout(function () { act.addParadata('submitted', true); res(); }, 200); });
		});`;
		const { runner } = window.H.make(src);
		await runner.begin();
		await runner.next();
		await runner.next();
		const outcomes = await Promise.all([runner.next(), runner.next(), runner.beforeSubmit(), runner.beforeSubmit()]);
		await runner.beforeSubmit();
		const evs = window.H.hookEvents(runner.state).filter((e) => e.effect.event === 'onBeforeSubmit');
		return {
			outcomes: outcomes.map((o) => o.outcome),
			recorded: evs.length,
			paradata: runner.state.data.hooks?.paradata.length,
			ended: runner.state.data.ended?.outcome
		};
	});
	expect(r.recorded).toBe(1);
	expect(r.paradata).toBe(1);
	expect(r.ended).toBe('complete');
});
