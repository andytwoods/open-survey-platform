/**
 * AST ⇄ tree for the condition builder (task B7). Pure functions, no I/O.
 *
 * AST → tree is exact for everything it accepts: `treeToAst(astToTree(a).root)` equals `a`.
 * What it accepts:
 *   and / or                       → "All of" / "Any of" group
 *   not (a or b …)                 → "None of" group of a, b …
 *   not x  (any other x)           → "None of" group of x alone
 *   q op literal | q op other_q    → row (op: == != < <= > >=; literal: int, decimal, text)
 *   contains(q, literal)           → row "includes";   not contains(…) → row "excludes"
 *   answered(q)                    → row "is answered"; not answered(q) → row "is not answered"
 * Anything else (arithmetic, `if()`, literals on the left, `true`, …) is not representable:
 * the builder then shows the text view only.
 */
import { COMPARE_OPS, COMPARE_SYMBOL, operatorDef, operatorsForType } from './operators';
import type { CondNode, ExprNode, GroupMode, GroupNode, OperatorId, QuestionInfo, RowNode } from './types';

let counter = 0;
/** A fresh key for a tree node (keys only identify nodes in the UI). */
export function nextKey(): string {
	counter += 1;
	return `c${counter}`;
}

export function newRow(question = '', op: OperatorId | null = null, value: ExprNode | null = null): RowNode {
	return { kind: 'row', key: nextKey(), question, op, value };
}

export function newGroup(mode: GroupMode = 'all', children: CondNode[] = []): GroupNode {
	return { kind: 'group', key: nextKey(), mode, children };
}

// --- AST → tree ---------------------------------------------------------------------------

export type FromAst = { ok: true; root: GroupNode } | { ok: false; reason: string };

const LITERALS = new Set(['int', 'decimal', 'text']);

function isRef(n: unknown): n is { kind: 'ref'; id: string } {
	return isNode(n) && n.kind === 'ref' && typeof n.id === 'string';
}

function isNode(n: unknown): n is ExprNode {
	return typeof n === 'object' && n !== null && typeof (n as ExprNode).kind === 'string';
}

function isValue(n: unknown): n is ExprNode {
	return isNode(n) && (LITERALS.has(n.kind) || isRef(n));
}

class NotRepresentable extends Error {}

function fail(reason: string): never {
	throw new NotRepresentable(reason);
}

function rowOf(ast: ExprNode): RowNode | null {
	switch (ast.kind) {
		case 'compare': {
			const op = COMPARE_OPS[String(ast.op)];
			if (!op || !isRef(ast.left) || !isValue(ast.right)) return null;
			return newRow(ast.left.id, op, ast.right);
		}
		case 'contains':
			if (!isRef(ast.ref) || !isNode(ast.value) || !LITERALS.has(ast.value.kind)) return null;
			return newRow(ast.ref.id, 'contains', ast.value);
		case 'answered':
			return isRef(ast.ref) ? newRow(ast.ref.id, 'answered') : null;
		case 'not': {
			const arg = ast.arg;
			if (!isNode(arg) || (arg.kind !== 'contains' && arg.kind !== 'answered')) return null;
			const inner = rowOf(arg);
			if (!inner) return null;
			inner.op = inner.op === 'contains' ? 'not_contains' : 'not_answered';
			return inner;
		}
	}
	return null;
}

function args(ast: ExprNode): ExprNode[] {
	const a = ast.args;
	if (!Array.isArray(a) || a.length < 2 || !a.every(isNode)) fail(`malformed '${ast.kind}'`);
	return a;
}

function toNode(ast: unknown, depth: number): CondNode {
	if (depth > 64) fail('nested too deeply');
	if (!isNode(ast)) fail('not an expression');
	const row = rowOf(ast);
	if (row) return row;
	switch (ast.kind) {
		case 'and':
			return newGroup('all', args(ast).map((a) => toNode(a, depth + 1)));
		case 'or':
			return newGroup('any', args(ast).map((a) => toNode(a, depth + 1)));
		case 'not': {
			const arg = ast.arg;
			if (isNode(arg) && arg.kind === 'or') {
				return newGroup('none', args(arg).map((a) => toNode(a, depth + 2)));
			}
			return newGroup('none', [toNode(arg, depth + 1)]);
		}
	}
	return fail(`'${ast.kind}' has no visual form`);
}

/** The tree for `ast` (null: an empty "All of" group), or why it is not representable. */
export function astToTree(ast: ExprNode | null | undefined): FromAst {
	if (ast === null || ast === undefined) return { ok: true, root: newGroup('all') };
	try {
		const node = toNode(ast, 0);
		return { ok: true, root: node.kind === 'group' ? node : newGroup('all', [node]) };
	} catch (e) {
		if (e instanceof NotRepresentable) return { ok: false, reason: e.message };
		throw e;
	}
}

// --- tree → AST ---------------------------------------------------------------------------

/** The value kind `row` needs, given its question (undefined if unknown). */
export function rowValueKind(row: RowNode, question: QuestionInfo | undefined) {
	if (!row.op) return 'none' as const;
	if (row.value?.kind === 'ref') return 'question' as const;
	return operatorDef(question, row.op).value;
}

/** Why `row` cannot be compiled yet, or null if it is complete. */
export function rowProblem(row: RowNode, question: QuestionInfo | undefined): string | null {
	if (!row.question) return 'Choose a question';
	if (!row.op) return 'Choose an operator';
	if (rowValueKind(row, question) !== 'none' && !row.value) {
		return row.draft ? 'Enter a valid value' : 'Enter a value';
	}
	return null;
}

function rowAst(row: RowNode): ExprNode {
	const ref = { kind: 'ref', id: row.question };
	const op = row.op as OperatorId;
	switch (op) {
		case 'answered':
			return { kind: 'answered', ref };
		case 'not_answered':
			return { kind: 'not', arg: { kind: 'answered', ref } };
		case 'contains':
			return { kind: 'contains', ref, value: row.value as ExprNode };
		case 'not_contains':
			return { kind: 'not', arg: { kind: 'contains', ref, value: row.value as ExprNode } };
		default:
			return { kind: 'compare', op: COMPARE_SYMBOL[op], left: ref, right: row.value as ExprNode };
	}
}

export interface ToAst {
	/** The condition; null if the tree is empty (no condition). */
	ast: ExprNode | null;
	/** Keys of rows left out because they are incomplete. */
	incomplete: string[];
}

/**
 * Compile a tree. Incomplete rows and empty groups are left out (and reported); a group
 * with one child compiles to that child ("None of" with one child to `not child`).
 */
export function treeToAst(root: GroupNode, questions: ReadonlyMap<string, QuestionInfo> = new Map()): ToAst {
	const incomplete: string[] = [];
	const compile = (node: CondNode): ExprNode | null => {
		if (node.kind === 'row') {
			if (rowProblem(node, questions.get(node.question))) {
				incomplete.push(node.key);
				return null;
			}
			return rowAst(node);
		}
		const parts = node.children.map(compile).filter((a): a is ExprNode => a !== null);
		if (parts.length === 0) return null;
		if (node.mode === 'none') {
			return { kind: 'not', arg: parts.length === 1 ? parts[0] : { kind: 'or', args: parts } };
		}
		if (parts.length === 1) return parts[0];
		return { kind: node.mode === 'all' ? 'and' : 'or', args: parts };
	};
	return { ast: compile(root), incomplete };
}

// --- edits (mutate in place; the components hold the tree in $state) ----------------------

/** The node with `key` and its parent group (null for the root). */
export function findNode(root: GroupNode, key: string): { node: CondNode; parent: GroupNode | null } | null {
	if (root.key === key) return { node: root, parent: null };
	const stack: GroupNode[] = [root];
	while (stack.length) {
		const g = stack.pop() as GroupNode;
		for (const c of g.children) {
			if (c.key === key) return { node: c, parent: g };
			if (c.kind === 'group') stack.push(c);
		}
	}
	return null;
}

export function removeNode(root: GroupNode, key: string): void {
	const found = findNode(root, key);
	if (!found?.parent) return;
	const i = found.parent.children.indexOf(found.node);
	found.parent.children.splice(i, 1);
}

/** After a question change: drop an operator the new type does not offer, and its value. */
export function fitRowToQuestion(row: RowNode, question: QuestionInfo | undefined, previousType?: string): void {
	const ops = operatorsForType(question?.type);
	if (!row.op || !ops.some((o) => o.id === row.op)) {
		row.op = ops[0]?.id ?? null;
		row.value = null;
		row.draft = undefined;
	} else if (previousType !== question?.type) {
		row.value = null;
		row.draft = undefined;
	}
	if (row.value?.kind === 'ref' && row.value.id === row.question) row.value = null;
}

/** After an operator change: drop a value of the wrong kind. */
export function fitRowToOperator(row: RowNode, question: QuestionInfo | undefined, previousKind: string): void {
	if (rowValueKind({ ...row, value: null }, question) !== previousKind) {
		row.value = null;
		row.draft = undefined;
	}
}

/** Parse a number input into an `int` or `decimal` literal (null if it is not a number). */
export function numberLiteral(text: string): ExprNode | null {
	const t = text.trim();
	if (/^-?\d+$/.test(t)) {
		const n = Number(t);
		return Number.isSafeInteger(n) ? { kind: 'int', value: n } : { kind: 'decimal', value: t };
	}
	if (/^-?\d+\.\d+$/.test(t)) return { kind: 'decimal', value: t };
	return null;
}

/** A choice code as a literal: numbers stay numbers (`int`), others are text. */
export function choiceLiteral(value: string | number): ExprNode {
	return typeof value === 'number' && Number.isSafeInteger(value)
		? { kind: 'int', value }
		: { kind: 'text', value: String(value) };
}

/** The text an input shows for a literal value. */
export function literalText(value: ExprNode | null): string {
	if (!value) return '';
	if (value.kind === 'int' || value.kind === 'decimal' || value.kind === 'text') return String(value.value);
	return '';
}
