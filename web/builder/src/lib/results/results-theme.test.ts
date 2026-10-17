import { THEME_PRESETS, type Theme } from '@osp/ui-components';
import { describe, expect, it } from 'vitest';
import { chartContrast, EXPORT_TOKENS, OKABE_ITO, themeConfig, tokensFromTheme } from './charts/theme';
import { layoutIn, presentIn, withPresent } from './presentation';
import {
	asTheme,
	choiceFromLayout,
	describeExportTheme,
	exportMode,
	parseThemeKey,
	resolveTheme,
	sameChoice,
	screenMode,
	surveyThemeOf,
	themeKey,
	themeProblems,
	themeTokens,
	type LibraryThemeRef
} from './results-theme';

// The Results page's own theme (task V6): resolving a choice against the survey's theme,
// the lab library and the presets; the tokens and contrast checks a theme gives the charts;
// what the manifest says; and the presentation URL flags.

const warm = THEME_PRESETS.find((p) => p.id === 'warm')!.theme;
const dark = THEME_PRESETS.find((p) => p.id === 'dark')!.theme;
const lib: LibraryThemeRef[] = [
	{ id: 'th1', name: 'Lab warm', theme: warm, isDefault: true, diagnostics: [] },
	{ id: 'th2', name: 'Lab dark', theme: dark, isDefault: false, diagnostics: [] }
];
const inputs = { surveyTheme: null, library: lib, labDefaultId: 'th1' };

describe('theme choices', () => {
	it('round-trip through the picker key and the layout reference', () => {
		for (const c of [{ kind: 'app' }, { kind: 'survey' }, { kind: 'preset', id: 'warm' }, { kind: 'library', id: 'th1' }] as const) {
			expect(parseThemeKey(themeKey(c))).toEqual(c);
			expect(choiceFromLayout({ kind: c.kind, id: 'id' in c ? c.id : null })).toEqual(c);
		}
		expect(themeKey({ kind: 'library', id: 'th1' })).toBe('library:th1');
		expect(parseThemeKey('nonsense')).toEqual({ kind: 'app' });
		expect(parseThemeKey('library:not valid')).toEqual({ kind: 'app' });
		expect(parseThemeKey(null)).toEqual({ kind: 'app' });
		expect(choiceFromLayout(null)).toEqual({ kind: 'app' });
		expect(choiceFromLayout({ kind: 'preset' })).toEqual({ kind: 'app' });
		expect(sameChoice({ kind: 'preset', id: 'warm' }, parseThemeKey('preset:warm'))).toBe(true);
		expect(sameChoice({ kind: 'app' }, { kind: 'survey' })).toBe(false);
	});

	it('resolve: app colours, the survey’s theme (own, lab default, Clean), presets and lab themes', () => {
		expect(resolveTheme({ kind: 'app' }, inputs)).toMatchObject({ theme: null, name: 'App colours', notice: null });
		expect(resolveTheme({ kind: 'survey' }, inputs)).toMatchObject({ theme: warm, name: 'This survey’s theme: the lab default “Lab warm”' });
		expect(resolveTheme({ kind: 'survey' }, { ...inputs, surveyTheme: dark })).toMatchObject({ theme: dark, name: 'This survey’s own theme' });
		const clean = resolveTheme({ kind: 'survey' }, { surveyTheme: null, library: [], labDefaultId: null });
		expect(clean.theme?.preset).toBe('clean');
		expect(clean.name).toContain('Clean preset');
		expect(resolveTheme({ kind: 'preset', id: 'warm' }, inputs)).toMatchObject({ theme: warm, name: 'Preset “Warm”' });
		expect(resolveTheme({ kind: 'library', id: 'th2' }, inputs)).toMatchObject({ theme: dark, name: 'Lab theme “Lab dark”' });
	});

	it('a deleted lab theme or unknown preset falls back to the app colours with a notice', () => {
		const gone = resolveTheme({ kind: 'library', id: 'th9' }, inputs);
		expect(gone.theme).toBeNull();
		expect(gone.notice).toContain('no longer in the lab library');
		expect(resolveTheme({ kind: 'preset', id: 'neon' }, inputs).notice).toContain('no “neon” preset');
	});

	it('reads a survey draft’s own theme only when it is a theme document', () => {
		expect(surveyThemeOf({ settings: { theme: warm } })).toEqual(warm);
		expect(surveyThemeOf({ settings: {} })).toBeNull();
		expect(surveyThemeOf(null)).toBeNull();
		expect(asTheme({ colours: { light: { accent: 'red' } } })).toBeNull();
	});
});

describe('theme tokens for charts', () => {
	it('come from the same derived palette as the participant page, in the theme’s mode', () => {
		const t = tokensFromTheme(warm, 'light');
		expect(t).toMatchObject({ bg: '#fdf8f1', surface: '#f5ecdf', text: '#2b2118', textMuted: '#65544a', accent: '#a3431a', borderStrong: '#65544a' });
		expect(t.font).toContain('serif');
		expect(tokensFromTheme(warm, 'dark').bg).toBe('#1c1713');
		expect(themeTokens(null, 'light')).toBeNull();
	});

	it('screen mode follows the theme, or the app when the theme follows the device; exports print light unless dark-only', () => {
		expect(screenMode(warm, 'dark')).toBe('dark'); // auto
		expect(screenMode(warm, 'light')).toBe('light');
		expect(screenMode(dark, 'light')).toBe('dark'); // dark-only
		expect(exportMode(warm)).toBe('light');
		expect(exportMode(dark)).toBe('dark');
	});

	it('the export config takes the theme’s colours: background, text, accent as the series colour', () => {
		const t = tokensFromTheme(warm, 'light');
		const c = themeConfig('export', t) as Record<string, unknown>;
		expect(c.background).toBe('#fdf8f1');
		expect((c.bar as { color: string }).color).toBe('#a3431a');
		expect(((c.range as { category: string[] }).category)[0]).toBe('#a3431a');
		expect((c.axis as { titleColor: string }).titleColor).toBe('#2b2118');
		// Without tokens the publication look is unchanged: white, Okabe-Ito.
		const pub = themeConfig('export') as Record<string, unknown>;
		expect(pub.background).toBe('#ffffff');
		expect((pub.range as { category: string[] }).category).toEqual(OKABE_ITO);
		expect(themeConfig('export', EXPORT_TOKENS)).toEqual(pub);
		// A dark theme swaps Okabe-Ito's black for a light grey.
		const d = themeConfig('export', tokensFromTheme(dark, 'dark')) as Record<string, unknown>;
		expect((d.range as { category: string[] }).category).toContain('#c8ccd4');
		expect((d.range as { category: string[] }).category).not.toContain('#000000');
	});

	it('contrast checks: the presets pass; washed-out colours fail with ratios', () => {
		for (const p of THEME_PRESETS) {
			for (const mode of ['light', 'dark'] as const) expect(themeProblems(p.theme, mode), `${p.id} ${mode}`).toEqual([]);
		}
		expect(themeProblems(null, 'light')).toEqual([]);
		const faint: Theme = { ...warm, colours: { ...warm.colours, light: { ...warm.colours.light, text: '#bbbbbb', accent: '#eeeeee' } } };
		const problems = themeProblems(faint, 'light');
		expect(problems.map((p) => p.what)).toEqual(['axis titles and labels on the background', 'bars and points on the background']);
		expect(problems[0]).toMatchObject({ required: 4.5 });
		expect(problems[0].ratio).toBeLessThan(4.5);
		expect(problems[1]).toMatchObject({ required: 3 });
		expect(chartContrast({ ...EXPORT_TOKENS, borderStrong: '#eeeeee' })[0].what).toContain('axis lines');
	});

	it('names the colours an export used', () => {
		expect(describeExportTheme(resolveTheme({ kind: 'app' }, inputs))).toBe('export (white background, Okabe-Ito palette, text >= 8 pt at final size)');
		expect(describeExportTheme(resolveTheme({ kind: 'library', id: 'th1' }, inputs))).toBe('Lab theme “Lab warm” (light colours; text >= 8 pt at final size)');
		expect(describeExportTheme(resolveTheme({ kind: 'library', id: 'th2' }, inputs))).toContain('dark colours');
	});
});

describe('presentation URL flags', () => {
	it('reads and writes ?present= and reads ?layout=', () => {
		expect(presentIn('')).toBe(false);
		expect(presentIn('?present=1')).toBe(true);
		expect(presentIn('?present')).toBe(true);
		expect(presentIn('?present=0')).toBe(false);
		expect(presentIn('?present=false&layout=x')).toBe(false);
		expect(layoutIn('?layout=lay_1')).toBe('lay_1');
		expect(layoutIn('?layout=not%20ok')).toBeNull();
		expect(layoutIn('?present=1')).toBeNull();
		expect(withPresent('http://h/surveys/1/results', true)).toBe('http://h/surveys/1/results?present=1');
		expect(withPresent('http://h/surveys/1/results?layout=a&present=1#x', false)).toBe('http://h/surveys/1/results?layout=a#x');
		expect(withPresent('http://h/r?present=1', true)).toBe('http://h/r?present=1');
	});
});
