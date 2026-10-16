import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import {
	buildRedirectUrl,
	checkManifest,
	checkOrigin,
	criticalEvents,
	exportsAllowed,
	flowCriticalVariables,
	matchesSchema,
	sourceChecksum
} from '../src/manifest.ts';
import { FRAME_CSP, FRAME_SCRIPT, FRAME_SCRIPT_HASH, FRAME_SRCDOC, workerSource } from '../src/sandbox-source.ts';
import { hookManifest, hookPlan } from './fixtures.ts';

const plan = hookPlan();

describe('manifest', () => {
	it('accepts the fixture manifest', () => {
		expect(checkManifest(plan, hookManifest('osp.on("onStart", function(){})'))).toEqual([]);
	});

	it('refuses undeclared writes, unknown reads, events and bad timeouts', () => {
		const m = hookManifest('');
		m.handlers.onPageNext = { reads: ['nope'], writes: ['q1', 'hv_score'], timeoutMs: 60_000 };
		(m.handlers as Record<string, unknown>).onEval = { reads: [], writes: [] };
		m.handlers.onSubmitted = { reads: [], writes: ['hv_note'] };
		const errs = checkManifest(plan, m).join('\n');
		expect(errs).toContain('reads: unknown nope');
		expect(errs).toContain('q1 is not a hook variable');
		expect(errs).toContain('onEval: unknown event');
		expect(errs).toContain('timeoutMs');
		expect(errs).toContain('onSubmitted: may not write');
	});

	it('refuses redirect templates that could change where the URL goes', () => {
		const bad = (url: string, params: Record<string, { pattern?: string }> = { code: {} }) =>
			checkManifest(plan, hookManifest('', { redirects: { r: { url, params } } }));
		expect(bad('http://app.prolific.com/x?cc={code}')).toEqual(['redirects.r: not https']);
		expect(bad('https://{code}.evil.com/x')).toEqual(['redirects.r: placeholder in the origin']);
		expect(bad('https://a.com{code}')[0]).toMatch(/placeholder in the origin|origin must be followed/);
		expect(bad('https://a.com/x?cc={code}&b={other}')).toEqual(['redirects.r: placeholders and params differ']);
		expect(bad('https://a.com/x?cc={code}', { code: { pattern: '(' } })).toEqual(['redirects.r: bad pattern for code']);
		expect(bad('javascript:alert(1)//{code}')[0]).toMatch(/not https|not a URL/);
	});

	it('parent origin must be a single https origin', () => {
		expect(checkOrigin('https://lab.example.org')).toBe(true);
		expect(checkOrigin('http://localhost:4417')).toBe(true);
		expect(checkOrigin('*')).toBe(false);
		expect(checkOrigin('https://lab.example.org/path')).toBe(false);
		expect(checkOrigin('http://lab.example.org')).toBe(false);
		expect(checkManifest(plan, hookManifest('', { parent: { origin: '*', messages: {} } }))).toEqual([
			'parent.origin: must be one https origin'
		]);
	});

	it('builds redirects only from declared templates and matching params, URL-encoded', () => {
		const m = hookManifest('x');
		expect(buildRedirectUrl(m, { templateId: 'prolific', params: { code: 'AB12CD' } })).toBe(
			'https://app.prolific.com/submissions/complete?cc=AB12CD'
		);
		expect(buildRedirectUrl(m, { templateId: 'prolific', params: { code: 'ab' } })).toBeNull();
		expect(buildRedirectUrl(m, { templateId: 'prolific', params: { code: 'AB12&x=1' } })).toBeNull();
		expect(buildRedirectUrl(m, { templateId: 'prolific', params: { code: 'AB12', extra: 'X' } })).toBeNull();
		expect(buildRedirectUrl(m, { templateId: 'evil', params: { code: 'AB12' } })).toBeNull();
		expect(buildRedirectUrl(m, { templateId: '__proto__', params: {} })).toBeNull();
	});

	it('data exports need an owner confirmation of this exact source', () => {
		const m = hookManifest('v1');
		expect(exportsAllowed(m)).toBe(true);
		expect(exportsAllowed({ ...m, source: 'v2' })).toBe(false);
		expect(exportsAllowed({ ...m, exportsConfirmedFor: null })).toBe(false);
		expect(buildRedirectUrl({ ...m, source: 'v2' }, { templateId: 'prolific', params: { code: 'AB12' } })).toBeNull();
		expect(sourceChecksum('v1')).toMatch(/^sha256:[0-9a-f]{64}$/);
	});

	it('closed payload schemas', () => {
		const s = hookManifest('').parent!.messages.progress!;
		expect(matchesSchema(s, { page: 3 })).toBe(true);
		expect(matchesSchema(s, { page: 3, answers: { q1: 5 } })).toBe(false);
		expect(matchesSchema(s, {})).toBe(false);
		expect(matchesSchema(s, { page: 3.5 })).toBe(false);
		expect(matchesSchema(s, [3])).toBe(false);
		expect(matchesSchema({ type: 'string', pattern: '[a-z]+' }, 'abc')).toBe(true);
		expect(matchesSchema({ type: 'string', pattern: '[a-z]+' }, 'abc1')).toBe(false);
		expect(matchesSchema({ type: 'array', items: { type: 'null' }, maxItems: 2 }, [null, null, null])).toBe(false);
	});

	it('detects flow-critical hook variables (branch, show-if, through computed)', () => {
		expect([...flowCriticalVariables(plan)].sort()).toEqual(['hv_flag', 'hv_score']);
		const m = hookManifest('');
		expect([...criticalEvents(plan, m)].sort()).toEqual(['onPageInit', 'onPageNext']);
		const p2 = {
			...plan,
			variables: { ...plan.variables, c1: { id: 'c1', kind: 'computed' as const, name: 'c1', expr: { kind: 'ref' as const, id: 'hv_note' } } },
			items: { ...plan.items, q3: { ...plan.items.q3!, showIf: { kind: 'answered' as const, ref: { kind: 'ref' as const, id: 'c1' } } } }
		};
		expect(flowCriticalVariables(p2).has('hv_note')).toBe(true);
	});
});

describe('sandbox sources', () => {
	it('frame CSP is default-src none with the hashed script and blob workers only', () => {
		expect(FRAME_CSP.startsWith("default-src 'none';")).toBe(true);
		expect(FRAME_CSP).toContain(`script-src ${FRAME_SCRIPT_HASH};`);
		expect(FRAME_CSP).toContain('worker-src blob:');
		expect(FRAME_CSP).not.toMatch(/unsafe-(inline|eval)|connect-src|\*/);
		expect(FRAME_SRCDOC).toContain(FRAME_CSP);
		expect(FRAME_SCRIPT_HASH).toBe(`'sha256-${createHash('sha256').update(FRAME_SCRIPT).digest('base64')}'`);
	});

	it('worker source runs the bootstrap before the researcher code', () => {
		const src = workerSource('osp.on("onStart", function(){})');
		expect(src.indexOf('Math,"random"')).toBeLessThan(src.indexOf('osp.on("onStart"'));
		expect(src).toContain('var LOCK=true');
		expect(workerSource('', { lockdown: false })).toContain('var LOCK=false');
	});
});
