import { readFileSync } from 'node:fs';
import { planChecksum } from '@osp/engine';
import { THEME_PRESETS } from '@osp/ui-components';
import { describe, expect, it } from 'vitest';
import { conditionTexts, previewPlan, resolveTheme } from './compile';

const fixture = (name: string) =>
	JSON.parse(readFileSync(new URL(`../../../../../fixtures/${name}/survey.json`, import.meta.url), 'utf8')) as Record<string, unknown>;

const clean = THEME_PRESETS.find((p) => p.id === 'clean')!.theme;

describe('previewPlan (POST /preview-plan, in the browser)', () => {
	it('compiles the draft with seedVersion "draft", the clean preset and the condition texts', () => {
		const r = previewPlan(fixture('05-showif-null'), null);
		expect(r.diagnostics.filter((d) => d.severity === 'error')).toEqual([]);
		const plan = r.plan as unknown as Record<string, unknown>;
		expect(plan).not.toBeNull();
		expect((plan.survey as { seedVersion: string }).seedVersion).toBe('draft');
		expect((plan.theme as { colours: unknown }).colours).toEqual(clean.colours);
		expect(plan.checksum).toBe(planChecksum(plan));
		expect(r.conditions['items.s_gt.showIf']).toBe('a > 5');
		expect(r.conditions['items.s_not_gt.showIf']).toBe('not a > 5');
	});

	it('every fixture compiles as it would on the server (no errors, a checksummed plan)', () => {
		for (const name of ['01-all-types', '02-required', '03-constraints', '11-end-nodes']) {
			const r = previewPlan(fixture(name), null);
			expect(r.plan, name).not.toBeNull();
		}
	});

	it('a draft with errors gives no plan and the diagnostics to fix', () => {
		const s = fixture('05-showif-null');
		(s.flow as unknown[]).push({ type: 'block', id: 'nx', block: 'missing' });
		const r = previewPlan(s, null);
		expect(r.plan).toBeNull();
		expect(r.diagnostics.map((d) => d.code)).toContain('ref.unknown_block');
	});

	it('never throws on a document that is not a survey', () => {
		for (const bad of [null, 1, 'x', [], {}, { blocks: 'x' }]) expect(previewPlan(bad, null).plan).toBeNull();
	});
});

describe('resolveTheme (publish_theme.resolve_theme)', () => {
	it("uses the survey's own theme, then the lab default, then the clean preset", () => {
		const warm = THEME_PRESETS.find((p) => p.id === 'warm')!.theme;
		const high = THEME_PRESETS.find((p) => p.id === 'high-contrast')!.theme;
		expect(resolveTheme({ settings: { theme: warm } }, { name: 'Lab', theme: high }).theme?.colours).toEqual(warm.colours);
		expect(resolveTheme({}, { name: 'Lab', theme: high }).theme?.colours).toEqual(high.colours);
		expect(resolveTheme({}, null).theme?.colours).toEqual(clean.colours);
	});

	it('a theme that fails the guard is left out and reported where it came from', () => {
		const grey = { ...clean, colours: { ...clean.colours, light: { ...clean.colours.light, text: '#fefefe' } } };
		const own = resolveTheme({ settings: { theme: grey } }, null);
		expect(own.theme).toBeNull();
		expect(own.diagnostics[0]).toMatchObject({ code: 'theme.contrast', severity: 'error' });
		expect(own.diagnostics[0]!.pointer).toMatch(/^\/settings\/theme\/colours\/light\//);
		expect(own.diagnostics[0]!.message).toMatch(/^Theme \(survey theme\): /);
		const lab = resolveTheme({}, { name: 'Grey', theme: grey });
		expect(lab.diagnostics[0]!.pointer).toMatch(/^\/labTheme\//);
		expect(lab.diagnostics[0]!.message).toMatch(/^Theme \(lab default 'Grey'\): /);
		expect(resolveTheme({ settings: { theme: { colours: 1 } } }, null)).toMatchObject({ theme: null, diagnostics: [{ code: 'theme.schema' }] });
	});
});

describe('conditionTexts', () => {
	it('prints flow branch and nested randomiser conditions by site', () => {
		const plan = {
			items: {},
			pages: { p: { showIf: { kind: 'bool', value: true } } },
			flow: [
				{ type: 'randomiser', children: [{ type: 'branch', id: 'br', if: { kind: 'ref', id: 'a' }, then: [], else: [] }] }
			]
		};
		expect(conditionTexts(plan as never)).toEqual({ 'pages.p.showIf': 'true', 'flow.br.if': 'a' });
	});
});
