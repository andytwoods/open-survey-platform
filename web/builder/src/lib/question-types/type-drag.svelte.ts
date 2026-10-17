/**
 * A question type being dragged from the toolbox onto the outline. The toolbox owns the
 * pointer; the outline owns the geometry: it attaches a resolver that turns a pointer
 * position into a gap (or null), and draws the indicator for `hit`.
 */
import type { DragHit } from '../outline/drag';
import type { QuestionTypeId } from './catalogue';

export interface InsertHit {
	hit: DragHit;
	/** Spoken while dragging, e.g. "Drop after Age". */
	description: string;
}

export type InsertResolver = (x: number, y: number) => InsertHit | null;

export class TypeDrag {
	type = $state<QuestionTypeId | null>(null);
	hit = $state<InsertHit | null>(null);
	#resolver: InsertResolver | null = null;

	/** The outline's resolver; returns a detach function. */
	attach(resolver: InsertResolver): () => void {
		this.#resolver = resolver;
		return () => {
			if (this.#resolver === resolver) this.#resolver = null;
		};
	}

	start(type: QuestionTypeId) {
		this.type = type;
		this.hit = null;
	}

	/** Follow the pointer; true when the gap under it changed. */
	move(x: number, y: number): boolean {
		if (!this.type) return false;
		const next = this.#resolver?.(x, y) ?? null;
		const a = this.hit?.hit;
		const b = next?.hit;
		const changed = a?.rowId !== b?.rowId || a?.edge !== b?.edge;
		this.hit = next;
		return changed;
	}

	/** End the drag; the gap it ended over, if any. */
	end(): InsertHit | null {
		const hit = this.type ? this.hit : null;
		this.type = null;
		this.hit = null;
		return hit;
	}
}
