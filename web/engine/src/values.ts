/**
 * Answer values: checking participant input, the stored (JSON) form, and the evaluator form.
 *
 * Stored forms (also the export / fixture form, fixtures/FORMAT.md §3):
 *   integer  JSON integer (safe range)        decimal  canonical decimal text, e.g. "2.5"
 *   text     trimmed text                     single   the choice's code
 *   multi    codes in choice-list order       date     "YYYY-MM-DD"
 * `null` means no answer. Semantics §2: text is trimmed and whitespace-only text is no
 * answer; an empty multi answer is no answer; codes, never labels.
 */

import * as dec from './decimal.ts';
import type { Code, Value } from './expr.ts';
import type { ChoiceValue, QuestionItem } from './plan.ts';

export type Stored = null | number | string | Code[];

/**
 * Trimming (semantics.md §2): the Unicode White_Space characters plus U+FEFF, and nothing
 * else (not U+200B; not U+001C-U+001F, which Python's `str.strip()` and JS `trim()` treat
 * differently). The same list as `osp_expr.values.TRIM_CODE_POINTS`; both are checked
 * against `contract/vectors/trim.json`. Text is never Unicode-normalised.
 */
export const TRIM_CODE_POINTS: readonly number[] = [
	0x0009, 0x000a, 0x000b, 0x000c, 0x000d, 0x0020, 0x0085, 0x00a0, 0x1680, 0x2000, 0x2001, 0x2002,
	0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f,
	0x3000, 0xfeff
];
const TRIM_SET = new Set(TRIM_CODE_POINTS);

/** Remove `TRIM_CODE_POINTS` from both ends of `s` (all are BMP, so code units suffice). */
export function trimAnswer(s: string): string {
	let a = 0;
	let b = s.length;
	while (a < b && TRIM_SET.has(s.charCodeAt(a))) a++;
	while (b > a && TRIM_SET.has(s.charCodeAt(b - 1))) b--;
	return s.slice(a, b);
}

/** \deprecated Use `trimAnswer` (the trim set is no longer Python's `str.strip()`). */
export const pyStrip = trimAnswer;

/** Most significant digits a decimal answer may have (osp_expr.values.DECIMAL_DIGITS). */
export const DECIMAL_DIGITS = 28;

const DECIMAL_INPUT = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;

/**
 * Canonical decimal text (semantics.md §2): no exponent, no `+`, no superfluous leading
 * zeros, no trailing zeros after the point, `0` for any zero. Null if `text` (trimmed) is
 * not `[+-]digits[.digits]` or has more than 28 significant digits. Mirrors
 * `osp_expr.values.canonical_decimal`; both are checked against `contract/vectors/decimal.json`.
 */
export function canonicalDecimal(text: string): string | null {
	const t = trimAnswer(text);
	if (!DECIMAL_INPUT.test(t)) return null;
	const negative = t.startsWith('-');
	const body = t.replace(/^[+-]/, '');
	const dot = body.indexOf('.');
	let int = dot < 0 ? body : body.slice(0, dot);
	let frac = dot < 0 ? '' : body.slice(dot + 1);
	int = int.replace(/^0+/, '');
	frac = frac.replace(/0+$/, '');
	if (int === '' && frac === '') return '0';
	const significant = (int + frac).replace(/^0+/, '').replace(/0+$/, '');
	if (significant.length > DECIMAL_DIGITS) return null;
	return (negative ? '-' : '') + (int === '' ? '0' : int) + (frac === '' ? '' : '.' + frac);
}

export type Checked = { ok: true; value: Stored } | { ok: false; code: string };

const INT_TEXT = /^[+-]?\d+$/;
const DEC_TEXT = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;
const DATE_TEXT = /^(\d{4})-(\d{2})-(\d{2})$/;

function isEmpty(raw: unknown): boolean {
	return raw === null || raw === undefined || (typeof raw === 'string' && trimAnswer(raw) === '');
}

/** Find a choice by code. Semantics C2-8 (proposed): `1` and `"1"` are the same code. */
export function matchChoice(item: QuestionItem, raw: unknown): ChoiceValue | undefined {
	if (typeof raw !== 'number' && typeof raw !== 'string') return undefined;
	const key = typeof raw === 'string' ? trimAnswer(raw) : String(raw);
	return (item.choices ?? []).find((c) => String(c.value) === key)?.value;
}

export function validDate(text: string): boolean {
	const m = DATE_TEXT.exec(text);
	if (!m) return false;
	const y = Number(m[1]);
	const mo = Number(m[2]);
	const d = Number(m[3]);
	if (y < 1 || mo < 1 || mo > 12 || d < 1) return false;
	const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
	const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]!;
	return d <= days;
}

/** Check participant input for `item` and return its stored form. Never throws. */
export function checkAnswer(item: QuestionItem, raw: unknown): Checked {
	try {
		if (isEmpty(raw)) return { ok: true, value: null };
		switch (item.type) {
			case 'integer': {
				if (typeof raw === 'number') {
					return Number.isSafeInteger(raw)
						? { ok: true, value: raw === 0 ? 0 : raw }
						: { ok: false, code: 'value.not_integer' };
				}
				if (typeof raw !== 'string') return { ok: false, code: 'value.not_integer' };
				const t = trimAnswer(raw);
				if (!INT_TEXT.test(t)) return { ok: false, code: 'value.not_integer' };
				const n = Number(t);
				return Number.isSafeInteger(n)
					? { ok: true, value: n === 0 ? 0 : n }
					: { ok: false, code: 'value.out_of_range' };
			}
			case 'decimal': {
				let t: string;
				if (typeof raw === 'number') {
					if (!Number.isFinite(raw)) return { ok: false, code: 'value.not_decimal' };
					t = dec.toPlain(dec.fromInteger(0).plus(raw));
				} else if (typeof raw === 'string') {
					t = trimAnswer(raw);
				} else return { ok: false, code: 'value.not_decimal' };
				if (!DEC_TEXT.test(t)) return { ok: false, code: 'value.not_decimal' };
				// Stored and exported in canonical form (semantics.md §2): "2.50" -> "2.5";
				// more than 28 significant figures cannot be read exactly, so it is refused.
				const c = canonicalDecimal(t);
				return c === null ? { ok: false, code: 'value.too_long' } : { ok: true, value: c };
			}
			case 'text': {
				if (typeof raw !== 'string') return { ok: false, code: 'value.not_text' };
				const t = trimAnswer(raw);
				return { ok: true, value: t === '' ? null : t };
			}
			case 'date': {
				if (typeof raw !== 'string') return { ok: false, code: 'value.not_date' };
				const t = trimAnswer(raw);
				return validDate(t) ? { ok: true, value: t } : { ok: false, code: 'value.not_date' };
			}
			case 'single': {
				const c = matchChoice(item, raw);
				return c === undefined ? { ok: false, code: 'value.not_a_choice' } : { ok: true, value: c };
			}
			case 'multi': {
				if (!Array.isArray(raw)) return { ok: false, code: 'value.not_a_list' };
				const picked = new Set<ChoiceValue>();
				for (const r of raw) {
					const c = matchChoice(item, r);
					if (c === undefined) return { ok: false, code: 'value.not_a_choice' };
					picked.add(c);
				}
				const ordered = (item.choices ?? []).map((c) => c.value).filter((v) => picked.has(v));
				return { ok: true, value: ordered.length ? ordered : null };
			}
		}
	} catch {
		// fall through
	}
	return { ok: false, code: 'value.invalid' };
}

/** The evaluator value of a stored answer of `type`. */
export function toValue(type: string, stored: Stored): Value {
	if (stored === null || stored === undefined) return null;
	switch (type) {
		case 'integer':
			return typeof stored === 'number' ? { k: 'num', v: dec.fromInteger(stored), int: true } : null;
		case 'decimal': {
			const d = typeof stored === 'string' ? dec.parseDecimal(stored) : null;
			return d === null ? null : { k: 'num', v: d, int: false };
		}
		case 'text':
			return typeof stored === 'string' && stored !== '' ? { k: 'text', v: stored } : null;
		case 'date':
			return typeof stored === 'string' ? { k: 'date', v: stored } : null;
		case 'single':
			return codeValue(stored as Code);
		case 'multi':
			return Array.isArray(stored) && stored.length ? { k: 'multi', v: stored } : null;
	}
	return null;
}

/** A choice code, condition level or literal: int → number, text → text (trimmed). */
export function codeValue(code: unknown): Value {
	if (typeof code === 'number') {
		return Number.isInteger(code) ? { k: 'num', v: dec.fromInteger(code), int: true } : null;
	}
	if (typeof code === 'string') {
		const t = trimAnswer(code);
		return t === '' ? null : { k: 'text', v: t };
	}
	return null;
}
