// Figure export, the pure part (task V4, planning/results-viewer.md V-D4, V-D6–V-D8):
// final sizes, "Hide counts below k", auto captions, the aggregate CSV, the manifest and
// file names. Nothing is re-aggregated: every number is V1's, only hidden or relabelled.
import type { Card, Cell, Group, HiddenCell, MenuChoice, SplitLayout } from '../charts/types';
import type { ResultsQuery, ResultsResponse } from '../types';

// -- sizes ------------------------------------------------------------------------------

/** Journal column widths (V-D6): single column 85 mm, double 180 mm, or custom. */
export const WIDTH_PRESETS = [
	{ id: 'single', label: 'Single column, 85 mm', mm: 85 },
	{ id: 'double', label: 'Double column, 180 mm', mm: 180 }
] as const;
export const DPI_CHOICES = [150, 300, 600] as const;
export const MIN_MM = 30;
export const MAX_MM = 500;

/** CSS pixels per inch: a figure laid out at its final width at 96 px/in has true text sizes. */
export const CSS_DPI = 96;
export const MM_PER_INCH = 25.4;

/** Width in CSS px of a figure `mm` wide (its final-size layout). */
export const cssWidth = (mm: number): number => Math.round((mm / MM_PER_INCH) * CSS_DPI);

/** PNG pixel width for `mm` at `dpi` (85 mm at 300 dpi = 1004 px). */
export const pixelWidth = (mm: number, dpi: number): number => Math.round((mm / MM_PER_INCH) * dpi);

/** Pixel height that keeps the aspect ratio of a `w` × `h` layout at `pxWidth`. */
export const pixelHeight = (w: number, h: number, pxWidth: number): number => Math.max(1, Math.round((h * pxWidth) / w));

export function validMm(mm: number): boolean {
	return Number.isFinite(mm) && mm >= MIN_MM && mm <= MAX_MM;
}

// -- suppression (V-D4) ----------------------------------------------------------------

export const DEFAULT_K = 5;
/** The export dialog warns when a shown cell has a count below this (V-D4). */
export const WARN_BELOW = 5;

type Unit = { groups?: Group[] | null; rows?: { groups: Group[] }[] | null };

function unitsOf(card: Card): Unit[] {
	return card.facets?.length ? card.facets : [card];
}

function cellsOf(card: Card): Cell[] {
	const out: Cell[] = [];
	for (const u of unitsOf(card)) {
		for (const g of u.groups ?? []) out.push(...g.cells);
		for (const r of u.rows ?? []) for (const g of r.groups) out.push(...g.cells);
	}
	return out;
}

const hidden = (c: Cell) => (c as HiddenCell).hidden === true;

/** True when a count would be hidden by "Hide counts below k": 1 ≤ count < k (0 stays 0). */
export const hides = (count: number, k: number): boolean => count > 0 && count < k;

/**
 * The card with every cell whose count is 1 … k-1 marked hidden: its share and interval
 * are removed; the count stays only for the chart builders, which never draw it. Zero
 * counts stay visible (a zero is not a small cell). `k` null: the card unchanged.
 */
export function suppressCard(card: Card, k: number | null): { card: Card; hidden: number } {
	if (k === null) return { card, hidden: 0 };
	let n = 0;
	const cell = (c: Cell): Cell => {
		if (!hides(c.count, k)) return c;
		n++;
		return { ...c, pct: null, ci: null, hidden: true } as HiddenCell;
	};
	const group = (g: Group): Group => ({ ...g, cells: g.cells.map(cell) });
	const unit = <U extends Unit>(u: U): U => ({
		...u,
		...(u.groups ? { groups: u.groups.map(group) } : {}),
		...(u.rows ? { rows: u.rows.map((r) => ({ ...r, groups: r.groups.map(group) })) } : {})
	});
	const out: Card = unit(card);
	if (card.facets?.length) out.facets = card.facets.map(unit);
	return { card: out, hidden: n };
}

/** Shown (not hidden) cells with 1 … WARN_BELOW-1 responses: the export dialog warns. */
export function smallCells(card: Card): number {
	return cellsOf(card).filter((c) => !hidden(c) && hides(c.count, WARN_BELOW)).length;
}

/** Chart types drawn from every answer (curves, quartiles): suppression cannot hide cells in them. */
export const DERIVED_CHARTS: readonly MenuChoice[] = ['cumulative', 'box'];

// -- captions (V-D8) ---------------------------------------------------------------------

const nf = new Intl.NumberFormat('en', { maximumFractionDigits: 0 });

function range(ns: number[]): string {
	const lo = Math.min(...ns);
	const hi = Math.max(...ns);
	return lo === hi ? nf.format(lo) : `${nf.format(lo)}–${nf.format(hi)}`;
}

/** "n = 3", "n = 2 (a), 2 (b)", "n per row 3–5", per version when faceted. */
export function describeN(card: Card): string {
	const one = (u: Unit): string => {
		if (u.rows?.length) {
			const groups = u.rows[0].groups;
			if (groups.length > 1) {
				return `n per row ${groups.map((g, i) => `${range(u.rows!.map((r) => r.groups[i]?.n ?? 0))} (${g.label})`).join(', ')}`;
			}
			return `n per row ${range(u.rows.map((r) => r.groups[0]?.n ?? 0))}`;
		}
		const gs = u.groups ?? [];
		if (gs.length <= 1) return `n = ${nf.format(gs[0]?.n ?? 0)}`;
		return `n = ${gs.map((g) => `${nf.format(g.n)} (${g.label})`).join(', ')}`;
	};
	if (card.facets?.length) return card.facets.map((f) => `version ${f.version}: ${one(f)}`).join('; ');
	return one(card);
}

export interface CaptionContext {
	/** The active filters in words (`describeFilters`), versions first. */
	filters: string[];
	/** "Hide counts below k" threshold, or null. */
	k: number | null;
	/** Cells hidden on this card. */
	hiddenCells: number;
}

/**
 * The automatic caption (V-D8): question text and variable, versions, filters, split,
 * denominator, n, and "counts below k hidden" when suppression is on. Editable in the dialog.
 */
export function autoCaption(card: Card, ctx: CaptionContext): string {
	const title = card.label && card.label !== card.name ? `${card.label} (${card.name})` : card.name;
	const parts = [`${title}.`];
	const filters = ctx.filters.filter((f) => !/^(Latest version|Versions? )/.test(f));
	const versions = `${card.versionsUsed.length === 1 ? 'Version' : 'Versions'} ${card.versionsUsed.join(', ')}`;
	parts.push(`${[versions, ...filters].join('; ')}.`);
	parts.push(`${describeN(card)} responses.`);
	if (ctx.k !== null) {
		parts.push(
			`Counts below ${ctx.k} hidden (shown as "n<${ctx.k}"; ${ctx.hiddenCells} ${ctx.hiddenCells === 1 ? 'cell' : 'cells'}).`
		);
	}
	return parts.join(' ');
}

/** Caption text split into lines of at most `chars` characters, at spaces. */
export function wrapText(text: string, chars: number): string[] {
	const words = text.replace(/\s+/g, ' ').trim().split(' ');
	const lines: string[] = [];
	let line = '';
	for (const w of words) {
		if (!w) continue;
		if (!line) line = w;
		else if (line.length + 1 + w.length <= chars) line += ` ${w}`;
		else {
			lines.push(line);
			line = w;
		}
	}
	if (line) lines.push(line);
	return lines;
}

// -- CSV (V-D6) --------------------------------------------------------------------------

export const CSV_COLUMNS = [
	'question',
	'variable',
	'type',
	'version',
	'row',
	'group',
	'group_label',
	'group_n',
	'denominator',
	'category',
	'label',
	'bin_lo',
	'bin_hi',
	'count',
	'percent',
	'ci_low',
	'ci_high',
	'hidden'
] as const;

/** One CSV field: quoted when needed; a leading = + - @ is defused (spreadsheet formulas). */
export function csvField(v: string | number | null | undefined): string {
	if (v === null || v === undefined) return '';
	let s = typeof v === 'number' ? (Number.isFinite(v) ? String(v) : '') : v;
	if (typeof v === 'string' && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
	return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

const round = (x: number | null | undefined, places = 4): number | null =>
	x === null || x === undefined || !Number.isFinite(x) ? null : Math.round(x * 10 ** places) / 10 ** places;

/**
 * The aggregate table behind a card as CSV: one line per (version, row, group, category)
 * with counts, the group's denominator n, numeric bin edges and 95 % intervals when
 * present. Hidden cells have blank count and percent and `hidden` = "<k".
 */
export function cardCsv(card: Card, opts: { denominator: string; k: number | null }): string {
	const lines = [CSV_COLUMNS.join(',')];
	const facets = card.facets?.length ? card.facets.map((f) => ({ v: String(f.version), u: f as Unit })) : [{ v: card.versionsUsed.join(' '), u: card as Unit }];
	const labelOf = (u: Unit & { categories?: Card['categories'] }, key: string, fallback: string) =>
		u.categories?.find((c) => c.key === key)?.label ?? fallback;
	for (const { v, u } of facets) {
		const sections = u.rows?.length
			? (u.rows as { id?: string; name?: string; groups: Group[] }[]).map((r) => ({ row: r.name ?? r.id ?? '', groups: r.groups }))
			: [{ row: '', groups: u.groups ?? [] }];
		for (const s of sections) {
			for (const g of s.groups) {
				for (const c of g.cells) {
					const hid = hidden(c);
					lines.push(
						[
							card.question,
							card.name,
							card.type,
							v,
							s.row,
							g.key,
							g.label,
							g.n,
							opts.denominator,
							c.key,
							labelOf(u as Unit & { categories?: Card['categories'] }, c.key, c.label),
							c.lo ?? null,
							c.hi ?? null,
							hid ? null : c.count,
							hid ? null : round(c.pct),
							hid ? null : round(c.ci?.[0]),
							hid ? null : round(c.ci?.[1]),
							hid ? `<${opts.k ?? ''}` : ''
						]
							.map(csvField)
							.join(',')
					);
				}
			}
		}
	}
	return lines.join('\r\n') + '\r\n';
}

// -- file names and manifest -------------------------------------------------------------

/** A safe file stem from a variable name: letters, digits, - and _ only. */
export function fileStem(card: Pick<Card, 'name' | 'question'>): string {
	const s = (card.name || card.question).normalize('NFKD').replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '');
	return s.slice(0, 60) || 'question';
}

export type FileFormat = 'svg' | 'png' | 'csv' | 'vega-lite' | 'manifest';

export function fileName(card: Pick<Card, 'name' | 'question'>, format: FileFormat): string {
	const stem = fileStem(card);
	switch (format) {
		case 'svg':
			return `${stem}.svg`;
		case 'png':
			return `${stem}.png`;
		case 'csv':
			return `${stem}.csv`;
		case 'vega-lite':
			return `${stem}.vl.json`;
		case 'manifest':
			return `${stem}.manifest.json`;
	}
}

export interface PngSettings {
	widthMm: number;
	dpi: number;
}

export interface FigureEntry {
	question: string;
	variable: string;
	type: string;
	chart: MenuChoice | null;
	layout: SplitLayout | null;
	caption: string;
	captionEdited: boolean;
	n: string;
	hiddenCells: number;
	files: string[];
	png?: PngSettings & { widthPx: number; heightPx: number };
	svg?: { widthMm: number };
}

export interface ManifestInput {
	response: Pick<ResultsResponse, 'surveyId' | 'versionsUsed' | 'generatedAt' | 'queryHash' | 'watermark' | 'denominator' | 'split' | 'language' | 'responses'>;
	query: ResultsQuery;
	filters: string[];
	k: number | null;
	figures: FigureEntry[];
	exportedAt: string;
	platform: { name: string; version: string };
	libraries: { vega: string; vegaLite: string; vegaEmbed: string };
	scope: 'card' | 'page';
	/** The colours the figures were drawn in (task V6); default the publication look. */
	theme?: string;
}

export const PUBLICATION_THEME = 'export (white background, Okabe-Ito palette, text >= 8 pt at final size)';

/** The manifest (V-D6): where the figures came from, enough to redo them. Values excluded. */
export function manifest(m: ManifestInput) {
	return {
		format: 'osp-results-export',
		manifestVersion: 1,
		scope: m.scope,
		surveyId: m.response.surveyId,
		versions: m.response.versionsUsed,
		language: m.response.language,
		responses: m.response.responses,
		filters: m.filters,
		split: m.response.split ? { question: m.response.split.question ?? null, condition: m.response.split.condition ?? null, label: m.response.split.label } : null,
		denominator: m.response.denominator,
		intervals: m.query.intervals ?? false,
		suppression: m.k === null ? null : { hideCountsBelow: m.k, marker: `n<${m.k}` },
		query: m.query,
		queryHash: m.response.queryHash,
		watermark: m.response.watermark,
		generatedAt: m.response.generatedAt,
		exportedAt: m.exportedAt,
		units: 'responses',
		platform: m.platform,
		vega: m.libraries,
		theme: m.theme ?? PUBLICATION_THEME,
		figures: m.figures
	};
}
