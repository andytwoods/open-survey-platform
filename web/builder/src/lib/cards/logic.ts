/**
 * Pure helpers behind the question cards: family dispatch, badges, condition text form,
 * `${pipe}` tokens. Display-only; nothing here decides survey behaviour (AGENTS.md rule 8).
 * Every function accepts hostile input and never throws.
 */
import { isRichText, plainTextOf } from '@osp/engine';
import {
	FAMILIES,
	type Badge,
	type CardDiagnostic,
	type CardFamily,
	type CardQuestion,
	type ExprNode,
	type PropertySchemaData,
	type SpecChoice,
	type SpecChoiceList,
	type SpecText
} from './types';

/** Fallback when no schema is given: the families of today's osp-spec types. */
const TYPE_FAMILY: Readonly<Record<string, CardFamily>> = {
	single: 'choice',
	multi: 'choice',
	text: 'text',
	date: 'text',
	integer: 'number',
	decimal: 'number',
	note: 'note',
	matrix: 'matrix',
	slider: 'scale',
	scale: 'scale'
};

export function isFamily(v: unknown): v is CardFamily {
	return typeof v === 'string' && (FAMILIES as readonly string[]).includes(v);
}

/** The card family: explicit prop, then the schema's `family`, then the type; else null. */
export function resolveFamily(
	family: unknown,
	schema: PropertySchemaData | null | undefined,
	question: CardQuestion | null | undefined
): CardFamily | null {
	if (isFamily(family)) return family;
	if (isFamily(schema?.family)) return schema.family;
	const t = question?.type;
	return typeof t === 'string' && Object.hasOwn(TYPE_FAMILY, t) ? TYPE_FAMILY[t] : null;
}

/**
 * Pick one language from translatable text: `lang`, then English, then the first entry.
 * Rich text (planning/rich-text.md, RT2) is flattened to its words: cards show plain text
 * until RT3 renders them rich.
 */
export function textFor(text: unknown, lang = 'en'): string {
	if (typeof text === 'string') return text;
	if (isRichText(text)) return plainTextOf(text);
	if (!text || typeof text !== 'object' || Array.isArray(text)) return '';
	const map = text as Record<string, unknown>;
	for (const key of [lang, 'en', ...Object.keys(map)]) {
		const v = map[key];
		if (typeof v === 'string') return v;
		if (isRichText(v)) return plainTextOf(v);
	}
	return '';
}

export type PipeSegment = { kind: 'text'; text: string } | { kind: 'pipe'; id: string };

const PIPE = /\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g;

/** Split text into literal runs and `${id}` pipe tokens (shown as tokens, never resolved). */
export function pipeSegments(text: string): PipeSegment[] {
	const out: PipeSegment[] = [];
	let last = 0;
	for (const m of text.matchAll(PIPE)) {
		const at = m.index ?? 0;
		if (at > last) out.push({ kind: 'text', text: text.slice(last, at) });
		out.push({ kind: 'pipe', id: m[1] });
		last = at + m[0].length;
	}
	if (last < text.length) out.push({ kind: 'text', text: text.slice(last) });
	return out;
}

// --- Condition text form (mirrors osp_expr.syntax.to_text) ------------------------------

const P_OR = 1;
const P_AND = 2;
const P_NOT = 3;
const P_CMP = 4;
const P_SUM = 5;
const P_PROD = 6;
const P_ATOM = 7;
const MAX_DEPTH = 64;

function prec(n: ExprNode): number {
	switch (n.kind) {
		case 'or':
			return P_OR;
		case 'and':
			return P_AND;
		case 'not':
			return P_NOT;
		case 'compare':
			return P_CMP;
		case 'arith':
			return n.op === '+' || n.op === '-' ? P_SUM : P_PROD;
		default:
			return P_ATOM;
	}
}

function textLiteral(v: string): string {
	let s = '"';
	for (const ch of v) {
		const c = ch.codePointAt(0)!;
		if (ch === '"') s += '\\"';
		else if (ch === '\\') s += '\\\\';
		else if (ch === '\n') s += '\\n';
		else if (ch === '\r') s += '\\r';
		else if (ch === '\t') s += '\\t';
		else if (c < 0x20 || c === 0x7f) s += `\\u${c.toString(16).padStart(4, '0')}`;
		else s += ch;
	}
	return s + '"';
}

const isNode = (v: unknown): v is ExprNode =>
	!!v && typeof v === 'object' && typeof (v as ExprNode).kind === 'string';

function refId(v: unknown): string {
	return isNode(v) && typeof v.id === 'string' ? v.id : '?';
}

function print(n: unknown, minPrec: number, depth: number): string {
	if (!isNode(n) || depth > MAX_DEPTH) return '?';
	const d = depth + 1;
	let t: string;
	switch (n.kind) {
		case 'int':
			t = String(n.value);
			break;
		case 'decimal': {
			const v = String(n.value);
			t = /[.eE]/.test(v) ? v : `${v}.0`;
			break;
		}
		case 'text':
			t = textLiteral(String(n.value ?? ''));
			break;
		case 'bool':
			t = n.value ? 'true' : 'false';
			break;
		case 'null':
			t = 'null';
			break;
		case 'ref':
			t = refId(n);
			break;
		case 'answered':
			t = `answered(${refId(n.ref)})`;
			break;
		case 'contains':
			t = `contains(${refId(n.ref)}, ${print(n.value, P_OR, d)})`;
			break;
		case 'or':
		case 'and': {
			const args = Array.isArray(n.args) ? n.args : [];
			const inner = n.kind === 'or' ? P_AND : P_NOT;
			t = args.map((a) => print(a, inner, d)).join(` ${n.kind} `);
			break;
		}
		case 'not':
			t = `not ${print(n.arg, P_NOT, d)}`;
			break;
		case 'compare':
			t = `${print(n.left, P_SUM, d)} ${String(n.op)} ${print(n.right, P_SUM, d)}`;
			break;
		case 'arith': {
			const p = prec(n);
			t = `${print(n.left, p, d)} ${String(n.op)} ${print(n.right, p + 1, d)}`;
			break;
		}
		default:
			return '?';
	}
	return prec(n) < minPrec ? `(${t})` : t;
}

/** Canonical text form of a condition, as the condition builder's text view shows it. */
export function exprToText(expr: unknown): string {
	return print(expr, P_OR, 0);
}

// --- Badges -----------------------------------------------------------------------------

/** True unless a schema is given and does not list `key` as an editable property. */
function schemaHas(schema: PropertySchemaData | null | undefined, key: string): boolean {
	const props = schema?.properties;
	return !props || typeof props !== 'object' || Object.hasOwn(props, key);
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`;

/** Badges shown on a card, in display order. Export warnings (B10) come in through a slot. */
export function badgesFor(
	question: CardQuestion | null | undefined,
	schema?: PropertySchemaData | null,
	diagnostics?: readonly CardDiagnostic[] | null
): Badge[] {
	const out: Badge[] = [];
	const diags = Array.isArray(diagnostics) ? diagnostics : [];
	const errors = diags.filter((d) => d?.severity === 'error').length;
	const warnings = diags.filter((d) => d?.severity === 'warning').length;
	if (errors) out.push({ kind: 'errors', label: plural(errors, 'error'), tone: 'danger' });
	if (warnings) out.push({ kind: 'warnings', label: plural(warnings, 'warning'), tone: 'warning' });
	if (!question || typeof question !== 'object') return out;

	if (isNode(question.showIf) && schemaHas(schema, 'showIf')) {
		out.push({ kind: 'showIf', label: 'Show if', detail: exprToText(question.showIf), tone: 'neutral' });
	}
	if (question.choiceOrder === 'shuffle' && schemaHas(schema, 'choiceOrder')) {
		out.push({ kind: 'shuffle', label: 'Shuffled choices', tone: 'neutral' });
	}
	if (isNode(question.constraint) && schemaHas(schema, 'constraint')) {
		out.push({
			kind: 'validation',
			label: 'Validation',
			detail: exprToText(question.constraint),
			tone: 'neutral'
		});
	}
	return out;
}

// --- Preview data -----------------------------------------------------------------------

export interface PreviewChoice {
	value: string;
	label: string;
}

function toPreview(list: unknown, lang: string): PreviewChoice[] {
	if (!Array.isArray(list)) return [];
	return list
		.filter((c): c is SpecChoice => !!c && typeof c === 'object')
		.map((c, i) => ({
			value: c.value === undefined || c.value === null ? `#${i}` : String(c.value),
			label: textFor(c.label as SpecText, lang)
		}))
		.filter((c, i, all) => all.findIndex((o) => o.value === c.value) === i);
}

/** Inline choices, or the shared list the question points at (when the caller passes it). */
export function choicesFor(
	question: CardQuestion,
	choiceLists: readonly SpecChoiceList[] = [],
	lang = 'en'
): { choices: PreviewChoice[]; sharedList: string | null } {
	if (Array.isArray(question.choices)) return { choices: toPreview(question.choices, lang), sharedList: null };
	const id = typeof question.choiceList === 'string' ? question.choiceList : null;
	const list = id ? choiceLists.find((l) => l?.id === id) : undefined;
	return { choices: toPreview(list?.choices, lang), sharedList: id };
}

/** Matrix rows (sub-questions), keyed by row id; rows without an id or repeated are dropped. */
export function rowsFor(question: CardQuestion, lang = 'en'): PreviewChoice[] {
	const rows = Array.isArray(question.rows) ? question.rows : [];
	return rows
		.filter((r): r is { id: string; label: SpecText } => !!r && typeof r === 'object' && typeof r.id === 'string' && r.id !== '')
		.map((r) => ({ value: r.id, label: textFor(r.label, lang) }))
		.filter((r, i, all) => all.findIndex((o) => o.value === r.value) === i);
}

/**
 * Slider range, made safe for the widget (finite, min < max, step > 0). Numbers may be
 * decimal text (osp-spec `DecimalText`); defaults are the model's (0, 100, 1).
 */
export function scaleRange(question: CardQuestion): { min: number; max: number; step: number } {
	const num = (v: unknown, d: number) => {
		const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN;
		return Number.isFinite(n) ? n : d;
	};
	const min = num(question.min, 0);
	let max = num(question.max, 100);
	if (max <= min) max = min + 1;
	let step = num(question.step, 1);
	if (step <= 0 || step > max - min) step = 1;
	return { min, max, step };
}

/** Attributes for a card's select button: the props minus card-only data. */
export function withoutCardData<T extends object>(props: T): Omit<T, 'choiceLists'> {
	const out = { ...props } as Record<string, unknown>;
	delete out.choiceLists;
	return out as Omit<T, 'choiceLists'>;
}
