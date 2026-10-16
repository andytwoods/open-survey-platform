import { describe, expect, it } from 'vitest';
import { createApiClient } from './index';

function fakeFetch(body: unknown) {
	const calls: string[] = [];
	const fetch = async (input: Request) => {
		calls.push(new URL(input.url).pathname);
		return new Response(JSON.stringify(body), {
			status: 200,
			headers: { 'content-type': 'application/json' }
		});
	};
	return { calls, fetch };
}

describe('api-client', () => {
	it('calls GET /api/health and returns typed data', async () => {
		const { calls, fetch } = fakeFetch({ status: 'ok' });
		const api = createApiClient({ baseUrl: 'http://test.invalid', fetch });
		const { data, error } = await api.GET('/api/health');
		expect(error).toBeUndefined();
		// Typed as { status: "ok" } from the generated schema.
		const status: 'ok' | undefined = data?.status;
		expect(status).toBe('ok');
		expect(calls).toEqual(['/api/health']);
	});

	it('calls GET /api/version', async () => {
		const { fetch } = fakeFetch({ name: 'osp-api', version: '0.0.0' });
		const api = createApiClient({ baseUrl: 'http://test.invalid', fetch });
		const { data } = await api.GET('/api/version');
		expect(data?.name).toBe('osp-api');
	});
});
