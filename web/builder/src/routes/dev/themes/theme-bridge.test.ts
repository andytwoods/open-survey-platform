/**
 * The theme bridge in @osp/ui-components/src/theme:
 * - the hand-written TS types match the JSON Schema exported by osp_spec.theme;
 * - derivePalette gives the same hex as Python (golden file), so what the guard checked is
 *   what the page draws;
 * - themeToCssVars only sets token names that exist in W1's tokens.css (plus --osp-*);
 * - accessibility floors hold whatever the theme says.
 * Generated files are read as text, so the boundary rules are unaffected.
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
	BUTTON_STYLES,
	CHOICE_STYLES,
	DENSITIES,
	FONT_IDS,
	PALETTE_FIELDS,
	PRESET_IDS,
	THEME_DEFAULTS,
	THEME_FIELDS,
	THEME_MODES,
	THEME_PRESETS,
	THEME_VERSION,
	contrastRatio,
	derivePalette,
	themeToCss,
	themeToCssVars,
	type Palette,
	type Theme
} from '@osp/ui-components';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const uiSrc = resolve(here, '../../../../../ui-components/src');
const read = (p: string) => readFileSync(resolve(uiSrc, p), 'utf8');
const schema = JSON.parse(read('theme/generated/theme.schema.json'));
const golden = JSON.parse(read('theme/generated/palettes.golden.json'));
const tokensCss = read('tokens.css');

type JsonSchema = {
	enum?: unknown[];
	const?: unknown;
	anyOf?: JsonSchema[];
	$ref?: string;
	default?: unknown;
};

/** The enum values of a property, following one $ref / anyOf level. */
function enumOf(prop: JsonSchema): unknown[] {
	const values: unknown[] = [];
	for (const p of prop.anyOf ?? [prop]) {
		const target: JsonSchema = p.$ref ? schema.$defs[p.$ref.split('/').pop()!] : p;
		if (target.enum) values.push(...target.enum);
		if (target.const !== undefined) values.push(target.const);
	}
	return values;
}

describe('Theme types match the JSON Schema', () => {
	const props = schema.properties as Record<string, JsonSchema>;

	it('has the same fields and required fields', () => {
		expect(Object.keys(props).sort()).toEqual([...THEME_FIELDS].sort());
		expect(schema.required).toEqual(['colours']);
		expect(schema.additionalProperties).toBe(false);
		expect(Object.keys(schema.$defs.Palette.properties).sort()).toEqual(
			[...PALETTE_FIELDS].sort()
		);
		expect([...schema.$defs.Palette.required].sort()).toEqual([...PALETTE_FIELDS].sort());
		expect([...schema.$defs.Colours.required].sort()).toEqual(['dark', 'light']);
	});

	it('has the same enum values', () => {
		expect(enumOf(props.themeVersion)).toEqual([THEME_VERSION]);
		expect(enumOf(props.preset)).toEqual([...PRESET_IDS]);
		expect(enumOf(props.font)).toEqual([...FONT_IDS]);
		expect(enumOf(props.density)).toEqual([...DENSITIES]);
		expect(enumOf(props.buttonStyle)).toEqual([...BUTTON_STYLES]);
		expect(enumOf(props.choiceStyle)).toEqual([...CHOICE_STYLES]);
		expect(enumOf(props.mode)).toEqual([...THEME_MODES]);
	});

	it('has the same defaults', () => {
		for (const [key, value] of Object.entries(THEME_DEFAULTS)) {
			expect(props[key].default, key).toEqual(value);
		}
	});

	it('has the five presets in order', () => {
		expect(THEME_PRESETS.map((p) => p.id)).toEqual([...PRESET_IDS]);
	});
});

describe('derivePalette matches Python', () => {
	for (const preset of THEME_PRESETS) {
		for (const mode of ['light', 'dark'] as const) {
			it(`${preset.id} ${mode}`, () => {
				expect(derivePalette(preset.theme.colours[mode])).toEqual(
					golden.presets[preset.id][mode]
				);
			});
		}
	}
	const cross = golden.crossCheck as Record<
		string,
		{ input: Palette; tokens: Record<string, string> }
	>;
	for (const [name, entry] of Object.entries(cross)) {
		it(`cross-check: ${name}`, () => {
			expect(derivePalette(entry.input)).toEqual(entry.tokens);
		});
	}
});

describe('themeToCssVars', () => {
	const w1Vars = new Set([...tokensCss.matchAll(/(--[\w-]+):/g)].map((m) => m[1]));
	const clean = THEME_PRESETS[0].theme;

	it('maps onto existing W1 token names (survey-only extras are --osp-*)', () => {
		for (const preset of THEME_PRESETS) {
			for (const name of Object.keys(themeToCssVars(preset.theme, 'light'))) {
				if (name === 'color-scheme' || name.startsWith('--osp-')) continue;
				expect(w1Vars.has(name), name).toBe(true);
			}
		}
	});

	it('uses the mode-specific palette', () => {
		expect(themeToCssVars(clean, 'light')['--color-bg']).toBe('#ffffff');
		expect(themeToCssVars(clean, 'dark')['--color-bg']).toBe('#12151b');
		expect(themeToCssVars(clean, 'dark')['color-scheme']).toBe('dark');
	});

	it('keeps the 16px input and 44px touch-target floors', () => {
		const tiny: Theme = { ...clean, baseSize: 12, density: 'compact' };
		const vars = themeToCssVars(tiny, 'light');
		expect(vars['--osp-input-font-size']).toBe('max(1rem, 0.75rem)');
		expect(vars['--control-height']).toBe('2.75rem');
		expect(themeToCssVars({ ...clean, baseSize: 20 }, 'light')['--text-md']).toBe('1.25rem');
	});

	it('compact density shrinks spacing', () => {
		expect(themeToCssVars(clean, 'light')['--space-4']).toBe('1rem');
		expect(themeToCssVars({ ...clean, density: 'compact' }, 'light')['--space-4']).toBe(
			'0.75rem'
		);
	});

	it('themeToCss adds a dark media query only for auto', () => {
		expect(themeToCss(clean, '.s')).toContain('@media (prefers-color-scheme: dark)');
		expect(themeToCss({ ...clean, mode: 'dark' }, '.s')).not.toContain('@media');
	});

	it('presets keep text and button-label contrast in the drawn tokens', () => {
		for (const preset of THEME_PRESETS) {
			for (const mode of ['light', 'dark'] as const) {
				const v = themeToCssVars(preset.theme, mode);
				expect(contrastRatio(v['--color-text'], v['--color-bg'])).toBeGreaterThanOrEqual(4.5);
				expect(contrastRatio(v['--color-on-accent'], v['--color-accent'])).toBeGreaterThanOrEqual(
					4.5
				);
			}
		}
	});
});
