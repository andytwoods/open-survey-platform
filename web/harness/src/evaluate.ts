/** A played script against its expected trace: diffs, invariants, status. */
import { checkInvariant, compare, pick, type Diff, type Realised } from './compare.ts';
import type { Case } from './fixtures.ts';
import type { Played, Problem } from './player.ts';

export type Status = 'passed' | 'pending' | 'failed';

export interface Verdict {
	fixture: string;
	script: string;
	status: Status;
	pending: string[];
	diffs: Diff[];
	problems: Problem[];
	invariants: string[];
	realised: Realised[];
	abort: string | null;
	/** First step index that differs (the minimal place to look), or null. */
	firstStep: number | null;
	/** The action that led to that step (steps[i] follows actions[i-1]). */
	firstAction: unknown;
	responseSource: Played['responseSource'];
	sessionId: string | null;
}

function stepOf(path: string): number | null {
	const m = /^steps\[(\d+)\]/.exec(path);
	return m ? Number(m[1]) : null;
}

export function evaluate(c: Case, played: Played): Verdict {
	const { expected } = c;
	const diffs: Diff[] = [];
	const realised: Realised[] = [];
	const steps = expected.steps.map((exp, i) => {
		const actual = played.steps[i];
		if (!actual) {
			if (played.abortedAt === null) diffs.push({ path: `steps[${i}]`, expected: exp, actual: undefined });
			return exp;
		}
		return compare(exp, pick(actual, exp), `steps[${i}]`, diffs, realised);
	});
	if (played.abortedAt === null && played.steps.length !== expected.steps.length) {
		diffs.push({ path: 'steps.length', expected: expected.steps.length, actual: played.steps.length });
	}
	let response: unknown = expected.response;
	if (played.abortedAt === null) {
		const exp = expected.response;
		const act = played.response && typeof exp === 'object' ? pick(played.response, exp) : played.response;
		response = compare(exp, act, 'response', diffs, realised);
	}
	if (expected.network && played.abortedAt === null) {
		compare(expected.network, pick(played.network as unknown as Record<string, unknown>, expected.network), 'network', diffs, realised);
	}
	const broken =
		played.abortedAt === null
			? expected.invariants.map((inv) => checkInvariant(inv, { steps, response })).filter((x): x is string => !!x)
			: [];
	const failedSteps = [...diffs.map((d) => stepOf(d.path)), ...played.problems.map((p) => stepOf(p.path))].filter(
		(x): x is number => x !== null
	);
	if (played.abortedAt !== null) failedSteps.push(Math.max(0, played.abortedAt + 1));
	const firstStep = failedSteps.length ? Math.min(...failedSteps) : null;
	const bad = diffs.length > 0 || broken.length > 0 || played.problems.length > 0 || played.abortedAt !== null;
	const pending = expected.pending ?? [];
	return {
		fixture: c.fixture,
		script: c.script.id,
		status: pending.length ? 'pending' : bad ? 'failed' : 'passed',
		pending,
		diffs,
		problems: played.problems,
		invariants: broken,
		realised,
		abort: played.abortReason,
		firstStep,
		firstAction: firstStep !== null && firstStep > 0 ? c.script.actions[firstStep - 1] : null,
		responseSource: played.responseSource,
		sessionId: played.sessionId
	};
}

/** One line per difference, for test output and the report. */
export function describe(v: Verdict, limit = 12): string[] {
	const out: string[] = [];
	if (v.abort) out.push(`could not play: ${v.abort}`);
	for (const d of v.diffs) out.push(`${d.path}: expected ${JSON.stringify(d.expected)}, got ${JSON.stringify(d.actual)}`);
	for (const p of v.problems) out.push(`${p.path}: expected ${JSON.stringify(p.expected)}, got ${JSON.stringify(p.actual)}`);
	for (const b of v.invariants) out.push(`invariant: ${b}`);
	return out.length > limit ? [...out.slice(0, limit), `… ${out.length - limit} more`] : out;
}
