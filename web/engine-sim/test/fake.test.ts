import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { Plan } from '@osp/engine';
import { FakeParticipants, type Ask, type ParticipantOutcome } from '../src/index.ts';

const BUILD = join(resolve(import.meta.dirname, '../../..'), 'web/engine/.build/fixtures');

function fixturePlan(name: string): Plan {
	const path = join(BUILD, `${name}.plan.json`);
	if (!existsSync(path)) throw new Error(`${path} is missing: run \`make sim-test\``);
	return JSON.parse(readFileSync(path, 'utf8')) as Plan;
}

async function run(plan: Plan, seed: number, n: number, dropAt: number | null = null) {
	const fakes = new FakeParticipants(plan, seed);
	const out: Array<{ outcome: ParticipantOutcome; asks: Ask[] }> = [];
	for (let i = 0; i < n; i++) {
		const asks: Ask[] = [];
		const outcome = await fakes.run(
			{ index: i, sessionSeed: 1000 + i, assigned: {}, sessionId: `s${i}`, startMs: 1_760_000_000_000, dropAt, saveMode: 'every-page' },
			async (a) => {
				asks.push(a);
				return { result: 'open' };
			}
		);
		out.push({ outcome, asks });
	}
	return out;
}

describe('fake participants (DS1)', () => {
	it('finish, submit the engine record, and answer with plausible shapes', async () => {
		const res = await run(fixturePlan('01-all-types'), 1, 200);
		const multi: number[] = [];
		for (const { outcome, asks } of res) {
			expect(outcome.submitted).toBe(true);
			expect(asks[asks.length - 1]!.do).toBe('submit');
			const a = outcome.record.answers;
			const m = a['m_multi']!;
			if (m.state === 'answered') multi.push((m.value as unknown[]).length);
			const d = a['d_date']!;
			if (d.state === 'answered') expect(String(d.value)).toMatch(/^2026-/);
			const times = asks.map((x) => x.at);
			expect([...times].sort((x, y) => x - y)).toEqual(times);
		}
		expect(Math.min(...multi)).toBe(1);
		expect(Math.max(...multi)).toBeLessThanOrEqual(3);
		// Not uniform: one fruit is clearly the favourite.
		const fruit = new Map<string, number>();
		for (const { outcome } of res) {
			const s = outcome.record.answers['s_single']!;
			if (s.state === 'answered') fruit.set(String(s.value), (fruit.get(String(s.value)) ?? 0) + 1);
		}
		const counts = [...fruit.values()].sort((x, y) => y - x);
		expect(counts[0]! / counts[counts.length - 1]!).toBeGreaterThan(1.5);
	});

	it('matrix rows correlate', async () => {
		const res = await run(fixturePlan('38-matrix'), 2, 300);
		const pairs = res
			.map((r) => r.outcome.record.answers)
			.filter((a) => a['taste_tea']!.state === 'answered' && a['taste_coffee']!.state === 'answered')
			.map((a) => [Number(a['taste_tea']!.value), Number(a['taste_coffee']!.value)] as const);
		const mean = (xs: number[]) => xs.reduce((s, x) => s + x, 0) / xs.length;
		const mx = mean(pairs.map((p) => p[0]));
		const my = mean(pairs.map((p) => p[1]));
		const cov = mean(pairs.map(([x, y]) => (x - mx) * (y - my)));
		const sd = (k: 0 | 1, m: number) => Math.sqrt(mean(pairs.map((p) => (p[k] - m) ** 2)));
		expect(cov / (sd(0, mx) * sd(1, my))).toBeGreaterThan(0.2);
	});

	it('drop-outs never submit, and the same seed gives the same answers', async () => {
		const plan = fixturePlan('39-slider');
		const drops = await run(plan, 3, 20, 0.6);
		for (const { outcome, asks } of drops) {
			expect(outcome.submitted).toBe(false);
			expect(asks.some((a) => a.do === 'submit')).toBe(false);
		}
		const a = (await run(plan, 4, 20)).map((r) => r.outcome.record.answers);
		const b = (await run(plan, 4, 20)).map((r) => r.outcome.record.answers);
		const c = (await run(plan, 5, 20)).map((r) => r.outcome.record.answers);
		expect(a).toEqual(b);
		expect(a).not.toEqual(c);
	});
});
