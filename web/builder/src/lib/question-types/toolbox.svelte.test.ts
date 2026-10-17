import '@testing-library/svelte/vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import type { DragHit } from '../outline/drag';
import type { DropTarget } from '../outline/moves';
import type { QuestionTypeId } from './catalogue';
import { TypeDrag } from './type-drag.svelte';
import TypeToolbox from './TypeToolbox.svelte';

// The question-type toolbox under the outline (B16): the catalogue as one toolbar, click
// adds, Shift+Enter asks where, the heading folds it, a11y. Pointer drags run in the
// Playwright suite (e2e/toolbox.spec.ts); the drag state they share is tested here.

function setup(collapsed = false) {
	const added: QuestionTypeId[] = [];
	const where: QuestionTypeId[] = [];
	const inserted: [QuestionTypeId, DropTarget][] = [];
	const t = render(TypeToolbox, {
		drag: new TypeDrag(),
		collapsed,
		onadd: (id: QuestionTypeId) => added.push(id),
		oninsert: (id: QuestionTypeId, target: DropTarget) => inserted.push([id, target]),
		onchoosewhere: (id: QuestionTypeId) => where.push(id)
	});
	const buttons = () => screen.getAllByRole('button', { name: /^Add .+ question$/ });
	return { t, buttons, added, where, inserted };
}

describe('TypeToolbox', () => {
	it('lists the nine types from the catalogue as one toolbar with one Tab stop', () => {
		const { buttons } = setup();
		expect(screen.getByRole('toolbar', { name: 'Add a question of type' })).toBeTruthy();
		expect(buttons().map((b) => b.dataset.type)).toEqual([
			'text',
			'integer',
			'decimal',
			'single',
			'multi',
			'date',
			'matrix',
			'slider',
			'note'
		]);
		expect(buttons()[0].getAttribute('aria-label')).toBe('Add Text question');
		expect(buttons().filter((b) => b.tabIndex === 0)).toHaveLength(1);
	});

	it('a click adds that type', async () => {
		const { buttons, added } = setup();
		await fireEvent.click(buttons()[3]);
		expect(added).toEqual(['single']);
		// The clicked type becomes the Tab stop.
		expect(buttons()[3].tabIndex).toBe(0);
	});

	it('arrows move focus (wrapping), Home/End jump; Shift+Enter asks where', async () => {
		const { buttons, where, added } = setup();
		buttons()[0].focus();
		await fireEvent.keyDown(buttons()[0], { key: 'ArrowDown' });
		expect(document.activeElement).toBe(buttons()[1]);
		await fireEvent.keyDown(buttons()[1], { key: 'ArrowUp' });
		await fireEvent.keyDown(buttons()[0], { key: 'ArrowUp' });
		expect(document.activeElement).toBe(buttons()[8]);
		await fireEvent.keyDown(buttons()[8], { key: 'Home' });
		expect(document.activeElement).toBe(buttons()[0]);
		await fireEvent.keyDown(buttons()[0], { key: 'End' });
		expect(document.activeElement?.getAttribute('data-type')).toBe('note');
		expect(buttons()[8].tabIndex).toBe(0);
		await fireEvent.keyDown(buttons()[8], { key: 'Enter', shiftKey: true });
		expect(where).toEqual(['note']);
		expect(added).toEqual([]);
	});

	it('the heading folds and unfolds it', async () => {
		setup(true);
		const toggle = screen.getByRole('button', { name: 'Question types' });
		expect(toggle.getAttribute('aria-expanded')).toBe('false');
		expect(screen.queryAllByRole('button', { name: /^Add .+ question$/ })).toHaveLength(0);
		await fireEvent.click(toggle);
		expect(toggle.getAttribute('aria-expanded')).toBe('true');
		expect(screen.getAllByRole('button', { name: /^Add .+ question$/ })).toHaveLength(9);
	});

	it('passes axe', async () => {
		const { t } = setup();
		const res = await axe.run(t.container, {
			rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }
		});
		expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	});
});

describe('TypeDrag', () => {
	const hit = (rowId: string, edge: DragHit['edge']): DragHit => ({
		target: { parent: 'p1', slot: 1 },
		rowId,
		edge,
		lineRowId: rowId
	});

	it('asks the attached resolver, reports changes of gap, and ends with the last gap', () => {
		const d = new TypeDrag();
		const off = d.attach((_x, y) => (y < 10 ? null : { hit: hit(y < 20 ? 'a' : 'b', 'after'), description: 'x' }));
		expect(d.move(0, 15)).toBe(false); // not dragging yet
		d.start('slider');
		expect(d.move(0, 15)).toBe(true);
		expect(d.move(0, 16)).toBe(false);
		expect(d.move(0, 25)).toBe(true);
		expect(d.hit?.hit.rowId).toBe('b');
		expect(d.end()?.hit.rowId).toBe('b');
		expect(d.type).toBeNull();
		expect(d.hit).toBeNull();

		d.start('note');
		d.move(0, 25);
		d.move(0, 5); // off the outline
		expect(d.end()).toBeNull();

		off();
		d.start('note');
		d.move(0, 25);
		expect(d.end()).toBeNull(); // no outline attached
	});

	it('several drop zones (outline, canvas): the first that answers wins; refresh re-asks', () => {
		const d = new TypeDrag();
		let canvasSlot = 'c1';
		const offOutline = d.attach((x) => (x < 100 ? { hit: hit('o', 'before'), description: 'outline' } : null));
		d.attach((x) => (x >= 300 ? { hit: hit(canvasSlot, 'before'), description: 'canvas' } : null));
		d.start('text');
		d.move(50, 0);
		expect(d.hit?.description).toBe('outline');
		d.move(400, 0);
		expect(d.hit?.description).toBe('canvas');
		expect([d.x, d.y]).toEqual([400, 0]);
		d.move(200, 0); // between the panes
		expect(d.hit).toBeNull();
		d.move(400, 0);
		// The canvas scrolled under a still pointer: a new gap.
		canvasSlot = 'c2';
		expect(d.refresh()).toBe(true);
		expect(d.hit?.hit.rowId).toBe('c2');
		offOutline();
		d.move(50, 0);
		expect(d.hit).toBeNull();
		d.end();
	});
});
