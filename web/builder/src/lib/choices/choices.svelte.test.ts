import '@testing-library/svelte/vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import { activate, blurField, editable, typeInto, wait } from '../richtext/test-utils';
import ChoiceListEditor from './ChoiceListEditor.svelte';
import type { ChoiceOp, ChoiceQuestion, SpecChoice } from './model';

// The choice list editor's labels as inline rich-text fields (planning/rich-text.md RT5):
// read-only textboxes until focused (one editor instance for any number of rows), the
// buffering contract (Enter, Escape, blur), rich commits, chips, Alt+arrow reorder from
// inside a field, the 200-row case, a11y. Codes, paste and shared lists are covered by
// e2e/choices.spec.ts on the /dev/choices sandbox.

const Q: ChoiceQuestion = {
	id: 'q_mood',
	type: 'single',
	label: 'How do you feel today?',
	choices: [
		{ value: 1, label: 'Good' },
		{ value: 2, label: { en: 'Okay', de: 'Geht so' } },
		{ value: 3, label: 'Bad' }
	]
};

function setup(opts: { lang?: string; question?: ChoiceQuestion; pipes?: null } = {}) {
	const sent: ChoiceOp[][] = [];
	const t = render(ChoiceListEditor, {
		question: opts.question ?? Q,
		lang: opts.lang,
		defaultLanguage: 'en',
		pointer: '/blocks/0/pages/0/items/1/choices',
		pipes: opts.pipes === null ? null : [{ id: 'q_age', label: 'Age', group: 'Earlier questions' }],
		diagnostics: [
			{ severity: 'error', code: 'ref.unknown', message: "'${nope}' is not a question", pointer: '/blocks/0/pages/0/items/1/choices/2/label' }
		],
		onOps: (ops: ChoiceOp[]) => sent.push(ops)
	});
	const label = (n: number) => screen.getByRole('textbox', { name: `Label for choice ${n}` });
	return { t, sent, label };
}

describe('ChoiceListEditor labels', () => {
	it('shows each label as a read-only textbox in the editing language, no editor and no counts', () => {
		const { t, label } = setup({ lang: 'de' });
		expect([1, 2, 3].map((n) => label(n).textContent)).toEqual(['Good', 'Geht so', 'Bad']);
		expect(label(1).getAttribute('aria-multiline')).toBe('false');
		expect(label(2).getAttribute('lang')).toBe('de');
		expect(t.container.querySelectorAll('[contenteditable]')).toHaveLength(0);
		expect(t.container.querySelector('.osp-rt-count')).toBeNull();
		// A row diagnostic names the row's label.
		expect(label(3).getAttribute('aria-invalid')).toBe('true');
		expect(label(3).getAttribute('aria-describedby')).toBeTruthy();
	});

	it('commits on Enter in the editing language, with the count shown while editing', async () => {
		const { t, sent, label } = setup({ lang: 'de' });
		const ed = await activate(label(2));
		expect(t.container.querySelector('.osp-rt-count')!.textContent).toMatch(/7 \/ 500/);
		await typeInto(ed, 'Ganz gut');
		await fireEvent.keyDown(editable(ed.view.dom.id)!, { key: 'Enter' });
		expect(sent).toEqual([[{ op: 'set_choice', params: { owner: 'q_mood', value: 2, label: { en: 'Okay', de: 'Ganz gut' } } }]]);
		await blurField(ed.view.dom.id);
		expect(sent).toHaveLength(1); // blur after Enter sends nothing more
		expect(t.container.querySelector('.osp-rt-count')).toBeNull();
	});

	it('sends a formatted label as a tree and a chip as ${id}; Escape reverts a draft', async () => {
		const { sent, label } = setup();
		const ed = await activate(label(1));
		ed.chain().selectAll().toggleBold().run();
		await blurField(ed.view.dom.id);
		expect(sent).toEqual([
			[{ op: 'set_choice', params: { owner: 'q_mood', value: 1, label: { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'Good', marks: ['b'] }] }] } } }]
		]);

		const again = await activate(label(3));
		await typeInto(again, 'Bad:');
		again.commands.insertContentAt(again.state.doc.content.size - 1, { type: 'pipe', attrs: { id: 'q_age' } });
		await blurField(again.view.dom.id);
		expect(sent[1]).toEqual([{ op: 'set_choice', params: { owner: 'q_mood', value: 3, label: 'Bad:${q_age}' } }]);

		const third = await activate(label(2));
		await typeInto(third, 'Oops');
		await fireEvent.keyDown(editable(third.view.dom.id)!, { key: 'Escape' });
		expect(third.getText()).toBe('Okay');
		await blurField(third.view.dom.id);
		expect(sent).toHaveLength(2);
	});

	it('a field without pipe candidates offers no Insert answer', async () => {
		const { t, label } = setup({ pipes: null });
		await activate(label(1));
		expect(t.container.querySelector('[role="toolbar"] [aria-label="Insert answer"]')).toBeNull();
	});

	it('Alt+↓ from inside a field sends the draft, then the move', async () => {
		const { sent, label } = setup();
		const ed = await activate(label(1));
		await typeInto(ed, 'Great');
		await fireEvent.keyDown(editable(ed.view.dom.id)!, { key: 'ArrowDown', altKey: true });
		expect(sent).toEqual([
			[{ op: 'set_choice', params: { owner: 'q_mood', value: 1, label: 'Great' } }],
			[{ op: 'move_choice', params: { owner: 'q_mood', value: 1, index: 1 } }]
		]);
	});

	it('a server echo lands when the row is clean and never while it is being typed in', async () => {
		const { t, label } = setup();
		const next = (labels: string[]) => ({ ...Q, choices: Q.choices!.map((c, i) => ({ ...c, label: labels[i] })) });
		await t.rerender({ question: next(['Fine', 'Okay', 'Bad']) });
		expect(label(1).textContent).toBe('Fine');
		const ed = await activate(label(1));
		await typeInto(ed, 'Typing');
		await t.rerender({ question: next(['Elsewhere', 'Okay', 'Bad']) });
		expect(ed.getText()).toBe('Typing');
	});

	it('200 rows: 200 read-only rows, one editor when a row is focused, quick to render', async () => {
		const choices: SpecChoice[] = Array.from({ length: 200 }, (_, i) => ({ value: i + 1, label: `Choice ${i + 1}` }));
		const started = performance.now();
		const { t, label } = setup({ question: { ...Q, choices } });
		const rendered = performance.now() - started;
		expect(screen.getAllByRole('textbox', { name: /^Label for choice/ })).toHaveLength(200);
		expect(t.container.querySelectorAll('[contenteditable]')).toHaveLength(0);
		expect(t.container.querySelectorAll('.osp-rt-count')).toHaveLength(0);
		const ed = await activate(label(150));
		expect(t.container.querySelectorAll('[contenteditable]')).toHaveLength(1);
		expect(t.container.querySelectorAll('[role="toolbar"]')).toHaveLength(1);
		expect(ed.getText()).toBe('Choice 150');
		await blurField(ed.view.dom.id);
		await wait(5);
		expect(t.container.querySelectorAll('[contenteditable]')).toHaveLength(0);
		// jsdom is slow; the bound only catches a per-row editor creeping back in.
		expect(rendered).toBeLessThan(5000);
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
