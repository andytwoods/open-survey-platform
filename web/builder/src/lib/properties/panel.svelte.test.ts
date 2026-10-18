import '@testing-library/svelte/vitest';
import { fireEvent, render } from '@testing-library/svelte';
import axe from 'axe-core';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { activate, blurField, editable, typeInto } from '../richtext/test-utils';
import fixture from './fixtures/property-schemas.json';
import { EXTERNAL_KINDS, TEXT_DEBOUNCE_MS, groupProperties } from './logic';
import PropertyPanel from './PropertyPanel.svelte';
import type { OpenEditorRequest, PanelDiagnostic, PanelOp, PropertySchemasDoc, TypeSchema } from './types';

// The property panel against the real schemas (fixtures/property-schemas.json is exactly
// what GET /api/meta/property-schemas serves): every MVP property editable, text debounce,
// focus and caret kept when patches arrive, inline diagnostics, focusProperty, axe.
// Participant-facing text fields are the rich editor (planning/rich-text.md §9, RT3): at
// rest a read-only textbox, an editor once focused; tests drive it through its commands.

const doc = fixture as unknown as PropertySchemasDoc;
const schemaOf = (type: string) => doc.schemas.find((s) => s.type === type)!;

/** A bare target of each entity: only identity, so every value comes from defaults. */
function bareTarget(s: TypeSchema): Record<string, unknown> {
	if (s.entity === 'survey') return { metadata: { languages: ['en', 'de'] } };
	if (s.entity === 'question') return { id: 'q1', type: s.type };
	return { id: s.entity === 'page' ? 'p1' : 'b1' };
}

function setup(
	s: TypeSchema,
	target: unknown = bareTarget(s),
	extra: {
		language?: string;
		diagnostics?: PanelDiagnostic[];
		pointer?: string;
		groupLabels?: Record<string, Record<string, string>>;
	} = {}
) {
	const ops: PanelOp[] = [];
	const opened: OpenEditorRequest[] = [];
	const dirty: boolean[] = [];
	const props = {
		schema: s,
		target,
		language: extra.language ?? 'en',
		defaultLanguage: 'en',
		diagnostics: extra.diagnostics ?? [],
		pointer: extra.pointer ?? '',
		groups: doc.groups,
		groupLabels: extra.groupLabels,
		onOp: (op: PanelOp) => ops.push(op),
		onOpenEditor: (r: OpenEditorRequest) => opened.push(r),
		onDirty: (d: boolean) => dirty.push(d)
	};
	const r = render(PropertyPanel, { props });
	const field = (key: string) =>
		r.container.querySelector<HTMLElement>(
			`[data-property="${key}"] :is(input, textarea, select, button.switch, button.open-editor, [role="textbox"])`
		)!;
	return { ...r, ops, opened, dirty, props, field };
}

/** Edit a rich field as a researcher would: focus, replace the text, leave. */
async function editRich(el: HTMLElement, text: string) {
	const ed = await activate(el);
	await typeInto(ed, text);
	await blurField(el.id);
}

afterEach(() => {
	vi.useRealTimers();
});

describe('every MVP property is editable', () => {
	for (const s of doc.schemas) {
		it(`${s.type}: each property emits set_property (or opens its editor)`, async () => {
			const t = setup(s);
			const groups = groupProperties(s, doc.groups);
			const rendered = [...t.container.querySelectorAll('[data-property]')].map((e) => e.getAttribute('data-property'));
			expect(rendered).toEqual(groups.flatMap((g) => g.entries.map((e) => e.key)));

			for (const [key, spec] of Object.entries(s.properties)) {
				const el = t.field(key);
				expect(el, key).toBeTruthy();
				const address =
					s.entity === 'survey'
						? { target: `/${key.split('.')[0]}`, property: key.split('.')[1] }
						: { target: (bareTarget(s) as { id: string }).id, property: key };
				const before = t.ops.length;

				if (EXTERNAL_KINDS.includes(spec.kind)) {
					await fireEvent.click(el);
					expect(t.opened.at(-1), key).toEqual({ kind: spec.kind, path: key, ...address, value: undefined });
					continue;
				}
				if (spec.kind === 'text' || spec.kind === 'richtext') {
					if (spec.rich) {
						expect(el.getAttribute('role'), key).toBe('textbox');
						await editRich(el, 'Edited');
					} else {
						expect(el.tagName, key).toBe('INPUT');
						await fireEvent.input(el, { target: { value: 'Edited' } });
						await fireEvent.blur(el);
					}
					const value = spec.translatable ? { en: 'Edited' } : 'Edited';
					expect(t.ops.slice(before), key).toEqual([{ op: 'set_property', params: { ...address, value } }]);
				} else if (spec.kind === 'bool') {
					await fireEvent.click(el);
					expect(el.getAttribute('role')).toBe('switch');
					expect(t.ops.slice(before), key).toEqual([
						{ op: 'set_property', params: { ...address, value: !(spec.default ?? false) } }
					]);
				} else if (spec.kind === 'enum') {
					const select = el as HTMLSelectElement;
					const last = select.options[select.options.length - 1].value;
					expect(last, key).not.toBe('');
					await fireEvent.change(select, { target: { value: last } });
					expect(t.ops.slice(before), key).toEqual([{ op: 'set_property', params: { ...address, value: last } }]);
				} else if (spec.kind === 'number') {
					await fireEvent.input(el, { target: { value: '7' } });
					await fireEvent.blur(el);
					expect(t.ops.slice(before), key).toEqual([{ op: 'set_property', params: { ...address, value: 7 } }]);
				} else {
					throw new Error(`no test for kind ${spec.kind}`);
				}
			}
		});
	}

	it('shows defaults when the target has no value', () => {
		const t = setup(schemaOf('single'));
		expect(t.field('label').textContent).toBe('Untitled question');
		expect(t.field('required').getAttribute('aria-checked')).toBe('false');
		expect((t.field('choiceOrder') as HTMLSelectElement).value).toBe('fixed');
		expect(t.container.querySelector('[data-property="choices"] [data-testid="summary"]')!.textContent).toBe('2 choices');
	});

	it('picks the editor level from the schema: block for a note, stem for a question, inline for a page title', async () => {
		const note = setup(schemaOf('note'));
		expect(note.container.querySelector('[data-property="label"] .osp-rt')!.getAttribute('data-level')).toBe('block');
		note.unmount();
		const single = setup(schemaOf('single'));
		expect(single.container.querySelector('[data-property="label"] .osp-rt')!.getAttribute('data-level')).toBe('stem');
		expect(single.container.querySelector('[data-property="constraintMessage"] .osp-rt')!.getAttribute('data-level')).toBe('inline');
		expect(single.container.querySelector('[data-property="name"] .osp-rt')).toBeNull();
		single.unmount();
		const page = setup(schemaOf('page'));
		expect(page.container.querySelector('[data-property="title"] .osp-rt')!.getAttribute('data-level')).toBe('inline');
		page.unmount();
		// metadata.title stays a plain input (lead decision 6).
		const survey = setup(schemaOf('survey'));
		expect(survey.field('metadata.title').tagName).toBe('INPUT');
		expect(survey.container.querySelector('[data-property="metadata.description"] .osp-rt')!.getAttribute('data-level')).toBe('block');
	});

	it('offers survey languages for optionsFrom and "Not set" when there is no default', () => {
		const t = setup(schemaOf('survey'));
		const select = t.field('metadata.defaultLanguage') as HTMLSelectElement;
		expect([...select.options].map((o) => o.value)).toEqual(['', 'en', 'de']);
		void fireEvent.change(select, { target: { value: '' } });
		expect(t.ops.at(-1)).toEqual({ op: 'set_property', params: { target: '/metadata', property: 'defaultLanguage', unset: true } });
	});

	it('sends a number edit and refuses non-numbers (generic number kind)', async () => {
		const s: TypeSchema = {
			type: 'x',
			entity: 'question',
			label: { en: 'X' },
			properties: { min: { kind: 'number', label: { en: 'Minimum' }, group: 'Validation' } }
		};
		const t = setup(s, { id: 'q9', type: 'x' });
		await fireEvent.input(t.field('min'), { target: { value: 'abc' } });
		await fireEvent.blur(t.field('min'));
		expect(t.ops).toEqual([]);
		expect(t.container.textContent).toContain('Enter a number.');
		await fireEvent.input(t.field('min'), { target: { value: '18' } });
		await fireEvent.blur(t.field('min'));
		expect(t.ops).toEqual([{ op: 'set_property', params: { target: 'q9', property: 'min', value: 18 } }]);
	});
});

describe('text buffers', () => {
	it(`send once after a ${TEXT_DEBOUNCE_MS} ms pause, not per keystroke`, async () => {
		vi.useFakeTimers();
		const t = setup(schemaOf('text'));
		const el = t.field('name');
		await fireEvent.input(el, { target: { value: 'a' } });
		vi.advanceTimersByTime(TEXT_DEBOUNCE_MS - 1);
		await fireEvent.input(el, { target: { value: 'ag' } });
		vi.advanceTimersByTime(TEXT_DEBOUNCE_MS - 1);
		await fireEvent.input(el, { target: { value: 'age' } });
		vi.advanceTimersByTime(TEXT_DEBOUNCE_MS - 1);
		expect(t.ops).toEqual([]);
		expect(t.dirty).toEqual([true]);
		vi.advanceTimersByTime(1);
		expect(t.ops).toEqual([{ op: 'set_property', params: { target: 'q1', property: 'name', value: 'age' } }]);
		expect(t.dirty).toEqual([true, false]);
		await fireEvent.blur(el); // nothing new to send
		expect(t.ops).toHaveLength(1);
	});

	it(`the rich editor sends once after the same pause`, async () => {
		const t = setup(schemaOf('text'), { id: 'q1', type: 'text', label: { en: 'One' } });
		const ed = await activate(t.field('label'));
		vi.useFakeTimers();
		await typeInto(ed, 'On');
		vi.advanceTimersByTime(TEXT_DEBOUNCE_MS - 1);
		await typeInto(ed, 'One two');
		vi.advanceTimersByTime(TEXT_DEBOUNCE_MS - 1);
		expect(t.ops).toEqual([]);
		expect(t.dirty).toEqual([true]);
		vi.advanceTimersByTime(1);
		expect(t.ops).toEqual([{ op: 'set_property', params: { target: 'q1', property: 'label', value: { en: 'One two' } } }]);
		expect(t.dirty).toEqual([true, false]);
	});

	it('send immediately on blur and on Enter, and never twice', async () => {
		vi.useFakeTimers();
		const t = setup(schemaOf('text'));
		const el = t.field('name');
		await fireEvent.input(el, { target: { value: 'x1' } });
		await fireEvent.blur(el);
		expect(t.ops).toHaveLength(1);
		vi.advanceTimersByTime(TEXT_DEBOUNCE_MS * 2);
		expect(t.ops).toHaveLength(1);
		await fireEvent.input(el, { target: { value: 'x2' } });
		await fireEvent.keyDown(el, { key: 'Enter' });
		expect(t.ops.at(-1)!.params.value).toBe('x2');
		expect(t.ops).toHaveLength(2);
	});

	it('Escape throws away unsent text (plain and rich)', async () => {
		vi.useFakeTimers();
		const t = setup(schemaOf('text'), { id: 'q1', type: 'text', name: 'orig' });
		const el = t.field('name') as HTMLInputElement;
		await fireEvent.input(el, { target: { value: 'oops' } });
		await fireEvent.keyDown(el, { key: 'Escape' });
		vi.advanceTimersByTime(TEXT_DEBOUNCE_MS * 2);
		expect(el.value).toBe('orig');
		expect(t.ops).toEqual([]);
		vi.useRealTimers();

		const ed = await activate(t.field('label'));
		await typeInto(ed, 'oops');
		await fireEvent.keyDown(editable(t.field('label').id)!, { key: 'Escape' });
		expect(ed.getText()).toBe('Untitled question');
		expect(t.ops).toEqual([]);
	});

	it('flush on selection change edits the object the text was typed into', async () => {
		const s = schemaOf('text');
		const t = setup(s, { id: 'q1', type: 'text', label: { en: 'One' } });
		const ed = await activate(t.field('label'));
		await typeInto(ed, 'One!');
		await t.rerender({ ...t.props, target: { id: 'q2', type: 'text', label: { en: 'Two' } } });
		expect(t.ops).toEqual([{ op: 'set_property', params: { target: 'q1', property: 'label', value: { en: 'One!' } } }]);
		expect(t.field('label').textContent).toBe('Two');
	});

	it('flush() commits every pending buffer, plain and rich', async () => {
		const t = setup(schemaOf('text'));
		await fireEvent.input(t.field('name'), { target: { value: 'n' } });
		const ed = await activate(t.field('constraintMessage'));
		await typeInto(ed, 'm');
		(t.component as unknown as { flush(): void }).flush();
		expect(t.ops.map((o) => (o.op === 'set_property' ? o.params.property : o.params.key)).sort()).toEqual(['constraintMessage', 'name']);
	});
});

describe('focus is kept when patches arrive', () => {
	const s = schemaOf('single');
	const base = { id: 'q1', type: 'single', label: { en: 'Hello world' } };

	it('keeps the editor open and focused when another property is patched', async () => {
		const t = setup(s, base);
		const el = t.field('label');
		const ed = await activate(el);
		ed.commands.setTextSelection({ from: 3, to: 5 });
		await t.rerender({ ...t.props, target: { ...base, required: true } });
		const editing = editable(el.id)!;
		expect(document.activeElement).toBe(editing);
		expect(ed.getText()).toBe('Hello world');
		expect([ed.state.selection.from, ed.state.selection.to]).toEqual([3, 5]);
		expect(t.field('required').getAttribute('aria-checked')).toBe('true');
	});

	it('keeps focus and the selection when the focused field itself is patched', async () => {
		const t = setup(s, base);
		const el = t.field('label');
		const ed = await activate(el);
		ed.commands.setTextSelection({ from: 3, to: 5 });
		await t.rerender({ ...t.props, target: { ...base, label: { en: 'Hello there world' } } });
		await tick();
		expect(ed.getText()).toBe('Hello there world');
		expect(document.activeElement).toBe(editable(el.id));
		expect([ed.state.selection.from, ed.state.selection.to]).toEqual([3, 5]);
	});

	it('never overwrites text the user is still typing', async () => {
		const t = setup(s, base);
		const ed = await activate(t.field('label'));
		vi.useFakeTimers();
		await typeInto(ed, 'Hello world, again');
		// An unrelated patch (and an echo of the old label) arrives mid-typing.
		await t.rerender({ ...t.props, target: { ...base, required: true } });
		expect(ed.getText()).toBe('Hello world, again');
		vi.advanceTimersByTime(TEXT_DEBOUNCE_MS);
		expect(t.ops.at(-1)!.params).toEqual({ target: 'q1', property: 'label', value: { en: 'Hello world, again' } });
	});

	it('keeps a switch focused after its own patch', async () => {
		const t = setup(s, base);
		const sw = t.field('required');
		sw.focus();
		await fireEvent.click(sw);
		await t.rerender({ ...t.props, target: { ...base, required: true } });
		expect(document.activeElement).toBe(sw);
		expect(sw.getAttribute('aria-checked')).toBe('true');
	});
});

describe('lab profile (B21)', () => {
	it('renders custom.<key> entries as fields that emit set_custom_property, under renamed headings', async () => {
		const single = schemaOf('single');
		const s: TypeSchema = {
			...single,
			properties: {
				...single.properties,
				'custom.construct': { kind: 'text', label: { en: 'Construct' }, group: 'Basics' },
				'custom.weight': { kind: 'number', label: { en: 'Weight' }, group: 'Advanced', default: 1 },
				'custom.prereg': { kind: 'bool', label: { en: 'Pre-registered' }, group: 'Logic' },
				'custom.scale': {
					kind: 'enum',
					label: { en: 'Scale' },
					group: 'Advanced',
					options: [{ value: 'likert', label: { en: 'Likert' } }]
				}
			}
		};
		const t = setup(s, { id: 'q1', type: 'single', custom: { construct: 'affect' } }, { groupLabels: { Logic: { en: 'Conditions' } } });
		expect([...t.container.querySelectorAll('.group-toggle')].map((b) => b.textContent?.trim())).toContain('Conditions');
		expect((t.field('custom.construct') as HTMLInputElement).value).toBe('affect');
		expect((t.field('custom.weight') as HTMLInputElement).value).toBe('1');
		await fireEvent.input(t.field('custom.construct'), { target: { value: 'arousal' } });
		await fireEvent.blur(t.field('custom.construct'));
		await fireEvent.click(t.field('custom.prereg'));
		await fireEvent.change(t.field('custom.scale'), { target: { value: 'likert' } });
		await fireEvent.input(t.field('custom.weight'), { target: { value: '' } });
		await fireEvent.blur(t.field('custom.weight'));
		expect(t.ops).toEqual([
			{ op: 'set_custom_property', params: { target: 'q1', key: 'construct', value: 'arousal' } },
			{ op: 'set_custom_property', params: { target: 'q1', key: 'prereg', value: true } },
			{ op: 'set_custom_property', params: { target: 'q1', key: 'scale', value: 'likert' } },
			{ op: 'set_custom_property', params: { target: 'q1', key: 'weight', unset: true } }
		]);
	});
});

describe('translations', () => {
	it('shows the language, a missing-translation hint and the fallback text', async () => {
		const t = setup(schemaOf('single'), { id: 'q1', type: 'single', label: { en: 'Hi' } }, { language: 'de' });
		const label = t.container.querySelector('[data-property="label"]')!;
		expect(label.getAttribute('data-missing-translation')).toBe('true');
		expect(label.textContent).toContain('Missing translation');
		expect(label.textContent).toContain('de');
		const el = t.field('label');
		expect(el.querySelector('.osp-rt-placeholder')!.textContent).toBe('Hi');
		expect(el.getAttribute('aria-placeholder')).toBe('Hi');
		expect(el.getAttribute('aria-describedby')).toContain(`${el.id}-lang`);
		expect(el.getAttribute('lang')).toBe('de');
		await editRich(el, 'Hallo');
		expect(t.ops).toEqual([{ op: 'set_property', params: { target: 'q1', property: 'label', value: { en: 'Hi', de: 'Hallo' } } }]);
		// Non-translatable fields have no language marker.
		expect(t.container.querySelector('[data-property="name"] .lang')).toBeNull();
	});

	it('keeps a rich value in another language when this one is edited', async () => {
		const rich = { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'Hi', marks: ['b'] }] }] };
		const t = setup(schemaOf('single'), { id: 'q1', type: 'single', label: { en: rich } }, { language: 'de' });
		await editRich(t.field('label'), 'Hallo');
		expect(t.ops).toEqual([{ op: 'set_property', params: { target: 'q1', property: 'label', value: { en: rich, de: 'Hallo' } } }]);
	});
});

describe('diagnostics', () => {
	const diags: PanelDiagnostic[] = [
		{ severity: 'error', code: 'expr.unknown_ref', message: 'Unknown question q99.', pointer: '/blocks/0/pages/0/items/0/constraint' },
		{ severity: 'warning', code: 'other', message: 'Somewhere else.', pointer: '/blocks/0/pages/0/items/1/label' }
	];

	it('show inline, linked by aria-describedby', () => {
		const t = setup(schemaOf('integer'), { id: 'q1', type: 'integer' }, { diagnostics: diags, pointer: '/blocks/0/pages/0/items/0' });
		const el = t.field('constraint');
		const ids = el.getAttribute('aria-describedby')!.split(' ');
		const diag = document.getElementById(ids.find((i) => i.endsWith('-diag'))!)!;
		expect(diag.textContent).toContain('Unknown question q99.');
		expect(t.container.querySelector('[data-property="constraint"]')!.getAttribute('data-invalid')).toBe('true');
		expect(t.container.textContent).not.toContain('Somewhere else.');
	});

	it('a ref.* diagnostic on a pipe marks that chip', async () => {
		const label = { en: { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'Hi ' }, { pipe: 'ghost' }, { text: ' and ' }, { pipe: 'ok' }] }] } };
		const t = setup(
			schemaOf('single'),
			{ id: 'q1', type: 'single', label },
			{
				pointer: '/blocks/0/pages/0/items/0',
				diagnostics: [{ severity: 'error', code: 'ref.unknown', message: 'ghost does not exist', pointer: '/blocks/0/pages/0/items/0/label/en/blocks/0/content/1' }]
			}
		);
		const el = t.field('label');
		expect(el.getAttribute('aria-invalid')).toBe('true');
		await activate(el);
		const chips = [...editable(el.id)!.querySelectorAll('.osp-rt-chip')];
		expect(chips.map((c) => c.classList.contains('osp-rt-chip-error'))).toEqual([true, false]);
		expect(chips[0]!.getAttribute('title')).toBe('ghost does not exist');
	});

	it('focusProperty expands a collapsed group and focuses the field', async () => {
		const t = setup(schemaOf('integer'), { id: 'q1', type: 'integer' }, { diagnostics: diags, pointer: '/blocks/0/pages/0/items/0' });
		const toggle = t.container.querySelector<HTMLButtonElement>('[data-group="Validation"] .group-toggle')!;
		await fireEvent.click(toggle);
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
		expect(t.container.querySelector('[data-group="Validation"] .group-body')!.hasAttribute('hidden')).toBe(true);
		const api = t.component as unknown as { focusProperty(p: string): Promise<boolean> };
		expect(await api.focusProperty('constraint')).toBe(true);
		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(document.activeElement).toBe(t.field('constraint'));
		expect(await api.focusProperty('nope')).toBe(false);
	});
});

describe('accessibility', () => {
	for (const type of ['single', 'note', 'survey', 'page', 'block']) {
		it(`${type} panel has no axe violations`, async () => {
			const t = setup(schemaOf(type), undefined, {
				language: 'de',
				diagnostics: [{ severity: 'error', code: 'c', message: 'Bad.', pointer: '/label' }]
			});
			const res = await axe.run(t.container, {
				rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }
			});
			expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
		});
	}

	it('the open editor has no axe violations', async () => {
		const t = setup(schemaOf('note'), { id: 'q1', type: 'note', label: { en: 'Read ${name}' } });
		await activate(t.field('label'));
		const res = await axe.run(t.container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
		expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	});
});
