/**
 * End redirects (end-of-survey plan §4.2, task EN2): filling a declared template with
 * checked values. A template is an absolute https URL with `{name}` placeholders after the
 * origin; every value must match its placeholder's pattern in full and is
 * `encodeURIComponent`-encoded, and the filled URL's origin is compared with the template's
 * before anything navigates. So a value can never change where the participant goes.
 *
 * The same rules as `web/hooks-sandbox/src/manifest.ts` (which checks hook manifests at
 * load time and fills `setEndRedirect`), kept in the engine so the ending screen's redirect
 * is resolved where the pipes are.
 */

import type { RedirectTemplatePlan } from './plan.ts';

/** Default rule for a placeholder value. */
export const DEFAULT_PARAM_PATTERN = '[A-Za-z0-9_-]{1,64}';
/** A value longer than this is refused whatever its pattern (as the hook host caps it). */
export const MAX_PARAM_LENGTH = 256;

const PLACEHOLDER = /\{([A-Za-z_][A-Za-z0-9_]{0,31})\}/g;

export function placeholders(url: string): string[] {
	return [...url.matchAll(PLACEHOLDER)].map((m) => m[1]!);
}

function fullMatch(pattern: string | undefined): RegExp | null {
	try {
		return new RegExp(`^(?:${pattern ?? DEFAULT_PARAM_PATTERN})$`, 'u');
	} catch {
		return null;
	}
}

/** The template's origin (`https://host[:port]`), or null when it is not an https URL. */
export function templateOrigin(url: string): string | null {
	try {
		const u = new URL(url.replace(PLACEHOLDER, 'x'));
		return u.protocol === 'https:' ? u.origin : null;
	} catch {
		return null;
	}
}

/** Why a template is refused, or null when it is fine (as `checkTemplate` in manifest.ts). */
export function checkRedirectTemplate(t: RedirectTemplatePlan): string | null {
	if (!t || typeof t.url !== 'string' || !t.params || typeof t.params !== 'object') return 'malformed';
	const names = placeholders(t.url);
	if (new Set(names).size !== names.length) return 'duplicate placeholder';
	const declared = Object.keys(t.params);
	if (declared.length !== names.length || names.some((n) => !Object.prototype.hasOwnProperty.call(t.params, n))) {
		return 'placeholders and params differ';
	}
	for (const n of names) if (!fullMatch(t.params[n]?.pattern)) return `bad pattern for ${n}`;
	const origin = templateOrigin(t.url);
	if (origin === null) return 'not https';
	// Placeholders only after the origin: a value can never change where the URL goes.
	const first = t.url.indexOf('{');
	if (first >= 0 && first < origin.length + 1) return 'placeholder in the origin';
	if (!t.url.startsWith(`${origin}/`)) return 'origin must be followed by a path';
	return null;
}

export type FilledRedirect = { url: string; rejected: null } | { url: null; rejected: string };

/**
 * Fill `t` with `values` (one per placeholder). `rejected` names the first placeholder
 * whose value is missing, too long or off its pattern, or `$origin` when the filled URL
 * would not stay on the template's origin (which cannot happen after encoding, but is
 * checked anyway). A rejected redirect is neither followed nor shown.
 */
export function fillRedirect(t: RedirectTemplatePlan, values: Record<string, string>): FilledRedirect {
	if (checkRedirectTemplate(t)) return { url: null, rejected: '$template' };
	const names = placeholders(t.url);
	for (const n of names) {
		const v = Object.prototype.hasOwnProperty.call(values, n) ? values[n] : undefined;
		if (typeof v !== 'string' || v.length === 0 || v.length > MAX_PARAM_LENGTH) return { url: null, rejected: n };
		if (!fullMatch(t.params[n]?.pattern)!.test(v)) return { url: null, rejected: n };
		// `.` and `..` survive encoding and would be collapsed as path segments (whatever a
		// permissive pattern allows): the one way a value could still move the path.
		if (v === '.' || v === '..') return { url: null, rejected: n };
	}
	const url = t.url.replace(PLACEHOLDER, (_, n: string) => encodeURIComponent(values[n]!));
	const origin = templateOrigin(t.url);
	try {
		const u = new URL(url);
		if (u.origin !== origin || u.username || u.password) return { url: null, rejected: '$origin' };
	} catch {
		return { url: null, rejected: '$origin' };
	}
	return { url, rejected: null };
}

/** The host name shown to the participant ("Continue to app.prolific.com"). */
export function templateHost(url: string): string {
	try {
		return new URL(url.replace(PLACEHOLDER, 'x')).host;
	} catch {
		return '';
	}
}
