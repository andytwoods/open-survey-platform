import { describe, expect, it } from 'vitest';
import { checkInvariant, compare, pick, type Diff, type Realised } from '../src/compare.ts';
import { evaluate } from '../src/evaluate.ts';
import { casesOf, fixtureNames, selectFixtures, variantKey } from '../src/fixtures.ts';
import type { Played } from '../src/player.ts';

function run(expected: unknown, actual: unknown) {
	const diffs: Diff[] = [];
	const realised: Realised[] = [];
	const filled = compare(expected, actual, 'x', diffs, realised);
	return { diffs, realised, filled };
}

describe('compare', () => {
	it('placeholders match anything and are recorded', () => {
		const r = run({ a: '<engine>', b: '<pending:R6-1>', c: 1 }, { a: [2, 1], b: 'whatever', c: 1 });
		expect(r.diffs).toEqual([]);
		expect(r.realised.map((x) => x.path)).toEqual(['x.a', 'x.b']);
		expect(r.filled).toEqual({ a: [2, 1], b: 'whatever', c: 1 });
	});

	it('reports missing, extra and different values', () => {
		const r = run({ a: 1, b: 2 }, { a: 1, c: 3 });
		expect(r.diffs.map((d) => d.path).sort()).toEqual(['x.b', 'x.c']);
		expect(run([1, 2], [1, 2, 3]).diffs).toHaveLength(1);
		expect(run('0.1', 0.1).diffs).toHaveLength(1); // decimals are strings, never floats
	});

	it('compares multi values as sets, every other array in order', () => {
		const q = (value: unknown) => ({ questions: { m: { state: 'answered', value } } });
		const d: Diff[] = [];
		compare(q(['a', 'b']), q(['b', 'a']), 'steps[0]', d, []);
		expect(d).toEqual([]);
		compare({ visible: ['a', 'b'] }, { visible: ['b', 'a'] }, 'steps[0]', d, []);
		expect(d.map((x) => x.path)).toEqual(['steps[0].visible[0]', 'steps[0].visible[1]']);
	});

	it('pick keeps the keys the expected step names (and only the asserted built-ins)', () => {
		expect(pick({ a: 1, b: 2, builtins: { trial: 1, position: null } }, { a: 0, builtins: { trial: 1 } })).toEqual({
			a: 1,
			builtins: { trial: 1 }
		});
	});

	it('invariants', () => {
		const root = { steps: [{ page: 'p1' }, { page: 'p1' }], response: { o: ['b', 'a'] } };
		expect(checkInvariant({ kind: 'equal', paths: ['steps[0].page', 'steps[1].page'] }, root)).toBeNull();
		expect(checkInvariant({ kind: 'permutation', of: ['a', 'b'], paths: ['response.o'] }, root)).toBeNull();
		expect(checkInvariant({ kind: 'permutation', of: ['a', 'c'], paths: ['response.o'] }, root)).toMatch(/not a permutation/);
	});
});

describe('evaluate', () => {
	const c = casesOf('01-all-types').find((x) => x.script.id === 'answered')!;
	const ok: Played = {
		steps: structuredClone(c.expected.steps),
		response: structuredClone(c.expected.response) as Record<string, unknown>,
		responseSource: 'server-record',
		network: { quotaCalls: {}, snapshotWrites: 0, submits: 1 },
		problems: [],
		sessionId: 's',
		abortedAt: null,
		abortReason: null
	};

	it('passes on the expected trace itself', () => {
		expect(evaluate(c, ok).status).toBe('passed');
	});

	it('fails on a screen problem and points at the first differing step', () => {
		const v = evaluate(c, { ...ok, problems: [{ path: 'steps[1].a11y.n_int', expected: 'x', actual: 'none found' }] });
		expect(v.status).toBe('failed');
		expect(v.firstStep).toBe(1);
		expect(v.firstAction).toEqual(c.script.actions[0]);
	});

	it('fails a script that could not be played', () => {
		const v = evaluate(c, { ...ok, steps: ok.steps.slice(0, 1), abortedAt: 0, abortReason: 'no Next button' });
		expect(v.status).toBe('failed');
		expect(v.firstStep).toBe(1);
	});
});

describe('fixture selection', () => {
	it('by folder name or number prefix; nothing named or nothing left = all', () => {
		const all = fixtureNames();
		expect(selectFixtures('')).toEqual(all);
		expect(selectFixtures('06, 25-second-device-resume')).toEqual(['06-clear-on-back', '25-second-device-resume']);
		expect(selectFixtures('99-deleted')).toEqual(all);
	});

	it('variant keys match the launcher (sorted, compact JSON)', () => {
		expect(variantKey(undefined)).toBe('{}');
		expect(variantKey({ q_b: 'full', q_a: 'open' })).toBe('{"q_a":"open","q_b":"full"}');
	});
});
