/**
 * Where the participant app finds osp-api (planning/pages-split.md D15).
 *
 * Default `/api`. A host that forwards the API under another prefix sets it on the mount:
 * `<div id="app" data-api-base="/osp/api"></div>` in the `index.html` it serves. The value
 * must be same-origin: a path (`/osp/api`) or a URL on the page's own origin. There is no
 * cross-origin allowlist here: the participant page's CSP says `connect-src 'self'`, and
 * participant requests never need another origin. A bad value stops the app with an
 * error instead of quietly calling somewhere else.
 */

export const DEFAULT_API_BASE = '/api';
const MAX_LEN = 512;

/** The API prefix (no trailing slash), or an error message. */
export function resolveApiBase(raw: string | null | undefined, pageOrigin: string): { base: string } | { error: string } {
	if (raw === null || raw === undefined) return { base: DEFAULT_API_BASE };
	const v = raw.trim();
	if (!v) return { base: DEFAULT_API_BASE };
	if (v.length > MAX_LEN) return { error: 'data-api-base is too long' };
	let u: URL;
	try {
		u = new URL(v, pageOrigin + '/');
	} catch {
		return { error: 'data-api-base is not a URL or path' };
	}
	if (u.protocol !== 'https:' && u.protocol !== 'http:') return { error: 'data-api-base must be http(s)' };
	if (u.origin !== pageOrigin) return { error: 'data-api-base must be on this page’s origin' };
	if (u.username || u.password || u.search || u.hash || v.includes('?') || v.includes('#')) {
		return { error: 'data-api-base must be a plain path, without query or fragment' };
	}
	const path = u.pathname.replace(/\/+$/, '');
	return { base: path || '' };
}

/**
 * The server's own URLs are under `/api/` (e.g. `planUrl`). Behind a prefix they are
 * reached under `base` instead; anything else is used as given.
 */
export function apiUrl(base: string, serverPath: string): string {
	return serverPath.startsWith('/api/') ? base + serverPath.slice(4) : serverPath;
}
