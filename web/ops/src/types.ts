/** The types the registry, the transaction and the validator share. */

import type { Patch } from './patch.ts';
import type { Json, JsonObject } from './py.ts';

export type Severity = 'error' | 'warning' | 'info';

export interface Diagnostic {
	severity: Severity;
	code: string;
	message: string;
	pointer: string;
}

export interface Invocation {
	op: string;
	params: JsonObject;
}

export interface OpResult {
	ok: boolean;
	/** survey' when `ok`, else the unchanged input. */
	survey: Json;
	/** Undoes the op exactly (survey' -> survey). */
	inverse: Invocation | null;
	/** RFC 6902 from survey to survey'. */
	patch: Patch;
	diagnostics: Diagnostic[];
}

/** One expression-parser diagnostic (`osp_expr.parse`): code, message, span. */
export interface ExprDiagnostic {
	code: string;
	message: string;
	start: number | null;
	end: number | null;
}

export type ParsedExpression = { expr: Json } | { expr: null; diagnostics: ExprDiagnostic[] };

/**
 * What the ops need from the survey validator (`osp-spec`) and the expression parser
 * (`osp-expr`). Each is optional; see `NO_VALIDATOR` for what an absent one means.
 */
export interface Validator {
	/** `osp_spec.parse`: whether the document is structurally valid, and its diagnostics. */
	parse(doc: Json): { valid: boolean; diagnostics: Diagnostic[] };
	/** `osp_spec.validate` (absent: `parse(doc).diagnostics`). */
	validate?(doc: Json): Diagnostic[];
	/** `osp_spec.bank.check_fragment` (absent: only "exactly one of question, page, block"). */
	checkFragment?(fragment: Json): Diagnostic[];
	/** `osp_expr.parse` for condition text (absent: text conditions are refused). */
	parseExpression?(text: string): ParsedExpression;
}

/** No validator at all: every document is valid and has no diagnostics. */
export const NO_VALIDATOR: Validator = {
	parse: () => ({ valid: true, diagnostics: [] })
};

export interface OpsEnv {
	validator: Validator;
}

