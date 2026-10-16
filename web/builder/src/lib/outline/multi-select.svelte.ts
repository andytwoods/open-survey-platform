/**
 * Outline multi-selection (Ctrl/Cmd+click toggles, Shift+click or Shift+↑/↓ extends).
 * Layered on the shared single `SelectionStore`: its id is the primary (focused) item,
 * and a selection made elsewhere (the canvas) that is not in the set resets to just it.
 * Only items of one type are selected together (they move together).
 */
import { SvelteSet } from 'svelte/reactivity';
import { selection as sharedSelection, type SelectionStore } from '../selection.svelte';

export class MultiSelection {
	#ids = new SvelteSet<string>();
	#anchor: string | null = null;
	readonly #primary: SelectionStore;

	constructor(primary: SelectionStore) {
		this.#primary = primary;
	}

	/** Selected ids (primary included), in no particular order. */
	get ids(): string[] {
		const p = this.#primary.id;
		if (!p) return [];
		return this.#ids.has(p) ? [...this.#ids] : [p];
	}

	has(id: string): boolean {
		const p = this.#primary.id;
		if (!p) return false;
		return this.#ids.has(p) ? this.#ids.has(id) : id === p;
	}

	/** Plain click / arrow: just this item. */
	single(id: string) {
		this.#ids.clear();
		this.#ids.add(id);
		this.#anchor = id;
		this.#primary.select(id);
	}

	/** Ctrl/Cmd+click: add or remove `id` (another type starts a new selection). */
	toggle(id: string, typeOf: (id: string) => string | undefined) {
		const current = this.ids;
		if (!current.length || typeOf(current[0]) !== typeOf(id)) return this.single(id);
		if (!this.#ids.has(this.#primary.id ?? '')) {
			this.#ids.clear();
			for (const c of current) this.#ids.add(c);
		}
		if (this.#ids.has(id) && this.#ids.size > 1) {
			this.#ids.delete(id);
			const next = [...this.#ids].at(-1)!;
			this.#primary.select(next);
		} else {
			this.#ids.add(id);
			this.#primary.select(id);
		}
		this.#anchor = id;
	}

	/** Shift+click / Shift+arrow: the anchor through `id`, in `order`, of `id`'s type. */
	range(id: string, order: readonly string[], typeOf: (id: string) => string | undefined) {
		const anchor = this.#anchor && this.has(this.#anchor) ? this.#anchor : this.#primary.id;
		if (!anchor || typeOf(anchor) !== typeOf(id)) return this.single(id);
		const a = order.indexOf(anchor);
		const b = order.indexOf(id);
		if (a < 0 || b < 0) return this.single(id);
		this.#ids.clear();
		const t = typeOf(id);
		for (let i = Math.min(a, b); i <= Math.max(a, b); i++) if (typeOf(order[i]) === t) this.#ids.add(order[i]);
		this.#anchor = anchor;
		this.#primary.select(id);
	}
}

export const outlineSelection = new MultiSelection(sharedSelection);
