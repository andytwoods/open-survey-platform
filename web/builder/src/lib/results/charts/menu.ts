// The chart menu per question type (planning/results-viewer.md, "Chart menu per question
// type"): which charts suit a card, and which is the default. V2's per-card menu reads it.
import type { Card, ChartChoice, ChartMenuEntry, ChartsFor, MenuChoice, SplitLayout } from './types';

export const CHART_LABELS: Record<MenuChoice, string> = {
	bars: 'Bars',
	'bars-sorted': 'Sorted bars',
	donut: 'Donut',
	'multi-pct': '% of respondents',
	'multi-counts': 'Counts',
	dot: 'Dot plot',
	histogram: 'Histogram',
	values: 'Frequency bars',
	box: 'Box plot',
	cumulative: 'Cumulative distribution',
	periods: 'Counts per period',
	likert: 'Diverging stacked bars',
	stacked100: '100 % stacked bars',
	heatmap: 'Heatmap',
	grouped: 'Grouped bars',
	states: 'Response states',
	table: 'Table',
	hidden: 'Hidden',
	heading: 'Show as heading'
};

const entry = (id: MenuChoice): ChartMenuEntry => ({ id, label: CHART_LABELS[id] });

/** True when the card (or one of its matrix rows / facets) has more than one group. */
export function isSplit(card: Card): boolean {
	const units = card.facets?.length ? card.facets : [card];
	return units.some((u) => (u.groups?.length ?? 0) > 1 || (u.rows ?? []).some((r) => r.groups.length > 1));
}

/** How a chart can lay out split groups ([] when the card has no split). */
export function splitsFor(card: Card, choice: MenuChoice): SplitLayout[] {
	if (!isSplit(card)) return [];
	switch (choice) {
		case 'bars':
		case 'bars-sorted':
			return ['grouped', 'stacked', 'multiples'];
		case 'multi-pct':
		case 'multi-counts':
		case 'dot':
		case 'values':
		case 'periods':
			// Multiple-choice shares can sum to more than 100 %: never stacked.
			return choice === 'periods' ? ['grouped', 'stacked', 'multiples'] : ['grouped', 'multiples'];
		case 'cumulative':
			return ['grouped', 'multiples'];
		case 'box':
			return ['grouped'];
		case 'donut':
		case 'histogram':
		case 'likert':
		case 'stacked100':
		case 'heatmap':
		case 'grouped':
			return ['multiples'];
		default:
			return [];
	}
}

function numberChoices(card: Card): ChartChoice[] {
	const units = card.facets?.length ? card.facets : [card];
	// V1 sends slider cards with <= 21 steps as one cell per value ("values"), else bins.
	const values = card.type === 'slider' && units.every((u) => u.binning === 'values');
	return [values ? 'values' : 'histogram', 'box', 'cumulative'];
}

/** Allowed chart choices and the default for a card, by question type. */
export function chartsFor(card: Card): ChartsFor {
	let ids: MenuChoice[];
	let binUnits: ChartsFor['binUnits'];
	switch (card.type) {
		case 'single':
			ids = ['bars', 'bars-sorted', 'donut', 'table'];
			break;
		case 'multi':
			ids = ['multi-pct', 'multi-counts', 'dot', 'table'];
			break;
		case 'integer':
		case 'decimal':
		case 'slider':
			ids = [...numberChoices(card), 'table'];
			break;
		case 'date':
			ids = ['periods', 'table'];
			binUnits = ['day', 'week', 'month', 'year'];
			break;
		case 'matrix':
			ids = card.ordered ? ['likert', 'stacked100', 'heatmap', 'table'] : ['grouped', 'heatmap', 'table'];
			break;
		case 'text':
			ids = ['states', 'table'];
			break;
		case 'note':
			ids = ['hidden', 'heading'];
			break;
		default:
			ids = ['table'];
	}
	const out: ChartsFor = { choices: ids.map(entry), default: ids[0], splits: splitsFor(card, ids[0]) };
	if (binUnits) out.binUnits = binUnits;
	return out;
}

/** Whether `choice` is a chart `buildSpec` draws (not the table or a note display). */
export function isChart(choice: MenuChoice): choice is ChartChoice {
	return choice !== 'table' && choice !== 'hidden' && choice !== 'heading';
}
