/**
 * Pure helpers behind the choice list editor (builder-design §3, task B6): code parsing
 * and validation, label text per language, and reading the editor's inputs out of a
 * survey document. Display and pre-send checks only: the server validates every op
 * (AGENTS.md rule 8). Every function accepts hostile input and never throws.
 *
 * Codes follow semantics.md C2-8: `1` and `"1"` are the same code, and a code may not be
 * empty or contain whitespace (XForms stores multi answers space-separated).
 */
import { isRichText, plainTextOf, type RichText } from '@osp/engine';
import type { SpecChoice, SpecChoiceList, SpecText } from '../cards/types';

export type { SpecChoice, SpecChoiceList, SpecText };
/** A label in one language: plain or rich (the editor's `RichValue`). */
export type LabelValue = string | RichText;
export type ChoiceCode = string | number;

/** One op invocation, as the op client sends it (`{ op, params }`). */
export interface ChoiceOp {
	op: string;
	params: Record<string, unknown>;
}

/** A server diagnostic (osp-spec `Diagnostic`). */
export interface ChoiceDiagnostic {
	severity: 'error' | 'warning' | 'info';
	code: string;
	message: string;
	pointer?: string;
}

/** The part of a single/multi question the editor reads. */
export interface ChoiceQuestion {
	id: string;
	type?: string;
	label?: SpecText;
	choices?: readonly SpecChoice[] | null;
	choiceList?: string | null;
}

/** Same pattern as the server's paste parser: an integer code if it looks like one. */
const INT = /^-?[0-9]{1,15}$/;
export const LIST_ID = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** The code a user typed: trimmed, an integer when it looks like one. */
export function parseCode(raw: string): ChoiceCode {
	const t = String(raw ?? '').trim();
	return INT.test(t) ? Number(t) : t;
}

/** Codes compare as text (C2-8: `1` == `"1"`). */
export function codeKey(v: unknown): string {
	return typeof v === 'number' || typeof v === 'string' ? String(v) : JSON.stringify(v) ?? '';
}

export function sameCode(a: unknown, b: unknown): boolean {
	return codeKey(a) === codeKey(b);
}

/** Why a single typed code is not acceptable on its own (empty, whitespace), or null. */
export function codeShapeError(raw: string): string | null {
	const t = String(raw ?? '').trim();
	if (!t) return 'A code is required.';
	if (/\s/.test(t)) return 'Codes cannot contain spaces.';
	return null;
}

/**
 * Per-row errors for a list of typed codes: shape errors first, then duplicates (every
 * row that shares a code with another row is flagged).
 */
export function codeErrors(raws: readonly string[]): (string | null)[] {
	const keys = raws.map((r) => codeKey(parseCode(r)));
	const count = new Map<string, number>();
	for (const k of keys) count.set(k, (count.get(k) ?? 0) + 1);
	return raws.map((r, i) => {
		const shape = codeShapeError(r);
		if (shape) return shape;
		return (count.get(keys[i]) ?? 0) > 1 ? `Code ${keys[i]} is used more than once.` : null;
	});
}

/** A list that mixes integer and text codes (the server warns: `choice.mixed_types`). */
export function mixedTypes(codes: readonly ChoiceCode[]): boolean {
	return new Set(codes.map((c) => typeof c)).size > 1;
}

/** The next integer code after the highest integer code (server `next_code`). */
export function nextCode(choices: readonly { value: unknown }[]): number {
	let max = 0;
	for (const c of choices) if (Number.isSafeInteger(c?.value) && (c.value as number) > max) max = c.value as number;
	return max + 1;
}

const isValue = (v: unknown): v is LabelValue => typeof v === 'string' || isRichText(v);

/**
 * A label's value in exactly `lang` ('' when missing), plain or rich. A value on its own
 * (a string or a tree) is any language's.
 */
export function labelValueIn(label: unknown, lang?: string): LabelValue {
	if (isValue(label)) return label;
	if (!label || typeof label !== 'object' || Array.isArray(label)) return '';
	const map = label as Record<string, unknown>;
	const key = lang ?? Object.keys(map)[0];
	const v = key !== undefined ? map[key] : undefined;
	return isValue(v) ? v : '';
}

/** `labelValueIn` as words (a rich value flattened): for names, descriptions, summaries. */
export function labelIn(label: unknown, lang?: string): string {
	return plainTextOf(labelValueIn(label, lang));
}

/** Some other language's text, shown as a placeholder when `lang` has none yet. */
export function labelFallback(label: unknown, lang?: string): string {
	if (isValue(label) || !label || typeof label !== 'object') return '';
	for (const [k, v] of Object.entries(label as Record<string, unknown>)) {
		if (k === lang || !isValue(v)) continue;
		const text = plainTextOf(v);
		if (text) return text;
	}
	return '';
}

/**
 * `old` with its `lang` value replaced (plain or rich). A value on its own stays so in the
 * default language (or when no language is given); editing another language turns it into
 * a map that keeps the old value under the default language. Other languages' values,
 * rich ones included, are kept.
 */
export function withLabel(old: unknown, value: LabelValue, lang?: string, defaultLanguage?: string): SpecText {
	if (old && typeof old === 'object' && !Array.isArray(old) && !isRichText(old)) {
		const map = old as Record<string, string | RichText>;
		const key = lang ?? defaultLanguage ?? Object.keys(map)[0] ?? 'en';
		return { ...map, [key]: value };
	}
	if (!lang || !defaultLanguage || lang === defaultLanguage) return value;
	return { [defaultLanguage]: isValue(old) ? old : '', [lang]: value };
}

/** Whether two label values are the same text (canonical JSON; `""` and unset agree). */
export function sameLabel(a: unknown, b: unknown): boolean {
	return JSON.stringify(a ?? '') === JSON.stringify(b ?? '');
}

// --- reading the editor's inputs out of a survey document ----------------------------

type Json = Record<string, unknown>;

function isObj(v: unknown): v is Json {
	return !!v && typeof v === 'object' && !Array.isArray(v);
}

function arr(v: unknown): unknown[] {
	return Array.isArray(v) ? v : [];
}

/** Every question in the survey with its RFC 6901 pointer. */
function questions(survey: unknown): { q: Json; pointer: string }[] {
	const out: { q: Json; pointer: string }[] = [];
	if (!isObj(survey)) return out;
	arr(survey.blocks).forEach((b, bi) => {
		if (!isObj(b)) return;
		arr(b.pages).forEach((p, pi) => {
			if (!isObj(p)) return;
			arr(p.items).forEach((q, qi) => {
				if (isObj(q) && typeof q.id === 'string') out.push({ q, pointer: `/blocks/${bi}/pages/${pi}/items/${qi}` });
			});
		});
	});
	return out;
}

function asChoices(v: unknown): SpecChoice[] {
	return arr(v).filter((c): c is SpecChoice => isObj(c) && (typeof c.value === 'string' || typeof c.value === 'number'));
}

export function choiceListsOf(survey: unknown): SpecChoiceList[] {
	if (!isObj(survey)) return [];
	return arr(survey.choiceLists)
		.filter((l): l is Json => isObj(l) && typeof l.id === 'string')
		.map((l) => ({ id: l.id as string, choices: asChoices(l.choices) }));
}

/** Shared list id → ids of the questions that use it (every list has an entry). */
export function listUsage(survey: unknown): Record<string, string[]> {
	const usage: Record<string, string[]> = {};
	for (const l of choiceListsOf(survey)) usage[l.id] = [];
	for (const { q } of questions(survey)) {
		if (typeof q.choiceList === 'string') (usage[q.choiceList] ??= []).push(q.id as string);
	}
	return usage;
}

/** Pointer to the choices the editor shows for `questionId` (inline, or its shared list). */
export function choicesPointer(survey: unknown, questionId: string): string | undefined {
	const found = questions(survey).find(({ q }) => q.id === questionId);
	if (!found) return undefined;
	if (typeof found.q.choiceList === 'string') {
		const i = choiceListsOf(survey).findIndex((l) => l.id === found.q.choiceList);
		return i < 0 ? undefined : `/choiceLists/${i}/choices`;
	}
	return `${found.pointer}/choices`;
}

/** Everything ChoiceListEditor needs about one question, read from the survey document. */
export function editorInputs(survey: unknown, questionId: string) {
	const found = questions(survey).find(({ q }) => q.id === questionId);
	const md = isObj(survey) && isObj(survey.metadata) ? survey.metadata : {};
	const languages = arr(md.languages).filter((l): l is string => typeof l === 'string');
	return {
		question: found
			? ({
					id: questionId,
					type: typeof found.q.type === 'string' ? found.q.type : undefined,
					label: found.q.label as SpecText | undefined,
					choices: found.q.choices == null ? null : asChoices(found.q.choices),
					choiceList: typeof found.q.choiceList === 'string' ? found.q.choiceList : null
				} satisfies ChoiceQuestion)
			: null,
		choiceLists: choiceListsOf(survey),
		usage: listUsage(survey),
		pointer: choicesPointer(survey, questionId),
		languages,
		defaultLanguage: typeof md.defaultLanguage === 'string' ? md.defaultLanguage : languages[0]
	};
}

/** A free shared-list id based on the question id (the user can change it). */
export function suggestListId(questionId: string, taken: Iterable<string>): string {
	const used = new Set(taken);
	const base = (`${questionId}_choices`.replace(/[^A-Za-z0-9_]/g, '_').replace(/^([0-9])/, '_$1')).slice(0, 56);
	if (!used.has(base)) return base;
	for (let n = 2; ; n++) if (!used.has(`${base}_${n}`)) return `${base}_${n}`;
}

/**
 * Split diagnostics into ones about a row (pointer under `${pointer}/<index>`) and the rest.
 * Without a pointer, every diagnostic is general.
 */
export function splitDiagnostics(
	diagnostics: readonly ChoiceDiagnostic[] | null | undefined,
	pointer: string | undefined
): { rows: Map<number, ChoiceDiagnostic[]>; general: ChoiceDiagnostic[] } {
	const rows = new Map<number, ChoiceDiagnostic[]>();
	const general: ChoiceDiagnostic[] = [];
	for (const d of diagnostics ?? []) {
		if (!d || typeof d.message !== 'string') continue;
		const p = typeof d.pointer === 'string' ? d.pointer : '';
		const m = pointer && p.startsWith(`${pointer}/`) ? /^(\d+)(?:\/|$)/.exec(p.slice(pointer.length + 1)) : null;
		if (m) {
			const i = Number(m[1]);
			rows.set(i, [...(rows.get(i) ?? []), d]);
		} else general.push(d);
	}
	return { rows, general };
}
