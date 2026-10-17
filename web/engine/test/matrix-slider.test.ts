/**
 * Matrix and slider (task C2c; semantics.md §2, C2c-1 to C2c-3) beyond what fixtures 38
 * and 39 trace: the view's row and track shapes, refusals, and replay.
 */
import { describe, expect, it } from 'vitest';
import { checkAnswer, isState, next, replay, result, start, tryAnswer, view, type QuestionItem } from '../src/index.ts';
import { loadPlan } from './fixture-runner.ts';

const clock = () => 1;

describe('matrix (C2c-1)', () => {
	const { plan } = loadPlan('38-matrix');

	it('shows one item with its rows and columns; rows are the questions', () => {
		const s = start(plan!, { sessionSeed: 7, clock });
		const v = view(s);
		expect(v.items.map((i) => i.id)).toEqual(['taste']);
		const m = v.items[0]!;
		expect(m.type).toBe('matrix');
		expect(m.state).toBeNull();
		expect(m.required).toBe(true);
		expect(m.rows!.map((r) => [r.id, r.required, r.state])).toEqual([
			['taste_tea', true, 'unanswered'],
			['taste_coffee', true, 'unanswered'],
			['taste_cocoa', false, 'unanswered']
		]);
		expect(m.choices!.map((c) => c.value)).toEqual([1, 2, 3]);
		expect(plan!.questions).not.toContain('taste');
	});

	it('refuses an answer to the matrix itself and accepts codes as text per row', () => {
		let s = start(plan!, { sessionSeed: 7, clock });
		expect(tryAnswer(s, 'taste', { tea: 1 }).rejected).toBe('not-a-question');
		s = tryAnswer(s, 'taste_tea', '3').state;
		expect(view(s).items[0]!.rows![0]!.value).toBe(3);
		expect(tryAnswer(s, 'taste_coffee', 9).state.data.invalid.taste_coffee).toBe('value.not_a_choice');
	});

	it('puts the first row error on the matrix item and every row error in errors', () => {
		const s = next(start(plan!, { sessionSeed: 7, clock })).state;
		const v = view(s);
		expect(Object.keys(v.errors)).toEqual(['taste_tea', 'taste_coffee']);
		expect(v.items[0]!.error?.kind).toBe('required');
		expect(v.items[0]!.rows![2]!.error).toBeNull();
	});

	it('replays to the same response, with row export names', () => {
		let s = start(plan!, { sessionSeed: 7, clock });
		s = tryAnswer(s, 'taste_tea', 2).state;
		s = tryAnswer(s, 'taste_coffee', 2).state;
		s = next(s).state;
		const r = replay(plan!, s.data.events);
		expect(isState(r) && result(r)).toEqual(result(s));
		expect(result(s).csvState).toMatchObject({ drink_tea__state: 'answered', when_morning__state: 'irrelevant' });
	});
});

describe('slider (C2c-3)', () => {
	const { plan } = loadPlan('39-slider');
	const item = (id: string) => plan!.items[id] as QuestionItem;

	it('starts unanswered and exposes its track', () => {
		const v = view(start(plan!, { sessionSeed: 7, clock }));
		const pain = v.items[0]!;
		expect(pain.value).toBeNull();
		expect(pain.state).toBe('unanswered');
		expect(pain.slider).toMatchObject({ min: 0, max: 10, step: 1, valueType: 'integer' });
		expect(pain.slider!.maxLabel?.[0]?.text).toBe('Worst imaginable');
	});

	it('reads input as its value type and checks the step grid', () => {
		expect(checkAnswer(item('pain'), 4)).toEqual({ ok: true, value: 4 });
		expect(checkAnswer(item('pain'), '4')).toEqual({ ok: true, value: 4 });
		expect(checkAnswer(item('pain'), 4.5)).toEqual({ ok: false, code: 'value.not_integer' });
		expect(checkAnswer(item('sleep'), 7.5)).toEqual({ ok: true, value: '7.5' });
		expect(checkAnswer(item('sleep'), '7.50')).toEqual({ ok: true, value: '7.5' });
		expect(checkAnswer(item('sleep'), '7.25')).toEqual({ ok: false, code: 'value.off_step' });
		expect(checkAnswer(item('mood'), -5)).toEqual({ ok: true, value: -5 });
		expect(checkAnswer(item('pain'), null)).toEqual({ ok: true, value: null });
	});

	it('reports a value off the track as a range error at submit', () => {
		let s = start(plan!, { sessionSeed: 7, clock });
		s = tryAnswer(s, 'pain', 11).state;
		expect(view(next(s).state).errors.pain?.kind).toBe('range');
	});
});
