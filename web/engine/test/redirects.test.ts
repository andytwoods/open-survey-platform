/**
 * End redirects (end-of-survey plan §4.2, task EN2): the ending's redirect is resolved in
 * `view.end.redirect` with pipes filled, every value pattern-checked and encoded, and the
 * origin re-checked, so no value can change where the participant goes. Security cases
 * from the task: origin change via a param, scheme change, encoded `/`, `..`, an overlong
 * value, a placeholder in the origin, and the built-ins known only at the end.
 */
import { describe, expect, it } from 'vitest';
import {
	answer,
	checkRedirectTemplate,
	decline,
	endRedirect,
	fillRedirect,
	next,
	result,
	start,
	toPlain,
	view,
	withChecksum,
	withResponseId,
	type EndRedirectPlan,
	type Plan,
	type RedirectTemplatePlan,
	type Variable
} from '../src/index.ts';
import { blockNode, clock, makePlan, q, t } from './helpers.ts';

const PROLIFIC: RedirectTemplatePlan = {
	url: 'https://app.prolific.com/submissions/complete?cc={cc}&pid={pid}',
	params: { cc: { pattern: '[A-Z0-9]{4,8}' }, pid: {} }
};
const LAB: RedirectTemplatePlan = { url: 'https://lab.example.org/done/{note}', params: { note: { pattern: '.{1,300}' } } };
const PID = { id: 'pid', kind: 'embedded', name: 'pid', valueType: 'text', source: 'url', param: 'PROLIFIC_PID', default: null } as Variable;

function plan(redirect: EndRedirectPlan | undefined, extra: Partial<Plan> = {}): Plan {
	const base = makePlan({
		pages: { p1: [q('code', 'text'), q('note', 'text')] },
		flow: [blockNode('p1')],
		variables: [PID]
	});
	return withChecksum({
		...base,
		redirectTemplates: { prolific: PROLIFIC, lab: LAB },
		endings: { complete: { status: 'auto', summary: 'none', redirect } },
		...extra
	} as Plan);
}

const begin = (p: Plan, urlParams: Record<string, string> = { PROLIFIC_PID: 'p123' }) =>
	start(p, { sessionSeed: 3, clock: clock(), urlParams, sessionId: 'sess-1' });

function finish(p: Plan, values: Record<string, string> = {}) {
	let s = begin(p);
	for (const [k, v] of Object.entries(values)) s = answer(s, k, v);
	return next(s).state;
}

describe('fillRedirect', () => {
	it('fills, encodes and keeps the origin', () => {
		expect(fillRedirect(PROLIFIC, { cc: 'C1AB2', pid: 'p-1_2' })).toEqual({
			url: 'https://app.prolific.com/submissions/complete?cc=C1AB2&pid=p-1_2',
			rejected: null
		});
	});

	it('rejects values that would change the origin, the scheme or the path', () => {
		// A pattern-permissive template: the encoding alone must keep the URL where it was.
		const t: RedirectTemplatePlan = { url: 'https://lab.example.org/done/{x}', params: { x: { pattern: '.{1,200}' } } };
		for (const evil of ['@evil.example', '../../admin', 'a/b', '%2F..%2F', '#frag', '?k=v', 'javascript:alert(1)', 'https://evil.example/', '\\evil', 'a\u0000b', '...']) {
			const out = fillRedirect(t, { x: evil });
			expect(out.rejected, evil).toBeNull();
			const u = new URL(out.url!);
			expect(u.origin, evil).toBe('https://lab.example.org');
			expect(u.pathname.startsWith('/done/'), evil).toBe(true);
			expect(u.pathname.split('/').some((seg) => seg === '..' || seg === '.'), evil).toBe(false);
			expect(u.pathname.split('/').length, evil).toBe(3); // /done/<one encoded segment>
			expect(u.search + u.hash, evil).toBe('');
			expect(out.url!.startsWith('https://lab.example.org/done/'), evil).toBe(true);
		}
		// A bare `.` or `..` is not encoded and would be collapsed as a path segment: refused.
		expect(fillRedirect(t, { x: '..' })).toEqual({ url: null, rejected: 'x' });
		expect(fillRedirect(t, { x: '.' })).toEqual({ url: null, rejected: 'x' });
		// With the default pattern the same values are simply refused.
		const plain: RedirectTemplatePlan = { url: 'https://lab.example.org/done/{x}', params: { x: {} } };
		for (const evil of ['@evil.example', '..', 'a/b', 'https://evil.example/']) {
			expect(fillRedirect(plain, { x: evil })).toEqual({ url: null, rejected: 'x' });
		}
	});

	it('rejects a missing, empty, extra-free, overlong or off-pattern value', () => {
		expect(fillRedirect(PROLIFIC, { cc: 'C1AB2' })).toEqual({ url: null, rejected: 'pid' });
		expect(fillRedirect(PROLIFIC, { cc: '', pid: 'p' })).toEqual({ url: null, rejected: 'cc' });
		expect(fillRedirect(PROLIFIC, { cc: 'lower', pid: 'p' })).toEqual({ url: null, rejected: 'cc' });
		expect(fillRedirect(PROLIFIC, { cc: 'C1AB2', pid: 'x'.repeat(257) })).toEqual({ url: null, rejected: 'pid' });
		expect(fillRedirect(LAB, { note: 'x'.repeat(257) })).toEqual({ url: null, rejected: 'note' });
		// A multi-line value cannot smuggle a second line past a `.` pattern.
		expect(fillRedirect(LAB, { note: 'a\nb' })).toEqual({ url: null, rejected: 'note' });
	});

	it('refuses templates that put a placeholder in the origin or are not https', () => {
		expect(checkRedirectTemplate({ url: 'https://{host}/done', params: { host: {} } })).toBe('placeholder in the origin');
		expect(checkRedirectTemplate({ url: 'https://x.org{p}/done', params: { p: {} } })).toBe('placeholder in the origin');
		expect(checkRedirectTemplate({ url: 'http://x.org/done/{c}', params: { c: {} } })).toBe('not https');
		expect(checkRedirectTemplate({ url: 'javascript:alert(1)//{c}', params: { c: {} } })).toBe('not https');
		expect(checkRedirectTemplate({ url: 'https://x.org', params: {} })).toBe('origin must be followed by a path');
		expect(checkRedirectTemplate({ url: 'https://x.org/{a}', params: { b: {} } })).toBe('placeholders and params differ');
		expect(checkRedirectTemplate({ url: 'https://x.org/{a}', params: { a: { pattern: '(' } } })).toBe('bad pattern for a');
		expect(checkRedirectTemplate(PROLIFIC)).toBeNull();
		expect(fillRedirect({ url: 'https://{host}/done', params: { host: {} } }, { host: 'evil.example' })).toEqual({
			url: null,
			rejected: '$template'
		});
	});
});

describe('view.end.redirect', () => {
	it('fills literal and piped params; a piped answer is encoded, never trusted', () => {
		const p = plan({ template: 'prolific', params: { cc: ['C1AB2'], pid: [{ pipe: 'pid' }] }, delay: 5, mode: 'auto' });
		const end = view(finish(p)).end!;
		expect(end.redirect).toEqual({
			url: 'https://app.prolific.com/submissions/complete?cc=C1AB2&pid=p123',
			rejected: null,
			host: 'app.prolific.com',
			delay: 5,
			mode: 'auto',
			label: null
		});
		expect(result(finish(p)).diagnostics).toEqual([]);
	});

	it('an answer that fails the pattern rejects the redirect and is in the record', () => {
		const p = plan({ template: 'prolific', params: { cc: [{ pipe: 'code' }], pid: ['p'] }, delay: 0, mode: 'auto', label: t('Go') });
		const bad = finish(p, { code: 'C1AB2@evil.example' });
		const end = view(bad).end!;
		expect(end.redirect!.url).toBeNull();
		expect(end.redirect!.rejected).toBe('cc');
		expect(toPlain(end.redirect!.label)).toBe('Go');
		expect(result(bad).diagnostics).toEqual([{ code: 'redirect.param_rejected', site: 'endings.complete.redirect', path: '/params/cc' }]);
		const good = finish(p, { code: 'C1AB2' });
		expect(view(good).end!.redirect!.url).toBe('https://app.prolific.com/submissions/complete?cc=C1AB2&pid=p');
	});

	it('an unanswered question pipes empty, so the redirect is rejected rather than sent short', () => {
		const p = plan({ template: 'prolific', params: { cc: [{ pipe: 'code' }], pid: ['p'] }, delay: 5, mode: 'link' });
		expect(view(finish(p)).end!.redirect).toMatchObject({ url: null, rejected: 'cc', mode: 'link' });
	});

	it('ending built-ins: $session.id and $outcome at the end, $response.id after the ack', () => {
		const p = plan({
			template: 'lab',
			params: { note: [{ pipe: '$session.id' }, '-', { pipe: '$outcome' }, '-', { pipe: '$response.id' }] },
			delay: 5,
			mode: 'auto'
		});
		const s = begin(p);
		expect(view(s).end).toBeNull();
		const ended = next(s).state;
		// Before the acknowledgement the response id is unknown: the value is incomplete.
		expect(endRedirect(ended)!.url).toBe('https://lab.example.org/done/sess-1-complete-');
		// The record does not report a rejection that only waits on the ack.
		expect(result(ended).diagnostics).toEqual([]);
		const acked = withResponseId(ended, 'resp-9');
		expect(view(acked).end!.redirect!.url).toBe('https://lab.example.org/done/sess-1-complete-resp-9');
		expect(withResponseId(acked, 'resp-9')).toBe(acked);
		expect(withResponseId(s, 'x')).toBe(s); // nothing before the end
		// The built-ins are empty on pages (not in the end view), never leak into labels.
		const labelled = plan(undefined, {
			items: { ...p.items, code: { ...p.items.code!, label: { en: ['id ', { pipe: '$response.id' }, { pipe: '$outcome' }] } } }
		} as Partial<Plan>);
		expect(toPlain(view(begin(labelled)).items[0]!.label)).toBe('id ');
	});

	it('no redirect without one, or when the template is not declared', () => {
		expect(view(finish(plan(undefined))).end!.redirect).toBeNull();
		const orphan = plan({ template: 'nope', params: {}, delay: 5, mode: 'auto' });
		expect(view(finish(orphan)).end!.redirect).toBeNull();
		const proto = plan({ template: 'constructor', params: {}, delay: 5, mode: 'auto' });
		expect(view(finish(proto)).end!.redirect).toBeNull();
	});

	it('a declined ending may redirect, with $response.id empty', () => {
		const base = plan({ template: 'lab', params: { note: ['declined-', { pipe: '$outcome' }] }, delay: 0, mode: 'auto' });
		const p = withChecksum({
			...base,
			consent: { version: 'sha256:' + 'c'.repeat(64), text: t('Consent?'), agree: t('Yes'), decline: t('No'), declineOutcome: 'declined', countDeclines: false },
			endings: { declined: base.endings!.complete! }
		} as Plan);
		const d = view(decline(begin(p))).end!;
		expect(d.status).toBe('not-recorded');
		expect(d.redirect!.url).toBe('https://lab.example.org/done/declined-declined');
	});
});
