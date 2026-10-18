/**
 * The slice of Python's `decimal` the validator uses: `Decimal(str)` parsing (whitespace,
 * underscores and Unicode digits as CPython's `_decimal` accepts them), exact comparison,
 * subtraction rounded to the default context (28 digits, half-even), `%` with its
 * DivisionImpossible error, and `osp_expr.values.canonical_decimal`. BigInt only.
 */

import { asciiDigits, digitValue, isSpace, stripChars, TRIM_SET } from './py.ts';

export interface Dec {
	neg: boolean;
	coef: bigint; // >= 0
	exp: number;
}

export type Parsed = { kind: 'finite'; d: Dec } | { kind: 'special' };

/** An error raised the way Python's decimal module would raise it (`internal.error`). */
export class PyError extends Error {
	constructor(readonly pyName: string) {
		super(pyName);
	}
}

const PREC = 28;
const NUMBER = /^([+-])?(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/;
const SPECIAL = /^[+-]?(?:inf|infinity|s?nan\d*)$/i;

/** `Decimal(s)`, or null where Python raises InvalidOperation. */
export function parseDecimal(s: string): Parsed | null {
	let ascii = '';
	for (const ch of s) {
		if (ch === '_') continue;
		if (isSpace(ch)) ascii += ' ';
		else if (ch.codePointAt(0)! < 128) ascii += ch;
		else {
			const d = digitValue(ch);
			ascii += d < 0 ? '?' : String(d);
		}
	}
	ascii = ascii.replace(/^ +| +$/g, '');
	if (SPECIAL.test(ascii)) return { kind: 'special' };
	const m = NUMBER.exec(ascii);
	if (!m) return null;
	const int = m[2] ?? '';
	const frac = m[3] ?? m[4] ?? '';
	const e = m[5] === undefined ? 0 : Number(m[5]);
	return {
		kind: 'finite',
		d: { neg: m[1] === '-', coef: BigInt((int + frac) || '0'), exp: e - frac.length }
	};
}

export function fromInt(n: number): Dec {
	return { neg: n < 0, coef: BigInt(Math.abs(n)), exp: 0 };
}

function pow10(n: number): bigint {
	return 10n ** BigInt(n);
}

function digits(c: bigint): number {
	return c === 0n ? 1 : c.toString().length;
}

/** Signed coefficients of a and b at a common exponent. */
function align(a: Dec, b: Dec): [bigint, bigint, number] {
	const e = Math.min(a.exp, b.exp);
	const x = a.coef * pow10(a.exp - e) * (a.neg ? -1n : 1n);
	const y = b.coef * pow10(b.exp - e) * (b.neg ? -1n : 1n);
	return [x, y, e];
}

export function compare(a: Dec, b: Dec): number {
	const [x, y] = align(a, b);
	return x < y ? -1 : x > y ? 1 : 0;
}

export function isZero(a: Dec): boolean {
	return a.coef === 0n;
}

function signed(c: bigint, e: number): Dec {
	return { neg: c < 0n, coef: c < 0n ? -c : c, exp: e };
}

/** Round to PREC significant digits, half-even (the default context). */
function round(d: Dec): Dec {
	const n = digits(d.coef);
	if (n <= PREC) return d;
	const drop = n - PREC;
	const div = pow10(drop);
	let q = d.coef / div;
	const r = d.coef % div;
	const half = div / 2n;
	if (r > half || (r === half && q % 2n === 1n)) q += 1n;
	if (digits(q) > PREC) return { neg: d.neg, coef: q / 10n, exp: d.exp + drop + 1 };
	return { neg: d.neg, coef: q, exp: d.exp + drop };
}

export function subtract(a: Dec, b: Dec): Dec {
	const [x, y, e] = align(a, b);
	return round(signed(x - y, e));
}

/** `a % b` is zero (Python `remainder`); raises as Python does when the quotient's
 * integer part needs more than 28 digits. */
export function remainderIsZero(a: Dec, b: Dec): boolean {
	const [x, y] = align(a, b);
	if (y === 0n) throw new PyError(x === 0n ? 'InvalidOperation' : 'InvalidOperation');
	const ax = x < 0n ? -x : x;
	const ay = y < 0n ? -y : y;
	const q = ax / ay;
	if (q !== 0n && digits(q) > PREC) throw new PyError('InvalidOperation');
	return ax % ay === 0n;
}

export function isIntegral(d: Dec): boolean {
	return d.exp >= 0 || d.coef % pow10(-d.exp) === 0n;
}

// --- osp_expr.values.canonical_decimal ------------------------------------------------------

const DECIMAL_INPUT = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;

function normalize(d: Dec): Dec {
	let { coef, exp } = d;
	while (coef !== 0n && coef % 10n === 0n) {
		coef /= 10n;
		exp++;
	}
	return { neg: d.neg, coef, exp };
}

function fixed(d: Dec): string {
	const s = d.coef.toString();
	let body: string;
	if (d.exp >= 0) body = s + '0'.repeat(d.exp);
	else if (s.length > -d.exp) body = s.slice(0, s.length + d.exp) + '.' + s.slice(s.length + d.exp);
	else body = '0.' + '0'.repeat(-d.exp - s.length) + s;
	return (d.neg ? '-' : '') + body;
}

/** `canonical_decimal(value)` for an int or a string; null where Python gives None. */
export function canonicalDecimal(value: string | number): string | null {
	let d: Dec;
	if (typeof value === 'number') d = fromInt(value);
	else {
		const text = stripChars(value, TRIM_SET);
		if (!DECIMAL_INPUT.test(asciiDigits(text))) return null;
		const p = parseDecimal(text);
		if (p === null || p.kind !== 'finite') return null;
		d = p.d;
	}
	if (isZero(d)) return '0';
	d = normalize(d);
	if (d.coef.toString().length > PREC) return null;
	return fixed(d);
}

/** `Decimal(text)` of a canonical decimal text. */
export function decimalOf(text: string): Dec {
	const p = parseDecimal(text);
	if (p === null || p.kind !== 'finite') throw new PyError('InvalidOperation');
	return p.d;
}
