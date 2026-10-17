/**
 * The host config contract (`OspPageConfig`, planning/pages-split.md F2 + D7). A host page
 * embeds it as `<script type="application/json" id="osp-config">` (or passes it to
 * `mount(el, config)`); every page validates it here before anything runs.
 *
 * Rules: known keys only, typed, length-capped. `apiBase`, every link and the sign-in
 * redirect resolve to the page's own origin unless that origin is listed in
 * `allowedOrigins` (exact origins). Pure: no DOM, so it is unit-tested in node.
 */

export const CONFIG_VERSION = 1;

/** Link names, one per page (`{id}` in a template is replaced by the survey id). */
export const LINK_NAMES = ['list', 'editor', 'flow', 'settings', 'appearance', 'themes', 'previewFrame'] as const;
export type LinkName = (typeof LINK_NAMES)[number];
/** Today's URLs: used by the dev host, and when no config was set (unit tests). */
export const DEFAULT_LINKS: Readonly<Record<LinkName, string>> = {
	list: '/',
	editor: '/surveys/{id}',
	flow: '/surveys/{id}/flow',
	settings: '/surveys/{id}/settings',
	appearance: '/surveys/{id}/appearance',
	themes: '/appearance',
	previewFrame: '/preview-frame'
};
/** Links that point at one survey: their template must contain `{id}`. */
export const SURVEY_LINKS: readonly LinkName[] = ['editor', 'flow', 'settings', 'appearance'];

export interface OspPageConfig {
	version: 1;
	/** Where the osp API lives, e.g. "/osp/api": replaces the `/api` prefix of every call. */
	apiBase: string;
	/** Survey-scoped pages (editor, flow, settings, appearance). */
	surveyId?: string;
	/** Which lab, if the user is in several. A selector only: the API still checks roles. */
	tenantId?: string;
	links: Record<LinkName, string>;
	/** The host's CSRF scheme: `header` carries `token`, or the value of cookie `cookie`. */
	csrf?: { header: string; token?: string; cookie?: string };
	/** After a 401. Default: reload once, so the host's own login runs. */
	onUnauthenticated?: { redirect: string } | 'reload';
	/** Shown in the header, if the host wants. */
	user?: { displayName?: string };
	/** Extra exact origins `apiBase` and the links may use (cross-origin is opt-in, D11). */
	allowedOrigins?: string[];
}

/** The preview frame's config: nothing but the version (D10: no API base, no CSRF). */
export interface OspFrameConfig {
	version: 1;
}

export type Parsed<T> = { ok: true; config: T } | { ok: false; errors: string[] };

const MAX_URL = 2048;
const MAX_ID = 200;
const MAX_TOKEN = 4096;
const MAX_NAME = 200;
const MAX_ORIGINS = 20;
const HEADER_NAME = /^[A-Za-z0-9-]{1,100}$/;
// RFC 6265 cookie-name token characters.
const COOKIE_NAME = /^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,200}$/;
// eslint-disable-next-line no-control-regex -- rejecting control characters is the point
const CONTROL = /[\u0000-\u001f\u007f]/;
const TOP_KEYS = new Set([
	'version',
	'apiBase',
	'surveyId',
	'tenantId',
	'links',
	'csrf',
	'onUnauthenticated',
	'user',
	'allowedOrigins'
]);

function isObject(v: unknown): v is Record<string, unknown> {
	return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function unknownKeys(o: Record<string, unknown>, allowed: Iterable<string>, where: string, errors: string[]) {
	const ok = new Set(allowed);
	for (const k of Object.keys(o)) if (!ok.has(k)) errors.push(`${where}: unknown key "${k}"`);
}

function str(v: unknown, where: string, max: number, errors: string[]): v is string {
	if (typeof v !== 'string') {
		errors.push(`${where}: must be a string`);
		return false;
	}
	if (!v.length || v.length > max) {
		errors.push(`${where}: must be 1–${max} characters`);
		return false;
	}
	if (CONTROL.test(v)) {
		errors.push(`${where}: must not contain control characters`);
		return false;
	}
	return true;
}

/** An exact origin, e.g. "https://osp.example.org" (no path, no trailing slash). */
function isOrigin(v: string): boolean {
	try {
		const u = new URL(v);
		return (u.protocol === 'https:' || u.protocol === 'http:') && u.origin === v;
	} catch {
		return false;
	}
}

/** Resolve `url` against the page; null unless http(s) on an allowed origin. */
export function allowedUrl(url: string, pageOrigin: string, allowedOrigins: readonly string[] = []): URL | null {
	let u: URL;
	try {
		u = new URL(url, pageOrigin + '/');
	} catch {
		return null;
	}
	if (u.protocol !== 'https:' && u.protocol !== 'http:') return null;
	if (u.username || u.password) return null;
	if (u.origin !== pageOrigin && !allowedOrigins.includes(u.origin)) return null;
	return u;
}

function url(v: unknown, where: string, origin: string, allowed: readonly string[], errors: string[]): v is string {
	if (!str(v, where, MAX_URL, errors)) return false;
	if (!allowedUrl(v, origin, allowed)) {
		errors.push(`${where}: must be same-origin (or an origin in allowedOrigins)`);
		return false;
	}
	return true;
}

/** An opaque id from the host: printable, no slash, length-capped. */
function id(v: unknown, where: string, errors: string[]): v is string {
	if (!str(v, where, MAX_ID, errors)) return false;
	if (v.includes('/') || v.includes('\\') || v.trim() !== v) {
		errors.push(`${where}: must not contain slashes or surrounding spaces`);
		return false;
	}
	return true;
}

/**
 * Validate a page config. `pageOrigin` is the page's own origin (`location.origin`);
 * `requireSurveyId` for the survey-scoped pages.
 */
export function parseConfig(
	raw: unknown,
	pageOrigin: string,
	opts: { requireSurveyId?: boolean } = {}
): Parsed<OspPageConfig> {
	const errors: string[] = [];
	if (!isObject(raw)) return { ok: false, errors: ['config: must be a JSON object'] };
	unknownKeys(raw, TOP_KEYS, 'config', errors);
	if (raw.version !== CONFIG_VERSION) errors.push(`version: must be ${CONFIG_VERSION}`);

	// allowedOrigins first: the URL checks below depend on it.
	let allowed: string[] = [];
	if (raw.allowedOrigins !== undefined) {
		const a = raw.allowedOrigins;
		if (!Array.isArray(a) || a.length > MAX_ORIGINS) {
			errors.push(`allowedOrigins: must be an array of at most ${MAX_ORIGINS} origins`);
		} else {
			a.forEach((o, i) => {
				if (typeof o !== 'string' || o.length > MAX_URL || !isOrigin(o)) {
					errors.push(`allowedOrigins[${i}]: must be an exact http(s) origin, e.g. "https://osp.example.org"`);
				}
			});
			if (a.every((o) => typeof o === 'string')) allowed = a as string[];
		}
	}

	url(raw.apiBase, 'apiBase', pageOrigin, allowed, errors);
	if (raw.surveyId !== undefined) id(raw.surveyId, 'surveyId', errors);
	else if (opts.requireSurveyId) errors.push('surveyId: required on this page');
	if (raw.tenantId !== undefined) id(raw.tenantId, 'tenantId', errors);

	if (!isObject(raw.links)) errors.push('links: must be an object');
	else {
		const links = raw.links;
		unknownKeys(links, LINK_NAMES, 'links', errors);
		for (const name of LINK_NAMES) {
			const v = links[name];
			const where = `links.${name}`;
			if (!str(v, where, MAX_URL, errors)) continue;
			if (SURVEY_LINKS.includes(name) && !v.includes('{id}')) {
				errors.push(`${where}: must contain {id}`);
				continue;
			}
			if (!allowedUrl(fillTemplate(v, { id: 'x' }), pageOrigin, allowed)) {
				errors.push(`${where}: must be same-origin (or an origin in allowedOrigins)`);
			}
		}
	}

	if (raw.csrf !== undefined) {
		const c = raw.csrf;
		if (!isObject(c)) errors.push('csrf: must be an object');
		else {
			unknownKeys(c, ['header', 'token', 'cookie'], 'csrf', errors);
			if (typeof c.header !== 'string' || !HEADER_NAME.test(c.header)) {
				errors.push('csrf.header: must be a header name (letters, digits, hyphens)');
			}
			if (c.token !== undefined) str(c.token, 'csrf.token', MAX_TOKEN, errors);
			if (c.cookie !== undefined && (typeof c.cookie !== 'string' || !COOKIE_NAME.test(c.cookie))) {
				errors.push('csrf.cookie: must be a cookie name');
			}
			if (c.token === undefined && c.cookie === undefined) errors.push('csrf: needs a token or a cookie');
		}
	}

	if (raw.onUnauthenticated !== undefined) {
		const o = raw.onUnauthenticated;
		if (o !== 'reload') {
			if (!isObject(o)) errors.push('onUnauthenticated: must be "reload" or { redirect }');
			else {
				unknownKeys(o, ['redirect'], 'onUnauthenticated', errors);
				url(o.redirect, 'onUnauthenticated.redirect', pageOrigin, allowed, errors);
			}
		}
	}

	if (raw.user !== undefined) {
		const u = raw.user;
		if (!isObject(u)) errors.push('user: must be an object');
		else {
			unknownKeys(u, ['displayName'], 'user', errors);
			if (u.displayName !== undefined) str(u.displayName, 'user.displayName', MAX_NAME, errors);
		}
	}

	if (errors.length) return { ok: false, errors };
	return { ok: true, config: structuredClone(raw) as unknown as OspPageConfig };
}

/** The preview frame takes no API base, links or CSRF (D10). */
export function parseFrameConfig(raw: unknown): Parsed<OspFrameConfig> {
	if (raw === undefined || raw === null) return { ok: true, config: { version: 1 } };
	if (!isObject(raw)) return { ok: false, errors: ['config: must be a JSON object'] };
	const errors: string[] = [];
	if (raw.version !== CONFIG_VERSION) errors.push(`version: must be ${CONFIG_VERSION}`);
	for (const k of Object.keys(raw)) {
		if (k !== 'version') errors.push(`config: the preview frame takes no "${k}"`);
	}
	return errors.length ? { ok: false, errors } : { ok: true, config: { version: 1 } };
}

/** Replace `{id}` (URL-encoded) in a link template. */
export function fillTemplate(template: string, params: { id?: string } = {}): string {
	return template.replaceAll('{id}', encodeURIComponent(params.id ?? ''));
}

/** An API path from the generated client (`/api/...`) under the host's `apiBase`. */
export function apiPath(apiBase: string, path: string): string {
	const base = apiBase.replace(/\/+$/, '');
	return path === '/api' || path.startsWith('/api/') || path.startsWith('/api?') ? base + path.slice(4) : path;
}
