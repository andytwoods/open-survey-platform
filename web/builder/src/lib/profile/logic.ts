/**
 * Pure helpers for the lab panel profile editor (task B21, planning/property-profiles.md).
 *
 * The editor holds a `ProfileDraft`: the profile document with `hidden` expanded to one
 * entry per type (`"<type>.<key>"`, never `"*"`), so a checkbox per type can toggle it, and
 * with every custom property as a row. `toProfile` compacts it back to the document the API
 * takes. Display and document shaping only: validation is the server's job (AGENTS.md rule
 * 8); it answers with diagnostics the page shows.
 */
import type { PropertySchemasDoc, PropertySpec, TypeSchema } from '../properties/types';

export const PROFILE_VERSION = 'osp-panel-profile/0.1';
export const CUSTOM_KINDS = ['text', 'number', 'bool', 'choice'] as const;
export type CustomKind = (typeof CUSTOM_KINDS)[number];
export const CUSTOM_KEY = /^[a-z][a-z0-9_]{0,39}$/;

export interface CustomOption {
	value: string;
	label: string;
}

/** One lab-defined property, as the editor shows it (labels in the editing language). */
export interface CustomRow {
	key: string;
	kind: CustomKind;
	label: string;
	help: string;
	/** Empty: every question type. */
	types: string[];
	options: CustomOption[];
	/** As typed; parsed by kind in `toProfile`. */
	defaultText: string;
	group: string;
	required: boolean;
}

export interface ProfileDraft {
	/** `"<type>.<key>"` only (star entries expanded against the stock schemas). */
	hidden: Set<string>;
	/** Per type: every property key of that type, in display order. */
	order: Record<string, string[]>;
	/** Group name -> heading override (editing language). */
	groups: Record<string, string>;
	/** Question type -> property key -> default value (as typed, parsed by `toProfile`). */
	defaults: Record<string, Record<string, string>>;
	custom: CustomRow[];
}

/** The document the API takes and returns. Loosely typed: the server validates. */
export interface ProfileDocument {
	profileVersion?: string;
	hidden?: string[];
	order?: Record<string, string[]>;
	groups?: Record<string, Record<string, string>>;
	defaults?: Record<string, Record<string, unknown>>;
	custom?: Record<string, unknown>[];
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

function text(v: unknown, language: string): string {
	if (typeof v === 'string') return v;
	if (isObj(v)) {
		const pick = v[language] ?? v.en ?? Object.values(v)[0];
		return typeof pick === 'string' ? pick : '';
	}
	return '';
}

/** Stock schemas (the `/api/meta/property-schemas` document) by type. */
export function stockSchemas(doc: PropertySchemasDoc): Record<string, TypeSchema> {
	return Object.fromEntries(doc.schemas.map((s) => [s.type, s]));
}

export function questionTypes(doc: PropertySchemasDoc): string[] {
	return doc.schemas.filter((s) => s.entity === 'question').map((s) => s.type);
}

/** Kinds a default can be typed for in the editor (external editors have none). */
export const DEFAULTABLE_KINDS = new Set(['text', 'richtext', 'number', 'bool', 'enum']);

/** A stored default value as the text the editor shows. */
export function defaultToText(v: unknown): string {
	if (v === undefined || v === null) return '';
	if (typeof v === 'string') return v;
	if (typeof v === 'number' || typeof v === 'boolean') return String(v);
	if (isObj(v) && typeof v.en === 'string') return v.en;
	return JSON.stringify(v);
}

/** The value a typed default means for a property of `spec` (undefined: none). */
export function parseDefault(spec: PropertySpec | undefined, raw: string): unknown {
	const t = raw.trim();
	if (t === '' || !spec) return undefined;
	switch (spec.kind) {
		case 'number': {
			const n = Number(t);
			return Number.isFinite(n) ? n : undefined;
		}
		case 'bool':
			return t === 'true' ? true : t === 'false' ? false : undefined;
		case 'enum': {
			const opt = spec.options?.find((o) => o.value === t);
			return opt ? opt.value : t;
		}
		default:
			return raw;
	}
}

/** The value a typed custom default means (undefined: none, or unparseable). */
export function parseCustomDefault(row: CustomRow): unknown {
	const t = row.defaultText.trim();
	if (t === '') return undefined;
	switch (row.kind) {
		case 'number': {
			const n = Number(t);
			return Number.isFinite(n) ? n : undefined;
		}
		case 'bool':
			return t === 'true' ? true : t === 'false' ? false : undefined;
		case 'choice':
			return row.options.some((o) => o.value === t) ? t : undefined;
		default:
			return row.defaultText;
	}
}

/** Options as one `value = label` per line (the editor's textarea form). */
export function optionsToText(options: CustomOption[]): string {
	return options.map((o) => (o.label && o.label !== o.value ? `${o.value} = ${o.label}` : o.value)).join('\n');
}

export function parseOptions(textarea: string): CustomOption[] {
	const out: CustomOption[] = [];
	for (const line of textarea.split('\n')) {
		const t = line.trim();
		if (!t) continue;
		const eq = t.indexOf('=');
		const value = (eq < 0 ? t : t.slice(0, eq)).trim();
		const label = (eq < 0 ? t : t.slice(eq + 1)).trim() || value;
		if (value && !out.some((o) => o.value === value)) out.push({ value, label });
	}
	return out;
}

export function emptyRow(): CustomRow {
	return { key: '', kind: 'text', label: '', help: '', types: [], options: [], defaultText: '', group: 'Advanced', required: false };
}

/** A fresh draft from a profile document (null: the stock panel) and the stock schemas. */
export function toDraft(profile: ProfileDocument | null, stock: Record<string, TypeSchema>, language: string): ProfileDraft {
	const p = profile ?? {};
	const hidden = new Set<string>();
	for (const ref of p.hidden ?? []) {
		if (typeof ref !== 'string') continue;
		const dot = ref.indexOf('.');
		if (dot < 0) continue;
		const type = ref.slice(0, dot);
		const key = ref.slice(dot + 1);
		const targets = type === '*' ? Object.keys(stock) : [type];
		for (const t of targets) if (stock[t]?.properties[key] && !stock[t].properties[key].required) hidden.add(`${t}.${key}`);
	}
	const order: Record<string, string[]> = {};
	for (const [type, s] of Object.entries(stock)) {
		const listed = (p.order?.[type] ?? p.order?.['*'] ?? []).filter((k) => k in s.properties);
		order[type] = [...listed, ...Object.keys(s.properties).filter((k) => !listed.includes(k))];
	}
	const groups: Record<string, string> = {};
	for (const [g, label] of Object.entries(p.groups ?? {})) groups[g] = text(label, language);
	const defaults: Record<string, Record<string, string>> = {};
	for (const [type, values] of Object.entries(p.defaults ?? {})) {
		if (!isObj(values)) continue;
		defaults[type] = {};
		for (const [k, v] of Object.entries(values)) defaults[type][k] = defaultToText(v);
	}
	const custom: CustomRow[] = [];
	for (const c of p.custom ?? []) {
		if (!isObj(c)) continue;
		const kind = CUSTOM_KINDS.includes(c.kind as CustomKind) ? (c.kind as CustomKind) : 'text';
		const options = Array.isArray(c.options)
			? c.options.filter(isObj).map((o) => ({ value: String(o.value ?? ''), label: text(o.label, language) }))
			: [];
		custom.push({
			key: typeof c.key === 'string' ? c.key : '',
			kind,
			label: text(c.label, language),
			help: text(c.help, language),
			types: Array.isArray(c.types) ? c.types.filter((t): t is string => typeof t === 'string') : [],
			options,
			defaultText: defaultToText(c.default),
			group: typeof c.group === 'string' ? c.group : 'Advanced',
			required: c.required === true
		});
	}
	return { hidden, order, groups, defaults, custom };
}

/**
 * The profile document for a draft. `hidden` entries hidden on every type that has the key
 * compact to `"*.<key>"`; an order equal to the stock order is dropped; a typed default
 * that parses to nothing is dropped.
 */
export function toProfile(d: ProfileDraft, stock: Record<string, TypeSchema>, language: string): ProfileDocument {
	const hidden: string[] = [];
	const byKey = new Map<string, string[]>();
	for (const ref of [...d.hidden].sort()) {
		const dot = ref.indexOf('.');
		const key = ref.slice(dot + 1);
		if (!byKey.has(key)) byKey.set(key, []);
		byKey.get(key)!.push(ref.slice(0, dot));
	}
	for (const [key, types] of byKey) {
		const having = Object.keys(stock).filter((t) => stock[t].properties[key] && !stock[t].properties[key].required);
		if (having.length > 1 && having.every((t) => types.includes(t))) hidden.push(`*.${key}`);
		else for (const t of types) hidden.push(`${t}.${key}`);
	}
	const order: Record<string, string[]> = {};
	for (const [type, keys] of Object.entries(d.order)) {
		const s = stock[type];
		if (!s) continue;
		const stockOrder = Object.keys(s.properties);
		if (keys.join('\u0000') !== stockOrder.join('\u0000')) order[type] = keys;
	}
	const groups: Record<string, Record<string, string>> = {};
	for (const [g, label] of Object.entries(d.groups)) if (label.trim()) groups[g] = { [language]: label.trim() };
	const defaults: Record<string, Record<string, unknown>> = {};
	for (const [type, values] of Object.entries(d.defaults)) {
		const s = stock[type];
		if (!s || s.entity !== 'question') continue;
		for (const [k, raw] of Object.entries(values)) {
			const v = parseDefault(s.properties[k], raw);
			if (v !== undefined) (defaults[type] ??= {})[k] = v;
		}
	}
	const custom = d.custom.map((c) => {
		const out: Record<string, unknown> = {
			key: c.key.trim(),
			kind: c.kind,
			label: { [language]: c.label.trim() || c.key.trim() },
			group: c.group
		};
		if (c.help.trim()) out.help = { [language]: c.help.trim() };
		if (c.types.length) out.types = c.types;
		if (c.kind === 'choice') out.options = c.options.map((o) => ({ value: o.value, label: { [language]: o.label || o.value } }));
		const def = parseCustomDefault(c);
		if (def !== undefined) out.default = def;
		if (c.required) out.required = true;
		return out;
	});
	const doc: ProfileDocument = { profileVersion: PROFILE_VERSION };
	if (hidden.length) doc.hidden = hidden;
	if (Object.keys(order).length) doc.order = order;
	if (Object.keys(groups).length) doc.groups = groups;
	if (Object.keys(defaults).length) doc.defaults = defaults;
	if (custom.length) doc.custom = custom;
	return doc;
}

/** Problems the editor can see before asking the server (the server is the judge). */
export function localProblems(d: ProfileDraft): string[] {
	const out: string[] = [];
	const keys = new Set<string>();
	d.custom.forEach((c, i) => {
		const key = c.key.trim();
		const where = `Custom property ${i + 1}`;
		if (!CUSTOM_KEY.test(key)) out.push(`${where}: the key must be 1–40 lower-case letters, digits or _, starting with a letter.`);
		else if (keys.has(key)) out.push(`${where}: the key "${key}" is used twice.`);
		keys.add(key);
		if (c.kind === 'choice' && c.options.length === 0) out.push(`${where}: a choice property needs at least one option.`);
		if (c.defaultText.trim() && parseCustomDefault(c) === undefined) out.push(`${where}: the default does not fit a ${c.kind} property.`);
	});
	return out;
}

/** Move `key` one step up or down in a type's order (a new array; unchanged at the ends). */
export function moveKey(keys: string[], key: string, dir: -1 | 1): string[] {
	const i = keys.indexOf(key);
	const j = i + dir;
	if (i < 0 || j < 0 || j >= keys.length) return keys;
	const out = [...keys];
	[out[i], out[j]] = [out[j], out[i]];
	return out;
}

/** Whether two documents mean the same profile (key order ignored). */
export function sameProfile(a: ProfileDocument | null, b: ProfileDocument | null): boolean {
	return canonical(a ?? { profileVersion: PROFILE_VERSION }) === canonical(b ?? { profileVersion: PROFILE_VERSION });
}

function canonical(v: unknown): string {
	if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
	if (isObj(v))
		return `{${Object.keys(v)
			.sort()
			.filter((k) => v[k] !== undefined)
			.map((k) => `${JSON.stringify(k)}:${canonical(v[k])}`)
			.join(',')}}`;
	return JSON.stringify(v);
}
