/**
 * Expression evaluator over the osp-expr AST, exactly as `osp_expr.evaluate`
 * (semantics.md §2, §3; the Python module is the reference and is tested for parity).
 *
 * - §3 Any comparison with null is false, including null == null.
 * - §3 Arithmetic with null gives null; a condition that is null counts as false.
 * - §3 A not-reached or irrelevant question gives null (the caller's `lookup` does that).
 * - §2 `/` is decimal; integer `+ - *` stays exact (decimal.ts).
 *
 * PROVISIONAL (semantics.md Open questions 1 and 2, decided by nobody yet):
 * - division by zero is null;
 * - a test (comparison, contains) on mismatched kinds is false; ordering is defined only
 *   for numbers and dates; arithmetic on non-numbers is null; and/or/not treat any operand
 *   that is not `true` as false (so `not null` is true).
 *
 * Never throws: a pathological AST evaluates to null.
 */

import * as dec from './decimal.ts';
import type { Dec } from './decimal.ts';
import type { Expr } from './plan.ts';

export type Code = number | string;
export type Value =
	| null
	| { k: 'num'; v: Dec; int: boolean }
	| { k: 'text'; v: string }
	| { k: 'date'; v: string }
	| { k: 'multi'; v: readonly Code[] }
	| { k: 'bool'; v: boolean };

export type Lookup = (id: string) => Value;

export function num(v: Dec, int: boolean): Value {
	return { k: 'num', v, int };
}

function codeEq(a: Code, b: Code): boolean {
	if (typeof a === 'number' && typeof b === 'number') return a === b;
	return a === b;
}

function codeIsIn(value: Value, codes: readonly Code[]): boolean {
	if (value === null) return false;
	if (value.k === 'num') {
		return codes.some((c) => typeof c === 'number' && dec.cmp(dec.fromInteger(c), value.v) === 0);
	}
	if (value.k === 'text') return codes.some((c) => typeof c === 'string' && c === value.v);
	return false;
}

function setEq(a: readonly Code[], b: readonly Code[]): boolean {
	const has = (xs: readonly Code[], y: Code) => xs.some((x) => codeEq(x, y));
	return a.every((x) => has(b, x)) && b.every((y) => has(a, y));
}

function contains(multi: Value, value: Value): boolean {
	if (multi === null || value === null) return false;
	if (multi.k !== 'multi' || (value.k !== 'num' && value.k !== 'text')) return false;
	return codeIsIn(value, multi.v);
}

function compare(op: string, left: Value, right: Value): boolean {
	if (left === null || right === null) return false;
	if (left.k !== right.k) return false;
	let c: number;
	switch (left.k) {
		case 'num':
			c = dec.cmp(left.v, (right as { v: Dec }).v);
			break;
		case 'date':
		case 'text': {
			const r = (right as { v: string }).v;
			if (op === '==') return left.v === r;
			if (op === '!=') return left.v !== r;
			if (left.k === 'text') return false; // ordering only for numbers and dates
			c = left.v < r ? -1 : left.v > r ? 1 : 0;
			break;
		}
		case 'multi': {
			const eq = setEq(left.v, (right as { v: readonly Code[] }).v);
			if (op === '==') return eq;
			if (op === '!=') return !eq;
			return false;
		}
		case 'bool': {
			const r = (right as { v: boolean }).v;
			if (op === '==') return left.v === r;
			if (op === '!=') return left.v !== r;
			return false;
		}
	}
	switch (op) {
		case '==':
			return c === 0;
		case '!=':
			return c !== 0;
		case '<':
			return c < 0;
		case '<=':
			return c <= 0;
		case '>':
			return c > 0;
		default:
			return c >= 0;
	}
}

function arith(op: string, left: Value, right: Value): Value {
	if (left === null || right === null) return null;
	if (left.k !== 'num' || right.k !== 'num') return null;
	const exact = op !== '/' && left.int && right.int;
	switch (op) {
		case '+':
			return num(dec.add(left.v, right.v, exact), exact);
		case '-':
			return num(dec.sub(left.v, right.v, exact), exact);
		case '*':
			return num(dec.mul(left.v, right.v, exact), exact);
		default: {
			const q = dec.div(left.v, right.v);
			return q === null ? null : num(q, false);
		}
	}
}

function evalNode(node: Expr, lookup: Lookup): Value {
	switch (node.kind) {
		case 'int':
			return Number.isInteger(node.value) ? num(dec.fromInteger(node.value), true) : null;
		case 'decimal': {
			const d = typeof node.value === 'string' ? dec.parseDecimal(node.value) : null;
			return d === null ? null : num(d, false);
		}
		case 'text':
			return typeof node.value === 'string' ? { k: 'text', v: node.value } : null;
		case 'null':
			return null;
		case 'ref':
			return lookup(node.id);
		case 'answered':
			return { k: 'bool', v: lookup(node.ref.id) !== null };
		case 'contains':
			return { k: 'bool', v: contains(lookup(node.ref.id), evalNode(node.value, lookup)) };
		case 'compare':
			return {
				k: 'bool',
				v: compare(node.op, evalNode(node.left, lookup), evalNode(node.right, lookup))
			};
		case 'arith':
			return arith(node.op, evalNode(node.left, lookup), evalNode(node.right, lookup));
		case 'and':
			return { k: 'bool', v: node.args.every((a) => isTrue(evalNode(a, lookup))) };
		case 'or':
			return { k: 'bool', v: node.args.some((a) => isTrue(evalNode(a, lookup))) };
		case 'not':
			return { k: 'bool', v: !isTrue(evalNode(node.arg, lookup)) };
	}
	return null;
}

function isTrue(v: Value): boolean {
	return v !== null && v.k === 'bool' && v.v === true;
}

/** Evaluate `expr`. Never throws. */
export function evaluate(expr: Expr, lookup: Lookup): Value {
	try {
		return evalNode(expr, lookup);
	} catch {
		return null;
	}
}

/** Evaluate as a condition: only `true` is true; null is false (§3). */
export function evaluateCondition(expr: Expr, lookup: Lookup): boolean {
	return isTrue(evaluate(expr, lookup));
}
