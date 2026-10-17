import { describe, expect, it } from 'vitest';
import type { OutlineNode } from '../model/outline';
import { canvasDropAt, canvasGapAt, describeGap, type CanvasPageBox } from './drag';
import { moveOps } from './moves';

// Canvas hit-testing (B19): pointer y → (page, slot) over page and card boxes, the same
// DragHit the outline uses, and the spoken description of a gap.

const q = (id: string, label = id): OutlineNode => ({ id, type: 'question', label });
const roots: OutlineNode[] = [
	{
		id: 'b1',
		type: 'block',
		label: 'Block 1',
		children: [
			{ id: 'p1', type: 'page', label: 'Page 1', children: [q('q1', 'Age'), q('q2', 'Gender'), q('q3', 'Town')] },
			{ id: 'p2', type: 'page', label: 'Page 2', children: [] }
		]
	}
];

// Page 1: header 0–40, cards 40–140, 152–252, 264–364, page ends 420 (the Add button).
// Page 2 (empty): 460–560.
const boxes: CanvasPageBox[] = [
	{
		id: 'p1',
		top: 0,
		bottom: 420,
		cards: [
			{ id: 'q1', top: 40, bottom: 140 },
			{ id: 'q2', top: 152, bottom: 252 },
			{ id: 'q3', top: 264, bottom: 364 }
		]
	},
	{ id: 'p2', top: 460, bottom: 560, cards: [] }
];

describe('canvasGapAt', () => {
	it('splits each card at its middle: the gap before or after it', () => {
		expect(canvasGapAt(boxes, 50)).toEqual({ target: { parent: 'p1', slot: 0 }, rowId: 'q1', edge: 'before', lineRowId: 'q1' });
		expect(canvasGapAt(boxes, 100)?.target).toEqual({ parent: 'p1', slot: 1 });
		// Between cards 1 and 2 (in the gap itself, or the top half of card 2).
		expect(canvasGapAt(boxes, 146)).toMatchObject({ target: { parent: 'p1', slot: 1 }, rowId: 'q2', edge: 'before' });
		expect(canvasGapAt(boxes, 190)?.target).toEqual({ parent: 'p1', slot: 1 });
		expect(canvasGapAt(boxes, 210)?.target).toEqual({ parent: 'p1', slot: 2 });
	});

	it('the page header is the start; below the last card is the end', () => {
		expect(canvasGapAt(boxes, 5)?.target).toEqual({ parent: 'p1', slot: 0 });
		expect(canvasGapAt(boxes, 400)).toEqual({ target: { parent: 'p1', slot: 3 }, rowId: 'q3', edge: 'after', lineRowId: 'q3' });
	});

	it('an empty page is one drop zone', () => {
		expect(canvasGapAt(boxes, 500)).toEqual({ target: { parent: 'p2', slot: 0 }, rowId: 'p2', edge: 'into', lineRowId: 'p2' });
	});

	it('between pages, above the first and below the last: the nearest page', () => {
		expect(canvasGapAt(boxes, 430)?.target).toEqual({ parent: 'p1', slot: 3 });
		expect(canvasGapAt(boxes, 455)?.target).toEqual({ parent: 'p2', slot: 0 });
		expect(canvasGapAt(boxes, -50)?.target).toEqual({ parent: 'p1', slot: 0 });
		expect(canvasGapAt(boxes, 900)?.target).toEqual({ parent: 'p2', slot: 0 });
	});

	it('no pages, or a pointer that is not a number: nowhere', () => {
		expect(canvasGapAt([], 10)).toBeNull();
		expect(canvasGapAt(boxes, Number.NaN)).toBeNull();
	});

	it('the gap feeds the outline move op unchanged', () => {
		const hit = canvasGapAt(boxes, 500)!;
		expect(moveOps(roots, ['q1'], hit.target)).toEqual([{ op: 'move_question', params: { id: 'q1', page: 'p2', index: 0 } }]);
	});
});

describe('canvasDropAt (reordering cards)', () => {
	it('a gap next to the dragged card moves nothing: null, no indicator', () => {
		expect(canvasDropAt(boxes, 146, roots, ['q2'])).toBeNull(); // just before itself
		expect(canvasDropAt(boxes, 230, roots, ['q2'])).toBeNull(); // just after itself
	});

	it('elsewhere: the same target as the outline would use', () => {
		expect(canvasDropAt(boxes, 50, roots, ['q2'])?.target).toEqual({ parent: 'p1', slot: 0 });
		expect(canvasDropAt(boxes, 400, roots, ['q1'])?.target).toEqual({ parent: 'p1', slot: 3 });
		expect(canvasDropAt(boxes, 500, roots, ['q3'])?.target).toEqual({ parent: 'p2', slot: 0 });
	});
});

describe('describeGap', () => {
	it('names the neighbours and the page', () => {
		expect(describeGap(roots, { parent: 'p1', slot: 1 })).toBe('Drop between Age and Gender on Page 1');
		expect(describeGap(roots, { parent: 'p1', slot: 0 })).toBe('Drop at the start of Page 1, before Age');
		expect(describeGap(roots, { parent: 'p1', slot: 3 })).toBe('Drop at the end of Page 1, after Town');
		expect(describeGap(roots, { parent: 'p2', slot: 0 })).toBe('Drop on Page 2, which is empty');
	});

	it('leaves out the items being moved, and takes a verb', () => {
		expect(describeGap(roots, { parent: 'p1', slot: 2 }, ['q2'])).toBe('Drop between Age and Town on Page 1');
		expect(describeGap(roots, { parent: 'p1', slot: 1 }, ['q1'], 'Place here')).toBe(
			'Place here at the start of Page 1, before Gender'
		);
	});
});
