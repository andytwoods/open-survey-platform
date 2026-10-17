// Chart themes (planning/results-viewer.md V-D7). The app theme follows the design tokens
// (light/dark, read from CSS custom properties); the export theme is for figures: white
// background, the Okabe-Ito qualitative palette, ordered palettes for Likert scales and
// text >= 8 pt at final size. Both take a set of tokens (task V6): the Results page can be
// drawn in a survey theme, whose colours then reach the figures too (`tokensFromTheme`).
// Pure apart from `readTokens`, which reads the DOM.
import { derivePalette, FONT_STACKS, THEME_DEFAULTS, type Mode, type Theme } from '@osp/ui-components';
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
	accent: '#5b3fd1',
	font: "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
};

/** Generic sans stack for exports: no bundled font (V-D7). */
export const EXPORT_FONT = 'Helvetica, Arial, sans-serif';

/** The publication look (V-D7): white, black text, Okabe-Ito blue as the series colour. */
export const EXPORT_TOKENS: ThemeTokens = {
	bg: '#ffffff',
	surface: '#ffffff',
	border: '#d9d9d9',
	borderStrong: '#666666',
	text: '#000000',
	textMuted: '#333333',
	accent: OKABE_ITO[0],
	font: EXPORT_FONT
};

/** The tokens a theme uses when none are given. */
export const defaultTokens = (theme: ChartTheme): ThemeTokens => (theme === 'export' ? EXPORT_TOKENS : LIGHT_TOKENS);

/**
 * Chart tokens from a survey theme in one mode (task V6): the same derived palette the
 * participant page is drawn with, and the theme's font stack.
 */
export function tokensFromTheme(theme: Theme, mode: Mode): ThemeTokens {
	const p = derivePalette(theme.colours[mode]);
	return {
		bg: p.bg,
		surface: p.surface,
		border: p.border,
		borderStrong: p['border-strong'],
		text: p.text,
		textMuted: p['text-muted'],
		accent: p.accent,
		font: FONT_STACKS[theme.font ?? THEME_DEFAULTS.font]
	};
}

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

/** WCAG 2 contrast ratio of two colours (1 when either cannot be parsed). */
export function contrast(a: string, b: string): number {
	if (!rgb(a) || !rgb(b)) return 1;
	const la = luminance(a);
	const lb = luminance(b);
	return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

export interface ChartContrastProblem {
	/** What fails: axis text, hint text, the bars, or the axis line. */
	what: string;
	ratio: number;
	required: number;
}

/** Text on the background needs WCAG AA 4.5:1; bars and axis lines 3:1 (graphical objects). */
const CHART_PAIRS: [keyof ThemeTokens, number, string][] = [
	['text', 4.5, 'axis titles and labels on the background'],
	['textMuted', 4.5, 'axis tick labels on the background'],
	['accent', 3, 'bars and points on the background'],
	['borderStrong', 3, 'axis lines on the background']
];

/**
 * The contrast checks a chart drawn from `tokens` fails (task V6: a results theme is
 * contrast-checked for what the figures actually draw, as the survey guard does for the
 * participant page). Empty when every pair passes.
 */
export function chartContrast(tokens: ThemeTokens): ChartContrastProblem[] {
	const out: ChartContrastProblem[] = [];
	for (const [key, required, what] of CHART_PAIRS) {
		const ratio = contrast(tokens[key], tokens.bg);
		if (ratio < required) out.push({ what, ratio: Math.round(ratio * 100) / 100, required });
	}
	return out;
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

const isDark = (tokens: ThemeTokens) => luminance(tokens.bg) < 0.2;

/**
 * Sequential palette for heatmaps (light → strong), readable on the theme's background.
 * The export one stays blue (a figure convention); the app one follows the violet accent.
 */
export function sequentialPalette(theme: ChartTheme, tokens: ThemeTokens = defaultTokens(theme)): string[] {
	if (isDark(tokens)) return ['#1f1b36', '#3a2f7a', '#5d4bc0', '#9a88ee', '#d9d0ff'];
	if (theme === 'export') return ['#f2f6fb', '#c6dbef', '#6baed6', '#2171b5', '#08306b'];
	return ['#f1edfb', '#d5c9f4', '#a48fe6', '#6a4fd2', '#3a2590'];
}

/** The single-series colour (bars without a split): the tokens' accent (Okabe-Ito blue for exports). */
export function seriesColor(theme: ChartTheme, tokens: ThemeTokens = defaultTokens(theme)): string {
	return tokens.accent;
}

/**
 * Qualitative palette for groups / unordered categories: the accent in place of Okabe-Ito's
 * blue, then the rest (so the publication tokens give Okabe-Ito itself); black swapped for
 * a light grey on dark backgrounds.
 */
export function categoryPalette(theme: ChartTheme, tokens: ThemeTokens = defaultTokens(theme)): string[] {
	const dark = isDark(tokens);
	const accent = tokens.accent.toLowerCase();
	const rest = OKABE_ITO.slice(1)
		.filter((c) => c.toLowerCase() !== accent)
		.map((c) => (dark && c === '#000000' ? '#c8ccd4' : c));
	return [tokens.accent, ...rest];
}

// -- Vega-Lite config -------------------------------------------------------------------

/** The Vega-Lite `config` for a theme drawn from `tokens`. */
export function themeConfig(theme: ChartTheme, tokens: ThemeTokens = defaultTokens(theme)): Config {
	const exp = theme === 'export';
	const t = tokens;
	const size = exp ? EXPORT_TEXT : APP_TEXT;
	return {
		background: exp ? t.bg : 'transparent',
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
export function textColors(theme: ChartTheme, tokens: ThemeTokens = defaultTokens(theme)): { text: string; muted: string; bg: string } {
	return { text: tokens.text, muted: tokens.textMuted, bg: tokens.bg };
}
