/**
 * Pure keyboard navigation for a tree view (WAI-ARIA tree pattern). Knows nothing about
 * surveys: it walks any { id, children } tree given the set of expanded ids.
 */
export interface TreeNode {
	id: string;
	children?: readonly TreeNode[];
}

export interface VisibleRow<T extends TreeNode> {
	node: T;
	level: number; // 1-based
	parentId: string | null;
	/** Siblings count and 1-based position, for aria-setsize / aria-posinset. */
	setsize: number;
	posinset: number;
}

/** Rows in display order, skipping children of collapsed nodes. */
export function visibleRows<T extends TreeNode>(
	roots: readonly T[],
	expanded: ReadonlySet<string>
): VisibleRow<T>[] {
	const out: VisibleRow<T>[] = [];
	const walk = (nodes: readonly T[], level: number, parentId: string | null) => {
		nodes.forEach((node, i) => {
			out.push({ node, level, parentId, setsize: nodes.length, posinset: i + 1 });
			if (node.children?.length && expanded.has(node.id)) {
				walk(node.children as readonly T[], level + 1, node.id);
			}
		});
	};
	walk(roots, 1, null);
	return out;
}

/** Ids of every ancestor of `id`, root first. Empty if not found or top-level. */
export function ancestorsOf(roots: readonly TreeNode[], id: string): string[] {
	const path: string[] = [];
	const walk = (nodes: readonly TreeNode[]): boolean => {
		for (const n of nodes) {
			if (n.id === id) return true;
			path.push(n.id);
			if (n.children && walk(n.children)) return true;
			path.pop();
		}
		return false;
	};
	return walk(roots) ? path : [];
}

export function findNode<T extends TreeNode>(roots: readonly T[], id: string): T | undefined {
	for (const n of roots) {
		if (n.id === id) return n;
		const hit = n.children && findNode(n.children as readonly T[], id);
		if (hit) return hit;
	}
	return undefined;
}

export type NavResult =
	| { kind: 'focus'; id: string }
	| { kind: 'expand'; id: string }
	| { kind: 'collapse'; id: string }
	| { kind: 'none' };

/** What a key press does from `currentId`. The caller applies it. */
export function navigate<T extends TreeNode>(
	key: string,
	currentId: string,
	roots: readonly T[],
	expanded: ReadonlySet<string>
): NavResult {
	const rows = visibleRows(roots, expanded);
	const i = rows.findIndex((r) => r.node.id === currentId);
	if (i < 0) return rows[0] ? { kind: 'focus', id: rows[0].node.id } : { kind: 'none' };
	const row = rows[i];
	const hasKids = !!row.node.children?.length;
	const isOpen = expanded.has(row.node.id);

	switch (key) {
		case 'ArrowDown':
			return rows[i + 1] ? { kind: 'focus', id: rows[i + 1].node.id } : { kind: 'none' };
		case 'ArrowUp':
			return rows[i - 1] ? { kind: 'focus', id: rows[i - 1].node.id } : { kind: 'none' };
		case 'Home':
			return { kind: 'focus', id: rows[0].node.id };
		case 'End':
			return { kind: 'focus', id: rows[rows.length - 1].node.id };
		case 'ArrowRight':
			if (!hasKids) return { kind: 'none' };
			if (!isOpen) return { kind: 'expand', id: row.node.id };
			return { kind: 'focus', id: row.node.children![0].id };
		case 'ArrowLeft':
			if (hasKids && isOpen) return { kind: 'collapse', id: row.node.id };
			return row.parentId ? { kind: 'focus', id: row.parentId } : { kind: 'none' };
		default:
			return { kind: 'none' };
	}
}
