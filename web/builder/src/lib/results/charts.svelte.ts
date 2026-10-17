/**
 * The chart chosen per question (task V2). Kept for the page's lifetime; saved layouts
 * (V5) will persist it. A choice the current menu does not offer (e.g. after a split is
 * added) falls back to the menu's default without forgetting it.
 */
export class ChartChoices {
	#chosen = $state<Record<string, string>>({});
	/** Per card: show the chart or the table. */
	#views = $state<Record<string, 'chart' | 'table'>>({});

	get all(): Readonly<Record<string, string>> {
		return this.#chosen;
	}

	get(question: string): string | undefined {
		return this.#chosen[question];
	}

	choose(question: string, chart: string) {
		this.#chosen = { ...this.#chosen, [question]: chart };
	}

	view(question: string): 'chart' | 'table' {
		return this.#views[question] ?? 'chart';
	}

	setView(question: string, view: 'chart' | 'table') {
		this.#views = { ...this.#views, [question]: view };
	}
}
