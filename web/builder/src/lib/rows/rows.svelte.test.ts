import '@testing-library/svelte/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import { activate, blurField, editable, typeInto } from '../richtext/test-utils';
import RowsEditor from './RowsEditor.svelte';
import type { RowOp, RowsOutcome, RowsQuestion } from './model';

// The rows editor on its own (the dialog around it is ui-components' Dialog): labels as
// inline rich-text fields (RT5: read-only textboxes until focused), keyboard reorder,
// required switch, delete (and the "still used" confirmation), a11y.

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

function setup(opts: { lang?: string; reply?: (ops: RowOp[]) => RowsOutcome; question?: RowsQuestion } = {}) {
	const sent: { ops: RowOp[]; quiet?: readonly string[] }[] = [];
	const t = render(RowsEditor, {
		question: opts.question ?? Q,
		lang: opts.lang,
		defaultLanguage: 'en',
		pointer: '/blocks/0/pages/0/items/1/rows',
		survey: SURVEY,
		pipes: [{ id: 'cups', label: 'How many cups?', group: 'Earlier questions' }],
		diagnostics: [
			{ severity: 'warning', code: 'text.missing_translation', message: 'No German text', pointer: '/blocks/0/pages/0/items/1/rows/0/label' }
		],
		submit: (ops: RowOp[], o?: { quiet?: readonly string[] }) => {
			sent.push({ ops, quiet: o?.quiet });
			return Promise.resolve(opts.reply ? opts.reply(ops) : { status: 'applied' });
		}
	});
	const label = (n: number) => screen.getByRole('textbox', { name: `Label for row ${n}` });
	return { t, sent, label };
}

describe('RowsEditor', () => {
	it('shows each row with its variable, required state and diagnostics', () => {
		const { t, label } = setup();
		expect([1, 2, 3].map((n) => label(n).textContent)).toEqual(['Tea', 'Coffee', 'Cocoa']);
		expect(t.container.querySelectorAll('[contenteditable]')).toHaveLength(0);
		expect(t.container.querySelectorAll('code.var')).toHaveLength(3);
		expect(t.container.textContent).toContain('taste_coffee');
		const switches = screen.getAllByRole('switch');
		expect(switches.map((s) => s.getAttribute('aria-checked'))).toEqual(['true', 'true', 'false']);
		expect(label(1).getAttribute('aria-describedby')).toBeTruthy();
		expect(t.container.textContent).toContain('No German text');
		// Compact rows: no character count until a row is being edited.
		expect(t.container.querySelector('.osp-rt-count')).toBeNull();
	});

	it('renames on Enter, once, in the editing language', async () => {
		const { sent, label } = setup({ lang: 'de' });
		expect(label(1).textContent).toBe('Tea'); // a plain label is every language's
		expect(label(2).textContent).toBe('Kaffee');
		const ed = await activate(label(2));
		await typeInto(ed, 'Filterkaffee');
		await fireEvent.keyDown(editable(ed.view.dom.id)!, { key: 'Enter' });
		await blurField(ed.view.dom.id);
		expect(sent).toEqual([
			{
				ops: [{ op: 'rename_matrix_row', params: { question: 'taste', row: 'coffee', label: { en: 'Coffee', de: 'Filterkaffee' } } }],
				quiet: undefined
			}
		]);
	});

	it('a formatted label is sent as a tree; the idle row shows the formatting', async () => {
		const { sent, label, t } = setup();
		const ed = await activate(label(1));
		ed.chain().selectAll().toggleItalic().run();
		await blurField(ed.view.dom.id);
		expect(sent.map((s) => s.ops[0])).toEqual([
			{
				op: 'rename_matrix_row',
				params: { question: 'taste', row: 'tea', label: { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'Tea', marks: ['i'] }] }] } }
			}
		]);
		// The server echoes the tree back: the row renders it read-only.
		await t.rerender({ question: { ...Q, rows: [{ ...Q.rows[0], label: sent[0].ops[0].params.label as RowsQuestion['rows'][0]['label'] }, ...Q.rows.slice(1)] } });
		expect(label(1).querySelector('em')!.textContent).toBe('Tea');
		expect(t.container.querySelectorAll('[contenteditable]')).toHaveLength(0);
	});

	it('Escape drops a typed label; unchanged text sends nothing', async () => {
		const { sent, label } = setup();
		const ed = await activate(label(1));
		await typeInto(ed, 'Green');
		await fireEvent.keyDown(editable(ed.view.dom.id)!, { key: 'Escape' });
		expect(ed.getText()).toBe('Tea');
		await typeInto(ed, 'Tea');
		await blurField(ed.view.dom.id);
		expect(sent).toEqual([]);
	});

	it('Alt+↓ / Alt+↑ move a row (a draft label is sent first); edges send nothing', async () => {
		const { sent, label } = setup();
		const ed = await activate(label(1));
		await typeInto(ed, 'Green tea');
		await fireEvent.keyDown(editable(ed.view.dom.id)!, { key: 'ArrowDown', altKey: true });
		await fireEvent.keyDown(editable(ed.view.dom.id)!, { key: 'ArrowUp', altKey: true });
		await fireEvent.keyDown(screen.getByRole('button', { name: 'Move Cocoa' }), { key: 'ArrowUp', altKey: true });
		expect(sent.map((s) => s.ops[0])).toEqual([
			{ op: 'rename_matrix_row', params: { question: 'taste', row: 'tea', label: 'Green tea' } },
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

	it('has no axe violations at rest and with a row open', async () => {
		const { t, label } = setup();
		const rules = { rules: { 'color-contrast': { enabled: false } } };
		const rest = await axe.run(t.container, rules);
		expect(rest.violations.map((v) => v.id)).toEqual([]);
		await activate(label(2));
		const editing = await axe.run(t.container, rules);
		expect(editing.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	});
});
