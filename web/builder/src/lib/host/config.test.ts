import { describe, expect, it } from 'vitest';
import { apiPath, DEFAULT_LINKS, fillTemplate, parseConfig, parseFrameConfig, type OspPageConfig } from './config';

const ORIGIN = 'https://lab.example.org';

function good(over: Record<string, unknown> = {}): Record<string, unknown> {
	return {
		version: 1,
		apiBase: '/osp/api',
		links: {
			list: '/osp/',
			editor: '/osp/surveys/{id}/',
			flow: '/osp/surveys/{id}/flow/',
			settings: '/osp/surveys/{id}/settings/',
			appearance: '/osp/surveys/{id}/appearance/',
			themes: '/osp/themes/',
			previewFrame: '/osp/preview-frame/'
		},
		...over
	};
}

function errorsOf(raw: unknown, opts = {}): string[] {
	const r = parseConfig(raw, ORIGIN, opts);
	return r.ok ? [] : r.errors;
}

describe('parseConfig', () => {
	it('accepts a minimal config and a full one', () => {
		expect(parseConfig(good(), ORIGIN)).toEqual({ ok: true, config: good() });
		const full = good({
			surveyId: 's-123',
			tenantId: 'lab-1',
			csrf: { header: 'X-CSRFToken', cookie: 'csrftoken' },
			onUnauthenticated: { redirect: '/accounts/login/' },
			user: { displayName: 'A. Researcher' },
			allowedOrigins: ['https://api.lab.example.org'],
			apiBase: 'https://api.lab.example.org/osp'
		});
		const r = parseConfig(full, ORIGIN, { requireSurveyId: true });
		expect(r.ok).toBe(true);
		if (r.ok) expect((r.config as OspPageConfig).csrf?.header).toBe('X-CSRFToken');
	});

	it('takes the optional profile link (no {id}: it is a lab page)', () => {
		const links = good().links as Record<string, string>;
		expect(parseConfig(good({ links: { ...links, profile: '/osp/profile/' } }), ORIGIN).ok).toBe(true);
		expect(errorsOf(good({ links: { ...links, profile: 'https://evil.example/p' } }))).toEqual([
			'links.profile: must be same-origin (or an origin in allowedOrigins)'
		]);
		expect(errorsOf(good({ links: { ...links, profile: 7 } }))).toEqual(['links.profile: must be a string']);
	});

	it('takes the optional results link, checked like the others', () => {
		const links = good().links as Record<string, string>;
		expect(parseConfig(good({ links: { ...links, results: '/osp/surveys/{id}/results/' } }), ORIGIN).ok).toBe(true);
		expect(errorsOf(good({ links: { ...links, results: '/osp/results/' } }))).toEqual([
			'links.results: must contain {id}'
		]);
		expect(errorsOf(good({ links: { ...links, results: 'https://evil.example/{id}' } }))).toEqual([
			'links.results: must be same-origin (or an origin in allowedOrigins)'
		]);
		expect(errorsOf(good({ links: { ...links, results: 7 } }))).toEqual(['links.results: must be a string']);
	});

	it('copies the config (later changes to the input do not leak in)', () => {
		const raw = good();
		const r = parseConfig(raw, ORIGIN);
		(raw.links as Record<string, string>).list = 'https://evil.example/';
		expect(r.ok && r.config.links.list).toBe('/osp/');
	});

	it('rejects non-objects, wrong versions and unknown keys', () => {
		expect(errorsOf(null)).toEqual(['config: must be a JSON object']);
		expect(errorsOf([])).toEqual(['config: must be a JSON object']);
		expect(errorsOf(good({ version: 2 }))).toContain('version: must be 1');
		expect(errorsOf(good({ version: '1' }))).toContain('version: must be 1');
		expect(errorsOf(good({ debug: true }))).toContain('config: unknown key "debug"');
	});

	it('requires same-origin apiBase and links unless the origin is allowed', () => {
		expect(errorsOf(good({ apiBase: 'https://evil.example/api' }))).toEqual([
			'apiBase: must be same-origin (or an origin in allowedOrigins)'
		]);
		expect(errorsOf(good({ apiBase: '//evil.example/api' }))).toHaveLength(1);
		expect(errorsOf(good({ apiBase: 'javascript:alert(1)' }))).toHaveLength(1);
		expect(errorsOf(good({ apiBase: 'https://user:pw@lab.example.org/api' }))).toHaveLength(1);
		expect(errorsOf(good({ apiBase: `${ORIGIN}/api` }))).toEqual([]);
		const links = { ...(good().links as object), list: 'https://evil.example/' };
		expect(errorsOf(good({ links }))).toEqual(['links.list: must be same-origin (or an origin in allowedOrigins)']);
		expect(errorsOf(good({ links, allowedOrigins: ['https://evil.example'] }))).toEqual([]);
	});

	it('checks allowedOrigins are exact origins', () => {
		expect(errorsOf(good({ allowedOrigins: ['https://x.example/'] }))).toHaveLength(1);
		expect(errorsOf(good({ allowedOrigins: ['https://x.example/path'] }))).toHaveLength(1);
		expect(errorsOf(good({ allowedOrigins: ['*'] }))).toHaveLength(1);
		expect(errorsOf(good({ allowedOrigins: 'https://x.example' }))).toHaveLength(1);
		expect(errorsOf(good({ allowedOrigins: Array(21).fill('https://x.example') }))).toHaveLength(1);
	});

	it('needs every link, with {id} in the survey ones', () => {
		const links = { ...(good().links as Record<string, string>) };
		delete links.flow;
		expect(errorsOf(good({ links }))).toEqual(['links.flow: must be a string']);
		expect(errorsOf(good({ links: { ...links, flow: '/osp/flow/' } }))).toEqual(['links.flow: must contain {id}']);
		expect(errorsOf(good({ links: { ...links, flow: '/f/{id}', extra: '/x' } }))).toEqual(['links: unknown key "extra"']);
		expect(errorsOf(good({ links: 'x' }))).toEqual(['links: must be an object']);
	});

	it('caps lengths and refuses control characters', () => {
		expect(errorsOf(good({ apiBase: '/' + 'a'.repeat(2048) }))).toEqual(['apiBase: must be 1–2048 characters']);
		expect(errorsOf(good({ apiBase: '' }))).toEqual(['apiBase: must be 1–2048 characters']);
		expect(errorsOf(good({ surveyId: 'x'.repeat(201) }))).toHaveLength(1);
		expect(errorsOf(good({ surveyId: 'a\nb' }))).toEqual(['surveyId: must not contain control characters']);
		expect(errorsOf(good({ user: { displayName: 'n'.repeat(201) } }))).toHaveLength(1);
	});

	it('survey ids are opaque but have no slashes', () => {
		expect(errorsOf(good({ surveyId: '../x' }))).toHaveLength(1);
		expect(errorsOf(good({ surveyId: 7 }))).toEqual(['surveyId: must be a string']);
		expect(errorsOf(good(), { requireSurveyId: true })).toEqual(['surveyId: required on this page']);
	});

	it('validates the CSRF scheme', () => {
		expect(errorsOf(good({ csrf: { header: 'X-CSRF-Token', token: 't' } }))).toEqual([]);
		expect(errorsOf(good({ csrf: { header: 'X CSRF', token: 't' } }))).toHaveLength(1);
		expect(errorsOf(good({ csrf: { header: 'X-CSRF-Token' } }))).toEqual(['csrf: needs a token or a cookie']);
		expect(errorsOf(good({ csrf: { header: 'X-CSRF-Token', cookie: 'a b' } }))).toEqual([
			'csrf.cookie: must be a cookie name'
		]);
		expect(errorsOf(good({ csrf: { header: 'X-CSRF-Token', token: 't', secret: 's' } }))).toEqual([
			'csrf: unknown key "secret"'
		]);
	});

	it('validates onUnauthenticated (redirect same-origin)', () => {
		expect(errorsOf(good({ onUnauthenticated: 'reload' }))).toEqual([]);
		expect(errorsOf(good({ onUnauthenticated: 'loop' }))).toHaveLength(1);
		expect(errorsOf(good({ onUnauthenticated: { redirect: 'https://evil.example/login' } }))).toHaveLength(1);
	});
});

describe('parseFrameConfig', () => {
	it('takes only the version: never an API base or CSRF', () => {
		expect(parseFrameConfig(undefined)).toEqual({ ok: true, config: { version: 1 } });
		expect(parseFrameConfig({ version: 1 })).toEqual({ ok: true, config: { version: 1 } });
		const r = parseFrameConfig({ version: 1, apiBase: '/api', csrf: { header: 'X', token: 't' } });
		expect(r.ok).toBe(false);
		if (!r.ok) expect(r.errors).toEqual(['config: the preview frame takes no "apiBase"', 'config: the preview frame takes no "csrf"']);
	});
});

describe('templates and API paths', () => {
	it('fills {id} URL-encoded', () => {
		expect(fillTemplate('/s/{id}/flow', { id: 'a b/c' })).toBe('/s/a%20b%2Fc/flow');
		expect(fillTemplate(DEFAULT_LINKS.editor, { id: 'x' })).toBe('/surveys/x');
	});

	it('puts /api calls under apiBase', () => {
		expect(apiPath('/osp/api', '/api/surveys')).toBe('/osp/api/surveys');
		expect(apiPath('/osp/api/', '/api/me')).toBe('/osp/api/me');
		expect(apiPath('/api', '/api/health')).toBe('/api/health');
		expect(apiPath('https://api.example.org/osp', '/api/x')).toBe('https://api.example.org/osp/x');
		expect(apiPath('/osp/api', '/apix')).toBe('/apix');
	});
});
