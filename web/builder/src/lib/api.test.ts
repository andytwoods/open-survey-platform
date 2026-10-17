import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, csrfHeader, readCookie } from './api';
import { setPageConfig } from './host/links';
import { session } from './host/session.svelte';

describe('CSRF from the host scheme', () => {
	it('reads a named cookie', () => {
		expect(readCookie('a=1; csrftoken=abc%3D; b=2', 'csrftoken')).toBe('abc=');
		expect(readCookie('a=1', 'csrftoken')).toBeNull();
		expect(readCookie('csrftoken=', 'csrftoken')).toBeNull();
	});

	it('uses the token from config, else the cookie, under the configured header', () => {
		expect(csrfHeader(undefined, 'x=1')).toBeNull();
		expect(csrfHeader({ header: 'X-CSRFToken', token: 't1', cookie: 'c' }, 'c=t2')).toEqual(['X-CSRFToken', 't1']);
		expect(csrfHeader({ header: 'X-CSRFToken', cookie: 'c' }, 'c=t2')).toEqual(['X-CSRFToken', 't2']);
		expect(csrfHeader({ header: 'X-CSRFToken', cookie: 'c' }, '')).toBeNull();
	});
});

describe('the API client under a host config', () => {
	const calls: { url: string; method: string; headers: Headers; credentials?: RequestCredentials }[] = [];
	let status = 200;

	beforeEach(() => {
		calls.length = 0;
		status = 200;
		vi.stubGlobal('location', { origin: 'https://lab.example.org', href: 'https://lab.example.org/x' });
		vi.stubGlobal('fetch', async (input: URL | string, init: RequestInit) => {
			calls.push({
				url: String(input),
				method: init.method ?? 'GET',
				headers: new Headers(init.headers),
				credentials: init.credentials
			});
			return new Response(JSON.stringify(status === 200 ? { status: 'ok' } : { code: 'x', message: 'no' }), {
				status,
				headers: { 'content-type': 'application/json' }
			});
		});
		setPageConfig({
			version: 1,
			apiBase: '/osp/api',
			links: { list: '/', editor: '/{id}', flow: '/{id}', settings: '/{id}', appearance: '/{id}', themes: '/', previewFrame: '/' },
			csrf: { header: 'X-Host-CSRF', token: 'host-token' }
		});
	});

	afterEach(() => {
		vi.unstubAllGlobals();
		setPageConfig(null);
		session.status = 'ok';
	});

	it('sends calls under apiBase, the host CSRF header on writes only', async () => {
		await api.GET('/api/health');
		await api.POST('/api/surveys', { body: { title: 't' } });
		expect(calls.map((c) => [c.method, c.url])).toEqual([
			['GET', 'https://lab.example.org/osp/api/health'],
			['POST', 'https://lab.example.org/osp/api/surveys']
		]);
		expect(calls[0].headers.get('X-Host-CSRF')).toBeNull();
		expect(calls[1].headers.get('X-Host-CSRF')).toBe('host-token');
		expect(calls[1].headers.get('X-CSRF-Token')).toBeNull();
		expect(calls[1].credentials).toBe('same-origin');
	});

	it('a 401 ends the session; later writes are not sent', async () => {
		status = 401;
		session.configure({ redirect: '/login' });
		const r = await api.GET('/api/surveys');
		expect(r.response.status).toBe(401);
		expect(session.status).toBe('ended');
		const w = await api.POST('/api/surveys', { body: { title: 't' } });
		expect(w.response.status).toBe(401);
		expect(calls).toHaveLength(1);
	});

	it('a 403 is reported as no access', async () => {
		status = 403;
		await api.GET('/api/themes');
		expect(session.status).toBe('forbidden');
	});
});
