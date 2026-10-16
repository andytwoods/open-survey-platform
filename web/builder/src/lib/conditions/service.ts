/**
 * Text ⇄ AST goes through the server (`osp_expr`), never a second parser in the browser.
 * `ExpressionService` is what the condition builder needs; `apiExpressionService` backs it
 * with the generated API client.
 */
import type { ApiClient, components } from '@osp/api-client';
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
