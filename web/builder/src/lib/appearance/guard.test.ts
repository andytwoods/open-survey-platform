/**
 * The TS guard and the import validator agree with Python (osp_spec.theme) on the golden
 * outputs in generated/guard.golden.json (regenerate: see generate_golden.py), and the
 * schema copy here is the one R8 commits in ui-components.
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { PALETTE_FIELDS, THEME_PRESETS, type Palette, type Theme } from '@osp/ui-components';
import { describe, expect, it } from 'vitest';
import { checkTheme, hexToOklch, oklchToHex, suggestColour, type ThemeDiagnostic } from './guard';
import { parseThemeJson, validateThemeValue } from './validate';

const here = dirname(fileURLToPath(import.meta.url));
const read = (p: string) => readFileSync(resolve(here, p), 'utf8');
const golden = JSON.parse(read('generated/guard.golden.json')) as {
	guard: { name: string; theme: Theme; diagnostics: ThemeDiagnostic[] }[];
	suggestions: { palette: Palette; suggestions: Record<string, string | null> }[];
	validation: { name: string; input: unknown; valid: boolean }[];
};

describe('schema copy', () => {
	it('matches the schema committed in ui-components', () => {
		const ours = JSON.parse(read('generated/theme.schema.json'));
		const theirs = JSON.parse(read('../../../../ui-components/src/theme/generated/theme.schema.json'));
		expect(ours, 'stale: regenerate with generate_golden.py').toEqual(theirs);
	});
});

describe('guard parity with Python', () => {
	it('has a meaningful golden set', () => {
		expect(golden.guard.length).toBeGreaterThan(40);
		expect(golden.guard.filter((c) => c.diagnostics.length > 0).length).toBeGreaterThan(20);
	});

	for (const c of golden.guard) {
		it(`check_theme: ${c.name}`, () => {
			expect(checkTheme(c.theme)).toEqual(c.diagnostics);
		});
	}

	it('suggest_colour gives the same hex for every field of 30 random palettes', () => {
		for (const c of golden.suggestions) {
			for (const field of PALETTE_FIELDS) {
				expect(suggestColour(c.palette, field), `${field} of ${JSON.stringify(c.palette)}`).toBe(
					c.suggestions[field]
				);
			}
		}
	});

	it('every preset passes in every mode it shows', () => {
		for (const p of THEME_PRESETS) expect(checkTheme(p.theme)).toEqual([]);
	});

	it('a suggestion actually fixes its pairs', () => {
		const theme = structuredClone(THEME_PRESETS[0].theme);
		theme.colours.light.accent = '#66aaff';
		const [d] = checkTheme(theme);
		expect(d.pointer).toBe('/colours/light/accent');
		theme.colours.light.accent = d.suggestion as string;
		expect(checkTheme(theme)).toEqual([]);
	});

	it('OKLCH round-trips sRGB hex', () => {
		for (const hex of ['#000000', '#ffffff', '#2456c7', '#ff8a80', '#7f7f7f']) {
			expect(oklchToHex(...hexToOklch(hex))).toBe(hex);
		}
	});
});

describe('JSON import validation', () => {
	for (const c of golden.validation) {
		it(`${c.name} is ${c.valid ? 'accepted' : 'rejected'} (as by pydantic)`, () => {
			const { theme, problems } = validateThemeValue(c.input);
			expect(theme !== null, JSON.stringify(problems)).toBe(c.valid);
			expect(problems.length === 0).toBe(c.valid);
		});
	}

	it('rejects text that is not JSON, with a problem instead of an exception', () => {
		const { theme, problems } = parseThemeJson('{not json');
		expect(theme).toBeNull();
		expect(problems[0].message).toMatch(/Not valid JSON/);
	});

	it('points at the offending field', () => {
		const t = structuredClone(THEME_PRESETS[0].theme) as Record<string, unknown>;
		(t.colours as Record<string, Record<string, string>>).dark.accent = 'blue';
		t.radius = 99;
		t.css = 'body{}';
		const { problems } = validateThemeValue(t);
		expect(problems.map((p) => p.pointer).sort()).toEqual(
			['/colours/dark/accent', '/css', '/radius'].sort()
		);
	});
});
