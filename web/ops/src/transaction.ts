/**
 * Transactions (port of `osp_ops.transaction`): a list of ops applied all-or-nothing
 * against a revision. One transaction yields one inverse transaction (the ops' inverses in
 * reverse order), so undo is `applyTransaction(draft, result.inverse, ...)` and its own
 * inverse is the redo. A stale `baseRevision` is a conflict (HTTP 409 on the server).
 */

import type { Patch } from './patch.ts';
import { isInt, isObj, has, slice, str as pyStr, type Json } from './py.ts';
import { DEFAULT_ENV, diag, execute, parseWith, type Diagnostic, type Invocation, type OpsEnv, type Parsed } from './registry.ts';

export const MAX_OPS = 1_000;

export interface Draft {
	survey: Json;
	revision: number;
}

export interface TransactionResult {
	/** ok (applied), rejected (nothing applied; `failedIndex` says which op) or conflict. */
	status: 'ok' | 'rejected' | 'conflict';
	draft: Draft;
	inverse: Invocation[];
	patch: Patch;
	diagnostics: Diagnostic[];
	failedIndex: number | null;
}

/** Apply `ops` in order to `draft`, all or nothing. Never throws. */
export function applyTransaction(draft: Draft, ops: unknown, baseRevision: unknown, env: OpsEnv = DEFAULT_ENV): TransactionResult {
	try {
		return applyUnguarded(draft, ops, baseRevision, env);
	} catch (e) {
		const name = e instanceof Error ? e.constructor.name : 'Exception';
		return result('rejected', draft, [diag('op.internal', `transaction failed: ${name}`)], null);
	}
}

function result(status: TransactionResult['status'], draft: Draft, diagnostics: Diagnostic[], failedIndex: number | null): TransactionResult {
	return { status, draft, inverse: [], patch: [], diagnostics, failedIndex };
}

function applyUnguarded(draft: Draft, ops: unknown, baseRevision: unknown, env: OpsEnv): TransactionResult {
	if (!isInt(baseRevision) || baseRevision !== draft.revision) {
		const shown = slice(pyStr(baseRevision as Json), 0, 20);
		return result(
			'conflict',
			draft,
			[diag('op.conflict', `base revision ${shown} is not the current revision ${draft.revision}; refetch and replay`)],
			null
		);
	}
	if (!Array.isArray(ops) || ops.length > MAX_OPS) {
		return result('rejected', draft, [diag('op.params', `ops must be a list of <= ${MAX_OPS}`)], null);
	}
	let survey = draft.survey;
	let parsed: Parsed = parseWith(env, survey);
	const inverses: Invocation[] = [];
	const patch: Patch = [];
	let diagnostics = parsed.diagnostics;
	for (let i = 0; i < ops.length; i++) {
		const inv: unknown = ops[i];
		if (!isObj(inv)) return result('rejected', draft, [diag('op.params', 'each op is an object {op, params}')], i);
		const res = execute(has(inv, 'op') ? inv.op : null, survey, has(inv, 'params') ? inv.params : {}, parsed, env);
		if (!res.ok) return result('rejected', draft, res.diagnostics, i);
		inverses.push(res.inverse!);
		patch.push(...res.patch);
		survey = res.survey;
		diagnostics = res.diagnostics;
		parsed = { valid: true, diagnostics }; // the op just validated its output
	}
	return {
		status: 'ok',
		draft: { survey, revision: patch.length ? draft.revision + 1 : draft.revision },
		inverse: inverses.reverse(),
		patch,
		diagnostics,
		failedIndex: null
	};
}
