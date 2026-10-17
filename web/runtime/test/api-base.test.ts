import { describe, expect, it } from 'vitest';
import { httpApi } from '../src/lib/api';
import { apiUrl, DEFAULT_API_BASE, resolveApiBase } from '../src/lib/api-base';

const ORIGIN = 'https://surveys.example.ac.uk';

describe('resolveApiBase (D15)', () => {
	it('defaults to /api', () => {
		expect(resolveApiBase(null, ORIGIN)).toEqual({ base: DEFAULT_API_BASE });
		expect(resolveApiBase(undefined, ORIGIN)).toEqual({ base: '/api' });
		expect(resolveApiBase('  ', ORIGIN)).toEqual({ base: '/api' });
	});

	it('takes a same-origin path or URL, without a trailing slash', () => {
		expect(resolveApiBase('/osp/api', ORIGIN)).toEqual({ base: '/osp/api' });
		expect(resolveApiBase('/osp/api/', ORIGIN)).toEqual({ base: '/osp/api' });
		expect(resolveApiBase(`${ORIGIN}/osp/api`, ORIGIN)).toEqual({ base: '/osp/api' });
		expect(resolveApiBase('/', ORIGIN)).toEqual({ base: '' });
	});

	it.each([
		'https://evil.example/api',
		'//evil.example/api',
		'javascript:alert(1)',
		'/api?x=1',
		'/api#x',
		'https://user:pw@surveys.example.ac.uk/api',
		`/${'a'.repeat(600)}`
	])('refuses %s', (bad) => {
		expect(resolveApiBase(bad, ORIGIN)).toHaveProperty('error');
	});

	it('maps server paths under /api/ onto the base', () => {
		expect(apiUrl('/osp/api', '/api/s/demo/plan/abc')).toBe('/osp/api/s/demo/plan/abc');
		expect(apiUrl('/api', '/api/sessions/resume')).toBe('/api/sessions/resume');
		expect(apiUrl('/osp/api', '/elsewhere/plan.json')).toBe('/elsewhere/plan.json');
	});
});

describe('httpApi with a prefix', () => {
	function recorder() {
		const urls: string[] = [];
		const fetchImpl = (async (url: string) => {
			urls.push(url);
			return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
		}) as unknown as typeof fetch;
		return { urls, fetchImpl };
	}

	it('sends every call and the plan URL under the base', async () => {
		const { urls, fetchImpl } = recorder();
		const api = httpApi('/osp/api', fetchImpl);
		await api.start('my slug');
		await api.resume('tok');
		await api.plan('/api/s/demo/plan/abc');
		await api.submit('s1', 'tok', {} as never);
		expect(urls).toEqual([
			'/osp/api/s/my%20slug/sessions',
			'/osp/api/sessions/resume',
			'/osp/api/s/demo/plan/abc',
			'/osp/api/sessions/s1/submit'
		]);
	});

	it('defaults to /api (make dev, the harness)', async () => {
		const { urls, fetchImpl } = recorder();
		await httpApi(undefined, fetchImpl).start('demo');
		expect(urls).toEqual(['/api/s/demo/sessions']);
	});
});
