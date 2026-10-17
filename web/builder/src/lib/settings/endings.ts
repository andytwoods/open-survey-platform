/**
 * Endings per outcome (end-of-survey plan §4.1, task EN1): pure helpers the Endings section of
 * Survey settings and the flow's End card build on. They only list what the survey already
 * says and shape `set_ending` ops; the server validates every op and reports `ending.*`.
 */
import type { Invocation } from '../sync/transport';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

/** Where an outcome comes from, for the editor's "used by" line. */
export interface OutcomeUse {
	outcome: string;
	/** Human-readable sources: "End node end_1", "Quota q_old (when full)", "Consent decline", "End of the flow". */
	sources: string[];
	/** The consent page's decline: nothing is recorded, so the status line is fixed. */
	declined: boolean;
}

export const HOOK_FAILED = 'hook-failed';

/** Outcomes a session can end with, in a stable order: `complete` first, then flow order. */
export function outcomesInUse(survey: unknown): OutcomeUse[] {
	const out = new Map<string, OutcomeUse>();
	const add = (outcome: string, source: string, declined = false) => {
		const u = out.get(outcome) ?? { outcome, sources: [], declined: false };
		if (!u.sources.includes(source)) u.sources.push(source);
		u.declined ||= declined;
		out.set(outcome, u);
	};
	add('complete', 'End of the flow');
	const s = isObj(survey) ? survey : {};
	if (isObj(s.consent)) {
		const d = typeof s.consent.declineOutcome === 'string' ? s.consent.declineOutcome : 'declined';
		add(d, 'Consent decline', true);
	}
	const checked = new Set<string>();
	const walk = (nodes: unknown[]) => {
		for (const n of nodes) {
			if (!isObj(n)) continue;
			if (n.type === 'end') add(typeof n.outcome === 'string' ? n.outcome : 'complete', `End node ${String(n.id)}`);
			if (n.type === 'quotaCheck' && typeof n.quota === 'string') checked.add(n.quota);
			walk(list(n.then));
			walk(list(n.else));
			walk(list(n.children));
		}
	};
	walk(list(s.flow));
	for (const q of list(s.quotas)) {
		if (isObj(q) && typeof q.id === 'string' && checked.has(q.id) && isObj(q.onFull) && typeof q.onFull.outcome === 'string') {
			add(q.onFull.outcome, `Quota ${q.id} (when full)`);
		}
	}
	return [...out.values()];
}

export function endingsOf(survey: unknown): Record<string, Obj> {
	const settings = isObj(survey) ? survey.settings : undefined;
	const e = isObj(settings) ? settings.endings : undefined;
	if (!isObj(e)) return {};
	return Object.fromEntries(Object.entries(e).filter((kv): kv is [string, Obj] => isObj(kv[1])));
}

export function endingOf(survey: unknown, outcome: string): Obj | null {
	return endingsOf(survey)[outcome] ?? null;
}

/** The ending object after one field changes; an emptied text field is removed. */
export function endingWith(ending: Obj | null, field: string, value: unknown): Obj {
	const next: Obj = { ...(ending ?? {}) };
	if (value === undefined) delete next[field];
	else next[field] = value;
	return next;
}

export function endingOp(outcome: string, ending: Obj | null): Invocation {
	return { op: 'set_ending', params: { outcome, ending } };
}

/** The `#…` Survey settings fragment that opens one outcome's ending. */
export const endingAnchor = (outcome: string) => `ending-${outcome}`;

// -- end redirects (end-of-survey plan §4.2, task EN2) ------------------------------------

/** Default rule for a placeholder value (osp_spec.hooks.DEFAULT_PARAM_PATTERN). */
export const DEFAULT_PARAM_PATTERN = '[A-Za-z0-9_-]{1,64}';
export const MAX_REDIRECT_DELAY = 60;
export const DEFAULT_REDIRECT_DELAY = 5;
/** Built-ins an ending may pipe besides questions and variables (osp_spec ENDING_PIPES). */
export const ENDING_BUILTINS = ['$response.id', '$session.id', '$outcome'] as const;

const PLACEHOLDER = /\{([A-Za-z_][A-Za-z0-9_]{0,31})\}/g;

export function placeholdersOf(url: string): string[] {
	return [...url.matchAll(PLACEHOLDER)].map((m) => m[1]!);
}

/** The host of a template URL, for "Continue to {host}"; empty when it is not a URL. */
export function hostOf(url: string): string {
	try {
		return new URL(url.replace(PLACEHOLDER, 'x')).host;
	} catch {
		return '';
	}
}

export interface RedirectTemplateInfo {
	name: string;
	url: string;
	params: Record<string, { pattern?: string }>;
	/** `settings`: `settings.redirectTemplates` (editable here); `hooks`: `hooks.redirects` (the JSON view). */
	source: 'settings' | 'hooks';
	host: string;
	placeholders: string[];
}

/** Every template an ending may name: the settings ones, then the hooks manifest's. */
export function templatesOf(survey: unknown): RedirectTemplateInfo[] {
	const out: RedirectTemplateInfo[] = [];
	const add = (map: unknown, source: 'settings' | 'hooks') => {
		if (!isObj(map)) return;
		for (const [name, t] of Object.entries(map)) {
			if (!isObj(t) || typeof t.url !== 'string' || out.some((x) => x.name === name)) continue;
			const params = isObj(t.params) ? (t.params as Record<string, { pattern?: string }>) : {};
			out.push({ name, url: t.url, params, source, host: hostOf(t.url), placeholders: placeholdersOf(t.url) });
		}
	};
	const s = isObj(survey) ? survey : {};
	add(isObj(s.settings) ? s.settings.redirectTemplates : undefined, 'settings');
	add(isObj(s.hooks) ? s.hooks.redirects : undefined, 'hooks');
	return out;
}

/**
 * What the researcher sees as the URL: literal values encoded as the app will encode them,
 * piped values left as their `${…}` token (the builder never resolves a pipe).
 */
export function previewUrl(t: Pick<RedirectTemplateInfo, 'url'>, params: Record<string, string>): string {
	return t.url.replace(PLACEHOLDER, (_, n: string) => {
		const v = params[n] ?? '';
		return v.includes('${') ? v : encodeURIComponent(v);
	});
}

/** A quick client-side read of a template before the server checks it in full. */
export function templateProblem(url: string): string | null {
	let u: URL;
	try {
		u = new URL(url.replace(PLACEHOLDER, 'x'));
	} catch {
		return 'Enter a full address, such as https://app.prolific.com/submissions/complete?cc={cc}.';
	}
	if (u.protocol !== 'https:') return 'The address must start with https://.';
	const first = url.indexOf('{');
	if (first >= 0 && first < u.origin.length + 1) return 'A placeholder cannot be part of the site itself (before the first /).';
	if (!url.startsWith(`${u.origin}/`)) return 'The site must be followed by a path, for example https://lab.example.org/done.';
	const names = placeholdersOf(url);
	if (new Set(names).size !== names.length) return 'Each placeholder may appear once.';
	return null;
}

export function redirectTemplateOp(name: string, template: { url: string; params: Record<string, { pattern?: string }> } | null): Invocation {
	return { op: 'set_redirect_template', params: { name, template } };
}

/** The redirect object of an ending, if it has one. */
export function redirectOf(ending: Obj | null): Obj | null {
	const r = ending?.redirect;
	return isObj(r) ? r : null;
}

/** The redirect's params as strings (anything else is treated as empty). */
export function redirectParams(r: Obj | null): Record<string, string> {
	const p = r?.params;
	if (!isObj(p)) return {};
	return Object.fromEntries(Object.entries(p).filter((kv): kv is [string, string] => typeof kv[1] === 'string'));
}

/** A fresh redirect for `t`: every placeholder empty, the defaults left implicit. */
export function newRedirect(t: RedirectTemplateInfo): Obj {
	return { template: t.name, params: Object.fromEntries(t.placeholders.map((n) => [n, ''])) };
}
