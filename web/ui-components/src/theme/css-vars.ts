/**
 * Tokens bridge: a Theme becomes CSS custom properties with W1's token names
 * (tokens.css), so every component already drawn from tokens picks the theme up.
 * Apply them to the survey container, not :root: the builder keeps its own tokens.
 *
 * Accessibility floors (runtime-design §6) are applied here regardless of the theme:
 * inputs never below 16px, controls never below a 44px touch target.
 */
import { derivePalette } from './colour';
import { THEME_DEFAULTS, type FontId, type Mode, type Theme } from './types';

export const FONT_STACKS: Record<FontId, string> = {
	'system-sans':
		"system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif",
	'system-serif':
		"ui-serif, 'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, 'Noto Serif', serif",
	'system-rounded':
		"ui-rounded, 'SF Pro Rounded', 'Hiragino Maru Gothic ProN', 'Arial Rounded MT Bold', system-ui, sans-serif"
};

// W1's type scale as multiples of the base size.
const TYPE_SCALE = { xs: 0.75, sm: 0.875, md: 1, lg: 1.125, xl: 1.375 } as const;
// W1's spacing scale in rem; compact density shrinks it.
const SPACE = { 1: 0.25, 2: 0.5, 3: 0.75, 4: 1, 5: 1.5, 6: 2, 8: 3 } as const;
const COMPACT = 0.75;

const rem = (n: number) => `${+n.toFixed(4)}rem`;

/** Which theme mode to show when the theme's mode is `auto`. */
export function resolveMode(theme: Theme, prefersDark: boolean): Mode {
	const mode = theme.mode ?? THEME_DEFAULTS.mode;
	return mode === 'auto' ? (prefersDark ? 'dark' : 'light') : mode;
}

/**
 * CSS custom properties (plus `color-scheme`) for one mode of a theme, keyed by property
 * name. Usable directly as an inline style object or with {@link cssVarsToStyle}.
 */
export function themeToCssVars(theme: Theme, mode: Mode): Record<string, string> {
	const t = { ...THEME_DEFAULTS, ...theme };
	const base = t.baseSize / 16; // rem, so participants' own text enlargement still scales
	const density = t.density === 'compact' ? COMPACT : 1;
	const vars: Record<string, string> = { 'color-scheme': mode };

	for (const [token, hex] of Object.entries(derivePalette(theme.colours[mode]))) {
		vars[`--color-${token}`] = hex;
	}
	vars['--font-sans'] = FONT_STACKS[t.font];
	for (const [step, ratio] of Object.entries(TYPE_SCALE)) {
		vars[`--text-${step}`] = rem(base * ratio);
	}
	vars['--leading-normal'] = String(t.lineSpacing);
	vars['--leading-tight'] = String(Math.min(1.25, t.lineSpacing));
	vars['--radius-sm'] = `${Math.round(t.radius * 0.67)}px`;
	vars['--radius-md'] = `${t.radius}px`;
	vars['--radius-lg'] = `${Math.round(t.radius * 1.67)}px`;
	for (const [step, size] of Object.entries(SPACE)) {
		vars[`--space-${step}`] = rem(size * density);
	}
	// Participant controls: >= 44px touch targets (2.75rem) even when compact.
	vars['--control-height'] = t.density === 'compact' ? '2.75rem' : '3rem';
	// Survey-only tokens (not in W1's builder set).
	vars['--osp-input-font-size'] = `max(1rem, ${rem(base)})`;
	vars['--osp-touch-target'] = '2.75rem';
	return vars;
}

/** Non-token choices the participant page styles by attribute. */
export function themeDataAttributes(theme: Theme): Record<string, string> {
	const t = { ...THEME_DEFAULTS, ...theme };
	return {
		'data-osp-density': t.density,
		'data-osp-button': t.buttonStyle,
		'data-osp-choice': t.choiceStyle
	};
}

/** `name: value; …` for a `style` attribute. */
export function cssVarsToStyle(vars: Record<string, string>): string {
	return Object.entries(vars)
		.map(([k, v]) => `${k}: ${v}`)
		.join('; ');
}

/**
 * A stylesheet for `selector`: the light (or only) mode, plus the dark mode under
 * `prefers-color-scheme` when the theme follows the device.
 */
export function themeToCss(theme: Theme, selector: string): string {
	const block = (mode: Mode) =>
		`${selector} {\n${Object.entries(themeToCssVars(theme, mode))
			.map(([k, v]) => `\t${k}: ${v};`)
			.join('\n')}\n}`;
	const mode = theme.mode ?? THEME_DEFAULTS.mode;
	if (mode !== 'auto') return block(mode) + '\n';
	return `${block('light')}\n@media (prefers-color-scheme: dark) {\n${block('dark')}\n}\n`;
}
