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
	const hit = gapAt(boxes, y, type, roots);
	if (!hit || !moveOps(roots, ids, hit.target).length) return null;
	return hit;
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
