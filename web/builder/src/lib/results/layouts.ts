/**
 * Saved results layouts (task V5b, planning/results-viewer.md V-D9): how the Results page's
 * state maps to a layout's settings (`LayoutSettings`, V5a) and back. Pure: no API calls.
 *
 * A layout holds the applied filters (versions, status, dates, condition, answer filters,
 * split, denominator, intervals, label language), one entry per card in display order
 * (chart, split layout, hidden, bins, edited caption) and "show notes". It never holds
 * data. Not in a layout, kept for the page's life only: each card's chart/Table view
 * switch, and V4's export width, DPI and "Hide counts below k" (the layout schema has no
 * place for them).
 */
import type { CardChoices } from './charts.svelte';
import { CHART_LABELS, chartsFor } from './charts/menu';
import type { MenuChoice, SplitLayout } from './charts/types';
import { BUNDLES, DEFAULT_EXPORT, type Bundle, type ExportChoices } from './export/settings.svelte';
import { DPI_CHOICES, MAX_MM, MIN_MM } from './export/model';
import { cleanBins, defaultFilters, endExclusive, startInclusive, type ResultsFilters } from './model';
import { APP_THEME, choiceFromLayout, type ThemeChoice } from './results-theme';
import type { Card, CardLayout, LayoutSettings } from './types';

export const SCHEMA_VERSION = 'osp-results-layout/0.1' as const;
export const MAX_CAPTION = 2000;

/** What a layout restores: the page state it maps to. */
export interface PageState {
	filters: ResultsFilters;
	cards: CardChoices;
	/** Edited captions per question (V4's export settings). */
	captions: Record<string, string>;
	/** Display order; questions not listed follow in survey order. */
	order: string[];
	showNotes: boolean;
	/** The page's theme (V6): a reference, never a theme document. */
	theme: ThemeChoice;
	/** V4's export width, DPI and k, and what "Export all" bundles (V6). */
	exports: ExportChoices;
}

export function emptyState(latest: number): PageState {
	return {
		filters: defaultFilters(latest),
		cards: { chosen: {}, layouts: {}, bins: {}, hidden: {} },
		captions: {},
		order: [],
		showNotes: false,
		theme: { ...APP_THEME },
		exports: { ...DEFAULT_EXPORT }
	};
}

// -- order --------------------------------------------------------------------------------

/** Items in display order: those `order` lists first (in that order), then the rest as given. */
export function inOrder<T extends { question: string }>(items: readonly T[], order: readonly string[]): T[] {
	const by = new Map(items.map((c) => [c.question, c]));
	const out: T[] = [];
	const seen = new Set<string>();
	for (const q of order) {
		const c = by.get(q);
		if (c && !seen.has(q)) {
			out.push(c);
			seen.add(q);
		}
	}
	for (const c of items) if (!seen.has(c.question)) out.push(c);
	return out;
}

/** `display` with `question` moved to index `to` (clamped). */
export function moved(display: readonly string[], question: string, to: number): string[] {
	const from = display.indexOf(question);
	if (from < 0) return [...display];
	const out = display.filter((q) => q !== question);
	out.splice(Math.max(0, Math.min(out.length, to)), 0, question);
	return out;
}

// -- dates --------------------------------------------------------------------------------

function utcDay(d: Date): string {
	return Number.isNaN(d.getTime()) ? '' : d.toISOString().slice(0, 10);
}

/** A stored `submittedFrom` as the bar's inclusive start day. */
export function fromDay(iso: string | null | undefined): string {
	return iso ? utcDay(new Date(iso)) : '';
}

/** A stored (exclusive) `submittedTo` as the bar's inclusive end day. */
export function toDay(iso: string | null | undefined): string {
	if (!iso) return '';
	const t = new Date(iso).getTime();
	return Number.isNaN(t) ? '' : utcDay(new Date(t - 1));
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

// -- state -> settings ----------------------------------------------------------------------

/**
 * The layout settings for this page state. `questions` (the response's cards, in survey
 * order) makes the card list the full display order; without it only the cards the state
 * names are listed. `latest` is the latest published version: a layout on just that
 * version is saved as "the latest" (no versions), so it follows the next publish.
 */
export function toSettings(state: PageState, latest: number, questions?: readonly string[]): LayoutSettings {
	const f = state.filters;
	const versions = [...new Set(f.versions)].sort((a, b) => a - b);
	const followLatest = !versions.length || (versions.length === 1 && versions[0] === latest);
	const query: LayoutSettings['query'] = {
		versions: followLatest ? null : versions,
		status: f.status,
		submittedFrom: f.from && DAY.test(f.from) ? startInclusive(f.from) : null,
		submittedTo: f.to && DAY.test(f.to) ? endExclusive(f.to) : null,
		filters: f.answers.filter((a) => a.question && a.codes.length).map((a) => ({ question: a.question, in: [...a.codes] })),
		condition:
			f.condition && f.condition.levels.length ? { variable: f.condition.variable, in: [...f.condition.levels] } : null,
		split: f.split
			? f.split.kind === 'question'
				? { question: f.split.id, condition: null, excludeMissing: !!f.split.excludeMissing }
				: { question: null, condition: f.split.id, excludeMissing: !!f.split.excludeMissing }
			: null,
		denominator: f.denominator,
		intervals: f.intervals,
		language: f.language || null
	};

	const c = state.cards;
	const named = new Set([
		...Object.keys(c.chosen),
		...Object.keys(c.layouts),
		...Object.keys(c.bins).filter((q) => cleanBins(c.bins[q])),
		...Object.keys(c.hidden).filter((q) => c.hidden[q]),
		...Object.keys(state.captions)
	]);
	const list: string[] = [];
	const add = (q: string) => {
		if (!list.includes(q)) list.push(q);
	};
	if (questions) inOrder(questions.map((question) => ({ question })), state.order).forEach((x) => add(x.question));
	state.order.forEach(add);
	[...named].sort().forEach(add);

	const cards: CardLayout[] = list.map((q) => ({
		question: q,
		chart: c.chosen[q] ?? null,
		splitLayout: c.layouts[q] ?? null,
		hidden: !!c.hidden[q],
		bins: cleanBins(c.bins[q]),
		caption: q in state.captions ? state.captions[q].slice(0, MAX_CAPTION) : null
	}));
	const t = state.theme;
	const e = state.exports;
	return {
		schemaVersion: SCHEMA_VERSION,
		query,
		cards,
		showNotes: state.showNotes,
		theme: { kind: t.kind, id: t.kind === 'preset' || t.kind === 'library' ? t.id : null },
		export: {
			widthMm: Math.min(MAX_MM, Math.max(MIN_MM, Math.round(e.widthMm))),
			dpi: ((DPI_CHOICES as readonly number[]).includes(e.dpi) ? e.dpi : DEFAULT_EXPORT.dpi) as 150 | 300 | 600,
			hideCountsBelow: e.k === null ? null : Math.min(1000, Math.max(2, Math.round(e.k))),
			bundle: BUNDLES.includes(e.bundle) ? e.bundle : DEFAULT_EXPORT.bundle
		}
	};
}

/** A layout's `export` part as the page's export choices (defaults for anything missing or wrong). */
export function exportsFromLayout(e: LayoutSettings['export'] | null | undefined): ExportChoices {
	const out = { ...DEFAULT_EXPORT };
	if (!e) return out;
	if (typeof e.widthMm === 'number' && e.widthMm >= MIN_MM && e.widthMm <= MAX_MM) out.widthMm = Math.round(e.widthMm);
	if ((DPI_CHOICES as readonly number[]).includes(e.dpi as number)) out.dpi = e.dpi as number;
	if (typeof e.hideCountsBelow === 'number' && e.hideCountsBelow >= 2) out.k = Math.min(1000, Math.round(e.hideCountsBelow));
	if (BUNDLES.includes(e.bundle as Bundle)) out.bundle = e.bundle as Bundle;
	return out;
}

// -- settings -> state ----------------------------------------------------------------------

/** The page state a layout's settings open (unknown or missing parts take the defaults). */
export function fromSettings(settings: LayoutSettings | null | undefined, latest: number): PageState {
	const state = emptyState(latest);
	if (!settings) return state;
	const q = settings.query;
	if (q) {
		const f = state.filters;
		if (q.versions?.length) f.versions = [...new Set(q.versions)].sort((a, b) => a - b);
		f.status = q.status === 'all' ? 'all' : 'complete';
		f.from = fromDay(q.submittedFrom);
		f.to = toDay(q.submittedTo);
		f.answers = (q.filters ?? []).map((a) => ({ question: a.question, codes: a.in.map(String) }));
		f.condition = q.condition ? { variable: q.condition.variable, levels: q.condition.in.map(String) } : null;
		if (q.split && (q.split.question || q.split.condition)) {
			f.split = q.split.question
				? { kind: 'question', id: q.split.question }
				: { kind: 'condition', id: q.split.condition! };
			if (q.split.excludeMissing) f.split.excludeMissing = true;
		}
		f.denominator = q.denominator === 'shown' ? 'shown' : 'answered';
		f.intervals = q.intervals === true;
		f.language = q.language || null;
	}
	for (const card of settings.cards ?? []) {
		const id = card.question;
		if (!id || state.order.includes(id)) continue;
		state.order.push(id);
		if (card.chart) state.cards.chosen[id] = card.chart as MenuChoice;
		if (card.splitLayout) state.cards.layouts[id] = card.splitLayout as SplitLayout;
		const bins = cleanBins(card.bins);
		if (bins) state.cards.bins[id] = bins;
		if (card.hidden) state.cards.hidden[id] = true;
		if (typeof card.caption === 'string') state.captions[id] = card.caption;
	}
	state.showNotes = settings.showNotes === true;
	state.theme = choiceFromLayout(settings.theme);
	state.exports = exportsFromLayout(settings.export);
	return state;
}

/** Whether two page states make the same layout (for the unsaved-changes indicator). */
export function sameLayout(a: PageState, b: PageState, latest: number, questions?: readonly string[]): boolean {
	return JSON.stringify(toSettings(a, latest, questions)) === JSON.stringify(toSettings(b, latest, questions));
}

// -- fallbacks ------------------------------------------------------------------------------

export interface ChartNotice {
	question: string;
	message: string;
}

/**
 * Cards whose chosen chart (from a layout) does not suit the question (an unknown id, or a
 * question whose type changed): the card shows the menu's default instead, and says so.
 */
export function chartNotices(cards: readonly Card[], chosen: Readonly<Record<string, string>>): ChartNotice[] {
	const out: ChartNotice[] = [];
	for (const card of cards) {
		const id = chosen[card.question];
		if (!id) continue;
		const menu = chartsFor(card);
		if (menu.choices.some((c) => c.id === id)) continue;
		const name = (CHART_LABELS as Record<string, string>)[id] ?? id;
		out.push({
			question: card.question,
			message: `${card.label || card.name}: the layout's chart “${name}” does not suit this question, so it shows ${CHART_LABELS[menu.default]} instead.`
		});
	}
	return out;
}

// -- errors ---------------------------------------------------------------------------------

/** A clear message for a failed layout request. */
export function layoutError(
	status: number,
	body: { message?: unknown; diagnostics?: unknown; detail?: unknown } | undefined,
	ctx: { name?: string; action: string }
): string {
	const message = typeof body?.message === 'string' ? body.message : '';
	switch (status) {
		case 409:
			return ctx.name
				? `There is already a layout called “${ctx.name}”. Choose another name.`
				: message || 'That conflicts with another layout.';
		case 422: {
			const diags = Array.isArray(body?.diagnostics) ? body!.diagnostics : Array.isArray(body?.detail) ? body!.detail : [];
			const parts = (diags as { message?: unknown; msg?: unknown; pointer?: unknown }[])
				.slice(0, 3)
				.map((d) => {
					const m = typeof d?.message === 'string' ? d.message : typeof d?.msg === 'string' ? d.msg : '';
					const at = typeof d?.pointer === 'string' && d.pointer ? ` (at ${d.pointer})` : '';
					return m ? `${m}${at}` : '';
				})
				.filter(Boolean);
			const why = parts.length ? parts.join('; ') : message || 'the server refused it';
			return `The layout could not be ${ctx.action}: ${why}.`;
		}
		case 403:
			return 'You need owner or editor access to this survey to change its layouts.';
		case 404:
			return 'That layout no longer exists (it may have been deleted elsewhere). The list has been refreshed.';
		case 0:
			return `The layout could not be ${ctx.action}: ${message || 'network error'}.`;
		default:
			return message || `The layout could not be ${ctx.action} (error ${status}).`;
	}
}
