import { describe, expect, it } from 'vitest';
import fixture from './fixtures/results.json';
import {
	cardRequests,
	cardSections,
	choiceVariables,
	conditionVariables,
	defaultFilters,
	describeFilters,
	endExclusive,
	filterProblems,
	NOT_AVAILABLE,
	sameFilters,
	statRows,
	stateRows,
	toQuery,
	toTextParams,
	type ResultsFilters
} from './model';
import { chartsFor } from './charts';
import type { Card, ResultsResponse } from './types';

// The results page's pure logic (task V2): filters → query, chart menus, labels. The
// fixture is the real API's answer for V1's hand-checked survey (fixtures/regenerate.py).

const plain = fixture.plain as unknown as ResultsResponse;
const card = (q: string) => plain.cards.find((c) => c.question === q)!;

function filters(over: Partial<ResultsFilters> = {}): ResultsFilters {
	return { ...defaultFilters(2), ...over };
}

describe('filters → query', () => {
	it('starts on the latest version, complete responses, answered denominator', () => {
		expect(defaultFilters(3)).toMatchObject({ versions: [3], status: 'complete', denominator: 'answered' });
		expect(defaultFilters(0).versions).toEqual([]);
		expect(toQuery(defaultFilters(3))).toEqual({
			versions: [3],
			status: 'complete',
			denominator: 'answered',
			intervals: false
		});
	});

	it('maps every filter to the V1 query', () => {
		const q = toQuery(
			filters({
				versions: [2, 1],
				status: 'all',
				from: '2026-01-01',
				to: '2026-01-31',
				condition: { variable: 'arm', levels: ['a'] },
				answers: [
					{ question: 'fruit', codes: ['apple', 'banana'] },
					{ question: 'col', codes: [] }
				],
				split: { kind: 'question', id: 'sat' },
				denominator: 'shown',
				language: 'cy'
			})
		);
		expect(q).toEqual({
			versions: [1, 2],
			status: 'all',
			submittedFrom: '2026-01-01T00:00:00Z',
			// The end day is included: the API's bound is exclusive.
			submittedTo: '2026-02-01T00:00:00Z',
			filters: [{ question: 'fruit', in: ['apple', 'banana'] }],
			condition: { variable: 'arm', in: ['a'] },
			split: { question: 'sat', excludeMissing: false },
			denominator: 'shown',
			intervals: false,
			language: 'cy'
		});
		expect(toQuery(filters({ split: { kind: 'condition', id: 'arm' } })).split).toEqual({
			condition: 'arm',
			excludeMissing: false
		});
	});

	it('gives the end of a day across month and year ends', () => {
		expect(endExclusive('2026-12-31')).toBe('2027-01-01T00:00:00Z');
		expect(endExclusive('2028-02-28')).toBe('2028-02-29T00:00:00Z');
	});

	it('refuses bad or reversed dates and leaves them out of the query', () => {
		expect(filterProblems(filters({ from: '2026-02-30' }))).toEqual([
			{ field: 'from', message: 'Enter the start date as YYYY-MM-DD.' }
		]);
		expect(filterProblems(filters({ from: '2026-03-01', to: '2026-02-01' }))).toEqual([
			{ field: 'to', message: 'The end date is before the start date.' }
		]);
		expect(filterProblems(filters({ from: '2026-03-01', to: '2026-03-01' }))).toEqual([]);
		expect(toQuery(filters({ from: 'soon' })).submittedFrom).toBeUndefined();
	});

	it('maps the same filters to the text endpoint', () => {
		expect(
			toTextParams(
				filters({
					from: '2026-01-02',
					answers: [{ question: 'fruit', codes: ['apple', 'cherry'] }],
					condition: { variable: 'arm', levels: ['a', 'b'] },
					split: { kind: 'condition', id: 'arm' }
				})
			)
		).toEqual({
			versions: [2],
			status: 'complete',
			submittedFrom: '2026-01-02T00:00:00Z',
			filter: ['fruit:apple,cherry'],
			condition: 'arm:a,b'
		});
	});

	it('compares filters by meaning, not by order', () => {
		const a = filters({ versions: [1, 2], answers: [{ question: 'fruit', codes: ['b', 'a'] }] });
		const b = filters({ versions: [2, 1], answers: [{ question: 'fruit', codes: ['a', 'b'] }, { question: 'x', codes: [] }] });
		expect(sameFilters(a, b)).toBe(true);
		expect(sameFilters(a, filters())).toBe(false);
	});

	it('describes the active filters in words', () => {
		const choices = choiceVariables(plain.cards);
		expect(
			describeFilters(
				filters({
					versions: [],
					to: '2026-01-31',
					answers: [{ question: 'fruit', codes: ['apple', 'banana'] }],
					condition: { variable: 'arm', levels: ['a'] },
					split: { kind: 'question', id: 'grid_r1' }
				}),
				{ choices, versionsUsed: [2] }
			)
		).toEqual([
			'Version 2',
			'Complete responses only',
			'Submitted up to 2026-01-31',
			'Condition arm is a',
			'Fruit? is Apple or Banana',
			'Split by Grid: Row one',
			'Denominator: answered'
		]);
		expect(describeFilters(filters({ versions: [1, 2], status: 'all', denominator: 'shown' }))).toEqual([
			'Versions 1, 2',
			'All submitted responses',
			'Denominator: shown (answered + unanswered)'
		]);
	});
});

describe('filter options', () => {
	it('offers single, multiple choice and grid rows; only single choice and rows split', () => {
		const v = choiceVariables(plain.cards);
		expect(v.map((c) => [c.id, c.splittable])).toEqual([
			['fruit', true],
			['sat', true],
			['col', false],
			['grid_r1', true],
			['grid_r2', true]
		]);
		expect(v[0].codes).toEqual([
			{ key: 'apple', label: 'Apple' },
			{ key: 'banana', label: 'Banana' },
			{ key: 'cherry', label: 'Cherry' }
		]);
	});

	it('reads the assigned variables from the survey and ignores anything malformed', () => {
		expect(
			conditionVariables({
				variables: [
					{ kind: 'assigned', id: 'arm', levels: ['a', 2] },
					{ kind: 'embedded', id: 'src', param: 'src' },
					{ kind: 'assigned', id: 'bad' },
					null
				]
			})
		).toEqual([{ id: 'arm', levels: ['a', '2'] }]);
		expect(conditionVariables(null)).toEqual([]);
		expect(conditionVariables({ variables: 'x' })).toEqual([]);
	});
});

describe('chart menu', () => {
	it('is V3\'s chartsFor per question type, default first (one source of truth)', () => {
		const ids = (c: Card) => chartsFor(c).choices.map((o) => o.id);
		expect(ids(card('fruit'))).toEqual(['bars', 'bars-sorted', 'donut', 'table']);
		expect(ids(card('col'))).toEqual(['multi-pct', 'multi-counts', 'dot', 'table']);
		expect(ids(card('sl'))).toEqual(['values', 'box', 'cumulative', 'table']); // 0..10: values
		expect(ids(card('big'))).toEqual(['histogram', 'box', 'cumulative', 'table']); // 0..100: bins
		expect(ids(card('when'))).toEqual(['periods', 'table']);
		expect(chartsFor(card('when')).binUnits).toEqual(['day', 'week', 'month', 'year']);
		expect(ids(card('grid'))).toEqual(['likert', 'stacked100', 'heatmap', 'table']); // ordered
		expect(ids(card('why'))).toEqual(['states', 'table']);
	});

	it('asks for per-card bins only when a date card is not per month', () => {
		expect(cardRequests(plain.cards, {})).toBeUndefined();
		expect(cardRequests(plain.cards, { when: 'month' })).toBeUndefined();
		const r = cardRequests(plain.cards, { when: 'week' })!;
		expect(r.map((c) => c.question)).toEqual(plain.cards.map((c) => c.question));
		expect(r.find((c) => c.question === 'when')).toEqual({ question: 'when', bins: { unit: 'week' } });
		expect(r.find((c) => c.question === 'age')).toEqual({ question: 'age' });
	});
});

describe('states and statistics', () => {
	it('lists all seven response states, including unrecorded and invalid', () => {
		expect(stateRows(card('fruit').states!).map((r) => [r.key, r.count])).toEqual([
			['answered', 3],
			['unanswered', 1],
			['irrelevant', 0],
			['notReached', 0],
			['notInVersion', 0],
			['unrecorded', 0],
			['invalid', 1]
		]);
	});

	it('labels what the server sent and says "not available" for listed nulls', () => {
		const sat = card('sat');
		expect(statRows(sat.groups![0].stats, sat.categories).map((r) => [r.label, r.value])).toEqual([
			['n', '4'],
			['Median', 'L2'],
			['Mode', 'L1, L2, L4, L5'],
			['Top-2 box', '50 %'],
			['Bottom-2 box', '50 %']
		]);
		const rows = statRows({ n: 1, mean: 3, sd: null, median: 3, notAvailable: ['sd', 'q1'] });
		expect(rows.map((r) => [r.key, r.value, r.available])).toEqual([
			['n', '1', true],
			['mean', '3', true],
			['sd', NOT_AVAILABLE, false],
			['median', '3', true],
			['q1', NOT_AVAILABLE, false]
		]);
	});
});

describe('card sections', () => {
	it('is the card itself, one section per grid row, or one facet per version', () => {
		expect(cardSections(card('fruit'))).toEqual([
			{ facet: null, sections: [expect.objectContaining({ heading: null, key: 'all' })] }
		]);
		const grid = cardSections(card('grid'));
		expect(grid[0].sections.map((s) => s.heading)).toEqual(['Row one', 'Row two']);
		expect(grid[0].sections[0].states?.answered).toBe(3);
		const f = card('fruit');
		const faceted: Card = {
			...f,
			groups: [],
			facets: [
				{ version: 1, groups: f.groups, categories: f.categories, binning: 'categories' },
				{ version: 2, groups: f.groups, categories: f.categories, binning: 'categories' }
			]
		};
		expect(cardSections(faceted).map((x) => x.facet)).toEqual([1, 2]);
	});
});
