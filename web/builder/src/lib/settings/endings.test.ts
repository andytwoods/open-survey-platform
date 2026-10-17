import { describe, expect, it } from 'vitest';
import {
	endingAnchor,
	endingOf,
	endingOp,
	endingsOf,
	endingWith,
	newRedirect,
	outcomesInUse,
	placeholdersOf,
	previewUrl,
	redirectOf,
	redirectParams,
	redirectTemplateOp,
	templateProblem,
	templatesOf
} from './endings';

const survey = {
	consent: { text: 'Agree?', declineOutcome: 'no_consent' },
	quotas: [
		{ id: 'q_old', onFull: { outcome: 'quota_full' } },
		{ id: 'q_unused', onFull: { outcome: 'never' } }
	],
	flow: [
		{ type: 'block', id: 'n1', block: 'b1' },
		{ type: 'branch', id: 'br', then: [{ type: 'end', id: 'end_out', outcome: 'screened_out' }], else: [] },
		{ type: 'randomiser', id: 'r', children: [{ type: 'quotaCheck', id: 'qc', quota: 'q_old' }] },
		{ type: 'end', id: 'end_done' }
	],
	settings: { endings: { screened_out: { body: 'Bye' }, junk: 3 } }
};

describe('endings (EN1)', () => {
	it('lists every outcome a session can end with, complete first', () => {
		const used = outcomesInUse(survey);
		expect(used.map((u) => u.outcome)).toEqual(['complete', 'no_consent', 'screened_out', 'quota_full']);
		expect(used[0]!.sources).toEqual(['End of the flow', 'End node end_done']);
		expect(used.find((u) => u.outcome === 'no_consent')!.declined).toBe(true);
		expect(used.find((u) => u.outcome === 'quota_full')!.sources).toEqual(['Quota q_old (when full)']);
		expect(outcomesInUse(null).map((u) => u.outcome)).toEqual(['complete']);
	});

	it('reads endings, ignoring malformed entries, and shapes set_ending', () => {
		expect(endingsOf(survey)).toEqual({ screened_out: { body: 'Bye' } });
		expect(endingOf(survey, 'complete')).toBeNull();
		expect(endingWith({ body: 'Bye', status: 'none' }, 'status', undefined)).toEqual({ body: 'Bye' });
		expect(endingWith(null, 'title', 'Hi')).toEqual({ title: 'Hi' });
		expect(endingOp('complete', null)).toEqual({ op: 'set_ending', params: { outcome: 'complete', ending: null } });
		expect(endingAnchor('quota_full')).toBe('ending-quota_full');
	});
});

describe('end redirects (EN2)', () => {
	const prolific = { url: 'https://app.prolific.com/submissions/complete?cc={cc}&r={r}', params: { cc: { pattern: '[A-Z0-9]{4,8}' }, r: {} } };
	const withTemplates = {
		settings: { redirectTemplates: { prolific }, endings: { complete: { redirect: { template: 'prolific', params: { cc: 'C1AB2', r: '${rating}' }, mode: 'link' } } } },
		hooks: { redirects: { done: { url: 'https://lab.example.org/done/{code}', params: { code: {} } }, prolific: { url: 'https://evil.example/{x}', params: { x: {} } } } }
	};

	it('lists settings templates first and hook templates after, never shadowing a name', () => {
		const ts = templatesOf(withTemplates);
		expect(ts.map((t) => [t.name, t.source, t.host, t.placeholders])).toEqual([
			['prolific', 'settings', 'app.prolific.com', ['cc', 'r']],
			['done', 'hooks', 'lab.example.org', ['code']]
		]);
		expect(templatesOf(null)).toEqual([]);
		expect(placeholdersOf('https://x.org/{a}/{b}?c={c}')).toEqual(['a', 'b', 'c']);
	});

	it('previews the URL with literals encoded and pipes left as tokens', () => {
		expect(previewUrl(prolific, { cc: 'C1 &B2', r: '${rating}' })).toBe(
			'https://app.prolific.com/submissions/complete?cc=C1%20%26B2&r=${rating}'
		);
		expect(previewUrl(prolific, {})).toBe('https://app.prolific.com/submissions/complete?cc=&r=');
	});

	it('reads a template quickly before the server does', () => {
		expect(templateProblem('https://app.prolific.com/submissions/complete?cc={cc}')).toBeNull();
		expect(templateProblem('http://x.org/done/{c}')).toMatch(/https/);
		expect(templateProblem('https://{host}/done')).toMatch(/placeholder cannot be part of the site/);
		expect(templateProblem('https://x.org')).toMatch(/followed by a path/);
		expect(templateProblem('https://x.org/{a}/{a}')).toMatch(/once/);
		expect(templateProblem('not a url')).toMatch(/full address/);
	});

	it('shapes the ops and the ending redirect', () => {
		expect(redirectTemplateOp('prolific', prolific)).toEqual({ op: 'set_redirect_template', params: { name: 'prolific', template: prolific } });
		expect(redirectTemplateOp('prolific', null).params).toEqual({ name: 'prolific', template: null });
		const ending = endingOf(withTemplates, 'complete');
		expect(redirectOf(ending)).toEqual({ template: 'prolific', params: { cc: 'C1AB2', r: '${rating}' }, mode: 'link' });
		expect(redirectParams(redirectOf(ending))).toEqual({ cc: 'C1AB2', r: '${rating}' });
		expect(redirectParams(null)).toEqual({});
		expect(newRedirect(templatesOf(withTemplates)[0]!)).toEqual({ template: 'prolific', params: { cc: '', r: '' } });
	});
});
