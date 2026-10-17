/**
 * The seam between the results page (V2) and the charts (V3). A card hands the chart slot
 * a `spec` and a `theme`, the props V3's `<ResultsChart spec theme>` takes. Until V3 lands,
 * `chartSpec` builds a data-only placeholder (the aggregate rows plus which chart was
 * chosen) and `ResultsChartSlot.svelte` draws it as a table; V3 swaps both for its
 * Vega-Lite spec builders and component. Nothing here aggregates: rows are the server's.
 */
import type { CardType, ResultUnit } from './types';

export type ResultsChartTheme = 'light' | 'dark';

/** One aggregate row of a chart: a cell of a group. */
export interface ChartDatum {
	group: string;
	category: string;
	count: number;
	pct: number | null;
}

/** What a chart is built from. V3's specs are Vega-Lite; the placeholder carries data only. */
export interface ResultsChartSpec {
	description: string;
	data: { values: ChartDatum[] };
	usermeta: { chart: string; chartLabel: string; question: string; type: CardType; denominator: string };
	[key: string]: unknown;
}

export function chartSpec(opts: {
	question: string;
	label: string;
	type: CardType;
	chart: string;
	chartLabel: string;
	denominator: string;
	unit: ResultUnit;
}): ResultsChartSpec {
	const values: ChartDatum[] = [];
	for (const g of opts.unit.groups) {
		for (const c of g.cells) values.push({ group: g.label, category: c.label, count: c.count, pct: c.pct });
	}
	return {
		description: `${opts.chartLabel}: ${opts.label}`,
		data: { values },
		usermeta: {
			chart: opts.chart,
			chartLabel: opts.chartLabel,
			question: opts.question,
			type: opts.type,
			denominator: opts.denominator
		}
	};
}
