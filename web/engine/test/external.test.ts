/**
 * External task step (task EX2, planning/external-tasks.md): reaching an `externalTask`
 * node is an effect, like a quota check. The engine fills the outbound URL like a redirect,
 * captures the whitelisted return values into the session's URL parameters on resolve, runs
 * the hop once (recorded, reused on back/replay), and skips a hop whose URL cannot be built.
 */
import { describe, expect, it } from 'vitest';
import {
	back,
	next,
	resolve,
	result,
	start,
	tryResolve,
	view,
	withChecksum,
	type Effect,
	type FlowNode,
	type Plan,
	type Variable
} from '../src/index.ts';
import { blockNode, clock, makePlan, q } from './helpers.ts';

const PID = { id: 'prolific_pid', kind: 'embedded', name: 'prolific_pid', valueType: 'text', source: 'url', param: 'PROLIFIC_PID', default: null } as Variable;
const RT = { id: 'rt', kind: 'embedded', name: 'rt', valueType: 'integer', source: 'url', param: 'rt', default: null } as Variable;

const EXT: FlowNode = {
	type: 'externalTask',
	id: 'et1',
	template: 'task',
	params: { pid: [{ pipe: 'prolific_pid' }] },
	returns: [{ variable: 'rt', param: 'rt' }]
};

function plan(): Plan {
	const base = makePlan({
		pages: { p1: [q('a', 'text')], p2: [q('b', 'text')] },
		flow: [blockNode('p1'), EXT, blockNode('p2')],
		variables: [PID, RT]
	});
	return withChecksum({
		...base,
		redirectTemplates: { task: { url: 'https://run.pavlovia.org/lab/e?pid={pid}', params: { pid: {} } } }
	} as Plan);
}

const begin = (urlParams: Record<string, string> = { PROLIFIC_PID: 'p123' }) =>
	start(plan(), { sessionSeed: 3, clock: clock(), urlParams, sessionId: 's1' });

/** Advance from p1 to the pending external effect. */
function toHop(urlParams?: Record<string, string>) {
	const r = next(begin(urlParams)); // submit p1
	return { state: r.state, effect: r.effect as Effect };
}

describe('external task effect', () => {
	it('pends with the outbound URL filled from a piped param', () => {
		const { state, effect } = toHop();
		const v = view(state);
		expect(v.status).toBe('pending');
		expect(effect.kind).toBe('external');
		if (effect.kind !== 'external') throw new Error('expected external');
		expect(effect.url).toBe('https://run.pavlovia.org/lab/e?pid=p123');
		expect(effect.host).toBe('run.pavlovia.org');
		expect(effect.rejected).toBeNull();
		expect(effect.returns).toEqual([{ variable: 'rt', param: 'rt' }]);
	});

	it('captures the return values into URL parameters and continues', () => {
		const { state, effect } = toHop();
		const after = resolve(state, effect, { params: { rt: '350', junk: 'x' } });
		const v = view(after);
		expect(v.status).toBe('page');
		expect(v.page).toBe('p2');
		const rec = result(after);
		expect(rec.urlParams.rt).toBe('350'); // whitelisted (declared in returns)
		expect(rec.urlParams.junk).toBeUndefined(); // not declared: dropped
		expect(rec.embedded.rt).toBe(350); // captured as the embedded (integer) variable
	});

	it('runs once: a second resolve is stale and a back does not re-trigger it', () => {
		const { state, effect } = toHop();
		const atP2 = resolve(state, effect, { params: { rt: '1' } });
		// Replay the same return: nothing changes (same-context replay).
		const again = tryResolve(atP2, effect, { params: { rt: '999' } });
		expect(again.rejected).toBe('stale');
		expect(result(again.state).urlParams.rt).toBe('1');
		// Back to p1, then forward again: the hop is recorded, so no new effect.
		const backToP1 = back(atP2);
		expect(view(backToP1).page).toBe('p1');
		const fwd = next(backToP1);
		expect(fwd.result.outcome).toBe('advanced');
		expect(view(fwd.state).page).toBe('p2');
	});

	it('skips a hop whose URL cannot be built and records a diagnostic', () => {
		const { state, effect } = toHop({}); // no PROLIFIC_PID: the piped pid is empty, rejected
		if (effect.kind !== 'external') throw new Error('expected external');
		expect(effect.url).toBeNull();
		expect(effect.rejected).toBe('pid');
		const after = resolve(state, effect, { params: {} });
		expect(view(after).page).toBe('p2'); // not stranded
		const codes = result(after).diagnostics.map((d) => d.code);
		expect(codes).toContain('external.param_rejected');
	});
});
