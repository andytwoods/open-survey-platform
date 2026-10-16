/**
 * Expression evaluator over the osp-expr AST, exactly as `osp_expr.evaluate`
 * (semantics.md §2, §3; the Python module is the reference and is tested for parity,
 * including the runtime diagnostics it reports).
 *
 * - §3 Two-valued logic: any comparison with null is false, including null == null;
 *   `contains(null, v)` is false; and/or/not and conditions treat anything that is not
 *   `true` as false, so `not null` is true.
 * - §3 Arithmetic with null gives null. A not-reached or irrelevant question gives null
 *   (the caller's `lookup` does that).
 * - §3 `if(cond, a, b)` is lazy; a condition that is not `true` picks `b`.
 * - §3 A type mismatch gives null and a `type-mismatch` diagnostic; inside and/or/not/if
 *   the mismatched operand counts as null.
 * - §2 Choice codes compare as text (C2-8): an integer equals a text when its decimal text
 *   is the text (`1 == "1"`), in `==`, `!=` and `contains`.
 * - §2 `/` is decimal; `x / 0` is null and a `division-by-zero` diagnostic; integer
 *   `+ - *` stays exact (decimal.ts).
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

/** A runtime diagnostic (never thrown): `path` is a JSON pointer into the AST. */
export interface ExprDiagnostic {
	code: 'type-mismatch' | 'division-by-zero';
	path: string;
}
export type DiagnosticSink = (d: ExprDiagnostic) => void;

export function num(v: Dec, int: boolean): Value {
	return { k: 'num', v, int };
}

/** Two codes: numbers numerically, a number and a text as text (C2-8). */
function codeEq(a: Code, b: Code): boolean {
	if (typeof a === 'number' && typeof b === 'number') return a === b;
	return String(a) === String(b);
}

/** A stored code against an evaluated value (`contains`). */
function codeMatches(code: Code, value: Value): boolean {
	if (value === null) return false;
	if (value.k === 'num') {
		if (typeof code === 'number') return dec.cmp(dec.fromInteger(code), value.v) === 0;
		return value.int && code === dec.toPlain(value.v);
	}
	if (value.k === 'text') return String(code) === value.v;
	return false;
}

function setEq(a: readonly Code[], b: readonly Code[]): boolean {
	const has = (xs: readonly Code[], y: Code) => xs.some((x) => codeEq(x, y));
	return a.every((x) => has(b, x)) && b.every((y) => has(a, y));
}

class Evaluator {
	constructor(
		readonly lookup: Lookup,
		readonly sink: DiagnosticSink | undefined
	) {}

	note(code: ExprDiagnostic['code'], path: string): void {
		this.sink?.({ code, path: path || '/' });
	}

	truth(node: Expr, path: string): boolean {
		const v = this.eval(node, path);
		if (v !== null && v.k !== 'bool') this.note('type-mismatch', path);
		return isTrue(v);
	}

	contains(multi: Value, value: Value, path: string): Value {
		if (multi === null || value === null) return { k: 'bool', v: false };
		if (multi.k !== 'multi') {
			this.note('type-mismatch', path + '/ref');
			return null;
		}
		if (value.k !== 'num' && value.k !== 'text') {
			this.note('type-mismatch', path + '/value');
			return null;
		}
		return { k: 'bool', v: multi.v.some((c) => codeMatches(c, value)) };
	}

	compare(op: string, left: Value, right: Value, path: string): Value {
		if (left === null || right === null) return { k: 'bool', v: false };
		const eqOp = op === '==' || op === '!=';
		const bool = (b: boolean): Value => ({ k: 'bool', v: op === '!=' ? !b : b });
		if (left.k !== right.k) {
			// C2-8: an integer and a text compare as text.
			const n = left.k === 'num' ? left : right.k === 'num' ? right : null;
			const t = left.k === 'text' ? left : right.k === 'text' ? right : null;
			if (eqOp && n && t && n.k === 'num' && n.int && t.k === 'text') return bool(dec.toPlain(n.v) === t.v);
			this.note('type-mismatch', path);
			return null;
		}
		let c: number;
		switch (left.k) {
			case 'num':
				c = dec.cmp(left.v, (right as { v: Dec }).v);
				break;
			case 'date': {
				const r = (right as { v: string }).v;
				c = left.v < r ? -1 : left.v > r ? 1 : 0;
				break;
			}
			case 'text':
			case 'bool':
			case 'multi': {
				if (!eqOp) {
					this.note('type-mismatch', path);
					return null;
				}
				if (left.k === 'multi') return bool(setEq(left.v, (right as { v: readonly Code[] }).v));
				return bool(left.v === (right as { v: unknown }).v);
			}
		}
		switch (op) {
			case '==':
				return { k: 'bool', v: c === 0 };
			case '!=':
				return { k: 'bool', v: c !== 0 };
			case '<':
				return { k: 'bool', v: c < 0 };
			case '<=':
				return { k: 'bool', v: c <= 0 };
			case '>':
				return { k: 'bool', v: c > 0 };
			default:
				return { k: 'bool', v: c >= 0 };
		}
	}

	arith(op: string, left: Value, right: Value, path: string): Value {
		if (left === null || right === null) return null;
		if (left.k !== 'num' || right.k !== 'num') {
			this.note('type-mismatch', path);
			return null;
		}
		const exact = op !== '/' && left.int && right.int;
		switch (op) {
			case '+':
				return num(dec.add(left.v, right.v, exact), exact);
			case '-':
				return num(dec.sub(left.v, right.v, exact), exact);
			case '*':
				return num(dec.mul(left.v, right.v, exact), exact);
			default: {
				if (right.v.eq(0)) {
					this.note('division-by-zero', path);
					return null;
				}
				const q = dec.div(left.v, right.v);
				return q === null ? null : num(q, false);
			}
		}
	}

	eval(node: Expr, path: string): Value {
		switch (node.kind) {
			case 'int': {
				const v = node.value;
				if (typeof v === 'number') return Number.isSafeInteger(v) ? num(dec.fromInteger(v), true) : null;
				return typeof v === 'string' && /^-?\d+$/.test(v) ? num(dec.fromInteger(BigInt(v)), true) : null;
			}
			case 'decimal': {
				const d = typeof node.value === 'string' ? dec.parseDecimal(node.value) : null;
				return d === null ? null : num(d, false);
			}
			case 'text':
				return typeof node.value === 'string' ? { k: 'text', v: node.value } : null;
			case 'bool':
				return typeof node.value === 'boolean' ? { k: 'bool', v: node.value } : null;
			case 'null':
				return null;
			case 'ref':
				return this.lookup(node.id);
			case 'answered':
				return { k: 'bool', v: this.lookup(node.ref.id) !== null };
			case 'contains':
				return this.contains(this.lookup(node.ref.id), this.eval(node.value, path + '/value'), path);
			case 'compare': {
				const a = this.eval(node.left, path + '/left');
				const b = this.eval(node.right, path + '/right');
				return this.compare(node.op, a, b, path);
			}
			case 'arith': {
				const a = this.eval(node.left, path + '/left');
				const b = this.eval(node.right, path + '/right');
				return this.arith(node.op, a, b, path);
			}
			case 'and':
				return { k: 'bool', v: node.args.every((a, i) => this.truth(a, `${path}/args/${i}`)) };
			case 'or':
				return { k: 'bool', v: node.args.some((a, i) => this.truth(a, `${path}/args/${i}`)) };
			case 'not':
				return { k: 'bool', v: !this.truth(node.arg, path + '/arg') };
			case 'if':
				return this.truth(node.cond, path + '/cond')
					? this.eval(node.then, path + '/then')
					: this.eval(node.else, path + '/else');
		}
		return null;
	}
}

function isTrue(v: Value): boolean {
	return v !== null && v.k === 'bool' && v.v === true;
}

/** Evaluate `expr`. Never throws. Runtime diagnostics go to `sink`, if given. */
export function evaluate(expr: Expr, lookup: Lookup, sink?: DiagnosticSink): Value {
	try {
		return new Evaluator(lookup, sink).eval(expr, '');
	} catch {
		return null;
	}
}

/** Evaluate as a condition: only `true` is true; null is false (§3). */
export function evaluateCondition(expr: Expr, lookup: Lookup, sink?: DiagnosticSink): boolean {
	const v = evaluate(expr, lookup, sink);
	if (v !== null && v.k !== 'bool') sink?.({ code: 'type-mismatch', path: '/' });
	return isTrue(v);
}
