/**
 * Optimistic outline moves (builder-design §4): the outline shows the move at once, the
 * ops go to the server as one transaction, and the overlay is dropped when it answers.
 * Applied: the store already holds the server's patch, so the view is reconciled to it.
 * Rejected (422): the overlay goes and the old order is back; the shell shows the
 * diagnostic. Moves made while one is in flight are computed on the optimistic view, which
 * is what the server will have when they reach it (the store sends in order).
 */
import { announce } from '@osp/ui-components';
import type { OutlineNode } from '../model/outline';
import type { Outcome } from '../sync/survey-store.svelte';
import type { Invocation } from '../sync/transport';
import { applyMoves, describeMove, moveOps, movableIds, type DropTarget } from './moves';

export type Submit = (ops: Invocation[]) => Promise<Outcome>;

export class OutlineMover {
	/** Batches sent and not yet answered, oldest first. */
	pending = $state.raw<Invocation[][]>([]);

	/** `roots` with every unanswered move applied. */
	view(roots: OutlineNode[]): OutlineNode[] {
		let out = roots;
		for (const ops of this.pending) out = applyMoves(out, ops);
		return out;
	}

	/** Move `ids` to `target` as one transaction. Null if nothing would move. */
	async move(submit: Submit, roots: OutlineNode[], ids: readonly string[], target: DropTarget): Promise<Outcome | null> {
		const moving = movableIds(roots, ids);
		const ops = moveOps(roots, moving, target);
		if (!ops.length) {
			announce('Already there.');
			return null;
		}
		const message = describeMove(roots, ops, moving);
		this.pending = [...this.pending, ops];
		let out: Outcome;
		try {
			out = await submit(ops);
		} finally {
			this.pending = this.pending.filter((b) => b !== ops);
		}
		if (out.status === 'applied') announce(message);
		else if (out.status === 'rejected') {
			const why = out.diagnostics[0]?.message ?? out.message;
			announce(`Move not applied: ${why}`, 'assertive');
		}
		return out;
	}
}
