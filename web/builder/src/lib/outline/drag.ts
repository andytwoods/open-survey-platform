/**
 * Drop geometry for dragging outline rows (same pointer approach as the choice editor's
 * `reorder.ts`: measure once when the drag starts, then hit-test the pointer's y).
 * `dropTargetAt` is pure, so it is unit tested; `measureRows` only reads the DOM.
 */
import type { OutlineNode } from '../model/outline';
import type { VisibleRow } from './tree-nav';
import { indexTree, moveOps, type DropTarget, type MovableType } from './moves';

export interface RowBox {
	id: string;
	top: number;
	bottom: number;
	/** Bottom of the row's last visible descendant (its own bottom if none). */
	groupBottom: number;
	/** Id of that last visible descendant row (itself if none). */
	lastRowId: string;
}

export interface DragHit {
	target: DropTarget;
	/** The row whose position the drop is relative to. */
	rowId: string;
	edge: 'before' | 'after' | 'into';
	/** The row that draws the indicator (for "after" a group: its last visible row). */
	lineRowId: string;
}

/** Row boxes in display order, with each row's extent including its visible descendants. */
export function boxesFrom(rows: readonly { id: string; level: number; top: number; bottom: number }[]): RowBox[] {
	const out: RowBox[] = rows.map((r) => ({ id: r.id, top: r.top, bottom: r.bottom, groupBottom: r.bottom, lastRowId: r.id }));
	const stack: number[] = [];
	rows.forEach((r, i) => {
		while (stack.length && rows[stack[stack.length - 1]].level >= r.level) stack.pop();
		for (const a of stack) {
			out[a].groupBottom = r.bottom;
			out[a].lastRowId = r.id;
		}
		stack.push(i);
	});
	return out;
}

export function measureRows(tree: HTMLElement, rows: readonly VisibleRow<OutlineNode>[]): RowBox[] {
	return boxesFrom(
		rows.map((r) => {
			const el = tree.querySelector<HTMLElement>(`[data-id="${CSS.escape(r.node.id)}"]`);
			const rect = el?.getBoundingClientRect();
			return { id: r.node.id, level: r.level, top: rect?.top ?? 0, bottom: rect?.bottom ?? 0 };
		})
	);
}

/**
 * Where items of `type` dropped at pointer `y` would go, or null (nowhere valid, or no
 * change). Over an item of the same type (or inside one): before/after it by the middle
 * of its extent. Over a parent that holds this type (a page for questions, a block for
 * pages): into it, at the end.
 */
export function dropTargetAt(
	boxes: readonly RowBox[],
	y: number,
	type: MovableType,
	roots: readonly OutlineNode[],
	ids: readonly string[]
): DragHit | null {
	return movesSomething(gapAt(boxes, y, type, roots), roots, ids);
}

/** The hit, if moving `ids` there changes anything (else null: no indicator, no op). */
function movesSomething(hit: DragHit | null, roots: readonly OutlineNode[], ids: readonly string[]): DragHit | null {
	return hit && moveOps(roots, ids, hit.target).length ? hit : null;
}

/**
 * Where a new question dropped at pointer `y` would go (a type dragged from the toolbox):
 * before/after a question, or into a page at the end. Null over a block.
 */
export function insertTargetAt(boxes: readonly RowBox[], y: number, roots: readonly OutlineNode[]): DragHit | null {
	return gapAt(boxes, y, 'question', roots);
}

/** The gap for an item of `type` at `y`, whether or not anything would move. */
function gapAt(boxes: readonly RowBox[], y: number, type: MovableType, roots: readonly OutlineNode[]): DragHit | null {
	if (!boxes.length) return null;
	const byId = new Map(boxes.map((b) => [b.id, b]));
	let row = boxes.find((b) => y >= b.top && y < b.bottom);
	if (!row) row = y < boxes[0].top ? boxes[0] : boxes[boxes.length - 1];
	const idx = indexTree(roots);
	const siblings = (parent: string | null): string[] => {
		if (parent === null) return roots.map((n) => n.id);
		const find = (ns: readonly OutlineNode[]): OutlineNode | undefined => {
			for (const n of ns) {
				if (n.id === parent) return n;
				const hit = n.children && find(n.children);
				if (hit) return hit;
			}
			return undefined;
		};
		return (find(roots)?.children ?? []).map((n) => n.id);
	};

	let hit: DragHit | null = null;
	// Climb from the row to the nearest node of the dragged type.
	let at: string | null = row.id;
	while (at !== null && idx.get(at)?.type !== type) at = idx.get(at)?.parent ?? null;
	if (at !== null) {
		const box = byId.get(at) ?? row;
		const after = y >= (box.top + box.groupBottom) / 2;
		const parent = idx.get(at)!.parent;
		const slot = siblings(parent).indexOf(at) + (after ? 1 : 0);
		hit = {
			target: { parent, slot },
			rowId: at,
			edge: after ? 'after' : 'before',
			lineRowId: after ? box.lastRowId : at
		};
	} else {
		const holds = idx.get(row.id)?.type === (type === 'question' ? 'page' : type === 'page' ? 'block' : '');
		if (holds) {
			hit = {
				target: { parent: row.id, slot: siblings(row.id).length },
				rowId: row.id,
				edge: 'into',
				lineRowId: row.id
			};
		}
	}
	return hit;
}

// -- the canvas (task B19) ---------------------------------------------------------------
//
// The canvas lays a page out as a header and its question cards one under another, so the
// gap is found per page rather than per row: the page the pointer is over (or the nearest
// one, so headings and the space between pages still drop somewhere), then how many of its
// cards have their middle above the pointer. The result is the same `DragHit` as the
// outline's, so a drop runs the same `add_question` / `moveOps` and both panes can draw it.

export interface CanvasCardBox {
	id: string;
	top: number;
	bottom: number;
}

export interface CanvasPageBox {
	id: string;
	top: number;
	bottom: number;
	cards: CanvasCardBox[];
}

/** The gap at pointer `y`: before a card, after the last one, or into an empty page. */
export function canvasGapAt(pages: readonly CanvasPageBox[], y: number): DragHit | null {
	if (!pages.length || !Number.isFinite(y)) return null;
	let page = pages.find((p) => y >= p.top && y < p.bottom);
	if (!page) {
		const dist = (p: CanvasPageBox) => (y < p.top ? p.top - y : y - p.bottom);
		page = pages.reduce((a, b) => (dist(b) < dist(a) ? b : a));
	}
	const { cards } = page;
	const slot = cards.filter((c) => (c.top + c.bottom) / 2 <= y).length;
	const target = { parent: page.id, slot };
	if (!cards.length) return { target, rowId: page.id, edge: 'into', lineRowId: page.id };
	if (slot < cards.length) return { target, rowId: cards[slot].id, edge: 'before', lineRowId: cards[slot].id };
	const last = cards[cards.length - 1].id;
	return { target, rowId: last, edge: 'after', lineRowId: last };
}

/** Where dragged cards `ids` dropped on the canvas at `y` go; null if nothing would move. */
export function canvasDropAt(
	pages: readonly CanvasPageBox[],
	y: number,
	roots: readonly OutlineNode[],
	ids: readonly string[]
): DragHit | null {
	return movesSomething(canvasGapAt(pages, y), roots, ids);
}

/** Page and card boxes from the canvas DOM (`data-canvas-page` / `data-canvas-question`). */
export function measureCanvas(root: HTMLElement): CanvasPageBox[] {
	return [...root.querySelectorAll<HTMLElement>('[data-canvas-page]')].map((el) => {
		const r = el.getBoundingClientRect();
		return {
			id: el.dataset.canvasPage ?? '',
			top: r.top,
			bottom: r.bottom,
			cards: [...el.querySelectorAll<HTMLElement>('[data-canvas-question]')].map((c) => {
				const b = c.getBoundingClientRect();
				return { id: c.dataset.canvasQuestion ?? '', top: b.top, bottom: b.bottom };
			})
		};
	});
}

/**
 * Where a gap is, by its neighbours (leaving out the items being moved), for screen readers:
 * "Drop between Age and Gender on Page 1", "Drop at the start of Page 1, before Age",
 * "Drop at the end of Page 1, after Gender", "Drop on Page 2, which is empty".
 */
export function describeGap(
	roots: readonly OutlineNode[],
	target: DropTarget,
	moving: readonly string[] = [],
	verb = 'Drop'
): string {
	const find = (ns: readonly OutlineNode[]): OutlineNode | undefined => {
		for (const n of ns) {
			if (n.id === target.parent) return n;
			const hit = n.children && find(n.children);
			if (hit) return hit;
		}
		return undefined;
	};
	const parent = target.parent === null ? undefined : find(roots);
	const where = parent?.label ?? target.parent ?? 'the survey';
	const skip = new Set(moving);
	const kids = parent?.children ?? [];
	const prev = kids
		.slice(0, target.slot)
		.filter((n) => !skip.has(n.id))
		.at(-1);
	const next = kids.slice(target.slot).find((n) => !skip.has(n.id));
	if (prev && next) return `${verb} between ${prev.label} and ${next.label} on ${where}`;
	if (next) return `${verb} at the start of ${where}, before ${next.label}`;
	if (prev) return `${verb} at the end of ${where}, after ${prev.label}`;
	return `${verb} on ${where}, which is empty`;
}
