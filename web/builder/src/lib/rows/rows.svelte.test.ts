import '@testing-library/svelte/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import RowsEditor from './RowsEditor.svelte';
import type { RowOp, RowsOutcome, RowsQuestion } from './model';

// The rows editor on its own (the dialog around it is ui-components' Dialog): labels,
// keyboard reorder, required switch, delete (and the "still used" confirmation), a11y.

const Q: RowsQuestion = {
	id: 'taste',
	label: 'Rate these drinks',
	required: true,
	rows: [
		{ id: 'tea', label: 'Tea', required: null },
		{ id: 'coffee', label: { en: 'Coffee', de: 'Kaffee' }, required: null },
		{ id: 'cocoa', label: 'Cocoa', required: false }
	]
};

const SURVEY = {
	blocks: [{ id: 'b', pages: [{ id: 'p', items: [{ id: 'cups', type: 'integer', label: 'How many cups?' }] }] }]
};

function setup(opts: { lang?: string; reply?: (ops: RowOp[]) => RowsOutcome } = {}) {
	const sent: { ops: RowOp[]; quiet?: readonly string[] }[] = [];
	const t = render(RowsEditor, {
		question: Q,
		lang: opts.lang,
		defaultLanguage: 'en',
		pointer: '/blocks/0/pages/0/items/1/rows',
		survey: SURVEY,
		diagnostics: [
			{ severity: 'warning', code: 'text.missing_translation', message: 'No German text', pointer: '/blocks/0/pages/0/items/1/rows/0/label' }
		],
		submit: (ops: RowOp[], o?: { quiet?: readonly string[] }) => {
			sent.push({ ops, quiet: o?.quiet });
			return Promise.resolve(opts.reply ? opts.reply(ops) : { status: 'applied' });
		}
	});
	const label = (n: number) => screen.getByRole('textbox', { name: `Label for row ${n}` }) as HTMLInputElement;
	return { t, sent, label };
}

describe('RowsEditor', () => {
	it('shows each row with its variable, required state and diagnostics', () => {
		const { t, label } = setup();
		expect([1, 2, 3].map((n) => label(n).value)).toEqual(['Tea', 'Coffee', 'Cocoa']);
		expect(t.container.querySelectorAll('code.var')).toHaveLength(3);
		expect(t.container.textContent).toContain('taste_coffee');
		const switches = screen.getAllByRole('switch');
		expect(switches.map((s) => s.getAttribute('aria-checked'))).toEqual(['true', 'true', 'false']);
		expect(label(1).getAttribute('aria-describedby')).toBeTruthy();
		expect(t.container.textContent).toContain('No German text');
	});

	it('renames on Enter, once, in the editing language', async () => {
		const { sent, label } = setup({ lang: 'de' });
		expect(label(1).value).toBe('Tea'); // a plain label is every language's
		expect(label(2).value).toBe('Kaffee');
		await fireEvent.input(label(2), { target: { value: 'Filterkaffee' } });
		await fireEvent.keyDown(label(2), { key: 'Enter' });
		await fireEvent.blur(label(2));
		expect(sent).toEqual([
			{
				ops: [{ op: 'rename_matrix_row', params: { question: 'taste', row: 'coffee', label: { en: 'Coffee', de: 'Filterkaffee' } } }],
				quiet: undefined
			}
		]);
	});

	it('Escape drops a typed label; unchanged text sends nothing', async () => {
		const { sent, label } = setup();
		await fireEvent.input(label(1), { target: { value: 'Green' } });
		await fireEvent.keyDown(label(1), { key: 'Escape' });
		expect(label(1).value).toBe('Tea');
		await fireEvent.input(label(1), { target: { value: 'Tea' } });
		await fireEvent.blur(label(1));
		expect(sent).toEqual([]);
	});

	it('Alt+↓ / Alt+↑ move a row; edges send nothing', async () => {
		const { sent, label } = setup();
		await fireEvent.keyDown(label(1), { key: 'ArrowDown', altKey: true });
		await fireEvent.keyDown(label(1), { key: 'ArrowUp', altKey: true });
		await fireEvent.keyDown(screen.getByRole('button', { name: 'Move Cocoa' }), { key: 'ArrowUp', altKey: true });
		expect(sent.map((s) => s.ops[0])).toEqual([
			{ op: 'move_matrix_row', params: { question: 'taste', row: 'tea', index: 1 } },
			{ op: 'move_matrix_row', params: { question: 'taste', row: 'cocoa', index: 1 } }
		]);
	});

	it('the required switch sets the row, or lets it follow the grid again', async () => {
		const { sent } = setup();
		await fireEvent.click(screen.getByRole('switch', { name: 'Required: Tea' }));
		await fireEvent.click(screen.getByRole('switch', { name: 'Required: Cocoa' }));
		expect(sent.map((s) => s.ops[0].params)).toEqual([
			{ question: 'taste', row: 'tea', required: false },
			{ question: 'taste', row: 'cocoa', required: null }
		]);
	});

	it('adds a row at the end', async () => {
		const { sent } = setup();
		await fireEvent.click(screen.getByRole('button', { name: /Add row/ }));
		expect(sent[0].ops).toEqual([{ op: 'add_matrix_row', params: { question: 'taste', label: '' } }]);
	});

	it('deletes quietly first; a row still in use asks, then deletes with force', async () => {
		const { sent } = setup({
			reply: (ops) =>
				ops[0].params.force
					? { status: 'applied' }
					: {
							status: 'rejected',
							diagnostics: [
								{ severity: 'error', code: 'op.dangling_ref', message: "row 'tea' is still referenced", pointer: '/blocks/0/pages/0/items/0/showIf' },
								{ severity: 'error', code: 'op.dangling_ref', message: "refers to 'taste_tea'", pointer: '/blocks/0/pages/0/items/0/showIf' }
							]
						}
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Delete Tea' }));
		expect(sent[0]).toEqual({ ops: [{ op: 'delete_matrix_row', params: { question: 'taste', row: 'tea' } }], quiet: ['op.dangling_ref'] });
		const warning = await screen.findByTestId('row-delete-warning');
		expect(warning.textContent).toContain('taste_tea');
		expect(warning.textContent).toContain('How many cups? (condition)');
		await fireEvent.click(screen.getByRole('button', { name: 'Delete anyway' }));
		await waitFor(() => expect(sent).toHaveLength(2));
		expect(sent[1].ops[0].params).toEqual({ question: 'taste', row: 'tea', force: true });
	});

	it('keeping the row sends nothing more', async () => {
		const { sent } = setup({
			reply: () => ({ status: 'rejected', diagnostics: [{ severity: 'error', code: 'op.dangling_ref', message: 'x', pointer: '' }] })
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Delete Coffee' }));
		await fireEvent.click(await screen.findByRole('button', { name: 'Keep row' }));
		await waitFor(() => expect(screen.queryByTestId('row-delete-warning')).toBeNull());
		expect(sent).toHaveLength(1);
	});

	it('has no axe violations', async () => {
		const { t } = setup();
		const results = await axe.run(t.container, { rules: { 'color-contrast': { enabled: false } } });
		expect(results.violations.map((v) => v.id)).toEqual([]);
	});
});
