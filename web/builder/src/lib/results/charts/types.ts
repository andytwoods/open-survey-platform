// Types for the results charts (task V3, planning/results-viewer.md). The cards come
// straight from V1's results API (`ResultsResponse.cards`); nothing here re-aggregates.
import type { components } from '@osp/api-client';

export type Card = components['schemas']['Card'];
export type Group = components['schemas']['Group'];
export type Cell = components['schemas']['Cell'];
export type Category = components['schemas']['Category'];
export type RowResult = components['schemas']['RowResult'];
export type Facet = components['schemas']['Facet'];
export type StateCounts = components['schemas']['StateCounts'];
export type Stats = components['schemas']['Stats'];
export type CardType = Card['type'];

/** A chart that `buildSpec` can draw. */
export type ChartChoice =
	// single choice
	| 'bars'
	| 'bars-sorted'
	| 'donut'
	// multiple choice
	| 'multi-pct'
	| 'multi-counts'
	| 'dot'
	// numbers (integer, decimal, slider)
	| 'histogram'
	| 'values'
	| 'box'
	| 'cumulative'
	// date
	| 'periods'
	// matrix
	| 'likert'
	| 'stacked100'
	| 'heatmap'
	| 'grouped'
	// text: the response-state counts
	| 'states';

/** A menu entry that is not a chart: the Table view, or a note's display. */
export type NonChartChoice = 'table' | 'hidden' | 'heading';
export type MenuChoice = ChartChoice | NonChartChoice;

/** How a split card (more than one group) lays its groups out. */
export type SplitLayout = 'grouped' | 'stacked' | 'multiples';

export type ChartTheme = 'app' | 'export';

/** The design tokens the app theme reads (CSS custom properties of tokens.css). */
export interface ThemeTokens {
	bg: string;
	surface: string;
	border: string;
	borderStrong: string;
	text: string;
	textMuted: string;
	accent: string;
	font: string;
}

export interface BuildOptions {
	/** Default 'app'. 'export': white background, Okabe-Ito, >= 8 pt text (V-D7). */
	theme?: ChartTheme;
	/** App theme colours; default the light tokens (pass `readTokens()` in the browser). */
	tokens?: ThemeTokens;
	/** Split cards only; default the first layout `chartsFor` offers. */
	split?: SplitLayout;
	/** Draw V1's 95 % intervals (Wilson for proportions, t for means) when present. */
	intervals?: boolean;
	/** The query's denominator, for axis titles. Default 'answered'. */
	denominator?: 'answered' | 'shown';
	/** Chart width in px; default 'container' for single views, 280 px per small multiple. */
	width?: number;
	/** Accessible description (Vega sets it as the SVG's aria-label). */
	description?: string;
}

export interface ChartMenuEntry {
	id: MenuChoice;
	label: string;
}

export interface ChartsFor {
	/** Allowed entries in menu order; the first is the default. */
	choices: ChartMenuEntry[];
	default: MenuChoice;
	/** Split layouts the default chart family supports when the card has groups (else []). */
	splits: SplitLayout[];
	/** Date cards: periods the page may re-query with (`bins.unit`). */
	binUnits?: ('day' | 'week' | 'month' | 'year')[];
}
