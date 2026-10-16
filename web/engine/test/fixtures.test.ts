/**
 * Every fixture script through the engine, compared with fixtures/<f>/expected/.
 *
 * - `"<engine>"` placeholders match anything; the realised values go into
 *   .build/fixture-report.json for the lead to approve into expected/ (not written here).
 *   The file's `invariants` are asserted instead.
 * - Traces with a non-empty `pending` list are drafts: they are run and reported, never
 *   asserted.
 */

import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';
import {
	BUILD,
	FIXTURES,
	checkInvariant,
	compare,
	fixtureNames,
	loadJson,
	loadPlan,
	pick,
	play,
	replayResponse,
	type Diff,
	type Invariant,
	type Realised,
	type Script
} from './fixture-runner.ts';
import { readdirSync } from 'node:fs';

interface Expected {
	pending: string[];
	steps: Array<Record<string, unknown>>;
	invariants: Invariant[];
	response: Record<string, unknown>;
}

type Status = 'passed' | 'pending' | 'failed';

/** Expected files that contradict themselves; fixtures are not R1's to edit (reported to the lead). */
const KNOWN_FIXTURE_BUGS: Record<string, { why: string; broken: string[] }> = {}; // 28's steps[12].visible: fixed in R2b
const report: Array<{
	fixture: string;
	script: string;
	status: Status;
	reason?: string;
	diffs?: Diff[];
	realised?: Realised[];
	invariants?: string[];
}> = [];

afterAll(() => {
	const counts = { passed: 0, pending: 0, failed: 0 };
	for (const r of report) counts[r.status]++;
	writeFileSync(join(BUILD, 'fixture-report.json'), JSON.stringify({ counts, scripts: report }, null, 2));
	console.log(`fixtures: ${counts.passed} passed, ${counts.pending} pending, ${counts.failed} failed`);
});

describe('runner', () => {
	it('detects a wrong expected trace and a broken invariant', () => {
		const name = '06-clear-on-back';
		const { plan } = loadPlan(name);
		const script = loadJson<Script>(join(FIXTURES, name, 'scripts', 'main.json'));
		const expected = loadJson<Expected>(join(FIXTURES, name, 'expected', 'main.json'));
		const run = play(plan!, script);
		const bad = structuredClone(expected.steps[5]!);
		(bad.questions as Record<string, { state: string }>).pet_name!.state = 'answered';
		bad.visible = ['pet_name', 'season'];
		const diffs: Diff[] = [];
		compare(bad, pick(run.steps[5]!, bad), 'steps[5]', diffs, []);
		expect(diffs.map((d) => d.path).sort()).toEqual([
			'steps[5].questions.pet_name.state',
			'steps[5].visible'
		]);
		const inv: Invariant = { kind: 'equal', paths: ['steps[0].page', 'steps[1].page'] };
		expect(checkInvariant(inv, { steps: run.steps })).toMatch(/differs/);
	});
});

for (const name of fixtureNames()) {
	describe(name, () => {
		const scripts = readdirSync(join(FIXTURES, name, 'scripts')).filter((f) => f.endsWith('.json')).sort();
		for (const file of scripts) {
			const script = loadJson<Script>(join(FIXTURES, name, 'scripts', file));
			const expected = loadJson<Expected>(join(FIXTURES, name, 'expected', file));
			const pending = expected.pending.length > 0;
			it(`${script.id}${pending ? ` (pending: ${expected.pending.join(', ')})` : ''}`, () => {
				const { plan, error } = loadPlan(name);
				const entry: (typeof report)[number] = { fixture: name, script: script.id, status: 'passed' };
				report.push(entry);
				if (!plan) {
					entry.status = pending ? 'pending' : 'failed';
					entry.reason = `no plan: ${error}`;
					if (!pending) expect.fail(entry.reason);
					return;
				}
				let run: ReturnType<typeof play>;
				try {
					run = play(plan, script);
				} catch (e) {
					entry.status = pending ? 'pending' : 'failed';
					entry.reason = `script could not be played: ${(e as Error).message}`;
					if (!pending) throw e;
					return;
				}
				const diffs: Diff[] = [];
				const realised: Realised[] = [];
				const steps = expected.steps.map((exp, i) => {
					const actual = run.steps[i];
					if (!actual) {
						diffs.push({ path: `steps[${i}]`, expected: exp, actual: undefined });
						return exp;
					}
					return compare(exp, pick(actual, exp), `steps[${i}]`, diffs, realised);
				});
				if (run.steps.length !== expected.steps.length) {
					diffs.push({ path: 'steps.length', expected: expected.steps.length, actual: run.steps.length });
				}
				const response = compare(
					expected.response,
					pick(run.response as unknown as Record<string, unknown>, expected.response),
					'response',
					diffs,
					realised
				);
				if (script.replay) {
					// The engine's replay makes no effect calls at all: results come from the log.
					const rep = replayResponse(plan, run.state);
					const same = 'response' in rep && JSON.stringify(rep.response) === JSON.stringify(run.response);
					if (!same) diffs.push({ path: 'replay', expected: 'the same response', actual: rep });
				}
				const root = { steps, response };
				const broken = expected.invariants.map((inv) => checkInvariant(inv, root)).filter((x): x is string => !!x);
				entry.diffs = diffs;
				entry.realised = realised;
				entry.invariants = broken;
				if (pending) {
					entry.status = 'pending';
					entry.reason = `pending ${expected.pending.join(', ')}`;
					return;
				}
				const known = KNOWN_FIXTURE_BUGS[`${name}/${script.id}`];
				if (known) {
					// Reported as failed, but only in exactly the known way; once the fixture is
					// fixed this assertion fails and the entry must be removed.
					entry.status = 'failed';
					entry.reason = `fixture bug: ${known.why}`;
					expect(diffs).toEqual([]);
					expect(broken).toEqual(known.broken);
					return;
				}
				if (diffs.length || broken.length) entry.status = 'failed';
				expect(diffs).toEqual([]);
				expect(broken).toEqual([]);
			});
		}
	});
}
