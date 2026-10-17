/** Endings per outcome (end-of-survey plan §4.1, task EN1): `view.end` carries the resolved ending. */
import { describe, expect, it } from 'vitest';
import { agree, answer, decline, next, start, toHtml, toPlain, view, withChecksum, type Plan } from '../src/index.ts';
import { blockNode, clock, cmp, int, makePlan, q, ref, t } from './helpers.ts';

function plan(extra: Partial<Plan> = {}): Plan {
	const base = makePlan({
		pages: { p1: [q('age', 'integer')], p2: [q('name', 'text')] },
		flow: [
			blockNode('p1'),
			{
				type: 'branch',
				id: 'br',
				if: cmp('<', ref('age'), int(18)),
				then: [{ type: 'end', id: 'end_young', outcome: 'screened_out', message: t('Sorry.') }],
				else: []
			},
			blockNode('p2')
		]
	});
	return withChecksum({
		...base,
		endings: {
			complete: { title: t('All done'), body: { en: ['Thanks, ', { pipe: 'name' }, '!'] }, status: 'auto', summary: 'none' },
			screened_out: { body: { en: ['You are ', { pipe: 'age' }, '.'] }, status: 'none', summary: 'none' }
		},
		...extra
	});
}

const begin = (p: Plan) => start(p, { sessionSeed: 3, clock: clock() });

describe('endings', () => {
	it('fills the ending of the outcome reached, pipes escaped by the renderer', () => {
		let s = answer(begin(plan()), 'age', 30);
		s = next(s).state;
		s = answer(s, 'name', '<b>Ann</b>');
		s = next(s).state;
		const end = view(s).end!;
		expect(end.outcome).toBe('complete');
		expect(toPlain(end.ending!.title)).toBe('All done');
		expect(toHtml(end.ending!.body)).toBe('Thanks, &lt;b&gt;Ann&lt;/b&gt;!');
		expect(end.message).toBeNull();
		expect(end.status).toBe('recorded');
	});

	it('keeps the end node message above the ending and honours status none', () => {
		let s = answer(begin(plan()), 'age', 12);
		s = next(s).state;
		const end = view(s).end!;
		expect(end.outcome).toBe('screened_out');
		expect(toPlain(end.message)).toBe('Sorry.');
		expect(end.ending!.title).toBeNull();
		expect(toPlain(end.ending!.body)).toBe('You are 12.');
		expect(end.status).toBeNull();
	});

	it('has no ending for an outcome without one, and none at all without endings', () => {
		const p = plan({ endings: undefined });
		let s = answer(begin(p), 'age', 12);
		s = next(s).state;
		expect(view(s).end).toEqual({ outcome: 'screened_out', message: view(s).end!.message, ending: null, status: 'recorded' });
		expect(view(begin(p)).end).toBeNull();
	});

	it('a consent decline always says nothing was recorded, whatever the ending sets', () => {
		const base = plan();
		const p = withChecksum({
			...base,
			consent: {
				version: 'sha256:' + 'b'.repeat(64),
				text: t('Consent?'),
				agree: t('Yes'),
				decline: t('No'),
				declineOutcome: 'declined',
				countDeclines: false
			},
			endings: { ...base.endings, declined: { body: t('Bye'), status: 'none', summary: 'none' } }
		});
		const d = view(decline(begin(p))).end!;
		expect(d.outcome).toBe('declined');
		expect(toPlain(d.ending!.body)).toBe('Bye');
		expect(d.status).toBe('not-recorded');
		expect(view(agree(begin(p))).end).toBeNull();
	});
});
