import '@testing-library/svelte/vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fixture from '../fixtures/results.json';
import { ResultsController, type ResultsSource } from '../results.svelte';
import type { Card, ResultsExportRequest, ResultsResponse } from '../types';
import ExportDialog from './ExportDialog.svelte';

// The export dialog (task V4) in jsdom: settings, the small-cell warning, the caption,
// the audit call before a download, its refusal, and axe. Figures themselves are checked
// in the e2e run (a real browser draws them).

const clone = <T,>(x: T): T => structuredClone(x);

function source(refuse = false) {
	const records: ResultsExportRequest[] = [];
	const s: ResultsSource = {
		async query() {
			return { ok: true, data: clone(fixture.plain) as unknown as ResultsResponse };
		},
		async text() {
			return { ok: false, status: 404, message: 'no' };
		},
		async recordExport(body) {
			records.push(clone(body));
			if (refuse) return { ok: false, status: 403, message: 'Forbidden' };
			return { ok: true, data: { recorded: true, queryHash: 'h', versions: [1], formats: body.formats } };
		},
		async platform() {
			return { name: 'osp', version: 'test' };
		}
	};
	return { s, records };
}

async function setup(format: 'csv' | 'png' = 'csv', refuse = false) {
	const { s, records } = source(refuse);
	const controller = new ResultsController(s, 1);
	await controller.load();
	const card = controller.response!.cards.find((c) => c.question === 'fruit') as Card;
	const t = render(ExportDialog, { open: true, format, card, controller });
	const dialog = await screen.findByRole('dialog', { name: 'Export: Fruit?' });
	return { t, controller, records, dialog };
}

const clicked: string[] = [];
beforeEach(() => {
	clicked.length = 0;
	URL.createObjectURL = vi.fn(() => 'blob:x');
	URL.revokeObjectURL = vi.fn();
	vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
		clicked.push(this.download);
	});
});
afterEach(() => vi.restoreAllMocks());

describe('ExportDialog', () => {
	it('warns about small shown cells until "Hide counts below k" is on', async () => {
		const { dialog, controller } = await setup('csv');
		expect(within(dialog).getByTestId('small-cells').textContent?.replace(/\s+/g, ' ')).toContain('2 shown cells have fewer than 5 responses');
		const preview = within(dialog).getByRole('region', { name: 'CSV preview' });
		expect(preview.textContent).toContain('apple,Apple,,,2,66.6667');
		await fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Hide counts below k' }));
		expect(controller.exports.k).toBe(5);
		expect(within(dialog).queryByTestId('small-cells')).toBeNull();
		expect(preview.textContent).toContain('apple,Apple,,,,,,,<5');
	});

	it('records the export (formats, cards, k) before downloading the file', async () => {
		const { dialog, records } = await setup('csv');
		await fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Hide counts below k' }));
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Download' }));
		await waitFor(() => expect(clicked).toEqual(['fruit.csv']));
		expect(records).toEqual([
			{
				query: { versions: [1], status: 'complete', denominator: 'answered', intervals: false },
				cards: ['fruit'],
				formats: ['csv'],
				scope: 'card',
				suppressBelow: 5
			}
		]);
		expect(within(dialog).getByRole('status').textContent).toContain('Downloaded fruit.csv.');
	});

	it('downloads nothing when the audit is refused', async () => {
		const { dialog } = await setup('csv', true);
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Download' }));
		expect((await within(dialog).findByRole('alert')).textContent).toContain('owner or editor access');
		expect(clicked).toEqual([]);
	});

	it('writes the caption automatically, keeps edits, and can go back', async () => {
		const { dialog, controller } = await setup('png');
		const caption = within(dialog).getByLabelText('Caption') as HTMLTextAreaElement;
		expect(caption.value).toBe('Fruit? (fruit). Version 1; Complete responses only; Denominator: answered. n = 3 responses.');
		expect(within(dialog).getByTestId('png-size').textContent).toContain('85 mm at 300 DPI = 1004');
		await fireEvent.input(caption, { target: { value: 'My caption' } });
		expect(controller.exports.caption('fruit')).toBe('My caption');
		await fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Hide counts below k' }));
		expect(caption.value).toBe('My caption'); // an edited caption is the researcher's
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Use the automatic caption' }));
		expect(caption.value).toContain('Counts below 5 hidden (shown as "n<5"; 2 cells).');
		await fireEvent.click(within(dialog).getByRole('radio', { name: /Double column, 180 mm/ }));
		expect(within(dialog).getByTestId('png-size').textContent).toContain('180 mm at 300 DPI = 2126');
	});

	it('passes axe', async () => {
		const { dialog } = await setup('png');
		const res = await axe.run(dialog, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
		expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	});
});
