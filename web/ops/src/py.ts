/**
 * Small Python compatibility helpers, so the port behaves like `osp-ops` byte for byte:
 * JSON values, type-strict equality, deep copies, `repr()`, code-point slicing, Python's
 * whitespace (`str.isspace`, `\s`), `str.strip()` and `str.splitlines()`, and code-point
 * ordering for `sorted()`.
 *
 * JavaScript numbers do not tell `1` from `1.0`: an integral number is treated as a Python
 * `int` throughout (see README.md, "What cannot match").
 */

export type Json = null | boolean | number | string | Json[] | JsonObject;
export interface JsonObject {
	[key: string]: Json;
}

export function isObj(v: unknown): v is JsonObject {
	return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export function isInt(v: unknown): v is number {
	return typeof v === 'number' && Number.isInteger(v);
}

export function has(obj: object, key: string): boolean {
	return Object.prototype.hasOwnProperty.call(obj, key);
}

/** `dict.get(key)`: undefined (Python None) when absent. */
export function get(obj: JsonObject, key: string): Json | undefined {
	return has(obj, key) ? obj[key] : undefined;
}

/** `obj[key] = value`, safe for a key named `__proto__` (JSON can carry one). */
export function setProp(obj: JsonObject, key: string, value: Json): void {
	if (key === '__proto__') Object.defineProperty(obj, key, { value, writable: true, enumerable: true, configurable: true });
	else obj[key] = value;
}

export function deepCopy<T extends Json | undefined>(v: T): T {
	if (v === null || typeof v !== 'object') return v;
	if (Array.isArray(v)) return v.map((x) => deepCopy(x)) as T;
	const out: JsonObject = {};
	for (const k of Object.keys(v)) setProp(out, k, deepCopy((v as JsonObject)[k]!));
	return out as T;
}

/** Type-strict JSON equality (`1 != true`), like `osp_ops.patch.same`. */
export function same(a: Json | undefined, b: Json | undefined): boolean {
	if (a === b) return true;
	if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return false;
	if (Array.isArray(a) !== Array.isArray(b)) return false;
	if (Array.isArray(a)) {
		const bb = b as Json[];
		return a.length === bb.length && a.every((x, i) => same(x, bb[i]));
	}
	const ao = a as JsonObject;
	const bo = b as JsonObject;
	const ak = Object.keys(ao);
	const bk = Object.keys(bo);
	if (ak.length !== bk.length) return false;
	// Python's `dict.keys() == dict.keys()` is a set comparison.
	for (const k of ak) if (!has(bo, k)) return false;
	return ak.every((k) => same(ao[k], bo[k]));
}

/** Python truthiness of a JSON value (None, False, 0, "", [], {} are false). */
export function truthy(v: Json | undefined): boolean {
	if (v === undefined || v === null || v === false || v === 0 || v === '') return false;
	if (Array.isArray(v)) return v.length > 0;
	if (isObj(v)) return Object.keys(v).length > 0;
	return true;
}

// --- strings by code point ---------------------------------------------------------------

export function codePoints(s: string): string[] {
	return Array.from(s);
}

export function pyLen(s: string): number {
	let n = 0;
	for (let i = 0; i < s.length; i++) {
		const c = s.charCodeAt(i);
		// A surrogate pair is one code point; a lone surrogate counts as one, as in Python.
		if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
			const d = s.charCodeAt(i + 1);
			if (d >= 0xdc00 && d <= 0xdfff) i++;
		}
		n++;
	}
	return n;
}

/** `s[start:end]` by code points (non-negative bounds). */
export function slice(s: string, start: number, end?: number): string {
	if (start === 0 && end !== undefined && s.length <= end) return s; // fast path: no slicing needed
	return Array.from(s).slice(start, end).join('');
}

/** Python sorts strings by code point; JS `sort()` compares UTF-16 units. */
export function byCodePoint(a: string, b: string): number {
	if (a === b) return 0;
	const x = Array.from(a);
	const y = Array.from(b);
	for (let i = 0; i < Math.min(x.length, y.length); i++) {
		const d = x[i]!.codePointAt(0)! - y[i]!.codePointAt(0)!;
		if (d !== 0) return d;
	}
	return x.length - y.length;
}

export function sorted(xs: Iterable<string>): string[] {
	return [...xs].sort(byCodePoint);
}

// --- whitespace and lines ----------------------------------------------------------------

/** Python's `str.isspace` set (also what `\s` matches in a `str` pattern). */
export const PY_SPACE_CLASS =
	'\\t\\n\\x0b\\x0c\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const SPACE_RE = new RegExp(`^[${PY_SPACE_CLASS}]$`, 'u');

export function isSpace(ch: string): boolean {
	return SPACE_RE.test(ch);
}

const STRIP_RE = new RegExp(`^[${PY_SPACE_CLASS}]+|[${PY_SPACE_CLASS}]+$`, 'gu');

export function strip(s: string): string {
	return s.replace(STRIP_RE, '');
}

// eslint-disable-next-line no-control-regex -- these are the line boundaries str.splitlines uses
const LINE_BREAK = /\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/u;

/** `str.splitlines()` (no keepends). */
export function splitlines(s: string): string[] {
	const out: string[] = [];
	let rest = s;
	while (rest.length > 0) {
		const m = LINE_BREAK.exec(rest);
		if (!m) {
			out.push(rest);
			break;
		}
		out.push(rest.slice(0, m.index));
		rest = rest.slice(m.index + m[0].length);
	}
	return out;
}

// --- repr ----------------------------------------------------------------------------------

const NOT_PRINTABLE = /[\p{C}\p{Z}]/u;

function hex(n: number, width: number): string {
	return n.toString(16).padStart(width, '0');
}

/** Python `repr()` of a string. */
export function reprStr(s: string): string {
	const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
	let out = quote;
	for (const ch of s) {
		if (ch === quote || ch === '\\') out += '\\' + ch;
		else if (ch === '\t') out += '\\t';
		else if (ch === '\n') out += '\\n';
		else if (ch === '\r') out += '\\r';
		else if (ch !== ' ' && NOT_PRINTABLE.test(ch)) {
			const cp = ch.codePointAt(0)!;
			if (cp < 0x100) out += '\\x' + hex(cp, 2);
			else if (cp < 0x10000) out += '\\u' + hex(cp, 4);
			else out += '\\U' + hex(cp, 8);
		} else out += ch;
	}
	return out + quote;
}

/** Python `repr()` of a float (shortest round-trip digits, Python's notation). */
export function reprFloat(n: number): string {
	if (Number.isNaN(n)) return 'nan';
	if (!Number.isFinite(n)) return n > 0 ? 'inf' : '-inf';
	const [mant, expS] = n.toExponential().split('e') as [string, string];
	const exp = Number(expS);
	const neg = mant.startsWith('-');
	const digits = mant.replace('-', '').replace('.', '');
	const sign = neg ? '-' : '';
	if (exp < -4 || exp >= 16) {
		const m = digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
		const e = Math.abs(exp).toString().padStart(2, '0');
		return `${sign}${m}e${exp < 0 ? '-' : '+'}${e}`;
	}
	if (exp < 0) return `${sign}0.${'0'.repeat(-exp - 1)}${digits}`;
	const intPart = digits.slice(0, exp + 1).padEnd(exp + 1, '0');
	const frac = digits.slice(exp + 1);
	return `${sign}${intPart}.${frac || '0'}`;
}

/** Python `repr()` of a JSON value (as the value Python's json module would load). */
export function repr(v: Json | undefined): string {
	if (v === undefined || v === null) return 'None';
	if (v === true) return 'True';
	if (v === false) return 'False';
	if (typeof v === 'number') return Number.isInteger(v) ? intStr(v) : reprFloat(v);
	if (typeof v === 'string') return reprStr(v);
	if (Array.isArray(v)) return `[${v.map(repr).join(', ')}]`;
	return `{${Object.keys(v)
		.map((k) => `${reprStr(k)}: ${repr(v[k])}`)
		.join(', ')}}`;
}

function intStr(n: number): string {
	if (Math.abs(n) < 1e21) return n.toFixed(0);
	return BigInt(n).toString();
}

/** Python `str()` of a JSON value. */
export function str(v: Json | undefined): string {
	return typeof v === 'string' ? v : repr(v);
}

/** A Python-style class name for `type(x).__name__` in messages. */
export function typeName(v: Json | undefined): string {
	if (v === undefined || v === null) return 'NoneType';
	if (typeof v === 'boolean') return 'bool';
	if (typeof v === 'number') return Number.isInteger(v) ? 'int' : 'float';
	if (typeof v === 'string') return 'str';
	return Array.isArray(v) ? 'list' : 'dict';
}
