/**
 * Semantics decisions batch 1 (planning/decisions-semantics-1.md) in the engine: page-level
 * showIf, numeric min/max, a branch change after back, back refused while a quota call is
 * pending, restart of a memory-only session, piping in display order, built-in pipes,
 * runtime diagnostics, canonical decimals, and variable states.
 */

import { describe, expect, it } from 'vitest';
import {
	answer,
	answers,
	back,
	canGoBack,
	next,
	restart,
	result,
	start,
	toHtml,
	tryAnswer,
	tryBack,
	view,
	withChecksum,
	type Expr,
	type Variable
} from '../src/index.ts';
import { blockNode, clock, cmp, int, makePlan, q, ref, txt } from './helpers.ts';

describe('page-level showIf (C2-9)', () => {
	it('skips the page and makes its questions irrelevant', () => {
		const plan = makePlan({
			pages: { p1: [q('age', 'integer')], p2: [q('job', 'text')], p3: [q('end', 'text')] }
		});
		const showIf: Expr = cmp('>=', ref('age'), int(18));
		const adult = { ...plan, pages: { ...plan.pages, p2: { ...plan.pages.p2!, showIf } } };
		const p = withChecksum(adult);
		const kid = next(answer(start(p, { sessionSeed: 1, clock: clock() }), 'age', 12)).state;
		expect(view(kid).page).toBe('p3');
		expect(answers(kid).job!.state).toBe('irrelevant');
		const grown = next(answer(start(p, { sessionSeed: 1, clock: clock() }), 'age', 30)).state;
		expect(view(grown).page).toBe('p2');
	});
});

describe('numeric min / max (C2-9)', () => {
	it('blocks next with a range error on an answered value only', () => {
		const plan = makePlan({ pages: { p1: [q('n', 'integer', { min: 1, max: 9 }), q('d', 'decimal', { min: '0.5' })] } });
		const s = start(plan, { sessionSeed: 1, clock: clock() });
		expect(view(next(s).state).page).toBe(null); // unanswered optional: fine, ends
		const low = next(answer(answer(s, 'n', 0), 'd', '0.25')).state;
		expect(view(low).errors).toMatchObject({ n: { kind: 'range' }, d: { kind: 'range' } });
		const ok = next(answer(answer(s, 'n', 9), 'd', '0.50')).state;
		expect(view(ok).status).toBe('ended');
		expect(result(ok).answers.d!.value).toBe('0.5'); // canonical decimal (R6-2)
	});

	it('refuses a decimal with more than 28 significant digits as invalid', () => {
		const plan = makePlan({ pages: { p1: [q('d', 'decimal')] } });
		const s = answer(start(plan, { sessionSeed: 1, clock: clock() }), 'd', '12345678901234567890.123456789');
		expect(view(next(s).state).errors.d).toMatchObject({ kind: 'invalid', code: 'value.too_long' });
	});
});

describe('a block that drops off the path after back (C3a-6)', () => {
	const plan = makePlan({
		pages: { p1: [q('route', 'text')], car: [q('make', 'text')], bus: [q('line', 'text')], end: [q('c', 'text')] },
		flow: [
			blockNode('p1'),
			{ type: 'branch', id: 'b', if: cmp('==', ref('route'), txt('car')), then: [blockNode('car')], else: [blockNode('bus')] },
			blockNode('end')
		]
	});
	it('makes its answers irrelevant and clears them on submit, and unanswered if it returns', () => {
		let s = start(plan, { sessionSeed: 1, clock: clock() });
		s = next(answer(s, 'route', 'car')).state;
		s = next(answer(s, 'make', 'Volvo')).state;
		s = back(back(s));
		s = answer(s, 'route', 'bus');
		expect(answers(s).make).toEqual({ state: 'answered', value: 'Volvo' }); // not submitted yet
		s = next(s).state;
		expect(view(s).page).toBe('bus');
		expect(answers(s).make).toEqual({ state: 'irrelevant', value: null });
		expect(s.data.values.make).toBeUndefined();
		s = next(answer(back(s), 'route', 'car')).state;
		expect(view(s).page).toBe('car');
		expect(answers(s).make).toEqual({ state: 'unanswered', value: null });
	});
});

describe('quota pending (R6-4)', () => {
	it('refuses back and answers while the call is pending', () => {
		const plan = makePlan({
			pages: { p1: [q('a', 'text')], p2: [q('b', 'text')], p3: [q('c', 'text')] },
			quotas: [{ id: 'qt', when: { kind: 'bool', value: true }, limit: 1, countOn: 'complete', onFull: { block: null, pages: [], outcome: 'quota_full' } }],
			flow: [blockNode('p1'), blockNode('p2'), { type: 'quotaCheck', id: 'qc', quota: 'qt' }, blockNode('p3')]
		});
		const s = next(next(start(plan, { sessionSeed: 1, clock: clock() })).state).state;
		expect(view(s).status).toBe('pending');
		expect(canGoBack(s)).toBe(false);
		expect(view(s).nav?.back).toBe(false);
		expect(tryBack(s).rejected).toBe('pending');
		expect(tryAnswer(s, 'b', 'x').rejected).toBe('pending');
	});
});

describe('restart (R6-5)', () => {
	it('starts again with the same seed, conditions and orders', () => {
		const variables: Variable[] = [{ id: 'cond', kind: 'assigned', name: 'cond', levels: ['x', 'y'], seedNode: 'a/cond' }];
		const plan = makePlan({
			pages: { p1: [q('a', 'text'), q('b', 'text'), q('c', 'text')], p2: [q('d', 'text')] },
			itemOrder: { p1: 'shuffle' },
			variables,
			flow: [{ type: 'assign', id: 'a', variables: ['cond'] }, blockNode('p1'), blockNode('p2')]
		});
		const s = next(start(plan, { sessionSeed: 77, clock: clock(), assigned: { cond: 'y' }, urlParams: { u: '1' } })).state;
		const again = restart(s);
		expect(view(again).page).toBe('p1');
		expect(again.data.conditions).toEqual(s.data.conditions);
		expect(again.data.orders.items.p1).toEqual(s.data.orders.items.p1);
		expect(again.data.urlParams).toEqual({ u: '1' });
		expect(again.data.events).toHaveLength(1);
	});
});

describe('piping (C3a-9, R6-3)', () => {
	it('pipes multi labels in display order and built-ins', () => {
		const plan = makePlan({
			pages: {
				p1: [q('m', 'multi', { choiceOrder: 'shuffle' })],
				p2: [q('show', 'note', { label: { en: [{ pipe: 'm' }, ' / ', { pipe: '$trial' }, ' / ', { pipe: '$position.index' }] } })]
			}
		});
		const s0 = start(plan, { sessionSeed: 4242, clock: clock() });
		const shown = s0.data.orders.choices.m!;
		const s = next(answer(s0, 'm', ['a', 'b', 'c'])).state;
		const labels = shown.map((c) => String(c).toUpperCase()).join(', ');
		expect(toHtml(view(s).items[0]!.label)).toBe(`${labels} / 2 / `); // no randomiser: empty
	});
});

describe('runtime diagnostics and variable states (C1-1, C1-2, C2-6, C3a-5)', () => {
	it('logs division by zero and a type mismatch, never throws, and records states', () => {
		const variables: Variable[] = [
			{ id: 'ratio', kind: 'computed', name: 'ratio', expr: { kind: 'arith', op: '/', left: ref('n'), right: int(0) } },
			{ id: 'twice', kind: 'computed', name: 'twice', expr: { kind: 'arith', op: '*', left: ref('n'), right: int(2) } },
			{ id: 'later', kind: 'computed', name: 'later', expr: ref('z') },
			{ id: 'src', kind: 'embedded', name: 'src', valueType: 'integer', source: 'url', param: 'src', default: null }
		];
		const plan = makePlan({
			pages: { p1: [q('n', 'integer'), q('t', 'text', { showIf: cmp('<', ref('n'), txt('b')) })], p2: [q('z', 'text')] },
			variables
		});
		let s = start(plan, { sessionSeed: 1, clock: clock(), urlParams: { src: '12a' } });
		s = answer(s, 'n', 3);
		s = next(s).state;
		const r = result(s);
		const codes = r.diagnostics.map((d) => `${d.code}@${d.site}`);
		expect(codes).toContain('embedded.malformed@variables.src');
		expect(codes).toContain('type-mismatch@items.t.showIf');
		expect(r.computed).toMatchObject({ ratio: null, twice: '6', later: null });
		expect(r.variableStates).toEqual({ ratio: 'unanswered', twice: 'answered', later: 'unanswered', src: 'unanswered' });
		expect(r.csvState['twice__state']).toBe('answered');
		const fresh = result(start(plan, { sessionSeed: 1, clock: clock() }));
		expect(fresh.variableStates.later).toBe('not-reached');
	});
});
