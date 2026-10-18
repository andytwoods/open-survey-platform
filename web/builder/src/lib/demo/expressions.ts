/**
 * The demo's `POST /api/meta/expressions/parse` and `/print` (osp_api.routes.expressions),
 * in the browser: @osp/engine's `parseExpr` / `exprToText` (CE1: identical to osp_expr's
 * text syntax) and, for a check in place, @osp/ops' `set_condition` on the draft, whose
 * validator diagnostics under the condition's field come back as they do from the API.
 *
 * Not ported: the type check of an expression with a survey but no target (osp_expr.typecheck
 * is not part of @osp/spec's API); the demo answers that case with the parse only.
 */
import { exprToText, parseExpr, type Expr } from '@osp/engine';
import { run, type Json } from '@osp/ops';

export interface ExprDiagnosticOut {
	code: string;
	message: string;
	severity: 'error' | 'warning' | 'info';
	start?: number | null;
	end?: number | null;
	path?: string | null;
	questionId?: string | null;
}

export interface ParseOut {
	ok: boolean;
	ast: Record<string, unknown> | null;
	text: string | null;
	references: string[];
	diagnostics: ExprDiagnosticOut[];
}

const QUOTED_ID = /'([A-Za-z_][A-Za-z0-9_]*)'/;
const questionId = (message: string): string | null => QUOTED_ID.exec(message)?.[1] ?? null;

/** Ids an expression refers to, in first-use order (osp_expr.references). */
export function references(ast: unknown): string[] {
	const out: string[] = [];
	const walk = (n: unknown) => {
		if (Array.isArray(n)) return n.forEach(walk);
		if (typeof n !== 'object' || n === null) return;
		const o = n as Record<string, unknown>;
		if (o.kind === 'ref' && typeof o.id === 'string' && !out.includes(o.id)) out.push(o.id);
		for (const v of Object.values(o)) if (typeof v === 'object') walk(v);
	};
	walk(ast);
	return out;
}

function inPlace(ast: Json, survey: Json, target: string, field: string | null): ExprDiagnosticOut[] {
	const params: Record<string, Json> = { target, condition: ast };
	if (field) params.field = field;
	const res = run('set_condition', survey, params);
	if (!res.ok) {
		return res.diagnostics.map((d) => ({ code: d.code, message: d.message, severity: 'error', questionId: questionId(d.message) }));
	}
	// The field the op wrote is the patch's path (".../showIf", ".../if", …).
	const ptr = res.patch.map((p) => p.path).find((p): p is string => typeof p === 'string');
	if (!ptr) return [];
	return res.diagnostics
		.filter((d) => d.pointer === ptr || d.pointer.startsWith(ptr + '/'))
		.map((d) => ({
			code: d.code,
			message: d.message,
			severity: d.severity,
			path: d.pointer.slice(ptr.length) || '/',
			questionId: d.code.startsWith('ref.') ? questionId(d.message) : null
		}));
}

export function parseExpression(text: unknown, survey: unknown = null, target: string | null = null, field: string | null = null): ParseOut {
	const res = parseExpr(text);
	if (!res.ok || !res.expr) {
		return {
			ok: false,
			ast: null,
			text: null,
			references: [],
			diagnostics: res.diagnostics.map((d) => ({ code: d.code, message: d.message, severity: 'error', start: d.start, end: d.end }))
		};
	}
	const ast = JSON.parse(JSON.stringify(res.expr)) as Record<string, unknown>;
	const diagnostics = survey !== null && target ? inPlace(ast as Json, survey as Json, target, field) : [];
	return { ok: true, ast, text: exprToText(res.expr), references: references(ast), diagnostics };
}

export function printExpression(ast: unknown): { text: string | null; diagnostics: ExprDiagnosticOut[] } {
	// Only text that parses again is printed: anything else was not an expression.
	try {
		const text = exprToText(ast as Expr);
		if (parseExpr(text).ok) return { text, diagnostics: [] };
	} catch (e) {
		if (e instanceof RangeError) {
			return { text: null, diagnostics: [{ code: 'too-deep', message: 'expression is nested too deeply', severity: 'error' }] };
		}
	}
	return { text: null, diagnostics: [{ code: 'invalid-ast', message: 'not an expression', severity: 'error' }] };
}

/** Every expression in a plan as text, by engine site (osp_app.preview.condition_texts). */
export function conditionTexts(plan: Record<string, unknown>): Record<string, string> {
	const out: Record<string, string> = {};
	const put = (site: string, ast: unknown) => {
		if (ast === null || ast === undefined) return;
		try {
			out[site] = exprToText(ast as Expr);
		} catch {
			// never crash on input
		}
	};
	const entries = (v: unknown) => (typeof v === 'object' && v !== null ? Object.entries(v as Record<string, Record<string, unknown>>) : []);
	for (const [id, item] of entries(plan.items)) {
		put(`items.${id}.showIf`, item?.showIf);
		put(`items.${id}.constraint`, item?.constraint);
	}
	for (const [id, page] of entries(plan.pages)) put(`pages.${id}.showIf`, page?.showIf);
	for (const [id, quota] of entries(plan.quotas)) put(`quotas.${id}.when`, quota?.when);
	for (const [id, v] of entries(plan.variables)) put(`variables.${id}.expr`, v?.expr);
	const walk = (nodes: unknown) => {
		if (!Array.isArray(nodes)) return;
		for (const n of nodes as Record<string, unknown>[]) {
			if (typeof n !== 'object' || n === null) continue;
			if (n.type === 'branch') {
				put(`flow.${String(n.id)}.if`, n.if);
				walk(n.then);
				walk(n.else);
			} else if (n.type === 'randomiser') walk(n.children);
		}
	};
	walk(plan.flow);
	return out;
}
