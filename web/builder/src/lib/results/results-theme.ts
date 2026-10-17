/**
 * The Results page's own theme (task V6): which colours the cards and figures are drawn
 * in, chosen independently of the survey. Pure: resolving a choice against the survey's
 * theme, the lab library and the built-in presets, the keys the picker uses, and the words
 * the export manifest records. A saved layout keeps the choice (a reference), never a
 * theme document.
 */
import { resolveMode, THEME_DEFAULTS, THEME_PRESETS, type Mode, type Theme } from '@osp/ui-components';
import { chartContrast, tokensFromTheme, type ChartContrastProblem } from './charts/theme';
import type { ThemeTokens } from './charts/types';

export type ThemeChoice = { kind: 'app' } | { kind: 'survey' } | { kind: 'preset'; id: string } | { kind: 'library'; id: string };

export const APP_THEME: ThemeChoice = { kind: 'app' };

/** A lab library theme as `/api/themes` lists it (the parts the page uses). */
export interface LibraryThemeRef {
	id: string;
	name: string;
	theme: Theme;
	isDefault: boolean;
	diagnostics: { severity: string; code: string; message: string; pointer: string }[];
}

export interface ThemeInputs {
	/** The survey's own theme (`settings.theme`), or null when it follows the lab default. */
	surveyTheme: Theme | null;
	library: readonly LibraryThemeRef[];
	labDefaultId: string | null;
}

export interface ResolvedTheme {
	choice: ThemeChoice;
	/** The theme to draw with, or null for the app's own colours. */
	theme: Theme | null;
	/** What is showing, in words (the picker's note and the manifest). */
	name: string;
	/** Set when the choice could not be honoured (a deleted library theme). */
	notice: string | null;
}

export const THEME_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** The `<select>` value for a choice. */
export function themeKey(choice: ThemeChoice): string {
	return choice.kind === 'preset' || choice.kind === 'library' ? `${choice.kind}:${choice.id}` : choice.kind;
}

/** The choice a `<select>` value (or a saved layout's `theme`) names; the app's colours if unknown. */
export function parseThemeKey(key: string | null | undefined): ThemeChoice {
	if (key === 'survey') return { kind: 'survey' };
	const m = /^(preset|library):(.+)$/.exec(key ?? '');
	if (m && THEME_ID.test(m[2])) return { kind: m[1] as 'preset' | 'library', id: m[2] };
	return APP_THEME;
}

/** A layout's `theme` part as a choice (defaults for anything missing or wrong). */
export function choiceFromLayout(t: { kind?: string | null; id?: string | null } | null | undefined): ThemeChoice {
	if (!t) return APP_THEME;
	if (t.kind === 'survey') return { kind: 'survey' };
	if ((t.kind === 'preset' || t.kind === 'library') && typeof t.id === 'string' && THEME_ID.test(t.id)) return { kind: t.kind, id: t.id };
	return APP_THEME;
}

export function sameChoice(a: ThemeChoice, b: ThemeChoice): boolean {
	return themeKey(a) === themeKey(b);
}

/** A theme document, if `value` looks like one (a survey's `settings.theme`). */
export function asTheme(value: unknown): Theme | null {
	const t = value as { colours?: { light?: Record<string, unknown>; dark?: Record<string, unknown> } } | null | undefined;
	if (!t || typeof t !== 'object' || !t.colours?.light || !t.colours?.dark) return null;
	const hex = (p: Record<string, unknown>) => ['accent', 'background', 'surface', 'text', 'muted', 'error', 'focus'].every((k) => typeof p[k] === 'string' && /^#[0-9a-fA-F]{6}$/.test(p[k] as string));
	return hex(t.colours.light) && hex(t.colours.dark) ? (t as Theme) : null;
}

/** The survey draft's own theme, or null (it follows the lab default). */
export function surveyThemeOf(survey: unknown): Theme | null {
	return asTheme((survey as { settings?: { theme?: unknown } } | null | undefined)?.settings?.theme);
}

const CLEAN = THEME_PRESETS.find((p) => p.id === 'clean')!;

/** Resolve a choice to the theme to draw with (or null for the app's colours). */
export function resolveTheme(choice: ThemeChoice, inputs: ThemeInputs): ResolvedTheme {
	switch (choice.kind) {
		case 'app':
			return { choice, theme: null, name: 'App colours', notice: null };
		case 'survey': {
			if (inputs.surveyTheme) return { choice, theme: inputs.surveyTheme, name: 'This survey’s own theme', notice: null };
			const def = inputs.library.find((t) => t.id === inputs.labDefaultId);
			if (def) return { choice, theme: def.theme, name: `This survey’s theme: the lab default “${def.name}”`, notice: null };
			return { choice, theme: CLEAN.theme, name: 'This survey’s theme: the Clean preset (the lab has no default theme)', notice: null };
		}
		case 'preset': {
			const p = THEME_PRESETS.find((x) => x.id === choice.id);
			if (p) return { choice, theme: p.theme, name: `Preset “${p.name}”`, notice: null };
			return { choice, theme: null, name: 'App colours', notice: `There is no “${choice.id}” preset, so the cards use the app’s colours.` };
		}
		case 'library': {
			const t = inputs.library.find((x) => x.id === choice.id);
			if (t) return { choice, theme: t.theme, name: `Lab theme “${t.name}”`, notice: null };
			return { choice, theme: null, name: 'App colours', notice: 'The layout’s theme is no longer in the lab library, so the cards use the app’s colours.' };
		}
	}
}

/** The mode the page shows a theme in: the theme's own, or the app's when it follows the device. */
export function screenMode(theme: Theme, appMode: Mode): Mode {
	return resolveMode(theme, appMode === 'dark');
}

/** Figures are exported in the light palette unless the theme is dark-only (print first). */
export function exportMode(theme: Theme): Mode {
	return (theme.mode ?? THEME_DEFAULTS.mode) === 'dark' ? 'dark' : 'light';
}

/** Chart tokens for a theme in a mode, or null for the app's colours. */
export function themeTokens(theme: Theme | null, mode: Mode): ThemeTokens | null {
	return theme ? tokensFromTheme(theme, mode) : null;
}

/** The chart contrast checks a theme fails in a mode (empty for the app's colours). */
export function themeProblems(theme: Theme | null, mode: Mode): ChartContrastProblem[] {
	return theme ? chartContrast(tokensFromTheme(theme, mode)) : [];
}

/** The theme line of an export manifest (V-D6). */
export function describeExportTheme(resolved: ResolvedTheme): string {
	if (!resolved.theme) return 'export (white background, Okabe-Ito palette, text >= 8 pt at final size)';
	return `${resolved.name} (${exportMode(resolved.theme)} colours; text >= 8 pt at final size)`;
}
