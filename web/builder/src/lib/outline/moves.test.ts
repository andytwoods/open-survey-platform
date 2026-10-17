import { describe, expect, it } from 'vitest';
import type { OutlineNode } from '../model/outline';
import { boxesFrom, dropTargetAt, insertTargetAt } from './drag';
import { applyMoves, describeMove, destinations, keyboardTarget, moveOps, movableIds } from './moves';

const q = (id: string): OutlineNode => ({ id, type: 'question', label: id.toUpperCase() });
const page = (id: string, ...qs: string[]): OutlineNode => ({ id, type: 'page', label: `Page ${id}`, children: qs.map(q) });
const block = (id: string, ...pages: OutlineNode[]): OutlineNode => ({ id, type: 'block', label: `Block ${id}`, children: pages });

// b1: p1 [a b c], p2 [d e]; b2: p3 [f]
const ROOTS = [block('b1', page('p1', 'a', 'b', 'c'), page('p2', 'd', 'e')), block('b2', page('p3', 'f'))];

/** The tree as nested id lists, for compact assertions. */
const shape = (roots: OutlineNode[]): unknown[] =>
	roots.map((n) => (n.children ? { [n.id]: shape(n.children) } : n.id));

describe('moveOps', () => {
	it('moves one question down within its page (index after removal)', () => {
		const ops = moveOps(ROOTS, ['a'], { parent: 'p1', slot: 3 });
		expect(ops).toEqual([{ op: 'move_question', params: { id: 'a', page: 'p1', index: 2 } }]);
		expect(shape(applyMoves(ROOTS, ops))[0]).toEqual({ b1: [{ p1: ['b', 'c', 'a'] }, { p2: ['d', 'e'] }] });
	});

	it('moves a question up', () => {
		expect(moveOps(ROOTS, ['c'], { parent: 'p1', slot: 0 })).toEqual([
			{ op: 'move_question', params: { id: 'c', page: 'p1', index: 0 } }
		]);
	});

	it('gives no ops when nothing moves', () => {
		expect(moveOps(ROOTS, ['b'], { parent: 'p1', slot: 1 })).toEqual([]);
		expect(moveOps(ROOTS, ['b'], { parent: 'p1', slot: 2 })).toEqual([]);
	});

	it('moves across pages and blocks', () => {
		const ops = moveOps(ROOTS, ['b'], { parent: 'p3', slot: 0 });
		expect(ops).toEqual([{ op: 'move_question', params: { id: 'b', page: 'p3', index: 0 } }]);
		expect(shape(applyMoves(ROOTS, ops))).toEqual([
			{ b1: [{ p1: ['a', 'c'] }, { p2: ['d', 'e'] }] },
			{ b2: [{ p3: ['b', 'f'] }] }
		]);
	});

	it('moves a multi-selection as one ordered transaction', () => {
		// Selected out of order and across pages: they land together, in document order.
		const ops = moveOps(ROOTS, ['e', 'a', 'c'], { parent: 'p2', slot: 1 });
		expect(ops).toEqual([
			{ op: 'move_question', params: { id: 'a', page: 'p2', index: 2 } },
			{ op: 'move_question', params: { id: 'c', page: 'p2', index: 3 } },
			{ op: 'move_question', params: { id: 'e', page: 'p2', index: 3 } }
		]);
		expect(shape(applyMoves(ROOTS, ops))[0]).toEqual({ b1: [{ p1: ['b'] }, { p2: ['d', 'a', 'c', 'e'] }] });
	});

	it('gathers a split selection within one page, skipping items already in place', () => {
		const ops = moveOps(ROOTS, ['a', 'c'], { parent: 'p1', slot: 0 });
		expect(ops).toEqual([{ op: 'move_question', params: { id: 'c', page: 'p1', index: 1 } }]);
		expect(shape(applyMoves(ROOTS, ops))[0]).toEqual({ b1: [{ p1: ['a', 'c', 'b'] }, { p2: ['d', 'e'] }] });
	});

	it('only moves items of the first type, and only into a parent that holds them', () => {
		expect(movableIds(ROOTS, ['p2', 'a', 'p1'])).toEqual(['p1', 'p2']);
		expect(moveOps(ROOTS, ['a'], { parent: 'b1', slot: 0 })).toEqual([]);
		expect(moveOps(ROOTS, ['p1'], { parent: 'p2', slot: 0 })).toEqual([]);
	});

	it('moves pages and blocks', () => {
		expect(moveOps(ROOTS, ['p1'], { parent: 'b2', slot: 1 })).toEqual([
			{ op: 'move_page', params: { id: 'p1', block: 'b2', index: 1 } }
		]);
		expect(moveOps(ROOTS, ['b2'], { parent: null, slot: 0 })).toEqual([
			{ op: 'move_block', params: { id: 'b2', index: 0 } }
		]);
		const ops = moveOps(ROOTS, ['p1', 'p2'], { parent: 'b2', slot: 0 });
		expect(shape(applyMoves(ROOTS, ops))).toEqual([{ b1: [] }, { b2: [{ p1: ['a', 'b', 'c'] }, { p2: ['d', 'e'] }, { p3: ['f'] }] }]);
	});

	it('describes the result for the live region', () => {
		const ops = moveOps(ROOTS, ['a'], { parent: 'p2', slot: 2 });
		expect(describeMove(ROOTS, ops, ['a'])).toBe('Moved A to position 3 of 3 in Page p2');
		const many = moveOps(ROOTS, ['a', 'b'], { parent: 'p3', slot: 1 });
		expect(describeMove(ROOTS, many, ['a', 'b'])).toBe('Moved 2 questions to position 2 of 3 in Page p3');
	});
});

describe('keyboardTarget', () => {
	it('Alt+↑/↓ steps past a sibling', () => {
		expect(keyboardTarget(ROOTS, ['b'], -1, false)).toEqual({ parent: 'p1', slot: 0 });
		expect(keyboardTarget(ROOTS, ['b'], 1, false)).toEqual({ parent: 'p1', slot: 3 });
		expect(keyboardTarget(ROOTS, ['a'], -1, false)).toBeNull();
		expect(keyboardTarget(ROOTS, ['c'], 1, false)).toBeNull();
	});

	it('moves a contiguous multi-selection as a group', () => {
		const t = keyboardTarget(ROOTS, ['b', 'c'], -1, false)!;
		expect(shape(applyMoves(ROOTS, moveOps(ROOTS, ['b', 'c'], t)))[0]).toEqual({
			b1: [{ p1: ['b', 'c', 'a'] }, { p2: ['d', 'e'] }]
		});
	});

	it('Alt+Shift crosses to the end of the previous / start of the next page, across blocks', () => {
		expect(keyboardTarget(ROOTS, ['d'], -1, true)).toEqual({ parent: 'p1', slot: 3 });
		expect(keyboardTarget(ROOTS, ['e'], 1, true)).toEqual({ parent: 'p3', slot: 0 });
		expect(keyboardTarget(ROOTS, ['a'], -1, true)).toBeNull();
		expect(keyboardTarget(ROOTS, ['p2'], 1, true)).toEqual({ parent: 'b2', slot: 0 });
		expect(keyboardTarget(ROOTS, ['b1'], 1, true)).toBeNull();
		expect(keyboardTarget(ROOTS, ['b1'], 1, false)).toEqual({ parent: null, slot: 2 });
	});
});

describe('dropTargetAt', () => {
	// Every row expanded, 10px tall, in display order.
	const order: [string, number][] = [
		['b1', 1], ['p1', 2], ['a', 3], ['b', 3], ['c', 3], ['p2', 2], ['d', 3], ['e', 3], ['b2', 1], ['p3', 2], ['f', 3]
	];
	const boxes = boxesFrom(order.map(([id, level], i) => ({ id, level, top: i * 10, bottom: i * 10 + 10 })));

	it('drops a question before/after a question by its midpoint', () => {
		expect(dropTargetAt(boxes, 41, 'question', ROOTS, ['a'])).toMatchObject({
			target: { parent: 'p1', slot: 2 },
			edge: 'before',
			rowId: 'c'
		});
		expect(dropTargetAt(boxes, 48, 'question', ROOTS, ['a'])).toMatchObject({ target: { parent: 'p1', slot: 3 }, edge: 'after' });
	});

	it('drops a question into a page row (at its end)', () => {
		expect(dropTargetAt(boxes, 95, 'question', ROOTS, ['a'])).toMatchObject({ target: { parent: 'p3', slot: 1 }, edge: 'into' });
	});

	it('drops a page relative to the page group under the pointer', () => {
		// Over question e (in p2's lower half): after p2, the line on its last row.
		expect(dropTargetAt(boxes, 75, 'page', ROOTS, ['p1'])).toMatchObject({
			target: { parent: 'b1', slot: 2 },
			edge: 'after',
			lineRowId: 'e'
		});
	});

	it('is null where nothing would move', () => {
		expect(dropTargetAt(boxes, 21, 'question', ROOTS, ['a'])).toBeNull();
		expect(dropTargetAt(boxes, 5, 'question', ROOTS, ['a'])).toBeNull();
	});
});

describe('insertTargetAt (a new question from the toolbox)', () => {
	const order: [string, number][] = [
		['b1', 1], ['p1', 2], ['a', 3], ['b', 3], ['c', 3], ['p2', 2], ['d', 3], ['e', 3], ['b2', 1], ['p3', 2], ['f', 3]
	];
	const boxes = boxesFrom(order.map(([id, level], i) => ({ id, level, top: i * 10, bottom: i * 10 + 10 })));

	it('goes before/after any question, even where a move would be a no-op', () => {
		expect(insertTargetAt(boxes, 21, ROOTS)).toMatchObject({ target: { parent: 'p1', slot: 0 }, edge: 'before', rowId: 'a' });
		expect(insertTargetAt(boxes, 28, ROOTS)).toMatchObject({ target: { parent: 'p1', slot: 1 }, edge: 'after' });
		expect(insertTargetAt(boxes, 78, ROOTS)).toMatchObject({ target: { parent: 'p2', slot: 2 }, edge: 'after', lineRowId: 'e' });
	});

	it('goes into a page at its end, including an empty page', () => {
		expect(insertTargetAt(boxes, 55, ROOTS)).toMatchObject({ target: { parent: 'p2', slot: 2 }, edge: 'into' });
		const empty = [block('b1', page('p1'))];
		const two = boxesFrom([
			{ id: 'b1', level: 1, top: 0, bottom: 10 },
			{ id: 'p1', level: 2, top: 10, bottom: 20 }
		]);
		expect(insertTargetAt(two, 15, empty)).toMatchObject({ target: { parent: 'p1', slot: 0 }, edge: 'into' });
	});

	it('is null over a block row, or with no rows', () => {
		expect(insertTargetAt(boxes, 5, ROOTS)).toBeNull();
		expect(insertTargetAt(boxes, 85, ROOTS)).toBeNull();
		expect(insertTargetAt([], 5, ROOTS)).toBeNull();
	});
});

describe('destinations', () => {
	it('lists the pages (with their block) a question can go to', () => {
		expect(destinations(ROOTS, 'question').map((d) => [d.parent, d.label, d.size])).toEqual([
			['p1', 'Page p1 (Block b1)', 3],
			['p2', 'Page p2 (Block b1)', 2],
			['p3', 'Page p3 (Block b2)', 1]
		]);
	});
});
