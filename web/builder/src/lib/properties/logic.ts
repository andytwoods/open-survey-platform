/**
 * Pure helpers for the property panel: grouping a schema, reading values, addressing
 * `set_property`, matching diagnostics to fields and shaping translatable text.
 * Display and op-shaping only; validation is the server's job (AGENTS.md rule 8).
 */
import { exprToText } from '../cards/logic';
import {
	CUSTOM_PREFIX,
	type EnumOption,
	type Entity,
	type LocalisedText,
	type PanelDiagnostic,
	type PanelOp,
	type PropertyKind,
	type PropertySpec,
	type TypeSchema
} from './types';

/** Field editor kinds the panel implements (the completeness guard checks this list). */
export const EDITOR_KINDS = [
	'text',
	'richtext',
	'number',
	'bool',
	'enum',
	'choicelist',
	'rows',
	'condition',
	'expression'
] as const satisfies readonly PropertyKind[];

/** Kinds edited elsewhere: the panel shows a button that asks the shell to open the editor. */
export const EXTERNAL_KINDS: readonly PropertyKind[] = ['choicelist', 'rows', 'condition', 'expression'];

/** Pause after the last keystroke before a text buffer is sent (builder-design §4). */
export const TEXT_DEBOUNCE_MS = 600;

const isObj = (v: unknown): v is Record<string, unknown> =>
	typeof v === 'object' && v !== null && !Array.isArray(v);

/** A lab-defined property (`custom.<key>` in an effective schema)? */
export function isCustomKey(key: string): boolean {
	return key.startsWith(CUSTOM_PREFIX) && key.length > CUSTOM_PREFIX.length;
}

/** A group heading: the profile's override for it, else its name. */
export function groupLabel(
	labels: Record<string, LocalisedText> | undefined,
	name: string,
	language: string
): string {
	return (labels && isObj(labels) && localised(labels[name], language)) || name;
}

/** A schema label/help in `language`, falling back to English, then any language. */
export function localised(text: LocalisedText | undefined, language: string): string {
	if (!isObj(text)) return '';
	const pick = text[language] ?? text.en ?? Object.values(text)[0];
	return typeof pick === 'string' ? pick : '';
}

export interface PropertyEntry {
	key: string;
	spec: PropertySpec;
}

export interface PropertyGroup {
	name: string;
	entries: PropertyEntry[];
}

/** Properties grouped by `group`, groups in `order` (unknown groups after, as first seen). */
export function groupProperties(schema: TypeSchema, order: readonly string[]): PropertyGroup[] {
	const byName = new Map<string, PropertyEntry[]>();
	for (const [key, spec] of Object.entries(schema.properties ?? {})) {
		if (!isObj(spec)) continue;
		const name = typeof spec.group === 'string' && spec.group ? spec.group : 'Advanced';
		if (!byName.has(name)) byName.set(name, []);
		byName.get(name)!.push({ key, spec });
	}
	const names = [...order.filter((g) => byName.has(g)), ...[...byName.keys()].filter((g) => !order.includes(g))];
	return names.map((name) => ({ name, entries: byName.get(name)! }));
}

/** Value at a dotted key (`metadata.title`), or undefined. Own keys only. */
export function getAt(obj: unknown, key: string): unknown {
	let cur: unknown = obj;
	for (const part of key.split('.')) {
		if (!isObj(cur) || !Object.hasOwn(cur, part)) return undefined;
		cur = cur[part];
	}
	return cur;
}

/** The value shown for a property: the target's own value, else the schema default. */
export function valueOf(target: unknown, key: string, spec: PropertySpec): unknown {
	const v = getAt(target, key);
	return v === undefined ? spec.default : v;
}

export interface OpAddress {
	target: string;
	property: string;
}

/**
 * Where `set_property` writes a schema key. Questions, pages and blocks are addressed by
 * id; survey keys are `<object>.<field>` on the `/metadata` or `/settings` pseudo-targets.
 * A question's `custom.<key>` (a lab-defined property) keeps its dotted key: `setPropertyOp`
 * turns it into `set_custom_property`. Null when the key can't be addressed (the field is
 * then shown read-only).
 */
export function opAddress(entity: Entity, target: unknown, key: string): OpAddress | null {
	if (entity === 'survey') {
		const parts = key.split('.');
		if (parts.length !== 2) return null;
		return { target: `/${parts[0]}`, property: parts[1] };
	}
	if (!isObj(target) || typeof target.id !== 'string' || !target.id) return null;
	if (key.includes('.') && !(entity === 'question' && isCustomKey(key))) return null;
	return { target: target.id, property: key };
}

/**
 * The op for a value: `set_property`, or `set_custom_property` for a `custom.<key>` address;
 * `undefined` means unset (back to the model default / no value).
 */
export function setPropertyOp(addr: OpAddress, value: unknown): PanelOp {
	if (isCustomKey(addr.property)) {
		const base = { target: addr.target, key: addr.property.slice(CUSTOM_PREFIX.length) };
		if (value === undefined) return { op: 'set_custom_property', params: { ...base, unset: true } };
		return { op: 'set_custom_property', params: { ...base, value } };
	}
	if (value === undefined) return { op: 'set_property', params: { ...addr, unset: true } };
	return { op: 'set_property', params: { ...addr, value } };
}

/** RFC 6901 pointer of a schema key under `base` (the target's own pointer). */
export function propertyPointer(base: string, key: string): string {
	return base + key.split('.').map((p) => '/' + p.replace(/~/g, '~0').replace(/\//g, '~1')).join('');
}

/** Diagnostics about one property: its pointer or anything below it. */
export function diagnosticsFor(
	diagnostics: readonly PanelDiagnostic[] | undefined,
	base: string,
	key: string
): PanelDiagnostic[] {
	const p = propertyPointer(base, key);
	return (diagnostics ?? []).filter(
		(d) => isObj(d) && typeof d.pointer === 'string' && (d.pointer === p || d.pointer.startsWith(p + '/'))
	);
}

/** DOM id for a property's control (dots are fine in ids, but not in CSS selectors). */
export function fieldId(prefix: string, key: string): string {
	return `${prefix}-${key.replace(/[^A-Za-z0-9_-]/g, '-')}`;
}

// --- Text ----------------------------------------------------------------------------

/** The text shown for `language`: a plain string is the same in every language. */
export function textIn(value: unknown, language: string): string {
	if (typeof value === 'string') return value;
	if (isObj(value) && typeof value[language] === 'string') return value[language] as string;
	return '';
}

/** A translation map that has text in some language but not in `language`. */
export function isMissingTranslation(value: unknown, language: string): boolean {
	if (!isObj(value)) return false;
	const has = (l: string) => typeof value[l] === 'string' && (value[l] as string) !== '';
	return !has(language) && Object.keys(value).some(has);
}

/** Text from another language to show as a placeholder when this one is missing. */
export function fallbackText(value: unknown, defaultLanguage: string): string {
	if (!isObj(value)) return '';
	const first = [defaultLanguage, ...Object.keys(value)].find(
		(l) => typeof value[l] === 'string' && value[l] !== ''
	);
	return first ? (value[first] as string) : '';
}

/**
 * The new value of a translatable field after editing it in `language`.
 * A map gets that language set (or removed when emptied); a plain string stays a string
 * when edited in the default language and becomes a map when another language is added.
 * `undefined` means unset.
 */
export function withTranslation(
	old: unknown,
	language: string,
	defaultLanguage: string,
	text: string
): unknown {
	if (isObj(old)) {
		const out: Record<string, string> = {};
		for (const [k, v] of Object.entries(old)) if (typeof v === 'string') out[k] = v;
		if (text === '') delete out[language];
		else out[language] = text;
		return Object.keys(out).length ? out : undefined;
	}
	if (typeof old === 'string' && old !== '') {
		if (language === defaultLanguage) return text === '' ? undefined : text;
		return text === '' ? old : { [defaultLanguage]: old, [language]: text };
	}
	return text === '' ? undefined : { [language]: text };
}

/** The value a text field commits: translated into `language`, or the plain string. */
export function textValue(
	spec: PropertySpec,
	old: unknown,
	language: string,
	defaultLanguage: string,
	text: string
): unknown {
	if (spec.translatable) return withTranslation(old, language, defaultLanguage, text);
	return text === '' ? undefined : text;
}

// --- Numbers, enums, external editors ------------------------------------------------

/** Parsed number from a text input; `undefined` for empty, `null` for not a number. */
export function parseNumber(text: string): number | undefined | null {
	const t = text.trim();
	if (t === '') return undefined;
	const n = Number(t);
	return Number.isFinite(n) ? n : null;
}

export interface ChoiceOption {
	value: string;
	label: string;
}

/** Options of an enum: listed in the schema, or read from the survey (`optionsFrom`). */
export function enumOptions(spec: PropertySpec, survey: unknown, language: string): ChoiceOption[] {
	if (Array.isArray(spec.options)) {
		return spec.options
			.filter((o): o is EnumOption => isObj(o) && typeof o.value === 'string')
			.map((o) => ({ value: o.value, label: localised(o.label, language) || o.value }));
	}
	if (typeof spec.optionsFrom === 'string') {
		const list = getAt(survey, spec.optionsFrom);
		if (Array.isArray(list)) {
			return [...new Set(list.filter((v): v is string => typeof v === 'string'))].map((v) => ({
				value: v,
				label: v
			}));
		}
	}
	return [];
}

export function editorButtonLabel(kind: PropertyKind): string {
	if (kind === 'choicelist') return 'Edit choices…';
	if (kind === 'rows') return 'Edit rows…';
	if (kind === 'condition') return 'Edit condition…';
	return 'Edit expression…';
}

/** One-line, read-only summary of a value edited in a specialised editor. */
export function externalSummary(kind: PropertyKind, value: unknown): string {
	if (kind === 'choicelist') {
		if (!Array.isArray(value) || value.length === 0) return 'No choices';
		return value.length === 1 ? '1 choice' : `${value.length} choices`;
	}
	if (kind === 'rows') {
		if (!Array.isArray(value) || value.length === 0) return 'No rows';
		return value.length === 1 ? '1 row' : `${value.length} rows`;
	}
	if (value === undefined || value === null) return kind === 'condition' ? 'No condition' : 'Not set';
	const text = exprToText(value);
	return text || 'Set';
}
