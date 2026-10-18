/**
 * Text ⇄ AST for the condition builder. `ExpressionService` is what the builder needs.
 *
 * `localExpressionService` answers in the browser (task CE5): `@osp/engine`'s `parseExpr` /
 * `exprToText` (the TS port of `osp_expr`, proved equal by parity vectors) and, for the
 * in-place check, `@osp/ops`'s `set_condition` with `@osp/spec`'s validator, exactly as
 * `POST /api/meta/expressions/parse` does it on the server (osp_api/routes/expressions.py)
 * but against the draft as edited here. `apiExpressionService` still backs it with the
 * server's endpoints (kept for other clients).
 */
import type { ApiClient, components } from '@osp/api-client';
import { exprToText, parseExpr, type Expr } from '@osp/engine';
import { buildIndex, CONDITION_FIELDS, exprAstProblem, run, type Json } from '@osp/ops';
import type { ConditionField, ExprDiagnostic, ExprNode } from './types';

export interface ParseRequest {
	text: string;
	surveyId?: string | null;
	target?: string | null;
	field?: ConditionField | null;
}

export interface ParseResult {
	ok: boolean;
	ast: ExprNode | null;
	text: string | null;
	diagnostics: ExprDiagnostic[];
}

export interface PrintResult {
	text: string | null;
	diagnostics: ExprDiagnostic[];
}

export interface ExpressionService {
	parse(req: ParseRequest): Promise<ParseResult>;
	print(ast: ExprNode): Promise<PrintResult>;
}

// -- in the browser ------------------------------------------------------------------------

const QUOTED_ID = /'([A-Za-z_][A-Za-z0-9_]*)'/;
const MAX_TEXT = 20_000;

function questionId(message: string): string | null {
	return QUOTED_ID.exec(message)?.[1] ?? null;
}

type Obj = Record<string, unknown>;

/** The pointer of `target`'s condition `field` (expressions.py `_field_pointer`). */
function fieldPointer(survey: Json, target: string, field: string | null | undefined): string | null {
	const loc = buildIndex(survey).get(target);
	if (!loc) return null;
	let obj: unknown = survey;
	for (const part of loc.path) obj = (obj as Obj)[part as never];
	let kind: string;
	if (loc.kind === 'question') kind = 'question';
	else if (loc.kind === 'quota') kind = 'quota';
	else kind = String((obj as Obj)[loc.kind === 'node' ? 'type' : 'kind']);
	const fields = Object.prototype.hasOwnProperty.call(CONDITION_FIELDS, kind) ? CONDITION_FIELDS[kind] : undefined;
	if (!fields?.length) return null;
	return `${loc.pointer}/${field || fields[0]}`;
}

/** Check `ast` as if `set_condition` had put it on `target` (expressions.py `_in_place`). */
function inPlace(ast: Json, survey: Json, target: string, field: ConditionField | null | undefined): ExprDiagnostic[] {
	const params: Obj = { target, condition: ast };
	if (field) params.field = field;
	const res = run('set_condition', survey, params);
	if (!res.ok) {
		return res.diagnostics.map((d) => ({ code: d.code, message: d.message, severity: 'error', questionId: questionId(d.message) }));
	}
	const ptr = fieldPointer(res.survey, target, field);
	if (ptr === null) return [];
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

function parseLocal(req: ParseRequest, survey: unknown): ParseResult {
	if ([...req.text].length > MAX_TEXT) {
		return { ok: false, ast: null, text: null, diagnostics: [{ code: 'too-long', message: `condition text is over ${MAX_TEXT} characters`, severity: 'error' }] };
	}
	const r = parseExpr(req.text);
	if (!r.ok || r.expr === null) {
		return {
			ok: false,
			ast: null,
			text: null,
			diagnostics: r.diagnostics.map((d) => ({ code: d.code, message: d.message, severity: 'error', start: d.start, end: d.end }))
		};
	}
	const diagnostics = survey && req.target ? inPlace(r.expr as unknown as Json, survey as Json, req.target, req.field) : [];
	return { ok: true, ast: r.expr as unknown as ExprNode, text: exprToText(r.expr), diagnostics };
}

function printLocal(ast: ExprNode): PrintResult {
	try {
		const problem = exprAstProblem(ast as unknown as Json);
		if (problem !== null) {
			return { text: null, diagnostics: [{ code: 'invalid-ast', message: `not an expression: ${problem}`, severity: 'error' }] };
		}
		return { text: exprToText(ast as unknown as Expr), diagnostics: [] };
	} catch {
		return { text: null, diagnostics: [{ code: 'too-deep', message: 'expression is nested too deeply', severity: 'error' }] };
	}
}

/**
 * Parse and print in the browser. `survey()` gives the draft to check a condition against
 * in place (the store's current survey, with edits not yet saved).
 */
export function localExpressionService(survey: () => unknown): ExpressionService {
	return {
		parse: async (req) => parseLocal(req, survey()),
		print: async (ast) => printLocal(ast)
	};
}

// -- over the API ---------------------------------------------------------------------------

type ApiParse = components['schemas']['ParseExpressionResponse'];
type ApiPrint = components['schemas']['PrintExpressionResponse'];

function unreachable(error: unknown): ExprDiagnostic[] {
	const message =
		typeof error === 'object' && error !== null && 'message' in error
			? String((error as { message: unknown }).message)
			: 'The server could not check this condition.';
	return [{ code: 'request', message, severity: 'error' }];
}

export function apiExpressionService(client: ApiClient): ExpressionService {
	return {
		async parse(req) {
			try {
				const { data, error } = await client.POST('/api/meta/expressions/parse', {
					body: {
						text: req.text,
						surveyId: req.surveyId ?? null,
						target: req.target ?? null,
						field: req.field ?? null
					}
				});
				if (!data) return { ok: false, ast: null, text: null, diagnostics: unreachable(error) };
				return fromParse(data);
			} catch (e) {
				return { ok: false, ast: null, text: null, diagnostics: unreachable(e) };
			}
		},
		async print(ast) {
			try {
				const { data, error } = await client.POST('/api/meta/expressions/print', { body: { ast } });
				if (!data) return { text: null, diagnostics: unreachable(error) };
				return fromPrint(data);
			} catch (e) {
				return { text: null, diagnostics: unreachable(e) };
			}
		}
	};
}

function fromParse(d: ApiParse): ParseResult {
	return {
		ok: d.ok,
		ast: (d.ast as ExprNode | null | undefined) ?? null,
		text: d.text ?? null,
		diagnostics: (d.diagnostics ?? []) as ExprDiagnostic[]
	};
}

function fromPrint(d: ApiPrint): PrintResult {
	return { text: d.text ?? null, diagnostics: (d.diagnostics ?? []) as ExprDiagnostic[] };
}
