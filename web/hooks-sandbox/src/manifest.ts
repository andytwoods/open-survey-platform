/**
 * The hook manifest: the researcher's script plus everything it declares at publish
 * (runtime-design.md §7a): handlers with their reads and writes, URL parameters, redirect
 * templates, and parent message types with typed schemas. The host refuses anything a
 * manifest does not declare.
 *
 * The manifest is the survey's own `hooks` field (osp-survey `osp_spec.hooks.Hooks`, task
 * R11); the plan compiler copies it into `plan.hooks`, inside the plan checksum.
 */

import { sha256, toHex, utf8, type Expr, type FlowNode, type Id, type Plan } from '@osp/engine';

export const HOOK_EVENTS = [
	'onStart',
	'onResume',
	'onPageInit',
	'onPageShown',
	'onAnswer',
	'onPageNext',
	'onBack',
	'onValidationError',
	'onBeforeSubmit',
	'onSubmitted'
] as const;
export type HookEvent = (typeof HOOK_EVENTS)[number];

export const DEFAULT_TIMEOUT_MS = 2000;
export const MAX_TIMEOUT_MS = 5000;
export const MAX_SOURCE_BYTES = 256 * 1024;
export const MAX_SCHEMA_DEPTH = 4;
/** Default rule for a redirect placeholder value. */
export const DEFAULT_PARAM_PATTERN = '[A-Za-z0-9_-]{1,64}';

export interface HandlerDecl {
	/** Questions and variables this hook reads; `ctx.results` and `ctx.vars` hold only these. */
	reads: Id[];
	/** Hook variables this hook may set. */
	writes: Id[];
	timeoutMs?: number;
}

export interface RedirectTemplate {
	/** Absolute https URL with `{name}` placeholders after the origin. */
	url: string;
	/** Every placeholder, with the pattern its value must match in full. */
	params: Record<string, { pattern?: string }>;
}

/** A small, closed JSON Schema subset. Objects never allow undeclared properties. */
export type PayloadSchema =
	| { type: 'string'; maxLength?: number; pattern?: string; enum?: string[] }
	| { type: 'number' | 'integer'; minimum?: number; maximum?: number }
	| { type: 'boolean' }
	| { type: 'null' }
	| { type: 'object'; properties: Record<string, PayloadSchema>; required?: string[] }
	| { type: 'array'; items: PayloadSchema; maxItems: number };

export interface HookManifest {
	format: 'osp-hooks/1';
	/** The researcher's script. It registers handlers with `osp.on(event, fn)`. */
	source: string;
	handlers: Partial<Record<HookEvent, HandlerDecl>>;
	/** URL parameters `onStart` may see. Undeclared ones are withheld. */
	urlParams?: string[];
	redirects?: Record<string, RedirectTemplate>;
	parent?: { origin: string; messages: Record<string, PayloadSchema> } | null;
	/**
	 * Checksum of `source` an owner confirmed for data exports (redirects, parent
	 * messages). Changing the code without re-confirming switches exports off.
	 */
	exportsConfirmedFor?: string | null;
}

export function sourceChecksum(source: string): string {
	return `sha256:${toHex(sha256(utf8(source)))}`;
}

export function exportsAllowed(m: HookManifest): boolean {
	return typeof m.exportsConfirmedFor === 'string' && m.exportsConfirmedFor === sourceChecksum(m.source);
}

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

function isLocalHttp(u: URL): boolean {
	return u.protocol === 'http:' && (u.hostname === 'localhost' || u.hostname === '127.0.0.1');
}

/** An origin a parent message may go to: https (or http on localhost for development). */
export function checkOrigin(origin: string): boolean {
	try {
		const u = new URL(origin);
		return (u.protocol === 'https:' || isLocalHttp(u)) && u.origin === origin;
	} catch {
		return false;
	}
}

function checkTemplate(t: RedirectTemplate): string | null {
	if (!t || typeof t.url !== 'string' || !t.params || typeof t.params !== 'object') return 'malformed';
	const names = placeholders(t.url);
	if (new Set(names).size !== names.length) return 'duplicate placeholder';
	const declared = Object.keys(t.params);
	if (declared.length !== names.length || names.some((n) => !(n in t.params))) return 'placeholders and params differ';
	for (const n of names) if (!fullMatch(t.params[n]?.pattern)) return `bad pattern for ${n}`;
	let u: URL;
	try {
		u = new URL(t.url.replace(PLACEHOLDER, 'x'));
	} catch {
		return 'not a URL';
	}
	if (u.protocol !== 'https:') return 'not https';
	// Placeholders only after the origin: a value can never change where the URL goes.
	const first = t.url.indexOf('{');
	if (first >= 0 && first < u.origin.length + 1) return 'placeholder in the origin';
	if (!t.url.startsWith(`${u.origin}/`)) return 'origin must be followed by a path';
	return null;
}

function checkSchema(s: PayloadSchema, depth: number): string | null {
	if (!s || typeof s !== 'object') return 'malformed';
	if (depth > MAX_SCHEMA_DEPTH) return 'too deep';
	switch (s.type) {
		case 'string':
			if (s.pattern !== undefined && !fullMatch(s.pattern)) return 'bad pattern';
			return null;
		case 'number':
		case 'integer':
		case 'boolean':
		case 'null':
			return null;
		case 'object':
			if (!s.properties || typeof s.properties !== 'object') return 'object needs properties';
			for (const v of Object.values(s.properties)) {
				const e = checkSchema(v, depth + 1);
				if (e) return e;
			}
			return null;
		case 'array':
			if (!Number.isInteger(s.maxItems) || s.maxItems < 0 || s.maxItems > 1000) return 'array needs maxItems';
			return checkSchema(s.items, depth + 1);
	}
	return 'unknown type';
}

/** Does `value` match `schema` (closed: no extra properties, bounded depth)? */
export function matchesSchema(schema: PayloadSchema, value: unknown, depth = 0): boolean {
	if (depth > MAX_SCHEMA_DEPTH) return false;
	switch (schema.type) {
		case 'string':
			return (
				typeof value === 'string' &&
				value.length <= (schema.maxLength ?? 1000) &&
				(schema.enum === undefined || schema.enum.includes(value)) &&
				(schema.pattern === undefined || !!fullMatch(schema.pattern)?.test(value))
			);
		case 'number':
		case 'integer':
			return (
				typeof value === 'number' &&
				Number.isFinite(value) &&
				(schema.type === 'number' || Number.isSafeInteger(value)) &&
				(schema.minimum === undefined || value >= schema.minimum) &&
				(schema.maximum === undefined || value <= schema.maximum)
			);
		case 'boolean':
			return typeof value === 'boolean';
		case 'null':
			return value === null;
		case 'object': {
			if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
			if (Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null) return false;
			const obj = value as Record<string, unknown>;
			for (const k of Object.keys(obj)) {
				const sub = Object.prototype.hasOwnProperty.call(schema.properties, k) ? schema.properties[k] : undefined;
				if (!sub || !matchesSchema(sub, obj[k], depth + 1)) return false;
			}
			return (schema.required ?? []).every((k) => Object.prototype.hasOwnProperty.call(obj, k));
		}
		case 'array':
			return (
				Array.isArray(value) &&
				value.length <= schema.maxItems &&
				value.every((v) => matchesSchema(schema.items, v, depth + 1))
			);
	}
	return false;
}

/** Problems with a manifest against its plan (empty when it is fine). */
export function checkManifest(plan: Plan, m: HookManifest): string[] {
	const errors: string[] = [];
	if (!m || typeof m !== 'object' || m.format !== 'osp-hooks/1') return ['manifest: not osp-hooks/1'];
	if (typeof m.source !== 'string' || utf8(m.source).length > MAX_SOURCE_BYTES) errors.push('source: missing or too large');
	for (const [ev, h] of Object.entries(m.handlers ?? {})) {
		if (!(HOOK_EVENTS as readonly string[]).includes(ev)) {
			errors.push(`handlers.${ev}: unknown event`);
			continue;
		}
		if (!h || !Array.isArray(h.reads) || !Array.isArray(h.writes)) {
			errors.push(`handlers.${ev}: needs reads and writes`);
			continue;
		}
		for (const id of h.reads) {
			if (!(plan.questions.includes(id) || id in plan.variables)) errors.push(`handlers.${ev}.reads: unknown ${id}`);
		}
		for (const id of h.writes) {
			if (plan.variables[id]?.kind !== 'hook') errors.push(`handlers.${ev}.writes: ${id} is not a hook variable`);
		}
		if (h.writes.length && ev === 'onSubmitted') errors.push('handlers.onSubmitted: may not write variables');
		if (h.timeoutMs !== undefined && !(Number.isInteger(h.timeoutMs) && h.timeoutMs > 0 && h.timeoutMs <= MAX_TIMEOUT_MS)) {
			errors.push(`handlers.${ev}.timeoutMs: 1 … ${MAX_TIMEOUT_MS}`);
		}
	}
	for (const [id, t] of Object.entries(m.redirects ?? {})) {
		const e = checkTemplate(t);
		if (e) errors.push(`redirects.${id}: ${e}`);
	}
	if (m.parent) {
		if (!checkOrigin(m.parent.origin)) errors.push('parent.origin: must be one https origin');
		for (const [type, s] of Object.entries(m.parent.messages ?? {})) {
			const e = checkSchema(s, 0);
			if (e) errors.push(`parent.messages.${type}: ${e}`);
		}
	}
	return errors;
}

/** Fill a declared redirect template. Null when anything is undeclared or does not match. */
export function buildRedirectUrl(m: HookManifest, redirect: { templateId: string; params: Record<string, string> } | null): string | null {
	if (!redirect || !exportsAllowed(m)) return null;
	const t = Object.prototype.hasOwnProperty.call(m.redirects ?? {}, redirect.templateId) ? m.redirects![redirect.templateId] : undefined;
	if (!t || checkTemplate(t)) return null;
	const names = placeholders(t.url);
	const given = Object.keys(redirect.params);
	if (given.length !== names.length || given.some((k) => !names.includes(k))) return null;
	for (const n of names) {
		const v = redirect.params[n];
		if (typeof v !== 'string' || !fullMatch(t.params[n]?.pattern)!.test(v)) return null;
		if (v === '.' || v === '..') return null; // would be collapsed as a path segment (EN2)
	}
	const url = t.url.replace(PLACEHOLDER, (_, n: string) => encodeURIComponent(redirect.params[n]!));
	const origin = new URL(t.url.replace(PLACEHOLDER, 'x')).origin;
	try {
		return new URL(url).origin === origin ? url : null;
	} catch {
		return null;
	}
}

// --- Flow-critical detection (§7a "Timeouts and failure") ------------------------------

function refsOf(e: Expr | undefined, out: Set<string>): void {
	if (!e) return;
	switch (e.kind) {
		case 'ref':
			out.add(e.id);
			return;
		case 'compare':
		case 'arith':
			refsOf(e.left, out);
			refsOf(e.right, out);
			return;
		case 'and':
		case 'or':
			for (const a of e.args) refsOf(a, out);
			return;
		case 'not':
			refsOf(e.arg, out);
			return;
		case 'answered':
			out.add(e.ref.id);
			return;
		case 'contains':
			out.add(e.ref.id);
			refsOf(e.value, out);
			return;
	}
}

/**
 * Hook variables that any condition reads (branches, quota conditions, show-if, constraints),
 * directly or through computed variables. A hook writing one is flow-critical.
 */
export function flowCriticalVariables(plan: Plan): Set<Id> {
	const read = new Set<string>();
	const walk = (ns: FlowNode[]) => {
		for (const n of ns) {
			if (n.type === 'branch') {
				refsOf(n.if, read);
				walk(n.then);
				walk(n.else);
			} else if (n.type === 'randomiser') walk(n.children);
		}
	};
	walk(plan.flow);
	for (const q of Object.values(plan.quotas)) refsOf(q.when, read);
	for (const it of Object.values(plan.items)) {
		refsOf(it.showIf, read);
		if (it.type !== 'note' && it.type !== 'matrix') refsOf(it.constraint, read);
	}
	// Computed variables pass reads through (to a fixpoint).
	let grew = true;
	while (grew) {
		grew = false;
		for (const v of Object.values(plan.variables)) {
			if (v.kind !== 'computed' || !read.has(v.id)) continue;
			const before = read.size;
			refsOf(v.expr, read);
			if (read.size > before) grew = true;
		}
	}
	const out = new Set<Id>();
	for (const id of read) if (plan.variables[id]?.kind === 'hook') out.add(id);
	return out;
}

/** Events whose hook writes a flow-critical variable. */
export function criticalEvents(plan: Plan, m: HookManifest): Set<HookEvent> {
	const vars = flowCriticalVariables(plan);
	const out = new Set<HookEvent>();
	for (const [ev, h] of Object.entries(m.handlers ?? {})) {
		if (h?.writes.some((w) => vars.has(w))) out.add(ev as HookEvent);
	}
	return out;
}
