import { describe, expect, it } from 'vitest';
import { withChecksum, type Expr, type Plan } from '@osp/engine';
import { explainPage, refsOf } from './explain';
import { compareStep, exportScript, parseScript, playScript, traceStep } from './script';

const t = (s: string) => ({ en: [s] });
const gt5: Expr = { kind: 'compare', op: '>', left: { kind: 'ref', id: 'a' }, right: { kind: 'int', value: 5 } };

/** p1: a (integer); p2: always, big (shown when a > 5). */
function plan(): Plan {
	const q = (id: string, page: string, extra: object = {}) => ({ id, page, type: 'integer', name: id, required: false, label: t(id), ...extra });
	return withChecksum({
		planVersion: 'osp-runtime-plan/1',
		engineVersion: '1',
		survey: { id: 's', version: null, specVersion: 'osp-survey/0.1', seedVersion: 'draft' },
		languages: ['en'],
		defaultLanguage: 'en',
		title: t('T'),
		settings: { backNavigation: true, saveMode: 'every-page', localCopy: 'browser', resumeExpiryDays: 30 },
		items: { a: q('a', 'p1'), always: q('always', 'p2'), big: q('big', 'p2', { showIf: gt5 }) },
		questions: ['a', 'always', 'big'],
		pages: {
			p1: { id: 'p1', block: 'b1', items: ['a'], itemOrder: 'fixed' },
			p2: { id: 'p2', block: 'b2', items: ['always', 'big'], itemOrder: 'fixed' }
		},
		blocks: { b1: { id: 'b1', pages: ['p1'] }, b2: { id: 'b2', pages: ['p2'] } },
		variables: {},
		quotas: {},
		flow: [
			{ type: 'block', id: 'n1', block: 'b1', pages: ['p1'] },
			{ type: 'block', id: 'n2', block: 'b2', pages: ['p2'] }
		]
	} as unknown as Plan);
}

const script = (a: number) => ({
	format: 'osp-fixture-script/0',
	id: 's',
	sessionSeed: 7,
	language: 'en',
	actions: [
		{ expectPage: 'b1', set: { a }, do: 'next' as const },
		{ expectPage: 'b2', do: 'next' as const }
	]
});

describe('debugger script player', () => {
	it('plays a script and traces each step by block', () => {
		const p = playScript(plan(), script(7));
		expect(p.error).toBeNull();
		expect(p.steps.map((s) => s.page)).toEqual(['b1', 'b2', null]);
		expect(p.steps[1]!.visible).toEqual(['always', 'big']);
		expect(p.steps[2]!.end).toBe('complete');
	});

	it('stops with a message on a wrong page', () => {
		const bad = { ...script(7), actions: [{ expectPage: 'b2', do: 'next' as const }] };
		const p = playScript(plan(), bad);
		expect(p.error?.message).toMatch(/expects page b2/);
	});

	it('compares a step with an expected one, ignoring placeholders', () => {
		const p = playScript(plan(), script(3), 1);
		const step = traceStep(p.state, 1);
		expect(compareStep({ page: 'b2', visible: ['always'], orders: '<engine>' }, step)).toEqual([]);
		expect(compareStep({ page: 'b2', visible: ['always', 'big'] }, step)).toHaveLength(1);
	});

	it('exports a run as a script that plays back to the same answers', () => {
		const p = playScript(plan(), script(9));
		const out = exportScript(p.state);
		expect(out.sessionSeed).toBe(7);
		expect(out.actions).toEqual([
			{ do: 'next', expectPage: 'b1', set: { a: 9 } },
			{ do: 'next', expectPage: 'b2' }
		]);
		expect(playScript(plan(), out).steps.at(-1)!.questions).toEqual(p.steps.at(-1)!.questions);
	});

	it('refuses scripts it cannot read without throwing', () => {
		expect(parseScript('{')).toHaveProperty('error');
		expect(parseScript('{"sessionSeed":0,"actions":[]}')).toHaveProperty('error');
		expect(parseScript('{"sessionSeed":1,"actions":[{"do":"jump"}]}')).toHaveProperty('error');
		expect(parseScript(JSON.stringify(script(1)))).toHaveProperty('script');
	});
});

describe('debugger explanations', () => {
	it('lists what a condition reads', () => {
		expect(refsOf(gt5)).toEqual(['a']);
	});

	it('explains shown and hidden questions with the values read', () => {
		const texts = { 'items.big.showIf': 'a > 5' };
		for (const [a, shown] of [
			[3, false],
			[8, true]
		] as const) {
			const p = playScript(plan(), script(a), 1);
			const rows = explainPage(p.state, texts);
			const big = rows.find((r) => r.id === 'big')!;
			expect(big.visible).toBe(shown);
			expect(big.reason.condition).toBe('a > 5');
			expect(big.reason.evaluated).toBe(shown);
			expect(big.reason.agrees).toBe(true);
			expect(big.reason.reads).toEqual([{ id: 'a', value: a, note: 'answered' }]);
			expect(rows.find((r) => r.id === 'always')!.reason.summary).toMatch(/no show-if/);
		}
	});
});
