import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { Plan } from '@osp/engine';
import { simulate, SimError, numericPoints, type SimResult } from '../src/index.ts';
import { blockNode, cmp, int, makePlan, q, ref, txt } from '../../engine/test/helpers.ts';

const REPO = resolve(import.meta.dirname, '../../..');
const BUILD = join(REPO, 'web/engine/.build/fixtures');

function fixturePlan(name: string): Plan {
	const path = join(BUILD, `${name}.plan.json`);
	if (!existsSync(path)) throw new Error(`${path} is missing: run \`make sim-test\` (it builds the plans first)`);
	const plan = JSON.parse(readFileSync(path, 'utf8')) as Plan & { error?: string };
	if (plan.error) throw new Error(plan.error);
	return plan;
}

function fixtureNames(): string[] {
	return readdirSync(join(REPO, 'fixtures'))
		.filter((n) => existsSync(join(REPO, 'fixtures', n, 'survey.json')))
		.sort();
}

const pathKeys = (r: SimResult['sample']) => r.paths.top.map((p) => `${p.pages.join('>')}|${p.end}`).sort();

describe('fixture 13: randomiser balance', () => {
	it('every one of the 6 block orders is realised, each within 10% of n/6 at n=5,000', () => {
		const r = simulate(fixturePlan('13-randomiser-blocks'), { n: 5000, seed: 13 });
		const rand = r.sample.randomisers['r_blocks']!;
		expect(rand.reached).toBe(5000);
		const counts = Object.values(rand.orders);
		expect(counts).toHaveLength(6);
		for (const c of counts) expect(Math.abs(c - 5000 / 6)).toBeLessThan(5000 / 6 / 10);
		// Each child in each position about a third of the time.
		for (const pos of Object.values(rand.positions)) for (const c of pos) expect(Math.abs(c - 5000 / 3)).toBeLessThan(5000 / 3 / 10);
		expect(r.coverage).toBe('exhaustive');
		expect(r.pathSpace).toMatchObject({ exhaustive: true, paths: 6, randomiserOrders: 6 });
	});
});

describe('fixture 11: end nodes', () => {
	it('reaches every end node, in the sample and in the enumeration', () => {
		const r = simulate(fixturePlan('11-end-nodes'), { n: 2000, seed: 11 });
		for (const end of ['end_ineligible', 'end_early_exit', 'end_complete']) {
			expect(r.sample.ends[end]).toBeGreaterThan(0);
			expect(r.exhaustive!.ends[end]).toBeGreaterThan(0);
		}
		expect(r.sample.stuck).toEqual({});
	});

	it('enumerates exactly the hand-listed paths', () => {
		const r = simulate(fixturePlan('11-end-nodes'), { n: 10, seed: 1 });
		expect(r.coverage).toBe('exhaustive');
		expect(pathKeys(r.exhaustive!)).toEqual(
			[
				'p1_page>p2_page>p3_page|complete@end_complete',
				'p1_page>p2_page|early_exit@end_early_exit',
				'p1_page|ineligible@end_ineligible'
			].sort()
		);
		// eligible ∈ {yes, no}; rating ∈ {2, 3, 4} (around the literal 3), required.
		expect(r.pathSpace.combinations).toBe(4);
		expect(r.exhaustive!.branches['branch_2']).toEqual({ then: 1, else: 2, undetermined: 0 });
	});
});

describe('exhaustive enumeration matches a brute-force enumeration', () => {
	it('fixtures 13 and 16: every order and every assigned condition', () => {
		const r13 = simulate(fixturePlan('13-randomiser-blocks'), { n: 1, seed: 1 });
		const perms = ['x', 'y', 'z'].flatMap((a) =>
			['x', 'y', 'z'].filter((b) => b !== a).map((b) => [a, b, ['x', 'y', 'z'].find((c) => c !== a && c !== b)!])
		);
		expect(pathKeys(r13.exhaustive!)).toEqual(
			perms.map((p) => `intro_page>${p.map((x) => `blk_${x}_page`).join('>')}>outro_page|complete@(implicit)`).sort()
		);
		const r16 = simulate(fixturePlan('16-assign'), { n: 1, seed: 1 });
		expect(r16.exhaustive!.assignments['cond']).toEqual({ control: 1, treatment: 1 });
		expect(r16.pathSpace).toMatchObject({ paths: 2, assignmentCombinations: 2 });
	});

	it('a hand-made plan: two single questions and nested branches', () => {
		// a ∈ {a,b,c} (required), b ∈ {blank,a,b,c}; then-arm when a == "a", nested on b == "b".
		const plan = makePlan({
			pages: { p1: [q('qa', 'single', { required: true })], p2: [q('qb', 'single')], p3: [q('qc', 'text')], p4: [q('qd', 'text')] },
			flow: [
				blockNode('p1'),
				{
					type: 'branch',
					id: 'br',
					if: cmp('==', ref('qa'), txt('a')),
					then: [blockNode('p2'), { type: 'branch', id: 'inner', if: cmp('==', ref('qb'), txt('b')), then: [blockNode('p3')], else: [] }],
					else: [blockNode('p4')]
				}
			]
		});
		const r = simulate(plan, { n: 3000, seed: 2 });
		// Brute force: qa=b|c → p1>p4 (2 combos); qa=a → qb ∈ {blank,a,b,c} → p3 only for b.
		expect(r.pathSpace.combinations).toBe(2 + 4);
		expect(pathKeys(r.exhaustive!)).toEqual(
			['p1>p4|complete@(implicit)', 'p1>p2|complete@(implicit)', 'p1>p2>p3|complete@(implicit)'].sort()
		);
		expect(r.exhaustive!.branches['inner']).toEqual({ then: 1, else: 3, undetermined: 0 });
		// The sample can't find a path the enumeration didn't.
		expect(pathKeys(r.sample)).toEqual(pathKeys(r.exhaustive!));
	});

	it('on every fixture, the sample only finds enumerated paths', () => {
		for (const name of fixtureNames()) {
			const r = simulate(fixturePlan(name), { n: 300, seed: 7 });
			if (!r.exhaustive) {
				expect(r.coverage, name).toBe('sampled');
				expect(r.pathSpace.reasons.length, name).toBeGreaterThan(0);
				continue;
			}
			expect(r.exhaustive.paths.distinct, name).toBe(r.pathSpace.paths);
			const all = new Set(pathKeys(r.exhaustive));
			if (r.exhaustive.paths.distinct <= 20) for (const k of pathKeys(r.sample)) expect(all.has(k), `${name}: ${k}`).toBe(true);
		}
	});
});

describe('unreachable logic is visible', () => {
	const plan = makePlan({
		pages: { p1: [q('age', 'integer', { required: true, min: 0, max: 120 })], p2: [q('x', 'text')], p3: [q('y', 'text')] },
		flow: [
			blockNode('p1'),
			{
				type: 'branch',
				id: 'never',
				if: { kind: 'and', args: [cmp('<', ref('age'), int(18)), cmp('>', ref('age'), int(65))] },
				then: [blockNode('p2'), { type: 'end', id: 'end_never', outcome: 'odd' }],
				else: []
			},
			blockNode('p3')
		]
	});

	it('a branch arm that no answer can take is never taken in the enumeration', () => {
		const r = simulate(plan, { n: 2000, seed: 3 });
		expect(r.coverage).toBe('exhaustive');
		expect(r.exhaustive!.branches['never']).toMatchObject({ then: 0 });
		expect(r.exhaustive!.nodes['n_p2']).toBe(0);
		expect(r.exhaustive!.ends['end_never']).toBe(0);
		expect(r.exhaustive!.questions['x']!['not-reached']).toBe(r.exhaustive!.runs);
		expect(r.sample.pages['p2']).toEqual({ reached: 0, shown: 0 });
	});
});

describe('strategies', () => {
	const plan = makePlan({
		pages: { p1: [q('s', 'single', { required: true }), q('o', 'single'), q('n', 'integer', { min: 5, max: 9 })] }
	});

	it('skip-optional leaves every optional question blank', () => {
		const r = simulate(plan, { n: 200, seed: 1, answerStrategy: 'skip-optional' });
		expect(r.sample.questions['o']!.answered).toBe(0);
		expect(r.sample.questions['n']!.answered).toBe(0);
		expect(r.sample.questions['s']!.answered).toBe(200);
	});

	it('first-choice always gives the first choice and the lowest number', () => {
		const r = simulate(plan, { n: 50, seed: 1, answerStrategy: 'first-choice', exhaustive: false });
		expect(r.sample.questions['o']!.answered).toBe(50);
		expect(r.sample.paths.distinct).toBe(1);
		expect(r.coverage).toBe('sampled');
		expect(r.pathSpace.reasons).toEqual(['enumeration was switched off']);
	});

	it('weights steer the answers (blank = "")', () => {
		const r = simulate(plan, { n: 2000, seed: 4, answerStrategy: { weights: { o: { '': 3, a: 1 } } } });
		const answered = r.sample.questions['o']!.answered;
		expect(answered).toBeGreaterThan(400);
		expect(answered).toBeLessThan(600);
	});

	it('uniform answers stay inside min/max and include the bounds', () => {
		expect(numericPoints(plan.items['n'] as never, [])).toEqual([5, 9]);
		const r = simulate(plan, { n: 300, seed: 5 });
		expect(r.sample.stuck).toEqual({});
		expect(r.sample.outcomes).toEqual({ complete: 300 });
	});
});

describe('robustness', () => {
	it('is a pure function of plan and options', () => {
		const plan = fixturePlan('20-worked-example');
		expect(simulate(plan, { n: 200, seed: 9 })).toEqual(simulate(plan, { n: 200, seed: 9 }));
		expect(simulate(plan, { n: 200, seed: 9 }).sample).not.toEqual(simulate(plan, { n: 200, seed: 10 }).sample);
	});

	it('refuses bad options', () => {
		const plan = fixturePlan('01-all-types');
		for (const bad of [{ n: 0 }, { n: 10_001 }, { n: 1.5 }, { n: 5, seed: -1 }, { n: 5, answerStrategy: 'bogus' }, { n: 5, quotaFull: 2 }]) {
			expect(() => simulate(plan, { seed: 1, ...bad } as never)).toThrow(SimError);
		}
	});

	it('falls back to sampled when the path space is over the limit', () => {
		const r = simulate(fixturePlan('20-worked-example'), { n: 50, seed: 1, exhaustiveLimit: 10 });
		expect(r.coverage).toBe('sampled');
		expect(r.exhaustive).toBeNull();
		expect(r.pathSpace.reasons).toContain('more than 10 answer combinations');
	});

	it('reports participants stuck on a page no answer can pass', () => {
		const plan = makePlan({
			pages: {
				p1: [q('v', 'integer', { required: true, constraint: { kind: 'and', args: [cmp('>', ref('v'), int(5)), cmp('<', ref('v'), int(3))] } })]
			}
		});
		const r = simulate(plan, { n: 20, seed: 1 });
		expect(r.sample.outcomes).toEqual({ stuck: 20 });
		expect(r.sample.stuck).toEqual({ p1: 20 });
		expect(r.exhaustive!.stuck).toEqual({ p1: 1 });
	});

	it('every fixture simulates without throwing', () => {
		for (const name of fixtureNames()) {
			const r = simulate(fixturePlan(name), { n: 100, seed: 1 });
			expect(r.sample.runs, name).toBe(100);
			for (const st of [r.sample, r.exhaustive]) {
				if (!st) continue;
				// Every reached branch has an observable arm in the fixtures.
				for (const [id, b] of Object.entries(st.branches)) {
					expect(b.undetermined, `${name} ${id}`).toBe(0);
					expect(b.then + b.else, `${name} ${id}`).toBe(st.nodes[id]);
				}
				const ended = Object.values(st.ends).reduce((a, b) => a + b, 0);
				expect(ended + Object.values(st.stuck).reduce((a, b) => a + b, 0), name).toBe(st.runs);
			}
		}
	});
});
