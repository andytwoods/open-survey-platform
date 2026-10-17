// Export figures (task V4, V-D6–V-D8): the export-theme spec at its final width with the
// caption drawn under it, and (browser only) its SVG and PNG. The PNG is rendered at
// final width × dpi / 96, resampled to the exact pixel width, and given pHYs DPI metadata.
import type { TopLevelSpec } from 'vega-lite';
import { buildSpec } from '../charts/spec';
import { EXPORT_TEXT, EXPORT_TOKENS } from '../charts/theme';
import type { Card, ChartChoice, SplitLayout, ThemeTokens } from '../charts/types';
import { cssWidth, pixelHeight, pixelWidth, suppressCard, wrapText } from './model';
import { withDpi } from './png';

export interface FigureOptions {
	chart: ChartChoice;
	layout?: SplitLayout;
	denominator: 'answered' | 'shown';
	intervals: boolean;
	widthMm: number;
	caption: string;
	/** "Hide counts below k", or null. */
	k: number | null;
	/** The colours to draw with (task V6: a results theme); default the publication look. */
	tokens?: ThemeTokens | null;
}

type Spec = Record<string, unknown>;

/** Average glyph width of the export font, as a share of its size (sans, mixed case). */
const GLYPH = 0.52;
/** Room for axis labels, legends and padding next to a fixed-width panel. */
const COMPOUND_ROOM = 200;

const compound = (s: Spec) => 'facet' in s || 'vconcat' in s || 'hconcat' in s || 'concat' in s;

/**
 * The export-theme Vega-Lite spec of `card` at `widthMm`, data embedded, hidden cells
 * applied and the caption as a bottom title (so it is in the SVG, the PNG and the spec).
 */
export function figureSpec(card: Card, o: FigureOptions): { spec: TopLevelSpec; hidden: number; widthPx: number } {
	const { card: shown, hidden } = suppressCard(card, o.k);
	const width = cssWidth(o.widthMm);
	const tokens = o.tokens ?? EXPORT_TOKENS;
	const base = {
		theme: 'export' as const,
		tokens,
		split: o.layout,
		denominator: o.denominator,
		intervals: o.intervals,
		description: o.caption,
		hiddenLabel: o.k === null ? undefined : `n<${o.k}`
	};
	let spec = buildSpec(shown, o.chart, { ...base, width }) as unknown as Spec;
	if (compound(spec)) {
		spec = buildSpec(shown, o.chart, { ...base, width: Math.max(140, width - COMPOUND_ROOM) }) as unknown as Spec;
	} else {
		// One view: the whole figure, axes and legend included, is `width` px wide.
		spec = { ...spec, width, autosize: { type: 'fit-x', contains: 'padding' } };
	}
	const size = EXPORT_TEXT.label;
	const lines = wrapText(o.caption, Math.max(20, Math.floor((width - 16) / (size * GLYPH))));
	if (lines.length) {
		spec.title = {
			text: lines,
			orient: 'bottom',
			anchor: 'start',
			frame: 'bounds',
			fontSize: size,
			fontWeight: 'normal',
			lineHeight: Math.round(size * 1.35),
			color: tokens.text,
			offset: 12
		};
	}
	const meta = (spec.usermeta as Spec | undefined) ?? {};
	spec.usermeta = { ...meta, osp: { ...((meta.osp as Spec | undefined) ?? {}), caption: o.caption, widthMm: o.widthMm, hideCountsBelow: o.k } };
	return { spec: spec as unknown as TopLevelSpec, hidden, widthPx: width };
}

/** The background a figure spec was built with (for the PNG's padding). */
export function specBackground(spec: TopLevelSpec): string {
	const bg = (spec as { config?: { background?: unknown } }).config?.background;
	return typeof bg === 'string' && bg ? bg : '#ffffff';
}

// -- rendering (browser) -----------------------------------------------------------------

export interface Rendered {
	svg: string;
	/** Layout size in CSS px (the SVG's own size). */
	width: number;
	height: number;
	png(dpi: number, widthMm: number): Promise<{ bytes: Uint8Array; width: number; height: number }>;
	dispose(): void;
}

function svgSize(svg: string): { width: number; height: number } {
	const head = /<svg[^>]*>/.exec(svg)?.[0] ?? '';
	const num = (a: string) => Number(new RegExp(`\\s${a}="([\\d.]+)"`).exec(head)?.[1] ?? 0);
	return { width: num('width'), height: num('height') };
}

/** The SVG with its physical size in mm (viewBox in CSS px), so it lands at final size. */
export function physicalSvg(svg: string, widthMm: number): string {
	const { width, height } = svgSize(svg);
	if (!width || !height) return svg;
	const hMm = Math.round(((height * widthMm) / width) * 100) / 100;
	return svg.replace(/<svg[^>]*>/, (head) => {
		let h = head.replace(/\swidth="[\d.]+"/, ` width="${widthMm}mm"`).replace(/\sheight="[\d.]+"/, ` height="${hMm}mm"`);
		if (!/\sviewBox=/.test(h)) h = h.replace('<svg', `<svg viewBox="0 0 ${width} ${height}"`);
		return h;
	});
}

async function canvasBytes(canvas: HTMLCanvasElement): Promise<Uint8Array> {
	const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
	if (!blob) throw new Error('The PNG could not be made.');
	return new Uint8Array(await blob.arrayBuffer());
}

/** Draw `spec` off screen (export theme, SVG renderer) and keep the view for PNG export. */
export async function renderFigure(spec: TopLevelSpec): Promise<Rendered> {
	const { default: embed } = await import('vega-embed');
	const host = document.createElement('div');
	host.setAttribute('aria-hidden', 'true');
	host.style.cssText = 'position:fixed;left:-20000px;top:0;visibility:hidden;pointer-events:none';
	document.body.append(host);
	try {
		const result = await embed(host, spec, { renderer: 'svg', actions: false, ast: true, defaultStyle: false });
		const view = result.view;
		const svg = await view.toSVG();
		const { width, height } = svgSize(svg);
		const dispose = () => {
			result.finalize();
			host.remove();
		};
		return {
			svg,
			width,
			height,
			async png(dpi, widthMm) {
				const pxW = pixelWidth(widthMm, dpi);
				const pxH = pixelHeight(width, height, pxW);
				const drawn = (await view.toCanvas(pxW / width)) as unknown as HTMLCanvasElement;
				let canvas = drawn;
				if (drawn.width !== pxW || drawn.height !== pxH) {
					// Rounding inside Vega can be a pixel off: resample to the exact size.
					canvas = document.createElement('canvas');
					canvas.width = pxW;
					canvas.height = pxH;
					const g = canvas.getContext('2d');
					if (!g) throw new Error('The PNG could not be made.');
					g.fillStyle = specBackground(spec);
					g.fillRect(0, 0, pxW, pxH);
					g.drawImage(drawn, 0, 0, pxW, pxH);
				}
				return { bytes: withDpi(await canvasBytes(canvas), dpi), width: pxW, height: pxH };
			},
			dispose
		};
	} catch (e) {
		host.remove();
		throw e;
	}
}

/** The versions of the chart libraries, for the manifest. */
export async function libraryVersions(): Promise<{ vega: string; vegaLite: string; vegaEmbed: string }> {
	const [vega, vl, embed] = await Promise.all([import('vega'), import('vega-lite'), import('vega-embed')]);
	const v = (m: unknown) => {
		const x = (m as { version?: unknown }).version ?? (m as { default?: { version?: unknown } }).default?.version;
		return typeof x === 'string' ? x : 'unknown';
	};
	return { vega: v(vega), vegaLite: v(vl), vegaEmbed: v(embed) };
}
