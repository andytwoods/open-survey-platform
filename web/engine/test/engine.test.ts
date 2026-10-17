import { describe, expect, it } from 'vitest';
import {
	answer,
	assign,
	back,
	context,
	EngineError,
	isState,
	next,
	nodeSeed,
	replay,
	resolve,
	restore,
	result,
	setLanguage,
	snapshot,
	start,
	toHtml,
	tryAnswer,
	tryResolve,
	view,
	type Effect,
	type State
} from '../src/index.ts';
import { blockNode, clock, cmp, int, makePlan, q, ref, t } from './helpers.ts';

const basic = () =>
	makePlan({
		pages: {
			p1: [q('age', 'integer', { required: true })],
			p2: [q('why', 'text', { label: { en: ['Age ', { pipe: 'age' }, ', trial ', { pipe: '$trial' }] } })],
			p3: [q('bye', 'note')]
		}
	});

describe('start and navigation', () => {
	it('refuses a tampered plan, a bad seed and a wrong assigned level', () => {
		const plan = basic();
		expect(() => start({ ...plan, title: t('x') }, { sessionSeed: 1, clock: clock() })).toThrow(EngineError);
		expect(() => start(plan, { sessionSeed: 0, clock: clock() })).toThrow(/seed/);
		expect(() => start(plan, { sessionSeed: 1.5, clock: clock() })).toThrow(EngineError);
		expect(() => start(plan, { sessionSeed: 1, clock: clock(), assigned: { nope: 'x' } })).toThrow(EngineError);
	});

	it('validates, pipes escaped values and $trial, and keeps the input state immutable', () => {
		const plan = basic();
		const s0 = start(plan, { sessionSeed: 5, clock: clock() });
		const frozen = JSON.stringify(s0.data);
		const r = next(s0);
		expect(r.result.outcome).toBe('invalid');
		expect(view(r.state).errors.age?.kind).toBe('required');
		expect(view(r.state).focus).toBe('error-summary');
		const s1 = next(answer(r.state, 'age', '42')).state;
		expect(JSON.stringify(s0.data)).toBe(frozen);
		const v = view(s1);
		expect(v.page).toBe('p2');
		expect(toHtml(v.items[0]!.label)).toBe('Age 42, trial 2');
		expect(v.focus).toBe('heading');
		const s2 = next(answer(s1, 'why', '<b>&</b>')).state;
		expect(view(s2).page).toBe('p3');
		const done = next(s2);
		expect(done.effect).toEqual({ kind: 'end', outcome: 'complete', nodeId: null });
		expect(next(done.state).state).toBe(done.state); // idempotent after the end
		expect(back(done.state)).toBe(done.state);
	});

	it('records invalid input as invalid, blocks next, and refuses hidden or off-page items', () => {
		const plan = makePlan({
			pages: { p1: [q('n', 'integer'), q('hid', 'text', { showIf: cmp('>', ref('n'), int(5)) })], p2: [q('z', 'text')] }
		});
		let s = start(plan, { sessionSeed: 3, clock: clock() });
		expect(tryAnswer(s, 'hid', 'x').rejected).toBe('hidden');
		expect(tryAnswer(s, 'z', 'x').rejected).toBe('not-on-page');
		expect(tryAnswer(s, 'nope', 'x').rejected).toBe('unknown-item');
		s = answer(s, 'n', '12a');
		expect(next(s).result.errors).toEqual({ n: { kind: 'invalid', code: 'value.not_integer' } });
		s = answer(s, 'n', 9);
		s = answer(s, 'hid', 'shown now');
		s = answer(s, 'n', 1); // hides `hid` live; its value is kept until the submit
		expect(result(s).answers.hid).toEqual({ state: 'irrelevant', value: null });
		s = answer(s, 'n', 9);
		expect(result(s).answers.hid).toEqual({ state: 'answered', value: 'shown now' });
		s = next(answer(s, 'n', 1)).state;
		s = back(s);
		s = answer(s, 'n', 9);
		expect(result(s).answers.hid).toEqual({ state: 'unanswered', value: null }); // cleared at submit
	});

	it('back is refused when disabled and on the first page', () => {
		const plan = makePlan({ pages: { p1: [q('a', 'text')], p2: [q('b', 'text')] }, backNavigation: false });
		const s = next(start(plan, { sessionSeed: 3, clock: clock() })).state;
		expect(back(s)).toBe(s);
		expect(view(s).nav).toEqual({ back: false, next: true });
	});
});

describe('quota effects', () => {
	const plan = () =>
		makePlan({
			pages: { p1: [q('age', 'integer')], full: [q('sorry', 'note')], p2: [q('x', 'text')] },
			quotas: [
				{
					id: 'old',
					when: cmp('>=', ref('age'), int(40)),
					limit: 10,
					countOn: 'complete',
					onFull: { block: 'b_full', pages: ['full'], outcome: 'screenout' }
				}
			],
			flow: [blockNode('p1'), { type: 'quotaCheck', id: 'qc', quota: 'old' }, blockNode('p2')]
		});

	it('skips the check while `when` is false', () => {
		const s = next(answer(start(plan(), { sessionSeed: 1, clock: clock() }), 'age', 30));
		expect(s.effect).toBeUndefined();
		expect(view(s.state).page).toBe('p2');
	});

	it('asks once, is idempotent while pending, rejects stale and bad results, and replays', () => {
		const s0 = answer(start(plan(), { sessionSeed: 1, clock: clock() }), 'age', 50);
		const r = next(s0);
		const effect = r.effect as Effect;
		expect(effect).toEqual({ kind: 'quota', nodeId: 'qc', quota: 'old' });
		expect(view(r.state).status).toBe('pending');
		expect(next(r.state).state).toBe(r.state);
		expect(tryAnswer(r.state, 'age', 1).rejected).toBe('pending');
		expect(tryResolve(r.state, effect, 'maybe').rejected).toBe('bad-result');
		expect(tryResolve(r.state, { ...effect, nodeId: 'other' } as Effect, 'open').rejected).toBe('stale');
		const full = resolve(r.state, effect, 'full');
		expect(view(full).page).toBe('full');
		expect(tryResolve(full, effect, 'open').rejected).toBe('stale'); // duplicate
		const end = next(full);
		expect(end.effect).toEqual({ kind: 'end', outcome: 'screenout', nodeId: 'qc' });
		expect(result(end.state).quotas).toEqual({ qc: 'full' });
		// Back to p1 and on again: the recorded result is reused, no new effect.
		const again = next(back(full));
		expect(again.effect).toBeUndefined();
		expect(view(again.state).page).toBe('full');
		const rep = replay(end.state.plan, end.state.data.events);
		expect(isState(rep) && JSON.stringify(rep.data)).toBe(JSON.stringify(end.state.data));
	});

	it('back on the first page while pending is refused; the effect stays pending', () => {
		const r = next(answer(start(plan(), { sessionSeed: 1, clock: clock() }), 'age', 50));
		expect(view(back(r.state)).status).toBe('pending');
	});
});

describe('snapshot and restore', () => {
	it('restores identically and refuses tampering, other plans and junk', () => {
		const plan = basic();
		const s = answer(next(answer(start(plan, { sessionSeed: 9, clock: clock() }), 'age', 3)).state, 'why', 'hi');
		const snap = JSON.parse(JSON.stringify(snapshot(s)));
		const r = restore(plan, snap);
		expect(isState(r) && JSON.stringify(r.data)).toBe(JSON.stringify(s.data));
		const tampered = structuredClone(snap);
		tampered.data.values.age = 99;
		expect(restore(plan, tampered)).toMatchObject({ error: { code: 'snapshot.inconsistent' } });
		const forged = structuredClone(snap);
		forged.data.events[1].value = 99;
		expect(restore(plan, forged)).toMatchObject({ error: { code: 'snapshot.inconsistent' } });
		expect(restore(makePlan({ pages: { p1: [q('a', 'text')] } }), snap)).toMatchObject({ error: { code: 'snapshot.plan' } });
		for (const junk of [null, 1, 'x', {}, { format: 'osp-engine-snapshot/1' }]) {
			expect('error' in restore(plan, junk)).toBe(true);
		}
	});
});

describe('assignment, randomiser, languages, ctx', () => {
	it('draws a missing condition on its seedNode, like the server', () => {
		const plan = makePlan({
			pages: { p1: [q('a', 'text')] },
			variables: [{ id: 'cond', kind: 'assigned', name: 'cond', levels: ['x', 'y', 'z'], seedNode: 'as1/cond' }],
			flow: [{ type: 'assign', id: 'as1', variables: ['cond'] }, blockNode('p1')]
		});
		for (const seed of [1, 2, 3, 1234567, 2 ** 40]) {
			const r = result(start(plan, { sessionSeed: seed, clock: clock() }));
			expect(r.conditions.cond).toBe(assign(['x', 'y', 'z'], null, nodeSeed('1', seed, 'as1/cond')));
			expect(r.allocation).toBe('seeded');
			expect(r.assigned).toEqual({});
		}
		const server = result(start(plan, { sessionSeed: 1, clock: clock(), assigned: { cond: 'y' } }));
		expect(server.assigned).toEqual({ cond: 'y' });
		expect(server.allocation).toBe('server');
	});

	it('pick shows a seeded subset, and $position counts within it', () => {
		const pages = { a: [q('qa', 'text')], b: [q('qb', 'text')], c: [q('qc', 'text')] };
		const plan = makePlan({
			pages,
			flow: [{ type: 'randomiser', id: 'r', pick: 2, children: Object.keys(pages).map(blockNode) }]
		});
		let s: State = start(plan, { sessionSeed: 77, clock: clock() });
		const order = result(s).orders.blocks.r!;
		expect(order).toHaveLength(2);
		expect(view(s).position).toEqual({ randomiserId: 'r', index: 1, of: 2 });
		s = next(s).state;
		expect(view(s).position).toEqual({ randomiserId: 'r', index: 2, of: 2 });
		s = next(s).state;
		const notShown = ['qa', 'qb', 'qc'].filter((id) => !order.includes(`n_${id.slice(1)}`));
		expect(result(s).answers[notShown[0]!]!.state).toBe('not-reached');
	});

	it('switches language and falls back for an unknown one', () => {
		const plan = makePlan({ pages: { p1: [q('a', 'text', { label: { en: ['Hi'], de: ['Hallo'] } })] }, languages: ['en', 'de'] });
		const s = start(plan, { sessionSeed: 1, clock: clock(), language: 'fr' });
		expect(view(s).language).toBe('en');
		expect(toHtml(view(setLanguage(s, 'de')).items[0]!.label)).toBe('Hallo');
	});

	it('ctx reports trial, progress and the injected clock', () => {
		const plan = basic();
		const c = clock(1000, 100);
		let s = start(plan, { sessionSeed: 1, clock: c, device: 'phone', sessionId: 'sess1' });
		s = next(answer(s, 'age', 5)).state;
		const ctx = context(s);
		expect(ctx).toMatchObject({ trial: 2, trialId: 'p2', pagesDone: 1, pagesEstimated: 3, device: 'phone', sessionId: 'sess1' });
		expect(ctx.elapsedMs).toBeGreaterThan(0);
		expect(ctx.results.age).toEqual({ state: 'answered', value: 5 });
	});
});

describe('regression: an error leaves with the question an answer hides', () => {
	// properties.test.ts, fast-check seed -1539521225 (shrunk). q2 is required and shown
	// while q1 != 3; answering q1 = 0 shows it, Next demands it, then clearing q1 hides it
	// (two-valued logic: null != 3 is false). Its `required` error must not stay behind.
	it('drops the error of a question hidden by a later answer on the same page', () => {
		const plan = makePlan({
			pages: {
				p1: [q('q1', 'integer', { required: false }), q('q2', 'integer', { required: true, showIf: cmp('!=', ref('q1'), int(3)) })],
				p2: [q('q3', 'integer', { required: false })]
			},
			flow: [blockNode('p1'), blockNode('p2')]
		});
		let s = start(plan, { sessionSeed: 1, clock: clock() });
		s = answer(s, 'q1', 0);
		const r = next(s);
		expect(r.result.outcome).toBe('invalid');
		expect(Object.keys(view(r.state).errors)).toEqual(['q2']);
		s = answer(r.state, 'q1', '');
		const v = view(s);
		expect(v.items.map((i) => i.id)).toEqual(['q1']);
		expect(v.errors).toEqual({});
		// The snapshot round trip agrees, and the page can now be submitted.
		const again = restore(plan, JSON.parse(JSON.stringify(snapshot(s))));
		expect(isState(again) && view(again).errors).toEqual({});
		expect(next(s).result.outcome).toBe('advanced');
	});
});
