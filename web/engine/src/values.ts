/**
 * Answer values: checking participant input, the stored (JSON) form, and the evaluator form.
 *
 * Stored forms (also the export / fixture form, fixtures/FORMAT.md §3):
 *   integer  JSON integer (safe range)        decimal  decimal text as typed, e.g. "2.50"
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
 * Python's `str.strip()` whitespace (str.isspace), so trimming matches the reference
 * evaluator: JS `trim()` differs (it strips U+FEFF; it keeps U+001C–U+001F and U+0085).
 * Semantics.md Open questions R1-3.
 */
const PY_WS =
	'\\t\\n\\v\\f\\r\\u001c-\\u001f \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const LEADING = new RegExp(`^[${PY_WS}]+`);
const TRAILING = new RegExp(`[${PY_WS}]+$`);

export function pyStrip(s: string): string {
	return s.replace(LEADING, '').replace(TRAILING, '');
}

export type Checked = { ok: true; value: Stored } | { ok: false; code: string };

const INT_TEXT = /^[+-]?\d+$/;
const DEC_TEXT = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;
const DATE_TEXT = /^(\d{4})-(\d{2})-(\d{2})$/;

function isEmpty(raw: unknown): boolean {
	return raw === null || raw === undefined || (typeof raw === 'string' && pyStrip(raw) === '');
}

/** Find a choice by code. Semantics C2-8 (proposed): `1` and `"1"` are the same code. */
export function matchChoice(item: QuestionItem, raw: unknown): ChoiceValue | undefined {
	if (typeof raw !== 'number' && typeof raw !== 'string') return undefined;
	const key = typeof raw === 'string' ? pyStrip(raw) : String(raw);
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
				const t = pyStrip(raw);
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
					t = pyStrip(raw);
				} else return { ok: false, code: 'value.not_decimal' };
				if (!DEC_TEXT.test(t)) return { ok: false, code: 'value.not_decimal' };
				if (t.startsWith('+')) t = t.slice(1);
				return { ok: true, value: t };
			}
			case 'text': {
				if (typeof raw !== 'string') return { ok: false, code: 'value.not_text' };
				const t = pyStrip(raw);
				return { ok: true, value: t === '' ? null : t };
			}
			case 'date': {
				if (typeof raw !== 'string') return { ok: false, code: 'value.not_date' };
				const t = pyStrip(raw);
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
		const t = pyStrip(code);
		return t === '' ? null : { k: 'text', v: t };
	}
	return null;
}
