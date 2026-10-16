/**
 * WCAG AA contrast for the design tokens in @osp/ui-components/tokens.css, both themes.
 * Reads the CSS as text (not an import), so the boundary rules are unaffected.
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(resolve(here, '../../../../ui-components/src/tokens.css'), 'utf8');

function block(selector: string): Record<string, string> {
	const start = css.indexOf(selector);
	if (start < 0) throw new Error(`selector not found: ${selector}`);
	const open = css.indexOf('{', start);
	const close = css.indexOf('}', open);
	const vars: Record<string, string> = {};
	for (const m of css.slice(open + 1, close).matchAll(/--(color-[\w-]+):\s*(#[0-9a-f]{6})/gi)) {
		vars[m[1]] = m[2];
	}
	return vars;
}

function luminance(hex: string): number {
	const [r, g, b] = [1, 3, 5].map((i) => {
		const c = parseInt(hex.slice(i, i + 2), 16) / 255;
		return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
	const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
	return (hi + 0.05) / (lo + 0.05);
}

const BACKGROUNDS = ['bg', 'surface', 'surface-raised', 'surface-sunken', 'selected', 'accent-subtle'];
// [foreground, minimum ratio, backgrounds]
const PAIRS: [string, number, string[]][] = [
	['text', 4.5, BACKGROUNDS],
	['text-muted', 4.5, BACKGROUNDS],
	['accent', 4.5, ['bg', 'surface', 'surface-raised']],
	['danger', 4.5, ['bg', 'surface', 'surface-raised']],
	['success', 4.5, ['bg', 'surface', 'surface-raised']],
	['warning', 4.5, ['bg', 'surface', 'surface-raised']],
	['border-strong', 3, ['bg', 'surface', 'surface-raised']],
	['focus', 3, BACKGROUNDS]
];

const themes = {
	light: block(':root {'),
	dark: block(":root[data-theme='dark']")
};

describe('design tokens', () => {
	it('dark tokens are identical in the media query and the manual override', () => {
		expect(block(":root:not([data-theme='light'])")).toEqual(themes.dark);
	});

	for (const [name, vars] of Object.entries(themes)) {
		it(`${name} theme meets WCAG AA`, () => {
			const failures: string[] = [];
			for (const [fg, min, bgs] of PAIRS) {
				for (const bg of bgs) {
					const ratio = contrast(vars[`color-${fg}`], vars[`color-${bg}`]);
					if (!(ratio >= min)) failures.push(`${fg} on ${bg}: ${ratio.toFixed(2)} < ${min}`);
				}
			}
			const onAccent = contrast(vars['color-on-accent'], vars['color-accent']);
			if (onAccent < 4.5) failures.push(`on-accent on accent: ${onAccent.toFixed(2)}`);
			const onHover = contrast(vars['color-on-accent'], vars['color-accent-hover']);
			if (onHover < 4.5) failures.push(`on-accent on accent-hover: ${onHover.toFixed(2)}`);
			expect(failures).toEqual([]);
		});
	}
});
