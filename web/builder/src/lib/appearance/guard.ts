/**
 * The theme contrast guard, client-side: a line-for-line port of osp_spec.theme's
 * check_theme / suggest_colour, so the editor can warn as you type. The Python guard stays
 * the authority (publishing will run it server-side); guard.test.ts proves this port gives
 * identical diagnostics on R8's presets and ~50 generated themes (generated/guard.golden.json).
 *
 * Pure presentation support: this checks colours, it knows nothing about surveys.
 */
import {
	THEME_DEFAULTS,
	contrastRatio,
	derivePalette,
	type DerivedToken,
	type HexColour,
	type Mode,
	type Palette,
	type PaletteField,
	type Theme
} from '@osp/ui-components';

export const MIN_INPUT_FONT_PX = 16;
export const TEXT_RATIO = 4.5;
export const UI_RATIO = 3.0;
export const FOCUS_RATIO = 3.0;

export interface ThemeDiagnostic {
	severity: 'error' | 'warning';
	code: 'theme.contrast' | 'theme.input_font_size' | 'theme.schema';
	message: string;
	/** RFC 6901 pointer into the theme document. */
	pointer: string;
	ratio: number | null;
	required: number | null;
	/** Nearest passing value for `pointer`. */
	suggestion: string | number | null;
}

// --- OKLCH (the parts of the colour maths the bridge does not export) ------------------

type Triple = [number, number, number];

const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const fromLinear = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

function hexToRgb(hex: HexColour): Triple {
	const h = hex.replace(/^#/, '');
	return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as Triple;
}

function rgbToHex(rgb: Triple): HexColour {
	return (
		'#' +
		rgb
			.map((c) =>
				Math.floor(Math.min(1, Math.max(0, c)) * 255 + 0.5)
					.toString(16)
					.padStart(2, '0')
			)
			.join('')
	);
}

function rgbToOklab(rgb: Triple): Triple {
	const [r, g, b] = rgb.map(toLinear);
	const lc = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
	const mc = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
	const sc = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
	return [
		0.2104542553 * lc + 0.793617785 * mc - 0.0040720468 * sc,
		1.9779984951 * lc - 2.428592205 * mc + 0.4505937099 * sc,
		0.0259040371 * lc + 0.7827717662 * mc - 0.808675766 * sc
	];
}

function oklabToLinear([L, a, b]: Triple): Triple {
	const lc = L + 0.3963377774 * a + 0.2158037573 * b;
	const mc = L - 0.1055613458 * a - 0.0638541728 * b;
	const sc = L - 0.0894841775 * a - 1.291485548 * b;
	const [l3, m3, s3] = [lc ** 3, mc ** 3, sc ** 3];
	return [
		4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
		-1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
		-0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3
	];
}

export function hexToOklch(hex: HexColour): Triple {
	const [L, a, b] = rgbToOklab(hexToRgb(hex));
	return [L, Math.hypot(a, b), Math.atan2(b, a)];
}

/** OKLCH to sRGB hex, gamut-mapped by reducing chroma (then clipped). */
export function oklchToHex(L: number, C: number, h: number): HexColour {
	const inGamut = (c: number) =>
		oklabToLinear([L, c * Math.cos(h), c * Math.sin(h)]).every((x) => x >= -1e-6 && x <= 1 + 1e-6);
	if (!inGamut(C)) {
		let lo = 0;
		let hi = C;
		for (let i = 0; i < 24; i++) {
			const mid = (lo + hi) / 2;
			if (inGamut(mid)) lo = mid;
			else hi = mid;
		}
		C = lo;
	}
	return rgbToHex(oklabToLinear([L, C * Math.cos(h), C * Math.sin(h)]).map(fromLinear) as Triple);
}

// --- Pairs ------------------------------------------------------------------------------

export interface ContrastPair {
	fg: DerivedToken;
	bg: DerivedToken;
	required: number;
	what: string;
	/** The theme colour to change when the pair fails. */
	adjust: PaletteField;
}

const BACKDROPS = ['bg', 'surface', 'surface-sunken', 'accent-subtle', 'selected'] as const;
const pair = (
	fg: DerivedToken,
	bg: DerivedToken,
	required: number,
	what: string,
	adjust: PaletteField
): ContrastPair => ({ fg, bg, required, what, adjust });

/** Every pair the participant page draws (same order as osp_spec.theme.PAIRS). */
export const PAIRS: readonly ContrastPair[] = [
	...BACKDROPS.map((b) => pair('text', b, TEXT_RATIO, 'body text', 'text')),
	...BACKDROPS.map((b) => pair('text-muted', b, TEXT_RATIO, 'hint text', 'muted')),
	pair('border-strong', 'surface-raised', UI_RATIO, 'control border', 'muted'),
	pair('accent', 'bg', TEXT_RATIO, 'link text / filled button label', 'accent'),
	pair('accent', 'surface', TEXT_RATIO, 'link text on a card', 'accent'),
	pair('accent', 'selected', UI_RATIO, 'selected choice border', 'accent'),
	pair('accent', 'accent-subtle', TEXT_RATIO, 'outline button label on hover', 'accent'),
	pair('on-accent', 'accent-hover', TEXT_RATIO, 'button label on hover', 'accent'),
	pair('danger', 'bg', TEXT_RATIO, 'error message', 'error'),
	pair('danger', 'surface', TEXT_RATIO, 'error message on a card', 'error'),
	...BACKDROPS.map((b) => pair('focus', b, FOCUS_RATIO, 'focus indicator', 'focus'))
];

function passes(palette: Palette, field: PaletteField): boolean {
	const tokens = derivePalette(palette);
	return PAIRS.every(
		(p) => p.adjust !== field || contrastRatio(tokens[p.fg], tokens[p.bg]) >= p.required
	);
}

/**
 * Nearest colour for `field` (same OKLCH chroma and hue, lightness moved as little as
 * possible) with which every pair adjusted by this field passes. Null if none does.
 */
export function suggestColour(palette: Palette, field: PaletteField): HexColour | null {
	const [L, C, h] = hexToOklch(palette[field]);
	let best: [number, HexColour] | null = null;
	for (const direction of [-1, 1]) {
		const step = 0.0025;
		let lightness = L;
		while (lightness >= 0 && lightness <= 1) {
			lightness += direction * step;
			const candidate = oklchToHex(Math.min(1, Math.max(0, lightness)), C, h);
			if (passes({ ...palette, [field]: candidate }, field)) {
				const delta = Math.abs(lightness - L);
				if (best === null || delta < best[0]) best = [delta, candidate];
				break;
			}
		}
	}
	return best ? best[1] : null;
}

/** The modes a theme can show: `auto` shows both. */
export function modesOf(theme: Theme): Mode[] {
	const mode = theme.mode ?? THEME_DEFAULTS.mode;
	return mode === 'auto' ? ['light', 'dark'] : [mode];
}

// Python formats floats with repr-like `{x}` (4.5, 3.0) and `{x:.2f}`.
const pyFloat = (x: number) => (Number.isInteger(x) ? x.toFixed(1) : String(x));

/**
 * Guard a theme: WCAG AA contrast for every pair used, in every mode the theme can show,
 * and the 16 px minimum input font size. Pure; never throws on a schema-valid theme.
 */
export function checkTheme(theme: Theme, modes: readonly Mode[] = modesOf(theme)): ThemeDiagnostic[] {
	const out: ThemeDiagnostic[] = [];
	const baseSize = theme.baseSize ?? THEME_DEFAULTS.baseSize;
	if (baseSize < MIN_INPUT_FONT_PX) {
		out.push({
			severity: 'error',
			code: 'theme.input_font_size',
			message:
				`Base size ${baseSize}px is below ${MIN_INPUT_FONT_PX}px; text inputs ` +
				'would trigger auto-zoom on iOS.',
			pointer: '/baseSize',
			ratio: null,
			required: null,
			suggestion: MIN_INPUT_FONT_PX
		});
	}
	for (const mode of modes) {
		const palette = theme.colours[mode];
		const tokens = derivePalette(palette);
		const suggestions = new Map<PaletteField, HexColour | null>();
		for (const { fg, bg, required, what, adjust } of PAIRS) {
			const ratio = contrastRatio(tokens[fg], tokens[bg]);
			if (ratio >= required) continue;
			if (!suggestions.has(adjust)) suggestions.set(adjust, suggestColour(palette, adjust));
			out.push({
				severity: 'error',
				code: 'theme.contrast',
				message:
					`${mode}: ${what} (${fg} ${tokens[fg]} on ${bg} ${tokens[bg]}) has contrast ` +
					`${ratio.toFixed(2)}:1; WCAG AA needs ${pyFloat(required)}:1.`,
				pointer: `/colours/${mode}/${adjust}`,
				ratio: Math.round(ratio * 100) / 100,
				required,
				suggestion: suggestions.get(adjust) ?? null
			});
		}
	}
	return out;
}

/** Diagnostics grouped by pointer, for showing each one next to its control. */
export function byPointer(diags: readonly ThemeDiagnostic[]): Map<string, ThemeDiagnostic[]> {
	const out = new Map<string, ThemeDiagnostic[]>();
	for (const d of diags) out.set(d.pointer, [...(out.get(d.pointer) ?? []), d]);
	return out;
}
