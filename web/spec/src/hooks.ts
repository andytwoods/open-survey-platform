/**
 * Researcher hooks, semantic checks (osp_spec.hooks: placeholders, redirect templates, the
 * parent origin, handler reads/writes). The `re` patterns are written for JavaScript with
 * Python's meaning: `\d` is any Unicode decimal digit, `\S` any non-`isspace` character and
 * `$` also matches before one final newline.
 */

import { pointer } from './diagnostics.ts';
import { asciiDigits, DIGIT_CLASS, PY_SPACE_CLASS } from './py.ts';
import { compileFull } from './pyregex.ts';
import type { Emit } from './richtext.ts';

export const DEFAULT_PARAM_PATTERN = '[A-Za-z0-9_-]{1,64}';

export interface RedirectTemplate {
	url: string;
	params: Map<string, { pattern: string | null }>;
}

const PLACEHOLDER = /\{([A-Za-z_][A-Za-z0-9_]{0,31})\}/g;
const END = '(?=\\n?$)';
const ORIGIN = new RegExp(
	`^(https?)://((?:[a-z0-9-]+\\.)*[a-z0-9-]+|\\[[0-9a-f:.]+\\])(?::([${DIGIT_CLASS}]{1,5}))?${END}`,
	'u'
);
const HTTPS_URL = new RegExp(
	`^https://((?:[A-Za-z0-9-]+\\.)*[A-Za-z0-9-]+|\\[[0-9A-Fa-f:.]+\\])(?::([${DIGIT_CLASS}]{1,5}))?(/[^${PY_SPACE_CLASS}]*)?${END}`,
	'u'
);
const SCHEME = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//;
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1']);

export function placeholders(url: string): string[] {
	return Array.from(url.matchAll(PLACEHOLDER), (m) => m[1]!);
}

/** `_pattern_ok`: the pattern compiles as a Python regex (null: the default). */
export function patternOk(pattern: string | null): boolean {
	return compileFull(pattern === null ? DEFAULT_PARAM_PATTERN : pattern) !== null;
}

export function originOk(origin: string): boolean {
	const m = ORIGIN.exec(origin);
	if (!m) return false;
	const [, scheme, host, port] = m;
	if (port !== undefined && (Number(asciiDigits(port)) > 65535 || port === (scheme === 'https' ? '443' : '80'))) {
		return false;
	}
	return scheme === 'https' || LOCAL_HOSTS.has(host!);
}

export function templateOrigin(url: string): string | null {
	const m = HTTPS_URL.exec(url.replace(PLACEHOLDER, 'x'));
	if (!m) return null;
	const [, host, port] = m;
	return `https://${host!.toLowerCase()}` + (port && port !== '443' ? `:${port}` : '');
}

export function redirectProblem(t: RedirectTemplate): string | null {
	const names = placeholders(t.url);
	if (new Set(names).size !== names.length) return 'duplicate placeholder';
	if (t.params.size !== names.length || names.some((n) => !t.params.has(n))) return 'placeholders and params differ';
	for (const n of names) {
		if (!patternOk(t.params.get(n)!.pattern)) return `bad pattern for ${n}`;
	}
	const filled = t.url.replace(PLACEHOLDER, 'x');
	const origin = templateOrigin(t.url);
	if (origin === null) return SCHEME.test(filled) ? 'not https' : 'not a URL';
	const first = Array.from(t.url).indexOf('{');
	if (first >= 0 && first < Array.from(origin).length + 1) return 'placeholder in the origin';
	if (!t.url.startsWith(origin + '/')) return 'origin must be followed by a path';
	return null;
}

export interface HooksDoc {
	handlers: Map<string, { reads: string[]; writes: string[] }>;
	redirects: Map<string, RedirectTemplate> | null;
	parent: { origin: string } | null;
}

export function checkHooks(hooks: HooksDoc, readable: Iterable<string>, hookVariables: Iterable<string>, emit: Emit): void {
	const canRead = new Set(readable);
	const canWrite = new Set(hookVariables);
	for (const [ev, h] of hooks.handlers) {
		const hp = pointer('hooks', 'handlers', ev);
		h.reads.forEach((rid, i) => {
			if (!canRead.has(rid)) {
				emit('hooks.unknown_ref', hp + pointer('reads', i), `'${rid}' is not a question or variable a hook can read`);
			}
		});
		h.writes.forEach((wid, i) => {
			if (!canWrite.has(wid)) {
				emit(
					'hooks.write_target',
					hp + pointer('writes', i),
					`'${wid}' is not a hook variable (hooks may set only hook variables; osp-survey/0.1 declares none yet)`
				);
			} else if (ev === 'onSubmitted') {
				emit('hooks.write_target', hp + pointer('writes', i), 'onSubmitted may not write variables');
			}
		});
	}
	for (const [rid, t] of hooks.redirects ?? new Map<string, RedirectTemplate>()) {
		const why = redirectProblem(t);
		if (why !== null) emit('hooks.redirect', pointer('hooks', 'redirects', rid), `redirect template: ${why}`);
	}
	if (hooks.parent !== null && !originOk(hooks.parent.origin)) {
		emit(
			'hooks.parent_origin',
			pointer('hooks', 'parent', 'origin'),
			'must be one https origin such as https://lab.example.org (http only on localhost)'
		);
	}
}
