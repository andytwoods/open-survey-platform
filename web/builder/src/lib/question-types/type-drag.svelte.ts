/**
 * Something dragged from the toolbox onto the outline or the canvas (B16, B19, QB5): a
 * question type, or a bank item (QB5's Bank section). The toolbox owns the pointer; each
 * drop zone owns its geometry: it attaches a resolver that turns a pointer position into a
 * gap (or null when the pointer is not over it), and draws the indicator for `hit`. The
 * first resolver that answers wins.
 */
import type { DragHit } from '../outline/drag';
import type { QuestionTypeId } from './catalogue';

export interface InsertHit {
	hit: DragHit;
	/** Spoken while dragging, e.g. "Drop between Age and Gender on Page 1". */
	description: string;
}

export type InsertResolver = (x: number, y: number) => InsertHit | null;

/** What is being dragged: a question type, or a bank item (question, page or block). */
export type DragItem =
	| { kind: 'type'; type: QuestionTypeId }
	| { kind: 'bank'; id: string; label: string; itemKind: 'question' | 'page' | 'block' };

export class TypeDrag {
	item = $state<DragItem | null>(null);
	hit = $state<InsertHit | null>(null);
	/** The pointer's last position (for auto-scrolling); not reactive. */
	x = 0;
	y = 0;
	#resolvers: InsertResolver[] = [];

	/** The question type being dragged (null for a bank item, or when nothing is). */
	get type(): QuestionTypeId | null {
		return this.item?.kind === 'type' ? this.item.type : null;
	}

	/** Is anything being dragged? */
	get active(): boolean {
		return this.item !== null;
	}

	/** Add a drop zone's resolver; returns a detach function. */
	attach(resolver: InsertResolver): () => void {
		this.#resolvers = [...this.#resolvers, resolver];
		return () => {
			this.#resolvers = this.#resolvers.filter((r) => r !== resolver);
		};
	}

	start(item: DragItem | QuestionTypeId) {
		this.item = typeof item === 'string' ? { kind: 'type', type: item } : item;
		this.hit = null;
	}

	/** Follow the pointer; true when the gap under it changed. */
	move(x: number, y: number): boolean {
		if (!this.item) return false;
		this.x = x;
		this.y = y;
		let next: InsertHit | null = null;
		for (const r of this.#resolvers) {
			next = r(x, y);
			if (next) break;
		}
		const a = this.hit?.hit;
		const b = next?.hit;
		const changed =
			a?.rowId !== b?.rowId ||
			a?.edge !== b?.edge ||
			a?.target.parent !== b?.target.parent ||
			a?.target.slot !== b?.target.slot;
		this.hit = next;
		return changed;
	}

	/** Look again where the pointer is (the zone under it scrolled); true if the gap changed. */
	refresh(): boolean {
		return this.move(this.x, this.y);
	}

	/** End the drag; the gap it ended over, if any. */
	end(): InsertHit | null {
		const hit = this.item ? this.hit : null;
		this.item = null;
		this.hit = null;
		return hit;
	}
}
