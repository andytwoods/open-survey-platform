// Chart themes (planning/results-viewer.md V-D7). The app theme follows the design tokens
// (light/dark, read from CSS custom properties); the export theme is for figures: white
// background, the Okabe-Ito qualitative palette, ordered palettes for Likert scales and
// text >= 8 pt at final size. Pure apart from `readTokens`, which reads the DOM.
import type { Config } from 'vega-lite';
import type { ChartTheme, ThemeTokens } from './types';

/** Okabe & Ito (2008) colour-blind-safe qualitative palette, blue first, yellow late. */
export const OKABE_ITO = ['#0072B2', '#E69F00', '#009E73', '#D55E00', '#CC79A7', '#56B4E9', '#F0E442', '#000000'];

/** tokens.css, light (the fallback when there is no DOM). */
export const LIGHT_TOKENS: ThemeTokens = {
	bg: '#ffffff',
	surface: '#f6f7f9',
	border: '#d5dae1',
	borderStrong: '#7b8494',
	text: '#1d2433',
	textMuted: '#505a6b',
	accent: '#2456c7',
	font: "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
};

/** Generic sans stack for exports: no bundled font (V-D7). */
export const EXPORT_FONT = 'Helvetica, Arial, sans-serif';

/**
 * Export text sizes in px, for a figure rendered at its final width at 96 px/in:
 * 8 pt = 10.7 px, so nothing is smaller than 11 px.
 */
export const EXPORT_TEXT = { label: 11, title: 12, legend: 11, mark: 11 } as const;
const APP_TEXT = { label: 12, title: 12, legend: 12, mark: 12 } as const;

const TOKEN_VARS: Record<keyof ThemeTokens, string> = {
	bg: '--color-bg',
	surface: '--color-surface',
	border: '--color-border',
	borderStrong: '--color-border-strong',
	text: '--color-text',
	textMuted: '--color-text-muted',
	accent: '--color-accent',
	font: '--font-sans'
};

/** The app tokens as currently computed on `el` (default <html>): light or dark. */
export function readTokens(el?: Element): ThemeTokens {
	const target = el ?? globalThis.document?.documentElement;
	if (!target || typeof getComputedStyle !== 'function') return { ...LIGHT_TOKENS };
	const css = getComputedStyle(target);
	const out = { ...LIGHT_TOKENS };
	for (const [k, v] of Object.entries(TOKEN_VARS) as [keyof ThemeTokens, string][]) {
		const value = css.getPropertyValue(v).trim();
		if (value) out[k] = value;
	}
	return out;
}

// -- colour helpers ---------------------------------------------------------------------

/** #rgb, #rrggbb or rgb()/rgba() (the build minifies token colours, e.g. #ffffff → #fff). */
function rgb(color: string): [number, number, number] | null {
	const s = color.trim();
	const short = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(s);
	if (short) return [short[1], short[2], short[3]].map((c) => parseInt(c + c, 16)) as [number, number, number];
	const m = /^#([0-9a-f]{6})$/i.exec(s);
	if (m) {
		const n = parseInt(m[1], 16);
		return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
	}
	const f = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec(s);
	return f ? [Number(f[1]), Number(f[2]), Number(f[3])] : null;
}

function hex([r, g, b]: [number, number, number]): string {
	return '#' + [r, g, b].map((c) => Math.round(c).toString(16).padStart(2, '0')).join('');
}

function mix(a: string, b: string, t: number): string {
	const x = rgb(a) ?? [0, 0, 0];
	const y = rgb(b) ?? [0, 0, 0];
	return hex([x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t]);
}

/** WCAG relative luminance of a #rrggbb colour (0 for anything else). */
export function luminance(color: string): number {
	const c = rgb(color);
	if (!c) return 0;
	const [r, g, b] = c.map((v) => {
		const s = v / 255;
		return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Dark or white text, whichever reads better on `fill`. */
export function inkOn(fill: string): string {
	return luminance(fill) > 0.18 ? '#1d2433' : '#ffffff';
}

// -- ordered palettes -------------------------------------------------------------------

/** Diverging ends (orange ↔ blue, colour-blind safe) and the neutral middle, per theme. */
const LIKERT = {
	export: { negStrong: '#a34a00', negLight: '#f3c79b', neutral: '#d4d4d4', posLight: '#a9c4e6', posStrong: '#0b4c8c' },
	app: { negStrong: '#b05a10', negLight: '#efc292', neutral: '#b9bec7', posLight: '#a3bfe6', posStrong: '#1f55a6' }
} as const;

/**
 * `k` ordered colours for a Likert scale, negative to positive. An odd `k` has a grey
 * neutral middle; the ends are the strongest. Text drawn on them uses `inkOn`.
 */
export function likertPalette(k: number, theme: ChartTheme = 'export'): string[] {
	if (k <= 0) return [];
	const p = LIKERT[theme];
	if (k === 1) return [p.neutral];
	const half = Math.floor(k / 2);
	const side = (strong: string, light: string) =>
		Array.from({ length: half }, (_, i) => (half === 1 ? mix(strong, light, 0.5) : mix(strong, light, i / (half - 1))));
	const neg = side(p.negStrong, p.negLight);
	const pos = side(p.posStrong, p.posLight).reverse();
	return k % 2 ? [...neg, p.neutral, ...pos] : [...neg, ...pos];
}

/** Sequential palette for heatmaps (light → strong), readable on the theme's background. */
export function sequentialPalette(theme: ChartTheme, tokens: ThemeTokens = LIGHT_TOKENS): string[] {
	if (theme === 'export') return ['#f2f6fb', '#c6dbef', '#6baed6', '#2171b5', '#08306b'];
	const dark = luminance(tokens.bg) < 0.2;
	return dark ? ['#1d2433', '#24406e', '#2f63b0', '#6b9be6', '#c9dbff'] : ['#eef3fb', '#c4d5f2', '#7d9fe0', '#2f63c4', '#123a8a'];
}

/** The single-series colour (bars without a split). */
export function seriesColor(theme: ChartTheme, tokens: ThemeTokens = LIGHT_TOKENS): string {
	return theme === 'export' ? OKABE_ITO[0] : tokens.accent;
}

/** Qualitative palette for groups / unordered categories. */
export function categoryPalette(theme: ChartTheme, tokens: ThemeTokens = LIGHT_TOKENS): string[] {
	if (theme === 'export') return OKABE_ITO;
	const dark = luminance(tokens.bg) < 0.2;
	// Okabe-Ito with the accent first; black swapped for a light grey on dark backgrounds.
	const rest = OKABE_ITO.slice(1).map((c) => (dark && c === '#000000' ? '#c8ccd4' : c));
	return [tokens.accent, ...rest];
}

// -- Vega-Lite config -------------------------------------------------------------------

/** The Vega-Lite `config` for a theme. */
export function themeConfig(theme: ChartTheme, tokens: ThemeTokens = LIGHT_TOKENS): Config {
	const exp = theme === 'export';
	const t = exp
		? { ...LIGHT_TOKENS, bg: '#ffffff', text: '#000000', textMuted: '#333333', border: '#d9d9d9', borderStrong: '#666666', font: EXPORT_FONT }
		: tokens;
	const size = exp ? EXPORT_TEXT : APP_TEXT;
	return {
		background: exp ? '#ffffff' : 'transparent',
		font: t.font,
		padding: 8,
		view: { stroke: null },
		axis: {
			labelColor: t.textMuted,
			titleColor: t.text,
			domainColor: t.borderStrong,
			tickColor: t.borderStrong,
			gridColor: t.border,
			labelFontSize: size.label,
			titleFontSize: size.title,
			titleFontWeight: 600,
			labelLimit: 220
		},
		axisBand: { grid: false, ticks: false, domain: false },
		legend: {
			labelColor: t.text,
			titleColor: t.text,
			labelFontSize: size.legend,
			titleFontSize: size.legend,
			orient: 'top',
			direction: 'horizontal',
			symbolType: 'square',
			labelLimit: 170,
			columns: 2
		},
		header: { labelColor: t.text, titleColor: t.text, labelFontSize: size.title, labelFontWeight: 600, labelAnchor: 'start', labelAngle: 0, labelOrient: 'top', title: null },
		title: { color: t.text, subtitleColor: t.textMuted, fontSize: size.title + 1, anchor: 'start' },
		text: { color: t.text, fontSize: size.mark },
		bar: { color: seriesColor(theme, tokens) },
		point: { color: seriesColor(theme, tokens), filled: true },
		line: { color: seriesColor(theme, tokens) },
		rule: { color: t.textMuted },
		tick: { color: t.text },
		range: {
			category: categoryPalette(theme, tokens),
			heatmap: sequentialPalette(theme, tokens)
		}
	};
}

/** Text colours the builders need for direct labels and the neutral line. */
export function textColors(theme: ChartTheme, tokens: ThemeTokens = LIGHT_TOKENS): { text: string; muted: string; bg: string } {
	return theme === 'export' ? { text: '#000000', muted: '#333333', bg: '#ffffff' } : { text: tokens.text, muted: tokens.textMuted, bg: tokens.bg };
}
