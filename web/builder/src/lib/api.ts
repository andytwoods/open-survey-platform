// The builder's only route to the backend is the generated client in @osp/api-client.
import { createApiClient } from '@osp/api-client';

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const CSRF_COOKIE = '__Host-osp_csrf';

let csrfToken: string | null = null;

/** Remember the CSRF token from /api/auth/me or a login response. */
export function setCsrfToken(token: string | null) {
	csrfToken = token;
}

/** The token to send: the one we were given, else the readable CSRF cookie. */
export function currentCsrfToken(): string | null {
	if (csrfToken) return csrfToken;
	if (typeof document === 'undefined') return null;
	for (const part of document.cookie.split(';')) {
		const [name, ...rest] = part.trim().split('=');
		if (name === CSRF_COOKIE) return rest.join('=') || null;
	}
	return null;
}

export const api = createApiClient({ baseUrl: '', credentials: 'same-origin' });

// Every unsafe request carries X-CSRF-Token (osp-api README: cookie auth + CSRF).
api.use({
	onRequest({ request }) {
		if (UNSAFE.has(request.method)) {
			const token = currentCsrfToken();
			if (token) request.headers.set('X-CSRF-Token', token);
		}
		return request;
	}
});
