import {
	canonicalJson,
	isState,
	replay,
	restore,
	result,
	snapshot,
	start,
	toHtml,
	tryResolve,
	view,
	type EngineEvent,
	type HookResolution,
	type State
} from '@osp/engine';
import { describe, expect, it } from 'vitest';
import { HookManifestError, HookRunner, type InflightMarker, type ParentMessage } from '../src/runner.ts';
import { validateActions } from '../src/validate.ts';
import { FakeInvoker, type Handler } from './fake-invoker.ts';
import { PARENT_ORIGIN, hookManifest, hookPlan } from './fixtures.ts';

const plan = hookPlan();

function clock() {
	let t = 1_000;
	return () => (t += 100);
}

function setup(handlers: Record<string, Handler>, opts: { source?: string; manifest?: ReturnType<typeof hookManifest> } = {}) {
	const invoker = new FakeInvoker(handlers);
	const state = start(plan, { sessionSeed: 42, clock: clock(), sessionId: 's1', urlParams: { PROLIFIC_PID: 'abc', secret: 'x' } });
	const sent: Array<[string, ParentMessage]> = [];
	const runner = new HookRunner({
		plan,
		manifest: opts.manifest ?? hookManifest(opts.source ?? 'src'),
		invoker,
		state,
		deliverToParent: (o, m) => sent.push([o, m])
	});
	return { invoker, runner, sent };
}

const hookEvents = (s: State) =>
	s.data.events.filter((e): e is Extract<EngineEvent, { type: 'resolve' }> => e.type === 'resolve' && e.effect.kind === 'hook');

async function toP2(runner: HookRunner) {
	await runner.begin();
	await runner.answer('q1', 5);
	return runner.next();
}

describe('HookRunner + engine', () => {
	it('refuses an invalid manifest', () => {
		const m = hookManifest('x');
		m.handlers.onStart = { reads: [], writes: ['q1'] };
		expect(() => new HookRunner({ plan, manifest: m, invoker: new FakeInvoker({}), state: start(plan, { sessionSeed: 1, clock: clock() }) })).toThrow(
			HookManifestError
		);
	});

	it('hook variables drive show-if and branches; everything is in the event log', async () => {
		const { runner } = setup({
			onPageInit: (ctx, data, act) => {
				if (data.page === 'p2') act.setVariable('hv_flag', true);
			},
			onPageNext: (ctx, data, act) => {
				const q1 = (ctx.results as Record<string, { value: number }>).q1?.value ?? 0;
				if (data.page === 'p2') act.setVariable('hv_score', q1 * 3);
			}
		});
		expect(await toP2(runner)).toEqual({ outcome: 'advanced' });
		expect(view(runner.state).items.map((i) => i.id)).toEqual(['n2', 'q5']); // q5 shown by hv_flag
		expect(await runner.next()).toEqual({ outcome: 'advanced' });
		expect(view(runner.state).page).toBe('p3'); // 5 * 3 >= 10
		const evs = hookEvents(runner.state);
		expect(evs.map((e) => e.effect.event)).toContain('onPageNext');
		expect(evs.every((e) => e.rejected === undefined)).toBe(true);

		// Replay rebuilds the same state from the log alone: no hook code runs.
		const rep = replay(plan, runner.state.data.events);
		expect(isState(rep)).toBe(true);
		expect(canonicalJson((rep as State).data)).toBe(canonicalJson(runner.state.data));
		const snap = restore(plan, snapshot(runner.state));
		expect(isState(snap)).toBe(true);
	});

	it('ctx.results and ctx.vars hold only declared reads; onStart sees declared URL params only', async () => {
		const { runner, invoker } = setup({ onStart: () => {}, onPageInit: () => {} });
		await runner.answer('q2', 'private');
		await runner.begin();
		const start = invoker.calls.find((c) => c.event === 'onStart')!;
		expect(start.data).toEqual({ urlParams: { PROLIFIC_PID: 'abc' } });
		expect(Object.keys((start.ctx as { results: object }).results)).toEqual([]);
		const init = invoker.calls.find((c) => c.event === 'onPageInit')!;
		expect(Object.keys((init.ctx as { results: object }).results)).toEqual(['q1']);
		expect(JSON.stringify(init.ctx)).not.toContain('private');
	});

	it('onAnswer fires only for declared items, with old and new value', async () => {
		const { runner, invoker } = setup({ onAnswer: () => {} });
		await runner.answer('q2', 'not declared');
		await runner.answer('q1', 3);
		await runner.answer('q1', 4);
		const calls = invoker.calls.filter((c) => c.event === 'onAnswer').map((c) => c.data);
		expect(calls).toEqual([
			{ itemId: 'q1', value: 3, oldValue: null },
			{ itemId: 'q1', value: 4, oldValue: 3 }
		]);
	});

	it('a result that arrives after the state moved on is stale: refused and logged', async () => {
		const { runner, invoker } = setup({ onAnswer: (ctx, data, act) => act.setVariable('hv_note', `v${String(data.value)}`) });
		let open!: () => void;
		invoker.gate.onAnswer = new Promise((r) => (open = r));
		const first = runner.answer('q1', 1);
		await Promise.resolve();
		// The participant answers again while the first hook is still running.
		const s = runner.state;
		const { state: moved } = (await import('@osp/engine')).tryAnswer(s, 'q2', 'typing');
		runner.setState(moved);
		open();
		expect(await first).toEqual({ outcome: 'stale' });
		const last = hookEvents(runner.state).at(-1)!;
		expect(last.rejected).toBe('stale');
		expect(runner.state.data.hooks?.vars.hv_note).toBeUndefined();
	});

	it('non-critical hooks fail open; the failure is recorded', async () => {
		const { runner, invoker } = setup({ onPageShown: () => {} });
		invoker.fail.onPageShown = { status: 'timeout', error: 'timeout' };
		const r = await runner.begin();
		expect(r).toEqual({ outcome: 'failed-open', error: 'timeout:timeout' });
		const ev = hookEvents(runner.state).find((e) => e.effect.event === 'onPageShown')!;
		expect((ev.value as HookResolution).status).toBe('failed');
		expect(runner.state.data.ended).toBeNull();
	});

	it('a flow-critical hook gets one retry prompt, then ends hook-failed (never another path)', async () => {
		const { runner, invoker } = setup({});
		invoker.fail.onPageNext = { status: 'timeout', error: 'timeout' };
		await runner.begin();
		await runner.answer('q1', 5);
		const r1 = await runner.next();
		expect(r1).toEqual({ outcome: 'hook', hook: { outcome: 'retry', event: 'onPageNext', error: 'timeout:timeout' } });
		expect(view(runner.state).page).toBe('p1');
		expect(await runner.next()).toMatchObject({ outcome: 'hook' }); // still waiting for the retry
		const r2 = await runner.retry();
		expect(r2).toEqual({ outcome: 'hook-failed', error: 'timeout:timeout' });
		expect(runner.state.data.ended?.outcome).toBe('hook-failed');
		expect(result(runner.state).end).toBe('hook-failed');
		expect(isState(replay(plan, runner.state.data.events))).toBe(true);
	});

	it('a flow-critical hook that succeeds on retry continues normally', async () => {
		const { runner, invoker } = setup({ onPageNext: (ctx, data, act) => act.setVariable('hv_score', 1) });
		invoker.fail.onPageNext = { status: 'error', error: 'TypeError' };
		await runner.begin();
		expect((await runner.next()).outcome).toBe('hook');
		delete invoker.fail.onPageNext;
		expect(await runner.retry()).toMatchObject({ outcome: 'ok' });
		expect(await runner.next()).toEqual({ outcome: 'advanced' });
	});

	it('invalid actions in a flow-critical hook count as a failure', async () => {
		const { runner } = setup({ onPageNext: (ctx, data, act) => act.setVariable('hv_score', 'ten') });
		await runner.begin();
		expect(await runner.next()).toMatchObject({ outcome: 'hook', hook: { outcome: 'retry', error: 'invalid-actions' } });
	});

	it('rejectPage blocks advancing; its message is escaped untrusted text', async () => {
		const { runner } = setup({
			onPageNext: (ctx, data, act) => act.rejectPage({ itemId: 'q1', message: '<img src=x onerror=alert(1)>Must‮ sum' })
		});
		await runner.begin();
		await runner.answer('q1', 1);
		expect(await runner.next()).toEqual({ outcome: 'rejected' });
		const v = view(runner.state);
		expect(v.page).toBe('p1');
		const err = v.errors.q1!;
		expect(err.kind).toBe('hook');
		expect(toHtml(err.message)).toBe('&lt;img src=x onerror=alert(1)&gt;Must sum');
		expect(v.focus).toBe('error-summary');
	});

	it('hook text piped into a label is escaped', async () => {
		const { runner } = setup({ onPageInit: (ctx, data, act) => act.setVariable('hv_note', '<b>Enter your password at evil.example</b>') });
		await toP2(runner);
		const n2 = view(runner.state).items.find((i) => i.id === 'n2')!;
		expect(toHtml(n2.label)).toBe('Hello &lt;b&gt;Enter your password at evil.example&lt;/b&gt;!');
	});

	it('onBeforeSubmit runs once however often submit is asked, with a filtered record', async () => {
		const { runner, invoker } = setup({ onBeforeSubmit: (ctx, data, act) => act.setVariable('hv_note', 'done') });
		await runner.begin();
		await runner.answer('q1', 5);
		await runner.answer('q2', 'secret text');
		await runner.next();
		await runner.next();
		const [a, b] = await Promise.all([runner.next(), runner.beforeSubmit(), runner.beforeSubmit()]);
		void a;
		void b;
		await runner.beforeSubmit();
		expect(runner.state.data.ended?.outcome).toBe('complete');
		const calls = invoker.calls.filter((c) => c.event === 'onBeforeSubmit');
		expect(calls).toHaveLength(1);
		expect(hookEvents(runner.state).filter((e) => e.effect.event === 'onBeforeSubmit')).toHaveLength(1);
		const rec = (calls[0]!.data as { record: Record<string, unknown> }).record;
		expect(Object.keys(rec.answers as object)).toEqual(['q1']);
		expect(rec.events).toBeUndefined();
		expect(rec.urlParams).toEqual({ PROLIFIC_PID: 'abc' });
		expect(JSON.stringify(rec)).not.toContain('secret text');
		expect(result(runner.state).hooks?.vars.hv_note).toBe('done');
	});

	it('refresh mid-hook: the lost result never lands, resume re-runs onPageInit once', async () => {
		const { runner, invoker } = setup({ onPageInit: (ctx, data, act) => act.setVariable('hv_flag', true) });
		await runner.begin();
		await runner.answer('q1', 5);
		let open!: () => void;
		invoker.gate.onPageInit = new Promise((r) => (open = r));
		const pending = runner.next();
		await new Promise((r) => setTimeout(r, 0));
		const snap = JSON.parse(JSON.stringify(snapshot(runner.state))); // persisted before the hook result
		// "Refresh": a new runner on the restored snapshot.
		const restored = restore(plan, snap, { clock: clock() });
		expect(isState(restored)).toBe(true);
		const inv2 = new FakeInvoker({ onPageInit: (ctx, data, act) => act.setVariable('hv_flag', true), onResume: () => {} });
		const r2 = new HookRunner({ plan, manifest: hookManifest('src'), invoker: inv2, state: restored as State });
		await r2.resume();
		expect(inv2.calls.map((c) => c.event)).toEqual(['onResume', 'onPageInit', 'onPageShown']);
		expect(view(r2.state).items.map((i) => i.id)).toEqual(['n2', 'q5']);
		await r2.resume(); // a second refresh: onPageInit already recorded for this page
		expect(inv2.calls.filter((c) => c.event === 'onPageInit')).toHaveLength(1);
		open();
		await pending; // the old tab's result lands only in the old tab's state
		expect(hookEvents(r2.state).filter((e) => e.effect.event === 'onPageInit' && e.rejected === undefined)).toHaveLength(2); // p1 + p2
	});

	it('postToParent: only declared types, schema-checked, to the declared origin, after owner confirmation', async () => {
		const { runner, sent } = setup({
			onPageShown: (ctx, data, act) => {
				act.postToParent('progress', { page: 1 });
				act.postToParent('answers', { q1: 5 });
				act.postToParent('progress', { page: 1, leak: 'x' });
			}
		});
		const r = await runner.begin();
		expect(r).toMatchObject({ outcome: 'ok', diagnostics: ['postToParent:undeclared:answers', 'postToParent:schema:progress'] });
		expect(sent).toEqual([[PARENT_ORIGIN, { source: 'osp-hooks', type: 'progress', payload: { page: 1 } }]]);

		const changed = setup(
			{ onPageShown: (ctx, data, act) => act.postToParent('progress', { page: 1 }) },
			{ manifest: { ...hookManifest('src'), source: 'edited without re-confirming' } }
		);
		expect(await changed.runner.begin()).toMatchObject({ diagnostics: ['postToParent:exports-not-confirmed'] });
		expect(changed.sent).toEqual([]);
	});

	it('setEndRedirect: declared template and placeholders only', async () => {
		const { runner } = setup({
			onBeforeSubmit: (ctx, data, act) => {
				act.setEndRedirect('prolific', { code: 'C0DE12', next: 'https://evil.example' });
				act.setEndRedirect('free', { url: 'https://evil.example' });
			},
			onSubmitted: (ctx, data, act) => act.setEndRedirect('prolific', { code: 'C0DE12' })
		});
		await runner.begin();
		await runner.next();
		await runner.next();
		await runner.next();
		expect(runner.redirectUrl()).toBeNull();
		const r = await runner.submitted();
		expect(r).toMatchObject({ outcome: 'ok' });
		expect(runner.redirectUrl()).toBe('https://app.prolific.com/submissions/complete?cc=C0DE12');
	});

	it('a tab that died mid-hook: never re-run blindly; non-critical switched off, critical retry then hook-failed', async () => {
		let marker: InflightMarker | null = null;
		const store = { get: () => marker, set: (m: InflightMarker | null) => (marker = m) };
		const invoker = new FakeInvoker({});
		const never = new Promise<void>(() => {});
		invoker.gate.onPageShown = never; // the "crash": the call never returns
		const s0 = start(plan, { sessionSeed: 3, clock: clock() });
		const r1 = new HookRunner({ plan, manifest: hookManifest('src'), invoker, state: s0, inflight: store });
		void r1.begin();
		await new Promise((r) => setTimeout(r, 0));
		expect(marker).toMatchObject({ event: 'onPageShown', retry: false });
		const snap = snapshot(r1.state);

		// Reload: a fresh runner on the persisted snapshot + marker.
		const inv2 = new FakeInvoker({});
		const r2 = new HookRunner({ plan, manifest: hookManifest('src'), invoker: inv2, state: restore(plan, snap) as State, inflight: store });
		await r2.resume();
		expect(marker).toBeNull();
		expect(inv2.calls.map((c) => c.event)).toEqual(['onResume']); // onPageShown is off now
		const crashed = hookEvents(r2.state).filter((e) => (e.value as HookResolution | null)?.error === 'crashed');
		expect(crashed.map((e) => e.effect.event)).toEqual(['onPageShown']);
		await r2.fire('onPageShown');
		expect(inv2.calls.map((c) => c.event)).toEqual(['onResume']);

		// A flow-critical hook (onPageNext writes hv_score) dies twice: retry prompt, then hook-failed.
		const crit = (s: State, retry: boolean) => ({ invocationId: `onPageNext@${s.data.revision}`, event: 'onPageNext' as const, data: { page: 'p1' }, retry });
		marker = crit(r2.state, false);
		const r3 = new HookRunner({ plan, manifest: hookManifest('src'), invoker: inv2, state: r2.state, inflight: store });
		expect(await r3.resume()).toEqual({ outcome: 'retry', event: 'onPageNext', error: 'crashed' });
		marker = crit(r3.state, true);
		const r4 = new HookRunner({ plan, manifest: hookManifest('src'), invoker: inv2, state: r3.state, inflight: store });
		expect(await r4.resume()).toEqual({ outcome: 'hook-failed', error: 'crashed' });
		expect(r4.state.data.ended?.outcome).toBe('hook-failed');
		expect(isState(replay(plan, r4.state.data.events))).toBe(true);
	});
});

describe('validateActions', () => {
	const m = hookManifest('src');
	const state = start(plan, { sessionSeed: 1, clock: clock() });
	const vc = { plan, manifest: m, event: 'onPageNext' as const, state };

	it('refuses oversized, deep or malformed results as a whole', () => {
		expect(validateActions('x', vc).refused).toBe('actions-not-a-list');
		expect(validateActions(Array.from({ length: 33 }, () => ({ type: 'addParadata', key: 'k', value: 1 })), vc).refused).toBe('too-many-actions');
		let deep: unknown = 1;
		for (let i = 0; i < 10; i++) deep = { a: deep };
		expect(validateActions([{ type: 'postToParent', messageType: 'progress', payload: deep }], vc).refused).toBe('too-deep');
	});

	it('checks every action', () => {
		const v = validateActions(
			[
				{ type: 'setVariable', id: 'hv_note', value: 'x' }, // not in onPageNext writes
				{ type: 'setVariable', id: 'q1', value: 1 },
				{ type: 'setVariable', id: 'hv_score', value: 1.5 },
				{ type: 'setVariable', id: 'hv_score', value: 12 },
				{ type: 'setVariable', id: 'hv_dec', value: 0.25 },
				{ type: 'addParadata', key: '<script>', value: 1 },
				{ type: 'addParadata', key: 'rt', value: { nested: true } },
				{ type: 'addParadata', key: 'rt', value: 532 },
				{ type: 'rejectPage', itemId: 'q4', message: 'no' },
				{ type: 'rejectPage', message: '   ' },
				{ type: 'eval', code: 'x' },
				null
			],
			vc
		);
		expect(v.actions).toEqual([
			{ kind: 'setVariable', id: 'hv_score', value: 12 },
			{ kind: 'setVariable', id: 'hv_dec', value: '0.25' },
			{ kind: 'addParadata', key: 'rt', value: 532 }
		]);
		expect(v.diagnostics).toEqual([
			'setVariable:undeclared:hv_note',
			'setVariable:undeclared:q1',
			'setVariable:type:hv_score',
			'addParadata:key',
			'addParadata:value:rt',
			'rejectPage:item:q4',
			'rejectPage:rate',
			'action:unknown:eval',
			'action:malformed'
		]);
	});

	it('rejectPage only from onPageNext; text with bidi overrides is refused for variables', () => {
		const v = validateActions(
			[
				{ type: 'rejectPage', message: 'x' },
				{ type: 'setVariable', id: 'hv_note', value: 'abc‮evil' }
			],
			{ ...vc, event: 'onPageInit' }
		);
		expect(v.actions).toEqual([]);
		expect(v.diagnostics).toEqual(['rejectPage:event:onPageInit', 'setVariable:type:hv_note']);
	});
});

describe('engine hook seam (resolve)', () => {
	const s = start(plan, { sessionSeed: 1, clock: clock() });
	const effect = { kind: 'hook' as const, invocationId: 'onPageInit@1', event: 'onPageInit', revision: 1 };
	const ok: HookResolution = { status: 'ok', actions: [{ kind: 'setVariable', id: 'hv_flag', value: true }], seed: 1, now: 0 };

	it('applies a well-formed result at the right revision', () => {
		const r = tryResolve(s, effect, ok);
		expect(r.rejected).toBeUndefined();
		expect(r.state.data.hooks?.vars).toEqual({ hv_flag: true });
	});

	it('refuses stale, duplicate, forged and malformed results (and logs them)', () => {
		expect(tryResolve(s, { ...effect, revision: 0 }, ok).rejected).toBe('stale');
		const once = tryResolve(s, effect, ok).state;
		expect(tryResolve(once, { ...effect, revision: once.data.revision }, ok).rejected).toBe('stale'); // same invocation id
		const forged = (a: unknown) => tryResolve(s, effect, { ...ok, actions: [a] } as HookResolution).rejected;
		expect(forged({ kind: 'setVariable', id: 'q1', value: 1 })).toBe('bad-result'); // a question, not a hook variable
		expect(forged({ kind: 'setVariable', id: 'hv_flag', value: 'yes' })).toBe('bad-result');
		expect(forged({ kind: 'rejectPage', itemId: null, message: 'x' })).toBe('bad-result'); // not onPageNext
		expect(forged({ kind: 'navigate', url: 'https://evil' })).toBe('bad-result');
		expect(tryResolve(s, effect, { ...ok, status: 'failed' }).rejected).toBe('bad-result'); // failed carries no actions
		expect(tryResolve(s, effect, 'open').rejected).toBe('bad-result');
		const logged = tryResolve(s, { ...effect, revision: 0 }, ok).state.data.events.at(-1)!;
		expect(logged).toMatchObject({ type: 'resolve', rejected: 'stale', value: null });
	});
});
