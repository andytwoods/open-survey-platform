import '@testing-library/svelte/vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import ImportDialog from './ImportDialog.svelte';
import type { CreateRequest, ImportClient, ImportPreview, ImportRequest } from './model';

// The Import dialog (task IM1) in jsdom against a fake client: picking a file previews it
// (what will be created, losses, warnings, notes), Import sends the same text with the
// detected format and an edited title, an unreadable file shows the server's reasons, a
// refused import keeps the preview, and axe is clean.

const preview: ImportPreview = {
	format: 'lss',
	ok: true,
	title: 'Coffee and sleep',
	summary: {
		title: 'Coffee and sleep',
		languages: ['en', 'de'],
		blocks: 2,
		pages: 2,
		questions: 5,
		byType: { single: 2, text: 2, note: 1 },
		choiceLists: 0,
		variables: 1,
		quotas: 0,
		flowNodes: 3,
		conditions: 1,
		losses: 1,
		warnings: 1,
		infos: 1
	},
	diagnostics: [
		{ format: 'lss', severity: 'loss', code: 'lss.question_type', feature: 'type=R', pointer: '/questions/3', message: 'ranking questions are not supported', target: null },
		{ format: 'lss', severity: 'warning', code: 'lss.soft_mandatory', feature: 'mandatory=S', pointer: '/questions/4', message: 'soft-mandatory: optional here', target: null },
		{ format: 'lss', severity: 'info', code: 'lss.html_stripped', feature: 'html', pointer: '', message: 'HTML formatting was removed', target: null }
	],
	validation: [{ severity: 'warning', code: 'text.missing_translation', message: 'no text for: de', pointer: '/x' }]
};

function fakeClient(opts: { previewOk?: boolean; createOk?: boolean } = {}) {
	const previews: ImportRequest[] = [];
	const creates: CreateRequest[] = [];
	const client: ImportClient = {
		async preview(req) {
			previews.push(req);
			if (opts.previewOk === false) {
				return {
					kind: 'ok',
					preview: {
						...preview,
						ok: false,
						summary: null,
						title: '',
						diagnostics: [{ format: 'lss', severity: 'error', code: 'lss.not_xml', feature: '', pointer: '', message: 'not well-formed XML', target: null }]
					}
				};
			}
			return { kind: 'ok', preview };
		},
		async create(req) {
			creates.push(req);
			if (opts.createOk === false) return { kind: 'failed', message: 'Not permitted.' };
			return { kind: 'ok', survey: { id: 'new1', title: req.title ?? preview.title } as never, preview };
		}
	};
	return { client, previews, creates };
}

async function pickFile(name = 'coffee.lss', text = '<document/>') {
	const input = screen.getByLabelText('Survey file') as HTMLInputElement;
	const file = new File([text], name, { type: 'text/xml' });
	Object.defineProperty(input, 'files', { value: [file], configurable: true });
	await fireEvent.change(input);
}

describe('ImportDialog', () => {
	it('previews a picked file, then imports it with the edited title', async () => {
		const { client, previews, creates } = fakeClient();
		const onimported = vi.fn();
		render(ImportDialog, { open: true, client, onimported, tenantId: 'lab-a' });
		await pickFile();
		await waitFor(() => expect(screen.getByTestId('import-preview')).toBeTruthy());
		expect(previews).toEqual([{ filename: 'coffee.lss', content: '<document/>' }]);
		expect(screen.getByText(/Read as/).textContent).toContain('LimeSurvey (.lss)');
		const summary = within(screen.getByTestId('import-summary'));
		expect(summary.getByText('5 questions on 2 pages in 2 blocks (2 single choice, 2 text, 1 note)')).toBeTruthy();
		expect(summary.getByText('Languages: en, de')).toBeTruthy();
		expect(screen.getByText(/The editor will show 1 warning/)).toBeTruthy();
		const losses = within(screen.getByTestId('import-losses'));
		expect(losses.getByText(/ranking questions are not supported/)).toBeTruthy();
		expect(losses.getByText('type=R')).toBeTruthy();
		expect(within(screen.getByTestId('import-warnings')).getByText(/soft-mandatory/)).toBeTruthy();
		expect(screen.getByText('Notes (1)')).toBeTruthy();

		const title = screen.getByLabelText('Title') as HTMLInputElement;
		expect(title.value).toBe('Coffee and sleep');
		await fireEvent.input(title, { target: { value: 'Pilot' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Import' }));
		await waitFor(() => expect(onimported).toHaveBeenCalledWith('new1'));
		expect(creates).toEqual([{ filename: 'coffee.lss', content: '<document/>', format: 'lss', title: 'Pilot', tenantId: 'lab-a' }]);

		const results = await axe.run(document.body, { rules: { region: { enabled: false } } });
		expect(results.violations).toEqual([]);
	});

	it('shows why a file could not be read and keeps Import disabled', async () => {
		const { client, creates } = fakeClient({ previewOk: false });
		render(ImportDialog, { open: true, client });
		await pickFile('broken.lss', '<');
		await waitFor(() => expect(screen.getByTestId('import-failed')).toBeTruthy());
		expect(screen.getByText('not well-formed XML')).toBeTruthy();
		expect((screen.getByRole('button', { name: 'Import' }) as HTMLButtonElement).disabled).toBe(true);
		expect(creates).toEqual([]);
	});

	it('a refused import keeps the preview and says why', async () => {
		const { client } = fakeClient({ createOk: false });
		const onimported = vi.fn();
		render(ImportDialog, { open: true, client, onimported });
		await pickFile();
		await waitFor(() => expect(screen.getByTestId('import-preview')).toBeTruthy());
		await fireEvent.click(screen.getByRole('button', { name: 'Import' }));
		await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Not permitted.'));
		expect(screen.getByTestId('import-preview')).toBeTruthy();
		expect(onimported).not.toHaveBeenCalled();
	});
});
