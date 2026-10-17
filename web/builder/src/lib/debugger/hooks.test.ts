import { describe, expect, it } from 'vitest';
import { start, tryResolve, withChecksum, type HookEffect, type Plan, type State } from '@osp/engine';
import { describeAction, hookLog } from './hooks';

const t = (s: string) => ({ en: [s] });

/** p1: a (integer); hook variable hv. */
function hookTestPlan(): Plan {
	return withChecksum({
		planVersion: 'osp-runtime-plan/1',
		engineVersion: '1',
		survey: { id: 's', version: null, specVersion: 'osp-survey/0.1', seedVersion: 'draft' },
		languages: ['en'],
		defaultLanguage: 'en',
		title: t('T'),
		settings: { backNavigation: true, saveMode: 'every-page', localCopy: 'browser', resumeExpiryDays: 30 },
		items: { a: { id: 'a', page: 'p1', type: 'integer', name: 'a', required: false, label: t('a') } },
		questions: ['a'],
		pages: { p1: { id: 'p1', block: 'b1', items: ['a'], itemOrder: 'fixed' } },
		blocks: { b1: { id: 'b1', pages: ['p1'] } },
		variables: { hv: { id: 'hv', kind: 'hook', name: 'hv', valueType: 'integer' } },
		quotas: {},
		flow: [{ type: 'block', id: 'n1', block: 'b1', pages: ['p1'] }]
	} as unknown as Plan);
}

const effect = (s: State, event: string, revision = s.data.revision): HookEffect => ({
	kind: 'hook',
	invocationId: `${event}@${revision}`,
	event,
	revision
});

describe('hook log in the debugger (R10)', () => {
	it('lists every hook call from the event log with its outcome', () => {
		let s = start(hookTestPlan(), { sessionSeed: 1, clock: () => 0 });
		expect(hookLog(s)).toEqual([]);
		s = tryResolve(s, effect(s, 'onStart'), { status: 'ok', actions: [{ kind: 'setVariable', id: 'hv', value: 4 }], seed: 1, now: 0 }).state;
		s = tryResolve(s, effect(s, 'onPageShown'), { status: 'failed', actions: [], seed: 2, now: 0, error: 'timeout:2000ms' }).state;
		s = tryResolve(s, effect(s, 'onAnswer'), { status: 'ok', actions: [], seed: 3, now: 0, diagnostics: ['undeclared-write:q9'] }).state;
		// A result for a state that has moved on: refused (stale), never applied.
		s = tryResolve(s, effect(s, 'onPageNext', 0), { status: 'ok', actions: [], seed: 4, now: 0 }).state;
		const log = hookLog(s);
		expect(log.map((c) => [c.event, c.status])).toEqual([
			['onStart', 'ok'],
			['onPageShown', 'failed'],
			['onAnswer', 'ok'],
			['onPageNext', 'refused']
		]);
		expect(log[0]!.actions).toEqual(['setVariable hv = 4']);
		expect(log[1]!.error).toBe('timeout:2000ms');
		expect(log[2]!.diagnostics).toEqual(['undeclared-write:q9']);
		expect(log[3]!.error).toBe('stale');
	});

	it('describes each kind of action in one line', () => {
		expect(describeAction({ kind: 'addParadata', key: 'k', value: true })).toBe('addParadata k = true');
		expect(describeAction({ kind: 'rejectPage', itemId: 'a', message: 'no' })).toBe('rejectPage a: "no"');
		expect(describeAction({ kind: 'rejectPage', itemId: null, message: 'no' })).toBe('rejectPage: "no"');
		expect(describeAction({ kind: 'setEndRedirect', templateId: 'prolific', params: { code: 'AB12' } })).toBe(
			'setEndRedirect prolific {"code":"AB12"}'
		);
		expect(describeAction({ kind: 'postToParent', type: 'progress', payload: {} })).toBe('postToParent progress (not sent from the preview)');
		expect(describeAction({ kind: 'setVariable', id: 'v', value: 'x'.repeat(200) })).toHaveLength('setVariable v = '.length + 80);
	});
});
