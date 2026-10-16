/** Reorder geometry and keys for the choice rows (pure, so it can be unit tested). */

/**
 * Where a dragged row lands: its final index, given the rows' vertical midpoints (in the
 * current order, measured when the drag started) and the pointer's y.
 */
export function dropIndex(mids: readonly number[], y: number, from: number): number {
	let to = 0;
	for (let i = 0; i < mids.length; i++) if (i !== from && y > mids[i]) to++;
	return to;
}

/**
 * The drop-indicator slot (0..n, a gap between rows in the current order) for a move
 * from `from` to `to`, or null when the row would not move.
 */
export function dropSlot(from: number, to: number): number | null {
	if (from === to) return null;
	return to > from ? to + 1 : to;
}

/** Alt+↑ / Alt+↓ on row `i` of `n`: the target index, or null (not a move key, or an edge). */
export function keyMoveTarget(e: Pick<KeyboardEvent, 'key' | 'altKey' | 'ctrlKey' | 'metaKey' | 'shiftKey'>, i: number, n: number): number | null {
	if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return null;
	if (e.key === 'ArrowUp') return i > 0 ? i - 1 : null;
	if (e.key === 'ArrowDown') return i < n - 1 ? i + 1 : null;
	return null;
}
