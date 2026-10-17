import '@testing-library/svelte/vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import fixture from './fixtures/results.json';
import { toSettings, emptyState } from './layouts';
import type { LayoutSource } from './layouts.svelte';
import type { ResultsSource } from './results.svelte';
import ResultsView from './ResultsView.svelte';
import type { LayoutSettings, ResultsLayout, ResultsQuery, ResultsResponse } from './types';

// Saved layouts on the Results page (task V5b) in jsdom, against an in-memory layout store
// that behaves like V5a's (unique names: 409; one default). Opening the default, the
// unsaved-changes indicator, Save / Save as / rename / delete / default, a refused layout
// (422), an unsuitable chart id, keyboard reorder, hide / show and axe.

const clone = <T,>(x: T): T => structuredClone(x);
const QUESTIONS = fixture.plain.cards.map((c) => c.question);

function store(initial: { name: string; settings: LayoutSettings; isDefault?: boolean }[] = []) {
	let n = 0;
	const now = '2026-10-17T12:00:00Z';
	const make = (name: string, settings: LayoutSettings, isDefault = false): ResultsLayout => ({
		id: `lay${++n}`,
		surveyId: 's1',
		name,
		settings: clone(settings),
		isDefault,
		createdBy: 'u',
		createdAt: now,
		updatedBy: 'u',
		updatedAt: now
	});
	let rows = initial.map((l) => make(l.name, l.settings, l.isDefault));
	const calls: { op: string; body?: unknown }[] = [];
	let refuseNext: number | null = null;
	const listed = () => ({
		surveyId: 's1',
		layouts: [...rows].sort((a, b) => a.name.localeCompare(b.name)).map(clone),
		defaultLayoutId: rows.find((r) => r.isDefault)?.id ?? null
	});
	const refused = () => {
		if (refuseNext === null) return null;
		const status = refuseNext;
		refuseNext = null;
		return {
			ok: false as const,
			status,
			body: { code: 'layout.schema', message: 'That is not a valid results layout.', diagnostics: [{ code: 'layout.schema', message: 'Extra inputs are not permitted', pointer: '/cards/0/colour' }] }
		};
	};
	const source: LayoutSource = {
		async list() {
			calls.push({ op: 'list' });
			return { ok: true, data: listed() };
		},
		async create(body) {
			calls.push({ op: 'create', body: clone(body) });
			const r = refused();
			if (r) return r;
			if (rows.some((x) => x.name === body.name)) return { ok: false, status: 409, body: { message: 'The survey already has a layout with that name.' } };
			if (body.isDefault) rows.forEach((x) => (x.isDefault = false));
			const row = make(body.name, body.settings, body.isDefault);
			rows.push(row);
			return { ok: true, data: clone(row) };
		},
		async update(id, body) {
			calls.push({ op: 'update', body: clone(body) });
			const r = refused();
			if (r) return r;
			const row = rows.find((x) => x.id === id);
			if (!row) return { ok: false, status: 404, body: { message: 'Layout not found.' } };
			if (body.name && rows.some((x) => x.name === body.name && x.id !== id)) return { ok: false, status: 409, body: {} };
			if (body.name) row.name = body.name;
			if (body.settings) row.settings = clone(body.settings);
			return { ok: true, data: clone(row) };
		},
		async remove(id) {
			calls.push({ op: 'remove', body: id });
			rows = rows.filter((x) => x.id !== id);
			return { ok: true, data: null };
		},
		async setDefault(id) {
			calls.push({ op: 'default', body: id });
			rows.forEach((x) => (x.isDefault = x.id === id));
			return { ok: true, data: listed() };
		}
	};
	return { source, calls, rows: () => rows, refuse: (status: number) => (refuseNext = status) };
}

function results(layouts: LayoutSource) {
	const queries: ResultsQuery[] = [];
	const source: ResultsSource = {
		async query(body) {
			queries.push(clone(body));
			return { ok: true, data: clone(fixture.plain) as unknown as ResultsResponse };
		},
		async text() {
			return { ok: false, status: 404, message: 'no' };
		},
		async recordExport() {
			return { ok: false, status: 403, message: 'no' };
		},
		layouts
	};
	return { source, queries };
}

/** A layout as the page would save it, from a few changes to the defaults. */
function paperLayout(): LayoutSettings {
	const s = emptyState(1);
	s.filters.denominator = 'shown';
	s.filters.split = { kind: 'condition', id: 'arm' };
	s.cards.chosen = { fruit: 'donut', age: 'likert' }; // likert does not suit a number
	s.cards.hidden = { why: true };
	s.order = ['grid', 'fruit'];
	return toSettings(s, 1, QUESTIONS);
}

async function setup(initial: Parameters<typeof store>[0] = []) {
	const st = store(initial);
	const r = results(st.source);
	const t = render(ResultsView, { surveyId: 's1', survey: { variables: [{ kind: 'assigned', id: 'arm', levels: ['a', 'b'] }] }, publishedVersions: 1, source: r.source });
	await screen.findByRole('list', { name: 'Questions' });
	return { t, ...st, queries: r.queries };
}

const titles = () => within(screen.getByRole('list', { name: 'Questions' })).queryAllByRole('heading', { level: 3 }).map((h) => h.textContent);
const unsaved = () => !screen.getByTestId('layout-unsaved').hidden;
const picker = () => screen.getByLabelText('Layout') as HTMLSelectElement;

describe('saved layouts on the Results page', () => {
	it('opens the default layout: its query, order, charts and hidden cards; nothing unsaved', async () => {
		const { queries } = await setup([
			{ name: 'Other', settings: toSettings(emptyState(1), 1) },
			{ name: 'Paper', settings: paperLayout(), isDefault: true }
		]);
		await waitFor(() => expect(titles()[0]).toBe('Grid'));
		expect(queries[0]).toEqual({ versions: [1], status: 'complete', denominator: 'shown', intervals: false, split: { condition: 'arm', excludeMissing: false } });
		expect(queries).toHaveLength(1);
		expect(picker().selectedOptions[0].textContent).toBe('Paper (opens by default)');
		expect(titles().slice(0, 3)).toEqual(['Grid', 'Fruit?', 'Satisfied?']);
		expect(titles()).not.toContain('Why?');
		expect(screen.getByTestId('hidden-card').textContent).toContain('Why?');
		const fruit = screen.getByRole('article', { name: 'Fruit?' });
		expect((within(fruit).getByRole('combobox', { name: 'Chart' }) as HTMLSelectElement).value).toBe('donut');
		// Unsuitable chart id: the default instead, and a notice.
		expect((within(screen.getByRole('article', { name: 'Age?' })).getByRole('combobox', { name: 'Chart' }) as HTMLSelectElement).value).toBe('histogram');
		expect(screen.getByTestId('layout-notices').textContent).toContain('Age?: the layout\'s chart “Diverging stacked bars” does not suit this question');
		expect(unsaved()).toBe(false);
	});

	it('with no default, shows the default view; a change is unsaved until saved as a layout', async () => {
		const { calls, rows } = await setup();
		expect(picker().value).toBe('');
		expect(unsaved()).toBe(false);
		expect(screen.queryByRole('button', { name: 'Save layout' })).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: 'Hide Fruit?' }));
		expect(unsaved()).toBe(true);
		await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Show Fruit?' })));

		await fireEvent.click(screen.getByRole('button', { name: 'Save as…' }));
		const dialog = await screen.findByRole('dialog', { name: 'Save layout as' });
		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: '  ' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
		expect(within(dialog).getByText('Enter a name for the layout.')).toBeTruthy();
		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Paper' } });
		await fireEvent.click(within(dialog).getByLabelText('Open this layout by default'));
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		const created = calls.find((c) => c.op === 'create')!.body as { name: string; settings: LayoutSettings; isDefault: boolean };
		expect(created.name).toBe('Paper');
		expect(created.isDefault).toBe(true);
		expect(created.settings.cards!.find((c) => c.question === 'fruit')!.hidden).toBe(true);
		expect(rows()[0].isDefault).toBe(true);
		expect(picker().selectedOptions[0].textContent).toBe('Paper (opens by default)');
		expect(screen.getByTestId('layout-status').textContent).toBe('Saved as “Paper”, the default layout.');
		expect(unsaved()).toBe(false);
	});

	it('Save writes the open layout; a duplicate name (409) and a refused layout (422) say why', async () => {
		const { calls, refuse } = await setup([
			{ name: 'Paper', settings: toSettings(emptyState(1), 1), isDefault: true },
			{ name: 'Talk', settings: toSettings(emptyState(1), 1) }
		]);
		await waitFor(() => expect(picker().value).not.toBe(''));
		const fruit = screen.getByRole('article', { name: 'Fruit?' });
		await fireEvent.change(within(fruit).getByRole('combobox', { name: 'Chart' }), { target: { value: 'bars-sorted' } });
		expect(unsaved()).toBe(true);
		await fireEvent.click(screen.getByRole('button', { name: 'Save layout' }));
		await waitFor(() => expect(unsaved()).toBe(false));
		const saved = calls.filter((c) => c.op === 'update').at(-1)!.body as { settings: LayoutSettings };
		expect(saved.settings.cards!.find((c) => c.question === 'fruit')!.chart).toBe('bars-sorted');
		expect(screen.getByTestId('layout-status').textContent).toBe('Saved “Paper”.');

		// 422: the server's reason, shown as an alert.
		await fireEvent.change(within(fruit).getByRole('combobox', { name: 'Chart' }), { target: { value: 'donut' } });
		refuse(422);
		await fireEvent.click(screen.getByRole('button', { name: 'Save layout' }));
		expect((await screen.findByTestId('layout-error')).textContent).toContain(
			'The layout could not be saved: Extra inputs are not permitted (at /cards/0/colour).'
		);
		expect(unsaved()).toBe(true);

		// 409 on rename: the dialog stays open and says so.
		await fireEvent.click(screen.getByRole('button', { name: 'Rename…' }));
		const dialog = await screen.findByRole('dialog', { name: 'Rename layout' });
		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Talk' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Rename' }));
		expect((await within(dialog).findByTestId('layout-dialog-error')).textContent).toContain(
			'There is already a layout called “Talk”. Choose another name.'
		);
		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Paper v2' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Rename' }));
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(picker().selectedOptions[0].textContent).toBe('Paper v2 (opens by default)');
	});

	it('switches layouts, changes the default and deletes', async () => {
		const talk = emptyState(1);
		talk.filters.status = 'all';
		talk.cards.hidden = { fruit: true };
		const { calls, queries } = await setup([
			{ name: 'Paper', settings: toSettings(emptyState(1), 1), isDefault: true },
			{ name: 'Talk', settings: toSettings(talk, 1, QUESTIONS) }
		]);
		await waitFor(() => expect(picker().value).not.toBe(''));
		const talkId = [...picker().options].find((o) => o.textContent === 'Talk')!.value;
		await fireEvent.change(picker(), { target: { value: talkId } });
		await waitFor(() => expect(queries.at(-1)!.status).toBe('all'));
		await waitFor(() => expect(screen.getByRole('button', { name: 'Show Fruit?' })).toBeTruthy());
		expect(unsaved()).toBe(false);

		await fireEvent.click(screen.getByRole('button', { name: 'Open by default' }));
		await waitFor(() => expect(picker().selectedOptions[0].textContent).toBe('Talk (opens by default)'));
		expect(calls.find((c) => c.op === 'default')!.body).toBe(talkId);
		await fireEvent.click(screen.getByRole('button', { name: 'Don’t open by default' }));
		await waitFor(() => expect(picker().selectedOptions[0].textContent).toBe('Talk'));

		await fireEvent.click(screen.getByRole('button', { name: 'Delete…' }));
		const dialog = await screen.findByRole('dialog', { name: 'Delete layout?' });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Delete layout' }));
		await waitFor(() => expect(picker().value).toBe(''));
		expect([...picker().options].map((o) => o.textContent)).toEqual(['Default view (no saved layout)', 'Paper']);
		expect(screen.getByTestId('layout-status').textContent).toBe('Deleted “Talk”.');
		// The page keeps the deleted layout's settings, now unsaved.
		expect(unsaved()).toBe(true);

		// Back to the default view: the defaults again.
		await fireEvent.change(picker(), { target: { value: '' } });
		await waitFor(() => expect(queries.at(-1)!.status).toBe('complete'));
		expect(unsaved()).toBe(false);
	});

	it('moves cards with the keyboard (focus stays on the handle) and says where', async () => {
		await setup();
		const handle = screen.getByRole('button', { name: 'Move Satisfied?' });
		handle.focus();
		await fireEvent.keyDown(handle, { key: 'ArrowUp' });
		await waitFor(() => expect(titles().slice(0, 2)).toEqual(['Satisfied?', 'Fruit?']));
		await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Move Satisfied?' })));
		expect(screen.getByTestId('move-status').textContent).toBe('Satisfied? moved to position 1 of 10.');
		expect(unsaved()).toBe(true);
		await fireEvent.keyDown(screen.getByRole('button', { name: 'Move Satisfied?' }), { key: 'End' });
		await waitFor(() => expect(titles().at(-1)).toBe('Satisfied?'));
		await fireEvent.keyDown(screen.getByRole('button', { name: 'Move Satisfied?' }), { key: 'Home' });
		await fireEvent.keyDown(screen.getByRole('button', { name: 'Move Satisfied?' }), { key: 'ArrowDown' });
		await waitFor(() => expect(titles().slice(0, 2)).toEqual(['Fruit?', 'Satisfied?']));
		// Moved back: the survey order again, nothing to save.
		expect(unsaved()).toBe(false);
	});

	it('moves a card by dragging its handle onto another card', async () => {
		await setup();
		const handle = screen.getByRole('button', { name: 'Move Grid' });
		const target = screen.getByRole('article', { name: 'Fruit?' }).closest('li')!;
		await fireEvent.dragStart(handle);
		await fireEvent.dragOver(target);
		await fireEvent.drop(target);
		await waitFor(() => expect(titles()[0]).toBe('Grid'));
	});

	it('passes axe with the layout bar, a notice and a hidden card', async () => {
		const { t } = await setup([{ name: 'Paper', settings: paperLayout(), isDefault: true }]);
		await screen.findByTestId('layout-notices');
		const res = await axe.run(t.container, {
			rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }
		});
		expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	});
});
