/**
 * The op registry (port of `osp_ops.registry`): every survey edit is a named op with a
 * params schema and `run(ctx, params) -> inverse`. The contract, enforced here once:
 *
 * - Ops are pure: the input survey is deep-copied and never mutated.
 * - The input must be structurally valid and so must the output (`Validator.parse`);
 *   semantic problems come back as `diagnostics` (the validator's output for survey').
 * - An op may not add a duplicate id, a dangling reference (deletes without `force`) or
 *   text the model refuses (`TEXT_CODES`), judged by the validator's errors before/after.
 * - Nothing throws: bad params, a bad survey or a bug become `op.*` diagnostics.
 *
 * The survey validator (`osp_spec.parse` / `validate`) is injected (`OpsEnv.validator`):
 * the TypeScript validator is a separate task (CE4). Without one every document counts as
 * structurally valid with no diagnostics, so the validator-backed guards do nothing.
 */

import * as jp from './patch.ts';
import { attrs, validate as pydValidate, type ModelSchema, type PydError } from './pyd.ts';
import { isObj, has, reprStr, slice, str as pyStr, deepCopy, type Json, type JsonObject } from './py.ts';
import type { Loc as DocLoc } from './loc.ts';

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
	patch: jp.Patch;
	diagnostics: Diagnostic[];
}

/** One expression-parser diagnostic (`osp_expr.parse`): code, message, span. */
export interface ExprDiagnostic {
	code: string;
	message: string;
	start: number;
	end: number;
}

export type ParsedExpression = { expr: Json } | { expr: null; diagnostics: ExprDiagnostic[] };

/**
 * What the ops need from the survey validator (`osp-spec`) and the expression parser
 * (`osp-expr`). Each is optional; see `NO_VALIDATOR` for what an absent one means.
 */
export interface Validator {
	/** `osp_spec.parse`: whether the document is structurally valid, and its diagnostics. */
	parse(doc: Json): { valid: boolean; diagnostics: Diagnostic[] };
	/** `osp_spec.validate` (default: `parse(doc).diagnostics`). */
	validate?(doc: Json): Diagnostic[];
	/** `osp_spec.bank.check_fragment` (default: only "exactly one of question, page, block"). */
	checkFragment?(fragment: Json): Diagnostic[];
	/** `osp_expr.parse` for condition text (default: text conditions are refused). */
	parseExpression?(text: string): ParsedExpression;
}

/** Every document is valid and has no diagnostics. */
export const NO_VALIDATOR: Validator = {
	parse: () => ({ valid: true, diagnostics: [] })
};

export interface OpsEnv {
	validator: Validator;
}

export const DEFAULT_ENV: OpsEnv = { validator: NO_VALIDATOR };

// Codes osp-ops reports itself (all errors). Validator codes come from osp-spec.
export const OP_CODES: Record<string, string> = {
	'op.unknown': 'no op with this id',
	'op.params': "params do not match the op's params schema",
	'op.invalid_survey': 'the input survey is not structurally valid',
	'op.not_found': 'the target id does not exist (or is the wrong kind of object)',
	'op.not_allowed': 'the edit is not allowed in this state',
	'op.not_applicable': "the target's type has no such property or condition",
	'op.duplicate_id': 'the edit would create a duplicate id',
	'op.dangling_ref': 'the delete would leave references to deleted objects',
	'op.cascade_blocked': 'cascade cannot repair a required expression',
	'op.type_conflict': 'the type change would break conditions or piping that use the answer',
	'op.invalid_result': 'the edit would make the survey structurally invalid',
	'op.invalid_text': 'the edit would store text the model refuses (link, length, level)',
	'op.expr_syntax': 'condition text does not parse',
	'op.patch': 'the JSON Patch is malformed or does not apply',
	'op.conflict': 'baseRevision is stale (HTTP 409)',
	'op.internal': 'an op failed unexpectedly (a bug; never expected)'
};

const DUPLICATE_CODES = new Set(['id.duplicate']);
const DANGLING_CODES = new Set([
	'ref.unknown',
	'ref.unknown_block',
	'ref.unknown_choice_list',
	'ref.unknown_quota',
	'ref.unknown_variable'
]);
export const TEXT_CODES = new Set(['text.too_long', 'text.too_many_blocks', 'text.block_not_allowed', 'link.scheme', 'link.empty']);

export function diag(code: string, message: string, pointer = ''): Diagnostic {
	return { severity: 'error', code, message, pointer };
}

/** Thrown inside an op's `run`; the registry turns it into diagnostics. */
export class OpError extends Error {
	readonly diagnostics: Diagnostic[];
	constructor(code: string, message: string, pointer = '', ...more: Diagnostic[]) {
		super(message);
		this.diagnostics = [diag(code, message, pointer), ...more];
	}
}

/** Returned by a `run` whose inverse is the reverse patch (cascading deletes and the like). */
export const REVERSE_PATCH: Invocation = Object.freeze({ op: 'apply_patch', params: { patch: [] } }) as Invocation;

/** What an op's `run` sees. `doc` is a private deep copy it may mutate (or replace). */
export class Ctx {
	checkDangling = false;
	private _index: Map<string, DocLoc> | null = null;
	constructor(
		public doc: Json,
		readonly before: Json,
		readonly env: OpsEnv,
		private readonly buildIndex: (doc: Json) => Map<string, DocLoc>
	) {}

	get d(): JsonObject {
		return this.doc as JsonObject;
	}

	index(): Map<string, DocLoc> {
		if (this._index === null) this._index = this.buildIndex(this.doc);
		return this._index;
	}

	touch(): void {
		this._index = null;
	}
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type RunFn = (ctx: Ctx, p: any) => Invocation;

export interface OpSpec {
	id: string;
	label: string;
	area: string;
	params: ModelSchema;
	run: RunFn;
	wholeDocument: boolean;
}

export const REGISTRY = new Map<string, OpSpec>();

export function op(
	id: string,
	params: ModelSchema,
	o: { label: string; area: string; wholeDocument?: boolean },
	run: RunFn
): void {
	if (REGISTRY.has(id)) throw new Error(`op '${id}' registered twice`);
	REGISTRY.set(id, { id, label: o.label, area: o.area, params, run, wholeDocument: o.wholeDocument ?? false });
}

// --- running ops -------------------------------------------------------------------------------

let indexBuilder: (doc: Json) => Map<string, DocLoc> = () => new Map();

/** doc.ts registers its `buildIndex` here (doc.ts imports the registry, not the reverse). */
export function setIndexBuilder(fn: (doc: Json) => Map<string, DocLoc>): void {
	indexBuilder = fn;
}

export type Parsed = { valid: boolean; diagnostics: Diagnostic[] };

/** Run one op. Never throws. */
export function run(opId: unknown, survey: Json, params: unknown = null, env: OpsEnv = DEFAULT_ENV): OpResult {
	return execute(opId, survey, params, null, env);
}

/** True if the op would succeed, else the reason (first diagnostic's message). */
export function enabled(opId: unknown, survey: Json, params: unknown = null, env: OpsEnv = DEFAULT_ENV): true | string {
	const res = run(opId, survey, params, env);
	if (res.ok) return true;
	return res.diagnostics[0]?.message ?? 'not enabled';
}

/** Run an `Invocation` (`{op, params}`). */
export function invoke(inv: unknown, survey: Json, env: OpsEnv = DEFAULT_ENV): OpResult {
	if (isObj(inv)) return run(has(inv, 'op') ? inv.op : null, survey, has(inv, 'params') ? inv.params : {}, env);
	return fail(survey, [diag('op.params', 'an invocation is an object {op, params}')]);
}

function fail(survey: Json, diagnostics: Diagnostic[]): OpResult {
	return { ok: false, survey, inverse: null, patch: [], diagnostics };
}

export function parseWith(env: OpsEnv, doc: Json): Parsed {
	const r = env.validator.parse(doc);
	return { valid: r.valid, diagnostics: r.diagnostics };
}

/** The Python exception type name for an unexpected error (`op.internal` messages). */
export function pyTypeName(e: unknown): string {
	if (e instanceof jp.PyException) return e.pyType;
	if (e instanceof jp.PatchError) return 'PatchError';
	return e instanceof Error ? e.constructor.name : 'Exception';
}

export function execute(opId: unknown, survey: Json, params: unknown, parsed: Parsed | null, env: OpsEnv): OpResult {
	try {
		return executeUnguarded(opId, survey, params, parsed, env);
	} catch (e) {
		const msg = `op ${reprStr(slice(pyStr(opId as Json), 0, 60))} failed: ${pyTypeName(e)}`;
		return fail(survey, [diag('op.internal', msg)]);
	}
}

function executeUnguarded(opId: unknown, survey: Json, params: unknown, parsed: Parsed | null, env: OpsEnv): OpResult {
	const spec = typeof opId === 'string' ? REGISTRY.get(opId) : undefined;
	if (spec === undefined) {
		return fail(survey, [diag('op.unknown', `no op with id ${reprStr(slice(pyStr(opId as Json), 0, 60))}`)]);
	}
	if (params === null || params === undefined) params = {};
	if (!isObj(params)) return fail(survey, [diag('op.params', 'params must be an object')]);
	const v = pydValidate(spec.params, params);
	if (!v.ok) return fail(survey, paramDiagnostics(v.errs));
	const p = attrs(v.v);

	const beforeParsed = parsed ?? parseWith(env, survey);
	if (!beforeParsed.valid && !spec.wholeDocument) {
		return fail(survey, [diag('op.invalid_survey', 'the survey is not structurally valid'), ...beforeParsed.diagnostics]);
	}

	const ctx = new Ctx(deepCopy(survey), survey, env, indexBuilder);
	let inverse: Invocation;
	try {
		inverse = spec.run(ctx, p);
	} catch (e) {
		if (e instanceof OpError) return fail(survey, e.diagnostics);
		throw e;
	}

	const after = parseWith(env, ctx.doc);
	if (!after.valid) {
		return fail(survey, [diag('op.invalid_result', 'the edit would make the survey invalid'), ...after.diagnostics]);
	}

	const guarded = new Set(TEXT_CODES);
	if (!spec.wholeDocument) {
		for (const c of DUPLICATE_CODES) guarded.add(c);
		if (ctx.checkDangling) for (const c of DANGLING_CODES) guarded.add(c);
	}
	const added = newErrors(beforeParsed.diagnostics, after.diagnostics, guarded);
	if (added.length) {
		const first = added[0]!.code;
		const code = DUPLICATE_CODES.has(first) ? 'op.duplicate_id' : TEXT_CODES.has(first) ? 'op.invalid_text' : 'op.dangling_ref';
		return fail(survey, [diag(code, `the edit would add: ${added[0]!.message}`), ...added]);
	}

	if (inverse === REVERSE_PATCH) inverse = { op: 'apply_patch', params: { patch: jp.diff(ctx.doc, survey) } };
	else inverse = { op: inverse.op, params: deepCopy(inverse.params) };
	return { ok: true, survey: ctx.doc, inverse, patch: jp.diff(survey, ctx.doc), diagnostics: after.diagnostics };
}

/** Errors in `after` with a code in `codes` that `before` did not have (multiset on code+message). */
export function newErrors(before: Diagnostic[], after: Diagnostic[], codes: Set<string>): Diagnostic[] {
	const seen = new Map<string, number>();
	for (const d of before) {
		if (!codes.has(d.code)) continue;
		const k = JSON.stringify([d.code, d.message]);
		seen.set(k, (seen.get(k) ?? 0) + 1);
	}
	const out: Diagnostic[] = [];
	for (const d of after) {
		if (!codes.has(d.code)) continue;
		const k = JSON.stringify([d.code, d.message]);
		const n = seen.get(k) ?? 0;
		if (n > 0) seen.set(k, n - 1);
		else out.push(d);
	}
	return out;
}

function paramDiagnostics(errs: PydError[]): Diagnostic[] {
	const out = errs
		.slice(0, 20)
		.map((e) => diag('op.params', slice(e.msg, 0, 300), jp.toPointer(e.loc)));
	return out.length ? out : [diag('op.params', 'invalid params')];
}
