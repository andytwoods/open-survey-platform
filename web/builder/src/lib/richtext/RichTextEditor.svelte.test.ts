import '@testing-library/svelte/vitest';
import { fireEvent, render } from '@testing-library/svelte';
import type { RichText } from '@osp/engine';
import axe from 'axe-core';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { editingLanguage } from '../translations/editing-language.svelte';
import RichTextEditor from './RichTextEditor.svelte';
import type { RichValue } from './convert';
import { activate, blurField, editable, typeInto, wait } from './test-utils';

// The rich-text field (planning/rich-text.md §9) in jsdom: edit on focus, the buffering
// contract (debounce, blur, Escape, echo-safe), normalised commits, levels, counts, chips.

const bold: RichText = { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'Be ' }, { text: 'bold', marks: ['b'] }] }] };

type Reference = { value: RichValue | undefined | null; language: string } | null;

function setup(
	value: RichValue | undefined,
	extra: Partial<{ level: 'block' | 'stem' | 'inline'; pipes: null; delay: number; placeholder: string; readonly: boolean; reference: Reference }> = {}
) {
	const commits: RichValue[] = [];
	const dirty: boolean[] = [];
	const props = {
		id: 'f1',
		value,
		level: extra.level ?? 'stem',
		pipes: extra.pipes === null ? null : [{ id: 'age', label: 'Age', group: 'Earlier questions' as const }],
		delay: extra.delay ?? 50,
		placeholder: extra.placeholder ?? '',
		readonly: extra.readonly ?? false,
		reference: extra.reference ?? null,
		labelledBy: 'lbl',
		onCommit: (v: RichValue) => commits.push(v),
		onDirty: (d: boolean) => dirty.push(d)
	};
	document.body.insertAdjacentHTML('afterbegin', '<span id="lbl">Question text</span>');
	const r = render(RichTextEditor, { props });
	const idle = () => r.container.querySelector<HTMLElement>('#f1[role="textbox"]')!;
	return { ...r, commits, dirty, props, idle };
}

afterEach(() => {
	document.getElementById('lbl')?.remove();
	editingLanguage.referenceOpen = true;
	vi.useRealTimers();
});

describe('translations (RT6)', () => {
	const ref = { value: bold, language: 'en' };
	const strip = (c: HTMLElement) => c.querySelector<HTMLElement>('[data-testid="reference-strip"]');
	const copy = (c: HTMLElement) => c.querySelector<HTMLButtonElement>('.osp-rt-ref-copy')!;

	it('shows the default-language value as a read-only reference, formatting included', () => {
		const t = setup('', { reference: ref, placeholder: 'Be bold' });
		const s = strip(t.container)!;
		expect(s).not.toBeNull();
		expect(s.querySelector('.osp-rt-ref-body')!.getAttribute('lang')).toBe('en');
		expect(s.querySelector('.osp-rt-ref-body strong')!.textContent).toBe('bold');
		expect(copy(t.container).textContent).toContain('Copy from en');
		expect(copy(t.container).disabled).toBe(false);
		expect(t.container.querySelector('[role="toolbar"]')).toBeNull();
		t.unmount();
		// No reference (the default language is being edited), or nothing to translate: no strip.
		const none = setup('x');
		expect(strip(none.container)).toBeNull();
		none.unmount();
		const empty = setup('x', { reference: { value: '', language: 'en' } });
		expect(strip(empty.container)).toBeNull();
	});

	it('Copy from <default> commits the reference at once and the field shows it', async () => {
		const t = setup('', { reference: ref, delay: 1000 });
		await fireEvent.click(copy(t.container));
		expect(t.commits).toEqual([bold]);
		expect(t.idle().querySelector('strong')!.textContent).toBe('bold');
		expect(copy(t.container).disabled).toBe(true); // the same as the reference now
		expect(t.dirty).toEqual([]);
		// While the editor is open the copy lands in the editor and replaces a pending draft.
		const ed = await activate(t.idle());
		await typeInto(ed, 'Fett');
		expect(t.dirty).toEqual([true]);
		expect(copy(t.container).disabled).toBe(false);
		await fireEvent.click(copy(t.container));
		expect(ed.getText()).toBe('Be bold');
		expect(t.dirty).toEqual([true, false]);
		expect(t.commits).toEqual([bold]); // unchanged from the server's value: nothing new sent
	});

	it('the reference collapses and expands, one shared choice for every field', async () => {
		const t = setup('', { reference: ref });
		const toggle = t.container.querySelector<HTMLButtonElement>('.osp-rt-ref-toggle')!;
		const body = t.container.querySelector<HTMLElement>('.osp-rt-ref-body')!;
		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(toggle.getAttribute('aria-controls')).toBe(body.id);
		await fireEvent.click(toggle);
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
		expect(body.hidden).toBe(true);
		expect(editingLanguage.referenceOpen).toBe(false);
		await fireEvent.click(toggle);
		expect(body.hidden).toBe(false);
	});

	it('an inline reference renders on one line', () => {
		const t = setup('', { level: 'inline', reference: { value: 'Yes', language: 'en' } });
		expect(t.container.querySelector('.osp-rt-ref-body .osp-rv-inline')!.textContent).toBe('Yes');
	});
});

describe('at rest', () => {
	it('renders the value read-only as a labelled textbox, chips included, with the count', () => {
		const t = setup('Hello ${age} there');
		const idle = t.idle();
		expect(idle.getAttribute('aria-labelledby')).toBe('lbl');
		expect(idle.getAttribute('aria-multiline')).toBe('true');
		expect(idle.textContent).toContain('Hello ');
		expect(idle.querySelector('.osp-rt-chip')!.textContent).toBe('${age}');
		expect(editable('f1')).toBeNull();
		expect(t.container.querySelector('.osp-rt-count')!.textContent).toMatch(/12 \/ 2,000/);
	});

	it('shows the placeholder when empty and renders formatting', () => {
		const t = setup('', { placeholder: 'Type here' });
		expect(t.idle().textContent).toBe('Type here');
		expect(t.idle().getAttribute('aria-placeholder')).toBe('Type here');
		t.unmount();
		const b = setup(bold);
		expect(b.idle().querySelector('strong')!.textContent).toBe('bold');
	});

	it('follows the value prop', async () => {
		const t = setup('one');
		await t.rerender({ ...t.props, value: 'two' });
		expect(t.idle().textContent).toBe('two');
	});
});

describe('editing', () => {
	it('focus swaps in the editor with the field id and ARIA, and a toolbar', async () => {
		const t = setup('Hello');
		const ed = await activate(t.idle());
		const el = editable('f1')!;
		expect(el.getAttribute('role')).toBe('textbox');
		expect(el.getAttribute('aria-labelledby')).toBe('lbl');
		expect(el.getAttribute('aria-describedby')).toContain('f1-count');
		expect(t.container.querySelector('#f1[role="textbox"]:not([contenteditable])')).toBeNull();
		expect(ed.getText()).toBe('Hello');
		const toolbar = t.container.querySelector('[role="toolbar"]')!;
		expect(toolbar.getAttribute('aria-label')).toBe('Text formatting');
		const names = [...toolbar.querySelectorAll('button')].map((b) => b.getAttribute('aria-label'));
		expect(names).toEqual(['Bold', 'Italic', 'Link', 'Bulleted list', 'Numbered list', 'Insert answer', 'Line break', 'Clear formatting', 'Undo', 'Redo']);
		expect(toolbar.querySelector('select')).toBeNull(); // no heading control at stem level
	});

	it('commits a plain string after the pause, once, and reports dirty', async () => {
		const t = setup('Hello');
		const ed = await activate(t.idle());
		await typeInto(ed, 'Hello world');
		expect(t.commits).toEqual([]);
		expect(t.dirty).toEqual([true]);
		await wait(80);
		expect(t.commits).toEqual(['Hello world']);
		expect(t.dirty).toEqual([true, false]);
	});

	it('commits the tree when formatted, normalised; a pipe typed as ${id} is a chip', async () => {
		const t = setup('Hello', { delay: 1000 });
		const ed = await activate(t.idle());
		ed.chain().selectAll().toggleBold().run();
		// Inserted at the end of bold text, the new text is bold too; `${age}` inserted as text
		// stays text (the input rule fires on typing, the paste pass on pasting).
		ed.commands.insertContentAt(ed.state.doc.content.size - 1, ' ${age}');
		await blurField('f1');
		expect(t.commits).toEqual([{ type: 'rich', blocks: [{ type: 'p', content: [{ text: 'Hello ${age}', marks: ['b'] }] }] }]);
	});

	it('Escape reverts the draft and keeps the Escape to itself; a clean Escape bubbles', async () => {
		const t = setup('Hello', { delay: 1000 });
		const ed = await activate(t.idle());
		await typeInto(ed, 'Oops');
		expect(t.dirty).toEqual([true]);
		const escaped: boolean[] = [];
		document.body.addEventListener('keydown', (e) => escaped.push(e.key === 'Escape'), { once: true });
		await fireEvent.keyDown(editable('f1')!, { key: 'Escape' });
		expect(ed.getText()).toBe('Hello');
		expect(t.dirty).toEqual([true, false]);
		expect(escaped).toEqual([]); // stopped: the drawer must not close
		await fireEvent.keyDown(editable('f1')!, { key: 'Escape' });
		expect(escaped).toEqual([true]);
		await blurField('f1');
		expect(t.commits).toEqual([]);
	});

	it('a server echo never clobbers text being typed, but lands when the field is clean', async () => {
		const t = setup('Hello', { delay: 1000 });
		const ed = await activate(t.idle());
		await typeInto(ed, 'Hello, typing');
		await t.rerender({ ...t.props, value: 'Hello' }); // the old value echoed back
		expect(ed.getText()).toBe('Hello, typing');
		await blurField('f1');
		expect(t.commits).toEqual(['Hello, typing']);
		// Clean again: another client's edit replaces the text.
		const again = await activate(t.idle());
		await t.rerender({ ...t.props, value: 'Elsewhere' });
		expect(again.getText()).toBe('Elsewhere');
	});

	it('blur commits and returns to the read-only view', async () => {
		const t = setup('Hello', { delay: 1000 });
		const ed = await activate(t.idle());
		await typeInto(ed, 'Done');
		await blurField('f1');
		expect(t.commits).toEqual(['Done']);
		expect(editable('f1')).toBeNull();
		expect(t.idle().textContent).toBe('Done');
	});

	it('flush() commits like the panel does before undo or navigation', async () => {
		const t = setup('Hello', { delay: 1000 });
		const ed = await activate(t.idle());
		await typeInto(ed, 'Flushed');
		(t.component as unknown as { flush(): void }).flush();
		expect(t.commits).toEqual(['Flushed']);
	});

	it('an emptied field commits "" (the caller unsets it)', async () => {
		const t = setup('Hello', { delay: 1000 });
		const ed = await activate(t.idle());
		await typeInto(ed, '');
		await blurField('f1');
		expect(t.commits).toEqual(['']);
	});
});

describe('levels', () => {
	it('block offers the heading select; inline offers no lists, breaks or paragraphs and Enter commits', async () => {
		const b = setup('x', { level: 'block' });
		await activate(b.idle());
		expect(b.container.querySelector('[role="toolbar"] select[aria-label="Text style"]')).not.toBeNull();
		b.unmount();

		const i = setup('x', { level: 'inline', delay: 1000 });
		const ed = await activate(i.idle());
		expect(editable('f1')!.getAttribute('aria-multiline')).toBe('false');
		const names = [...i.container.querySelectorAll('[role="toolbar"] button')].map((b) => b.getAttribute('aria-label'));
		expect(names).toEqual(['Bold', 'Italic', 'Link', 'Insert answer', 'Clear formatting', 'Undo', 'Redo']);
		expect(i.container.querySelector('.osp-rt-count')!.textContent).toMatch(/1 \/ 500/);
		await typeInto(ed, 'xy');
		await fireEvent.keyDown(editable('f1')!, { key: 'Enter' });
		expect(i.commits).toEqual(['xy']);
		expect(ed.state.doc.childCount).toBe(1);
	});

	it('a field without pipes has no Insert answer button', async () => {
		const t = setup('x', { pipes: null });
		await activate(t.idle());
		expect(t.container.querySelector('[role="toolbar"] [aria-label="Insert answer"]')).toBeNull();
	});

	it('over the limit the count turns into an error and the commit still happens', async () => {
		const t = setup('x'.repeat(499), { level: 'inline', delay: 1000 });
		const ed = await activate(t.idle());
		await typeInto(ed, 'y'.repeat(501));
		const count = t.container.querySelector('.osp-rt-count')!;
		expect(count.textContent).toMatch(/501 \/ 500/);
		expect(count.textContent).toContain('too long');
		expect(count.getAttribute('aria-live')).toBe('polite');
		expect(editable('f1')!.getAttribute('aria-invalid')).toBe('true');
		await blurField('f1');
		expect(t.commits).toHaveLength(1);
	});

	it('read-only fields are not focusable', () => {
		const t = setup('x', { readonly: true });
		expect(t.idle().getAttribute('tabindex')).toBe('-1');
		expect(t.idle().getAttribute('aria-readonly')).toBe('true');
	});
});

describe('accessibility', () => {
	it('has no axe violations at rest and while editing', async () => {
		const t = setup('Hello ${age}');
		const rules = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
		const rest = await axe.run(t.container, rules);
		expect(rest.violations.map((v) => v.id)).toEqual([]);
		await activate(t.idle());
		const editing = await axe.run(t.container, rules);
		expect(editing.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	});
});

describe('keys typed before the editor is ready (RT7)', () => {
	/** Press a key on whatever has focus; true when the field took it for replay. */
	const press = (key: string, init: KeyboardEventInit = {}) =>
		!(document.activeElement ?? document.body).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }));

	it('replays text, Backspace and Enter typed straight after focus, in order', async () => {
		const t = setup('Hi', { level: 'block', delay: 1000 });
		const idle = t.idle();
		idle.focus();
		// The chunk is still loading: every key below arrives before the editor exists.
		for (const key of [' ', 't', 'h', 'e', 'r', 'x', 'Backspace', 'e', 'Enter', 'B', 'y', 'e']) expect(press(key)).toBe(true);
		const ed = await activate(idle);
		expect(ed.getText({ blockSeparator: '|' })).toBe('Hi there|Bye');
		await blurField('f1');
		expect(t.commits.at(-1)).toEqual({ type: 'rich', blocks: [{ type: 'p', content: [{ text: 'Hi there' }] }, { type: 'p', content: [{ text: 'Bye' }] }] });
	});

	it('leaves shortcuts and other keys alone, and stops catching once the editor is ready', async () => {
		const t = setup('Hi');
		const idle = t.idle();
		idle.focus();
		expect(press('b', { ctrlKey: true })).toBe(false);
		expect(press('Tab')).toBe(false);
		expect(press('Escape')).toBe(false);
		const ed = await activate(idle);
		expect(ed.getText()).toBe('Hi');
		expect(press('z')).toBe(false); // ProseMirror's own handling now (jsdom cannot type it)
		expect(ed.getText()).toBe('Hi');
	});

	it('keys aimed at another control while the field loads stay with that control', async () => {
		const t = setup('Hi');
		const other = document.createElement('input');
		document.body.append(other);
		try {
			t.idle().focus();
			other.focus();
			expect(press('q')).toBe(false);
			await vi.dynamicImportSettled();
			for (let i = 0; i < 5; i++) await wait(5);
			expect(t.container.textContent).not.toContain('q');
		} finally {
			other.remove();
		}
	});
});
