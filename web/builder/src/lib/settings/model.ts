/**
 * Small, pure helpers the Survey settings view builds its ops from. They only shape values
 * for `set_property`, `set_languages` and `set_consent`; the server validates every op.
 */
import { isRichText, type RichText } from '@osp/engine';
import type { TypeSchema } from '../properties/types';
import type { Invocation } from '../sync/transport';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const isText = (v: unknown): v is string | RichText => typeof v === 'string' || isRichText(v);

// -- retention (settings.retention, from GET /api/meta/retention) ------------------------

export interface RetentionKind {
	kind: string;
	label: string;
	description: string;
	field?: 'days' | 'until' | null;
}

export interface RetentionDraft {
	kind: string;
	days: string;
	until: string;
}

export function retentionOf(survey: unknown): RetentionDraft | null {
	const r = isObj(survey) && isObj(survey.settings) ? survey.settings.retention : undefined;
	if (!isObj(r) || typeof r.kind !== 'string') return null;
	return {
		kind: r.kind,
		days: typeof r.days === 'number' ? String(r.days) : '',
		until: typeof r.until === 'string' ? r.until : ''
	};
}

/** The `settings.retention` value for a draft, or null while it is incomplete. */
export function retentionValue(d: RetentionDraft, kinds: readonly RetentionKind[]): Obj | null {
	const k = kinds.find((x) => x.kind === d.kind);
	if (!k) return null;
	if (k.field === 'days') {
		if (!/^\d{1,5}$/.test(d.days.trim())) return null;
		return { kind: k.kind, days: Number(d.days.trim()) };
	}
	if (k.field === 'until') {
		if (!/^\d{4}-\d{2}-\d{2}$/.test(d.until)) return null;
		return { kind: k.kind, until: d.until };
	}
	return { kind: k.kind };
}

export function retentionOp(value: Obj): Invocation {
	return { op: 'set_property', params: { target: '/settings', property: 'retention', value } };
}

// -- languages (metadata.languages / defaultLanguage) ----------------------------------

export function languagesOf(survey: unknown): string[] {
	const m = isObj(survey) ? survey.metadata : undefined;
	return isObj(m) && Array.isArray(m.languages) ? m.languages.filter((l): l is string => typeof l === 'string') : [];
}

export function explicitDefaultOf(survey: unknown): string | null {
	const m = isObj(survey) ? survey.metadata : undefined;
	return isObj(m) && typeof m.defaultLanguage === 'string' ? m.defaultLanguage : null;
}

export function languagesOp(languages: string[], defaultLanguage: string | null, cascade = false): Invocation {
	const params: Obj = { languages };
	if (defaultLanguage && languages.includes(defaultLanguage)) params.default_language = defaultLanguage;
	if (cascade) params.cascade = true;
	return { op: 'set_languages', params };
}

// -- translatable text ------------------------------------------------------------------

/**
 * The value written for exactly `lang` (no fallback), plain or rich (planning/rich-text.md
 * RT2). A plain string or a rich tree on its own belongs to `defaultLang`.
 */
export function richExact(text: unknown, lang: string, defaultLang: string): string | RichText {
	if (isText(text)) return lang === defaultLang ? text : '';
	if (isObj(text) && isText(text[lang])) return text[lang];
	return '';
}

/** Whether two text values (plain or rich) are the same text. */
export function sameText(a: unknown, b: unknown): boolean {
	return JSON.stringify(a ?? '') === JSON.stringify(b ?? '');
}

/** `richExact` as words only (rich values flattened away): for plain inputs. */
export function textExact(text: unknown, lang: string, defaultLang: string): string {
	const v = richExact(text, lang, defaultLang);
	return typeof v === 'string' ? v : '';
}

/**
 * `old` with its `lang` text set to `value` (plain or rich). A value on its own stays so
 * only for the default language; another language turns it into a map. An empty value
 * removes that language. Other languages' rich values are kept.
 */
export function setText(old: unknown, lang: string, defaultLang: string, value: string | RichText): string | RichText | Obj | undefined {
	let map: Record<string, string | RichText> = {};
	if (isText(old)) {
		if (lang === defaultLang) return value === '' ? undefined : value;
		map[defaultLang] = old;
	} else if (isObj(old)) {
		map = Object.fromEntries(Object.entries(old).filter(([, v]) => isText(v))) as Record<string, string | RichText>;
	}
	if (value === '') delete map[lang];
	else map[lang] = value;
	const keys = Object.keys(map);
	if (keys.length === 0) return undefined;
	return map;
}

// -- consent (survey.consent, the set_consent op) -------------------------------------

export const CONSENT_DEFAULTS = {
	agreeLabel: 'I agree',
	declineLabel: 'I do not agree',
	declineOutcome: 'declined',
	countDeclines: false
} as const;

export const CONSENT_TEXT_FIELDS = ['text', 'agreeLabel', 'declineLabel'] as const;
export type ConsentTextField = (typeof CONSENT_TEXT_FIELDS)[number];

export function consentOf(survey: unknown): Obj | null {
	return isObj(survey) && isObj(survey.consent) ? survey.consent : null;
}

/** The consent object after one field changes. Removing the required text is not allowed here. */
export function consentWith(consent: Obj | null, field: string, value: unknown): Obj {
	const next: Obj = { ...(consent ?? { text: '' }) };
	if (value === undefined) delete next[field];
	else next[field] = value;
	return next;
}

export function consentOp(consent: Obj | null): Invocation {
	return { op: 'set_consent', params: { consent } };
}

/** Languages that have consent text missing (the participant would see the fallback). */
export function missingConsentLanguages(consent: Obj | null, languages: readonly string[], defaultLang: string): string[] {
	if (!consent) return [];
	const written = CONSENT_TEXT_FIELDS.filter((f) => f === 'text' || consent[f] !== undefined);
	return languages.filter((l) => written.some((f) => !richExact(consent[f], l, defaultLang)));
}

// -- property schema subsets ----------------------------------------------------------

/** The survey schema narrowed to `keys`, all in one group (for one settings section). */
export function subsetSchema(schema: TypeSchema, keys: readonly string[], group: string, label: string): TypeSchema {
	const properties: TypeSchema['properties'] = {};
	for (const k of keys) {
		const spec = schema.properties[k];
		if (spec) properties[k] = { ...spec, group };
	}
	return { ...schema, label: { en: label }, properties, hidden: {} };
}
