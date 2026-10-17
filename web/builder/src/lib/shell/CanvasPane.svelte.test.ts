import '@testing-library/svelte/vitest';
import { fireEvent, render } from '@testing-library/svelte';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import { outlineFromSurvey } from '../model/outline';
import fixture from '../properties/fixtures/property-schemas.json';
import type { PropertySchemasDoc } from '../properties/types';
import { SelectionStore } from '../selection.svelte';
import { canvasQuestions, cardSchema } from './canvas';
import CanvasPane from './CanvasPane.svelte';

// The editor canvas renders each question with the rich per-family card (lib/cards), fed
// the question's JSON from the survey document; it keeps the simple card's contract
// (`id="card-<id>"`, aria-current, data-pane-focus, click to select) and follows patches.

// jsdom has no ResizeObserver; the slider (Bits UI) and matrix widgets observe their size.
globalThis.ResizeObserver ??= class {
	observe() {}
	unobserve() {}
	disconnect() {}
} as unknown as typeof ResizeObserver;

const schemas = fixture as unknown as PropertySchemasDoc;

type Doc = {
	metadata: unknown;
	choiceLists: unknown[];
	blocks: { id: string; pages: { id: string; items: Record<string, unknown>[] }[] }[];
};

function survey(): Doc {
	return {
		metadata: { title: 'All types', languages: ['en'] },
		choiceLists: [
			{
				id: 'fruit',
				choices: [
					{ value: 'apple', label: 'Apple' },
					{ value: 'banana', label: 'Banana' }
				]
			}
		],
		blocks: [
			{
				id: 'b1',
				pages: [
					{
						id: 'p1',
						items: [
							{ type: 'note', id: 'q_note', label: 'Welcome note' },
							{ type: 'integer', id: 'q_int', label: 'How many?' },
							{ type: 'decimal', id: 'q_dec', label: 'How much?' },
							{ type: 'text', id: 'q_text', label: 'Describe it' },
							{ type: 'single', id: 'q_single', label: 'Pick a fruit', choiceList: 'fruit' },
							{
								type: 'multi',
								id: 'q_multi',
								label: 'Pick colours',
								choices: [
									{ value: 'red', label: 'Red' },
									{ value: 'blue', label: 'Blue' }
								]
							},
							{ type: 'date', id: 'q_date', label: 'When?' },
							{
								type: 'matrix',
								id: 'q_grid',
								label: 'Rate these drinks',
								rows: [
									{ id: 'tea', label: 'Tea' },
									{ id: 'coffee', label: 'Coffee' }
								],
								choices: [
									{ value: 1, label: 'Poor' },
									{ value: 2, label: 'Good' }
								]
							},
							{
								type: 'slider',
								id: 'q_slider',
								label: 'How strong?',
								min: 0,
								max: 10,
								step: 1,
								minLabel: 'None',
								maxLabel: 'Worst imaginable'
							}
						]
					}
				]
			}
		]
	};
}

function setup(doc: unknown = survey(), extra: { schemas?: PropertySchemasDoc | null } = {}) {
	const selection = new SelectionStore();
	const r = render(CanvasPane, {
		props: {
			pages: outlineFromSurvey(doc),
			selection,
			survey: doc,
			schemas: 'schemas' in extra ? extra.schemas : schemas
		}
	});
	const card = (id: string) => r.container.querySelector<HTMLElement>(`[data-question-card="${id}"]`);
	return { ...r, selection, card };
}

describe('canvas mapping: question JSON → card', () => {
	const FAMILY: [string, string][] = [
		['q_note', 'note'],
		['q_int', 'number'],
		['q_dec', 'number'],
		['q_text', 'text'],
		['q_single', 'choice'],
		['q_multi', 'choice'],
		['q_date', 'text'],
		['q_grid', 'matrix'],
		['q_slider', 'scale']
	];

	it('every type gets its family card, with the select button as #card-<id>', () => {
		const t = setup();
		for (const [id, family] of FAMILY) {
			expect(t.card(id)?.dataset.family, id).toBe(family);
			const button = t.container.querySelector<HTMLElement>(`#card-${id}`);
			expect(button?.tagName).toBe('BUTTON');
			expect(t.card(id)?.contains(button)).toBe(true);
		}
		expect(t.container.querySelector('.card-placeholder')).toBeNull();
	});

	it('shows what each question looks like: grid rows × columns, slider ends, options', () => {
		const t = setup();
		const grid = t.card('q_grid')!;
		for (const s of ['Tea', 'Coffee', 'Poor', 'Good']) expect(grid.textContent).toContain(s);
		const slider = t.card('q_slider')!;
		for (const s of ['None', 'Worst imaginable']) expect(slider.textContent).toContain(s);
		// A shared list is previewed through `choiceLists`; inline choices directly.
		expect(t.card('q_single')!.textContent).toContain('Apple');
		expect(t.card('q_single')!.textContent).toContain('Banana');
		expect(t.card('q_multi')!.textContent).toContain('Blue');
		// The type label comes from the schema.
		expect(t.card('q_grid')!.textContent).toMatch(/Grid|Matrix/i);
	});

	it('a missing schema still renders the card (family from the type)', () => {
		const t = setup(survey(), { schemas: null });
		expect(t.card('q_grid')?.dataset.family).toBe('matrix');
		expect(t.card('q_grid')!.textContent).toContain('Coffee');
		expect(t.card('q_slider')?.dataset.family).toBe('scale');
	});

	it('an unknown type still gets a selectable card', () => {
		const doc = survey();
		doc.blocks[0].pages[0].items.push({ type: 'ranking', id: 'q_rank', label: 'Rank these' });
		const t = setup(doc);
		expect(t.card('q_rank')?.dataset.family).toBe('unknown');
		expect(t.container.querySelector('#card-q_rank')).not.toBeNull();
	});

	it('click selects; aria-current and data-pane-focus follow the selection', async () => {
		const t = setup();
		const button = t.container.querySelector<HTMLElement>('#card-q_grid')!;
		expect(button.getAttribute('aria-current')).toBeNull();
		await fireEvent.click(button);
		expect(t.selection.id).toBe('q_grid');
		expect(button.getAttribute('aria-current')).toBe('true');
		expect(button.hasAttribute('data-pane-focus')).toBe(true);
		expect(t.card('q_grid')!.hasAttribute('data-selected')).toBe(true);
	});

	it('follows patches: a new row label and a type change show at once', async () => {
		const t = setup();
		const next = survey();
		next.blocks[0].pages[0].items[7] = {
			...next.blocks[0].pages[0].items[7],
			rows: [
				{ id: 'tea', label: 'Green tea' },
				{ id: 'coffee', label: 'Coffee' }
			]
		};
		next.blocks[0].pages[0].items[4] = { ...next.blocks[0].pages[0].items[4], type: 'text' };
		await t.rerender({ survey: next, pages: outlineFromSurvey(next) });
		expect(t.card('q_grid')!.textContent).toContain('Green tea');
		expect(t.card('q_single')?.dataset.family).toBe('text');
	});

	it('nodes without question JSON (the mock tree) keep the simple card', () => {
		const selection = new SelectionStore();
		const r = render(CanvasPane, {
			props: {
				pages: [
					{
						id: 'p1',
						type: 'page',
						label: 'Page',
						children: [
							{
								id: 'b1',
								type: 'block',
								label: 'Block',
								children: [{ id: 'q1', type: 'question', label: 'Hello', family: 'text' }]
							}
						]
					}
				],
				selection,
				mock: true
			}
		});
		expect(r.container.querySelector('#card-q1')?.classList.contains('card')).toBe(true);
		expect(r.container.querySelector('[data-question-card]')).toBeNull();
	});

	it('axe: no violations', async () => {
		const t = setup();
		const res = await axe.run(t.container, { rules: { region: { enabled: false } } });
		expect(res.violations.map((v) => v.id)).toEqual([]);
	});
});

describe('canvasQuestions / cardSchema', () => {
	it('indexes questions by id and tolerates junk', () => {
		expect(canvasQuestions(null).size).toBe(0);
		expect(canvasQuestions({ blocks: 'x' }).size).toBe(0);
		expect(canvasQuestions({ blocks: [{ pages: [{ items: [null, { id: 1 }, { id: 'a' }] }] }] }).size).toBe(0);
		const m = canvasQuestions(survey());
		expect(m.size).toBe(9);
		expect(m.get('q_grid')?.type).toBe('matrix');
	});

	it('passes a schema through, null when there is none', () => {
		expect(cardSchema(undefined)).toBeNull();
		expect(cardSchema(schemas.schemas[0])?.type).toBe(schemas.schemas[0].type);
	});
});
