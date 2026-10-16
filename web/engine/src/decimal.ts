/**
 * Exact decimal arithmetic (semantics.md §2), mirroring `osp_expr.evaluate` exactly:
 *
 * - integer `+ - *` integer stays an exact integer (Python ints are unbounded);
 * - every other operation is a Python `Decimal` operation in a context with 28 significant
 *   digits and ROUND_HALF_EVEN: the exact result rounded once to 28 significant digits;
 * - `/` always gives a decimal; division by zero gives null (provisional, semantics.md
 *   Open questions 1).
 *
 * big.js (MIT) does exact `plus`, `minus`, `times` and comparison. Division is rounded
 * correctly by computing a truncated quotient with guard digits and a sticky digit, then
 * rounding once to 28 significant digits. Never a JS float.
 */

import BigCtor from 'big.js';
import type { Big } from 'big.js';

/** Significant digits kept by decimal arithmetic (osp_expr.evaluate.DECIMAL_PRECISION). */
export const DECIMAL_PRECISION = 28;
const HALF_EVEN = 2;
const ROUND_DOWN = 0;
const GUARD = 3;
const MAX_DP = 1_000_000;

// Private constructors, so no global big.js configuration is read or changed.
const D = BigCtor();
D.DP = 40;
D.RM = HALF_EVEN;
D.NE = -1_000_000;
D.PE = 1_000_000;
const Q = BigCtor();
Q.RM = ROUND_DOWN;

export type Dec = Big;

const DECIMAL_TEXT = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;

/** Parse decimal text (as in an AST literal or a stored answer). Null if not a number. */
export function parseDecimal(text: string): Dec | null {
	const t = text.trim();
	if (!DECIMAL_TEXT.test(t)) return null;
	try {
		return new D(t.startsWith('+') ? t.slice(1) : t);
	} catch {
		return null;
	}
}

export function fromInteger(n: number | bigint): Dec {
	return new D(typeof n === 'bigint' ? n.toString() : n);
}

function round(x: Dec): Dec {
	return x.prec(DECIMAL_PRECISION, HALF_EVEN);
}

export function add(a: Dec, b: Dec, exact: boolean): Dec {
	const r = a.plus(b);
	return exact ? r : round(r);
}

export function sub(a: Dec, b: Dec, exact: boolean): Dec {
	const r = a.minus(b);
	return exact ? r : round(r);
}

export function mul(a: Dec, b: Dec, exact: boolean): Dec {
	const r = a.times(b);
	return exact ? r : round(r);
}

/** `a / b` correctly rounded to 28 significant digits (ROUND_HALF_EVEN); null if b is 0. */
export function div(a: Dec, b: Dec): Dec | null {
	if (b.eq(0)) return null;
	if (a.eq(0)) return new D(0);
	// The quotient's leading digit is at 10^(a.e − b.e) or 10^(a.e − b.e − 1); keep
	// 28 + GUARD digits below the lower of the two.
	const dp = Math.max(0, DECIMAL_PRECISION + GUARD + 1 - (a.e - b.e));
	if (dp > MAX_DP) return null;
	Q.DP = dp;
	const qa = new Q(a);
	const qb = new Q(b);
	let q = qa.div(qb); // truncated toward zero at dp places
	if (!q.times(qb).eq(qa)) {
		// Inexact: the true quotient lies strictly beyond q (away from zero). A sticky digit
		// below every kept digit makes the single rounding below exact.
		const sticky = new Q(`1e-${dp + 1}`);
		q = q.s < 0 ? q.minus(sticky) : q.plus(sticky);
	}
	return round(new D(q));
}

export function cmp(a: Dec, b: Dec): number {
	return a.cmp(b);
}

/** Plain (non-exponent) decimal text, e.g. for piping a computed number. */
export function toPlain(x: Dec): string {
	return x.toFixed();
}

export function isInteger(x: Dec): boolean {
	return x.eq(x.round(0, ROUND_DOWN));
}
