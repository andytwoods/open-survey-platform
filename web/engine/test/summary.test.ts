/** The ending's list of answers (end-of-survey plan §4.4, task EN5): `answerSummary`. */
import { describe, expect, it } from 'vitest';
import { answer, answerSummary, back, next, start, toHtml, toPlain, withChecksum, type Item, type Plan } from '../src/index.ts';
import { blockNode, clock, cmp, int, makePlan, q, ref, t } from './helpers.ts';

const row = (id: string, matrix: string): Item =>
	({ id, type: 'single', page: '', label: t(id), name: id, required: false, matrix, choices: [{ value: 1, label: t('Poor') }, { value: 2, label: t('Good') }] }) as Item;

function plan(): Plan {
	const base = makePlan({
		pages: {
			p1: [q('note', 'note'), q('age', 'integer'), q('colour', 'multi'), q('why', 'text')],
			p2: [q('fruit', 'single'), q('when', 'date'), q('pain', 'slider', { min: 0, max: 10, step: 1 })],
			p3: [q('skipped', 'text')],
			p4: [
				{ id: 'drinks', type: 'matrix', page: '', label: t('Drinks'), name: 'drinks', required: false, rows: ['drinks_tea', 'drinks_coffee'], choices: [{ value: 1, label: t('Poor') }, { value: 2, label: t('Good') }] } as Item,
				row('drinks_tea', 'drinks'),
				row('drinks_coffee', 'drinks')
			]
		},
		flow: [
			blockNode('p1'),
			blockNode('p2'),
			{ type: 'branch', id: 'br', if: cmp('<', ref('age'), int(18)), then: [blockNode('p3')], else: [] },
			blockNode('p4')
		]
	});
	// A matrix lists itself, not its rows, on the page (C2c-1).
	base.pages.p4!.items = ['drinks'];
	return withChecksum({ ...base, endings: { complete: { status: 'auto', summary: 'answers' } } });
}

const begin = () => start(plan(), { sessionSeed: 7, clock: clock() });
const text = (e: { label: unknown; value: unknown }) => [toPlain(e.label as never), toPlain(e.value as never)];

describe('answerSummary (EN5)', () => {
	it('lists answered questions in path order with display labels; notes and unanswered ones are left out', () => {
		let s = begin();
		s = answer(s, 'age', 30);
		s = answer(s, 'colour', ['c', 'a']);
		s = next(s).state; // why unanswered
		s = answer(s, 'fruit', 'b');
		s = answer(s, 'when', '2026-10-01');
		s = answer(s, 'pain', 7);
		s = next(s).state; // age >= 18: p3 skipped
		s = answer(s, 'drinks_coffee', 2);
		s = next(s).state;
		const out = answerSummary(s);
		expect(out.map((e) => e.id)).toEqual(['age', 'colour', 'fruit', 'when', 'pain', 'drinks']);
		expect(out.slice(0, 5).map(text)).toEqual([
			['age', '30'],
			['colour', 'A, C'], // labels in the displayed order, as piping does
			['fruit', 'B'],
			['when', '2026-10-01'],
			['pain', '7']
		]);
		const m = out[5]!;
		expect(m.type).toBe('matrix');
		expect(m.value).toBeNull();
		expect(m.rows!.map(text)).toEqual([['drinks_coffee', 'Good']]);
	});

	it('marks answers as participant data (escaped as HTML) and drops pages taken off the path', () => {
		let s = begin();
		s = answer(s, 'age', 12);
		s = answer(s, 'why', '<b>x</b>\nline 2');
		s = next(s).state;
		s = next(s).state; // age < 18: p3 is on the path
		s = answer(s, 'skipped', 'seen');
		s = next(s).state;
		expect(answerSummary(s).map((e) => e.id)).toEqual(['age', 'why', 'skipped']);
		expect(toHtml(answerSummary(s)[1]!.value)).toBe('&lt;b&gt;x&lt;/b&gt;\nline 2');
		// Back to p1, grow up: p3 drops off the path and its answer is cleared (§3).
		s = back(back(back(s)));
		s = answer(s, 'age', 40);
		s = next(s).state;
		s = next(s).state;
		s = next(s).state;
		expect(answerSummary(s).map((e) => e.id)).toEqual(['age', 'why']);
	});

	it('is empty before anything is answered', () => {
		expect(answerSummary(begin())).toEqual([]);
	});
});
