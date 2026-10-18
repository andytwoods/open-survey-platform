/**
 * Python semantics the validator's messages and checks depend on: code-point lengths and
 * slices, `str.strip()` / `str.isspace()`, `repr()` / `str()` of JSON values, code-point
 * sorting, Unicode decimal digits (`\d`, `int()`, `Decimal()`), and a translator from the
 * Python `re` dialect to JavaScript for researcher-supplied redirect patterns.
 */

/** A JSON object (not an array, not null). */
export type JsonObject = { [key: string]: unknown };

/** A JSON object: a plain object (what JSON.parse makes), not an array, Map, Date or class
 * instance, which a Python validator would never see as a dict either. */
export function isObject(v: unknown): v is JsonObject {
	if (typeof v !== 'object' || v === null || Array.isArray(v)) return false;
	const proto = Object.getPrototypeOf(v) as unknown;
	return proto === Object.prototype || proto === null;
}

export function hasOwn(o: JsonObject, key: string): boolean {
	return Object.prototype.hasOwnProperty.call(o, key);
}

/** Python `len(s)`: code points (a lone surrogate counts one, as in Python). */
export function pyLen(s: string): number {
	let n = 0;
	for (let i = 0; i < s.length; i++) {
		const c = s.charCodeAt(i);
		// A high surrogate followed by a low one is one code point.
		if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
			const d = s.charCodeAt(i + 1);
			if (d >= 0xdc00 && d <= 0xdfff) i++;
		}
		n++;
	}
	return n;
}

/** Python `s[:n]`. */
export function pySlice(s: string, n: number): string {
	if (s.length <= n) return s;
	let out = '';
	let i = 0;
	for (const ch of s) {
		if (i++ >= n) break;
		out += ch;
	}
	return out;
}

/** Python `str.isspace()` characters (also what `str.strip()` removes). */
export const PY_SPACE =
	'\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0                　';
const SPACE_SET = new Set(PY_SPACE);
/** A regex character class body matching Python's `\s` (str patterns). */
export const PY_SPACE_CLASS = '\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';

/** `osp_expr.values.TRIM_CHARS`: Unicode White_Space plus U+FEFF (not the C0 separators). */
export const TRIM_SET = new Set(
	'\t\n\v\f\r \x85\xa0                　﻿'
);

export function isSpace(ch: string): boolean {
	return SPACE_SET.has(ch);
}

export function stripChars(s: string, chars: Set<string>): string {
	const cps = Array.from(s);
	let a = 0;
	let b = cps.length;
	while (a < b && chars.has(cps[a]!)) a++;
	while (b > a && chars.has(cps[b - 1]!)) b--;
	return cps.slice(a, b).join('');
}

/** Python `s.strip()`. */
export function pyStrip(s: string): string {
	return stripChars(s, SPACE_SET);
}

/** Compare by code point, as Python sorts strings. */
export function cmpCodePoints(a: string, b: string): number {
	const ai = a[Symbol.iterator]();
	const bi = b[Symbol.iterator]();
	for (;;) {
		const x = ai.next();
		const y = bi.next();
		if (x.done) return y.done ? 0 : -1;
		if (y.done) return 1;
		const cx = x.value.codePointAt(0)!;
		const cy = y.value.codePointAt(0)!;
		if (cx !== cy) return cx - cy;
	}
}

export function pySorted(xs: Iterable<string>): string[] {
	return Array.from(xs).sort(cmpCodePoints);
}

// --- Unicode decimal digits (category Nd), Unicode 16.0 as in Python 3.14 -----------------

/** The code point of every Nd zero; each starts a run of ten digits 0–9. */
const ND_ZEROS = [
	0x30, 0x660, 0x6f0, 0x7c0, 0x966, 0x9e6, 0xa66, 0xae6, 0xb66, 0xbe6, 0xc66, 0xce6, 0xd66, 0xde6,
	0xe50, 0xed0, 0xf20, 0x1040, 0x1090, 0x17e0, 0x1810, 0x1946, 0x19d0, 0x1a80, 0x1a90, 0x1b50,
	0x1bb0, 0x1c40, 0x1c50, 0xa620, 0xa8d0, 0xa900, 0xa9d0, 0xa9f0, 0xaa50, 0xabf0, 0xff10, 0x104a0,
	0x10d30, 0x10d40, 0x11066, 0x110f0, 0x11136, 0x111d0, 0x112f0, 0x11450, 0x114d0, 0x11650,
	0x116c0, 0x116d0, 0x116da, 0x11730, 0x118e0, 0x11950, 0x11bf0, 0x11c50, 0x11d50, 0x11da0,
	0x11f50, 0x16130, 0x16a60, 0x16ac0, 0x16b50, 0x16d70, 0x1ccf0, 0x1d7ce, 0x1d7d8, 0x1d7e2,
	0x1d7ec, 0x1d7f6, 0x1e140, 0x1e2f0, 0x1e4f0, 0x1e5f1, 0x1e950, 0x1fbf0
];

/** The value 0–9 of a Unicode decimal digit, or -1. */
export function digitValue(ch: string): number {
	const cp = ch.codePointAt(0)!;
	for (const z of ND_ZEROS) {
		if (cp >= z && cp < z + 10) return cp - z;
	}
	return -1;
}

/** A regex class body (for a `u`-flag RegExp) matching exactly the Nd digits (`\d`). */
export const DIGIT_CLASS = ND_ZEROS.map((z) => `\\u{${z.toString(16)}}-\\u{${(z + 9).toString(16)}}`).join('');

/** Unicode digits to ASCII (other characters unchanged). */
export function asciiDigits(s: string): string {
	let out = '';
	for (const ch of s) {
		const d = ch >= '0' && ch <= '9' ? -1 : digitValue(ch);
		out += d >= 0 ? String(d) : ch;
	}
	return out;
}

// --- repr ------------------------------------------------------------------------------

const NON_PRINTABLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;

function hex(n: number, width: number): string {
	return n.toString(16).padStart(width, '0');
}

/** Python `repr(str)`. */
export function reprStr(s: string): string {
	const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
	let out = quote;
	for (const ch of s) {
		if (ch === quote || ch === '\\') out += '\\' + ch;
		else if (ch === '\t') out += '\\t';
		else if (ch === '\n') out += '\\n';
		else if (ch === '\r') out += '\\r';
		else if (ch !== ' ' && NON_PRINTABLE.test(ch)) {
			const cp = ch.codePointAt(0)!;
			if (cp < 0x100) out += '\\x' + hex(cp, 2);
			else if (cp < 0x10000) out += '\\u' + hex(cp, 4);
			else out += '\\U' + hex(cp, 8);
		} else out += ch;
	}
	return out + quote;
}

/** Python `repr(float)` (the shortest round-trip digits, Python's layout). */
export function reprFloat(x: number): string {
	if (Number.isNaN(x)) return 'nan';
	if (!Number.isFinite(x)) return x > 0 ? 'inf' : '-inf';
	if (x === 0) return Object.is(x, -0) ? '-0.0' : '0.0';
	const sign = x < 0 ? '-' : '';
	const [mant, expText] = Math.abs(x).toExponential().split('e') as [string, string];
	const digits = mant.replace('.', '');
	const exp = Number(expText); // value = d1.d2d3... × 10^exp
	if (exp >= -4 && exp < 16) {
		if (exp < 0) return sign + '0.' + '0'.repeat(-exp - 1) + digits;
		if (digits.length <= exp + 1) return sign + digits + '0'.repeat(exp + 1 - digits.length) + '.0';
		return sign + digits.slice(0, exp + 1) + '.' + digits.slice(exp + 1);
	}
	const m = digits.length > 1 ? digits[0] + '.' + digits.slice(1) : digits;
	const e = Math.abs(exp).toString().padStart(2, '0');
	return `${sign}${m}e${exp < 0 ? '-' : '+'}${e}`;
}

/** Python `repr()` of a JSON value (ints and floats as Python would hold them). */
export function pyRepr(v: unknown): string {
	if (v === null || v === undefined) return 'None';
	if (v === true) return 'True';
	if (v === false) return 'False';
	if (typeof v === 'number') return Number.isInteger(v) ? String(v) : reprFloat(v);
	if (typeof v === 'string') return reprStr(v);
	if (Array.isArray(v)) return '[' + v.map(pyRepr).join(', ') + ']';
	if (v instanceof Map) {
		return '{' + Array.from(v, ([k, x]) => `${pyRepr(k)}: ${pyRepr(x)}`).join(', ') + '}';
	}
	if (isObject(v)) {
		return '{' + Object.keys(v).map((k) => `${reprStr(k)}: ${pyRepr(v[k])}`).join(', ') + '}';
	}
	return String(v);
}

/** Python `str()` of a JSON value. */
export function pyStr(v: unknown): string {
	return typeof v === 'string' ? v : pyRepr(v);
}

/** Python `==` between a pydantic location element (str or int) and a JSON value. */
export function pyEq(a: string | number, b: unknown): boolean {
	if (typeof a === 'string') return typeof b === 'string' && a === b;
	if (typeof b === 'number') return a === b;
	if (typeof b === 'boolean') return a === (b ? 1 : 0);
	return false;
}

