// Export runs (task V4): one card's files or the whole page as a ZIP, audited first.
// Browser only (renders with Vega, downloads with an <a download>).
import { chartsFor, isChart, splitsFor } from '../charts/menu';
import type { Card, ChartChoice, SplitLayout } from '../charts/types';
import type { ChartChoices } from '../charts.svelte';
import type { ResultsQuery, ResultsResponse } from '../types';
import { utf8 } from './bytes';
import { figureSpec, libraryVersions, physicalSvg, renderFigure } from './figure';
import {
	autoCaption,
	cardCsv,
	describeN,
	fileName,
	fileStem,
	manifest,
	suppressCard,
	type FigureEntry,
	type FileFormat
} from './model';
import { zipStore, type ZipEntry } from './zip';

export type ExportFormat = 'png' | 'svg' | 'csv' | 'vega-lite';

export interface ExportSettingsLike {
	widthMm: number;
	dpi: number;
	k: number | null;
	caption(question: string): string | undefined;
}

export interface ExportPage {
	response: ResultsResponse;
	/** The query the response answers (what the audit records). */
	query: ResultsQuery;
	/** The active filters in words. */
	filters: string[];
	charts: ChartChoices;
	/** Writes the `results.export` audit row; resolves to an error message or null. */
	record(body: { cards: string[]; formats: string[]; scope: 'card' | 'page'; suppressBelow: number | null }): Promise<string | null>;
	platform(): Promise<{ name: string; version: string }>;
}

export interface FileOut {
	name: string;
	data: Uint8Array;
	type: string;
}

/** The chart a card exports as: its chosen chart, else the menu default (a table → default). */
export function figureChoice(card: Card, charts: Pick<ChartChoices, 'get' | 'layout'>): { chart: ChartChoice | null; layout: SplitLayout | undefined } {
	const menu = chartsFor(card);
	const chosen = charts.get(card.question);
	let chart = chosen && menu.choices.some((c) => c.id === chosen) && isChart(chosen) ? chosen : null;
	if (!chart) {
		const first = menu.choices.find((c) => isChart(c.id))?.id;
		chart = first && isChart(first) ? first : null;
	}
	const layouts = chart ? splitsFor(card, chart) : [];
	const l = charts.layout(card.question);
	return { chart, layout: l && layouts.includes(l) ? l : layouts[0] };
}

export function captionFor(card: Card, page: Pick<ExportPage, 'filters'>, s: ExportSettingsLike, hidden: number): { text: string; edited: boolean } {
	const edited = s.caption(card.question);
	if (edited !== undefined) return { text: edited, edited: true };
	return { text: autoCaption(card, { filters: page.filters, k: s.k, hiddenCells: hidden }), edited: false };
}

const MIME: Record<FileFormat, string> = {
	svg: 'image/svg+xml',
	png: 'image/png',
	csv: 'text/csv',
	'vega-lite': 'application/json',
	manifest: 'application/json'
};

const json = (x: unknown) => utf8(JSON.stringify(x, null, 2) + '\n');

/** One card's files (and its manifest entry) at the current settings. */
export async function cardFiles(card: Card, page: ExportPage, s: ExportSettingsLike, formats: ExportFormat[], stem = fileStem(card)): Promise<{ files: FileOut[]; entry: FigureEntry }> {
	const { chart, layout } = figureChoice(card, page.charts);
	const denominator = page.response.denominator;
	const intervals = page.query.intervals ?? false;
	const named = { name: stem, question: stem };
	const files: FileOut[] = [];
	const entry: FigureEntry = {
		question: card.question,
		variable: card.name,
		type: card.type,
		chart,
		layout: layout ?? null,
		caption: '',
		captionEdited: false,
		n: describeN(card),
		hiddenCells: 0,
		files: []
	};
	// The hidden count is known before the caption (the caption names it).
	const probe = chart ? figureSpec(card, { chart, layout, denominator, intervals, widthMm: s.widthMm, caption: '', k: s.k }) : null;
	const hidden = probe?.hidden ?? 0;
	const cap = captionFor(card, page, s, hidden);
	entry.caption = cap.text;
	entry.captionEdited = cap.edited;
	entry.hiddenCells = hidden;
	const figure = chart ? figureSpec(card, { chart, layout, denominator, intervals, widthMm: s.widthMm, caption: cap.text, k: s.k }) : null;
	const add = (format: FileFormat, data: Uint8Array) => {
		const name = fileName(named, format);
		files.push({ name, data, type: MIME[format] });
		entry.files.push(name);
	};
	if (figure && (formats.includes('svg') || formats.includes('png'))) {
		const r = await renderFigure(figure.spec);
		try {
			if (formats.includes('svg')) {
				add('svg', utf8(physicalSvg(r.svg, s.widthMm)));
				entry.svg = { widthMm: s.widthMm };
			}
			if (formats.includes('png')) {
				const png = await r.png(s.dpi, s.widthMm);
				add('png', png.bytes);
				entry.png = { widthMm: s.widthMm, dpi: s.dpi, widthPx: png.width, heightPx: png.height };
			}
		} finally {
			r.dispose();
		}
	}
	if (formats.includes('csv')) {
		add('csv', utf8(cardCsv(suppressCard(card, s.k).card, { denominator, k: s.k })));
	}
	if (formats.includes('vega-lite') && figure) add('vega-lite', json(figure.spec));
	return { files, entry };
}

async function manifestBytes(page: ExportPage, s: ExportSettingsLike, figures: FigureEntry[], scope: 'card' | 'page'): Promise<Uint8Array> {
	const [platform, libraries] = await Promise.all([page.platform(), libraryVersions()]);
	return json(
		manifest({
			response: page.response,
			query: page.query,
			filters: page.filters,
			k: s.k,
			figures,
			exportedAt: new Date().toISOString(),
			platform,
			libraries,
			scope
		})
	);
}

export function download(file: FileOut): void {
	const url = URL.createObjectURL(new Blob([file.data as BlobPart], { type: file.type }));
	const a = document.createElement('a');
	a.href = url;
	a.download = file.name;
	a.rel = 'noopener';
	a.style.display = 'none';
	document.body.append(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

/** Export one card in `format` (the spec comes with its manifest). Audited first. */
export async function exportCard(card: Card, page: ExportPage, s: ExportSettingsLike, format: ExportFormat): Promise<FileOut[]> {
	const formats = format === 'vega-lite' ? ['vega-lite', 'manifest'] : [format];
	const refused = await page.record({ cards: [card.question], formats, scope: 'card', suppressBelow: s.k });
	if (refused) throw new Error(refused);
	const { files, entry } = await cardFiles(card, page, s, [format]);
	if (format === 'vega-lite') {
		const name = fileName(card, 'manifest');
		entry.files.push(name);
		files.push({ name, data: await manifestBytes(page, s, [entry], 'card'), type: MIME.manifest });
	}
	return files;
}

/** Every card's SVG, PNG, CSV and spec plus one manifest, as a store-only ZIP. Audited first. */
export async function exportAll(page: ExportPage, s: ExportSettingsLike, progress?: (done: number, total: number) => void): Promise<FileOut> {
	const cards = page.response.cards.filter((c) => c.type !== 'note');
	const refused = await page.record({
		cards: cards.map((c) => c.question),
		formats: ['svg', 'png', 'csv', 'vega-lite', 'manifest', 'zip'],
		scope: 'page',
		suppressBelow: s.k
	});
	if (refused) throw new Error(refused);
	const entries: ZipEntry[] = [];
	const figures: FigureEntry[] = [];
	const stems = new Set<string>();
	for (const [i, card] of cards.entries()) {
		progress?.(i, cards.length);
		let stem = fileStem(card);
		for (let n = 2; stems.has(stem); n++) stem = `${fileStem(card)}_${n}`;
		stems.add(stem);
		const { files, entry } = await cardFiles(card, page, s, ['svg', 'png', 'csv', 'vega-lite'], stem);
		entries.push(...files.map((f) => ({ name: f.name, data: f.data })));
		figures.push(entry);
	}
	progress?.(cards.length, cards.length);
	entries.push({ name: 'manifest.json', data: await manifestBytes(page, s, figures, 'page') });
	const day = new Date().toISOString().slice(0, 10);
	return { name: `results-${page.response.surveyId.slice(0, 8)}-${day}.zip`, data: zipStore(entries), type: 'application/zip' };
}
