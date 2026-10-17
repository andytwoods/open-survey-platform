// Vega-Lite spec builders for the results cards (task V3, planning/results-viewer.md).
// Pure: a card from V1's results API in, a Vega-Lite spec with its data embedded out.
// Nothing is re-aggregated here: counts, shares, bin edges, quartiles and intervals all
// come from V1 (V-D5), so an exported spec re-renders the same in Altair or vegawidget.
import type { TopLevelSpec } from 'vega-lite';
import { chartsFor, isChart, splitsFor } from './menu';
import { inkOn, likertPalette, LIGHT_TOKENS, luminance, textColors, themeConfig } from './theme';
import type { BuildOptions, Card, Cell, ChartChoice, Group, HiddenCell, MenuChoice, SplitLayout, StateCounts } from './types';

export const VEGA_LITE_SCHEMA = 'https://vega.github.io/schema/vega-lite/v6.json';

type Spec = Record<string, unknown>;
type Datum = Record<string, string | number | boolean | null>;

interface Ctx {
	card: Card;
	opts: Required<Pick<BuildOptions, 'theme' | 'tokens' | 'intervals' | 'denominator'>> & BuildOptions;
	split: SplitLayout | null;
	/** Width of one view: a number inside facets / concatenations, else 'container'. */
	width: number | 'container';
	cellWidth: number;
}

// -- small helpers ----------------------------------------------------------------------

const MULTIPLE_WIDTH = 280;

/** "45%"; empty for a null share. */
function pctText(p: number | null): string {
	if (p === null) return '';
	const v = p * 100;
	return `${v > 0 && v < 1 ? '<1' : Math.round(v)}%`;
}

const share = (c: Cell): number | null => (isHidden(c) || c.pct === null || c.pct === undefined ? null : c.pct / 100);

/** A cell an export hid ("Hide counts below k", V-D4): no count, no share, only a label. */
const isHidden = (c: Cell): boolean => (c as HiddenCell).hidden === true;

/** The label hidden cells draw (BuildOptions.hiddenLabel); set per buildSpec call. */
let hiddenText = 'n<5';

function denomWord(ctx: Ctx): string {
	return ctx.opts.denominator === 'shown' ? 'shown' : 'answered';
}

/** "% of answered responses", plus " (n = 120)" for a card without a split. */
function pctTitle(ctx: Ctx, groups: Group[], extra = ''): string {
	const base = `% of ${denomWord(ctx)} responses${extra}`;
	return groups.length === 1 ? `${base} (n = ${groups[0].n})` : base;
}

const groupLabel = (g: Group): string => `${g.label} (n = ${g.n})`;

const PCT_TICKS = [0, 0.2, 0.4, 0.6, 0.8, 1];
/** Matrix rows are long statements: cut at this width (the full text is in the tooltip). */
const ROW_LABEL_LIMIT = 170;
/** Matrix row axis: statement and n on two lines, so a long statement never hides its n. */
const ROW_AXIS: Spec = { labelLimit: ROW_LABEL_LIMIT, labelExpr: "split(datum.value, '\\n')", labelLineHeight: 14 };

/**
 * A 0-100 % axis with room on the right for the direct labels: the scale runs past 100 %
 * (`room`) but ticks and grid stop at 100 %.
 */
function pctAxis(room: number): Spec {
	return { scale: { domain: [0, 1 + room], nice: false }, axis: { format: '.0%', values: PCT_TICKS } };
}

/** Category labels made unique (a duplicated label gets its code appended). */
function uniqueLabels(items: { key: string; label: string }[]): string[] {
	const seen = new Map<string, number>();
	for (const c of items) seen.set(c.label, (seen.get(c.label) ?? 0) + 1);
	return items.map((c) => ((seen.get(c.label) ?? 0) > 1 ? `${c.label} (${c.key})` : c.label));
}

function groupsOf(card: Card): Group[] {
	return card.groups ?? [];
}

const hasAnswers = (groups: Group[]): boolean => groups.some((g) => g.n > 0);

function emptySpec(ctx: Ctx, message: string): Spec {
	return {
		width: ctx.width,
		height: 40,
		data: { values: [{ message }] },
		mark: { type: 'text', align: 'left', x: 0, baseline: 'middle', color: textColors(ctx.opts.theme, ctx.opts.tokens).muted },
		encoding: { text: { field: 'message', type: 'nominal' } }
	};
}

function tooltip(...fields: [string, string, string?][]): Spec[] {
	return fields.map(([field, title, format]) => ({ field, title, type: 'nominal', ...(format ? { format, type: 'quantitative' } : {}) }));
}

/** Wrap a per-group view in a small-multiples facet (one row per group). */
function multiples(data: Datum[], inner: Spec, groupOrder: string[], ctx: Ctx, facetField = 'groupLabel'): Spec {
	// The facet carries the data; each panel gets the fixed panel width.
	const rest: Spec = { ...inner };
	delete rest.data;
	delete rest.width;
	return {
		data: { values: data },
		facet: { row: { field: facetField, type: 'nominal', sort: groupOrder, header: { title: null } } },
		spec: { width: ctx.cellWidth, ...rest },
		resolve: { scale: { y: 'shared' } }
	};
}

// -- categories (single / multiple choice) ---------------------------------------------

interface CategoryRows {
	data: Datum[];
	labels: string[];
	groups: string[];
}

/** One datum per (group, category), declared order, shares as fractions. */
function categoryData(card: Card, groups: Group[]): CategoryRows {
	const cats = card.categories?.length ? card.categories : (groups[0]?.cells ?? []);
	const labels = uniqueLabels(cats);
	const labelOf = new Map(cats.map((c, i) => [c.key, labels[i]]));
	const data: Datum[] = [];
	groups.forEach((g, gi) => {
		for (const c of g.cells) {
			const p = share(c);
			const hid = isHidden(c);
			const label = labelOf.get(c.key) ?? c.label;
			data.push({
				key: c.key,
				label,
				order: labels.indexOf(label),
				count: hid ? null : c.count,
				p,
				text: hid ? hiddenText : pctText(p),
				countText: hid ? hiddenText : String(c.count),
				...(hid ? { hidden: true } : {}),
				group: g.key,
				groupLabel: groupLabel(g),
				groupOrder: gi,
				ciLo: c.ci && !hid ? c.ci[0] / 100 : null,
				ciHi: c.ci && !hid ? c.ci[1] / 100 : null
			});
		}
	});
	return { data, labels, groups: groups.map(groupLabel) };
}

function sortedLabels(rows: CategoryRows): string[] {
	const total = new Map<string, number>();
	for (const d of rows.data) total.set(d.label as string, (total.get(d.label as string) ?? 0) + (d.count as number));
	return [...rows.labels].sort((a, b) => (total.get(b) ?? 0) - (total.get(a) ?? 0) || rows.labels.indexOf(a) - rows.labels.indexOf(b));
}

interface BarOpts {
	measure: 'p' | 'count';
	mark: 'bar' | 'point';
	sorted: boolean;
	axisExtra?: string;
}

function categoryBars(ctx: Ctx, o: BarOpts): Spec {
	const groups = groupsOf(ctx.card);
	if (!hasAnswers(groups)) return emptySpec(ctx, 'No answers to show.');
	const rows = categoryData(ctx.card, groups);
	const order = o.sorted ? sortedLabels(rows) : rows.labels;
	const split = groups.length > 1 ? ctx.split : null;
	if (split === 'stacked') return stackedBars(ctx, rows.data, 'groupLabel', rows.groups, 'label', order, likertOrCategory(ctx, order.length, ctx.card.ordered), pctTitle(ctx, groups));

	const isPct = o.measure === 'p';
	const xTitle = isPct ? pctTitle(ctx, groups, o.axisExtra ?? '') : `Responses${groups.length === 1 ? ` (n = ${groups[0].n})` : ''}`;
	const x: Spec = {
		field: o.measure,
		type: 'quantitative',
		title: xTitle,
		...(isPct
			? pctAxis(split === 'grouped' ? 0.32 : 0.14)
			: { axis: { tickMinStep: 1 }, scale: { domain: [0, Math.max(1, ...rows.data.map((d) => Number(d.count))) * 1.15], nice: false } })
	};
	const grouped = split === 'grouped';
	const y: Spec = { field: 'label', type: 'nominal', sort: order, title: null, axis: { labelLimit: ROW_LABEL_LIMIT } };
	const enc: Spec = {
		y,
		x,
		tooltip: [
			...tooltip(['label', 'Option'], ...(groups.length > 1 ? ([['groupLabel', 'Group']] as [string, string][]) : [])),
			{ field: 'count', type: 'quantitative', title: 'Responses' },
			{ field: 'p', type: 'quantitative', title: `% of ${denomWord(ctx)}`, format: '.1%' }
		]
	};
	if (grouped) {
		enc.yOffset = { field: 'groupLabel', type: 'nominal', sort: rows.groups };
		enc.color = { field: 'groupLabel', type: 'nominal', sort: rows.groups, title: null };
	}
	const mark: Spec =
		o.mark === 'bar' ? { type: 'bar', cornerRadiusEnd: 2 } : { type: 'point', filled: true, size: 90, opacity: 1 };
	const textField = isPct ? 'text' : 'countText';
	const layers: Spec[] = [{ mark, encoding: enc }];
	if (ctx.opts.intervals && isPct) {
		layers.push({
			mark: { type: 'rule', strokeWidth: 1.5, color: textColors(ctx.opts.theme, ctx.opts.tokens).text },
			encoding: {
				y,
				...(grouped ? { yOffset: enc.yOffset } : {}),
				x: { field: 'ciLo', type: 'quantitative' },
				x2: { field: 'ciHi' }
			}
		});
	}
	// Direct labels, so no value depends on colour or hover. Grouped bars name their group.
	layers.push({
		mark: { type: 'text', align: 'left', dx: o.mark === 'bar' ? 4 : 9, baseline: 'middle' },
		encoding: {
			y,
			...(grouped ? { yOffset: enc.yOffset } : {}),
			x: { field: ctx.opts.intervals && isPct ? 'labelX' : o.measure, type: 'quantitative' },
			text: { field: grouped ? 'groupText' : textField, type: 'nominal' }
		}
	});
	const data = rows.data.map((d) => ({
		...d,
		groupText: `${String(d.groupLabel).replace(/ \(n = \d+\)$/, '')}: ${d[textField]}`,
		labelX: Math.max(Number(d.p ?? 0), Number(d.ciHi ?? 0))
	}));
	const band = grouped ? 16 * rows.groups.length + 8 : 26;
	const view: Spec = { width: ctx.width, height: band * order.length, data: { values: data }, layer: layers };
	if (split === 'multiples') return multiples(data, view, rows.groups, ctx);
	return view;
}

function donut(ctx: Ctx): Spec {
	const groups = groupsOf(ctx.card);
	if (!hasAnswers(groups)) return emptySpec(ctx, 'No answers to show.');
	const rows = categoryData(ctx.card, groups);
	const data = rows.data.filter((d) => (d.count as number) > 0).map((d) => ({ ...d, slice: `${d.label}: ${d.text}` }));
	const theta = { field: 'count', type: 'quantitative', stack: true };
	const order = { field: 'order', type: 'quantitative' };
	const view: Spec = {
		width: 300,
		height: 240,
		data: { values: data },
		layer: [
			{
				mark: { type: 'arc', innerRadius: 46, outerRadius: 82, stroke: textColors(ctx.opts.theme, ctx.opts.tokens).bg, strokeWidth: 1 },
				encoding: {
					theta,
					order,
					color: { field: 'label', type: 'nominal', sort: rows.labels, title: null, legend: null },
					tooltip: [
						{ field: 'label', type: 'nominal', title: 'Option' },
						{ field: 'count', type: 'quantitative', title: 'Responses' },
						{ field: 'p', type: 'quantitative', title: `% of ${denomWord(ctx)}`, format: '.1%' }
					]
				}
			},
			{
				// Direct labels outside the ring: option and share, never colour alone.
				mark: { type: 'text', radius: 104 },
				encoding: { theta, order, text: { field: 'slice', type: 'nominal' } }
			}
		]
	};
	if (groups.length > 1) return multiples(data, view, rows.groups, { ...ctx, cellWidth: 300 });
	return view;
}

// -- shared stacked bars (100 % stacked, diverging Likert) ------------------------------

function likertOrCategory(ctx: Ctx, k: number, ordered: boolean | null | undefined): string[] {
	if (ordered) return likertPalette(k, ctx.opts.theme);
	const pal = (themeConfig(ctx.opts.theme, ctx.opts.tokens).range?.category ?? []) as string[];
	return Array.from({ length: k }, (_, i) => pal[i % pal.length]);
}

/**
 * Stacked shares per bar (`barField`), segments in `segOrder`. `diverging`: the scale is
 * centred, so the negative half (and half of an odd neutral) sits left of 0.
 */
function stackedBars(
	ctx: Ctx,
	data: Datum[],
	barField: string,
	barOrder: string[],
	segField: string,
	segOrder: string[],
	colors: string[],
	xTitle: string,
	diverging = false
): Spec {
	const k = segOrder.length;
	const mid = (k - 1) / 2;
	const out: Datum[] = [];
	for (const bar of barOrder) {
		const segs = segOrder.map((s) => data.find((d) => d[barField] === bar && d[segField] === s));
		const shares = segs.map((d) => Number(d?.p ?? 0));
		let start = 0;
		if (diverging) {
			start = -shares.reduce((acc, p, i) => acc + (i < mid ? p : i === mid ? p / 2 : 0), 0);
		}
		segs.forEach((d, i) => {
			if (!d) return;
			const p = shares[i];
			const fill = colors[i] ?? '#999999';
			out.push({ ...d, x0: start, x1: start + p, ink: inkOn(fill), seg: i, shown: p >= 0.07 ? (d.text as string) : '' });
			start += p;
		});
	}
	const y = { field: barField, type: 'nominal', sort: barOrder, title: null, axis: barField === 'rowLabel' ? ROW_AXIS : { labelLimit: ROW_LABEL_LIMIT } };
	// Diverging: a symmetric domain just wide enough for the longest side, in 10 % steps.
	const ext = diverging ? Math.min(1, Math.ceil(Math.max(0.1, ...out.map((d) => Math.max(-Number(d.x0), Number(d.x1)))) * 10 - 1e-9) / 10) : 1;
	const x: Spec = {
		field: 'x0',
		type: 'quantitative',
		title: xTitle,
		scale: { domain: diverging ? [-ext, ext] : [0, 1], nice: false },
		axis: diverging ? { labelExpr: "format(abs(datum.value), '.0%')", tickCount: 5 } : { format: '.0%', values: PCT_TICKS }
	};
	const layers: Spec[] = [
		{
			mark: { type: 'bar' },
			encoding: {
				y,
				x,
				x2: { field: 'x1' },
				color: { field: segField, type: 'nominal', sort: segOrder, scale: { domain: segOrder, range: colors }, title: null },
				tooltip: [
					{ field: barField, type: 'nominal', title: barField === 'groupLabel' ? 'Group' : 'Row' },
					{ field: segField, type: 'nominal', title: 'Answer' },
					{ field: 'count', type: 'quantitative', title: 'Responses' },
					{ field: 'p', type: 'quantitative', title: `% of ${denomWord(ctx)}`, format: '.1%' }
				]
			}
		},
		{
			mark: { type: 'text', baseline: 'middle', align: 'center' },
			transform: [{ calculate: '(datum.x0 + datum.x1) / 2', as: 'xm' }],
			encoding: {
				y,
				x: { field: 'xm', type: 'quantitative' },
				text: { field: 'shown', type: 'nominal' },
				color: { field: 'ink', type: 'nominal', scale: null }
			}
		}
	];
	if (diverging) {
		layers.push({
			mark: { type: 'rule', color: textColors(ctx.opts.theme, ctx.opts.tokens).text, strokeWidth: 1, aria: false },
			encoding: { x: { datum: 0, type: 'quantitative' } }
		});
	}
	return { width: ctx.width, height: (barField === 'rowLabel' ? 38 : 30) * barOrder.length, data: { values: out }, layer: layers };
}

// -- matrix -----------------------------------------------------------------------------

interface MatrixRows {
	data: Datum[];
	rows: string[];
	cats: string[];
	groups: string[];
}

function matrixData(card: Card): MatrixRows {
	const cats = uniqueLabels(card.categories ?? []);
	const catOf = new Map((card.categories ?? []).map((c, i) => [c.key, cats[i]]));
	const rowLabels = uniqueLabels((card.rows ?? []).map((r) => ({ key: r.name, label: r.label })));
	const data: Datum[] = [];
	const groups: string[] = [];
	(card.rows ?? []).forEach((r, ri) => {
		r.groups.forEach((g, gi) => {
			if (ri === 0) groups.push(g.label);
			for (const c of g.cells) {
				const p = share(c);
				const hid = isHidden(c);
				data.push({
					row: rowLabels[ri],
					// Two axis lines (ROW_AXIS splits them): the statement, then its own n.
					rowLabel: `${rowLabels[ri]}\nn = ${g.n}`,
					rowOrder: ri,
					rowN: g.n,
					key: c.key,
					label: catOf.get(c.key) ?? c.label,
					order: cats.indexOf(catOf.get(c.key) ?? c.label),
					count: hid ? null : c.count,
					p,
					text: hid ? hiddenText : pctText(p),
					...(hid ? { hidden: true } : {}),
					group: g.key,
					groupLabel: g.label,
					groupOrder: gi
				});
			}
		});
	});
	return { data, rows: rowLabels, cats, groups };
}

/** Matrix charts, per split group when the card is split (small multiples). */
function matrixChart(ctx: Ctx, choice: 'likert' | 'stacked100' | 'heatmap' | 'grouped'): Spec {
	const m = matrixData(ctx.card);
	const answered = (ctx.card.rows ?? []).some((r) => r.groups.some((g) => g.n > 0));
	if (!m.rows.length || !answered) return emptySpec(ctx, 'No answers to show.');
	const perGroup = m.groups.map((g) => {
		const data = m.data.filter((d) => d.groupLabel === g);
		// Row labels carry this group's n.
		const rowOrder = m.rows.map((r) => data.find((d) => d.row === r)?.rowLabel as string).filter(Boolean);
		return { g, data, rowOrder };
	});
	const one = (data: Datum[], rowOrder: string[], c: Ctx): Spec => {
		if (choice === 'likert' || choice === 'stacked100') {
			const colors = likertOrCategory(c, m.cats.length, choice === 'likert' || ctx.card.ordered);
			const title =
				choice === 'likert'
					? `% of ${denomWord(c)} per row, neutral centred`
					: `% of ${denomWord(c)} responses per row`;
			return stackedBars(c, data, 'rowLabel', rowOrder, 'label', m.cats, colors, title, choice === 'likert');
		}
		if (choice === 'heatmap') return heatmap(c, data, rowOrder, m.cats, m.data);
		return matrixGrouped(c, data, rowOrder, m.cats);
	};
	if (perGroup.length === 1) return one(perGroup[0].data, perGroup[0].rowOrder, ctx);
	// One panel per group (row labels differ by n, so a vconcat rather than a facet).
	return {
		vconcat: perGroup.map(({ g, data, rowOrder }) => ({
			title: { text: g, anchor: 'start' },
			...one(data, rowOrder, { ...ctx, width: ctx.cellWidth })
		})),
		resolve: { scale: { color: 'shared' } }
	};
}

function heatmap(ctx: Ctx, data: Datum[], rowOrder: string[], cats: string[], all: Datum[] = data): Spec {
	// One colour domain for every panel of a split card.
	const max = Math.max(0.0001, ...all.map((d) => Number(d.p ?? 0)));
	const values = data.map((d) => ({ ...d, strong: Number(d.p ?? 0) / max > 0.55 }));
	const theme = ctx.opts.theme;
	const dark = theme === 'app' && luminance(ctx.opts.tokens.bg) < 0.2;
	const y = { field: 'rowLabel', type: 'nominal', sort: rowOrder, title: null, axis: ROW_AXIS };
	const x = { field: 'label', type: 'nominal', sort: cats, title: null, axis: { labelAngle: -30, labelAlign: 'right', labelLimit: 140 } };
	return {
		width: ctx.width,
		height: 38 * rowOrder.length,
		data: { values },
		layer: [
			{
				mark: { type: 'rect', stroke: textColors(theme, ctx.opts.tokens).bg, strokeWidth: 2 },
				encoding: {
					y,
					x,
					color: {
						field: 'p',
						type: 'quantitative',
						scale: { domain: [0, max], type: 'linear' },
						title: `% of ${denomWord(ctx)}`,
						legend: { format: '.0%', direction: 'horizontal', orient: 'top', gradientLength: 160 }
					},
					tooltip: [
						{ field: 'row', type: 'nominal', title: 'Row' },
						{ field: 'label', type: 'nominal', title: 'Answer' },
						{ field: 'count', type: 'quantitative', title: 'Responses' },
						{ field: 'p', type: 'quantitative', title: `% of ${denomWord(ctx)}`, format: '.1%' }
					]
				}
			},
			{
				mark: { type: 'text', baseline: 'middle' },
				encoding: {
					y,
					x,
					text: { field: 'text', type: 'nominal' },
					// Strong cells are dark in light themes and light in the dark app theme.
					color: {
						condition: { test: 'datum.strong', value: dark ? '#0b1220' : '#ffffff' },
						value: textColors(theme, ctx.opts.tokens).text
					}
				}
			}
		]
	};
}

function matrixGrouped(ctx: Ctx, data: Datum[], rowOrder: string[], cats: string[]): Spec {
	const values = data.map((d) => ({ ...d, catText: `${d.label}: ${d.text}` }));
	const y = { field: 'rowLabel', type: 'nominal', sort: rowOrder, title: null, axis: ROW_AXIS };
	const yOffset = { field: 'label', type: 'nominal', sort: cats };
	return {
		width: ctx.width,
		height: (16 * cats.length + 10) * rowOrder.length,
		data: { values },
		layer: [
			{
				mark: { type: 'bar', cornerRadiusEnd: 2 },
				encoding: {
					y,
					yOffset,
					x: { field: 'p', type: 'quantitative', title: `% of ${denomWord(ctx)} responses per row`, ...pctAxis(0.4) },
					color: { field: 'label', type: 'nominal', sort: cats, scale: { domain: cats, range: likertOrCategory(ctx, cats.length, false) }, title: null },
					tooltip: [
						{ field: 'row', type: 'nominal', title: 'Row' },
						{ field: 'label', type: 'nominal', title: 'Answer' },
						{ field: 'count', type: 'quantitative', title: 'Responses' },
						{ field: 'p', type: 'quantitative', title: `% of ${denomWord(ctx)}`, format: '.1%' }
					]
				}
			},
			{
				mark: { type: 'text', align: 'left', dx: 4, baseline: 'middle' },
				encoding: { y, yOffset, x: { field: 'p', type: 'quantitative' }, text: { field: 'catText', type: 'nominal' } }
			}
		]
	};
}

// -- numbers ----------------------------------------------------------------------------

function numberData(card: Card, groups: Group[]): { data: Datum[]; groups: string[] } {
	const data: Datum[] = [];
	groups.forEach((g, gi) => {
		g.cells.forEach((c, ci) => {
			const p = share(c);
			const hid = isHidden(c);
			data.push({
				key: c.key,
				label: c.label,
				order: ci,
				lo: c.lo ?? null,
				hi: c.hi ?? null,
				count: hid ? null : c.count,
				p,
				text: hid ? hiddenText : pctText(p),
				countText: hid ? hiddenText : String(c.count),
				...(hid ? { hidden: true } : {}),
				group: g.key,
				groupLabel: groupLabel(g),
				groupOrder: gi
			});
		});
	});
	return { data, groups: groups.map(groupLabel) };
}

function histogram(ctx: Ctx): Spec {
	const groups = groupsOf(ctx.card);
	const edges = ctx.card.binEdges ?? [];
	if (!hasAnswers(groups) || edges.length < 2) return emptySpec(ctx, 'No answers to show.');
	const { data, groups: gl } = numberData(ctx.card, groups);
	const bars: Spec = {
		mark: { type: 'bar', stroke: textColors(ctx.opts.theme, ctx.opts.tokens).bg, strokeWidth: 1 },
		encoding: {
			// Shared bin edges from V1, shown on the axis.
			x: {
				field: 'lo',
				type: 'quantitative',
				bin: 'binned',
				title: ctx.card.name,
				scale: { domain: [edges[0], edges[edges.length - 1]], nice: false, zero: false },
				axis: { values: edges.length <= 21 ? edges : edges.filter((_, i) => i % Math.ceil(edges.length / 20) === 0), labelFlush: true }
			},
			x2: { field: 'hi' },
			y: { field: 'p', type: 'quantitative', title: pctTitle(ctx, groups), axis: { format: '.0%', tickCount: 4 } },
			tooltip: [
				{ field: 'label', type: 'nominal', title: 'Bin' },
				...(groups.length > 1 ? [{ field: 'groupLabel', type: 'nominal', title: 'Group' }] : []),
				{ field: 'count', type: 'quantitative', title: 'Responses' },
				{ field: 'p', type: 'quantitative', title: `% of ${denomWord(ctx)}`, format: '.1%' }
			]
		}
	};
	const layers: Spec[] = [bars];
	const anyHidden = data.some((d) => d.hidden);
	if (anyHidden) {
		// Hidden bins (export suppression) say so above the axis, unlike an empty bin.
		layers.push({
			transform: [{ filter: 'datum.hidden' }, { calculate: '(datum.lo + datum.hi) / 2', as: 'mid' }],
			mark: { type: 'text', baseline: 'bottom', dy: -3, angle: 0 },
			encoding: { x: { field: 'mid', type: 'quantitative' }, y: { datum: 0, type: 'quantitative' }, text: { field: 'text', type: 'nominal' } }
		});
	}
	const view: Spec = { width: ctx.width, height: 180, data: { values: data }, ...(anyHidden ? { layer: layers } : bars) };
	return groups.length > 1 ? multiples(data, view, gl, ctx) : view;
}

/** Slider frequency bars (one bar per step) or date periods: vertical bars over an ordinal axis. */
function columnBars(ctx: Ctx, kind: 'values' | 'periods'): Spec {
	const groups = groupsOf(ctx.card);
	if (!hasAnswers(groups)) return emptySpec(ctx, 'No answers to show.');
	const { data, groups: gl } = numberData(ctx.card, groups);
	const keys = (groups[0]?.cells ?? []).map((c) => c.label);
	const split = groups.length > 1 ? ctx.split : null;
	const periods = kind === 'periods';
	const unit = ctx.card.binUnit ?? 'month';
	const measure = periods ? 'count' : 'p';
	const yTitle = periods ? `Responses per ${unit}${groups.length === 1 ? ` (n = ${groups[0].n})` : ''}` : pctTitle(ctx, groups);
	const x: Spec = {
		field: 'label',
		type: 'ordinal',
		sort: keys,
		title: periods ? `Answer date, per ${unit}` : ctx.card.name,
		axis: { labelAngle: keys.length > 12 ? -45 : 0, labelOverlap: true }
	};
	const enc: Spec = {
		x,
		y: {
			field: measure,
			type: 'quantitative',
			title: yTitle,
			...(periods ? { axis: { tickMinStep: 1 } } : { axis: { format: '.0%', tickCount: 4 } }),
			...(split === 'stacked' ? { stack: 'zero' } : { stack: null })
		},
		tooltip: [
			{ field: 'label', type: 'nominal', title: periods ? 'Period' : 'Value' },
			...(groups.length > 1 ? [{ field: 'groupLabel', type: 'nominal', title: 'Group' }] : []),
			{ field: 'count', type: 'quantitative', title: 'Responses' },
			{ field: 'p', type: 'quantitative', title: `% of ${denomWord(ctx)}`, format: '.1%' }
		]
	};
	if (split === 'grouped' || split === 'stacked') {
		enc.color = { field: 'groupLabel', type: 'nominal', sort: gl, title: null };
		if (split === 'grouped') enc.xOffset = { field: 'groupLabel', type: 'nominal', sort: gl };
	}
	const layers: Spec[] = [{ mark: { type: 'bar', cornerRadiusEnd: 2 }, encoding: enc }];
	if (!split && keys.length <= 24) {
		layers.push({
			mark: { type: 'text', baseline: 'bottom', dy: -3 },
			encoding: { x, y: { field: measure, type: 'quantitative' }, text: { field: periods ? 'countText' : 'text', type: 'nominal' } }
		});
	}
	const view: Spec = { width: ctx.width, height: 180, data: { values: data }, layer: layers };
	return split === 'multiples' ? multiples(data, view, gl, ctx) : view;
}

function boxPlot(ctx: Ctx): Spec {
	const groups = groupsOf(ctx.card).filter((g) => g.stats.q1 !== null && g.stats.q1 !== undefined);
	if (!groups.length) return emptySpec(ctx, 'No answers to show.');
	// Five-number summary from V1's quartiles (type 7): no individual points (V-D5).
	const data: Datum[] = groups.map((g, gi) => ({
		groupLabel: groups.length === 1 && g.key === 'all' ? `n = ${g.n}` : groupLabel(g),
		groupOrder: gi,
		min: g.stats.min ?? null,
		q1: g.stats.q1 ?? null,
		median: typeof g.stats.median === 'number' ? g.stats.median : null,
		q3: g.stats.q3 ?? null,
		max: g.stats.max ?? null,
		mean: g.stats.mean ?? null,
		ciLo: g.stats.meanCi ? g.stats.meanCi[0] : null,
		ciHi: g.stats.meanCi ? g.stats.meanCi[1] : null
	}));
	const order = data.map((d) => d.groupLabel as string);
	const y = { field: 'groupLabel', type: 'nominal', sort: order, title: null };
	const x = { field: 'min', type: 'quantitative', title: ctx.card.name, scale: { zero: false, nice: true } };
	const c = textColors(ctx.opts.theme, ctx.opts.tokens);
	const tip = [
		{ field: 'min', type: 'quantitative', title: 'Min' },
		{ field: 'q1', type: 'quantitative', title: 'Q1' },
		{ field: 'median', type: 'quantitative', title: 'Median' },
		{ field: 'q3', type: 'quantitative', title: 'Q3' },
		{ field: 'max', type: 'quantitative', title: 'Max' }
	];
	const layers: Spec[] = [
		{ mark: { type: 'rule', color: c.muted }, encoding: { y, x, x2: { field: 'max' }, tooltip: tip } },
		{ mark: { type: 'bar', size: 18, opacity: 0.85 }, encoding: { y, x: { field: 'q1', type: 'quantitative' }, x2: { field: 'q3' }, tooltip: tip } },
		{ mark: { type: 'tick', thickness: 3, size: 18, color: c.text }, encoding: { y, x: { field: 'median', type: 'quantitative' }, tooltip: tip } }
	];
	if (ctx.opts.intervals && data.some((d) => d.ciLo !== null)) {
		const ci = { y, tooltip: [{ field: 'mean', type: 'quantitative', title: 'Mean', format: '.2f' }, { field: 'ciLo', type: 'quantitative', title: '95 % CI low', format: '.2f' }, { field: 'ciHi', type: 'quantitative', title: '95 % CI high', format: '.2f' }] };
		layers.push(
			{ mark: { type: 'rule', yOffset: 16, strokeWidth: 2, color: c.text }, encoding: { ...ci, x: { field: 'ciLo', type: 'quantitative' }, x2: { field: 'ciHi' } } },
			{ mark: { type: 'point', yOffset: 16, shape: 'diamond', filled: true, size: 50, color: c.text }, encoding: { ...ci, x: { field: 'mean', type: 'quantitative' } } }
		);
	}
	return { width: ctx.width, height: (ctx.opts.intervals ? 52 : 40) * data.length, data: { values: data }, layer: layers };
}

function cumulative(ctx: Ctx): Spec {
	const groups = groupsOf(ctx.card).filter((g) => g.n > 0);
	if (!groups.length) return emptySpec(ctx, 'No answers to show.');
	const values = ctx.card.binning === 'values';
	const data: Datum[] = [];
	const gl = groups.map(groupLabel);
	groups.forEach((g, gi) => {
		const answered = g.cells.reduce((a, c) => a + c.count, 0);
		if (!answered) return;
		let cum = 0;
		if (!values && g.cells.length && g.cells[0].lo !== null && g.cells[0].lo !== undefined) {
			data.push({ x: g.cells[0].lo, cum: 0, text: '0%', groupLabel: gl[gi], i: -1 });
		}
		g.cells.forEach((c, i) => {
			cum += c.count;
			const at = values ? (c.lo ?? Number(c.key)) : (c.hi ?? null);
			data.push({ x: at, cum: cum / answered, text: pctText(cum / answered), groupLabel: gl[gi], i });
		});
	});
	const split = groups.length > 1 ? ctx.split : null;
	const enc: Spec = {
		x: { field: 'x', type: 'quantitative', title: ctx.card.name, scale: { zero: false, nice: false } },
		y: {
			field: 'cum',
			type: 'quantitative',
			title: `Cumulative % of answers${groups.length === 1 ? ` (n = ${groups[0].n})` : ''}`,
			scale: { domain: [0, 1] },
			axis: { format: '.0%', tickCount: 5 }
		},
		order: { field: 'i', type: 'quantitative' },
		tooltip: [
			{ field: 'x', type: 'quantitative', title: values ? 'Value ≤' : 'Below' },
			...(groups.length > 1 ? [{ field: 'groupLabel', type: 'nominal', title: 'Group' }] : []),
			{ field: 'cum', type: 'quantitative', title: 'Cumulative %', format: '.1%' }
		]
	};
	if (split === 'grouped') {
		// Colour and dash both name the group.
		enc.color = { field: 'groupLabel', type: 'nominal', sort: gl, title: null };
		enc.strokeDash = { field: 'groupLabel', type: 'nominal', sort: gl, title: null };
		enc.detail = { field: 'groupLabel', type: 'nominal' };
	}
	const view: Spec = {
		width: ctx.width,
		height: 180,
		data: { values: data },
		mark: { type: 'line', interpolate: values ? 'step-after' : 'linear', point: true, strokeWidth: 2 },
		encoding: enc
	};
	return split === 'multiples' ? multiples(data, view, gl, ctx) : view;
}

// -- text and notes ----------------------------------------------------------------------

const STATE_LABELS: [keyof StateCounts, string, boolean][] = [
	['answered', 'Answered', true],
	['unanswered', 'Unanswered', true],
	['irrelevant', 'Not shown (condition)', true],
	['notReached', 'Not reached', true],
	['notInVersion', 'Not in this version', false],
	['unrecorded', 'No record', false],
	['invalid', 'Invalid', false]
];

function statesChart(ctx: Ctx): Spec {
	const states = ctx.card.states;
	if (!states) return emptySpec(ctx, 'No responses to show.');
	const data = STATE_LABELS.filter(([k, , always]) => always || states[k] > 0).map(([k, label], i) => ({ state: label, count: states[k], order: i }));
	const order = data.map((d) => d.state);
	const y = { field: 'state', type: 'nominal', sort: order, title: null };
	return {
		width: ctx.width,
		height: 26 * data.length,
		data: { values: data },
		layer: [
			{
				mark: { type: 'bar', cornerRadiusEnd: 2 },
				encoding: { y, x: { field: 'count', type: 'quantitative', title: 'Responses', axis: { tickMinStep: 1 } }, tooltip: [{ field: 'state', type: 'nominal', title: 'State' }, { field: 'count', type: 'quantitative', title: 'Responses' }] }
			},
			{ mark: { type: 'text', align: 'left', dx: 4, baseline: 'middle' }, encoding: { y, x: { field: 'count', type: 'quantitative' }, text: { field: 'count', type: 'quantitative' } } }
		]
	};
}

// -- dispatch ---------------------------------------------------------------------------

function view(ctx: Ctx, choice: ChartChoice): Spec {
	switch (choice) {
		case 'bars':
			return categoryBars(ctx, { measure: 'p', mark: 'bar', sorted: false });
		case 'bars-sorted':
			return categoryBars(ctx, { measure: 'p', mark: 'bar', sorted: true });
		case 'donut':
			return donut(ctx);
		case 'multi-pct':
			return categoryBars(ctx, { measure: 'p', mark: 'bar', sorted: false, axisExtra: ' (can sum > 100 %)' });
		case 'multi-counts':
			return categoryBars(ctx, { measure: 'count', mark: 'bar', sorted: false });
		case 'dot':
			return categoryBars(ctx, { measure: 'p', mark: 'point', sorted: false, axisExtra: ' (can sum > 100 %)' });
		case 'histogram':
			return histogram(ctx);
		case 'values':
			return columnBars(ctx, 'values');
		case 'periods':
			return columnBars(ctx, 'periods');
		case 'box':
			return boxPlot(ctx);
		case 'cumulative':
			return cumulative(ctx);
		case 'likert':
		case 'stacked100':
		case 'heatmap':
		case 'grouped':
			return matrixChart(ctx, choice);
		case 'states':
			return statesChart(ctx);
	}
}

/** Charts that only make sense for some card types fall back to that type's default. */
const FITS: Record<ChartChoice, Card['type'][]> = {
	bars: ['single'],
	'bars-sorted': ['single'],
	donut: ['single'],
	'multi-pct': ['multi'],
	'multi-counts': ['multi'],
	dot: ['multi'],
	histogram: ['integer', 'decimal', 'slider'],
	values: ['slider', 'integer', 'decimal'],
	box: ['integer', 'decimal', 'slider'],
	cumulative: ['integer', 'decimal', 'slider'],
	periods: ['date'],
	likert: ['matrix'],
	stacked100: ['matrix'],
	heatmap: ['matrix'],
	grouped: ['matrix'],
	states: ['text', 'single', 'multi', 'integer', 'decimal', 'slider', 'date', 'matrix']
};

/**
 * The Vega-Lite spec for `card` drawn as `chartChoice`. Data is embedded; the theme's
 * config is included. Cards V1 shows per version (`facets`) get one panel per version.
 * Throws for a choice that is not a chart ('table', 'hidden', 'heading') or that does not
 * fit the card's type (check `chartsFor(card)` first).
 */
export function buildSpec(card: Card, chartChoice: MenuChoice, opts: BuildOptions = {}): TopLevelSpec {
	if (!isChart(chartChoice)) throw new Error(`"${chartChoice}" is not a chart`);
	if (!FITS[chartChoice].includes(card.type)) throw new Error(`"${chartChoice}" does not fit a ${card.type} card`);
	hiddenText = opts.hiddenLabel ?? 'n<5';
	const resolved: Ctx['opts'] = {
		...opts,
		theme: opts.theme ?? 'app',
		tokens: opts.tokens ?? LIGHT_TOKENS,
		intervals: opts.intervals ?? false,
		denominator: opts.denominator ?? 'answered'
	};
	const layouts = splitsFor(card, chartChoice);
	const split = layouts.length ? (opts.split && layouts.includes(opts.split) ? opts.split : layouts[0]) : null;
	const facets = card.facets ?? [];
	const fixedWidth = opts.width ?? MULTIPLE_WIDTH;
	const ctx: Ctx = {
		card,
		opts: resolved,
		split,
		width: facets.length || split === 'multiples' ? fixedWidth : (opts.width ?? 'container'),
		cellWidth: opts.width ?? MULTIPLE_WIDTH
	};
	let body: Spec;
	if (facets.length) {
		// Per-version facets (V-D5): definitions differ, so never combined.
		body = {
			vconcat: facets.map((f) => {
				const sub: Card = { ...card, ...f, facets: null };
				const subSplit = splitsFor(sub, chartChoice);
				const v = view({ ...ctx, card: sub, split: subSplit.length ? (split && subSplit.includes(split) ? split : subSplit[0]) : null, width: fixedWidth }, chartChoice);
				return { title: { text: `Version ${f.version}`, anchor: 'start' }, ...v };
			}),
			resolve: { scale: { color: 'independent' } }
		};
	} else {
		body = view(ctx, chartChoice);
	}
	if (hasHidden(card)) showInvalidText(body);
	const spec: Spec = {
		$schema: VEGA_LITE_SCHEMA,
		...(opts.description ? { description: opts.description } : {}),
		...body,
		config: themeConfig(resolved.theme, resolved.tokens),
		usermeta: { osp: { question: card.question, chart: chartChoice, split, theme: resolved.theme } }
	};
	return spec as unknown as TopLevelSpec;
}

function hasHidden(card: Card): boolean {
	const units = [card, ...(card.facets ?? [])];
	return units.some((u) =>
		[...(u.groups ?? []), ...(u.rows ?? []).flatMap((r) => r.groups)].some((g) => g.cells.some(isHidden))
	);
}

/**
 * Hidden cells have no count or share (null): their text labels are placed as if zero
 * (`invalid: 'show'`) so the label still appears; bars and points for them are not drawn.
 */
function showInvalidText(node: unknown): void {
	if (Array.isArray(node)) {
		node.forEach(showInvalidText);
		return;
	}
	if (!node || typeof node !== 'object') return;
	const o = node as Spec;
	const mark = o.mark as Spec | string | undefined;
	if (mark === 'text') o.mark = { type: 'text', invalid: 'show' };
	else if (mark && typeof mark === 'object' && mark.type === 'text') mark.invalid = 'show';
	for (const k of ['layer', 'spec', 'vconcat', 'hconcat', 'concat']) if (k in o) showInvalidText(o[k]);
}

/** Default chart for `card` (the first `chartsFor` entry), as a spec, or null for notes. */
export function defaultSpec(card: Card, opts: BuildOptions = {}): TopLevelSpec | null {
	const first = chartsFor(card).default;
	return isChart(first) ? buildSpec(card, first, opts) : null;
}
