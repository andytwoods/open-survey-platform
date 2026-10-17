import { describe, expect, it } from 'vitest';
import { endingAnchor, endingOf, endingOp, endingsOf, endingWith, outcomesInUse } from './endings';

const survey = {
	consent: { text: 'Agree?', declineOutcome: 'no_consent' },
	quotas: [
		{ id: 'q_old', onFull: { outcome: 'quota_full' } },
		{ id: 'q_unused', onFull: { outcome: 'never' } }
	],
	flow: [
		{ type: 'block', id: 'n1', block: 'b1' },
		{ type: 'branch', id: 'br', then: [{ type: 'end', id: 'end_out', outcome: 'screened_out' }], else: [] },
		{ type: 'randomiser', id: 'r', children: [{ type: 'quotaCheck', id: 'qc', quota: 'q_old' }] },
		{ type: 'end', id: 'end_done' }
	],
	settings: { endings: { screened_out: { body: 'Bye' }, junk: 3 } }
};

describe('endings (EN1)', () => {
	it('lists every outcome a session can end with, complete first', () => {
		const used = outcomesInUse(survey);
		expect(used.map((u) => u.outcome)).toEqual(['complete', 'no_consent', 'screened_out', 'quota_full']);
		expect(used[0]!.sources).toEqual(['End of the flow', 'End node end_done']);
		expect(used.find((u) => u.outcome === 'no_consent')!.declined).toBe(true);
		expect(used.find((u) => u.outcome === 'quota_full')!.sources).toEqual(['Quota q_old (when full)']);
		expect(outcomesInUse(null).map((u) => u.outcome)).toEqual(['complete']);
	});

	it('reads endings, ignoring malformed entries, and shapes set_ending', () => {
		expect(endingsOf(survey)).toEqual({ screened_out: { body: 'Bye' } });
		expect(endingOf(survey, 'complete')).toBeNull();
		expect(endingWith({ body: 'Bye', status: 'none' }, 'status', undefined)).toEqual({ body: 'Bye' });
		expect(endingWith(null, 'title', 'Hi')).toEqual({ title: 'Hi' });
		expect(endingOp('complete', null)).toEqual({ op: 'set_ending', params: { outcome: 'complete', ending: null } });
		expect(endingAnchor('quota_full')).toBe('ending-quota_full');
	});
});
