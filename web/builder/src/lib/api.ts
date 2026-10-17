// The builder's only route to the backend is the generated client in @osp/api-client.
//
// Where the API lives and how writes prove they came from the page are the host's choice
// (OspPageConfig `apiBase` and `csrf`, planning/pages-split.md F2/F3): every call's `/api`
// prefix is replaced by `apiBase`, and unsafe requests carry `csrf.header` with the
// configured token or the value of the named cookie. No CSRF scheme of our own.
//
// A 401 or 403 is reported to the session (host/session.svelte.ts). Once the session has
// ended, writes are not sent at all: they are answered here with a local 401, so the
// survey store keeps them queued.
import { createApiClient } from '@osp/api-client';
import { allowedUrl, apiPath, type OspPageConfig } from './host/config';
import { pageConfig } from './host/links';
import { session } from './host/session.svelte';

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const DEFAULT_API_BASE = '/api';

/** The value of cookie `name` in `cookies` (document.cookie format), or null. */
export function readCookie(cookies: string, name: string): string | null {
	for (const part of cookies.split(';')) {
		const [k, ...rest] = part.trim().split('=');
		if (k === name) {
			const v = rest.join('=');
			try {
				return v ? decodeURIComponent(v) : null;
			} catch {
				return v || null;
			}
		}
	}
	return null;
}

/** The CSRF header to send on a write, from the host's scheme; null if none is configured. */
export function csrfHeader(
	csrf: OspPageConfig['csrf'],
	cookies: string = typeof document === 'undefined' ? '' : document.cookie
): [string, string] | null {
	if (!csrf) return null;
	const token = csrf.token ?? (csrf.cookie ? readCookie(cookies, csrf.cookie) : null);
	return token ? [csrf.header, token] : null;
}

/** An `/api/...` path (or full URL from the client) rewritten under `apiBase`. */
export function apiUrl(path: string): string {
	return apiPath(pageConfig()?.apiBase ?? DEFAULT_API_BASE, path);
}

function sessionEndedResponse(): Response {
	return new Response(JSON.stringify({ code: 'auth', message: 'Your session ended. Sign in again.' }), {
		status: 401,
		headers: { 'content-type': 'application/json' }
	});
}

async function hostFetch(request: Request): Promise<Response> {
	const cfg = pageConfig();
	const u = new URL(request.url);
	const origin = typeof location === 'undefined' ? u.origin : location.origin;
	const target = new URL(apiPath(cfg?.apiBase ?? DEFAULT_API_BASE, u.pathname) + u.search, origin + '/');
	if (!allowedUrl(target.toString(), origin, cfg?.allowedOrigins ?? [])) {
		throw new Error('API base is not an allowed origin.');
	}
	const unsafe = UNSAFE.has(request.method);
	if (unsafe && session.ended) return sessionEndedResponse();
	const headers = new Headers(request.headers);
	if (unsafe) {
		const h = csrfHeader(cfg?.csrf);
		if (h) headers.set(h[0], h[1]);
	}
	const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
	const response = await fetch(target, {
		method: request.method,
		headers,
		body: hasBody ? await request.blob() : undefined,
		credentials: target.origin === origin ? 'same-origin' : 'include',
		signal: request.signal
	});
	if (response.status === 401) session.unauthenticated();
	else if (response.status === 403) session.forbidden();
	return response;
}

export const api = createApiClient({
	baseUrl: typeof location === 'undefined' ? 'http://localhost' : location.origin,
	fetch: hostFetch
});
