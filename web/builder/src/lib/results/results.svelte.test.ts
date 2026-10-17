import '@testing-library/svelte/vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import axe from 'axe-core';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import fixture from './fixtures/results.json';
import type { Fetched, ResultsSource } from './results.svelte';
import ResultsView from './ResultsView.svelte';
import type { Card, ResultsQuery, ResultsResponse, TextPage } from './types';

const AXE_TIMEOUT = 20_000;

// The Results page from a stubbed source (task V2): cards from a real ResultsResponse
// (fixtures/results.json, regenerated from the API), the Table view, the filter bar's
// mapping to the query, chart choices, facets, "not available", text answers, waiting,
// errors and axe.

const SURVEY = { variables: [{ kind: 'assigned', id: 'arm', levels: ['a', 'b'] }] };
const clone = <T,>(x: T): T => structuredClone(x);

/**
 * The stub's "server": its responses and watermark (task LV3). `arrive()` is one more
 * response: the watermark moves, the count grows and Fruit? gains an Apple, so a refresh
 * shows a changed card. Until it is called, every reply is the fixture as it is.
 */
function server() {
	const s = { watermark: fixture.plain.watermark as string, responses: fixture.plain.responses as number, polls: 0, pollAfterMs: 1000 };
	return {
		...s,
		arrive() {
			this.responses += 1;
			this.watermark = `wm${this.responses}`;
		},
		stamp(r: ResultsResponse): ResultsResponse {
			r.watermark = this.watermark;
			if (this.responses === fixture.plain.responses) return r;
			r.responses = this.responses;
			const fruit = r.cards.find((c) => c.question === 'fruit')!;
			const apple = fruit.groups![0].cells.find((c) => c.key === 'apple')!;
			apple.count += this.responses - fixture.plain.responses;
			return r;
		}
	};
}

function stub(reply: (q: ResultsQuery) => ResultsResponse | Promise<Fetched<ResultsResponse>> = () => clone(fixture.plain) as unknown as ResultsResponse) {
	const queries: ResultsQuery[] = [];
	const texts: Record<string, unknown>[] = [];
	const exports: Record<string, unknown>[] = [];
	const srv = server();
	const source: ResultsSource = {
		async recordExport(body) {
			exports.push(clone(body));
			return { ok: true, data: { recorded: true, queryHash: 'h', versions: [1], formats: body.formats } };
		},
		async query(body) {
			queries.push(clone(body));
			const r = await reply(body);
			return 'ok' in r ? r : { ok: true, data: srv.stamp(r) };
		},
		async text(_q, params) {
			texts.push(clone(params));
			const page = clone(fixture.text) as unknown as TextPage;
			page.watermark = srv.watermark;
			if (params.cursor) return { ok: true, data: { ...page, items: [{ ...page.items[0], responseId: 'r3', value: 'ok' }], nextCursor: null } };
			return { ok: true, data: page };
		},
		async watermark() {
			srv.polls++;
			return { ok: true, data: { watermark: srv.watermark, responses: srv.responses, versionsUsed: [1], pollAfterMs: srv.pollAfterMs } };
		}
	};
	return { source, queries, texts, exports, server: srv };
}

async function setup(opts: { source?: ResultsSource; published?: number; minRefreshMs?: number } = {}) {
	const s = opts.source ? { source: opts.source, queries: [], texts: [], exports: [], server: server() } : stub();
	const t = render(ResultsView, {
		surveyId: 's1',
		survey: SURVEY,
		publishedVersions: opts.published ?? 1,
		source: s.source,
		minRefreshMs: opts.minRefreshMs
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
		expect((within(grid).getByRole('combobox', { name: 'Chart' }) as HTMLSelectElement).value).toBe('likert');
		await fireEvent.click(within(grid).getByRole('button', { name: 'Table view' }));
		const rowTable = within(grid).getByRole('table', { name: 'Grid, Row one' });
		expect(within(rowTable).getByRole('row', { name: /n \(answered\)/ }).textContent).toContain('3');
	});

	it('the chart menu offers charts per type; the slot gets the choice; a date period re-queries', async () => {
		const { queries } = await setup();
		const fruit = cardOf('Fruit?');
		const menu = within(fruit).getByRole('combobox', { name: 'Chart' }) as HTMLSelectElement;
		expect([...menu.options].map((o) => o.textContent)).toEqual(['Bars', 'Sorted bars', 'Donut', 'Table']);
		expect(fruit.querySelector('[data-chart]')?.getAttribute('data-chart')).toBe('bars');
		await fireEvent.change(menu, { target: { value: 'donut' } });
		expect(fruit.querySelector('[data-chart]')?.getAttribute('data-chart')).toBe('donut');
		expect(queries).toHaveLength(1); // a choice-card chart is drawn from the same numbers
		const why = within(cardOf('Why?')).getByRole('combobox', { name: 'Chart' }) as HTMLSelectElement;
		expect([...why.options].map((o) => o.textContent)).toEqual(['Response states', 'Table']);

		const when = within(cardOf('When?')).getByRole('combobox', { name: 'Per' });
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

	it('presentation mode (V6): only the cards and a way out; Escape leaves; the URL carries the flag', async () => {
		history.replaceState(null, '', '/surveys/s1/results');
		await setup();
		expect(screen.getByRole('button', { name: 'Export all' })).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'Present' }));
		await waitFor(() => expect(screen.getByTestId('exit-presentation')).toBeTruthy());
		expect(location.search).toBe('?present=1');
		expect(screen.queryByRole('button', { name: 'Export all' })).toBeNull();
		expect(screen.queryByRole('button', { name: 'Show results' })).toBeNull();
		expect(screen.queryByTestId('theme-picker')).toBeNull();
		expect(screen.queryByRole('button', { name: 'Hide Fruit?' })).toBeNull();
		const fruit = cardOf('Fruit?');
		expect(within(fruit).queryByRole('combobox', { name: 'Chart' })).toBeNull();
		expect(within(fruit).queryByRole('button', { name: 'Export Fruit?' })).toBeNull();
		expect(fruit.querySelector('[data-chart="bars"]')).toBeTruthy();
		expect(within(fruit).getByTestId('card-caption').textContent).toBe(
			'Fruit? (fruit). Version 1; Complete responses only; Denominator: answered. n = 3 responses.'
		);
		// The page heading stays for the landmark, visually hidden, and is the page's h1 now the top bar is gone.
		expect(screen.getByRole('heading', { name: 'Results', level: 1 })).toBeTruthy();
		await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId('exit-presentation')));

		await fireEvent.keyDown(window, { key: 'Escape' });
		await waitFor(() => expect(screen.getByRole('button', { name: 'Export all' })).toBeTruthy());
		expect(location.search).toBe('');
		expect(screen.queryByTestId('exit-presentation')).toBeNull();
		await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Present' })));
		expect(within(cardOf('Fruit?')).getByRole('combobox', { name: 'Chart' })).toBeTruthy();
	});

	it('opens in presentation mode from ?present=1, and the floating button leaves it', async () => {
		history.replaceState(null, '', '/surveys/s1/results?present=1&layout=lay_9');
		await setup();
		await waitFor(() => expect(screen.getByTestId('exit-presentation')).toBeTruthy());
		expect(screen.queryByTestId('layout-bar')).toBeNull();
		await fireEvent.click(screen.getByTestId('exit-presentation'));
		await waitFor(() => expect(screen.getByRole('button', { name: 'Present' })).toBeTruthy());
		expect(location.search).toBe('?layout=lay_9'); // only the presentation flag is touched
		history.replaceState(null, '', '/');
	});

	it('the theme picker (V6): the survey’s theme, presets and lab themes recolour the charts; contrast is checked', async () => {
		const warmLight = { accent: '#a3431a', background: '#fdf8f1', surface: '#f5ecdf', text: '#2b2118', muted: '#65544a', error: '#a8201a', focus: '#a3431a' };
		const warmDark = { accent: '#f2a571', background: '#1c1713', surface: '#262019', text: '#f3eadf', muted: '#c4b4a2', error: '#ff8f84', focus: '#f2a571' };
		const faint = { ...warmLight, text: '#bbbbbb' };
		const s = stub();
		s.source.themes = async () => ({
			ok: true,
			data: {
				themes: [
					{ id: 'th1', name: 'Lab warm', theme: { colours: { light: warmLight, dark: warmDark } }, isDefault: true, diagnostics: [] },
					{ id: 'th2', name: 'Faint', theme: { colours: { light: faint, dark: warmDark }, mode: 'light' }, isDefault: false, diagnostics: [] }
				],
				defaultThemeId: 'th1'
			}
		});
		await setup({ source: s.source });
		await screen.findByRole('list', { name: 'Questions' });
		const picker = screen.getByLabelText('Theme') as HTMLSelectElement;
		await waitFor(() => expect([...picker.options].map((o) => o.textContent)).toContain('Lab warm (lab default)'));
		expect([...picker.options].map((o) => o.value)).toEqual(['app', 'survey', 'preset:clean', 'preset:warm', 'preset:high-contrast', 'preset:dark', 'preset:compact', 'library:th1', 'library:th2']);
		expect(screen.getByTestId('theme-note').textContent).toContain('App colours.');
		const list = screen.getByRole('list', { name: 'Questions' });
		expect(list.getAttribute('style')).toBeNull();

		// No survey theme: "this survey's theme" is the lab default.
		await fireEvent.change(picker, { target: { value: 'survey' } });
		expect(screen.getByTestId('theme-note').textContent).toContain('This survey’s theme: the lab default “Lab warm”, light colours.');
		expect(list.getAttribute('style')).toContain('--color-bg: #fdf8f1');
		expect(list.getAttribute('data-theme-mode')).toBe('light');
		expect(screen.queryByTestId('theme-contrast')).toBeNull();

		await fireEvent.change(picker, { target: { value: 'library:th2' } });
		expect(screen.getByTestId('theme-note').textContent).toContain('Lab theme “Faint”');
		expect(screen.getByTestId('theme-contrast').textContent).toContain('fails a contrast check for charts: axis titles and labels on the background');

		await fireEvent.change(picker, { target: { value: 'preset:dark' } });
		expect(list.getAttribute('data-theme-mode')).toBe('dark');
		expect(list.getAttribute('style')).toContain('color-scheme: dark');
		await fireEvent.change(picker, { target: { value: 'app' } });
		expect(list.getAttribute('style')).toBeNull();
	});

	it('Live (LV3): polls the watermark, refreshes by itself when idle as a live query, announces once, pulses the changed card, carries ?live=1', async () => {
		history.replaceState(null, '', '/surveys/s1/results');
		const s = stub();
		await setup({ source: s.source, minRefreshMs: 0 });
		await screen.findByRole('list', { name: 'Questions' });
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
		const toggle = screen.getByTestId('live-toggle');
		expect(toggle.getAttribute('role')).toBe('switch');
		expect(toggle.getAttribute('aria-checked')).toBe('false');
		expect(screen.queryByTestId('live-status')).toBeNull();
		await fireEvent.click(toggle);
		expect(toggle.getAttribute('aria-checked')).toBe('true');
		await tick();
		expect(location.search).toBe('?live=1');
		await vi.advanceTimersByTimeAsync(0);
		expect(s.server.polls).toBe(1);
		expect(screen.getByTestId('live-status').textContent).toBe('Checking every 1 s');
		expect(s.queries).toHaveLength(1);

		s.server.arrive();
		await vi.advanceTimersByTimeAsync(1000);
		await tick();
		expect(s.server.polls).toBe(2);
		expect(s.queries).toHaveLength(2);
		expect(s.queries[1].live).toBe(true);
		expect(screen.getByTestId('results-count').textContent).toContain('6 responses');
		expect(screen.getByTestId('live-announce').textContent).toBe('Results updated: 6 responses.');
		expect(screen.queryByTestId('live-badge')).toBeNull();
		expect(cardOf('Fruit?').getAttribute('data-pulse')).toBe('true');
		expect(cardOf('Age?').getAttribute('data-pulse')).toBeNull();
		expect(screen.getByTestId('live-status').textContent).toMatch(/^Checking every 1 s · updated \d\d:\d\d$/);
		await vi.advanceTimersByTimeAsync(2000);
		expect(cardOf('Fruit?').getAttribute('data-pulse')).toBeNull();
		expect(s.queries).toHaveLength(2); // nothing changed: nothing re-asked

		await fireEvent.click(screen.getByTestId('live-toggle'));
		await tick();
		expect(location.search).toBe('');
		await vi.advanceTimersByTimeAsync(5000);
		expect(s.server.polls).toBe(4);
		history.replaceState(null, '', '/');
	});

	it('Live (LV3): busy means "N new responses · Refresh" (a manual query); a text page never refreshes by itself', async () => {
		const s = stub();
		await setup({ source: s.source, minRefreshMs: 0 });
		await screen.findByRole('list', { name: 'Questions' });
		const why = cardOf('Why?');
		await fireEvent.click(within(why).getByRole('button', { name: 'Show answers' }));
		await within(why).findByText('Answers 1–2 of 3');
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
		await fireEvent.click(screen.getByTestId('live-toggle'));
		await vi.advanceTimersByTimeAsync(0);
		// Unapplied filter changes mean the researcher is working: badge, don't yank.
		await fireEvent.change(screen.getByLabelText('Responses'), { target: { value: 'all' } });
		s.server.arrive();
		await vi.advanceTimersByTimeAsync(1000);
		await tick();
		expect(screen.getByTestId('live-badge').textContent).toBe('1 new response');
		expect(screen.getByTestId('results-count').textContent).toContain('5 responses');
		expect(s.queries).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(3000);
		expect(s.queries).toHaveLength(1); // still working: still only the badge
		expect(within(why).queryByTestId('text-stale')).toBeNull();

		await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
		await vi.advanceTimersByTimeAsync(0);
		await tick();
		expect(s.queries).toHaveLength(2);
		expect(s.queries[1].live).toBeUndefined(); // a click is a manual read (results.read)
		expect(s.queries[1].status).toBe('complete'); // the unapplied draft stays a draft
		expect(screen.getByTestId('results-count').textContent).toContain('6 responses');
		expect(screen.queryByTestId('live-badge')).toBeNull();
		expect(screen.getByText('Changes not applied yet.')).toBeTruthy();
		// LV-D8: the text page kept its answers and offers a reload.
		expect(within(why).getByText('Answers 1–2 of 3')).toBeTruthy();
		expect(within(why).getByTestId('text-stale').textContent).toContain('New answers have arrived');
		expect(s.texts).toHaveLength(1);
		await fireEvent.click(within(why).getByRole('button', { name: 'Reload answers' }));
		await vi.advanceTimersByTimeAsync(0);
		await tick();
		expect(s.texts).toHaveLength(2);
		expect(within(why).queryByTestId('text-stale')).toBeNull();
	});

	it('Live (LV3): opens on from ?live=1; without a watermark source there is no toggle', async () => {
		history.replaceState(null, '', '/surveys/s1/results?live=1');
		const s = stub();
		await setup({ source: s.source });
		await screen.findByRole('list', { name: 'Questions' });
		await waitFor(() => expect(screen.getByTestId('live-toggle').getAttribute('aria-checked')).toBe('true'));
		await waitFor(() => expect(s.server.polls).toBe(1));
		history.replaceState(null, '', '/');

		const bare = stub();
		delete bare.source.watermark;
		render(ResultsView, { surveyId: 's2', survey: SURVEY, publishedVersions: 1, source: bare.source });
		await waitFor(() => expect(screen.getAllByRole('list', { name: 'Questions' })).toHaveLength(2));
		expect(screen.getAllByTestId('live-toggle')).toHaveLength(1);
	});

	// axe walks every card, chart SVG included, through jsdom's getComputedStyle: ~1.3 s on a
	// laptop, ~6 s on a 4-core CI runner beside the other vitest workers. It is CPU-bound, with
	// no state to wait on, so it gets a budget past vitest's 5 s default.
	it('passes axe with cards, tables and a filter row', async () => {
		const { t } = await setup();
		await fireEvent.click(within(cardOf('Fruit?')).getByRole('button', { name: 'Table view' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Add answer filter' }));
		const res = await axe.run(t.container, {
			rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }
		});
		expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	}, AXE_TIMEOUT);
});
