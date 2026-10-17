/**
 * The results page's pure logic (task V2): the filter bar's state and how it maps to the
 * results query (V1), the chart menu per question type (planning/results-viewer.md), and
 * how states and statistics are labelled. No aggregation happens here: every number comes
 * from the server (V-D2); this only chooses what to ask for and how to name it.
 */
import type {
	Card,
	CardRequest,
	CardType,
	Category,
	Facet,
	ResultsQuery,
	ResultUnit,
	RowResult,
	StateCounts,
	Stats
} from './types';

// -- filters ----------------------------------------------------------------------------

export type Status = 'complete' | 'all';
export type Denominator = 'answered' | 'shown';

export interface AnswerFilter {
	/** A single- or multiple-choice question id, or a matrix row variable. */
	question: string;
	/** Category keys (codes as text). */
	codes: string[];
}

export interface Split {
	kind: 'question' | 'condition';
	id: string;
}

export interface ResultsFilters {
	/** Published version numbers; empty: the latest. */
	versions: number[];
	status: Status;
	/** Submission dates, `YYYY-MM-DD`, both inclusive; '' for none. */
	from: string;
	to: string;
	condition: { variable: string; levels: string[] } | null;
	answers: AnswerFilter[];
	split: Split | null;
	denominator: Denominator;
	/** Label language; null: the survey's main language. */
	language: string | null;
}

/** The page's starting point: the latest published version, complete responses only. */
export function defaultFilters(publishedVersions: number): ResultsFilters {
	return {
		versions: publishedVersions > 0 ? [publishedVersions] : [],
		status: 'complete',
		from: '',
		to: '',
		condition: null,
		answers: [],
		split: null,
		denominator: 'answered',
		language: null
	};
}

export function cloneFilters(f: ResultsFilters): ResultsFilters {
	return {
		...f,
		versions: [...f.versions],
		condition: f.condition ? { variable: f.condition.variable, levels: [...f.condition.levels] } : null,
		answers: f.answers.map((a) => ({ question: a.question, codes: [...a.codes] })),
		split: f.split ? { ...f.split } : null
	};
}

export function sameFilters(a: ResultsFilters, b: ResultsFilters): boolean {
	return JSON.stringify(normalised(a)) === JSON.stringify(normalised(b));
}

function normalised(f: ResultsFilters) {
	return {
		...f,
		versions: [...f.versions].sort((x, y) => x - y),
		answers: f.answers.filter((a) => a.codes.length).map((a) => ({ ...a, codes: [...a.codes].sort() })),
		condition: f.condition?.levels.length ? { ...f.condition, levels: [...f.condition.levels].sort() } : null
	};
}

const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

function validDay(s: string): boolean {
	const m = DAY.exec(s);
	if (!m) return false;
	const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
	return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
}

/** The day after `day` (`YYYY-MM-DD`), as the query's exclusive end (UTC midnight). */
export function endExclusive(day: string): string {
	const m = DAY.exec(day)!;
	const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3] + 1));
	return d.toISOString().replace('.000Z', 'Z');
}

export function startInclusive(day: string): string {
	return `${day}T00:00:00Z`;
}

/** Problems that stop the filters being applied (shown next to the controls). */
export function filterProblems(f: ResultsFilters): { field: 'from' | 'to'; message: string }[] {
	const out: { field: 'from' | 'to'; message: string }[] = [];
	if (f.from && !validDay(f.from)) out.push({ field: 'from', message: 'Enter the start date as YYYY-MM-DD.' });
	if (f.to && !validDay(f.to)) out.push({ field: 'to', message: 'Enter the end date as YYYY-MM-DD.' });
	if (!out.length && f.from && f.to && f.to < f.from) {
		out.push({ field: 'to', message: 'The end date is before the start date.' });
	}
	return out;
}

/**
 * The results query for these filters. Dates are whole days in UTC: `from` is inclusive
 * and `to` includes its whole day (the API's `submittedTo` is exclusive). Answer filters
 * without a chosen code are left out. `cards` (with per-card bins) only when needed.
 */
export function toQuery(f: ResultsFilters, cards?: CardRequest[]): ResultsQuery {
	const q: ResultsQuery = { status: f.status, denominator: f.denominator, intervals: false };
	if (f.versions.length) q.versions = [...f.versions].sort((a, b) => a - b);
	if (f.from && validDay(f.from)) q.submittedFrom = startInclusive(f.from);
	if (f.to && validDay(f.to)) q.submittedTo = endExclusive(f.to);
	const filters = f.answers.filter((a) => a.question && a.codes.length);
	if (filters.length) q.filters = filters.map((a) => ({ question: a.question, in: [...a.codes] }));
	if (f.condition && f.condition.levels.length) {
		q.condition = { variable: f.condition.variable, in: [...f.condition.levels] };
	}
	if (f.split) {
		q.split =
			f.split.kind === 'question'
				? { question: f.split.id, excludeMissing: false }
				: { condition: f.split.id, excludeMissing: false };
	}
	if (f.language) q.language = f.language;
	if (cards) q.cards = cards;
	return q;
}

/** The text endpoint's query parameters for the same filters (no split, no denominator). */
export function toTextParams(f: ResultsFilters): {
	versions?: number[];
	status: Status;
	submittedFrom?: string;
	submittedTo?: string;
	filter?: string[];
	condition?: string;
} {
	const q = toQuery(f);
	const out: ReturnType<typeof toTextParams> = { status: q.status };
	if (q.versions) out.versions = q.versions;
	if (q.submittedFrom) out.submittedFrom = q.submittedFrom;
	if (q.submittedTo) out.submittedTo = q.submittedTo;
	if (q.filters?.length) out.filter = q.filters.map((a) => `${a.question}:${a.in.join(',')}`);
	if (q.condition) out.condition = `${q.condition.variable}:${q.condition.in.join(',')}`;
	return out;
}

// -- what the filter bar offers ---------------------------------------------------------

export interface ChoiceVariable {
	/** The variable id (a matrix row: `<matrix>_<row>`). */
	id: string;
	label: string;
	codes: { key: string; label: string }[];
	/** Single choice and matrix rows can split; multiple choice can only filter. */
	splittable: boolean;
}

export interface ConditionVariable {
	id: string;
	levels: string[];
}

/**
 * The choice variables the cards of a response offer, in survey order. Category lists
 * are declared, not data, so they do not change with the filters.
 */
export function choiceVariables(cards: readonly Card[]): ChoiceVariable[] {
	const out: ChoiceVariable[] = [];
	for (const c of cards) {
		const cats = c.categories ?? c.facets?.at(-1)?.categories ?? [];
		const codes = cats.map((k) => ({ key: k.key, label: k.label }));
		if (c.type === 'single' || c.type === 'multi') {
			out.push({ id: c.question, label: c.label, codes, splittable: c.type === 'single' });
		} else if (c.type === 'matrix') {
			const rows = c.rows ?? c.facets?.at(-1)?.rows ?? [];
			for (const r of rows) out.push({ id: r.id, label: `${c.label}: ${r.label}`, codes, splittable: true });
		}
	}
	return out;
}

/** The assigned variables (between-subjects conditions) of a survey document. */
export function conditionVariables(survey: unknown): ConditionVariable[] {
	const vars = (survey as { variables?: unknown } | null)?.variables;
	if (!Array.isArray(vars)) return [];
	const out: ConditionVariable[] = [];
	for (const v of vars) {
		if (!v || typeof v !== 'object') continue;
		const { kind, id, levels } = v as { kind?: unknown; id?: unknown; levels?: unknown };
		if (kind !== 'assigned' || typeof id !== 'string' || !Array.isArray(levels)) continue;
		out.push({ id, levels: levels.filter((l) => typeof l === 'string' || typeof l === 'number').map(String) });
	}
	return out;
}

const list = (xs: string[]) =>
	xs.length <= 1 ? (xs[0] ?? '') : `${xs.slice(0, -1).join(', ')} or ${xs[xs.length - 1]}`;

/**
 * The active filters in words, for the line above the cards (and, later, every export
 * caption). `versionsUsed` names the versions the server resolved "latest" to.
 */
export function describeFilters(
	f: ResultsFilters,
	opts: { choices?: readonly ChoiceVariable[]; versionsUsed?: readonly number[]; splitLabel?: string } = {}
): string[] {
	const out: string[] = [];
	const versions = f.versions.length ? [...f.versions].sort((a, b) => a - b) : [...(opts.versionsUsed ?? [])];
	if (versions.length) out.push(`${versions.length === 1 ? 'Version' : 'Versions'} ${versions.join(', ')}`);
	else out.push('Latest version');
	out.push(f.status === 'complete' ? 'Complete responses only' : 'All submitted responses');
	if (f.from && f.to) out.push(`Submitted ${f.from} to ${f.to}`);
	else if (f.from) out.push(`Submitted from ${f.from}`);
	else if (f.to) out.push(`Submitted up to ${f.to}`);
	if (f.condition?.levels.length) out.push(`Condition ${f.condition.variable} is ${list(f.condition.levels)}`);
	for (const a of f.answers) {
		if (!a.codes.length) continue;
		const v = opts.choices?.find((c) => c.id === a.question);
		const names = a.codes.map((k) => v?.codes.find((c) => c.key === k)?.label ?? k);
		out.push(`${v?.label ?? a.question} is ${list(names)}`);
	}
	if (f.split) {
		const name =
			opts.splitLabel ??
			(f.split.kind === 'condition' ? f.split.id : (opts.choices?.find((c) => c.id === f.split!.id)?.label ?? f.split.id));
		out.push(`Split by ${f.split.kind === 'condition' ? 'condition ' : ''}${name}`);
	}
	out.push(f.denominator === 'answered' ? 'Denominator: answered' : 'Denominator: shown (answered + unanswered)');
	return out;
}

// -- chart menu (planning/results-viewer.md, "Chart menu per question type") -------------

export interface ChartOption {
	id: string;
	label: string;
}

const TABLE: ChartOption = { id: 'table', label: 'Table' };
const SPLIT_BARS: ChartOption[] = [
	{ id: 'grouped', label: 'Grouped bars' },
	{ id: 'stacked100', label: '100 % stacked bars' },
	{ id: 'small-multiples', label: 'Small multiples' }
];
export const DATE_UNITS = ['month', 'day', 'week', 'year'] as const;
export type DateUnit = (typeof DATE_UNITS)[number];

/**
 * The charts that suit a card, default first. With a split, choice questions get the
 * split layouts (grouped, 100 % stacked, small multiples). Text has no chart (its card
 * is the verbatim table); notes are hidden.
 */
export function chartMenu(card: Pick<Card, 'type' | 'ordered' | 'binning'>, split = false): ChartOption[] {
	switch (card.type) {
		case 'single':
			return split
				? [...SPLIT_BARS, TABLE]
				: [
						{ id: 'bars', label: 'Horizontal bars (declared order)' },
						{ id: 'sorted', label: 'Sorted bars' },
						{ id: 'donut', label: 'Donut' },
						TABLE
					];
		case 'multi':
			return split
				? [...SPLIT_BARS, TABLE]
				: [
						{ id: 'bars-pct', label: 'Bars, % of respondents' },
						{ id: 'bars-count', label: 'Bars, counts' },
						{ id: 'dot', label: 'Dot plot' }
					];
		case 'integer':
		case 'decimal':
			return [
				{ id: 'histogram', label: 'Histogram' },
				{ id: 'box', label: 'Box plot' },
				{ id: 'cumulative', label: 'Cumulative distribution' }
			];
		case 'slider':
			return [
				card.binning === 'values'
					? { id: 'frequency', label: 'Frequency bars' }
					: { id: 'histogram', label: 'Histogram' },
				{ id: 'box', label: 'Box plot' },
				{ id: 'cumulative', label: 'Cumulative distribution' }
			];
		case 'date':
			return [
				{ id: 'month', label: 'Counts per month' },
				{ id: 'day', label: 'Counts per day' },
				{ id: 'week', label: 'Counts per week' },
				{ id: 'year', label: 'Counts per year' }
			];
		case 'matrix':
			return card.ordered
				? [
						{ id: 'diverging', label: 'Diverging stacked bars' },
						{ id: 'stacked100', label: '100 % stacked bars' },
						{ id: 'heatmap', label: 'Heatmap' },
						TABLE
					]
				: [{ id: 'grouped', label: 'Grouped bars' }, { id: 'heatmap', label: 'Heatmap' }, TABLE];
		default:
			return [];
	}
}

/** The chosen chart if the menu has it, else the menu's default (or null: no chart). */
export function effectiveChart(menu: readonly ChartOption[], chosen: string | undefined): string | null {
	if (chosen && menu.some((o) => o.id === chosen)) return chosen;
	return menu[0]?.id ?? null;
}

export function isDateUnit(id: string | null | undefined): id is DateUnit {
	return !!id && (DATE_UNITS as readonly string[]).includes(id);
}

/**
 * Per-card requests when a chart choice changes what the server computes (a date card per
 * day / week / year): every card of the last response in order, with its bins. Undefined
 * when nothing differs from the defaults (the server then sends every question).
 */
export function cardRequests(
	cards: readonly Pick<Card, 'question' | 'type'>[],
	chosen: Readonly<Record<string, string>>
): CardRequest[] | undefined {
	let custom = false;
	const out = cards.map((c) => {
		const unit = c.type === 'date' ? chosen[c.question] : undefined;
		if (isDateUnit(unit) && unit !== 'month') {
			custom = true;
			return { question: c.question, bins: { unit } };
		}
		return { question: c.question };
	});
	return custom ? out : undefined;
}

// -- states and statistics --------------------------------------------------------------

export const STATE_LABELS: [keyof StateCounts, string][] = [
	['answered', 'Answered'],
	['unanswered', 'Unanswered'],
	['irrelevant', 'Irrelevant (skipped by logic)'],
	['notReached', 'Not reached'],
	['notInVersion', 'Not in this version'],
	['unrecorded', 'Unrecorded'],
	['invalid', 'Invalid']
];

export function stateRows(states: StateCounts): { key: keyof StateCounts; label: string; count: number }[] {
	return STATE_LABELS.map(([key, label]) => ({ key, label, count: states[key] }));
}

const nf = new Intl.NumberFormat('en', { maximumFractionDigits: 2 });

export function fmtNum(x: number): string {
	return Number.isFinite(x) ? nf.format(x) : String(x);
}

export function fmtPct(x: number | null | undefined): string {
	if (x === null || x === undefined) return '–';
	return `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(x)} %`;
}

type StatKey = Exclude<keyof Stats, 'notAvailable'>;

const STAT_LABELS: [StatKey, string][] = [
	['n', 'n'],
	['mean', 'Mean'],
	['meanCi', 'Mean, 95 % interval'],
	['sd', 'SD'],
	['median', 'Median'],
	['q1', 'Lower quartile'],
	['q3', 'Upper quartile'],
	['min', 'Minimum'],
	['max', 'Maximum'],
	['mode', 'Mode'],
	['top2', 'Top-2 box'],
	['bottom2', 'Bottom-2 box'],
	['meanOptions', 'Mean options chosen'],
	['meanLength', 'Mean length (characters)'],
	['earliest', 'Earliest'],
	['latest', 'Latest']
];
const PCT_STATS = new Set<StatKey>(['top2', 'bottom2']);

export const NOT_AVAILABLE = 'not available';

export interface StatRow {
	key: StatKey;
	label: string;
	value: string;
	available: boolean;
}

/**
 * The statistics a group has, labelled: a value the server sent, or "not available" for
 * one it lists in `notAvailable` (undefined for the data, e.g. SD with n < 2; never 0).
 * Statistics that do not apply to the question type are left out. Category keys (mode,
 * the median of an ordered scale) are shown by their labels.
 */
export function statRows(stats: Stats, categories?: readonly Category[] | null): StatRow[] {
	const na = new Set(stats.notAvailable ?? []);
	const label = (k: string) => categories?.find((c) => c.key === k)?.label ?? k;
	const out: StatRow[] = [];
	for (const [key, name] of STAT_LABELS) {
		const v = stats[key];
		if (v === null || v === undefined || (Array.isArray(v) && !v.length && key !== 'mode')) {
			if (na.has(key)) out.push({ key, label: name, value: NOT_AVAILABLE, available: false });
			continue;
		}
		let value: string;
		if (key === 'mode') {
			const m = v as string[];
			if (!m.length) {
				if (na.has(key)) out.push({ key, label: name, value: NOT_AVAILABLE, available: false });
				continue;
			}
			value = m.map(label).join(', ');
		} else if (key === 'meanCi') value = (v as number[]).map(fmtNum).join(' to ');
		else if (key === 'median' && typeof v === 'string') value = label(v);
		else if (PCT_STATS.has(key)) value = fmtPct(v as number);
		else if (typeof v === 'number') value = fmtNum(v);
		else value = String(v);
		out.push({ key, label: name, value, available: true });
	}
	return out;
}

// -- what a card draws ------------------------------------------------------------------

export interface CardSection {
	/** Heading for the section (a facet's version, a matrix row); null for the card itself. */
	heading: string | null;
	key: string;
	unit: ResultUnit;
	/** The row's or facet's own states (matrix rows have their own n). */
	states?: StateCounts | null;
	rows?: RowResult[] | null;
}

/** A card's or facet's units: itself, or one per matrix row (each row is its own variable). */
function unitsOf(data: Pick<Facet, 'groups' | 'rows' | 'categories' | 'binning' | 'binEdges' | 'binUnit'>, prefix: string) {
	const base = { categories: data.categories, binning: data.binning, binEdges: data.binEdges, binUnit: data.binUnit };
	if (data.rows?.length) {
		return data.rows.map((r) => ({
			heading: r.label,
			key: `${prefix}row-${r.id}`,
			unit: { ...base, groups: r.groups },
			states: r.states
		}));
	}
	return [{ heading: null, key: `${prefix}all`, unit: { ...base, groups: data.groups ?? [] } }];
}

/** The sections of a card: per-version facets when versions do not combine, else the card. */
export function cardSections(card: Card): { facet: number | null; sections: CardSection[] }[] {
	if (card.facets?.length) {
		return card.facets.map((f) => ({ facet: f.version, sections: unitsOf(f, `v${f.version}-`) }));
	}
	return [{ facet: null, sections: unitsOf(card, '') }];
}

export const TYPE_NAMES: Record<CardType, string> = {
	single: 'Single choice',
	multi: 'Multiple choice',
	integer: 'Whole number',
	decimal: 'Decimal',
	slider: 'Slider',
	date: 'Date',
	text: 'Text',
	matrix: 'Grid',
	note: 'Note'
};

/** The first column's heading in a card's table. */
export function categoryHeading(unit: Pick<ResultUnit, 'binning' | 'binUnit'>): string {
	switch (unit.binning) {
		case 'bins':
			return 'Range';
		case 'values':
			return 'Value';
		case 'periods':
			return `Period (per ${unit.binUnit ?? 'month'})`;
		default:
			return 'Option';
	}
}

/** The % column's heading: multiple choice is % of respondents and can sum past 100. */
export function pctHeading(type: CardType, denominator: Denominator): string {
	if (type === 'multi') return '% of respondents (can sum > 100 %)';
	return denominator === 'answered' ? '% of answered' : '% of shown';
}
