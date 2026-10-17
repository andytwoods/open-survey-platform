import '@testing-library/svelte/vitest';
import { fireEvent, render } from '@testing-library/svelte';
import axe from 'axe-core';
import { flushSync } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { outlineFromSurvey } from '../model/outline';
import type { DropTarget } from '../outline/moves';
import { TypeDrag } from '../question-types/type-drag.svelte';
import { SelectionStore } from '../selection.svelte';
import CanvasPane from './CanvasPane.svelte';

// Drag and drop on the canvas (B19), in the DOM: the canvas as a drop zone for a toolbox
// type (the line between cards, the zone on an empty page), reordering a card with the
// pointer (mouse anywhere on the card, touch only by its grip), Escape, and tap-to-place.
// Real mouse and touch drags run in Playwright (e2e/canvas-drag.spec.ts).

globalThis.ResizeObserver ??= class {
	observe() {}
	unobserve() {}
	disconnect() {}
} as unknown as typeof ResizeObserver;

const doc = {
	metadata: { title: 'Drag', languages: ['en'] },
	choiceLists: [],
	blocks: [
		{
			id: 'b1',
			pages: [
				{
					id: 'p1',
					title: 'Page 1',
					items: [
						{ type: 'text', id: 'q1', label: 'Age' },
						{ type: 'text', id: 'q2', label: 'Gender' },
						{ type: 'text', id: 'q3', label: 'Town' }
					]
				},
				{ id: 'p2', title: 'Page 2', items: [] }
			]
		}
	]
};

// Layout stand-in (jsdom has none): page i spans 500·i … 500·i + 420; card j of a page
// spans 40 + 112·j … 140 + 112·j below the page's top. Everything else is the viewport.
function rect(top: number, bottom: number): DOMRect {
	return { top, bottom, left: 0, right: 800, width: 800, height: bottom - top, x: 0, y: top, toJSON() {} } as DOMRect;
}
beforeEach(() => {
	vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
		const el = this as HTMLElement;
		const pages = [...document.querySelectorAll('[data-canvas-page]')];
		if (el.dataset?.canvasPage) {
			const i = pages.indexOf(el);
			return rect(500 * i, 500 * i + 420);
		}
		if (el.dataset?.canvasQuestion) {
			const page = el.closest('[data-canvas-page]')!;
			const base = 500 * pages.indexOf(page);
			const j = [...page.querySelectorAll('[data-canvas-question]')].indexOf(el);
			return rect(base + 40 + 112 * j, base + 140 + 112 * j);
		}
		return rect(0, 2000);
	});
});
afterEach(() => vi.restoreAllMocks());

function setup(extra: Record<string, unknown> = {}) {
	const selection = new SelectionStore();
	const typeDrag = new TypeDrag();
	const moves: [string[], DropTarget][] = [];
	const r = render(CanvasPane, {
		props: {
			pages: outlineFromSurvey(doc),
			selection,
			survey: doc,
			typeDrag,
			onMove: (ids: string[], target: DropTarget) => void moves.push([ids, target]),
			...extra
		}
	});
	const slot = (id: string) => r.container.querySelector<HTMLElement>(`[data-canvas-question="${id}"]`)!;
	const page = (id: string) => r.container.querySelector<HTMLElement>(`[data-canvas-page="${id}"]`)!;
	const canvas = r.container.querySelector<HTMLElement>('.canvas')!;
	return { ...r, selection, typeDrag, moves, slot, page, canvas };
}

describe('a toolbox type over the canvas', () => {
	it('resolves the gap under the pointer and draws the line between cards 1 and 2', () => {
		const t = setup();
		t.typeDrag.start('slider');
		flushSync();
		t.typeDrag.move(100, 150); // in the gap under card 1
		flushSync();
		expect(t.typeDrag.hit?.hit.target).toEqual({ parent: 'p1', slot: 1 });
		expect(t.typeDrag.hit?.description).toBe('Drop between Age and Gender on Page 1');
		expect(t.slot('q2').dataset.drop).toBe('before');
		expect(t.slot('q1').dataset.drop).toBeUndefined();
		// Below the last card: after it.
		t.typeDrag.move(100, 400);
		flushSync();
		expect(t.slot('q3').dataset.drop).toBe('after');
		expect(t.slot('q2').dataset.drop).toBeUndefined();
	});

	it('an empty page shows a drop zone while dragging, highlighted when over it', () => {
		const t = setup();
		expect(t.container.querySelector('.empty-drop')).toBeNull();
		t.typeDrag.start('note');
		flushSync();
		expect(t.page('p2').querySelector('.empty-drop')).not.toBeNull();
		t.typeDrag.move(100, 560);
		flushSync();
		expect(t.typeDrag.hit?.hit.target).toEqual({ parent: 'p2', slot: 0 });
		expect(t.typeDrag.hit?.description).toBe('Drop on Page 2, which is empty');
		expect(t.page('p2').dataset.drop).toBe('into');
		t.typeDrag.end();
		flushSync();
		expect(t.container.querySelector('.empty-drop')).toBeNull();
		expect(t.container.querySelector('[data-drop]')).toBeNull();
	});

	it('outside the canvas: no gap', () => {
		const t = setup();
		t.typeDrag.start('text');
		t.typeDrag.move(5000, 150);
		expect(t.typeDrag.hit).toBeNull();
	});
});

describe('dragging a card', () => {
	const ptr = (x: number, y: number, extra: Record<string, unknown> = {}) => ({
		pointerId: 1,
		button: 0,
		clientX: x,
		clientY: y,
		pointerType: 'mouse',
		...extra
	});

	it('mouse: drag card 3 above card 2 → one move, selected, no click selection side effects', async () => {
		const t = setup();
		const button = t.container.querySelector<HTMLElement>('#card-q3')!;
		await fireEvent.pointerDown(button, ptr(100, 300));
		await fireEvent.pointerMove(button, ptr(100, 290));
		expect(t.slot('q3').classList.contains('moving')).toBe(true);
		await fireEvent.pointerMove(button, ptr(100, 150));
		expect(t.slot('q2').dataset.drop).toBe('before');
		await fireEvent.pointerUp(button, ptr(100, 150));
		expect(t.moves).toEqual([[['q3'], { parent: 'p1', slot: 1 }]]);
		expect(t.selection.id).toBe('q3');
		expect(t.container.querySelector('[data-drop]')).toBeNull();
	});

	it('next to itself there is no gap: dropping moves nothing', async () => {
		const t = setup();
		const button = t.container.querySelector<HTMLElement>('#card-q2')!;
		await fireEvent.pointerDown(button, ptr(100, 200));
		await fireEvent.pointerMove(button, ptr(100, 160));
		expect(t.container.querySelector('[data-drop]')).toBeNull();
		await fireEvent.pointerUp(button, ptr(100, 160));
		expect(t.moves).toEqual([]);
	});

	it('Escape cancels mid-drag', async () => {
		const t = setup();
		const button = t.container.querySelector<HTMLElement>('#card-q1')!;
		await fireEvent.pointerDown(button, ptr(100, 80));
		await fireEvent.pointerMove(button, ptr(100, 560));
		expect(t.page('p2').dataset.drop).toBe('into');
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(t.container.querySelector('[data-drop]')).toBeNull();
		await fireEvent.pointerUp(button, ptr(100, 560));
		expect(t.moves).toEqual([]);
	});

	it('touch drags only by the grip (elsewhere a swipe scrolls)', async () => {
		const t = setup();
		const button = t.container.querySelector<HTMLElement>('#card-q1')!;
		const touch = { pointerType: 'touch' };
		await fireEvent.pointerDown(button, ptr(100, 80, touch));
		await fireEvent.pointerMove(button, ptr(100, 560, touch));
		await fireEvent.pointerUp(button, ptr(100, 560, touch));
		expect(t.moves).toEqual([]);
		const grip = t.slot('q1').querySelector<HTMLElement>('[data-drag-handle]')!;
		await fireEvent.pointerDown(grip, ptr(780, 50, touch));
		await fireEvent.pointerMove(grip, ptr(780, 560, touch));
		await fireEvent.pointerUp(grip, ptr(780, 560, touch));
		expect(t.moves).toEqual([[['q1'], { parent: 'p2', slot: 0 }]]);
	});

	it('without onMove (the mock, other views) cards do not drag and have no grip', async () => {
		const t = setup({ onMove: undefined });
		expect(t.container.querySelector('[data-drag-handle]')).toBeNull();
		const button = t.container.querySelector<HTMLElement>('#card-q3')!;
		await fireEvent.pointerDown(button, ptr(100, 300));
		await fireEvent.pointerMove(button, ptr(100, 150));
		expect(t.container.querySelector('[data-drop]')).toBeNull();
	});
});

describe('tap-to-place (narrow screens)', () => {
	it('a "Place here" button in every gap, named by its neighbours; a tap places', async () => {
		const placed: DropTarget[] = [];
		const t = setup({ placing: 'Slider', placeDefault: 'p1', onPlace: (x: DropTarget) => placed.push(x) });
		const buttons = [...t.container.querySelectorAll<HTMLButtonElement>('[data-place-page]')];
		expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual([
			'Place here at the start of Page 1, before Age',
			'Place here between Age and Gender on Page 1',
			'Place here between Gender and Town on Page 1',
			'Place here at the end of Page 1, after Town',
			'Place here on Page 2, which is empty'
		]);
		expect(t.container.textContent).toContain('Choose where the Slider question goes.');
		// The grip steps aside while placing.
		expect(t.container.querySelector('[data-drag-handle]')).toBeNull();
		await fireEvent.click(buttons[1]);
		expect(placed).toEqual([{ parent: 'p1', slot: 1 }]);
		const results = await axe.run(t.container, { rules: { region: { enabled: false } } });
		expect(results.violations.map((v) => v.id)).toEqual([]);
	});

	it('focus starts on the default page’s last gap; Escape and Cancel stop placing', async () => {
		let cancelled = 0;
		const t = setup({ placing: 'Note', placeDefault: 'p1', onCancelPlace: () => cancelled++ });
		await new Promise((r) => setTimeout(r, 0));
		expect(document.activeElement?.getAttribute('aria-label')).toBe('Place here at the end of Page 1, after Town');
		await fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
		expect(cancelled).toBe(1);
		await fireEvent.click(t.getByRole('button', { name: 'Cancel' }));
		expect(cancelled).toBe(2);
	});
});
