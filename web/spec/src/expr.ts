/**
 * Expressions as the validator sees them (osp_spec.expr and osp_expr.static): references,
 * literal choice-code tests and the static type check, over the parsed AST JSON
 * (`{kind: ...}` nodes; `if` keeps its else branch as `else_`).
 */

import { parseDecimal } from './decimal.ts';

export interface ExprNode {
	kind: string;
	[key: string]: unknown;
}

function children(node: ExprNode): Array<[string, ExprNode]> {
	switch (node.kind) {
		case 'compare':
		case 'arith':
			return [
				['/left', node.left as ExprNode],
				['/right', node.right as ExprNode]
			];
		case 'and':
		case 'or':
			return (node.args as ExprNode[]).map((a, i) => [`/args/${i}`, a]);
		case 'not':
			return [['/arg', node.arg as ExprNode]];
		case 'answered':
			return [['/ref', node.ref as ExprNode]];
		case 'contains':
			return [
				['/ref', node.ref as ExprNode],
				['/value', node.value as ExprNode]
			];
		case 'if':
			return [
				['/cond', node.cond as ExprNode],
				['/then', node.then as ExprNode],
				['/else', node.else_ as ExprNode]
			];
		default:
			return [];
	}
}

/** Ids referenced by `expr`, in first-seen order, without duplicates. */
export function references(expr: ExprNode): string[] {
	const seen = new Set<string>();
	const stack: ExprNode[] = [expr];
	while (stack.length) {
		const node = stack.pop()!;
		if (node.kind === 'ref') seen.add(node.id as string);
		const kids = children(node);
		for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]![1]);
	}
	return [...seen];
}

const isLit = (n: ExprNode): boolean => n.kind === 'int' || n.kind === 'text';

/** `(pointer suffix of the literal, ref id, code)` for `ref == code`, `ref != code` (either
 * order) and `contains(ref, code)`. */
export function codeTests(expr: ExprNode): Array<[string, string, string | number]> {
	const out: Array<[string, string, string | number]> = [];
	const stack: Array<[ExprNode, string]> = [[expr, '']];
	while (stack.length) {
		const [node, path] = stack.pop()!;
		if (node.kind === 'compare' && (node.op === '==' || node.op === '!=')) {
			const left = node.left as ExprNode;
			const right = node.right as ExprNode;
			if (left.kind === 'ref' && isLit(right)) out.push([path + '/right', left.id as string, right.value as string | number]);
			else if (isLit(left) && right.kind === 'ref') out.push([path + '/left', right.id as string, left.value as string | number]);
		} else if (node.kind === 'contains') {
			const value = node.value as ExprNode;
			if (isLit(value)) out.push([path + '/value', (node.ref as ExprNode).id as string, value.value as string | number]);
		}
		// osp_spec.expr._children_with_paths: no children for answered(), only the value of contains().
		let kids: Array<[string, ExprNode]>;
		if (node.kind === 'answered') kids = [];
		else if (node.kind === 'contains') kids = [['/value', node.value as ExprNode]];
		else kids = children(node);
		for (let i = kids.length - 1; i >= 0; i--) stack.push([kids[i]![1], path + kids[i]![0]]);
	}
	return out;
}

// --- osp_expr.static.typecheck ----------------------------------------------------------------

const FROM_QUESTION: Record<string, string> = {
	integer: 'number',
	decimal: 'number',
	text: 'text',
	single: 'code',
	multi: 'multi',
	date: 'date'
};

function pairIs(a: string, b: string, x: string, y: string): boolean {
	return (a === x && b === y) || (a === y && b === x);
}

function compatibleEq(a: string, b: string): boolean {
	if (a === 'any' || b === 'any' || a === b) return true;
	return pairIs(a, b, 'code', 'number') || pairIs(a, b, 'code', 'text');
}

function branchType(a: string, b: string): string | null {
	if (a === b) return a;
	if (a === 'any' || b === 'any') return 'any';
	if (a === 'null') return b;
	if (b === 'null') return a;
	if (pairIs(a, b, 'code', 'number') || pairIs(a, b, 'code', 'text')) return 'code';
	return null;
}

function orderable(a: string, b: string): boolean {
	if (a === 'any' || b === 'any') return true;
	const ok = new Set(['number', 'code']);
	if (ok.has(a) && ok.has(b)) return true;
	return a === 'date' && b === 'date';
}

function isZeroLit(node: ExprNode): boolean {
	if (node.kind === 'int') return node.value === 0;
	if (node.kind !== 'decimal') return false;
	const v = node.value;
	if (typeof v === 'number') return v === 0;
	const p = parseDecimal(v as string);
	return p !== null && p.kind === 'finite' && p.d.coef === 0n;
}

interface StaticDiag {
	code: string;
	message: string;
	path: string;
}

class TypeChecker {
	diags: StaticDiag[] = [];
	constructor(private readonly types: ReadonlyMap<string, string>) {}

	add(code: string, message: string, path: string): void {
		this.diags.push({ code, message, path: path || '/' });
	}

	refType(ref: ExprNode, path: string): string {
		const id = ref.id as string;
		const t = this.types.get(id);
		if (t === undefined) {
			this.add('unknown-question', `no question with id '${id}'`, path);
			return 'any';
		}
		const s = FROM_QUESTION[t];
		if (s === undefined) {
			this.add('unknown-type', `question '${id}' has unknown type '${t}'`, path);
			return 'any';
		}
		return s;
	}

	check(node: ExprNode, path: string): string {
		switch (node.kind) {
			case 'int':
			case 'decimal':
				return 'number';
			case 'text':
				return 'text';
			case 'bool':
				return 'boolean';
			case 'null':
				return 'null';
			case 'ref':
				return this.refType(node, path);
			case 'answered':
				this.refType(node.ref as ExprNode, path + '/ref');
				return 'boolean';
			case 'contains': {
				const r = node.ref as ExprNode;
				const rt = this.refType(r, path + '/ref');
				const vt = this.check(node.value as ExprNode, path + '/value');
				if (rt !== 'multi' && rt !== 'any') {
					this.add('contains-non-multi', `contains() needs a multi-choice question; '${r.id as string}' is ${rt}`, path + '/ref');
				}
				if (vt === 'null') {
					this.add('null-comparison', 'contains(q, null) is always false; use answered()', path + '/value');
				} else if (!['number', 'text', 'code', 'any'].includes(vt)) {
					this.add('type-mismatch', `contains() looks for a choice code (number or text), not ${vt}`, path + '/value');
				}
				return 'boolean';
			}
			case 'compare': {
				const op = node.op as string;
				const lt = this.check(node.left as ExprNode, path + '/left');
				const rt = this.check(node.right as ExprNode, path + '/right');
				if (lt === 'null' || rt === 'null') {
					this.add('null-comparison', 'comparing with null is always false (even null == null); use answered()', path);
				} else if (op === '==' || op === '!=') {
					if (!compatibleEq(lt, rt)) this.add('type-mismatch', `cannot compare ${lt} ${op} ${rt}`, path);
				} else if (!orderable(lt, rt)) {
					this.add('type-mismatch', `'${op}' needs two numbers or two dates, not ${lt} and ${rt}`, path);
				}
				return 'boolean';
			}
			case 'arith': {
				const op = node.op as string;
				const lt = this.check(node.left as ExprNode, path + '/left');
				const rt = this.check(node.right as ExprNode, path + '/right');
				if (lt === 'null' || rt === 'null') {
					this.add('null-arithmetic', 'arithmetic with null is always null', path);
					return 'any';
				}
				for (const [side, t] of [
					['left', lt],
					['right', rt]
				] as const) {
					if (!['number', 'code', 'any'].includes(t)) {
						this.add('type-mismatch', `'${op}' needs numbers; ${side} is ${t}`, `${path}/${side}`);
					}
				}
				if (op === '/' && isZeroLit(node.right as ExprNode)) {
					this.add('division-by-zero', 'dividing by the constant 0 always gives null', path + '/right');
				}
				return 'number';
			}
			case 'and':
			case 'or':
				(node.args as ExprNode[]).forEach((a, i) => this.booleanOperand(a, `${path}/args/${i}`, `'${node.kind}'`));
				return 'boolean';
			case 'not':
				this.booleanOperand(node.arg as ExprNode, path + '/arg', "'not'");
				return 'boolean';
			case 'if': {
				this.booleanOperand(node.cond as ExprNode, path + '/cond', 'if()');
				const tt = this.check(node.then as ExprNode, path + '/then');
				const et = this.check(node.else_ as ExprNode, path + '/else');
				const joined = branchType(tt, et);
				if (joined === null) {
					this.add('type-mismatch', `if() branches must have compatible types, not ${tt} and ${et}`, path);
					return 'any';
				}
				return joined;
			}
		}
		return 'any';
	}

	booleanOperand(node: ExprNode, path: string, where: string): void {
		const t = this.check(node, path);
		if (t !== 'boolean' && t !== 'any') this.add('not-boolean', `${where} needs a condition, not ${t}`, path);
	}
}

// osp-expr codes osp-spec reports itself (as `ref.*`).
const OWN_CHECKS = new Set(['unknown-question', 'unknown-type']);

/** osp_spec.expr.typecheck: `(pointer suffix, message)` pairs. */
export function typecheck(expr: ExprNode, env: ReadonlyMap<string, string>, boolean: boolean): Array<[string, string]> {
	const checker = new TypeChecker(env);
	let diags: StaticDiag[];
	try {
		const result = checker.check(expr, '');
		if (boolean && result !== 'boolean' && result !== 'any') {
			checker.add('not-boolean', `a condition must be true/false, not ${result}`, '');
		}
		diags = checker.diags;
	} catch (e) {
		if (!(e instanceof RangeError)) throw e;
		diags = [{ code: 'too-deep', message: 'expression is nested too deeply', path: '/' }];
	}
	return diags
		.filter((d) => !OWN_CHECKS.has(d.code))
		.map((d) => [d.path && d.path !== '/' ? d.path : '', `${d.message} [${d.code}]`]);
}
