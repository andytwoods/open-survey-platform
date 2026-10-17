// Fixture cards in V1's response shape (ResultsResponse.cards), made-up numbers only.
// Used by the spec tests and the /dev/charts gallery.
import type { Card, Category, Cell, Group, StateCounts, Stats } from './types';

const ZERO: StateCounts = { answered: 0, unanswered: 0, irrelevant: 0, notReached: 0, notInVersion: 0, unrecorded: 0, invalid: 0 };

function states(answered: number, unanswered = 0, irrelevant = 0, notReached = 0): StateCounts {
	return { ...ZERO, answered, unanswered, irrelevant, notReached };
}

/** Wilson 95 % interval of k / n in percent, like V1's `wilson`. */
function wilson(k: number, n: number): number[] | null {
	if (n <= 0) return null;
	const z = 1.959964;
	const p = k / n;
	const z2 = z * z;
	const centre = (p + z2 / (2 * n)) / (1 + z2 / n);
	const half = (z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / (1 + z2 / n);
	return [Math.max(0, centre - half) * 100, Math.min(1, centre + half) * 100];
}

function cells(keys: string[], labels: string[], counts: number[], n: number, ci = false, extra?: (i: number) => Partial<Cell>): Cell[] {
	return keys.map((key, i) => ({
		key,
		label: labels[i],
		count: counts[i],
		pct: n ? (100 * counts[i]) / n : null,
		...(ci ? { ci: wilson(counts[i], n) } : {}),
		...(extra ? extra(i) : {})
	}));
}

function group(key: string, label: string, n: number, cs: Cell[], stats: Partial<Stats> = {}, missing = false): Group {
	return { key, label, n, responses: n + 3, missing, states: states(n, 3), cells: cs, stats: { n, notAvailable: [], ...stats } };
}

const cats = (labels: string[], codes?: (number | string)[]): Category[] =>
	labels.map((label, i) => ({ key: String(codes ? codes[i] : i + 1), code: codes ? codes[i] : i + 1, label }));

const keysOf = (c: Category[]) => c.map((x) => x.key);
const labelsOf = (c: Category[]) => c.map((x) => x.label);

function base(question: string, type: Card['type'], label: string, extra: Partial<Card> = {}): Card {
	return { question, name: question, type, label, versionsUsed: [3], warnings: [], facets: null, ...extra };
}

// -- single choice ----------------------------------------------------------------------

const TRANSPORT = cats(['Bus', 'Train', 'Bicycle', 'Car', 'On foot']);
const tc = [42, 31, 18, 55, 14];
const tn = tc.reduce((a, b) => a + b, 0);

export const singleCard: Card = base('transport', 'single', 'How do you usually travel to work?', {
	binning: 'categories',
	categories: TRANSPORT,
	ordered: false,
	states: states(tn, 6, 0, 4),
	groups: [group('all', 'All responses', tn, cells(keysOf(TRANSPORT), labelsOf(TRANSPORT), tc, tn, true), { mode: ['4'] })]
});

const ARMS: [string, string, number[], boolean][] = [
	['1', 'Control', [20, 14, 9, 25, 6], false],
	['2', 'Treatment', [17, 15, 7, 24, 7], false],
	['_missing', 'No value', [5, 2, 2, 6, 1], true]
];

export const singleSplitCard: Card = base('transport', 'single', 'How do you usually travel to work?', {
	binning: 'categories',
	categories: TRANSPORT,
	ordered: false,
	states: states(tn, 6, 0, 4),
	groups: ARMS.map(([k, l, c, m]) => {
		const n = c.reduce((a, b) => a + b, 0);
		return group(k, l, n, cells(keysOf(TRANSPORT), labelsOf(TRANSPORT), c, n), {}, m);
	})
});

// -- multiple choice --------------------------------------------------------------------

const DEVICES = cats(['Phone', 'Laptop', 'Tablet', 'Desktop computer', 'Smart watch', 'None of these']);
const dc = [118, 96, 41, 37, 12, 3];
const dn = 140;

export const multiCard: Card = base('devices', 'multi', 'Which devices do you use every week?', {
	binning: 'categories',
	categories: DEVICES,
	ordered: null,
	states: states(dn, 8),
	groups: [group('all', 'All responses', dn, cells(keysOf(DEVICES), labelsOf(DEVICES), dc, dn, true), { meanOptions: 2.18 })]
});

export const multiSplitCard: Card = base('devices', 'multi', 'Which devices do you use every week?', {
	binning: 'categories',
	categories: DEVICES,
	ordered: null,
	states: states(dn, 8),
	groups: [
		group('1', 'Control', 72, cells(keysOf(DEVICES), labelsOf(DEVICES), [61, 50, 19, 20, 7, 1], 72)),
		group('2', 'Treatment', 68, cells(keysOf(DEVICES), labelsOf(DEVICES), [57, 46, 22, 17, 5, 2], 68))
	]
});

// -- numbers ----------------------------------------------------------------------------

const AGE_EDGES = [15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70];
const ageCounts = [6, 22, 31, 27, 19, 14, 11, 8, 6, 3, 1];
const ageN = ageCounts.reduce((a, b) => a + b, 0);
const binCells = (edges: number[], counts: number[], n: number) =>
	counts.map<Cell>((count, i) => ({
		key: String(i),
		label: `${edges[i]}–${edges[i + 1]}`,
		count,
		pct: n ? (100 * count) / n : null,
		lo: edges[i],
		hi: edges[i + 1]
	}));

export const integerCard: Card = base('age', 'integer', 'How old are you?', {
	binning: 'bins',
	binEdges: AGE_EDGES,
	states: states(ageN, 2),
	groups: [
		group('all', 'All responses', ageN, binCells(AGE_EDGES, ageCounts, ageN), {
			mean: 34.6,
			sd: 10.9,
			median: 32,
			q1: 26,
			q3: 41.5,
			min: 18,
			max: 69,
			meanCi: [32.9, 36.3]
		})
	]
});

export const integerSplitCard: Card = base('age', 'integer', 'How old are you?', {
	binning: 'bins',
	binEdges: AGE_EDGES,
	states: states(ageN, 2),
	groups: [
		group('1', 'Control', 76, binCells(AGE_EDGES, [3, 12, 17, 13, 10, 7, 6, 4, 3, 1, 0], 76), { mean: 33.8, median: 31, q1: 25.5, q3: 40, min: 18, max: 66, sd: 10.2, meanCi: [31.5, 36.1] }),
		group('2', 'Treatment', 72, binCells(AGE_EDGES, [3, 10, 14, 14, 9, 7, 5, 4, 3, 2, 1], 72), { mean: 35.4, median: 33, q1: 27, q3: 43, min: 19, max: 69, sd: 11.5, meanCi: [32.7, 38.1] })
	]
});

const RT_EDGES = [0.2, 0.4, 0.6, 0.8, 1, 1.2, 1.4, 1.6];
const rtCounts = [4, 19, 36, 28, 13, 6, 2];
const rtN = rtCounts.reduce((a, b) => a + b, 0);

export const decimalCard: Card = base('reaction', 'decimal', 'Reaction time in the practice trial (seconds)', {
	binning: 'bins',
	binEdges: RT_EDGES,
	states: states(rtN, 1),
	groups: [group('all', 'All responses', rtN, binCells(RT_EDGES, rtCounts, rtN), { mean: 0.74, sd: 0.23, median: 0.71, q1: 0.58, q3: 0.88, min: 0.23, max: 1.52, meanCi: [0.7, 0.78] })]
});

const STEPS = Array.from({ length: 11 }, (_, i) => i);
const sliderCounts = [1, 2, 4, 7, 9, 18, 21, 25, 19, 11, 6];
const sliderN = sliderCounts.reduce((a, b) => a + b, 0);

export const sliderValuesCard: Card = base('wellbeing', 'slider', 'How satisfied are you with your life nowadays? (0–10)', {
	binning: 'values',
	states: states(sliderN, 4),
	groups: [
		group(
			'all',
			'All responses',
			sliderN,
			STEPS.map((v, i) => ({ key: String(v), label: String(v), count: sliderCounts[i], pct: (100 * sliderCounts[i]) / sliderN, lo: v, hi: v })),
			{ mean: 6.4, sd: 2.1, median: 7, q1: 5, q3: 8, min: 0, max: 10 }
		)
	]
});

const VAS_EDGES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
const vasCounts = [3, 5, 9, 12, 18, 22, 19, 14, 8, 4];
const vasN = vasCounts.reduce((a, b) => a + b, 0);

export const sliderBinsCard: Card = base('pain', 'slider', 'Rate your pain right now (0–100)', {
	binning: 'bins',
	binEdges: VAS_EDGES,
	states: states(vasN, 2),
	groups: [group('all', 'All responses', vasN, binCells(VAS_EDGES, vasCounts, vasN), { mean: 51.2, sd: 20.4, median: 52, q1: 37, q3: 66, min: 1, max: 98 })]
});

// -- date -------------------------------------------------------------------------------

const MONTHS = ['2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10'];
const monthCounts = [4, 11, 19, 26, 22, 17, 30, 9];
const monthN = monthCounts.reduce((a, b) => a + b, 0);

export const dateCard: Card = base('visit', 'date', 'When did you last visit your doctor?', {
	binning: 'periods',
	binUnit: 'month',
	states: states(monthN, 7),
	groups: [group('all', 'All responses', monthN, cells(MONTHS, MONTHS, monthCounts, monthN), { earliest: '2026-03-02', latest: '2026-10-15' })]
});

// -- matrix -----------------------------------------------------------------------------

const AGREE = cats(['Strongly disagree', 'Disagree', 'Neither agree nor disagree', 'Agree', 'Strongly agree']);
const LIKERT_ROWS: [string, string, number[]][] = [
	['easy', 'The survey was easy to complete', [3, 8, 14, 52, 43]],
	['recommend', 'I would recommend it to a friend', [9, 17, 31, 40, 23]],
	['again', 'I would take part again', [21, 26, 28, 30, 15]]
];

function matrixRows(rows: [string, string, number[]][], c: Category[], groups: [string, string, number][] = [['all', 'All responses', 1]]) {
	return rows.map(([id, label, counts]) => ({
		id: `sat_${id}`,
		name: `sat_${id}`,
		label,
		states: states(counts.reduce((a, b) => a + b, 0)),
		groups: groups.map(([gk, gl, scale]) => {
			const cs = counts.map((x) => Math.round(x * scale));
			const n = cs.reduce((a, b) => a + b, 0);
			return group(gk, gl, n, cells(keysOf(c), labelsOf(c), cs, n));
		})
	}));
}

export const matrixOrderedCard: Card = base('sat', 'matrix', 'How much do you agree with each statement?', {
	binning: 'categories',
	categories: AGREE,
	ordered: true,
	rows: matrixRows(LIKERT_ROWS, AGREE),
	groups: []
});

export const matrixSplitCard: Card = base('sat', 'matrix', 'How much do you agree with each statement?', {
	binning: 'categories',
	categories: AGREE,
	ordered: true,
	rows: matrixRows(LIKERT_ROWS, AGREE, [
		['1', 'Control', 0.5],
		['2', 'Treatment', 0.45]
	]),
	groups: []
});

const FLAVOURS = cats(['Apple', 'Cherry', 'Lemon', 'Mint'], ['apple', 'cherry', 'lemon', 'mint']);

export const matrixUnorderedCard: Card = base('flavour', 'matrix', 'Which flavour would you pick for each season?', {
	binning: 'categories',
	categories: FLAVOURS,
	ordered: false,
	rows: matrixRows(
		[
			['spring', 'Spring', [22, 12, 31, 18]],
			['summer', 'Summer', [15, 20, 38, 27]],
			['winter', 'Winter', [34, 29, 8, 12]]
		],
		FLAVOURS
	),
	groups: []
});

// -- text, note, facets, empty ----------------------------------------------------------

export const textCard: Card = base('comments', 'text', 'Any other comments?', {
	states: states(64, 81, 12, 9),
	groups: [group('all', 'All responses', 64, [], { meanLength: 87.5 })]
});

export const noteCard: Card = base('intro', 'note', 'Thank you for taking part.', { groups: [] });

export const facetCard: Card = base('transport', 'single', 'How do you usually travel to work?', {
	versionsUsed: [2, 3],
	warnings: [{ code: 'versions.incompatible', message: 'Shown per version: option codes differ.', question: 'transport' }],
	states: states(tn + 40, 9),
	groups: [],
	facets: [
		{
			version: 2,
			binning: 'categories',
			categories: cats(['Bus', 'Train', 'Car']),
			states: states(40, 3),
			groups: [group('all', 'All responses', 40, cells(['1', '2', '3'], ['Bus', 'Train', 'Car'], [14, 9, 17], 40))]
		},
		{
			version: 3,
			binning: 'categories',
			categories: TRANSPORT,
			states: states(tn, 6),
			groups: [group('all', 'All responses', tn, cells(keysOf(TRANSPORT), labelsOf(TRANSPORT), tc, tn))]
		}
	]
});

export const emptyCard: Card = base('transport', 'single', 'How do you usually travel to work?', {
	binning: 'categories',
	categories: TRANSPORT,
	ordered: false,
	states: states(0, 5),
	groups: [group('all', 'All responses', 0, cells(keysOf(TRANSPORT), labelsOf(TRANSPORT), [0, 0, 0, 0, 0], 0), {})]
});

export const FIXTURE_CARDS = {
	single: singleCard,
	singleSplit: singleSplitCard,
	multi: multiCard,
	multiSplit: multiSplitCard,
	integer: integerCard,
	integerSplit: integerSplitCard,
	decimal: decimalCard,
	sliderValues: sliderValuesCard,
	sliderBins: sliderBinsCard,
	date: dateCard,
	matrixOrdered: matrixOrderedCard,
	matrixSplit: matrixSplitCard,
	matrixUnordered: matrixUnorderedCard,
	text: textCard,
	note: noteCard,
	facets: facetCard,
	empty: emptyCard
} as const;
