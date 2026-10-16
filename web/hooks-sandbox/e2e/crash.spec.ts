/**
 * Runs only in the Chromium headless shell, where a worker that exhausts its heap takes
 * the whole tab down (the full browser terminates just the worker; see containment.spec).
 * Containment then means: no data lost, and on reload the hook is not run again. A
 * non-critical hook is switched off for the session; a flow-critical one gets its retry
 * prompt and, if it crashes again, the session ends `hook-failed`.
 */

import { expect, test, type Page } from '@playwright/test';
import { egressLog, openRuntime, resetEgress } from './util.ts';

test.beforeEach(async ({ request }) => resetEgress(request));
test.afterEach(async ({ request }) => {
	expect(await egressLog(request)).toEqual([]);
});

const BOMB = `var a = []; while (true) a.push(new Array(1e6).fill(Math.random()));`;

async function crashes(page: Page, run: () => Promise<unknown>): Promise<boolean> {
	const crashed = new Promise<boolean>((r) => page.once('crash', () => r(true)));
	const done = run().then(
		() => false,
		() => true
	);
	return Promise.race([crashed, done.then(async (failed) => (failed ? crashed : false))]);
}

test('a non-critical hook that crashes the tab is recorded as failed and switched off', async ({ page, context }) => {
	const src = `osp.on('onPageShown', function (ctx, data, act) { if (data.page === 'p2') { ${BOMB} } });`;
	let frame = await openRuntime(page);
	await frame.evaluate(async (src) => {
		window.H.clearSnapshot();
		const { runner } = window.H.make(src, { persist: true, manifest: { handlers: { onPageShown: { reads: [], writes: [], timeoutMs: 5000 } } } });
		await runner.begin();
		await runner.answer('q1', 4);
	}, src);
	const crashed = await crashes(page, () =>
		frame.evaluate(async (src) => {
			const { runner } = window.H.make(src, {
				persist: true,
				restore: true,
				manifest: { handlers: { onPageShown: { reads: [], writes: [], timeoutMs: 5000 } } }
			});
			await runner.next();
		}, src)
	);
	expect(crashed).toBe(true);

	const page2 = await context.newPage(); // the participant reloads
	frame = await openRuntime(page2);
	const r = await frame.evaluate(async (src) => {
		const marker = window.H.inflight();
		const { runner } = window.H.make(src, {
			persist: true,
			restore: true,
			manifest: { handlers: { onPageShown: { reads: [], writes: [], timeoutMs: 5000 } } }
		});
		const resumed = await runner.resume();
		const again = await runner.fire('onPageShown', { page: 'p2' });
		const evs = window.H.hookEvents(runner.state);
		return {
			marker,
			resumed,
			again,
			page: window.H.engine.view(runner.state).page,
			answers: window.H.engine.result(runner.state).answers.q1,
			crashedRecorded: evs.filter((e) => (e.value as { error?: string } | null)?.error === 'crashed').map((e) => e.effect.event)
		};
	}, src);
	expect(r.marker).toMatchObject({ event: 'onPageShown' });
	expect(r.page).toBe('p2');
	expect(r.answers).toEqual({ state: 'answered', value: 4 }); // nothing lost
	expect(r.crashedRecorded).toEqual(['onPageShown']);
	expect(r.again).toEqual({ outcome: 'skipped' }); // never run again this session
	expect(r.resumed).toMatchObject({ outcome: 'skipped' });
});

test('a flow-critical hook that crashes twice ends the session hook-failed, never another path', async ({ page, context }) => {
	const src = `osp.on('onPageNext', function (ctx, data, act) { ${BOMB} });`;
	let frame = await openRuntime(page);
	await frame.evaluate(() => window.H.clearSnapshot());
	const crashed1 = await crashes(page, () =>
		frame.evaluate(async (src) => {
			const { runner } = window.H.make(src, { persist: true, manifest: { handlers: { onPageNext: { reads: [], writes: ['hv_score'], timeoutMs: 5000 } } } });
			await runner.begin();
			await runner.next();
		}, src)
	);
	expect(crashed1).toBe(true);

	const page2 = await context.newPage();
	frame = await openRuntime(page2);
	const first = await frame.evaluate(async (src) => {
		const { runner } = window.H.make(src, { persist: true, restore: true, manifest: { handlers: { onPageNext: { reads: [], writes: ['hv_score'], timeoutMs: 5000 } } } });
		return runner.resume();
	}, src);
	expect(first).toEqual({ outcome: 'retry', event: 'onPageNext', error: 'crashed' });

	// The participant presses "Try again": it crashes again.
	const crashed2 = await crashes(page2, () =>
		frame.evaluate(async (src) => {
			const { runner } = window.H.make(src, { persist: true, restore: true, manifest: { handlers: { onPageNext: { reads: [], writes: ['hv_score'], timeoutMs: 5000 } } } });
			await runner.resume(); // records nothing new: no marker
			await runner.next(); // the pending retry is reported…
			await runner.retry(); // …and run
		}, src)
	);
	expect(crashed2).toBe(true);

	const page3 = await context.newPage();
	frame = await openRuntime(page3);
	const last = await frame.evaluate(async (src) => {
		const { runner } = window.H.make(src, { persist: true, restore: true, manifest: { handlers: { onPageNext: { reads: [], writes: ['hv_score'], timeoutMs: 5000 } } } });
		const resumed = await runner.resume();
		return { resumed, end: runner.state.data.ended?.outcome ?? null, page: window.H.engine.view(runner.state).status };
	}, src);
	expect(last.resumed).toEqual({ outcome: 'hook-failed', error: 'crashed' });
	expect(last.end).toBe('hook-failed');
});
