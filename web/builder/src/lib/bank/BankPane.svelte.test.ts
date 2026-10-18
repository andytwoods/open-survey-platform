import '@testing-library/svelte/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import axe from 'axe-core';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { outlineFromSurvey } from '../model/outline';
import { TypeDrag } from '../question-types/type-drag.svelte';

// The Bank section against a mocked API: searching lists items with their badges and the
// "newer version" dot, expanding fetches the document and shows the preview, Insert hands
// the summary and document to the shell, a filter re-searches, axe.

const calls: { path: string; query?: unknown }[] = [];
const PHQ2 = {
	id: 'phq2',
	source: 'bundled',
	kind: 'block',
	title: 'Patient Health Questionnaire-2',
	abbreviation: 'PHQ-2',
	description: 'Two items.',
	tags: ['depression'],
	languages: ['en'],
	licenceClass: 'public-domain',
	version: 1,
	itemCount: 2,
	visibility: null,
	labId: null,
	canEdit: false
};
const MINE = { ...PHQ2, id: 'mine', source: 'lab', title: 'Our scale', abbreviation: null, licenceClass: 'unknown', version: 3, visibility: 'lab', labId: 'lab', canEdit: true };
const DOC = {
	summary: PHQ2,
	version: 1,
	checksum: null,
	document: {
		title: PHQ2.title,
		licence: { class: 'public-domain', holder: 'Pfizer', statement: 'No permission is required.', url: 'https://example.org/terms' },
		citation: { text: 'Kroenke 2003' },
		scoring: { text: 'Sum of the two items.' },
		fragment: {
			choiceLists: [{ id: 'phq_frequency', choices: [{ value: 0, label: 'Not at all' }, { value: 1, label: 'Several days' }] }],
			variables: [{ id: 'phq2_total', kind: 'computed', expr: {} }],
			block: { id: 'phq2_block', title: 'PHQ-2', pages: [{ id: 'p', items: [{ id: 'phq2', type: 'matrix', label: 'Over the last 2 weeks…', choiceList: 'phq_frequency', rows: [{ id: 'q1', label: 'Little interest' }, { id: 'q2', label: 'Feeling down' }] }] }] }
		}
	}
};

vi.mock('../api', () => ({
	api: {
		GET: vi.fn(async (path: string, opts?: { params?: { query?: unknown; path?: { item_id?: string } } }) => {
			calls.push({ path, query: opts?.params?.query });
			if (path === '/api/bank') {
				const q = (opts?.params?.query ?? {}) as { q?: string; source?: string };
				let items = [MINE, PHQ2];
				if (q.source) items = items.filter((i) => i.source === q.source);
				if (q.q) items = items.filter((i) => i.title.toLowerCase().includes(q.q!.toLowerCase()));
				return { data: { tenantId: 't', items, total: items.length, page: 1, pageSize: 50, canManage: true, canShare: true, hostSharing: true }, response: { status: 200 } };
			}
			if (path === '/api/bank/{item_id}') {
				const id = opts?.params?.path?.item_id;
				if (id === 'phq2') return { data: DOC, response: { status: 200 } };
				return { error: { message: 'Bank item not found.' }, response: { status: 404 } };
			}
			return { error: { message: 'no' }, response: { status: 404 } };
		})
	}
}));

import BankPane from './BankPane.svelte';

const SURVEY = {
	id: 's',
	metadata: { languages: ['en'] },
	blocks: [{ id: 'b1', source: { bank: 'mine', version: 2, library: 'lab' }, pages: [{ id: 'p1', items: [{ id: 'qa', type: 'text', label: 'A' }] }] }],
	flow: [{ type: 'block', id: 'n1', block: 'b1' }]
};

afterEach(() => {
	calls.length = 0;
});

function setup() {
	const inserted: unknown[] = [];
	const t = render(BankPane, {
		props: {
			drag: new TypeDrag(),
			roots: outlineFromSurvey(SURVEY),
			survey: SURVEY,
			collapsed: false,
			oninsert: (s: unknown, item: unknown) => inserted.push([s, item]),
			ondrop: () => {},
			onplace: () => {}
		}
	});
	return { t, inserted };
}

describe('BankPane', () => {
	it('lists the bank with badges, marks a newer version, previews on expand and inserts', async () => {
		const { t, inserted } = setup();
		await waitFor(() => expect(screen.getAllByRole('button', { name: /^Insert / })).toHaveLength(2));
		const list = screen.getByRole('list', { name: 'Bank items' });
		expect(list.textContent).toContain('Public domain');
		expect(list.textContent).toContain('Licence not stated');
		// The survey holds `mine` at v2; the bank has v3.
		expect(screen.getByText('newer version available')).toBeTruthy();
		expect(t.container.querySelector('[data-bank-result="phq2"] .newer')).toBeNull();

		await fireEvent.click(screen.getByRole('button', { name: /^Patient Health Questionnaire-2/ }));
		await waitFor(() => expect(screen.getByTestId('bank-preview')).toBeTruthy());
		const preview = screen.getByTestId('bank-preview');
		expect(preview.textContent).toContain('Little interest');
		expect(preview.textContent).toContain('phq2_total');
		expect(preview.textContent).toContain('No permission is required.');

		await fireEvent.click(screen.getByRole('button', { name: 'Insert Patient Health Questionnaire-2' }));
		await waitFor(() => expect(inserted).toHaveLength(1));
		expect((inserted[0] as [{ id: string }, { version: number }])[0].id).toBe('phq2');
		expect((inserted[0] as [unknown, { version: number }])[1].version).toBe(1);
		// The document was fetched once (cached between the preview and the insert).
		expect(calls.filter((c) => c.path === '/api/bank/{item_id}')).toHaveLength(1);

		const res = await axe.run(t.container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
		expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	});

	it('the source filter and the search re-query the API', async () => {
		setup();
		await waitFor(() => expect(screen.getAllByRole('button', { name: /^Insert / })).toHaveLength(2));
		const source = screen.getByRole('combobox', { name: 'Source' });
		await fireEvent.change(source, { target: { value: 'bundled' } });
		await waitFor(() => expect(screen.getAllByRole('button', { name: /^Insert / })).toHaveLength(1));
		expect(calls.at(-1)).toEqual({ path: '/api/bank', query: { pageSize: 50, source: 'bundled' } });
		const search = screen.getByRole('searchbox', { name: 'Search the bank' });
		await fireEvent.input(search, { target: { value: 'nothing here' } });
		await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Nothing matches'), { timeout: 2000 });
		expect(calls.at(-1)).toEqual({ path: '/api/bank', query: { pageSize: 50, q: 'nothing here', source: 'bundled' } });
	});

	it('an item that cannot be read says so instead of inserting', async () => {
		const { inserted } = setup();
		await waitFor(() => expect(screen.getAllByRole('button', { name: /^Insert / })).toHaveLength(2));
		await fireEvent.click(screen.getByRole('button', { name: 'Insert Our scale' }));
		await new Promise((r) => setTimeout(r, 20));
		expect(inserted).toEqual([]);
	});
});
