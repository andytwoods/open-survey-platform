import '@testing-library/svelte/vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import axe from 'axe-core';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import fixture from './fixtures/results.json';
import type { Fetched, ResultsSource } from './results.svelte';
import ResultsView from './ResultsView.svelte';
import type { Card, ResultsQuery, ResultsResponse, TextPage } from './types';

// The Results page from a stubbed source (task V2): cards from a real ResultsResponse
// (fixtures/results.json, regenerated from the API), the Table view, the filter bar's
// mapping to the query, chart choices, facets, "not available", text answers, waiting,
// errors and axe.

const SURVEY = { variables: [{ kind: 'assigned', id: 'arm', levels: ['a', 'b'] }] };
const clone = <T,>(x: T): T => structuredClone(x);

function stub(reply: (q: ResultsQuery) => ResultsResponse | Promise<Fetched<ResultsResponse>> = () => clone(fixture.plain) as unknown as ResultsResponse) {
	const queries: ResultsQuery[] = [];
	const texts: Record<string, unknown>[] = [];
	const source: ResultsSource = {
		async query(body) {
			queries.push(clone(body));
			const r = await reply(body);
			return 'ok' in r ? r : { ok: true, data: r };
		},
		async text(_q, params) {
			texts.push(clone(params));
			const page = clone(fixture.text) as unknown as TextPage;
			if (params.cursor) return { ok: true, data: { ...page, items: [{ ...page.items[0], responseId: 'r3', value: 'ok' }], nextCursor: null } };
			return { ok: true, data: page };
		}
	};
	return { source, queries, texts };
}

async function setup(opts: { source?: ResultsSource; published?: number } = {}) {
	const s = opts.source ? { source: opts.source, queries: [], texts: [] } : stub();
	const t = render(ResultsView, {
		surveyId: 's1',
		survey: SURVEY,
		publishedVersions: opts.published ?? 1,
		source: s.source
	});
	if ((opts.published ?? 1) > 0 && !opts.source) await screen.findByRole('list', { name: 'Questions' });
	return { t, ...s };
}

const cardOf = (label: string) => screen.getByRole('article', { name: label });

afterEach(() => vi.useRealTimers());

describe('ResultsView', () => {
	it('shows one card per question in survey order, with states and statistics', async () => {
		const { queries } = await setup();
		expect(queries).toEqual([{ versions: [1], status: 'complete', denominator: 'answered', intervals: false }]);
		const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
		expect(headings).toEqual([
			'Filters',
			'Active filters',
			'Fruit?',
			'Satisfied?',
			'Colours?',
			'Age?',
			'Price?',
			'Slide',
			'Big slide',
			'When?',
			'Why?',
			'Grid'
		]);
		const fruit = cardOf('Fruit?');
		const dl = fruit.querySelector('dl[aria-label="Response states for Fruit?"]')!;
		expect([...dl.querySelectorAll('.state')].map((s) => s.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
			'Answered 3',
			'Unanswered 1',
			'Irrelevant (skipped by logic) 0',
			'Not reached 0',
			'Not in this version 0',
			'Unrecorded 0',
			'Invalid 1'
		]);
		const stats = within(fruit).getByRole('table', { name: 'Statistics' });
		expect(within(stats).getByRole('row', { name: /Mode/ }).textContent).toContain('Apple');
		expect(screen.getByTestId('results-count').textContent).toContain('5 responses');
		expect([...screen.getByTestId('active-filters').querySelectorAll('li')].map((l) => l.textContent)).toEqual([
			'Version 1',
			'Complete responses only',
			'Denominator: answered'
		]);
	});

	it('Table view shows the exact numbers, with each group n', async () => {
		await setup();
		const fruit = cardOf('Fruit?');
		await fireEvent.click(within(fruit).getByRole('button', { name: 'Table view' }));
		expect(within(fruit).getByRole('button', { name: 'Table view' }).getAttribute('aria-pressed')).toBe('true');
		const table = within(fruit).getByRole('table', { name: 'Fruit?' });
		const rows = within(table)
			.getAllByRole('row')
			.map((r) => [...r.querySelectorAll('th, td')].map((c) => c.textContent?.trim()));
		expect(rows).toEqual([
			['Option', 'Count', '% of answered'],
			['Apple', '2', '66.7 %'],
			['Banana', '1', '33.3 %'],
			['Cherry', '0', '0 %'],
			['n (answered)', '3', '']
		]);
		// Multiple choice says its percentages can sum past 100.
		const col = cardOf('Colours?');
		await fireEvent.click(within(col).getByRole('button', { name: 'Table view' }));
		expect(within(col).getByRole('columnheader', { name: '% of respondents (can sum > 100 %)' })).toBeTruthy();
	});

	it('a grid shows one section per row, each with its own n', async () => {
		await setup();
		const grid = cardOf('Grid');
		expect(within(grid).getAllByRole('heading', { level: 4 }).map((h) => h.textContent)).toEqual(['Row one', 'Row two']);
		expect((within(grid).getByRole('combobox', { name: 'Chart' }) as HTMLSelectElement).value).toBe('diverging');
		await fireEvent.click(within(grid).getByRole('button', { name: 'Table view' }));
		const rowTable = within(grid).getByRole('table', { name: 'Grid, Row one' });
		expect(within(rowTable).getByRole('row', { name: /n \(answered\)/ }).textContent).toContain('3');
	});

	it('the chart menu offers charts per type; the slot gets the choice; a date period re-queries', async () => {
		const { queries } = await setup();
		const fruit = cardOf('Fruit?');
		const menu = within(fruit).getByRole('combobox', { name: 'Chart' }) as HTMLSelectElement;
		expect([...menu.options].map((o) => o.textContent)).toEqual([
			'Horizontal bars (declared order)',
			'Sorted bars',
			'Donut',
			'Table'
		]);
		expect(fruit.querySelector('[data-chart]')?.getAttribute('data-chart')).toBe('bars');
		await fireEvent.change(menu, { target: { value: 'donut' } });
		expect(fruit.querySelector('[data-chart]')?.getAttribute('data-chart')).toBe('donut');
		expect(queries).toHaveLength(1); // a choice-card chart is drawn from the same numbers
		expect(within(cardOf('Why?')).queryByRole('combobox', { name: 'Chart' })).toBeNull();

		const when = within(cardOf('When?')).getByRole('combobox', { name: 'Chart' });
		await fireEvent.change(when, { target: { value: 'week' } });
		await waitFor(() => expect(queries).toHaveLength(2));
		expect(queries[1].cards?.find((c) => c.question === 'when')).toEqual({ question: 'when', bins: { unit: 'week' } });
	});

	it('maps the filter bar to the query only when applied', async () => {
		const { queries } = await setup();
		await fireEvent.change(screen.getByLabelText('Responses'), { target: { value: 'all' } });
		await fireEvent.input(screen.getByLabelText('Submitted from'), { target: { value: '2026-01-02' } });
		await fireEvent.input(screen.getByLabelText('Submitted to (inclusive)'), { target: { value: '2026-01-31' } });
		await fireEvent.change(screen.getByLabelText('Condition'), { target: { value: 'arm\u0000b' } });
		await fireEvent.change(screen.getByLabelText('Split by'), { target: { value: 'question\u0000sat' } });
		await fireEvent.click(screen.getByRole('radio', { name: 'Shown (answered + unanswered)' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Add answer filter' }));
		const codes = screen.getByRole('group', { name: 'Keep responses that answered' });
		await fireEvent.click(within(codes).getByRole('checkbox', { name: 'Banana' }));
		expect(screen.getByText('Changes not applied yet.')).toBeTruthy();
		expect(queries).toHaveLength(1);

		await fireEvent.click(screen.getByRole('button', { name: 'Show results' }));
		await waitFor(() => expect(queries).toHaveLength(2));
		expect(queries[1]).toEqual({
			versions: [1],
			status: 'all',
			submittedFrom: '2026-01-02T00:00:00Z',
			submittedTo: '2026-02-01T00:00:00Z',
			filters: [{ question: 'fruit', in: ['banana'] }],
			condition: { variable: 'arm', in: ['b'] },
			split: { question: 'sat', excludeMissing: false },
			denominator: 'shown',
			intervals: false
		});
		await waitFor(() => expect(screen.queryByText('Changes not applied yet.')).toBeNull());
		const chips = [...screen.getByTestId('active-filters').querySelectorAll('li')].map((l) => l.textContent);
		expect(chips).toContain('Fruit? is Banana');
		expect(chips).toContain('Condition arm is b');
		expect(chips).toContain('Submitted 2026-01-02 to 2026-01-31');
	});

	it('refuses a reversed date range and moves focus to it', async () => {
		const { queries } = await setup();
		await fireEvent.input(screen.getByLabelText('Submitted from'), { target: { value: '2026-03-01' } });
		await fireEvent.input(screen.getByLabelText('Submitted to (inclusive)'), { target: { value: '2026-02-01' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Show results' }));
		expect(screen.getByText('The end date is before the start date.')).toBeTruthy();
		expect(screen.getByLabelText('Submitted to (inclusive)').getAttribute('aria-invalid')).toBe('true');
		await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('Submitted to (inclusive)')));
		expect(queries).toHaveLength(1);
	});

	it('shows split groups side by side in the table', async () => {
		const { source } = stub(() => clone(fixture.split) as unknown as ResultsResponse);
		await setup({ source });
		await screen.findByRole('list', { name: 'Questions' });
		const fruit = cardOf('Fruit?');
		await fireEvent.click(within(fruit).getByRole('button', { name: 'Table view' }));
		const head = within(within(fruit).getByRole('table', { name: 'Fruit?' })).getAllByRole('columnheader');
		expect(head.map((h) => h.textContent)).toEqual([
			'Option',
			'a: count',
			'a: %',
			'b: count',
			'b: %',
			'No condition: count',
			'No condition: %'
		]);
		expect(screen.getByTestId('results-count').textContent).toMatch(/a: 2, b: 2, No condition: 1/);
	});

	it('shows "not available" for statistics the server lists, and version facets with their warning', async () => {
		const response = clone(fixture.plain) as unknown as ResultsResponse;
		const age = response.cards.find((c) => c.question === 'age')!;
		age.groups![0].stats = { ...age.groups![0].stats, sd: null, notAvailable: ['sd'] };
		const fruit = response.cards.find((c) => c.question === 'fruit')! as Card;
		fruit.facets = [1, 2].map((version) => ({
			version,
			groups: fruit.groups,
			categories: fruit.categories,
			binning: 'categories' as const,
			states: fruit.states
		}));
		fruit.groups = [];
		fruit.versionsUsed = [1, 2];
		fruit.warnings = [{ code: 'versions.incompatible', message: 'The options differ between versions 1 and 2.', question: 'fruit' }];
		await setup({ source: stub(() => response).source, published: 2 });
		await screen.findByRole('list', { name: 'Questions' });
		const sd = within(cardOf('Age?')).getByRole('row', { name: /SD/ });
		expect(sd.textContent).toContain('not available');
		const card = cardOf('Fruit?');
		expect(within(card).getAllByRole('heading', { level: 4 }).map((h) => h.textContent)).toEqual(['Version 1', 'Version 2']);
		expect(within(card).getByRole('list', { name: 'Warnings for Fruit?' }).textContent).toContain('differ between versions');
		expect(card.textContent).toContain('Versions 1, 2');
	});

	it('pages through a text question’s answers on request', async () => {
		const { texts } = await setup();
		const why = cardOf('Why?');
		expect(texts).toEqual([]); // reading answers is audited: only on request
		await fireEvent.click(within(why).getByRole('button', { name: 'Show answers' }));
		const table = within(await within(why).findByRole('region', { name: 'Answers to Why?' })).getByRole('table');
		expect(within(table).getAllByRole('row').slice(1).map((r) => r.querySelector('td')?.textContent)).toEqual(['sunny', 'rain!']);
		expect(within(why).getByText('Answers 1–2 of 3')).toBeTruthy();
		expect(texts).toEqual([{ versions: [1], status: 'complete', limit: 20 }]);
		await fireEvent.click(within(why).getByRole('button', { name: 'Next' }));
		await within(why).findByText('Answers 21–21 of 3');
		expect(texts[1]).toMatchObject({ cursor: fixture.text.nextCursor });
		await fireEvent.click(within(why).getByRole('button', { name: 'Previous' }));
		await waitFor(() => expect(texts).toHaveLength(3));
		expect(texts[2].cursor).toBeUndefined();
	});

	it('waits visibly for a long query and can cancel it', async () => {
		vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
		let release!: (r: Fetched<ResultsResponse>) => void;
		const source = stub(() => new Promise<Fetched<ResultsResponse>>((r) => (release = r))).source;
		await setup({ source });
		await tick();
		expect(screen.getByTestId('results-waiting').textContent).toContain('Computing results…');
		expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
		vi.advanceTimersByTime(2100);
		await tick();
		expect(screen.getByTestId('results-waiting').textContent).toContain('2 s');
		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
		expect(screen.queryByTestId('results-waiting')).toBeNull();
		release({ ok: true, data: clone(fixture.plain) as unknown as ResultsResponse });
		await tick();
		expect(screen.queryByRole('list', { name: 'Questions' })).toBeNull(); // the cancelled reply is dropped
	});

	it('shows the API error with a retry, and an unpublished survey asks nothing', async () => {
		let fail = true;
		const source = stub(() =>
			Promise.resolve(
				fail
					? { ok: false as const, status: 422, message: 'split condition "x" not found' }
					: { ok: true as const, data: clone(fixture.plain) as unknown as ResultsResponse }
			)
		).source;
		await setup({ source });
		expect((await screen.findByRole('alert')).textContent).toContain('split condition "x" not found');
		fail = false;
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await screen.findByRole('list', { name: 'Questions' });

		const s = stub();
		render(ResultsView, { surveyId: 's2', survey: {}, publishedVersions: 0, source: s.source });
		expect(screen.getByTestId('results-unpublished').textContent).toContain('Nothing is published yet');
		expect(s.queries).toEqual([]);
	});

	it('passes axe with cards, tables and a filter row', async () => {
		const { t } = await setup();
		await fireEvent.click(within(cardOf('Fruit?')).getByRole('button', { name: 'Table view' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Add answer filter' }));
		const res = await axe.run(t.container, {
			rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }
		});
		expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	});
});
