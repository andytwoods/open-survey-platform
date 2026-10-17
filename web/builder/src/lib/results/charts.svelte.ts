import type { MenuChoice, SplitLayout } from './charts/types';
import type { CardBins } from './model';

/**
 * What the researcher chose per question (tasks V2, V4, V5): the chart, how a split card
 * lays out its groups, its bins (a date card's period; a saved layout may also carry a bin
 * width or count), whether the card is hidden, and chart or Table view. Saved layouts (V5)
 * persist all but the view. A choice the card's menu (`chartsFor`) does not offer falls
 * back to the menu's default without being forgotten.
 */
export interface CardChoices {
	chosen: Record<string, MenuChoice>;
	layouts: Record<string, SplitLayout>;
	bins: Record<string, CardBins>;
	hidden: Record<string, boolean>;
}

export class ChartChoices {
	#chosen = $state<Record<string, MenuChoice>>({});
	#layouts = $state<Record<string, SplitLayout>>({});
	#bins = $state<Record<string, CardBins>>({});
	#hidden = $state<Record<string, boolean>>({});
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

	/** Per card bins (only the cards that have any). */
	get bins(): Readonly<Record<string, CardBins>> {
		return this.#bins;
	}

	/** Date cards: the period per bar ('month' when not chosen). */
	unit(question: string): string {
		return this.#bins[question]?.unit ?? 'month';
	}

	setUnit(question: string, unit: string) {
		this.#bins = { ...this.#bins, [question]: { ...this.#bins[question], unit: unit as CardBins['unit'] } };
	}

	hidden(question: string): boolean {
		return !!this.#hidden[question];
	}

	setHidden(question: string, hidden: boolean) {
		const next = { ...this.#hidden };
		if (hidden) next[question] = true;
		else delete next[question];
		this.#hidden = next;
	}

	view(question: string): 'chart' | 'table' {
		return this.#views[question] ?? 'chart';
	}

	setView(question: string, view: 'chart' | 'table') {
		this.#views = { ...this.#views, [question]: view };
	}

	/** A plain copy of what a saved layout keeps (not the chart/table view). */
	snapshot(): CardChoices {
		return {
			chosen: { ...this.#chosen },
			layouts: { ...this.#layouts },
			bins: Object.fromEntries(Object.entries(this.#bins).map(([q, b]) => [q, { ...b }])),
			hidden: { ...this.#hidden }
		};
	}

	/** Replace what a saved layout keeps (a layout was opened). */
	restore(c: CardChoices) {
		this.#chosen = { ...c.chosen };
		this.#layouts = { ...c.layouts };
		this.#bins = Object.fromEntries(Object.entries(c.bins).map(([q, b]) => [q, { ...b }]));
		this.#hidden = { ...c.hidden };
	}
}
