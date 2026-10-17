import type { MenuChoice, SplitLayout } from './charts/types';

/**
 * What the researcher chose per question (tasks V2, V4): the chart, how a split card lays
 * out its groups, a date card's period, and chart or Table view. Kept for the page's
 * lifetime; saved layouts (V5) will persist it. A choice the card's menu (`chartsFor`)
 * does not offer falls back to the menu's default without being forgotten.
 */
export class ChartChoices {
	#chosen = $state<Record<string, MenuChoice>>({});
	#layouts = $state<Record<string, SplitLayout>>({});
	#units = $state<Record<string, string>>({});
	/** Per card: show the chart or the table. */
	#views = $state<Record<string, 'chart' | 'table'>>({});

	get all(): Readonly<Record<string, MenuChoice>> {
		return this.#chosen;
	}

	get(question: string): MenuChoice | undefined {
		return this.#chosen[question];
	}

	choose(question: string, chart: MenuChoice) {
		this.#chosen = { ...this.#chosen, [question]: chart };
	}

	layout(question: string): SplitLayout | undefined {
		return this.#layouts[question];
	}

	setLayout(question: string, layout: SplitLayout) {
		this.#layouts = { ...this.#layouts, [question]: layout };
	}

	/** Date cards: the period per bar ('month' when not chosen). */
	get units(): Readonly<Record<string, string>> {
		return this.#units;
	}

	unit(question: string): string {
		return this.#units[question] ?? 'month';
	}

	setUnit(question: string, unit: string) {
		this.#units = { ...this.#units, [question]: unit };
	}

	view(question: string): 'chart' | 'table' {
		return this.#views[question] ?? 'chart';
	}

	setView(question: string, view: 'chart' | 'table') {
		this.#views = { ...this.#views, [question]: view };
	}
}
