/**
 * Selection shared by every pane: the id of the selected outline node (or null).
 * Panes read `selection.id` and call `select()`; nothing else owns selection.
 */
export class SelectionStore {
	id = $state<string | null>(null);
	// Listener bookkeeping, deliberately not reactive.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	#listeners = new Set<(id: string | null) => void>();

	select(id: string | null) {
		if (id === this.id) return;
		this.id = id;
		for (const fn of this.#listeners) fn(id);
	}

	clear() {
		this.select(null);
	}

	isSelected(id: string): boolean {
		return this.id === id;
	}

	/** Non-reactive subscription (for code outside components). Returns unsubscribe. */
	onChange(fn: (id: string | null) => void): () => void {
		this.#listeners.add(fn);
		return () => this.#listeners.delete(fn);
	}
}

export const selection = new SelectionStore();
